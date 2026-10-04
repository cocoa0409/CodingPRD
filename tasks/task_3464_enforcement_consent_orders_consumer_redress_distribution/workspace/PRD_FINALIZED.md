# Enforcement Consent Orders API — Product Requirements Document

## 1. Introduction

Consumer protection enforcement produces a long, interconnected paper trail: a matter begins as a trickle of complaints, a referral, or an anomaly in market monitoring; it escalates through compulsory process; and — when the evidence supports it — it resolves into a negotiated consent order that binds a company for years. This document specifies the Enforcement Consent Orders API, the system of record for that pipeline as administered by the Federal Trade Commission. The API covers investigation intake and advancement, the drafting and enforcement of civil investigative demands, settlement negotiation culminating in proposed consent agreements exposed to public comment, multi-year order compliance monitoring with reporting obligations and per-violation civil penalties, entry and collection of monetary judgments (including asset tracing and inability-to-pay suspension), and the administration of consumer redress funds from claimant identification through claims adjudication, refund check issuance, and final residual disposition.

The API is a role-segregated, workflow-driven service: eight distinct roles cooperate across the lifecycle, and several operations deliberately require a different actor than the one who performed an earlier step. All enforcement resources are mounted under the `/enforcement` path prefix, with a single exception — a platform-level logical clock capability, described in §2.5, that lives outside the prefix. Time in this system is logical rather than wall-clock: response deadlines, comment-period closings, check staleness, and monitoring-term expirations are all evaluated against a controllable clock, which makes every temporal rule in this document deterministic.

## 2. Global Specifications & System-Wide Principles

This section defines the cross-cutting contracts every endpoint obeys: authentication, response shape, pagination, resource metadata, the logical clock, concurrency control, monetary precision, and the ordered validation cascade.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. A request missing either header, or carrying an empty value for either, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). The system recognizes exactly eight roles, spelled as follows: `PlatformAdmin`, `StaffAttorney`, `Commissioner`, `ComplianceMonitor`, `FundAdministrator`, `DisbursementOfficer`, `CompanyRepresentative`, and `Claimant`.

Role capabilities differ sharply. A `PlatformAdmin` is the agency platform operator: it registers subject companies and drives the logical clock. A `StaffAttorney` opens and advances investigations, issues civil investigative demands, drafts and proposes consent orders, and records asset traces. A `Commissioner` finalizes consent orders, places them into monitoring, terminates them, enters monetary judgments, and rules on inability-to-pay suspensions. A `ComplianceMonitor` reviews compliance reports and assesses, confirms, or waives violation penalties. A `FundAdministrator` identifies claimants, adjudicates claims, and advances the redress fund lifecycle. A `DisbursementOfficer` issues, cashes, and voids refund checks. A `CompanyRepresentative` speaks for a subject company: responding to demands, submitting compliance reports, and paying judgments and penalties. A `Claimant` is an identified consumer filing their own redress claim. Every one of the eight roles may call any GET endpoint; write access is partitioned per §4. A request whose role is not permitted for the endpoint — or, on a transition endpoint, not permitted for the requested `target_state` — is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

Identity semantics differ by role. When `X-User-Role` is `CompanyRepresentative`, `X-User-ID` is the `id` of the acting `SubjectCompany`; ownership checks on any resource that references a `SubjectCompany` compare the resource's foreign-key field to `X-User-ID`. When `X-User-Role` is `Claimant`, `X-User-ID` is the `id` of the acting `Claimant`, and the same comparison rule applies to resources that reference a `Claimant`. When `X-User-Role` is `PlatformAdmin`, `StaffAttorney`, `Commissioner`, `ComplianceMonitor`, `FundAdministrator`, or `DisbursementOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `opened_by_user_id` on an `Investigation` or as `negotiating_attorney_user_id` on a `ConsentOrder`) but does not compare it to any entity's `id` — except where a segregation-of-duties rule explicitly requires two operators to differ.

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

List endpoints paginate through two query parameters. `limit` sets the maximum number of items returned: it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` sets the number of items to skip and defaults to 0. Unless an endpoint states otherwise, list responses are sorted by `created_at` in ascending order; the public-comment-period listing is the single exception and is ordered by `round` ascending. Paginated list responses include `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. Common Resource Properties

All twelve resource types in this system — `SubjectCompany`, `Investigation`, `CivilInvestigativeDemand`, `ConsentOrder`, `PublicCommentPeriod`, `ComplianceReport`, `ViolationPenalty`, `MonetaryJudgment`, `RedressFund`, `Claimant`, `Claim`, and `RefundCheck` — carry a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set when the resource is first created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed upon any change to the resource, including changes caused by cascaded side effects from operations on other resources.
- `version` (integer): a system-managed integer that increments with every modification to the resource, including cascaded ones. This field backs the optimistic concurrency control rules of §2.6.

No resource in this system is exempt from this convention: even resources that come into existence purely as side effects of another operation (a comment period opened by a proposal, a redress fund created by a judgment) carry the full set.

### 2.5. The Logical Clock and Automatic Lifecycle Sweeps

The system never reads wall-clock time. All temporal evaluation — deadlines, period closings, staleness, expiry — runs against a **logical clock** whose initial reading, before any operator intervention, is exactly `2026-09-01T00:00:00Z`. A `PlatformAdmin` may advance this clock through a test-driving capability that lives outside the `/enforcement` prefix: `POST /_clock/set_current_utc`, carrying a `to_iso8601` timestamp and returning the new `current_utc` reading.

Every clock advance performs an automatic transition sweep across three lifecycles:

1. Any public comment period still `OPEN` whose `closes_at` instant has been reached or passed transitions to `CLOSED`. At exactly `closes_at` the period is already closed — the open interval is half-open on its closing boundary — and further comments are rejected from that instant onward.
2. Any refund check still `ISSUED` whose `stale_after` instant has been reached or passed transitions to `STALE`. At exactly `stale_after` the check is stale.
3. Any consent order in `IN_MONITORING` transitions to `EXPIRED` only once the clock is strictly later than the order's `monitoring_ends_at`. At exactly `monitoring_ends_at` the order remains `IN_MONITORING`; expiry requires the clock to move past the boundary.

Note the deliberate asymmetry: comment-period closing and check staleness trigger at the boundary instant itself, while monitoring expiry triggers strictly after it.

### 2.6. Optimistic Concurrency Control on Order and Fund Transitions

Two write endpoints in this system are guarded by optimistic concurrency control, and both take a mandatory version field:

- A request to `POST /enforcement/consent-orders/{orderId}/transition` must carry `expected_consent_order_version`, holding the client's last observed `version` of the target consent order. If that value no longer matches the order's current `version` — because the client's view predates a committed transition, such as a withdrawal-and-reproposal that already advanced the version — the request is rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412) rather than applied on a moved base.
- A request to `POST /enforcement/redress-funds/{fundId}/transition` must carry `expected_redress_fund_version`, holding the client's last observed `version` of the target redress fund. Claim approvals and payment-cascade ledger syncs advance the fund's `version` between an administrator's last read and the transition call; a mismatch proves the administrator's view is out of date, and the request is rejected with `ERR_STALE_FUND_VERSION` (HTTP 412).

Endpoints not listed here do not take a version field. Within the guarded endpoints, the version check fires only after the request has survived the state-legality check (see the validation cascade in §2.8).

### 2.7. Money, Rates, and Rounding Discipline

Every monetary amount in this API is an integer number of cents. No floating-point money appears anywhere: judgment amounts, penalty figures, fund ledger fields, claim losses, awards, and check amounts are all integer cents.

Several calculation families share this integer discipline, each with its own rounding rule stated here once and referenced from §3:

- Complaint-velocity thresholds are pure integer comparisons with no rounding.
- Civil penalty day counts are floored to whole days and can never be less than 1 day; penalty amounts are integer cents produced by multiplying a per-day rate by a day count, then capping. The per-day civil penalty rates are 1,000,000 cents for a `STANDARD` violation, 4,353,000 cents for an `AGGRAVATED` violation, and 5,000,000 cents for an `EGREGIOUS` violation.
- The redress waterfall computes the administration reserve by taking ten percent of total eligible loss rounded up (ceiling) to a whole cent, then caps it; individual awards are floored to whole cents per claim *first*, and only then is the leftover remainder distributed one cent at a time to claims in `created_at` ascending order — earliest approved claim first, never ordered by `id`.
- The residual claim-rate comparison is an exact rational comparison: a rate of exactly 0.60 qualifies for cy pres disposition.
- Timestamps are compared at second precision, with boundary inclusivity as stated per rule (§2.5 and §3).

### 2.8. The Validation Cascade

Every mutating request is validated against an ordered cascade. When several checks could fail, the one at the lowest priority number fires first and determines the error the client sees; later checks are not evaluated. The cascade, in firing order:

1. **Authentication context** — `X-User-ID` and `X-User-Role` present and non-empty, else `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. Applies to all endpoints.
2. **Role authorization** — the role is permitted for the endpoint and, on target-scoped transition endpoints, for the requested `target_state`, else `ERR_INSUFFICIENT_PERMISSIONS`. Applies to all endpoints.
3. **Path existence** — templated path identifiers resolve left-to-right (see §2.9), else the entity-specific `ERR_*_NOT_FOUND`.
4. **Request well-formedness** — required fields present, enum values within their declared sets, integer and datetime types valid, else `ERR_INVALID_REQUEST`. Applies to all POST endpoints.
5. **State legality** — the target entity's current state permits the requested transition or action, else `ERR_INVALID_STATE_TRANSITION`; this tier also carries `ERR_JUDGMENT_SUSPENDED` for payments or reversals on a `SUSPENDED` judgment and `ERR_FUND_NOT_DISBURSING` for check issuance while the fund is not `DISBURSING`. Applies to all transition and action endpoints.
6. **Optimistic concurrency** — `expected_consent_order_version` or `expected_redress_fund_version` matches the parent's current `version`, else `ERR_STALE_ORDER_VERSION` or `ERR_STALE_FUND_VERSION`. Applies only to the consent-order and redress-fund transition endpoints named in §2.6.
7. **Segregation of duties** — the confirming or waiving monitor differs from the assessing monitor (`ERR_SOD_PENALTY_CONFIRM`), and the issuing officer differs from the claim approver (`ERR_SOD_CHECK_ISSUE`). Applies to penalty transitions and refund-check issuance.
8. **Regulatory cooling-off** — a consent order's finalization requires its latest public comment period (highest `round`) to be `CLOSED`, else `ERR_COMMENT_PERIOD_OPEN`. Applies to order finalization only.
9. **Deadline discipline** — a CID response must arrive before `response_due_date` (`ERR_CID_RESPONSE_OVERDUE`), a public comment must arrive while the period is `OPEN` (`ERR_COMMENT_PERIOD_CLOSED`), and a check reissue must arrive before the original check's `reissue_deadline` (`ERR_REISSUE_WINDOW_EXPIRED`).
10. **Interval overlap** — a new compliance report's closed interval must not overlap a non-deficient report's interval on the same order (`ERR_REPORTING_PERIOD_OVERLAP`), and an order entering monitoring must not overlap another monitoring order of the same company (`ERR_MONITORING_TERM_OVERLAP`). Applies to compliance-report submission and to the order's monitoring-entry transition.
11. **Uniqueness and cardinality** — at most one judgment per order (`ERR_JUDGMENT_ALREADY_EXISTS`), at most one claim per claimant (`ERR_CLAIM_ALREADY_FILED`), at most one non-voided check per claim (`ERR_CHECK_ALREADY_OUTSTANDING`).
12. **Cross-entity referential integrity** — a claim's `redress_fund_id` must equal its claimant's fund (`ERR_CLAIM_FUND_MISMATCH`), and a compliance report's submitter must be the order's subject company (`ERR_REPORT_COMPANY_MISMATCH`). The company-match check is intentionally evaluated *after* the tier-10 overlap check, so a wrong-company submission on an overlapping window reports the overlap rather than the mismatch.
13. **Ownership and aggregate gates** — claim-filing identity (`ERR_CLAIMANT_IDENTITY_MISMATCH`), subject-company ownership on CID responses, quash petitions, and judgment payments (`ERR_SUBJECT_COMPANY_MISMATCH`), claims-close requiring zero unresolved claims (`ERR_UNRESOLVED_CLAIMS_EXIST`), and residual disposition requiring all checks terminal (`ERR_CHECKS_OUTSTANDING`).
14. **Money and threshold limits** — payment within outstanding (`ERR_PAYMENT_EXCEEDS_OUTSTANDING`), reversal within collected (`ERR_REVERSAL_EXCEEDS_COLLECTED`), suspension sworn assets strictly below the ten-percent threshold (`ERR_SUSPENSION_THRESHOLD_NOT_MET`), and market-monitoring intake gated on risk tier (`ERR_MONITORING_THRESHOLD_NOT_MET`). The intake-threshold rule is grouped with the fiscal tier by domain convention: the agency gates its cheapest intake channel last, after every structural check has passed.

### 2.9. Nested Resource Retrieval and Existence Checks

When an endpoint path contains resource identifiers, the system validates them in strict left-to-right order, and the request is rejected with the entity-specific not-found error for the *first* identifier that does not resolve. A request addressing a CID under a nonexistent investigation therefore fails with `ERR_INVESTIGATION_NOT_FOUND` before the CID itself is ever consulted. The full not-found vocabulary is: `ERR_SUBJECT_COMPANY_NOT_FOUND`, `ERR_INVESTIGATION_NOT_FOUND`, `ERR_CID_NOT_FOUND`, `ERR_CONSENT_ORDER_NOT_FOUND`, `ERR_COMMENT_PERIOD_NOT_FOUND`, `ERR_COMPLIANCE_REPORT_NOT_FOUND`, `ERR_VIOLATION_PENALTY_NOT_FOUND`, `ERR_JUDGMENT_NOT_FOUND`, `ERR_REDRESS_FUND_NOT_FOUND`, `ERR_CLAIMANT_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, and `ERR_REFUND_CHECK_NOT_FOUND` — all HTTP 404.

### 2.10. Transition Side Effects and Version Discipline

State machines in this system are not isolated: transitions routinely cascade. Finalizing a consent order bubbles its parent investigation into a terminal state; recording a judgment payment syncs the redress fund and can fling it open for claims, notifying every waiting claimant; cashing or voiding a refund check moves its claim and shifts the fund's ledger. Every such mutation — whether directly requested or produced as a cascade — increments the mutated resource's `version` by exactly 1 and refreshes its `updated_at`. A single request may therefore advance the versions of several resources at once, and clients holding OCC fields (§2.6) must re-read after observing such cascades. Some resources are created only as side effects of another operation and have no standalone creation endpoint: a `PublicCommentPeriod` springs into existence when a consent order is proposed, and a `RedressFund` is created automatically when a monetary judgment is entered.

## 3. Business Logic & Workflows

This section walks the enforcement pipeline in chronological order, from case intake to fund closure. Endpoint paths are deliberately absent here — each capability is named by the state change it drives or the role that performs it, and §4 supplies the HTTP contract.

### 3.1. Case Intake: Subject Companies and Investigation Origins

A matter cannot exist until its target does. A `PlatformAdmin` registers each company under scrutiny as a `SubjectCompany`, supplying its `legal_name` and, optionally, a `complaint_count_90d` — the number of consumer complaints received against the company in the trailing ninety days, ingested from external channels and supplied at intake. When omitted, `complaint_count_90d` defaults to 0; it must always be a non-negative integer. From this single figure the system derives the company's `risk_tier`: a company with at least 50 complaints in the window is `CRITICAL`; one with at least 10 but fewer than 50 is `ELEVATED`; anything fewer than 10 is `STANDARD`. The boundaries are inclusive upward — exactly 10 complaints is `ELEVATED`, and exactly 50 is `CRITICAL`.

With a company registered, a `StaffAttorney` may open an `Investigation` against it, providing the `subject_company_id`, an `origin` of `COMPLAINT`, `REFERRAL`, or `MARKET_MONITORING`, and a free-text `summary` of the allegations. The investigation is born in `INTAKE` status, and the system records the opening attorney's identifier in `opened_by_user_id`. One intake channel is gated: market-monitoring investigations are reserved for companies already showing elevated complaint velocity, so an `origin` of `MARKET_MONITORING` is accepted only when the subject company's `risk_tier` is `ELEVATED` or `CRITICAL`; against a `STANDARD` company the filing is rejected with `ERR_MONITORING_THRESHOLD_NOT_MET`.

From `INTAKE`, the attorney advances the investigation to `PRELIMINARY_REVIEW`, thence to `EVIDENCE_GATHERING`, and thence to `NEGOTIATING`, each step requested with a `target_state`. Negotiation is fragile: an investigation in `NEGOTIATING` can collapse back into `EVIDENCE_GATHERING` when talks break down, and this loop may repeat any number of times. At any point before settlement — that is, from `INTAKE`, `PRELIMINARY_REVIEW`, or `EVIDENCE_GATHERING` — the attorney may instead close the matter as `CLOSED_NO_ACTION`. Any target state not legal from the investigation's current state is rejected with `ERR_INVALID_STATE_TRANSITION`. Two transitions are never requested directly: drafting a consent order against an investigation that has reached `NEGOTIATING` moves the investigation automatically to `SETTLED`, and the moment any consent order of a settled investigation reaches `FINAL`, the investigation bubbles up to `CLOSED_ORDER_ENTERED`. Both `CLOSED_NO_ACTION` and `CLOSED_ORDER_ENTERED` are terminal. Every transition, requested or automatic, increments the investigation's `version`.

### 3.2. Compulsory Process: The Civil Investigative Demand Lifecycle

While an investigation is gathering evidence, a `StaffAttorney` drafts civil investigative demands against the subject company. Each demand carries a `subject_matter` describing the documents or testimony demanded and a `response_due_date` fixing the company's deadline; its `investigation_id` binds it to the parent investigation. A new demand starts in `DRAFT`.

Issuance is gated on the parent: a demand can move from `DRAFT` to `ISSUED` only while its investigation sits in `EVIDENCE_GATHERING`; otherwise the transition is rejected with `ERR_INVALID_STATE_TRANSITION`. Once issued, the company holds two options. It may respond — a `CompanyRepresentative` whose identity is the subject company itself (a mismatched caller is refused with `ERR_SUBJECT_COMPANY_MISMATCH`) supplies a `response_document_ref` (omitting it is an `ERR_INVALID_REQUEST`), and the response must arrive while the logical clock is still strictly before `response_due_date`: a response attempted at or after the deadline fails with `ERR_CID_RESPONSE_OVERDUE`. A timely response moves the demand to `RESPONDED` and stamps `responded_at` with the logical time. Alternatively, the company may petition to quash, moving the demand from `ISSUED` to `QUASH_PETITIONED` under the same ownership rule.

A quash petition is answered by the courts, not the company: a `StaffAttorney` records enforcement, moving `QUASH_PETITIONED` to `ENFORCED`. Court enforcement strips the deadline's protection — a demand in `ENFORCED` may still be answered to `RESPONDED` with a `response_document_ref`, and the overdue check no longer applies to that enforced response, though the ownership rule still does. Finally, the agency may abandon a demand that has not yet been answered: withdrawal moves a demand from `DRAFT` to `WITHDRAWN` or from `ISSUED` to `WITHDRAWN` at a `StaffAttorney`'s hand. `RESPONDED` and `WITHDRAWN` are the demand's terminal states, and every transition increments the demand's `version`.

### 3.3. Settlement: Drafting, Public Comment, and Finalization of Consent Orders

When negotiation succeeds, a `StaffAttorney` drafts a `ConsentOrder` against an investigation that has reached `NEGOTIATING`. The drafting payload fixes the order's economic and behavioral terms: `monetary_relief_cents`, the total equitable monetary relief agreed in the settlement (an integer number of cents greater than zero, later mirrored into the judgment); `max_penalty_cents`, the per-violation penalty accrual cap (also an integer greater than zero); `reporting_frequency_months`, the cadence of mandatory compliance reports during monitoring, which must be one of 3, 6, or 12; `monitoring_term_years`, the length of the monitoring term in whole years, from 1 to 20; and `conduct_prohibitions`, a non-empty array of prohibition clause strings the company must observe. The order is born in `DRAFT` with `proposal_round` set to 1. The system records the drafting attorney in `negotiating_attorney_user_id` — a value later segregation-of-duties checks rely on — and denormalizes the investigation's `subject_company_id` onto the order as a frozen mirror, captured at creation and not a navigable reference. Drafting is also the settlement event itself: the parent investigation automatically transitions to `SETTLED`.

Proposing the agreement — moving the order from `DRAFT` to `IN_PUBLIC_COMMENT` — is a `StaffAttorney` action guarded by `expected_consent_order_version`. Proposal opens a `PublicCommentPeriod` on the order: the period's `consent_order_id` ties it to the order, its `round` matches the order's current `proposal_round`, its `opened_at` is the proposal instant, and its `closes_at` falls exactly 30 days later. The period starts `OPEN`, and the order's `version` increments.

While a period is `OPEN`, any authenticated role may file a public comment by supplying an `author_email` and a `body`. Each filing appends an entry — `author_email`, `body`, and the logical filing time `submitted_at` — to the period's append-only `comments` array, grows `comment_count` by one, and increments the period's `version`. The clock sweep closes the period at or after `closes_at` (§2.5), and from that instant comments are rejected; a comment filed against a period that is `CLOSED` — or `VOIDED`, after a withdrawal — fails with `ERR_COMMENT_PERIOD_CLOSED`. All of an order's comment periods, across every proposal round, can be listed together and are ordered by `round` ascending.

A proposed agreement need not survive contact with the public. A `StaffAttorney` may withdraw an order from `IN_PUBLIC_COMMENT` back to `DRAFT` (again under `expected_consent_order_version`): the order's `OPEN` comment period is voided to `VOIDED`, `proposal_round` increments by 1, and the order's `version` increments. The withdrawal-and-reproposal cycle may repeat — each reproposal opens a fresh period stamped with the new round — so an order's comment history is a sequence of rounds, at most one of them ever `OPEN`.

Finalization is reserved for a `Commissioner` and carries the regulatory cooling-off gate: moving from `IN_PUBLIC_COMMENT` to `FINAL` requires the order's latest comment period — the one with the highest `round` — to be `CLOSED`; if it is still `OPEN`, the transition fails with `ERR_COMMENT_PERIOD_OPEN`. On finalization the system stamps `finalized_at` with the logical time and records the acting commissioner in `finalized_by_user_id`, the parent investigation bubbles from `SETTLED` to `CLOSED_ORDER_ENTERED`, and the order's `version` increments.

Termination is likewise a commissioner's prerogative: an order may move from `DRAFT` to `TERMINATED` — abandoning a draft that will never be proposed — or from `IN_MONITORING` to `TERMINATED`, ending oversight early. Both carry the order's OCC field and increment its `version`. `EXPIRED` and `TERMINATED` are the order's terminal states; the road from `FINAL` into `IN_MONITORING` and on to `EXPIRED` belongs to the monitoring workflow of §3.4.

### 3.4. Monitoring the Order: Compliance Reports and Violation Penalties

A finalized order does not monitor itself. A `Commissioner` places an order into monitoring — `FINAL` to `IN_MONITORING`, under `expected_consent_order_version` — at which point the system stamps `monitoring_started_at` with the logical time and computes `monitoring_ends_at` as exactly `monitoring_term_years` years later. One company cannot be under two overlapping monitoring terms: if another consent order of the same `subject_company_id` is already `IN_MONITORING` and its half-open window — from its `monitoring_started_at` up to but not including its `monitoring_ends_at` — overlaps the new window from now up to but not including now plus `monitoring_term_years` years, the transition is rejected with `ERR_MONITORING_TERM_OVERLAP`. Because both windows are half-open, adjacency is not overlap: one term ending at the exact instant another begins is permitted. Once in monitoring, the order expires only when the clock moves strictly past `monitoring_ends_at` (§2.5), transitioning to `EXPIRED` with a version increment.

Throughout the term, the company reports on its own compliance at the agreed cadence. A `CompanyRepresentative` submits a `ComplianceReport` — permitted only while the order is `IN_MONITORING` — supplying `period_start`, `period_end`, and a `report_document_ref`. The reporting window is a closed interval, inclusive at both ends, and `period_end` must be strictly after `period_start`; anything else is an `ERR_INVALID_REQUEST`. The system records the submitter in `submitted_by_company_id`, and that identity must equal the order's `subject_company_id` — a report filed by any other company is rejected with `ERR_REPORT_COMPANY_MISMATCH`. Closed intervals are strict neighbors: a new report's interval must not overlap the interval of any existing report on the same order that is `SUBMITTED` or `ACCEPTED`, and because both ends are inclusive, merely touching endpoints already count as overlap, drawing `ERR_REPORTING_PERIOD_OVERLAP`. Intervals of reports marked `DEFICIENT` do not block resubmission of a corrected window. Recall from §2.8 that the overlap check deliberately fires before the company-match check. A fresh report enters as `SUBMITTED`.

Review belongs to a `ComplianceMonitor`. Acceptance moves `SUBMITTED` to `ACCEPTED` — the report's terminal state — recording the reviewer in `reviewed_by_user_id`. Alternatively the monitor marks the report `DEFICIENT`, which requires `deficiency_notes` (omitting them is an `ERR_INVALID_REQUEST`); the notes and the reviewer are both recorded. Deficiency is curable: the company's representative resubmits, moving `DEFICIENT` back to `SUBMITTED` with a fresh `report_document_ref` under the same subject-company ownership rule, which increments `resubmission_count` and clears `deficiency_notes`. This resubmission cycle may repeat any number of times until the report is accepted.

Monitoring also has teeth. When a monitor observes prohibited conduct, they assess a `ViolationPenalty` against the `IN_MONITORING` order, supplying a `severity` of `STANDARD`, `AGGRAVATED`, or `EGREGIOUS`, the `detected_on` date, and a `description` of the conduct. The penalty enters as `ASSESSED_PROVISIONAL` with the assessor's identifier in `assessed_by_user_id`, and the system immediately computes a forward-looking projection: `provisional_days` is fixed at 30 days, and `provisional_amount_cents` is the severity's per-day rate (§2.7) multiplied by 30, capped at the order's `max_penalty_cents`.

Confirmation converts the projection into a final figure, and it must be a second pair of eyes: a `ComplianceMonitor` moves `ASSESSED_PROVISIONAL` to `CONFIRMED` by supplying `cured_on`, the date the violation was cured, which must be provided and must not fall earlier than `detected_on` (otherwise `ERR_INVALID_REQUEST`). Segregation of duties forbids self-confirmation — if the confirming monitor's identity equals `assessed_by_user_id`, the request fails with `ERR_SOD_PENALTY_CONFIRM`. On confirmation the system records `confirmed_by_user_id` and computes the final accrual: `final_days` is the number of whole days from `detected_on` to `cured_on`, floored, and never less than 1; `final_amount_cents` is the per-day rate multiplied by `final_days`, capped at the order's `max_penalty_cents`. Provisional and final figures for the same violation differ whenever the actual cure duration differs from the 30-day projection. A penalty may instead be waived — from `ASSESSED_PROVISIONAL` to `WAIVED`, or from `CONFIRMED` to `WAIVED` — again only by a monitor other than the assessor, under the same `ERR_SOD_PENALTY_CONFIRM` rule. Payment closes the loop: the subject company's representative moves a `CONFIRMED` penalty to `PAID`, under the usual ownership rule (`ERR_SUBJECT_COMPANY_MISMATCH` for anyone else). `PAID` and `WAIVED` are terminal.

### 3.5. Judgment Collection and Inability-to-Pay Suspensions

A consent order's monetary relief becomes collectible when a `Commissioner` enters a `MonetaryJudgment` for an order that is `FINAL` or already `IN_MONITORING`, supplying the `amount_cents` (an integer greater than zero, mirroring the order's monetary relief). An order carries at most one judgment; a second entry attempt fails with `ERR_JUDGMENT_ALREADY_EXISTS`. The judgment opens with `collection_status` of `OUTSTANDING`, `suspension_status` of `ACTIVE`, and `collected_cents` of 0, so `outstanding_cents` initially equals the full `amount_cents`. Entering the judgment also creates the consumer-facing half of the machinery: a `RedressFund` is auto-created in `ACCUMULATING` status, linked 1:1 to the judgment through its `judgment_id`, carrying the judgment's `consent_order_id` as a denormalized mirror, and starting with `total_collected_cents` of 0.

A judgment's state is two parallel dimensions, not one line. `collection_status` — `OUTSTANDING`, `PARTIALLY_COLLECTED`, or `SATISFIED` — evolves with payments; `suspension_status` — `ACTIVE`, `SUSPENDED`, or `REINSTATED` — evolves with inability-to-pay rulings. The dimensions are independent with a single coupling: while `suspension_status` is `SUSPENDED`, no payment or reversal is accepted at all, and the attempt is rejected with `ERR_JUDGMENT_SUSPENDED`. Neither dimension has a terminal state.

Collection itself is driven by the subject company. A `CompanyRepresentative` of that company records a payment by supplying an `amount_cents` and a `kind` of `COLLECTION` or `REVERSAL`. Beyond the suspension gate, two windows must be open: the linked redress fund must still be `ACCUMULATING` or `OPEN_FOR_CLAIMS` — once the fund has moved on, further payments are refused with `ERR_COLLECTION_WINDOW_CLOSED` — and the amounts must fit the ledger: a `COLLECTION` may not exceed the judgment's `outstanding_cents` (`ERR_PAYMENT_EXCEEDS_OUTSTANDING`), and a `REVERSAL` may not exceed the `collected_cents` already booked (`ERR_REVERSAL_EXCEEDS_COLLECTED`). Each accepted payment adds to (or, for a reversal, subtracts from) `collected_cents` — which always equals the sum of collection payments minus the sum of reversals — and `outstanding_cents` is recomputed as `amount_cents` minus `collected_cents`. The linked fund's `total_collected_cents` is synced to the judgment's `collected_cents` on every payment and reversal, and the judgment's `version` increments each time. Collection status follows the money: a payment that leaves collected above zero but short of the full amount moves `OUTSTANDING` to `PARTIALLY_COLLECTED` (further partial activity keeps it there); reaching exactly the full amount moves to `SATISFIED`, whether achieved in one full payment from `OUTSTANDING` or by topping off from `PARTIALLY_COLLECTED`; and a reversal that drains `collected_cents` back to zero returns the judgment from `PARTIALLY_COLLECTED` to `OUTSTANDING`.

That sync is also the fund's ignition. The moment a payment or reversal leaves the fund's `total_collected_cents` at or above the 1,000,000-cent opening minimum while the fund is `ACCUMULATING`, the fund automatically transitions to `OPEN_FOR_CLAIMS`, every claimant of the fund still in `IDENTIFIED` is flipped to `NOTIFIED` with `notified_at` stamped at the logical time, and the fund's `version` increments. This opening transition is system-only: a manual transition request targeting `OPEN_FOR_CLAIMS` is rejected with `ERR_INVALID_STATE_TRANSITION`.

When a company genuinely cannot pay, a `Commissioner` may suspend collection — `ACTIVE` to `SUSPENDED` — on a sworn showing: the request must supply `sworn_total_assets_cents` (omission is an `ERR_INVALID_REQUEST`), and the sworn total must be strictly less than one-tenth of the judgment's current `outstanding_cents`; at or above that threshold the request fails with `ERR_SUSPENSION_THRESHOLD_NOT_MET`. The sworn total is recorded on the judgment, `collection_status` is untouched, and the judgment's `version` increments. Reinstatement — `SUSPENDED` to `REINSTATED`, likewise by a `Commissioner` — requires evidence on file: the judgment's `asset_trace_log` must be non-empty (otherwise `ERR_NO_COMPLETED_ASSET_TRACE`), and the most recent trace by `traced_at` must report `found_assets_cents` of at least one-tenth of the current `outstanding_cents` (otherwise `ERR_SUSPENSION_THRESHOLD_NOT_MET`). A successful reinstatement increments the judgment's `version`.

That evidence comes from asset tracing. A `StaffAttorney` records each completed trace against a judgment by supplying `found_assets_cents` and a `trace_ref`; the system appends an entry — `found_assets_cents`, `trace_ref`, and the logical timestamp `traced_at` — to the judgment's append-only `asset_trace_log` and increments its `version`.

### 3.6. Redress Fund Accumulation, Claimant Identification, and Claims Review

The auto-created `RedressFund` is a ledger as much as a state machine. Alongside `total_collected_cents` — a mirror of the judgment's collected figure, re-synced on every payment and reversal — it carries a family of computed amounts: `admin_reserve_cents`, the reserve carved out for administration; `distributable_pool_cents`, what remains for consumers after the reserve; `allocated_cents`, the sum of final awards committed but not yet disbursed or released; `disbursed_cents`, the sum sitting on cashed refund checks; `available_cents`, the pool minus allocations and disbursements (the figure residual disposition later sweeps); `residual_cents`, the amount moved out at disposition; `residual_disposition`, which starts as `NONE`; and `residual_recipient_name`. These fields are derived, never written directly, and §3.6 through §3.8 pin each one's update rule.

Consumers enter the picture as claimants. While the fund is `ACCUMULATING` or `OPEN_FOR_CLAIMS`, a `FundAdministrator` identifies claimants — from the settling company's own records or from claims intake — supplying each consumer's `full_name`, `email`, and an `identified_from` of `COMPANY_RECORDS` or `CLAIMS_PROCESS`. A claimant starts `IDENTIFIED`, with one immediate exception: if the fund is already `OPEN_FOR_CLAIMS` at identification time, the claimant is notified on the spot, moving straight to `NOTIFIED` with `notified_at` stamped. Otherwise notification arrives with the fund's automatic opening cascade described in §3.5.

Only a notified consumer may file. A `Claimant` files a claim supplying `claimant_id`, `redress_fund_id`, and a `documented_loss_cents` greater than zero. Three guards protect filing: the caller's identity must equal the `claimant_id` being filed for — anyone else draws `ERR_CLAIMANT_IDENTITY_MISMATCH`; the `redress_fund_id` named must equal the claimant's own fund, else `ERR_CLAIM_FUND_MISMATCH`; and each claimant gets exactly one claim, so a second filing fails with `ERR_CLAIM_ALREADY_FILED`. Filing is possible only while the fund is `OPEN_FOR_CLAIMS` and the claimant is `NOTIFIED`; attempts outside that window are rejected as invalid state transitions. A successful filing creates the claim in `FILED` status and automatically advances the claimant from `NOTIFIED` to `CLAIMED`.

Review is the `FundAdministrator`'s desk. A claim moves from `FILED` to `UNDER_REVIEW`, and from there the administrator either denies or approves. Denial requires a `denial_reason` (omission is an `ERR_INVALID_REQUEST`) and lands in `DENIED`, which is terminal. Approval — `UNDER_REVIEW` to `APPROVED` — is permitted only while the fund remains `OPEN_FOR_CLAIMS`, and it does real arithmetic. On each approval the system records `approved_by_user_id`, sets the claim's `eligible_loss_cents` to the smaller of its `documented_loss_cents` and the standing loss cap of 2,500,000 cents, and then recomputes `provisional_award_cents` for *every* `APPROVED` claim of the fund against the currently collected money. The approving claim's `version` increments, and the fund's `version` increments as well — the recomputation is a derived-field reconciliation on the fund's claims, and the fund must reflect it. Because provisional awards are recomputed on every approval against the current `APPROVED` set and the current collections, an early-approved claim's provisional award can shrink as later claims are approved against the same pool; nothing is final until disbursement.

The award arithmetic is a pinned-order waterfall; the steps must not be reordered, because each depends on the previous:

1. For every `APPROVED` claim of the fund, take the eligible loss — the smaller of `documented_loss_cents` and the 2,500,000-cent cap — and sum them into the total eligible loss. With no approved claims, the total is 0.
2. The administration reserve is the smaller of two figures: ten percent of the total eligible loss, rounded up to a whole cent, and the fixed reserve cap of 500,000 cents.
3. The distributable pool is the fund's `total_collected_cents` minus the administration reserve.
4. Awards: if the total eligible loss is 0, every award is 0. If the pool covers the total eligible loss, every claim is awarded its full eligible loss. Otherwise awards are pro-rata: each claim's award is its eligible share of the pool floored to a whole cent *first* — pool multiplied by the claim's eligible loss, divided by the total eligible loss, rounded down — and only then is the leftover remainder distributed one cent at a time to claims in `created_at` ascending order, earliest approved claim first and never ordered by `id`, until the remainder is exhausted.

When intake and adjudication are done, the administrator closes the claims window — `OPEN_FOR_CLAIMS` to `CLAIMS_CLOSED`, under `expected_redress_fund_version`. Closing is blocked while any claim of the fund remains `FILED` or `UNDER_REVIEW`, surfacing `ERR_UNRESOLVED_CLAIMS_EXIST`; denied and approved claims do not block. On closing, steps 1 through 3 of the waterfall run again, refreshing `admin_reserve_cents` and `distributable_pool_cents` against the now-final claim set, and the fund's `version` increments.

### 3.7. Disbursement: Refund Check Issuance, Cashing, and Reissue

With claims closed, the administrator turns the fund to disbursement — `CLAIMS_CLOSED` to `DISBURSING`, under `expected_redress_fund_version`. This is the freezing point of the waterfall: the final variant runs exactly once, against the frozen `APPROVED` set and the frozen collection figure, and writes `final_award_cents` onto every `APPROVED` claim, never to be recomputed. The fund's `allocated_cents` becomes the sum of those final awards, `available_cents` becomes the distributable pool minus that allocation, and the fund's `version` increments.

A `DisbursementOfficer` then issues a refund check for each `APPROVED` claim. Issuance requires the fund to be `DISBURSING` — against any other fund state the request fails with `ERR_FUND_NOT_DISBURSING` — and it carries the second segregation-of-duties rule of the system: the issuing officer's identity must differ from the `approved_by_user_id` recorded on the claim, else `ERR_SOD_CHECK_ISSUE`. Each claim supports at most one live check: while a check in `ISSUED`, `STALE`, or `CASHED` exists for the claim, another issuance is refused with `ERR_CHECK_ALREADY_OUTSTANDING`. The issued check freezes the claim's `final_award_cents` into its own `amount_cents`, stamps `issued_at` with the logical time, computes `stale_after` as 90 days after issuance and `reissue_deadline` as 180 days after issuance, records the `claim_id` and a denormalized mirror of the claim's `redress_fund_id`, and leaves `original_check_id` null on a first issuance. Every check is stamped with the standing `fraud_warning_text`: "WARNING: The FTC never requires payment or personal information to cash a refund check. Anyone who demands money or information in exchange for your refund is a scammer." Issuance moves the claim from `APPROVED` to `PAYMENT_PENDING`.

Cashing is the happy path. A `DisbursementOfficer` moves an `ISSUED` check to `CASHED`: `cashed_at` is stamped, the claim cascades from `PAYMENT_PENDING` to `PAID`, and the fund's ledger syncs — `allocated_cents` falls by the check's amount while `disbursed_cents` rises by the same amount, with the fund's `version` incrementing. Checks that go uncashed do not linger: the clock sweep moves an `ISSUED` check to `STALE` once the clock reaches or passes its `stale_after` instant, and at exactly `stale_after` the check is already stale.

Voiding is the correction mechanism, and it always compensates. A `DisbursementOfficer` voids a check in `ISSUED` or `STALE` — the only voidable states — by supplying a `voided_reason` (omission is an `ERR_INVALID_REQUEST`). The reason is recorded, and because only uncashed checks can be voided, the claim always cascades back from `PAYMENT_PENDING` to `APPROVED`, reopening it for a replacement; the void simultaneously releases the allocation, so the fund's `allocated_cents` falls by the check's amount, `available_cents` rises by the same amount, and the fund's `version` increments.

Reissue completes the loop: once the claim stands `APPROVED` again, a replacement check may be issued for it — but only within the original check's reissue window. The attempt succeeds strictly before the `reissue_deadline` of the original check in the chain; at or after that instant it fails with `ERR_REISSUE_WINDOW_EXPIRED`. The replacement check's `original_check_id` points at the `VOIDED` check it reissues, forming the audit chain. `CASHED` and `VOIDED` are a check's terminal states.

### 3.8. Residual Disposition and Fund Closure

When disbursement has run its course — every check cashed, voided, or reissued into one of those outcomes — the administrator moves the fund from `DISBURSING` to `RESIDUAL_DISPOSITION`, under `expected_redress_fund_version` and carrying a `residual_recipient_name` (omission is an `ERR_INVALID_REQUEST`). The gate is absolute: every refund check of the fund's claims must already sit in `CASHED` or `VOIDED`, so a single check still `ISSUED` or `STALE` blocks the transition with `ERR_CHECKS_OUTSTANDING`.

The transition decides where the leftover money goes by measuring how well the program reached its consumers. The final claim rate is the number of the fund's claims that reached `APPROVED` at any point — claims now standing in `APPROVED` or `PAID`, excluding both `DENIED` claims and any claim that never left `FILED` or `UNDER_REVIEW` before the window closed — divided by the total count of the fund's claimant records in any status; a fund with no claimants at all has a claim rate of 0. If the rate is at least 0.60, `residual_disposition` is set to `CY_PRES` — and exactly 0.60 qualifies — otherwise it is set to `TREASURY_ESCHEAT`. Either way, `residual_cents` captures the fund's remaining `available_cents` — the uncashed and unawarded money — `available_cents` falls to 0, the `residual_recipient_name` is recorded, and the fund's `version` increments. The fraud warning stamped on every check exists precisely because uncashed checks are common enough to move this number: scammers target refund recipients, and every consumer frightened away from cashing a real check pushes the fund toward escheatment.

Closure is the administrator's final act: from `RESIDUAL_DISPOSITION` to `CLOSED`, again under `expected_redress_fund_version`, incrementing the fund's `version`. `CLOSED` is the fund's only terminal state.

## 4. Endpoint Definitions

Operations that create a new resource — registering a company, opening an investigation, drafting a demand or an order, filing a comment, submitting a report, assessing a penalty, entering a judgment, recording a payment or an asset trace, identifying a claimant, filing a claim, or issuing a check — return `201 Created`. Operations that modify an existing resource in place, including every state transition and the clock-set capability, return `200 OK`, as do all reads. The full mount point for enforcement resources is `/enforcement`; the single platform-level exception, the logical clock, is mounted unprefixed and appears first in the table.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------- |
| POST | `/_clock/set_current_utc` | Advance the logical clock and run the automatic transition sweep | PlatformAdmin |
| POST | `/enforcement/subject-companies` | Register a subject company | PlatformAdmin |
| GET | `/enforcement/subject-companies/{companyId}` | Get a subject company | PlatformAdmin, StaffAttorney, Commissioner, ComplianceMonitor, FundAdministrator, DisbursementOfficer, CompanyRepresentative, Claimant |
| POST | `/enforcement/investigations` | Open an investigation against a subject company | StaffAttorney |
| GET | `/enforcement/investigations` | List investigations, filterable by `subject_company_id` and `status` | PlatformAdmin, StaffAttorney, Commissioner, ComplianceMonitor, FundAdministrator, DisbursementOfficer, CompanyRepresentative, Claimant |
| GET | `/enforcement/investigations/{investigationId}` | Get an investigation | PlatformAdmin, StaffAttorney, Commissioner, ComplianceMonitor, FundAdministrator, DisbursementOfficer, CompanyRepresentative, Claimant |
| POST | `/enforcement/investigations/{investigationId}/transition` | Move an investigation along its machine: `PRELIMINARY_REVIEW`, `EVIDENCE_GATHERING`, `NEGOTIATING`, `CLOSED_NO_ACTION` | StaffAttorney |
| POST | `/enforcement/investigations/{id}/cids` | Draft a civil investigative demand under an investigation | StaffAttorney |
| GET | `/enforcement/investigations/{id}/cids` | List civil investigative demands of an investigation, filterable by `status` | PlatformAdmin, StaffAttorney, Commissioner, ComplianceMonitor, FundAdministrator, DisbursementOfficer, CompanyRepresentative, Claimant |
| POST | `/enforcement/cids/{cidId}/transition` | Demand lifecycle: `ISSUED`, `RESPONDED` (needs `response_document_ref`), `QUASH_PETITIONED`, `ENFORCED`, `WITHDRAWN` | StaffAttorney, CompanyRepresentative |
| POST | `/enforcement/investigations/{id}/consent-orders` | Draft a consent order for an investigation in `NEGOTIATING` | StaffAttorney |
| GET | `/enforcement/investigations/{id}/consent-orders` | List consent orders of an investigation, filterable by `status` | PlatformAdmin, StaffAttorney, Commissioner, ComplianceMonitor, FundAdministrator, DisbursementOfficer, CompanyRepresentative, Claimant |
| GET | `/enforcement/consent-orders/{orderId}` | Get a consent order | PlatformAdmin, StaffAttorney, Commissioner, ComplianceMonitor, FundAdministrator, DisbursementOfficer, CompanyRepresentative, Claimant |
| POST | `/enforcement/consent-orders/{orderId}/transition` | Order lifecycle (OCC-guarded): `IN_PUBLIC_COMMENT` and `DRAFT`-withdrawal by StaffAttorney; `FINAL`, `IN_MONITORING`, `TERMINATED` by Commissioner | StaffAttorney, Commissioner |
| GET | `/enforcement/consent-orders/{id}/comment-periods` | List public comment periods of an order (all proposal rounds), ordered by `round` ascending | PlatformAdmin, StaffAttorney, Commissioner, ComplianceMonitor, FundAdministrator, DisbursementOfficer, CompanyRepresentative, Claimant |
| POST | `/enforcement/comment-periods/{periodId}/comments` | File a public comment on a proposed consent agreement; period must be `OPEN` | PlatformAdmin, StaffAttorney, Commissioner, ComplianceMonitor, FundAdministrator, DisbursementOfficer, CompanyRepresentative, Claimant |
| POST | `/enforcement/consent-orders/{id}/compliance-reports` | Submit a compliance report for an order in `IN_MONITORING` | CompanyRepresentative |
| GET | `/enforcement/consent-orders/{id}/compliance-reports` | List compliance reports of an order, filterable by `status` | PlatformAdmin, StaffAttorney, Commissioner, ComplianceMonitor, FundAdministrator, DisbursementOfficer, CompanyRepresentative, Claimant |
| POST | `/enforcement/compliance-reports/{reportId}/transition` | Report review: `ACCEPTED` / `DEFICIENT` (needs `deficiency_notes`) by ComplianceMonitor; `SUBMITTED` resubmission (needs `report_document_ref`) by CompanyRepresentative | ComplianceMonitor, CompanyRepresentative |
| POST | `/enforcement/consent-orders/{id}/violation-penalties` | Assess a violation penalty (provisional) against an order in `IN_MONITORING` | ComplianceMonitor |
| GET | `/enforcement/consent-orders/{id}/violation-penalties` | List violation penalties of an order, filterable by `status` | PlatformAdmin, StaffAttorney, Commissioner, ComplianceMonitor, FundAdministrator, DisbursementOfficer, CompanyRepresentative, Claimant |
| POST | `/enforcement/violation-penalties/{penaltyId}/transition` | Penalty lifecycle: `CONFIRMED` (needs `cured_on`, segregation of duties) / `WAIVED` (segregation of duties) / `PAID` by the subject company | ComplianceMonitor, CompanyRepresentative |
| POST | `/enforcement/consent-orders/{id}/judgment` | Enter the monetary judgment for a `FINAL` or `IN_MONITORING` order; at most one per order | Commissioner |
| GET | `/enforcement/consent-orders/{id}/judgment` | Get the judgment of an order (array of 0 or 1) | PlatformAdmin, StaffAttorney, Commissioner, ComplianceMonitor, FundAdministrator, DisbursementOfficer, CompanyRepresentative, Claimant |
| GET | `/enforcement/judgments/{judgmentId}` | Get a monetary judgment | PlatformAdmin, StaffAttorney, Commissioner, ComplianceMonitor, FundAdministrator, DisbursementOfficer, CompanyRepresentative, Claimant |
| POST | `/enforcement/judgments/{judgmentId}/payments` | Record a collection payment or a compensating reversal by the subject company | CompanyRepresentative |
| POST | `/enforcement/judgments/{judgmentId}/transition` | Suspension dimension: `SUSPENDED` (needs `sworn_total_assets_cents` below the ten-percent threshold) and `REINSTATED` (needs a qualifying asset trace) | Commissioner |
| POST | `/enforcement/judgments/{judgmentId}/asset-traces` | Record a completed asset trace against a judgment | StaffAttorney |
| GET | `/enforcement/judgments/{id}/redress-fund` | Get the redress fund linked to a judgment (array of 0 or 1) | PlatformAdmin, StaffAttorney, Commissioner, ComplianceMonitor, FundAdministrator, DisbursementOfficer, CompanyRepresentative, Claimant |
| GET | `/enforcement/redress-funds/{fundId}` | Get a redress fund with its computed ledger fields | PlatformAdmin, StaffAttorney, Commissioner, ComplianceMonitor, FundAdministrator, DisbursementOfficer, CompanyRepresentative, Claimant |
| POST | `/enforcement/redress-funds/{fundId}/transition` | Fund lifecycle (OCC-guarded): `CLAIMS_CLOSED`, `DISBURSING`, `RESIDUAL_DISPOSITION` (needs `residual_recipient_name`), `CLOSED`; `ACCUMULATING` to `OPEN_FOR_CLAIMS` is system-only | FundAdministrator |
| POST | `/enforcement/redress-funds/{id}/claimants` | Identify a claimant (from company records or claims intake) while the fund is `ACCUMULATING` or `OPEN_FOR_CLAIMS` | FundAdministrator |
| GET | `/enforcement/redress-funds/{id}/claimants` | List claimants of a fund, filterable by `status` | PlatformAdmin, StaffAttorney, Commissioner, ComplianceMonitor, FundAdministrator, DisbursementOfficer, CompanyRepresentative, Claimant |
| POST | `/enforcement/claims` | File a redress claim (caller identity must equal `claimant_id`; fund must be `OPEN_FOR_CLAIMS`; claimant `NOTIFIED`; one claim per claimant) | Claimant |
| GET | `/enforcement/claims` | List claims, filterable by `claimant_id`, `redress_fund_id`, and `status`; ordered by `created_at` ascending | PlatformAdmin, StaffAttorney, Commissioner, ComplianceMonitor, FundAdministrator, DisbursementOfficer, CompanyRepresentative, Claimant |
| GET | `/enforcement/claims/{claimId}` | Get a single claim | PlatformAdmin, StaffAttorney, Commissioner, ComplianceMonitor, FundAdministrator, DisbursementOfficer, CompanyRepresentative, Claimant |
| POST | `/enforcement/claims/{claimId}/transition` | Claim review: `UNDER_REVIEW`, `APPROVED` (recomputes provisional awards fund-wide), `DENIED` (needs `denial_reason`) | FundAdministrator |
| POST | `/enforcement/claims/{id}/checks` | Issue (or reissue) the refund check for an `APPROVED` claim of a `DISBURSING` fund; issuer must not be the claim approver; fraud warning stamped | DisbursementOfficer |
| GET | `/enforcement/claims/{id}/checks` | List refund checks of a claim (issuance and any reissues), ordered by `created_at` ascending | PlatformAdmin, StaffAttorney, Commissioner, ComplianceMonitor, FundAdministrator, DisbursementOfficer, CompanyRepresentative, Claimant |
| POST | `/enforcement/refund-checks/{checkId}/transition` | Check lifecycle: `CASHED` (claim paid, fund disburses) and `VOIDED` (claim returned to `APPROVED`, fund reallocates; needs `voided_reason`) | DisbursementOfficer |

## 5. Error Code Catalogue

The catalogue below fixes every error identifier and its HTTP status. The conditions that trigger each error are specified in the narratives of §2 and §3, not here.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_SUBJECT_COMPANY_NOT_FOUND` | 404 Not Found |
| `ERR_INVESTIGATION_NOT_FOUND` | 404 Not Found |
| `ERR_CID_NOT_FOUND` | 404 Not Found |
| `ERR_CONSENT_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_COMMENT_PERIOD_NOT_FOUND` | 404 Not Found |
| `ERR_COMPLIANCE_REPORT_NOT_FOUND` | 404 Not Found |
| `ERR_VIOLATION_PENALTY_NOT_FOUND` | 404 Not Found |
| `ERR_JUDGMENT_NOT_FOUND` | 404 Not Found |
| `ERR_REDRESS_FUND_NOT_FOUND` | 404 Not Found |
| `ERR_CLAIMANT_NOT_FOUND` | 404 Not Found |
| `ERR_CLAIM_NOT_FOUND` | 404 Not Found |
| `ERR_REFUND_CHECK_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE_TRANSITION` | 409 Conflict |
| `ERR_JUDGMENT_SUSPENDED` | 409 Conflict |
| `ERR_FUND_NOT_DISBURSING` | 409 Conflict |
| `ERR_STALE_ORDER_VERSION` | 412 Precondition Failed |
| `ERR_STALE_FUND_VERSION` | 412 Precondition Failed |
| `ERR_SOD_PENALTY_CONFIRM` | 403 Forbidden |
| `ERR_SOD_CHECK_ISSUE` | 403 Forbidden |
| `ERR_COMMENT_PERIOD_OPEN` | 409 Conflict |
| `ERR_COMMENT_PERIOD_CLOSED` | 409 Conflict |
| `ERR_CID_RESPONSE_OVERDUE` | 409 Conflict |
| `ERR_REISSUE_WINDOW_EXPIRED` | 409 Conflict |
| `ERR_REPORTING_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_MONITORING_TERM_OVERLAP` | 409 Conflict |
| `ERR_JUDGMENT_ALREADY_EXISTS` | 409 Conflict |
| `ERR_CLAIM_ALREADY_FILED` | 409 Conflict |
| `ERR_CHECK_ALREADY_OUTSTANDING` | 409 Conflict |
| `ERR_UNRESOLVED_CLAIMS_EXIST` | 409 Conflict |
| `ERR_CHECKS_OUTSTANDING` | 409 Conflict |
| `ERR_COLLECTION_WINDOW_CLOSED` | 409 Conflict |
| `ERR_CLAIM_FUND_MISMATCH` | 400 Bad Request |
| `ERR_REPORT_COMPANY_MISMATCH` | 400 Bad Request |
| `ERR_SUBJECT_COMPANY_MISMATCH` | 403 Forbidden |
| `ERR_CLAIMANT_IDENTITY_MISMATCH` | 403 Forbidden |
| `ERR_MONITORING_THRESHOLD_NOT_MET` | 422 Unprocessable Entity |
| `ERR_SUSPENSION_THRESHOLD_NOT_MET` | 422 Unprocessable Entity |
| `ERR_PAYMENT_EXCEEDS_OUTSTANDING` | 422 Unprocessable Entity |
| `ERR_REVERSAL_EXCEEDS_COLLECTED` | 422 Unprocessable Entity |
| `ERR_NO_COMPLETED_ASSET_TRACE` | 409 Conflict |
