# Retail Shopper Insights API — Product Requirements Document

## 1. Introduction

Retailers sit on an asset their suppliers covet: a loyalty-card-linked household transaction panel that reveals who buys what, in which category, and how behavior shifts when promotions run. Turning that panel into a revenue product without leaking shopper identity or favoring one supplier's brand intelligence over another's requires a platform that is part subscription billing system, part privacy clean room, and part compliance audit trail. This document specifies the Retail Shopper Insights API, the system that operationalizes that product.

The API manages the full commercial lifecycle of supplier data subscriptions. A supplier's access is governed by a tiered subscription contract that gates which report types it may request, how many report credits it can spend in a period, how much budget it can commit to audience activation, and whether it may redistribute reports or build modeled data products at all. On top of the panel, the system supports privacy-suppressed aggregate reporting, audience segment construction and channel activation, matched-control incrementality measurement for promotions, a query-audited data clean room with minimum-cell-size suppression, category line-review deliverable tracking with compliance scoring, and analog-based new-item forecasting.

Two concerns dominate the design. First, privacy: no report, segment, or query may expose a population smaller than the minimum cell size, and every export, query, grant decision, and activation launch is written to an append-only audit log. Second, segregation of duties: the analyst who builds an artifact is never the steward who approves it, and supplier-side identities are bound to the supplier account they act for. The sections that follow define the roles, the response envelope, the domain rules, the business workflows, the endpoints, and the error catalogue.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules that apply across every resource and endpoint.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. A request missing either header, or carrying a malformed value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is not permitted for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The system recognizes exactly five roles, spelled as follows: `RetailerAdmin`, `CategoryManager`, `InsightsScientist`, `SupplierAnalyst`, and `DataSteward`.

Role identity semantics differ by role and are part of the authorization contract:

- When `X-User-Role` is `SupplierAnalyst`, `X-User-ID` is the `id` of the acting `SupplierAccount`; ownership checks on any resource that references a `SupplierAccount` compare the resource's foreign-key field to `X-User-ID`. In particular, for any `SupplierAnalyst` write operation, the `X-User-ID` must equal the owning supplier account `id` of the target resource — a report, segment, activation, or grant belonging to a different supplier account is rejected with `ERR_FORBIDDEN_ROLE`.
- When `X-User-Role` is `RetailerAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it on audit events but does not compare it to any entity's `id`.
- When `X-User-Role` is `CategoryManager`, `X-User-ID` is likewise an opaque operator identifier, recorded (for example) as `actor_user_id` on audit events but never matched to an entity.
- When `X-User-Role` is `InsightsScientist`, `X-User-ID` is an opaque operator identifier; the server does not compare it to any entity's `id`.
- When `X-User-Role` is `DataSteward`, `X-User-ID` is an opaque operator identifier with one critical exception: it participates in segregation-of-duties checks — a `DataSteward` approving a clean-room grant must have an `X-User-ID` different from the grant's `requested_by_user_id` (see §3.6), even though the steward id itself corresponds to no persisted entity.

Segregation of duties is a deliberate design constraint across the platform: the analyst who creates an artifact is never the steward who approves it, and the retailer-side roles (`RetailerAdmin`, `CategoryManager`, `InsightsScientist`, `DataSteward`) partition contract administration, category governance, measurement science, and privacy stewardship into separate hands.

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

Endpoints that return lists of resources paginate via query parameters. The `limit` parameter specifies the maximum number of items to return; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. Both parameters are optional on every list endpoint.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

List-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Primary resources carry a standard set of system-managed fields:

- `id` (string): a unique, server-generated identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that starts at 1 on creation and increments with every modification to the resource. It is the basis for optimistic concurrency control.

Resources with the full common-field set are: `SupplierAccount`, `SubscriptionContract`, `InsightReport`, `AudienceSegment`, `SegmentActivation`, `IncrementalityStudy`, `CleanRoomGrant`, `LineReviewCycle`, `ReviewDeliverable`, and `NewItemForecast`.

Three resources are exceptions. `CategoryScope` carries only `id` and `created_at` — both `updated_at` and `version` are absent, because scopes are append-only descriptors of contract coverage. `CleanRoomQuery` likewise carries only `id` and `created_at`, because a query's outcome is decided synchronously at submission and the record is immutable thereafter. `AuditEvent` is an append-only log record carrying only `id` and `created_at`; it is never updated.

Any mutation of a resource — including system-driven mutations such as lazy state transitions, cascade effects from a parent operation, and derived-field reconciliation — refreshes `updated_at` and increments `version` on every resource that actually changes, where those fields exist.

### 2.5. The Logical Clock and Lazy Auto-Transitions

The system evaluates all time-dependent behavior against a logical clock, never against wall-clock time. At startup, before any clock-setting call has been made, the logical clock reads exactly `2026-09-01T00:00:00Z`. A `RetailerAdmin` advances the clock through an admin-only test-driving capability that accepts a `to_iso8601` timestamp and moves the logical clock to that instant; the response carries the resulting `current_utc`. The clock never falls back to wall-clock time on its own.

Three resources evolve lazily against this clock — the transition is evaluated when the resource is read or when a related operation occurs, not by a background scheduler:

- A `LineReviewCycle` in `SCHEDULED` moves to `OPEN` once the logical clock reaches its `open_at` instant (see §3.7). The auto-open is evaluated on cycle reads, on deliverable creation, and on deliverable submission.
- An `IncrementalityStudy` in `RUNNING` moves to `ANALYSIS` once the logical clock reaches the study's `window_end`, computing its lift metrics at that moment (see §3.5). The transition is evaluated on study reads and on study transition requests.
- A `CleanRoomGrant` in `APPROVED` moves to `EXPIRED` once the logical clock reaches `valid_until`; the transition is evaluated on grant reads and on query submission against the grant.

Additionally, a `SegmentActivation` in `LAUNCHED` completes automatically once the logical clock reaches the instant twenty-eight days after its `launched_at` timestamp, moving to `COMPLETED` (see §3.4).

### 2.6. Validation Ordering and Nested Resource Retrieval

Every request passes through a fixed validation cascade, evaluated in this order. Earlier failures mask later ones — a request rejected at an earlier stage never surfaces a later stage's error.

1. **Authentication context.** The `X-User-ID` and `X-User-Role` headers must be present and well-formed (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. **Role authorization.** The role must be permitted for the endpoint, and for `SupplierAnalyst` writes the `X-User-ID` must equal the owning supplier account `id` (`ERR_FORBIDDEN_ROLE`).
3. **Request shape.** Required fields must be present, enum members valid, types correct, and arrays non-empty where the endpoint requires them (`ERR_INVALID_REQUEST`).
4. **Existence.** Path resource identifiers must exist, validated left-to-right (`ERR_RESOURCE_NOT_FOUND`).
5. **State preconditions.** The target resource must be in a legal state for the operation (the family of state errors such as `ERR_CONTRACT_NOT_ACTIVE`, `ERR_GRANT_NOT_QUERYABLE`, `ERR_INVALID_STATE`, and their peers).
6. **Privacy and segregation-of-duties.** Grant self-approval, segment emptiness, and segment minimum-size checks (`ERR_SELF_APPROVAL_FORBIDDEN`, `ERR_SEGMENT_EMPTY`, `ERR_SEGMENT_BELOW_MINIMUM`).
7. **Referential business rules.** Category scope, tier permission, the one-active-contract-per-account rule, and modeled-derivation permission (`ERR_CATEGORY_OUT_OF_SCOPE`, `ERR_TIER_INSUFFICIENT`, `ERR_ACCOUNT_HAS_ACTIVE_CONTRACT`, `ERR_MODELED_DERIVATION_FORBIDDEN`).
8. **Temporal business rules.** Grant window overlap and line-review cycle gap (`ERR_WINDOW_OVERLAP`, `ERR_CYCLE_GAP_VIOLATION`).
9. **Fiscal rules.** Credit, allowance, activation budget, and query budget sufficiency (`ERR_INSUFFICIENT_REPORT_CREDITS`, `ERR_ALLOWANCE_BELOW_CONSUMED`, `ERR_ACTIVATION_BUDGET_EXCEEDED`, `ERR_INSUFFICIENT_QUERY_BUDGET`).
10. **Redistribution clauses.** Export-time contract clause checks (`ERR_REDISTRIBUTION_RESTRICTED`).

For endpoints whose paths nest resources (for example, a deliverable created within a cycle, or a query submitted within a grant), the path identifiers are validated in strict left-to-right order. The request is rejected with `ERR_RESOURCE_NOT_FOUND` corresponding to the first path identifier that does not exist, before any subsequent identifier or any business rule is examined.

### 2.7. Optimistic Concurrency Control

Two write operations require the caller to prove it has observed the current state of the parent resource, using a mandatory version field in the request body.

Amending a subscription contract requires `expected_contract_version`, carrying the client's last observed `version` of the target `SubscriptionContract`. If the value does not match the contract's current `version` — because another amendment, suspension, or termination has advanced it since the client last read the contract — the request is rejected with `ERR_STALE_CONTRACT_VERSION` (HTTP 412). The amendment supersedes the contract's tier and credit terms, so acting on a stale view would silently overwrite terms the client never saw.

Creating a segment activation requires `expected_segment_version`, carrying the client's last observed `version` of the target `AudienceSegment`. A mismatch with the segment's current `version` is rejected with `ERR_STALE_SEGMENT_VERSION` (HTTP 412), because the activation pins the approved segment's `size` at creation and a stale version means the fee and reach were computed from a size the client did not observe.

Endpoints not named here do not accept a version field; no other write operation performs an optimistic concurrency check.

### 2.8. Monetary Values, Units, and Rounding

Monetary amounts are represented as integer cents unless a field explicitly states otherwise (for example, `activation_budget_cents`, `line_fee_cents`, `total_fee_cents`, and the household spend metrics). Certain rates are fractional — the per-household activation rate is 2.5 cents — and intermediate arithmetic may produce fractional cents; the rounding rules for each calculation are stated where the calculation is defined.

Where a computed figure is a real number rather than an integer — forecast unit projections and lift percentages — the final stored value is rounded to exactly two decimal places using the round-half-up method. Computed counts (household counts, segment sizes, credit balances, query budgets) are integers with no rounding. The deterministic rounding order of the activation fee calculation is pinned in §3.4: each channel line's fee is rounded first, and the rounded line fees are then summed — summing raw values and rounding once at the end is a different algorithm and is forbidden.

### 2.9. Privacy Posture: Minimum Cell Size

A single privacy threshold governs all population reporting: the minimum cell size is twenty households. Any reported population smaller than twenty is suppressed — never rounded, bucketed, or approximated. The boundary is inclusive-pass: a count of exactly twenty passes, a count of nineteen is suppressed. This threshold applies identically to the cells of a generated insight report (where suppression of any cell suppresses the whole report) and to the result rows of a clean-room query. A separate, larger threshold — a minimum segment size of twenty-five households — governs audience segment approval. Both thresholds are hard constants of the platform, not per-contract configuration.

### 2.10. The Audit Trail

The system maintains an append-only compliance log of `AuditEvent` records. Each event records its `event_type`, the `actor_role` and `actor_user_id` drawn from the acting request's headers, the `subject_type` and `subject_id` of the entity the event concerns, and a free-form `detail` string. The recognized event types are `REPORT_EXPORTED`, `QUERY_EXECUTED`, `QUERY_SUPPRESSED`, `GRANT_APPROVED`, `GRANT_DENIED`, `GRANT_REVOKED`, and `ACTIVATION_LAUNCHED`. Audit events are written as side effects of the operations named in §3 and are never modified or deleted. The audit log is queryable by any authenticated role, with optional filtering by `subject_type` and `subject_id`.

## 3. Business Logic & Workflows

### 3.1. Onboarding Suppliers: Accounts, Contracts, and Category Scopes

A `RetailerAdmin` onboards a supplier by creating a supplier account with an `account_name` and a primary operating `region` code. The account's `status` is `ACTIVE` upon creation; the enumeration also defines `OFFBOARDED`, though accounts in this deployment always remain `ACTIVE`.

Within an account, the `RetailerAdmin` establishes a subscription contract by specifying its `tier`, the period's `report_credit_allowance`, the `activation_budget_cents` available for audience activation fees, and two contractual clauses: `redistribution_allowed`, which determines whether generated reports may be exported and redistributed at all, and `modeled_derivation_allowed`, which determines whether modeled or derived data products may be created and exported. The `tier` is one of `TIER_CATEGORY`, `TIER_BRAND`, or `TIER_PORTFOLIO`, and it gates which report types the supplier may request. A new contract is born `ACTIVE`. An account may hold at most one `ACTIVE` contract at a time: creating a second contract while one is still `ACTIVE` is rejected with `ERR_ACCOUNT_HAS_ACTIVE_CONTRACT`.

A contract tracks three credit counters. `report_credits_reserved` holds credits committed by reports awaiting generation; `report_credits_consumed` holds credits finalized by successfully generated reports; and `report_credits_available` is a read-only derived value equal to the `report_credit_allowance` minus the reserved and consumed counters. The invariant `report_credit_allowance` equals the sum of `report_credits_available`, `report_credits_reserved`, and `report_credits_consumed` holds at all times. Similarly, `activation_budget_spent_cents` accumulates the `total_fee_cents` of every activation under the contract that is not `CANCELLED`, and the contract carries a `compliance_score` that starts at 1000 and only ever decreases (see §3.7), with a floor of zero.

The contract's category coverage is expressed through category scopes. A `RetailerAdmin` adds a scope by supplying a `category_code` together with the supplier's own `brand_codes` within that category — the brand list drives both the own-brand reporting cells and the competitor blinding described in §3.2. Each scope belongs to its contract via `contract_id`.

Contract terms change through amendment. A `RetailerAdmin` amends a contract by submitting `expected_contract_version` (per §2.7) together with any of an optional new `tier`, an optional `credit_allowance_delta`, and optional `add_category_codes` or `remove_category_codes` lists. A positive or negative `credit_allowance_delta` adjusts both the `report_credit_allowance` and the `report_credits_available` by the same amount, but an amendment that would push the new allowance below the sum of already-consumed and currently-reserved credits is rejected with `ERR_ALLOWANCE_BELOW_CONSUMED` — commitments already made must remain fundable. Categories named in `remove_category_codes` delete the matching scope rows outright. Every successful amendment increments the contract's `version` by one.

Suspension is the platform's emergency brake. When a `RetailerAdmin` suspends a contract — permitted only while the contract is `ACTIVE`, otherwise `ERR_CONTRACT_NOT_ACTIVE` — the contract moves to `SUSPENDED`, its `version` increments, and a cascade runs: every insight report of the contract still in `REQUESTED` or `GENERATING` is moved to `CANCELLED` and its reserved credits are refunded to the contract (the reserved counter decreases by the cancelled report's `credit_cost`); every review deliverable backed by one of those cancelled reports and still in `PLANNED` moves to `BLOCKED`; and for each deliverable so blocked, its line review cycle's `planned_open_count` decreases by one, because that counter tracks only deliverables in `PLANNED` or `SUBMITTED`. Termination, by contrast, is a quiet end: a `RetailerAdmin` may terminate a contract from either `ACTIVE` or `SUSPENDED`; the contract moves to `TERMINATED` (its terminal state) with a version increment and no cascade.

### 3.2. Insight Reports: Reservation, Generation, Suppression, and Export

A `SupplierAnalyst` requests an insight report by naming the sponsoring `contract_id`, a `report_type` of `CATEGORY`, `BRAND_OWN`, or `COMPETITOR_BLIND`, the `category_code` to report on, and a reporting window via `period_start` and `period_end` (both ISO dates; the window is metadata — the household counting itself is driven by category membership, not by the dates). Two referential checks guard creation, evaluated in this order: first the `category_code` must be covered by one of the contract's category scopes, else the request fails with `ERR_CATEGORY_OUT_OF_SCOPE`; then the `report_type` must be permitted by the contract's tier, else `ERR_TIER_INSUFFICIENT`. The scope check precedes the tier check so that a supplier probing categories it was never granted learns nothing about tier boundaries.

Each report type carries a fixed credit cost, computed at creation and stored as `credit_cost`: a `CATEGORY` report costs one credit, a `BRAND_OWN` report costs two credits, and a `COMPETITOR_BLIND` report costs three credits. Creating the report reserves its cost against the contract — the reserved counter increases by `credit_cost` — and the reservation requires `report_credits_available` to be at least `credit_cost`, failing with `ERR_INSUFFICIENT_REPORT_CREDITS` otherwise. The report is born `REQUESTED`. A `SupplierAnalyst` may cancel a report while it is still `REQUESTED` (any other state fails with `ERR_REPORT_NOT_CANCELLABLE`); cancellation moves it to `CANCELLED` and refunds the reservation by decreasing the reserved counter by `credit_cost`.

Generation is where the panel meets the privacy threshold. A `SupplierAnalyst` triggers generation on a report in `REQUESTED` or `SUPPRESSED` — generation from any other state fails with `ERR_REPORT_NOT_GENERATABLE` — and only while the sponsoring contract is `ACTIVE`, else `ERR_CONTRACT_NOT_ACTIVE`. The system then computes the report's cells from the panel: `household_count` is the number of panel households whose `category_codes` contain the report's `category_code`; `own_brand_households` is the number of those households that have at least one `brand_metrics` entry whose `brand_code` appears in the contract scope's `brand_codes`; and, for `COMPETITOR_BLIND` reports only, `other_supplier_aggregate_households` is the remainder — the household count minus the own-brand households. The competitor side of a `COMPETITOR_BLIND` report is always this single blinded bucket; no per-competitor breakdown exists anywhere in the product. All three cell fields remain null until generation computes them. Generation also stamps the report's `redistribution_class`: `CATEGORY` reports are `SHAREABLE_AGGREGATE`, `BRAND_OWN` reports are `INTERNAL_ONLY`, and `COMPETITOR_BLIND` reports are `MODELED_DERIVED`.

Every reported cell is then tested against the minimum cell size of twenty (§2.9). If any cell falls below twenty households, the entire report moves to `SUPPRESSED` and its reserved credits are refunded in full — suppression never finalizes a charge. If all cells pass, the report moves to `READY` and the reservation finalizes: the reserved counter decreases by `credit_cost` and the consumed counter increases by the same amount. A `SUPPRESSED` report is not dead; the analyst may regenerate it (for instance after fresh panel ingest has grown the population). Regeneration from `SUPPRESSED` re-reserves the `credit_cost` on entry — again requiring sufficient `report_credits_available`, else `ERR_INSUFFICIENT_REPORT_CREDITS` — recomputes the cells, and lands in `READY` if every cell now passes or back in `SUPPRESSED` with a full refund if any still fails.

Export is the contractual red line. A `SupplierAnalyst` may export a report only from `READY` (else `ERR_INVALID_STATE`), only when the contract's `redistribution_allowed` clause is true, and — when the report's `redistribution_class` is `MODELED_DERIVED` — only when the contract's `modeled_derivation_allowed` clause is also true. A violation of either clause is rejected with `ERR_REDISTRIBUTION_RESTRICTED`. A successful export moves the report to `DELIVERED` and writes a `REPORT_EXPORTED` audit event naming the report as its subject.

### 3.3. Audience Segments: Definition, Stewardship, and Approval

A `SupplierAnalyst` builds an audience segment on a contract by providing a human-readable `segment_name`, a `category_code` that must already be in the contract's scope at creation (else `ERR_CATEGORY_OUT_OF_SCOPE`), and any combination of three optional criteria: `min_frequency`, which matches only households whose `frequency_12m` is at least that value; `min_monetary_cents`, which matches only households whose `monetary_12m_cents` is at least that value; and `region`, which matches only households whose `region` equals the criterion exactly. When a criterion is omitted, it filters nothing.

The segment's `size` is the count of panel households that satisfy every supplied criterion, computed against the full panel at creation and recomputed at every submission. The segment is born `DRAFT`.

Submission is the analyst's request for stewardship review and doubles as a freshness check: submitting recomputes `size` from the current panel, and if the recomputed size is zero the submission is refused with `ERR_SEGMENT_EMPTY` and no state change occurs. Otherwise the segment moves to `PENDING_APPROVAL`. Submission is valid from `DRAFT` and from `REJECTED` alike — a rejected segment may be revised and resubmitted — but from no other state (else `ERR_SEGMENT_NOT_SUBMITTABLE`).

Approval belongs to a `DataSteward`, never to the analyst who built the segment. The steward may approve a segment only while it is `PENDING_APPROVAL` (else `ERR_INVALID_STATE`) and only when its `size` is at least the minimum segment size of twenty-five households; a smaller segment fails approval with `ERR_SEGMENT_BELOW_MINIMUM`. Approval moves the segment to `APPROVED`. The steward may instead reject a `PENDING_APPROVAL` segment, moving it to `REJECTED` (again, any other state fails with `ERR_INVALID_STATE`). Both decisions increment the segment's `version`.

### 3.4. Segment Activations: Channel Reach, Fees, and the Measurement Window

Activation is where audience work meets money. A `SupplierAnalyst` creates an activation on a segment by submitting `expected_segment_version` (per §2.7) and a `channels` list drawn from the allowed set — `COUPON` and `RETAIL_MEDIA` — with one fee line produced per channel in the order the channels are listed. The segment must be `APPROVED` for activation creation (else `ERR_SEGMENT_NOT_APPROVED`), and its `category_code` must still be in the sponsoring contract's scope at both creation and launch time (else `ERR_CATEGORY_OUT_OF_SCOPE`) — an amendment that removed the category between approval and launch blocks the launch.

The activation's reach and fee are computed line by line from the segment's `size` snapshot at creation, and the activation is permanently linked to that segment through its system-assigned `segment_id`. For each channel line, `households_reached` is the segment size multiplied by the channel's reach rate, rounded down to a whole household: the `COUPON` channel reaches eighty percent of the segment, and the `RETAIL_MEDIA` channel reaches fifty percent. Each line's `line_fee_cents` is then the reached households multiplied by the base rate of 2.5 cents per household and by the channel multiplier — 1.0 for `COUPON` and 1.3 for `RETAIL_MEDIA` — rounded half-up to a whole cent. The rounding order is pinned: each line fee is rounded first, and `total_fee_cents` is the integer sum of the rounded line fees. Summing the raw unrounded values and rounding once is a different, forbidden algorithm; concretely, a size-37 segment activated on both channels yields line fees of 73 cents and 59 cents for a total of 132 cents, even though the raw sum is exactly 131.0 cents. The computed lines are stored as `channel_lines`, each entry recording its `channel`, `households_reached`, and `line_fee_cents`.

Creating the activation debits the sponsoring contract: `activation_budget_spent_cents` increases by `total_fee_cents`, and the create is rejected with `ERR_ACTIVATION_BUDGET_EXCEEDED` when the fee exceeds the contract's remaining activation budget (the `activation_budget_cents` less what has already been spent). The activation is born `PENDING`, and the segment's `version` increments by one because the activation pins it.

A `SupplierAnalyst` launches a `PENDING` activation — any other state fails with `ERR_ACTIVATION_NOT_LAUNCHABLE` — which moves it to `LAUNCHED`, stamps `launched_at` with the current logical clock time, and writes an `ACTIVATION_LAUNCHED` audit event. From `LAUNCHED`, the analyst may halt the activation, moving it to the terminal `HALTED` state (halting from any other state fails with `ERR_INVALID_STATE`). Alternatively, when the logical clock reaches the instant twenty-eight days after `launched_at` — the standard measurement window — the activation completes automatically, moving to the terminal `COMPLETED` state.

### 3.5. Incrementality Studies: Matched Controls and Lift Measurement

An `InsightsScientist` measures promotion incrementality by creating a study with the promoted `brand_code`, the `category_code` that restricts the treated and control pools, and a campaign window from `window_start` to `window_end` (both ISO dates). The study is born `DRAFT`.

Starting the study — permitted only from `DRAFT`, else `ERR_STUDY_INVALID_TRANSITION` — runs the matched-control selection and moves the study to `RUNNING`. The treated pool is every panel household whose `category_codes` contain the study's category and whose `exposed_brands` contain the promoted brand; the control pool is every panel household in the same category whose `exposed_brands` do not contain the brand. Matching is deterministic nearest-neighbor with one control per treated household. The distance between a treated household and a candidate control is the sum of the absolute difference of their `recency_days`, the absolute difference of their `frequency_12m`, and the absolute difference of their `monetary_12m_cents` divided by one thousand. Treated households are processed in ascending `created_at` order; each selects the not-yet-chosen control of minimum distance, breaking ties by the control's ascending `created_at`; and each control is chosen at most once. If the control pool empties before every treated household is matched, the remaining treated households are simply dropped from the pairing. The resulting pairings are stored as `matched_pairs`, each entry recording a `test_household_ref` and a `control_household_ref`.

The study stays `RUNNING` while the campaign window is open. When the logical clock reaches `window_end`, the study auto-transitions to `ANALYSIS` — evaluated lazily on study reads and transition requests (§2.5) — and the lift metrics are computed at that moment. `test_avg_spend_cents` is the mean `campaign_spend_cents` for the promoted brand across the treated households of the matched pairs, taken from each household's `brand_metrics` entry for that brand; `control_avg_spend_cents` is the same mean across the matched controls. The `provisional_lift_pct` is the raw lift: the difference of the test and control averages, divided by the control average, expressed as a percentage. The `final_lift_pct` applies a bias correction for baseline divergence: the correction is one-half of the gap between the treated households' mean `baseline_spend_cents` and the controls' mean `baseline_spend_cents` for the brand; that correction is subtracted from the spend difference before dividing by the control average and converting to a percentage. The final lift is therefore strictly smaller than the provisional lift whenever the treated group was already out-spending the controls at baseline. Both lift figures are stored rounded half-up to two decimal places.

From `ANALYSIS`, the scientist moves the study to `IN_REVIEW` for internal scrutiny (any other state fails with `ERR_STUDY_INVALID_TRANSITION`). Review has two exits. Publishing moves the study to its terminal `PUBLISHED` state. Revising sends the study back to `RUNNING` and re-runs the matched-control selection against the current panel, replacing `matched_pairs` wholesale — the revision cycle exists because panel composition drifts while a study is under review, and a stale pairing undermines the measurement. Both review exits require the study to actually be `IN_REVIEW`, else `ERR_STUDY_INVALID_TRANSITION`.

### 3.6. The Clean Room: Access Grants, Query Costing, and Suppression Refunds

Clean-room access is granted per supplier account, under segregation of duties, and always inside a time window. A `SupplierAnalyst` requests a grant by naming the `supplier_account_id`, a half-open access window from `valid_from` (inclusive) to `valid_until` (exclusive), and a `query_budget_total` of query credits. The system records the requesting analyst's `X-User-ID` as `requested_by_user_id` — this field is the segregation-of-duties anchor — and the grant is born `REQUESTED`. Access windows for the same account must not overlap: because windows are half-open, adjacency is permitted — a new window may start exactly when an existing one ends — but any true overlap with an existing `REQUESTED` or `APPROVED` grant window for the same account is rejected with `ERR_WINDOW_OVERLAP`.

A `DataSteward` dispositions the request. Approval requires the grant to be `REQUESTED` (else `ERR_GRANT_NOT_APPROVABLE`) and requires the approving steward's `X-User-ID` to differ from the grant's `requested_by_user_id` — a requester who also holds a steward credential cannot approve their own request, and the attempt is rejected with `ERR_SELF_APPROVAL_FORBIDDEN`. Approval moves the grant to `APPROVED` and writes a `GRANT_APPROVED` audit event. Denial, likewise from `REQUESTED` only, moves the grant to `DENIED`, records the steward-supplied `reason` on the grant as `denial_reason`, and writes a `GRANT_DENIED` audit event. An `APPROVED` grant may be revoked by a `DataSteward` — revocation from any other state fails with `ERR_INVALID_STATE` — moving it to `REVOKED` and writing `GRANT_REVOKED`. Separately, when the logical clock reaches `valid_until`, an `APPROVED` grant expires automatically (evaluated lazily on grant reads and on query submission), moving to `EXPIRED`.

A grant tracks its consumption through `query_budget_consumed`, the sum of the `query_cost` of its executed queries, and exposes `query_budget_remaining` as the read-only difference between `query_budget_total` and `query_budget_consumed`; the invariant that the total equals consumed plus remaining holds at all times.

Query submission is synchronous and fully audited, and each query record is linked to its governing grant through a system-assigned `grant_id`. A `SupplierAnalyst` submits a query under a grant by supplying the `dataset_joins` — the list of dataset names to join, whose breadth drives cost — and `estimated_rows`, the expected result row count. The deterministic engine always returns exactly the estimated row count, which is stored as `result_rows`. The query's `query_cost` is computed as follows. The row volume is converted to row units by dividing `estimated_rows` by one thousand and rounding up to a whole unit. The join factor is 1.0 for a single dataset and grows by 0.25 for each additional dataset joined. The tier multiplier is 1.0 when the account's single `ACTIVE` contract is `TIER_CATEGORY`, 1.25 for `TIER_BRAND`, and 1.5 for `TIER_PORTFOLIO`; the contract is resolved through the grant's supplier account. The raw cost is the product of row units, join factor, and tier multiplier; the final `query_cost` is that product rounded up to a whole credit — the ceiling is applied once, after the full multiplication — then clamped to a minimum of one credit and a maximum of one hundred credits.

The submission then passes its gates in order. The grant must be `APPROVED` (else `ERR_GRANT_NOT_QUERYABLE`) and the logical clock must be before `valid_until` (a submission at or after the window's end flips the grant to `EXPIRED` and fails with `ERR_GRANT_EXPIRED`). The `query_cost` must not exceed `query_budget_remaining` (else `ERR_INSUFFICIENT_QUERY_BUDGET`). Finally, the privacy threshold applies: if `result_rows` is at least twenty, the query lands in `EXECUTED`, the grant's `query_budget_consumed` increases by `query_cost`, and a `QUERY_EXECUTED` audit event is written. If `result_rows` is below twenty, the query lands in `SUPPRESSED` instead, and the privacy refund policy applies — the cost is charged and then immediately refunded in full, leaving `query_budget_consumed` unchanged net-net — with a `QUERY_SUPPRESSED` audit event recording the attempt. Queries that fail the grant or budget gates are `REJECTED` rather than executed. A submitted query's record is immutable thereafter; the full history of a grant's queries is its audit trail.

### 3.7. Line Review Cycles and Review Deliverables: Timing, Penalties, and Cascades

Category line reviews run on a calendar the retailer controls. A `CategoryManager` schedules a line review cycle for a `category_code` with a closed review window from `window_start` to `window_end` (both ISO dates, inclusive). The cycle's `open_at` instant is computed as fourteen days before `window_start`, and the cycle is born `SCHEDULED`. When the logical clock reaches `open_at`, the cycle auto-opens to `OPEN` (evaluated on cycle reads, deliverable creation, and deliverable submission). Cycles for the same category must be spaced: a new cycle whose window begins less than seven days after an existing non-`COMPLETED` cycle's closed window for the same category is rejected with `ERR_CYCLE_GAP_VIOLATION`.

A cycle's `planned_open_count` tracks how many of its deliverables are still in flight — specifically, the count of its review deliverables in `PLANNED` or `SUBMITTED` status. The counter starts at zero and is recomputed on every deliverable transition into or out of that set: planning a deliverable increments it; acceptance, blocking, or missing decrements it.

Within a cycle, the `CategoryManager` plans a review deliverable by naming the funding `contract_id` (compliance penalties land on this contract), the backing `insight_report_id`, and a `due_at` submission deadline; the deliverable is linked to its governing cycle through a system-assigned `cycle_id`. The deadline must fall strictly before the cycle's `window_start` — a deadline at or after the window start is rejected as `ERR_INVALID_REQUEST`. The deliverable is born `PLANNED`, and the cycle's `planned_open_count` increments.

Submission belongs to the `InsightsScientist`. A deliverable may be submitted from `PLANNED` or from `REJECTED` — resubmission after rejection is expected — and from no other state (else `ERR_DELIVERABLE_NOT_SUBMITTABLE`). Two further preconditions apply: the cycle must be `OPEN` at submission time (the lazy auto-open applies first; a still-`SCHEDULED` cycle fails with `ERR_CYCLE_NOT_OPEN`), and the backing insight report must be `READY` or `DELIVERED` (else `ERR_INVALID_STATE`) — a deliverable cannot be submitted on the strength of a report that has not finished generating. Submission moves the deliverable to `SUBMITTED` and evaluates timeliness: if the logical clock is later than `due_at`, the deliverable's `is_late` flag is set to true and the funding contract's `compliance_score` decreases by ten points — the late-submission penalty — subject to the score's floor of zero.

Review of a `SUBMITTED` deliverable belongs to the `CategoryManager` (accept or reject from any other state fails with `ERR_DELIVERABLE_NOT_REVIEWABLE`). Acceptance moves the deliverable to its terminal `ACCEPTED` state and decrements the cycle's `planned_open_count`. Rejection moves it back to `REJECTED`, from which it may be resubmitted; rejection does not decrement the counter, since the deliverable already left the in-flight set at submission.

Locking is the cycle's point of no return. A `CategoryManager` locks a cycle only from `OPEN` (else `ERR_CYCLE_NOT_LOCKABLE`), moving it to `LOCKED`. The lock cascades: every deliverable of the cycle still in `PLANNED` moves to its terminal `MISSED` state, and for each missed deliverable the funding contract's `compliance_score` decreases by twenty-five points — the missed-deliverable penalty — floored at zero, while the cycle's `planned_open_count` decrements accordingly. (Deliverables in `SUBMITTED` survive the lock and may still be accepted or rejected; the lock penalizes only work that was never submitted.) From `LOCKED`, the `CategoryManager` completes the cycle, moving it to its terminal `COMPLETED` state (any other state fails with `ERR_INVALID_STATE`).

The compliance score therefore drifts downward through two independent mechanisms — ten points per late submission and twenty-five points per missed deliverable — from its initial 1000, never below zero, and serves as the retailer's running record of a supplier's delivery discipline.

### 3.8. New-Item Forecasts: Analog Products and Supersession

An `InsightsScientist` forecasts a new item's early performance by creating a forecast under a sponsoring `contract_id`. Because a forecast is a modeled, derived data product, creation requires the contract's `modeled_derivation_allowed` clause to be true; otherwise the request fails with `ERR_MODELED_DERIVATION_FORBIDDEN`. The request names the `product_ref` of the new item, an `analogs` array of comparable established products — each entry carrying an `analog_ref`, a `similarity_score`, and the analog's `observed_week4_units` — and a `variant` of `SIMPLE_AVERAGE` or `SIMILARITY_WEIGHTED`. The analogs array must contain at least one entry.

Two projections are always computed and stored. `forecast_simple_avg_units` is the unweighted mean of the analogs' `observed_week4_units`, ignoring similarity entirely. `forecast_weighted_units` is the similarity-weighted mean: each analog's `observed_week4_units` weighted by its `similarity_score`, summed, and divided by the sum of the similarity scores — shifting the projection toward closer analogs. Both are rounded half-up to two decimal places. The `forecast_selected_units` field holds whichever projection the `variant` selects: the simple average for `SIMPLE_AVERAGE`, the weighted figure for `SIMILARITY_WEIGHTED`.

A new forecast is born `PUBLISHED`, and publication supersedes: the moment a forecast is created for a `product_ref` that already has a `PUBLISHED` forecast, the older forecast moves automatically to its terminal `SUPERSEDED` state. Only one live forecast per product reference exists at any time.

### 3.9. Panel Ingest and the Audit Surface

The panel itself is maintained by bulk ingest. A `RetailerAdmin` submits a `households` array, and the ingest is best-effort: every valid household is persisted — the panel is append-only — and every invalid item is reported back per-item. The response carries the `ingested_count` and a `rejected` array describing the items that failed validation. Each household record carries a client-supplied `household_ref` label — explicitly not unique and never used for identity decisions — a `region` code defaulting to `NA`, the `category_codes` the household transacts in (defaulting to empty), a `recency_days` count of days since the last loyalty-linked transaction (defaulting to zero), a `frequency_12m` trailing-twelve-month transaction count (defaulting to zero), a `monetary_12m_cents` trailing-twelve-month spend in cents (defaulting to zero), the `exposed_brands` the household was exposed to via promotion or coupon (defaulting to empty), and a `brand_metrics` array of per-brand entries recording each brand's `brand_code`, `baseline_spend_cents`, and `campaign_spend_cents` (defaulting to empty). Because counting, matching, and measurement all read this panel directly, a later ingest can change a report's suppression outcome on regeneration, a segment's size on resubmission, or a study's matched pairs on revision.

The audit surface closes the loop. Any authenticated role may list the audit events — the compliance log described in §2.10 — optionally filtering by `subject_type` and `subject_id`, with standard pagination. The same five roles also share read access to every entity in the system: accounts, contracts, scopes, reports, segments, activations, studies, grants, queries, cycles, deliverables, and forecasts are all readable by `RetailerAdmin`, `CategoryManager`, `InsightsScientist`, `SupplierAnalyst`, and `DataSteward` alike, since stewardship, category governance, science, and supplier self-service each depend on visibility into the others' artifacts.

## 4. Endpoint Definitions

Operations that create a new resource — a supplier account, a contract, a category scope, a report, a segment, an activation, a study, a grant, a query, a cycle, a deliverable, or a forecast — return `201 Created`. Operations that modify an existing resource or trigger a state transition return `200 OK`; the bulk panel ingest also returns `200 OK` with its per-item outcome summary. All endpoints are mounted under the `/shopper-insights` prefix.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/shopper-insights/supplier-accounts` | Create a supplier account | RetailerAdmin |
| GET | `/shopper-insights/supplier-accounts/{id}` | Get a supplier account | Any |
| GET | `/shopper-insights/supplier-accounts/{id}/subscription-contracts` | List contracts of an account | Any |
| GET | `/shopper-insights/supplier-accounts/{id}/clean-room-grants` | List clean-room grants of an account | Any |
| POST | `/shopper-insights/supplier-accounts/{id}/subscription-contracts` | Create a subscription contract (one ACTIVE contract per account) | RetailerAdmin |
| GET | `/shopper-insights/subscription-contracts/{id}` | Get a contract | Any |
| POST | `/shopper-insights/subscription-contracts/{id}/amend` | Amend tier, credit allowance, and/or category scopes (OCC on contract version) | RetailerAdmin |
| POST | `/shopper-insights/subscription-contracts/{id}/suspend` | Suspend a contract (cascades to reports, deliverables, cycle counts) | RetailerAdmin |
| POST | `/shopper-insights/subscription-contracts/{id}/terminate` | Terminate a contract | RetailerAdmin |
| POST | `/shopper-insights/subscription-contracts/{id}/category-scopes` | Add a category scope with the supplier's own brand codes | RetailerAdmin |
| GET | `/shopper-insights/subscription-contracts/{id}/category-scopes` | List scopes of a contract | Any |
| GET | `/shopper-insights/subscription-contracts/{id}/insight-reports` | List reports of a contract | Any |
| GET | `/shopper-insights/subscription-contracts/{id}/audience-segments` | List segments of a contract | Any |
| GET | `/shopper-insights/subscription-contracts/{id}/review-deliverables` | List deliverables funded by a contract | Any |
| GET | `/shopper-insights/subscription-contracts/{id}/new-item-forecasts` | List forecasts of a contract | Any |
| POST | `/shopper-insights/panel-households` | Bulk-ingest panel households (best-effort, per-item errors) | RetailerAdmin |
| POST | `/shopper-insights/insight-reports` | Request an insight report (reserves credits) | SupplierAnalyst |
| GET | `/shopper-insights/insight-reports/{id}` | Get a report | Any |
| GET | `/shopper-insights/insight-reports/{id}/review-deliverables` | List deliverables backed by a report | Any |
| POST | `/shopper-insights/insight-reports/{id}/generate` | Generate or regenerate report cells (READY or SUPPRESSED) | SupplierAnalyst |
| POST | `/shopper-insights/insight-reports/{id}/cancel` | Cancel a REQUESTED report (refund reservation) | SupplierAnalyst |
| POST | `/shopper-insights/insight-reports/{id}/export` | Export a READY report subject to redistribution clauses | SupplierAnalyst |
| POST | `/shopper-insights/audience-segments` | Create an audience segment (size computed) | SupplierAnalyst |
| GET | `/shopper-insights/audience-segments/{id}` | Get a segment | Any |
| GET | `/shopper-insights/audience-segments/{id}/activations` | List activations of a segment | Any |
| POST | `/shopper-insights/audience-segments/{id}/submit` | Submit segment for stewardship approval (recomputes size) | SupplierAnalyst |
| POST | `/shopper-insights/audience-segments/{id}/approve` | Approve a segment (segregation of duties) | DataSteward |
| POST | `/shopper-insights/audience-segments/{id}/reject` | Reject a segment | DataSteward |
| POST | `/shopper-insights/audience-segments/{id}/activations` | Create an activation on an APPROVED segment (OCC on segment version) | SupplierAnalyst |
| POST | `/shopper-insights/segment-activations/{id}/launch` | Launch a PENDING activation | SupplierAnalyst |
| POST | `/shopper-insights/segment-activations/{id}/halt` | Halt a LAUNCHED activation | SupplierAnalyst |
| POST | `/shopper-insights/incrementality-studies` | Create an incrementality study for a promoted brand | InsightsScientist |
| GET | `/shopper-insights/incrementality-studies/{id}` | Get a study (auto-transitions RUNNING to ANALYSIS at window end) | Any |
| POST | `/shopper-insights/incrementality-studies/{id}/start` | Start a study (runs matched control selection) | InsightsScientist |
| POST | `/shopper-insights/incrementality-studies/{id}/submit-review` | Move study from ANALYSIS to IN_REVIEW | InsightsScientist |
| POST | `/shopper-insights/incrementality-studies/{id}/publish` | Publish a reviewed study | InsightsScientist |
| POST | `/shopper-insights/incrementality-studies/{id}/revise` | Send study back to RUNNING and re-match controls | InsightsScientist |
| POST | `/shopper-insights/clean-room-grants` | Request a clean-room access grant | SupplierAnalyst |
| GET | `/shopper-insights/clean-room-grants/{id}` | Get a grant (lazy-expires APPROVED grants past their window) | Any |
| POST | `/shopper-insights/clean-room-grants/{id}/approve` | Approve a grant (approver must differ from requester) | DataSteward |
| POST | `/shopper-insights/clean-room-grants/{id}/deny` | Deny a grant | DataSteward |
| POST | `/shopper-insights/clean-room-grants/{id}/revoke` | Revoke an APPROVED grant | DataSteward |
| POST | `/shopper-insights/clean-room-grants/{id}/queries` | Submit an audited clean-room query (synchronous outcome) | SupplierAnalyst |
| GET | `/shopper-insights/clean-room-grants/{id}/queries` | List queries of a grant (audit trail) | Any |
| POST | `/shopper-insights/line-review-cycles` | Schedule a line review cycle for a category | CategoryManager |
| GET | `/shopper-insights/line-review-cycles/{id}` | Get a cycle (lazy auto-open at open_at) | Any |
| POST | `/shopper-insights/line-review-cycles/{id}/lock` | Lock a cycle (cascades PLANNED deliverables to MISSED) | CategoryManager |
| POST | `/shopper-insights/line-review-cycles/{id}/complete` | Complete a LOCKED cycle | CategoryManager |
| POST | `/shopper-insights/line-review-cycles/{id}/deliverables` | Plan a category review deliverable timed to a cycle | CategoryManager |
| GET | `/shopper-insights/line-review-cycles/{id}/deliverables` | List deliverables of a cycle | Any |
| POST | `/shopper-insights/review-deliverables/{id}/submit` | Submit a deliverable (late flag and penalty past due_at) | InsightsScientist |
| POST | `/shopper-insights/review-deliverables/{id}/accept` | Accept a SUBMITTED deliverable | CategoryManager |
| POST | `/shopper-insights/review-deliverables/{id}/reject` | Reject a SUBMITTED deliverable (resubmission allowed) | CategoryManager |
| POST | `/shopper-insights/new-item-forecasts` | Create a new-item forecast from analog products (supersedes prior) | InsightsScientist |
| GET | `/shopper-insights/audit-events` | List audit events (append-only compliance log) | Any |
| POST | `/shopper-insights/_clock/set_current_utc` | Set the logical clock | RetailerAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_RESOURCE_NOT_FOUND` | 404 Not Found |
| `ERR_CONTRACT_NOT_ACTIVE` | 409 Conflict |
| `ERR_ACCOUNT_HAS_ACTIVE_CONTRACT` | 422 Unprocessable Entity |
| `ERR_TIER_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_CATEGORY_OUT_OF_SCOPE` | 422 Unprocessable Entity |
| `ERR_MODELED_DERIVATION_FORBIDDEN` | 422 Unprocessable Entity |
| `ERR_SEGMENT_EMPTY` | 422 Unprocessable Entity |
| `ERR_SEGMENT_BELOW_MINIMUM` | 422 Unprocessable Entity |
| `ERR_SEGMENT_NOT_SUBMITTABLE` | 409 Conflict |
| `ERR_SEGMENT_NOT_APPROVED` | 409 Conflict |
| `ERR_SELF_APPROVAL_FORBIDDEN` | 403 Forbidden |
| `ERR_GRANT_NOT_QUERYABLE` | 409 Conflict |
| `ERR_GRANT_EXPIRED` | 409 Conflict |
| `ERR_GRANT_NOT_APPROVABLE` | 409 Conflict |
| `ERR_INSUFFICIENT_QUERY_BUDGET` | 402 Payment Required |
| `ERR_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_CYCLE_GAP_VIOLATION` | 409 Conflict |
| `ERR_CYCLE_NOT_OPEN` | 409 Conflict |
| `ERR_CYCLE_NOT_LOCKABLE` | 409 Conflict |
| `ERR_DELIVERABLE_NOT_SUBMITTABLE` | 409 Conflict |
| `ERR_DELIVERABLE_NOT_REVIEWABLE` | 409 Conflict |
| `ERR_REPORT_NOT_GENERATABLE` | 409 Conflict |
| `ERR_REPORT_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_INSUFFICIENT_REPORT_CREDITS` | 402 Payment Required |
| `ERR_ALLOWANCE_BELOW_CONSUMED` | 402 Payment Required |
| `ERR_ACTIVATION_BUDGET_EXCEEDED` | 402 Payment Required |
| `ERR_REDISTRIBUTION_RESTRICTED` | 403 Forbidden |
| `ERR_ACTIVATION_NOT_LAUNCHABLE` | 409 Conflict |
| `ERR_STUDY_INVALID_TRANSITION` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_CONTRACT_VERSION` | 412 Precondition Failed |
| `ERR_STALE_SEGMENT_VERSION` | 412 Precondition Failed |
