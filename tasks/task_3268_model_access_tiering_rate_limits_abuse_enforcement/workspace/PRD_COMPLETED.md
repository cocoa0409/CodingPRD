# Model Access Governance API — Product Requirements Document

## 1. Introduction

Operating a hosted model inference platform means deciding, continuously and defensibly, who receives how much capacity, at what price, and under which safety and conduct constraints. Commercial customers onboard under self-serve usage tiers and graduate as their payment history deepens; enterprise customers negotiate committed throughput under formal agreements; and every model version the platform exposes must pass a safety gate before broad availability, then age through a managed deprecation and sunset pipeline. At the same time, the platform carries an acceptable-use obligation: abusive tenants must be throttled, restricted, suspended, or terminated through a graduated, auditable enforcement process that includes an appeal path for accounts flagged in error.

This document specifies the Model Access Governance API, the system of record for all of the above. It covers organization onboarding and usage-tier progression, per-minute rate limiting with burst credits and request queueing, the model version lifecycle from registration through safety evaluation to deprecation and pinned-version support, usage-based invoicing with prepaid credit and batch discounts, enterprise agreements with price overrides, and graduated abuse enforcement with appeals and reinstatement. All time-driven behavior in the system — agreement expiry, model sunset, queue time-to-live, and queue admission — is evaluated against a controllable logical clock rather than wall-clock time, so that operators and tests can drive deterministic outcomes.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and invariants that apply across the entire API surface.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. A request with missing or malformed headers is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A well-authenticated request whose role is not authorized for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

The system recognizes exactly five roles: `PlatformAdmin`, `OrganizationAdmin`, `BillingContact`, `TrustAnalyst`, and `TrustLead`.

When `X-User-Role` is `OrganizationAdmin`, `X-User-ID` is the `id` of the acting Organization; ownership checks on any resource that references an Organization compare the resource's foreign-key field (such as `organization_id`) to `X-User-ID`. This is what binds, for example, an appeal filer to the accused organization. When `X-User-Role` is `PlatformAdmin`, `BillingContact`, `TrustAnalyst`, or `TrustLead`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records these identifiers on the artifacts those operators produce — for example `verdict_by` on a safety evaluation, `assigned_analyst_id` on an abuse case, `issued_by` on an enforcement action, `submitted_by` and `resolved_by` on an appeal — but never compares them to any entity's `id`.

A `PlatformAdmin` operates the platform's administrative surface: onboarding and activating organizations, registering and deprecating model versions, opening and countersigning enterprise agreements, settling payments, and driving the logical clock. Segregation of duties bars `PlatformAdmin` from judging safety verdicts or appeals. A `TrustAnalyst` opens safety evaluations and claims and works abuse cases; a `TrustLead` submits safety verdicts and resolves appeals, and must be a different user than the analyst who originated the work under judgment. A `BillingContact` performs financial operations — invoicing and payment recording — and cannot modify the model lifecycle or enforcement state.

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

List endpoints accept two query parameters. The `limit` parameter specifies the maximum number of items to return; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. A `limit` or `offset` that is not an integer, a `limit` outside the range 1–100, or a negative `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Unless otherwise specified, all list endpoints return resources sorted by creation timestamp in ascending order, with ties between equal creation timestamps broken by `id` ascending. List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. Common Resource Properties

Primary resources — Organization, ModelVersion, SafetyEvaluation, EnterpriseAgreement, QueuedRequest, Invoice, AbuseCase, and Appeal — carry a standard set of system-managed fields:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp at whole-second precision (for example `2026-09-01T00:00:00Z`), set at creation from the logical clock.
- `updated_at` (string): an ISO 8601 UTC timestamp at whole-second precision, refreshed from the logical clock on every mutation.
- `version` (integer): a system-managed integer that increments by one with every modification to the resource, starting at 1 on creation.

Event-style or append-only resources — PaymentEvent, UsageRecord, RateLimitWindow, InvoiceLine, and AbuseAction — carry only `id` and `created_at`. For these resources both `updated_at` and `version` are absent; they are never mutated after creation (PaymentEvent transitions only from `PENDING` to `SETTLED` through its settle operation, and exposes no update or delete endpoints).

### 2.5. The Logical Clock

The platform never consults wall-clock time. A single logical clock governs every temporal comparison in the system: agreement `effective_at` and `expires_at` checks, model `sunset_at` evaluation, queue time-to-live expiry, invoice period ordering, and all recorded timestamps. At server startup the logical clock reads exactly `2026-09-01T00:00:00Z`; before any operator intervention it continues to read that default and never falls back to wall-clock time.

An admin-only test-driving capability advances the logical clock to a supplied `current_utc` instant. Setting the clock re-evaluates every time-driven auto-transition in the system: enterprise agreements reaching `expires_at` expire, deprecated model versions reaching `sunset_at` sunset, queued requests older than their time-to-live expire, and queue admission is evaluated for the minute window containing the new clock reading (see §2.8). Any operation that would violate a logical-clock invariant — for example an invoice whose `period_end` does not fall strictly after its `period_start` — is rejected with `ERR_TEMPORAL_INVALID` (HTTP 422). (The analogous agreement rule, an `effective_at` that does not precede `expires_at`, is classified instead as `ERR_AGREEMENT_CONFLICT` per §3.6.)

### 2.6. Tier Framework and Rate Ceilings

Every organization operates under exactly one of five usage tiers: `TIER_1`, `TIER_2`, `TIER_3`, `TIER_4`, or `ENTERPRISE`. The tier determines the base per-minute admission ceilings applied to that organization's traffic:

- `TIER_1`: at most 50 requests per minute and at most 50,000 tokens per minute.
- `TIER_2`: at most 200 requests per minute and at most 200,000 tokens per minute.
- `TIER_3`: at most 1,000 requests per minute and at most 1,000,000 tokens per minute.
- `TIER_4`: at most 4,000 requests per minute and at most 4,000,000 tokens per minute.
- `ENTERPRISE`: the tokens-per-minute ceiling equals the agreement's `committed_tpm`; the requests-per-minute ceiling is the committed tokens-per-minute divided by an average request size of 1,000 tokens, rounded up to the next whole request.

Tier assignment is computed, never set directly, and is described in §3.1. Tier comparisons and progression thresholds are integer comparisons with inclusive boundaries — meeting a threshold exactly is sufficient.

### 2.7. Minute Windows, Burst Credits, and the Admission Test

Rate limiting is enforced against minute-aligned windows. Each window is identified by its `window_start`, an ISO 8601 UTC timestamp truncated to the minute, and is half-open: it covers the interval from `window_start` inclusive to sixty seconds later exclusive. A window is scoped to a single organization and a single model version — there is at most one window per (organization, model version, minute) combination. The window tracks `requests_used` (requests admitted so far, whether directly or by queue admission), `tokens_used` (the sum of input, output, and cached tokens admitted so far), and `burst_credits_used`.

A burst pool softens short spikes. The pool size for a window is twice the organization's effective requests-per-minute ceiling (the ceiling after any active throttle is applied — see §3.7), and it refills at each window roll. One burst credit covers exactly one request slot or one token slot. The admission test for a request carrying `r` request slots and `t` token slots is strict: the request is admitted when the window's `requests_used` plus `r` is at most the effective requests-per-minute ceiling, and the window's `tokens_used` plus `t` is at most the effective tokens-per-minute ceiling. When the base test fails but the burst pool still holds sufficient credits, the overage is covered by consuming burst credits and the request is admitted; otherwise it is rejected with `ERR_RATE_LIMITED` (HTTP 429). Because each credit covers one slot of either dimension, the number of burst credits a request needs is the larger of its request-slot overage and its token-slot overage — the request overage being `requests_used` plus `r` minus the effective requests-per-minute ceiling (zero when not over), and the token overage being `tokens_used` plus `t` minus the effective tokens-per-minute ceiling (zero when not over); the two overages are never summed.

Admission is instantaneous: the test applies to the current minute window only, with no lookback across earlier windows.

### 2.8. Request Queueing

When an organization prefers deferral over rejection, it may explicitly enqueue a request. The queue is scoped per (organization, model version) pair and is depth-bounded: an organization-model queue holds at most 100 pending items, and an enqueue attempt beyond that depth is rejected with `ERR_QUEUE_FULL` (HTTP 429). Each queued item declares the request slots (`requests_cost`) and token budget (`tokens_cost`) it will consume when admitted, each at least one.

A queued item is `QUEUED` at creation, recording its `enqueued_at` from the logical clock. Three exits exist. At each minute boundary crossed by the logical clock, a new window opens and the head-of-line item — the oldest by `enqueued_at` ascending, with ties between equal `enqueued_at` instants broken in favor of the item enqueued first — is admitted (transitioning to `ADMITTED`) while the target window can cover its declared costs under the admission test of §2.7, burst credits included; admission adds the item's costs to the window's `requests_used` and `tokens_used` (consuming burst credits when the base caps alone would not have covered them). Only the head-of-line item is considered at each such evaluation — at most one item per queue is admitted when the clock is set, and items behind it wait for a later evaluation even when residual capacity remains. An item still waiting 120 seconds after `enqueued_at` expires (transitioning to `EXPIRED`), evaluated when the clock advances past that instant. And if the organization is placed under enforcement — moving to `RESTRICTED`, `SUSPENDED`, or `TERMINATED` — every `QUEUED` item it owns is dropped (transitioning to `DROPPED`) as a cascade of the enforcement action.

### 2.9. Monetary Precision and Rounding

All monetary quantities are integer cents. Two rounding rules are pinned and must not be reordered. First, invoice line amounts are rounded individually, half-up, before any summation: each line's `amount_cents` is its `quantity` multiplied by its `rate_per_mtok_cents`, divided by one million, rounded half-up to a whole cent — and only then are the rounded line amounts summed into the invoice's `subtotal_cents`. The alternative order (summing quantities and rounding once) yields different cents and is forbidden. Second, the batch discount is computed on those already-rounded line amounts and rounded half-up exactly once more, at the invoice level only; line amounts themselves receive no further rounding. Safety scores and classifier confidences are decimal numbers compared exactly as supplied — no rounding is applied before comparison.

### 2.10. Concurrency Discipline and Validation Order

Exactly one endpoint in the system is guarded by optimistic concurrency control: issuing an enforcement action against an abuse case. That request must carry `expected_abuse_case_version`, holding the `version` of the abuse case the caller last observed. If the case's current `version` no longer matches — because another writer has advanced the case since the caller read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the caller from acting on a case state it has not seen. No other endpoint accepts a version field.

Requests are validated in a fixed priority order, and the first failing check determines the response. The order is: authentication (presence and well-formedness of the identity headers) first; role authorization second; path-resource existence third — validated left-to-right, so a missing organization surfaces as `ERR_NOT_FOUND` (HTTP 404) before any child under it is examined; request-body shape fourth — missing required fields, ill-typed values, or enum members outside the declared set yield `ERR_INVALID_REQUEST` (HTTP 400); state-machine admissibility of the requested transition fifth, with violations rejected as `ERR_INVALID_STATE` (HTTP 409); the stale-version check sixth; and only then the domain business rules — segregation of duties, model availability, organization status blocks, invoice period overlap, duplicate pending appeals, duplicate model registrations, agreement conflicts, payment amount conventions, credit sufficiency, rate-limit admission, appeal filer identity, action issuer identity and rank, and temporal invariants — each paired with its catalogue entry in §5.

## 3. Business Logic & Workflows

### 3.1. Onboarding, Payments, and Tier Progression

A `PlatformAdmin` onboards a new customer by supplying the organization's `legal_name` — immutable once recorded — and, optionally, a `pinned_model_version_id`. The pin locks the organization to a specific model version and exempts it from automatic migration at deprecation; it may be set only at creation, is immutable afterwards, and when present must reference a model version whose status is `ACTIVE` or `DEPRECATED` — a pin naming a nonexistent model version is rejected with `ERR_NOT_FOUND` (HTTP 404), and a pin naming a version in any other status is rejected with `ERR_INVALID_REQUEST` (HTTP 400). New organizations begin in `PROVISIONAL` status with all aggregates at zero: `lifetime_spend_cents` and `qualifying_payment_count` start at 0, `credit_balance_cents` starts at 0, `enterprise_agreement_id` is unset, and the computed `tier` starts at `TIER_1`.

Money enters the system through payment events, recorded by a `PlatformAdmin` or `BillingContact` with an `organization_id`, a `kind`, and a signed `amount_cents`. Three kinds exist: `PREPAID_TOPUP` and `INVOICE_SETTLEMENT` carry positive amounts; `REFUND` carries a negative amount. A zero amount is always rejected with `ERR_INVALID_AMOUNT` (HTTP 422), as is an amount whose sign violates the kind's convention. Payments are created `PENDING` and are append-only — no update or delete capability exists.

Settlement, performed by a `PlatformAdmin`, moves a payment from `PENDING` to `SETTLED` and is the moment the money becomes real. Settlement of a payment belonging to a `TERMINATED` organization is refused as an invalid state transition. On settlement, the payment's `amount_cents` is added to the organization's `lifetime_spend_cents` — refunds, being negative, subtract from it. When a settled payment's `amount_cents` is at least 1,000 cents (ten dollars), the organization's `qualifying_payment_count` increases by one; refunds never qualify, since their amounts are negative. If the payment is a `PREPAID_TOPUP`, its amount is also added to `credit_balance_cents`; if it is a `REFUND`, its (negative) amount is applied to `credit_balance_cents` as well, floored at zero — the prepaid balance may never go negative. Every settlement increments the organization's `version` and refreshes its `updated_at`.

Tier progression recomputes the organization's tier whenever `lifetime_spend_cents` or `qualifying_payment_count` changes, when an enterprise agreement activates, expires, or terminates, and when the organization itself is activated. The thresholds are cumulative and conjunctive — both the spend leg and the count leg must be met:

- `TIER_2` requires lifetime spend of at least 5,000,000 cents (fifty thousand dollars) and at least 5 qualifying payments.
- `TIER_3` requires lifetime spend of at least 25,000,000 cents (two hundred fifty thousand dollars) and at least 25 qualifying payments.
- `TIER_4` requires lifetime spend of at least 100,000,000 cents (one million dollars) and at least 100 qualifying payments.

Thresholds are inclusive, and progression is bidirectional: because refunds reduce `lifetime_spend_cents`, a recomputed tier may move down as well as up, and the recomputed value replaces the previous one. The single override is `ENTERPRISE`: while the organization holds an `ACTIVE` enterprise agreement, its tier is `ENTERPRISE` regardless of spend; when the agreement ends, the tier falls back to whatever the settled aggregates dictate.

The authoritative, persisted tier always counts only `SETTLED` payments. Fetching a single organization accepts an optional `preview` query flag: the flag counts as true when its value, case-insensitively, is `true`, `1`, or `yes`, and counts as false when absent or any other value. When `preview` is true, the returned tier is a forward-looking projection that additionally counts `PENDING` payments as if they will settle, and so may exceed the settled tier. The projected value is returned only in that preview response and is never persisted.

Activation by a `PlatformAdmin` moves an organization from `PROVISIONAL` to `ACTIVE`. Activation requires the organization to still be `PROVISIONAL` and to have at least one `SETTLED` payment on record; it triggers a tier recomputation and increments the organization's `version`. The list view over organizations supports filtering by `status`, by `tier`, by `pinned_model_version_id`, and by `enterprise_agreement_id` — the latter two giving reverse reachability along both of the organization's foreign keys. An organization's payment events are listed under the organization with filters on `status` and `kind`.

### 3.2. Model Version Lifecycle and the Safety Gate

Model versions are registered by a `PlatformAdmin` with a `model_slug` (the human model identifier, such as "claude-sonnet"), a `version_tag` (the version suffix, such as "4-5"), and a `pricing` table. The pair (`model_slug`, `version_tag`) must be unique among versions that have not reached `SUNSET`; a registration colliding with a live pair is rejected with `ERR_DUPLICATE_MODEL_VERSION` (HTTP 409). The pricing table carries three keys — `input_per_mtok_cents`, `output_per_mtok_cents`, and `cached_per_mtok_cents` — each a non-negative integer number of cents per million tokens, and the cached rate must be strictly less than the input rate. A freshly registered version is `DRAFT`, with `deprecation_announced_at`, `sunset_at`, and `safety_evaluation_id` all unset.

Before a draft version may serve general traffic it must pass the safety gate. A `TrustAnalyst` opens a safety evaluation against the draft, supplying a `capability_class` of `STANDARD`, `ELEVATED`, or `FRONTIER`. At most one evaluation may be `OPEN` for a given model version at a time; an attempt to open a second evaluation while one is `OPEN` is rejected with `ERR_INVALID_STATE` (HTTP 409). Opening the evaluation moves the model `DRAFT → GATED`, creates the evaluation with status `OPEN`, records the opening analyst's identifier on the evaluation (exposed as the `_opened_by` field) for later segregation-of-duties comparison, records the new evaluation's id in the model's `safety_evaluation_id`, and increments the model's `version`.

A `TrustLead` then submits a verdict carrying a `score`, a decimal between 0.0 and 1.0 inclusive, recorded at verdict time and unset while the evaluation is `OPEN`. The pass threshold depends on the capability class: `STANDARD` and `ELEVATED` require a score of at least 0.70, while `FRONTIER` requires a score of at least 0.90. The boundary is inclusive — a score exactly equal to the threshold passes — and the score is compared as supplied, without rounding. Segregation of duties is enforced: the verdict-submitting lead, recorded as the evaluation's `verdict_by`, must not be the user who opened the evaluation; a self-verdict is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 422). A passing verdict moves the evaluation `OPEN → PASSED` and the model `GATED → ACTIVE`, releasing it to broad availability and incrementing the model's `version`. A failing verdict moves the evaluation `OPEN → FAILED` and returns the model `GATED → DRAFT`, likewise incrementing the model's `version`; the draft may then be revised and re-evaluated by opening a fresh evaluation. Both `PASSED` and `FAILED` are terminal for the evaluation itself.

### 3.3. Deprecation, Migration Windows, and Pinned Support

When a model version is to be retired, a `PlatformAdmin` deprecates it, moving it `ACTIVE → DEPRECATED`. Deprecation stamps `deprecation_announced_at` with the current logical time and fixes `sunset_at` exactly 30 days later — a fixed migration window that is not editable afterwards — and increments the model's `version`. The model collection can be listed with filters on `status`, on `model_slug`, and on `safety_evaluation_id`, the last giving reverse reachability from an evaluation back to its model. The safety evaluations of a single model version are listed under that version with a `status` filter.

When the logical clock reaches `sunset_at`, the version auto-transitions from `DEPRECATED` to `SUNSET`, its terminal state. Access rules around deprecation depend on the consuming organization, in three branches. An organization whose `pinned_model_version_id` names the deprecated version retains pinned access indefinitely, past sunset. An organization without a pin but with at least one usage record against the version in the trailing 30 days before deprecation enters the migration window: new usage on the deprecated version is permitted until `sunset_at` and rejected after. An organization with neither a pin nor recent usage is blocked from new usage on the version immediately upon deprecation. Any attempt to record usage against a `SUNSET` version — or against a `DEPRECATED` version by an unpinned organization without recent usage — is rejected with `ERR_MODEL_UNAVAILABLE` (HTTP 422). These are the only two `ERR_MODEL_UNAVAILABLE` triggers: usage against a `DRAFT` or `GATED` version is not rejected on availability grounds (the safety gate governs release to broad availability, not the admission of individual usage records).

### 3.4. Usage Reporting and Rate-Limit Enforcement

Usage enters the system as usage records, reported by an `OrganizationAdmin` (for its own organization) or a `PlatformAdmin`. Each record names its `organization_id` and the `model_version_id` it ran against, identifies its minute window via `minute_window_start` (truncated to the minute, matching the window semantics of §2.7), and carries four non-negative counters: `requests`, `input_tokens`, `output_tokens`, and `cached_tokens` (cached input tokens, billed at the discounted cached rate). A `batch` flag, defaulting to false, marks usage that originated from the batch API; batch usage earns the batch discount at invoice time.

Reporting usage is an admission-controlled write. Before a record is created, the platform computes the organization's effective ceilings for the current window per §2.6 and §2.7 — base tier caps, enterprise overrides, and any throttle reduction — applies the admission test, and either admits the request (updating the window's `requests_used` and `tokens_used`, and consuming burst credits when the base caps alone would not have covered it) or rejects it with `ERR_RATE_LIMITED` (HTTP 429). The model-availability rules of §3.3 apply as well, and organization status gates the write entirely: a `TERMINATED` organization blocks all new usage and payments, a `SUSPENDED` organization blocks new usage, and a `RESTRICTED` organization blocks new queue admissions; violations are rejected with `ERR_ORG_STATUS_BLOCKED` (HTTP 422).

Organizations may inspect their own traffic posture through the per-organization list views: usage records filterable by `model_version_id` and by `batch`; rate-limit windows filterable by `model_version_id` and by `window_start`; and queued requests filterable by `model_version_id` and by `status`. (The `batch` filter follows the same truthy parsing as the organization `preview` flag: `true`, `1`, or `yes`, case-insensitively, select batch usage; any other value selects non-batch usage.) Usage records are also listed per model version, filterable by `organization_id` and by `batch`, for platform-side analysis.

### 3.5. Invoicing and Credit

Billing is period-based. A `BillingContact` or `PlatformAdmin` opens an invoice in `DRAFT` status for an `organization_id` over a half-open period from `period_start` inclusive to `period_end` exclusive, with `period_end` strictly after `period_start`. Periods for one organization may not overlap: the new interval is tested, closed-open, against every existing invoice for that organization, and a collision is rejected with `ERR_PERIOD_OVERLAP` (HTTP 409). The create payload may optionally include a `lines` array, which materializes the invoice's line items alongside it. Each line names the `model_version_id` being priced, a `kind` of `INPUT_TOKENS`, `OUTPUT_TOKENS`, or `CACHED_TOKENS`, a non-negative `quantity` of tokens, the `rate_per_mtok_cents` to apply, and an optional `batch` flag defaulting to false. The governing rate for a line is caller-supplied but derived: when the organization has an `ACTIVE` enterprise agreement carrying a `price_override` — a per-token price table with the same keys as model pricing — those rates govern; otherwise the model's list pricing governs. While the invoice remains `DRAFT`, its totals are unset: `subtotal_cents`, `batch_discount_cents`, and `total_cents` all read zero, and each line's `amount_cents` is null.

Finalization, performed by a `BillingContact`, is terminal and does the arithmetic. Per the pinned rounding order of §2.9, each line's `amount_cents` is computed first — quantity times rate per million tokens, rounded half-up to a whole cent — and the rounded line amounts are then summed into the invoice's `subtotal_cents`. The batch discount is then computed over exactly the lines flagged `batch`: their already-rounded amounts are summed, half of that sum is taken — the batch discount is fifty percent — and the result is rounded half-up once, at the invoice level only, yielding `batch_discount_cents`. The invoice's `total_cents` is the subtotal minus the discount, floored at zero. While the invoice is still in draft the same arithmetic may be recomputed on demand as a provisional estimate, but that value is never persisted and is not sticky: adding lines before finalization changes what the finalized discount will be.

Finally, the organization's prepaid credit is applied: `credit_balance_cents` is debited by the smaller of the invoice total and the available balance, and any remainder becomes payable. Because the debit is capped at the balance, underflow cannot occur; any implementation path that would drive `credit_balance_cents` negative is rejected with `ERR_INSUFFICIENT_CREDIT` (HTTP 422). Finalization against an organization that has reached `TERMINATED` is refused as an invalid state transition. Successful finalization moves the invoice `DRAFT → FINALIZED` and increments the invoice's `version`. Invoice lines are independently addressable: they can be listed with filters on `invoice_id` and `model_version_id` — reverse reachability along both foreign keys — and fetched individually, and an organization's invoices are listed under the organization with a `status` filter.

### 3.6. Enterprise Agreements

Enterprise customers operate under a formal agreement, drafted by a `PlatformAdmin` with an `organization_id`, a `committed_tpm` (committed tokens-per-minute throughput, which must be greater than zero), a `dedicated_capacity_pct` (the percentage of the organization's model traffic, from 1 to 100 inclusive, that must be served on dedicated capacity), an `effective_at`, an `expires_at`, and an optional `price_override`. The effective timestamp must lie strictly before the expiry timestamp, and an organization may hold at most one `ACTIVE` agreement at a time; violations of either rule are rejected with `ERR_AGREEMENT_CONFLICT` (HTTP 422). A new agreement is `DRAFT`.

Countersigning, by a `PlatformAdmin`, activates the agreement. It requires the agreement to be `DRAFT`, the organization to be `ACTIVE`, and the current logical time to fall at or after `effective_at` and strictly before `expires_at`; a countersign attempted when the agreement is not `DRAFT`, when the organization is not `ACTIVE`, or when the current logical time falls outside the effective window is rejected with `ERR_INVALID_STATE` (HTTP 409). The at-most-one-`ACTIVE`-agreement rule is re-checked at countersign time, with a conflict again rejected as `ERR_AGREEMENT_CONFLICT`. Countersigning sets the organization's `enterprise_agreement_id` to the agreement, forces the organization's tier to `ENTERPRISE` — overriding tier progression for as long as the agreement remains active — and increments the agreement's `version`. From that moment the organization's rate ceilings are the enterprise ceilings of §2.6, and its billing follows any `price_override` per §3.5.

Agreements end in two ways. When the logical clock reaches `expires_at`, an `ACTIVE` agreement auto-transitions to `EXPIRED`; the organization's `enterprise_agreement_id` is cleared, its tier is recomputed from its settled payment aggregates, and the organization's `version` increments. Alternatively, if the organization is suspended or terminated under enforcement, every `ACTIVE` agreement it holds cascades to `TERMINATED` with the same clearing and tier-recomputation effects. Both `EXPIRED` and `TERMINATED` are terminal. Agreements are listed with filters on `organization_id` and `status`, and fetched individually.

### 3.7. Abuse Detection and Graduated Enforcement

Enforcement begins with an abuse case, opened by a `PlatformAdmin` or `TrustAnalyst` against an `organization_id`, with a detection `source` of `AUTOMATED` or `MANUAL` and a `severity` of `LOW`, `MEDIUM`, `HIGH`, or `CRITICAL`. An automated case must carry a `classifier_confidence`, a decimal between 0.0 and 1.0 inclusive; for manual cases the confidence is null and ignored even if supplied. New cases are `OPEN` with `assigned_analyst_id` unset.

High-confidence automated detections escalate immediately: when an automated case is created with a `classifier_confidence` of at least 0.95, the system itself issues a `THROTTLE` action on the spot and moves the case directly `OPEN → ACTIONED`, cascading the throttle effects described below to the organization. Below that threshold the case simply remains `OPEN`, awaiting a human. The 0.95 boundary is inclusive.

A `TrustAnalyst` claims an `OPEN`, unassigned case, which moves it `OPEN → UNDER_REVIEW` and records the caller's identifier in `assigned_analyst_id`. Only the assigned analyst may then issue actions against the case — with one exception: `TrustLead` may also issue actions, and termination (below) is reserved to the lead. An action issued by anyone other than the assigned analyst, or whose requested `action_type` rank exceeds the case's severity rank, is rejected with `ERR_ACTION_NOT_PERMITTED` (HTTP 422). The graduated actions are ranked — `WARN`, then `THROTTLE`, then `RESTRICT`, then `SUSPEND`, then `TERMINATE` — and only actions whose rank is at most the case's severity rank are issuable: a `LOW` case admits only `WARN`; a `MEDIUM` case admits `WARN` and `THROTTLE`; a `HIGH` case admits `WARN`, `THROTTLE`, `RESTRICT`, and `SUSPEND` (`RESTRICT` and `SUSPEND` share the rank of `HIGH`); and only a `CRITICAL` case admits `TERMINATE` (a `CRITICAL` case admits every action). Issuing an action requires the case to be `UNDER_REVIEW`; moves the case `UNDER_REVIEW → ACTIONED`; creates the action record, stamping `issued_by` with the caller and leaving `revoked_at` null; increments the case's `version`; and is the single OCC-guarded write of §2.10 — the request must carry `expected_abuse_case_version` matching the case's current `version`, or it is rejected with `ERR_STALE_VERSION` (HTTP 412). The organizational cascade depends on the action's rank:

- `WARN` records the warning; the organization's status is unchanged.
- `THROTTLE` leaves the organization `ACTIVE` but reduces its effective rate limits — both the requests-per-minute and tokens-per-minute ceilings — to one quarter of their base values, floored, with a floor of at least one in each dimension, for as long as the action remains unrevoked. The throttle is applied to the base caps before burst-pool sizing, so the burst pool is likewise sized from the throttled ceilings.
- `RESTRICT` moves the organization `ACTIVE → RESTRICTED`, requires a case severity whose rank is at least that of `RESTRICT`, drops every `QUEUED` request the organization holds, and increments the organization's `version`. The organization must be `ACTIVE` at issuance; issuing `RESTRICT` against an organization in any other status is an inadmissible transition rejected with `ERR_INVALID_STATE` (HTTP 409).
- `SUSPEND` moves the organization `RESTRICTED → SUSPENDED`, requires a case severity of `HIGH` or `CRITICAL`, terminates every `ACTIVE` enterprise agreement the organization holds (with the clearing and tier-recomputation effects of §3.6), and increments the organization's `version`. The organization must be `RESTRICTED` at issuance; issuing `SUSPEND` against an organization in any other status is an inadmissible transition rejected with `ERR_INVALID_STATE` (HTTP 409).
- `TERMINATE` is issuable only by a `TrustLead` and only on a `CRITICAL` case; it moves the organization `ACTIVE → TERMINATED` — its terminal state — cascades every agreement in `DRAFT` or `ACTIVE` to `TERMINATED`, drops every `QUEUED` request, and increments the organization's `version`. The organization must be `ACTIVE` at issuance; issuing `TERMINATE` against an organization in any other status is an inadmissible transition rejected with `ERR_INVALID_STATE` (HTTP 409).

An organization's cases are listed under the organization with a `status` filter; each case is individually fetchable, as are its actions and its appeals.

### 3.8. Appeals and Reinstatement

An organization that believes an action was issued in error may appeal. Only an `OrganizationAdmin` may file, and only against an `ACTIONED` case, by supplying the `abuse_case_id`. The filer's identity is binding: the appeal's `submitted_by` is the caller's `X-User-ID`, and because an `OrganizationAdmin`'s identity is the organization itself, that identifier must equal the accused organization's `id` — a mismatch is rejected with `ERR_APPEAL_FORBIDDEN` (HTTP 403). At most one appeal may be `PENDING` for a case at a time; a second filing while one is pending is rejected with `ERR_APPEAL_ALREADY_PENDING` (HTTP 409).

A `TrustLead` resolves a pending appeal by granting it. The appealed action is the case's most recently created unrevoked action. Segregation of duties applies again: the resolver, recorded as the appeal's `resolved_by`, must not be the user whose `issued_by` stands on the appealed action — a self-resolution is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 422). Granting is a compound transition. The appeal moves `PENDING → GRANTED` (terminal) and its `version` increments; the appealed action is revoked, stamping its `revoked_at` with the current logical time; the case moves `ACTIONED → REINSTATED` (terminal); and the organization returns to its pre-action posture — `SUSPENDED → ACTIVE` or `RESTRICTED → ACTIVE` as applicable (an organization still `ACTIVE`, as after a `WARN` or `THROTTLE`, is left unchanged) — with its `version` incremented when its status changes. Any throttle imposed by the revoked action lifts with it, restoring the organization's base rate ceilings. A case's appeals are listed under the case with a `status` filter.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify or transition an existing resource return `200 OK`. Unless otherwise noted, both return the created or updated resource in the envelope's `data` field. The platform mounts no global URL prefix; paths below are absolute.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock and re-evaluate time-driven transitions | PlatformAdmin |
| POST | `/organizations` | Onboard a new organization in PROVISIONAL status | PlatformAdmin |
| GET | `/organizations` | List organizations; filter by status, tier, pinned model, or agreement | PlatformAdmin, TrustAnalyst, TrustLead, BillingContact, OrganizationAdmin |
| GET | `/organizations/{id}` | Fetch one organization; optional forward-looking tier preview | PlatformAdmin, TrustAnalyst, TrustLead, BillingContact, OrganizationAdmin |
| POST | `/organizations/{id}/activate` | Transition PROVISIONAL to ACTIVE; requires a settled payment | PlatformAdmin |
| GET | `/organizations/{id}/payment-events` | List payment events for an organization | PlatformAdmin, BillingContact, OrganizationAdmin |
| GET | `/organizations/{id}/usage-records` | List usage records for an organization | PlatformAdmin, BillingContact, OrganizationAdmin |
| GET | `/organizations/{id}/invoices` | List invoices for an organization | PlatformAdmin, BillingContact, OrganizationAdmin |
| GET | `/organizations/{id}/rate-limit-windows` | List rate-limit windows for an organization | PlatformAdmin, OrganizationAdmin |
| GET | `/organizations/{id}/queued-requests` | List queued requests for an organization | PlatformAdmin, OrganizationAdmin |
| GET | `/organizations/{id}/abuse-cases` | List abuse cases against an organization | PlatformAdmin, TrustAnalyst, TrustLead, OrganizationAdmin |
| POST | `/payment-events` | Record a payment event (created PENDING) | PlatformAdmin, BillingContact |
| POST | `/payment-events/{id}/settle` | Settle a PENDING payment; update aggregates and tier | PlatformAdmin |
| POST | `/model-versions` | Register a new model version in DRAFT status | PlatformAdmin |
| GET | `/model-versions` | List model versions; filter by status, slug, or evaluation | PlatformAdmin, TrustAnalyst, TrustLead, BillingContact, OrganizationAdmin |
| GET | `/model-versions/{id}` | Fetch one model version | PlatformAdmin, TrustAnalyst, TrustLead, BillingContact, OrganizationAdmin |
| POST | `/model-versions/{id}/deprecate` | Transition ACTIVE to DEPRECATED; set deprecation and sunset timestamps | PlatformAdmin |
| GET | `/model-versions/{id}/safety-evaluations` | List safety evaluations for a model version | PlatformAdmin, TrustAnalyst, TrustLead |
| GET | `/model-versions/{id}/usage-records` | List usage records against a model version | PlatformAdmin, BillingContact |
| POST | `/model-versions/{id}/safety-evaluations` | Open a safety evaluation; model DRAFT to GATED | TrustAnalyst |
| POST | `/safety-evaluations/{id}/submit-verdict` | Submit score; PASS gates release, FAIL returns model to DRAFT | TrustLead |
| POST | `/usage-records` | Report usage into a minute window; admission-controlled | OrganizationAdmin, PlatformAdmin |
| POST | `/queued-requests` | Enqueue a request; bounded by queue depth | OrganizationAdmin, PlatformAdmin |
| POST | `/invoices` | Open a DRAFT invoice over a non-overlapping period, with optional lines | BillingContact, PlatformAdmin |
| GET | `/invoice-lines` | List invoice lines; filter by invoice or model version | BillingContact, PlatformAdmin, OrganizationAdmin |
| GET | `/invoice-lines/{id}` | Fetch one invoice line | BillingContact, PlatformAdmin, OrganizationAdmin |
| POST | `/invoices/{id}/finalize` | Compute amounts, discount, totals; debit credit; terminal | BillingContact |
| POST | `/enterprise-agreements` | Open a DRAFT enterprise agreement | PlatformAdmin |
| GET | `/enterprise-agreements` | List agreements; filter by organization or status | PlatformAdmin, BillingContact, OrganizationAdmin |
| GET | `/enterprise-agreements/{id}` | Fetch one agreement | PlatformAdmin, BillingContact, OrganizationAdmin, TrustLead |
| POST | `/enterprise-agreements/{id}/countersign` | Transition DRAFT to ACTIVE; forces organization tier to ENTERPRISE | PlatformAdmin |
| POST | `/abuse-cases` | Open an abuse case; high-confidence automated cases auto-throttle | PlatformAdmin, TrustAnalyst |
| GET | `/abuse-cases/{id}` | Fetch one abuse case | PlatformAdmin, TrustAnalyst, TrustLead, OrganizationAdmin |
| POST | `/abuse-cases/{id}/claim` | Claim an OPEN case; transitions to UNDER_REVIEW | TrustAnalyst |
| POST | `/abuse-cases/{id}/actions` | Issue a graduated action; OCC-guarded | TrustAnalyst, TrustLead |
| GET | `/abuse-cases/{id}/actions` | List actions recorded on a case | PlatformAdmin, TrustAnalyst, TrustLead, OrganizationAdmin |
| GET | `/abuse-cases/{id}/appeals` | List appeals for a case | PlatformAdmin, TrustAnalyst, TrustLead, OrganizationAdmin |
| POST | `/appeals` | File an appeal against an actioned case | OrganizationAdmin |
| POST | `/appeals/{id}/grant` | Grant an appeal; revoke action, reinstate case and organization | TrustLead |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_SEGREGATION_OF_DUTIES` | 422 |
| `ERR_MODEL_UNAVAILABLE` | 422 |
| `ERR_ORG_STATUS_BLOCKED` | 422 |
| `ERR_PERIOD_OVERLAP` | 409 |
| `ERR_APPEAL_ALREADY_PENDING` | 409 |
| `ERR_DUPLICATE_MODEL_VERSION` | 409 |
| `ERR_AGREEMENT_CONFLICT` | 422 |
| `ERR_INVALID_AMOUNT` | 422 |
| `ERR_INSUFFICIENT_CREDIT` | 422 |
| `ERR_RATE_LIMITED` | 429 |
| `ERR_APPEAL_FORBIDDEN` | 403 |
| `ERR_ACTION_NOT_PERMITTED` | 422 |
| `ERR_TEMPORAL_INVALID` | 422 |
| `ERR_QUEUE_FULL` | 429 |

