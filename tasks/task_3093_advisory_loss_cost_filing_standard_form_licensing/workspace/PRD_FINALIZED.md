# Advisory Loss Cost Bureau API — Product Requirements Document

## 1. Introduction

Member insurers of a rating bureau depend on a single, authoritative pipeline: they submit their statistical experience data, the bureau edits and validates it, actuaries develop advisory loss costs from the pooled experience, regulators review and object to those loss costs, insurers adopt them through loss cost multipliers, and the bureau licenses the standard policy forms and manuals that give the whole system legal effect. This document specifies the API for the **Advisory Loss Cost Bureau**, a service that operationalizes that entire pipeline — statistical data collection with edit and validation routines, loss cost development with actuarial trend selection, regulatory filing and objection handling, standard form and endorsement drafting with state variants, circular publication with implementation dates, licensing agreements, and class plan revisions that keep insurer rating engines synchronized.

The platform serves four distinct constituencies whose duties are deliberately segregated: bureau operations staff who register entities and drive workflows, bureau actuaries who review filings and clear form variants, state department analysts who raise objections within their jurisdiction, and member insurer users who submit data and adopt loss costs. Because filing outcomes carry regulatory and financial consequences, the system enforces a logical clock for all time-gated behavior, optimistic concurrency on versioned filing chains and adoption pricing, and pinned evaluation orders for every monetary or actuarial calculation so that two independent implementations produce bit-identical results.

## 2. Global Specifications & System-Wide Principles

This section defines the cross-cutting rules that apply to every endpoint and entity in the bureau platform. All endpoints are mounted under the `/bureau` path prefix.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, specifying the caller's operational capacity. The recognized role names are exactly `BureauAdmin`, `BureauActuary`, `RegulatorAnalyst`, and `InsurerUser`. A request arriving without a recognized `X-User-Role`, or without `X-User-ID`, is treated as an anonymous call and fails the first validation check with `ERR_UNAUTHENTICATED` (HTTP 401). A caller whose role is recognized but not permitted for the requested endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

Role identity semantics differ by role and matter for ownership and jurisdiction checks:

- When `X-User-Role` is `BureauAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it where a workflow requires attribution — most notably on a loss cost filing as `last_submitted_by_admin_id` when the filing is submitted to actuarial review — but it is never compared against any entity's `id`.
- When `X-User-Role` is `BureauActuary`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity. It participates in the segregation-of-duties comparison at review completion (see §3.3) but is never treated as an entity key.
- When `X-User-Role` is `RegulatorAnalyst`, `X-User-ID` is the `id` of the acting `StateDepartment`. Jurisdiction checks compare the department's `state_code` against the filing's `state_code`.
- When `X-User-Role` is `InsurerUser`, `X-User-ID` is the `id` of the acting `MemberInsurer`. Ownership checks on any resource that references a member insurer — for example, withdrawing an adoption — compare the resource's `insurer_id` to `X-User-ID`.

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

List endpoints accept the query parameters `limit` and `offset`. `limit` defaults to 10, with a minimum of 1 and a maximum of 100; `offset` defaults to 0. All list endpoints return resources sorted by `created_at` in ascending order. List responses include the pagination fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. The Logical Clock

All time-gated behavior in the platform — objection windows, license coverage, scheduled class plan activation, variant go-live — is evaluated against a **logical clock**, never wall-clock time. Before any administrative action sets it, the logical clock reads exactly `2026-09-01T00:00:00Z`. A `BureauAdmin` may advance the logical clock to a supplied `to_iso8601` instant via the clock-setting capability; system transitions gated on the logical clock are evaluated lazily on the next relevant read or action rather than by a background scheduler. This means, for example, that a license agreement is not proactively flipped when its coverage ends — the lapse is evaluated when the agreement is next read or when an adoption authorization consults it.

### 2.5. Common Resource Properties and the Lifecycle of a Mutation

Every primary resource — `MemberInsurer`, `StatisticalPlan`, `StatisticalSubmission`, `LossCostFiling`, `StateDepartment`, `LossCostMultiplierAdoption`, `PolicyForm`, `FormVariant`, `Circular`, `LicenseAgreement`, `ClassPlan`, and `ClassPlanRevision` — carries four system-managed fields: `id`, a server-minted UUID with no type prefix; `created_at`, an ISO 8601 UTC timestamp with three fractional digits captured at creation; `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation; and `version`, an integer starting at creation that increments by exactly 1 on every mutation of that resource.

Three leaf resources are lighter-weight. `SubmissionEditFinding`, `LossCostCell`, and `RegulatoryObjection` carry only `id` and `created_at`; both `updated_at` and `version` are absent from them, because they are immutable records written once and never modified.

Whenever a cascade described in §3 touches a parent resource — recomputing an insurer's quality score on submission disposition, superseding a filing on resubmission, advancing a class plan's current revision — that touch is itself a mutation: the parent's `updated_at` refreshes and its `version` increments by 1.

### 2.6. Nested Resource Retrieval and Referential Order

Requests that target nested resources validate path segments left to right: each identifier in the path must correspond to an existing resource, and the first missing identifier produces `ERR_NOT_FOUND` (HTTP 404) before later segments are examined. The same discipline applies to foreign keys in request bodies: body references are validated in the order they are declared in the endpoint's input list — for example, on a statistical submission the `insurer_id` is checked before the `plan_id`, and on an adoption the `insurer_id` is checked before the `filing_id` — and the first dangling reference is rejected with `ERR_NOT_FOUND`. Several read endpoints exist purely for reverse reachability: objections raised by a given department, license agreements of a given insurer, and class plans whose `current_revision_id` points at a given revision (which returns zero or one rows, since a revision can be in force for at most one plan).

### 2.7. Validation Priority Order

Every request passes through an ordered validation pipeline, and the order is part of the contract — when several checks could fail, the one with the highest priority determines the error returned:

1. **Authentication.** The `X-User-Role` header must be present and a declared role, and `X-User-ID` must be present; otherwise `ERR_UNAUTHENTICATED`.
2. **Authorization.** The role must be permitted for the endpoint; otherwise `ERR_UNAUTHORIZED`.
3. **Path existence.** Path-segment resources must exist, validated left to right; otherwise `ERR_NOT_FOUND`.
4. **Body referential existence.** Body foreign keys must exist, validated in declared input order; otherwise `ERR_NOT_FOUND`.
5. **From-state validity.** The target resource must be in a valid from-state for the requested transition; otherwise `ERR_INVALID_STATE` (HTTP 409).
6. **Cross-entity state gates.** A filing is adoptable only when `EFFECTIVE`; a class plan revision activates only while its plan is `OPEN`; adoption authorization proceeds only while the insurer is `ACTIVE`. These gates guard adoption creation, adoption authorization, and revision activation, and also fail with `ERR_INVALID_STATE`.
7. **Segregation of duties** on review completion (see §3.3) — `ERR_SEGREGATION_OF_DUTIES`.
8. **Regulator jurisdiction** on objections — `ERR_JURISDICTION_MISMATCH`.
9. **Objection window** temporal check — `ERR_OBJECTION_WINDOW_CLOSED`.
10. **Variant window overlap** temporal check — `ERR_VARIANT_WINDOW_OVERLAP`.
11. **License coverage** temporal check — `ERR_LICENSE_NOT_COVERING`.
12. **LCM band pre-screen** — `ERR_LCM_BAND_EXCEEDED` (only when an adoption creation requests immediate authorization screening; see §3.4). At the same priority tier, the optimistic-concurrency check on filing resubmission — `ERR_STALE_VERSION` (HTTP 412).
13. **Supersede chain integrity** — `ERR_SUPERSEDE_CHAIN_BROKEN` (HTTP 422). At the same tier, the loss-cost-cell field-range checks on cell creation — `ERR_INVALID_REQUEST`.
14. **General request shape.** Required input fields must be present, enum values must fall in their declared sets, and numeric ranges (such as `record_count` at least 1 and `written_premium_cents` at least 0) must hold; otherwise `ERR_INVALID_REQUEST` (HTTP 400).

One specialized rejection sits inside category 5/6 but is reported distinctly for audit purposes: when a `SUSPENDED` insurer attempts to create a statistical submission, the rejection is `ERR_INSURER_SUSPENDED` (HTTP 409) rather than the generic state error.

### 2.8. Optimistic Concurrency Control

Two write endpoints pin their effect to the caller's last observed version of a parent filing, and both reject stale views with `ERR_STALE_VERSION` (HTTP 412).

Creating a filing resubmission must carry `expected_superseded_version` equal to the current `version` of the filing named by `supersedes_filing_id`. If the superseded filing's version has advanced since the client last read it — because another resubmission already moved that filing from `OBJECTED` to `WITHDRAWN`, or because a withdrawal fired — the resubmission is rejected with `ERR_STALE_VERSION`, preventing the client from building a supersede chain on a view of the objected filing that is no longer current.

Creating a loss cost multiplier adoption must carry `expected_filing_version` equal to the current `version` of the filing being adopted. The adoption pins the filing version it was priced against; if the filing's version has advanced, the advisory loss costs the client saw are no longer current and the create is rejected with `ERR_STALE_VERSION`. Adoption creation itself does not mutate the filing: the filing's `version` and `updated_at` are untouched by it, so several adoptions created against the same unchanged filing version are all accepted.

Endpoints not named above do not accept a version field at all.

### 2.9. Actuarial and Monetary Precision

Percentage results and monetary amounts follow pinned rounding contracts so independent implementations agree to the digit. The indicated loss-cost change on a filing is rounded once, at the final aggregation step, to exactly 4 decimal places using round-half-up; per-cell indications are carried at full floating-point precision until that single final rounding. All premium and royalty amounts are integer cents, each rounded half-up at exactly the rounding points named in §3 — for adoption premium, per cell before summation; for royalty accrual, once at the end. Interval comparisons involving datetimes use direct datetime comparison with no rounding; interval comparisons involving license coverage use day-granularity date comparison.

### 2.10. The Two Interval Semantics

The platform deliberately employs two different interval conventions, and confusing them changes answers. Variant usability windows are **half-open**: a variant is usable from `effective_from` up to but not including `effective_to`, and an open-ended variant has `effective_to` unset. License coverage windows are **closed**: a license covers a date from `coverage_start` through `coverage_end` inclusive, so a window whose start and end are the same day covers exactly that one day. The same pair of timestamps can therefore be non-overlapping under variant semantics yet covering under license semantics; §3 applies each convention exactly where it belongs.

## 3. Business Logic & Workflows

### 3.1. Membership, Statistical Plans, and the Quality Score

A `BureauAdmin` onboards a member insurer by registering its bureau-assigned `insurer_code` (unique across the bureau) and `legal_name`. A new insurer begins life with `insurer_status` `ACTIVE` and a perfect statistical reporting quality: `quality_score_bps` starts at 10000, expressed in basis points on a 0 to 10000 scale. That score is recomputed after every statistical submission disposition, per §3.2.

The same administrator defines the statistical plans that govern what members may submit. Each plan carries a unique `plan_code`, the `line_of_business` it governs (for example `COMMERCIAL_PROPERTY`), a `min_premium_cents` floor below which records are excluded from the aggregate edit, and a `max_record_age_months` bound: policy records older than that many months from the submission period end are rejected by the age edit. A plan is created in `DRAFT` status and becomes usable when the administrator activates it, moving `plan_status` from `DRAFT` to `ACTIVE`; a plan may eventually be `RETIRED`.

Membership itself has a lifecycle. Suspending an insurer moves `insurer_status` from `ACTIVE` to `SUSPENDED`, increments the insurer's `version`, and has an immediate side effect: any attempt by that insurer to create a statistical submission is rejected with `ERR_INSURER_SUSPENDED` while the suspension stands. Reinstatement returns a `SUSPENDED` insurer to `ACTIVE`. Membership withdrawal is terminal — `insurer_status` becomes `WITHDRAWN` — and is permitted from either `ACTIVE` or `SUSPENDED`, but only when the insurer holds zero license agreements in `ACTIVE` status and zero adoptions in `PENDING` or `AUTHORIZED` status; withdrawal from a non-eligible state fails with `ERR_INVALID_STATE`. Suspension, reinstatement, and withdrawal each increment the insurer's `version` by 1 and refresh `updated_at`.

### 3.2. Statistical Submissions: Edit Routines and Disposition

An `InsurerUser` reports experience by creating a statistical submission: a payload naming the `insurer_id`, the `plan_id` whose edit routines will govern the batch, the inclusive `period_start`, the exclusive `period_end` (the period is the half-open interval from `period_start` up to but not including `period_end`), the `record_count` of statistical records in the batch (at least 1), and the `written_premium_cents` total (at least 0). Submissions can be listed filtered by `insurer_id`, `plan_id`, or `submission_status`. A new submission begins in `RECEIVED` status.

A `BureauAdmin` then drives the edit pass. Beginning the edit moves `submission_status` from `RECEIVED` to `EDITING`. While editing, the administrator records findings against the submission; each finding is created as a `SubmissionEditFinding` carrying the owning `submission_id`, an `edit_code` (for example `E-101` for premium-below-minimum), a `severity` of either `ERROR` or `WARNING`, and the `affected_records` count (at least 1). Findings are immutable once written.

Disposition closes the loop. When the administrator disposes a submission, the server first computes three counters from the finding rows at that moment: `error_finding_count` (findings of severity `ERROR`), `warning_finding_count` (findings of severity `WARNING`), and `accepted_record_count` (the `record_count` minus the number of `ERROR`-severity findings). The terminal status follows deterministically: with zero error findings and zero warning findings the submission is `ACCEPTED`; with zero errors but at least one warning it is `ACCEPTED_WITH_WARNINGS`; with at least one error finding it is `REJECTED`. All three dispositions are only reachable from `EDITING`. There is also a fast path: disposing a submission still in `RECEIVED` with the optional payload flag `fast_reject` set to true covers batch-level structural edit failure and moves the submission directly from `RECEIVED` to `REJECTED`. Disposing from any other state is rejected with `ERR_INVALID_STATE`.

Every disposition — whether `ACCEPTED`, `ACCEPTED_WITH_WARNINGS`, or `REJECTED`, and whether reached through the edit pass or the fast reject — triggers the same two side effects: the insurer's `quality_score_bps` is recomputed, and the insurer's `version` increments by 1 (with `updated_at` refreshed per §2.5).

The quality score recomputation is pinned. Consider all of the insurer's submissions in a terminal status, sorted by `updated_at` ascending with ties broken by `created_at` ascending. For each submission, compute its points as 10000 minus 200 per error finding minus 50 per warning finding, floored at zero so no single submission contributes negative points. Then weight by recency: the most recent submission gets weight 1, the next most recent gets weight one half, the next one quarter — the k-th most recent submission's weight is one half raised to the power of k minus 1. The score is the weighted average — the sum over submissions of points times weight, divided by the sum of the weights — rounded half-up to an integer number of basis points exactly once at the end, and finally clamped into the 0 to 10000 range. An insurer with no terminal submissions retains its starting score of 10000. The unweighted flat average is expressly not used: the geometric decay means the most recent disposition dominates.

### 3.3. Loss Cost Filings: Development, Review, Filing, Objection, Resubmission

A loss cost filing is the bureau's vehicle for proposing advisory loss costs for a state and line of business. A `BureauAdmin` creates one with a `filing_code` (unique per filing version chain root), the two-letter `state_code` it targets, the `line_of_business`, and the actuarial `trend_selection`, which must be exactly one of `EXPONENTIAL_LEAST_SQUARES` or `LINEAR_LEAST_SQUARES`. The creation payload may optionally include `review_notes` (the actuarial review narrative, nullable), an `effective_date` (the requested effective date of the advisory loss costs, which stays unset until the filing is filed), and — for resubmissions only — a `supersedes_filing_id` together with `expected_superseded_version`. A fresh filing starts in `DRAFT` with `filing_version` 1 and no superseding parent (`supersedes_filing_id` is null on version 1). Filings can be listed filtered by `state_code`, `line_of_business`, `filing_status`, or `supersedes_filing_id`.

While the filing is in `DRAFT`, the administrator builds its experience exhibit cell by cell. Each cell names a `class_code` within the filing's line of business and carries the on-level `earned_premium_cents` for the experience period (strictly greater than 0), the developed `incurred_loss_cents` (zero or more), a `weight_pct` credibility weight in whole percent from 1 to 100, and the `current_loss_cost_cents` currently effective for that state, line, and class (strictly greater than 0). Cell weights within a filing need not sum to 100 — the residual is treated as no-change at aggregation time. Out-of-range cell values are rejected with `ERR_INVALID_REQUEST`.

With at least one cell in place, the administrator submits the filing to actuarial review, moving `filing_status` from `DRAFT` to `IN_ACTUARIAL_REVIEW` and recording the submitting administrator's identity on the filing as `last_submitted_by_admin_id`. That recorded identity is the fulcrum of the bureau's segregation of duties: a `BureauActuary` completes the review, and the completing actuary's `X-User-ID` must differ from the administrator identity recorded at submit time. If they match, the completion is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 422). Successful completion moves the filing from `IN_ACTUARIAL_REVIEW` to `REVIEWED` and computes the filing's `indicated_change_pct`.

The indicated change computation is pinned step for step. First, for each cell, an unrounded per-cell indication is derived: the cell's raw loss ratio is its `incurred_loss_cents` divided by its `earned_premium_cents`, carried as an exact rational with no rounding yet; that ratio is trended by the filing's chosen methodology — under `EXPONENTIAL_LEAST_SQUARES`, the raw ratio is multiplied by one plus the per-period trend rate of 4 percent, compounded over two and a half trend periods; under `LINEAR_LEAST_SQUARES`, the raw ratio is multiplied by one plus the accumulated trend, that is the 4 percent per-period rate times two and a half periods (the linear variant always yields a strictly smaller indication than the exponential for identical inputs). The trended ratio is then compared to the target loss ratio of 60 percent: the per-cell indication in percent is the trended ratio divided by 0.60, minus one, times one hundred. Second, the cells' `weight_pct` values are summed; the residual weight — one hundred minus the weight sum, floored at zero — receives a zero percent indication. Third, if the weight sum exceeds 100, every weight is scaled down by the factor 100 divided by the weight sum so the total normalizes to 100; otherwise the weights are used as-is. Fourth, the indicated change is the sum over cells of scaled weight times per-cell indication, divided by 100. Fifth and finally, the result is rounded half-up to exactly 4 decimal places — the single rounding in the entire computation — and stored as `indicated_change_pct`. The cell rows are immutable once the filing is `REVIEWED`, so this value never drifts after review completion.

From `REVIEWED`, a `BureauAdmin` files the filing with the state. Filing requires that `effective_date` is set and lies strictly after the logical clock, and that a `StateDepartment` row exists for the filing's `state_code`; it moves `filing_status` from `REVIEWED` to `FILED` and stamps `filed_at` with the logical-clock instant. All objection-window arithmetic anchors on `filed_at`.

The objection window belongs to the department. Each `StateDepartment` is registered with its unique `state_code`, its `department_name`, an `objection_window_days` count (greater than 0) measuring how many days from `FILED` the department may raise an objection, and a `max_lcm_deviation_pct` ceiling (zero or more, in whole percent) governing multiplier deviations. A `RegulatorAnalyst` raises an objection against a `FILED` filing by supplying the `department_id`, an `objection_code` categorizing the objection, and the `objection_text` narrative; the created `RegulatoryObjection` is stamped with `raised_at` from the logical clock. Two business checks guard this, applied after the state gate and in the priority order of §2.7: jurisdiction first — the analyst's department `state_code` must equal the filing's `state_code`, else `ERR_JURISDICTION_MISMATCH` — then the window — the logical clock must be no later than `filed_at` plus the department's `objection_window_days`, else `ERR_OBJECTION_WINDOW_CLOSED`. The first in-window objection moves the filing from `FILED` to `OBJECTED` and increments the filing's `version` by 1.

If instead the window lapses quietly, the administrator finalizes the filing: finalization requires the filing still `FILED`, the logical clock strictly later than `filed_at` plus `objection_window_days`, and zero objection rows against the filing. It moves `filing_status` to `EFFECTIVE`, at which point the filing becomes adoptable — insurers may now create multiplier adoptions against it (§3.4).

An `OBJECTED` filing is answered by resubmission, and the cycle lives on the version chain rather than on the row. The administrator creates a new filing whose `supersedes_filing_id` names the objected filing; the optimistic-concurrency check of §2.8 applies via `expected_superseded_version` and is evaluated first (`ERR_STALE_VERSION` on mismatch), and the supersede chain check then requires the named filing to currently be `OBJECTED` — otherwise `ERR_SUPERSEDE_CHAIN_BROKEN`. Because the whole cycle lives on one version chain, the resubmission continues the chain root's identity: the new filing's `filing_code` is taken from the superseded filing, not from any `filing_code` value supplied in the resubmission payload. On success the new filing is created in `DRAFT` with `filing_version` equal to the superseded filing's version number plus 1, while the superseded filing itself transitions from `OBJECTED` to `WITHDRAWN` (terminal) with its `version` incremented by 1.

Withdrawal is available from four states: a filing in `DRAFT`, `IN_ACTUARIAL_REVIEW`, or `REVIEWED` may be withdrawn unconditionally, and a filing in `FILED` may be withdrawn only while it has zero objection rows. Any withdrawal lands in `WITHDRAWN`, and withdrawing from any other state fails with `ERR_INVALID_STATE`.

### 3.4. Multiplier Adoptions and License Agreements

Once a filing is `EFFECTIVE`, an `InsurerUser` adopts its advisory loss costs through a loss cost multiplier. The adoption payload names the `insurer_id`, the `filing_id` of an `EFFECTIVE` filing (adoption against a filing in any other status fails the cross-entity state gate with `ERR_INVALID_STATE`), the `multiplier_pct` in whole percent (at least 1; exactly 100 means pure adoption of the advisory loss costs), and the OCC field `expected_filing_version` per §2.8. Adoptions can be listed filtered by `insurer_id`, `filing_id`, or `adoption_status`. A new adoption starts in `PENDING` status.

Authorization is the bureau's decision, taken by a `BureauAdmin` while the insurer is still `ACTIVE`. Two outcomes are possible, and both are states, not errors. The license gate is checked first: the insurer must hold a license agreement in `ACTIVE` status whose closed coverage window contains the logical-clock date — meaning the date is on or after `coverage_start` and on or before `coverage_end`, with a same-day window covering exactly that day — else the authorization is rejected with `ERR_LICENSE_NOT_COVERING` (HTTP 422). With the license gate satisfied, the bureau compares the deviation: if the multiplier's excess over 100 (that is, `multiplier_pct` minus 100) is no greater than the department's `max_lcm_deviation_pct` for the filing's state, the adoption is `AUTHORIZED`; if the excess exceeds that ceiling, the adoption is `REJECTED_BAND`. At exactly the boundary — deviation equal to the ceiling — authorization is granted. The band check also exists as a pre-screen at adoption creation time: when an insurer requests immediate authorization screening at creation and the deviation exceeds the ceiling, creation is refused with `ERR_LCM_BAND_EXCEEDED`.

Authorization prices the adoption. On the transition into `AUTHORIZED`, the server computes `authorized_premium_cents` cell by cell over the filing's cells: for each cell, the cell premium is the cell's `current_loss_cost_cents` times `multiplier_pct` divided by 100, rounded half-up to integer cents, and the adoption's premium is the sum of those per-cell rounded amounts. The rounding order is pinned — round each cell first, then sum. Summing the unrounded products and rounding once would yield different cents whenever any cell product has a fractional part of half a cent or more, and that alternative is expressly rejected.

An insurer may walk away from its own adoption: withdrawal by an `InsurerUser` requires `X-User-ID` to equal the adoption's `insurer_id`, and is permitted from `PENDING` or from `AUTHORIZED`, landing the adoption in `WITHDRAWN`.

License agreements are the bureau's commercial gate over form and loss-cost use. A `BureauAdmin` creates one for an insurer with the closed coverage window `coverage_start` through `coverage_end` and a `royalty_rate_bps` between 0 and 5000 basis points applied to adopted premium; agreements of an insurer can be listed through the insurer-scoped read. A new agreement starts with `agreement_status` `ACTIVE`. Lapse is lazy: when the logical clock's date is strictly later than the `coverage_end` date — a day-granularity date comparison per §2.9, so an agreement whose coverage ends today still covers the whole of today — the `agreement_status` transitions from `ACTIVE` to `LAPSED` upon the next read of the agreement or the next adoption authorization that consults it — and every `PENDING` adoption of that insurer is withdrawn as a consequence, marked with the reason `LICENCE_LAPSED`. Active termination by a `BureauAdmin` requires the insurer to hold zero `AUTHORIZED` adoptions; it moves the agreement's `agreement_status` from `ACTIVE` to `TERMINATED` and likewise withdraws every `PENDING` adoption of the insurer, marked `LICENCE_TERMINATED`.

Royalties accrue on read. The royalty view for an agreement sums the `authorized_premium_cents` of the insurer's `AUTHORIZED` adoptions whose filings became `EFFECTIVE` while the agreement was `ACTIVE`, multiplies that sum by the agreement's `royalty_rate_bps` divided by 10000, and rounds half-up once to integer cents, returning the result as `royalty_due_cents`.

### 3.5. Standard Forms, State Variants, and Circulars

The bureau drafts standard policy forms and endorsements. A `BureauAdmin` creates a form with a unique `form_number`, a `form_title`, and a `form_kind` of either `POLICY_FORM` or `ENDORSEMENT`; the form begins in `DRAFTING`. Beneath each form sit its variants, each linked to its parent through `form_id`: the administrator adds a variant with a `state_code` — the two-letter state, or the literal `CW` marking the countrywide variant — a `variant_text_ref` pointing at the text payload, and a usability window `effective_from` through `effective_to`, the latter nullable for open-ended usability. A new variant begins with `review_status` `PENDING` and `publication_status` `UNPUBLISHED`; variants of a form can be listed and filtered by `state_code`.

The two variant dimensions advance in parallel. On the review dimension, a `BureauActuary` clears a variant — moving `review_status` from `PENDING` to `CLEARED` — only while its `publication_status` is still `UNPUBLISHED` and only when no sibling variant of the same form and same `state_code` has a conflicting usability window. The conflict test uses the half-open semantics of §2.10: two variants conflict when the first's `effective_from` is strictly before the second's `effective_to` (or the second is open-ended) and the second's `effective_from` is strictly before the first's `effective_to` (or the first is open-ended); merely touching windows, where one variant's `effective_to` equals the other's `effective_from`, do not conflict. The comparison set consists only of sibling variants whose `review_status` is `CLEARED` and whose `publication_status` is not `RETIRED`: siblings still `PENDING` or `BLOCKED` on the review dimension, and siblings `RETIRED` on the publication dimension, do not block clearing. A conflict rejects the clearing with `ERR_VARIANT_WINDOW_OVERLAP` (HTTP 422). The actuary may instead block a `PENDING` variant (`review_status` becomes `BLOCKED`), and may later unblock it back to `PENDING`, again only while its `publication_status` is `UNPUBLISHED`.

On the publication dimension, variants move without direct action: when the parent form reaches `PUBLISHED` through circular publication, every variant of that form whose `review_status` is `CLEARED` transitions `publication_status` from `UNPUBLISHED` to `SCHEDULED`; when the logical clock reaches the publishing circular's `implementation_date`, each `SCHEDULED` variant transitions to `LIVE`, opening the licensed-use gate — insurers holding an `ACTIVE` license agreement covering that date may use the variant. A `BureauAdmin` may retire a `LIVE` variant, moving `publication_status` to `RETIRED`, which is terminal on the publication dimension.

The form's own review is gated on its variants. Submitting a form for review requires at least one variant with `state_code` `CW` to exist, and moves `form_status` from `DRAFTING` to `IN_REVIEW`. Approval by a `BureauActuary` requires every variant of the form to have `review_status` `CLEARED`, and moves the form from `IN_REVIEW` to `APPROVED`. Returning the form to drafting moves it from `IN_REVIEW` back to `DRAFTING` and reverts every `CLEARED` variant to `PENDING`, forcing re-clearance. A form in `DRAFTING` or `IN_REVIEW` may be withdrawn to the terminal `WITHDRAWN`.

Circulars are the bureau's announcement channel and the trigger that publishes forms. A `BureauAdmin` creates a circular with a unique `circular_number`, a `subject` line, the `implementation_date` by which members must implement the announced changes, an optional list of `form_ids` the circular publishes, and an optional `supersedes_circular_id` naming an earlier circular it replaces; circulars can be listed filtered by `circular_status` or `supersedes_circular_id`. A new circular is `DRAFT`. Publishing requires the `implementation_date` to lie strictly after the logical clock, and the supersede chain check requires any named predecessor to currently be `PUBLISHED` — otherwise `ERR_SUPERSEDE_CHAIN_BROKEN`. Publication is a cascade: the circular itself moves from `DRAFT` to `PUBLISHED`; every listed form that is `APPROVED` moves to `PUBLISHED`, which in turn schedules that form's `CLEARED` variants per the publication dimension above; and the superseded circular, if any, moves from `PUBLISHED` to `SUPERSEDED`.

### 3.6. Class Plans and Scheduled Revisions

Insurer rating engines key off class plans, so the bureau manages plan revisions as scheduled events. A `BureauAdmin` creates a class plan with a unique `class_plan_code` and its `line_of_business`; the plan starts `OPEN` with `current_revision_id` unset — null until the first revision activates. Plans can be listed filtered by `current_revision_id` or `line_of_business`.

Revisions are staged ahead of time, each linked to its plan through `class_plan_id`. Staging a revision on a plan takes the `class_count` of classes in the revision (at least 1) and the `activates_at` logical-clock instant at which activation becomes permitted; the new revision starts with `revision_status` `STAGED` and a `revision_number` that is monotonic per plan — the first revision is number 1 and each staged revision takes the next number. Activation is permitted once the logical clock has reached `activates_at` and only while the parent plan is `OPEN`; activating moves the revision's `revision_status` from `STAGED` to `ACTIVATED` and fires three cascades at once: the plan's previously `ACTIVATED` revision, if any, moves to `SUPERSEDED`; the plan's `current_revision_id` is set to the newly activated revision; and the plan's `version` increments by 1 (with `updated_at` refreshed). Activation while the plan is `LOCKED`, or before `activates_at`, fails with `ERR_INVALID_STATE`.

Activation also ripples outward to insurer rating engines: every `AUTHORIZED` adoption whose filing's `line_of_business` equals the plan's `line_of_business` is flagged `rating_engine_stale` as true — a derived flag recomputed on read rather than stored — telling the insurer its pricing basis has moved. A reverse read lists the class plans for which a given revision is currently in force, returning zero or one plan.

Locking a class plan is terminal and requires the plan `OPEN`, a `current_revision_id` that is set, and zero revisions still in `STAGED` status; it moves `plan_status` from `OPEN` to `LOCKED`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — including all state-transition actions — return `200 OK`. Computed reads such as the royalty view return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/bureau/_clock/set_current_utc` | Set the logical clock | BureauAdmin |
| POST | `/bureau/insurers` | Register a member insurer | BureauAdmin |
| GET | `/bureau/insurers/{id}` | Get an insurer | BureauAdmin, BureauActuary, RegulatorAnalyst, InsurerUser |
| GET | `/bureau/insurers` | List insurers | BureauAdmin, BureauActuary, RegulatorAnalyst |
| POST | `/bureau/insurers/{id}/suspend` | Suspend an insurer | BureauAdmin |
| POST | `/bureau/insurers/{id}/reinstate` | Reinstate a suspended insurer | BureauAdmin |
| POST | `/bureau/insurers/{id}/withdraw-membership` | Withdraw insurer membership (terminal) | BureauAdmin |
| POST | `/bureau/statistical-plans` | Create a statistical plan | BureauAdmin |
| GET | `/bureau/statistical-plans/{id}` | Get a statistical plan | BureauAdmin, BureauActuary, InsurerUser |
| POST | `/bureau/statistical-plans/{id}/activate` | Activate a statistical plan | BureauAdmin |
| POST | `/bureau/submissions` | Submit a statistical data batch | InsurerUser |
| GET | `/bureau/submissions/{id}` | Get a submission | BureauAdmin, BureauActuary, InsurerUser |
| GET | `/bureau/submissions` | List submissions (filtered) | BureauAdmin, BureauActuary, InsurerUser |
| POST | `/bureau/submissions/{id}/begin-edit` | Begin edit routine pass | BureauAdmin |
| POST | `/bureau/submissions/{id}/findings` | Record an edit finding against a submission | BureauAdmin |
| GET | `/bureau/submissions/{id}/findings` | List findings of a submission | BureauAdmin, BureauActuary, InsurerUser |
| POST | `/bureau/submissions/{id}/dispose` | Dispose a submission to a terminal status | BureauAdmin |
| POST | `/bureau/departments` | Register a state department of insurance | BureauAdmin |
| GET | `/bureau/departments/{id}` | Get a department | BureauAdmin, BureauActuary, RegulatorAnalyst, InsurerUser |
| GET | `/bureau/departments/{id}/objections` | List objections raised by a department | BureauAdmin, BureauActuary, RegulatorAnalyst |
| POST | `/bureau/filings` | Create a loss cost filing (resubmission when superseding) | BureauAdmin |
| GET | `/bureau/filings/{id}` | Get a filing | BureauAdmin, BureauActuary, RegulatorAnalyst, InsurerUser |
| GET | `/bureau/filings` | List filings (filtered) | BureauAdmin, BureauActuary, RegulatorAnalyst, InsurerUser |
| POST | `/bureau/filings/{id}/cells` | Add a loss cost cell to a draft filing | BureauAdmin |
| GET | `/bureau/filings/{id}/cells` | List cells of a filing | BureauAdmin, BureauActuary, RegulatorAnalyst, InsurerUser |
| POST | `/bureau/filings/{id}/submit-review` | Submit filing to actuarial review | BureauAdmin |
| POST | `/bureau/filings/{id}/complete-review` | Complete actuarial review and compute indication | BureauActuary |
| POST | `/bureau/filings/{id}/file` | File the reviewed filing with the department | BureauAdmin |
| POST | `/bureau/filings/{id}/objections` | Raise a regulatory objection | RegulatorAnalyst |
| GET | `/bureau/filings/{id}/objections` | List objections against a filing | BureauAdmin, BureauActuary, RegulatorAnalyst |
| POST | `/bureau/filings/{id}/finalize` | Finalize a filed filing after the window lapses | BureauAdmin |
| POST | `/bureau/filings/{id}/withdraw` | Withdraw a filing (terminal) | BureauAdmin |
| POST | `/bureau/adoptions` | Adopt an effective filing via a multiplier | InsurerUser |
| GET | `/bureau/adoptions/{id}` | Get an adoption | BureauAdmin, BureauActuary, InsurerUser |
| GET | `/bureau/adoptions` | List adoptions (filtered) | BureauAdmin, BureauActuary, InsurerUser |
| POST | `/bureau/adoptions/{id}/authorize` | Authorize or band-reject an adoption | BureauAdmin |
| POST | `/bureau/adoptions/{id}/withdraw` | Insurer withdraws its own adoption | InsurerUser |
| POST | `/bureau/forms` | Create a standard policy form or endorsement | BureauAdmin |
| GET | `/bureau/forms/{id}` | Get a form | BureauAdmin, BureauActuary, InsurerUser |
| POST | `/bureau/forms/{id}/variants` | Add a state or countrywide variant to a form | BureauAdmin |
| GET | `/bureau/forms/{id}/variants` | List variants of a form | BureauAdmin, BureauActuary, InsurerUser |
| GET | `/bureau/variants/{id}` | Get a variant | BureauAdmin, BureauActuary, InsurerUser |
| POST | `/bureau/variants/{id}/clear` | Clear a variant (overlap-checked) | BureauActuary |
| POST | `/bureau/variants/{id}/block` | Block a variant | BureauActuary |
| POST | `/bureau/variants/{id}/unblock` | Return a blocked variant to pending | BureauActuary |
| POST | `/bureau/variants/{id}/retire` | Retire a live variant (terminal) | BureauAdmin |
| POST | `/bureau/forms/{id}/submit-review` | Submit form for review | BureauAdmin |
| POST | `/bureau/forms/{id}/approve` | Approve a form (all variants cleared) | BureauActuary |
| POST | `/bureau/forms/{id}/return-to-drafting` | Return form to drafting | BureauActuary |
| POST | `/bureau/forms/{id}/withdraw` | Withdraw a form (terminal) | BureauAdmin |
| POST | `/bureau/circulars` | Create a circular | BureauAdmin |
| GET | `/bureau/circulars/{id}` | Get a circular | BureauAdmin, BureauActuary, InsurerUser |
| GET | `/bureau/circulars` | List circulars (filtered) | BureauAdmin, BureauActuary, InsurerUser |
| POST | `/bureau/circulars/{id}/publish` | Publish a circular (cascades forms and variants) | BureauAdmin |
| POST | `/bureau/agreements` | Create a license agreement for an insurer | BureauAdmin |
| GET | `/bureau/agreements/{id}` | Get an agreement (lapse evaluated lazily) | BureauAdmin, BureauActuary, InsurerUser |
| GET | `/bureau/agreements/{id}/royalty` | Computed royalty accrual read | BureauAdmin, BureauActuary |
| POST | `/bureau/agreements/{id}/terminate` | Terminate an agreement | BureauAdmin |
| GET | `/bureau/insurers/{id}/agreements` | List license agreements of an insurer | BureauAdmin, BureauActuary, InsurerUser |
| POST | `/bureau/class-plans` | Create a class plan | BureauAdmin |
| GET | `/bureau/class-plans/{id}` | Get a class plan | BureauAdmin, BureauActuary, InsurerUser |
| GET | `/bureau/class-plans` | List class plans (filtered) | BureauAdmin, BureauActuary, InsurerUser |
| POST | `/bureau/class-plans/{id}/revisions` | Stage a class plan revision | BureauAdmin |
| GET | `/bureau/class-plans/{id}/revisions` | List revisions of a class plan | BureauAdmin, BureauActuary, InsurerUser |
| GET | `/bureau/class-plan-revisions/{id}` | Get a class plan revision | BureauAdmin, BureauActuary, InsurerUser |
| GET | `/bureau/class-plan-revisions/{id}/in-force-for` | List class plans whose current revision is this one | BureauAdmin, BureauActuary, InsurerUser |
| POST | `/bureau/class-plan-revisions/{id}/activate` | Activate a staged revision | BureauAdmin |
| POST | `/bureau/class-plans/{id}/lock` | Lock a class plan (terminal) | BureauAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 422 |
| `ERR_JURISDICTION_MISMATCH` | 422 |
| `ERR_OBJECTION_WINDOW_CLOSED` | 422 |
| `ERR_VARIANT_WINDOW_OVERLAP` | 422 |
| `ERR_LICENSE_NOT_COVERING` | 422 |
| `ERR_LCM_BAND_EXCEEDED` | 422 |
| `ERR_SUPERSEDE_CHAIN_BROKEN` | 422 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INSURER_SUSPENDED` | 409 |
