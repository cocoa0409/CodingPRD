# Government Finance Awards API — Product Requirements Document

## 1. Introduction

Public-sector finance officers measure their craft against peer standards: the annual financial report that survives line-by-line checklist scrutiny, and the budget presentation that communicates policy as clearly as it accounts for money. This API operates the association's award and professional-practice programs end to end — the Financial Reporting award and the Budget Presentation award, the blind peer-review machinery that decides them, the reviewer recruitment and training pipeline that staffs them, the best-practice publications that codify what committees learn, and the small-government scholarship and technical-assistance funds that let the smallest jurisdictions participate at all. It also coordinates with standards setters by tracking emerging reporting standards and cascading their activation through the checklists and draft applications that depend on them.

Every workflow is anchored to a server-maintained logical clock rather than wall-clock time, so program calendars, appeal windows, member comment periods, and standards effective dates behave deterministically. Access is organized around segregation of duties: the government that submits a report never reviews it, the reviewer never decides the award, the committee member who drafts a publication may not be the chair who publishes it, and the administrators who configure programs hold no vote in their outcomes.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. All resources are exposed under a flat topology beneath the `/gfoa` mount, with one test-driving capability that lives outside that mount (see §2.4).

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting party, and `X-User-Role`, declaring the capacity in which they act. The system recognizes exactly six roles: `PlatformAdmin`, `GovernmentContact`, `Reviewer`, `CommitteeMember`, `Member`, and `AwardsDirector`. A request with either header missing or invalid, or whose role is not one of these six, is rejected with `ERR_UNAUTHENTICATED`. Each operation declares the roles authorized to call it (§4); a caller whose role is not on that operation's list is rejected with `ERR_FORBIDDEN_ROLE`.

The meaning of `X-User-ID` depends on the presented role. When `X-User-Role` is `GovernmentContact`, `X-User-ID` is the `id` of the acting Government; ownership checks on any resource that references a government compare the resource's `government_id` field to `X-User-ID`. When `X-User-Role` is `Reviewer`, `X-User-ID` is the `id` of the acting ReviewerProfile; ownership checks compare it to an assignment's `reviewer_id` or to the profile's own `id`. When `X-User-Role` is `CommitteeMember` or `Member`, `X-User-ID` is the `id` of the acting Member; committee operations additionally require that this id be an element of the target publication's `member_ids`, and publishing additionally requires that it equal the publication's `chair_member_id`. When `X-User-Role` is `PlatformAdmin` or `AwardsDirector`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. Any attempt to act on a resource owned by someone else — another government's submission, another reviewer's assignment or profile, a publication whose committee the caller does not sit on — is rejected with `ERR_NOT_RESOURCE_OWNER`.

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

List endpoints accept two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items skipped and defaults to 0.

Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order.

The `meta` object of every list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and Posture-Derived Fields

All time-dependent behavior in the system reads a single logical clock maintained by the server — never the host's wall-clock time. At startup the logical clock reads exactly `2026-09-01T00:00:00Z`; before any explicit set call the clock holds this default and must not fall back to wall-clock time. A `PlatformAdmin`-only test-driving capability, mounted outside the `/gfoa` prefix, advances the clock to a supplied `to_iso8601` instant and responds with the resulting `current_utc`. Advancing the clock changes what time-gated operations permit and what derived fields report on their next read.

One derived field depends on the clock directly. An award cycle's `posture` is recomputed on every read of the cycle and on every posture-gated write, from the cycle's three instants: before `submission_opens_at` the posture is `SCHEDULED`; at or after `submission_opens_at` and before `submission_deadline_at` it is `OPEN`; at or after `submission_deadline_at` and before `review_close_at` it is `IN_REVIEW`; and at or after `review_close_at` it is `PAST_REVIEW`. The bounds are half-open throughout — each lower bound inclusive, each upper bound exclusive.

Lifecycle timestamps recorded by the system — `trained_at`, `submitted_at`, `decided_at`, `conferred_at`, `published_at`, and the comment window fields — are all stamps of this logical clock, and each remains null until the event that sets it occurs. A scholarship fund's `status` is likewise derived rather than stored as an independent fact (§3.9).

### 2.5. Common Resource Properties

All primary resources — governments, members, reviewer profiles, checklist versions, standards references, award cycles, report submissions, review assignments, publications, member comments, scholarship funds, and scholarship applications — share a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp of the last modification, refreshed on every change to the resource.
- `version` (integer): a system-managed integer that increments by exactly one on every mutation of the resource, including mutations driven by cascading side effects on related resources.

The review finding is the sole exception: it is an immutable record created once and never modified, so it carries only `id` and `created_at` — both `updated_at` and `version` are absent from it.

### 2.6. Validation Order and Error Precedence

A single request can fail several rules at once, so the system evaluates checks in a fixed order and reports the first failure encountered. The order is:

1. **Authentication** — the headers of §2.1 are present and the role is declared, else `ERR_UNAUTHENTICATED`.
2. **Request shape** — the body parses, every required input field is present, enum fields hold declared values, and numeric ranges are respected: `page_count` must be positive, `requested_cents` must be positive, `pool_total_cents` and `per_applicant_cap_cents` must be positive, `closes_at` must lie after the current logical time, and a cycle's `submission_opens_at` must precede its `submission_deadline_at`, which must precede its `review_close_at`. Violations yield `ERR_VALIDATION`.
3. **Role authorization** — the caller's role appears in the operation's authorized list, else `ERR_FORBIDDEN_ROLE`.
4. **Existence** — path identifiers resolve, then body foreign keys (§2.7), else the matching not-found error.
5. **Ownership** — the caller owns the target resource per §2.1, else `ERR_NOT_RESOURCE_OWNER`.
6. **State gates** — each state-machine precondition of §3 holds, including the two optimistic-concurrency version checks (§2.10) and the requirement that a reviewer be `ELIGIBLE` when accepting an assignment or filing a finding.
7. **Segregation of duties and independence** — a publication's chair may not publish a draft they created (`ERR_SELF_APPROVAL_FORBIDDEN`), and the blind reviewer selector must return a non-empty pool (`ERR_NO_ELIGIBLE_REVIEWER`).
8. **Referential and pin integrity** — pinned checklists and standards must be current, at most one checklist may be `ACTIVE` per program, document types and live submissions must not duplicate, and reviewer availability windows and cycle calendars must not overlap (§3).
9. **Temporal gates** — submissions only while a cycle is `OPEN`, appeals only within thirty days of the decision, standard activation only at or after its effective date, and comments only inside their window.
10. **Structural constraints** — budget-document completeness, exact criterion coverage, checklist weights summing to exactly 1.000, small-government eligibility, purpose-to-program matching, committee membership of the chair, the three-assignment review quorum, and full comment resolution before publishing.
11. **Fiscal checks** — a scholarship fund must still hold unallocated funds at grant time, else `ERR_POOL_EXHAUSTED`.

Precedence is observable: because existence outranks state, an operation on a nonexistent submission reports `ERR_SUBMISSION_NOT_FOUND` rather than a state error, and because state outranks temporal gates, an appeal against a submission that is not `DECIDED_DENIED` reports `ERR_SUBMISSION_STATE_INVALID` rather than `ERR_APPEAL_WINDOW_CLOSED`.

### 2.7. Resource Existence and Reference Resolution

The topology is flat: every write path carries a single resource identifier, and the server validates it before touching anything else. Body foreign-key references are then resolved in input order — `government_id`, `cycle_id`, `checklist_version_id`, `member_id`, `employer_government_id`, `fund_id`, `publication_id`, and finally `chair_member_id` together with `member_ids` — each checked against the corresponding collection. Every unresolvable reference reports the error paired with its resource kind: `ERR_GOVERNMENT_NOT_FOUND` for a government, `ERR_MEMBER_NOT_FOUND` for a member, `ERR_REVIEWER_NOT_FOUND` for a reviewer profile, `ERR_CYCLE_NOT_FOUND` for an award cycle, `ERR_CHECKLIST_NOT_FOUND` for a checklist version, `ERR_STANDARD_NOT_FOUND` for a standards reference, `ERR_SUBMISSION_NOT_FOUND` for a report submission, `ERR_ASSIGNMENT_NOT_FOUND` for a review assignment, `ERR_PUBLICATION_NOT_FOUND` for a publication, `ERR_COMMENT_NOT_FOUND` for a member comment, `ERR_FUND_NOT_FOUND` for a scholarship fund, and `ERR_APPLICATION_NOT_FOUND` for a scholarship application.

### 2.8. Version Pinning and Standards Supersession

Two creation-time pins freeze the criteria a long-lived workflow will be judged against. A report submission pins `pinned_checklist_version_id` from its cycle's `checklist_version_id` at the moment the draft is created; a publication pins `pinned_standards_reference_id` at creation when the committee supplies one. Pins do not float: if a pinned checklist is later superseded, drafts that pinned it are marked stale rather than silently re-pointed, and a publication whose pinned standard has been superseded cannot be published. Supersession itself arrives only through standards activation — a checklist version never transitions directly; its `status` moves from `ACTIVE` to `SUPERSEDED` exclusively as a cascade of an activated standard of the same `program_type` (§3.7), and at most one checklist may be `ACTIVE` per program at any time.

### 2.9. Scores, Money, and Rounding Conventions

All review scores — per-criterion entries, a finding's `weighted_score`, a submission's `provisional_score` and `final_score`, and a checklist's `pass_score` — are numbers carried to exactly 2 decimal places, with rounding performed half-up. Each per-criterion score a reviewer files must lie between 0 and 100 inclusive and carry at most 2 decimal places. All monetary amounts — member dues, fund pools, caps, balances, and grants — are integer cents; wherever a division occurs in a monetary calculation the result is rounded half-up to whole cents. Where a rounding order is pinned by a calculation rule (the finding's weighted score, the award decision's bonus, the dues computation), the order is stated with the rule in §3 and is part of the contract.

### 2.10. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and only these two accept a version field.

Granting a scholarship application requires the request to carry `expected_fund_version`, holding the caller's last observed `version` of the parent scholarship fund. If the fund's current `version` no longer matches — because a prior allocation or rescission has advanced it — the request is rejected with `ERR_STALE_FUND_VERSION` (HTTP 412), since the caller's view of the remaining pool is stale and the grant must be re-issued against the version actually observed.

Publishing a best-practice publication requires `expected_publication_version`, holding the chair's last observed `version` of the publication. Every comment resolution and every comment-period transition advances that version, so a mismatch means the chair has not seen the latest resolution snapshot; the publish is rejected with `ERR_STALE_PUBLICATION_VERSION` (HTTP 412). No other endpoint takes a version field of any kind.

### 2.11. Blind Review and Identity Masking

Review is blind in one direction. When a `GovernmentContact` reads a review assignment — singly or in a list — the assignment's `reviewer_id` is masked to null and only the blind `reviewer_alias` is visible; `PlatformAdmin`, `AwardsDirector`, and `Reviewer` callers see the true value. List scoping also applies to governments: a `GovernmentContact` listing report submissions or scholarship applications sees only rows belonging to their own government, while privileged roles see the full collections.

## 3. Business Logic & Workflows

### 3.1. Program Configuration: Checklists and the Award Calendar

Before any award cycle can open, a `PlatformAdmin` assembles the criteria it will be judged against. Creating a checklist version takes a `program_type` of either `FINANCIAL_REPORTING` or `BUDGET_PRESENTATION`, a human `version_label`, a `pass_score` carried to 2 decimal places, and a `criteria` list in which each entry pairs a `criterion_code` with a numeric `weight`. The weights across the list must sum to exactly 1.000; any other total is rejected with `ERR_WEIGHT_SUM_INVALID`. A new checklist begins life `ACTIVE`, and the association keeps exactly one active checklist per program: creating one while another `ACTIVE` checklist exists for the same `program_type` is rejected with `ERR_CHECKLIST_ALREADY_ACTIVE`.

With an active checklist in hand, the administrator opens an award cycle by supplying its `program_type`, `fiscal_year`, the three calendar instants `submission_opens_at`, `submission_deadline_at`, and `review_close_at`, and the `checklist_version_id` it will run under. The referenced checklist must be `ACTIVE` and must belong to the same `program_type` as the cycle; a mismatch on either count is rejected with `ERR_CYCLE_CHECKLIST_MISMATCH`. The submission window is half-open — it begins inclusively at `submission_opens_at` and ends exclusively at `submission_deadline_at` — and windows of the same program may not overlap, though back-to-back cycles whose boundary instants merely touch are permitted. An overlapping window is rejected with `ERR_CYCLE_WINDOW_OVERLAP`.

A fresh cycle's three counters — `submitted_count`, `decision_ready_count`, and `conferred_count` — all start at zero and advance as submissions move through the pipeline. Anyone reading a cycle sees its `posture` derived live from the logical clock per §2.4, so a cycle created for a future window reads `SCHEDULED`, opens to `OPEN` at its first instant, passes through `IN_REVIEW` once the deadline has passed, and settles into `PAST_REVIEW` once the review horizon closes.

### 3.2. Government Registration, Membership, and Annual Dues

`PlatformAdmin` staff register each participating government with its `legal_name`, a `gov_type` of `CITY`, `COUNTY`, `STATE_GOV`, or `SPECIAL_DISTRICT`, a `population_band` of `SMALL`, `MEDIUM`, or `LARGE` — where `SMALL` means a population under 10,000 and is what drives scholarship eligibility — and a two-letter `state_code`. The government's `lifetime_award_count` starts at zero and is advanced only by the award decision fork of §3.6.

Members are registered with a `full_name`, a contact `email`, the `government_size_band` (`SMALL`, `MEDIUM`, or `LARGE`) of the government the officer serves, and an `independent_finance_officer` flag that defaults to false and marks officers who practice independently. The server computes `annual_dues_cents` at creation; any client-supplied value for it is ignored. The dues computation follows a pinned evaluation order so that the discount tier cannot feed back on itself: first the band base — 15,000 cents for `SMALL`, 30,000 cents for `MEDIUM`, 60,000 cents for `LARGE`; second, an affiliation fee of 5,000 cents added when `independent_finance_officer` is true, and zero otherwise; third, the pre-discount total formed as the band base plus the affiliation fee; fourth, the discount tier keyed on that pre-discount total — ten percent when the pre-discount total is at least 60,000 cents, five percent when it is at least 30,000 cents but below 60,000, and no discount below 30,000; fifth and finally, the dues are the pre-discount total reduced by the discount percentage, rounded half-up to whole cents.

### 3.3. Reviewer Recruitment, Training, and Independence

A finance officer enters the reviewer pipeline by self-application: a `Member` creates a reviewer profile whose `member_id` must equal the caller's own identity, naming an `employer_government_id` and optionally attesting `conflicted_government_ids` and `unavailability_windows`, both of which default to empty lists. The new profile starts as `APPLICANT`, its three counters `open_assignment_count`, `completed_review_count`, and `declined_assignment_count` start at zero, and `trained_at` stays null. Each unavailability window is a pair of `start_date` and `end_date` forming a closed interval — both endpoints inclusive — and the windows on a profile must not intersect; since the intervals are closed, two windows that merely touch at an endpoint already count as overlapping and are rejected with `ERR_AVAILABILITY_WINDOW_OVERLAP`.

Training is administered, never self-declared: a `PlatformAdmin` moves a profile from `APPLICANT` to `TRAINED`, which stamps `trained_at` with the logical clock; attempting that transition from any other state is rejected with `ERR_REVIEWER_STATE_INVALID`. Independence, by contrast, is attested by the reviewer personally. When a `Reviewer` updates their own profile — the caller's identity must equal the profile's `id`, else `ERR_NOT_RESOURCE_OWNER` — setting `independence_attested` to true moves the profile from `TRAINED` to `ELIGIBLE`. Attesting while still `APPLICANT` is rejected with `ERR_REVIEWER_NOT_TRAINED`, since training must come first, and attesting from any other state is rejected with `ERR_REVIEWER_STATE_INVALID`. A reviewer may refresh their own conflict list and availability windows at any time through the same self-service update, but may never write their own `status`.

Suspension, reinstatement, and retirement belong to the administrator. A `PlatformAdmin` may suspend an `ELIGIBLE` reviewer, moving the profile to `SUSPENDED`; reinstate a `SUSPENDED` reviewer back to `ELIGIBLE`; or retire a reviewer from either `ELIGIBLE` or `SUSPENDED` into the terminal `RETIRED` state. Each of these transitions attempted from any other source state is rejected with `ERR_REVIEWER_STATE_INVALID`. Suspension never cancels the reviewer's open assignments — they remain on the books — but nothing can move on them while the reviewer is suspended, because both accepting an assignment and filing a finding require the reviewer to be `ELIGIBLE` at that moment (§3.5).

### 3.4. Award Applications: Drafting, Budget Documents, and Submission

A `GovernmentContact` opens an award application by naming the `government_id` of their own government — it must equal the caller's identity, else `ERR_NOT_RESOURCE_OWNER` — and the `cycle_id` of the target cycle. At creation the system copies the cycle's `program_type` onto the submission and pins `pinned_checklist_version_id` from the cycle's `checklist_version_id`, freezing the criteria this application will be judged against even if the checklist is later superseded. The draft begins with `appeal_round` set to 1, `award_conferred` false, `pinned_checklist_stale` false, and the score fields `provisional_score`, `final_score`, and the timestamps `submitted_at`, `decided_at`, and `conferred_at` all null, with `major_deficiency_total` at zero and `required_improvements` empty. A government may hold only one live application per cycle: creation is rejected with `ERR_DUPLICATE_SUBMISSION` when a submission already exists for the same government and cycle in `DRAFT`, `SUBMITTED`, `UNDER_REVIEW`, `DECISION_READY`, or `APPEALED`; an earlier application that reached `DECIDED_AWARDED` or `DECIDED_DENIED` does not block a fresh draft.

Budget-presentation applications carry their evidence inline. The `budget_documents` list holds entries each pairing a `doc_type` of `POLICY`, `FINANCIAL_PLAN`, or `COMMUNICATION` with a `title` and a positive `page_count`. The list is lawful only for cycles whose program is `BUDGET_PRESENTATION`; supplying it on a submission into a `FINANCIAL_REPORTING` cycle is rejected with `ERR_PROGRAM_NOT_BUDGET`. Within the list each `doc_type` may appear at most once — a repeated type is rejected with `ERR_DOCUMENT_TYPE_DUPLICATE`.

Submitting is the applicant's act and is guarded by four gates, each with its own error. The submission must be in `DRAFT`, else `ERR_SUBMISSION_STATE_INVALID`. Its pinned checklist must still be trustworthy — `pinned_checklist_stale` must be false, else `ERR_CHECKLIST_PIN_STALE` (§3.7 describes how the flag is set). The cycle's `posture` must be `OPEN`, meaning the logical clock is at or after `submission_opens_at` and before `submission_deadline_at`; submitting at any other posture is rejected with `ERR_SUBMISSION_WINDOW_CLOSED`. And a `BUDGET_PRESENTATION` submission must present all three document types — `POLICY`, `FINANCIAL_PLAN`, and `COMMUNICATION` — with any missing type rejected as `ERR_BUDGET_DOCUMENTS_INCOMPLETE`. A successful submit stamps `submitted_at` with the logical clock, moves the submission from `DRAFT` to `SUBMITTED`, advances the cycle's `submitted_count` by one, and increments the `version` of both the submission and the cycle.

### 3.5. Blind Assignment and the Review Round

Review staffing is done one assignment at a time by an `AwardsDirector`, who asks the system to blind-assign the next eligible reviewer to a submission. The submission must be in `SUBMITTED`, `APPEALED`, or `UNDER_REVIEW` — any other state is rejected with `ERR_SUBMISSION_STATE_INVALID` — and the current appeal round must still have seats open: a round holds at most three active assignments, where active means `OFFERED`, `ACCEPTED`, or `SUBMITTED`, and an attempt to seat a fourth is rejected with `ERR_REVIEW_QUORUM_FULL`.

The blind selector is deterministic and filters every reviewer profile through five tests. The candidate must be `ELIGIBLE`; the candidate's `employer_government_id` must differ from the submitting government's `id`; the submitting government must not appear in the candidate's `conflicted_government_ids`; the candidate's `open_assignment_count` must be below five; and the candidate must hold no assignment for this submission in any appeal round whatsoever — prior `OFFERED`, `ACCEPTED`, `DECLINED`, `SUBMITTED`, and `CANCELLED` assignments all exclude, so a reviewer who declined or was cancelled out of an earlier round is never re-offered this submission. Survivors are ranked by `open_assignment_count` ascending, then `completed_review_count` descending, then `trained_at` ascending, and finally `created_at` ascending as the last tie-break, and the first row of that ranking is selected. If no reviewer survives the filter, the request is rejected with `ERR_NO_ELIGIBLE_REVIEWER`.

A created assignment starts `OFFERED`, with its `appeal_round` copied from the submission and its `reviewer_id` set to the selected profile — masked to null whenever a `GovernmentContact` later reads it (§2.11). The blind `reviewer_alias` is formed from the letter R, the current appeal round, and a sequence number, as in `R1-3` for the third assignment created for that submission in round one; the sequence counts every assignment ever created for the submission in that round plus one and is never reused, even by declined or cancelled assignments. Creation increments the reviewer's `open_assignment_count` by one and bumps the reviewer's `version`. The round's first assignment additionally flips the submission — from `SUBMITTED`, or from `APPEALED` after an appeal — into `UNDER_REVIEW` and bumps the submission's `version`; the round's second and third assignments are created while the submission is already `UNDER_REVIEW`, so no further flip occurs.

The offered reviewer answers personally. Accepting requires the caller's identity to equal the assignment's `reviewer_id` (else `ERR_NOT_RESOURCE_OWNER`), the assignment to be `OFFERED` (else `ERR_ASSIGNMENT_STATE_INVALID`), and the reviewer's profile to be `ELIGIBLE` at that moment (else `ERR_REVIEWER_NOT_ELIGIBLE`); acceptance moves the assignment to `ACCEPTED`. Declining requires the same ownership and the same `OFFERED` state, moves the assignment to `DECLINED`, decrements the reviewer's `open_assignment_count`, increments their `declined_assignment_count`, and bumps the `version` of both records.

Filing a finding is the round's productive act. The reviewer must own an `ACCEPTED` assignment and still be `ELIGIBLE`, under the same ownership, state, and eligibility errors as acceptance. The finding's `criterion_scores` list, each entry pairing a `criterion_code` with a `score` between 0 and 100 carried to at most 2 decimal places, must cover exactly the criteria of the submission's pinned checklist: a code the checklist does not declare is rejected with `ERR_UNKNOWN_CRITERION`, and a declared criterion left unscored is rejected with `ERR_CRITERION_SET_INCOMPLETE`. The optional `comments` list carries entries of `criterion_code`, a `severity` of `MAJOR` or `MINOR`, and free `text`; the finding's `major_deficiency_count` counts its `MAJOR` comments. The finding inherits `assignment_id` and `appeal_round` from its assignment.

The finding's `weighted_score` follows a pinned rounding order: each criterion's `score` is multiplied by its pinned checklist `weight`, each per-criterion contribution is rounded half-up to 2 decimal places first, and those rounded contributions are then summed exactly. Consider a checklist whose two criteria each carry weight 0.5 and a finding scoring them 10.01 and 20.01: rounding each contribution first yields 5.01 and 10.01, which sum to 15.02. Summing the raw products first and rounding once would yield 15.01 — that order is deliberately not used.

A filed finding ripples outward in a fixed cascade. The assignment moves from `ACCEPTED` to `SUBMITTED`; the reviewer's `open_assignment_count` decrements and `completed_review_count` increments; the submission's `provisional_score` and `major_deficiency_total` are recomputed over the current round's findings; and when the finding is the round's third, the submission advances from `UNDER_REVIEW` to `DECISION_READY` and the cycle's `decision_ready_count` increments. The `version` of the assignment, the reviewer profile, and the submission each increment, and the cycle's `version` increments when the decision-ready cascade fires.

### 3.6. Scoring, the Award Decision, and the Appeal Loop

While a round is in flight, the submission's `provisional_score` tracks the mean of the current appeal round's submitted findings — the average of their `weighted_score` values, rounded half-up to 2 decimal places — and reads null whenever the round has no findings yet. The `major_deficiency_total` sums the `major_deficiency_count` of the same current-round findings. An appeal resets both: the score back to null and the deficiency total back to zero, because a fresh round supersedes the old evidence.

Deciding is the `AwardsDirector`'s exclusive act and is lawful only from `DECISION_READY`. Attempted while the submission is still `UNDER_REVIEW` — that is, with fewer than three current-round findings filed — it is rejected with `ERR_FINDINGS_INCOMPLETE`; attempted from `DRAFT` or `SUBMITTED` it is rejected with `ERR_SUBMISSION_STATE_INVALID`. The decision first computes `final_score` from the three current-round findings. The base is the mean of the three findings' `weighted_score` values, rounded half-up to 2 decimal places. For a `FINANCIAL_REPORTING` submission the final score is exactly this base. For a `BUDGET_PRESENTATION` submission, when the round's three findings collectively contain zero `MAJOR` and zero `MINOR` comments, a clean-presentation bonus of 1.00 is added after the mean has been rounded, and the result is then capped at 100.00 — the final score is the lesser of 100.00 and the base plus 1.00; when any comment of either severity exists, the final score is the base alone.

The decision then forks deterministically. When the computed `final_score` is at least the pinned checklist's `pass_score` and the `major_deficiency_total` is zero, the submission is decided `DECIDED_AWARDED`: `final_score` is stored, `decided_at` and `conferred_at` are stamped with the logical clock, `award_conferred` becomes true, the cycle's `conferred_count` increments, and the government's `lifetime_award_count` increments, with the `version` of the submission, the cycle, and the government each advancing by one. `DECIDED_AWARDED` is terminal. Otherwise the submission is decided `DECIDED_DENIED`: `final_score` is still computed and stored, `decided_at` is stamped, `required_improvements` is compiled as the texts of every `MAJOR` comment from the current round's findings in the order the findings were submitted, `award_conferred` stays false and the government's lifetime count is untouched, and the submission's `version` increments.

A denied government may appeal within thirty days: the `GovernmentContact` who owns the submission (else `ERR_NOT_RESOURCE_OWNER`) may appeal only from `DECIDED_DENIED` (else `ERR_SUBMISSION_STATE_INVALID`) and only while the logical clock is no later than `decided_at` plus thirty days, after which the request is rejected with `ERR_APPEAL_WINDOW_CLOSED`. An accepted appeal moves the submission to `APPEALED`, increments `appeal_round` by one, resets `provisional_score` to null and `major_deficiency_total` to zero, and cancels every assignment of the superseded round still sitting in `OFFERED` or `ACCEPTED` — each cancelled assignment moves to `CANCELLED` and its reviewer's `open_assignment_count` decrements — while the submission's `version` increments. The cycle then repeats: a fresh blind assignment round under the new `appeal_round` returns the submission to `UNDER_REVIEW` on its first assignment, with every reviewer from every prior round excluded from selection by the any-round rule of §3.5.

### 3.7. Standards Coordination and the Supersession Cascade

The association tracks emerging reporting requirements as standards references. A `PlatformAdmin` registers one with a `topic_code`, a `title`, the `program_type` whose checklist it will eventually supersede, and an `effective_date`; the record begins `ISSUED`.

Activation is a clock-gated, state-gated act. The logical clock must be at or after the standard's `effective_date`, else the activation is rejected with `ERR_STANDARD_NOT_YET_EFFECTIVE`, and the standard must still be `ISSUED` — an attempt to activate one that has already left that state is rejected with `ERR_STANDARD_STATE_INVALID`. Activation moves the standard to `EFFECTIVE` and fires a three-link cascade: every other `EFFECTIVE` standard sharing the same `topic_code` is superseded to `SUPERSEDED`; the `ACTIVE` checklist version of the standard's `program_type` is superseded to `SUPERSEDED`; and every report submission still in `DRAFT` that pinned that checklist has its `pinned_checklist_stale` set to true, which bars it from submitting until a fresh cycle and checklist apply. Submissions already past `DRAFT` keep their pinned checklist and are decided against it — the pin freezes their criteria, and staleness blocks only the submit gate. The activated standard's `version` increments. When a still-later standard on the same topic is itself activated, the previously `EFFECTIVE` one moves to its terminal `SUPERSEDED` state through the same cascade.

### 3.8. Best-Practice Publications: Committee Drafting to Publication

Best-practice publications are drafted by committees and published under segregation of duties. A `CommitteeMember` creates a publication with a `committee_name`, a `chair_member_id`, the full `member_ids` roster, a `title`, a `topic_code`, and optionally a `pinned_standards_reference_id` which defaults to null and, when supplied, freezes the standard the practice interprets. Both the creator and the chair must sit on the committee: the creator's identity — recorded on the publication as `created_by_member_id` — must be an element of `member_ids`, and `chair_member_id` must be an element of `member_ids` as well, with either failure rejected as `ERR_CHAIR_NOT_ON_COMMITTEE`. A new publication starts `DRAFTING` with `draft_number` at 1, both comment counters at zero, both comment-window fields null, and `published_at` null.

Opening the member comment period is a committee act — the caller's identity must be an element of `member_ids`, else `ERR_NOT_RESOURCE_OWNER` — lawful only from `DRAFTING`, else `ERR_PUBLICATION_STATE_INVALID`. The caller supplies `closes_at`, which must lie after the current logical time, else `ERR_VALIDATION`; opening stamps `comment_window_opens_at` with the clock and sets `comment_window_closes_at` to `closes_at`, moving the publication to `MEMBER_COMMENT`.

While the window is open, any `Member` may file a comment with a `publication_id` and a `body`; their `member_id` is taken from the caller's identity. Filing is lawful only while the publication is in `MEMBER_COMMENT` and the logical clock remains before `comment_window_closes_at` — a filing at or after the close is rejected with `ERR_COMMENT_WINDOW_CLOSED`. Each new comment starts with `resolution` set to `PENDING` and increments the publication's `pending_comment_count`, bumping the publication's `version`.

Closing the period is again a committee act, lawful only from `MEMBER_COMMENT` (else `ERR_PUBLICATION_STATE_INVALID`) and only once the logical clock has reached `comment_window_closes_at`; closing early is rejected with `ERR_COMMENT_WINDOW_STILL_OPEN`. The publication moves to `RESOLUTION`, where the committee works the comment queue. Resolving a comment requires committee membership, the publication to be in `RESOLUTION` (else `ERR_PUBLICATION_STATE_INVALID`), and the comment to still be `PENDING` — a comment already resolved is rejected with `ERR_COMMENT_ALREADY_RESOLVED`. The committee member records a `resolution` of `ACCEPTED`, `REVISED`, or `REJECTED`, with an optional `resolution_note`; each resolution decrements the publication's `pending_comment_count`, increments its `resolved_comment_count`, and bumps the `version` of both the comment and the publication. Should the draft need another pass, a committee member may revise, returning the publication from `RESOLUTION` to `DRAFTING`: `draft_number` increments by one, both comment-window fields reset to null, and the publication's `version` increments, while comments from prior rounds are retained as history. The loop between drafting, comment, and resolution may repeat as many times as the committee requires.

Publishing is the chair's act alone. The caller's identity must equal the publication's `chair_member_id` — any other committee member is rejected with `ERR_NOT_RESOURCE_OWNER` — and segregation of duties forbids the chair from publishing a draft they themselves created: when `chair_member_id` equals `created_by_member_id` the publish is rejected with `ERR_SELF_APPROVAL_FORBIDDEN`. The publication must be in `RESOLUTION`, else `ERR_PUBLICATION_STATE_INVALID`; every comment must be resolved, so `pending_comment_count` must be zero, else `ERR_UNRESOLVED_COMMENTS`; and the pinned standard must still be current — when `pinned_standards_reference_id` is set and that standard has become `SUPERSEDED`, the publish is rejected with `ERR_PINNED_STANDARD_SUPERSEDED`. The request must also carry `expected_publication_version` matching the publication's current `version` per §2.10, else `ERR_STALE_PUBLICATION_VERSION`. A successful publish moves the publication to its terminal `PUBLISHED` state, stamps `published_at` with the logical clock, and increments its `version`.

### 3.9. Small-Government Funds: Applications, Allocation, and Rescission

Small-government support runs through dedicated funds. A `PlatformAdmin` creates a scholarship fund with a `fiscal_year`, a `program_label` of `SCHOLARSHIP` or `TECHNICAL_ASSISTANCE` naming which small-government program the fund serves, a `pool_total_cents` and a `per_applicant_cap_cents` that must both be positive, and an `allocation_policy` of `FLAT_CAP` or `PRO_RATA` that defaults to `FLAT_CAP` when omitted. The fund's `remaining_cents` is initialized to `pool_total_cents`, and its `status` is derived from that balance rather than stored as an independent fact: `ALLOCATING` while `remaining_cents` is positive, `EXHAUSTED` exactly when it reaches zero, flipping in either direction as grants and rescissions move the balance.

A `GovernmentContact` applies on behalf of their own government — the application's `government_id` must equal the caller's identity — by naming the `fund_id`, a `purpose`, and a positive `requested_cents`. Two structural gates guard the application. The government's `population_band` must be `SMALL`, else `ERR_GOVERNMENT_NOT_SMALL`. And the purpose must match the fund's program: a `purpose` of `CONFERENCE_SCHOLARSHIP` belongs to a fund labeled `SCHOLARSHIP`, and a `purpose` of `TECHNICAL_ASSISTANCE` belongs to a fund labeled `TECHNICAL_ASSISTANCE`, with any cross pairing rejected as `ERR_PURPOSE_PROGRAM_MISMATCH`. A lawful application starts `PENDING` with `granted_cents` at zero.

Allocation belongs to the `AwardsDirector`. The application must be `PENDING`, else `ERR_APPLICATION_STATE_INVALID`; the request must carry `expected_fund_version` matching the fund's current `version` per §2.10, else `ERR_STALE_FUND_VERSION`; and the fund's `remaining_cents` must still be positive, else `ERR_POOL_EXHAUSTED`. The granted amount follows the fund's allocation policy. Under `FLAT_CAP`, the grant is the smallest of the application's `requested_cents`, the fund's `per_applicant_cap_cents`, and the fund's `remaining_cents` — a first-come waterfall that permits partial grants when the cap or the pool runs short. Under `PRO_RATA`, the system first totals `requested_cents` across all of the fund's applications still in `PENDING`, including the one being allocated; the grant is then the smallest of the per-applicant cap, the fund's `remaining_cents` scaled by this application's share of that total and rounded half-up to whole cents, and the remaining balance itself, so an oversubscribed pool yields a strictly smaller grant than the same fund data would under the flat cap. Allocation stores the result in `granted_cents`, moves the application from `PENDING` to `GRANTED`, subtracts the grant from the fund's `remaining_cents`, recomputes the fund's derived `status` — `EXHAUSTED` exactly when the remainder is zero — and increments the `version` of both the application and the fund.

Rescission is the compensating action, also the `AwardsDirector`'s. Lawful only from `GRANTED`, else `ERR_APPLICATION_STATE_INVALID`, it moves the application to the terminal `RESCINDED` state, adds its `granted_cents` back into the fund's `remaining_cents`, and recomputes the fund's `status` — which returns to `ALLOCATING` as soon as the balance is positive again. The rescinded application keeps its `granted_cents` on record for audit, and the `version` of both the application and the fund increments.

## 4. Endpoint Definitions

The API exposes forty-four operations. Operations that create a new resource — registering a government, member, reviewer profile, checklist, cycle, standard, draft submission, assignment, publication, comment, fund, application, or filing a finding — return `201 Created`. Operations that act on an existing resource, including every state-transition action and the profile update, return `200 OK`, as does the clock capability. Single-resource reads and lists return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the logical clock (test-driving; outside the `/gfoa` mount) | PlatformAdmin |
| POST | `/gfoa/governments` | Register a government | PlatformAdmin |
| POST | `/gfoa/members` | Register a finance-officer member; `annual_dues_cents` computed | PlatformAdmin |
| POST | `/gfoa/reviewer-profiles` | Member self-applies to become a reviewer | Member |
| PUT | `/gfoa/reviewer-profiles/{id}` | Update own attestations/windows (Reviewer) or administer status (PlatformAdmin) | Reviewer, PlatformAdmin |
| POST | `/gfoa/checklist-versions` | Create an `ACTIVE` checklist for a program | PlatformAdmin |
| POST | `/gfoa/award-cycles` | Create an award cycle | PlatformAdmin |
| POST | `/gfoa/standards-references` | Register an emerging reporting standard | PlatformAdmin |
| POST | `/gfoa/standards-references/{id}/activate` | Activate a standard; fires the supersession cascade | PlatformAdmin |
| POST | `/gfoa/report-submissions` | Create a `DRAFT` award application | GovernmentContact |
| POST | `/gfoa/report-submissions/{id}/submit` | Submit a `DRAFT` application | GovernmentContact |
| POST | `/gfoa/report-submissions/{id}/decide` | Decide the award from `DECISION_READY` | AwardsDirector |
| POST | `/gfoa/report-submissions/{id}/appeal` | Appeal a denied decision within thirty days | GovernmentContact |
| POST | `/gfoa/review-assignments` | Blind-assign the next eligible reviewer to a submission | AwardsDirector |
| POST | `/gfoa/review-assignments/{id}/accept` | Reviewer accepts an offered assignment | Reviewer |
| POST | `/gfoa/review-assignments/{id}/decline` | Reviewer declines an offered assignment | Reviewer |
| POST | `/gfoa/review-assignments/{id}/finding` | Reviewer submits the checklist-scored finding | Reviewer |
| POST | `/gfoa/publications` | Create a best-practice publication draft | CommitteeMember |
| POST | `/gfoa/publications/{id}/open-comment-period` | Open the member comment window | CommitteeMember |
| POST | `/gfoa/publications/{id}/close-comment-period` | Close the comment window at/after its close instant | CommitteeMember |
| POST | `/gfoa/publications/{id}/revise` | Return the publication to drafting for another round | CommitteeMember |
| POST | `/gfoa/publications/{id}/publish` | Chair publishes from `RESOLUTION` (OCC on publication version) | CommitteeMember |
| POST | `/gfoa/member-comments` | Member files a comment on an open publication | Member |
| POST | `/gfoa/member-comments/{id}/resolve` | Resolve a `PENDING` comment during `RESOLUTION` | CommitteeMember |
| POST | `/gfoa/scholarship-funds` | Create a small-government scholarship or assistance fund | PlatformAdmin |
| POST | `/gfoa/scholarship-applications` | A `SMALL` government applies to a fund | GovernmentContact |
| POST | `/gfoa/scholarship-applications/{id}/allocate` | Grant funds to a `PENDING` application (OCC on fund version) | AwardsDirector |
| POST | `/gfoa/scholarship-applications/{id}/rescind` | Rescind a grant; the pool is recredited | AwardsDirector |
| GET | `/gfoa/report-submissions/{id}` | Read one submission | PlatformAdmin, GovernmentContact, AwardsDirector |
| GET | `/gfoa/report-submissions` | List submissions; filterable by `government_id`, `cycle_id`, `pinned_checklist_version_id`, `status`; GovernmentContact sees only own rows | PlatformAdmin, GovernmentContact, AwardsDirector |
| GET | `/gfoa/reviewer-profiles/{id}` | Read one reviewer profile | PlatformAdmin, AwardsDirector, Reviewer |
| GET | `/gfoa/reviewer-profiles` | List reviewer profiles; filterable by `member_id`, `employer_government_id`, `status` | PlatformAdmin, AwardsDirector |
| GET | `/gfoa/award-cycles/{id}` | Read one award cycle; `posture` reflects the current logical clock | PlatformAdmin, GovernmentContact, AwardsDirector |
| GET | `/gfoa/award-cycles` | List award cycles; filterable by `checklist_version_id`, `program_type`, `fiscal_year` | PlatformAdmin, GovernmentContact, AwardsDirector |
| GET | `/gfoa/checklist-versions` | List checklist versions; filterable by `program_type`, `status` | PlatformAdmin, GovernmentContact, AwardsDirector |
| GET | `/gfoa/review-assignments/{id}` | Read one assignment; `reviewer_id` masked to null for GovernmentContact | PlatformAdmin, AwardsDirector, Reviewer, GovernmentContact |
| GET | `/gfoa/review-assignments` | List assignments; filterable by `submission_id`, `reviewer_id`, `status`, `appeal_round`; blinded for GovernmentContact | PlatformAdmin, AwardsDirector, Reviewer, GovernmentContact |
| GET | `/gfoa/review-findings/{id}` | Read one finding | PlatformAdmin, AwardsDirector, Reviewer, GovernmentContact |
| GET | `/gfoa/review-findings` | List findings; filterable by `assignment_id` | PlatformAdmin, AwardsDirector, Reviewer, GovernmentContact |
| GET | `/gfoa/member-comments/{id}` | Read one member comment | PlatformAdmin, CommitteeMember, Member |
| GET | `/gfoa/member-comments` | List member comments; filterable by `publication_id`, `member_id`, `resolution` | PlatformAdmin, CommitteeMember, Member |
| GET | `/gfoa/scholarship-applications/{id}` | Read one scholarship application | PlatformAdmin, AwardsDirector, GovernmentContact |
| GET | `/gfoa/scholarship-applications` | List applications; filterable by `fund_id`, `government_id`, `status`; GovernmentContact sees only own rows | PlatformAdmin, AwardsDirector, GovernmentContact |
| GET | `/gfoa/scholarship-funds/{id}` | Read one scholarship fund | PlatformAdmin, AwardsDirector |

## 5. Error Code Catalogue

Trigger conditions for each error live with the workflows that raise them in §2 and §3; this catalogue fixes only the identifier and the HTTP status.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_VALIDATION` | 400 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_SELF_APPROVAL_FORBIDDEN` | 403 |
| `ERR_GOVERNMENT_NOT_FOUND` | 404 |
| `ERR_MEMBER_NOT_FOUND` | 404 |
| `ERR_REVIEWER_NOT_FOUND` | 404 |
| `ERR_CYCLE_NOT_FOUND` | 404 |
| `ERR_CHECKLIST_NOT_FOUND` | 404 |
| `ERR_STANDARD_NOT_FOUND` | 404 |
| `ERR_SUBMISSION_NOT_FOUND` | 404 |
| `ERR_ASSIGNMENT_NOT_FOUND` | 404 |
| `ERR_PUBLICATION_NOT_FOUND` | 404 |
| `ERR_COMMENT_NOT_FOUND` | 404 |
| `ERR_FUND_NOT_FOUND` | 404 |
| `ERR_APPLICATION_NOT_FOUND` | 404 |
| `ERR_SUBMISSION_STATE_INVALID` | 409 |
| `ERR_REVIEWER_STATE_INVALID` | 409 |
| `ERR_REVIEWER_NOT_TRAINED` | 409 |
| `ERR_REVIEWER_NOT_ELIGIBLE` | 409 |
| `ERR_ASSIGNMENT_STATE_INVALID` | 409 |
| `ERR_PUBLICATION_STATE_INVALID` | 409 |
| `ERR_UNRESOLVED_COMMENTS` | 409 |
| `ERR_COMMENT_ALREADY_RESOLVED` | 409 |
| `ERR_APPLICATION_STATE_INVALID` | 409 |
| `ERR_FINDINGS_INCOMPLETE` | 409 |
| `ERR_NO_ELIGIBLE_REVIEWER` | 409 |
| `ERR_CHECKLIST_PIN_STALE` | 409 |
| `ERR_PINNED_STANDARD_SUPERSEDED` | 409 |
| `ERR_CHECKLIST_ALREADY_ACTIVE` | 409 |
| `ERR_DOCUMENT_TYPE_DUPLICATE` | 409 |
| `ERR_DUPLICATE_SUBMISSION` | 409 |
| `ERR_AVAILABILITY_WINDOW_OVERLAP` | 409 |
| `ERR_CYCLE_WINDOW_OVERLAP` | 409 |
| `ERR_SUBMISSION_WINDOW_CLOSED` | 409 |
| `ERR_APPEAL_WINDOW_CLOSED` | 409 |
| `ERR_STANDARD_NOT_YET_EFFECTIVE` | 409 |
| `ERR_COMMENT_WINDOW_CLOSED` | 409 |
| `ERR_COMMENT_WINDOW_STILL_OPEN` | 409 |
| `ERR_REVIEW_QUORUM_FULL` | 409 |
| `ERR_POOL_EXHAUSTED` | 409 |
| `ERR_CYCLE_CHECKLIST_MISMATCH` | 422 |
| `ERR_BUDGET_DOCUMENTS_INCOMPLETE` | 422 |
| `ERR_PROGRAM_NOT_BUDGET` | 422 |
| `ERR_UNKNOWN_CRITERION` | 422 |
| `ERR_CRITERION_SET_INCOMPLETE` | 422 |
| `ERR_WEIGHT_SUM_INVALID` | 422 |
| `ERR_GOVERNMENT_NOT_SMALL` | 422 |
| `ERR_PURPOSE_PROGRAM_MISMATCH` | 422 |
| `ERR_CHAIR_NOT_ON_COMMITTEE` | 422 |
| `ERR_STALE_FUND_VERSION` | 412 |
| `ERR_STALE_PUBLICATION_VERSION` | 412 |
