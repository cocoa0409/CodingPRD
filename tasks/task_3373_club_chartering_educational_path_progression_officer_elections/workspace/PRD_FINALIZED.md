# Club Chartering Path Progression API — Product Requirements Document

## 1. Introduction

This document specifies the product requirements for the Club Chartering Path Progression API, the system of record for a Toastmasters-style district organization. It governs the complete institutional lifecycle of a club: the petition filed by a sponsoring club, the organizing meeting that must be held and attended before anything else can proceed, the roster of dues-paid members that must exist before a charter can be granted, and the suspension, reinstatement and revocation that may follow. Running underneath that institutional lifecycle is a semiannual dues cycle that invoices every member, prorates for mid-cycle joiners, charges reinstatement and late fees where they are owed, and re-derives each club's standing whenever it closes.

Layered on top of the club are the three programs that make the organization work. Members advance through five-level educational paths gated by approved speech and project completions, and a retroactive return of a supporting completion walks a level back down. Clubs run meetings with rotating functional and speaking roles, elect officers who must be trained within a deadline, and run speech contests whose winners climb from club level to area level under eligibility and judging protocols. Area and division directors record governance visits and work a ranked queue of struggling clubs.

The API is a single REST surface mounted under `/toastmasters`. Every resource is addressed by an opaque server-minted identifier, every mutation is versioned so a stale client cannot overwrite a change it has not observed, and every derived figure on a club — the dues counters, the recognition points, the composite standing score and the posture that follows from it — is recomputed by the server rather than supplied by the caller.

## 2. Global Specifications & System-Wide Principles

This section states the rules that apply across the whole surface: who may call what, how responses are shaped, how collections are paged, how the dues clock and the derived club posture behave, how money is rounded, and in what order the server evaluates its checks.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` identifies the acting principal and `X-User-Role` declares their capacity. The system recognizes exactly four roles, spelled `WorldHeadquarters`, `ClubOfficer`, `Member` and `DistrictDirector`. A request that omits either header, or that names a role outside that set, is rejected with `ERR_UNAUTHENTICATED`. A request whose declared role is not listed on the endpoint it targets, or that fails the ownership clause attached to that role, is rejected with `ERR_UNAUTHORIZED`.

The identity carried by `X-User-ID` means different things for different roles. When `X-User-Role` is `WorldHeadquarters`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it where a transition writes an actor, but it is never compared to any entity's `id`, and headquarters staff act across the whole organization without an ownership check. When `X-User-Role` is `ClubOfficer`, `X-User-ID` is the `id` of the acting `Membership`; ownership checks on any resource that references a `Membership` compare the resource's foreign-key field to `X-User-ID`, which in practice means the acting membership's `club_id` must equal the club targeted by the operation, and club-scoped writes are refused for a membership of any other club. When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member`; ownership checks compare the resource's member foreign key — `member_id`, `evaluator_member_id` or the member named by a path's `membership_id` — to `X-User-ID`. When `X-User-Role` is `DistrictDirector`, `X-User-ID` is likewise the `id` of the acting `Member`, and two additional clauses apply on top of that identity: recording officer training requires that `X-User-ID` differs from the `member_id` of the term being trained, and completing a governance visit requires that `X-User-ID` equals that visit's `director_member_id`.

Role assignment across the surface follows a hierarchical-override model. `WorldHeadquarters` alone may create an organizing club, grant or reinstate a charter, and close a dues cycle. `ClubOfficer` owns the operational club surface: enrolling members into their own club, paying or refunding dues, approving or returning completions, scheduling and closing meetings, assigning and releasing roles, and nominating and electing officers. `Member` owns the personal progression surface: enrolling in an education path, advancing a level, logging a completion, recording the evaluation they wrote, entering a contest, and paying dues on their own membership. `DistrictDirector` owns the district surface: recording officer training, creating and completing contests, recording judge ballots, scheduling and completing governance visits, and reading the coaching queue. Every authenticated role may read the list and single-resource endpoints.

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

Collection reads accept `limit` and `offset` as query parameters. `limit` is the maximum number of items returned; when omitted it defaults to 10, and it must lie between 1 and 100 inclusive. `offset` is the number of items to skip and defaults to 0. Every list endpoint returns its resources sorted by creation timestamp in ascending order unless a rule elsewhere in this document defines a ranked ordering for a specific collection.

Paginated responses carry `limit`, `offset`, `total_count` and `has_more` in the `meta` object of the envelope. `total_count` is the number of items matching the filter before paging, and `has_more` reports whether further items remain beyond the returned window. The coaching queue read accepts only `limit` and returns its candidates best-first under the ranking defined in §3.9; it is not offset-paged.

### 2.4. Common Resource Properties and Record Identity

All eleven primary resources — clubs, members, memberships, education paths, project completions, meetings, role assignments, officer terms, contests, contest entries and area visits — carry the same four system-managed properties. Every one of them has an `id`, which is a unique server-minted UUID with no type prefix and is the only way the resource is addressed. Every one has a `created_at` timestamp recording when the row was first written, and an `updated_at` timestamp recording when it was last modified; both are ISO 8601 UTC timestamps rendered with three fractional digits, for example `2025-05-24T10:30:00.123Z`. Every one has a `version` integer that starts at its creation value and increments by one on each modification of that resource.

The `updated_at` and `version` properties are not decorative. Any server-side recomputation of a derived field is a mutation of the resource that owns that field, so it refreshes `updated_at` and increments `version` exactly as a caller-driven edit would. A resource's `version` is bumped at most once by any single request: when one request both recomputes a resource's derived fields and writes to that same resource, those two count as one modification, not two. A club whose counters are refreshed because a meeting was closed therefore reports a newer `version` than it did before the meeting was closed, and a client holding the older value will be told its view is stale the next time it writes against that club. None of the eleven resources is immutable after creation, so none of them omits `updated_at` or `version`.

### 2.5. The Semiannual Dues Cycle Clock

Dues are billed on a semiannual cycle, and the club is the clock. A club carries `dues_cycle_index`, a counter that begins at 0 when the club row is created and increases by exactly one every time a dues cycle is closed. It carries `cycle_opened_at`, the instant the current cycle opened, which is supplied when the club is created and refreshed on every close; and `cycle_closed_at`, the instant of the most recent close, which is null before the first close ever runs.

The midpoint that drives dues proration is derived from the open of the cycle: a membership whose `join_date` falls at or after `cycle_opened_at` plus 91 days has joined in the second half of the cycle and is prorated accordingly. The cycle index is also the yardstick for payment: `dues_paid_through_cycle` on a membership records the highest cycle index that has been fully paid, and starts at minus one when no dues have ever been paid at all.

Several club counters are scoped to the cycle rather than to all time, and they are recomputed as the cycle's activity changes: `meetings_held_this_cycle`, `approved_level_completions_this_cycle`, `contest_participation_count`, `new_member_count_this_cycle`, and the derived `dcp_recognition_points` and `dcp_tier`. One further property, `cycle_open_standing`, is a snapshot of the club's `good_standing` taken when the current dues cycle opened; it is written when a cycle closes and when a charter is granted, and it is consumed by the recognition-point calculation described in §2.7.

### 2.6. Charter Standing and Posture Reconciliation

A club's institutional standing is `charter_status`, which takes exactly one of four values: `ORGANIZING`, `CHARTERED`, `SUSPENDED` and `REVOKED`. A newly created club is always `ORGANIZING`. Granting a charter moves a club from `ORGANIZING` to `CHARTERED`; reinstating one moves it from `SUSPENDED` to `CHARTERED`; a club that fails its cycle review moves from `CHARTERED` to `SUSPENDED`, and a club that fails badly enough moves from either `CHARTERED` or `SUSPENDED` to `REVOKED`. `REVOKED` is terminal — no transition leaves it. When a charter is granted or reinstated, `charter_date` is set to the request timestamp and the club's current `good_standing` is copied into `cycle_open_standing`; while a club is `ORGANIZING` its `charter_date` is null.

Standing posture is a second, independent dimension called `good_standing`, with the values `GOOD`, `PROBATION` and `NOT_IN_GOOD_STANDING`. Posture is never supplied by a caller and is never flipped by an ordinary in-cycle mutation. It is re-derived from `good_standing_score` in exactly two situations: when a dues cycle closes, and at the moment a charter is granted, where it is forced to `GOOD`. Outside those two situations a club keeps whatever posture it was last assigned, even while its score changes underneath it.

The club also carries a coaching posture, `coaching_status`, one of `NONE`, `FLAGGED`, `ASSIGNED` or `COACHED`, and a family of server-computed counters that feed the score: `paid_member_count` (memberships whose `dues_paid_through_cycle` is at least the club's `dues_cycle_index`), `total_member_count` (memberships in status `PENDING` or `ACTIVE`), `new_member_count_this_cycle` (memberships whose first paid cycle equals the current `dues_cycle_index`), `officer_trained_count` (officer terms for the current `term_index` in status `TRAINED` or `COMPLETED`), `meetings_held_this_cycle`, `approved_level_completions_this_cycle` (approved completions at this club in the current cycle whose level equals the member's current path level), and `contest_participation_count` (this cycle's contest entries whose `contest_level` is `CLUB`). All of these, plus `good_standing_score`, are recomputed on every membership, officer, education, meeting and cycle mutation. The four roster counters — `paid_member_count`, `total_member_count`, `new_member_count_this_cycle` and `officer_trained_count` — are defined purely by the rows' current status and cycle pointers, with no creation window of their own: a membership or officer term that was created before `cycle_opened_at` still counts toward them, and only the cycle-close variant's `cycle_closed_at` cap described in §2.7 can exclude a row from them. The cycle-activity counters among them — `meetings_held_this_cycle`, `approved_level_completions_this_cycle` and `contest_participation_count` — are the ones anchored to the cycle window, counting only rows created at or after `cycle_opened_at`.

### 2.7. Recognition Points and the Composite Good-Standing Score

A club's `good_standing_score` is an integer between 0 and 100 assembled from five weighted components. The dues component is the smaller of 30 and the whole-number part of thirty multiplied by `paid_member_count` and divided by twenty. The officer component is the smaller of 25 and the whole-number part of twenty-five multiplied by `officer_trained_count` and divided by four. The education component is the smaller of 20 and the whole-number part of twenty multiplied by `approved_level_completions_this_cycle` and divided by four. The meeting component is the smaller of 15 and the whole-number part of fifteen multiplied by `meetings_held_this_cycle` and divided by six. The recognition component is the smaller of 10 and the whole-number part of ten multiplied by `dcp_recognition_points` and divided by five. The score is the sum of those five capped integers, and each component is truncated to a whole number before the sum is taken, so the score itself is always a whole number.

Posture follows from the score in bands: a score of at least 80 places the club in `GOOD`; a score from 60 through 79 inclusive places it in `PROBATION`; a score strictly below 60 places it in `NOT_IN_GOOD_STANDING`. The thresholds that govern a charter's survival are separate and stricter: a score strictly below 60 suspends a `CHARTERED` club, and a score strictly below 40 revokes a club that is `CHARTERED` or `SUSPENDED`.

A club's recognition points, `dcp_recognition_points`, are a separate ten-point aggregate assembled from four sources, and they are evaluated before the standing score and independently of it. The education component sums, over the club's memberships in status `ACTIVE`, the number of that membership's approved completions at this club in the current cycle, counting at most 2 per membership, and caps the resulting total at 6. The membership component is the sum of two capped halves: 1 point when the whole-number part of `new_member_count_this_cycle` divided by four is at least 1, plus 1 point when the whole-number part of `paid_member_count` divided by twenty is at least 1. The training component is 1 point when the whole-number part of `officer_trained_count` divided by four is at least 1, and 0 otherwise. The administrative component sums three separate awards of 1 point each: one when `officer_trained_count` is exactly 7 — a full slate of trained officers — one when `contest_participation_count` is at least 1, and one when the club's `cycle_open_standing` snapshot is `GOOD`. The club's recognition points are those four components added together and capped at 10.

The recognition tier follows from the points. A club with at least 9 points is `PRESIDENT_DISTINGUISHED`; 7 or 8 points is `SELECT_DISTINGUISHED`; 5 or 6 points is `DISTINGUISHED`; and fewer than 5 points is `NONE`. Like the standing score, the recognition points have a live variant and a cycle-close variant. The live variant is recomputed on any mutation that changes `paid_member_count`, `new_member_count_this_cycle`, `officer_trained_count`, `approved_level_completions_this_cycle` or `contest_participation_count`, and its administrative component reads `cycle_open_standing` only — never the club's live posture. The cycle-close variant is frozen for the closing cycle and reported on the club until the next close.

Two ordering rules are pinned. First, `dcp_recognition_points` is always evaluated before `good_standing_score`, and it uses the `cycle_open_standing` snapshot captured when the cycle opened rather than the live posture; the score is then computed from those points, and the score computed in a cycle never feeds back into that same cycle's recognition points. Second, the score has two variants. The live variant is recomputed on any mutation inside an open cycle and counts every current row. The cycle-close variant is recomputed while a cycle is being closed and counts only rows created at or before `cycle_closed_at`; the posture it derives is then snapshotted into `cycle_open_standing` for the cycle that follows.

### 2.8. Optimistic Concurrency Control

Four write operations carry a mandatory version field so that a client cannot act on a view of a parent resource that has already moved. Scheduling a meeting requires `expected_club_version`, which must equal the target club's current `version`. Enrolling a membership in an education path requires `expected_membership_version`, which must equal the target membership's current `version`. Logging a project completion requires `expected_education_path_version`, which must equal the target path's current `version`. Adding a role assignment requires `expected_meeting_version`, which must equal the target meeting's current `version`.

In every one of those four cases the field is a required part of the request; when the supplied value differs from the parent entity's current `version`, the write is rejected with `ERR_STALE_VERSION`. The rejection is a stale-read rejection, not a scheduling conflict: a second meeting at the same club, a second completion on the same path, a second assignment on the same meeting and a second education path for the same membership are each legitimate on their own terms, and are refused only because the client's view of the parent is out of date. Advancement of an education path likewise requires `expected_education_path_version` to equal the path's current `version`, and is rejected with `ERR_STALE_VERSION` when it does not. No other endpoint accepts a version field, and no other endpoint performs this check.

### 2.9. Monetary Precision and Rounding

All money in this system is held in whole cents and every monetary field is an integer count of cents: `club_dues_cents` on a club, and `quoted_total_cents` on a membership. There are no fractional-cent balances anywhere in the model.

Intermediate lines of a dues quote are not whole numbers, because a percentage levy is applied to them. Each such line is rounded to two decimal places — that is, to the nearest cent — using round half up, where a value sitting exactly halfway between two cents rounds upward, and the rounding is applied line by line before any addition takes place. The rounded lines are then summed, and that sum is itself rounded to two decimal places with round half up. Rounding once at the end, after summing unrounded lines, produces a different and incorrect total; the difference is small but real, and it is observable. The pinned per-line order is what the system implements.

### 2.10. Validation Precedence and Referential Integrity

Checks are evaluated in a fixed order, and the first check that fails determines the response. A request whose payload is structurally invalid — a required field missing, a field of the wrong type, an enum value outside its declared set, or a judge score outside the range 0 through 100 inclusive — is rejected with `ERR_INVALID_REQUEST` before any business rule is consulted.

Once the payload is well formed, the checks run in this order. First, authentication: both headers must be present and the role must be one of the four declared roles, otherwise `ERR_UNAUTHENTICATED`. Second, authorization: the acting role must be listed on the endpoint, and for the entity-backed roles the ownership clause must hold, otherwise `ERR_UNAUTHORIZED`. This pair applies to all endpoints for authentication and to all mutating endpoints and all club-scoped reads for authorization. Third, the resource named in the path must exist, otherwise `ERR_NOT_FOUND`; this applies to every endpoint whose path contains an `id`. Fourth, every entity referenced by the payload must exist, and the references are resolved left to right in path order and then in body field order, with the same `ERR_NOT_FOUND`; this applies to the club, membership, education-path, project-completion, meeting, role-assignment, officer-term, contest, contest-entry and area-visit creation endpoints. Fifth, the optimistic-concurrency field must match the parent's current version, otherwise `ERR_STALE_VERSION`; this applies to meeting creation, education-path creation, project-completion creation and role-assignment creation. Sixth, the target resource must be in a status that admits the requested transition, otherwise `ERR_INVALID_STATE`; this covers dues renewal, dues refund, meeting close, completion evaluation, completion review, role release, officer election, officer training and governance-visit completion, and the statuses it demands are these: a refund requires `PAID`, a close requires `SCHEDULED`, an evaluation requires `LOGGED` or `RETURNED`, a review requires `EVALUATED` or `APPROVED`, a release requires `ASSIGNED`, an election requires `NOMINATED`, a training record requires `ELECTED`, and a visit completion requires `SCHEDULED`.

Seventh, no conflicting resource of the same kind may already exist, otherwise one of `ERR_DUPLICATE_PATH_ENROLLMENT`, `ERR_DUPLICATE_ASSIGNMENT`, `ERR_DUPLICATE_BALLOT` or `ERR_OFFICE_ALREADY_FILLED` is returned; this covers a duplicate path enrollment, a duplicate role assignment, a duplicate ballot and a doubly-filled office. Eighth, a candidate meeting may not intersect, or begin inside the thirty-minute buffer of, another meeting of the same club, otherwise `ERR_MEETING_OVERLAP`. Ninth, a speech role assignment may not push the member past the rolling window limit, otherwise `ERR_ROLE_WINDOW_EXCEEDED`.

Tenth, the charter prerequisites are checked, and they fail with `ERR_ORGANIZING_MEETING_REQUIRED`, `ERR_CHARTER_MINIMUM_NOT_MET`, `ERR_CORPORATE_SPONSOR_REQUIRED` or `ERR_SPONSOR_NOT_IN_GOOD_STANDING`. Eleventh, the level requirement table must be satisfied for advancement, otherwise `ERR_LEVEL_REQUIREMENTS_NOT_MET`. Twelfth, evaluator and judge independence must hold, otherwise `ERR_EVALUATOR_CONFLICT` or `ERR_JUDGE_CONFLICT`. Thirteenth, the contest protocol and the meeting quorum rule are enforced, failing with `ERR_CONTEST_NOT_OPEN` or `ERR_QUORUM_NOT_MET`. Fourteenth, the seven-slot capacity of a meeting is enforced, failing with `ERR_ROLE_SLOTS_FULL`. Fifteenth, the election protocol is enforced, failing with `ERR_ELECTION_QUORUM_NOT_MET`.

Sixteenth, dues payment admissibility is checked — an already-paid or voided invoice is refused, and a club that is not in a state that admits the payment is refused — failing with `ERR_DUES_ALREADY_PAID`, `ERR_CLUB_NOT_CHARTERED` or `ERR_CLUB_REVOKED`. Seventeenth, the club's posture must be `GOOD` for contest entry and for level advancement, otherwise `ERR_CLUB_NOT_IN_GOOD_STANDING`. Eighteenth, the membership must be `ACTIVE` and paid through the club's current cycle, otherwise `ERR_MEMBERSHIP_NOT_ACTIVE`. Nineteenth and last, the coaching queue must be non-empty when a district director asks for the next club to coach, otherwise `ERR_NO_COACHING_CANDIDATES`.

### 2.11. Cascade Discipline Across Aggregates

State does not live in isolation here. When a parent resource loses the condition that made its children viable, the server resolves those children in the same operation rather than leaving them dangling. A membership that lapses suspends that member's education paths, disqualifies the contest entries those paths were supporting, and vacates the member's officer terms. A club that is suspended or revoked lapses its memberships and vacates its officers; every membership it lapses this way has its `dues_status` set to `OVERDUE`, whatever that field held before. A path whose level drops disqualifies the contest entries the member had entered through that club. A meeting closed as held resolves every one of its outstanding role assignments to a final outcome.

Every one of these cascades is part of the same atomic operation as the change that triggered it, and every resource touched by a cascade is itself mutated — its `updated_at` is refreshed and its `version` is incremented — so the client that reads the child afterwards sees a version it has not observed before. Cascade effects never propagate back up to re-trigger the change that caused them; the server recomputes the affected derived counters once, from the state left behind by the cascade.

## 3. Business Logic & Workflows

### 3.1. Petitioning and Chartering a Club

A club begins as a petition. A `WorldHeadquarters` operator creates it by supplying its `club_name`, its `club_type` — one of `COMMUNITY`, `CORPORATE`, `CAMPUS` or `ADVANCED` — its `district_number`, `division_code` and `area_code`, the `venue_name` at which it intends to meet, its per-cycle `club_dues_cents`, and the `cycle_opened_at` instant at which its first dues cycle opens. Two optional fields describe how it came to be: `sponsor_club_id` names a mentoring club that will carry it while it is `ORGANIZING`, and `corporate_sponsor_name` names the employer behind a corporate club. Two more describe the organizing meeting itself: `organizing_meeting_at` and `organizing_meeting_attendees`, both of which stay empty until that meeting is actually held.

The newly created club is `ORGANIZING`, with `good_standing` and `cycle_open_standing` both `GOOD`, `dues_cycle_index` 0, `cycle_closed_at` null and `coaching_status` `NONE`. Its `good_standing_score` is 0 at this point, its `dcp_recognition_points` is 0 and its `dcp_tier` is `NONE`: no membership, officer, meeting or completion rows exist yet, and a newly created club is written with every derived counter zeroed rather than run through the §2.7 formulas, even though its `cycle_open_standing` snapshot is already `GOOD`. A `CORPORATE` club must carry a `corporate_sponsor_name`; for the other three types the field stays null.

Chartering is a `WorldHeadquarters` decision, and it is gated. The organizing meeting must have been held — `organizing_meeting_at` must be set — and at least 3 prospective members must have attended it, that is `organizing_meeting_attendees` must be at least 3; a petition that arrives before that meeting has happened is refused with `ERR_ORGANIZING_MEETING_REQUIRED`. The roster must be real: `paid_member_count` must be at least 20 dues-paid memberships, and a petition that falls short is refused with `ERR_CHARTER_MINIMUM_NOT_MET`. A corporate club with no `corporate_sponsor_name` is refused with `ERR_CORPORATE_SPONSOR_REQUIRED`. And when the petition names a `sponsor_club_id`, that sponsor must itself be `CHARTERED` with `good_standing` `GOOD`; a sponsor that is suspended, revoked, on probation or otherwise not in good standing produces `ERR_SPONSOR_NOT_IN_GOOD_STANDING`.

Sponsorship carries an obligation in the other direction. A club whose posture is `PROBATION` cannot sponsor: while it sits there, any charter request naming it as the sponsor is blocked, and the block lifts only when the club returns to `GOOD`. The same refusal applies to a club in `NOT_IN_GOOD_STANDING`, since such a club is not `GOOD` either.

Granting a charter moves the club from `ORGANIZING` to `CHARTERED` in one atomic operation. `charter_date` is stamped with the request timestamp, `cycle_open_standing` is set to the club's current `good_standing`, and the roster is activated: every membership of that club that is `PENDING` with `dues_status` `PAID` becomes `ACTIVE`. Each membership that is thereby activated has its education paths at that club lifted from `SUSPENDED` back to `ACTIVE`. The club's `paid_member_count`, `total_member_count` and `good_standing_score` are recomputed, and the club's `version` increments.

Reinstatement is the same act performed on a suspended club, with its own gate. A `SUSPENDED` club returns to `CHARTERED` when `paid_member_count` is at least 20 and `good_standing_score` is at least 60; it does not re-hold an organizing meeting and its sponsor is not re-examined. On reinstatement `charter_date` is stamped with the request timestamp, `cycle_open_standing` is set to the current `good_standing`, every membership of the club in status `LAPSED` becomes `ACTIVE`, each reactivated membership's education paths move from `SUSPENDED` to `ACTIVE`, the club's counters and score are recomputed, and the club's `version` increments.

The reverse direction is automatic rather than requested. When a cycle closes and the club's recomputed score is strictly below 60, a `CHARTERED` club moves to `SUSPENDED`; when it is strictly below 40, a club that is `CHARTERED` or `SUSPENDED` moves to `REVOKED`, which is terminal. Both of those transitions are part of the cycle-close sequence described in §3.2.

### 3.2. The Dues Cycle, Invoices and Cycle Close

Every invoice in the system is produced by a single dues quote, and the order in which that quote is assembled matters to the cent, so it is worth stating in full. The international dues line is 4500 cents increased by the district levy of 7.5 percent, that is, 4500 multiplied by 1.075. The club dues line is the club's `club_dues_cents` increased by the same 7.5 percent levy. When the membership's `join_date` falls on or after the moment the cycle opened plus 91 days, both of those lines are halved, because the member is joining for the second half of the cycle only. The new-member line is 2000 cents when the membership is flagged `first_time_member` and its `dues_paid_through_cycle` is minus one — the member has never paid dues at any club — and is 0 otherwise. The reinstatement line is 1000 cents when the membership's status is `LAPSED` and 0 otherwise. The late line is 0 unless the membership's `dues_status` is `OVERDUE`, in which case it is 5 percent of the sum of the four lines already described — international, club, new-member and reinstatement, each taken before any rounding.

Rounding is then applied in a pinned order. Each of the five lines — international, club, new-member, reinstatement and late — is individually rounded to two decimal places, that is to the nearest cent, using round half up, and only then are the five rounded values summed. That sum is the quote total. Summing the raw lines first and rounding once at the end is a different and incorrect result: for a club whose `club_dues_cents` is 2999 and a first-time member who has never paid, the pinned per-line order yields 10062 cents, while summing the unrounded lines and rounding once yields 10061.

Two variants of the quote exist. The renewal quote applies while the membership's status is `PENDING` or `ACTIVE`, and its reinstatement line is 0. The reinstatement quote applies while the membership's status is `LAPSED`; its reinstatement line is 1000 cents, and its new-member line is forced to 0 even when `first_time_member` is true and `dues_paid_through_cycle` is minus one. A quote is recomputed and returned whenever a renewal is paid, and it is recomputed when a cycle closes and the next invoice is issued.

Closing a dues cycle is a `WorldHeadquarters` operation that accepts an optional `cycle_opened_at` and an optional `cycle_closed_at`, and it proceeds in five ordered steps.

Step one sweeps the closing cycle. Every membership whose `dues_paid_through_cycle` is below the club's `dues_cycle_index` — evaluated before the index moves — is resolved: an invoice still in `ISSUED` becomes `OVERDUE`, and a membership still in `ACTIVE` becomes `LAPSED`. Each membership that lapses drags its dependents with it: its education paths move from `ACTIVE` to `SUSPENDED`, each of those suspended paths' contest entries are disqualified, and each of that membership's officer terms in status `NOMINATED`, `ELECTED` or `TRAINED` is vacated.

Step two recomputes `dcp_recognition_points` with the cycle-close variant, from the state step one left behind and against the `cycle_open_standing` snapshot.

Step three recomputes `good_standing_score` from those points and re-derives `good_standing` from the score, moving the club between the three postures according to the bands in §2.7: a club in `GOOD` whose score lands in the 60-through-79 band moves to `PROBATION`; a club in `PROBATION` returns to `GOOD` when its score reaches at least 80 and falls to `NOT_IN_GOOD_STANDING` when its score drops strictly below 60; a club in `NOT_IN_GOOD_STANDING` moves back to `PROBATION` when its score is in the 60-through-79 band and to `GOOD` when its score reaches at least 80. For a club whose `charter_status` is `CHARTERED` or `SUSPENDED`, a score strictly below 60 moves `CHARTERED` to `SUSPENDED`, and a score strictly below 40 moves either `CHARTERED` or `SUSPENDED` to `REVOKED`; both of those evaluations happen here, before the cycle index advances. A club still in `ORGANIZING` keeps its `charter_status` through the close — a low score neither suspends nor revokes a club that has not yet been chartered.

Step four advances the clock. `dues_cycle_index` increments by one; `cycle_opened_at` becomes the supplied `cycle_opened_at`, or the request timestamp when that is omitted; and `cycle_open_standing` becomes the `good_standing` derived in step three. The next invoice is then issued to every membership still in status `PENDING` or `ACTIVE`: a membership whose `dues_status` was `PAID` or `VOID` moves to `ISSUED`, and the applicable quote total for the new cycle is stored in its `quoted_total_cents`.

Step five ages the term and the governance schedule. Every officer term whose `term_index` is below the new cycle index becomes `COMPLETED`, and each such completion clears the member's `officer_role` to `NONE`. Every scheduled area visit whose `scheduled_at` is before `cycle_closed_at` becomes `MISSED`. Finally, a club whose newly derived `good_standing` is `PROBATION` or `NOT_IN_GOOD_STANDING` and whose `coaching_status` is still `NONE` has its `coaching_status` set to `FLAGGED`.

The club's `version` increments once for the whole close. The counters step two recomputed are the ones the club reports when the close returns; the close does not recompute the club a second time against the cycle it has just opened.

### 3.3. Membership Enrollment and Dues Payment

Enrolling a person into a club is a `ClubOfficer` or `WorldHeadquarters` act. The payload names the `club_id`, the `join_date`, and whether the person is a `first_time_member`, and it may carry an existing `member_id`, or the person's `full_name`, `email` and `home_area_code`. The member row is reused rather than duplicated: when `member_id` matches an existing member, or when `email` matches one, that member is enrolled again; only when neither matches is a new member row created, stamped with `member_since` at the moment of creation. The member's `email` is the natural key used for that reuse, and a member accumulates `total_speeches_delivered` and `highest_level_completed` across every club they belong to.

The membership starts its life in a deliberately incomplete state. Its `status` is `PENDING`, its `dues_status` is `ISSUED`, its `dues_paid_through_cycle` is minus one, its `consecutive_cycles_paid` is 0, its `officer_role` is `NONE`, and its `quoted_total_cents` holds the renewal quote computed for the cycle it is joining. Its `speeches_delivered_this_cycle` and `roles_completed_this_cycle` begin at 0. The club's `total_member_count` and `good_standing_score` are recomputed as a result.

Bulk enrollment accepts up to 25 people for one club in a single request, carrying the `club_id`, the array of `members`, and a `pay_dues_immediately` flag. It is best-effort rather than all-or-nothing: one membership is created per entry of `members` in array order, reusing a member row when the entry's email already exists, and a row whose email is malformed is skipped and counted in `failed_count` while the remaining rows are still committed. The response reports `created_count`, `failed_count` and the created `memberships`. When `pay_dues_immediately` is true, every created membership is written as `ACTIVE` with `dues_status` `PAID`, `dues_paid_through_cycle` equal to the club's `dues_cycle_index`, and `quoted_total_cents` taken from the renewal quote. Afterwards the club's `total_member_count`, `paid_member_count`, `new_member_count_this_cycle` and `good_standing_score` are recomputed.

Paying dues is done by the member themselves or by an officer of their club. The gate depends on where the membership stands. A `PENDING` membership may be activated when the club's `charter_status` is `CHARTERED`, or when the membership is paying the cycle the club is currently organizing under, and its `dues_status` is `ISSUED` or `OVERDUE`. A `LAPSED` membership is restored to `ACTIVE` through the reinstatement route: the quote charged is the reinstatement variant, so `reinstatement_fee_cents` of 1000 cents is part of it, and the invoice must be `OVERDUE`. Across both routes the invoice itself must be payable, and the club must be in a state that admits the payment. An invoice that is already `PAID` or has been `VOID`ed is refused with `ERR_DUES_ALREADY_PAID`; a club whose `charter_status` is `SUSPENDED` refuses the renewal with `ERR_CLUB_NOT_CHARTERED`; and a club whose `charter_status` is `REVOKED` refuses it with `ERR_CLUB_REVOKED`. An `ORGANIZING` or `CHARTERED` club admits the payment, which is why a prospective member can pay dues into a club that has not yet been chartered and have that payment count toward the roster the charter will later be judged on.

When a payment lands, the invoice moves from `ISSUED` or `OVERDUE` to `PAID`, `dues_paid_through_cycle` is set to the club's current `dues_cycle_index`, and the consecutive-payment counter is updated: `consecutive_cycles_paid` increments by one when the previous `dues_paid_through_cycle` equalled the club's `dues_cycle_index` minus one, and otherwise resets to 1. The membership's `status` moves from `PENDING` or `LAPSED` to `ACTIVE`, and if it became `ACTIVE` in this operation each of its suspended education paths is lifted back to `ACTIVE`. The club's `paid_member_count`, `new_member_count_this_cycle` and `good_standing_score` are recomputed, and the membership's `version` increments.

An invoice that survives a cycle close unpaid does not simply sit there. It moves from `ISSUED` to `OVERDUE`, and a late fee of 500 cents is recorded against the membership and added to that membership's next quote.

Reversing a payment is a `ClubOfficer` act and requires the invoice to be `PAID`. The refund moves `dues_status` to `VOID`, restores `dues_paid_through_cycle` and `consecutive_cycles_paid` to the values they held before the refunded payment, recomputes the club's `paid_member_count` and `good_standing_score`, and increments the membership's `version`. A membership whose dues are not paid through the club's current cycle is barred from the progression and participation surfaces — creating an education path, logging a project completion, taking a meeting role and entering a contest all require an `ACTIVE` membership paid through the current cycle, and are refused with `ERR_MEMBERSHIP_NOT_ACTIVE` when that does not hold.

### 3.4. Educational Paths and Level Advancement

A member's education runs along a path. Enrollment is the member's own act: the payload carries the `membership_id` the path belongs to, the `path_code` — one of `DYNAMIC_LEADERSHIP`, `ENGAGING_HUMOR`, `PERSUASIVE_INFLUENCE`, `PRESENTATION_MASTERY`, `TEAM_COLLABORATION` or `VISIONARY_COMMUNICATION` — and `expected_membership_version`, which must match the target membership's current `version` or the enrollment is refused as stale. A membership may hold only one path per `path_code`; if it already holds one for that code in status `ACTIVE` or `SUSPENDED`, the request is refused with `ERR_DUPLICATE_PATH_ENROLLMENT`. The new path opens at `LEVEL_1` in status `ACTIVE`, with `level_started_at` set to the request timestamp and `last_advanced_at` left null until the first advance. Enrolling a path is a mutation of the membership as well as a creation of the path, so the membership's `version` increments.

A path's `level` runs through `LEVEL_1`, `LEVEL_2`, `LEVEL_3`, `LEVEL_4` and `LEVEL_5` to `COMPLETED`, which is terminal. Its `status` is an independent dimension taking `ACTIVE` or `SUSPENDED`, and the two do not move together: a path can be suspended at any level. Its `approved_speeches_at_level` counts approved completions on that path whose level equals the path's current level and whose `project_kind` is `SPEECH`; its `approved_projects_at_level` counts every approved completion on that path whose level equals the current level, whatever the kind.

Advancement is gated by a published requirement table, and the table is not uniform across levels. To leave `LEVEL_1` a path needs at least 2 approved speeches and at least 2 approved projects at that level. To leave `LEVEL_2`, `LEVEL_3` or `LEVEL_4` it needs at least 1 approved speech and at least 2 approved projects at that level. To leave `LEVEL_5` — that is, to finish the path — it needs at least 1 approved speech and at least 1 approved project at that level. A path that does not meet the requirement for its current level is refused with `ERR_LEVEL_REQUIREMENTS_NOT_MET`.

Three further conditions gate the same operation. The path itself must be `ACTIVE`; a suspended path cannot advance. The membership behind it must be `ACTIVE` with `dues_paid_through_cycle` at least the club's `dues_cycle_index`. And the club must be in `GOOD` standing — advancing a level at a club whose posture is `PROBATION` or `NOT_IN_GOOD_STANDING` is refused with `ERR_CLUB_NOT_IN_GOOD_STANDING`. Finally, the request carries `expected_education_path_version`, which must equal the path's current `version`; a mismatch is refused with `ERR_STALE_VERSION`.

On a successful advance the level moves up exactly one step — `LEVEL_1` to `LEVEL_2` and so on — and `LEVEL_5` becomes `COMPLETED`. Both `level_started_at` and `last_advanced_at` are stamped with the request timestamp for every advance except the final one into `COMPLETED`, which stamps `last_advanced_at` only. The member's `highest_level_completed` is recomputed, the club's `approved_level_completions_this_cycle`, `dcp_recognition_points` and `good_standing_score` are recomputed, and the path's `version` increments.

Paths are suspended and restored by their membership rather than by the member. When the owning membership lapses, the path moves from `ACTIVE` to `SUSPENDED`; any completion on that path still sitting in `LOGGED` or `EVALUATED` keeps its status but stops counting toward advancement while the path is suspended. When the owning membership is restored to `ACTIVE`, the path moves back from `SUSPENDED` to `ACTIVE` in the same operation. Either way the path's `version` increments.

### 3.5. Project Completions: Evaluation, Officer Review and Retroactive Return

Progress is recorded as a project completion. A member logs one against a path by supplying the `path_id`, the `project_code` — a Pathways identifier such as `L1-ICE-BREAKER` or `L2-ACTIVE-LISTENING` — the `project_kind`, one of `SPEECH`, `EVALUATION` or `LEADERSHIP`, the `level` from 1 through 5 that the project belongs to, the `speech_minutes` delivered (0 for a non-speech project), the `delivered_at` timestamp, an optional `evaluator_member_id` for the person who will evaluate it, and `expected_education_path_version`, which must match the path's current `version` or the log is refused as stale.

The completion is stamped rather than supplied: its `member_id` and `club_id` are copied from the path's membership at creation, its `status` is `LOGGED`, and `counts_for_level_advancement` is false. `evaluation_summary` and `return_reason` are both empty at this point. The log is a mutation of the path, so the path's `version` increments. If the payload names an `evaluator_member_id` equal to the member the completion belongs to, the log is refused with `ERR_EVALUATOR_CONFLICT` — a member does not evaluate their own project.

The evaluator then records their assessment. The completion must be in `LOGGED` or `RETURNED` status, otherwise the request is refused with `ERR_INVALID_STATE`. The `evaluator_member_id` must be set and must equal the acting member, and the `evaluation_summary` supplied must be a non-empty string. On success the completion moves to `EVALUATED`; when it came from `RETURNED`, the `return_reason` is cleared as part of the same operation. The path's `approved_speeches_at_level` and `approved_projects_at_level` are recomputed, and the completion's `version` increments.

An officer of the completion's club then reviews it, deciding with `decision` — either `APPROVE` or `RETURN` — and supplying `return_reason` when the decision is to return. The officer must belong to the same club as the completion; a review from an officer of any other club fails the ownership clause. Approval is available only from `EVALUATED`, and it carries two content requirements: when the completion's `project_kind` is `SPEECH`, an `evaluation_summary` must be set, and the path's approved speech and project counts after the approval must not exceed the published maximum of 6 for a level. A return is available from `EVALUATED` and also from `APPROVED`, and it requires a non-empty `return_reason`. Attempting a review against a completion in any other status is refused with `ERR_INVALID_STATE`.

Approval is the moment a completion starts counting. `counts_for_level_advancement` becomes true when the completion's level equals the path's current level, and the member's `total_speeches_delivered` and `highest_level_completed`, the path's two approved counters, and the club's `approved_level_completions_this_cycle`, `dcp_recognition_points` and `good_standing_score` are all recomputed. The membership's `speeches_delivered_this_cycle` — the count of approved `SPEECH` completions the member has logged at that club in the current cycle — moves with it. The completion's `version` increments.

A return from `EVALUATED` is a correction: the completion moves to `RETURNED`, the path's approved counters are recomputed, and the completion's `version` increments. A return from `APPROVED` is more consequential, because it reaches backwards. It clears `counts_for_level_advancement` to false, and when the returned completion's level equals the path's current level, the path itself drops by one step — `LEVEL_2` back to `LEVEL_1`, `LEVEL_3` back to `LEVEL_2`, `LEVEL_4` back to `LEVEL_3`, or `LEVEL_5` back to `LEVEL_4` — with `level_started_at` reset to the request timestamp. That reversion is itself a mutation of everything the level was supporting: the path's approved counters, the member's `total_speeches_delivered` and `highest_level_completed`, and the club's `approved_level_completions_this_cycle`, `dcp_recognition_points` and `good_standing_score` are all recomputed, and every contest entry belonging to that member through that club is disqualified. The completion's `version` increments in both kinds of return.

### 3.6. Meetings, Functional Roles and Speaker Rotation

Scheduling a meeting is a `ClubOfficer` act for their own club. The payload carries the `club_id`, the `scheduled_at` instant, the `venue_name`, an optional `duration_minutes` that defaults to 90 when omitted, an optional `theme`, and `expected_club_version`, which must equal the club's current `version` or the schedule is refused as stale. A newly scheduled meeting is in status `SCHEDULED` with `required_role_slots` fixed at 7, `filled_role_slots` 0, `quorum_met` false and `held_at` null. Scheduling increments the club's `version`.

The one thing standing between a client and a double-booked club is the overlap rule, and it is scoped to the club's meeting window rather than to a room. A candidate meeting is refused when any meeting of the same club in status `SCHEDULED` or `HELD` intersects it: the existing meeting starts before the candidate's start plus the candidate's `duration_minutes`, and the candidate starts before the existing meeting's start plus its own `duration_minutes`. Cancelled meetings never occupy the window, so a cancelled slot frees up completely. A second, one-sided rule guards the gap that precedes the candidate: the request is also refused when the candidate starts at or after the end of an existing meeting and less than 30 minutes after it — that is, when the difference between the candidate's start and the existing meeting's end is at least 0 and strictly less than 30 minutes. The buffer runs one way only; a candidate starting exactly 30 minutes after an existing meeting ends is accepted. Both refusals carry `ERR_MEETING_OVERLAP`.

Filling the meeting's roles is also an officer act. A role assignment names the `meeting_id`, the `member_id`, the `role_code` — one of `TOASTMASTER`, `TABLE_TOPICS_MASTER`, `SPEAKER`, `EVALUATOR`, `TIMER`, `AH_COUNTER`, `GRAMMARIAN` or `GENERAL_EVALUATOR` — and `expected_meeting_version`, which must equal the meeting's current `version` or the assignment is refused as stale. The assignment's `role_class` is derived, not supplied: `SPEECH` for `SPEAKER` and `FUNCTIONARY` for every other code. The new assignment starts in status `ASSIGNED` with `credit_awarded` false and `released_reason` empty, and it recomputes the meeting's `filled_role_slots` and increments the meeting's `version`.

Three rules constrain who may be put in a slot. A member may hold only one `ASSIGNED` assignment on a given meeting; a second one is refused with `ERR_DUPLICATE_ASSIGNMENT`. A meeting never carries more than 7 assignments in status `ASSIGNED`, `COMPLETED` or `NO_SHOW` — the count that `filled_role_slots` reports — and an eighth is refused with `ERR_ROLE_SLOTS_FULL`. And speaking roles rotate: for a candidate `SPEECH` assignment, the window runs from 7 days before the meeting's `scheduled_at` to 7 days after it, inclusive at both ends, and the server counts every role assignment for that member whose `role_class` is `SPEECH` and whose status is `ASSIGNED`, `COMPLETED` or `NO_SHOW` and whose meeting falls inside that window. If that count already stands at 2, the new assignment is refused with `ERR_ROLE_WINDOW_EXCEEDED`; released assignments never occupy the window, so releasing a role genuinely frees the member's slot in the rotation. The window follows the member across every club, not just the club of the meeting being scheduled.

Releasing an assignment is an officer act that requires the assignment to be `ASSIGNED` and its meeting to still be `SCHEDULED`; the payload carries `released_reason`. The assignment moves to `RELEASED`, the meeting's `filled_role_slots` is recomputed, and the assignment's `version` increments. A `RELEASED` assignment is terminal, and its member is free to take another speaking role inside the same window.

Closing a meeting is how it reaches an outcome, and the payload carries `outcome`, plus `attendance_count` and `attendee_member_ids` when the meeting is being closed as held. Closing as `HELD` requires `attendance_count` of at least 5; anything lower is refused with `ERR_QUORUM_NOT_MET`. When the quorum is met, `quorum_met` becomes true and `held_at` is stamped with the request timestamp. Every role assignment of that meeting still in status `ASSIGNED` is then resolved in the same operation: those whose member appears in `attendee_member_ids` become `COMPLETED`, and those whose member does not appear become `NO_SHOW`. A completion awards credit when the role was a speaking role — `credit_awarded` becomes true when the assignment's `role_class` is `SPEECH` — and it recomputes the member's `roles_completed_this_cycle`. The club's `meetings_held_this_cycle` and `good_standing_score` are recomputed, and the meeting's `version` increments.

Closing as `CANCELLED` requires no quorum and no attendance, and every assignment of the meeting still in status `ASSIGNED` is released rather than resolved. A meeting closed as `HELD` or `CANCELLED` is terminal and cannot be closed again.

### 3.7. Officer Elections and District Training

Club leadership turns over on the dues cycle. An officer term is opened by a `ClubOfficer` of the club, who names the `club_id`, the `member_id` being put forward and the `office` — one of `PRESIDENT`, `VP_EDUCATION`, `VP_MEMBERSHIP`, `VP_PUBLIC_RELATIONS`, `SECRETARY`, `TREASURER` or `SERGEANT_AT_ARMS`. The term is stamped with `term_index` equal to the club's `dues_cycle_index` at the moment of nomination and `nominated_at` equal to the request timestamp, and it starts in status `NOMINATED`. Its `elected_at`, `training_due_at` and `trained_at` all stay empty until the election happens. A member's `officer_role` mirrors the office they currently hold, derived from the `ELECTED` or `TRAINED` term standing at that club, and is `NONE` when they hold none.

Electing the nominee is also a `ClubOfficer` act, and it is the most heavily gated step in the club's governance. Four things must hold. The nominee must hold a membership at that club that is `ACTIVE` and paid through the club's current cycle. The club must have held at least one meeting with `quorum_met` true whose `held_at` falls after this term's `nominated_at` — an election needs a quorum that postdates the nomination, and a missing or stale quorum produces `ERR_ELECTION_QUORUM_NOT_MET`. No other officer term for the same club and the same `term_index` may already be `ELECTED` or `TRAINED` for the same office, and the nominee must not already hold another term at that club and term index in `ELECTED` or `TRAINED` status; either collision produces `ERR_OFFICE_ALREADY_FILLED`. A term that is not `NOMINATED` cannot be elected at all and is refused with `ERR_INVALID_STATE`.

A successful election stamps `elected_at` with the request timestamp and sets `training_due_at` to exactly 30 days after `elected_at`. The elected member's `officer_role` is recomputed so it reflects the new office, and the term's `version` increments.

Training is a district obligation rather than a club one. A `DistrictDirector` records it against a term that is `ELECTED`, and the director must be someone other than the officer being trained — the acting director's member identity must differ from the term's `member_id`, so an officer cannot sign off on their own training. The club must be in `GOOD` or `PROBATION` posture; a club in `NOT_IN_GOOD_STANDING` cannot have its officers trained. A term that is not `ELECTED` is refused with `ERR_INVALID_STATE`. On success the term moves to `TRAINED` and `trained_at` is stamped with the request timestamp, which is what closes the 30-day obligation recorded at election time. The club's `officer_trained_count`, `dcp_recognition_points` and `good_standing_score` are recomputed, and the term's `version` increments. Trained officers are what the club's officer component measures, so this is one of the few operations a district director performs that moves a club's own score.

Two automatic ends exist for a term. When the member's membership at that club lapses, any term of theirs in `ELECTED` status is vacated: it moves to `VACATED`, their `officer_role` returns to `NONE`, and the club's `officer_trained_count` and `good_standing_score` are recomputed. And when a cycle close pushes the club's `dues_cycle_index` past a term's `term_index`, that term — whether it was `ELECTED` or `TRAINED` — becomes `COMPLETED`, and the member's `officer_role` returns to `NONE`. `COMPLETED` and `VACATED` are both terminal.

### 3.8. Speech Contests and Advancement to Area Level

Contests run at four levels. A `DistrictDirector` or a `WorldHeadquarters` operator creates one by naming its `contest_level` — `CLUB`, `AREA`, `DIVISION` or `DISTRICT` — its `contest_type` — `INTERNATIONAL_SPEECH`, `TALL_TALES`, `EVALUATION` or `HUMOROUS` — the `district_number` and `division_code` that run it, its `scheduled_at`, and the `area_code` when the contest is at area level. A `club_id` is required when the contest is at `CLUB` level and stays null for `AREA`, `DIVISION` and `DISTRICT` contests; the `area_code` is null for `CLUB` and `DIVISION` contests. A new contest opens in status `SCHEDULED` with `entry_count` 0, `judged_entry_count` 0 and `winner_entry_id` null.

Entering is the member's act: the payload names the `contest_id`, the `member_id` competing, the `club_id` through which eligibility is claimed, and the `speech_title`. The entry starts in status `ENTERED` with `ballot_count` 0 and `judge_score_total` 0, and the contest's `entry_count` is recomputed. Two eligibility conditions gate the entry, on top of the general requirement that the member's membership be `ACTIVE` and paid through the club's current cycle — a member who is not is refused with `ERR_MEMBERSHIP_NOT_ACTIVE`. The claiming club must be in `GOOD` standing, and an entry through a club on `PROBATION` or in `NOT_IN_GOOD_STANDING` is refused with `ERR_CLUB_NOT_IN_GOOD_STANDING`. Entries are also accepted only while the contest is still `SCHEDULED`; once it has started or finished, a new entry is refused with `ERR_CONTEST_NOT_OPEN`.

Judging is a `DistrictDirector` act. A ballot names the `judge_member_id` and three scores — `content_score`, `delivery_score` and `language_score` — each of which must lie between 0 and 100 inclusive, with anything outside that range rejected as an invalid request. The ballot's `total_score` is a weighted blend: the content score carries half the weight, the delivery score three tenths, and the language score the remaining two tenths, and the blended result is rounded to a whole number using round half up. The judge must be independent of the entry: a ballot from the competing member, or from anyone who holds a membership at the entry's club, is refused with `ERR_JUDGE_CONFLICT`. A judge may ballot an entry only once, and a second ballot from the same judge is refused with `ERR_DUPLICATE_BALLOT`. Ballots are accepted while the contest is `SCHEDULED` or `IN_PROGRESS` and refused once it is `COMPLETED`, with `ERR_CONTEST_NOT_OPEN`.

Recording a ballot increments the entry's `ballot_count` by one and increases its `judge_score_total` by the ballot's total. The first ballot recorded anywhere in a contest moves that contest from `SCHEDULED` to `IN_PROGRESS`. When an entry's third ballot lands, its `ballot_count` reaches 3 and the entry moves from `ENTERED` to `JUDGED` — three ballots is the threshold at which an entry becomes judgeable, and an entry that never reaches it stays `ENTERED` and is simply not part of the final ranking. The contest's `entry_count` and `judged_entry_count` are recomputed after each ballot, and the entry's `version` increments.

Completing the contest is a `DistrictDirector` act and it ranks the field. The candidate set is the contest's entries in status `JUDGED`; a contest with no judged entry is refused with `ERR_NO_JUDGED_ENTRIES`, and every judged entry must carry at least 3 ballots before the contest may complete. Ranking is by `judge_score_total` descending, with ties broken by the entry's `created_at` ascending, so the earlier-logged entry takes the higher place when scores are equal. The first-ranked entry becomes `ADVANCED` with `placement` 1 and becomes the contest's `winner_entry_id`. Every other judged entry becomes `ELIMINATED` with its `placement` set to its one-based rank. Entries still sitting in `ENTERED` are left untouched by the completion. The contest's `status` becomes `COMPLETED`, `completed_at` is stamped with the request timestamp, and the contest's `version` increments.

A club-level contest feeds the area above it. When the completed contest is at `CLUB` level and an `AREA` contest with the same `contest_type`, `area_code` and `district_number` exists in status `SCHEDULED`, a new contest entry is created at that area contest for the advancing winner. The winner's club also has its `contest_participation_count` and `dcp_recognition_points` recomputed, and so does each eliminated entry's club.

Eligibility can be lost after the fact. An entry in `ENTERED` or `JUDGED` status is disqualified when its club's `good_standing` is no longer `GOOD`, when the member's membership at that club is no longer `ACTIVE`, or when the member's supporting path level has dropped. A `DISQUALIFIED` entry stops counting toward the contest's `entry_count` and `judged_entry_count`, both of which are recomputed, and the entry's `version` increments. One further trigger comes from the posture dimension itself: when a club's posture falls from `PROBATION` to `NOT_IN_GOOD_STANDING`, every contest entry at that club is disqualified in the same operation.

### 3.9. District Governance Visits and the Coaching Queue

Area and division directors keep the district honest by visiting clubs. A `DistrictDirector` schedules a visit by naming the `club_id`, the `director_member_id` making it, the `visit_kind` — `AREA_DIRECTOR`, `DIVISION_DIRECTOR` or `CLUB_COACH` — and the `scheduled_at` instant. The visit opens in status `SCHEDULED` with `completed_at` null and `findings` empty. When the visit is a `CLUB_COACH` visit and the club's `coaching_status` is `FLAGGED`, scheduling it moves the club's `coaching_status` to `ASSIGNED`, marking that help is on the way.

Completing a visit is the director's own act: the acting director's member identity must equal the visit's `director_member_id`, so a director cannot complete someone else's visit, and the `findings` recorded must be a non-empty string. The visit moves from `SCHEDULED` to `COMPLETED` with `completed_at` stamped at the request timestamp. The coaching posture follows: when the visit's `visit_kind` is `CLUB_COACH`, the club's `coaching_status` becomes `COACHED`; for any other visit kind, a club whose `coaching_status` was `FLAGGED` becomes `ASSIGNED`. The visit's `version` increments. A visit that is not `SCHEDULED` cannot be completed and is refused with `ERR_INVALID_STATE`.

A visit that is never completed lapses on its own. When a cycle closes, every scheduled visit whose `scheduled_at` falls before the club's `cycle_closed_at` becomes `MISSED`, and its `version` increments. A missed `CLUB_COACH` visit carries a consequence for the club: if the club's `good_standing` is `PROBATION` or `NOT_IN_GOOD_STANDING`, its `coaching_status` becomes `FLAGGED`, so a club that was supposed to receive coaching and did not is flagged for it. Conversely, when a club climbs out of `NOT_IN_GOOD_STANDING` all the way back to `GOOD` and a `CLUB_COACH` visit against it has been completed, its `coaching_status` becomes `COACHED`.

District directors work from a ranked queue of clubs that need help. The queue's candidate set is the clubs whose `good_standing` is `PROBATION` or `NOT_IN_GOOD_STANDING` and whose `coaching_status` is still `NONE` — a club already flagged, already assigned a coach or already coached has left the queue. Candidates are ordered by `good_standing_score` ascending, so the weakest club comes first; ties are broken by `paid_member_count` ascending, so the smaller club comes first among equals; remaining ties are broken by `created_at` ascending, so the older club comes first. The queue holds at most 100 candidates. Asking for the next club to coach when no club qualifies is refused with `ERR_NO_COACHING_CANDIDATES`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource — an organizing club, a membership, an education path, a project completion, a meeting, a role assignment, an officer term, a contest, a contest entry or a governance visit — return `201 Created`. Every operation that modifies a resource that already exists, including advancing a level, closing a meeting, electing an officer, completing a contest and every state-driving action on an existing resource, returns `200 OK`. The table below lists the HTTP contract only; the request payloads, preconditions, cascades and computed outcomes for each operation are the ones stated in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| GET | `/toastmasters/clubs` | List clubs with optional filters; the sponsor filter is the reverse-reachability read for `sponsor_club_id` | WorldHeadquarters, ClubOfficer, Member, DistrictDirector |
| GET | `/toastmasters/clubs/coaching-queue` | Ranked list of clubs a district director should coach next, best candidate first | DistrictDirector, WorldHeadquarters |
| GET | `/toastmasters/clubs/{id}` | Get one club with every derived counter | WorldHeadquarters, ClubOfficer, Member, DistrictDirector |
| GET | `/toastmasters/members/{id}` | Get one member with derived speech and level totals | WorldHeadquarters, ClubOfficer, Member, DistrictDirector |
| GET | `/toastmasters/memberships` | List memberships filtered by member or club | WorldHeadquarters, ClubOfficer, Member, DistrictDirector |
| GET | `/toastmasters/memberships/{id}` | Get one membership with dues and derived counters | WorldHeadquarters, ClubOfficer, Member, DistrictDirector |
| GET | `/toastmasters/education-paths` | List education paths filtered by membership | WorldHeadquarters, ClubOfficer, Member, DistrictDirector |
| GET | `/toastmasters/education-paths/{id}` | Get one education path with its level counters | WorldHeadquarters, ClubOfficer, Member, DistrictDirector |
| GET | `/toastmasters/project-completions` | List project completions filtered by path, member, club or evaluator | WorldHeadquarters, ClubOfficer, Member, DistrictDirector |
| GET | `/toastmasters/project-completions/{id}` | Get one project completion | WorldHeadquarters, ClubOfficer, Member, DistrictDirector |
| GET | `/toastmasters/meetings` | List meetings filtered by club or status | WorldHeadquarters, ClubOfficer, Member, DistrictDirector |
| GET | `/toastmasters/meetings/{id}` | Get one meeting with slot and quorum counters | WorldHeadquarters, ClubOfficer, Member, DistrictDirector |
| GET | `/toastmasters/role-assignments` | List role assignments filtered by meeting, member or role class | WorldHeadquarters, ClubOfficer, Member, DistrictDirector |
| GET | `/toastmasters/role-assignments/{id}` | Get one role assignment | WorldHeadquarters, ClubOfficer, Member, DistrictDirector |
| GET | `/toastmasters/officer-terms` | List officer terms filtered by club, member or term index | WorldHeadquarters, ClubOfficer, Member, DistrictDirector |
| GET | `/toastmasters/officer-terms/{id}` | Get one officer term | WorldHeadquarters, ClubOfficer, Member, DistrictDirector |
| GET | `/toastmasters/contests` | List contests filtered by club, level or type | WorldHeadquarters, ClubOfficer, Member, DistrictDirector |
| GET | `/toastmasters/contests/{id}` | Get one contest with entry counters | WorldHeadquarters, ClubOfficer, Member, DistrictDirector |
| GET | `/toastmasters/contest-entries` | List contest entries filtered by contest, member or club | WorldHeadquarters, ClubOfficer, Member, DistrictDirector |
| GET | `/toastmasters/contest-entries/{id}` | Get one contest entry with ballot counters | WorldHeadquarters, ClubOfficer, Member, DistrictDirector |
| GET | `/toastmasters/area-visits` | List governance visits filtered by club, director or status | WorldHeadquarters, ClubOfficer, Member, DistrictDirector |
| GET | `/toastmasters/area-visits/{id}` | Get one governance visit | WorldHeadquarters, ClubOfficer, Member, DistrictDirector |
| POST | `/toastmasters/clubs` | Create an organizing club; dues cycle 0 opens immediately | WorldHeadquarters |
| POST | `/toastmasters/clubs/{id}/charter` | Grant or reinstate a charter once the organizing requirements hold | WorldHeadquarters |
| POST | `/toastmasters/clubs/{id}/close-cycle` | Close the open dues cycle, open the next one and re-derive standing | WorldHeadquarters |
| POST | `/toastmasters/memberships` | Enroll a person into a club; reuses the member row when the member or email already exists | ClubOfficer, WorldHeadquarters |
| POST | `/toastmasters/memberships/bulk` | Enroll up to 25 people into one club in a single request; best-effort with per-row results | ClubOfficer, WorldHeadquarters |
| POST | `/toastmasters/memberships/{id}/renew` | Pay the current cycle's dues using the applicable quote variant | Member, ClubOfficer |
| POST | `/toastmasters/memberships/{id}/refund-dues` | Reverse the most recent dues payment and restore the prior cycle counters | ClubOfficer |
| POST | `/toastmasters/education-paths` | Enroll a membership in a Pathways path at `LEVEL_1` | Member |
| POST | `/toastmasters/education-paths/{id}/advance-level` | Advance the path one level once the published requirement table is satisfied | Member |
| POST | `/toastmasters/project-completions` | Log a project or speech completion against an education path | Member |
| POST | `/toastmasters/project-completions/{id}/evaluation` | Record the evaluator's written evaluation | Member |
| POST | `/toastmasters/project-completions/{id}/review` | Officer approves or returns an evaluated completion | ClubOfficer |
| POST | `/toastmasters/meetings` | Schedule a club meeting; rejected when the interval collides with another meeting at the same club | ClubOfficer |
| POST | `/toastmasters/meetings/{id}/close` | Close a scheduled meeting as held or cancelled | ClubOfficer |
| POST | `/toastmasters/role-assignments` | Assign a member to a meeting role; rejected on window, capacity and duplicate violations | ClubOfficer |
| POST | `/toastmasters/role-assignments/{id}/release` | Release an assigned role, freeing the slot and the rotation window | ClubOfficer |
| POST | `/toastmasters/officer-terms` | Nominate a member for a club office in the current term | ClubOfficer |
| POST | `/toastmasters/officer-terms/{id}/elect` | Record the election of a nominated officer | ClubOfficer |
| POST | `/toastmasters/officer-terms/{id}/training` | Record district officer training for an elected officer | DistrictDirector |
| POST | `/toastmasters/contests` | Create a club, area, division or district contest | DistrictDirector, WorldHeadquarters |
| POST | `/toastmasters/contests/{id}/complete` | Rank judged entries, advance the winner and open the next contest level | DistrictDirector |
| POST | `/toastmasters/contest-entries` | Enter a member in a contest through a named club | Member |
| POST | `/toastmasters/contest-entries/{id}/ballots` | Record one judge's ballot for an entry | DistrictDirector |
| POST | `/toastmasters/area-visits` | Schedule an area director, division director or club coach visit | DistrictDirector |
| POST | `/toastmasters/area-visits/{id}/complete` | Complete a scheduled governance visit and record findings | DistrictDirector |

## 5. Error Code Catalogue

The table below lists every error identifier the API can return together with the HTTP status code that carries it. The conditions that trigger each one are stated in §2 and §3 alongside the workflow they guard.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_DUPLICATE_PATH_ENROLLMENT` | 409 Conflict |
| `ERR_DUPLICATE_ASSIGNMENT` | 409 Conflict |
| `ERR_DUPLICATE_BALLOT` | 409 Conflict |
| `ERR_OFFICE_ALREADY_FILLED` | 409 Conflict |
| `ERR_MEETING_OVERLAP` | 409 Conflict |
| `ERR_ROLE_WINDOW_EXCEEDED` | 409 Conflict |
| `ERR_ROLE_SLOTS_FULL` | 409 Conflict |
| `ERR_CONTEST_NOT_OPEN` | 409 Conflict |
| `ERR_QUORUM_NOT_MET` | 409 Conflict |
| `ERR_DUES_ALREADY_PAID` | 409 Conflict |
| `ERR_ORGANIZING_MEETING_REQUIRED` | 422 Unprocessable Entity |
| `ERR_CHARTER_MINIMUM_NOT_MET` | 422 Unprocessable Entity |
| `ERR_CORPORATE_SPONSOR_REQUIRED` | 422 Unprocessable Entity |
| `ERR_SPONSOR_NOT_IN_GOOD_STANDING` | 422 Unprocessable Entity |
| `ERR_LEVEL_REQUIREMENTS_NOT_MET` | 422 Unprocessable Entity |
| `ERR_EVALUATOR_CONFLICT` | 422 Unprocessable Entity |
| `ERR_JUDGE_CONFLICT` | 422 Unprocessable Entity |
| `ERR_ELECTION_QUORUM_NOT_MET` | 422 Unprocessable Entity |
| `ERR_CLUB_NOT_CHARTERED` | 422 Unprocessable Entity |
| `ERR_CLUB_REVOKED` | 422 Unprocessable Entity |
| `ERR_CLUB_NOT_IN_GOOD_STANDING` | 422 Unprocessable Entity |
| `ERR_MEMBERSHIP_NOT_ACTIVE` | 422 Unprocessable Entity |
| `ERR_NO_JUDGED_ENTRIES` | 422 Unprocessable Entity |
| `ERR_NO_COACHING_CANDIDATES` | 404 Not Found |

