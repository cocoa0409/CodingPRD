# NAIC Model Law, Accreditation & Filings API — Product Requirements Document

## 1. Introduction

State insurance regulation rests on a shared scaffolding: model laws and regulations drafted centrally through a committee process, adopted — often with local variations — by dozens of jurisdictions, and an accreditation program that holds every state insurance department to common solvency-oversight standards. When a model act is revised, some states adopt the new text verbatim, some adopt it with substantive variations, and some never adopt it at all, leaving insurers, producers, and regulators to reconcile inconsistent requirements across jurisdictions. Meanwhile every insurer files quarterly and annual financial statements that must pass validation edits, be converted into a risk-based capital posture, and, when the numbers deteriorate far enough, trigger regulatory intervention.

This document specifies the API of a data service supporting that work end to end. It covers the model instrument lifecycle from committee drafting through public exposure drafts, member ballots, adoption, publication, and supersession of whole version lines; state adoption tracking with certification of variations; accreditation reviews scored first at desk and then on site, whose outcomes drive each state's standing; financial statement filings with validation edits and a dual-variant risk-based capital computation; producer licensing across jurisdictions; coordinated market conduct data calls with examination-cost allocation; and the maintenance of valuation and reserving standards under segregation of duties. All state transitions run against a logical clock that is fully under operator control, so that comment-window expirations, license sweeps, and review periods behave deterministically.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming exactly one of six declared roles — `AssociationStaff`, `Actuary`, `StateRegulator`, `InsurerUser`, `ProducerUser`, and `ReviewTeamLead`. A request with a missing header, an undeclared role name, or — for the entity-backed roles below — an `X-User-ID` that does not name an existing instance of that entity is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not listed on the target endpoint, or that fails the ownership rules below, is rejected with `ERR_FORBIDDEN` (HTTP 403). All six roles may invoke every read endpoint; write operations are segregated per role as narrated in §3 and summarized in §4.

The identity carried by `X-User-ID` depends on the role:

- When `X-User-Role` is `AssociationStaff`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. Association staff administer model acts, exposure drafts, ballot closure and publication, adoption certification, review scheduling and finalization, filing validation, the state, insurer and producer registries, and the logical clock.
- When `X-User-Role` is `Actuary`, `X-User-ID` is likewise an opaque operator identifier. The server records it as `author_user_id` on each `ValuationStandard` the actuary drafts, and — as a segregation-of-duties control — refuses to let that same identifier activate the standard (§3.5).
- When `X-User-Role` is `StateRegulator`, `X-User-ID` is the `id` of the acting `State`; ownership checks on any resource that references a state compare the resource's jurisdiction field — `state_code` on ballots, adoptions and licenses, `lead_state_code` when a market conduct call is closed — to that State's `code`.
- When `X-User-Role` is `InsurerUser`, `X-User-ID` is the `id` of the acting `Insurer`; it must equal the `insurer_id` carried by the filing being created or pinned on the filing being submitted, and it determines which insurer a market conduct response is filed for.
- When `X-User-Role` is `ProducerUser`, `X-User-ID` is the `id` of the acting `Producer`; it must equal the `producer_id` on any license application.
- When `X-User-Role` is `ReviewTeamLead`, `X-User-ID` is an opaque operator identifier. The server records it as `team_lead_id` on the `AccreditationReview` at scheduling time and compares the header against that stored value when findings are issued; a review whose `team_lead_id` is null can never be matched by any header.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits. It is read from the server's wall clock, not from the logical clock of §2.4 — the logical clock governs persisted resource timestamps only, which is why an envelope timestamp may read earlier than the logical clock's initial instant.
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

All list endpoints accept the optional query parameters `limit` and `offset`. The `limit` parameter defaults to 10, with a minimum of 1 and a maximum of 100; `offset` defaults to 0. Out-of-range values are clamped, not rejected: a `limit` below 1 becomes 1, a `limit` above 100 becomes 100, and a negative `offset` becomes 0; a non-integer `limit` or `offset` is `ERR_INVALID_REQUEST` (400). List responses are sorted by `created_at` ascending, with resources created at the same clock instant ordered by creation sequence. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more` in addition to the standard request fields; `has_more` is true exactly when `offset` plus the number of items returned is less than `total_count`. The filing list of an insurer additionally accepts the optional filters `period_year` and `status` (§3.4) — a non-integer `period_year` or a `status` value outside the filing lifecycle (`DRAFT`, `SUBMITTED`, `VALIDATED`, `EDITS_FAILED`, `SUPERSEDED`) is `ERR_INVALID_REQUEST` (400); no other list endpoint defines filters beyond `limit` and `offset`.

### 2.4. Resource Identity, Timestamps, and the Logical Clock

Every resource in this API — model acts, exposure drafts, ballots, states, adoptions, reviews, insurers, filings, RBC reports, producers, licenses, market conduct calls, responses, and valuation standards — carries four common properties: `id`, a server-minted UUID with no type prefix; `created_at` and `updated_at`, ISO 8601 UTC timestamps rendered with three fractional digits; and `version`, an integer that starts at 1 at creation and increments by exactly one on every mutation of the resource, with `updated_at` refreshed to the current logical clock at the same moment. When one operation cascades across several resources, each touched resource's `version` increments individually. Two maintained counters are exempt from the per-mutation rule: a producer's `active_license_count` and a state's `core_act_coverage_pct` change as side effects of other resources' lifecycles, and such a change does not by itself increment the producer's or state's `version`. Every other timestamp — the client-supplied instants echoed back unchanged (`comment_window_start`, `comment_window_end`, `enacted_on`, `period_start`, `period_end`, `effective_from`, `valid_until`) and the clock-written `cast_at` and `published_at` — is rendered as plain ISO 8601 UTC exactly as the underlying instant reads, carrying a fractional part only when that instant has sub-second precision.

The platform runs on a logical clock and never falls back to wall-clock time. Before any request has been processed, the clock reads exactly 2026-09-01T00:00:00Z. An `AssociationStaff`-only test-driving capability advances the clock to a supplied `to_iso8601` instant — any well-formed instant is accepted, whether earlier than, equal to, or later than the current reading; no monotonicity is enforced. Every timestamp the server writes — `created_at`, `updated_at`, a ballot's `cast_at`, an act's `published_at` — reads from that clock. Every clock set runs the expiry sweep: a license whose `valid_until` the new reading has strictly passed is swept from `ISSUED` to `EXPIRED` (§3.6). The clock endpoint answers HTTP 200 with an empty `data` object.

### 2.5. Precision, Rounding, and Monetary Conventions

Monetary inputs are integers denominated in cents — `reported_surplus_cents`, `asset_risk_cents`, `underwriting_risk_cents`, `other_risk_cents`, `total_cost_cents`, `direct_premium_cents`, and the computed `allocated_cost_cents` — and each must be non-negative unless a stricter rule is stated. Computed monetary values are rounded half-up to two decimal places; the risk-based capital ratios `ratio_covariance` and `ratio_additive` are rounded half-up to four decimal places; percentages and point scores — `core_act_coverage_pct`, `desk_score`, and `onsite_score` — are rounded half-up to one decimal place, while `exam_priority_score` is rounded half-up to two. "Rounded half-up" means a value lying exactly halfway between two representable neighbors rounds to the larger neighbor. Rounding is applied exactly where §3 pins it — in particular, the risk-based capital aggregation rounds the capital requirement to two decimals before dividing by it, never the other way around (§3.4).

### 2.6. Optimistic Concurrency Control

Exactly two write endpoints take a mandatory expected-version field; no other endpoint accepts one.

- Creating a financial filing (`POST /naic/filings`) requires `expected_insurer_version`, carrying the client's last observed `version` of the target insurer. If the insurer's current `version` has advanced since that observation — for example because another filing was created or validated against the same insurer — the create is rejected with `ERR_STALE_VERSION` (HTTP 412). A new filing for an already-used statement period legitimately supersedes the prior filing (§3.4), so a client holding a stale insurer version must be refused rather than allowed to supersede on an outdated view.
- Recording a state adoption (`POST /naic/adoptions`) requires `expected_state_version`, carrying the client's last observed `version` of the adopting state. A mismatch with the state's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412). A new adoption for an act the state has already certified legitimately supersedes the prior certified adoption (§3.2), so here too a stale client is refused rather than allowed to supersede on an outdated view.

### 2.7. Registries, Version Lines, and Supersession

Five uniqueness rules guard the registries, each rejected with HTTP 409 and its own error identifier: the pair (`model_code`, `version_label`) on a model act (`ERR_DUPLICATE_MODEL_ACT`); `naic_code` on an insurer (`ERR_DUPLICATE_NAIC_CODE`); `npn` on a producer (`ERR_DUPLICATE_NPN`); the pair (`code`, `version_label`) on a valuation standard (`ERR_DUPLICATE_STANDARD_VERSION`); and `call_code` on a market conduct call (`ERR_DUPLICATE_CALL_CODE`). In addition, a state's `code` — a two-letter jurisdiction code such as CA — is unique across registered states; the catalogue assigns this rule no identifier of its own, so a duplicate `code` is rejected with `ERR_INVALID_REQUEST` (400) rather than one of the five 409 identifiers above. The two-letter form names the convention only: no length or format validation is applied to `code`.

Four supersession disciplines recur across the domain and are detailed where they live in §3. A model act line is keyed by `model_code`: publishing a new `version_label` under the same code supersedes the previously `PUBLISHED` act of that line and fires a coverage cascade into the states (§3.2). A valuation standard line is keyed by `code`: activating a new version retires the previously `ACTIVE` version, which in turn invalidates filings pinned to it (§3.5). A financial filing is unique per insurer and statement period: creating a fresh filing for an already-used period supersedes the earlier one from any lifecycle state (§3.4). And a state that re-adopts an act it has already certified supersedes its own prior certified adoption at the moment the successor is recorded (§3.2).

### 2.8. Validation Pipeline and Error Precedence

Every request is checked against a fixed pipeline of validation stages, and the first failing check wins — later stages are not evaluated once a rejection has been issued. The stages, in order, are:

1. **Authentication** — the headers and identity rules of §2.1; failures carry `ERR_UNAUTHENTICATED` (401).
2. **Authorization and ownership** — the role must be listed on the endpoint and the ownership comparisons of §2.1 must hold; failures carry `ERR_FORBIDDEN` (403). Ownership comparisons that read a path-addressed resource (a filing's `insurer_id`, a license's `state_code`, a call's `lead_state_code`, a review's `team_lead_id`) necessarily run immediately after that resource resolves at stage 3, ahead of the shape and lifecycle stages; body-derived comparisons (`state_code`, `insurer_id`, `producer_id` supplied in the payload) run at this stage, before path resolution. When a request body omits the field an ownership comparison would read (for example `state_code` on a ballot or `insurer_id` on a filing create), there is nothing to compare at this stage and the omission is caught at stage 5 as a missing required field (`ERR_INVALID_REQUEST`, 400), not as an ownership failure.
3. **Path resolution** — path identifiers resolve left to right, each with its own not-found error (404): `ERR_MODEL_ACT_NOT_FOUND`, `ERR_EXPOSURE_DRAFT_NOT_FOUND`, `ERR_STATE_NOT_FOUND`, `ERR_ADOPTION_NOT_FOUND`, `ERR_REVIEW_NOT_FOUND`, `ERR_INSURER_NOT_FOUND`, `ERR_FILING_NOT_FOUND`, `ERR_PRODUCER_NOT_FOUND`, `ERR_LICENSE_NOT_FOUND`, `ERR_MARKET_CONDUCT_CALL_NOT_FOUND`, and `ERR_VALUATION_STANDARD_NOT_FOUND`.
4. **Body reference resolution** — references supplied in a request body must name existing resources: `model_act_id` (`ERR_MODEL_ACT_NOT_FOUND`), `insurer_id` (`ERR_INSURER_NOT_FOUND`), `producer_id` (`ERR_PRODUCER_NOT_FOUND`), `state_code` and `domicile_state_code` (`ERR_STATE_NOT_FOUND`), and `valuation_standard_code` (`ERR_VALUATION_STANDARD_NOT_FOUND`), all 404.
5. **Request shape** — required fields are present, enum values are valid, integer amounts are at least zero (`direct_premium_cents` must be strictly positive), every window's end is strictly after its start, and findings or self-assessment totals are at least 1 with the compliant count between 0 and that total; any violation is `ERR_INVALID_REQUEST` (400).
6. **Lifecycle state gates** — each write endpoint's status preconditions as narrated in §3, nearly all 409; recording an adoption against an act that is not yet published is the exception at 422.
7. **Expected-version checks** — the two optimistic-concurrency rules of §2.6, 412.
8. **Business safety** — reviewer rotation and the actuarial self-activation ban, both 422.
9. **Uniqueness and duplicates** — the registry rules of §2.7 plus the per-workflow duplicate guards on ballots, adoptions, and responses, all 409.
10. **Domain guards** — exposure-window length and the suspended-state gates on balloting and license issuance, 422.
11. **Temporal overlap and gap rules** — exposure windows, review periods, and license windows, 409 for overlaps and 422 for an insufficient review gap.
12. **Valuation standard currency** — the standard a filing cites must be the currently active version, 422.
13. **Fiscal and participation minimums** — the examination cost floor and the requirement that a call hold at least one response before closing, both 422.

Where several checks from different stages guard the same endpoint, §3 states their evaluation order explicitly alongside the workflow they protect.

## 3. Business Logic & Workflows

### 3.1. Developing a Model Instrument: Drafting, Exposure, and Ballot

A model instrument begins when `AssociationStaff` registers it with a stable `model_code` (for example MDL-101), a `version_label` within that line (for example v2026.1), a full `title`, an `act_type` of either `MODEL_LAW` or `MODEL_REGULATION`, and the sponsoring `committee_name` — committees are free text and are not persisted as entities in their own right. The optional `is_core` flag defaults to false and marks the act as counting toward each state's core-act coverage (§3.2). A new act starts in `DRAFTING` status with `published_at` null and both vote counters, `votes_cast` and `favorable_votes`, at zero.

Once drafted, the act is exposed for public comment. Staff open an exposure draft by supplying the `model_act_id` together with `comment_window_start` and `comment_window_end`. The window is half-open: the start instant is inclusive and the end instant exclusive, so the logical clock must reach `comment_window_end` before the draft can close. Three checks guard draft creation and are evaluated in this order: first the act must be in `DRAFTING` or `EXPOSURE_OPEN` status, otherwise the request fails with `ERR_ACT_NOT_OPEN_FOR_EXPOSURE` (409); then the window length must span at least 30 days, otherwise `ERR_COMMENT_WINDOW_TOO_SHORT` (422); finally the new window must not intersect the window of any other existing draft of the same act in any status, otherwise `ERR_EXPOSURE_WINDOW_OVERLAP` (409) — bare adjacency, where the new start equals an existing end, does not count as an intersection. Every new draft starts in `OPEN` status. The first draft of an act is numbered `exposure_number` 1 and moves the act from `DRAFTING` to `EXPOSURE_OPEN`; each additional draft takes the next sequential number — one more than the count of the act's prior drafts in any status — and leaves the act in `EXPOSURE_OPEN` (an explicit self-loop, not a no-op). Either way the act's `version` increments.

Closing a draft is also staff work and checks two conditions in order: the draft must still be `OPEN` (`ERR_EXPOSURE_DRAFT_NOT_OPEN`, 409), and the logical clock must have reached its `comment_window_end` (`ERR_COMMENT_WINDOW_OPEN`, 409). The closed draft becomes `CLOSED` and its `version` increments. When the draft being closed was the act's last remaining `OPEN` draft, the act itself advances from `EXPOSURE_OPEN` to `BALLOTING` and the act's `version` increments; while other drafts of the act remain open, closing one changes nothing on the act.

With the act in `BALLOTING`, each member state votes. A `StateRegulator` casts the ballot of its own state — the supplied `state_code` must equal the acting regulator's State `code`, or the request fails ownership with `ERR_FORBIDDEN` — choosing a `vote` of `YEA`, `NAY`, or `ABSTAIN`. Three checks apply in order: the act must be in `BALLOTING` (`ERR_ACT_NOT_BALLOTING`, 409 — the same rejection covers the ballot-closing action below), the voting state's `accreditation_status` must not be `SUSPENDED` (`ERR_VOTING_STATE_SUSPENDED`, 422), and the state must not already hold a `CAST` ballot on this act (`ERR_DUPLICATE_BALLOT`, 409). A successful ballot is recorded with status `CAST` and a `cast_at` read from the logical clock; the act's `votes_cast` and `favorable_votes` are recomputed and the act's `version` increments. An `ABSTAIN` ballot counts toward `votes_cast` but never toward `favorable_votes`, which counts only `CAST` ballots whose vote is `YEA`.

Closing the ballot tallies the result against the adoption rule. The eligible electorate is the count of states whose `accreditation_status` is `ACCREDITED` or `PROBATION`; `SUSPENDED` states do not count. Quorum is the smallest whole number that is at least 60 percent of that eligible count. The required favorable count is the smallest whole number that is at least two-thirds of `votes_cast`. The adoption passes if and only if `votes_cast` is at least the quorum and `favorable_votes` is at least the required favorable count; both thresholds are computed with integer arithmetic, rounding up at exactly those two points. On a pass the act moves from `BALLOTING` to `ADOPTED`, its counters are recomputed from the `CAST` ballots, and its `version` increments. On a failure the act loops back from `BALLOTING` to `DRAFTING` for revision: every `CAST` ballot of the act cascades to `VOID` and is excluded from both counters thereafter, the counters themselves reset to zero, and the act's `version` increments.

### 3.2. Publication, State Adoption, and Coverage Tracking

Publishing is the point where an adopted instrument becomes law-track. Staff may publish only an act in `ADOPTED` status — any other status is rejected with `ERR_ACT_NOT_ADOPTED` (409). Publication stamps `published_at` with the current logical clock, moves the act to `PUBLISHED`, increments its `version`, and then fires a four-hop cascade. Hop 1: any other model act sharing the same `model_code` that is currently `PUBLISHED` becomes `SUPERSEDED` — a version line never has two published members. Hop 2: every adoption of each superseded act whose status is `PENDING_CERTIFICATION`, `CERTIFIED_SIMILAR`, or `CERTIFIED_VARIED` becomes `SUPERSEDED`; adoptions already in `REJECTED_NOT_SIMILAR` are left untouched. Hop 3: `core_act_coverage_pct` is recomputed for every state whose adoption was superseded in hop 2. Hop 4: for each such state that is currently `ACCREDITED` and whose recomputed coverage has fallen below 50.0 percent, the system auto-creates an accreditation review with `origin` `AUTO_COVERAGE`, a null `team_lead_id`, a period running from the current clock to 180 days later, self-assessment counts of 0 out of 1 — so its `desk_score` computes to 0.0 — and status `SCHEDULED` (§3.3).

A state's coverage percentage is the share of published core acts the state has certified: the numerator counts the state's own adoptions in `CERTIFIED_SIMILAR` or `CERTIFIED_VARIED` status whose act has `is_core` true, and the denominator counts all model acts in `PUBLISHED` status with `is_core` true. When no published core act exists the coverage reads 100.0; otherwise it is one hundred times the numerator divided by the denominator, rounded half-up to one decimal place. The same recomputation runs on every certification, on every adoption supersession, and — via the publish cascade — on every publication that affects the state.

Before any of this can happen, the jurisdiction itself must be registered: staff supply a unique two-letter `code` and a full `name`. A new state starts `ACCREDITED`, with `consecutive_fail_count` 0 and `core_act_coverage_pct` 100.0.

A state adopts a published act through its `StateRegulator`, whose State `code` must equal the payload's `state_code` (`ERR_FORBIDDEN` otherwise). The recording carries the `model_act_id`, the local statutory reference `adopted_citation`, the `enacted_on` date of the local enactment, and the OCC field `expected_state_version` (§2.6). Three domain checks follow in order: the act must be `PUBLISHED` (`ERR_ACT_NOT_PUBLISHED`, 422), the expected version must match (`ERR_STALE_VERSION`, 412), and the state must not already hold a `PENDING_CERTIFICATION` adoption for the same act (`ERR_DUPLICATE_ADOPTION`, 409). The new adoption starts in `PENDING_CERTIFICATION`. Recording it supersedes the state's prior `CERTIFIED_SIMILAR` or `CERTIFIED_VARIED` adoption of the same act, if one exists — that adoption becomes `SUPERSEDED` — and the state's `version` increments by exactly one; when such a supersession occurred, the state's coverage is recomputed.

Certification is an `AssociationStaff` decision supplied as `variation_class`, and it is only available while the adoption is `PENDING_CERTIFICATION` (`ERR_ADOPTION_NOT_PENDING`, 409). All three branches receive the same treatment — the adopting state's `core_act_coverage_pct` is recomputed and the adoption's `version` increments — and differ only in outcome: `SUBSTANTIALLY_SIMILAR` moves the adoption to `CERTIFIED_SIMILAR`, `SUBSTANTIVE_VARIATIONS` moves it to `CERTIFIED_VARIED`, and `NOT_SIMILAR` moves it to the terminal `REJECTED_NOT_SIMILAR`. Any other value is a shape error under §2.8 stage 5. Both certified statuses count toward coverage; a rejected adoption does not. Independently of certification, an adoption in `PENDING_CERTIFICATION`, `CERTIFIED_SIMILAR`, or `CERTIFIED_VARIED` also becomes `SUPERSEDED` when its adopted act is superseded (hop 2 above), with the adopting state's coverage recomputed in every case.

### 3.3. Accreditation Reviews and a State's Standing

An accreditation review is scheduled by `AssociationStaff` against a `state_id`, with a `period_start` and `period_end` forming a closed interval — both boundary days are inside the period — plus the `team_lead_id` of the review team lead and the state's self-assessment counts, `self_assessment_compliant` out of `self_assessment_total`. Shape rules (§2.8 stage 5) require the total to be at least 1 and the compliant count to lie between 0 and the total. Beyond shape, three checks apply in this order: first, reviewer rotation — the proposed `team_lead_id` must differ from the `team_lead_id` of the same state's most recent `FINAL_PASS` or `FINAL_FAIL` review, "most recent" meaning the latest-created such review, otherwise `ERR_REVIEWER_ROTATION_REQUIRED` (422); second, the new period must not intersect any existing review period of the same state, where closed intervals that merely touch still count as overlapping (`ERR_REVIEW_WINDOW_OVERLAP`, 409); third, the gap between the new `period_start` and the most recent prior `period_end` of that state must be at least 180 days (`ERR_REVIEW_GAP_TOO_SHORT`, 422). These three checks guard staff scheduling only; the coverage-triggered reviews auto-created by the publish cascade (§3.2) skip all three. A scheduled review starts in `SCHEDULED` status with `origin` `MANUAL`, and its `desk_score` is computed immediately: one hundred times `self_assessment_compliant` divided by `self_assessment_total`, rounded half-up to one decimal place. The on-site fields — `findings_compliant`, `findings_total`, `onsite_score`, and `proposed_outcome` — remain null until findings are issued.

Coverage-triggered reviews created by the publish cascade (§3.2) look different: `origin` is `AUTO_COVERAGE`, `team_lead_id` is null, the period runs from the current clock to 180 days later, and the self-assessment counts are 0 out of 1. Because ownership of the findings step compares the caller's header to `team_lead_id` and a null value can never match any `X-User-ID`, such a review cannot issue findings until it is reassigned — reassignment is outside the scope of this API.

Issuing findings is the `ReviewTeamLead`'s exclusive act, and only while the review is `SCHEDULED` — otherwise `ERR_REVIEW_NOT_SCHEDULED` (409); a header that fails to match the stored `team_lead_id` fails earlier with `ERR_FORBIDDEN`. The lead supplies `findings_compliant` out of `findings_total`, with the same shape rules as the self-assessment counts. The `onsite_score` is then computed — one hundred times `findings_compliant` divided by `findings_total`, rounded half-up to one decimal place — and `proposed_outcome` is derived from it alone: `PASS` when the onsite score is at least 75.0, otherwise `FAIL`. The desk score plays no part in the outcome; a state can look compliant on paper and fail on site — a desk picture of 18 out of 20 scores 90.0, while an on-site result of 12 out of 20 scores 60.0 and proposes `FAIL`. Issuing findings moves the review from `SCHEDULED` to `FINDINGS_ISSUED` and increments its `version`.

Finalization belongs to `AssociationStaff` and requires the review to be in `FINDINGS_ISSUED` (`ERR_REVIEW_NOT_FINDINGS_ISSUED`, 409). What happens next depends entirely on `proposed_outcome`. When it is `PASS`, the review closes as `FINAL_PASS` and the state's standing is restored: `accreditation_status` becomes `ACCREDITED` and `consecutive_fail_count` resets to 0, whether the state entered the review `ACCREDITED`, on `PROBATION`, or `SUSPENDED` — the last is the reinstatement loop. When it is `FAIL`, the review closes as `FINAL_FAIL` and the state's `consecutive_fail_count` increases by one: a count that becomes 1 moves the state from `ACCREDITED` to `PROBATION`; a count that becomes 2 moves a state on `PROBATION` to `SUSPENDED`; and a state already `SUSPENDED` stays `SUSPENDED` while its count keeps climbing. Either way the review's `version` increments, and the state's `version` increments with every standing change.

A state's standing has teeth elsewhere in the system: a `SUSPENDED` state may not cast ballots (§3.1) and may not issue producer licenses (§3.6).

### 3.4. Financial Filings and Risk-Based Capital

An insurer enters the system when `AssociationStaff` registers it with a unique `naic_code`, a legal `name`, and a `domicile_state_code` that must match the `code` of an already-registered state (`ERR_STATE_NOT_FOUND`, 404). A new insurer's `status` is `ACTIVE`, and its `latest_rbc_ratio` and `latest_action_level` are both null until a filing validates.

Filings are the insurer's own work. An `InsurerUser` creates a draft filing with `insurer_id` — which must equal the caller's `X-User-ID` (`ERR_FORBIDDEN`) — plus `period_year`, a `period_quarter` of `Q1`, `Q2`, `Q3`, `Q4`, or `ANNUAL`, the `valuation_standard_code` to file under, the four cent-denominated figures `reported_surplus_cents`, `asset_risk_cents`, `underwriting_risk_cents`, and `other_risk_cents` (each at least zero), and the OCC field `expected_insurer_version` (§2.6). The cited valuation standard code must resolve to some standard (`ERR_VALUATION_STANDARD_NOT_FOUND`, 404) and must have a currently `ACTIVE` version (`ERR_VALUATION_STANDARD_NOT_ACTIVE`, 422, checked after the expected-version check); the server pins that active version's label into the filing's `valuation_standard_version_label` at creation. Creation also supersedes: any existing filing of the same (`insurer_id`, `period_year`, `period_quarter`) that is not already `SUPERSEDED` — whether `DRAFT`, `SUBMITTED`, `EDITS_FAILED`, or `VALIDATED` — becomes `SUPERSEDED`. A superseded `VALIDATED` filing keeps its RBC report for history, but the insurer's `latest_rbc_ratio` and `latest_action_level` are recomputed to null until a successor filing validates — this nulling applies even when the insurer holds validated filings for other periods, and the insurer's `status` is not changed by supersession. The new filing starts in `DRAFT` with `edit_failures` empty, and the insurer's `version` increments by exactly one. An insurer's filing list can be narrowed by the optional `period_year` and `status` filters.

Submitting a filing requires it to be in `DRAFT` (`ERR_FILING_NOT_DRAFT`, 409) and the caller's `X-User-ID` to equal the filing's `insurer_id` (`ERR_FORBIDDEN`); the filing moves to `SUBMITTED` and its `version` increments.

Validation is performed by `AssociationStaff`. The filing must be `SUBMITTED` (`ERR_FILING_NOT_SUBMITTED`, 409), and — checked after that state gate — the pinned `valuation_standard_version_label` must still be the `ACTIVE` version of its code, otherwise `ERR_VALUATION_STANDARD_NOT_ACTIVE` (422). The server then runs the validation edits E101, E103, E106, and E107. This document defines no failure condition for any of the four edits beyond the creation-time shape rules (§2.8 stage 5) that every filed payload has already passed, so a filing that reaches validation always passes all four; the `EDITS_FAILED` outcome below is specified for completeness and does not occur in practice. Validation is not an all-or-error operation: it returns success (HTTP 200) either way. If every edit passes, the filing becomes `VALIDATED` with `edit_failures` reset to an empty list, and the risk-based capital cascade below fires. If at least one edit fails, the filing becomes `EDITS_FAILED` with `edit_failures` holding the list of failed edit ids — always a subset of E101, E103, E106, and E107 — and no RBC report is created; in both branches the filing's `version` increments.

The pass cascade runs in three hops. Hop 1 computes the filing's RBC report — exactly one report per validated filing, keyed back by `filing_id` and carrying the denormalized `insurer_naic_code` for analysis reads. Total adjusted capital, `tac_cents`, is the filing's `reported_surplus_cents` carried verbatim at two decimals. The authorized control level has two variants, and the rounding order is pinned: the three integer-cent risk charges are squared and summed first, the square root of that sum is taken next, and only then is the result rounded half-up to two decimals to form `acl_covariance_cents`; dividing by the unrounded square root is a prohibited order — with charges of 1, 1, and 1 cents against a surplus of 3 cents, the pinned order yields a ratio of 1.7341 while the unpinned order yields 1.7321. The additive variant `acl_additive_cents` is simply the sum of the three charges at two decimals. The official ratio `ratio_covariance` is `tac_cents` divided by the rounded `acl_covariance_cents`, rounded half-up to four decimals; `ratio_additive` divides by `acl_additive_cents` the same way. When all three risk charges are zero, both rounded capital requirements are zero and each ratio is defined as 0.0000 rather than being undefined, which classifies the filing `MANDATORY_CONTROL` under hop 2.

Hop 2 classifies the filing. From `ratio_covariance`: at least 2.0000 maps to `NONE`; at least 1.5000 but below 2.0000 to `COMPANY_ACTION`; at least 1.0000 but below 1.5000 to `REGULATORY_ACTION`; at least 0.7000 but below 1.0000 to `AUTHORIZED_CONTROL`; and anything below 0.7000 to `MANDATORY_CONTROL`. Boundaries are inclusive at the lower edge of each band — exactly 2.0000 is `NONE`, while 1.9999 is `COMPANY_ACTION`. The insurer's `latest_rbc_ratio` and `latest_action_level` are set from this report, and the insurer's `status` becomes `UNDER_SUPERVISION` when the action level is `AUTHORIZED_CONTROL` or `MANDATORY_CONTROL`, otherwise `ACTIVE` — the same classification reinstates a supervised insurer back to `ACTIVE` when a later filing lands in the three milder bands. Hop 3 fires only when hop 2 leaves the insurer in `UNDER_SUPERVISION` — whether the insurer was newly supervised or already so: every market conduct response that insurer has filed on a still-`OPEN` call has its `escalation_flag` set to true (§3.7); a response already carrying a true flag is left untouched. Across the cascade, both the filing's and the insurer's `version` increment.

The two ratio variants coexist deliberately. The covariance variant is official: it drives `action_level`, `latest_rbc_ratio`, and the supervision cascade. The additive variant divides by a larger capital requirement and therefore yields an equal or lower ratio; it is reported alongside as `ratio_additive` for conservative review and never drives classification — identical filing data can classify differently under the two, as with charges of 1000000, 800000, and 600000 cents against a surplus of 4000000 cents, where the covariance ratio of 2.8284 reads `NONE` but the additive ratio of 1.6667 reads `COMPANY_ACTION`. Reading a filing's RBC reports returns a list of zero or one element.

### 3.5. Valuation and Reserving Standards

Valuation standards follow a strict author-versus-activator separation. An `Actuary` drafts a standard version with a `code` (for example VM-20), a `version_label` within that code line, and the actuarial `guidance_text`; the server records the caller's `X-User-ID` as `author_user_id`, and the draft starts in `DRAFT`. The pair (`code`, `version_label`) is unique (`ERR_DUPLICATE_STANDARD_VERSION`, 409).

Activation is also `Actuary` work, but never the author's own: the standard must be in `DRAFT` (`ERR_STANDARD_NOT_DRAFT`, 409) and — checked after that state gate — the caller's `X-User-ID` must differ from the standard's `author_user_id` (`ERR_SELF_ACTIVATION_FORBIDDEN`, 422). Activation moves the standard from `DRAFT` to `ACTIVE`, increments its `version`, and cascades: any other standard with the same `code` that is currently `ACTIVE` becomes `RETIRED`. Retirement reaches into the filing pipeline — a filing pinned to the retired version label will fail validation with `ERR_VALUATION_STANDARD_NOT_ACTIVE` (§3.4), which is how the standard-maintenance lifecycle forces filers onto current guidance.

### 3.6. Producer Licensing and the License Expiry Sweep

A producer is registered by `AssociationStaff` with a unique national producer number `npn` (`ERR_DUPLICATE_NPN`, 409), a `full_name`, and a `home_state_code` that is informational only and references nothing. The producer's `active_license_count` starts at 0 and is maintained by the license lifecycle below.

Applying for a license is `ProducerUser` work: the payload's `producer_id` must equal the caller's `X-User-ID` (`ERR_FORBIDDEN`), the `state_code` must name a registered state (`ERR_STATE_NOT_FOUND`, 404), and the `license_class` must be one of `LIFE`, `HEALTH`, `PROPERTY_CASUALTY`, or `PERSONAL_LINES`. The window from `effective_from` to `valid_until` is a closed interval — both endpoints are inside the license's life — and `valid_until` must be strictly after `effective_from` (`ERR_INVALID_REQUEST`, 400). For the same (`producer_id`, `state_code`, `license_class`) combination, the new window must not intersect the window of any existing license in `APPLIED` or `ISSUED` status, and because these intervals are closed, two windows that merely touch at an endpoint already count as overlapping (`ERR_LICENSE_WINDOW_OVERLAP`, 409). A successful application starts in `APPLIED`.

Issuance belongs to the `StateRegulator` of the licensing state — the acting regulator's State `code` must equal the license's `state_code` (`ERR_FORBIDDEN`). Two checks follow in order: the license must be `APPLIED` (`ERR_LICENSE_NOT_APPLIED`, 409), and the licensing state must not be `SUSPENDED` (`ERR_STATE_SUSPENDED`, 422) — an accreditation failure (§3.3) therefore freezes a department's licensing pipeline. Issuance moves the license from `APPLIED` to `ISSUED`, adds one to the producer's `active_license_count`, and increments the license's `version`.

Revocation is the same regulator's inverse act on an `ISSUED` license (`ERR_LICENSE_NOT_ISSUED`, 409), moving it to the terminal `REVOKED`, subtracting one from `active_license_count`, and incrementing `version`.

Finally, the logical clock itself is a lifecycle actor: when the clock is advanced strictly past a license's `valid_until`, the license moves from `ISSUED` to the terminal `EXPIRED`, subtracting one from the producer's `active_license_count` and incrementing the license's `version`. A license whose `valid_until` equals the current clock instant has not yet expired; the clock must pass it.

### 3.7. Market Conduct Data Calls and Examination Cost Allocation

A coordinated data call is opened by a `StateRegulator` supplying a unique `call_code` (`ERR_DUPLICATE_CALL_CODE`, 409), a `topic` describing the subject matter, and a `total_cost_cents` examination cost pool that must be at least 100000 cents (`ERR_CALL_COST_BELOW_MINIMUM`, 422). The call's `lead_state_code` is never client-supplied: it is derived from the acting regulator's own State `code` at creation, and only a regulator of that lead state may later close the call. A new call is `OPEN`.

Responding is `InsurerUser` work against an `OPEN` call — otherwise `ERR_CALL_NOT_OPEN` (409), a gate that applies identically to closing — and each insurer may respond at most once per call (`ERR_DUPLICATE_RESPONSE`, 409), with the state gate evaluated before the duplicate check. Each response records the call it answers as `call_id` and carries `direct_premium_cents`, which must be strictly positive, and `complaint_count`, which may be zero; the responding `insurer_naic_code` is derived from the acting insurer and is never client-supplied. At creation the server computes the response's `exam_priority_score` and sets its `escalation_flag` — true when the responding insurer is `UNDER_SUPERVISION` at that moment and false otherwise, and independently forced true later if the RBC supervision cascade catches the insurer while the call is still open (§3.4). Both `allocated_cost_cents` and `cost_share_excluded` remain null until the call closes.

The priority score blends three components. The complaint component takes the response's complaint rate — one hundred million times `complaint_count` divided by `direct_premium_cents` — caps that rate at 50, and multiplies the capped rate by a weight of 0.5. The capital component reads the insurer's `latest_rbc_ratio`: when the insurer has no validated filing and the ratio is null, it contributes a neutral 25 points; otherwise a ratio below 0.7000 contributes 50 points, below 1.0000 contributes 35, below 1.5000 contributes 20, below 2.0000 contributes 10, and a ratio of at least 2.0000 contributes nothing. The share component compares this response's premium to the sum of premiums across all responses on the call, this one included: a share of at least 25 percent contributes 20 points, a share of at least 10 percent but under 25 contributes 10, and anything smaller contributes nothing. The score is the sum of the three components, capped at 100, then rounded half-up to two decimal places.

Closing the call requires the acting regulator's State `code` to equal the call's `lead_state_code` (`ERR_FORBIDDEN`), the call to be `OPEN` (`ERR_CALL_NOT_OPEN`, 409), and at least one response to exist (`ERR_CALL_NO_RESPONSES`, 422). Closing runs the cost-share assessment, whose evaluation order is pinned and runs exactly once — no iteration to a fixed point. In pass one, each response's share is its premium divided by the premium sum over all responses; any response whose pass-one share falls below 5 percent is excluded, marked `cost_share_excluded` true, and allocated zero cents — with one pinned fallback: if that floor would exclude every response, no exclusion is applied and every response survives. In pass two, each surviving response's share is recomputed against the premium sum of the survivors only, and its raw allocation is the call's `total_cost_cents` multiplied by that share. Each survivor's `allocated_cost_cents` is the raw allocation rounded down to a whole cent; the leftover cents — the difference between `total_cost_cents` and the sum of the floored allocations — are then distributed one cent at a time to the survivors in descending order of their raw allocations' fractional parts, breaking ties by `insurer_naic_code` ascending, so the insurer codes decide ties deterministically and resource ids never do. Surviving responses are marked `cost_share_excluded` false. The invariant on completion is exact: the allocated cents across all responses sum to `total_cost_cents`. The call becomes `CLOSED` and its `version` increments.

## 4. Endpoint Definitions

All endpoints are mounted under `/naic`. Creating a new resource returns HTTP 201; state transitions, actions on existing resources, and the clock advance return HTTP 200 — note that filing validation returns 200 whether the edits pass or fail, with the outcome expressed in the filing's `status`. Reads return HTTP 200. Request payloads, preconditions, cascades, and error triggers are specified in §2 and §3; the table below is a navigational summary only.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /naic/_clock/set_current_utc | Advance the logical clock; expires licenses whose `valid_until` is passed | AssociationStaff |
| POST | /naic/model-acts | Create a model law/regulation in `DRAFTING` | AssociationStaff |
| GET | /naic/model-acts/{id} | Read one model act | All roles |
| POST | /naic/model-acts/{id}/close-ballot | Tally `CAST` ballots; act moves to `ADOPTED` on pass or back to `DRAFTING` on fail | AssociationStaff |
| POST | /naic/model-acts/{id}/publish | Publish an `ADOPTED` act; supersedes the prior published version and fires the coverage cascade | AssociationStaff |
| POST | /naic/exposure-drafts | Open an exposure draft on an act; the first draft moves it to `EXPOSURE_OPEN` | AssociationStaff |
| GET | /naic/model-acts/{id}/exposure-drafts | List exposure drafts of an act | All roles |
| POST | /naic/exposure-drafts/{id}/close | Close an `OPEN` draft once its comment window has ended | AssociationStaff |
| POST | /naic/model-acts/{id}/ballots | Cast the acting state's ballot on a `BALLOTING` act | StateRegulator |
| GET | /naic/model-acts/{id}/ballots | List ballots of an act | All roles |
| POST | /naic/states | Register a jurisdiction (starts `ACCREDITED`) | AssociationStaff |
| GET | /naic/states/{id} | Read one state | All roles |
| POST | /naic/adoptions | Record the acting state's adoption of a `PUBLISHED` act (OCC on state version) | StateRegulator |
| GET | /naic/model-acts/{id}/adoptions | List adoptions of an act | All roles |
| POST | /naic/adoptions/{id}/certify | Certify a `PENDING_CERTIFICATION` adoption into one of three outcome branches | AssociationStaff |
| POST | /naic/reviews | Schedule an accreditation review (rotation, overlap, and gap rules apply) | AssociationStaff |
| GET | /naic/states/{id}/reviews | List accreditation reviews of a state | All roles |
| POST | /naic/reviews/{id}/issue-findings | Team lead issues findings; computes `onsite_score` and `proposed_outcome` | ReviewTeamLead |
| POST | /naic/reviews/{id}/finalize | Finalize into `FINAL_PASS` or `FINAL_FAIL`; drives the state standing cascade | AssociationStaff |
| POST | /naic/insurers | Register an insurer | AssociationStaff |
| GET | /naic/insurers/{id} | Read one insurer | All roles |
| POST | /naic/filings | Create a `DRAFT` filing; supersedes any prior filing of the same period (OCC on insurer version) | InsurerUser |
| GET | /naic/insurers/{id}/filings | List filings of an insurer; optional `period_year` and `status` filters | All roles |
| GET | /naic/filings/{id} | Read one filing | All roles |
| POST | /naic/filings/{id}/submit | Submit a `DRAFT` filing | InsurerUser |
| POST | /naic/filings/{id}/validate | Run validation edits; pass yields `VALIDATED` plus the RBC cascade, fail yields `EDITS_FAILED` (200 either way) | AssociationStaff |
| GET | /naic/filings/{id}/rbc-reports | List the RBC reports computed from a filing (zero or one) | All roles |
| POST | /naic/producers | Register a producer | AssociationStaff |
| GET | /naic/producers/{id} | Read one producer | All roles |
| POST | /naic/licenses | Apply for a producer license in a jurisdiction | ProducerUser |
| GET | /naic/producers/{id}/licenses | List licenses of a producer | All roles |
| POST | /naic/licenses/{id}/issue | Issue an `APPLIED` license; blocked while the licensing state is `SUSPENDED` | StateRegulator |
| POST | /naic/licenses/{id}/revoke | Revoke an `ISSUED` license | StateRegulator |
| POST | /naic/market-conduct-calls | Open a coordinated data call; lead state is the acting regulator's state | StateRegulator |
| GET | /naic/market-conduct-calls/{id} | Read one data call | All roles |
| POST | /naic/market-conduct-calls/{id}/responses | File the acting insurer's response to an `OPEN` call | InsurerUser |
| GET | /naic/market-conduct-calls/{id}/responses | List responses of a call | All roles |
| POST | /naic/market-conduct-calls/{id}/close | Close an `OPEN` call and run the cost-share assessment | StateRegulator |
| POST | /naic/valuation-standards | Draft a valuation/reserving standard version | Actuary |
| POST | /naic/valuation-standards/{id}/activate | Activate a `DRAFT` standard (not the author); retires the prior `ACTIVE` version | Actuary |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3; this catalogue lists only the identifier and its HTTP status.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_INVALID_REQUEST | 400 |
| ERR_STALE_VERSION | 412 |
| ERR_MODEL_ACT_NOT_FOUND | 404 |
| ERR_EXPOSURE_DRAFT_NOT_FOUND | 404 |
| ERR_STATE_NOT_FOUND | 404 |
| ERR_ADOPTION_NOT_FOUND | 404 |
| ERR_REVIEW_NOT_FOUND | 404 |
| ERR_INSURER_NOT_FOUND | 404 |
| ERR_FILING_NOT_FOUND | 404 |
| ERR_PRODUCER_NOT_FOUND | 404 |
| ERR_LICENSE_NOT_FOUND | 404 |
| ERR_MARKET_CONDUCT_CALL_NOT_FOUND | 404 |
| ERR_VALUATION_STANDARD_NOT_FOUND | 404 |
| ERR_ACT_NOT_OPEN_FOR_EXPOSURE | 409 |
| ERR_ACT_NOT_BALLOTING | 409 |
| ERR_ACT_NOT_ADOPTED | 409 |
| ERR_ACT_NOT_PUBLISHED | 422 |
| ERR_EXPOSURE_DRAFT_NOT_OPEN | 409 |
| ERR_COMMENT_WINDOW_OPEN | 409 |
| ERR_ADOPTION_NOT_PENDING | 409 |
| ERR_REVIEW_NOT_SCHEDULED | 409 |
| ERR_REVIEW_NOT_FINDINGS_ISSUED | 409 |
| ERR_FILING_NOT_DRAFT | 409 |
| ERR_FILING_NOT_SUBMITTED | 409 |
| ERR_LICENSE_NOT_APPLIED | 409 |
| ERR_LICENSE_NOT_ISSUED | 409 |
| ERR_CALL_NOT_OPEN | 409 |
| ERR_STANDARD_NOT_DRAFT | 409 |
| ERR_REVIEWER_ROTATION_REQUIRED | 422 |
| ERR_SELF_ACTIVATION_FORBIDDEN | 422 |
| ERR_DUPLICATE_MODEL_ACT | 409 |
| ERR_DUPLICATE_NAIC_CODE | 409 |
| ERR_DUPLICATE_NPN | 409 |
| ERR_DUPLICATE_STANDARD_VERSION | 409 |
| ERR_DUPLICATE_CALL_CODE | 409 |
| ERR_DUPLICATE_BALLOT | 409 |
| ERR_DUPLICATE_ADOPTION | 409 |
| ERR_DUPLICATE_RESPONSE | 409 |
| ERR_COMMENT_WINDOW_TOO_SHORT | 422 |
| ERR_VOTING_STATE_SUSPENDED | 422 |
| ERR_STATE_SUSPENDED | 422 |
| ERR_EXPOSURE_WINDOW_OVERLAP | 409 |
| ERR_REVIEW_WINDOW_OVERLAP | 409 |
| ERR_REVIEW_GAP_TOO_SHORT | 422 |
| ERR_LICENSE_WINDOW_OVERLAP | 409 |
| ERR_VALUATION_STANDARD_NOT_ACTIVE | 422 |
| ERR_CALL_COST_BELOW_MINIMUM | 422 |
| ERR_CALL_NO_RESPONSES | 422 |












