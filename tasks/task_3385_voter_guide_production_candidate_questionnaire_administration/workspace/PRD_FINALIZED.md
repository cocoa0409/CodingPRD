# Voter Guide Production API — Product Requirements Document

## 1. Introduction

Every election cycle, League chapters produce the nonpartisan voter guides their communities rely on: an accurate inventory of every contest and ballot measure drawn from official candidate filings, questionnaires sent to every verified candidate under a firm deadline and a per-answer word limit, answers published exactly as written — or an explicit indication that the candidate did not respond — plain-language explanations of ballot measures with pro and con arguments held to a neutrality standard, and the finished guide rendered in multiple languages and accessibility formats across print, web, and partner distribution channels. Alongside the guide itself, chapters organize candidate forums with neutral moderators, published participation criteria, and audience-sourced questions. All of this work is performed by volunteers whose own conduct is bound by the League's nonpartisanship policy, and voter-education work must remain visibly separate from any advocacy position a volunteer may hold.

This document specifies the API that administers that production pipeline. Fourteen resource types form an aggregate tree — an election cycle contains jurisdictions, jurisdictions contain contests, and contests branch into filings, a questionnaire with candidate responses, a ballot measure with arguments and reviews, and forums with questions — while volunteers, their attestations, and nonpartisanship incidents cut across the whole tree. Every deadline, sweep, and attestation lapse in the system reads a server-side logical clock that administrators set explicitly, never the host wall clock. Optimistic concurrency controls protect the two most-contested aggregates (contests and questionnaires), guide editions pin versioned snapshots of the content they distribute, and a compliance cascade stands ready to suspend volunteers, quarantine measures, and revert contests the moment a nonpartisanship incident is substantiated.

## 2. Global Specifications & System-Wide Principles

The API is mounted at the server root; every path in §4 is relative to that root.

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-Role`, naming one of the seven declared roles, and `X-User-ID`, identifying the actor. The roles are spelled exactly `LeagueAdmin`, `ChapterCoordinator`, `QuestionnaireEditor`, `NeutralityReviewer`, `ForumModerator`, `Candidate`, and `PublicUser`.

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `LeagueAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server never compares it to any entity's `id`. When `X-User-Role` is `ChapterCoordinator`, `X-User-ID` is the `id` of the acting `Volunteer`, and that volunteer's `roles` array must contain the `COORDINATOR` capability. When `X-User-Role` is `QuestionnaireEditor`, `X-User-ID` is likewise the `id` of the acting `Volunteer`, whose `roles` array must contain `EDITOR`; ownership checks on any resource that references an editor — such as a measure's `drafter_volunteer_id` — compare the resource's foreign-key field to `X-User-ID`. When `X-User-Role` is `NeutralityReviewer`, `X-User-ID` is the `id` of the acting `Volunteer` carrying the `REVIEWER` capability, and a review's `reviewer_volunteer_id` is stamped from it. When `X-User-Role` is `ForumModerator`, `X-User-ID` is the `id` of the acting `Volunteer` carrying the `MODERATOR` capability; forum ownership checks compare a forum's `moderator_volunteer_id` to `X-User-ID`. When `X-User-Role` is `Candidate`, `X-User-ID` is the `id` of the acting `CandidateFiling`; a candidate's response shell is identified by the pair of questionnaire and filing, so a candidate submitting under another filing's id simply has no shell and is answered with `ERR_NOT_FOUND`. When `X-User-Role` is `PublicUser`, no `X-User-ID` is required at all — this is the only role exempt from the header — and any value supplied is an opaque identifier not tied to any persisted entity.

Authentication failures — a missing or unrecognized `X-User-Role`, a missing `X-User-ID` for any role other than `PublicUser`, or an entity-backed `X-User-ID` that does not reference a live record of the role's backing type carrying the required capability tag — are rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A caller whose authenticated role is not listed for the endpoint, or who fails an ownership-flavored check such as a moderator driving someone else's forum, is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

Beyond role membership, every mutation performed under a volunteer-backed role additionally requires the acting volunteer — and, where a moderator is referenced at forum scheduling time, that referenced volunteer — to be in `ACTIVE` status and to hold a `CURRENT` nonpartisanship attestation at the current logical time; violations surface as `ERR_VOLUNTEER_SUSPENDED` (HTTP 403) or `ERR_ATTESTATION_LAPSED` (HTTP 403). The lone exception is attestation renewal itself, which remains open to a lapsed volunteer as the cure path.

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

List endpoints accept `limit` and `offset` query parameters. The `limit` parameter defaults to 10, with a minimum of 1 and a maximum of 100; `offset` defaults to 0. List responses carry `limit`, `offset`, `total_count`, and `has_more` in `meta`. Unless a filter is supplied, list results are ordered by `created_at` ascending. Several list endpoints additionally accept a `status` filter — the filings list, the response-shell list, and the forum-question list — and the measure-argument list accepts both a `status` filter and a `side` filter.

### 2.4. The Logical Clock

All temporal semantics in the system — filing deadlines, questionnaire submission windows, nonresponse sweeps, forum conclusion checks, and attestation lapse — read a single server-side logical clock, never the host wall clock. Before any administrator action the clock reads exactly 2026-09-01T00:00:00Z, the server startup default. A `LeagueAdmin` moves the clock through the clock-setting capability by supplying `current_utc`; the response echoes the installed `current_utc`. Setting the clock has no eager side effects of its own, but every subsequent read or action re-evaluates clock-dependent state lazily — most visibly a volunteer's `attestation_status`, which reads `LAPSED` whenever the logical clock has passed `attestation_expires_at`, until the volunteer renews.

### 2.5. Resource Identity, Timestamps, and Version Semantics

Every resource in the system carries four common properties: `id`, a server-minted UUID with no type prefix, rendered in the canonical dashed UUID string form — thirty-two lowercase hexadecimal digits grouped 8-4-4-4-12 with hyphens; `created_at`, an ISO 8601 UTC timestamp with three fractional digits recording the logical creation time; `updated_at`, refreshed on every mutation; and `version`, an integer that increments by exactly 1 on every mutation of that resource. This applies uniformly to all fourteen resource types — cycles, jurisdictions, contests, filings, questionnaires, response shells, measures, arguments, reviews, editions, forums, questions, volunteers, and incidents alike. Consistency is immediate: every mutation is atomic and its full effect is visible in the response of the same request. Where one operation cascades into another resource — a filing withdrawal hiding a response shell, an incident quarantining a measure — the cascade belongs to the same atomic mutation, and every version increment named for the affected resources happens within that same request.

Timestamps stamped from the logical clock — `filed_at`, `verified_at`, `submitted_at`, `resolved_at` — record the value of `current_utc` at the moment of the mutation.

### 2.6. Optimistic Concurrency Control on Contests and Questionnaires

Two write operations are version-gated, and no other endpoint accepts a version field.

A contest lifecycle transition must carry `expected_contest_version` equal to the contest's current `version`. Filing verifications, withdrawals of verified filings, disqualifications, incident-driven contest reverts, and every successful contest transition all advance the contest's `version`, so a transition request built on a previously observed version may be stale: when `expected_contest_version` no longer matches the current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412) and the caller must re-read the contest before retrying.

A questionnaire amendment must likewise carry `expected_questionnaire_version` equal to the questionnaire's current `version`. Issuing a questionnaire, every candidate submission against it, and every successful amendment advance the questionnaire's `version`; a stale amendment is rejected with `ERR_STALE_VERSION` (HTTP 412).

### 2.7. The Validation Priority Ladder

When several rules could reject the same request, the first matching rule in a fixed order wins, so callers always see one deterministic error. Authentication comes first (`ERR_UNAUTHENTICATED`), then authorization and ownership denials (`ERR_UNAUTHORIZED_ROLE`), then request-body well-formedness (`ERR_INVALID_REQUEST` — covering missing or undeclared fields, bad types or enum members, the `office_name` kind rule, duplicate question positions, incomplete answer coverage, out-of-range channel tiers, and missing `minutes_text` or `corrective_action` where those are required). Only then are path identifiers resolved, strictly left to right, with the first unresolvable id producing `ERR_NOT_FOUND`; for candidate submissions this is also where a missing response shell surfaces.

State checks follow: cycle-open enforcement (`ERR_CYCLE_NOT_OPEN`), then the generic from-state check (`ERR_INVALID_STATE`), then — for candidate submissions — the questionnaire-accepting check (`ERR_QUESTIONNAIRE_NOT_ACCEPTING_SUBMISSIONS`) and the filing-verified check (`ERR_FILING_NOT_VERIFIED`). Version staleness (`ERR_STALE_VERSION`) is evaluated after those state checks and before the volunteer-safety battery. That battery runs in order: suspension (`ERR_VOLUNTEER_SUSPENDED`), attestation lapse (`ERR_ATTESTATION_LAPSED`), advocacy separation (`ERR_ADVOCACY_SEPARATION`), moderator qualification (`ERR_MODERATOR_NOT_QUALIFIED`), the two segregation-of-duties rules (`ERR_SOD_DRAFTER_CANNOT_REVIEW`, `ERR_SOD_MODERATOR_OWN_QUESTION`), and drafter ownership (`ERR_ONLY_DRAFTER_MAY_REVISE`). Compliance posture (`ERR_NEUTRALITY_REVIEW_OUTSTANDING`) comes next, then the temporal rules (`ERR_FILING_DEADLINE_PASSED`, `ERR_FILING_STILL_OPEN`, `ERR_SUBMISSION_WINDOW_CLOSED`, `ERR_CLOSE_BEFORE_DEADLINE`, `ERR_FORUM_TIME_OVERLAP`, `ERR_MODERATOR_BUFFER_VIOLATION`, `ERR_FORUM_NOT_CONCLUDED`), and finally the uniqueness and business constraints (`ERR_DUPLICATE_FIPS`, `ERR_DUPLICATE_FILING_REFERENCE`, `ERR_DUPLICATE_QUESTIONNAIRE`, `ERR_DUPLICATE_MEASURE`, `ERR_DUPLICATE_REVIEW_THIS_ROUND`, `ERR_CONTEST_KIND_MISMATCH`, `ERR_MISSING_PRO_OR_CON`, `ERR_FORUM_QUORUM_NOT_MET`, `ERR_QUESTION_CAP_REACHED`, `ERR_LANGUAGE_UNSUPPORTED`, `ERR_ACCESSIBILITY_GRADE_EXCEEDED`, `ERR_STALE_SNAPSHOT`, `ERR_CONTESTS_NOT_LOCKED`, `ERR_UNRESOLVED_INCIDENTS_EXIST`, `ERR_NO_DISTRIBUTED_EDITION`).

The ordering has one consequence worth stating explicitly: on a candidate submission or resubmission, a questionnaire that has already been `CLOSED` is rejected with `ERR_QUESTIONNAIRE_NOT_ACCEPTING_SUBMISSIONS` even when the submission window has also expired — the state check is evaluated before the temporal one, so state beats temporal.

### 2.8. Nested Path Resolution

Identifiers appearing in a request path are validated from left to right: the cycle id before the jurisdiction id beneath it, the jurisdiction before the contest, the contest before its questionnaire, measure, or forum, and so on down the tree. The first identifier that fails to resolve determines the `ERR_NOT_FOUND` response; deeper identifiers are never examined.

### 2.9. Word Counting, Readability Grades, and Rounding Conventions

Two word-counting policies exist, and every answer or argument text is tokenized the same way before counting: the text is split on whitespace into tokens, and each token is stripped of leading and trailing punctuation — commas, periods, colons, semicolons, exclamation marks, question marks, double quotes, and single quotes. A token is a URL when it contains the substring `://` or begins with the prefix `www.`. Under the `STRICT` policy, a URL token counts as 0 words, and any other token counts as the number of hyphen-separated parts it contains, so a hyphenated compound contributes one word per part. Under the `LENIENT` policy every token counts as exactly 1 word, whether it is a URL or a hyphenated compound, so identical text always yields a LENIENT count lower than or equal to its STRICT count. Measure arguments are always counted `STRICT`, regardless of any contest setting. All word counts are integers.

Rounding everywhere in the system is half-up. Reading-grade scores are rounded half-up to two decimal places, with rounding applied once at the very end of the formula. A contest's completion index is rounded half-up to one decimal place. A measure's balance ratio is rounded half-up to four decimal places. Page estimates and copy allocations are whole numbers, and any division that must yield a whole number rounds up to the next integer.

### 2.10. Nonpartisanship Safeguards: Attestation, Advocacy Separation, and Segregation of Duties

Every volunteer carries two independent dimensions. The lifecycle `status` runs from `ACTIVE` to a terminal `SUSPENDED`. In parallel, `attestation_status` cycles between `CURRENT` and `LAPSED`, driven by the logical clock and by the volunteer's own renewal, entirely independently of suspension. A volunteer whose `advocacy_flag` is set may not be assigned as a measure drafter, a neutrality reviewer, or a forum moderator — voter-education work is kept separate from advocacy positions, and any such assignment is rejected with `ERR_ADVOCACY_SEPARATION`. Segregation of duties binds authorship and judgment to different people throughout: the editor who drafted a measure's explanation may not review it, only the drafter may revise or submit a measure for review, and a moderator may not select a forum question they authored themselves. The concrete trigger conditions for each of these principles appear with their workflows in §3.

## 3. Business Logic & Workflows

Lifecycle transitions throughout this section are driven by transition endpoints whose payload names the requested target state in a `to` field; the state pairs used in the prose (for example `FILING_OPEN` → `QUESTIONNAIRE_PHASE`) identify both the endpoint in §4 and the `to` value that drives it.

### 3.1. Election Cycles, Jurisdictions, and the Volunteer Registry

A `LeagueAdmin` begins by creating an election cycle with a `cycle_name` and an ISO calendar `election_date` in YYYY-MM-DD form; the cycle is born `DRAFT`. Opening the cycle (`DRAFT` → `OPEN`) carries no preconditions and increments the cycle's `version`. Jurisdictions may be added while the cycle is in any status. Each jurisdiction records its parent as `cycle_id` and carries a `jurisdiction_name`, an official `fips_code` that must be unique within the parent cycle (a repeat is rejected with `ERR_DUPLICATE_FIPS`), a non-empty `supported_language_codes` array drawn from `EN`, `ES`, `ZH`, `VI`, and `TL`, and a `reading_level_metric` of `FLESCH_KINCAID` or `SMOG` that will later gate the cycle's accessible editions. A cycle also tracks `distributed_edition_count`, the number of its guide editions currently in `DISTRIBUTED` status, and ultimately progresses `OPEN` → `PUBLISHED` → `ARCHIVED` under the gates described in §3.9.

The volunteer registry is administered by a `LeagueAdmin`. Registering a volunteer records `volunteer_name`, `chapter_code`, a non-empty `roles` array drawn from `COORDINATOR`, `EDITOR`, `REVIEWER`, and `MODERATOR`, and an optional `advocacy_flag` that defaults to false. A new volunteer is `ACTIVE` with a `CURRENT` attestation whose `attestation_expires_at` is set to ninety days after creation. Thereafter the attestation is evaluated lazily: whenever the logical clock has passed `attestation_expires_at`, `attestation_status` reads `LAPSED`, and privileged mutations attempted by that volunteer fail with `ERR_ATTESTATION_LAPSED` until renewal. Renewal is self-service — the caller's `X-User-ID` must equal the volunteer's id, and the capability is open to the four volunteer-backed roles but pointedly not to `LeagueAdmin` — and it resets `attestation_expires_at` to ninety days after the current logical time, restoring `CURRENT` and incrementing the volunteer's `version`. A `LeagueAdmin` may also set or clear a volunteer's `advocacy_flag` at any time. Suspension is terminal and arrives only through the incident cascade of §3.8; a volunteer's `substantiated_incident_count` tallies the incidents that have been substantiated against them.

### 3.2. Building the Contest Inventory and Recording Official Filings

Within an `OPEN` cycle, a `ChapterCoordinator` creates contests under a jurisdiction; attempting this while the cycle is not `OPEN` is rejected with `ERR_CYCLE_NOT_OPEN`. Every contest records its parent as `jurisdiction_id` and declares a `kind` — `CANDIDATE_RACE` or `BALLOT_MEASURE`. An `office_name` is required when and only when the kind is `CANDIDATE_RACE`, and must be omitted for a ballot measure; violating either direction is a malformed request (`ERR_INVALID_REQUEST`). The `seat_count` and `vote_for_count` fields each default to 1, `questionnaire_word_limit` defaults to 100 words per answer, and `word_count_policy` defaults to `STRICT` with `LENIENT` as the alternative. Every contest carries a `filing_deadline`, the last instant at which filings are accepted, and is born `FILING_OPEN`. Reading a contest exposes two computed figures: `verified_candidate_count`, the number of its filings currently `VERIFIED`, and `completion_index`, derived on every read — when the contest has a questionnaire, one hundred times the questionnaire's `submitted_count` divided by its `invited_count`, rounded half-up to one decimal place, and 0.0 when there is no questionnaire or nothing has ever been invited.

The contest lifecycle runs `FILING_OPEN` → `QUESTIONNAIRE_PHASE` → `GUIDE_READY` → `LOCKED`, each step driven by a `ChapterCoordinator` under the optimistic-concurrency rule of §2.6 and each incrementing the contest's `version`. Advancing out of `FILING_OPEN` requires the parent cycle to be `OPEN` (`ERR_CYCLE_NOT_OPEN`) and the logical clock to be strictly past `filing_deadline`: at exactly the deadline the advance is rejected with `ERR_FILING_STILL_OPEN`, and filings remain acceptable at that instant. Advancing from `QUESTIONNAIRE_PHASE` to `GUIDE_READY` is kind-dependent — a candidate race requires its questionnaire to be `PINNED` (`ERR_QUESTIONNAIRE_NOT_PINNED`), while a ballot-measure contest requires its measure to be `APPROVED_FOR_GUIDE` (`ERR_NEUTRALITY_REVIEW_OUTSTANDING`). Locking needs nothing beyond the version check. Two system-driven reversals exist for ballot-measure contests only — `GUIDE_READY` → `QUESTIONNAIRE_PHASE` and `LOCKED` → `QUESTIONNAIRE_PHASE` — fired by the compliance cascade of §3.8; candidate races are never reverted, and apart from those reversals `LOCKED` is terminal.

Filings are recorded against a contest while it is `FILING_OPEN` and the logical clock has not passed `filing_deadline` — a filing at exactly the deadline is accepted, anything later is rejected with `ERR_FILING_DEADLINE_PASSED`, and a contest in any other state rejects the filing with `ERR_INVALID_STATE`. A filing records its parent as `contest_id` — as do the questionnaire, measure, and forums later created beneath the same contest — and carries the officially filed `candidate_name` and `party_label` (which may legitimately read "Nonpartisan") plus a `filing_reference` that must be unique within the contest (`ERR_DUPLICATE_FILING_REFERENCE`). It is born `FILED` and is stamped with `filed_at` from the logical clock.

Verification (`FILED` → `VERIFIED`) is allowed while the contest is `FILING_OPEN` or `QUESTIONNAIRE_PHASE` and is rejected with `ERR_INVALID_STATE` in any later state. Verifying stamps `verified_at`, recomputes the contest's `verified_candidate_count`, and increments the contest's `version`; additionally, when the contest's questionnaire already exists in `ISSUED` status with its submission window still open, verification creates the candidate's response shell in `INVITED` status and recomputes the questionnaire's `invited_count` — this is how a late-verified candidate still receives the questionnaire.

Withdrawal works from either filed state, with asymmetric consequences. Withdrawing a `VERIFIED` filing increments the filing's `withdrawal_count`, recomputes `verified_candidate_count`, increments the contest's `version`, and cascades: the candidate's response shell, whatever its current status, moves to `WITHDRAWN_HIDDEN`, and the questionnaire's `submitted_count`, `nonresponse_count`, and `late_count` are recomputed, with the contest's `completion_index` re-deriving on its next read. Withdrawing a merely `FILED` filing only increments `withdrawal_count`, because no shell can exist for a candidate who was never verified. Disqualification (`VERIFIED` → `DISQUALIFIED`, terminal) requires a `reason` in the request and cascades exactly like a verified withdrawal. Refiling returns a `WITHDRAWN` filing to `FILED` and is deadline-gated: either the contest is `FILING_OPEN` with the logical clock at or before `filing_deadline`, or the contest is `QUESTIONNAIRE_PHASE` with its questionnaire `ISSUED` and the clock at or before the questionnaire's `due_at`; in every other situation the refile is rejected with `ERR_FILING_DEADLINE_PASSED`. A successful refile refreshes `filed_at`, leaves `withdrawal_count` untouched, and — when a hidden shell exists for the filing — restores that shell to `INVITED` with its previously submitted `answers` preserved, recomputing the questionnaire's counters.

A candidate's identity is their filing: when `X-User-Role` is `Candidate`, `X-User-ID` is the filing's `id`, and every shell the candidate can touch is keyed by the pair of questionnaire and filing.

### 3.3. The Candidate Questionnaire

Once a candidate race reaches `QUESTIONNAIRE_PHASE` — and only then; attempting creation earlier is rejected with `ERR_INVALID_STATE`, and attempting it on a ballot-measure contest is rejected with `ERR_CONTEST_KIND_MISMATCH` — a `QuestionnaireEditor` creates the contest's single questionnaire, a second attempt meeting `ERR_DUPLICATE_QUESTIONNAIRE`, inside an `OPEN` cycle. Creation supplies `due_at`, the submission deadline, and `questions`, an ordered array of question objects each carrying a `position_index`, a `prompt_text`, and an optional `word_limit_override`; position indexes must be unique within the questionnaire, and a question whose `word_limit_override` is null inherits the contest's `questionnaire_word_limit`. The questionnaire is born `DRAFT`. Fetching a contest's questionnaire returns an array of zero or one element.

While `DRAFT`, the questionnaire is freely editable: amending replaces `due_at` and/or `questions` when either is supplied, stays in `DRAFT`, and increments the questionnaire's `version`. Amending is the second version-gated operation of §2.6 and must carry `expected_questionnaire_version` matching the questionnaire's current `version`.

Issuing (`DRAFT` → `ISSUED`) requires a non-empty questions array (`ERR_INVALID_REQUEST`) and a contest still in `QUESTIONNAIRE_PHASE` (`ERR_INVALID_STATE`). Issuing creates, for every `VERIFIED` filing of the contest, a response shell in `INVITED` status with empty `answers`, and sets the questionnaire's `invited_count` to the number of shells created. From then on the amendment loop re-opens with sharper consequences: amending an `ISSUED` questionnaire stays in `ISSUED`, but when the amendment extends `due_at` to a moment beyond the current logical time, every shell previously marked `NONRESPONSE_MARKED` returns to `INVITED`, its `published_indicator` returns to `PENDING`, and the questionnaire's `nonresponse_count` is recomputed.

Closing (`ISSUED` → `CLOSED`) requires the logical clock to be strictly past `due_at`; at or before the deadline the attempt is rejected with `ERR_CLOSE_BEFORE_DEADLINE`. Pinning (`CLOSED` → `PINNED`) carries no further preconditions and establishes the questionnaire as the snapshot source for guide editions — the pin is precisely what a candidate race needs before its contest may advance to `GUIDE_READY`. `PINNED` is terminal. Four counters ride on the questionnaire throughout: `invited_count` counts every shell ever created, while `submitted_count`, `nonresponse_count`, and `late_count` count the shells currently in `SUBMITTED`, `NONRESPONSE_MARKED`, and `LATE_UNPUBLISHED` respectively; the six shell statuses always partition `invited_count` exactly.

### 3.4. Candidate Responses, Word Limits, and the Publication Indicator

A candidate always answers against their own shell: the server identifies the shell by the questionnaire in the path and the caller's filing id — the shell is the join of `questionnaire_id` and `filing_id` — and when no such shell exists the request is rejected with `ERR_NOT_FOUND`, which is also what a candidate encounters when probing another filing's slot. Four further gates then apply, in the ladder order of §2.7: the questionnaire must be `ISSUED` (`ERR_QUESTIONNAIRE_NOT_ACCEPTING_SUBMISSIONS`, and this state check fires even when the window has also expired); the shell's filing must be `VERIFIED`, meaning the shell must not be `WITHDRAWN_HIDDEN` (`ERR_FILING_NOT_VERIFIED`); the logical clock must be at or before `due_at`, with a submission at exactly the deadline accepted (`ERR_SUBMISSION_WINDOW_CLOSED`); and the submitted `answers` must cover every declared `position_index` exactly once, each entry pairing a `position_index` with its `text` (`ERR_INVALID_REQUEST`).

On a valid submission, each answer's words are counted under the contest's `word_count_policy` using the tokenization of §2.9, producing `per_answer_word_counts` in the same order as the `answers`. Each answer is measured against its effective limit — the question's `word_limit_override` when set, otherwise the contest's `questionnaire_word_limit` — and an answer is over limit only when its count strictly exceeds that limit; a count exactly at the limit passes. When every answer is within its limit, the shell lands in `SUBMITTED` with `submitted_at` stamped from the logical clock, `over_limit_positions` empty, the questionnaire's `submitted_count` recomputed, and the questionnaire's `version` incremented. When any answer is over, the very same call lands the shell in `OVER_LIMIT_RETURNED` instead, with `over_limit_positions` listing each offending `position_index`. Word-limit excess is deliberately not an error: the League publishes answers unedited or not at all, so an over-limit answer is returned to the candidate rather than trimmed. From `OVER_LIMIT_RETURNED` the candidate resubmits a corrected answer set under the same four gates; the resubmission recomputes the counts and either lands `SUBMITTED` — stamping `submitted_at`, recomputing counters, incrementing the questionnaire's `version` — or remains `OVER_LIMIT_RETURNED` with refreshed `over_limit_positions` and replaced answers. The resubmission's from-state discipline is deliberately no stricter than the initial submission's: a shell in `INVITED`, `SUBMITTED`, `NONRESPONSE_MARKED`, or `LATE_UNPUBLISHED` status is rejected with `ERR_INVALID_STATE`, but a `WITHDRAWN_HIDDEN` shell is not rejected there — exactly as on an initial submission, it proceeds into the four gates, so a resubmission against a hidden shell on a still-`ISSUED` questionnaire is answered by the filing-verified gate with `ERR_FILING_NOT_VERIFIED`, never `ERR_INVALID_STATE`.

After the deadline, a `ChapterCoordinator` runs the nonresponse sweep over the contest. The sweep is defined while the questionnaire is `ISSUED` and the logical clock is past `due_at`, and is rejected under the generic invalid-state rule (`ERR_INVALID_STATE`) at any other time. It moves every `INVITED` shell to `NONRESPONSE_MARKED` and every `OVER_LIMIT_RETURNED` shell to `LATE_UNPUBLISHED`, recomputes the questionnaire's counters, and reports how many shells it moved as `marked_nonresponse_count` and `marked_late_count`; a second sweep over the same contest moves nothing and reports zeros.

Two system cascades complete the shell lifecycle. A withdrawal or disqualification moves the candidate's shell from any status — `INVITED`, `SUBMITTED`, `OVER_LIMIT_RETURNED`, or `NONRESPONSE_MARKED` — to `WITHDRAWN_HIDDEN`, recomputing whichever questionnaire counters the departure touches, and a refile moves a hidden shell back to `INVITED` with its `answers` preserved. The voter-facing `published_indicator` then derives deterministically from shell status: `SUBMITTED` shows as `PUBLISHED_UNEDITED`; `NONRESPONSE_MARKED` shows as `DID_NOT_RESPOND`, so the guide states plainly that the candidate did not reply; `LATE_UNPUBLISHED` shows as `LATE`; `WITHDRAWN_HIDDEN` shows as `WITHDRAWN`; and shells still `INVITED` or `OVER_LIMIT_RETURNED` show as `PENDING`.

### 3.5. Ballot Measure Explanations, Arguments, and Neutrality Review

Once a `BALLOT_MEASURE` contest reaches `QUESTIONNAIRE_PHASE` — earlier attempts are rejected with `ERR_INVALID_STATE`, creating a measure on a candidate race with `ERR_CONTEST_KIND_MISMATCH`, and a second measure on the same contest with `ERR_DUPLICATE_MEASURE` — a `QuestionnaireEditor` creates the contest's ballot measure inside an `OPEN` cycle. Creation records `measure_title`, `official_text`, and the League-drafted `explanation_text`, and stamps `drafter_volunteer_id` with the creator's `X-User-ID`, an attribution that drives segregation of duties for the rest of the measure's life. Both readability grades are computed at creation and on every later revision and are stored as `grade_fk` and `grade_smog`.

The grades share a common analysis of `explanation_text`. Words are the tokens of §2.9. Sentences are the non-empty segments obtained by splitting the text on periods, exclamation marks, and question marks. The syllable count of a word is the number of vowel-group runs — maximal runs of the letters a, e, i, o, u, y — in its lowercased form, and is never less than 1 for any word. Polysyllables are the words with at least three syllables. The Flesch-Kincaid grade equals 0.39 multiplied by the number of words divided by the number of sentences, plus 11.8 multiplied by the total number of syllables divided by the number of words, minus 15.59. The SMOG grade equals 1.043 multiplied by the square root of the polysyllable count multiplied by 30 and divided by the number of sentences, plus 3.1291. Each grade is rounded half-up to two decimal places, with rounding applied once at the very end.

Arguments are filed against the measure — each records its parent as `measure_id` — with a `side` of `PRO` or `CON`, an `argument_text`, and an `author_credit` attribution line. An argument's `word_count` is computed with the `STRICT` policy regardless of contest settings, and the verdict is automatic at creation: a count of at most 250 words makes the argument `ACCEPTED`, while anything more makes it `REJECTED`. Only accepted arguments feed the measure's totals: `pro_word_total` and `con_word_total` sum `word_count` over the `ACCEPTED` arguments of each side, and a rejected argument never touches them. From these totals, `balance_ratio` is the absolute difference between the two divided by the larger of them — except that when both totals are zero the divisor is 1 — rounded half-up to four decimal places. The `balance_flag` is true when the ratio is strictly greater than 0.15, so a ratio of exactly 0.15 does not raise the flag; the flag is advisory to reviewers, never a gate.

When the drafter judges the explanation ready, submitting it for review requires the caller to be the measure's own drafter (`ERR_ONLY_DRAFTER_MAY_REVISE`) and requires at least one `ACCEPTED` `PRO` argument and at least one `ACCEPTED` `CON` argument (`ERR_MISSING_PRO_OR_CON`). Submission moves the measure `DRAFTING` → `IN_NEUTRALITY_REVIEW`, increments `review_round_count`, resets `approvals_this_round` to zero, and increments the measure's `version`. A `NeutralityReviewer` then records a `verdict` — `NEUTRAL`, `LOADED_LANGUAGE`, or `UNBALANCED` — together with `notes`. The reviewer must not be the measure's drafter (`ERR_SOD_DRAFTER_CANNOT_REVIEW`), must personally be `ACTIVE`, `CURRENT` in attestation, and free of the advocacy flag, and may review a given measure at most once per round (`ERR_DUPLICATE_REVIEW_THIS_ROUND`); every review is stamped with a `round_index` equal to the measure's `review_round_count` at the moment it is filed, and every verdict increments the measure's `version`. A `NEUTRAL` verdict increments `approvals_this_round`, and the measure advances to `APPROVED_FOR_GUIDE` only when that counter reaches 2 — approval requires two distinct reviewers in the same round, and a lone approval leaves the measure in `IN_NEUTRALITY_REVIEW`. Either remanding verdict, `LOADED_LANGUAGE` or `UNBALANCED`, ends the round immediately by moving the measure to `REMANDED`. From `REMANDED` — or while still `DRAFTING` — the drafter, and only the drafter, revises: a revision replaces `explanation_text`, recomputes both grades, returns a remanded measure to `DRAFTING`, and increments the measure's `version`.

### 3.6. Guide Editions: Assembly, Snapshot Pinning, and Distribution

A `QuestionnaireEditor` assembles guide editions beneath an `OPEN` cycle — every edition records its parent as `cycle_id` — each edition declaring a `language_code` (`EN`, `ES`, `ZH`, `VI`, or `TL`), a distribution `channel` (`PRINT`, `WEB`, or `PARTNER`), and an `accessibility_format` (`STANDARD`, `LARGE_PRINT`, or `SCREEN_READER`); the edition is born `ASSEMBLING`. Every lifecycle transition of an edition additionally requires the parent cycle to be `OPEN` (`ERR_CYCLE_NOT_OPEN`).

Marking an edition ready (`ASSEMBLING` → `READY`) is the system's great checkpoint, gated by five conditions. The cycle must be `OPEN`. At least one contest of the cycle must be `LOCKED` (`ERR_CONTESTS_NOT_LOCKED`). No ballot measure anywhere in the cycle may sit in `IN_NEUTRALITY_REVIEW` or `REMANDED` (`ERR_NEUTRALITY_REVIEW_OUTSTANDING`). The edition's `language_code` must appear in the `supported_language_codes` of every jurisdiction of the cycle (`ERR_LANGUAGE_UNSUPPORTED`). And when the `accessibility_format` is anything other than `STANDARD`, every `APPROVED_FOR_GUIDE` measure in the cycle must grade at most 8.0 under the `reading_level_metric` of the jurisdiction that owns the measure's contest — a grade of exactly 8.0 passes, while 8.01 fails (`ERR_ACCESSIBILITY_GRADE_EXCEEDED`).

A successful readying pins the snapshot. `snapshot_contest_ids` captures the ids of all of the cycle's contests that are `LOCKED` at that instant, and `pinned_questionnaire_versions` records, for each candidate-race contest in the snapshot, its questionnaire's current `version`. At the same moment `estimated_page_count` is computed over the pinned content, and it then stays stable for as long as the edition remains `READY`. The estimate rounds per contest and only then sums, and that order is significant. For each snapshot contest a word total is computed: for a candidate race, the sum, over the pinned questionnaire's `SUBMITTED` responses, of every answer's word count recomputed under the `STRICT` policy; for a ballot-measure contest, the `STRICT` word count of the measure's `explanation_text` plus the `word_count` of its `ACCEPTED` arguments. Each contest's words are divided by ten and rounded up to whole columns; those columns are divided by two and rounded up to whole pages. The edition's `estimated_page_count` is the sum of these per-contest page counts plus two front-matter pages. By way of illustration, two snapshot contests carrying twenty-one words each yield three columns and then two pages apiece — six pages in total once the two front-matter pages are added — whereas pooling the words across contests before rounding would yield five; the pinned, per-contest order is the specification.

Re-opening (`READY` → `ASSEMBLING`) clears `snapshot_contest_ids` and `pinned_questionnaire_versions` while retaining the last `estimated_page_count` until the next readying. Distribution (`READY` → `DISTRIBUTED`) first proves the snapshot is still faithful: every contest id in `snapshot_contest_ids` must still be `LOCKED`, and every pinned questionnaire version must still equal that questionnaire's current `version`, otherwise the attempt is rejected with `ERR_STALE_SNAPSHOT` — this is the enforcement point through which the incident-driven contest revert of §3.8 blocks a stale print run. The distribute payload carries `print_run_total`, which must be greater than zero, and a non-empty `channel_requests` array whose entries each name a `channel_code`, a `requested` copy count, and a `priority_tier` of 1, 2, or 3; any other tier is a malformed request (`ERR_INVALID_REQUEST`). Allocation then proceeds as a waterfall: tiers are served in ascending order; within a tier, requests are ordered by `requested` descending, with ties broken by `channel_code` in ascending lexicographic order; and each channel receives the lesser of its `requested` count and the copies still remaining, which are then deducted from the run. The result is written to `allocations`, one entry per channel request carrying its `channel_code`, `requested`, `priority_tier`, and the computed `allocated` count, with the leftover recorded as `unallocated_copies`; the allocated copies and the unallocated remainder always sum exactly to `print_run_total`. Distribution recomputes the cycle's `distributed_edition_count`. Retiring (`DISTRIBUTED` → `RETIRED`) closes the edition and recomputes that counter again. Each of these transitions increments the edition's `version`.

### 3.7. Candidate Forums and Public Question Curation

A `ChapterCoordinator` schedules a forum on a candidate-race contest that is in `QUESTIONNAIRE_PHASE` or `GUIDE_READY`; any other contest state is rejected with `ERR_INVALID_STATE`, a ballot-measure contest with `ERR_CONTEST_KIND_MISMATCH`, and a cycle that is not `OPEN` with `ERR_CYCLE_NOT_OPEN`. The request names `scheduled_start` and `scheduled_end` — the start must be strictly before the end — plus a `moderator_volunteer_id`. The referenced moderator must hold the `MODERATOR` capability (`ERR_MODERATOR_NOT_QUALIFIED`), be `ACTIVE` (`ERR_VOLUNTEER_SUSPENDED`), hold a `CURRENT` attestation (`ERR_ATTESTATION_LAPSED`), and be free of the advocacy flag (`ERR_ADVOCACY_SEPARATION`). Two scheduling rules then protect the calendar. Within one jurisdiction, the new forum's half-open interval — inclusive of `scheduled_start`, exclusive of `scheduled_end` — may not overlap any other forum of that jurisdiction in `PLANNED` or `CONFIRMED` status, though two forums may legitimately abut, one ending at exactly the moment the other begins (`ERR_FORUM_TIME_OVERLAP`). And one moderator's commitments must be buffered: between any two forums of the same moderator in `PLANNED` or `CONFIRMED` status, the gap measured from the earlier forum's end to the later forum's start must be at least 24 hours, with a gap of exactly 24 hours allowed (`ERR_MODERATOR_BUFFER_VIOLATION`). A created forum is `PLANNED`, with `eligible_candidate_count` computed at creation as the number of the contest's filings currently `VERIFIED`.

The assigned moderator — and only the assigned moderator, anyone else being rejected with `ERR_UNAUTHORIZED_ROLE` — drives the forum through its lifecycle, and each successful transition increments the forum's `version`. Confirming (`PLANNED` → `CONFIRMED`) recomputes `eligible_candidate_count` at that moment and requires a quorum of at least two eligible candidates, exactly two being sufficient (`ERR_FORUM_QUORUM_NOT_MET`). Marking the forum held (`CONFIRMED` → `HELD`) requires the logical clock to have reached `scheduled_end` (`ERR_FORUM_NOT_CONCLUDED`) and a non-empty `minutes_text` to be supplied (`ERR_INVALID_REQUEST`). The moderator may cancel from either `PLANNED` or `CONFIRMED`, and the system cancels those same states automatically when the moderator is suspended (§3.8); `HELD` and `CANCELLED` are both terminal.

Questions arrive from the public and from the podium. A `PublicUser` submits a question with `question_text` and a `source` of `PUBLIC_SUBMISSION`, leaving `author_volunteer_id` null; the forum's assigned moderator may also submit — either on behalf of a member of the public, again as `PUBLIC_SUBMISSION`, or in the moderator's own voice as `MODERATOR_AUTHORED`, which stamps `author_volunteer_id` with the moderator's `X-User-ID`. Submission is open while the forum is `PLANNED` or `CONFIRMED` and is rejected with `ERR_INVALID_STATE` at any other time; each question records the `forum_id` it was submitted to and is born `SUBMITTED`. Curation happens on the confirmed forum: the assigned moderator selects or rejects questions (`SUBMITTED` → `SELECTED` or `SUBMITTED` → `REJECTED`, both terminal) only while the forum is `CONFIRMED` (`ERR_INVALID_STATE`). Selection carries two further rules — a moderator may never select a `MODERATOR_AUTHORED` question they authored themselves (`ERR_SOD_MODERATOR_OWN_QUESTION`), and a forum may carry at most five `SELECTED` questions, so an attempt to select a sixth is rejected with `ERR_QUESTION_CAP_REACHED`.

### 3.8. Nonpartisanship Incidents and the Compliance Cascade

Any `ChapterCoordinator` may report a policy incident against a volunteer, supplying `volunteer_id`, an `incident_type` of `PARTISAN_STATEMENT`, `ADVOCACY_ROLE_CONFLICT`, `MODERATOR_BIAS`, or `QUESTIONNAIRE_SLANT`, and a free-text `description`; the incident is born `REPORTED` with `resolved_at` null. Adjudication belongs to a `LeagueAdmin`. Dismissal (`REPORTED` → `DISMISSED`) merely stamps `resolved_at` and changes nothing else. Substantiation (`REPORTED` → `SUBSTANTIATED`) requires a non-empty `corrective_action` (`ERR_INVALID_REQUEST`), stamps `resolved_at`, recomputes the volunteer's `substantiated_incident_count`, and then fires the compliance cascade in three links. First, the volunteer moves from `ACTIVE` to the terminal `SUSPENDED`. Second, every ballot measure that volunteer drafted which currently sits in `DRAFTING`, `IN_NEUTRALITY_REVIEW`, or `APPROVED_FOR_GUIDE` is quarantined to `REMANDED`, and every forum that volunteer moderates in `PLANNED` or `CONFIRMED` is cancelled. Third, each contest whose measure was quarantined and which currently sits in `GUIDE_READY` or `LOCKED` reverts to `QUESTIONNAIRE_PHASE`, incrementing that contest's `version`; candidate-race contests are never touched by this cascade. A revert out of `LOCKED` immediately invalidates every edition snapshot that pinned the contest, because the pinned version check of §3.6 will no longer match — any later distribution attempt against such an edition fails with `ERR_STALE_SNAPSHOT`, which is precisely the enforcement point that keeps a quarantined measure out of distributed guides. Both `SUBSTANTIATED` and `DISMISSED` are terminal.

### 3.9. Publishing and Archiving the Cycle

Publishing the cycle (`OPEN` → `PUBLISHED`) is the League's public commitment, so three gates apply, all enforced together: the cycle must contain at least one contest and every contest of the cycle must be `LOCKED` (`ERR_CONTESTS_NOT_LOCKED`); no policy incident involving any volunteer referenced by the cycle's activity may remain `REPORTED` (`ERR_UNRESOLVED_INCIDENTS_EXIST`); and at least one edition must actually have reached the public, meaning `distributed_edition_count` must be at least 1 (`ERR_NO_DISTRIBUTED_EDITION`). A volunteer is referenced by the cycle's activity exactly when a resource of the cycle's tree names them in one of its declared volunteer fields, whatever the resource's current status: as the `drafter_volunteer_id` of a ballot measure beneath one of the cycle's contests, as the `reviewer_volunteer_id` of a neutrality review recorded against such a measure, or as the `moderator_volunteer_id` of a forum beneath one of the cycle's contests. Volunteers who merely operated the pipeline leave no such reference behind them — questionnaires and editions, for instance, record no creator — so a `REPORTED` incident against one of them does not by itself block publishing. Archiving (`PUBLISHED` → `ARCHIVED`) carries no preconditions, and `ARCHIVED` is terminal. As everywhere, each successful cycle transition increments the cycle's `version`.

## 4. Endpoint Definitions

Endpoints that create a new resource respond 201 on success; all other successful operations — reads, lifecycle transitions, and actions — respond 200. Request payloads, derived fields, trigger conditions, and side effects are specified in §2 and §3 rather than repeated here; the table below is a navigational summary only.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/_clock/set_current_utc` | Set the logical clock to a supplied `current_utc` | LeagueAdmin |
| POST | `/election-cycles` | Create an election cycle in `DRAFT` | LeagueAdmin |
| GET | `/election-cycles/{id}` | Read one election cycle | LeagueAdmin, ChapterCoordinator, QuestionnaireEditor |
| POST | `/election-cycles/{id}/transitions` | Cycle lifecycle: `OPEN` from `DRAFT`, `PUBLISHED` from `OPEN` (gated), `ARCHIVED` from `PUBLISHED` | LeagueAdmin |
| POST | `/election-cycles/{id}/jurisdictions` | Create a jurisdiction in the cycle (any cycle status; `fips_code` unique per cycle) | LeagueAdmin |
| GET | `/election-cycles/{id}/jurisdictions` | List jurisdictions of a cycle | LeagueAdmin, ChapterCoordinator, QuestionnaireEditor |
| GET | `/jurisdictions/{id}` | Read one jurisdiction | LeagueAdmin, ChapterCoordinator, QuestionnaireEditor |
| POST | `/jurisdictions/{id}/contests` | Create a contest (candidate race or ballot measure); requires the cycle `OPEN` | ChapterCoordinator |
| GET | `/jurisdictions/{id}/contests` | List contests of a jurisdiction | LeagueAdmin, ChapterCoordinator, QuestionnaireEditor, ForumModerator |
| GET | `/contests/{id}` | Read one contest, including computed `verified_candidate_count` and `completion_index` | LeagueAdmin, ChapterCoordinator, QuestionnaireEditor |
| POST | `/contests/{id}/transitions` | Contest lifecycle with optimistic concurrency: `to` = `QUESTIONNAIRE_PHASE`, `GUIDE_READY`, or `LOCKED` | ChapterCoordinator |
| POST | `/contests/{id}/filings` | Record an official candidate filing (born `FILED`) | ChapterCoordinator |
| GET | `/contests/{id}/filings` | List filings of a contest | LeagueAdmin, ChapterCoordinator, QuestionnaireEditor |
| POST | `/filings/{id}/verify` | Verify a filing; a late verification while the questionnaire is `ISSUED` and in-window creates the `INVITED` shell | ChapterCoordinator |
| POST | `/filings/{id}/withdraw` | Withdraw a filing; cascades its response shell to `WITHDRAWN_HIDDEN` | ChapterCoordinator |
| POST | `/filings/{id}/disqualify` | Disqualify a verified filing (terminal); cascades like withdraw | ChapterCoordinator |
| POST | `/filings/{id}/refile` | Refile a `WITHDRAWN` filing back to `FILED` (deadline-gated); restores a hidden shell to `INVITED` | ChapterCoordinator |
| POST | `/contests/{id}/questionnaire` | Create the contest's questionnaire in `DRAFT` | QuestionnaireEditor |
| GET | `/contests/{id}/questionnaire` | Fetch the contest's questionnaire (array of 0 or 1) | LeagueAdmin, ChapterCoordinator, QuestionnaireEditor |
| GET | `/questionnaires/{id}` | Read one questionnaire with counters and version | LeagueAdmin, ChapterCoordinator, QuestionnaireEditor |
| POST | `/questionnaires/{id}/amend` | Amend `due_at` and/or `questions` with optimistic concurrency; allowed in `DRAFT` and `ISSUED` | QuestionnaireEditor |
| POST | `/questionnaires/{id}/issue` | Issue the questionnaire, creating `INVITED` shells for all `VERIFIED` filings of the contest | QuestionnaireEditor |
| POST | `/questionnaires/{id}/close` | Close submissions (requires the clock past `due_at`) | QuestionnaireEditor |
| POST | `/questionnaires/{id}/pin` | Pin the closed questionnaire as the guide snapshot source | QuestionnaireEditor |
| POST | `/questionnaires/{id}/responses` | Candidate submits answers against their own shell; over-limit answers land in `OVER_LIMIT_RETURNED`, not an error | Candidate |
| GET | `/questionnaires/{id}/responses` | List response shells of a questionnaire | LeagueAdmin, ChapterCoordinator, QuestionnaireEditor |
| POST | `/responses/{id}/resubmit` | Candidate resubmits from `OVER_LIMIT_RETURNED` | Candidate |
| POST | `/contests/{id}/sweep-nonresponses` | Mark `INVITED` shells `NONRESPONSE_MARKED` and `OVER_LIMIT_RETURNED` shells `LATE_UNPUBLISHED` | ChapterCoordinator |
| POST | `/contests/{id}/measure` | Create the contest's ballot measure; the acting editor becomes the drafter | QuestionnaireEditor |
| GET | `/contests/{id}/measure` | Fetch the contest's measure (array of 0 or 1) | LeagueAdmin, ChapterCoordinator, QuestionnaireEditor, NeutralityReviewer |
| GET | `/measures/{id}` | Read one ballot measure with computed grades and balance fields | LeagueAdmin, QuestionnaireEditor, NeutralityReviewer |
| POST | `/measures/{id}/revise` | Drafter edits `explanation_text` (from `DRAFTING` or `REMANDED`) | QuestionnaireEditor |
| POST | `/measures/{id}/arguments` | Add a `PRO` or `CON` argument; auto-accepted at most 250 words | QuestionnaireEditor |
| GET | `/measures/{id}/arguments` | List arguments of a measure | LeagueAdmin, QuestionnaireEditor, NeutralityReviewer |
| POST | `/measures/{id}/submit-for-review` | Drafter submits the measure for neutrality review (requires an accepted argument on each side) | QuestionnaireEditor |
| POST | `/measures/{id}/reviews` | Reviewer records a verdict; `NEUTRAL` approves, `LOADED_LANGUAGE`/`UNBALANCED` remands | NeutralityReviewer |
| GET | `/measures/{id}/reviews` | List reviews of a measure | LeagueAdmin, QuestionnaireEditor, NeutralityReviewer |
| POST | `/election-cycles/{id}/guide-editions` | Create a guide edition (language, channel, accessibility format) in `ASSEMBLING` | QuestionnaireEditor |
| GET | `/election-cycles/{id}/guide-editions` | List editions of a cycle | LeagueAdmin, QuestionnaireEditor |
| GET | `/guide-editions/{id}` | Read one guide edition with snapshot and allocation fields | LeagueAdmin, QuestionnaireEditor |
| POST | `/guide-editions/{id}/transitions` | Edition lifecycle: `to` = `READY` (pins the snapshot, computes pages; gated), `ASSEMBLING` (re-open from `READY`), or `RETIRED` (from `DISTRIBUTED`) | QuestionnaireEditor |
| POST | `/guide-editions/{id}/distribute` | Distribute a `READY` edition; runs the print-copy allocation over `channel_requests` | QuestionnaireEditor |
| POST | `/contests/{id}/forums` | Schedule a candidate forum; moderator eligibility, jurisdiction overlap, and moderator buffer enforced | ChapterCoordinator |
| GET | `/contests/{id}/forums` | List forums of a contest | LeagueAdmin, ChapterCoordinator, QuestionnaireEditor, ForumModerator |
| GET | `/forums/{id}` | Read one forum | LeagueAdmin, ChapterCoordinator, ForumModerator |
| POST | `/forums/{id}/transitions` | Forum lifecycle by the assigned moderator: `to` = `CONFIRMED` (quorum-gated), `HELD` (requires `minutes_text` and the clock past `scheduled_end`), or `CANCELLED` | ForumModerator |
| POST | `/forums/{id}/questions` | Submit a forum question (`PUBLIC_SUBMISSION` or `MODERATOR_AUTHORED`) | PublicUser, ForumModerator |
| GET | `/forums/{id}/questions` | List questions of a forum | LeagueAdmin, ChapterCoordinator, ForumModerator, PublicUser |
| POST | `/forum-questions/{id}/select` | Moderator selects a submitted question (at most five per forum; never one's own) | ForumModerator |
| POST | `/forum-questions/{id}/reject` | Moderator rejects a submitted question | ForumModerator |
| POST | `/volunteers` | Register a volunteer (`ACTIVE`, attestation `CURRENT` for ninety days) | LeagueAdmin |
| GET | `/volunteers/{id}` | Read one volunteer (attestation lazily evaluated against the logical clock) | LeagueAdmin, ChapterCoordinator, QuestionnaireEditor, NeutralityReviewer, ForumModerator |
| POST | `/volunteers/{id}/attest` | Renew the caller's own nonpartisanship attestation | ChapterCoordinator, QuestionnaireEditor, NeutralityReviewer, ForumModerator |
| POST | `/volunteers/{id}/flag-advocacy` | Set or clear a volunteer's advocacy flag | LeagueAdmin |
| POST | `/incidents` | Report a nonpartisanship policy incident against a volunteer | ChapterCoordinator |
| GET | `/volunteers/{id}/incidents` | List incidents filed against a volunteer | LeagueAdmin, ChapterCoordinator |
| POST | `/incidents/{id}/transitions` | Resolve an incident: `to` = `SUBSTANTIATED` (requires `corrective_action`; fires the compliance cascade) or `DISMISSED` | LeagueAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in §2 and §3; this table is a reference index only.

| Error ID | HTTP Status Code |
|---|---|
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED_ROLE` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_CYCLE_NOT_OPEN` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_QUESTIONNAIRE_NOT_ACCEPTING_SUBMISSIONS` | 409 |
| `ERR_FILING_NOT_VERIFIED` | 409 |
| `ERR_QUESTIONNAIRE_NOT_PINNED` | 422 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_VOLUNTEER_SUSPENDED` | 403 |
| `ERR_ATTESTATION_LAPSED` | 403 |
| `ERR_ADVOCACY_SEPARATION` | 403 |
| `ERR_MODERATOR_NOT_QUALIFIED` | 422 |
| `ERR_SOD_DRAFTER_CANNOT_REVIEW` | 403 |
| `ERR_SOD_MODERATOR_OWN_QUESTION` | 403 |
| `ERR_ONLY_DRAFTER_MAY_REVISE` | 403 |
| `ERR_NEUTRALITY_REVIEW_OUTSTANDING` | 422 |
| `ERR_FILING_DEADLINE_PASSED` | 422 |
| `ERR_FILING_STILL_OPEN` | 422 |
| `ERR_SUBMISSION_WINDOW_CLOSED` | 422 |
| `ERR_CLOSE_BEFORE_DEADLINE` | 422 |
| `ERR_FORUM_TIME_OVERLAP` | 422 |
| `ERR_MODERATOR_BUFFER_VIOLATION` | 422 |
| `ERR_FORUM_NOT_CONCLUDED` | 422 |
| `ERR_DUPLICATE_FIPS` | 409 |
| `ERR_DUPLICATE_FILING_REFERENCE` | 409 |
| `ERR_DUPLICATE_QUESTIONNAIRE` | 409 |
| `ERR_DUPLICATE_MEASURE` | 409 |
| `ERR_DUPLICATE_REVIEW_THIS_ROUND` | 409 |
| `ERR_CONTEST_KIND_MISMATCH` | 422 |
| `ERR_MISSING_PRO_OR_CON` | 422 |
| `ERR_FORUM_QUORUM_NOT_MET` | 422 |
| `ERR_QUESTION_CAP_REACHED` | 422 |
| `ERR_LANGUAGE_UNSUPPORTED` | 422 |
| `ERR_ACCESSIBILITY_GRADE_EXCEEDED` | 422 |
| `ERR_STALE_SNAPSHOT` | 422 |
| `ERR_CONTESTS_NOT_LOCKED` | 422 |
| `ERR_UNRESOLVED_INCIDENTS_EXIST` | 422 |
| `ERR_NO_DISTRIBUTED_EDITION` | 422 |
