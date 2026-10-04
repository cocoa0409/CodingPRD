# Rail Rate Complaint Adjudication API — Product Requirements Document

## 1. Introduction

When a shipper believes a railroad is charging an unreasonably high rate on a captive movement, when service on a corridor collapses, when two carriers propose to merge, or when a railroad seeks to abandon a line its neighbors still depend on, the dispute lands before the Surface Transportation Board. This document specifies the API of the Board's adjudication and transaction-review platform, mounted under the `/stb` prefix. The platform registers rail carriers, receives rate reasonableness complaints from shippers, gates them behind a market dominance threshold determination, conducts evidentiary proceedings under three evidentiary tracks scaled to the relief sought, and renders decisions that can prescribe rates, grant reparations, and track payment through a reparations ledger. Alongside the rate docket, the same platform administers the Board's annual revenue adequacy findings, shipper service complaints and the emergency service orders they escalate into, merger and acquisition review under public interest standards with attendant service assurance plans, line abandonment and discontinuance applications including interim trail use conversion, and reciprocal switching petitions that ration scarce interchange capacity.

Two design commitments shape everything that follows. First, the Board's time is a **logical clock**, not wall-clock time: comment periods, negotiation windows, and order expirations all read a clock that only moves when an administrator advances it, so every temporal rule in this document is deterministic. Second, carrier condition is **derived, not stored**: a carrier's revenue adequacy standing, compliance standing, route-mileage accounting, and reparation exposure are always recomputed from the underlying filings and orders, never edited directly. Implementers should treat every derived figure described below as a function of the recorded facts, refreshed at the moment those facts change.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the calling party, and `X-User-Role`, identifying the caller's role. If either header is missing, or if `X-User-Role` is not one of the declared role names, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A caller whose role is syntactically valid but not listed among the roles authorized for the invoked endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

Four roles exist, spelled exactly as follows:

- `PlatformAdmin` — Board staff administrator. Registers railroad carriers and operates the logical clock. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any resource's `id`.
- `BoardAdjudicator` — the Board's adjudicator. Issues market dominance determinations, revenue adequacy findings, merits decisions, evidence reviews, service-order escalations and resolutions, merger decisions, abandonment dispositions, and petition rulings. When `X-User-Role` is `BoardAdjudicator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any resource's `id`.
- `Shipper` — a shipper party. Files rate complaints, evidentiary submissions on its own complaints, petitions to reopen, service complaints, and reciprocal switching petitions. When `X-User-Role` is `Shipper`, `X-User-ID` is an opaque party identifier that is not an entity `id`; it is recorded verbatim as the `shipper_id` of each filing, and ownership checks compare a resource's `shipper_id` field to `X-User-ID`.
- `CarrierOperator` — a railroad operator acting for a registered carrier. Files merger applications and amendments as acquiring carrier, service assurance plans, and abandonment applications, submits carrier-side evidence, and posts reparation payments. When `X-User-Role` is `CarrierOperator`, `X-User-ID` is the `id` of the acting `Carrier`; ownership checks on any request that names a carrier — in a path parameter or in a body field such as `acquiring_carrier_id` or `carrier_id` — compare that carrier reference to `X-User-ID`, and a mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

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

All list endpoints accept the optional query parameters `limit` and `offset`. The `limit` parameter defaults to 10, must be at least 1, and may not exceed 100. The `offset` parameter defaults to 0. Results are always sorted by `created_at` in ascending order (oldest first). The `meta` object of a list response carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more`, where `total_count` is the number of records matching the query before pagination and `has_more` reports whether additional records exist beyond the returned window.

### 2.4. Resource Identity, Timestamps, and Versioning

Every resource in the system carries a common identity block. The `id` is a server-minted dashed UUID with no type prefix, assigned at creation and immutable thereafter. `created_at` and `updated_at` are ISO 8601 UTC timestamps rendered with exactly three fractional digits; `created_at` is fixed at creation and `updated_at` is refreshed on every mutation. Each resource also carries a `version`, an integer that starts at 1 at creation and increments by exactly 1 on every mutation of that resource — **including cascaded mutations** inflicted by another resource's lifecycle event. When, for example, an emergency service order's issuance flips a carrier's compliance standing and sets a hold flag on several merger applications, the carrier and each affected merger application each gain one `version` increment and a refreshed `updated_at`, exactly as if they had been edited directly.

Domain timestamps are rendered differently from the identity block. The fields `issued_at`, `expires_at`, `comment_close_at`, and `nitu_expires_at` are computed from the logical clock and are rendered **exactly as the logical clock read when they were computed** — they are not re-normalized to three fractional digits. If the clock read `2026-09-01T00:00:00Z` at issuance, that is precisely the string the field renders.

### 2.5. The Logical Clock and Automatic Expiry

All time-dependent behavior in the system — comment periods, negotiation windows, order durations, and evidence freshness — reads a single logical clock, never wall-clock time. At server startup the logical clock reads exactly `2026-09-01T00:00:00Z`; before any administrator call, every "now" in the system is that default instant. A `PlatformAdmin` advances the clock through an administrator-only test-driving capability — `POST /stb/_clock/set_current_utc` (HTTP 200) — supplying the `current_utc` instant the clock must thereafter read. The capability returns an empty success envelope and has no resource representation of its own.

The logical clock has one automatic side effect: whenever the clock reaches or passes the `expires_at` of an emergency service order in `ACTIVE` status, the order transitions to `EXPIRED`, the affected carrier's compliance standing is recomputed, and the merger review holds that depended on the order are cleared. This expiry is evaluated **lazily on any read or write** in the system, not only when the clock is set: any request processed at a clock reading at or beyond an active order's `expires_at` observes and applies the expiry before responding.

### 2.6. Request Validation and Error Precedence

Every request is validated against the following seventeen checks in strict priority order. The first check that fails determines the response; no later check is evaluated. This ordering is observable: a request that fails two checks surfaces the error of the earlier one.

1. **Caller context and request shape** (applies to every endpoint). The `X-User-ID` and `X-User-Role` headers must be present and the role must be a declared role, failing which the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). Only after the headers pass is the request body examined: every required input field must be present, enum values must be in range, numeric bounds must be respected, `service_end_date` must be strictly later than `service_start_date`, and the `conditions` array must be non-empty where an outcome requires it — any such defect is `ERR_INVALID_REQUEST` (HTTP 400). Header failure always precedes body failure.
2. **Role authorization** (every endpoint). The caller's role must appear in the endpoint's authorized role list, failing which `ERR_FORBIDDEN_ROLE` (HTTP 403). This check also covers event-type/role mismatches on the reparation ledger: a `CarrierOperator` submitting a `REVERSAL` event or a `BoardAdjudicator` submitting a `PAYMENT` event is rejected here.
3. **Ownership** (the ten party-bound write endpoints: rate complaint creation, evidence submission, complaint reopening, reparation events, service complaint creation, reciprocal switching petition creation, merger application creation, merger amendment, service assurance plan creation, and abandonment application creation). A `Shipper` caller's `X-User-ID` must equal the `shipper_id` of the filing or of the target complaint; a `CarrierOperator` caller's `X-User-ID` must equal the carrier the request acts on — the `carrier_id` path or body parameter, the `acquiring_carrier_id` of the merger being created or amended or given a plan, or the `carrier_id` of the complaint receiving evidence or a payment. On evidence submissions, `submitted_by_party` must be `SHIPPER` for a `Shipper` caller and `CARRIER` for a `CarrierOperator` caller. Any mismatch is `ERR_NOT_RESOURCE_OWNER` (HTTP 403). Ownership is evaluated only when the target resource exists; an unknown path identifier cannot be ownership-checked and falls through to the existence failure below.
4. **Path existence** (every endpoint with path identifiers). Path identifiers are validated left to right — the carrier first, then the complaint, application, petition, or evidence identifier nested beneath it. A missing carrier id yields `ERR_CARRIER_NOT_FOUND`; a missing rate complaint `ERR_RATE_COMPLAINT_NOT_FOUND`; a missing evidence submission `ERR_EVIDENCE_NOT_FOUND`; a missing service complaint `ERR_SERVICE_COMPLAINT_NOT_FOUND`; a missing merger application `ERR_MERGER_APPLICATION_NOT_FOUND`; a missing abandonment application `ERR_ABANDONMENT_APPLICATION_NOT_FOUND`; a missing petition `ERR_PETITION_NOT_FOUND` — all HTTP 404.
5. **Body reference existence** (creation endpoints). Carriers named in body fields must exist: `carrier_id` on rate complaint, service complaint, petition, and abandonment creation, and both `acquiring_carrier_id` and `target_carrier_id` on merger creation, failing which `ERR_CARRIER_NOT_FOUND` (HTTP 404). The `evidence_service_complaint_id` named on petition creation must exist, failing which `ERR_SERVICE_COMPLAINT_NOT_FOUND` (HTTP 404).
6. **State admissibility** (every action endpoint). The target resource must be in a state that permits the requested transition: `ERR_COMPLAINT_NOT_FILED`, `ERR_COMPLAINT_NOT_IN_EVIDENTIARY`, `ERR_COMPLAINT_NOT_DECIDED`, `ERR_EVIDENCE_ALREADY_REVIEWED`, `ERR_SERVICE_COMPLAINT_NOT_OPEN`, `ERR_MERGER_NOT_IN_COMMENT_PERIOD`, `ERR_ABANDONMENT_NOT_UNDER_REVIEW`, `ERR_ABANDONMENT_NOT_GRANTED`, `ERR_ABANDONMENT_NOT_TRAIL_PENDING`, `ERR_PETITION_NOT_FILED`, or `ERR_PETITION_NOT_GRANTED` (all HTTP 409), each as defined with its transition in §3.
7. **Rate-decision regulatory gate — revenue adequacy.** Any decision call on a rate complaint — whatever the requested `outcome` — requires that a revenue adequacy finding exist for the defendant carrier and the complaint's `contested_fiscal_year`, failing which `ERR_REVENUE_ADEQUACY_FINDING_REQUIRED` (HTTP 409).
8. **Rate-decision regulatory gate — verified evidence (outcomes `UPHELD` and `REJECTED` only).** At least one evidence submission with `review_status` `VERIFIED` must exist, failing which `ERR_NO_VERIFIED_EVIDENCE` (HTTP 409).
9. **Rate-decision regulatory gate — market dominance consistency.** Outcomes `UPHELD` and `REJECTED` require an `adjudicated_rvc_ratio` of at least 1.8000, failing which `ERR_MARKET_DOMINANCE_ABSENT` (HTTP 409); outcome `DISMISSED` requires the ratio to be absent or below 1.8000, failing which `ERR_MARKET_DOMINANCE_PRESENT` (HTTP 409).
10. **Merger gate — service hold.** Outcome `APPROVED` requires the application's `service_review_hold` to be false, failing which `ERR_MERGER_SERVICE_HOLD` (HTTP 409).
11. **Merger gate — plan required.** Outcome `APPROVED_WITH_CONDITIONS` requires at least one service assurance plan on the application, failing which `ERR_SERVICE_ASSURANCE_PLAN_REQUIRED` (HTTP 409).
12. **Decision consistency.** A merger outcome must match the `public_interest_score` band, failing which `ERR_DECISION_INCONSISTENT_WITH_SCORE` (HTTP 422); an abandonment outcome of `GRANTED` requires a `public_convenience_finding` of `SERVED`, failing which `ERR_DECISION_INCONSISTENT_WITH_FINDING` (HTTP 422).
13. **Petition evidence carrier alignment.** At petition decision time the evidence service complaint's carrier must be the petition's incumbent carrier, failing which `ERR_SERVICE_COMPLAINT_CARRIER_MISMATCH` (HTTP 422).
14. **Petition evidence freshness.** The evidence service complaint must have been created no more than 84 days before the petition, failing which `ERR_SERVICE_FAILURE_WINDOW_EXPIRED` (HTTP 422).
15. **Temporal gates** (decide, convert, and consummate endpoints). The petition's evidence complaint must be in `ESCALATED` status at decide time (`ERR_PETITION_EVIDENCE_NOT_ESCALATED`, HTTP 409); a merger may be decided only when the logical clock has reached `comment_close_at` (`ERR_COMMENT_PERIOD_OPEN`, HTTP 409); trail conversion is permitted only when the logical clock has not passed `nitu_expires_at` (`ERR_TRAIL_USE_NOTICE_EXPIRED`, HTTP 409); consummation from `TRAIL_PENDING` requires the logical clock to be strictly later than `nitu_expires_at` (`ERR_TRAIL_USE_WINDOW_OPEN`, HTTP 409).
16. **Uniqueness and capacity** (creation and decide endpoints as listed in §3). Carrier codes are unique (`ERR_DUPLICATE_CARRIER_CODE`, HTTP 409); there is at most one revenue adequacy finding per carrier per fiscal year (`ERR_DUPLICATE_FINDING`, HTTP 409); at most one emergency service order is `ACTIVE` per carrier (`ERR_ESO_ALREADY_ACTIVE`, HTTP 409); at most one non-terminal petition exists per shipper and interchange (`ERR_DUPLICATE_ACTIVE_PETITION`, HTTP 409); at most one service assurance plan exists per merger application (`ERR_SERVICE_ASSURANCE_PLAN_EXISTS`, HTTP 409); at most one non-terminal abandonment application exists per line segment (`ERR_DUPLICATE_ACTIVE_ABANDONMENT`, HTTP 409); an interchange accommodates at most four overlapping granted switching windows (`ERR_INTERCHANGE_CAPACITY_EXCEEDED`, HTTP 409); a petitioning facility must lie within 30 miles of the interchange (`ERR_FACILITY_BEYOND_INTERCHANGE_DISTANCE`, HTTP 422).
17. **Reparation fiscal guards** (reparation events only). A `PAYMENT` must carry an `amount_cents` of at least 1 (`ERR_INVALID_REQUEST`, HTTP 400) and no greater than the outstanding award (`ERR_PAYMENT_EXCEEDS_OUTSTANDING`, HTTP 402); a `REVERSAL` requires that nothing has yet been paid (`ERR_AWARD_HAS_PAYMENTS`, HTTP 409).

### 2.7. Numeric Precision and Rounding

Monetary amounts are integer cents throughout: rates in integer cents per ton, totals in integer cents, and no fractional cents anywhere in stored state. Every rounding in the system is **round half up** — a fraction of exactly one half rounds away from zero. Three precision regimes apply. Ratios — `alleged_rvc_ratio`, `adjudicated_rvc_ratio`, and the adequacy floors — are rendered to exactly 4 decimal places, round half up. Weighted scores — `public_interest_score` — are rendered to exactly 2 decimal places, round half up. Returns on investment and the prescribed-rate floor are whole numbers: `current_year_roi_bps` and `five_year_avg_roi_bps` are integer basis points, and the floor rate computed during a merits decision is rounded half up to whole cents per ton before any comparison is made. The one structurally pinned rounding order lives in the reparations ledger: each shipment's overcharge is rounded to whole cents first, and only then are the per-shipment amounts summed (§3.4).

### 2.8. Optimistic Concurrency Control

Exactly one endpoint participates in optimistic concurrency control: the merger amendment capability. An amendment request must carry `expected_merger_application_version`, a non-optional input field holding the `version` of the merger application the client last observed. If that value does not match the application's current `version`, the amendment is rejected with `ERR_STALE_VERSION` (HTTP 412) and nothing is modified. An amendment legitimately supersedes the prior application content — it resets the comment window — so a client holding a stale version would otherwise silently overwrite a newer amendment. No other endpoint takes a version field; in particular, decisions, evidence submissions, and reparation events are governed by the state and validation rules of §2.6, not by client-supplied versions.

### 2.9. Derived Carrier Condition Registers

A carrier's condition is never edited directly; four registers are derived from underlying records and recomputed at the moment those records change, and all of them are visible on every carrier read:

- **Mileage accounting.** `active_route_miles` equals the carrier's `base_route_miles` minus `abandoned_route_miles` minus `trail_use_route_miles`. `abandoned_route_miles` is the sum of `segment_miles` over the carrier's abandonment applications in `CONSUMMATED` status; `trail_use_route_miles` is the sum over those in `TRAIL_CONVERTED` status. Both start at 0, and `active_route_miles` is recomputed on abandonment consummation and on trail conversion.
- **Revenue adequacy standing.** `revenue_adequacy_status` equals the `finding` of the carrier's revenue adequacy finding with the greatest `fiscal_year`, and is `UNDETERMINED` when the carrier has no findings at all. Its possible values are `UNDETERMINED`, `ADEQUATE`, and `INADEQUATE`.
- **Compliance standing.** `compliance_standing` is `PROBATION` if and only if the carrier has at least one emergency service order in `ACTIVE` status, and `GOOD` otherwise. It is recomputed on every order lifecycle event — issuance, expiry, and lifting.
- **Reparation exposure.** `reparation_exposure_cents` is the sum of `award_outstanding_cents` over the carrier's rate complaints in `DECIDED` status. It starts at 0; a decision upholding a complaint adds the granted award; a complaint leaving `DECIDED` — closing on full payment or reversal — stops contributing.

A fifth derived flag lives on merger applications: `service_review_hold` is true if and only if the acquiring carrier has any emergency service order in `ACTIVE` status. It is recomputed on every order lifecycle event and gates the `APPROVED` outcome at decision time (§3.6).

### 2.10. Nested Resource Retrieval

Several resources are reachable as read-only views nested beneath a carrier: a carrier's revenue adequacy findings, the rate complaints filed against it, the service complaints filed against it, the emergency service orders directed at it, the merger applications in which it is acquirer or target, its abandonment applications, and the reciprocal switching petitions naming it as incumbent. Path identifiers on all nested routes are validated left to right — the carrier id is checked first, so a request naming an unknown carrier is rejected with `ERR_CARRIER_NOT_FOUND` (HTTP 404) before any nested identifier is examined, and an unknown nested identifier produces that resource type's own not-found error. The list views of rate complaints, service complaints, emergency service orders, and reciprocal switching petitions additionally accept an optional `status` query parameter that filters results to the named state.

## 3. Business Logic & Workflows

### 3.1. Carrier Registration and Annual Revenue Adequacy Reporting

Before any complaint, merger, or abandonment can be filed, a `PlatformAdmin` registers the railroad. Registration supplies a `carrier_code` — the railroad's unique reporting mark, such as `CSXT` — together with its `legal_name`, its `carrier_class` (one of `I`, `II`, or `III`), and its `base_route_miles`, the total route mileage at registration expressed in whole miles and no less than 1. The `carrier_code` is unique across all carriers: a registration repeating an existing code is rejected with `ERR_DUPLICATE_CARRIER_CODE` (HTTP 409). At registration the derived registers initialize: `active_route_miles` equals `base_route_miles`, `abandoned_route_miles` and `trail_use_route_miles` are 0, `revenue_adequacy_status` is `UNDETERMINED`, `compliance_standing` is `GOOD`, and `reparation_exposure_cents` is 0.

Once a year per fiscal year, a `BoardAdjudicator` files the carrier's annual report, which publishes the Board's revenue adequacy finding for that year. The filing names the `fiscal_year` it covers and three figures: `operating_revenue_cents` and `operating_expense_cents` (each at least 0) and `net_investment_cents` (at least 1). There is at most one finding per carrier per fiscal year; a second filing for the same carrier and `fiscal_year` is rejected with `ERR_DUPLICATE_FINDING` (HTTP 409).

Two return-on-investment figures are computed at filing. The **current-year return** `current_year_roi_bps` is the year's operating revenue minus its operating expense, the difference multiplied by 10000 and divided by the net investment base, the result rounded half up to a whole basis point. The **five-year average** `five_year_avg_roi_bps` is the mean of the `current_year_roi_bps` values over this carrier's findings whose `fiscal_year` falls in the five-year window from `fiscal_year` minus 4 through `fiscal_year` inclusive, that mean rounded half up to a whole basis point; when fewer than five findings exist in the window, only the years that exist are averaged. Identical filings can therefore yield a current-year figure below the adequacy bar while the five-year average clears it, or the reverse. The finding itself is a threshold determination: `finding` is `ADEQUATE` when `five_year_avg_roi_bps` is at least 1140 basis points — the Board's cost of capital — and `INADEQUATE` otherwise. Both ROI figures and the `finding` are recorded on the finding resource and are response-visible, and the carrier's `revenue_adequacy_status` immediately adopts the `finding` of whichever finding now has the greatest `fiscal_year`.

### 3.2. Filing a Rate Complaint and the Market Dominance Threshold

A rate reasonableness case begins when a `Shipper` files a complaint against a registered carrier. The filing body carries the `shipper_id` of the complaining party — which must equal the caller's `X-User-ID` — the defendant's `carrier_id`, the `commodity` moving under the challenged rate, the `challenged_rate_cents_per_ton` (the challenged through rate, integer cents per ton, at least 1), the shipper-alleged `alleged_variable_cost_cents_per_ton` (at least 1), the `annual_tons` subject to the rate (at least 1), the total `relief_sought_cents` in reparations and rate relief (at least 1), and the `contested_fiscal_year` whose revenue adequacy finding will govern the prescription floor at decision time. No revenue adequacy finding need exist at filing; that requirement attaches at decision time only.

Two values are computed the moment the complaint is filed. The evidentiary **track** is selected by the relief sought: `relief_sought_cents` of at most 100000000 cents (one million dollars) places the complaint on the `THREE_BENCHMARK` track; at most 400000000 cents (four million dollars) places it on the `SIMPLIFIED_SAC` track; anything larger places it on the `FULL_SAC` track. And the **alleged revenue-to-variable-cost ratio** `alleged_rvc_ratio` is the `challenged_rate_cents_per_ton` divided by the `alleged_variable_cost_cents_per_ton`, rounded half up to 4 decimal places. The complaint enters `FILED` status with `market_dominance` `UNDETERMINED`, `award_status` `NONE`, `adjudicated_rvc_ratio` and `decision_outcome` absent (null), and the award and prescription fields at their zero or null defaults.

The Board's threshold act is the **market dominance determination**, performed by a `BoardAdjudicator` on a complaint in `FILED` status — a complaint in any other state is rejected with `ERR_COMPLAINT_NOT_FILED` (HTTP 409). The determination takes two boolean inputs, `product_competition_exists` and `geographic_competition_exists`, and has exactly two branches:

- **Dominance present.** When the `alleged_rvc_ratio` is at least 1.8000 — a ratio of exactly 1.8000 clears the threshold, while 1.7999 does not — and neither product competition nor geographic competition exists, `market_dominance` is set to `PRESENT` and the complaint advances from `FILED` to `EVIDENTIARY_PHASE`.
- **Dominance absent.** When the `alleged_rvc_ratio` is below 1.8000, or product competition exists, or geographic competition exists, `market_dominance` is set to `ABSENT` and the complaint moves from `FILED` to `DISMISSED`, a terminal state.

### 3.3. Evidentiary Proceedings and Merits Adjudication

While a complaint is in `EVIDENTIARY_PHASE` — or in `REOPENED`, as described in §3.4 — either party may place evidence on the record. A `Shipper` submits evidence on the shipper's own complaints; a `CarrierOperator` submits on complaints against the operator's own carrier. Each submission carries a `submission_type` of `SAC_STUDY`, `THREE_BENCHMARK_PACKET`, or `REBUTTAL`; a `submitted_by_party` of `SHIPPER` or `CARRIER` consistent with the caller's role (a `Shipper` must submit as `SHIPPER`, a `CarrierOperator` as `CARRIER`, and any inconsistency is `ERR_NOT_RESOURCE_OWNER`); a `reference_rate_cents_per_ton` (at least 1) carrying the stand-alone-cost rate for a `SAC_STUDY`, the benchmark rate for a `THREE_BENCHMARK_PACKET`, or the counter-figure for a `REBUTTAL`; and a `verified_variable_cost_cents_per_ton` (at least 1), the cost figure the Board will adopt if the submission is verified. Each submission is recorded beneath its complaint: the system stamps it with the `rate_complaint_id` taken from the creation path. A submission on a complaint in any state other than `EVIDENTIARY_PHASE` or `REOPENED` is rejected with `ERR_COMPLAINT_NOT_IN_EVIDENTIARY` (HTTP 409). The submission enters with `review_status` `SUBMITTED`, and its creation has a side effect on a reopened complaint: the complaint leaves `REOPENED` and re-enters `EVIDENTIARY_PHASE`, resuming the cycle.

A `BoardAdjudicator` then reviews each submission by supplying a `review_outcome` of `VERIFIED` or `REJECTED`. Review is a one-way door: only a submission still in `SUBMITTED` may be reviewed, and a second review attempt is rejected with `ERR_EVIDENCE_ALREADY_REVIEWED` (HTTP 409). A `REJECTED` outcome simply marks the submission `REJECTED` with no further effect. A `VERIFIED` outcome recomputes the parent complaint's `adjudicated_rvc_ratio`: the complaint's `challenged_rate_cents_per_ton` divided by **this submission's** `verified_variable_cost_cents_per_ton`, rounded half up to 4 decimal places. The most recently verified submission always wins, so successive verifications overwrite the ratio; the ratio is null until the first verification. The adjudicated variant of the revenue-to-variable-cost ratio uses the same formula as the alleged variant but over the verified cost figure, and the two diverge whenever verified cost differs from alleged cost; the adjudicated variant alone gates the merits outcomes below.

The merits decision is taken by a `BoardAdjudicator` supplying an `outcome` of `UPHELD`, `REJECTED`, or `DISMISSED`, plus an optional `shipments` array used only when the complaint is upheld. The complaint must be in `EVIDENTIARY_PHASE` (`ERR_COMPLAINT_NOT_IN_EVIDENTIARY`). Four regulatory gates then apply, in the precedence order of §2.6: a revenue adequacy finding must exist for the defendant carrier and the complaint's `contested_fiscal_year` (`ERR_REVENUE_ADEQUACY_FINDING_REQUIRED`); for `UPHELD` or `REJECTED`, at least one submission with `review_status` `VERIFIED` must exist (`ERR_NO_VERIFIED_EVIDENCE`); for `UPHELD` or `REJECTED` the `adjudicated_rvc_ratio` must be at least 1.8000, the Board otherwise lacking jurisdiction (`ERR_MARKET_DOMINANCE_ABSENT`); and for `DISMISSED` the ratio must be null or below 1.8000, a merits decision being otherwise mandatory (`ERR_MARKET_DOMINANCE_PRESENT`).

When the outcome is `DISMISSED`, `decision_outcome` is recorded as `DISMISSED`, `market_dominance` is set to `ABSENT`, and the complaint terminates in `DISMISSED`. When the outcome is `REJECTED`, `decision_outcome` is recorded as `REJECTED`, `award_status` remains `NONE`, and the complaint rests in `DECIDED`, where it remains reopenable. When the outcome is `UPHELD`, the Board prescribes a maximum reasonable rate and grants relief, as follows.

The prescription draws on five inputs: the complaint's `challenged_rate_cents_per_ton`; the latest verified submission's `verified_variable_cost_cents_per_ton` and `reference_rate_cents_per_ton`; an adequacy floor drawn from a **different entity** — the contested-year revenue adequacy finding, contributing a floor factor of 1.0000 when that finding is `ADEQUATE` and 1.1000 when it is `INADEQUATE`; the complaint's `annual_tons`; and the complaint's `track`. The computation proceeds in exact order. First, the floor rate is the verified variable cost multiplied by the floor factor, rounded half up to whole cents per ton. Second, the prescribed rate is the smaller of the challenged rate and the larger of the reference rate and the floor rate — the floor binds exactly when it exceeds the reference rate, and the prescription never exceeds the challenged rate. This `prescribed_rate_cents_per_ton` is recorded on the complaint and is response-visible. Third, the relief per ton is the challenged rate minus the prescribed rate, and the raw relief is that per-ton figure multiplied by `annual_tons`. Fourth, `relief_granted_cents` is the raw relief capped at the track's cap: 100000000 cents on the `THREE_BENCHMARK` track, 400000000 cents on the `SIMPLIFIED_SAC` track, and no cap at all on the `FULL_SAC` track. Both the prescribed rate and the granted relief are set only on `UPHELD`; they remain null on every other outcome.

### 3.4. The Reparations Ledger: Award, Payment, Reversal, Reopening, and Closure

An `UPHELD` decision also computes the reparation award from the `shipments` array supplied in the decision call. Each shipment names a tonnage, a decimal figure with up to 3 decimal places. The per-ton overcharge is the `challenged_rate_cents_per_ton` minus the `prescribed_rate_cents_per_ton`, a whole number of cents. For each shipment, the overcharge multiplied by that shipment's tonnage is rounded half up to **whole cents first**; the award `award_granted_cents` is then the integer sum of those per-shipment amounts. This rounding order is pinned: rounding each shipment and then summing is the only correct procedure, and summing first and rounding once is the forbidden alternative — the two diverge on fractional tonnage. When the `shipments` array is omitted or empty, the award is 0.

The ledger maintains three amounts under a pinned identity: `award_paid_cents` is the sum of all `PAYMENT` events, `award_outstanding_cents` is always exactly `award_granted_cents` minus `award_paid_cents`, and both are response-visible on the complaint at all times. On `UPHELD`, `award_outstanding_cents` initializes to the full `award_granted_cents`, and `award_status` becomes `GRANTED` — or `PAID` immediately when the award is 0. An award of 0 has a further consequence: the complaint passes through `DECIDED` and auto-advances to `CLOSED` in the same decision, because the closure rule below already sees a `PAID` award. When the award is greater than 0, the complaint rests in `DECIDED` and the defendant carrier's `reparation_exposure_cents` increases by `award_granted_cents` at decision time.

Settlement proceeds through reparation events posted against a complaint in `DECIDED` status — a complaint in any other state, including `CLOSED`, rejects the posting with `ERR_COMPLAINT_NOT_DECIDED` (HTTP 409). Each event carries an `event_type` and, for payments, an `amount_cents`. The two event types belong to different parties: a `CarrierOperator` posts `PAYMENT` events, and only on complaints against the operator's own carrier; a `BoardAdjudicator` posts `REVERSAL` events. A carrier operator submitting `REVERSAL`, or an adjudicator submitting `PAYMENT`, is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

- **Payment.** A `PAYMENT` must carry an `amount_cents` of at least 1 (otherwise `ERR_INVALID_REQUEST`, HTTP 400) and no greater than the current `award_outstanding_cents` (otherwise `ERR_PAYMENT_EXCEEDS_OUTSTANDING`, HTTP 402). The amount is added to `award_paid_cents` and subtracted from `award_outstanding_cents`. The `award_status` becomes `PARTIALLY_PAID` while a balance remains and `PAID` when the outstanding balance reaches 0.
- **Reversal.** A `REVERSAL` requires that `award_paid_cents` is exactly 0 — if anything has been paid the reversal is rejected with `ERR_AWARD_HAS_PAYMENTS` (HTTP 409). The reversal sets `award_granted_cents` to the paid amount (which the precondition pins at 0), sets `award_outstanding_cents` to 0, and sets `award_status` to `REVERSED`.

Closure is automatic: whenever a decided complaint's `award_status` becomes `PAID` or `REVERSED`, the complaint transitions from `DECIDED` to `CLOSED`, a terminal state, and the carrier's `reparation_exposure_cents` is recomputed — a closed complaint no longer contributes to exposure.

A decided complaint may also be **reopened** by the owning `Shipper` — the complaint's `shipper_id` must equal the caller's `X-User-ID`, and the complaint must be in `DECIDED` (`ERR_COMPLAINT_NOT_DECIDED`). Reopening moves the complaint to `REOPENED`, supersedes the record — every evidence submission with `review_status` `VERIFIED` becomes `SUPERSEDED` — and resets the `adjudicated_rvc_ratio` to null. The complaint then sits in `REOPENED` until the next evidentiary submission arrives, which returns it to `EVIDENTIARY_PHASE` (§3.3), from which a fresh merits decision may be taken.

### 3.5. Service Complaints and Emergency Service Orders

Separate from rate reasonableness, a `Shipper` may file a service complaint against a carrier that is failing to provide adequate service. The filing names the `shipper_id` (equal to the caller's `X-User-ID`), the defendant `carrier_id`, an `issue_type` of `DELAY`, `EMBARGO`, `CAR_SUPPLY`, or `FAILURE_TO_DELIVER`, and a free-form `territory_code` designator such as `GULF-COAST`. The complaint opens in `OPEN` status.

A `BoardAdjudicator` resolves a service complaint from either `OPEN` or `ESCALATED`; a complaint in any other state — that is, one already `RESOLVED` — rejects both resolution and escalation with `ERR_SERVICE_COMPLAINT_NOT_OPEN` (HTTP 409). Resolving from `OPEN` simply moves the complaint to `RESOLVED` with no further effect. Resolving from `ESCALATED` fires a cascade: the linked emergency service order, if still `ACTIVE`, becomes `LIFTED`; with no remaining `ACTIVE` order for the carrier, the carrier's `compliance_standing` recomputes to `GOOD`; and that return to `GOOD` clears `service_review_hold` on the carrier's `COMMENT_PERIOD` merger applications, unblocking the `APPROVED` outcome there (§3.6).

Escalation is the Board's coercive instrument. A `BoardAdjudicator` escalates an `OPEN` complaint by supplying a `directive` — the Board's directive text — provided no other emergency service order is `ACTIVE` for the same carrier; the closed-interval capacity is one active order per carrier, and a second escalation is rejected with `ERR_ESO_ALREADY_ACTIVE` (HTTP 409). Escalation moves the complaint to `ESCALATED` and fires a three-hop cascade. Hop 1: an emergency service order is created in `ACTIVE` status, carrying the `carrier_id` and `service_complaint_id` copied from the complaint, the supplied `directive`, an `issued_at` stamped from the logical clock at issuance, and an `expires_at` exactly 60 days after `issued_at`. Hop 2: the order becoming `ACTIVE` flips the carrier's `compliance_standing` to `PROBATION`. Hop 3: `PROBATION` on the acquiring carrier sets `service_review_hold` to true on that carrier's `COMMENT_PERIOD` merger applications, which then blocks the `APPROVED` outcome at merger decision time with `ERR_MERGER_SERVICE_HOLD`.

Orders unwind in two ways. When the logical clock reaches or passes an order's `expires_at` — evaluated lazily on any read or write, per §2.5 — the order transitions from `ACTIVE` to `EXPIRED`; the carrier's `compliance_standing` recomputes to `GOOD` if no other `ACTIVE` order remains, and the review holds clear on the carrier's `COMMENT_PERIOD` merger applications. When the linked service complaint resolves while the order is still `ACTIVE`, the order transitions to `LIFTED`, with the same standing recompute. `EXPIRED` and `LIFTED` are both terminal for the order.

### 3.6. Merger Review: Comment Windows, Amendments, and Public Interest Decisions

A merger case opens when a `CarrierOperator` files an application as acquiring carrier — the body's `acquiring_carrier_id` must equal the caller's `X-User-ID` — naming the `target_carrier_id` being acquired, the announced `transaction_value_cents` (at least 1), and three showings scored from 0 to 100 inclusive: `competition_preservation_score`, `service_reliability_score`, and `shipper_impact_score`. Both named carriers must exist (`ERR_CARRIER_NOT_FOUND`), and a showing outside the 0-to-100 range is `ERR_INVALID_REQUEST`. The application opens in `COMMENT_PERIOD` status, the comment window `comment_close_at` is set to the creation time plus 45 days, `conditions_imposed` initializes as an empty array, `service_review_hold` initializes false (recomputing thereafter with the acquiring carrier's order lifecycle), and the **public interest score** `public_interest_score` is computed: four-tenths of the competition-preservation showing plus three-tenths of the service-reliability showing plus three-tenths of the shipper-impact showing, the weighted sum rounded half up to 2 decimal places.

While the application is in `COMMENT_PERIOD`, the acquiring carrier may amend it. Amendment is the system's one optimistic-concurrency-guarded write (§2.8): the request must carry `expected_merger_application_version` matching the application's current `version`, failing which `ERR_STALE_VERSION` (HTTP 412), and the application must still be in `COMMENT_PERIOD`, failing which `ERR_MERGER_NOT_IN_COMMENT_PERIOD` (HTTP 409). The amendment may supply any of `transaction_value_cents`, `competition_preservation_score`, `service_reliability_score`, or `shipper_impact_score`; any field not supplied retains its current value. A successful amendment supersedes the prior content: the application's `version` increments by 1, `comment_close_at` resets to the amendment time plus 45 days, and `public_interest_score` is recomputed from the amended showings.

The applicant may also file a **service assurance plan** on the application — at most one plan per application, a second attempt being rejected with `ERR_SERVICE_ASSURANCE_PLAN_EXISTS` (HTTP 409) — and only while the application is in `COMMENT_PERIOD` (`ERR_MERGER_NOT_IN_COMMENT_PERIOD`). The plan carries a `plan_name` and an array of `commitments` strings, is stamped with the `merger_application_id` taken from the creation path, and enters in `DRAFT` status. Its fate then follows the merger's: when the merger is decided `APPROVED` or `APPROVED_WITH_CONDITIONS` the plan moves to `MONITORING`; when the merger is `REJECTED` the plan becomes `MOOT`, a terminal state.

Decision belongs to the `BoardAdjudicator`, who supplies an `outcome` — and, for one branch, a `conditions` array. All three branches share two gates: the application must be in `COMMENT_PERIOD` (`ERR_MERGER_NOT_IN_COMMENT_PERIOD`), and the logical clock must have reached `comment_close_at` — a decision attempted earlier is rejected with `ERR_COMMENT_PERIOD_OPEN` (HTTP 409), while a decision at exactly `comment_close_at` is permitted. The branches then diverge, and the Board's outcome must be consistent with the score: `ERR_DECISION_INCONSISTENT_WITH_SCORE` (HTTP 422) fires whenever the requested outcome does not match the band the `public_interest_score` has earned.

- **`APPROVED`** requires a `public_interest_score` of at least 60.00 and a `service_review_hold` of false — an active emergency service order against the acquiring carrier holds the application and rejects the approval with `ERR_MERGER_SERVICE_HOLD` (HTTP 409). On approval, any service assurance plan on the application moves from `DRAFT` to `MONITORING`.
- **`APPROVED_WITH_CONDITIONS`** requires a `public_interest_score` of at least 45.00 but less than 60.00, at least one service assurance plan already on the application (`ERR_SERVICE_ASSURANCE_PLAN_REQUIRED`, HTTP 409), and a `conditions` input that is a non-empty array of condition strings (an absent or empty array is `ERR_INVALID_REQUEST`, HTTP 400). The supplied conditions are recorded verbatim as `conditions_imposed`, the plan moves to `MONITORING`, and the conditions attach to the plan. A `service_review_hold` does **not** block this branch.
- **`REJECTED`** requires a `public_interest_score` below 45.00. On rejection, any service assurance plan on the application moves from `DRAFT` to `MOOT`.

All three outcomes are terminal for the application.

### 3.7. Abandonment, Interim Trail Use, and the Mileage Ledger

A `CarrierOperator` seeking to abandon or discontinue a line files an abandonment application, naming the `carrier_id` (equal to the caller's `X-User-ID`), the `line_segment_ref` milepost designator of the line (for example `MP 100.0-MP 120.0`), and the segment's `segment_miles` in whole route miles (at least 1). A line may carry at most one live application: a filing whose `line_segment_ref` already appears on an application in `UNDER_REVIEW`, `GRANTED`, or `TRAIL_PENDING` is rejected with `ERR_DUPLICATE_ACTIVE_ABANDONMENT` (HTTP 409). The application opens in `UNDER_REVIEW`, with `public_convenience_finding` null and `nitu_expires_at` null.

The `BoardAdjudicator` decides the application by supplying an `outcome` and the `public_convenience_finding` — `SERVED` or `NOT_SERVED` — that the record supports; the finding is recorded on the application in either branch. The application must be in `UNDER_REVIEW` (`ERR_ABANDONMENT_NOT_UNDER_REVIEW`, HTTP 409). An outcome of `GRANTED` additionally requires the finding to be `SERVED`; granting on any other finding is rejected with `ERR_DECISION_INCONSISTENT_WITH_FINDING` (HTTP 422). An outcome of `DENIED` records the finding and moves the application to `DENIED`, a terminal state. A grant moves the application to `GRANTED` and opens two divergent paths.

**Trail use.** While the application is `GRANTED`, the Board may issue a Notice of Interim Trail Use — an application in any other state rejects the notice with `ERR_ABANDONMENT_NOT_GRANTED` (HTTP 409). The notice moves the application to `TRAIL_PENDING` and sets `nitu_expires_at`, the negotiation deadline, to the notice issuance time plus 180 days. Within that window the Board may convert the line to interim trail use: conversion requires the `TRAIL_PENDING` state (`ERR_ABANDONMENT_NOT_TRAIL_PENDING`, HTTP 409) and a logical clock reading no later than `nitu_expires_at` — a conversion attempted after the deadline is rejected with `ERR_TRAIL_USE_NOTICE_EXPIRED` (HTTP 409), while a conversion at exactly the deadline still succeeds. Conversion moves the application to `TRAIL_CONVERTED`, a terminal state, and moves the mileage: the carrier's `active_route_miles` decreases by `segment_miles` and its `trail_use_route_miles` increases by `segment_miles`.

**Consummation.** Alternatively, the Board may consummate the abandonment. From `GRANTED`, consummation requires only the state — an application in any state other than `GRANTED` or `TRAIL_PENDING` is rejected with `ERR_ABANDONMENT_NOT_GRANTED` (HTTP 409) — and moves the application directly to `CONSUMMATED`. From `TRAIL_PENDING`, consummation carries a temporal guard: the logical clock must be **strictly later** than `nitu_expires_at`, and a consummation attempted at or before the deadline — at equality the window is still open — is rejected with `ERR_TRAIL_USE_WINDOW_OPEN` (HTTP 409). Either way, consummation is terminal and moves the mileage differently from conversion: the carrier's `active_route_miles` decreases by `segment_miles` and its `abandoned_route_miles` increases by `segment_miles`. A trail-pending application that consummates never incremented `trail_use_route_miles`, so its miles land entirely in the abandoned register.

### 3.8. Reciprocal Switching Petitions and Interchange Slot Capacity

A `Shipper` bottled up behind a single incumbent carrier may petition for reciprocal switching — access to a competing carrier at a nearby interchange. The petition names the `shipper_id` (equal to the caller's `X-User-ID`), the `incumbent_carrier_id` the petition seeks relief against, the `interchange_code` identifying the requested interchange point, the `facility_distance_miles` from the shipper's facility to the interchange, the `evidence_service_complaint_id` of a service complaint evidencing the inadequate service, and a requested switching window: `service_start_date`, an ISO date (`YYYY-MM-DD`) on which the window inclusively begins, and `service_end_date`, an ISO date on which it exclusively ends. Creation applies three guards: both referenced resources must exist — an unknown incumbent carrier is `ERR_CARRIER_NOT_FOUND` and an unknown evidence complaint is `ERR_SERVICE_COMPLAINT_NOT_FOUND` (both HTTP 404); the facility must lie within 30 miles of the interchange, a greater `facility_distance_miles` being rejected with `ERR_FACILITY_BEYOND_INTERCHANGE_DISTANCE` (HTTP 422); and the window must be non-empty, a `service_end_date` not strictly later than `service_start_date` being `ERR_INVALID_REQUEST` (HTTP 400). One further guard rations live petitions per shipper per interchange: at most one non-terminal petition — one in `FILED` or `GRANTED` status — may exist for the same `shipper_id` and `interchange_code`, a duplicate being rejected with `ERR_DUPLICATE_ACTIVE_PETITION` (HTTP 409). The petition enters `FILED` status.

A `BoardAdjudicator` decides the petition with an `outcome` of `GRANTED` or `DENIED`, and the petition must be in `FILED` (`ERR_PETITION_NOT_FILED`, HTTP 409). Denial has no further precondition and moves the petition to `DENIED`, a terminal state. Grant is gated by four further checks, evaluated in the precedence order of §2.6 — carrier alignment first, then evidence freshness, then escalation, then capacity:

1. **Carrier alignment.** The evidence service complaint's carrier must be the petition's `incumbent_carrier_id`, failing which `ERR_SERVICE_COMPLAINT_CARRIER_MISMATCH` (HTTP 422).
2. **Evidence freshness.** The evidence complaint must have been created no more than 84 days before the petition — that is, the difference between the petition's `created_at` and the evidence complaint's `created_at` may not exceed 84 days. An older complaint fails with `ERR_SERVICE_FAILURE_WINDOW_EXPIRED` (HTTP 422); a difference of exactly 84 days is still within the window.
3. **Escalation.** The evidence complaint must be in `ESCALATED` status at decide time — existence was validated at creation, but eligibility is re-validated now, and a complaint that was resolved in the meantime fails with `ERR_PETITION_EVIDENCE_NOT_ESCALATED` (HTTP 409).
4. **Slot capacity.** Each interchange accommodates at most four overlapping granted switching windows. Counting this petition's own `interchange_code`, the number of already-`GRANTED` petitions whose windows overlap the requested window under half-open semantics — the window runs from `service_start_date` inclusive to `service_end_date` exclusive, so two windows that merely touch, one ending on the day another begins, do not overlap — must be fewer than 4. A grant that would produce a fourth overlapping granted window is rejected with `ERR_INTERCHANGE_CAPACITY_EXCEEDED` (HTTP 409).

A successful grant moves the petition to `GRANTED` and consumes one switching slot on the `interchange_code` for the requested window. Later, the Board may terminate a granted petition — one in any other state rejects termination with `ERR_PETITION_NOT_GRANTED` (HTTP 409) — moving it to `TERMINATED`, a terminal state, and releasing the consumed slot as the compensating action for the grant.

## 4. Endpoint Definitions

All endpoints are mounted under the `/stb` prefix shown in each path below. Status code rules are uniform: an endpoint that creates a new resource responds 201 Created; reads, actions, and modifications of an existing resource respond 200 OK. Request bodies, computed fields, side effects, and the precise error each guard raises are specified in §2 and §3; this table is the index, not the contract.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/stb/_clock/set_current_utc` | Set the logical clock (startup default is exactly `2026-09-01T00:00:00Z`) | PlatformAdmin |
| POST | `/stb/carriers` | Register a railroad carrier | PlatformAdmin |
| GET | `/stb/carriers/{id}` | Read a carrier including all computed fields | PlatformAdmin, BoardAdjudicator, Shipper, CarrierOperator |
| GET | `/stb/carriers/{id}/revenue-adequacy-findings` | List revenue adequacy findings filed for a carrier | PlatformAdmin, BoardAdjudicator, Shipper, CarrierOperator |
| GET | `/stb/carriers/{id}/rate-complaints` | List rate complaints filed against a carrier | PlatformAdmin, BoardAdjudicator, Shipper, CarrierOperator |
| GET | `/stb/carriers/{id}/service-complaints` | List service complaints filed against a carrier | PlatformAdmin, BoardAdjudicator, Shipper, CarrierOperator |
| GET | `/stb/carriers/{id}/emergency-service-orders` | List emergency service orders directed at a carrier | PlatformAdmin, BoardAdjudicator, Shipper, CarrierOperator |
| GET | `/stb/carriers/{id}/merger-applications` | List merger applications where the carrier is acquirer or target | PlatformAdmin, BoardAdjudicator, Shipper, CarrierOperator |
| GET | `/stb/carriers/{id}/abandonment-applications` | List abandonment applications filed by a carrier | PlatformAdmin, BoardAdjudicator, Shipper, CarrierOperator |
| GET | `/stb/carriers/{id}/reciprocal-switching-petitions` | List reciprocal switching petitions naming a carrier as incumbent | PlatformAdmin, BoardAdjudicator, Shipper, CarrierOperator |
| POST | `/stb/carriers/{id}/revenue-adequacy-findings` | File the annual report and publish the revenue adequacy finding for a fiscal year | BoardAdjudicator |
| POST | `/stb/rate-complaints` | Shipper files a rate reasonableness complaint | Shipper |
| GET | `/stb/rate-complaints/{id}` | Read a rate complaint | PlatformAdmin, BoardAdjudicator, Shipper, CarrierOperator |
| POST | `/stb/rate-complaints/{id}/determine-market-dominance` | Board issues the threshold market dominance determination | BoardAdjudicator |
| POST | `/stb/rate-complaints/{id}/evidence` | Submit evidentiary material (SAC study, three-benchmark packet, or rebuttal) | Shipper, CarrierOperator |
| GET | `/stb/rate-complaints/{id}/evidence` | List evidence submissions on a complaint | PlatformAdmin, BoardAdjudicator, Shipper, CarrierOperator |
| POST | `/stb/evidence-submissions/{id}/verify` | Board verifies or rejects an evidence submission | BoardAdjudicator |
| POST | `/stb/rate-complaints/{id}/decide` | Board decides the complaint on the merits or dismisses for lack of market dominance | BoardAdjudicator |
| POST | `/stb/rate-complaints/{id}/reopen` | Shipper petitions to reopen a decided complaint | Shipper |
| POST | `/stb/rate-complaints/{id}/reparation-events` | Carrier posts a reparation PAYMENT; Board posts a REVERSAL (only when nothing paid) | CarrierOperator, BoardAdjudicator |
| POST | `/stb/service-complaints` | Shipper files a service complaint against a carrier | Shipper |
| GET | `/stb/service-complaints/{id}` | Read a service complaint | PlatformAdmin, BoardAdjudicator, Shipper, CarrierOperator |
| GET | `/stb/service-complaints/{id}/emergency-service-orders` | List emergency service orders issued from a service complaint | PlatformAdmin, BoardAdjudicator, Shipper, CarrierOperator |
| POST | `/stb/service-complaints/{id}/resolve` | Board marks a service complaint resolved; lifts any active ESO | BoardAdjudicator |
| POST | `/stb/service-complaints/{id}/escalate` | Board escalates a service complaint by issuing an emergency service order | BoardAdjudicator |
| POST | `/stb/merger-applications` | Acquiring carrier files a merger application; comment period opens immediately | CarrierOperator |
| GET | `/stb/merger-applications/{id}` | Read a merger application | PlatformAdmin, BoardAdjudicator, Shipper, CarrierOperator |
| POST | `/stb/merger-applications/{id}/amend` | Amend a merger application's showings; resets the comment window (OCC-guarded) | CarrierOperator |
| POST | `/stb/merger-applications/{id}/decide` | Board decides a merger application on public interest standards | BoardAdjudicator |
| POST | `/stb/merger-applications/{id}/service-assurance-plans` | File a service assurance plan on a merger application (at most one) | CarrierOperator |
| GET | `/stb/merger-applications/{id}/service-assurance-plans` | List service assurance plans on a merger application | PlatformAdmin, BoardAdjudicator, Shipper, CarrierOperator |
| POST | `/stb/abandonment-applications` | Carrier files a line abandonment/discontinuance application | CarrierOperator |
| GET | `/stb/abandonment-applications/{id}` | Read an abandonment application | PlatformAdmin, BoardAdjudicator, Shipper, CarrierOperator |
| POST | `/stb/abandonment-applications/{id}/decide` | Board issues the public convenience and necessity finding and grants or denies | BoardAdjudicator |
| POST | `/stb/abandonment-applications/{id}/issue-trail-use-notice` | Board issues a Notice of Interim Trail Use, opening the 180-day negotiation window | BoardAdjudicator |
| POST | `/stb/abandonment-applications/{id}/convert-to-trail-use` | Convert the line to interim trail use (railbanking) within the NITU window | BoardAdjudicator |
| POST | `/stb/abandonment-applications/{id}/consummate-abandonment` | Consummate the abandonment; from TRAIL_PENDING only after the NITU window lapses | BoardAdjudicator |
| POST | `/stb/reciprocal-switching-petitions` | Shipper petitions for reciprocal switching / interchange access | Shipper |
| POST | `/stb/reciprocal-switching-petitions/{id}/decide` | Board grants or denies a reciprocal switching petition | BoardAdjudicator |
| POST | `/stb/reciprocal-switching-petitions/{id}/terminate` | Board terminates a granted petition, releasing its interchange slot | BoardAdjudicator |

## 5. Error Code Catalogue

Trigger conditions for every error are specified in the narratives of §2 and §3; this catalogue fixes only the identifier-to-status mapping.

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_INVALID_REQUEST | 400 |
| ERR_FORBIDDEN_ROLE | 403 |
| ERR_NOT_RESOURCE_OWNER | 403 |
| ERR_CARRIER_NOT_FOUND | 404 |
| ERR_RATE_COMPLAINT_NOT_FOUND | 404 |
| ERR_EVIDENCE_NOT_FOUND | 404 |
| ERR_SERVICE_COMPLAINT_NOT_FOUND | 404 |
| ERR_MERGER_APPLICATION_NOT_FOUND | 404 |
| ERR_ABANDONMENT_APPLICATION_NOT_FOUND | 404 |
| ERR_PETITION_NOT_FOUND | 404 |
| ERR_COMPLAINT_NOT_FILED | 409 |
| ERR_COMPLAINT_NOT_IN_EVIDENTIARY | 409 |
| ERR_COMPLAINT_NOT_DECIDED | 409 |
| ERR_EVIDENCE_ALREADY_REVIEWED | 409 |
| ERR_SERVICE_COMPLAINT_NOT_OPEN | 409 |
| ERR_MERGER_NOT_IN_COMMENT_PERIOD | 409 |
| ERR_ABANDONMENT_NOT_UNDER_REVIEW | 409 |
| ERR_ABANDONMENT_NOT_GRANTED | 409 |
| ERR_ABANDONMENT_NOT_TRAIL_PENDING | 409 |
| ERR_PETITION_NOT_FILED | 409 |
| ERR_PETITION_NOT_GRANTED | 409 |
| ERR_REVENUE_ADEQUACY_FINDING_REQUIRED | 409 |
| ERR_NO_VERIFIED_EVIDENCE | 409 |
| ERR_MARKET_DOMINANCE_ABSENT | 409 |
| ERR_MARKET_DOMINANCE_PRESENT | 409 |
| ERR_MERGER_SERVICE_HOLD | 409 |
| ERR_SERVICE_ASSURANCE_PLAN_REQUIRED | 409 |
| ERR_DECISION_INCONSISTENT_WITH_SCORE | 422 |
| ERR_DECISION_INCONSISTENT_WITH_FINDING | 422 |
| ERR_SERVICE_COMPLAINT_CARRIER_MISMATCH | 422 |
| ERR_SERVICE_FAILURE_WINDOW_EXPIRED | 422 |
| ERR_PETITION_EVIDENCE_NOT_ESCALATED | 409 |
| ERR_COMMENT_PERIOD_OPEN | 409 |
| ERR_TRAIL_USE_NOTICE_EXPIRED | 409 |
| ERR_TRAIL_USE_WINDOW_OPEN | 409 |
| ERR_DUPLICATE_CARRIER_CODE | 409 |
| ERR_DUPLICATE_FINDING | 409 |
| ERR_ESO_ALREADY_ACTIVE | 409 |
| ERR_DUPLICATE_ACTIVE_PETITION | 409 |
| ERR_SERVICE_ASSURANCE_PLAN_EXISTS | 409 |
| ERR_DUPLICATE_ACTIVE_ABANDONMENT | 409 |
| ERR_INTERCHANGE_CAPACITY_EXCEEDED | 409 |
| ERR_FACILITY_BEYOND_INTERCHANGE_DISTANCE | 422 |
| ERR_PAYMENT_EXCEEDS_OUTSTANDING | 402 |
| ERR_AWARD_HAS_PAYMENTS | 409 |
| ERR_STALE_VERSION | 412 |
