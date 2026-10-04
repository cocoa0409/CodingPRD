# Brand Line Coverage API — Product Requirements Document

## 1. Introduction

A single iconic brand lives or dies by two disciplines that pull in opposite directions. On one side, the business wants line extensions that leverage the brand without diluting the core product's identity, packaging proliferation across can sizes and delivery systems, broader distributor and retailer coverage across the hardware, automotive, industrial and mass channels, and international expansion through distributors operating under local formulation and registration regimes. On the other side, the core formulation is a trade secret manufactured under contract and confidentiality, the brand must be defended against genericization and counterfeit product, and pricing and promotion for a low-price, high-frequency item must stay disciplined even as pack sizes and channels differentiate.

This document specifies the Brand Line Coverage API, the system of record for those two disciplines. It governs the full lifecycle of brands and their product lines — formulation, sealing and compartmentalized disclosure of trade-secret recipes to contract manufacturers, market registration, distributor onboarding and coverage assignment, channel price lists, promotions and their funding, sell-through attainment, counterfeit enforcement, and the consumer-submitted use cases that power the brand's marketing. Every rule below is contractual: field names, state names, error identifiers, thresholds, rounding behaviour and the logical clock are all part of the specification.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. All resources described in §3 are served under the `/brand-ops` namespace; the only exception is the platform's logical-clock endpoint, which is mounted outside that prefix and is described in §2.4.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. A request missing either header, presenting an empty value, or naming an undeclared role is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). When the headers are valid but the caller's role is not among the roles authorized for the target endpoint, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403).

The system recognizes eleven roles. Every role may call every read (GET) endpoint; the write operations below are exclusive to the named role unless stated otherwise.

- `PlatformAdmin` — the platform operator. Its only exclusive operation is driving the logical clock; it otherwise reads everything. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- `BrandManager` — owns brand creation and the product-line lifecycle: product-line creation, brand reviews, launches and discontinuations. `X-User-ID` is an opaque operator identifier for this role.
- `TradeSecretOfficer` — owns formulations (create, seal), contract manufacturers (onboard, qualify) and the requesting, granting and activation side of confidentiality grants. `X-User-ID` is opaque, but it is recorded: the manufacturer record captures it as `sponsoring_officer_id`, and each grant action captures it as `granted_by_user_id`.
- `ComplianceAuditor` — owns revocation of confidentiality grants, brand lockdown and its lifting, and counterfeit-case enforcement (report, take-action, close). `X-User-ID` is opaque; segregation-of-duties rules in §3 compare it against previously recorded user ids.
- `ChannelManager` — owns the distributor lifecycle (create, approve, suspend, reinstate, terminate), coverage assignments (propose, activate, suspend, resume, withdraw), records promotion redemptions, and may read the rebate preview. `X-User-ID` is opaque.
- `PricingAnalyst` — owns channel price lists and creates and submits promotions; a `PricingAnalyst` may never approve a promotion. This role may also read the rebate preview. `X-User-ID` is opaque but is recorded on each promotion as `created_by_user_id`.
- `MarketingManager` — approves and resumes promotions (segregated from their creator) and moderates consumer use cases (review, publish, retract). `X-User-ID` is opaque and is recorded at approve time as `approved_by_user_id`.
- `RegulatoryAffairs` — owns markets (create, close) and market registrations (create, submit, approve, reject, revise, renew, revoke). `X-User-ID` is opaque.
- `SupplyPlanner` — owns pack formats and their tooling, production and retirement. `X-User-ID` is opaque.
- `DistributorContact` — an external distributor user. When `X-User-Role` is `DistributorContact`, `X-User-ID` is the `id` of the acting `Distributor`; ownership checks on any resource that references a `Distributor` compare the resource's foreign-key field to `X-User-ID`. Its only write operation is filing sell-through reports, and only against that distributor's own assignments; a mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).
- `Consumer` — an external consumer. When `X-User-Role` is `Consumer`, `X-User-ID` is the consumer handle, an opaque identifier not tied to any persisted entity; it is significant only in that a use case's `submitter_ref` must equal it, failing which the submission is rejected with `ERR_SUBMITTER_MISMATCH` (HTTP 403).

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, taken from the server's logical clock (§2.4), never from the host clock.
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

Endpoints that return lists of resources are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items to skip and defaults to 0. A non-integer `limit` or `offset`, a `limit` outside 1 to 100, or a negative `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order, with ties on `created_at` broken toward the resource created earliest.

List responses carry the pagination fields `limit`, `offset`, `total_count` and `has_more` in the `meta` object of the response envelope.

### 2.4. The Logical Clock and the Time Sweep

The server runs on a logical clock, never on wall-clock time. Before any operator intervention the logical time is exactly `2026-09-01T00:00:00Z`; the server must not fall back to the host clock under any circumstance. A `PlatformAdmin` may advance the clock through an admin-only test-driving capability — mounted outside the `/brand-ops` namespace — that accepts a target instant in the `to_iso8601` field (ISO 8601 UTC) and echoes the resulting time back as `current_utc`. The target must be strictly after the current logical time; any attempt to hold or regress the clock is rejected with `ERR_CLOCK_REGRESSION` (HTTP 400).

Setting the clock runs a **time sweep** that reconciles every time-driven state machine before the response is returned:

- Market registrations move `ACTIVE` → `RENEWAL_DUE` when the current time reaches the instant 90 days before their `expires_on` (the boundary instant itself opens the window), and move to `EXPIRED` when the current time reaches `expires_on` — from `RENEWAL_DUE`, or directly from `ACTIVE` when a single clock jump carries the time past `expires_on` without resting in the renewal window.
- Confidentiality grants in `GRANTED` or `ACTIVE` move to `EXPIRED` when the current time reaches their `expires_on`.
- Channel price lists move `SCHEDULED` → `EFFECTIVE` when the current time enters their window, and on to `EXPIRED` when it reaches `effective_to`; a `SCHEDULED` list whose window is jumped past entirely goes straight to `EXPIRED`.
- Promotions move `APPROVED` → `LIVE` when the current date reaches `starts_on` while not past `ends_on`, and `APPROVED` or `LIVE` → `ENDED` once the current date passes `ends_on`. The sweep never ends a `SUSPENDED` promotion.
- Coverage assignments in `ACTIVE` or `SUSPENDED` move to `CLOSED` when the current date passes their `ends_on`.
- Every brand's `protection_posture` is recomputed as part of the sweep.

### 2.5. Common Resource Properties

Every primary resource carries a standard set of system-managed fields:

- `id` (string): a server-minted UUID with no type prefix, assigned at creation.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): starts at 1 at creation and increments by exactly one on every mutation, including system-driven cascades and sweeps. A recomputation or sweep pass that leaves every field of a resource unchanged is not a mutation: it neither increments `version` nor refreshes `updated_at`.

The sole exception is the sell-through report. A `SellThroughReport` is immutable once filed and carries only `id` and `created_at`; both `updated_at` and `version` are absent from it.

### 2.6. Validation Order: First Failure Wins

Every request is evaluated against an ordered validation pipeline, and the first failing check determines the error returned — later checks are never reached once an earlier one fails. The order is:

1. **User context.** `X-User-ID` and `X-User-Role` must be present and non-empty, and the role must be a declared role name (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`, 400).
2. **Role authorization.** The caller's role must appear in the endpoint's authorized roles (`ERR_FORBIDDEN_FOR_ROLE`, 403).
3. **Path existence.** Every identifier in the URL path must resolve to an existing resource, checked left to right (`ERR_NOT_FOUND`, 404).
4. **Request shape.** Required body fields must be present; enum, integer, date and datetime values must be well-formed and in range — `severity` within 1 to 5, `discount_pct` greater than 0 and at most 90.00 with no more than two decimal places, `component_codes` a non-empty array of non-empty strings, constrained arrays non-empty. Fields that are undeclared, computed or system-sourced and appear in a request body are ignored, never stored (`ERR_INVALID_REQUEST`, 400). (The 12-entry ceiling on `component_codes` is not a shape check; it is the capacity rule of category 12 below and fails as `ERR_COMPONENT_LIMIT_EXCEEDED`.)
5. **Body references.** Identifiers referenced inside the request body — `formulation_id`, `market_id`, `home_market_id`, `product_line_id`, `pack_format_id`, `coverage_assignment_id`, `manufacturer_id`, `master_formulation_id` — must exist (`ERR_INVALID_REFERENCE`, 422).
6. **Ownership and caller identity.** A `DistributorContact`'s `X-User-ID` must equal the path distributor id, and a `Consumer`'s `submitter_ref` must equal the caller's `X-User-ID` (`ERR_NOT_RESOURCE_OWNER` or `ERR_SUBMITTER_MISMATCH`, 403).
7. **Optimistic concurrency.** Where an endpoint takes an expected parent version (§2.7), it must equal the parent entity's current `version` (`ERR_STALE_VERSION`, 412).
8. **State-machine admissibility.** The target resource's own state machine must admit the requested transition (`ERR_INVALID_STATE_TRANSITION`, 409; with the dedicated wrong-from-state errors `ERR_RENEWAL_WINDOW_NOT_OPEN`, `ERR_REGISTRATION_EXPIRED`, `ERR_DISTRIBUTOR_NOT_APPROVED` and `ERR_PROMO_WINDOW_CLOSED` where §3 assigns them).
9. **Brand-protection and trade-secret gates.** Lockdown, critical posture, manufacturer qualification, the compartmentalization scope cap, segregation of duties, the VOC regime, the genericization publish gate and the recent-breach requalification block (`ERR_BRAND_IN_LOCKDOWN`, `ERR_POSTURE_CRITICAL`, `ERR_MANUFACTURER_NOT_QUALIFIED`, `ERR_COMPARTMENT_SCOPE_EXCEEDED`, `ERR_SEGREGATION_OF_DUTIES`, `ERR_AUDITOR_CONFLICT`, `ERR_VOC_REGIME_MISMATCH`, `ERR_GENERICIZATION_RISK`, `ERR_RECENT_BREACH`).
10. **Temporal arithmetic.** Windows must start before they end, expiries must lie in the future at creation, activations must fall inside the coverage window, grants must be unexpired at grant and activate time, exclusive windows must not overlap, report periods must be completed, and the clock must strictly advance (`ERR_WINDOW_INVALID`, `ERR_EXCLUSIVE_OVERLAP`, `ERR_PERIOD_NOT_COMPLETED`, `ERR_CLOCK_REGRESSION`, `ERR_GRANT_EXPIRED`).
11. **Referential compatibility.** Referenced entities must be in a compatible state — formulations sealed or compartmentalized for grants and registrations, a compartmentalized formulation for production entry, an active registration for coverage activation, price lists present where required, a producible pack format for launch, a launched line for use-case creation, an open market for distributor approval and registration creation (`ERR_FORMULATION_NOT_SEALED`, `ERR_FORMULATION_NOT_COMPARTMENTALIZED`, `ERR_FORMULATION_LINE_MISMATCH`, `ERR_PACK_LINE_MISMATCH`, `ERR_REGISTRATION_NOT_ACTIVE`, `ERR_NO_PRICE_LIST`, `ERR_NO_PRODUCIBLE_PACK_FORMAT`, `ERR_NO_EFFECTIVE_PRICE`, `ERR_LINE_STAGE_TOO_EARLY`, `ERR_LINE_NOT_LAUNCHED`, `ERR_MARKET_NOT_OPEN`, `ERR_PRICE_LISTS_OUTSTANDING`, `ERR_MARKET_IN_USE`).
12. **Uniqueness, subset and capacity constraints.** Line codes unique per brand among live lines, a single live core line, unique market country codes, channel membership, component-scope subset, the minimum component count at sealing, the coverage-cell capacity of three, one report per assignment per month, one non-terminal registration per market and line, and advertised-price floors (`ERR_DUPLICATE_LINE_CODE`, `ERR_CORE_LINE_EXISTS`, `ERR_CORE_LINE_IMMUTABLE`, `ERR_MARKET_CODE_EXISTS`, `ERR_CHANNEL_NOT_SERVED`, `ERR_CHANNEL_NOT_ALLOWED`, `ERR_CHANNEL_OUTSIDE_LINE_SCOPE`, `ERR_CELL_CAPACITY_EXCEEDED`, `ERR_DUPLICATE_REPORT`, `ERR_REGISTRATION_EXISTS`, `ERR_SCOPE_NOT_SUBSET`, `ERR_INSUFFICIENT_COMPONENTS`, `ERR_COMPONENT_LIMIT_EXCEEDED`, `ERR_MAP_ABOVE_LIST`).
13. **Fiscal gates, evaluated last.** The equity budget, the core-identity floor, the promotion depth cap, price-list presence and the advertised-price floor at approval, promotion frequency then gap, and the redemption budget (`ERR_EQUITY_BUDGET_EXCEEDED`, `ERR_CORE_IDENTITY_DILUTION`, `ERR_PROMO_DEPTH_EXCEEDS_CAP`, `ERR_BELOW_MAP_PRICE`, `ERR_PROMO_TOO_FREQUENT`, `ERR_PROMO_GAP_VIOLATION`, `ERR_PROMO_BUDGET_EXCEEDED`).

### 2.7. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control on a parent entity's `version`; no other endpoint takes a version field.

- Creating a coverage assignment requires the request to carry `expected_distributor_version`, holding the caller's last observed `version` of the parent distributor. A missing or malformed `expected_distributor_version` is a request-shape failure (`ERR_INVALID_REQUEST`, HTTP 400); a well-formed but stale value — the distributor's version has advanced since, for example because another writer just created an assignment that superseded a pending proposal on the same cell — is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the caller from acting on a distributor record it has not observed.
- Creating a channel price list requires `expected_pack_format_version`, holding the caller's last observed `version` of the parent pack format, under the same split: a missing or malformed field fails as `ERR_INVALID_REQUEST` (HTTP 400), and a mismatch with the pack format's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412).

Both creates themselves mutate the parent's bookkeeping: a successful coverage-assignment creation increments the distributor's `version` by one, and a successful price-list creation increments the pack format's `version` by one.

### 2.8. Numeric Precision, Rounding and Units

Brand-equity, dilution, genericization and attainment figures are expressed in integer **basis points** (ten-thousandths of a whole: 10000 basis points is the full brand). Monetary values are integer **cents**. Where a division produces a fraction, the rule is fixed per calculation and never varies: promotion funding and case pricing round **half up to whole cents**, attainment ratios round **half up to integer basis points**, the discontinued-line dilution refund applies a mathematical **floor** (halving discards the remainder), and each coverage assignment's three-month quota is floored **per assignment before summing**. Percentages such as `discount_pct` are numbers with at most two decimal places. Datetime comparisons operate at second precision; calendar dates use the `YYYY-MM-DD` form. Every datetime value emitted in a response — `created_at`, `updated_at`, `sealed_at`, `launched_at`, `revoked_at`, `suspended_at`, `submitted_at`, `approved_at`, `expires_on`, `effective_from`, `effective_to` and the envelope's `api_request_timestamp` — is canonicalized to ISO 8601 UTC with exactly three fractional digits (for example `2026-09-01T00:00:00.000Z`), however the value was spelled on input. No calculation anywhere in the API uses floating-point approximation, and no result is ever described or stored as approximate.

### 2.9. Calendar Windows and Overlap Semantics

Two window conventions coexist and must not be confused. Coverage assignments and promotions run on **calendar dates** (`starts_on`, `ends_on`) interpreted as closed intervals: both endpoints are included, so two exclusive assignments whose date ranges merely touch on a single day already overlap. Channel price lists instead run on **datetimes** interpreted as half-open intervals — a list governs from `effective_from` up to but not including `effective_to` — so two lists on the same pack and channel may touch (one's `effective_from` equal to the other's `effective_to`) but may never overlap in the interior. Registration renewal windows open exactly 90 days before expiry, and the boundary instant itself counts: the moment the current time equals `expires_on` minus 90 days, the registration is due for renewal.

### 2.10. Nested Resource Resolution

Several creation endpoints nest the new resource under a parent in the URL — a product line under a brand, a formulation or pack format or use case under a product line, a coverage assignment or sell-through report under a distributor, a price list under a pack format, a counterfeit case under a brand. For every such request the server validates path identifiers strictly left to right and rejects with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve, before any body-level, state-level or business-level check is attempted.

## 3. Business Logic & Workflows

### 3.1. Brand Stewardship, Equity Budget and Protective Lockdown

Everything begins with the **Brand**. A `BrandManager` registers one by supplying its display `name`, the `legal_entity_name` of the owning company, and optionally an `equity_budget_bps` — the annual brand-equity dilution budget in basis points, which must be positive and defaults to 10000 when omitted. A new brand starts in `OPERATING` status with `protection_posture` `NORMAL`, `dilution_consumed_bps` of 0, `core_identity_share_bps` of 10000, and `genericization_risk_bps` of 0, and with `lockdown_reason` unset. Any role may read a brand; brands may be listed and individual brands retrieved, and the computed fields are always part of the representation.

A `ComplianceAuditor` can place an `OPERATING` brand into `PROTECTIVE_LOCKDOWN` at any time, supplying a `reason` of `CONFIDENTIALITY_BREACH`, `COUNTERFEIT_SURGE` or `MANUAL`, which is recorded in `lockdown_reason`; the transition is admitted only from `OPERATING`, so a brand already in `PROTECTIVE_LOCKDOWN` refuses a repeated lockdown with `ERR_INVALID_STATE_TRANSITION` (HTTP 409). While a brand is locked down, product-line launches, registration submissions, the activation of exclusive coverage and the resumption of suspended promotions are all refused with `ERR_BRAND_IN_LOCKDOWN` (HTTP 409). Lifting the lockdown — admitted only from `PROTECTIVE_LOCKDOWN`, any other status drawing `ERR_INVALID_STATE_TRANSITION` (HTTP 409) — returns the brand to `OPERATING` and clears `lockdown_reason` to null, but the lift is refused with `ERR_LOCKDOWN_CONDITIONS_UNMET` (HTTP 409) for as long as either of two conditions holds: any counterfeit case of the brand is still open (in `REPORTED` or `ACTION_TAKEN`) with `severity` equal to 5, or any confidentiality grant touching a formulation of one of the brand's lines was revoked for cause within the trailing 90 days.

The brand's `protection_posture` is a derived thermometer recomputed whenever a counterfeit case is created, acted upon or closed, whenever a grant is revoked for cause (including cascade revocations), and at every clock sweep. The recomputation considers the brand's **open cases** — counterfeit cases in `REPORTED` or `ACTION_TAKEN` — and its **recent breaches** — grants on formulations of the brand's lines whose `revoked_for_cause` flag is true and whose `revoked_at` falls within the trailing 180 days. The posture is `CRITICAL` when at least two such breaches exist, or any single open case has `severity` 5, or the open-case severities sum to at least 10. Failing that, it is `ELEVATED` when exactly one such breach exists or the severity sum reaches at least 6. Otherwise the posture is `NORMAL`. These are integer thresholds with no rounding. Posture is not decorative: it caps promotion depth (§3.8), blocks launches and registration submissions outright while `CRITICAL`, and flips every `LIVE` promotion of the brand to `SUSPENDED` whenever a recomputation yields `CRITICAL` — including a recomputation that leaves an already-`CRITICAL` posture unchanged.

Two further computed fields track the brand's equity. `dilution_consumed_bps` accumulates the frozen dilution cost of every line of the brand currently in `PILOT` or `LAUNCHED`, plus half — rounded down — of the frozen cost of every `DISCONTINUED` line that had reached `PILOT` before discontinuation; a line discontinued while still in `FORMULATION` never froze a cost and contributes nothing. `core_identity_share_bps` is whatever remains of the 10000-point whole after consumption, floored at zero: it is the greater of zero and 10000 minus `dilution_consumed_bps`. The genericization measure `genericization_risk_bps` is described with the use-case workflow in §3.9.

### 3.2. Product-Line Development, Brand Review and the Dilution Ledger

A **ProductLine** is created under a brand by a `BrandManager`, carrying a machine `line_code`, a human `name`, an optional `is_core` flag (default false) and a non-empty `target_channels` array drawn from `HARDWARE`, `AUTOMOTIVE`, `INDUSTRIAL` and `MASS`. The `line_code` must be unique within the brand among lines that are not `DISCONTINUED` — a clash is rejected with `ERR_DUPLICATE_LINE_CODE` (HTTP 409) — and at most one non-`DISCONTINUED` line per brand may be marked `is_core`; a second core line is rejected with `ERR_CORE_LINE_EXISTS` (HTTP 409). Lines can be listed with optional `brand_id` and `status` filters, and retrieved individually. Every line begins in `FORMULATION` with `brand_review_attempts` at 0 and `launched_at` unset.

From `FORMULATION` the line passes through **brand review**, a `BrandManager` decision supplied as `decision`. A `REJECT` decision while `brand_review_attempts` is below 2 keeps the line in `FORMULATION` for rework and increments `brand_review_attempts` by one. The third rejection is fatal: when the count already stands at 2, the rejection moves the line to `DISCONTINUED`, sets `brand_review_attempts` to 3, and recomputes the brand's `dilution_consumed_bps` and `core_identity_share_bps`. An `APPROVE` decision moves the line `FORMULATION` → `PILOT`, but only after three gates pass in order. First, at least one formulation of the line must be `SEALED` or `COMPARTMENTALIZED`, failing `ERR_FORMULATION_NOT_SEALED` (HTTP 409). Then the two fiscal gates fire, in this order: the brand's `dilution_consumed_bps` plus the candidate line's live dilution cost must not exceed `equity_budget_bps` (`ERR_EQUITY_BUDGET_EXCEEDED`, HTTP 422), and the brand's `core_identity_share_bps` minus that same candidate cost must remain at least 7000 (`ERR_CORE_IDENTITY_DILUTION`, HTTP 422). On approval the line's `dilution_cost_bps` is **frozen** at its current value and the brand's consumption and identity share are recomputed with the line now counting at full frozen cost.

The dilution cost itself is computed as follows. A core line always costs 0. Any other line costs 400 basis points, plus 150 basis points for every target channel beyond the first, plus a 200-basis-point **novelty** surcharge when at least one of the line's pack formats (in any status except `RETIRED`) uses a `delivery_system` that no pack format (again excluding `RETIRED`) of any *other* `LAUNCHED` line of the same brand uses — capped in total at 1000 basis points. The evaluation baseline is pinned: only the brand's other lines that are already `LAUNCHED` at the moment this line's launch arithmetic is evaluated count, and the candidate line is never part of its own baseline. Before `PILOT` the value is a live-computed preview; from `PILOT` entry onward it is the frozen figure.

A `PILOT` line is launched by a `BrandManager`, moving it `PILOT` → `LAUNCHED`. Three gates guard the launch, evaluated in this order: the brand must be `OPERATING` (`ERR_BRAND_IN_LOCKDOWN`, 409), the brand's posture must not be `CRITICAL` (`ERR_POSTURE_CRITICAL`, 409), and at least one pack format of the line must be `IN_PRODUCTION` (`ERR_NO_PRODUCIBLE_PACK_FORMAT`, 409). Launching stamps `launched_at` with the current logical time; the dilution figures do not change at launch, because the frozen cost was already counted when the line entered `PILOT`.

A line in `PILOT` or `LAUNCHED` may be discontinued by a `BrandManager`, unless it is the core line — the core line can never be discontinued and the attempt is rejected with `ERR_CORE_LINE_IMMUTABLE` (HTTP 409). Discontinuation recomputes the brand's dilution consumption and identity share; a discontinued line that had reached `PILOT` continues to consume half of its frozen cost, rounded down, forever. `DISCONTINUED` is terminal.

### 3.3. Trade-Secret Formulations, Contract Manufacturers and Compartmentalized Disclosure

The core formulation is a trade secret, and the system models exactly who has seen how much of it. A `TradeSecretOfficer` authors a **Formulation** under a product line, giving it a free-form `version_label`, a `component_codes` array of trade-secret component identifiers, and a `voc_class` of `STANDARD` or `LOW_VOC` (`LOW_VOC` being the only class a `STRICT` market will register). The array must hold between 1 and 12 non-empty strings: an empty array, or any entry that is not a non-empty string, is a request-shape failure (`ERR_INVALID_REQUEST`, HTTP 400), while an oversized list — more than 12 entries — is rejected with `ERR_COMPONENT_LIMIT_EXCEEDED` (HTTP 422). Passing a `master_formulation_id` — which must reference an existing formulation — declares the new record a local market variant of that master; a master formulation itself carries null there. Formulations begin in `DRAFT` with `sealed_at` unset, and can be listed with optional `product_line_id`, `master_formulation_id` and `status` filters.

Sealing, performed by a `TradeSecretOfficer`, moves a formulation `DRAFT` → `SEALED` and stamps `sealed_at` with the current logical time; it is only possible once the formulation names at least three components, failing `ERR_INSUFFICIENT_COMPONENTS` (HTTP 422). From `SEALED` the formulation advances to `COMPARTMENTALIZED` automatically — no explicit call exists — at the moment every one of its component codes is covered by at least one confidentiality grant of that formulation in `ACTIVE` status. Symmetrically, the instant a revocation or an expiry breaks that complete coverage, the formulation regresses `COMPARTMENTALIZED` → `SEALED`, again automatically.

**Contract manufacturers** are onboarded by a `TradeSecretOfficer` with a `legal_name`, a `site_country` ISO code, and a non-empty `capabilities` array drawn from `BLENDING`, `AEROSOL_FILL`, `LIQUID_FILL` and `PACKAGING`. The onboarding officer's `X-User-ID` is recorded as `sponsoring_officer_id`; the field is informational only and gates no later operation — segregation of duties on for-cause revocation is judged solely against `granted_by_user_id`, as described with the revoke transition below. A manufacturer begins in `VETTING` and is qualified — `VETTING` → `QUALIFIED` — by a `TradeSecretOfficer` without further preconditions. Only a `QUALIFIED` manufacturer may hold live grants. Requalification from `SUSPENDED` back to `QUALIFIED` clears `suspended_at`, but it is refused with `ERR_RECENT_BREACH` (HTTP 409) while any grant of this manufacturer shows `revoked_for_cause` true with a `revoked_at` inside the trailing 90 days. Each manufacturer also exposes the computed `disclosed_component_count`: the number of distinct formulation-and-component pairs its `GRANTED` or `ACTIVE` grants currently cover.

A **ConfidentialityGrant** is requested by a `TradeSecretOfficer` for a `manufacturer_id` and a `formulation_id`, naming a `component_scope` — a non-empty subset of that formulation's `component_codes`, failing `ERR_SCOPE_NOT_SUBSET` (HTTP 422) — a `grant_reason` of `PRODUCTION`, `PILOT_SUPPLY` or `SECOND_SOURCE`, and an `expires_on` instant that must lie strictly after the current logical time; an expiry already at or in the past at creation is refused as an invalid window (`ERR_WINDOW_INVALID`, HTTP 422). Creation further requires the manufacturer to be `QUALIFIED` (`ERR_MANUFACTURER_NOT_QUALIFIED`, HTTP 409) and the formulation to be `SEALED` or `COMPARTMENTALIZED` (`ERR_FORMULATION_NOT_SEALED`, HTTP 409). The grant starts in `REQUESTED` with `granted_by_user_id`, `revoked_at` unset and `revoked_for_cause` false. Grants are listable with optional `manufacturer_id`, `formulation_id` and `status` filters.

The grant action moves `REQUESTED` → `GRANTED`. It enforces **compartmentalization** first: taking the union of this manufacturer's component scopes on this same formulation across grants already in `GRANTED` or `ACTIVE`, plus the candidate scope, the size of that union multiplied by two must not exceed the formulation's total component count — a manufacturer may never hold disclosure over more than half of a formulation's recipe, and a breach is rejected with `ERR_COMPARTMENT_SCOPE_EXCEEDED` (HTTP 422). Only then does it re-verify that `expires_on` is still strictly after the current logical time (`ERR_GRANT_EXPIRED`, HTTP 409). Granting records the caller's `X-User-ID` in `granted_by_user_id` and recomputes the manufacturer's `disclosed_component_count`.

Activation moves `GRANTED` → `ACTIVE` and is the moment disclosure actually bites. It requires the manufacturer to be `QUALIFIED` (`ERR_MANUFACTURER_NOT_QUALIFIED`) and `expires_on` still strictly in the future (`ERR_GRANT_EXPIRED`); it recomputes `disclosed_component_count`, and when the newly active scope completes the formulation's coverage the formulation flips `SEALED` → `COMPARTMENTALIZED` as described above.

Revocation is the `ComplianceAuditor`'s instrument and accepts a `for_cause` boolean; it is admissible from `REQUESTED`, `GRANTED` and `ACTIVE` alike. Segregation of duties applies when `for_cause` is true and a `granted_by_user_id` has been recorded: the revoking caller's `X-User-ID` must differ from it, failing `ERR_AUDITOR_CONFLICT` (HTTP 409). Every revocation stamps `revoked_at` with the current logical time and copies the flag into `revoked_for_cause`. From `REQUESTED` the revocation stops there, apart from a posture recompute when for-cause — a never-granted request triggers no manufacturer cascade. From `GRANTED` the manufacturer's `disclosed_component_count` is recomputed, and from `ACTIVE` the formulation's coverage is additionally re-evaluated, regressing it to `SEALED` if some component is now uncovered. When the revocation is for cause and the manufacturer is `QUALIFIED`, the full **for-cause cascade** fires: the manufacturer drops to `SUSPENDED` with `suspended_at` stamped at the current logical time; every *other* grant of that manufacturer in `REQUESTED`, `GRANTED` or `ACTIVE` is itself revoked with `revoked_for_cause` true and `revoked_at` set to now; each formulation touched by those revocations re-evaluates its coverage and may regress from `COMPARTMENTALIZED` to `SEALED`; and the `protection_posture` of every brand owning an affected formulation's line is recomputed. A posture recompute on the owning brand also follows any revocation. Finally, the clock sweep expires grants: a `GRANTED` grant reaching its `expires_on` becomes `EXPIRED` with a `disclosed_component_count` recompute, and an `ACTIVE` grant doing so additionally re-evaluates formulation coverage, regressing the formulation if coverage broke. `REVOKED` and `EXPIRED` are terminal.

### 3.4. Markets and Product Registration

International expansion is modelled market by market. A `RegulatoryAffairs` officer creates a **Market** with a `country_code` — unique across all markets, with duplicates rejected by `ERR_MARKET_CODE_EXISTS` (HTTP 409) — a display `name`, a `registration_required` flag, a `voc_regime` of `STANDARD` or `STRICT`, and a non-empty `allowed_channels` array drawn from the four channels. A market is born `OPEN`. Closing a market moves it `OPEN` → `CLOSED`; `CLOSED` is terminal, and the close is refused with `ERR_MARKET_IN_USE` (HTTP 409) while either any coverage assignment references it in `PROPOSED`, `ACTIVE` or `SUSPENDED` status, or any registration references it in `DRAFT`, `SUBMITTED`, `ACTIVE` or `RENEWAL_DUE` status.

A **MarketRegistration** ties a product line to a market under a specific formulation. Creation by `RegulatoryAffairs` supplies `market_id`, `product_line_id`, `formulation_id` and an `expires_on` that must lie strictly after the current logical time. The gates: the market must be `OPEN` (`ERR_MARKET_NOT_OPEN`, HTTP 409); the line must be `PILOT` or `LAUNCHED` (`ERR_LINE_STAGE_TOO_EARLY`, HTTP 409); the formulation must actually belong to the named line (`ERR_FORMULATION_LINE_MISMATCH`, HTTP 422) and be `SEALED` or `COMPARTMENTALIZED` (`ERR_FORMULATION_NOT_SEALED`); a `STRICT`-regime market accepts only a `LOW_VOC` formulation (`ERR_VOC_REGIME_MISMATCH`, HTTP 422); and at most one non-terminal registration may exist per market-and-line pair, a second being refused with `ERR_REGISTRATION_EXISTS` (HTTP 409). The record starts in `DRAFT` with `registration_number`, `submitted_at` and `approved_at` unset and `revise_count` at 0. Registrations are listable with optional `market_id`, `product_line_id`, `formulation_id` and `status` filters.

Submission moves `DRAFT` → `SUBMITTED`, stamps `submitted_at`, and is gated on the brand being `OPERATING` (`ERR_BRAND_IN_LOCKDOWN`) and its posture not `CRITICAL` (`ERR_POSTURE_CRITICAL`). Approval moves `SUBMITTED` straight to `ACTIVE`: the authority's `registration_number` is supplied with the request and stored, `approved_at` is stamped, and the registration's `expires_on` must still be strictly after the current logical time (`ERR_WINDOW_INVALID`, HTTP 422). Rejection moves `SUBMITTED` → `REJECTED` and carries a mandatory `reason` in the request; the reason is validated for presence but is not stored on the registration. Revision loops `REJECTED` → `DRAFT` and increments `revise_count`, readying the dossier for a fresh submission.

The renewal regime is driven by the clock. When the current time reaches the instant 90 days before `expires_on` — the boundary instant itself counts — an `ACTIVE` registration becomes `RENEWAL_DUE`. When the current time reaches `expires_on`, a `RENEWAL_DUE` registration becomes `EXPIRED`, and an `ACTIVE` registration whose expiry was jumped past in a single sweep goes straight to `EXPIRED`. Renewal is admitted only from `RENEWAL_DUE` and requires a `new_expires_on` strictly greater than the current `expires_on` (`ERR_WINDOW_INVALID` otherwise); on success the registration returns to `ACTIVE` with `expires_on` replaced and `submitted_at` / `approved_at` left untouched. Calling for renewal while the registration is still `ACTIVE` is rejected with `ERR_RENEWAL_WINDOW_NOT_OPEN` (HTTP 409), because the window has not opened; calling for it once the registration is `EXPIRED` is rejected with `ERR_REGISTRATION_EXPIRED` (HTTP 409). Revocation is available from `ACTIVE` and `RENEWAL_DUE`, lands in `REVOKED`, and cascades: every coverage assignment matching the registration's market and line that is currently `ACTIVE` drops to `SUSPENDED`. `EXPIRED` and `REVOKED` are terminal.

### 3.5. Distributors, Coverage Cells and the Assignment Lifecycle

A **Distributor** is created by a `ChannelManager` with a `legal_name`, a `home_market_id`, a non-empty `channels_served` array drawn from the four channels, and a positive `credit_limit_cents` ceiling (informational only — no rule in this API debits it). The distributor starts as an `APPLICANT` with `suspension_count` 0; its attainment fields `attainment_actual_bps` and `attainment_projected_bps` and its `quota_compliance_tier` are null until the first attainment recomputation (§3.6). Distributors are listable with optional `home_market_id` and `status` filters. Approval — `APPLICANT` → `APPROVED` — requires the home market to be `OPEN` (`ERR_MARKET_NOT_OPEN`).

Suspension is a strike system. Suspending an `APPROVED` distributor — whether by a `ChannelManager`'s manual action or automatically when an attainment recomputation yields a `SANCTION` tier (§3.6) — increments `suspension_count` by one and cascades every `ACTIVE` coverage assignment of the distributor to `SUSPENDED`. But a suspension that would bring the count to 3 never lands: the distributor goes straight to `TERMINATED` with `suspension_count` set to 3. Termination is also available directly to a `ChannelManager` from `APPLICANT`, `APPROVED` or `SUSPENDED`. On termination the distributor's `PROPOSED` assignments are `WITHDRAWN` and its `ACTIVE` or `SUSPENDED` assignments are `TERMINATED`. Reinstatement returns a `SUSPENDED` distributor to `APPROVED`, but — importantly — it does **not** resume coverage: each `SUSPENDED` assignment must be resumed individually. `TERMINATED` is terminal.

A **CoverageAssignment** is the atomic unit of distribution coverage: one distributor, one market, one product line, one channel. A `ChannelManager` proposes one under a distributor's path, and the create is concurrency-guarded per §2.7 — the request must carry `expected_distributor_version`, and a stale value is rejected with `ERR_STALE_VERSION` (HTTP 412); a successful create increments the distributor's `version` by one. The proposal names `market_id`, `product_line_id`, a single `channel`, an `exclusive` flag defaulting to false, a `starts_on` and `ends_on` pair of `YYYY-MM-DD` dates forming a closed window, and a positive `annual_quota_units`. Creation requires: the distributor `APPROVED` (`ERR_DISTRIBUTOR_NOT_APPROVED`, HTTP 409); the market `OPEN` (`ERR_MARKET_NOT_OPEN`); the line `PILOT` or `LAUNCHED` (`ERR_LINE_STAGE_TOO_EARLY`); the channel present in the distributor's `channels_served` (`ERR_CHANNEL_NOT_SERVED`, HTTP 422), in the market's `allowed_channels` (`ERR_CHANNEL_NOT_ALLOWED`, HTTP 422), and in the line's `target_channels` (`ERR_CHANNEL_OUTSIDE_LINE_SCOPE`, HTTP 422); and a sane window — `starts_on` strictly before `ends_on`, and `ends_on` not already past (`ERR_WINDOW_INVALID`, HTTP 422). If `exclusive` is true, the proposal also conflicts — `ERR_EXCLUSIVE_OVERLAP` (HTTP 409) — with any other assignment on the same market-channel-line **cell** that is itself exclusive, sits in `ACTIVE` or `SUSPENDED`, and overlaps under closed-interval semantics; because the intervals are closed, windows that merely touch on a single date already conflict. The triple `(market_id, channel, product_line_id)` defines the cell for every capacity and exclusivity rule in this section. Creation has one more side effect: any `PROPOSED` proposals already sitting on the same cell are moved to `SUPERSEDED`, and the new assignment's `supersedes_assignment_id` points at the superseded proposal with the greatest `created_at` — ties broken toward the most recently created proposal — or stays null when nothing was superseded. Assignments are listable with optional `distributor_id`, `market_id`, `product_line_id`, `channel` and `status` filters.

Activation moves a `PROPOSED` assignment to `ACTIVE` through a battery of gates, evaluated in §2.6 category order: the distributor must be `APPROVED` (`ERR_DISTRIBUTOR_NOT_APPROVED`); when the assignment is exclusive, the brand must be `OPERATING` (`ERR_BRAND_IN_LOCKDOWN`, 409) and its posture not `CRITICAL` (`ERR_POSTURE_CRITICAL`, 409); the current date must lie inside the closed coverage window (`ERR_WINDOW_INVALID`); exclusivity is re-checked against overlapping exclusive `ACTIVE` or `SUSPENDED` assignments on the cell (`ERR_EXCLUSIVE_OVERLAP`); the line must be `LAUNCHED` (`ERR_LINE_NOT_LAUNCHED`, HTTP 409); when the market's `registration_required` is true, a registration for the assignment's market and line must be `ACTIVE` (`ERR_REGISTRATION_NOT_ACTIVE`, HTTP 409); and the cell must currently hold fewer than 3 assignments in `ACTIVE` or `SUSPENDED` — a third coexists, a fourth is refused with `ERR_CELL_CAPACITY_EXCEEDED` (HTTP 409).

An `ACTIVE` assignment may be suspended by a `ChannelManager`, and is suspended automatically by the distributor-suspension and registration-revocation cascades. `SUSPENDED` still reserves its cell: it counts for both the exclusivity check and the capacity ceiling, and it keeps its quota in the attainment basis (§3.6). Suspending an assignment recomputes the distributor's attainment with the quota basis unchanged — a suspended assignment still counts. Resuming a `SUSPENDED` assignment re-applies only a subset of the activation gates, in the same category order and with the same error codes — distributor approved, window live, the exclusivity re-check, registration active where required, and cell capacity. The line-`LAUNCHED` gate and the exclusive-brand lockdown/posture gates are not re-applied on resume. A `PROPOSED` assignment may instead be withdrawn to `WITHDRAWN`. The clock sweep closes coverage: when the current date passes `ends_on`, `ACTIVE` and `SUSPENDED` assignments become `CLOSED`. Distributor termination moves `ACTIVE` or `SUSPENDED` assignments to `TERMINATED` and `PROPOSED` ones to `WITHDRAWN`. `SUPERSEDED`, `WITHDRAWN`, `CLOSED` and `TERMINATED` are all terminal.

### 3.6. Sell-Through Reporting, Attainment and the Rebate Preview

Coverage is paid for in reported sell-through. A **SellThroughReport** is filed under a distributor's path by a `DistributorContact` whose `X-User-ID` must equal that path distributor's `id` — a mismatch is refused with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). The body names a `coverage_assignment_id` that must exist and belong to the path distributor — a body-reference failure (`ERR_INVALID_REFERENCE`, HTTP 422) that, per the §2.6 pipeline, fires before the ownership check above — a `period_month` in `YYYY-MM` form, a non-negative `units_sold`, and an optional `units_returned` defaulting to 0. The referenced assignment must be `ACTIVE`, `SUSPENDED` or `CLOSED`; reporting against any other status is refused with `ERR_INVALID_STATE_TRANSITION` (HTTP 409). The period must be a **completed** month, strictly before the current logical month — reporting the in-progress month or a future one is refused with `ERR_PERIOD_NOT_COMPLETED` (HTTP 422) — and each assignment admits exactly one report per month, a duplicate drawing `ERR_DUPLICATE_REPORT` (HTTP 409). The stored `net_units` is the larger of zero and `units_sold` minus `units_returned`. As noted in §2.5, the report is immutable: it carries `id` and `created_at` only, with no `updated_at` and no `version`. Reports are listable with optional `distributor_id`, `coverage_assignment_id` and `period_month` filters.

Every accepted report recomputes the distributor's **coverage attainment**, in two variants over the same window — the three calendar months strictly before the current logical month, matched by `period_month`. The scope is the distributor's assignments in `ACTIVE` or `SUSPENDED`; if that scope is empty, all attainment fields and the tier are left untouched. The **ACTUAL** variant is conservative: it sums `net_units` across the in-scope assignments' reports inside the window into a total, and sums a three-month quota built as the per-assignment floor of `annual_quota_units` divided by 4; `attainment_actual_bps` is then 0 when that quota sums to zero, and otherwise 10000 times the total net divided by the three-month quota, rounded half up to integer basis points. The **PROJECTED** variant is deliberately optimistic: it takes the single best window month — summing `net_units` per month, with a missing month counting as 0 — annualizes that best month by multiplying by 12, and divides by the full annual quota (the sum of `annual_quota_units` over the in-scope assignments); `attainment_projected_bps` is 0 when that annual quota is zero, and otherwise 10000 times the annualized best month divided by the annual quota, again rounded half up.

The tier derives from `attainment_actual_bps` alone: `GOLD` at 12000 or above, `STANDARD` at 10000 or above, `WATCH` at 9000 or above, and `SANCTION` below that. Whenever a recomputation yields `SANCTION` while the distributor is `APPROVED` — whether or not the tier changed on this recompute — the suspension machinery of §3.5 fires automatically: suspension and assignment cascade, or outright termination on the third strike.

The **rebate preview** is a computed read available to `ChannelManager`, `PricingAnalyst` and `PlatformAdmin`, taking a `reference_unit_price_cents` query parameter from the caller — required and a non-negative integer; a missing, malformed or negative value is `ERR_INVALID_REQUEST` (HTTP 400). It answers with the distributor's current `attainment_actual_bps`, `attainment_projected_bps` and `quota_compliance_tier` (each possibly null), plus a `rebate_bps` rate and a monetary `rebate_estimate_cents`, and the `window_net_units` total it was priced from. The rate is tier-driven: `GOLD` earns 300 basis points, `STANDARD` 200, `WATCH` 100, `SANCTION` 0, and a null tier earns 0 with no `MASS` bonus; for a non-null tier, serving the `MASS` channel adds a 25-basis-point bonus, and the sum is capped at 350. The estimate multiplies the trailing-three-month net-units total by `reference_unit_price_cents` and by `rebate_bps` per ten thousand, rounding half up to whole cents.

### 3.7. Pack Formats, Tooling and Channel Price Lists

A **PackFormat** is created under a product line by a `SupplyPlanner` with a positive `size_ml`, a `delivery_system` of `AEROSOL`, `TRIGGER_SPRAY`, `PUMP`, `PRECISION_PEN` or `BULK_CONTAINER`, a `channel_restrictions` array that must be a non-empty subset of the owning line's `target_channels` (a channel outside that scope is refused with `ERR_CHANNEL_OUTSIDE_LINE_SCOPE`, HTTP 422), and an optional `case_pack_qty` — units per trade case — defaulting to 1 and never below 1. A pack begins `DESIGNED`; packs are listable with optional `product_line_id` and `status` filters. Tooling moves `DESIGNED` → `TOOLED` and requires the owning line to be `PILOT` or `LAUNCHED` (`ERR_LINE_STAGE_TOO_EARLY`, HTTP 409). Entering production moves `TOOLED` → `IN_PRODUCTION` and requires both a `COMPARTMENTALIZED` formulation on the owning line (`ERR_FORMULATION_NOT_COMPARTMENTALIZED`, HTTP 409) and at least one price list of the pack in `SCHEDULED` or `EFFECTIVE` (`ERR_NO_PRICE_LIST`, HTTP 409). Retirement moves `IN_PRODUCTION` → `RETIRED` and is only possible once every price list of the pack is terminal — `SUPERSEDED` or `EXPIRED` — otherwise `ERR_PRICE_LISTS_OUTSTANDING` (HTTP 409). `RETIRED` is terminal.

A **ChannelPriceList** prices one pack format in one channel over a half-open datetime window. A `PricingAnalyst` creates one under the pack's path, and the create is concurrency-guarded per §2.7: the request carries `expected_pack_format_version`, a stale value draws `ERR_STALE_VERSION` (HTTP 412), and a successful create increments the pack format's `version` by one. The body names the `channel` — which must be a member of the pack's `channel_restrictions` (`ERR_CHANNEL_NOT_ALLOWED`, HTTP 422) — a positive `list_price_cents`, a `map_price_cents` minimum advertised price that must be positive and no greater than the list price (`ERR_MAP_ABOVE_LIST`, HTTP 422), and the `effective_from` / `effective_to` window bounds. The window must be well-ordered — `effective_from` strictly before `effective_to` — and not entirely in the past; either fault is `ERR_WINDOW_INVALID` (HTTP 422). Creation stamps the initial status from the current logical time: `EFFECTIVE` when the time already lies inside the window, otherwise `SCHEDULED`. Price lists are listable with optional `pack_format_id`, `channel` and `status` filters.

Because windows on the same pack-and-channel pair may touch but never overlap, creation reconciles the incumbents. An overlapped `SCHEDULED` list becomes `SUPERSEDED`. An overlapped `EFFECTIVE` list is treated by where the newcomer starts: when the new list's `effective_from` is at or before the incumbent's `effective_from`, the incumbent is `SUPERSEDED`; when the new list starts strictly inside the incumbent's window, the incumbent is **clipped** — its `effective_to` is set to the new list's `effective_from` and it stays `EFFECTIVE` until that instant. Thereafter the clock sweep walks lists forward: `SCHEDULED` → `EFFECTIVE` when the current time enters the window, `EFFECTIVE` → `EXPIRED` when it reaches `effective_to`, and a `SCHEDULED` list whose entire window is jumped past in one sweep goes straight to `EXPIRED`. `SUPERSEDED` and `EXPIRED` are terminal.

The **effective-price** read resolves which list governs a pack and channel at an instant: the caller supplies the `channel` query parameter — required, a missing or invalid value drawing `ERR_INVALID_REQUEST` (HTTP 400) — and may supply an `at` query parameter (defaulting to the current logical time). Among non-`SUPERSEDED` lists for the pair whose half-open window contains the instant, the one with the greatest `effective_from` wins; a tie on `effective_from` breaks toward the earliest `created_at`. When no candidate covers the instant, the read fails with `ERR_NO_EFFECTIVE_PRICE` (HTTP 404). The response carries the winning list's `price_list_id`, `channel`, `list_price_cents`, `map_price_cents`, `effective_from` and `effective_to`.

### 3.8. Promotions: Depth Discipline, Funding and Redemption

A **Promotion** is a dated percent-off event for one product line in one channel. A `PricingAnalyst` creates one with `product_line_id`, `channel`, a `discount_pct` strictly greater than 0 and at most 90.00 with at most two decimal places, a closed date window `starts_on` to `ends_on` (`ends_on` may equal `starts_on` but never precede it, and a window entirely past is refused — both faults are `ERR_WINDOW_INVALID`, HTTP 422), and a positive `funding_budget_cents` pool. Creation requires the line to be `PILOT` or `LAUNCHED` (`ERR_LINE_STAGE_TOO_EARLY`) and the channel to sit inside the line's `target_channels` (`ERR_CHANNEL_OUTSIDE_LINE_SCOPE`). The creator's `X-User-ID` is stored as `created_by_user_id`; the promotion starts in `DRAFT` with `accrued_funding_cents` and `redemptions_count` at 0, `unit_funding_provisional_cents` null, and `approved_by_user_id` unset. Promotions are listable with optional `product_line_id`, `channel` and `status` filters.

Submitting moves `DRAFT` → `PENDING_APPROVAL`. Approval is a `MarketingManager` act and is deliberately segregated: the approver's `X-User-ID` must differ from `created_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`, HTTP 403). Approval then enforces the pricing doctrine in order. The depth cap tracks the brand's protection posture: `discount_pct` may not exceed 25.00 under `NORMAL`, 15.00 under `ELEVATED`, or 5.00 under `CRITICAL` (`ERR_PROMO_DEPTH_EXCEEDS_CAP`, HTTP 422). Price support must exist: at least one pack format of the line must hold a non-`SUPERSEDED` price list for this channel whose half-open window contains the instant `starts_on`T00:00:00Z (`ERR_NO_PRICE_LIST`, HTTP 409). The advertised-price floor must hold for **every** such pack and covering list: the list price minus the per-unit discount — the discount being `list_price_cents` times `discount_pct` per hundred, rounded half up to whole cents — must stay at or above that list's `map_price_cents` (`ERR_BELOW_MAP_PRICE`, HTTP 422). Then cadence, frequency before gap: among the promotion's peers — the other promotions of the same line and channel in `APPROVED`, `LIVE`, `SUSPENDED` or `ENDED` — those whose `starts_on` falls within 90 days before or after the candidate's `starts_on` must number fewer than 2 (`ERR_PROMO_TOO_FREQUENT`, HTTP 422); and every peer's `starts_on` must sit at least 14 days away in absolute terms (`ERR_PROMO_GAP_VIOLATION`, HTTP 422). On approval the approver is recorded in `approved_by_user_id`, and the provisional unit funding `unit_funding_provisional_cents` is computed once and never updated afterwards: among the line's packs that hold a non-`SUPERSEDED` list for the channel covering `starts_on` (again at the `starts_on`T00:00:00Z instant), the reference pack is the smallest by `size_ml` with ties broken by earliest `created_at`, the reference list is that pack's governing list for the channel at that instant under the §3.7 resolution rule, and the provisional funding is that list's `list_price_cents` times `discount_pct` per hundred, rounded half up to whole cents. If the approval lands while the current date already lies inside the promotion window, the promotion skips `APPROVED` and enters `LIVE` immediately.

From `APPROVED`, the clock sweep moves the promotion to `LIVE` when the current date reaches `starts_on` while not past `ends_on`, or straight to `ENDED` when the date passes `ends_on` first. A `LIVE` promotion ends via the sweep once the current date passes `ends_on`. The protection cascade of §3.1 and §3.9 can instead flip `LIVE` → `SUSPENDED` whenever a posture recomputation yields `CRITICAL` (transition or not); `accrued_funding_cents` and `funding_budget_cents` are deliberately left untouched by that flip, and the sweep never ends a `SUSPENDED` promotion — one that outlives its window while suspended can only leave by resuming and then expiring. Resuming is a `MarketingManager` act that returns the promotion to `LIVE`. Its guards fire in §2.6 order: first the closed window — a current date past `ends_on` is refused with `ERR_PROMO_WINDOW_CLOSED` (HTTP 409) — then the posture must no longer be `CRITICAL` (`ERR_POSTURE_CRITICAL`), and finally the brand must be `OPERATING` (`ERR_BRAND_IN_LOCKDOWN`). `ENDED` is terminal.

**Redemption** is recorded by a `ChannelManager` against a `LIVE` promotion, naming a `pack_format_id` and a `units` count that must be an integer of at least 1 (anything less is `ERR_INVALID_REQUEST`, HTTP 400). The pack must belong to the promotion's line (`ERR_PACK_LINE_MISMATCH`, HTTP 422). The actual unit funding is priced fresh at redemption time: the price list `EFFECTIVE` right now for the redeemed pack and the promotion's channel is resolved exactly as in §3.7, and the per-unit funding is that list's `list_price_cents` times `discount_pct` per hundred, rounded half up to whole cents — this ACTUAL figure can diverge from the provisional one when the price list changed between `starts_on` and redemption. The promotional unit price is the list price minus the unit funding, and the promotional case price multiplies that unit price by the pack's `case_pack_qty` — rounding happens **once**, at the unit level, before the multiplication; discounting the case gross and rounding at case level is non-conformant (a 499-cent list at 15.00 percent with a case of 12 must yield 5088 cents, not 5090). The redemption's total funding is the unit funding times the redeemed units, and it must fit the purse: the accrued funding plus this total may not exceed `funding_budget_cents` (`ERR_PROMO_BUDGET_EXCEEDED`, HTTP 409). On success `accrued_funding_cents` grows by the total and `redemptions_count` increments by one. The response carries `redemption_id`, `unit_funding_cents`, `promo_unit_price_cents`, `promo_case_price_cents`, `total_funding_cents`, the updated `accrued_funding_cents`, and the `remaining_budget_cents` left in the pool.

### 3.9. Brand Defense: Counterfeit Enforcement and Consumer Use Cases

A **CounterfeitCase** is reported under a brand by a `ComplianceAuditor`, naming the `market_id` where the counterfeit surfaced, the `channel` of the finding, a `severity` from 1 (isolated) to 5 (systemic), and optionally `units_seized`, defaulting to 0. The case opens in `REPORTED`. Creation itself already recomputes the brand's `protection_posture` — so a severity-5 report makes the posture `CRITICAL` immediately and fires the promotion cascade at creation time. Cases are listable with optional `brand_id`, `market_id` and `status` filters. Recording enforcement action moves `REPORTED` → `ACTION_TAKEN`, overwrites `units_seized` with the figure in the request, recomputes the posture, and every `LIVE` promotion of the brand flips to `SUSPENDED` whenever the recomputed posture is `CRITICAL` — even if it was already `CRITICAL` before the action. Closing — from either `REPORTED` or `ACTION_TAKEN` — lands in `CLOSED` and recomputes the posture, but never auto-resumes suspended promotions: bringing them back is an explicit resume decision under §3.8. `CLOSED` is terminal.

The marketing engine runs on consumer-submitted applications. A **UseCaseSubmission** is filed under a product line by a `Consumer`, with a `submitter_ref` that must equal the caller's `X-User-ID` (`ERR_SUBMITTER_MISMATCH`, HTTP 403), a short `title`, and a free-text `description`. The line must be `LAUNCHED` (`ERR_LINE_NOT_LAUNCHED`, HTTP 409). The submission starts `SUBMITTED` with `generic_use_flag` false; submissions are listable with optional `product_line_id`, `status` and `submitter_ref` filters. Moderation is a `MarketingManager` review carrying a `decision` and a `generic_use_flag`: a `VERIFY` decision moves the submission to `VERIFIED`, records the flag, and recomputes the brand's genericization risk; a `REJECT` decision lands in `REJECTED`. Publishing moves `VERIFIED` → `PUBLISHED`, but a flagged submission — one whose `generic_use_flag` is true — may publish only while the brand's `genericization_risk_bps` stands below 500; at or above that level the publish is refused with `ERR_GENERICIZATION_RISK` (HTTP 422). A published piece can later be retracted to `RETRACTED`. `REJECTED` and `RETRACTED` are terminal.

The **genericization risk** ties the loop shut. Across every line of the brand, each `PUBLISHED` submission flagged for generic use contributes 100 basis points and each flagged `VERIFIED` submission contributes 50; the risk is the sum, capped at 10000. `REJECTED` and `RETRACTED` submissions contribute nothing, and the figure is recomputed at every verify-with-flag, publish and retract. It is the same `genericization_risk_bps` surfaced on the brand in §3.1, and the 500-point publish gate above reads it before the publish is allowed through.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify, transition or compute against an existing resource return `200 OK`. Creation and modification responses return the created or updated resource in the envelope's `data` field. The table below is a contract index only — request fields, gate order and side effects are specified in §2 and §3. Note that the logical-clock endpoint is mounted outside the `/brand-ops` prefix; every other path below is prefixed by `/brand-ops` exactly as shown.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the server's logical clock; runs the time sweep | PlatformAdmin |
| POST | `/brand-ops/brands` | Create a brand | BrandManager |
| GET | `/brand-ops/brands` | List brands | Any authenticated role |
| GET | `/brand-ops/brands/{id}` | Get a brand with computed posture, dilution, identity share and genericization risk | Any authenticated role |
| POST | `/brand-ops/brands/{id}/lockdown` | Enter `PROTECTIVE_LOCKDOWN` | ComplianceAuditor |
| POST | `/brand-ops/brands/{id}/lift-lockdown` | Return to `OPERATING` | ComplianceAuditor |
| POST | `/brand-ops/brands/{brandId}/product-lines` | Create a product line under a brand | BrandManager |
| GET | `/brand-ops/product-lines/{id}` | Get a product line | Any authenticated role |
| GET | `/brand-ops/product-lines` | List product lines (`brand_id`, `status` filters) | Any authenticated role |
| POST | `/brand-ops/product-lines/{id}/brand-review` | Brand review: `APPROVE` → `PILOT`, `REJECT` loops, third rejection auto-discontinues | BrandManager |
| POST | `/brand-ops/product-lines/{id}/launch` | Launch a `PILOT` line | BrandManager |
| POST | `/brand-ops/product-lines/{id}/discontinue` | Discontinue a non-core `PILOT` or `LAUNCHED` line | BrandManager |
| POST | `/brand-ops/product-lines/{lineId}/formulations` | Create a formulation for a line | TradeSecretOfficer |
| GET | `/brand-ops/formulations/{id}` | Get a formulation | Any authenticated role |
| GET | `/brand-ops/formulations` | List formulations (`product_line_id`, `master_formulation_id`, `status` filters) | Any authenticated role |
| POST | `/brand-ops/formulations/{id}/seal` | Seal a `DRAFT` formulation | TradeSecretOfficer |
| POST | `/brand-ops/contract-manufacturers` | Onboard a contract manufacturer | TradeSecretOfficer |
| GET | `/brand-ops/contract-manufacturers/{id}` | Get a manufacturer with computed `disclosed_component_count` | Any authenticated role |
| POST | `/brand-ops/contract-manufacturers/{id}/qualify` | Qualify from `VETTING`, or requalify from `SUSPENDED` | TradeSecretOfficer |
| POST | `/brand-ops/confidentiality-grants` | Request a confidentiality grant | TradeSecretOfficer |
| GET | `/brand-ops/confidentiality-grants/{id}` | Get a confidentiality grant | Any authenticated role |
| GET | `/brand-ops/confidentiality-grants` | List confidentiality grants (`manufacturer_id`, `formulation_id`, `status` filters) | Any authenticated role |
| POST | `/brand-ops/confidentiality-grants/{id}/grant` | Grant a `REQUESTED` grant | TradeSecretOfficer |
| POST | `/brand-ops/confidentiality-grants/{id}/activate` | Activate a `GRANTED` grant | TradeSecretOfficer |
| POST | `/brand-ops/confidentiality-grants/{id}/revoke` | Revoke a non-terminal grant; for-cause fires the suspension cascade | ComplianceAuditor |
| POST | `/brand-ops/distributors` | Create a distributor | ChannelManager |
| GET | `/brand-ops/distributors/{id}` | Get a distributor with computed attainment fields and tier | Any authenticated role |
| GET | `/brand-ops/distributors` | List distributors (`home_market_id`, `status` filters) | Any authenticated role |
| POST | `/brand-ops/distributors/{id}/approve` | Approve an `APPLICANT` | ChannelManager |
| POST | `/brand-ops/distributors/{id}/suspend` | Suspend an `APPROVED` distributor; third strike terminates | ChannelManager |
| POST | `/brand-ops/distributors/{id}/reinstate` | Reinstate a `SUSPENDED` distributor to `APPROVED` | ChannelManager |
| POST | `/brand-ops/distributors/{id}/terminate` | Terminate a non-terminated distributor | ChannelManager |
| GET | `/brand-ops/distributors/{id}/rebate-preview` | Attainment variants, tier, rebate rate and estimate for a reference unit price | ChannelManager, PricingAnalyst, PlatformAdmin |
| POST | `/brand-ops/markets` | Create a market | RegulatoryAffairs |
| GET | `/brand-ops/markets/{id}` | Get a market | Any authenticated role |
| POST | `/brand-ops/markets/{id}/close` | Close an `OPEN` market | RegulatoryAffairs |
| POST | `/brand-ops/market-registrations` | Create a registration | RegulatoryAffairs |
| GET | `/brand-ops/market-registrations/{id}` | Get a market registration | Any authenticated role |
| GET | `/brand-ops/market-registrations` | List registrations (`market_id`, `product_line_id`, `formulation_id`, `status` filters) | Any authenticated role |
| POST | `/brand-ops/market-registrations/{id}/submit` | Submit a `DRAFT` registration | RegulatoryAffairs |
| POST | `/brand-ops/market-registrations/{id}/approve` | Approve a `SUBMITTED` registration to `ACTIVE` | RegulatoryAffairs |
| POST | `/brand-ops/market-registrations/{id}/reject` | Reject a `SUBMITTED` registration | RegulatoryAffairs |
| POST | `/brand-ops/market-registrations/{id}/revise` | Return a `REJECTED` registration to `DRAFT` | RegulatoryAffairs |
| POST | `/brand-ops/market-registrations/{id}/renew` | Renew a `RENEWAL_DUE` registration | RegulatoryAffairs |
| POST | `/brand-ops/market-registrations/{id}/revoke` | Revoke an `ACTIVE` or `RENEWAL_DUE` registration | RegulatoryAffairs |
| POST | `/brand-ops/distributors/{distributorId}/coverage-assignments` | Propose a coverage assignment (OCC on distributor version) | ChannelManager |
| GET | `/brand-ops/coverage-assignments/{id}` | Get a coverage assignment | Any authenticated role |
| GET | `/brand-ops/coverage-assignments` | List coverage assignments (`distributor_id`, `market_id`, `product_line_id`, `channel`, `status` filters) | Any authenticated role |
| POST | `/brand-ops/coverage-assignments/{id}/activate` | Activate a `PROPOSED` assignment | ChannelManager |
| POST | `/brand-ops/coverage-assignments/{id}/suspend` | Suspend an `ACTIVE` assignment | ChannelManager |
| POST | `/brand-ops/coverage-assignments/{id}/resume` | Resume a `SUSPENDED` assignment | ChannelManager |
| POST | `/brand-ops/coverage-assignments/{id}/withdraw` | Withdraw a `PROPOSED` assignment | ChannelManager |
| POST | `/brand-ops/product-lines/{lineId}/pack-formats` | Create a pack format for a line | SupplyPlanner |
| GET | `/brand-ops/pack-formats/{id}` | Get a pack format | Any authenticated role |
| GET | `/brand-ops/pack-formats` | List pack formats (`product_line_id`, `status` filters) | Any authenticated role |
| POST | `/brand-ops/pack-formats/{id}/tool` | Tool a `DESIGNED` pack | SupplyPlanner |
| POST | `/brand-ops/pack-formats/{id}/enter-production` | Move a `TOOLED` pack to `IN_PRODUCTION` | SupplyPlanner |
| POST | `/brand-ops/pack-formats/{id}/retire` | Retire an `IN_PRODUCTION` pack | SupplyPlanner |
| POST | `/brand-ops/pack-formats/{packFormatId}/price-lists` | Create a channel price list (OCC on pack format version) | PricingAnalyst |
| GET | `/brand-ops/price-lists/{id}` | Get a price list | Any authenticated role |
| GET | `/brand-ops/price-lists` | List price lists (`pack_format_id`, `channel`, `status` filters) | Any authenticated role |
| GET | `/brand-ops/pack-formats/{id}/effective-price` | Resolve the price list governing a pack and channel at an instant | Any authenticated role |
| POST | `/brand-ops/promotions` | Create a promotion | PricingAnalyst |
| GET | `/brand-ops/promotions/{id}` | Get a promotion with accrued and provisional funding | Any authenticated role |
| GET | `/brand-ops/promotions` | List promotions (`product_line_id`, `channel`, `status` filters) | Any authenticated role |
| POST | `/brand-ops/promotions/{id}/submit` | Submit a `DRAFT` promotion for approval | PricingAnalyst |
| POST | `/brand-ops/promotions/{id}/approve` | Approve a `PENDING_APPROVAL` promotion | MarketingManager |
| POST | `/brand-ops/promotions/{id}/resume` | Resume a `SUSPENDED` promotion | MarketingManager |
| POST | `/brand-ops/promotions/{id}/redemptions` | Record units redeemed under a `LIVE` promotion | ChannelManager |
| POST | `/brand-ops/brands/{brandId}/counterfeit-cases` | Report a counterfeit case | ComplianceAuditor |
| GET | `/brand-ops/counterfeit-cases/{id}` | Get a counterfeit case | Any authenticated role |
| GET | `/brand-ops/counterfeit-cases` | List counterfeit cases (`brand_id`, `market_id`, `status` filters) | Any authenticated role |
| POST | `/brand-ops/counterfeit-cases/{id}/take-action` | Record enforcement action on a `REPORTED` case | ComplianceAuditor |
| POST | `/brand-ops/counterfeit-cases/{id}/close` | Close a `REPORTED` or `ACTION_TAKEN` case | ComplianceAuditor |
| POST | `/brand-ops/product-lines/{lineId}/use-cases` | Submit a consumer use case | Consumer |
| GET | `/brand-ops/use-cases/{id}` | Get a use-case submission | Any authenticated role |
| GET | `/brand-ops/use-cases` | List use-case submissions (`product_line_id`, `status`, `submitter_ref` filters) | Any authenticated role |
| POST | `/brand-ops/use-cases/{id}/review` | Moderate a `SUBMITTED` use case (`VERIFY` or `REJECT`) | MarketingManager |
| POST | `/brand-ops/use-cases/{id}/publish` | Publish a `VERIFIED` use case | MarketingManager |
| POST | `/brand-ops/use-cases/{id}/retract` | Retract a `PUBLISHED` use case | MarketingManager |
| POST | `/brand-ops/distributors/{distributorId}/sell-through-reports` | File a monthly sell-through report | DistributorContact |
| GET | `/brand-ops/sell-through-reports/{id}` | Get a sell-through report | Any authenticated role |
| GET | `/brand-ops/sell-through-reports` | List sell-through reports (`distributor_id`, `coverage_assignment_id`, `period_month` filters) | Any authenticated role |

## 5. Error Code Catalogue

The catalogue below fixes each error identifier and its HTTP status. The conditions that trigger each error are specified in §2 and §3 where the guarded workflow lives.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_SUBMITTER_MISMATCH` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_REFERENCE` | 422 Unprocessable Entity |
| `ERR_NO_EFFECTIVE_PRICE` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE_TRANSITION` | 409 Conflict |
| `ERR_DISTRIBUTOR_NOT_APPROVED` | 409 Conflict |
| `ERR_RENEWAL_WINDOW_NOT_OPEN` | 409 Conflict |
| `ERR_REGISTRATION_EXPIRED` | 409 Conflict |
| `ERR_PROMO_WINDOW_CLOSED` | 409 Conflict |
| `ERR_GRANT_EXPIRED` | 409 Conflict |
| `ERR_BRAND_IN_LOCKDOWN` | 409 Conflict |
| `ERR_POSTURE_CRITICAL` | 409 Conflict |
| `ERR_MANUFACTURER_NOT_QUALIFIED` | 409 Conflict |
| `ERR_COMPARTMENT_SCOPE_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_AUDITOR_CONFLICT` | 409 Conflict |
| `ERR_VOC_REGIME_MISMATCH` | 422 Unprocessable Entity |
| `ERR_GENERICIZATION_RISK` | 422 Unprocessable Entity |
| `ERR_RECENT_BREACH` | 409 Conflict |
| `ERR_LOCKDOWN_CONDITIONS_UNMET` | 409 Conflict |
| `ERR_WINDOW_INVALID` | 422 Unprocessable Entity |
| `ERR_EXCLUSIVE_OVERLAP` | 409 Conflict |
| `ERR_PERIOD_NOT_COMPLETED` | 422 Unprocessable Entity |
| `ERR_CLOCK_REGRESSION` | 400 Bad Request |
| `ERR_DUPLICATE_LINE_CODE` | 409 Conflict |
| `ERR_CORE_LINE_EXISTS` | 409 Conflict |
| `ERR_CORE_LINE_IMMUTABLE` | 409 Conflict |
| `ERR_MARKET_CODE_EXISTS` | 409 Conflict |
| `ERR_CHANNEL_NOT_SERVED` | 422 Unprocessable Entity |
| `ERR_CHANNEL_NOT_ALLOWED` | 422 Unprocessable Entity |
| `ERR_CHANNEL_OUTSIDE_LINE_SCOPE` | 422 Unprocessable Entity |
| `ERR_CELL_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_DUPLICATE_REPORT` | 409 Conflict |
| `ERR_REGISTRATION_EXISTS` | 409 Conflict |
| `ERR_SCOPE_NOT_SUBSET` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_COMPONENTS` | 422 Unprocessable Entity |
| `ERR_COMPONENT_LIMIT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_MAP_ABOVE_LIST` | 422 Unprocessable Entity |
| `ERR_FORMULATION_LINE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_PACK_LINE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_MARKET_IN_USE` | 409 Conflict |
| `ERR_MARKET_NOT_OPEN` | 409 Conflict |
| `ERR_FORMULATION_NOT_SEALED` | 409 Conflict |
| `ERR_FORMULATION_NOT_COMPARTMENTALIZED` | 409 Conflict |
| `ERR_REGISTRATION_NOT_ACTIVE` | 409 Conflict |
| `ERR_NO_PRICE_LIST` | 409 Conflict |
| `ERR_NO_PRODUCIBLE_PACK_FORMAT` | 409 Conflict |
| `ERR_PRICE_LISTS_OUTSTANDING` | 409 Conflict |
| `ERR_LINE_STAGE_TOO_EARLY` | 409 Conflict |
| `ERR_LINE_NOT_LAUNCHED` | 409 Conflict |
| `ERR_EQUITY_BUDGET_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_CORE_IDENTITY_DILUTION` | 422 Unprocessable Entity |
| `ERR_PROMO_DEPTH_EXCEEDS_CAP` | 422 Unprocessable Entity |
| `ERR_BELOW_MAP_PRICE` | 422 Unprocessable Entity |
| `ERR_PROMO_TOO_FREQUENT` | 422 Unprocessable Entity |
| `ERR_PROMO_GAP_VIOLATION` | 422 Unprocessable Entity |
| `ERR_PROMO_BUDGET_EXCEEDED` | 409 Conflict |
