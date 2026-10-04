# Cohort Scholar Program API — Product Requirements Document

## 1. Introduction

Every recruitment season, the foundation runs a cohort-based scholarship pipeline in each of its cities: high schools and community organizations nominate candidates against fixed quotas, nominees move through a multi-round group assessment in which assessors score leadership, teamwork and group presence, and the survivors are formed into a cohort that will matriculate together at a single partner college under a full-tuition leadership scholarship. Partner colleges sign per-cycle agreements committing a finite number of scholarship seats, scholars complete an eight-module pre-collegiate training curriculum before matriculation, and on campus they are supported by a faculty mentor through whole-cohort meetings and individual check-ins, by a career program that places internships, and — after graduation — by access to the alumni network. Partnerships are not permanent: each cohort's retention and graduation outcomes feed a standing derivation that can put a college on probation, and periodic renewal decisions either extend or terminate the relationship.

This document is the complete product specification for the API that operates that pipeline end to end. It covers nomination windows and per-partner quotas, immutable assessor scorecards and cutoff-gated round advancement, a cohort seat ledger with waitlist promotion cascades, offer expiry driven by a logical clock, matriculation with a pinned invoicing procedure, two independent scholar state axes, partnership outcome measurement in basis points, and renewal review. It is written for the engineers implementing the service; every rule stated here is normative, and the HTTP contract in Section 4 is deliberately minimal — request shapes and side effects are specified by the workflow narratives of Section 3.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID` identifies the caller and `X-User-Role` names the caller's role. A request that is missing either header, carries a malformed header, or names a role outside the declared set is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A caller whose role is not on an endpoint's authorized-role list is rejected with `ERR_FORBIDDEN` (HTTP 403).

Eight roles exist, spelled exactly as follows: `ProgramAdmin`, `Nominator`, `Assessor`, `SelectionOfficer`, `Nominee`, `FacultyMentor`, `CareerDirector`, and `Scholar`.

`ProgramAdmin` is the foundation operator and holds a superset of every write operation except offer accept/decline (which is `Nominee`-only), evaluation submission (which is `Assessor`-only), and meeting logging (which is `FacultyMentor`-only). When `X-User-Role` is `ProgramAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`, and the role is exempt from every ownership check described below.

When `X-User-Role` is `Nominator`, `X-User-ID` is the `id` of the acting `NominatingPartner`; ownership checks on any resource that references a `NominatingPartner` compare the resource's `nominator_id` field to `X-User-ID`, so a nominator creates nominations under its own partner record and withdraws only its own nominees.

When `X-User-Role` is `Assessor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it on each submitted evaluation as `assessor_ref`, where it participates in a uniqueness key, but it is never compared to any entity's `id`.

When `X-User-Role` is `SelectionOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.

When `X-User-Role` is `Nominee`, `X-User-ID` is the `id` of the acting `Nominee`; ownership checks on offers compare the offer's `nominee_id` field to `X-User-ID`, so a nominee accepts or declines only its own offers.

When `X-User-Role` is `FacultyMentor`, `X-User-ID` is the `id` of the acting `Mentor`; ownership checks on meeting logging compare the cohort's `mentor_id` field to `X-User-ID`, so a faculty mentor logs meetings only for cohorts assigned to them.

When `X-User-Role` is `CareerDirector`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.

When `X-User-Role` is `Scholar`, `X-User-ID` is the `id` of the acting `Scholar`; ownership checks on the scholar lifecycle compare the target scholar's `id` to `X-User-ID`, and a scholar caller may drive only their own record and only toward self-withdrawal.

Any ownership-scope violation — a nominator touching another partner's nominee, a nominee touching another nominee's offer, a mentor logging into another mentor's cohort, or a scholar attempting anything beyond self-withdrawal — is rejected with `ERR_FORBIDDEN` (HTTP 403).

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

All list endpoints accept the optional query parameters `limit` and `offset`. The `limit` parameter defaults to 10, with a minimum of 1 and a maximum of 100; the `offset` parameter defaults to 0. List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside `meta`. Unless otherwise noted, every list endpoint sorts its results by `created_at` ascending. The single exception is a scholar's training-record listing: because a scholar's eight training records are created together and share a `created_at`, that listing sorts by `module_code` ascending instead.

### 2.4. The Logical Clock and Offer Expiry

All time-dependent behavior in the system is driven by a logical clock, never by wall-clock time. The server boots with the logical clock at exactly 2026-09-01T00:00:00Z, before any clock-set call has been made. A `ProgramAdmin`-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant; the target instant must be at or after 2026-09-01T00:00:00Z, and the response reports the new `current_utc`. This logical clock governs nomination-window checks, offer expiry, and the `completed_at` timestamps stamped onto training records.

Every time the clock moves, an offer-expiry sweep runs against the new now. Each offer still in `OFFERED` status whose `expires_at` is strictly earlier than the new now transitions to `EXPIRED`; an offer whose `expires_at` is exactly equal to the new now does not expire and remains acceptable at its deadline. When several offers expire in one sweep they are processed in `created_at` ascending order — no `id` tie-break is ever needed, because the ledger recompute makes processing order unobservable while promotion selection order is fully pinned by the waitlist ranking rule of Section 3.5. Per expired offer, the cohort's outstanding count drops by one and the waitlist promotion sweep runs for that cohort.

Every offer lives for fourteen days: at creation, its `expires_at` is set to its `created_at` plus 14 days.

### 2.5. Resource Identity, Timestamps and Versioning

Every persisted resource carries an `id` — a server-minted UUID with no type prefix — and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. Except where noted, resources also carry `updated_at` (same format, refreshed on every mutation of the resource) and `version` (an integer that increments on every mutation). The `Evaluation` record is the exception: it carries only `id` and `created_at`, and both `updated_at` and `version` are absent, because evaluations are immutable — no update or delete endpoint exists for them.

### 2.6. Optimistic Concurrency on Partnership Drafting

Exactly one endpoint participates in optimistic concurrency control: drafting a new partner agreement via `POST /api/partner-agreements`. The request must carry `expected_college_version`, a non-optional field holding the `version` of the target partner college as the client last observed it. If the supplied value does not equal the college's current `version` — meaning another writer has advanced the college's version since the client last read it, for example by drafting an agreement for the same college and cycle, an act which legitimately supersedes the prior draft — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), forcing the client to refresh its view of the college before terms are drafted. Successfully drafting an agreement itself increments the college's `version` by exactly 1. Endpoints other than agreement drafting do not take a version field.

### 2.7. Validation Pipeline and Priority Ordering

Every incoming request passes through twelve validation tiers in a strict priority order: the lower-numbered tier wins whenever one request violates several rules, so the error the caller receives is always the earliest applicable one. The tiers are:

**Tier 1 — authentication.** The `X-User-Role` and `X-User-ID` headers must be present, well-formed, and name a declared role; otherwise the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). This applies to every endpoint.

**Tier 2 — request shape.** Required fields must be present, types must be valid, enum values must be in range, numeric ranges must be honored, datetimes and dates must parse, `ends_at` must be strictly after `starts_at`, `ends_on` must not precede `starts_on`, an `INDIVIDUAL` meeting must carry `scholar_id`, a `COHORT` meeting must not carry `scholar_id`, and a scholar lifecycle call must carry at least one of its two target fields. Violations are rejected with `ERR_INVALID_REQUEST` (HTTP 400). This tier owns the nomination-quota bounds (a `nomination_quota` below 1 or above 20 fails here) and the positivity of `tuition_annual_cents`; the `cohort_size` bounds deliberately live in tier 10 instead.

**Tier 3 — role authorization.** The caller's role must appear in the endpoint's authorized-role list; otherwise `ERR_FORBIDDEN` (HTTP 403).

**Tier 4 — ownership scope.** A `Nominator` acts only on its own nominees (the nominee's `nominator_id` must equal `X-User-ID`); a `Nominee` acts only on its own offers (the offer's `nominee_id` must equal `X-User-ID`); a `FacultyMentor` acts only on its own cohorts (the cohort's `mentor_id` must equal `X-User-ID`); a `Scholar` may drive only its own lifecycle and only with `to_enrollment_status` set to `WITHDRAWN`; `ProgramAdmin` is exempt from all of these checks. Violations are rejected with `ERR_FORBIDDEN` (HTTP 403). This tier applies to six operations: nominee withdrawal, offer acceptance, offer decline, cohort-meeting creation, scholar lifecycle calls, and nomination creation when the supplied `nominator_id` does not match the caller.

**Tier 5 — path resolution.** Path parameters resolve left to right: every identifier segment in the URL must name an existing resource, otherwise `ERR_NOT_FOUND` (HTTP 404).

**Tier 6 — body references.** Identifiers referenced in the request body — `city_program_id`, `nominator_id`, `nominee_id`, `partner_college_id`, `agreement_id`, `mentor_id`, `cohort_id`, `scholar_id` (including a meeting's `scholar_id` when its `kind` is `INDIVIDUAL`) — must each name an existing resource, otherwise `ERR_NOT_FOUND` (HTTP 404).

**Tier 7 — stale version.** On agreement drafting, `expected_college_version` must equal the partner college's current `version`, otherwise `ERR_STALE_VERSION` (HTTP 412). This tier guards exactly one endpoint, per Section 2.6.

**Tier 8 — state preconditions.** The requested transition must be declared from the target's current state. This tier covers: offer creation requiring a `SELECTED` nominee (`ERR_INVALID_STATE`); offer creation requiring a `FORMING` cohort (`ERR_COHORT_NOT_FORMING`); evaluation submission requiring the nominee to be in the matching round (`ERR_NOMINEE_NOT_IN_ROUND`); cohort creation requiring an `ACTIVE` agreement (`ERR_AGREEMENT_NOT_ACTIVE`); agreement activation requiring an `ACTIVE` college (`ERR_COLLEGE_NOT_ACTIVE`); matriculation requiring a `LOCKED` cohort; lifecycle, transition, decision, withdrawal and completion calls being declared transitions from the current state (`ERR_INVALID_STATE`); and internship creation or confirmation requiring a scholar enrolled as `MATRICULATED` or `RETAINED` with `GOOD_STANDING` (`ERR_SCHOLAR_NOT_ELIGIBLE`). All reject with HTTP 409. Within this tier the ordering is: the nominee's state first, then the cohort's state, then any other entity's state.

**Tier 9 — nomination window.** A nomination is accepted only while the logical now falls inside the nominating city program's window; otherwise `ERR_NOMINATION_WINDOW_CLOSED` (HTTP 422). This tier guards nomination creation only.

**Tier 10 — uniqueness, overlap and referential consistency.** Nine rules: (a) no duplicate evaluation for the same (`nominee_id`, `round_number`, `assessor_ref`) triple — `ERR_DUPLICATE_EVALUATION`; (b) a nominee holds at most one offer in `OFFERED` or `ACCEPTED` status across all cohorts — `ERR_ACTIVE_OFFER_EXISTS`; (c) at most one cohort per agreement — `ERR_COHORT_EXISTS`; (d) at most one `ACTIVE` agreement per college and admissions cycle — `ERR_ACTIVE_AGREEMENT_EXISTS`; (e) the nominee's `city_program_id` must equal the cohort's `city_program_id` on offer creation — `ERR_CITY_MISMATCH`; (f) the mentor's `partner_college_id` must equal the agreement's `partner_college_id` on cohort creation — `ERR_MENTOR_COLLEGE_MISMATCH`; (g) the mentor 15-minute meeting-buffer rule — `ERR_MENTOR_SCHEDULE_CONFLICT`; (h) the internship inclusive-interval overlap rule — `ERR_INTERNSHIP_OVERLAP`; (i) `cohort_size` must lie within 3 to 6 inclusive on agreement creation — `ERR_COHORT_SIZE_INVALID`. Rules (a) through (d) reject with HTTP 409; rules (e) through (i) reject with HTTP 422.

**Tier 11 — capacity and quota.** A nomination is rejected with `ERR_NOMINATION_QUOTA_EXCEEDED` (HTTP 422) when the partner's `nominations_used` has already reached its `nomination_quota`; an offer creation is rejected with `ERR_COHORT_FULL` (HTTP 422) when the cohort has no `seats_remaining`. These guard nomination creation and offer creation respectively.

**Tier 12 — threshold gates.** Advancement and waitlist decisions require at least 2 evaluations in the current round (`ERR_INSUFFICIENT_EVALUATIONS`); advancement additionally requires the round score to meet the round cutoff (`ERR_CUTOFF_NOT_MET`); a renewal `RENEW` decision requires the census retention and graduation thresholds (`ERR_RENEWAL_THRESHOLDS_NOT_MET`, with null rates failing). All reject with HTTP 422. Within this tier, the evaluation-count check runs before the cutoff check: when both would fail, the caller sees `ERR_INSUFFICIENT_EVALUATIONS`, never `ERR_CUTOFF_NOT_MET`.

### 2.8. Scoring Arithmetic, Rounding and Monetary Precision

Evaluation arithmetic is exact integer arithmetic: the weighted score of a scorecard involves no rounding step at all. Wherever an average or a weighted term must collapse to an integer — a nominee's round scores, a cohort's provisional fill projection, each per-scholar invoice line item, and the basis-point outcome rates — the system rounds half-up. Round scores and fill projections are whole integers; invoice line items are rounded half-up to whole cents per scholar before any summation takes place; outcome rates are integer basis points. Comparisons against cutoffs and thresholds are inclusive unless stated otherwise — a score exactly equal to its cutoff passes. The notable strict comparison is offer expiry, where only a deadline strictly earlier than the logical now expires the offer.

### 2.9. Nested Resources, Filtering and Identifier Resolution

Nested URLs resolve their path parameters left to right, and every segment must name an existing resource before the request proceeds, per tier 5 of the validation pipeline. List endpoints double as reverse lookups over the references their resources carry. The nominee list filters by `city_program_id`, `nominator_id`, and `status`; a nominee's evaluation list filters by `round_number`; a college's agreement list filters by `status`; the cohort list filters by `agreement_id`, `city_program_id`, `partner_college_id`, `mentor_id`, and `status`; the offer list filters by `nominee_id`, `cohort_id`, and `status`; the scholar list filters by `cohort_id`, `nominee_id`, `enrollment_status`, and `standing`; a scholar's training-record list filters by `status`; a scholar's internship list filters by `status`; and a cohort's meeting list filters by `kind`.

## 3. Business Logic & Workflows

### 3.1. City Programs, Nomination Windows and Partner Quotas

Recruitment begins when a `ProgramAdmin` opens a city program for an admissions cycle. Each city program carries a short unique `code` (for example ATL), a display `name`, an `admissions_cycle` label (for example 2027), and a nomination window delimited by `nomination_window_opens_at` and `nomination_window_closes_at`. Both window bounds are inclusive: nominations are accepted from the opening instant through the closing instant.

Under each city program, the `ProgramAdmin` registers nominating partners — the high schools and community organizations that supply candidates. A partner record carries the `city_program_id` of the program it nominates into, a `name`, a `kind` of either `HIGH_SCHOOL` or `COMMUNITY_ORG`, and a `nomination_quota` bounding its live nominations to at least 1 and at most 20 per cycle. The partner's `nominations_used` is a computed count of its nominees whose status is anything other than `WITHDRAWN`; at all times, `nominations_used` plus the partner's remaining slots equals its `nomination_quota`. A freshly registered partner starts with `nominations_used` at zero.

A nomination creates a `Nominee` with `full_name`, the target `city_program_id`, and an optional `first_generation` flag that defaults to false when omitted. Who can file the nomination depends on the caller: when a `Nominator` calls, the server sets the nominee's `nominator_id` from `X-User-ID`, and any `nominator_id` supplied in the payload must be absent or equal to it — a mismatch is an ownership violation rejected with `ERR_FORBIDDEN`; a `ProgramAdmin` caller must supply `nominator_id` explicitly. The new nominee starts in `NOMINATED` status with `current_round` at 0 and all three round scores null, and the filing partner's `nominations_used` increases by one.

Two business rules guard nomination creation, in this order. First, the logical now must fall within the city program's inclusive nomination window; a submission before the window opens or after it closes is rejected with `ERR_NOMINATION_WINDOW_CLOSED`. Second, the partner must have quota left: if `nominations_used` already equals `nomination_quota`, the nomination is rejected with `ERR_NOMINATION_QUOTA_EXCEEDED`.

A nominee may be withdrawn only while still `NOMINATED` — withdrawal is impossible once the nominee has entered `ROUND_1`, and attempting it is rejected with `ERR_INVALID_STATE`. Withdrawal may be performed by the owning nominator or by a `ProgramAdmin`; it moves the nominee to `WITHDRAWN` and releases one quota slot, decreasing the partner's `nominations_used` by one.

### 3.2. The Dynamic Assessment: Scorecards, Round Scores and Advancement Decisions

Assessment is a three-round pipeline in which candidates are evaluated in group settings. During each round, `Assessor` callers submit scorecards: one evaluation carries the target `nominee_id`, a `round_number` of 1, 2 or 3, and three integer dimension scores — `leadership`, `teamwork`, and `group_presence` — each between 0 and 100 inclusive. The `round_number` must equal the nominee's `current_round` at submission, which is another way of saying the nominee's status must be the matching round (`ROUND_1` for round 1, and so on); a mismatch is rejected with `ERR_NOMINEE_NOT_IN_ROUND`. The server copies the caller's `X-User-ID` onto the record as `assessor_ref`, and the triple of `nominee_id`, `round_number` and `assessor_ref` is a uniqueness key: a second scorecard from the same assessor for the same nominee in the same round is rejected with `ERR_DUPLICATE_EVALUATION`. Evaluations are immutable — once created, no scorecard is ever updated, deleted, or excluded from aggregation.

At creation, each evaluation's `weighted_score` is computed and stored. Leadership is weighted 4, teamwork is weighted 3, and group presence is weighted 3, so the base score is four times `leadership` plus three times `teamwork` plus three times `group_presence`. If any single dimension falls below 40, the stored `weighted_score` is capped: it becomes the smaller of the base score and 499. A dimension score of exactly 40 does not trigger the cap. All of this arithmetic is exact integer arithmetic with no rounding step.

After each evaluation is created, the nominee's score for the affected round is recomputed. While fewer than 2 evaluations exist for the nominee in that round, the round score remains null. Once at least 2 evaluations exist, the round score becomes the round-half-up average of their `weighted_score` values, stored as an integer on the nominee as `round_1_score`, `round_2_score`, or `round_3_score`. The `round_3_score` doubles as the waitlist ranking key described in Section 3.5.

Advancement is driven by `SelectionOfficer` or `ProgramAdmin` decisions carrying a `decision` value of `ADVANCE`, `WAITLIST`, or `DROP`. An `ADVANCE` decision walks the nominee forward one step along `NOMINATED` → `ROUND_1` → `ROUND_2` → `ROUND_3` → `SELECTED`, and also maps `WAITLISTED` → `SELECTED`. The step from `NOMINATED` to `ROUND_1` has no preconditions and sets `current_round` to 1. Each later step carries two gates, evaluated in order — evaluation count first, cutoff second:

- From `ROUND_1` to `ROUND_2`: at least 2 evaluations must exist for round 1, otherwise `ERR_INSUFFICIENT_EVALUATIONS`; then `round_1_score` must be at least 600, otherwise `ERR_CUTOFF_NOT_MET`. Success sets `current_round` to 2.
- From `ROUND_2` to `ROUND_3`: at least 2 round-2 evaluations, otherwise `ERR_INSUFFICIENT_EVALUATIONS`; then `round_2_score` must be at least 700, otherwise `ERR_CUTOFF_NOT_MET`. Success sets `current_round` to 3.
- From `ROUND_3` to `SELECTED`: at least 2 round-3 evaluations, otherwise `ERR_INSUFFICIENT_EVALUATIONS`; then `round_3_score` must be at least 800, otherwise `ERR_CUTOFF_NOT_MET`.

Every cutoff boundary is inclusive: a score exactly equal to the cutoff advances, while a score one point below the cutoff fails with `ERR_CUTOFF_NOT_MET`. Because the count gate runs before the cutoff gate, a nominee short on evaluations always surfaces `ERR_INSUFFICIENT_EVALUATIONS` even if the score would also miss.

A `WAITLIST` decision exists only from `ROUND_3`: it requires at least 2 round-3 evaluations (otherwise `ERR_INSUFFICIENT_EVALUATIONS`) but imposes no cutoff, and moves the nominee to `WAITLISTED`. The `current_round` stays at 3 in both `SELECTED` and `WAITLISTED`. A waitlisted nominee returns to `SELECTED` either through a manual `ADVANCE` decision, which carries no preconditions from `WAITLISTED`, or through the system-driven waitlist promotion cascade of Section 3.5.

A `DROP` decision is available from `NOMINATED`, `ROUND_1`, `ROUND_2`, `ROUND_3`, `WAITLISTED`, and `SELECTED`, and moves the nominee to `DROPPED`. If the dropped nominee holds an offer still in `OFFERED` status, that offer becomes `REVOKED`, the cohort's `offers_outstanding` decreases by one, and the waitlist promotion sweep then runs for that cohort. The nominee's terminal states are `PLACED`, `DROPPED`, and `WITHDRAWN`.

### 3.3. Partner Colleges, Agreements and Faculty Mentors

On the partnership side, a `ProgramAdmin` registers each partner college with nothing more than a `name`; the college starts in `ACTIVE` status with `renewed_cycles_count` at 0. Faculty mentors are registered against a college with a `partner_college_id` and a `full_name`, and each mentor belongs to exactly one college.

Funding for a cohort is negotiated as a partner agreement. Drafting one (a `ProgramAdmin` operation guarded by the optimistic-concurrency rule of Section 2.6) takes the `partner_college_id`, the `admissions_cycle` the agreement funds, a `cohort_size` of committed scholarship seats, the `tuition_annual_cents` value of one year's full tuition per scholar, and the `expected_college_version`. The `cohort_size` must be at least 3 and at most 6 inclusive; a size outside that range is rejected with `ERR_COHORT_SIZE_INVALID` — deliberately a business-rule rejection at tier 10 rather than a shape error. The `tuition_annual_cents` must be a positive integer number of cents; a non-positive value fails request-shape validation with `ERR_INVALID_REQUEST`. A freshly drafted agreement starts in `DRAFT` status.

Drafting an agreement for a college and admissions cycle that already has a `DRAFT` agreement supersedes the older draft: the existing agreement moves from `DRAFT` to `SUPERSEDED`. Drafting against a `LAPSED` college is blocked with `ERR_COLLEGE_NOT_ACTIVE`, as is activation; drafting against a `PROBATION` college is permitted, and only activation is blocked there.

Activation moves an agreement from `DRAFT` to `ACTIVE` and carries two gates. The college must currently be `ACTIVE` — attempting activation under a `PROBATION` or `LAPSED` college is rejected with `ERR_COLLEGE_NOT_ACTIVE`. And no other `ACTIVE` agreement may exist for the same college and admissions cycle — otherwise the activation is rejected with `ERR_ACTIVE_AGREEMENT_EXISTS`. Once `ACTIVE`, an agreement remains so until its cohort completes, at which point it becomes `FULFILLED` (Sections 3.7 and 3.9).

### 3.4. Cohort Formation and the Seat Ledger

Each active agreement funds exactly one cohort. Creating the cohort (a `ProgramAdmin` operation) takes the `agreement_id`, the `city_program_id` whose recruitment feeds the cohort — every scholar of the cohort is recruited from that city — and the `mentor_id` of the faculty mentor who will accompany it. The agreement must be `ACTIVE`; creating against a `DRAFT`, `SUPERSEDED`, `FULFILLED`, or `EXPIRED` agreement is rejected with `ERR_AGREEMENT_NOT_ACTIVE`. At most one cohort may exist per agreement; a second attempt is rejected with `ERR_COHORT_EXISTS`. And the mentor must belong to the agreement's college: a `mentor_id` naming a mentor whose `partner_college_id` differs from the agreement's is rejected with `ERR_MENTOR_COLLEGE_MISMATCH`.

At creation the server copies the agreement's `partner_college_id`, `cohort_size`, and `tuition_annual_cents` onto the cohort, and those copies are immutable. The cohort starts in `FORMING` status with `seats_committed` at 0, `offers_outstanding` at 0, `invoice_total_cents` null, and `meetings_held_count` at 0.

The cohort's seat ledger is recomputed on every offer creation, acceptance, decline, expiry and revocation, as well as at cohort creation. The `seats_committed` count is the number of the cohort's offers in `ACCEPTED` or `FULFILLED` status — a `FULFILLED` offer keeps its committed seat, and such offers exist only after matriculation (Section 3.6), so before matriculation the committed count is exactly the `ACCEPTED` count; `offers_outstanding` is the number in `OFFERED` status; and `seats_remaining` is the `cohort_size` minus both. The ledger never goes negative, because offer creation requires at least one remaining seat. The ledger's invariant is that `seats_committed` equals the count of `ACCEPTED` plus `FULFILLED` offers at all times — so an acceptance immediately followed by the scholar's pre-collegiate withdrawal nets to zero change, the acceptance adding one and the revocation subtracting one, and a matriculating scholar's `ACCEPTED` to `FULFILLED` transition changes nothing.

Every read of a cohort also surfaces two fill projections side by side. The `projected_fill_provisional` is the planning view: pending offers are weighted at 75% likely to convert, so it equals `seats_committed` plus the `offers_outstanding` count multiplied by 7500 and divided by 10000, that product rounded half-up to a whole seat. The `projected_fill_final` is the committed view: pending offers count as zero, so it always equals `seats_committed`.

### 3.5. Placement Offers and the Waitlist Promotion Cascade

Once a nominee is `SELECTED`, a `SelectionOfficer` or `ProgramAdmin` extends a placement offer naming the `nominee_id` and the target `cohort_id`. Offer creation is guarded by a chain of gates, evaluated in pipeline order. Within the state tier, the nominee's state is checked before the cohort's state: the nominee must be `SELECTED` — any other nominee status is rejected with `ERR_INVALID_STATE` — and the cohort must be `FORMING`, since an offer against a `LOCKED`, `MATRICULATED`, or `COMPLETED` cohort is rejected with `ERR_COHORT_NOT_FORMING`. The uniqueness and consistency tier then applies: the nominee must not already hold an offer in `OFFERED` or `ACCEPTED` status anywhere, across all cohorts, otherwise `ERR_ACTIVE_OFFER_EXISTS`; and the nominee's `city_program_id` must equal the cohort's `city_program_id`, otherwise `ERR_CITY_MISMATCH`. Finally the capacity tier requires `seats_remaining` above zero; a cohort may still be `FORMING` with every seat spoken for, and that attempt is rejected with `ERR_COHORT_FULL`. A created offer starts in `OFFERED` status with its `expires_at` set fourteen days out, and the cohort's `offers_outstanding` rises by one.

Only the nominee may answer an offer, and only for their own offers. Acceptance requires the offer to still be `OFFERED` — an `OFFERED` offer whose deadline has passed is already `EXPIRED` via the clock sweep of Section 2.4. No cohort-state precondition is needed on acceptance by construction: the creation-time capacity gate keeps committed plus outstanding seats within the `cohort_size`, so a cohort that has reached `LOCKED` necessarily has zero outstanding offers, meaning every live `OFFERED` offer belongs to a `FORMING` cohort and acceptance can never violate capacity.

Acceptance is the pivotal moment of the pipeline and cascades widely. A new `Scholar` is created, bound to the offer's cohort and nominee, with `enrollment_status` `PRE_COLLEGIATE`, `standing` `GOOD_STANDING`, and `ever_matriculated` false. Eight training records are auto-created for the new scholar, module codes `T1` through `T8`, all in `NOT_STARTED` status. The nominee's status becomes `PLACED`. The cohort's `seats_committed` rises by one while `offers_outstanding` falls by one. And if committed seats have now reached the `cohort_size` — the boundary is inclusive, so equality locks — the cohort automatically moves from `FORMING` to `LOCKED`, after which no further offers can be created for it.

Decline releases the seat: the offer moves from `OFFERED` to `DECLINED`, the cohort's `offers_outstanding` falls by one, and the waitlist promotion sweep runs for the cohort — though the sweep only fires while the cohort is `FORMING` with at least one seat remaining.

Offers die in three other ways. The clock sweep expires an `OFFERED` offer past its deadline, per Section 2.4, decrementing `offers_outstanding` and running the promotion sweep for that cohort. Dropping a nominee who holds a pending offer revokes it — `OFFERED` to `REVOKED` — again decrementing `offers_outstanding` and running the promotion sweep. And when an accepted scholar withdraws during the pre-collegiate phase (including via the matriculation training gate of Section 3.6), the accepted offer moves from `ACCEPTED` to `REVOKED`, `seats_committed` falls by one, and — if the cohort was `LOCKED` and committed seats have fallen below the `cohort_size` — the cohort reverts from `LOCKED` back to `FORMING` with the promotion sweep running immediately after the revert. That revert-and-promote cascade is suppressed entirely once the cohort is `MATRICULATED` or `COMPLETED`. Finally, an accepted offer whose scholar matriculates with the cohort moves from `ACCEPTED` to `FULFILLED`.

The waitlist promotion sweep follows a fully deterministic selection policy. It triggers on any event that raises `seats_remaining` while the cohort is `FORMING`: an offer decline, an offer expiry, an offer revocation, or a lock revert. The eligible pool is the set of nominees in `WAITLISTED` status whose `city_program_id` equals the cohort's and who hold no offer in `OFFERED` or `ACCEPTED` status in any cohort. If the pool is empty the sweep is a no-op — the cohort simply stays `FORMING` with an open seat. Otherwise the sweep repeats while `seats_remaining` is above zero and the pool is non-empty: it picks the nominee ranked by `round_3_score` descending with ties broken by earlier nominee `created_at` — the `id` is never used in ranking or tie-breaking — moves that nominee from `WAITLISTED` to `SELECTED`, creates a fresh offer for the nominee and the triggering cohort in `OFFERED` status with `expires_at` set to now plus 14 days, and raises the cohort's `offers_outstanding` by one.

### 3.6. Matriculation and the Program-Fee Invoice

When a cohort's seats are full, a `ProgramAdmin` matriculates it. The cohort must be `LOCKED`; matriculating a cohort in any other status is rejected with `ERR_INVALID_STATE`. The call executes four pinned steps, in exactly this order:

**Step 1.** The cohort moves from `LOCKED` to `MATRICULATED` first. Moving the cohort up front suppresses every `LOCKED` → `FORMING` revert and every waitlist promotion sweep for the remainder of the call, no matter what happens in the later steps.

**Step 2.** Every offer of the cohort still in `OFFERED` status expires in place: each becomes `EXPIRED`, with `offers_outstanding` falling by one per expiry. No promotion sweep runs for these expiries.

**Step 3.** The scholars of the cohort are visited one by one in `created_at` ascending order, and each faces the training gate. A scholar whose `training_completed_count` is exactly 8 matriculates: `enrollment_status` becomes `MATRICULATED`, `ever_matriculated` latches to true, and that scholar's accepted offer becomes `FULFILLED`. A scholar with any shortfall — fewer than 8 completed modules — is instead moved to `WITHDRAWN`, their accepted offer becomes `REVOKED`, and `seats_committed` falls by one. Because Step 1 already moved the cohort, these revocations trigger no lock revert and no promotion.

**Step 4.** The cohort's `invoice_total_cents` is computed as the program-fee invoice over exactly the scholars who matriculated in Step 3 of this call; scholars already `MATRICULATED` or `WITHDRAWN` beforehand are excluded. Processing those scholars in `created_at` ascending order, each scholar's fee is a 250000-cent base plus a tuition-proportional component — the cohort's `tuition_annual_cents` multiplied by 125 and divided by 10000, that is 1.25% of annual tuition — with the per-scholar fee rounded half-up to whole cents. The invoice total is the sum of those per-scholar fees.

The rounding order is pinned: each per-scholar fee is rounded half-up to whole cents before the sum is taken. Summing the raw fractional components first and rounding once at the end is forbidden, because it produces a different total. For concreteness: with a `tuition_annual_cents` of 6123460 and two scholars matriculating, the pinned per-line rounding yields an invoice of 653086 cents, whereas sum-then-round would yield 653087 cents. If zero scholars matriculated in the call, `invoice_total_cents` is 0. Until a cohort matriculates, its `invoice_total_cents` remains null.

### 3.7. Scholar Lifecycle: Two Independent State Axes and Pre-Collegiate Training

A scholar carries two independent state axes. The `enrollment_status` axis begins at `PRE_COLLEGIATE` and can reach `MATRICULATED`, `RETAINED`, `GRADUATED`, `WITHDRAWN`, or `DISMISSED`, the last three being terminal. The `standing` axis begins at `GOOD_STANDING` and can flip to `PROBATION` and back. The two axes evolve independently, with one exception: `standing` freezes once `enrollment_status` is terminal, so no standing change is possible for a scholar who has graduated, withdrawn, or been dismissed. Two derived flags ride on these axes: `alumni_network_access` is true exactly when the scholar's `enrollment_status` is `GRADUATED`, and `ever_matriculated` latches true the first time the scholar reaches `MATRICULATED`, gating the scholar's inclusion in the outcome-rate denominators of Section 3.9.

Lifecycle changes are driven by `ProgramAdmin` callers, with a narrow self-service exception for scholars. The call may carry `to_enrollment_status` — one of `RETAINED`, `GRADUATED`, `WITHDRAWN`, or `DISMISSED` — and/or `to_standing` — `GOOD_STANDING` or `PROBATION`. At least one of the two fields is required; a call carrying neither is rejected with `ERR_INVALID_REQUEST`. A `Scholar` caller may target only their own record and may only set `to_enrollment_status` to `WITHDRAWN`; any other combination is rejected with `ERR_FORBIDDEN`. The declared enrollment transitions are:

- `PRE_COLLEGIATE` → `MATRICULATED` happens only inside cohort matriculation, under the training gate of Section 3.6; a lifecycle call requesting `MATRICULATED` is rejected with `ERR_INVALID_STATE`.
- `PRE_COLLEGIATE` → `WITHDRAWN`, by the scholar themself or a `ProgramAdmin`, or by the system at the matriculation training gate: the scholar's accepted offer becomes `REVOKED`, the cohort's `seats_committed` falls by one, and the lock-revert-plus-promotion cascade of Section 3.5 runs when the cohort is still `LOCKED` (and is suppressed once the cohort is `MATRICULATED` or `COMPLETED`).
- `MATRICULATED` → `RETAINED`, by a `ProgramAdmin`, with no further side effects.
- `MATRICULATED` or `RETAINED` → `WITHDRAWN`, by the scholar themself or a `ProgramAdmin`: the partnership outcome rates change on next read, because a post-matriculation withdrawal counts in the denominators, and the cohort completion check below runs.
- `MATRICULATED` or `RETAINED` → `DISMISSED`, by a `ProgramAdmin`: outcome rates likewise change on next read, and the completion check runs.
- `RETAINED` → `GRADUATED`, by a `ProgramAdmin`: `alumni_network_access` becomes true, outcome rates change on next read, and the completion check runs.

The standing transitions are `GOOD_STANDING` → `PROBATION` and `PROBATION` → `GOOD_STANDING`, both `ProgramAdmin`-driven through `to_standing`. Each requires that the scholar's `enrollment_status` is not terminal; attempting either against a `GRADUATED`, `WITHDRAWN`, or `DISMISSED` scholar is rejected with `ERR_INVALID_STATE`.

The cohort completion check runs whenever a scholar leaves a non-terminal enrollment state: when the count of the cohort's scholars whose `enrollment_status` is non-terminal reaches zero — meaning every scholar is `GRADUATED`, `WITHDRAWN`, or `DISMISSED` — the cohort moves from `MATRICULATED` to `COMPLETED`, its agreement moves from `ACTIVE` to `FULFILLED`, and the partner college's census outcome rates are recomputed, which may flip the college's standing per Section 3.9.

Before matriculation, every scholar works through the pre-collegiate curriculum: eight training records, auto-created at acceptance, with `module_code` values `T1` through `T8`. Each record's `category` is derived from its module: `T1`–`T3` are `ACADEMIC`, `T4`–`T6` are `LEADERSHIP`, and `T7`–`T8` are `TEAM_BUILDING`. Each record starts `NOT_STARTED`. A `ProgramAdmin` marks a module complete, which moves the record to `COMPLETED`, stamps `completed_at` with the current logical-clock instant, and raises the scholar's `training_completed_count` by one. The count therefore ranges from 0 to 8 and is the gate the matriculation call applies in Step 3.

### 3.8. Campus Meetings and the Career Program

Once a cohort is on campus, its faculty mentor keeps it coherent through meetings. Logging a meeting is a `FacultyMentor`-only operation carrying the `cohort_id`, a `kind` of `COHORT` for a whole-group meeting or `INDIVIDUAL` for a one-scholar check-in, a `starts_at` and an `ends_at`, and an optional `scholar_id`. The cohort must be `MATRICULATED` — logging against a cohort in any other status is rejected with `ERR_INVALID_STATE` — and the caller must be the cohort's own mentor, meaning the cohort's `mentor_id` must equal the caller's `X-User-ID`, otherwise `ERR_FORBIDDEN`. The `scholar_id` is required when the `kind` is `INDIVIDUAL` and must be null or absent when the `kind` is `COHORT`; either violation is a request-shape error rejected with `ERR_INVALID_REQUEST`. A supplied `scholar_id` is validated to exist and to belong to the meeting's cohort, otherwise `ERR_NOT_FOUND`. The `ends_at` must be strictly after the `starts_at`, otherwise `ERR_INVALID_REQUEST`.

A mentor's calendar observes a 15-minute buffer rule: a new meeting conflicts with an existing meeting of the same mentor exactly when the new meeting's `starts_at` falls before the existing meeting's `ends_at` plus fifteen minutes, and the existing meeting's `starts_at` falls before the new meeting's `ends_at` plus fifteen minutes. Such a conflict is rejected with `ERR_MENTOR_SCHEDULE_CONFLICT`. Every successfully logged meeting raises the cohort's `meetings_held_count` by one.

The career program places scholars into internships. A `CareerDirector` or `ProgramAdmin` proposes one with the `scholar_id`, an `employer_name`, a `starts_on`, and an `ends_on`, the latter two being inclusive calendar dates in YYYY-MM-DD form; an `ends_on` earlier than the `starts_on` is rejected with `ERR_INVALID_REQUEST`. Eligibility is gated at proposal time: the scholar's `enrollment_status` must be `MATRICULATED` or `RETAINED` and the scholar's `standing` must be `GOOD_STANDING`, otherwise the proposal is rejected with `ERR_SCHOLAR_NOT_ELIGIBLE`. The new internship's inclusive date interval is then checked for overlap against the same scholar's other internships in `PROPOSED` or `CONFIRMED` status: a conflict exists exactly when the new `starts_on` is on or before the existing internship's `ends_on` and the existing `starts_on` is on or before the new `ends_on`. Because both intervals are inclusive, sharing a boundary date is itself a conflict. An overlapping proposal is rejected with `ERR_INTERNSHIP_OVERLAP`. A created internship starts in `PROPOSED` status.

Internships advance through transition calls by a `CareerDirector` or `ProgramAdmin` carrying a `to_status`. Moving from `PROPOSED` to `CONFIRMED` re-checks the scholar's standing at confirm time: if the scholar is no longer in `GOOD_STANDING`, the transition is rejected with `ERR_SCHOLAR_NOT_ELIGIBLE`. From `CONFIRMED`, the internship moves to `COMPLETED`. From either `PROPOSED` or `CONFIRMED`, it may instead move to `TERMINATED`. `COMPLETED` and `TERMINATED` are terminal. A `TERMINATED` internship stops occupying the scholar's calendar — the overlap rule ignores it from then on.

### 3.9. Partnership Outcomes, Standing Derivation and Renewal

Partner accountability rests on outcome rates in basis points, computed on read by the partner-college outcomes readout and recomputed internally whenever one of the college's cohorts completes. Only scholars with `ever_matriculated` set to true enter any outcome set: a scholar who withdrew during the `PRE_COLLEGIATE` phase never matriculated and is excluded from every numerator and every denominator.

Each readout reports two variants side by side. The census variant counts only scholars whose cohort has reached `COMPLETED`; it is the authoritative variant, driving both standing derivation and renewal decisions. The rolling variant counts scholars of cohorts in any status — `FORMING`, `LOCKED`, `MATRICULATED`, or `COMPLETED` — giving a live dashboard view that diverges from census whenever a not-yet-completed cohort has matriculated scholars.

For each variant, the retention rate in basis points is the count of the variant's scholars whose `enrollment_status` is `RETAINED` or `GRADUATED`, multiplied by 10000, divided by the variant's total scholar count, and rounded half-up to an integer; the rate is null when the variant's set is empty. The graduation set of a variant is its members whose `enrollment_status` is `GRADUATED`, `WITHDRAWN`, or `DISMISSED`, and the graduation rate in basis points is the count of `GRADUATED` scholars within that set, multiplied by 10000, divided by the graduation set's size, and rounded half-up to an integer; the rate is null when the graduation set is empty. The readout returns five fields: `retention_bps_census`, `graduation_bps_census`, `retention_bps_rolling`, `graduation_bps_rolling`, and the college's current `college_status`.

Standing derivation runs automatically, immediately after one of the college's cohorts reaches `COMPLETED`, using the freshly recomputed census retention rate. An `ACTIVE` college whose census retention falls below 7000 basis points moves to `PROBATION` — a census retention of 6999 sends the college to `PROBATION`, while exactly 7000 leaves it `ACTIVE`. A `PROBATION` college recovers to `ACTIVE` when a later completion lifts census retention to at least 8000 basis points. A null census retention — an empty census — never changes standing. While a college is `PROBATION`, activation of new agreements is blocked with `ERR_COLLEGE_NOT_ACTIVE`.

Renewal review is the periodic `ProgramAdmin` decision on the partnership, carrying a `decision` of `RENEW` or `LAPSE`. A `RENEW` decision is threshold-gated on the census variant: it requires census retention of at least 8000 basis points and census graduation of at least 6000 basis points, and failing either threshold — including a null rate, which always fails the gate — is rejected with `ERR_RENEWAL_THRESHOLDS_NOT_MET`. A successful renewal increments the college's `renewed_cycles_count` by one and the college becomes, or stays, `ACTIVE`. A `LAPSE` decision is terminal: the college moves to `LAPSED`, every `DRAFT` agreement of the college expires to `EXPIRED`, and both agreement creation and agreement activation against the college are blocked from then on with `ERR_COLLEGE_NOT_ACTIVE`.

## 4. Endpoint Definitions

Endpoints that create a new resource respond with HTTP 201; endpoints that modify an existing resource, perform an action, or read data respond with HTTP 200. All list endpoints return the envelope pagination fields of Section 2.3 and sort by `created_at` ascending unless noted otherwise. The table below is a minimal index — request fields, response shapes, and side effects are specified by the narratives of Sections 2 and 3, not repeated here.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /api/_clock/set_current_utc | Advance the logical clock; runs the offer-expiry sweep against the new now | ProgramAdmin |
| POST | /api/city-programs | Create a city recruitment program for an admissions cycle | ProgramAdmin |
| GET | /api/city-programs/{id} | Get one city program | All eight roles |
| POST | /api/nominating-partners | Register a high school or community organization as a nominating partner | ProgramAdmin |
| GET | /api/city-programs/{id}/partners | List the nominating partners of a city program | All eight roles |
| POST | /api/nominees | Submit a nomination against a partner's quota | Nominator, ProgramAdmin |
| GET | /api/nominees | List and filter nominees | All eight roles |
| GET | /api/nominees/{id} | Get one nominee with status, current round, and round scores | All eight roles |
| POST | /api/nominees/{id}/withdraw | Withdraw a nominee before assessment begins, releasing one quota slot | Nominator, ProgramAdmin |
| POST | /api/nominees/{id}/decision | Assessment decision: ADVANCE, WAITLIST (round 3 only), or DROP | SelectionOfficer, ProgramAdmin |
| GET | /api/nominees/{id}/evaluations | List the evaluations of a nominee | All eight roles |
| POST | /api/evaluations | Submit one assessor scorecard for a nominee's current round | Assessor |
| POST | /api/partner-colleges | Create a partner college | ProgramAdmin |
| GET | /api/partner-colleges/{id} | Get one partner college | All eight roles |
| GET | /api/partner-colleges/{id}/outcomes | Computed census and rolling outcome rates plus current college status | All eight roles |
| GET | /api/partner-colleges/{id}/agreements | List the agreements of a college | All eight roles |
| GET | /api/partner-colleges/{id}/mentors | List the mentors of a college | All eight roles |
| POST | /api/partner-colleges/{id}/renewal-review | Renewal decision on the partnership: RENEW or LAPSE | ProgramAdmin |
| POST | /api/mentors | Register a faculty mentor for a partner college | ProgramAdmin |
| POST | /api/partner-agreements | Draft a partner agreement, optimistic-concurrency guarded | ProgramAdmin |
| POST | /api/partner-agreements/{id}/activate | Activate a DRAFT agreement | ProgramAdmin |
| POST | /api/cohorts | Create the cohort for an ACTIVE agreement | ProgramAdmin |
| GET | /api/cohorts | List and filter cohorts | All eight roles |
| GET | /api/cohorts/{id} | Get one cohort with seat ledger, fill projections, status, and invoice | All eight roles |
| POST | /api/cohorts/{id}/matriculate | Matriculate a LOCKED cohort and compute the program-fee invoice | ProgramAdmin |
| POST | /api/offers | Extend a placement offer to a SELECTED nominee | SelectionOfficer, ProgramAdmin |
| GET | /api/offers | List and filter offers | All eight roles |
| GET | /api/offers/{id} | Get one offer | All eight roles |
| POST | /api/offers/{id}/accept | Nominee accepts an offer, creating the scholar and training records | Nominee |
| POST | /api/offers/{id}/decline | Nominee declines an offer, releasing the seat | Nominee |
| GET | /api/scholars | List and filter scholars | All eight roles |
| GET | /api/scholars/{id} | Get one scholar with both state axes, training count, and alumni flag | All eight roles |
| GET | /api/scholars/{id}/training-records | List the scholar's eight training records, sorted by module_code ascending | All eight roles |
| GET | /api/scholars/{id}/internships | List the scholar's internships | All eight roles |
| POST | /api/scholars/{id}/lifecycle | Drive the enrollment and/or standing axis of a scholar | ProgramAdmin, Scholar |
| POST | /api/training-records/{id}/complete | Mark a training module COMPLETED | ProgramAdmin |
| POST | /api/cohort-meetings | Log a cohort meeting or an individual check-in | FacultyMentor |
| GET | /api/cohorts/{id}/meetings | List the meetings of a cohort | All eight roles |
| POST | /api/internships | Propose an internship for a scholar | CareerDirector, ProgramAdmin |
| POST | /api/internships/{id}/transition | Move an internship along its lifecycle | CareerDirector, ProgramAdmin |

## 5. Error Code Catalogue

The catalogue below lists every error identifier and its HTTP status. Trigger conditions are specified in the narrative of Sections 2 and 3, alongside the workflows each error guards; they are deliberately not repeated here.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_INVALID_REQUEST | 400 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_STALE_VERSION | 412 |
| ERR_INVALID_STATE | 409 |
| ERR_NOMINEE_NOT_IN_ROUND | 409 |
| ERR_COHORT_NOT_FORMING | 409 |
| ERR_AGREEMENT_NOT_ACTIVE | 409 |
| ERR_COLLEGE_NOT_ACTIVE | 409 |
| ERR_SCHOLAR_NOT_ELIGIBLE | 409 |
| ERR_NOMINATION_WINDOW_CLOSED | 422 |
| ERR_DUPLICATE_EVALUATION | 409 |
| ERR_ACTIVE_OFFER_EXISTS | 409 |
| ERR_COHORT_EXISTS | 409 |
| ERR_ACTIVE_AGREEMENT_EXISTS | 409 |
| ERR_CITY_MISMATCH | 422 |
| ERR_MENTOR_COLLEGE_MISMATCH | 422 |
| ERR_MENTOR_SCHEDULE_CONFLICT | 422 |
| ERR_INTERNSHIP_OVERLAP | 422 |
| ERR_COHORT_SIZE_INVALID | 422 |
| ERR_NOMINATION_QUOTA_EXCEEDED | 422 |
| ERR_COHORT_FULL | 422 |
| ERR_INSUFFICIENT_EVALUATIONS | 422 |
| ERR_CUTOFF_NOT_MET | 422 |
| ERR_RENEWAL_THRESHOLDS_NOT_MET | 422 |
