# Competitive Hiring Certificates API — Product Requirements Document

## 1. Introduction

Federal competitive hiring is a compliance-heavy pipeline in which every decision — how a position is graded, who may apply, how applicants are assessed and ranked, and why a selecting official may bypass a veteran — must be defensible under audit. This document specifies the Competitive Hiring Certificates API, a system that administers that pipeline end to end under Office of Personnel Management rules: position classification and grade determination from documented duties, qualification standards published by occupational series, job announcement construction with open periods and areas of consideration, applicant assessment producing quality categories rather than numeric rankings with subject matter expert involvement, veterans preference adjudication with pass-over procedures, certificate issuance to selecting officials, and the sequencing of tentative offers, suitability review, and security clearance before entry on duty.

The API serves nine operator roles, from `HRSpecialist` staffing actions through `OPMDelegate` delegated-examining authority to the `Applicant` self-service surface, and it encodes the procedural protections that distinguish federal hiring from ordinary recruiting: preference eligibles float ahead within quality categories, passing one over requires an approved objection, direct-hire and special hiring authorities bypass competitive ranking only with documented eligibility, certificates expire on a fixed validity clock, and applicants hold complaint and appeal rights inside fixed windows. Every rule below is stated exactly as the system enforces it; where narrative and tables could be read apart, the narrative is the requirement.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and invariants that apply to every endpoint and every resource.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. The declared roles are `HRSpecialist`, `HiringManager`, `SME`, `Applicant`, `SelectingOfficial`, `OPMDelegate`, `SuitabilityReviewer`, `SecurityAdjudicator`, and `PlatformAdmin`. A request with missing or malformed headers, or whose `X-User-Role` is not one of these declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not listed among an endpoint's authorized roles, or that violates an entity-backed ownership rule, is rejected with `ERR_FORBIDDEN` (HTTP 403).

Identity semantics differ by role. When `X-User-Role` is `Applicant`, `X-User-ID` is the `id` of the acting `Applicant`; ownership checks on any resource that references an applicant compare the resource's applicant foreign key to `X-User-ID`. An `Applicant` may therefore read only its own applicant record, its own applications, its own documents, its own appeals, and offers resting on its own applications, and may act — apply, upload, appeal, respond — only for itself. One registration nuance: when applicant registration is invoked under the `Applicant` role, the supplied `X-User-ID` is ignored and the `id` of the newly created record becomes that applicant's identity from then on.

The remaining eight roles — `HRSpecialist`, `HiringManager`, `SME`, `SelectingOfficial`, `OPMDelegate`, `SuitabilityReviewer`, `SecurityAdjudicator`, and `PlatformAdmin` — are opaque: `X-User-ID` is an operator identifier not tied to any persisted entity. The server may record it, for example as `sme_user_id` on an `Assessment`, `verified_by` on an `EligibilityDocument`, `adjudicated_by` on a `PassOverRequest`, `reviewer_id` on a `SuitabilityReview`, `adjudicator_id` on a `SecurityClearance`, or `suitability_reviewer_id` on an `Offer`, but it does not compare such an identifier to any entity's `id`. One ownership rule nonetheless binds an opaque role: an `SME` acts only on assessments it authored, so submitting or resubmitting an assessment requires the acting `X-User-ID` to equal the assessment's recorded `sme_user_id`, and a mismatch is `ERR_FORBIDDEN`.

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

List endpoints accept two query parameters. `limit` sets the maximum number of items returned; when omitted it defaults to 10, and it is bounded below by 1 and above by 100. `offset` sets the number of items skipped and defaults to 0. A `limit` outside 1–100, a negative `offset`, or a non-integer value for either parameter is rejected as `ERR_INVALID_REQUEST` (HTTP 400). Unless otherwise specified, every list endpoint returns its resources sorted by `created_at` in ascending order; ties on `created_at` — common while the logical clock is frozen — fall to creation order, never to a record `id`.

List responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope; `has_more` is true exactly when items remain beyond the returned page. Two lists accept additional filters beyond paging: the application list of an announcement takes an optional `status` filter, and the offer list takes optional `application_id`, `certificate_entry_id`, and `status` filters. Filter values match exactly and are not validated against any enum; an unrecognized filter value simply yields an empty page.

### 2.4. Common Resource Properties

Every resource in the system — occupational series, positions, announcements, applicants, eligibility documents, applications, assessments, certificates, certificate entries, pass-over requests, offers, suitability reviews, security clearances, appeals, and appointments — carries four system-managed properties:

- `id`: a server-minted UUID, formatted as a bare UUID with no type prefix.
- `created_at`: an ISO 8601 UTC timestamp with three fractional digits, recorded at creation.
- `updated_at`: an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version`: an integer that increments by one on every mutation of the resource.

Cascaded mutations count as mutations: when one operation touches several resources, each resource actually changed by the cascade has its own `updated_at` refreshed and its own `version` incremented.

### 2.5. The Logical Clock

All server-recorded timestamps — among them `submitted_at`, `notified_at`, `issued_at`, `tentative_offered_at`, `responded_at`, `verified_at`, `filed_at`, and `recorded_at` — are taken from a single server-side logical clock, never from wall-clock time. Before any operator intervention the clock reads exactly 2026-09-01T00:00:00Z, and it never falls back to wall-clock time thereafter. Two renderings apply on the wire. `created_at`, `updated_at`, and the envelope's `api_request_timestamp` always render with three fractional digits (§2.2, §2.4). Every other timestamp the API emits — the clock-sourced fields named above, values computed from clock instants such as `expires_at`, `response_due_at`, and `deadline_at`, and stored client-supplied datetimes echoed back such as `open_at`, `close_at`, and `eod_date` — is rendered exactly as the clock reads: with no fractional part at a whole-second instant (the startup instant renders as `2026-09-01T00:00:00Z`), and with three fractional digits at any finer instant, truncated rather than rounded (§2.10). Client-supplied datetimes are normalized to UTC when echoed, and an instant supplied without an offset is read as UTC.

A `PlatformAdmin`-only test-driving capability, mounted at the platform root outside the `/hiring` prefix as `/_clock/set_current_utc`, advances the clock to a supplied `to_iso8601` instant and returns 200 with no resource payload; any parseable ISO 8601 instant is accepted, earlier or later — no monotonicity constraint is enforced. The clock is what drives the lazily-evaluated transitions described later. Certificate expiry is evaluated on the single-certificate read, on every certificate-scoped write (extension, return, selection, and filing a pass-over request against one of its entries), and whenever a rule must decide whether a certificate is still `ACTIVE` — certificate issuance's active-certificate bar (§3.6) and the `RATING`-appeal bar (§3.9) each evaluate every certificate of the announcement before testing. Offer expiry is evaluated on the single-offer read, on the offer list (every offer is evaluated, whether or not it survives the filters), and on every offer-scoped write (respond, suitability review, clearance recording, EOD scheduling, and EOD confirmation). No other read triggers evaluation: the certificate lists of an announcement, single-entry reads, a certificate's entry list, an entry's pass-over-request list, and the suitability, clearance, and appointment lists all serve stored state as-is.

### 2.6. Optimistic Concurrency Control

Exactly two write operations are guarded by optimistic concurrency control, and no other endpoint accepts a version field. Reclassifying a position requires the request to carry `expected_position_version`, holding the client's last observed `version` of the `Position`; if the position's current `version` differs — because the position has been classified or reclassified since the client last read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), and the client must refresh its factor view before re-grading. A reclassification legitimately supersedes the prior classification under the point-factor rule, which is exactly why a stale factor view must not silently overwrite a newer one.

Extending a certificate likewise requires `expected_certificate_version` matching the certificate's current `version`, with the same `ERR_STALE_VERSION` (HTTP 412) rejection on mismatch. Extensions legitimately stack — each one moves `expires_at` later — so a client extending from a stale `expires_at` view must refresh before extending again.

### 2.7. Validation Order

When a single request violates several rules, the failure it meets is the one with the lowest priority number. The categories run in this order: authentication of the headers first (priority 1); then role authorization and entity-backed ownership (2); then request-body shape — required fields present, types correct (strings non-empty, booleans not accepted where integers are required), enum values in range, numeric ranges honored, such as ratings between 1 and 5, `close_at` strictly later than `open_at`, `certificate_validity_days` between 30 and 90, and `wq_cut` below `bq_cut` — rejected as `ERR_INVALID_REQUEST` (3); then existence of every identifier in the path and every foreign key in the body (4, `ERR_NOT_FOUND`); then state-machine preconditions (5); then business-safety rules such as segregation of duties and the suitability-before-clearance sequence (6); then business constraints such as uniqueness, roster minima, and the selection gates (7); then temporal windows (8); then cross-resource posture rules (9); and finally the optimistic-concurrency check (10, `ERR_STALE_VERSION`). One placement note on priority 2: entity-backed ownership checks read the target entity, so they are evaluated immediately after the existence of the entities they read has been confirmed (priority 4) and before any state-machine, business, or temporal check; a dangling path identifier therefore yields `ERR_NOT_FOUND`, never `ERR_FORBIDDEN`, even for a caller that would also have failed ownership.

Two orderings deserve emphasis because the general ladder does not settle them. When certificate issuance is blocked both because another certificate of the announcement is still `ACTIVE` and because the new issuance window would overlap a prior certificate's window — an `ACTIVE` certificate always overlaps its own window — the rejection is `ERR_ACTIVE_CERTIFICATE_EXISTS`, never `ERR_CERTIFICATE_WINDOW_OVERLAP`. And on offer response the temporal check runs before the state check: a still-`TENTATIVE` offer whose response deadline has been reached is rejected with `ERR_OFFER_RESPONSE_EXPIRED` (and flips to `OFFER_EXPIRED` with its cascade), whereas an offer in any state other than `TENTATIVE` fails the state check with `ERR_OFFER_NOT_ACTIONABLE` regardless of what the clock says.

### 2.8. Nested Resource Retrieval

Paths that chain identifiers are validated left to right. A request naming a position and then an announcement beneath it first resolves the position, then the announcement; the first identifier that does not resolve to an existing entity produces `ERR_NOT_FOUND` (HTTP 404), and later segments are never examined. Foreign-key identifiers carried in request bodies — a `series_id` on position creation, an `applicant_id` on application submission, a `desired_entry_id` on a pass-over request — resolve the same way and draw the same error when they dangle. A body-carried foreign key that resolves to an entity outside the path's scope — a `certificate_entry_id` belonging to a certificate other than the one named in the path, for example — draws the same `ERR_NOT_FOUND` as a dangling identifier.

### 2.9. Two Interval Semantics: Open Periods and Certificate Windows

The system uses two different interval conventions, and confusing them changes behavior. An announcement's open period is half-open: applications are accepted while the logical clock is at or after `open_at` and strictly before `close_at`, so a submission landing at exactly `open_at` succeeds and one landing at exactly `close_at` is rejected with `ERR_OUTSIDE_OPEN_PERIOD`. Sibling announcements of the same position follow half-open overlap semantics: their periods must not intersect, but adjacency is allowed — a new announcement whose `open_at` equals an existing sibling's `close_at` is not a conflict, while a genuine intersection is rejected with `ERR_ANNOUNCEMENT_PERIOD_OVERLAP` (HTTP 409). Cancelled announcements still count as siblings for this rule, just as cancelled certificates' windows still count under the certificate rule below.

Certificate windows follow the opposite convention. The interval from `issued_at` to `expires_at` is closed, inclusive of both ends: a new issuance whose `issued_at` falls on or before any prior certificate's `expires_at` on the same announcement conflicts — adjacency is a conflict here, unlike announcement periods — and is rejected with `ERR_CERTIFICATE_WINDOW_OVERLAP` (HTTP 409). Windows of cancelled certificates still count toward this rule. Consistent with the closed interval, a certificate is `EXPIRED` once the logical clock reaches `expires_at`; at exactly `expires_at` it is already expired.

### 2.10. Precision and Rounding

All computed quantities in the system are either integers or timestamps; there are no decimal monetary values. Grade point totals, experience months, technical scores, rank positions, extension counts, and vacancy counts are integers produced without rounding, and timestamps are carried without rounding. The single rounding operation anywhere in the system lives inside the assessment scoring formula, where each weighted component is rounded half-up to a whole number individually before the components are summed; §3.5 pins that order and shows why it is load-bearing.

### 2.11. Cascades and Derived Consistency

State changes propagate across the aggregate. Cancelling an announcement withdraws its applications, cancels its active certificate, rescinds offers still mid-flight, and flips the affected certificate entries to `NOT_SELECTED`; the full cascade is specified in §3.2. Computed fields are refreshed eagerly rather than at read time: `remaining_vacancies` is recomputed immediately on every mutation that contributes to it — a selection, an offer declined, expired, or rescinded — and never lazily.

Some transitions fire without any client request on the affected resource. An announcement fills itself when its remaining vacancies reach zero; a certificate closes itself when its roster is exhausted; certificates and offers expire lazily against the logical clock on the next read or scoped action. Every mutation, whether requested directly or delivered by a cascade, refreshes the mutated resource's `updated_at` and increments its `version` (§2.4).

## 3. Business Logic & Workflows

### 3.1. Occupational Series and Position Classification

An `HRSpecialist` establishes the qualification framework by creating occupational series. A series carries a unique four-digit `series_code` (such as 0343), an official `title`, the grade span it can classify — `min_grade` and `max_grade`, each between 5 and 15 with the minimum not above the maximum — and its qualification standard: `quals_base_months` of specialized experience required at the minimum grade, `quals_months_per_grade_step` of additional months demanded for each grade above the minimum, a flag `allows_education_substitution` permitting education to stand in for experience, an `education_substitution_cap_months` ceiling on that credit, and a `positive_education_required` flag that, when set, demands a positive education claim for an applicant to be qualified at all. The three month-valued qualification fields are non-negative integers. Registering a series whose `series_code` is already taken fails with `ERR_DUPLICATE_KEY` (HTTP 409).

A `HiringManager` drafts a `Position` under a series by supplying the `series_id`, a position `title`, the hiring `org_code`, a `sensitivity_level` of `NONE`, `SECRET`, or `TOP_SECRET` that later drives the clearance gate, and four factor-evaluation levels — `factor_knowledge_level`, `factor_supervision_level`, `factor_complexity_level`, and `factor_impact_level` — each an integer from 1 to 5. The position is born in `DRAFT`, and two figures are computed at once and stored: `total_points`, the weighted point sum in which knowledge contributes 300 points per level, supervision 200, complexity 250, and impact 250; and `provisional_grade`, the narrative-method grade preview. The narrative preview caps the grade each factor can support — level 1 caps at grade 5, level 2 at grade 7, level 3 at grade 9, level 4 at grade 11, level 5 at grade 13 — and takes the lowest of the four caps. While the position remains `DRAFT`, its `official_grade` is null.

Classification is the `HRSpecialist`'s act of record, moving the position from `DRAFT` to `CLASSIFIED` and computing the official grade by the point-factor method. Because every factor level is at least 1, `total_points` is always at least 1000, and the official grade is the band containing the point total, with bands inclusive at both ends: 1000–1599 yields grade 5, 1600–2199 grade 7, 2200–2799 grade 9, 2800–3399 grade 11, 3400–3899 grade 12, 3900–4299 grade 13, 4300–4699 grade 14, and 4700–5000 grade 15. When the computed grade falls outside the series' inclusive range from `min_grade` to `max_grade`, the classification fails with `ERR_SERIES_GRADE_RANGE` (HTTP 422) and the position stays `DRAFT`; the same range check applies at every later re-grade. The two grading methods can legitimately disagree on identical inputs — levels of 3 across the board preview at grade 9 but classify at grade 11, and a profile of 5, 1, 1, 1 previews at grade 5 but classifies at grade 9 — so `provisional_grade` is deliberately left stored unchanged by classification precisely to preserve that comparison. Classification also increments the position's `version`.

A classified position can later be re-graded through a `CLASSIFIED` → `CLASSIFIED` self-loop. The `HRSpecialist` submits replacement values for all four factor levels together with the OCC guard `expected_position_version` (§2.6); the server reruns the point-factor computation over the new levels, rewrites the four factor fields along with `total_points` and `official_grade`, and increments the position's `version`. Reclassification is deliberately not retroactive: applications already screened keep their recorded determinations, and the revised grade feeds only the qualification screenings performed after it.

### 3.2. Job Announcements: Construction, Open Period, and Cancellation

With a classified position in hand, a `HiringManager` builds the public announcement bound to that position by `position_id`. Creating an announcement against a position still in `DRAFT` is rejected with `ERR_POSITION_NOT_CLASSIFIED` (HTTP 422). The announcement carries a unique `announcement_number` (a collision meets `ERR_DUPLICATE_KEY`), an `area_of_consideration` of `ALL_US_CITIZENS`, `STATUS_CANDIDATES`, or `AGENCY_ONLY`, a `hiring_authority` of `COMPETITIVE`, `DIRECT_HIRE`, `VEOA`, `SCHEDULE_A`, or `NONCOMPETITIVE_SPOUSE`, an `assessment_method` of `CATEGORY_RATING` or `UNRANKED`, the open-period endpoints `open_at` and `close_at`, a `vacancies_count` of at least 1, and three optional knobs: `bq_cut` defaulting to 95, `wq_cut` defaulting to 85, and `certificate_validity_days` defaulting to 60. Cut points must sit within 70 to 100 with `wq_cut` strictly below `bq_cut`, and the validity window must be between 30 and 90 days; malformed combinations are `ERR_INVALID_REQUEST`. Authority and method must cohere: `COMPETITIVE` requires `CATEGORY_RATING`, `DIRECT_HIRE` requires `UNRANKED`, while `VEOA`, `SCHEDULE_A`, and `NONCOMPETITIVE_SPOUSE` accept either, and an incoherent pairing fails with `ERR_AUTHORITY_METHOD_MISMATCH` (HTTP 422). The new period must also clear the sibling-overlap rule of §2.9. When several of these business constraints fail at once, the sibling-overlap check fires first, then the duplicate-`announcement_number` check, then the authority/method coherence check, and the position's `CLASSIFIED` posture (§2.7, priority 9) is examined after all three.

The announcement opens when the `HiringManager` moves it from `DRAFT` to `OPEN`, which is permitted only while the logical clock is still earlier than `close_at`; a request whose transition preconditions fail is rejected with `ERR_INVALID_STATE` (HTTP 409). While `OPEN`, applications flow in under the gates of §3.4. Closing flips `OPEN` → `CLOSED` and nothing more: the clock gate at submission time, not the close action itself, is what bounds the intake window. Opening, closing, and cancelling each increment the announcement's `version`.

Cancellation is the heaviest cascade in the system, and its blast radius depends on the state it is cancelled from. Cancelling a `DRAFT` announcement touches nothing else. Cancelling an `OPEN` announcement withdraws every application in `RECEIVED`, `QUALIFIED`, `INELIGIBLE`, or `RATED`. Cancelling a `CLOSED` or `CERT_ISSUED` announcement withdraws every application in `RECEIVED`, `QUALIFIED`, `RATED`, or `REFERRED` — note the asymmetric sets: `INELIGIBLE` applications are withdrawn only when the announcement is cancelled from `OPEN`, and `REFERRED` applications exist only once certificates have been issued — cancels every `ACTIVE` certificate of the announcement, and rescinds every offer in `TENTATIVE`, `ACCEPTED`, or `EOD_SCHEDULED` that was created from those certificates' entries. Each rescinded offer flips its certificate entry from `SELECTED` to `NOT_SELECTED` and pushes `remaining_vacancies` back up by one. Applications already in terminal states, and offers already `ENTERED_ON_DUTY`, are beyond recall.

The announcement's `remaining_vacancies` is a computed counter: `vacancies_count` minus the number of certificate entries belonging to this announcement that sit in `SELECTED` with their offer in `TENTATIVE`, `ACCEPTED`, `EOD_SCHEDULED`, or `ENTERED_ON_DUTY`; it is recomputed immediately on every contributing mutation per §2.11 and is visible on every announcement read. The first certificate issuance flips the announcement `CLOSED` → `CERT_ISSUED`; a re-issuance after the prior certificate has terminated keeps it in `CERT_ISSUED`. When `remaining_vacancies` reaches zero the announcement auto-transitions `CERT_ISSUED` → `FILLED`, a terminal state — and reaching `FILLED` does not recall or close an `ACTIVE` certificate: if vacancies later reappear because an offer is declined or rescinded, the still-`ACTIVE` certificate remains selectable, and only once no `ACTIVE` certificate with `REFERRED` entries exists would a fresh announcement be needed.

### 3.3. Applicants, Eligibility Documents, and Veterans Preference

Applicants enter the system by registration, either self-service under the `Applicant` role or brokered by an `HRSpecialist`. The record holds `full_name`, a unique `email` (collisions fail with `ERR_DUPLICATE_KEY`), the citizenship flag `is_us_citizen`, the status-candidate flag `is_current_federal_employee`, an optional `agency_code` naming the employing agency, and the `veteran_preference_claim` — one of `NONE`, `FIVE_POINT`, `TEN_POINT_CP`, or `TEN_POINT_CPS`. A claim is only a claim: two derived fields are computed from the document file. `preference_verified` is true exactly when the verified documents the claim requires are on file — a `FIVE_POINT` claim needs a verified `DD214`, `TEN_POINT_CP` and `TEN_POINT_CPS` each need a verified `DD214` plus a verified `VA_LETTER`, and a `NONE` claim is always verified. `preference_points` is 0 when the claim is `NONE` or unverified, 5 for a verified `FIVE_POINT` claim, and 10 for a verified ten-point claim of either kind.

The document file grows through uploads of a `doc_type` — `DD214`, `SF50`, `VA_LETTER`, `SCHEDULE_A_CERT`, or `MILITARY_SPOUSE_ORDERS` — performed by the owning `Applicant` or by an `OPMDelegate` on the applicant's file. A document arrives unverified: `verified` is false and `verified_by` and `verified_at` are null. Verification is the `OPMDelegate`'s exclusive act. It sets `verified` true, stamps `verified_by` with the delegate's `X-User-ID` and `verified_at` with the logical clock, increments the document's `version`, and immediately recomputes the owning applicant's `preference_verified` and `preference_points`, so a single verification can move an applicant from unentitled to entitled mid-process. Verification is repeatable: re-verifying an already-verified document succeeds, re-stamps `verified_by` and `verified_at`, increments the document's `version` again, and recomputes the applicant's derived preference fields once more.

### 3.4. Application Submission and Qualification Screening

An `Applicant` applies to an `OPEN` announcement, bound to it by `announcement_id`, with a payload naming the `applicant_id` and quantifying the claim: `claimed_experience_months` and `claimed_education_months`, each zero or more, plus three self-assessment ratings — `self_rating_knowledge`, `self_rating_skill`, and `self_rating_ability` — each an integer from 1 to 5. The server stamps `submitted_at` from the logical clock (this value later breaks ranking ties; a record's `id` never does) and initializes `notified_at` to the same submission instant. At submission the system scores the self-claim with the same formula the SME will later apply (§3.5): the result is stored as `provisional_score`, and `provisional_category` maps it against the announcement's cut points — a score at or above `bq_cut` yields `BEST_QUALIFIED`, at or above `wq_cut` but below `bq_cut` yields `WELL_QUALIFIED`, and anything lower yields `QUALIFIED`. Because the inputs are self-reported, this provisional pair routinely differs from the SME-certified score and category that later supersede it.

Submission is the most heavily gated operation in the system, and the gates fire in the priority order of §2.7. The announcement must be `OPEN`; otherwise the rejection is `ERR_ANNOUNCEMENT_NOT_OPEN` (HTTP 409). One application per applicant per announcement: a repeat pairing fails with `ERR_DUPLICATE_APPLICATION` (HTTP 409). The clock must sit inside the half-open period defined in §2.9, or the rejection is `ERR_OUTSIDE_OPEN_PERIOD` (HTTP 422). The area of consideration must admit the applicant, else `ERR_OUTSIDE_AREA_OF_CONSIDERATION` (HTTP 422): `ALL_US_CITIZENS` requires `is_us_citizen`; `STATUS_CANDIDATES` additionally requires `is_current_federal_employee` or a verified non-`NONE` preference claim (a `NONE` claim is always verified per §3.3 yet confers no preference, so it does not satisfy this prong); `AGENCY_ONLY` additionally requires the applicant's `agency_code` to equal the position's `org_code`. Finally, non-`COMPETITIVE` authorities demand a verified eligibility document of the mapped type at application time, else `ERR_ELIGIBILITY_DOC_REQUIRED` (HTTP 422): `VEOA` requires a verified `DD214`, `SCHEDULE_A` a verified `SCHEDULE_A_CERT`, and `NONCOMPETITIVE_SPOUSE` a verified `MILITARY_SPOUSE_ORDERS`, while `DIRECT_HIRE` demands nothing beyond the preference-verification rules of §3.3.

Screening is the `HRSpecialist`'s determination of minimum qualifications and moves a `RECEIVED` application to `QUALIFIED` or `INELIGIBLE`. Screening anything not in `RECEIVED` is rejected with `ERR_APPLICATION_WRONG_STATE` (HTTP 409), and the announcement must sit in `OPEN`, `CLOSED`, or `CERT_ISSUED` for the transition to exist at all; when both fail on one request, the application's own state is reported first (`ERR_APPLICATION_WRONG_STATE`) and the announcement-posture check second (`ERR_INVALID_STATE`). The determination reads the position's `official_grade` first — which presumes the position is `CLASSIFIED` — and then computes, in this pinned order: `required_experience_months` as the series' `quals_base_months` plus the difference between the official grade and `min_grade`, multiplied by `quals_months_per_grade_step`; the education credit as the lesser of `claimed_education_months` and the series' `education_substitution_cap_months` when `allows_education_substitution` holds, and zero otherwise; and `creditable_experience_months` as `claimed_experience_months` plus that credit. The applicant is qualified when creditable months are at least the required months — equality qualifies — and, when the series demands positive education, when `claimed_education_months` is greater than zero; any shortfall, or a missing positive-education claim on such a series, renders the applicant `INELIGIBLE`. Either outcome writes both computed month fields onto the application, refreshes `notified_at` from the logical clock — anchoring the appeal window of §3.9 — and increments the application's `version`.

### 3.5. SME Assessment and Quality-Category Assignment

Category-rated announcements route every qualified application through a subject matter expert. An `SME` opens a `DRAFT` assessment on a `QUALIFIED` application, supplying the three component ratings `rating_knowledge`, `rating_skill`, and `rating_ability` — each from 1 to 5 — while the server records the author's `X-User-ID` as `sme_user_id`. Creating an assessment for an application of an `UNRANKED` announcement is rejected with `ERR_ASSESSMENT_NOT_APPLICABLE` (HTTP 422), and creating one for an application not yet `QUALIFIED` is `ERR_APPLICATION_WRONG_STATE`. Record concurrency is capped: at most one assessment per application may sit in `DRAFT` or `SUBMITTED`, and at most one may ever stand `ACCEPTED` — violations surface as `ERR_ACTIVE_ASSESSMENT_EXISTS` (HTTP 409), both at creation time and at acceptance time. At creation the checks fire in this order: the application's `QUALIFIED` state, then the one-active-assessment cap, then the announcement's `CATEGORY_RATING` applicability.

Submission — the first `DRAFT` → `SUBMITTED` and every later `RETURNED` → `SUBMITTED` resubmission — belongs to the authoring `SME` alone under the ownership rule of §2.1, and it computes the `technical_score`. Each component is weighted and scaled: knowledge carries weight 0.30, skill 0.20, and ability 0.50, and each weight is multiplied by its rating and by the scale factor 6. The pinned order is to round each component half-up to a whole number first, then sum the three rounded components, then add the base of 70; with every rating between 1 and 5 the resulting score always lands between 76 and 100. The order is not cosmetic: summing before rounding produces a different number for some inputs — ratings of 3, 1, 1 score 79 under the pinned order but 80 if summed first, and ratings of 1, 3, 1 score 79 versus 78 — and only the pinned order is correct. At submission the assessment's `quality_category` is also mapped from the raw `technical_score` against the announcement's cut points, exactly as §3.4 maps the provisional score. A resubmission replaces each rating field the payload carries — a field omitted from the payload keeps its current value — and recomputes both results, and the return-resubmit cycle may repeat without bound; every submission increments the assessment's `version`.

An `HRSpecialist` disposes of submitted work. Acceptance moves the assessment `SUBMITTED` → `ACCEPTED` and requires the application still `QUALIFIED` (else `ERR_INVALID_STATE`) with no other `ACCEPTED` assessment on it; acceptance cascades the application `QUALIFIED` → `RATED`, copying the assessment's `technical_score` and `quality_category` onto the application and refreshing the application's `notified_at`. Until that cascade lands, the application's own `technical_score` and `quality_category` are null — and because assessments exist only under `CATEGORY_RATING`, applications of `UNRANKED` announcements carry both fields as null for their whole lives. Returning moves the assessment `SUBMITTED` → `RETURNED` and records the payload's `return_reason` — optional, stored as null when absent — handing the work back to the SME. Acting on an assessment in the wrong posture — accepting or returning anything not `SUBMITTED`, or submitting from a state other than `DRAFT` or `RETURNED` — is rejected with `ERR_ASSESSMENT_NOT_SUBMITTED` (HTTP 409). One rule outranks preference throughout the rating machinery: categories are computed from the raw score alone, and veterans preference points never move an applicant between categories. The only path out of `ACCEPTED` runs through a sustained rating appeal (§3.9), which forces the assessment back to `RETURNED` with `return_reason` set to `APPEAL_SUSTAINED`.

### 3.6. Certificate Issuance and Ranking

Once intake closes, the `HRSpecialist` issues the certificate of eligibles to the selecting official. Issuance requires the announcement in `CLOSED` or `CERT_ISSUED` — anything else is `ERR_ANNOUNCEMENT_NOT_CLOSED` (HTTP 409) — and it is barred while another certificate of the same announcement is still `ACTIVE`, a block reported as `ERR_ACTIVE_CERTIFICATE_EXISTS` (HTTP 409) which, per §2.7, outranks the window rule when both would fire. The new issuance window must also clear the closed-interval overlap rule of §2.9 against every prior certificate of the announcement, cancelled ones included (`ERR_CERTIFICATE_WINDOW_OVERLAP`), and the roster must satisfy the rule of many.

Under `CATEGORY_RATING`, the candidate pool is the announcement's `RATED` applications. Categories rank `BEST_QUALIFIED` above `WELL_QUALIFIED` above `QUALIFIED`; the roster opens with every candidate in the highest category present, and while it still holds fewer than three names and a lower non-empty category exists, the entire next lower category is merged in — never a partial category. If the final roster still falls short of three candidates, issuance fails with `ERR_INSUFFICIENT_ELIGIBLES` (HTTP 422). Under `UNRANKED` the roster is simply every `QUALIFIED` application, with no categories and no scores; the rule-of-many minimum does not apply there, but an empty pool still fails issuance with `ERR_INSUFFICIENT_ELIGIBLES`. Every rostered application transitions to `REFERRED` and gains a certificate entry.

Each entry is a fixed snapshot taken at issuance, recording its owning `certificate_id` and the referred `application_id`, plus `quality_category` (null on `UNRANKED` certificates), `preference_eligible` — true exactly when the applicant holds a verified non-`NONE` preference claim at that instant (a `NONE` claim is always verified per §3.3 yet confers no preference, so it is not eligibility; otherwise no `NONE`-claimant could ever be the non-preference desired entry of §3.8) — `preference_points` (0, 5, or 10), `augmented_score` computed as `technical_score` plus `preference_points` (null under `UNRANKED`), and a 1-based `rank_position`. Ranking under `CATEGORY_RATING` is lexicographic, each key descending unless noted: category first; then, within a category, a verified `TEN_POINT_CPS` entry floats to the top of that category; then preference-eligible entries ahead of non-eligible ones; then `augmented_score`; and any remaining tie falls to the earlier `submitted_at`, never to a record `id` — a tie that survives `submitted_at` (possible while the logical clock is frozen) falls to application creation order. Under `UNRANKED`, entries are ordered by `submitted_at` ascending alone, with the same creation-order tie-break. The certificate itself is stamped `issued_at` from the logical clock, takes `expires_at` as `issued_at` plus the announcement's `certificate_validity_days` days — a closed interval per §2.9 — starts its `extension_count` at 0, and is born `ACTIVE`; the first issuance flips the announcement `CLOSED` → `CERT_ISSUED`.

### 3.7. Certificate Lifecycle: Extension, Return, Expiry, and Exhaustion

A certificate dies four ways, and expiry is the quietest. Expiry is evaluated lazily: on any certificate read or certificate-scoped action, an `ACTIVE` certificate whose `expires_at` has been reached by the logical clock flips to `EXPIRED` — at exactly `expires_at` it is already expired — and every application it still holds in `REFERRED` returns to the pool, landing back in `RATED` under `CATEGORY_RATING` and in `QUALIFIED` under `UNRANKED`, free to be referred again by a later certificate.

An `HRSpecialist` may instead push the deadline later: each extension adds `additional_days` to `expires_at`, between 1 and 30 days per extension, at most two extensions over the certificate's life, and breaching either bound is `ERR_EXTENSION_LIMIT` (HTTP 422). The request carries the OCC guard `expected_certificate_version` (§2.6), and a successful extension moves `expires_at`, increments `extension_count`, and increments the certificate's `version`.

A `SelectingOfficial` may hand a certificate back — carrying an optional `reason` — but only while no entry on it is `SELECTED` with an offer still in `TENTATIVE`, `ACCEPTED`, or `EOD_SCHEDULED`; a return attempted while such an entry exists is rejected with `ERR_INVALID_STATE` (HTTP 409). The `ACTIVE` → `RETURNED` transition preserves each referred entry's historical row and returns those applications to their pools exactly as expiry does, and it increments the certificate's `version`. Any certificate-scoped action — selections, return, extension, or filing a pass-over request against one of its entries — attempted while the certificate is not `ACTIVE`, including one that has only just lazily expired, is rejected with `ERR_CERTIFICATE_NOT_ACTIVE` (HTTP 409).

Two further endings need no one's action. When no entry remains `REFERRED` — every entry having resolved to `SELECTED`, `PASSED_OVER`, or `NOT_SELECTED` — the roster is exhausted and the certificate auto-transitions `ACTIVE` → `CLOSED`. Vacancy consumption alone never closes a certificate: an `ACTIVE` certificate still holding `REFERRED` entries remains selectable while `remaining_vacancies` is positive. And an announcement cancellation per §3.2 drags every `ACTIVE` certificate to `CANCELLED`, rescinds the offers mid-flight created from its entries, flips those entries from `SELECTED` to `NOT_SELECTED`, and recomputes `remaining_vacancies`.

### 3.8. Selection, Pass-Over, and the Offer Itself

Selection is the `SelectingOfficial`'s core act: naming a `certificate_entry_id` on an `ACTIVE` certificate. The gates surface in §2.7's order. The certificate must be `ACTIVE`, else `ERR_CERTIFICATE_NOT_ACTIVE`. The entry and its application must still stand in `REFERRED`; a state-machine violation draws the generic `ERR_INVALID_STATE` (HTTP 409). While a `PENDING` pass-over request names a higher-ranked `REFERRED` preference-eligible entry on the same certificate, selections of lower-ranked entries are blocked with `ERR_PASS_OVER_PENDING` (HTTP 409), and adjudication of that request to either outcome clears the block. On a `CATEGORY_RATING` certificate, no entry may be selected while a `REFERRED` entry in a strictly higher category exists on the same certificate — `ERR_CATEGORY_BYPASS` (HTTP 422) — and a pass-over approval cannot cure a category bypass, while `UNRANKED` certificates carry no categories and bypass this gate entirely. Again under `CATEGORY_RATING`, a non-preference-eligible entry may not be selected while a `REFERRED` preference-eligible entry with a smaller `rank_position` exists in the same category, unless an `APPROVED` pass-over request covers exactly that target-and-desired pair; a violation is `ERR_PASS_OVER_REQUIRED` (HTTP 422), and `UNRANKED` selection has no preference-ordering gate at all. Finally, `remaining_vacancies` must be positive, else `ERR_NO_REMAINING_VACANCIES` (HTTP 409).

A clean selection flips the entry `REFERRED` → `SELECTED` and the application `REFERRED` → `SELECTED`, and creates the offer in `TENTATIVE` with `tentative_offered_at` stamped from the logical clock and `response_due_at` set five days later. `remaining_vacancies` drops by one at once, which may auto-fill the announcement per §3.2, and if the selection emptied the certificate of `REFERRED` entries the certificate auto-closes per §3.7.

To reach a lower-ranked non-preference candidate, the official files a pass-over request against the preference-eligible entry standing in the way, the request naming that entry as `certificate_entry_id` and supplying the `desired_entry_id`, a `reason_code` of `INADEQUATE_EXPERIENCE`, `MISCONDUCT`, or `OTHER`, and a free-text `justification`. The target must be preference-eligible and must rank above the desired entry — that is, hold a smaller `rank_position` — and the desired entry must not itself be preference-eligible; failure of any of these is `ERR_NOT_PREFERENCE_ELIGIBLE` (HTTP 422). Creation applies the certificate-`ACTIVE` gate against the target's certificate and otherwise validates only the eligibility and relative-rank rules; it does not require either entry to still stand `REFERRED`, nor that the desired entry belong to the same certificate as the target. Adjudication belongs to the `OPMDelegate` and acts only on a `PENDING` request — anything else is `ERR_PASS_OVER_NOT_PENDING` (HTTP 409). An `outcome` of `APPROVED` moves the target entry `REFERRED` → `PASSED_OVER`, a terminal resting place — applied only while the target still stands `REFERRED`, otherwise leaving the entries untouched — and records the delegate's `X-User-ID` as `adjudicated_by`; `DENIED` records `adjudicated_by` and leaves the entries untouched. Either outcome clears the pending block described above, increments the request's `version`, and an optional `adjudication_note` may accompany the decision.

The offer's first move then belongs to the applicant. Responding — with a payload `response` of `ACCEPT` or `DECLINE` — requires the offer still `TENTATIVE`, the acting `X-User-ID` equal to the `applicant_id` of the offer's application, and the clock still short of `response_due_at`; either reply stamps `responded_at` and increments the offer's `version`. Per §2.7 the deadline check runs before the state check on this operation: a `TENTATIVE` offer whose deadline has been reached is rejected with `ERR_OFFER_RESPONSE_EXPIRED` (HTTP 409) and flips to `OFFER_EXPIRED` on the spot, while an offer already past `TENTATIVE` draws `ERR_OFFER_NOT_ACTIONABLE` (HTTP 409) whatever the clock says. Decline and expiry share a cascade: the application and the certificate entry both move to `NOT_SELECTED`, and `remaining_vacancies` climbs by one. The same expiry transition also fires lazily whenever an offer is read or an offer-scoped action is attempted at or past `response_due_at`.

### 3.9. Suitability, Security Clearance, Entry on Duty, and Appeals

An accepted offer enters the pre-employment gauntlet, and the sequence is fixed: suitability before clearance, both before entry on duty. A `SuitabilityReviewer` records the offer's single suitability review — an `outcome` of `FAVORABLE` or `UNFAVORABLE` with optional `notes` — while the offer is `ACCEPTED`; any other posture is `ERR_OFFER_NOT_ACTIONABLE`. The act stamps the offer's `suitability_reviewer_id` from the caller's `X-User-ID` and records the review's own `reviewer_id` and `recorded_at`, and a second review on the same offer is `ERR_REVIEW_ALREADY_RECORDED` (HTTP 409). An `UNFAVORABLE` outcome rescinds the offer on the spot, running the same `NOT_SELECTED` cascade as a decline: application and entry flip, and `remaining_vacancies` climbs.

The security clearance follows, recorded by a `SecurityAdjudicator` with an `outcome` of `FAVORABLE_INTERIM`, `FAVORABLE_FINAL`, or `UNFAVORABLE`. Recording it requires the offer `ACCEPTED` — any other posture is again `ERR_OFFER_NOT_ACTIONABLE` — and a `FAVORABLE` suitability review already on file: suitability precedes clearance, and its absence is `ERR_SUITABILITY_NOT_FAVORABLE` (HTTP 422). The record copies `level_required` from the position's `sensitivity_level`, stamps `adjudicator_id` and `recorded_at` from the caller and the clock, admits no second clearance per offer (`ERR_REVIEW_ALREADY_RECORDED`), and an `UNFAVORABLE` outcome rescinds the offer with the same cascade. Segregation of duties binds the pair in both directions: the adjudicator's `X-User-ID` must differ from the offer's `suitability_reviewer_id`, and symmetrically the suitability reviewer must differ from any prior clearance adjudicator on the same offer — a collision in either direction is `ERR_SEGREGATION_OF_DUTIES` (HTTP 422).

Scheduling entry on duty is the `SelectingOfficial`'s act on an `ACCEPTED` offer — the wrong posture is again `ERR_OFFER_NOT_ACTIONABLE`. It demands the favorable suitability review (`ERR_SUITABILITY_NOT_FAVORABLE`), the clearance gate scaled to the position's sensitivity — `NONE` needs no clearance record at all, `SECRET` accepts `FAVORABLE_INTERIM` or `FAVORABLE_FINAL`, and `TOP_SECRET` insists on `FAVORABLE_FINAL` alone, shortfalls drawing `ERR_CLEARANCE_INSUFFICIENT` (HTTP 422) — and an `eod_date` not earlier than the current logical-clock date, else `ERR_EOD_DATE_INVALID` (HTTP 422); the date floor compares calendar dates, so an `eod_date` anywhere on the current date is accepted whatever the clock's time of day. Success stores `eod_date`, moves the offer to `EOD_SCHEDULED`, and increments its `version`. Confirmation is the `HRSpecialist`'s act on an `EOD_SCHEDULED` offer — any other posture is `ERR_OFFER_NOT_ACTIONABLE` — performed once the logical clock has reached the stored `eod_date` instant — this check compares full instants, not calendar dates; earlier is again `ERR_EOD_DATE_INVALID`, and the act re-validates the same suitability and clearance gates before moving the offer to `ENTERED_ON_DUTY`. Confirmation then flips the application `SELECTED` → `HIRED` and creates the appointment bound to the consummated `offer_id`: the `appointment_type` derives from the announcement's `hiring_authority` — `COMPETITIVE` for a competitive hire, `DIRECT_HIRE` for a direct hire, `SPECIAL_AUTHORITY` for every other authority — and the appointment's `eod_date` copies the offer's. Both `ENTERED_ON_DUTY` and `HIRED` are terminal, as are `DECLINED`, `OFFER_EXPIRED`, and `RESCINDED` on the offer side and `NOT_SELECTED` and `WITHDRAWN` on the application side.

Applicants hold appeal rights against adverse determinations, exercised by the owning `Applicant` with `grounds` of `QUALIFICATION`, `RATING`, or `PREFERENCE`. Filing requires the application in `INELIGIBLE` or `RATED`, and a `RATING` appeal additionally requires that no entry on an `ACTIVE` certificate references the application — a certificate's `ACTIVE`-ness here is determined after applying its lazy expiry evaluation (§2.5); violations are `ERR_APPEAL_NOT_ALLOWED_STATE` (HTTP 409), the same code that greets adjudication attempted on a non-`FILED` appeal. Grounds must match posture: `QUALIFICATION` only from `INELIGIBLE`, `RATING` only from `RATED`, and `PREFERENCE` from either, with mismatches drawing `ERR_APPEAL_GROUND_MISMATCH` (HTTP 422). A `QUALIFICATION` appeal must carry `corrected_experience_months`, zero or more, and omitting it is a malformed request under §2.7's shape rules. `RATING` and `PREFERENCE` filings may carry it optionally; when carried, it is stored on the appeal. The window is fixed: `deadline_at` is computed and stored as the application's `notified_at` plus fourteen days, and the filing itself must land strictly before that deadline — arriving at exactly `deadline_at` is already late and is rejected with `ERR_APPEAL_WINDOW_EXPIRED` (HTTP 422). A timely, well-formed filing is born `FILED` with `filed_at` taken from the clock.

Adjudication belongs to the `HRSpecialist`, who acts on a `FILED` appeal with an `outcome` of `SUSTAINED` or `DENIED` and an optional `adjudication_note`, and either decision increments the appeal's `version`. A sustained appeal cascades by ground. On `QUALIFICATION` or `PREFERENCE`, the application's `claimed_experience_months` is replaced by the appeal's `corrected_experience_months` when the appeal carries one (a `PREFERENCE` filing may omit it, in which case the claim stands) and the qualification determination of §3.4 is re-run: a passing re-screen moves the application `INELIGIBLE` → `QUALIFIED`, a failing one leaves it in `INELIGIBLE`, and either way the required and creditable month fields and `notified_at` are refreshed — a single sustained appeal lifts an application out of `INELIGIBLE` at most once. A sustained `PREFERENCE` appeal on a `RATED` application re-runs the same determination and refreshes the month fields and `notified_at`, but the application stays `RATED` — the rating itself stands. On `RATING`, the application's `ACCEPTED` assessment is forced to `RETURNED` with `return_reason` set to `APPEAL_SUSTAINED`, the application falls back `RATED` → `QUALIFIED` with its `technical_score` and `quality_category` cleared to null, and `notified_at` refreshes. A denied appeal touches nothing: the application is left exactly as it stood when the appeal was filed.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`: registering a series, drafting a position, creating an announcement, registering an applicant, uploading a document, submitting an application, filing an appeal, opening an assessment, issuing a certificate, filing a pass-over request, recording a selection (which creates the offer), recording a suitability review, and recording a security clearance. All other operations — reads, state transitions, and modifications of existing resources, including the clock-setting capability — return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/hiring/series` | Create an occupational series with its qualification standard | HRSpecialist |
| GET | `/hiring/series/{id}` | Read one occupational series | HRSpecialist, HiringManager |
| GET | `/hiring/series/{id}/positions` | List positions classified under a series | HRSpecialist, HiringManager |
| POST | `/hiring/positions` | Create a position in DRAFT with factor levels; provisional grade and point total computed immediately | HiringManager |
| GET | `/hiring/positions/{id}` | Read one position | HRSpecialist, HiringManager, SelectingOfficial |
| POST | `/hiring/positions/{id}/classify` | DRAFT → CLASSIFIED; computes the official grade; fails when the grade falls outside the series range | HRSpecialist |
| POST | `/hiring/positions/{id}/reclassifications` | CLASSIFIED → CLASSIFIED re-grade with new factor levels; OCC-guarded on the position version | HRSpecialist |
| POST | `/hiring/positions/{id}/announcements` | Create a job announcement for a CLASSIFIED position; open period must not overlap sibling announcements | HiringManager |
| GET | `/hiring/announcements/{id}` | Read one announcement, including the computed remaining vacancies | HRSpecialist, HiringManager, SelectingOfficial, OPMDelegate, Applicant, SME |
| GET | `/hiring/positions/{id}/announcements` | List announcements of a position | HRSpecialist, HiringManager, SelectingOfficial |
| POST | `/hiring/announcements/{id}/open` | DRAFT → OPEN | HiringManager |
| POST | `/hiring/announcements/{id}/close` | OPEN → CLOSED | HiringManager |
| POST | `/hiring/announcements/{id}/cancel` | DRAFT, OPEN, CLOSED, or CERT_ISSUED → CANCELLED with the full cancellation cascade | HiringManager |
| GET | `/hiring/announcements/{id}/applications` | List applications to an announcement | HRSpecialist, SelectingOfficial |
| GET | `/hiring/announcements/{id}/certificates` | List certificates issued from an announcement | HRSpecialist, SelectingOfficial |
| POST | `/hiring/applicants` | Register an applicant; under the Applicant role the response id becomes that applicant's identity | Applicant, HRSpecialist |
| GET | `/hiring/applicants/{id}` | Read one applicant; the Applicant role may only read its own id | Applicant, HRSpecialist, OPMDelegate |
| GET | `/hiring/applicants/{id}/applications` | List an applicant's applications | Applicant, HRSpecialist |
| POST | `/hiring/applicants/{id}/documents` | Upload an eligibility document, unverified | Applicant, OPMDelegate |
| GET | `/hiring/applicants/{id}/documents` | List an applicant's eligibility documents | Applicant, HRSpecialist, OPMDelegate |
| POST | `/hiring/documents/{id}/verify` | Mark a document verified; recomputes the applicant's preference verification and points | OPMDelegate |
| POST | `/hiring/announcements/{id}/applications` | Submit an application; computes the provisional score and category | Applicant |
| GET | `/hiring/applications/{id}` | Read one application; the Applicant role may only read its own | Applicant, HRSpecialist, SelectingOfficial, SME |
| POST | `/hiring/applications/{id}/screen` | RECEIVED → QUALIFIED or INELIGIBLE via the qualification determination | HRSpecialist |
| GET | `/hiring/applications/{id}/assessments` | List assessments of an application | HRSpecialist, SME |
| GET | `/hiring/applications/{id}/appeals` | List appeals of an application | Applicant, HRSpecialist |
| GET | `/hiring/applications/{id}/certificate-entries` | List certificate entries referencing an application, across certificates | HRSpecialist, SelectingOfficial |
| POST | `/hiring/applications/{id}/appeals` | File an appeal; posture-grounds match and the fourteen-day window are enforced | Applicant |
| POST | `/hiring/applications/{id}/assessments` | SME creates a DRAFT assessment for a QUALIFIED application of a CATEGORY_RATING announcement | SME |
| GET | `/hiring/assessments/{id}` | Read one assessment | SME, HRSpecialist |
| POST | `/hiring/assessments/{id}/submit` | DRAFT → SUBMITTED, or RETURNED → SUBMITTED resubmission optionally replacing ratings; computes score and category | SME |
| POST | `/hiring/assessments/{id}/accept` | SUBMITTED → ACCEPTED; cascades the application QUALIFIED → RATED | HRSpecialist |
| POST | `/hiring/assessments/{id}/return` | SUBMITTED → RETURNED with a reason | HRSpecialist |
| POST | `/hiring/announcements/{id}/certificates` | Issue a certificate of eligibles; builds and ranks the roster and flips the announcement to CERT_ISSUED | HRSpecialist |
| GET | `/hiring/certificates/{id}` | Read one certificate; lazily evaluates expiry against the logical clock | HRSpecialist, SelectingOfficial |
| POST | `/hiring/certificates/{id}/extend` | Extend the certificate window by additional days; OCC-guarded on the certificate version | HRSpecialist |
| POST | `/hiring/certificates/{id}/return` | ACTIVE → RETURNED; referred applications return to their pools | SelectingOfficial |
| GET | `/hiring/certificates/{id}/entries` | List a certificate's entries in rank-position order | HRSpecialist, SelectingOfficial |
| POST | `/hiring/certificates/{id}/selections` | Select a REFERRED entry; creates the TENTATIVE offer and recomputes remaining vacancies | SelectingOfficial |
| GET | `/hiring/entries/{id}` | Read one certificate entry | HRSpecialist, SelectingOfficial |
| GET | `/hiring/entries/{id}/pass-over-requests` | List pass-over requests naming an entry as target or as desired | HRSpecialist, SelectingOfficial, OPMDelegate |
| POST | `/hiring/entries/{id}/pass-over-requests` | Request approval to pass over the path's preference-eligible entry in favor of a desired entry | SelectingOfficial |
| POST | `/hiring/pass-over-requests/{id}/adjudicate` | PENDING → APPROVED (entry cascades to PASSED_OVER) or DENIED | OPMDelegate |
| GET | `/hiring/offers` | Filtered offer list; lazily evaluates response expiry on the listed offers | HRSpecialist, SelectingOfficial |
| GET | `/hiring/offers/{id}` | Read one offer; lazily evaluates response expiry; the Applicant role may only read offers on its own applications | HRSpecialist, SelectingOfficial, Applicant |
| POST | `/hiring/offers/{id}/respond` | TENTATIVE → ACCEPTED or DECLINED by the applicant; the five-day response window is enforced | Applicant |
| POST | `/hiring/offers/{id}/suitability-reviews` | Record the suitability determination for an ACCEPTED offer; UNFAVORABLE rescinds the offer | SuitabilityReviewer |
| GET | `/hiring/offers/{id}/suitability-reviews` | List suitability reviews of an offer (zero or one) | HRSpecialist, SelectingOfficial, SuitabilityReviewer |
| POST | `/hiring/offers/{id}/security-clearances` | Record the clearance adjudication for an ACCEPTED offer with favorable suitability; UNFAVORABLE rescinds the offer | SecurityAdjudicator |
| GET | `/hiring/offers/{id}/security-clearances` | List security clearances of an offer (zero or one) | HRSpecialist, SelectingOfficial, SecurityAdjudicator |
| POST | `/hiring/offers/{id}/schedule-eod` | ACCEPTED → EOD_SCHEDULED; requires favorable suitability, the sensitivity-level clearance gate, and a non-past entry date | SelectingOfficial |
| POST | `/hiring/offers/{id}/confirm-eod` | EOD_SCHEDULED → ENTERED_ON_DUTY at or after the entry date; re-validates the gates, creates the appointment, hires the application | HRSpecialist |
| GET | `/hiring/offers/{id}/appointments` | List appointments of an offer (zero or one) | HRSpecialist, SelectingOfficial |
| POST | `/hiring/appeals/{id}/adjudicate` | FILED → SUSTAINED or DENIED; SUSTAINED cascades by grounds | HRSpecialist |
| POST | `/_clock/set_current_utc` | Test-driving endpoint: set the server's logical clock, whose startup default is exactly 2026-09-01T00:00:00Z | PlatformAdmin |

## 5. Error Code Catalogue

The catalogue below enumerates every error identifier and its HTTP status. The trigger conditions for each error are specified in the narratives of §2 and §3, not here.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ANNOUNCEMENT_NOT_OPEN` | 409 Conflict |
| `ERR_ANNOUNCEMENT_NOT_CLOSED` | 409 Conflict |
| `ERR_CERTIFICATE_NOT_ACTIVE` | 409 Conflict |
| `ERR_OFFER_NOT_ACTIONABLE` | 409 Conflict |
| `ERR_ASSESSMENT_NOT_SUBMITTED` | 409 Conflict |
| `ERR_PASS_OVER_NOT_PENDING` | 409 Conflict |
| `ERR_APPEAL_NOT_ALLOWED_STATE` | 409 Conflict |
| `ERR_APPLICATION_WRONG_STATE` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 422 Unprocessable Entity |
| `ERR_SUITABILITY_NOT_FAVORABLE` | 422 Unprocessable Entity |
| `ERR_CLEARANCE_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_APPLICATION` | 409 Conflict |
| `ERR_ACTIVE_ASSESSMENT_EXISTS` | 409 Conflict |
| `ERR_ANNOUNCEMENT_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_CERTIFICATE_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_ACTIVE_CERTIFICATE_EXISTS` | 409 Conflict |
| `ERR_INSUFFICIENT_ELIGIBLES` | 422 Unprocessable Entity |
| `ERR_CATEGORY_BYPASS` | 422 Unprocessable Entity |
| `ERR_PASS_OVER_REQUIRED` | 422 Unprocessable Entity |
| `ERR_NOT_PREFERENCE_ELIGIBLE` | 422 Unprocessable Entity |
| `ERR_EXTENSION_LIMIT` | 422 Unprocessable Entity |
| `ERR_NO_REMAINING_VACANCIES` | 409 Conflict |
| `ERR_DUPLICATE_KEY` | 409 Conflict |
| `ERR_APPEAL_GROUND_MISMATCH` | 422 Unprocessable Entity |
| `ERR_SERIES_GRADE_RANGE` | 422 Unprocessable Entity |
| `ERR_AUTHORITY_METHOD_MISMATCH` | 422 Unprocessable Entity |
| `ERR_OUTSIDE_OPEN_PERIOD` | 422 Unprocessable Entity |
| `ERR_APPEAL_WINDOW_EXPIRED` | 422 Unprocessable Entity |
| `ERR_OFFER_RESPONSE_EXPIRED` | 409 Conflict |
| `ERR_EOD_DATE_INVALID` | 422 Unprocessable Entity |
| `ERR_POSITION_NOT_CLASSIFIED` | 422 Unprocessable Entity |
| `ERR_OUTSIDE_AREA_OF_CONSIDERATION` | 422 Unprocessable Entity |
| `ERR_ELIGIBILITY_DOC_REQUIRED` | 422 Unprocessable Entity |
| `ERR_PASS_OVER_PENDING` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_REVIEW_ALREADY_RECORDED` | 409 Conflict |
| `ERR_ASSESSMENT_NOT_APPLICABLE` | 422 Unprocessable Entity |
