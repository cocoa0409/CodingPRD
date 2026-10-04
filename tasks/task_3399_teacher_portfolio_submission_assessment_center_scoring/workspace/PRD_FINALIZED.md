# Teacher Portfolio Certification API — Product Requirements Document

## 1. Introduction

National-board-style teacher certification is a high-stakes, multi-instrument process. A candidate assembles portfolio entries — classroom video, student work samples, written commentary — and separately sits a timed content-knowledge session at an assessment center, while calibrated assessors score the portfolio evidence under double-blind conditions. This document specifies the API for the Teacher Portfolio Certification service, which operates that pipeline end to end: candidate eligibility screening against licensure and teaching-experience requirements, certification-cycle and assessment-center configuration, evidence upload under technical constraints, submission and retake windows, assessor recruitment, training and calibration with inter-rater reliability monitoring, weighted score aggregation against a certification threshold, certification renewal on continued-practice evidence, and state and district incentive programs with stipend administration.

Three commitments shape every rule that follows. Fairness: portfolio scores come from two blind reads with a divergence check and adjudication, assessors prove themselves against benchmark performances before going live, and no assessor ever scores a candidate from their own district. Temporal discipline: submission, booking, retake, and renewal windows are all evaluated against a server-held logical clock, never wall-clock time, so every deadline decision is reproducible. Fiscal control: stipend programs carry fixed budgets, proposals never encumber funds, approvals debit budgets under a compensating invariant, and revocation restores them. Read §2 for system-wide contracts, §3 for the business workflows those contracts serve, §4 for the endpoint inventory, and §5 for the error catalogue.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two identity headers: `X-User-ID` and `X-User-Role`. Both headers must be present and well-formed on every endpoint other than candidate self-registration; a missing or malformed header is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). If the presented role is not in the endpoint's authorized role list, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403). A third auth gate guards ownership: when an entity-backed caller touches a resource owned by someone else, the request fails with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

The role names, spelled exactly as the API expects them, are `Anonymous`, `Candidate`, `Assessor`, `ScoringAdministrator`, `BoardAdministrator`, and `IncentiveAdministrator`.

- `Anonymous` is an unauthenticated visitor whose only capability is self-registering as a candidate. When `X-User-Role` is `Anonymous`, `X-User-ID` is an opaque identifier not tied to any persisted entity; the server does not compare it to any resource's `id`.
- `Candidate` is a teacher pursuing certification who owns submissions, artifacts, bookings, and renewal applications. When `X-User-Role` is `Candidate`, `X-User-ID` is the `id` of the acting `Candidate` record; ownership checks on any candidate-scoped resource compare the resource's `candidate_id` field to `X-User-ID`. A candidate reads only their own candidate record, submissions, artifacts, bookings, certifications, renewals, and stipends.
- `Assessor` is a calibrated scoring professional who submits blind scores. When `X-User-Role` is `Assessor`, `X-User-ID` is the `id` of the acting `Assessor` record; submitting a score compares the assignment's `assessor_id` to `X-User-ID`, an assessor reads only their own assessor record and their own assignments, and an assessor may read a submission and its artifacts only while holding an assignment on that submission.
- `ScoringAdministrator` runs the assessment-center program: technical review of submissions, the assessor pipeline, assignment orchestration, and exam completion. When `X-User-Role` is `ScoringAdministrator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- `BoardAdministrator` handles board operations: cycle and center configuration, eligibility decisions, renewal review, and the logical clock. When `X-User-Role` is `BoardAdministrator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- `IncentiveAdministrator` administers state and district incentive programs and stipend disbursement. When `X-User-Role` is `IncentiveAdministrator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. Segregation of duties applies: an `IncentiveAdministrator` cannot verify eligibility, review renewals, or score, and the scoring and board roles cannot move stipend money.

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

List endpoints paginate through two query parameters. `limit` sets the page size: it defaults to 10, accepts a minimum of 1, and is capped at a maximum of 100. `offset` sets how many records to skip and defaults to 0. Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside `meta`, so a caller can page deterministically through the full result set. Unless an endpoint states otherwise, list results sort by `created_at` ascending.

### 2.4. The Logical Clock and Scheduled Sweeps

All temporal rules in this document are evaluated against a server-held **logical clock**, never against wall-clock time. At startup the clock reads exactly `2026-09-01T00:00:00Z`. A `BoardAdministrator` advances it through a test-driving capability that accepts a `to_iso8601` instant and answers with the resulting `current_utc`.

Advancing the clock performs exactly two sweeps, and no others. First, any assessment booking still in `BOOKED` status whose `slot_end_at` the new clock has passed flips to `NO_SHOW`. Second, any certification in `CERTIFIED` or `RENEWED` status whose `valid_until` the new clock has passed flips to `EXPIRED`. Component submissions are deliberately never expired by the clock — they expire only when their parent cycle leaves `OPEN` or leaves `SCORING` — so the submission-window temporal gate stays reachable regardless of how far the clock is advanced.

### 2.5. Resource Identity and Common Fields

Every persisted resource carries four system-managed properties. `id` is a server-minted UUID with no type prefix, rendered in the canonical hyphenated form — five lowercase hexadecimal groups of 8, 4, 4, 4, and 12 digits joined by hyphens, for example `550e8400-e29b-41d4-a716-446655440000`. `created_at` and `updated_at` are ISO 8601 UTC timestamps rendered with three fractional digits; `created_at` is fixed at creation while `updated_at` refreshes on every mutation. `version` is an integer that increments on every mutation of the resource.

One resource breaks this pattern deliberately: the evidence **artifact** record is immutable once uploaded, has no update endpoint, and carries only `id` and `created_at`. Both `updated_at` and `version` are absent from artifacts — clients must not expect them.

### 2.6. Score Scale, Grid, and Rounding Discipline

Every score in the system lives on a quarter-point grid within a fixed range: a valid score is at least 0.00, at most 4.00, and an exact multiple of 0.25. A score outside that range or off that grid is rejected with `ERR_SCORE_INVALID` (HTTP 422) wherever scores enter the system — booking completion, assignment score submission, and benchmark publication alike.

All rounding in the platform is **round half up**. The rounding order of the weighted certification total is pinned and non-negotiable: each component's weighted contribution is rounded half up to 3 decimal places **before** summing, the rounded contributions are summed, and the resulting sum is then rounded half up to 2 decimal places. Summing the raw products and rounding only once at the end is a different, non-conformant algorithm — with component weights 0.325, 0.275, 0.225, and 0.175 against scores 0.00, 0.25, 0.50, and 1.50, the pinned round-then-sum order yields 0.45 while sum-then-round yields 0.44. Component final scores are rounded half up to 2 decimal places. Reliability agreement rates are reported to 2 decimal places. Stipend amounts are integer cents, rounded half up at the multiplication step.

### 2.7. Windows, Intervals, and Boundary Semantics

A certification cycle's submission window is **half-open**: submissions are accepted from `submission_window_open` inclusive up to but not including `submission_window_close`. The same half-open reading governs the window-overlap check between cycles, so two cycles whose windows merely touch at an endpoint do not overlap and are both allowed. A cycle's `retake_window_close` must be at or after its own `submission_window_close`, and the retake boundary is exclusive — a retake requested exactly at `retake_window_close` is already too late.

An assessment booking's `slot_start_at` must be **strictly after** the current logical clock — a slot at exactly the current instant is rejected — and no later than the cycle's `submission_window_close`, with a slot exactly at the close still permitted. Capacity for a booking pools on the **exact** `slot_start_at` instant: two bookings thirty minutes apart draw from different pools even though their 120-minute sessions overlap in time. This is a deliberate contrast with cycle windows, which use half-open, adjacency-allowed semantics.

The renewal window is the exception to half-open discipline: it is **inclusive at both ends**, running from 90 days before a certification's `valid_until` through 30 days after it. A filing exactly at either boundary is inside the window.

### 2.8. Validation Priority Order

When several checks could reject the same request, the server evaluates them in a fixed order so callers always see the same error. The ten gates, in order:

1. **Header presence and well-formedness** (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`, 400) — on every endpoint except candidate self-registration.
2. **Role authorization** (`ERR_INSUFFICIENT_PERMISSIONS`, 403) — the presented role must be in the endpoint's role list.
3. **Ownership** (`ERR_NOT_RESOURCE_OWNER`, 403) — entity-backed callers acting on resources they do not own.
4. **Existence** (404) — path identifiers resolve to existing resources, validated strictly left-to-right along the URL; body-supplied identifiers such as `center_id`, `cycle_id`, `submission_id`, `benchmark_id`, and `assessor_id` resolve as well, each mapping to its own not-found error.
5. **State preconditions** (409) — the invoked transition must be legal from the resource's current state.
6. **Temporal windows** (422) — submission, retake, booking, renewal, and cycle-advance clock rules.
7. **Structural and numeric constraints** (400/409/422) — required fields, weight sums, component membership, score grids, attempt caps, capacity, and duplicate-active-resource guards.
8. **Scoring-integrity safety** (403) — conflict-of-interest and read-segregation bars on assignment creation.
9. **Portfolio composition** (422) — required-artifact and release-form checks at submit time.
10. **Fiscal** (422) — the stipend-approval budget gate.

Three intra-endpoint orderings are pinned on top of this list. A submission-submit request checks the state gate (`ERR_SUBMISSION_NOT_SUBMITTABLE`) **before** any temporal rule, and among the composition gates the required-artifact check (`ERR_REQUIRED_ARTIFACT_MISSING`) fires **before** the release-form check (`ERR_RELEASE_FORM_MISSING`). An assignment-creation request checks target ambiguity (`ERR_ASSIGNMENT_TARGET_AMBIGUOUS`) **before** conflict-of-interest. A cycle advance out of `OPEN` checks that the cycle is in fact `OPEN` (`ERR_INVALID_CYCLE_TRANSITION`) **before** it checks whether the submission window has closed (`ERR_CYCLE_WINDOW_STILL_OPEN`).

### 2.9. Concurrency Without Version Fields

No endpoint in this API accepts an expected-version field, and optimistic concurrency control is deliberately absent. Every write-write conflict in this domain is decidable by a sequential observer of state: a second retake create sees `attempt_number` already at the cycle cap and fails with `ERR_RETAKE_LIMIT_REACHED`; a second stipend approval sees `budget_remaining_cents` already debited below the amount and fails with `ERR_PROGRAM_BUDGET_EXHAUSTED`; a second attempt create for the same component sees the still-open attempt and fails with `ERR_ACTIVE_ATTEMPT_EXISTS`. Clients therefore never send a version token; they observe current state and act on it.

## 3. Business Logic & Workflows

### 3.1. Configuring and Advancing a Certification Cycle

A `BoardAdministrator` opens a season by creating a certification cycle with a unique `code` (for example, NB-2027), a `components` array defining the instruments of the cycle, and the window fields `submission_window_open`, `submission_window_close`, and `retake_window_close`. Each entry of `components` carries a `code`, a `kind` of either `ASSESSMENT` or `PORTFOLIO`, and a numeric `weight`. Exactly one component of the cycle may be of `ASSESSMENT` kind, and the component weights must sum to exactly 1.000; violating either rule rejects the creation with `ERR_WEIGHT_SUM_INVALID` (HTTP 422). The cycle's `certification_threshold` is the weighted total at or above which certification is granted — a total exactly equal to the threshold certifies. `max_attempts_per_component` caps how many attempts (the original plus retakes) a candidate may make per component and defaults to 2 when omitted. The new cycle's submission window must not overlap the window of any existing cycle in `DRAFT`, `OPEN`, or `SCORING` status under the half-open semantics of §2.7 — touching endpoints are allowed — or creation fails with `ERR_CYCLE_WINDOW_OVERLAP` (HTTP 409).

A cycle is born `DRAFT`. A `BoardAdministrator` advances it by naming the desired target in a `to` field: `DRAFT` to `OPEN`, then `OPEN` to `SCORING`, then `SCORING` to `CLOSED`, which is terminal. Requesting any other move is rejected with `ERR_INVALID_CYCLE_TRANSITION` (HTTP 409). The advance out of `OPEN` additionally requires the logical clock to have reached `submission_window_close`; before that instant the request fails with `ERR_CYCLE_WINDOW_STILL_OPEN` (HTTP 422), and per §2.8 the state check is evaluated before the window check. That advance sweeps every component submission of the cycle still sitting in `IN_PROGRESS`, `SUBMITTED`, or `RETURNED` into `EXPIRED`. The later advance from `SCORING` to `CLOSED` sweeps submissions still in `SCORING` or `ADJUDICATION_REQUIRED` into `EXPIRED`. `EXPIRED` is terminal for a submission: expired attempts never score and never count.

### 3.2. Candidate Intake and the Eligibility Loop

Anyone may self-register. Open registration creates a candidate record in `REGISTERED` status carrying `full_name`, a unique `email`, `license_number`, the two-letter `license_state` that issued the license, the employing `district_code`, `years_experience` as completed years of classroom teaching, and an optional `fte_fraction` teaching-load fraction which defaults to 1.0 and must lie between 0.5 and 1.0 inclusive. The `district_code` matters twice downstream: it drives district-specific stipend matching (§3.8) and bars same-district assessors from scoring the candidate's work (§3.6).

To enter review, the candidate submits their eligibility evidence, supplying `license_document_ref` and `employer_verification_ref` together — omitting either is `ERR_INVALID_REQUEST` (HTTP 400). The candidate must be in `REGISTERED` or `ELIGIBILITY_DENIED`; from anywhere else the request is `ERR_CANDIDATE_NOT_SUBMITTABLE` (HTTP 409). Both references are stored on the candidate record, and the candidate moves to `ELIGIBILITY_REVIEW`. A denied candidate may resubmit through the same loop, replacing the stored references.

A `BoardAdministrator` then decides the review by supplying a `decision` of APPROVE or REJECT with an optional `note`. The decision is only legal from `ELIGIBILITY_REVIEW` — otherwise `ERR_CANDIDATE_NOT_IN_REVIEW` (HTTP 409). APPROVE carries a hard floor: `years_experience` must be at least 3, the minimum teaching-experience requirement; approving a candidate below three years fails with `ERR_EXPERIENCE_REQUIREMENT_NOT_MET` (HTTP 422). Approval lands the candidate in `ELIGIBLE`; rejection lands them in `ELIGIBILITY_DENIED`. Either way, the request's `note` is stored as the candidate's `eligibility_note`. Only an `ELIGIBLE` candidate may begin component attempts or book an assessment session — the gate everywhere is `ERR_CANDIDATE_NOT_ELIGIBLE` (HTTP 409).

### 3.3. Component Attempts, Evidence Artifacts, and Retakes

An `ELIGIBLE` candidate begins a component attempt by naming a `component_code` within a chosen cycle. The code must exist in that cycle's `components` array, else `ERR_COMPONENT_NOT_IN_CYCLE` (HTTP 422), and the cycle must be `OPEN`, else `ERR_CYCLE_NOT_OPEN` (HTTP 409). The new attempt starts `IN_PROGRESS` with `attempt_number` 1 and a null `prior_submission_id`; its `kind` — `ASSESSMENT` or `PORTFOLIO` — is copied from the cycle's component definition at creation and never changes. While any earlier attempt of the same candidate, cycle, and component still sits in `IN_PROGRESS`, `SUBMITTED`, `RETURNED`, `SCORING`, or `ADJUDICATION_REQUIRED`, creating another is refused with `ERR_ACTIVE_ATTEMPT_EXISTS` (HTTP 409): only one open attempt per component triple may exist. The candidate's very first attempt in a cycle also auto-creates their certification record for that cycle in `PENDING` status with `weighted_total_provisional` at 0.0 — exactly one certification record ever exists per candidate-and-cycle pair.

Evidence uploads target a portfolio attempt the caller owns while it is in `IN_PROGRESS` or `RETURNED`. Each artifact declares an `artifact_type` — one of `VIDEO`, `STUDENT_WORK`, `WRITTEN_COMMENTARY`, or `RELEASE_FORM` — plus a `file_format` and `file_size_mb`, and conditionally `duration_minutes` and `subject_student_count`. Videos accept only the mp4 or mov containers and at most 500 MB; the three document types (`STUDENT_WORK`, `WRITTEN_COMMENTARY`, `RELEASE_FORM`) accept only pdf or docx and at most 50 MB. A container outside the allowed set for its type is `ERR_ARTIFACT_FORMAT_INVALID` (HTTP 422); a file over its type's size limit is `ERR_ARTIFACT_SIZE_EXCEEDED` (HTTP 422). `duration_minutes` is required if and only if the artifact is a `VIDEO` — omitting it for a video, or supplying it for a non-video, is `ERR_INVALID_REQUEST` (HTTP 400) — and a video longer than 15 minutes is rejected with `ERR_VIDEO_DURATION_EXCEEDED` (HTTP 422). `subject_student_count` is optional on every artifact type and defaults to null when omitted; when supplied it must be an integer of at least 1, else `ERR_INVALID_REQUEST` (HTTP 400). It records how many students appear in a `VIDEO` or `STUDENT_WORK` artifact, and only a count reported on one of those two types feeds the release-form check at submit time. Artifacts are immutable records (§2.5); correcting evidence means uploading a new artifact, never editing an old one.

Submitting an attempt — from `IN_PROGRESS`, or resubmitting from `RETURNED` in the revision loop — runs its gates in the fixed order of §2.8. The state gate fires first: an attempt not in `IN_PROGRESS` or `RETURNED` is `ERR_SUBMISSION_NOT_SUBMITTABLE` (HTTP 409). Then the cycle must be `OPEN` (`ERR_CYCLE_NOT_OPEN`), and the logical clock must fall within the half-open submission window, else `ERR_SUBMISSION_WINDOW_CLOSED` (HTTP 422). Portfolio composition follows for `PORTFOLIO` attempts: the submission must carry at least one `WRITTEN_COMMENTARY` artifact and at least one of `VIDEO` or `STUDENT_WORK`, else `ERR_REQUIRED_ARTIFACT_MISSING` (HTTP 422); and when any `VIDEO` or `STUDENT_WORK` artifact on the submission reports a `subject_student_count` of 1 or more, at least one `RELEASE_FORM` artifact must ride on the same submission, else `ERR_RELEASE_FORM_MISSING` (HTTP 422). A successful submit lands the attempt in `SUBMITTED`.

A `ScoringAdministrator` then performs technical review, again supplying a `decision` and an optional `note`, on an attempt in `SUBMITTED` — anything else is `ERR_SUBMISSION_NOT_REVIEWABLE` (HTTP 409). ACCEPT advances the attempt to `SCORING`; RETURN sends it back to `RETURNED` so the candidate can revise and resubmit. For an `ASSESSMENT` attempt nothing further happens at acceptance — its score arrives from the completed assessment-center session of §3.4.

Retakes give a scored component another chance. The candidate opens the next attempt from an attempt whose status is `SCORED`; from any other status the request is `ERR_SUBMISSION_NOT_RETAKEABLE` (HTTP 409). The new attempt links back to its source through `prior_submission_id`, takes `attempt_number` one higher than the count of prior attempts for the same candidate, cycle, and component, and may not push `attempt_number` beyond the cycle's `max_attempts_per_component` — breaching that cap is `ERR_RETAKE_LIMIT_REACHED` (HTTP 422). Retakes also close with the cycle: a retake requested at or after `retake_window_close` is `ERR_RETAKE_WINDOW_CLOSED` (HTTP 422). When the new attempt lands, every earlier attempt of the same component triple flips its `superseded` flag to true — only the highest-`attempt_number` row carries false — and if the candidate's certification for that cycle was `DENIED`, the decision reopens: the certification returns to `PENDING` with `weighted_total_final` cleared to null.

Every attempt of a component triple shares one more computed value. Once any attempt of the triple reaches `SCORED`, each attempt row of the triple carries the same `counted_score`: the maximum `final_score` across the triple's `SCORED` attempts, excluding anything `EXPIRED`, `RETURNED`, or still in flight. `counted_score` stays null until at least one attempt is `SCORED`, and it — not the latest attempt — is what final certification aggregation reads, so a worse retake never lowers a candidate's certified record.

### 3.4. Assessment-Center Sessions

The content-knowledge component runs at physical centers. A `BoardAdministrator` registers each assessment center with a `name`, the `region_code` it serves, and a `slot_capacity`: the number of seats available per slot start instant, which must be at least 1.

Booking a session is the candidate's move, naming a `center_id`, a `cycle_id`, and a `slot_start_at`. The gates, each with its own rejection: the candidate must be `ELIGIBLE` (`ERR_CANDIDATE_NOT_ELIGIBLE`); the candidate must hold an `IN_PROGRESS` attempt of the `ASSESSMENT` component in that cycle — with no such open attempt the booking fails with `ERR_SUBMISSION_NOT_FOUND` (HTTP 404); `slot_start_at` must be strictly after the logical clock, else `ERR_SLOT_IN_PAST` (HTTP 422); it must be no later than the cycle's `submission_window_close`, else `ERR_SLOT_OUTSIDE_WINDOW` (HTTP 422); and the candidate may hold at most one `BOOKED` booking per cycle, else `ERR_ACTIVE_BOOKING_EXISTS` (HTTP 409). Capacity is the last gate: the occupied count for a pool is the number of `BOOKED` bookings at that center with exactly that `slot_start_at`, and a booking that would push the occupied count to equal `slot_capacity` is rejected with `ERR_SLOT_CAPACITY_FULL` (HTTP 409) — a pool with exactly one seat free still accepts the booking. A created booking starts `BOOKED`, occupies one seat of its (center, slot start) pool, and its `slot_end_at` is computed as `slot_start_at` plus 120 minutes, the fixed session duration.

From `BOOKED`, three exits exist, and any transition requested from a status other than `BOOKED` is `ERR_BOOKING_NOT_TRANSITIONABLE` (HTTP 409). The owning candidate may cancel — the transition request carries a `to` of CANCELLED, anyone other than the owning candidate attempting it is refused with `ERR_NOT_RESOURCE_OWNER`, and the cancellation frees one seat: the pool's occupied count decrements and its remaining capacity increments, a compensating invariant that holds across every create-and-cancel pair. A `ScoringAdministrator` completes the session by carrying a `to` of COMPLETED together with the `earned_score` the candidate achieved; completion is only legal once the logical clock has reached `slot_start_at` — earlier is `ERR_BOOKING_NOT_COMPLETABLE` (HTTP 409) — the `earned_score` must be supplied (omitting it is `ERR_INVALID_REQUEST`) and must sit on the 0.25 grid within [0.00, 4.00] (`ERR_SCORE_INVALID`), and the score is recorded on the booking. The administrator may likewise mark a session NO_SHOW directly; independently, the clock sweep of §2.4 flips a booking to `NO_SHOW` on its own when the clock advances past `slot_end_at` with the booking still `BOOKED`. `COMPLETED`, `CANCELLED`, and `NO_SHOW` are all terminal.

Completion cascades through three hops. Hop 1: the candidate's matching `ASSESSMENT` attempt for that cycle — the latest attempt in `IN_PROGRESS` or `RETURNED` — transitions straight to `SCORED` with its `final_score` set to the booking's `earned_score`; an assessment component has exactly one score source, so no reads or averaging apply. Hop 2: certification aggregation recomputes for that candidate and cycle (§3.7), and when every component of the cycle now holds a `counted_score`, the certification is decided on the spot. Hop 3: if the decision certifies the candidate, stipend auto-proposal fires across every eligible open incentive program (§3.8).

### 3.5. The Assessor Pipeline: Recruitment, Calibration, and Reliability

A `ScoringAdministrator` recruits each assessor with a `full_name`, a unique `email`, and the assessor's own `home_district_code`, which later drives the conflict-of-interest bar. A new assessor starts `RECRUITED`. From there the administrator walks the training ladder by naming a target `to`: `RECRUITED` to `IN_TRAINING`, `IN_TRAINING` to `CALIBRATING`, and — once calibration succeeds — `CALIBRATED` to `ACTIVE`, the only status eligible for live scoring. A `SUSPENDED` assessor may be returned to `IN_TRAINING`, and that retraining move resets both `calibration_passes` and `calibration_failures` to 0. Two transitions are system-only and may never be requested directly: the move from `CALIBRATING` to `CALIBRATED` fires only when the calibration counters earn it, and threshold-driven suspensions fire only from the reliability machinery below. Any transition request outside the declared ladder — including direct requests for those system-only moves — is rejected with `ERR_INVALID_ASSESSOR_TRANSITION` (HTTP 409).

While `CALIBRATING`, an assessor scores benchmark performances (§3.6). A calibration read passes when its distance from the benchmark's `known_score` is within the benchmark's `tolerance` — the boundary is inclusive, so a read exactly `tolerance` away from the known score passes — and the verdict is recorded as the assignment's `is_within_tolerance`. Each passing read increments the assessor's `calibration_passes`, and when that counter reaches 2 the assessor auto-transitions from `CALIBRATING` to `CALIBRATED`, stamping `calibrated_at` from the logical clock. Each failing read increments `calibration_failures`, and when that counter reaches 3 the assessor auto-transitions to `SUSPENDED`.

Live scoring is continuously policed for reliability. Every finalized live (non-calibration) read feeds the assessor's trailing reliability window: the 10 most recent finalized live reads, ordered by `score_submitted_at` ascending with `created_at` breaking exact ties, while `scored_read_count` tracks how many finalized live reads the assessor has in total. Once 10 such reads exist, two rates are computed to 2 decimal places: `exact_agreement_rate`, the fraction of the window whose own score equals the submission's `final_score` exactly, and `adjacent_agreement_rate`, the fraction within 0.25 of it — the adjacent band means the same read set always yields an adjacent rate at least as high as the exact rate, and strictly higher whenever any read sits exactly 0.25 off. Both rates are null until the window fills. When a finalization pushes `scored_read_count` to at least 10 while the recomputed `exact_agreement_rate` falls below 0.70, the assessor is auto-suspended from `ACTIVE` to `SUSPENDED` — an exact rate of exactly 0.70 does not suspend. An administrator may also suspend an `ACTIVE` assessor directly through the ladder.

Suspension cascades, whatever its cause. Every scoring assignment the assessor still holds in `ASSIGNED` status flips to `REASSIGNED`; for each affected submission the missing reads become re-assignable, and the assessor's `open_assignment_count` — the count of their assignments in `ASSIGNED` or `SCORE_SUBMITTED`, and the selector's primary ranking key (§3.6) — refreshes accordingly.

### 3.6. Double-Blind Scoring, Calibration Reads, and Adjudication

Calibration rests on benchmark performances. A `ScoringAdministrator` publishes each benchmark with the `component_code` it exemplifies, a free-text `content_domain` descriptor, a panel-blessed `known_score` on the standard grid (§2.6, else `ERR_SCORE_INVALID`), and an optional `tolerance` defaulting to 0.25 — the pass band for calibration reads against it.

Scoring assignments are created by a `ScoringAdministrator` and come in exactly two flavors, distinguished by their target: naming a `submission_id` creates a live read, while naming a `benchmark_id` creates a calibration read. Exactly one of the two may be non-null — supplying neither or both is `ERR_ASSIGNMENT_TARGET_AMBIGUOUS` (HTTP 422), and per §2.8 this ambiguity check runs before any conflict-of-interest test. A live target submission must be in `SCORING` or `ADJUDICATION_REQUIRED`; anything else — including a request for a third read after reads 1 and 2 already agreed and finalized the attempt — is `ERR_SUBMISSION_NOT_SCORABLE` (HTTP 409). The assigned assessor must be `ACTIVE` for a live target or `CALIBRATING` for a benchmark target, else `ERR_ASSESSOR_NOT_SCORING_ELIGIBLE` (HTTP 409).

Two integrity bars then guard live assignments, each rejecting with HTTP 403. An assessor whose `home_district_code` equals the candidate's `district_code` may never hold a live assignment on that candidate's submission — that is `ERR_CONFLICT_OF_INTEREST`. And reads are segregated: the second read of a submission may not go to the assessor who took the first, and an adjudication read may not go to either earlier reader — a breach is `ERR_READ_SEGREGATION_VIOLATION`.

When the creation request omits `assessor_id`, the assessor selector policy runs instead. The eligibility filter requires every one of: the assessor is `ACTIVE`; their `home_district_code` differs from the submission candidate's `district_code`; and they hold no existing assignment on this submission in `ASSIGNED`, `SCORE_SUBMITTED`, or `FINALIZED` status. Survivors rank by `open_assignment_count` ascending; ties break toward the earlier `calibrated_at`, and any remaining tie breaks toward the earlier `created_at` — a total, deterministic order in which random ids never participate. An empty eligible pool fails creation with `ERR_NO_ELIGIBLE_ASSESSOR` (HTTP 409). However the assessor is chosen, creation computes `read_number` — 1 for the first live read of a submission, 2 for the second blind read, 3 for the adjudication read which is creatable only while the submission sits in `ADJUDICATION_REQUIRED`; calibration reads number sequentially per assessor — and increments the assessor's `open_assignment_count`. The new assignment starts `ASSIGNED`.

Scoring is the assessor's own act: they submit a `score` against their own assignment. The assignment must be `ASSIGNED`, else `ERR_ASSIGNMENT_NOT_SUBMITTABLE` (HTTP 409); the caller must be the assignment's assessor, else `ERR_NOT_RESOURCE_OWNER`; and the score must sit on the 0.25 grid within [0.00, 4.00], else `ERR_SCORE_INVALID`. The submission stamps the assignment's `score` and `score_submitted_at` from the logical clock and moves it to `SCORE_SUBMITTED` — with one exception: a calibration read finalizes immediately, its `is_within_tolerance` verdict is computed against the benchmark, the assessor's pass or failure counter increments, and the counter-driven assessor transitions of §3.5 may fire on the spot.

Live reads resolve in pairs under the double-blind agreement rule. When the second read of a submission lands, the two scores are compared against a divergence tolerance of 0.50. If the reads sit within 0.50 of each other — the boundary is inclusive — the attempt's `final_score` is the mean of the two reads rounded half up to 2 decimal places, both read assignments transition to `FINALIZED`, and the attempt becomes `SCORED`. If the reads differ by more than 0.50, the attempt instead moves to `ADJUDICATION_REQUIRED`, reads 1 and 2 remain `SCORE_SUBMITTED`, and the read-3 assignment becomes creatable. When the adjudication read lands, the attempt takes the adjudicator's score as its `final_score` — no averaging — and all three reads transition to `FINALIZED`. Every live-read finalization also updates the reader's trailing reliability window and may trigger the auto-suspension of §3.5. And every attempt reaching `SCORED` — by agreement or by adjudication — recomputes the component triple's `counted_score`, refreshes `superseded` flags across the triple's attempts, and re-runs the certification aggregation of §3.7 with its stipend cascade of §3.8.

### 3.7. Certification Decisions, Renewal, and Expiry

The weighted certification score walks the cycle's `components` in array order. Each component's contribution is its score input multiplied by that component's `weight`, rounded half up to 3 decimal places **first**; the rounded contributions are then summed, and the sum is rounded half up to 2 decimal places (§2.6 pins this order and shows it diverging from sum-then-round at boundaries). The score exists in two variants. `weighted_total_provisional` lives on the certification at all times, starts at 0.0, is recomputed on every score event and every retake creation, and uses each component's **latest-attempt** `final_score`, treating a component whose latest attempt is unscored as 0 — so a worse retake drags the provisional total down. `weighted_total_final` uses each component's `counted_score` — the best across `SCORED` attempts — so a worse retake cannot lower it; it is computed only once every component of the cycle has at least one `SCORED` attempt, it drives the certification decision, and it is stored on the certification when decided, staying null until then.

The decision fires automatically the moment every cycle component holds a `counted_score`. A `weighted_total_final` at or above the cycle's `certification_threshold` moves the certification from `PENDING` to `CERTIFIED` — equality certifies — stamping `certified_at` from the logical clock and computing `valid_until` as `certified_at` plus 1825 days, the fixed validity period. A total below the threshold moves the certification to `DENIED` instead. Certification triggers the stipend auto-proposal cascade of §3.8. A certification stays `PENDING` while any component remains unscored, and a retake after a denial reopens the decision exactly as §3.3 describes: back to `PENDING`, with `weighted_total_final` cleared to null.

Renewal keeps a certification alive on evidence of continued practice. The candidate files a renewal application under the certification's `certification_id` while the certification is `CERTIFIED` or `RENEWED` — against any other status the filing is `ERR_CERTIFICATION_NOT_RENEWABLE` (HTTP 409) — and while the logical clock sits inside the renewal window from 90 days before `valid_until` through 30 days after it, both bounds inclusive; outside the window the filing is `ERR_RENEWAL_WINDOW_NOT_OPEN` (HTTP 422). The application carries `evidence_items`, an array that must contain at least one item — an empty array is `ERR_INVALID_REQUEST` — where each item names an `evidence_type`, a `description`, and `hours` of at least 0; the application's `total_hours` is the sum of those hours. Only one application per certification may be in flight: filing while another application of the same certification is `SUBMITTED` fails with `ERR_ACTIVE_RENEWAL_EXISTS` (HTTP 409). Refiling against a `RETURNED` application instead reuses it — the application flips from `RETURNED` back to `SUBMITTED` with the new `evidence_items` and recomputed `total_hours` replacing the old.

A `BoardAdministrator` reviews each application, and the review is legal only from `SUBMITTED` or `RETURNED` — otherwise `ERR_RENEWAL_NOT_REVIEWABLE` (HTTP 409). APPROVE requires `total_hours` of at least 45 hours of continued-practice evidence — exactly 45 passes, fewer fails with `ERR_RENEWAL_HOURS_INSUFFICIENT` (HTTP 422) — and moves the application to `APPROVED`, the terminal state for applications, while the certification transitions to `RENEWED` and its `valid_until` extends by another 1825 days. Renewing an already-`RENEWED` certification is legal and simply adds another 1825 days to `valid_until` each time, without leaving `RENEWED`. A `decision` of RETURN moves the application to `RETURNED` and stores the request's `note` as the application's `review_note`, inviting the candidate's revised resubmission.

Expiry closes the loop. When the logical clock advances past `valid_until` for a certification in `CERTIFIED` or `RENEWED`, the sweep of §2.4 flips it to `EXPIRED`, the certification's terminal state.

### 3.8. Incentive Programs and Stipend Money Flow

States and districts fund certification through incentive programs. An `IncentiveAdministrator` creates each program with a `name`, the two-letter `sponsor_state`, an optional `sponsor_district_code`, a `budget_total_cents` of at least 0, a `base_stipend_cents`, and optionally an `early_bird_multiplier` — defaulting to 1.10 — together with an `early_bird_deadline`, which is null by default and disables the multiplier entirely when null. Eligibility geography works two ways: a program with a non-null `sponsor_district_code` is district-specific and only candidates whose `district_code` matches it qualify, while a program with a null `sponsor_district_code` is statewide and requires the candidate's `license_state` to equal `sponsor_state`. The program's `budget_remaining_cents` is derived, never stored by hand: it equals `budget_total_cents` minus the summed `amount_cents` of its stipends in `APPROVED` or `PAID` status — `PROPOSED` stipends encumber nothing. A program is `OPEN` whenever its remaining budget is positive and `EXHAUSTED` exactly when the remaining budget reaches 0; exhaustion is automatic on the debit that lands on 0, and a revocation that credits budget back above 0 returns the program to `OPEN`.

The moment a certification becomes `CERTIFIED`, stipend auto-proposal runs: for every `OPEN` program whose eligibility geography matches the candidate and whose `budget_remaining_cents` is above 0, the system creates a stipend in `PROPOSED` keyed by `program_id` and `certification_id`. At most one stipend row ever exists per program-and-certification pair, so pairs already holding a row are skipped silently. The proposed `amount_cents` is computed in a pinned evaluation order that resolves what looks like a circular dependency. First the multiplier: `early_bird_multiplier` applies when the certification's `certified_at` is at or before the program's `early_bird_deadline` — equality earns the multiplier — and 1.0 applies otherwise, including whenever the deadline is null. Second the tentative amount: `base_stipend_cents` multiplied by the candidate's `fte_fraction` multiplied by the multiplier, rounded half up to integer cents. Third the cap: the tentative amount is clipped down to the program's **current** `budget_remaining_cents`, so the proposal never exceeds what the program could still pay. Worked example: a 300000-cent base at 0.8 FTE with the 1.10 early multiplier tentatives to 264000 cents, and a program with 200000 cents remaining clips the proposal to 200000 cents; the same base at 1.0 FTE tentatives to 330000 cents. No money moves at proposal time — the debit happens only at approval.

Disbursement is the `IncentiveAdministrator`'s work, driving each stipend through a `to` target. Approving a `PROPOSED` stipend requires the program's `budget_remaining_cents` to cover the stipend's `amount_cents`; a shortfall — including the zero-remaining case of an `EXHAUSTED` program, which this single gate already covers — is `ERR_PROGRAM_BUDGET_EXHAUSTED` (HTTP 422). Approval debits `budget_remaining_cents` by `amount_cents`, and a debit landing exactly on 0 flips the program to `EXHAUSTED`. From `APPROVED`, the stipend moves to `PAID` when the money goes out. Revocation is possible from either `PROPOSED` or `APPROVED`: revoking a `PROPOSED` stipend touches no budget because it never encumbered any, while revoking an `APPROVED` stipend credits `amount_cents` back to `budget_remaining_cents` — and if the program sat `EXHAUSTED`, the credit reopens it to `OPEN`. The compensating invariant holds across every debit and credit: `budget_remaining_cents` plus the summed `amount_cents` of the program's `APPROVED` and `PAID` stipends always equals `budget_total_cents`. Any transition request outside these declared moves — from `PAID`, from `REVOKED`, or skipping states — is `ERR_STIPEND_NOT_TRANSITIONABLE` (HTTP 409). `PAID` and `REVOKED` are terminal for a stipend.

## 4. Endpoint Definitions

All endpoints are mounted under the API root. Endpoints that create a new resource answer 201 Created; reads, transitions, and actions on existing resources answer 200 OK. Unless a row says otherwise, a successful response returns the affected resource object in `data` per the envelope of §2.2. List endpoints accept the `limit` and `offset` pagination parameters of §2.3 plus the filter fields surfaced in §3 — `candidate_id`, `cycle_id`, `prior_submission_id`, `center_id`, `assessor_id`, `submission_id`, `benchmark_id`, and `status` as applicable per row. Request bodies and full response shapes are reconstructed from the §3 workflows; this table is the inventory, not the schema.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /_clock/set_current_utc | Advance the logical clock; sweeps bookings to NO_SHOW and certifications to EXPIRED | BoardAdministrator |
| POST | /cycles | Create a certification cycle in DRAFT | BoardAdministrator |
| GET | /cycles/{id} | Read one cycle | Candidate, Assessor, ScoringAdministrator, BoardAdministrator, IncentiveAdministrator |
| POST | /cycles/{id}/transition | Advance the cycle DRAFT → OPEN → SCORING → CLOSED | BoardAdministrator |
| POST | /benchmarks | Create a calibration benchmark with a known score | ScoringAdministrator |
| POST | /candidates | Self-register a candidate in REGISTERED | Anonymous |
| GET | /candidates/{id} | Read one candidate; candidates read only their own record | Candidate, ScoringAdministrator, BoardAdministrator, IncentiveAdministrator |
| POST | /candidates/{id}/submit-eligibility | Submit licensure and experience evidence into review | Candidate |
| POST | /candidates/{id}/verify-eligibility | Board eligibility decision: approve or reject | BoardAdministrator |
| POST | /cycles/{id}/submissions | Begin a component attempt for the calling candidate | Candidate |
| GET | /submissions/{id} | Read one submission; owner, assigned assessors, administrators | Candidate, Assessor, ScoringAdministrator, BoardAdministrator |
| GET | /submissions | List submissions with filters; candidates see only their own | Candidate, ScoringAdministrator, BoardAdministrator |
| POST | /submissions/{id}/submit | Submit or resubmit (from RETURNED) a component attempt | Candidate |
| POST | /submissions/{id}/tech-review | Technical review: accept into SCORING or return for revision | ScoringAdministrator |
| POST | /submissions/{id}/retake | Open the next attempt of a SCORED component | Candidate |
| POST | /submissions/{id}/artifacts | Upload an evidence artifact to an open portfolio attempt | Candidate |
| GET | /submissions/{id}/artifacts | List artifacts of a submission | Candidate, Assessor, ScoringAdministrator, BoardAdministrator |
| POST | /assessment-centers | Create an assessment center with per-slot capacity | BoardAdministrator |
| GET | /assessment-centers/{id} | Read one assessment center | Candidate, ScoringAdministrator, BoardAdministrator |
| POST | /bookings | Book an assessment session for the calling candidate | Candidate |
| GET | /bookings/{id} | Read one booking; the owning candidate and administrators | Candidate, ScoringAdministrator, BoardAdministrator |
| GET | /bookings | List bookings with filters | ScoringAdministrator, BoardAdministrator |
| POST | /bookings/{id}/transition | Cancel (owner), complete with a score, or mark NO_SHOW | Candidate, ScoringAdministrator |
| POST | /assessors | Recruit an assessor in RECRUITED | ScoringAdministrator |
| GET | /assessors/{id} | Read one assessor; assessors read only their own record | Assessor, ScoringAdministrator, BoardAdministrator |
| POST | /assessors/{id}/transition | Advance the assessor along the training ladder | ScoringAdministrator |
| POST | /assignments | Create a live or calibration scoring assignment | ScoringAdministrator |
| GET | /assignments/{id} | Read one assignment; the assigned assessor and administrators | Assessor, ScoringAdministrator, BoardAdministrator |
| GET | /assignments | List assignments with filters | ScoringAdministrator, BoardAdministrator |
| POST | /assignments/{id}/submit-score | Submit a blind score for the caller's own assignment | Assessor |
| GET | /certifications/{id} | Read one certification with weighted totals and validity | Candidate, ScoringAdministrator, BoardAdministrator, IncentiveAdministrator |
| GET | /certifications | List certifications with filters | ScoringAdministrator, BoardAdministrator, IncentiveAdministrator |
| POST | /certifications/{id}/renewals | File a renewal application with continued-practice evidence | Candidate |
| GET | /certifications/{id}/renewals | List renewal applications of a certification | Candidate, BoardAdministrator |
| POST | /renewals/{id}/review | Board renewal decision: approve or return | BoardAdministrator |
| POST | /incentive-programs | Create a state or district incentive program | IncentiveAdministrator |
| GET | /incentive-programs/{id} | Read one program including remaining budget | Candidate, ScoringAdministrator, BoardAdministrator, IncentiveAdministrator |
| GET | /incentive-programs/{id}/stipends | List stipend payments of a program | IncentiveAdministrator, BoardAdministrator |
| GET | /certifications/{id}/stipends | List stipend payments attached to a certification | Candidate, IncentiveAdministrator, BoardAdministrator |
| POST | /stipends/{id}/transition | Approve, pay out, or revoke a stipend | IncentiveAdministrator |

## 5. Error Code Catalogue

The catalogue below fixes each error identifier and its HTTP status. Trigger conditions are defined where the rules live — §2's system-wide principles and §3's workflow narratives — and are intentionally not repeated here.

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_INSUFFICIENT_PERMISSIONS | 403 |
| ERR_NOT_RESOURCE_OWNER | 403 |
| ERR_CYCLE_NOT_FOUND | 404 |
| ERR_CANDIDATE_NOT_FOUND | 404 |
| ERR_SUBMISSION_NOT_FOUND | 404 |
| ERR_CENTER_NOT_FOUND | 404 |
| ERR_BOOKING_NOT_FOUND | 404 |
| ERR_ASSESSOR_NOT_FOUND | 404 |
| ERR_BENCHMARK_NOT_FOUND | 404 |
| ERR_ASSIGNMENT_NOT_FOUND | 404 |
| ERR_CERTIFICATION_NOT_FOUND | 404 |
| ERR_RENEWAL_NOT_FOUND | 404 |
| ERR_PROGRAM_NOT_FOUND | 404 |
| ERR_STIPEND_NOT_FOUND | 404 |
| ERR_CANDIDATE_NOT_SUBMITTABLE | 409 |
| ERR_CANDIDATE_NOT_IN_REVIEW | 409 |
| ERR_CANDIDATE_NOT_ELIGIBLE | 409 |
| ERR_SUBMISSION_NOT_SUBMITTABLE | 409 |
| ERR_SUBMISSION_NOT_REVIEWABLE | 409 |
| ERR_SUBMISSION_NOT_SCORABLE | 409 |
| ERR_CYCLE_NOT_OPEN | 409 |
| ERR_INVALID_CYCLE_TRANSITION | 409 |
| ERR_BOOKING_NOT_TRANSITIONABLE | 409 |
| ERR_BOOKING_NOT_COMPLETABLE | 409 |
| ERR_INVALID_ASSESSOR_TRANSITION | 409 |
| ERR_ASSESSOR_NOT_SCORING_ELIGIBLE | 409 |
| ERR_RENEWAL_NOT_REVIEWABLE | 409 |
| ERR_CERTIFICATION_NOT_RENEWABLE | 409 |
| ERR_STIPEND_NOT_TRANSITIONABLE | 409 |
| ERR_ACTIVE_ATTEMPT_EXISTS | 409 |
| ERR_ACTIVE_RENEWAL_EXISTS | 409 |
| ERR_SUBMISSION_NOT_RETAKEABLE | 409 |
| ERR_SUBMISSION_WINDOW_CLOSED | 422 |
| ERR_RETAKE_WINDOW_CLOSED | 422 |
| ERR_SLOT_IN_PAST | 422 |
| ERR_SLOT_OUTSIDE_WINDOW | 422 |
| ERR_RENEWAL_WINDOW_NOT_OPEN | 422 |
| ERR_CYCLE_WINDOW_STILL_OPEN | 422 |
| ERR_INVALID_REQUEST | 400 |
| ERR_WEIGHT_SUM_INVALID | 422 |
| ERR_COMPONENT_NOT_IN_CYCLE | 422 |
| ERR_CYCLE_WINDOW_OVERLAP | 409 |
| ERR_SCORE_INVALID | 422 |
| ERR_ASSIGNMENT_TARGET_AMBIGUOUS | 422 |
| ERR_RETAKE_LIMIT_REACHED | 422 |
| ERR_SLOT_CAPACITY_FULL | 409 |
| ERR_ACTIVE_BOOKING_EXISTS | 409 |
| ERR_EXPERIENCE_REQUIREMENT_NOT_MET | 422 |
| ERR_ARTIFACT_FORMAT_INVALID | 422 |
| ERR_ARTIFACT_SIZE_EXCEEDED | 422 |
| ERR_VIDEO_DURATION_EXCEEDED | 422 |
| ERR_NO_ELIGIBLE_ASSESSOR | 409 |
| ERR_RENEWAL_HOURS_INSUFFICIENT | 422 |
| ERR_CONFLICT_OF_INTEREST | 403 |
| ERR_READ_SEGREGATION_VIOLATION | 403 |
| ERR_REQUIRED_ARTIFACT_MISSING | 422 |
| ERR_RELEASE_FORM_MISSING | 422 |
| ERR_PROGRAM_BUDGET_EXHAUSTED | 422 |
