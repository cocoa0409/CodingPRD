# Low-Income College Match API — Product Requirements Document

## 1. Introduction

Every admission cycle, large numbers of high-achieving students from low-income households never apply to the selective colleges that would serve them best — a well-documented undermatching problem driven by sticker price, application complexity, and the absence of trusted guidance at the moment of application. This platform operates a dedicated application channel, deliberately separate from the standard admission process, through which such students apply once and are considered by a network of partner colleges. Each partner college commits to meeting the full demonstrated financial need of every student it matches, under either a no-loan or a minimal-loan aid policy, and the match itself is binding: a matched student is admitted with an early, guaranteed funding decision rather than waiting through the regular admission calendar.

The API governs the entire pipeline behind that promise. High school counselors and community partner organizations recruit and nominate eligible students; summer and college-prep scholar programs feed the applicant pool; a consortium program operator drives each cycle through recruitment, application, review, ranking, match-run, regular-decision, and outcome-tracking phases. Students who rank partner colleges but do not match are not lost — they flow automatically into the partner colleges' regular decision pools. Behind the decisions sit document-based income verification conducted under segregation of duties, financial aid packaging that must always balance to the cent against the cost of attendance, enrollment recording, and multi-year tracking of persistence and graduation. All monetary values are integer cents, and all time-dependent behavior reads a single controllable logical clock so that an entire cycle can be driven deterministically.

## 2. Global Specifications & System-Wide Principles

This section defines the rules that hold uniformly across the API: identity and access, the response envelope, pagination, time, money, the cycle phase model, concurrency control, slot accounting, and the order in which validation failures are reported.

### 2.1. User and Role-Based Access Control

Every request carries two HTTP headers that establish the caller's identity: `X-User-Role`, which names the caller's operational role, and `X-User-ID`, which identifies the caller. The platform recognizes exactly six roles, spelled exactly as shown here: `Anonymous`, `ProgramAdmin`, `Student`, `Counselor`, `PartnerStaff`, and `CollegeOfficer`. A request whose `X-User-Role` header is absent or names no declared role, or whose `X-User-ID` header is absent for any role other than `Anonymous`, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not among an endpoint's authorized roles, or that fails the entity-backed ownership rule attached to that role, is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

Identity bindings differ per role. When `X-User-Role` is `Student`, `X-User-ID` is the `id` of the acting Student; ownership checks on any resource that references a Student compare the resource's student foreign key to `X-User-ID`, so a student may act only on their own applications, rankings, and enrollment acceptance. When `X-User-Role` is `Counselor`, `X-User-ID` is the `id` of the acting Counselor, and the counselor may act only on their own referrals and their own verification submissions. When `X-User-Role` is `PartnerStaff`, `X-User-ID` is the `id` of the acting CommunityPartner organization, and ownership extends only to that organization's own referrals. When `X-User-Role` is `CollegeOfficer`, `X-User-ID` is the `id` of the PartnerCollege the officer serves; ownership checks on college-scoped resources — aid packages, matches, outcome records, regular-decision authority — compare the resource's `college_id` to `X-User-ID`. When `X-User-Role` is `ProgramAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity: the server may record it but never compares it to any entity's `id`. When `X-User-Role` is `Anonymous`, no `X-User-ID` is required at all, and any value supplied is treated as opaque and never compared to a persisted entity. These ownership rules bind wherever a request resolves to a single owned resource or a single owning parent: single-resource reads, action endpoints, per-parent listings such as a student's prep-program history or an application's rankings and income verifications, and college-scoped reads whose path names the college (an officer reads only their own college's ranking entries and regular pool). For a `Student` they also reach matches, aid packages, and outcome records through the owning application. The global query-filtered list endpoints — `GET /colleges`, `GET /referrals`, `GET /applications`, `GET /matches`, `GET /aid-packages`, and `GET /outcomes` — enforce role membership only and are never filtered by ownership: any authorized caller sees the full filtered result set.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, read from the logical clock of §2.4 — never the wall clock.
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
- Requests to undeclared paths or unsupported methods are answered in the same error envelope with `error_id` `ERR_NOT_FOUND` and the matching 4xx status; an unexpected server failure is answered with `error_id` `ERR_INTERNAL` (HTTP 500).

### 2.3. Pagination

List endpoints are paginated through two query parameters. `limit` caps the number of items returned; when omitted it defaults to 10, and it accepts a minimum of 1 and a maximum of 100. `offset` skips a number of items from the start of the result set and defaults to 0. Out-of-range values are clamped rather than rejected: a `limit` below 1 is read as 1 and above 100 as 100, and a negative `offset` is read as 0; a non-integer `limit` or `offset` is `ERR_INVALID_REQUEST` (HTTP 400).

Unless an endpoint states otherwise, every list endpoint returns its resources sorted by `created_at` in ascending order. Resources that share a `created_at` keep their insertion order — the sort is stable — and the same stable tie-break holds wherever §3 orders by `created_at`, including the match-run candidate order and the regular-pool ordering.

List responses carry four pagination fields in the envelope's `meta` object: `limit`, `offset`, `total_count`, and `has_more`. `total_count` counts every matching resource before pagination, and `has_more` is true exactly when `offset` plus the number of items on the returned page is less than `total_count`.

### 2.4. The Logical Clock

Every window check, deadline comparison, and system-assigned timestamp in the platform reads one server-side logical clock — never the wall clock. Before the clock is explicitly set, it reads exactly 2026-09-01T00:00:00Z, and it never falls back to wall-clock time on its own. Every ISO 8601 datetime input is read as UTC: a value carrying an offset is honored and normalized to UTC, and a value with no offset is interpreted as UTC. A `ProgramAdmin`-only test-driving capability moves the clock: the caller supplies a `to_iso8601` instant, the clock adopts that instant, the response reports the new value as `current_utc`, and every subsequent window or deadline evaluation reads the new value. Timestamps the server stamps onto resources — `submitted_at` on an application, `matched_at` on a match, `last_checkpoint_at` on an outcome record — all come from this clock.

### 2.5. Common Resource Properties

Every primary resource carries a standard set of system-managed fields. `id` is a server-minted UUID with no type prefix. `created_at` records creation time as an ISO 8601 UTC timestamp with three fractional digits; `updated_at` follows the same format, refreshes on every mutation of the resource, and on a freshly created resource equals `created_at`. `version` is an integer that starts at 1 on creation and increments by exactly 1 on every mutation, including mutations the server performs itself as cascade side effects — an advance of the cycle, a committee decision, an accepted ranking submission, a finalize, a release all move the owning resource's `version` and `updated_at` together.

`RankingEntry` is the single exception to this convention. A ranking row carries only `id` and `created_at`; both `updated_at` and `version` are absent, because a ranking row is never mutated in place — revision replaces the whole list atomically, as §3.4 describes.

### 2.6. Money, Integer Cents, and Rounding Discipline

All monetary quantities — household income, assets, cost of attendance, expected family contribution, and every aid component — are represented as integer cents. No monetary field ever carries a fractional value or a floating-point representation. Where a computation produces a fractional cent, the result is rounded half-up to the nearest whole cent, and the rounding points are pinned per calculation: the asset add-back in the verified contribution formula is rounded before the rate multiplication, and each aid component is rounded individually before its cap is applied — the server never sums first and rounds later. The grant component of an aid package is the one deliberate exception to rounding: it is the unrounded remainder that absorbs residual cents so that every package balances exactly, as §3.7 specifies.

### 2.7. The Nine-Phase Cycle Pipeline

A match cycle moves through nine phases in one fixed order: `SETUP` → `RECRUITMENT` → `APPLICATION_OPEN` → `REVIEW` → `RANKING` → `MATCH_RUN` → `REGULAR_DECISION` → `OUTCOME_TRACKING` → `CLOSED`. A `ProgramAdmin` advances the cycle exactly one phase per advance operation, never skipping; each successful advance increments the cycle's `version` by 1. `CLOSED` is terminal, and advancing a cycle already in `CLOSED` is rejected with `ERR_INVALID_STATE`.

Operations are gated by the cycle's current `phase`, and an operation attempted in the wrong phase is rejected with `ERR_WRONG_CYCLE_PHASE` (HTTP 409). The gating map is fixed: application creation and submission are permitted only during `APPLICATION_OPEN`; committee review only during `REVIEW`; ranking submissions only during `RANKING`; the match run only during `MATCH_RUN`; regular-decision admissions and denials only during `REGULAR_DECISION`; enrollment recording during `REGULAR_DECISION` or `OUTCOME_TRACKING`; outcome checkpoints only during `OUTCOME_TRACKING`; referral nominations only during `RECRUITMENT` or `APPLICATION_OPEN`; and income-verification submission and decision only during `REVIEW`, `RANKING`, `MATCH_RUN`, or `REGULAR_DECISION`. Certain phase advances carry their own preconditions — unexpired referral expiry on entering `REVIEW`, list locking on entering `MATCH_RUN`, and terminal-state checks on entering `CLOSED` — which §3 narrates where they occur.

### 2.8. Optimistic Concurrency Control

Exactly two write operations carry optimistic concurrency control, and they are the only endpoints in the API that accept a version field.

Submitting or revising a student's ranking list requires the request to carry `expected_application_version`, the caller's last observed `version` of the application. If the application's current `version` has advanced since the caller last read it — because a prior accepted submission already replaced the list and moved the version forward — the request is rejected with `ERR_STALE_VERSION` (HTTP 412): the caller would otherwise overwrite a list they have never seen.

Revising a finalized aid package requires the request to carry `expected_aid_package_version`, the caller's last observed `version` of the package. If the package's current `version` has advanced since the caller last read it — because a prior finalize or revise already recomputed the amounts — the request is likewise rejected with `ERR_STALE_VERSION` (HTTP 412).

No endpoint outside these two accepts a version field, and no implicit version checks exist anywhere else.

### 2.9. Match Slot Conservation

Each partner college declares `match_slots`, the total number of binding-match slots it offers a cycle, as an integer of zero or more. Its `slots_committed` counter tracks how many of those slots are spoken for, counting exactly the college's matches in `BINDING` or `ENROLLED` status. The conserved invariant: for every college, `match_slots` always equals `slots_committed` plus the free slots still available — a match consumes exactly one slot when it is created, and an administrative release returns exactly one slot to the pool. A college whose slots are all committed simply stops qualifying for further assignments in the match run; exhausted quota is an ordinary outcome, never an error. Both `slots_committed` and `enrolled_count` are computed at read time over the college's entire history — `slots_committed` counts the college's `BINDING` or `ENROLLED` matches across all cycles, and `enrolled_count` counts every outcome record ever created for the college — so match, release, and enrollment events never mutate the college record itself: the college's own `version` and `updated_at` do not move when these counters change.

### 2.10. Validation Order and Error Precedence

When a single request could fail several checks at once, the earliest failure in a fixed global order wins and later checks are never evaluated. The order is:

1. Request well-formedness — required fields present, correct types, enum fields carrying a declared member, list-payload shape — `ERR_INVALID_REQUEST` (HTTP 400). An absent request body is treated as an empty object (so required-field checks fire), a body that is not a JSON object is malformed, and a field present with a JSON null value is treated as absent. The numeric range floors declared in §3 — `match_slots` ≥ 0 on college registration and `household_size` ≥ 1 on application creation — also fail with `ERR_INVALID_REQUEST`, but are enforced immediately after role authorization (priority 3) rather than at this priority.
2. Authentication of the two identity headers — `ERR_UNAUTHENTICATED` (HTTP 401).
3. Role permission on the endpoint — `ERR_UNAUTHORIZED` (HTTP 403). Entity-backed ownership is likewise `ERR_UNAUTHORIZED`, but it is evaluated on the resolved resource and so fires immediately after existence (priority 4): a request naming an unresolvable path identifier reports `ERR_NOT_FOUND` before ownership is ever consulted.
4. Existence of every path parameter, resolved left to right — `ERR_NOT_FOUND` (HTTP 404) at the first unresolved identifier.
5. State-machine legality of the requested transition — `ERR_INVALID_STATE` (HTTP 409). This priority also covers the transition-specific state rejections `ERR_MATCH_BINDING` (withdrawing a matched application), `ERR_MATCH_ALREADY_RUN` (a second match run for the cycle), `ERR_CYCLE_BLOCKED` (a phase advance whose preconditions fail), and the OCC stale-version check `ERR_STALE_VERSION` (HTTP 412) — which on aid-package revision fires at this priority, immediately after the state check, while on ranking submission it fires after cycle-phase gating and the ranking-window check, in the position §3.4 narrates.
6. Cycle-phase gating — `ERR_WRONG_CYCLE_PHASE` (HTTP 409), per the map in §2.7. Evaluating the gate requires reading the gating cycle, so where that cycle is body-supplied — directly, or through a body-supplied application — the reference must resolve first: an unresolvable one is `ERR_NOT_FOUND` ahead of the phase check itself.
7. Time-window checks against the logical clock — `ERR_WINDOW_CLOSED` (HTTP 409) for application submission and ranking submission outside their windows, `ERR_CYCLE_OVERLAP` (HTTP 409) when a new cycle's application window shares even one date with a non-`CLOSED` cycle's window, and `ERR_PROGRAM_OVERLAP` (HTTP 409) when a new prep enrollment intersects an existing one.
8. Referential integrity of body-supplied references — `ERR_REFERRAL_NOT_FOUND` (HTTP 422) for an unusable `referral_id` on an application, `ERR_UNKNOWN_COLLEGE` (HTTP 422) for a college in a ranking list that does not exist, and `ERR_NOT_FOUND` (HTTP 404) when a new referral, income verification, or prep enrollment names a student, cycle, or application that does not exist.
9. Uniqueness and list-shape constraints — `ERR_EMAIL_TAKEN` (HTTP 409) on student registration, `ERR_DUPLICATE_APPLICATION` (HTTP 409) on a second live application, and `ERR_RANK_ORDER_INVALID` (HTTP 422), `ERR_TOO_MANY_RANKS` (HTTP 422), and `ERR_COLLEGE_INACTIVE` (HTTP 409) on ranking submissions.
10. Segregation of duties on verification decisions — `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).
11. The academic eligibility screen at submission — `ERR_ACADEMIC_INELIGIBLE` (HTTP 422).
12. The household income screen at submission — `ERR_INCOME_INELIGIBLE` (HTTP 422).
13. The decided-verification requirement on aid finalization — `ERR_VERIFICATION_REQUIRED` (HTTP 409).

Two consequences of this ordering are worth internalizing. At application submission the academic screen runs before the income screen, so an applicant who fails both is told about academics, not money. And state legality always precedes phase gating, so an operation against an entity in the wrong state reports the state problem even when the phase would also have rejected it.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Cycle: Colleges, Counselors, Partners, and Students

A `ProgramAdmin` opens the pipeline by creating a match cycle with a display `name` and four datetimes that fence the two student-facing windows: `app_opens_at` and `app_closes_at` bracket the application window, and `ranking_opens_at` and `ranking_closes_at` bracket the ranking window. Both windows are closed intervals that include their endpoints. The new cycle's `phase` starts at `SETUP` and its `match_run_completed` flag starts false. One scheduling rule protects the calendar: the new cycle's application window must not share a single date with the application window of any cycle that is not yet `CLOSED`. Because the windows are closed intervals, two windows that merely touch on one date still conflict, and such a create is rejected with `ERR_CYCLE_OVERLAP`.

Partner colleges join the network by registration. A college is registered with a `name`, an `aid_policy` of either `NO_LOAN` or `MINIMAL_LOAN`, a `min_academic_index` floor that an applicant's academic index must reach before the college can take them in the match, a `match_slots` quota of zero or more binding-match slots per cycle, and `coa_cents`, the annual cost of attendance in cents. A newly registered college starts `ACTIVE` with `slots_committed` at zero and `enrolled_count` at zero. Suspension moves a college `ACTIVE` → `SUSPENDED`: a suspended college is excluded from future ranking submissions and from the next match run, while its existing matches and aid packages are entirely unaffected. Reinstatement returns a suspended college to `ACTIVE`. The college directory can be listed with an optional `status` filter.

People enter the system through three registration paths. A `ProgramAdmin` registers each high school counselor with a `full_name`, a `school_name`, and the school's `state_code`, and each community-based organization with an `org_name`, a `state_code`, and a `contact_email`. Students, by contrast, self-register as `Anonymous`, supplying an `email`, a `full_name`, their `state_code` of residence, and a `source` recording how they arrived — one of `SELF`, `COUNSELOR`, `COMMUNITY_PARTNER`, or `PREP_PROGRAM`. The `email` must be unique across students; a duplicate is rejected with `ERR_EMAIL_TAKEN`. Every new student begins at `student_stage` `PROSPECT`, and the stage ladder — `PROSPECT` → `APPLICANT` → `FINALIST` → `MATCHED` → `ENROLLED` — is advanced only by the workflow cascades narrated later in this section, never set directly.

### 3.2. Recruitment and Preparation: Referrals and Prep Programs

While a cycle is in `RECRUITMENT` or `APPLICATION_OPEN` — and only then — a `Counselor` or `PartnerStaff` user nominates a student into the cycle by supplying the `student_id` and the target `cycle_id`, both of which must resolve to existing records (`ERR_NOT_FOUND`), plus an optional free-text `note` that defaults to an empty string. The referral starts in `NOMINATED`. The referrer's identity is recorded polymorphically from the role headers: when a counselor files the nomination the referral's `counselor_id` is set from `X-User-ID` and `partner_id` stays null; when partner staff file it the `partner_id` is set and `counselor_id` stays null. Referrals can be listed with the optional filters `student_id`, `counselor_id`, `partner_id`, `cycle_id`, and `status`.

A nomination can be withdrawn while it is still `NOMINATED` — by the counselor or partner who filed it, or by a `ProgramAdmin`. Revoking a referral that has already left `NOMINATED` is rejected with `ERR_INVALID_STATE`, and a successful revocation lands the referral in `REVOKED`. Nominations the student never acted on die with the application window: the cycle's advance from `APPLICATION_OPEN` to `REVIEW` moves every still-`NOMINATED` referral of that cycle to `EXPIRED`. The only path to `CONVERTED` runs through application submission in §3.3, and a converted referral is what later feeds the referral bonus in regular-pool ordering (§3.8).

Prep programs are the second feeder channel. A `ProgramAdmin` records a summer or college-prep scholar enrollment for a student with the `student_id` — which must exist (`ERR_NOT_FOUND`) — a `program_type` of `SUMMER` or `SCHOLAR`, a `cohort_label` such as "summer-2026", and the enrollment interval from `starts_on` to `ends_on`. The interval is half-open: it includes its start and excludes its end. A new enrollment is rejected with `ERR_PROGRAM_OVERLAP` whenever its interval intersects another non-`WITHDRAWN` enrollment of the same student; touching endpoints do not intersect, so back-to-back programs are allowed. A new record starts `ENROLLED` and is later closed with an `outcome` of `COMPLETED` or `WITHDRAWN`; closing a record that is not currently `ENROLLED` fails with `ERR_INVALID_STATE`. Completion matters downstream: a `COMPLETED` record makes the student count as a prep alumnus on subsequent application submissions, whereas a `WITHDRAWN` record drops out of the overlap check and confers nothing. A student's full prep history is reachable through a per-student listing endpoint.

### 3.3. The Application and Its Eligibility Screens

A student — and only the `Student` role — drafts the match application, which exists entirely apart from the colleges' standard admission processes. The `student_id` is taken from the caller's `X-User-ID`, never from the payload. The payload names the target `cycle_id`, an optional `referral_id` that stays null for self-originated applications, `household_income_cents` as the self-reported annual household income in cents, a `household_size` of at least one, an optional `self_reported_assets_cents` defaulting to zero, `gpa_scaled` carrying the GPA multiplied by 100 (so 375 encodes a 3.75), an optional `test_score` holding the SAT composite with null allowed, and an optional `essay_text` defaulting to an empty string. Creation is permitted only while the target cycle is `APPLICATION_OPEN`; at most one non-`WITHDRAWN` application may exist per student per cycle, a second attempt failing with `ERR_DUPLICATE_APPLICATION`; and a cited referral must exist, still be `NOMINATED`, and belong to the same student and the same cycle — failing any of which the create is rejected with `ERR_REFERRAL_NOT_FOUND`. The new application starts in `DRAFT` with `verification_flag` `NONE`, `matched_college_id` null, and `submitted_at` null, and with `academic_index` and `need_tier` null and `prep_alum` false until the first submission computes those snapshots. Applications can be listed filtered by `student_id`, `cycle_id`, `referral_id`, `matched_college_id`, or `status`.

Submission moves an application `DRAFT` → `UNDER_REVIEW` and is guarded by five screens evaluated in the global order of §2.10: the application must currently be `DRAFT` (`ERR_INVALID_STATE`); the cycle must be in `APPLICATION_OPEN` (`ERR_WRONG_CYCLE_PHASE`); the logical clock must fall within the application window, both bounds inclusive — a submit exactly at `app_opens_at` or `app_closes_at` is inside, anything outside is `ERR_WINDOW_CLOSED`; then the academic screen (`ERR_ACADEMIC_INELIGIBLE`); then the income screen (`ERR_INCOME_INELIGIBLE`).

Three snapshots are computed and stored on the application at submit time. `prep_alum` is true exactly when the student has at least one `COMPLETED` prep record at that moment — `ENROLLED` and `WITHDRAWN` records do not count — and because the flag is a snapshot, a prep program completed later never rewrites an already-submitted application. `academic_index` combines twice the `gpa_scaled` with a test component — zero when `test_score` is null, otherwise the test score divided by 4 with the quotient rounded down to a whole number — and the sum is capped at 2,000, so the stored index is the lesser of 2,000 and the raw sum. `need_tier` compares income against half the household cap: the cap from the income screen is halved and that half is rounded half-up to a whole cent; income at or below the half yields `HIGH`, and anything above it yields `STANDARD`.

The academic screen runs before the income screen and has two paths. A prep alumnus qualifies on grades alone: a `gpa_scaled` of at least 330, with the test requirement waived entirely. Every other applicant must present a `gpa_scaled` of at least 350 and a non-null `test_score` of at least 1200. Every comparison in the screen is inclusive of its boundary, and failure is rejected with `ERR_ACADEMIC_INELIGIBLE`.

The income screen applies a household-size-adjusted cap. The cap starts at $65,000 — 6,500,000 cents — for a reference household of four and adjusts by $4,000, that is 400,000 cents, for each household member above or below four; a household of six is capped at $73,000 and a household of two at $57,000. Eligibility requires `household_income_cents` to be no more than the cap computed for the applicant's `household_size`, and income exactly equal to the cap is eligible. Income above the cap is rejected with `ERR_INCOME_INELIGIBLE`. The comparison is exact integer arithmetic with no rounding.

A successful submit stamps `submitted_at` from the logical clock, flips the cited referral (when there is one) from `NOMINATED` to `CONVERTED` — a cited referral that has left `NOMINATED` by submit time is simply left as it stands and never converts, without failing the submit — advances the student's `student_stage` to `APPLICANT`, and increments the application's `version`. Withdrawal is the student's exit hatch at every point before a binding match: from `DRAFT`, `UNDER_REVIEW`, `FINALIST`, `RANKING_SUBMITTED`, or `REGULAR_POOL` the application lands in `WITHDRAWN`, and every aid package of the application still in `PROVISIONAL`, `FINALIZED`, or `REVISED` is voided with it. Once the application is `MATCHED` the commitment is binding and withdrawal is rejected with `ERR_MATCH_BINDING`. Withdrawal from any other status — `RANKING_LOCKED`, `UNMATCHED`, `ADMITTED_REGULAR`, `ENROLLED`, or an already-terminal application — is rejected with `ERR_INVALID_STATE`.

### 3.4. Review, Ranking, and the Locking of Lists

During `REVIEW`, a `ProgramAdmin` records the committee's `decision` of `FINALIST` or `NOT_FINALIST` on each application. Reviewing an application that is not currently `UNDER_REVIEW` is rejected with `ERR_INVALID_STATE`, and review attempted outside the `REVIEW` phase fails with `ERR_WRONG_CYCLE_PHASE`. Naming an application a `FINALIST` advances the student's `student_stage` to `FINALIST`; `NOT_FINALIST` is a terminal outcome that ends the application's cycle. Either decision increments the application's `version`.

When the cycle reaches `RANKING`, a finalist submits their ranked college list. The payload carries `entries` — each entry pairing a `college_id` with a 1-based `rank_position` — together with `expected_application_version`, the optimistic-concurrency token of §2.8. The guards fire in the global order: the application must be `FINALIST` or `RANKING_SUBMITTED` (`ERR_INVALID_STATE`); the cycle must be in `RANKING` (`ERR_WRONG_CYCLE_PHASE`); the logical clock must sit inside the ranking window, both `ranking_opens_at` and `ranking_closes_at` inclusive (`ERR_WINDOW_CLOSED`); the expected version must equal the application's current `version` (`ERR_STALE_VERSION`); every `college_id` in the list must resolve to an existing partner college (`ERR_UNKNOWN_COLLEGE`) and must name an `ACTIVE` college (`ERR_COLLEGE_INACTIVE`); the list must hold at least 1 and at most 12 entries — more than twelve is `ERR_TOO_MANY_RANKS`, an empty list is `ERR_INVALID_REQUEST`; and the positions must be exactly the contiguous integers 1 through N with no repeats and no college appearing twice, otherwise `ERR_RANK_ORDER_INVALID`.

An accepted submission replaces the application's ranking rows atomically — the previous list is discarded wholesale, never edited row by row — and the new rows carry a `list_seq` one higher than the previous list's, starting at 1 on the first accepted submission. The first submission transitions the application `FINALIST` → `RANKING_SUBMITTED`; a resubmission is a self-loop that leaves it in `RANKING_SUBMITTED`. Every accepted submission increments the application's `version` by 1, which is precisely what invalidates any stale `expected_application_version` a client may still be holding. Ranking rows are reachable two ways: the current list — the rows with the greatest `list_seq` — hangs off the application, while a per-college listing exposes every ranking row that names the college across all submissions, past and present.

The advance from `RANKING` to `MATCH_RUN` is the point of no return, and it is gated twice: the logical clock must have reached `ranking_closes_at`, and no application of the cycle may still be sitting in `UNDER_REVIEW`. Either failure rejects the advance with `ERR_CYCLE_BLOCKED`. When the advance succeeds, every `RANKING_SUBMITTED` application locks into `RANKING_LOCKED`, and every `FINALIST` that never submitted a list slides directly to `REGULAR_POOL`, joining the regular-decision track without ever entering the match.

### 3.5. The Binding Match Run

Once per cycle, in the `MATCH_RUN` phase, a `ProgramAdmin` executes the match. A run requested against a cycle whose `match_run_completed` is already true is rejected with `ERR_MATCH_ALREADY_RUN`. The candidate set is the cycle's applications in `RANKING_LOCKED`, processed in descending `academic_index` with ties broken by `created_at` ascending — never by id. Each candidate's current list is walked in `rank_position` ascending, and a college qualifies at a position when three conditions hold at once: the college is `ACTIVE`, its `slots_committed` is still below its `match_slots`, and the application's `academic_index` is at least the college's `min_academic_index`. The first qualifying position on the list wins — the match is binding — and the walk stops there.

A single assignment fans out into a four-link cascade. First, a Match record is created in `BINDING` status with `rank_position_awarded` set to the winning `rank_position`, `matched_at` stamped from the logical clock, and `application_id`, `college_id`, and `cycle_id` recorded. Second, the match auto-creates its aid package: `PROVISIONAL` status, `guaranteed_full_need` true, `coa_cents` copied from the college's current figure, and all amounts computed under the provisional contribution variant and the composition waterfall of §3.7 — while the college's `slots_committed` rises by exactly 1. Third, the application moves `RANKING_LOCKED` → `MATCHED` and its `matched_college_id` is set to the winning college. Fourth, the student's `student_stage` advances `FINALIST` → `MATCHED`.

A candidate whose list offers no qualifying position — every ranked college full or `SUSPENDED` — is never an error: the application falls through `RANKING_LOCKED` → `UNMATCHED` → `REGULAR_POOL` inside the same run and becomes visible on every partner college's regular-pool read. An empty candidate set is likewise legal: the run succeeds and reports `matched_count` 0 and `unmatched_count` 0. In all cases the run's response reports `matched_count` and `unmatched_count`, the cycle's `match_run_completed` flips to true, and the cycle's `version` increments by 1. Until the run has executed, the advance from `MATCH_RUN` to `REGULAR_DECISION` is blocked with `ERR_CYCLE_BLOCKED` — the pipeline cannot skip its own match.

### 3.6. Income Verification Under Segregation of Duties

From `REVIEW` through `REGULAR_DECISION` — those four phases and no others — a `Counselor` or `PartnerStaff` user files document-verified figures for an application: the `application_id` (which must resolve, else `ERR_NOT_FOUND`), `verified_income_cents`, `verified_assets_cents`, and `verified_household_size`. The record starts `PENDING`, and the filer's identity lands in exactly one of two slots: `submitted_by_counselor_id` when a counselor files, `submitted_by_partner_id` when partner staff file, the other staying null. An application's verification history is listed through a per-application endpoint.

Decisions belong to `PartnerStaff` alone, acting with a `decision` of `VERIFY` or `WAIVE`, and only against a `PENDING` record — any other `outcome` is `ERR_INVALID_STATE`. One conflict-of-interest rule overrides everything else: the deciding partner's `X-User-ID` must differ from the record's `submitted_by_partner_id`, and it must also differ from the `partner_id` of any referral the application cites. The organization that submitted the documents and the organization that nominated the student are both barred from judging them; a violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Whatever the decision, `decided_by_partner_id` is set from the decider's `X-User-ID` — it stays null until a decision — and the application's `verification_flag` follows the outcome.

A `VERIFY` decision runs the discrepancy assessment. When the application reported zero income, the outcome is `VERIFIED` exactly when the verified figure is also zero; any nonzero verified figure is a `DISCREPANCY`. Otherwise the absolute difference between `verified_income_cents` and the reported `household_income_cents` is compared against ten percent of the reported figure using exact integer cross-multiplication — no floating point anywhere: a difference strictly greater than ten percent lands in `DISCREPANCY`, while a difference of exactly ten percent or less is `VERIFIED`. A `WAIVE` decision skips the arithmetic entirely and lands in `WAIVED` under the same segregation rule. All three outcomes are terminal for the record, and each is mirrored onto the application's `verification_flag`.

### 3.7. Aid Packages: Composition, Finalization, and Revision

Every aid package is computed under one of two expected-family-contribution variants, and the package's `aid_variant` records which variant produced its current amounts. The `PROVISIONAL` variant works from the application's self-reported figures: an allowance of $24,000 — 2,400,000 cents — plus $6,000 (600,000 cents) per household member is subtracted from `household_income_cents`, the excess is multiplied by 0.20, the product is rounded half-up to a whole cent, and the result is floored at zero so the contribution never goes negative. The `VERIFIED` variant works from the latest verification record decided `VERIFIED`: first an asset add-back — 12% of `verified_assets_cents`, rounded half-up to a whole cent before any further arithmetic, a pinned rounding order — then an allowance of $20,000 (2,000,000 cents) plus $5,500 (550,000 cents) per verified household member. The verified contribution is `verified_income_cents` plus the add-back minus the allowance, the difference multiplied by 0.22, rounded half-up to a whole cent, and again floored at zero. The two variants deliberately diverge for the same family: the verified path adds assets back in, grants a smaller allowance, and charges a higher rate.

Given `coa_cents` and `efc_cents`, the package decomposes in a pinned order. `need_cents` is the greater of zero and the cost of attendance minus the expected family contribution. `work_study_cents` is the lesser of the $3,000 work-study cap and ten percent of need rounded half-up to a whole cent. `loan_cents` is exactly zero at a `NO_LOAN` college; at a `MINIMAL_LOAN` college it is the lesser of the $1,500 loan cap and twenty percent of the need remaining after work-study, rounded half-up to a whole cent. `grant_cents` is whatever remains — need minus work-study minus loan — and is never rounded, so it absorbs any residual cents. The package always balances: work-study plus loan plus grant plus the expected family contribution equals `coa_cents` exactly. Provenance differs by birth: a match-derived package carries the binding full-need commitment — `guaranteed_full_need` true and a `match_id` pointing at its match — while a package born of regular admission carries `guaranteed_full_need` false and a null `match_id`.

A `CollegeOfficer` of the owning college finalizes a package that is `PROVISIONAL` or `REVISED`; finalizing from any other status is `ERR_INVALID_STATE`. Finalization also requires a decided verification: the application's latest decided income verification must carry the outcome `VERIFIED` or `WAIVED`, failing which the request is rejected with `ERR_VERIFICATION_REQUIRED`. The two acceptable outcomes diverge in effect. A `VERIFIED` decision recomputes every amount under the `VERIFIED` contribution variant and flips `aid_variant` to `VERIFIED`; a `WAIVED` decision keeps the provisional amounts and leaves `aid_variant` at `PROVISIONAL`. Either way the package lands `FINALIZED` and its `version` increments by 1.

A finalized package can be revised by the owning college's officer. The request must carry `expected_aid_package_version` matching the package's current `version`; a mismatch means a prior finalize or revise has already advanced the version since the caller last read the package, and the request is rejected with `ERR_STALE_VERSION` (HTTP 412) per §2.8. An optional `coa_cents` in the payload replaces the stored cost of attendance; all amounts are then recomputed under the package's current `aid_variant`, the status moves `FINALIZED` → `REVISED`, and the `version` increments by 1. Packages die only by cascade: a match release or an application withdrawal moves every affected package still in `PROVISIONAL`, `FINALIZED`, or `REVISED` to `VOID`, which is terminal. Packages can be listed filtered by `match_id`, `application_id`, `college_id`, or `status`.

### 3.8. Regular Decision, Release, and the Two Enrollment Paths

During `REGULAR_DECISION` each college works its regular pool. The pool read takes a `cycle_id` — a missing `cycle_id` query parameter is `ERR_INVALID_REQUEST`, and one naming no cycle is `ERR_NOT_FOUND` — and returns that cycle's `REGULAR_POOL` applications ordered for the viewing college by a priority score: the application's `academic_index`, plus a 40-point bonus when `prep_alum` is set, plus a 25-point bonus when the application cites a referral that reached `CONVERTED`, plus a 15-point need-aware bonus that applies only when the viewing college's `aid_policy` is `NO_LOAN` and the application's `need_tier` is `HIGH`. Ordering is by descending score with ties broken by the application's `created_at` ascending, and an empty pool returns an empty array with HTTP 200 — never an error. Because the need-aware bonus depends on the viewing college, the same application can outrank a higher-index competitor at a `NO_LOAN` college while losing to it at a `MINIMAL_LOAN` one.

Against that pool, a `CollegeOfficer` records a regular `decision` of `ADMIT` or `DENY` for an application that is currently `REGULAR_POOL` — any other status is `ERR_INVALID_STATE` — and only while the cycle is in `REGULAR_DECISION` (`ERR_WRONG_CYCLE_PHASE`). An admission additionally requires the acting college itself to be `ACTIVE` — an `X-User-ID` naming no registered college fails identically, with `ERR_COLLEGE_INACTIVE` — while a denial performs no college check at all. `ADMIT` lands the application in `ADMITTED_REGULAR` and creates its aid package in the same motion: `PROVISIONAL` status, `guaranteed_full_need` false, `match_id` null, `college_id` set to the acting college, and amounts computed under the provisional variant. `DENY` lands the application in `REGULAR_DENIED`, a terminal state, and creates nothing. Either decision increments the application's `version`.

A binding match ends only by administrative release: a `ProgramAdmin` releases a `BINDING` match, optionally recording a `reason`, and releasing a match in any other status is `ERR_INVALID_STATE`. The release cascade has four links. The match itself moves `BINDING` → `RELEASED` and its `version` increments. Its aid package, if still `PROVISIONAL`, `FINALIZED`, or `REVISED`, is voided, and the college's `slots_committed` drops by exactly 1 — the freed slot returns to the pool per the conservation rule of §2.9. The application cascades `MATCHED` → `REGULAR_POOL` with `matched_college_id` cleared to null, rejoining the regular-decision pool. And the student's `student_stage` falls back to `FINALIST`. Matches can be listed filtered by `application_id`, `college_id`, `cycle_id`, or `status`.

Enrollment is recorded on one of two paths, both confined to the `REGULAR_DECISION` and `OUTCOME_TRACKING` phases (`ERR_WRONG_CYCLE_PHASE` elsewhere). A student admitted through regular decision accepts by enrolling their `ADMITTED_REGULAR` application — an application in any other status refuses with `ERR_INVALID_STATE` — and an aid package for the application must exist in `PROVISIONAL`, `FINALIZED`, or `REVISED` status, the enroll failing with `ERR_INVALID_STATE` without one. The acceptance creates an outcome record in `ENROLLED_Y1` with `match_id` null, the college taken from the package, and the cycle taken from the application, moves the application to `ENROLLED`, raises the college's `enrolled_count` by 1, advances `student_stage` to `ENROLLED`, and increments the application's `version`. A matched student is enrolled from the match side instead: a `CollegeOfficer` of the match's college, or a `ProgramAdmin`, records enrollment against a `BINDING` match — any other match status is `ERR_INVALID_STATE` — which moves the match `BINDING` → `ENROLLED`, creates the outcome record in `ENROLLED_Y1` with `match_id` set and application, college, and cycle copied from the match, raises `enrolled_count` by 1, cascades the application `MATCHED` → `ENROLLED`, sets `student_stage` to `ENROLLED`, and increments the match's `version`.

### 3.9. Outcome Tracking and Persistence Reporting

Each outcome record follows its enrollee across the cycle's `OUTCOME_TRACKING` phase, and checkpoints recorded in any other phase are rejected with `ERR_WRONG_CYCLE_PHASE`. A `CollegeOfficer` of the record's college, or a `ProgramAdmin`, files each checkpoint with a `to_status` and an optional `credits_completed`. The legal moves trace a persistence ladder with a re-entry ramp: `ENROLLED_Y1` → `PERSISTED_Y2`, then `PERSISTED_Y2` → `PERSISTED_Y3`, then `PERSISTED_Y3` → `GRADUATED` for students who finish; `ENROLLED_Y1` → `NOT_PERSISTED` for first-year departures; `STOPPED_OUT` from any of `ENROLLED_Y1`, `PERSISTED_Y2`, or `PERSISTED_Y3` for interruptions; and `STOPPED_OUT` → `PERSISTED_Y2` for re-enrollment. Any other pairing of current and target status is rejected with `ERR_INVALID_STATE`. Every checkpoint stamps `last_checkpoint_at` from the logical clock, a stamp the record already carries from the moment of its creation; on the two year-to-year persistence advances — into `PERSISTED_Y2` and into `PERSISTED_Y3` — a supplied `credits_completed` also updates the cumulative credit count, which otherwise simply carries forward from its initial zero. Outcome records can be listed filtered by `application_id`, `college_id`, `cycle_id`, `match_id`, or `status`.

The cycle's outcome summary is a computed read, open to every authenticated role, that reports `enrolled_count`, `on_track_numerator`, `on_track_denominator`, `on_track_rate_bp`, `cohort150_numerator`, `cohort150_denominator`, and `cohort150_rate_bp`. The denominator for both rates is the count of all outcome records of the cycle regardless of status, and the reported `enrolled_count` is that same count. The on-track numerator counts records in `PERSISTED_Y2`, `PERSISTED_Y3`, or `GRADUATED` — a continued-enrollment measure — while the cohort-150 numerator counts `GRADUATED` alone, a completion measure, so the two diverge whenever any enrollee persists without graduating. Each rate is expressed in basis points: the numerator multiplied by 10,000, divided by the denominator, and rounded half-up to a whole basis point. A cycle with no outcome records yet reports 0 for both rates rather than an error.

The cycle's final advance, `OUTCOME_TRACKING` → `CLOSED`, is gated: every application of the cycle must have reached a terminal state — `NOT_FINALIST`, `REGULAR_DENIED`, `WITHDRAWN`, or `ENROLLED` — or be sitting in `MATCHED`; if any application is anywhere else the advance is rejected with `ERR_CYCLE_BLOCKED`. `CLOSED` ends the cycle for good.

## 4. Endpoint Definitions

Operations that create a new resource — a cycle, a college, a counselor, a community partner, a student, a referral, a prep enrollment, an application, or an income verification — answer `201 Created`. Operations that modify an existing resource, drive a state transition, or perform a computed read answer `200 OK`. The table below is deliberately minimal: request payloads, response bodies, and side effects are specified by the narratives of §2 and §3, not here.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | ProgramAdmin |
| POST | `/cycles` | Create a match cycle | ProgramAdmin |
| GET | `/cycles/{id}` | Get a cycle | ProgramAdmin, Student, Counselor, PartnerStaff, CollegeOfficer |
| POST | `/cycles/{id}/advance` | Advance the cycle one phase in the fixed pipeline order | ProgramAdmin |
| POST | `/cycles/{id}/run-match` | Execute the binding match run (once per cycle) | ProgramAdmin |
| GET | `/cycles/{id}/outcome-summary` | Computed persistence and graduation rates for the cycle | ProgramAdmin, Student, Counselor, PartnerStaff, CollegeOfficer |
| POST | `/colleges` | Register a partner college | ProgramAdmin |
| GET | `/colleges` | List partner colleges | ProgramAdmin, Student, Counselor, PartnerStaff, CollegeOfficer |
| GET | `/colleges/{id}` | Get a partner college | ProgramAdmin, Student, Counselor, PartnerStaff, CollegeOfficer |
| POST | `/colleges/{id}/suspend` | Suspend a college from new rankings and the next match run | ProgramAdmin |
| POST | `/colleges/{id}/reinstate` | Reinstate a suspended college | ProgramAdmin |
| GET | `/colleges/{id}/ranking-entries` | List all ranking rows naming this college, across all submissions | ProgramAdmin, CollegeOfficer |
| GET | `/colleges/{id}/regular-pool` | Computed read: the cycle's regular pool ordered for this college | CollegeOfficer, ProgramAdmin |
| POST | `/counselors` | Register a high school counselor | ProgramAdmin |
| GET | `/counselors/{id}` | Get a counselor | ProgramAdmin, Student, Counselor, PartnerStaff, CollegeOfficer |
| POST | `/community-partners` | Register a community partner organization | ProgramAdmin |
| GET | `/community-partners/{id}` | Get a community partner | ProgramAdmin, Student, Counselor, PartnerStaff, CollegeOfficer |
| POST | `/students` | Self-register a student | Anonymous |
| GET | `/students/{id}` | Get a student | ProgramAdmin, Student, Counselor, PartnerStaff, CollegeOfficer |
| GET | `/students/{id}/prep-programs` | List a student's prep program enrollments | ProgramAdmin, Student, Counselor, PartnerStaff |
| POST | `/referrals` | Nominate a student into a cycle | Counselor, PartnerStaff |
| POST | `/referrals/{id}/revoke` | Revoke a nominated referral | Counselor, PartnerStaff, ProgramAdmin |
| GET | `/referrals` | List referrals with optional filters | ProgramAdmin, Counselor, PartnerStaff, Student |
| GET | `/referrals/{id}` | Get a referral | ProgramAdmin, Counselor, PartnerStaff, Student |
| POST | `/prep-programs` | Record a prep program enrollment for a student | ProgramAdmin |
| POST | `/prep-programs/{id}/close` | Close a prep enrollment as completed or withdrawn | ProgramAdmin |
| GET | `/prep-programs/{id}` | Get a prep program record | ProgramAdmin, Student, Counselor, PartnerStaff |
| POST | `/applications` | Create the match application | Student |
| GET | `/applications/{id}` | Get an application | ProgramAdmin, Student, CollegeOfficer, Counselor |
| GET | `/applications` | List applications with optional filters | ProgramAdmin, CollegeOfficer, Counselor, PartnerStaff |
| POST | `/applications/{id}/submit` | Submit a draft application through the eligibility screens | Student |
| POST | `/applications/{id}/withdraw` | Withdraw before the binding match | Student |
| POST | `/applications/{id}/review` | Committee decision: finalist or not | ProgramAdmin |
| POST | `/applications/{id}/rankings` | Submit or revise the ranked college list (OCC) | Student |
| GET | `/applications/{id}/rankings` | Get the application's current ranking list | ProgramAdmin, Student, CollegeOfficer |
| GET | `/applications/{id}/income-verifications` | List the application's income verification records | ProgramAdmin, PartnerStaff, Counselor, Student |
| POST | `/applications/{id}/regular-decision` | Admit or deny a regular-pool application | CollegeOfficer |
| POST | `/applications/{id}/enroll` | Student accepts a regular admission | Student |
| GET | `/matches/{id}` | Get a match | ProgramAdmin, Student, CollegeOfficer |
| GET | `/matches` | List matches with optional filters | ProgramAdmin, Student, CollegeOfficer |
| POST | `/matches/{id}/release` | Administratively release a binding match (compensation cascade) | ProgramAdmin |
| POST | `/matches/{id}/enroll` | Record enrollment of a matched student | CollegeOfficer, ProgramAdmin |
| GET | `/aid-packages/{id}` | Get an aid package | ProgramAdmin, Student, CollegeOfficer |
| GET | `/aid-packages` | List aid packages with optional filters | ProgramAdmin, Student, CollegeOfficer |
| POST | `/aid-packages/{id}/revise` | Revise a finalized package (OCC; optional new cost of attendance) | CollegeOfficer |
| POST | `/aid-packages/{id}/finalize` | Finalize a provisional or revised package | CollegeOfficer |
| POST | `/income-verifications` | Submit document-verified income figures for an application | Counselor, PartnerStaff |
| POST | `/income-verifications/{id}/decide` | Decide a pending verification | PartnerStaff |
| POST | `/outcomes/{id}/checkpoint` | Advance an outcome record (persistence, graduation, stop-out, re-enrollment) | CollegeOfficer, ProgramAdmin |
| GET | `/outcomes/{id}` | Get an outcome record | ProgramAdmin, Student, CollegeOfficer |
| GET | `/outcomes` | List outcome records with optional filters | ProgramAdmin, Student, CollegeOfficer |

## 5. Error Code Catalogue

Trigger conditions for each error live in the narratives of §2 and §3; this catalogue is the index of identifiers to HTTP status codes.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_MATCH_BINDING` | 409 Conflict |
| `ERR_MATCH_ALREADY_RUN` | 409 Conflict |
| `ERR_CYCLE_BLOCKED` | 409 Conflict |
| `ERR_WRONG_CYCLE_PHASE` | 409 Conflict |
| `ERR_WINDOW_CLOSED` | 409 Conflict |
| `ERR_CYCLE_OVERLAP` | 409 Conflict |
| `ERR_PROGRAM_OVERLAP` | 409 Conflict |
| `ERR_REFERRAL_NOT_FOUND` | 422 Unprocessable Entity |
| `ERR_UNKNOWN_COLLEGE` | 422 Unprocessable Entity |
| `ERR_COLLEGE_INACTIVE` | 409 Conflict |
| `ERR_DUPLICATE_APPLICATION` | 409 Conflict |
| `ERR_EMAIL_TAKEN` | 409 Conflict |
| `ERR_RANK_ORDER_INVALID` | 422 Unprocessable Entity |
| `ERR_TOO_MANY_RANKS` | 422 Unprocessable Entity |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_ACADEMIC_INELIGIBLE` | 422 Unprocessable Entity |
| `ERR_INCOME_INELIGIBLE` | 422 Unprocessable Entity |
| `ERR_VERIFICATION_REQUIRED` | 409 Conflict |
| `ERR_INTERNAL` | 500 Internal Server Error |
