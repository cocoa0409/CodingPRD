# Wholesaler Territory Agreements, Brand Equity & Draft Quality API — Product Requirements Document

## 1. Introduction

American beer distribution runs on a legally enforced three-tier chain: the brewer manufactures, an independent wholesaler distributes, and a licensed retailer sells. This document specifies the API through which a national brewer manages its wholesaler network end to end — appointing distributors to exclusive sales territories under brand equity agreements that carry contractual performance expectations, approving the resale of a distributorship from one wholesaler to another under a right of first refusal, coordinating limited-release allocations across the network, and running promotion programs — all while staying inside the regulatory guardrails that prohibit a manufacturer from controlling the retail tier.

Day-to-day product quality is as contractual as price. The same API administers the brewer's draft-quality program: field auditors record line-cleaning and keg-age evidence at on-premise accounts, repeated critical failures escalate from the account to the serving wholesaler, and point-of-sale material reaches accounts only within the annual value limits that state law imposes. Quarterly performance reviews score each wholesaler on distribution, freshness, and market share, and sub-floor scores spawn corrective plans that gate reinstatement. Throughout, the model enforces a deliberate segregation of duties on the brewer side — operations staff create, amend, and consummate; the compliance office qualifies, decides, and resolves — while wholesaler principals act only on their own records and draft auditors hold no commercial powers at all.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelope contracts, and regulatory principles that apply to every endpoint of the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. Four roles are recognized — `BrewerAdmin`, `BrewerCompliance`, `WholesalerPrincipal`, and `DraftAuditor`. A request whose headers are missing or empty, or whose role value is not one of these four, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). Beyond authentication, each endpoint admits a fixed list of roles; a caller whose role is not on that list is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403).

- `BrewerAdmin` — manufacturer operations: territory creation, the wholesaler registry, agreement creation and amendment, limited-release allocation events and locking, performance-review publication, retail-account registration, point-of-sale material issuance and voiding, promotion programs, transfer consummation, and the logical clock. When `X-User-Role` is `BrewerAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server never compares it against an entity `id`.
- `BrewerCompliance` — the manufacturer's regulatory and compliance office, deliberately segregated from `BrewerAdmin`'s creation powers: transfer qualification reviews and decisions, and corrective-plan activation and resolution. When `X-User-Role` is `BrewerCompliance`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity.
- `WholesalerPrincipal` — the principal of one specific wholesaler. When `X-User-Role` is `WholesalerPrincipal`, `X-User-ID` is the `id` of the acting `Wholesaler`; ownership checks compare the governing wholesaler field of the resource being acted upon to `X-User-ID`, and a mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). The governed operations are exactly seven: creating a transfer application (the caller must be the selling wholesaler named on the agreement), responding to a right-of-first-refusal window (the caller must be the ROFR holder named on the agreement), filing an allocation request (the caller files for itself), confirming or releasing an assignment (the caller must be the wholesaler named in the path), responding to a performance review (the caller must be the reviewed wholesaler), revising a corrective plan (the caller must be the reviewed wholesaler of the plan's review), and opting into a promotion program (the caller opts itself in).
- `DraftAuditor` — a field quality auditor who records draft-quality audits and holds no commercial powers. When `X-User-Role` is `DraftAuditor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.

Read access is shared: all four roles may call every GET endpoint in the API.

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

List endpoints accept two query parameters: `limit`, the maximum number of items to return, and `offset`, the number of items to skip. When omitted, `limit` defaults to 10 and must lie between a minimum of 1 and a maximum of 100; `offset` defaults to 0. A non-integer `limit` or `offset`, a `limit` outside that range, or a negative `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Unless otherwise specified, every list endpoint returns its resources sorted by `created_at` in ascending order, with ties keeping insertion order. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`: pagination is applied after any `status` filter, so `total_count` counts the whole filtered set rather than the page, and `has_more` is true exactly when `offset` plus the number of items returned is less than `total_count`.

### 2.4. Common Resource Properties

Every primary resource in the API carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, recording when the resource was created against the logical clock of §2.5.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): begins at 1 when the resource is created and increments by one on every mutation.

One deliberate exception exists: a draft-quality audit is immutable field evidence. It carries only `id` and `created_at` — `updated_at` and `version` are absent, because an audit is never modified after it is recorded.

### 2.5. The Logical Clock and Scheduled Sweeps

All server-recorded time in this API — creation timestamps, amendment entries, request and opt-in times, void stamps, deadline comparisons, and the calendar year that scopes the point-of-sale caps — reads from a server-side logical clock, never from wall-clock time. Before the clock has ever been set, the logical clock reads exactly `2026-09-01T00:00:00Z`. Client-supplied timestamps that the server stores — audit `conducted_at`, `line_cleaning_last_at`, and keg `filled_at` values, and promotion `starts_at`/`ends_at` — are re-rendered in the same canonical UTC form with three fractional digits.

A `BrewerAdmin`-only capability sets the logical clock to a supplied instant, given as the `to_iso8601` request field. The response reports the new `current_utc` together with three sweep counts: `rofr_lapsed_count`, `consummation_expired_count`, and `promotions_closed_count`. Setting the clock runs three time-based sweeps before those counts are computed:

- Right-of-first-refusal windows whose deadline has passed lapse: a transfer application sitting in `ROFR_OPEN` whose `rofr_deadline` is strictly before the new clock moves to `ROFR_LAPSED`.
- Approved transfers whose consummation window has run out expire: an application in `APPROVED` whose `consummation_deadline` is strictly before the new clock moves to `EXPIRED`.
- Promotion programs whose window has ended close: a program in `OPEN` whose `ends_at` is at or before the new clock moves to `CLOSED`.

Because the sweeps run as part of the clock advance, a right-of-first-refusal response or a consummation attempted after its deadline does not surface a dedicated deadline error: by the time such a request arrives, the application's state has already moved on, and the request fails the state tier with `ERR_INVALID_STATE_TRANSITION` (see §2.10).

### 2.6. Numeric Precision and Rounding

Scores and indices published by this API — the successor qualification score, the equity index, the review freshness index, and the performance composite — are rounded half-up to exactly two decimal places. One calculation pins a stricter discipline: the performance composite of §3.8 rounds each input metric to one decimal place, half-up, before the profile weights are applied, and only then rounds the weighted result to two decimals; skipping the input rounding produces different values and is non-conformant. Allocation arithmetic runs in whole cases, with proportional shares floored to integers and the remainder distributed case by case (§3.5). Monetary amounts — `purchase_price_cents`, POS `value_cents`, and the POS annual caps — are integer cents with no rounding. The portfolio concentration ratio of §3.1 is compared exactly, with a strict greater-than against its limit, so a ratio of precisely one half does not breach the rule.

### 2.7. Optimistic Concurrency Control on Agreement Amendments

Amendment is the only write in this API guarded by optimistic concurrency control. A request to amend an agreement must carry `expected_agreement_version`, a non-optional input holding the agreement `version` the client last observed. When the supplied value does not match the agreement's current `version` — because another writer has amended the agreement since the client read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from silently overwriting terms it has not observed. No other endpoint accepts a version field of any kind. Ordering matters here: the stale-version check runs immediately after the state precondition, so amending a `TERMINATED` agreement reports `ERR_AGREEMENT_NOT_ACTIVE` even when the supplied version is also stale.

### 2.8. Three-Tier Regulatory Guardrails

Three-tier law constrains what the brewer may do, and the API enforces those constraints as first-class rejections rather than policy text:

- A wholesaler holding any retail-tier ownership interest may not acquire a distributorship. Naming a buyer whose `holds_retail_interest` flag is true on a transfer application is rejected with `ERR_THREE_TIER_PROHIBITION` (HTTP 422).
- The brewer may never dictate retail price. A promotion program submitted with a `mandated_retail_price_cents` value present and non-null is rejected with `ERR_RETAIL_PRICE_MANDATE_PROHIBITED` (HTTP 422); the field must be null or absent. A program's `suggested_discount_pct` is strictly advisory on the wholesale side and is never binding on the price a retailer charges.
- Point-of-sale material is provided to retail accounts only within the annual value limits that state law sets. The cap schedule and the chargeable-value accounting live in §3.7; a grant that would breach the account's cap is rejected with `ERR_POS_VALUE_CAP_EXCEEDED` (HTTP 422).

### 2.9. Identifier Existence and Reverse Reachability

Every identifier referenced in a request path or body — territory, wholesaler, agreement, transfer application, allocation event, retail account, performance review, corrective plan, POS grant, or promotion program — must name an existing resource; an unresolvable reference is rejected with `ERR_NOT_FOUND` (HTTP 404). Where a path contains more than one identifier, identifiers are validated in a strict left-to-right order, and the first identifier that fails to resolve produces the 404. Two operations also resolve the caller's own wholesaler record — filing an allocation request (§3.5) and opting into a promotion program (§3.9); there, a `WholesalerPrincipal` whose `X-User-ID` names no registered wholesaler is likewise rejected with `ERR_NOT_FOUND`. On every other operation the principal's `X-User-ID` is only compared against a governing field, never resolved.

The entity graph is flat: foreign keys travel in request bodies rather than in nested creation paths. Reverse reachability is therefore provided through dedicated sub-resource list endpoints — agreements by territory and by wholesaler, transfer applications by agreement, retail accounts and performance reviews by wholesaler, corrective plans by review, and draft audits and POS grants by account. Each of these lists accepts the pagination parameters of §2.3, and most accept an optional `status` filter.

### 2.10. The Validation Ladder

When several checks would fail for a single request, the rejection that surfaces is the one from the earliest tier of this ladder — the tiers are evaluated in order, not as independent checks:

1. **Header context** — `X-User-ID` and `X-User-Role` are present, non-empty, and name a declared role (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`, 400).
2. **Role authorization** — the caller's role appears in the endpoint's role list (`ERR_FORBIDDEN_FOR_ROLE`, 403).
3. **Ownership** — a `WholesalerPrincipal` caller acts only where its `X-User-ID` equals the governing wholesaler id (`ERR_NOT_RESOURCE_OWNER`, 403). Where the governing field lives on a resource the request names, that resource is resolved first, so an unresolvable identifier surfaces the tier-5 `ERR_NOT_FOUND` before any ownership comparison can run; where ownership rides on a path parameter itself (the assignment-decision `wholesalerId`), it is checked before any resource lookup.
4. **Body well-formedness** — required fields are present, types and enum members are valid, and unknown fields are rejected (`ERR_INVALID_REQUEST`, 400).
5. **Existence** — every referenced identifier resolves, path identifiers left to right (`ERR_NOT_FOUND`, 404).
6. **State preconditions** — the target resource sits in a state from which the requested transition exists, terminal-state lockdown included. The domain state rejections live in this tier alongside the generic `ERR_INVALID_STATE_TRANSITION` (all 409): `ERR_TERRITORY_NOT_VACANT` (agreement creation on an `AWARDED` territory), `ERR_AGREEMENT_NOT_ACTIVE` (amendment or transfer creation on a `TERMINATED` agreement), `ERR_ACCOUNT_NOT_ACTIVE` (POS issuance to a `SERVICE_SUSPENDED` account), `ERR_WHOLESALER_NOT_ELIGIBLE` (a wholesaler in the wrong lifecycle state for the operation, `SUSPENDED` included), `ERR_REVIEW_NOT_ACKNOWLEDGED` (plan activation before the parent review is `ACKNOWLEDGED`), `ERR_ROFR_WINDOW_OPEN` (a transfer decision while the ROFR window is unresolved), and `ERR_OPT_IN_WINDOW_CLOSED` (opt-in on a non-`OPEN` program).
7. **Three-tier prohibitions** — a retail-interest transfer buyer (`ERR_THREE_TIER_PROHIBITION`, 422) and a mandated retail price (`ERR_RETAIL_PRICE_MANDATE_PROHIBITED`, 422).
8. **Uniqueness, overlap, and structural caps** — one pending transfer per agreement (`ERR_TRANSFER_ALREADY_PENDING`, 409); one review per wholesaler per quarter (`ERR_DUPLICATE_REVIEW`, 409); one request per wholesaler per allocation event (`ERR_DUPLICATE_REQUEST`, 409); one opt-in per wholesaler per program (`ERR_DUPLICATE_OPT_IN`, 409); non-overlapping promotion windows per brand (`ERR_PROMOTION_WINDOW_OVERLAP`, 409); a window end strictly after its start (`ERR_INVALID_WINDOW`, 422); the event brand inside the acting wholesaler's agreement scope (`ERR_BRAND_SCOPE_MISMATCH`, 422); a valid, distinct ROFR holder (`ERR_ROFR_HOLDER_CONFLICT`, 422); and the portfolio concentration cap (`ERR_PORTFOLIO_CONCENTRATION_EXCEEDED`, 409).
9. **Temporal separation** — the seven-day minimum spacing between accepted audits on a single account (`ERR_AUDIT_TOO_SOON`, 409).
10. **Fiscal caps** — the POS annual value cap (`ERR_POS_VALUE_CAP_EXCEEDED`, 422).

Concretely: a POS grant that would both target a suspended account and breach the value cap is reported as `ERR_ACCOUNT_NOT_ACTIVE`, never as the cap error, because the state tier outranks the fiscal tier. Likewise, a transfer application that names a retail-interest buyer for an agreement already carrying a pending transfer reports `ERR_THREE_TIER_PROHIBITION`, because the three-tier tier is evaluated before the uniqueness tier.

## 3. Business Logic & Workflows

The sections below walk the network's working life — from opening a market, through transfers, allocations, field quality, and scorecards, to promotional windows — with each rule stated where it naturally applies.

### 3.1. Opening a Market: Territories, Wholesalers, and Appointment

A `BrewerAdmin` opens a new market by registering a territory with a display `name` and the `state_code` of the state whose law governs it — conventionally a two-letter code, stored as supplied with no format validation. Every territory is born `VACANT`, with `incumbent_wholesaler_id` null, waiting for its first appointment.

Wholesalers enter the network through the registry. A `BrewerAdmin` records the applicant's `legal_name`, its `home_state`, and its state-issued `license_number`; assigns a performance `tier` of `GOLD`, `SILVER`, or `BRONZE` — a label that later weighs limited-release allocations (§3.5); flags whether the firm `holds_retail_interest`, true when the wholesaler holds any retail-tier ownership interest and defaulting to false; and captures three qualification inputs scored from 0 to 100 — `financial_capacity_score`, `warehouse_capacity_score`, and `market_coverage_score`, accepted as integers with no range check enforced — which the successor-qualification review of §3.3 consumes. The registry also keeps the wholesaler's `supplier_book`, its book of competing suppliers, defaulting to an empty list; each entry names a `supplier_name`, classifies it by `supplier_type` as `CRAFT`, `IMPORT`, or `DOMESTIC_PREMIUM`, and may stamp the `added_at` date (optional), and an entry failing the name or type shape is rejected with `ERR_INVALID_REQUEST`. A registered wholesaler is born `APPLICANT` with a `suspended_account_count` of zero.

Appointment itself happens through the brand equity agreement. A `BrewerAdmin` appoints a wholesaler to a territory by supplying the `territory_id` and `wholesaler_id`, the `brand_scope` listing the brand codes the wholesaler is authorized to distribute, a `weighting_profile` of `STANDARD` or `SHARE_TILTED` (defaulting to `STANDARD`, and selecting between the two performance-composite weight sets of §3.8), the contractual performance expectations `distribution_target_pct`, `freshness_target_index`, and `share_target_pct`, the wholesaler-declared metrics `declared_distribution_pct`, `declared_freshness_index`, and `declared_share_pct` that feed the provisional equity index of §3.2, and the agreement's `term_years`. An optional `rofr_holder_wholesaler_id` names another wholesaler holding a right of first refusal over any future transfer of this award; when omitted, no ROFR attaches. The agreement is born `ACTIVE` at `version` 1.

Four gates stand in front of creation. The territory must still be `VACANT` — appointing onto an `AWARDED` territory is rejected with `ERR_TERRITORY_NOT_VACANT`. The candidate wholesaler must be an `APPLICANT` or already `APPOINTED`; a `SUSPENDED` or `TERMINATED` wholesaler cannot take an appointment and is rejected with `ERR_WHOLESALER_NOT_ELIGIBLE`. A named ROFR holder must differ from the appointed wholesaler and must reference an existing, non-`TERMINATED` wholesaler, else the creation fails with `ERR_ROFR_HOLDER_CONFLICT`. Finally, the portfolio concentration rule keeps a craft-and-import house from quietly absorbing the brewer's book: counting the `supplier_book` entries typed `CRAFT` or `IMPORT` as competing entries, the appointment is rejected with `ERR_PORTFOLIO_CONCENTRATION_EXCEEDED` when the book holds at least four competing entries and either the book contains no entries at all or the competing entries make up strictly more than half of all entries. Because the ratio comparison is a strict greater-than, exactly four competing entries among eight total — a ratio of precisely one half — is permitted.

Two cascades fire on a successful appointment. The territory moves `VACANT` → `AWARDED`, and its `incumbent_wholesaler_id` is set to the appointed wholesaler. And when this agreement is the wholesaler's first `ACTIVE` agreement, the wholesaler itself moves `APPLICANT` → `APPOINTED`.

### 3.2. Living Agreements: Amendment and the Equity Index

Terms evolve over the life of an agreement, and amendment is an in-place update performed by a `BrewerAdmin`: any subset of `distribution_target_pct`, `freshness_target_index`, `share_target_pct`, `declared_distribution_pct`, `declared_freshness_index`, `declared_share_pct`, `brand_scope`, `weighting_profile`, `term_years`, and `rofr_holder_wholesaler_id` may be supplied, and only the supplied fields change. Every amendment request must carry `expected_agreement_version` under the optimistic-concurrency rule of §2.7 — a supplied version that no longer matches is rejected with `ERR_STALE_VERSION`, while amending a `TERMINATED` agreement is rejected with `ERR_AGREEMENT_NOT_ACTIVE`. On success, the agreement's initially empty `amendment_log` gains an entry recording `amended_at` — read from the logical clock — together with the `fields_changed`, listed in the order the amendable fields are enumerated above; the agreement's `version` increments by one and its status remains `ACTIVE`. Amendment applies the supplied values as they stand: the ROFR-holder gate of §3.1 guards creation only, so an amended `rofr_holder_wholesaler_id` is stored without re-validation.

The equity index is a computed read, never persisted: each request recomputes it from current data. A `variant` query parameter selects the recipe; any value other than `PROVISIONAL` or `AUDITED` is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Under the default `PROVISIONAL` variant, the three components are the agreement's own declared metrics — `declared_distribution_pct`, `declared_freshness_index`, and `declared_share_pct` — and the response's `components_source` reads `DECLARED`. Under the `AUDITED` variant, the components come instead from the latest performance review of the agreement's wholesaler — latest by `period_year` and then `period_quarter`, in any review status: that review's `distribution_pct`, `freshness_index`, and `share_pct` become the components and `components_source` reads `LATEST_REVIEW`. When the wholesaler has no performance review at all, the audited index cannot be computed: `equity_index` is null, the three component fields are likewise null, and `components_source` reads `NO_REVIEW`.

Either way, the index itself is the same weighted blend: one-half of the distribution component, plus three-tenths of the freshness component, plus one-fifth of the share component, rounded half-up to two decimal places. The response reports the `variant` used, the `equity_index`, the three resolved components `distribution_component`, `freshness_component`, and `share_component`, and the `components_source`.

### 3.3. Selling the Distributorship: Application and Successor Qualification

A distributorship changes hands through a transfer application, initiated by the seller: a `WholesalerPrincipal` whose `X-User-ID` equals the wholesaler currently named on the agreement — anyone else is rejected with `ERR_NOT_RESOURCE_OWNER`. The application carries the `agreement_id` of the agreement whose territory award is being transferred, the `buyer_wholesaler_id` of the candidate successor, and the agreed `purchase_price_cents` in integer cents. At creation the application is born `SUBMITTED`, and its `seller_wholesaler_id` is copied from the agreement's `wholesaler_id`.

Three gates stand in front of submission. The referenced agreement must be `ACTIVE` — a transfer on a `TERMINATED` agreement is rejected with `ERR_AGREEMENT_NOT_ACTIVE`. The buyer must be an `APPLICANT` wholesaler holding no retail-tier interest: an ineligible lifecycle state draws `ERR_WHOLESALER_NOT_ELIGIBLE`, while a buyer whose `holds_retail_interest` is true draws the three-tier rejection `ERR_THREE_TIER_PROHIBITION`. And only one application per agreement may be in flight: when another application for the same agreement sits in `SUBMITTED`, `QUALIFIED`, `ROFR_OPEN`, `ROFR_EXERCISED`, `ROFR_WAIVED`, `ROFR_LAPSED`, or `APPROVED`, the new one is rejected with `ERR_TRANSFER_ALREADY_PENDING`. Separately, while a wholesaler is `SUSPENDED` it may not initiate a transfer as seller at all (§3.6).

Qualification review belongs to `BrewerCompliance`. The review computes the successor qualification score from the buyer's registry record — one-half of the buyer's `financial_capacity_score`, plus three-tenths of the `warehouse_capacity_score`, plus one-fifth of the `market_coverage_score`, the total rounded half-up to two decimal places — and stores it on the application as `qualification_score`. What happens next depends on the score and on the agreement. A score of at least 70.00 qualifies the buyer, and the threshold is inclusive, so exactly 70.00 qualifies: the application moves `SUBMITTED` → `QUALIFIED` when the agreement names no ROFR holder, with `rofr_deadline` remaining null, or `SUBMITTED` → `ROFR_OPEN` when it does, setting `rofr_deadline` to the logical clock plus 30 days. A score below 70.00 moves the application `SUBMITTED` → `REJECTED`, a terminal state, with the computed score still stored.

### 3.4. Right of First Refusal, Decision, and the Consummation Cascade

While an application sits in `ROFR_OPEN`, the right of first refusal belongs to the wholesaler named as the agreement's `rofr_holder_wholesaler_id`, read afresh from the agreement at each step — an amendment swapping the holder mid-flight binds the later steps. That wholesaler's principal — whose `X-User-ID` must equal the ROFR holder's id, else `ERR_NOT_RESOURCE_OWNER` — answers with a `decision` on or before the `rofr_deadline`: `EXERCISE` moves the application to `ROFR_EXERCISED`, and `WAIVE` moves it to `ROFR_WAIVED`. Silence has its own outcome: when the logical clock is set strictly past the deadline, the sweep of §2.5 moves the application to `ROFR_LAPSED`, and a response arriving late meets an already-moved state machine and is rejected with `ERR_INVALID_STATE_TRANSITION`.

The transfer decision itself rests with `BrewerCompliance`, acting on an application in `QUALIFIED`, `ROFR_WAIVED`, `ROFR_LAPSED`, or `ROFR_EXERCISED`, with a `decision` and an optional `reason`. One state is explicitly out of bounds: deciding while the ROFR window is still unresolved — the application sits in `ROFR_OPEN` — is never permitted, and the attempt is rejected with `ERR_ROFR_WINDOW_OPEN`. An `APPROVE` decision moves the application to `APPROVED` and fixes the succession: `successor_wholesaler_id` becomes the agreement's ROFR holder when the application arrived via `ROFR_EXERCISED`, and the `buyer_wholesaler_id` when it arrived from `QUALIFIED`, `ROFR_WAIVED`, or `ROFR_LAPSED`; the `consummation_deadline` is set to the logical clock plus 60 days. A `REJECT` decision from any of those four states moves the application to the terminal `REJECTED` state, recording the supplied reason as `decision_reason`.

Consummation is the closing act, performed by a `BrewerAdmin` on an `APPROVED` application no later than its `consummation_deadline`. The successor must not be `TERMINATED` at that point — a terminated successor is rejected with `ERR_WHOLESALER_NOT_ELIGIBLE`. A consummated application lands in the terminal `CONSUMMATED` state and fires the reassignment cascade:

- The referenced agreement moves `ACTIVE` → `TERMINATED`.
- The territory of that agreement stays `AWARDED`, but its `incumbent_wholesaler_id` is swapped to the `successor_wholesaler_id`.
- A brand-new agreement is created for the territory and the successor, copying the old agreement's `brand_scope`, `weighting_profile`, all three performance targets, all three declared metrics, and `term_years`; it carries no ROFR holder (`rofr_holder_wholesaler_id` null) and is born `ACTIVE` at `version` 1.
- When this new agreement is the successor's first `ACTIVE` agreement, the successor moves `APPLICANT` → `APPOINTED`.
- The seller is re-evaluated: when it now holds zero remaining `ACTIVE` agreements, it moves `APPOINTED` → `TERMINATED`, and every `PENDING` allocation assignment naming the seller is released — `pending_qty` decreases and `released_qty` increases by each released assignment's `assigned_qty` (§3.5).

If the clock passes the consummation deadline first, the sweep expires the application — `APPROVED` → `EXPIRED` — and consummation is no longer possible; a late attempt fails the state tier with `ERR_INVALID_STATE_TRANSITION`.

### 3.5. Limited Releases: Requests, the Waterfall, and Assignment Decisions

For a limited release, a `BrewerAdmin` opens an allocation event naming the `brand_code` being released and the `total_qty_cases` available for assignment. Two tuning knobs ride along: `min_guarantee_cases`, the per-wholesaler minimum guarantee used in the first phase of the waterfall, defaulting to 100 cases; and `territory_cap_pct`, the largest share of `total_qty_cases` any single wholesaler may be assigned, defaulting to 0.40. The event is born `OPEN`, with `requests` and `assignments` empty, `committed_qty`, `pending_qty`, and `released_qty` all at zero, and `unassigned_remainder` null until lock.

While the event is `OPEN`, a `WholesalerPrincipal` files a request carrying a `requested_qty_cases`; the requester is the caller itself, so the recorded `wholesaler_id` is the caller's `X-User-ID`. The wholesaler must be `APPOINTED` — an `APPLICANT`, `SUSPENDED`, or `TERMINATED` requester is rejected with `ERR_WHOLESALER_NOT_ELIGIBLE` — and the event's brand must appear in the `brand_scope` of one of the requester's `ACTIVE` agreements, else `ERR_BRAND_SCOPE_MISMATCH`. Each wholesaler files at most one request per event: a second request is rejected with `ERR_DUPLICATE_REQUEST`. An admitted request is appended to the event with its `requested_qty_cases` and a logical-clock `created_at`, and the `201 Created` response carries the updated parent event.

Locking the event is a `BrewerAdmin` action that requires at least one eligible request; locking an empty event is rejected with `ERR_INVALID_STATE_TRANSITION`. At lock, the waterfall treats every recorded request as eligible — each was admitted only while the event was `OPEN`, by an `APPOINTED` wholesaler whose `ACTIVE` agreement scope contains the event's brand, and ineligible requests were refused at request time. The waterfall then runs in two phases.

Before the phases begin, a per-request cap is computed for every request: the event's `territory_cap_pct` multiplied by `total_qty_cases`, floored to a whole number of cases. Phase one, the guarantee phase, assigns each request the smallest of three quantities: the number of cases it requested, the event's `min_guarantee_cases`, and its cap.

Phase two distributes what remains, iteratively. Call the unallocated pool P: `total_qty_cases` minus the sum of everything assigned so far. A pass repeats until the pool is empty or no request has remaining capacity, where a request's remaining capacity is the smaller of its requested quantity and its cap, minus what it has already been assigned. Within a pass, each request that still has capacity is given a weight equal to its remaining capacity multiplied by its wholesaler's tier multiplier — 1.2 for `GOLD`, 1.0 for `SILVER`, 0.8 for `BRONZE` — and those weights are fixed for the duration of the pass. Each such request is then granted the smaller of two quantities: the pool multiplied by its own weight and divided by the sum of all weights, floored to whole cases; or its remaining capacity. A request whose weight is zero is granted nothing in this step. The granted cases are added to each request's running assignment.

A proportional pass usually leaves a remainder — the pool minus the sum of the grants. That remainder is distributed by cycling through the requests that still have capacity, in order of weight descending with ties broken by the request's `created_at` ascending (requests filed at the same clock instant keep their filing order), granting exactly one case per visit, until the remainder is exhausted or no capacity remains anywhere. The pool is then recomputed as `total_qty_cases` minus the sum of all assigned quantities, and the next pass begins.

When the waterfall completes, the `assignments` array is materialized: each entry records the requesting `wholesaler_id`, the `tier_snapshot` — the wholesaler's tier captured at lock — the `requested_qty_cases`, and the `assigned_qty`, and starts in `PENDING` status. The event's `unassigned_remainder` — `total_qty_cases` minus the sum of all assigned cases — and its `pending_qty` — the sum of assigned cases, equal to the whole assigned volume at this moment — are computed and frozen at lock, while `committed_qty` and `released_qty` remain at zero. The event itself has moved `OPEN` → `LOCKED`.

Once an event is `LOCKED` — and even after it has `CLOSED` — the wholesaler named by the path's `wholesalerId` parameter, which must equal the caller's `X-User-ID`, decides its own assignment with a `decision`. `CONFIRM` moves a `PENDING` assignment to `CONFIRMED`: `pending_qty` decreases by the assignment's `assigned_qty`, and `committed_qty` increases by the same amount. `RELEASE` moves an assignment from `PENDING` or `CONFIRMED` to `RELEASED`: `released_qty` increases by the assigned quantity, and `pending_qty` or `committed_qty` decreases accordingly. Both decisions remain legal while the event is `LOCKED` or `CLOSED`. When a decision leaves no `PENDING` assignments — `pending_qty` has reached zero — the event moves `LOCKED` → `CLOSED`. A conservation invariant holds after every decision: `committed_qty`, `pending_qty`, `released_qty`, and `unassigned_remainder` always sum to `total_qty_cases`.

Two lifecycle events release a wholesaler's pending work across all events. When a wholesaler is suspended under the draft-quality cascade of §3.6, or terminated as the seller at consummation under §3.4, every `PENDING` assignment naming that wholesaler becomes `RELEASED`: `released_qty` increases by each released assignment's `assigned_qty`, and `pending_qty` decreases by the same amounts. Within each affected event, such a cascade release changes only assignment statuses and the quantity ledger; the event's own `status` is not affected — the `LOCKED` → `CLOSED` transition occurs only in response to an assignment decision, never as part of a cascade.

### 3.6. Draft Quality in the Field: Audits and Service Suspension

Retail accounts are the bars and restaurants a wholesaler serves. A `BrewerAdmin` registers an account with its `name`, the `state_code` that will select its point-of-sale value cap (§3.7), the `serving_wholesaler_id` of the wholesaler servicing it, and an optional `line_cleaning_frequency_days` — the required draft-line cleaning frequency in days, defaulting to 14. An account is born `ACTIVE`.

Quality evidence arrives through the `DraftAuditor`, who records an audit with the `account_id`, the `conducted_at` timestamp of the visit, the account's `line_cleaning_last_at`, and the `kegs` found on tap — each keg described by its `brand_code`, its `filled_at`, and its `volume_bbl`. From this evidence the audit computes its findings. Every keg's age is measured in whole days: the number of complete 86400-second days between `filled_at` and `conducted_at`, discarding any partial day. A keg aged at least 90 days is stale; a keg aged at least 120 days is critical. The audit's `stale_keg_count` counts the kegs aged at least 90 days, and its `critical_keg_flag` is true when any keg on tap is critical. Line cleaning is measured the same way, as the whole-day gap between `line_cleaning_last_at` and `conducted_at`: the audit's `line_cleaning_overdue` is true when that gap strictly exceeds the account's `line_cleaning_frequency_days`, and the cleaning is critically overdue when the gap exceeds twice that frequency. From these measurements the audit derives its `result`: `CRITICAL_FAIL` when a critical keg or a critically overdue cleaning is present; otherwise `FAIL` when at least one keg is stale or the cleaning is overdue; otherwise `PASS`.

Audits on one account are spaced apart. A new audit is rejected with `ERR_AUDIT_TOO_SOON` (HTTP 409) when its `conducted_at` falls less than seven days — 604800 seconds — after the account's previous accepted audit; a gap of exactly 604800 seconds is allowed, while a gap of 604799 seconds is rejected. The anchor for this spacing is the account's `last_audit_at`, which is null until the account's first accepted audit and thereafter carries the `conducted_at` of the most recent accepted audit; audits that fail — a `FAIL` or `CRITICAL_FAIL` result — do not update it.

Results move the account. A `CRITICAL_FAIL` on an `ACTIVE` account moves it `ACTIVE` → `SERVICE_SUSPENDED` and adds one to the serving wholesaler's `suspended_account_count`; POS grants to the account are rejected with `ERR_ACCOUNT_NOT_ACTIVE` while the suspension stands (§3.7). When that increment leaves an `APPOINTED` wholesaler's count at three or more — in the common flow, taking it from 2 to 3 — the cascade continues up one level: the wholesaler moves `APPOINTED` → `SUSPENDED`, every `PENDING` allocation assignment naming it is released per §3.5, and while `SUSPENDED` its allocation requests, its transfer applications as seller, its appointment to new agreements, and its promotion opt-ins are all rejected with `ERR_WHOLESALER_NOT_ELIGIBLE`. A later `PASS` on a `SERVICE_SUSPENDED` account restores it `SERVICE_SUSPENDED` → `ACTIVE` and subtracts one from the count — but the wholesaler's own status is not restored by field evidence alone. Reinstatement requires a `VERIFIED` corrective plan (§3.8).

### 3.7. Point-of-Sale Material Within State-Law Value Limits

Signage, glassware, and other point-of-sale material flow to accounts as POS grants, issued by a `BrewerAdmin` with the `account_id`, an `item_description`, and the material's `value_cents` in integer cents. A grant is born `ISSUED`, and its `granted_year` is set to the calendar year of the logical clock at issuance — that year scopes the annual cap below.

State law caps how much free material an account may receive in a calendar year. An account's chargeable year-to-date value is the sum of `value_cents` over its grants that are still `ISSUED` and whose `granted_year` equals the current logical-clock year. A new grant is allowed only when that running total plus the new grant's `value_cents` does not exceed the cap selected by the account's `state_code`: 30000 cents for Texas, 25000 cents for California, and 20000 cents for every other state. The cap is inclusive — a grant that lands the running total exactly on the cap is accepted, while one cent beyond it is rejected with `ERR_POS_VALUE_CAP_EXCEEDED`. Grants to a `SERVICE_SUSPENDED` account are refused outright with `ERR_ACCOUNT_NOT_ACTIVE`, independent of the cap.

A `BrewerAdmin` may void an `ISSUED` grant, moving it `ISSUED` → `VOIDED` and stamping `voided_at` from the logical clock. A voided grant stops counting toward the account's chargeable year-to-date value — voiding can therefore reopen headroom under the cap — while the lifetime granted value on record is unchanged.

### 3.8. Quarterly Scorecards and the Corrective-Plan Loop

Performance is measured quarterly. A `BrewerAdmin` publishes a review for a wholesaler by supplying the `wholesaler_id`, the `period_year`, the `period_quarter` — one of `Q1`, `Q2`, `Q3`, or `Q4` — and the measured `distribution_pct` and `share_pct` for the period. The wholesaler must be `APPOINTED` or `SUSPENDED`; publishing against an `APPLICANT` or `TERMINATED` wholesaler is rejected with `ERR_WHOLESALER_NOT_ELIGIBLE`. One review per wholesaler per period: a second review for the same `wholesaler_id`, `period_year`, and `period_quarter` is rejected with `ERR_DUPLICATE_REVIEW`. A review is born `PUBLISHED`.

Two quantities are computed at creation, and both are stored on the review. First, the `freshness_index` pools the draft-quality evidence: across all audits of accounts served by the wholesaler whose `conducted_at` falls inside the calendar quarter identified by `period_year` and `period_quarter` — inclusive of both window endpoints — sum the `volume_bbl` of every keg into a total volume, and sum the `volume_bbl` of every keg that was stale at its audit (aged at least 90 days, per §3.6) into a stale volume. When there are no audits in the window, or the pooled total volume is zero, the index is 100.00; otherwise it is one hundred minus one hundred times the stale volume divided by the total volume, rounded half-up to two decimal places.

Second, the `composite_score` blends the period's three metrics under a pinned rounding order, and the order is mandatory. Step one: round each of the three inputs — `distribution_pct`, `freshness_index`, and `share_pct` — to one decimal place, half-up. Step two: combine the three rounded values at full intermediate precision using the profile weights. Step three: round the weighted sum half-up to two decimal places to produce the `composite_score`. Rounding each metric before weighting is required; rounding only the final sum produces different values and is non-conformant. The weight set is chosen by the review's `weighting_profile_snapshot`, which copies the `weighting_profile` of the wholesaler's `ACTIVE` agreement at the moment the review is created — the earliest-created one when several are active, and `STANDARD` when the wholesaler holds no `ACTIVE` agreement at all — so later amendments never reweight a published review: under `STANDARD`, the weights are 0.40 for distribution, 0.30 for freshness, and 0.30 for share; under `SHARE_TILTED`, they are 0.25 for distribution, 0.25 for freshness, and 0.50 for share — the same inputs yield a different composite under the two profiles.

When the `composite_score` lands below the corrective floor of 70.00, the review automatically spawns a `CorrectivePlan` — unless the wholesaler holds no `ACTIVE` agreement at review-creation time, in which case no plan is spawned, there being no agreement targets to snapshot: the plan's `review_id` references the spawning review, its status is `PROPOSED`, its `revision_count` is zero, and its `target_snapshot` copies the agreement targets in force when the plan was created.

The reviewed wholesaler then responds. The caller's `X-User-ID` must equal the review's `wholesaler_id`, else `ERR_NOT_RESOURCE_OWNER`. Responding to a `PUBLISHED` review with `action` `ACKNOWLEDGE` moves it to `ACKNOWLEDGED`; responding with `action` `DISPUTE` moves it to `DISPUTED` and requires a `dispute_reason` to be present and non-empty — a dispute without one is rejected with `ERR_INVALID_REQUEST`. Both outcomes are terminal for the review.

The plan lifecycle belongs to `BrewerCompliance`, with one exception. Activation moves a `PROPOSED` plan to `ACTIVE`, but only once the plan's parent review — reached through its `review_id` — is `ACKNOWLEDGED`; while the review is still `PUBLISHED` or has been `DISPUTED`, activation is rejected with `ERR_REVIEW_NOT_ACKNOWLEDGED`. Resolution moves an `ACTIVE` plan to its outcome, supplied as `outcome` with optional `resolution_notes`, which are recorded either way: `VERIFIED` is terminal, and when the reviewed wholesaler is `SUSPENDED` at that moment, it is reinstated `SUSPENDED` → `APPOINTED` and may once again request allocations, opt into promotions, and be appointed to new agreements; `FAILED` leaves the plan in `FAILED`. The exception is revision: the reviewed wholesaler itself — ownership-checked against the review's wholesaler — may resubmit a `FAILED` plan, moving it `FAILED` → `PROPOSED` for another round while its `revision_count` increments by one. The cycle may repeat: propose, activate, resolve, revise.

### 3.9. Promotion Programs Under Three-Tier Limits

Promotion support runs through time-boxed programs. A `BrewerAdmin` creates a program with the `brand_code` it supports, a `starts_at` and an `ends_at` bounding its window, a `suggested_discount_pct` advising wholesalers on the discount the brewer suggests, and — almost never — a `mandated_retail_price_cents`. The window is half-open: `starts_at` is inclusive and `ends_at` is exclusive. The end must be strictly after the start, else creation is rejected with `ERR_INVALID_WINDOW`. Two programs for the same `brand_code` may not overlap while both are non-`CLOSED`; adjacency is allowed, so one program's `ends_at` may equal another's `starts_at` — anything tighter is rejected with `ERR_PROMOTION_WINDOW_OVERLAP`. And per §2.8, a `mandated_retail_price_cents` that is present and non-null is flatly prohibited: `ERR_RETAIL_PRICE_MANDATE_PROHIBITED`, because a manufacturer-mandated retail price violates three-tier law. The `suggested_discount_pct` is advisory only and never binds the retail price. A program is born `OPEN` with its `opt_ins` list empty.

Participation is voluntary and self-managed: a `WholesalerPrincipal` opts its own wholesaler into a program, with the caller's `X-User-ID` recorded as the entry's `wholesaler_id` alongside the logical-clock `opted_at`; the `201 Created` response carries the updated program. The program must be `OPEN` with the logical clock still strictly before `ends_at` — an opt-in on a closed program, or at or after the window's end, is rejected with `ERR_OPT_IN_WINDOW_CLOSED`. The wholesaler must be `APPOINTED`, else `ERR_WHOLESALER_NOT_ELIGIBLE`; the program's brand must lie within the `brand_scope` of one of the wholesaler's `ACTIVE` agreements, else `ERR_BRAND_SCOPE_MISMATCH`; and each wholesaler opts in at most once per program, a second attempt drawing `ERR_DUPLICATE_OPT_IN`.

Programs close on the clock, not by request. When the logical clock is set to an instant at or past a program's `ends_at`, the sweep of §2.5 moves the program `OPEN` → `CLOSED`, and from then on every opt-in attempt is rejected with `ERR_OPT_IN_WINDOW_CLOSED`.

## 4. Endpoint Definitions

Operations that create a new resource — including sub-resource additions such as an allocation request or a promotion opt-in — return a `201 Created` status code. Operations that act on an existing resource without creating a new one (amendments, reviews of state, decisions, consummation, locking, voiding, clock advancement) return `200 OK`, as do all reads. The request and response shapes of each operation are specified by the narratives of §2 and §3; the table below is the structural index.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock and run the time-based sweeps | BrewerAdmin |
| POST | `/territories` | Create an exclusive sales territory | BrewerAdmin |
| GET | `/territories/{id}` | Get a territory | BrewerAdmin, BrewerCompliance, WholesalerPrincipal, DraftAuditor |
| GET | `/territories/{id}/agreements` | List agreements covering a territory | BrewerAdmin, BrewerCompliance, WholesalerPrincipal, DraftAuditor |
| POST | `/agreements` | Appoint a wholesaler to a vacant territory with a brand equity agreement | BrewerAdmin |
| GET | `/agreements/{id}` | Get an agreement | BrewerAdmin, BrewerCompliance, WholesalerPrincipal, DraftAuditor |
| POST | `/agreements/{id}/amendments` | Amend an active agreement's terms in place (OCC-guarded) | BrewerAdmin |
| GET | `/agreements/{id}/equity-index` | Compute the agreement's equity index (provisional or audited variant) | BrewerAdmin, BrewerCompliance, WholesalerPrincipal, DraftAuditor |
| GET | `/agreements/{id}/transfer-applications` | List transfer applications for an agreement | BrewerAdmin, BrewerCompliance, WholesalerPrincipal, DraftAuditor |
| POST | `/wholesalers` | Register a wholesaler | BrewerAdmin |
| GET | `/wholesalers/{id}` | Get a wholesaler | BrewerAdmin, BrewerCompliance, WholesalerPrincipal, DraftAuditor |
| GET | `/wholesalers/{id}/agreements` | List a wholesaler's agreements | BrewerAdmin, BrewerCompliance, WholesalerPrincipal, DraftAuditor |
| GET | `/wholesalers/{id}/retail-accounts` | List retail accounts served by a wholesaler | BrewerAdmin, BrewerCompliance, WholesalerPrincipal, DraftAuditor |
| GET | `/wholesalers/{id}/performance-reviews` | List a wholesaler's performance reviews | BrewerAdmin, BrewerCompliance, WholesalerPrincipal, DraftAuditor |
| POST | `/transfer-applications` | Seller wholesaler applies to transfer its agreement's territory award | WholesalerPrincipal |
| POST | `/transfer-applications/{id}/qualification-review` | Compute the successor qualification score and route the application | BrewerCompliance |
| POST | `/transfer-applications/{id}/rofr-response` | ROFR holder exercises or waives its right of first refusal | WholesalerPrincipal |
| POST | `/transfer-applications/{id}/decision` | Approve or reject a qualified transfer | BrewerCompliance |
| POST | `/transfer-applications/{id}/consummate` | Consummate an approved transfer and run the reassignment cascade | BrewerAdmin |
| POST | `/performance-reviews` | Publish a quarterly performance review | BrewerAdmin |
| GET | `/performance-reviews/{id}` | Get a performance review | BrewerAdmin, BrewerCompliance, WholesalerPrincipal, DraftAuditor |
| POST | `/performance-reviews/{id}/response` | Reviewed wholesaler acknowledges or disputes the review | WholesalerPrincipal |
| GET | `/performance-reviews/{id}/corrective-plans` | List corrective plans spawned by a review | BrewerAdmin, BrewerCompliance, WholesalerPrincipal, DraftAuditor |
| POST | `/corrective-plans/{id}/activate` | Activate a proposed corrective plan | BrewerCompliance |
| POST | `/corrective-plans/{id}/resolve` | Resolve an active corrective plan as verified or failed | BrewerCompliance |
| POST | `/corrective-plans/{id}/revise` | Resubmit a failed corrective plan for another round | WholesalerPrincipal |
| POST | `/allocation-events` | Create a limited-release allocation event | BrewerAdmin |
| GET | `/allocation-events/{id}` | Get an allocation event with requests, assignments, and ledger fields | BrewerAdmin, BrewerCompliance, WholesalerPrincipal, DraftAuditor |
| POST | `/allocation-events/{id}/requests` | Wholesaler requests a quantity from an open event | WholesalerPrincipal |
| POST | `/allocation-events/{id}/lock` | Lock an open event and run the waterfall assignment | BrewerAdmin |
| POST | `/allocation-events/{id}/assignments/{wholesalerId}/decision` | Wholesaler confirms or releases its own assignment | WholesalerPrincipal |
| POST | `/retail-accounts` | Register an on-premise retail account | BrewerAdmin |
| GET | `/retail-accounts/{id}` | Get a retail account | BrewerAdmin, BrewerCompliance, WholesalerPrincipal, DraftAuditor |
| GET | `/retail-accounts/{id}/draft-audits` | List draft-quality audits of an account | BrewerAdmin, BrewerCompliance, WholesalerPrincipal, DraftAuditor |
| POST | `/draft-audits` | Record a completed draft-quality audit | DraftAuditor |
| GET | `/retail-accounts/{id}/pos-grants` | List POS grants issued to an account | BrewerAdmin, BrewerCompliance, WholesalerPrincipal, DraftAuditor |
| POST | `/pos-grants` | Issue point-of-sale material within the state-law value cap | BrewerAdmin |
| POST | `/pos-grants/{id}/void` | Void an issued POS grant | BrewerAdmin |
| POST | `/promotion-programs` | Create a promotion program with a half-open window | BrewerAdmin |
| POST | `/promotion-programs/{id}/opt-ins` | Opt the caller's wholesaler into an open promotion program | WholesalerPrincipal |

## 5. Error Code Catalogue

The trigger condition for each error is specified in the narratives of §2 and §3; this catalogue is the index of identifiers to HTTP status codes.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE_TRANSITION` | 409 Conflict |
| `ERR_TERRITORY_NOT_VACANT` | 409 Conflict |
| `ERR_WHOLESALER_NOT_ELIGIBLE` | 409 Conflict |
| `ERR_AGREEMENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_ACCOUNT_NOT_ACTIVE` | 409 Conflict |
| `ERR_REVIEW_NOT_ACKNOWLEDGED` | 409 Conflict |
| `ERR_ROFR_WINDOW_OPEN` | 409 Conflict |
| `ERR_OPT_IN_WINDOW_CLOSED` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_THREE_TIER_PROHIBITION` | 422 Unprocessable Entity |
| `ERR_RETAIL_PRICE_MANDATE_PROHIBITED` | 422 Unprocessable Entity |
| `ERR_TRANSFER_ALREADY_PENDING` | 409 Conflict |
| `ERR_DUPLICATE_REVIEW` | 409 Conflict |
| `ERR_DUPLICATE_REQUEST` | 409 Conflict |
| `ERR_DUPLICATE_OPT_IN` | 409 Conflict |
| `ERR_PROMOTION_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_INVALID_WINDOW` | 422 Unprocessable Entity |
| `ERR_BRAND_SCOPE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_ROFR_HOLDER_CONFLICT` | 422 Unprocessable Entity |
| `ERR_PORTFOLIO_CONCENTRATION_EXCEEDED` | 409 Conflict |
| `ERR_AUDIT_TOO_SOON` | 409 Conflict |
| `ERR_POS_VALUE_CAP_EXCEEDED` | 422 Unprocessable Entity |
