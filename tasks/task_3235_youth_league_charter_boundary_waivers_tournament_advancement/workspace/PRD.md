# Youth League Charter API — Product Requirements Document

## 1. Introduction

Youth baseball at the local-league level is not a single activity but a chain of regulated obligations. Before a child can take the field, the league itself must hold a valid charter for the current season, the child's age and residency must be established with documentary proof, every adult who touches the program must pass background screening, and the league must carry active insurance for the entire season window. When the regular season ends, a second chain begins: all-star rosters are selected from eligible players, entered into tournament competition at the district level, and advanced — game by game, level by level — through sectional, state, and regional brackets under strict pitch-count safety rules and a formal protest process.

This document specifies the API that administers that entire lifecycle. It exists because the people who operate these leagues — district administrators, local league administrators, tournament directors, and official scorers — need a single system of record in which charter status, player eligibility, volunteer clearances, insurance coverage, roster composition, and tournament advancement are all derived from the same underlying facts and enforced by the same rules. The system deliberately couples these concerns: a lapsed charter cascades into suspended divisions and withdrawn tournament entries; a revoked player eligibility cascades into vacated roster selections and cancelled games; an upheld protest can reopen a final game and reverse an elimination.

A logical clock underpins the whole platform. All date-sensitive behavior — renewal windows, registration windows, document freshness, insurance expiry, pitch-count rest windows, and the annual charter lapse — is evaluated against this clock rather than wall-clock time, so that an entire season can be exercised deterministically.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the role under which the user acts. A request missing either header, or carrying a role value outside the enumerated set, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is valid but not authorized for the target operation is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

The platform defines five roles, spelled exactly as follows:

- `DistrictAdministrator` — the district-level authority. This role charters leagues, approves or rejects charter renewals, decides boundary waivers, adjudicates volunteer background screenings, records insurance certificates, and operates the logical clock.
- `LeagueAdministrator` — the local league operator. This role submits charter renewals, sets division team counts, registers players and attaches their eligibility documents, verifies and revokes player eligibility, requests boundary waivers, registers volunteers and submits their screenings, and builds and submits all-star rosters.
- `TournamentDirector` — the tournament authority. This role creates tournament entries, schedules games, finalizes games with official scores, files and resolves protests, and advances entries between tournament levels.
- `OfficialScorer` — the scoring official. This role records pitching appearances during tournament games.
- `Any` — a synthetic role standing for any authenticated caller; every read endpoint in the system is available to all four concrete roles above.

All four concrete roles have `identity: opaque`: `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server does not compare it to any entity's `id` for ownership checks. The same is true of the synthetic `Any` role. No role in this system is entity-backed; authorization is purely role-based, never ownership-based.

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

Every list endpoint accepts two optional query parameters: `limit`, defaulting to 10, with a minimum of 1 and a maximum of 100, and `offset`, defaulting to 0. List responses carry `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object. Unless a more specific ordering is stated for a particular collection, list endpoints return resources sorted by `created_at` ascending.

### 2.4. Resource Identity, Timestamps, and Versioning

Every persisted resource carries an `id` that is a server-minted UUID with no type prefix — the identifier is the bare UUID string and nothing more. Every resource with the standard common fields also carries `created_at` and `updated_at`, both ISO 8601 UTC timestamps with three fractional digits, and a `version` integer that starts at its initial value on creation and increments by 1 on every mutation of that resource. The single exception is the eligibility document resource, which is immutable evidence: it carries only `id` and `created_at`; `updated_at` and `version` are absent from it entirely.

Two mutations also propagate a version bump upward along the ownership chain. Setting a division's team count increments the parent league's `version` in addition to the division's own. Recording a pitching appearance or finalizing a game increments the game's `version`; the charter decision and the waiver-creation paths likewise increment the league's `version`, as described in their respective sections. Reads never change a version.

Child resources remember their parents through server-assigned foreign-key fields, all carrying the referenced resource's `id`: a renewal, division, player, waiver, volunteer, insurance certificate, roster, and entry each carry `league_id`; an eligibility document carries `player_id`; a screening carries `volunteer_id`; a game carries `entry_id`; and a pitching appearance or protest carries `game_id`.

### 2.5. The Logical Clock and Its Scheduled Sweeps

The platform keeps a single logical clock, distinct from wall-clock time. At server startup the clock reads exactly 2026-09-01T00:00:00Z, and before any operator sets it the clock continues to report that instant — it never silently falls back to the host's wall clock. A `DistrictAdministrator` moves time forward through an admin-only clock-setting capability that accepts a target instant `to_iso8601`.

Advancing the clock is never a passive read of time: each set operation runs two scheduled sweeps across the whole dataset. The first is the charter lapse sweep: any league whose latest approved renewal covers season year Y, where the new clock date falls after March 31 of season Y+1, and for which no approved renewal for season Y+1 exists, transitions from `CHARTERED` to `SUSPENDED`, with the full cascade described in §3.8. The second is the insurance expiry sweep: every insurance certificate whose coverage end date falls before the new clock date transitions from `ACTIVE` to `EXPIRED`. Both sweeps run inside the same clock-setting operation, so a single time advance can simultaneously suspend leagues and expire the certificates that might otherwise have saved them.

### 2.6. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and only those two. Endpoints not named here do not take a version field.

Creating a boundary waiver requires the request to carry `expected_league_version`, holding the client-observed `version` of the parent league. If the league's current `version` has advanced past that value — because a charter renewal was decided, a suspension sweep fired, a team count was patched, or another waiver was created against the same league — the creation is rejected with `ERR_STALE_VERSION` (HTTP 412). The rule exists because a waiver's validity is evaluated against the league's current charter posture, and a charter decision legitimately supersedes the posture the client based its request on.

Finalizing a tournament game requires the request to carry `expected_game_version`, holding the client-observed `version` of the game. Because every recorded pitching appearance advances the game's `version`, a client that reviewed the appearance set and then sends its finalization against an older `version` is rejected with `ERR_STALE_VERSION` (HTTP 412) — the official score may only be certified against the complete appearance set the client actually observed.

### 2.7. Nested Resource Retrieval and Validation Order

Many resources live below their parents in the URL hierarchy — a renewal below its league, a screening below its volunteer below its league, a protest below its game below its entry. The path variables are named `leagueId`, `divisionId`, `playerId`, `documentId`, `renewalId`, `waiverId`, `volunteerId`, `screeningId`, `certificateId`, `rosterId`, `entryId`, `gameId`, `appearanceId`, and `protestId`, each resolving to the `id` of the corresponding resource. For every nested endpoint, the path parameters are validated strictly left to right: the league identifier first, then the next identifier in the path (player, volunteer, renewal, waiver, roster, or division), then the entry identifier, then the game identifier, and finally the protest or screening identifier. The first identifier that fails to resolve produces the corresponding not-found error — `ERR_LEAGUE_NOT_FOUND`, `ERR_DIVISION_NOT_FOUND`, `ERR_PLAYER_NOT_FOUND`, `ERR_RENEWAL_NOT_FOUND`, `ERR_WAIVER_NOT_FOUND`, `ERR_VOLUNTEER_NOT_FOUND`, `ERR_SCREENING_NOT_FOUND`, `ERR_ROSTER_NOT_FOUND`, `ERR_ENTRY_NOT_FOUND`, `ERR_GAME_NOT_FOUND`, or `ERR_PROTEST_NOT_FOUND` — each with HTTP 404, and no later identifier is examined once an earlier one has failed.

Beyond resource existence, every request is checked against a fixed, ordered ladder of validation categories, and the ordering is normative: when a request would violate several rules at once, the error that surfaces is the one belonging to the earliest category on the ladder. The ladder, from first to last, is: (1) authentication context — the presence and validity of the two headers; (2) authorization — whether the role may perform the operation; (3) resource existence, left to right as described above; (4) the league charter gate described in §2.8; (5) the state precondition of the target entity (renewal pending, waiver pending, roster open, game in progress, and so on); (6) pitching and screening safety rules; (7) temporal-window rules such as renewal, registration, document freshness, and screening coverage windows; (8) cross-entity referential integrity such as document presence, boundary satisfaction, division assignment, roster membership, overlap checks, insurance containment, advancement prerequisites, and roster size bounds; and (9) the fiscal late-fee rule. A charter-gate failure therefore surfaces as `ERR_LEAGUE_NOT_CHARTERED` even when the request would also fail a later business rule, and a state precondition surfaces before any window or integrity check.

### 2.8. The Charter Gate

Charter status is the master switch for league activity. A league must be `CHARTERED` — not `PROVISIONAL`, not `SUSPENDED` — before any of the following six operations will proceed: registering a player, requesting a boundary waiver, creating an all-star roster, adding a selection to a roster, submitting a roster, and creating a tournament entry. Any of these attempted while the league is `PROVISIONAL` or `SUSPENDED` is rejected with `ERR_LEAGUE_NOT_CHARTERED` (HTTP 409). Operations not on this list — submitting a charter renewal, setting division team counts, registering volunteers and submitting screenings, recording insurance certificates — are intentionally available before the charter is granted, because they are precisely the instruments by which a league earns its charter.

### 2.9. Money, Precision, and Rounding

All monetary amounts in this system are integer counts of cents — there are no fractional cents anywhere. Percentages and fees that require decimals are rounded half up: halfway cases round away from zero. The participation percentage is carried at two decimal places, rounded half up. Renewal fees are computed per line and rounded half up to integer cents before the lines are summed; §3.2 pins down this rounding order, which matters because rounding the total instead of each line produces different cent values. Pitch counts, rest days, roster sizes, and loss counts are all plain integers.

## 3. Business Logic & Workflows

### 3.1. Chartering a League and Its Five Divisions

A league comes into existence when a `DistrictAdministrator` creates it with a `league_name`, a `region_code` (values such as WEST or SOUTHWEST), and the `season_year` the league will be chartered for. Creation does not grant a charter: the league's `charter_status` begins as `PROVISIONAL`. Creation does, however, build the league's entire competitive skeleton in one step — five divisions are auto-created in a fixed creation order: `TEE_BALL` first, then `MINOR`, then `MAJOR`, then `JUNIOR`, then `SENIOR`. Each division carries a standard league-age range: `TEE_BALL` spans ages 4 through 6 (`min_league_age` 4, `max_league_age` 6), `MINOR` spans 7 through 9, `MAJOR` spans 10 through 12, `JUNIOR` spans 13 through 14, and `SENIOR` spans 15 through 16. Every division starts with a `team_count` of 0 and `status` `ACTIVE`. When the league's divisions are listed, they come back in `created_at` ascending order with ties broken by that fixed creation order, so the first entry is always `TEE_BALL` and the fifth is always `SENIOR`. The league's `total_team_count` is initialized to 0 at creation.

Each division carries a `division_code` drawn from the five values above. A `LeagueAdministrator` sets how many teams the league will field in each division by patching the division's `team_count`, which defaults to 0; this is allowed while the league is `PROVISIONAL` or `CHARTERED`. Every such patch recomputes the league's `total_team_count` as the sum of `team_count` across all five of the league's divisions, and bumps the league's `version` by 1 alongside the division's own. Division status itself is never set directly: a division moves `ACTIVE` → `SUSPENDED` only as a cascade of league suspension, and `SUSPENDED` → `ACTIVE` only as a cascade of league reinstatement (§3.8).

### 3.2. Renewing the Charter: Windows, Fees, and the Late Penalty

A charter is granted season by season through the renewal process. A `LeagueAdministrator` submits a renewal request naming the `season_year` the renewal covers; the year must not be earlier than the league's own `season_year`, and at most one renewal per league and season year may exist in a state other than `REJECTED` — a second live renewal for the same league and season is rejected with `ERR_INVALID_REQUEST` (HTTP 400). The new renewal starts in `SUBMITTED` status.

Submission is only accepted inside two calendar windows, both measured against the logical clock on the day of submission. Let S be the renewal's `season_year` and D the clock date. The submission is classified `ON_TIME` when D falls anywhere from October 1 of year S−1 through December 31 of year S−1, inclusive on both ends. It is classified `LATE` when D falls anywhere from January 1 of year S through March 31 of year S, inclusive on both ends. Any other submission date is rejected outright with `ERR_RENEWAL_WINDOW_CLOSED` (HTTP 422). The classification is recorded on the renewal as `window_classification`, whose value is either `ON_TIME` or `LATE`.

Submission also computes the renewal's `provisional_fee_cents`. The fee is built line by line: one line of 50000 cents — the base charter fee, i.e. 500 dollars — plus one line per division of the league equal to that division's `team_count` multiplied by 7500 cents (75 dollars per team). All five divisions contribute regardless of whether they are `ACTIVE` or `SUSPENDED`. For an `ON_TIME` submission the fee is simply the sum of the lines. For a `LATE` submission each line is first multiplied by 1.175 and rounded half up to integer cents, and the fee is the sum of those rounded lines. The rounding order is pinned: multiply and round each line to whole cents first, then sum. Rounding the grand total instead would produce different cent values and is not permitted. The provisional fee freezes the division team counts as they exist at the moment of submission.

Approval comes later, from a `DistrictAdministrator` deciding the renewal with an `action` of `APPROVE` or `REJECT`. A decision against a renewal that is no longer `SUBMITTED` is rejected with `ERR_RENEWAL_NOT_PENDING` (HTTP 409). Approval enforces two further gates. First, insurance containment: the league must hold an `ACTIVE` insurance certificate whose coverage window fully contains the season window — that is, coverage from March 1 of the season year through October 31 of the season year, inclusive — and without one the decision is rejected with `ERR_INSURANCE_NOT_ACTIVE` (HTTP 409). Second, the late fee: when the renewal's `window_classification` is `LATE`, the decision payload's `late_fee_paid` must be true, or the approval is rejected with `ERR_LATE_FEE_UNPAID` (HTTP 402). The `late_fee_paid` flag is recorded onto the renewal from the decide payload at approval; for `ON_TIME` approvals it is recorded as false.

An approved renewal recomputes the fee as `final_fee_cents`, using the same line-by-line construction — base fee, per-team lines, the 1.175 late multiplier with per-line rounding when `LATE` — but reading the divisions' `team_count` values as they exist at approval time rather than submission time. The final fee therefore diverges from the provisional fee whenever team counts changed in between; until a renewal is approved, `final_fee_cents` is null. Approval then drives the league's charter transition: a `PROVISIONAL` league becomes `CHARTERED`, and a `SUSPENDED` league is reinstated to `CHARTERED`, in the latter case flipping every `SUSPENDED` division back to `ACTIVE`. Tournament entries withdrawn by the suspension are not resurrected — they remain `WITHDRAWN`. In both approval paths the league's `version` increments by 1. A rejection decision simply moves the renewal from `SUBMITTED` to `REJECTED`, a terminal state, with no effect on the league.

### 3.3. Player Registration: League Age, Participation, and Division Assignment

With the league `CHARTERED`, a `LeagueAdministrator` registers players by supplying `first_name`, `last_name`, `birth_date` in YYYY-MM-DD form, the two boundary flags `residence_within_boundary` and `school_within_boundary`, and the participation figures `games_played` and `games_scheduled` — respectively the number of regular-season games the player appeared in and the number the player's team scheduled. A new player's `eligibility_status` starts as `PENDING`.

Registration computes the player's `league_age`, the player's age as of August 31 of the league's `season_year`. Concretely: the age is the league's season year minus the player's birth year, and if the player's month-and-day of birth falls after August 31 in the calendar — that is, a birth date later in the year than the August 31 cutoff — one is subtracted. Players born on or before August 31 keep the unsubtracted value. The result is an integer number of years.

The league age drives automatic division assignment: if the standard division whose range covers the player's `league_age` exists among the five — `min_league_age` at or below the age and `max_league_age` at or above it — the player's `division_id` is set to that division. If no standard division covers the age (for example a 17-year-old, or a 3-year-old), `division_id` is left null. The `division_id` may later be overwritten when an approved waiver carries a `target_division_id` (§3.5).

Registration also computes the player's `participation_pct`. When `games_scheduled` is zero the percentage is 0.00. Otherwise it is one hundred times `games_played` divided by `games_scheduled`, rounded half up to two decimal places. The participation threshold used by all-star selection is 60.00, and a player at exactly 60.00 passes. The percentage is computed once at registration and simply re-read later at selection and roster submission.

### 3.4. Eligibility: Documents, Boundaries, Verification, and Revocation

Eligibility rests on documentary evidence. A `LeagueAdministrator` attaches an eligibility document to a player by attesting a `doc_type` — one of `BIRTH_CERTIFICATE`, `RESIDENCE_PROOF`, or `SCHOOL_ENROLLMENT` — together with the document's `issued_date` in YYYY-MM-DD form. Documents are immutable evidence records: they carry an `id` and a `created_at` and nothing else — no `updated_at`, no `version`.

Verification turns a `PENDING` player — or an `INELIGIBLE` one being reinstated — into `ELIGIBLE`, performed by a `LeagueAdministrator` through the player's verify-eligibility action. A player in any other state cannot be verified; the attempt is rejected with `ERR_PLAYER_NOT_VERIFIABLE` (HTTP 409). Four conditions must all hold, evaluated under the temporal and referential rules of the validation ladder.

The first condition is the registration window: the clock date at verification must fall within January 1 through April 30 of the league's `season_year`, inclusive; outside that window the verification is rejected with `ERR_REGISTRATION_WINDOW_CLOSED` (HTTP 422). The second is documentary completeness and freshness: the player must hold at least one `BIRTH_CERTIFICATE` document and at least one document matching the residency basis — a `RESIDENCE_PROOF` when eligibility rests on residence, or a `SCHOOL_ENROLLMENT` when it rests on school attendance. A missing required document yields `ERR_NO_ELIGIBILITY_DOCUMENT` (HTTP 422). In addition, each `RESIDENCE_PROOF` or `SCHOOL_ENROLLMENT` relied upon must have been issued within 365 days before the verification date; a document issued more than 365 days earlier yields `ERR_DOCUMENT_EXPIRED` (HTTP 422). The third condition is boundary satisfaction: at least one of the player's `residence_within_boundary` flag, the player's `school_within_boundary` flag, or an approved residency-boundary waiver whose window covers the current clock date must hold; otherwise the verification is rejected with `ERR_OUTSIDE_BOUNDARY` (HTTP 422). The fourth is division assignment: the player's `division_id` must be non-null — either from automatic assignment at registration or from an approved waiver — and a null `division_id` is rejected with `ERR_AGE_DIVISION_MISMATCH` (HTTP 422).

Revocation runs in the other direction. A `LeagueAdministrator` may revoke eligibility, optionally attaching a `reason`, only for a player currently `ELIGIBLE`; the attempt against any other status is rejected with `ERR_PLAYER_NOT_ELIGIBLE` (HTTP 409). Revocation flips the player to `INELIGIBLE` and fires a deliberate cascade across the tournament side of the system. On every all-star roster holding an `ACTIVE` selection of this player, that selection becomes `VACATED` and the roster's `roster_size` is recomputed; if such a roster was `SUBMITTED` it is recalled to `RECALLED`, while a `LOCKED` roster stays `LOCKED` — a self-loop in which only the selection and the count change (§3.6). Every tournament entry with status `ACTIVE` whose roster contains — or contained — an `ACTIVE` selection of this player is withdrawn, and every still-`SCHEDULED` game of those entries is cancelled. The revocation cascade is the intended serialization point between regular-season eligibility and tournament integrity.

### 3.5. Boundary Waivers: Requests, Overlap, and Effect

When a player falls outside the ordinary rules — living beyond the boundary, needing to play down for safety, or caught on the wrong side of the birth-date cutoff — a `LeagueAdministrator` requests a waiver. The request names the `player_id`, a `waiver_type` of `RESIDENCY_BOUNDARY`, `PLAY_DOWN_SAFETY`, or `BIRTH_DATE_CUTOFF`, a free-text `reason`, and a validity window given as `valid_from` (inclusive) and `valid_until` (exclusive), both YYYY-MM-DD. The end must come strictly after the start; a window that is empty or inverted is rejected with `ERR_INVALID_REQUEST` (HTTP 400). A `target_division_id` naming one of the league's divisions is required for `PLAY_DOWN_SAFETY` and `BIRTH_DATE_CUTOFF` waivers and forbidden for `RESIDENCY_BOUNDARY` waivers; supplying one where forbidden, or omitting one where required, is likewise `ERR_INVALID_REQUEST`.

Because waiver validity is judged against the league's charter posture, the request must also carry `expected_league_version` under the optimistic-concurrency rule of §2.6; a stale version is rejected with `ERR_STALE_VERSION` (HTTP 412). Successful creation puts the waiver in `PENDING` status and bumps the league's `version` by 1.

A `DistrictAdministrator` then decides the waiver with an `action` of `APPROVE`, `DENY`, or `REVOKE`. Approval or denial requires the waiver to be `PENDING`; revocation requires it to be `APPROVED`; any other combination is rejected with `ERR_WAIVER_NOT_PENDING` (HTTP 409). Approval enforces the overlap rule: for the same player and the same `waiver_type`, no other already-`APPROVED` waiver may have a half-open validity window — start inclusive, end exclusive — that intersects this waiver's window. Adjacency is allowed: one waiver ending exactly on the day another begins does not intersect it. A violating approval is rejected with `ERR_WAIVER_OVERLAP` (HTTP 409).

Approval has a targeted side effect: when the waiver carries a `target_division_id` (the `PLAY_DOWN_SAFETY` and `BIRTH_DATE_CUTOFF` cases), the player's `division_id` is overwritten with that division — this is the only mechanism besides registration-time auto-assignment that sets `division_id`, and it is what rescues a player whose league age fell outside every standard range. Denial moves the waiver to `DENIED`, a terminal state. Revocation moves an approved waiver to `REVOKED`, also terminal, and deliberately does not roll back the player's `division_id`; revocation only closes the waiver's future effect on eligibility checks, so a player whose boundary eligibility rested on the revoked waiver will fail the next verification under `ERR_OUTSIDE_BOUNDARY` unless residence or school now qualifies.

### 3.6. All-Star Rosters: Selection, Submission, and Recall

Once the regular season is underway, a `LeagueAdministrator` opens an all-star roster for a division by creating it with the target `division_id`. The roster copies its `season_year` from the league at creation, starts in `OPEN` status with an empty `selections` array, and has a `roster_size` of 0. The `selections` array holds one entry per selected player, each recording the `player_id`, the `selected_at` timestamp, and a per-selection status of `ACTIVE` or `VACATED`. The roster's `roster_size` is maintained as an invariant: it is always exactly the count of selections whose status is `ACTIVE`, recomputed whenever a selection is added or vacated.

Adding a selection is permitted while the roster is `OPEN` or `RECALLED`; against a `SUBMITTED` or `LOCKED` roster the attempt is rejected with `ERR_ROSTER_NOT_OPEN` (HTTP 409). The request names a `player_id`. Within a single add, the checks are evaluated in a pinned order — the player's division match is evaluated before roster capacity. The candidate player must be `ELIGIBLE`, or the add is rejected with `ERR_PLAYER_NOT_ELIGIBLE` (HTTP 409); the player's `division_id` must equal the roster's `division_id`, or the add is rejected with `ERR_PLAYER_DIVISION_MISMATCH` (HTTP 422); the player's `participation_pct` must be at least 60.00 — exactly 60.00 passes — or the add is rejected with `ERR_PARTICIPATION_THRESHOLD_NOT_MET` (HTTP 422); and the add must not push the roster beyond its capacity of 5 active selections, or it is rejected with `ERR_ROSTER_ABOVE_MAXIMUM` (HTTP 422). These bounds — a submittable roster window of 3 to 5 active players — are the benchmark-scale stand-in for the real twelve-to-fourteen-player all-star window. A successful add appends a selection with status `ACTIVE` and recomputes `roster_size`.

Submitting the roster moves it `OPEN` → `SUBMITTED`, or `RECALLED` → `SUBMITTED` when resubmitting after fixing selections, and is the certification that the roster is ready for tournament play. Submission requires a `roster_size` of at least 3, enforced with `ERR_ROSTER_BELOW_MINIMUM` (HTTP 422); every `ACTIVE` selection's player must be `ELIGIBLE`, enforced with `ERR_PLAYER_NOT_ELIGIBLE`; and every `ACTIVE` selection's player must have a `participation_pct` of at least 60.00, enforced with `ERR_PARTICIPATION_THRESHOLD_NOT_MET`.

Two cascades move a roster out of `SUBMITTED` without any direct operator action. When a tournament entry is created against the roster (§3.7), the roster locks: `SUBMITTED` → `LOCKED`, its terminal state. When a player eligibility revocation vacates a selection on a `SUBMITTED` roster (§3.4), the roster is recalled: `SUBMITTED` → `RECALLED`, its `roster_size` recomputed, and the league administrator must repair and resubmit it. On a `LOCKED` roster the same revocation leaves the status untouched — a `LOCKED` → `LOCKED` self-loop in which the selection becomes `VACATED`, `roster_size` is recomputed, and the roster stays locked while the withdrawal cascade plays out on the tournament entry instead.

### 3.7. Tournament Entries, Games, and the Pitch-Count Safety Regime

Tournament play begins when a `TournamentDirector` enters a roster into competition by creating an entry with the `roster_id` and the `level` — one of `DISTRICT`, `SECTIONAL`, `STATE`, or `REGIONAL`. The roster must be `SUBMITTED`; any other roster status is rejected with `ERR_ROSTER_NOT_SUBMITTED` (HTTP 409). Levels form a strict ladder: an entry at any level other than `DISTRICT` requires an already-`ADVANCED` entry at the immediately preceding level within the same league — `SECTIONAL` follows `DISTRICT`, `STATE` follows `SECTIONAL`, `REGIONAL` follows `STATE` — and a request missing that prerequisite is rejected with `ERR_ADVANCEMENT_PREREQUISITE_NOT_MET` (HTTP 409). Creating the entry computes its `elimination_format`: `DOUBLE_ELIMINATION` for `DISTRICT` and `SECTIONAL`, `SINGLE_ELIMINATION` for `STATE` and `REGIONAL`. The new entry starts `ACTIVE` with a `losses_count` of 0, and creation locks the source roster (`SUBMITTED` → `LOCKED`).

Games are scheduled against an `ACTIVE` entry by the `TournamentDirector`, optionally naming an `opponent_entry_id`; when supplied, the opponent must be an `ACTIVE` entry at the same level, and violations surface as `ERR_ENTRY_NOT_ACTIVE`. Any operation that requires an `ACTIVE` entry — scheduling a game, recording an appearance, finalizing, filing a protest, advancing — rejects a non-active entry with `ERR_ENTRY_NOT_ACTIVE` (HTTP 409). A new game starts with `play_status` `SCHEDULED`, `protest_status` `NONE`, a `recorded_pitch_total` of 0, and null `game_date`, `our_score`, `opponent_score`, and `result`.

The game starts itself: when an `OfficialScorer` records the first pitching appearance against a `SCHEDULED` game, the game moves to `IN_PROGRESS` and its `game_date` is set to the current clock date. Recording an appearance names a `player_id` and the reported `pitches_thrown`, which must be at least 1; the player must hold an `ACTIVE` selection on the roster of the entry the game belongs to, or the recording is rejected with `ERR_PLAYER_NOT_ON_ROSTER` (HTTP 422). Appearances are accepted while the game is `SCHEDULED` or `IN_PROGRESS`; against any other play status the recording is rejected with `ERR_GAME_NOT_IN_PROGRESS` (HTTP 409). The recorded `appearance_date` is the current clock date.

Three safety rules govern every appearance, and they are the heart of the pitch-count regime. First, the cap: at recording time, the reported `pitches_thrown` must not exceed the pitch maximum of the player's division — 50 for `TEE_BALL`, 75 for `MINOR`, 85 for `MAJOR`, 95 for `JUNIOR`, and 95 for `SENIOR` — or the recording is rejected with `ERR_PITCH_COUNT_EXCEEDED` (HTTP 422). Second, the rest tier: the appearance's `rest_days_required` is computed from the effective pitch count, which at recording time is simply `pitches_thrown`. The tiers are closed intervals: 1 through 20 pitches require 0 rest days, 21 through 35 require 1 day, 36 through 50 require 2 days, 51 through 65 require 3 days, and 66 pitches up to and including the division maximum require 4 days. The appearance's `eligible_again_on` is the `appearance_date` plus `rest_days_required` days. Third, the rest gate: recording a new appearance for a player is rejected with `ERR_REST_REQUIREMENT_VIOLATION` (HTTP 409) when the clock date falls strictly before the `eligible_again_on` of that player's latest `RECORDED` appearance — latest by `appearance_date`, with ties broken by `created_at` ascending so that the appearance with the later `created_at` counts as the latest. A recording that passes all three rules recomputes the game's `recorded_pitch_total` and bumps the game's `version` by 1.

Finalization certifies the result. A `TournamentDirector` finalizes an `IN_PROGRESS` game by supplying `our_score`, `opponent_score`, the optimistic-concurrency field `expected_game_version` (§2.6), and optionally `scorebook_corrections` — an array of entries each naming an `appearance_id` and an `official_pitches` value. A finalization against a game not `IN_PROGRESS` is rejected with `ERR_GAME_NOT_IN_PROGRESS`. The league the entry belongs to must hold an `ACTIVE` insurance certificate whose coverage window contains the clock date of finalization, or the finalize is rejected with `ERR_INSURANCE_NOT_ACTIVE` (HTTP 409). The two scores must differ; a tied score is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Corrections are applied before the result is computed: each correction writes `official_pitches` onto the named appearance (null until corrected), and for that appearance the effective pitch count becomes the `official_pitches` value rather than `pitches_thrown`; the `rest_days_required` and `eligible_again_on` are recomputed from the corrected count using the same tier table, so a correction that crosses a tier boundary — say from 60 to 70 pitches — changes the same appearance's rest window. After corrections, every `RECORDED` appearance's effective count is re-checked against the player's division maximum, and any excess is rejected with `ERR_PITCH_COUNT_EXCEEDED`. Finalization then records `our_score` and `opponent_score` on the game, computes the `result` — `WIN` when our score is greater, `LOSS` otherwise — moves the game to `FINAL`, recomputes `recorded_pitch_total`, and bumps the game's `version` by 1. The `recorded_pitch_total` is always exactly the sum over the game's `RECORDED` appearances of each appearance's effective count — `official_pitches` when set, else `pitches_thrown` — with `REVERSED` appearances contributing zero.

A `LOSS` result triggers the elimination evaluation. The entry's `losses_count` increments by 1, and when it reaches the elimination limit — 1 loss for `SINGLE_ELIMINATION`, 2 losses for `DOUBLE_ELIMINATION` — the entry cascades from `ACTIVE` to `ELIMINATED` and every remaining `SCHEDULED` game of that entry is cancelled (`SCHEDULED` → `CANCELLED`).

Advancement is the explicit reward for survival. A `TournamentDirector` advances an `ACTIVE` entry when it has at least one `FINAL` game with result `WIN` at its level, its `losses_count` is below the elimination limit for its format, and none of its games has a protest still `OPEN` — an open protest blocks advancement, surfaced as `ERR_PROTEST_NOT_OPEN` (HTTP 409). An entry already at `REGIONAL` cannot advance further; the attempt is rejected with `ERR_ALREADY_HIGHEST_LEVEL` (HTTP 409). An entry that fails the win or losses prerequisites is rejected with `ERR_ADVANCEMENT_PREREQUISITE_NOT_MET`. A successful advance moves the entry to `ADVANCED`, a terminal state, and it is that `ADVANCED` marker at level N that licenses the league's entry at level N+1.

### 3.8. Protests, Volunteers, Insurance, and the Suspension Cascade

A game carries two independent status dimensions: `play_status` (`SCHEDULED`, `IN_PROGRESS`, `FINAL`, `CANCELLED`) and, in parallel, `protest_status` (`NONE`, `OPEN`, `RESOLVED`). A `TournamentDirector` files a protest against a game that is `IN_PROGRESS` or `FINAL`, but only while its `protest_status` is `NONE`; filing against a game with a protest already open is rejected with `ERR_DUPLICATE_OPEN_PROTEST` (HTTP 409). The filing names a `protest_type` of `RULE_INTERPRETATION` or `ELIGIBILITY_CHALLENGE` and free-text `grounds`; a `target_player_id` is required for an `ELIGIBILITY_CHALLENGE` and forbidden for a `RULE_INTERPRETATION`, with violations rejected as `ERR_INVALID_REQUEST` (HTTP 400). Filing moves the game's `protest_status` to `OPEN` and the new protest starts in `FILED` status.

Resolution comes from a `TournamentDirector` acting on a `FILED` protest with an `action` of `UPHOLD`, `OVERTURN`, or `WITHDRAW`. Resolution requires both that the protest is `FILED` and that the game's `protest_status` is `OPEN`; otherwise the attempt is rejected with `ERR_PROTEST_NOT_OPEN` (HTTP 409). All three resolutions move the game's `protest_status` to `RESOLVED`, but their downstream effects differ by branch.

Upholding a `RULE_INTERPRETATION` protest reopens the game: a `FINAL` game moves back to `IN_PROGRESS`, its `result` is cleared to null, and `our_score`/`opponent_score` are retained on the record but no longer authoritative. If the voided result had been a `LOSS`, the entry's `losses_count` is decremented by 1, and if that loss had previously pushed the entry to `ELIMINATED` by reaching the elimination limit, the entry is restored from `ELIMINATED` to `ACTIVE`. Because the game has reopened, its `protest_status` is then reset from `RESOLVED` to `NONE`, so the game can be protested again. When the upheld protest targets a game still `IN_PROGRESS`, only the protest-status bookkeeping applies. Upholding an `ELIGIBILITY_CHALLENGE` instead strikes the player: every `RECORDED` pitching appearance of the protest's `target_player_id` in that game moves to `REVERSED`, the game's `recorded_pitch_total` is recomputed excluding the reversed appearances, and the game itself stays where it is. Overturning a protest lets everything stand — the game result, counters, and appearances are unchanged; only the protest moves to `OVERTURNED` and the game's `protest_status` to `RESOLVED`. Withdrawing a protest moves the protest to `WITHDRAWN` and likewise resolves the game's protest status without touching anything else. `UPHELD`, `OVERTURNED`, and `WITHDRAWN` are all terminal for the protest.

Adults are policed with the same rigor as players. A `LeagueAdministrator` registers a volunteer with a `full_name` and a `role_title` of `MANAGER`, `COACH`, `UMPIRE`, `BOARD_MEMBER`, or `CONCESSIONS`; the volunteer starts `REGISTERED`. The administrator then submits a background screening for the volunteer, naming an `offense_category` — `NONE`, `NONVIOLENT_MISDEMEANOR`, `VIOLENT_FELONY`, `SEXUAL_OFFENSE`, or `CHILD_ABUSE` — and a validity window `valid_from` through `valid_through`, both YYYY-MM-DD, with the end at or after the start. At submission the screening computes `auto_flagged`: true exactly when the `offense_category` is one of `VIOLENT_FELONY`, `SEXUAL_OFFENSE`, or `CHILD_ABUSE`. The screening starts `SUBMITTED`.

A `DistrictAdministrator` adjudicates a `SUBMITTED` screening with an `action` of `APPROVE` or `DISQUALIFY`; adjudicating a screening in any other state is rejected with `ERR_SCREENING_NOT_ADJUDICATABLE` (HTTP 409). Approval carries two gates: the screening's window from `valid_from` through `valid_through`, inclusive, must fully contain the season window from March 1 through October 31 of the league's `season_year`, or the approval is rejected with `ERR_SCREENING_WINDOW_INCOMPLETE` (HTTP 422); and the `offense_category` must not be one of the three severe categories — `VIOLENT_FELONY`, `SEXUAL_OFFENSE`, `CHILD_ABUSE` — or the approval is rejected with `ERR_DISQUALIFYING_OFFENSE` (HTTP 422). An approved screening becomes `CLEARED` and flips the volunteer from `REGISTERED` to `CLEARED`. A disqualification moves the screening to `DISQUALIFIED` and the volunteer from `REGISTERED` to `DISQUALIFIED`, which is terminal for the volunteer.

Insurance is the league's standing proof of coverage. A `DistrictAdministrator` records an insurance certificate with a `carrier_name` and a coverage window `coverage_start` through `coverage_end`, both YYYY-MM-DD and inclusive, with the end at or after the start. The certificate starts `ACTIVE` and remains so until the logical clock's date moves past `coverage_end`, at which point the clock sweep flips it to `EXPIRED`, its terminal state. Two business gates depend on an `ACTIVE` certificate, as described where they live: charter-renewal approval requires one whose window contains the whole season window (§3.2), and game finalization requires one whose window contains the clock date of the finalize (§3.7); both failures surface as `ERR_INSURANCE_NOT_ACTIVE`.

Finally, the suspension cascade ties the season cycle closed. When the clock sweep of §2.5 detects that a `CHARTERED` league's latest approved renewal covers season Y, the new clock date falls after March 31 of season Y+1, and no approved renewal for season Y+1 exists, the league moves `CHARTERED` → `SUSPENDED`. The cascade then runs in order: every `ACTIVE` division of the league becomes `SUSPENDED`; every `ACTIVE` tournament entry of the league becomes `WITHDRAWN`; every still-`SCHEDULED` game of those withdrawn entries becomes `CANCELLED`; and the league's `version` increments by 1. Reinstatement is possible only through a new approved renewal (§3.2), which flips the divisions back to `ACTIVE` but leaves the withdrawn entries withdrawn — tournament participation is never resurrected retroactively.

## 4. Endpoint Definitions

All endpoints are mounted under the top-level `/leagues` prefix family shown in the paths below, with tournament-game operations under `/tournament-entries` and the clock capability under `/_clock`. Status-code rules are uniform: an operation that creates a new resource responds 201; an operation that modifies, decides, or transitions an existing resource responds 200; list and detail reads respond 200. Errors use the codes and HTTP statuses of §5. The table intentionally lists only method, path, a one-line description, and the authorized roles — request and response payloads are defined by the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /leagues | Create a league; auto-creates the five standard divisions in fixed creation order (TEE_BALL, MINOR, MAJOR, JUNIOR, SENIOR), charter starts PROVISIONAL | DistrictAdministrator |
| GET | /leagues | List leagues | DistrictAdministrator, LeagueAdministrator, TournamentDirector, OfficialScorer |
| GET | /leagues/{leagueId} | Get a single league | DistrictAdministrator, LeagueAdministrator, TournamentDirector, OfficialScorer |
| POST | /leagues/{leagueId}/charter-renewals | Submit a charter renewal; computes window classification and provisional fee | LeagueAdministrator |
| GET | /leagues/{leagueId}/charter-renewals | List charter renewals of a league | DistrictAdministrator, LeagueAdministrator, TournamentDirector, OfficialScorer |
| POST | /leagues/{leagueId}/charter-renewals/{renewalId}/decide | Approve or reject a SUBMITTED renewal; approval computes the final fee and charters the league | DistrictAdministrator |
| GET | /leagues/{leagueId}/divisions | List divisions of a league (created_at ascending, fixed creation order tie-break) | DistrictAdministrator, LeagueAdministrator, TournamentDirector, OfficialScorer |
| PATCH | /leagues/{leagueId}/divisions/{divisionId} | Set a division's team count; recomputes the league's total | LeagueAdministrator |
| POST | /leagues/{leagueId}/players | Register a player; computes league age, division assignment, and participation percentage | LeagueAdministrator |
| GET | /leagues/{leagueId}/players | List players of a league; filterable by division_id and eligibility_status | DistrictAdministrator, LeagueAdministrator, TournamentDirector, OfficialScorer |
| POST | /leagues/{leagueId}/players/{playerId}/eligibility-documents | Attach an eligibility document to a player | LeagueAdministrator |
| GET | /leagues/{leagueId}/players/{playerId}/eligibility-documents | List a player's eligibility documents | DistrictAdministrator, LeagueAdministrator, TournamentDirector, OfficialScorer |
| POST | /leagues/{leagueId}/players/{playerId}/verify-eligibility | Verify a PENDING or INELIGIBLE player into ELIGIBLE | LeagueAdministrator |
| POST | /leagues/{leagueId}/players/{playerId}/revoke-eligibility | Revoke an ELIGIBLE player; cascades to rosters, entries, and games | LeagueAdministrator |
| POST | /leagues/{leagueId}/boundary-waivers | Request a boundary/safety/cutoff waiver (OCC via expected_league_version) | LeagueAdministrator |
| GET | /leagues/{leagueId}/boundary-waivers | List boundary waivers of a league; filterable by player_id and target_division_id | DistrictAdministrator, LeagueAdministrator, TournamentDirector, OfficialScorer |
| POST | /leagues/{leagueId}/boundary-waivers/{waiverId}/decide | Approve, deny, or revoke a waiver; approval applies target division and overlap rule | DistrictAdministrator |
| POST | /leagues/{leagueId}/volunteers | Register a volunteer | LeagueAdministrator |
| GET | /leagues/{leagueId}/volunteers | List volunteers of a league | DistrictAdministrator, LeagueAdministrator, TournamentDirector, OfficialScorer |
| POST | /leagues/{leagueId}/volunteers/{volunteerId}/screenings | Submit a background screening; computes auto_flagged | LeagueAdministrator |
| POST | /leagues/{leagueId}/volunteers/{volunteerId}/screenings/{screeningId}/adjudicate | Approve or disqualify a SUBMITTED screening; updates the volunteer | DistrictAdministrator |
| GET | /leagues/{leagueId}/volunteers/{volunteerId}/screenings | List a volunteer's screenings | DistrictAdministrator, LeagueAdministrator, TournamentDirector, OfficialScorer |
| POST | /leagues/{leagueId}/insurance-certificates | Record an insurance certificate (ACTIVE) | DistrictAdministrator |
| GET | /leagues/{leagueId}/insurance-certificates | List insurance certificates of a league | DistrictAdministrator, LeagueAdministrator, TournamentDirector, OfficialScorer |
| POST | /leagues/{leagueId}/all-star-rosters | Create an all-star roster for a division (OPEN) | LeagueAdministrator |
| GET | /leagues/{leagueId}/all-star-rosters | List all-star rosters of a league; filterable by division_id | DistrictAdministrator, LeagueAdministrator, TournamentDirector, OfficialScorer |
| POST | /leagues/{leagueId}/all-star-rosters/{rosterId}/selections | Add a player selection to an OPEN or RECALLED roster | LeagueAdministrator |
| POST | /leagues/{leagueId}/all-star-rosters/{rosterId}/submit | Submit an OPEN or RECALLED roster for tournament eligibility | LeagueAdministrator |
| POST | /leagues/{leagueId}/tournament-entries | Enter a SUBMITTED roster into a tournament level; locks the roster | TournamentDirector |
| GET | /leagues/{leagueId}/tournament-entries | List tournament entries of a league; filterable by roster_id | DistrictAdministrator, LeagueAdministrator, TournamentDirector, OfficialScorer |
| POST | /tournament-entries/{entryId}/games | Schedule a game for an ACTIVE entry | TournamentDirector |
| GET | /tournament-entries/{entryId}/games | List games of an entry; filterable by opponent_entry_id | DistrictAdministrator, LeagueAdministrator, TournamentDirector, OfficialScorer |
| POST | /tournament-entries/{entryId}/games/{gameId}/pitching-appearances | Record a pitching appearance; auto-starts the game; enforces safety rules | OfficialScorer |
| GET | /tournament-entries/{entryId}/games/{gameId}/pitching-appearances | List pitching appearances of a game; filterable by player_id | DistrictAdministrator, LeagueAdministrator, TournamentDirector, OfficialScorer |
| POST | /tournament-entries/{entryId}/games/{gameId}/finalize | Finalize an IN_PROGRESS game with the official score (OCC via expected_game_version) | TournamentDirector |
| POST | /tournament-entries/{entryId}/games/{gameId}/protests | File a protest on an IN_PROGRESS or FINAL game | TournamentDirector |
| GET | /tournament-entries/{entryId}/games/{gameId}/protests | List protests of a game; filterable by player_id | DistrictAdministrator, LeagueAdministrator, TournamentDirector, OfficialScorer |
| POST | /tournament-entries/{entryId}/games/{gameId}/protests/{protestId}/resolve | Resolve a FILED protest (UPHOLD, OVERTURN, WITHDRAW) | TournamentDirector |
| POST | /tournament-entries/{entryId}/advance | Advance an ACTIVE entry to the next tournament level | TournamentDirector |
| POST | /_clock/set_current_utc | Set the logical clock; runs the charter-lapse and insurance-expiry sweeps | DistrictAdministrator |
| GET | /leagues/charter-renewals | Cross-league filtered list of charter renewals; filterable by league_id | DistrictAdministrator, LeagueAdministrator, TournamentDirector, OfficialScorer |
| GET | /leagues/divisions | Cross-league filtered list of divisions; filterable by league_id | DistrictAdministrator, LeagueAdministrator, TournamentDirector, OfficialScorer |
| GET | /leagues/players | Cross-league filtered list of players; filterable by league_id and division_id | DistrictAdministrator, LeagueAdministrator, TournamentDirector, OfficialScorer |
| GET | /leagues/eligibility-documents | Cross-league filtered list of eligibility documents; filterable by player_id | DistrictAdministrator, LeagueAdministrator, TournamentDirector, OfficialScorer |
| GET | /leagues/boundary-waivers | Cross-league filtered list of boundary waivers; filterable by league_id, player_id, target_division_id | DistrictAdministrator, LeagueAdministrator, TournamentDirector, OfficialScorer |
| GET | /leagues/volunteers | Cross-league filtered list of volunteers; filterable by league_id | DistrictAdministrator, LeagueAdministrator, TournamentDirector, OfficialScorer |
| GET | /leagues/screenings | Cross-league filtered list of background screenings; filterable by volunteer_id | DistrictAdministrator, LeagueAdministrator, TournamentDirector, OfficialScorer |
| GET | /leagues/insurance-certificates | Cross-league filtered list of insurance certificates; filterable by league_id | DistrictAdministrator, LeagueAdministrator, TournamentDirector, OfficialScorer |
| GET | /leagues/all-star-rosters | Cross-league filtered list of all-star rosters; filterable by league_id and division_id | DistrictAdministrator, LeagueAdministrator, TournamentDirector, OfficialScorer |
| GET | /leagues/tournament-entries | Cross-league filtered list of tournament entries; filterable by league_id and roster_id | DistrictAdministrator, LeagueAdministrator, TournamentDirector, OfficialScorer |
| GET | /leagues/games | Cross-league filtered list of tournament games; filterable by entry_id and opponent_entry_id | DistrictAdministrator, LeagueAdministrator, TournamentDirector, OfficialScorer |
| GET | /leagues/pitching-appearances | Cross-league filtered list of pitching appearances; filterable by game_id and player_id | DistrictAdministrator, LeagueAdministrator, TournamentDirector, OfficialScorer |
| GET | /leagues/protests | Cross-league filtered list of protests; filterable by game_id, player_id, target_player_id | DistrictAdministrator, LeagueAdministrator, TournamentDirector, OfficialScorer |
| GET | /leagues/leagues/{leagueId} | League detail | DistrictAdministrator, LeagueAdministrator, TournamentDirector, OfficialScorer |
| GET | /leagues/charter-renewals/{renewalId} | Charter renewal detail | DistrictAdministrator, LeagueAdministrator, TournamentDirector, OfficialScorer |
| GET | /leagues/divisions/{divisionId} | Division detail | DistrictAdministrator, LeagueAdministrator, TournamentDirector, OfficialScorer |
| GET | /leagues/players/{playerId} | Player detail | DistrictAdministrator, LeagueAdministrator, TournamentDirector, OfficialScorer |
| GET | /leagues/eligibility-documents/{documentId} | Eligibility document detail | DistrictAdministrator, LeagueAdministrator, TournamentDirector, OfficialScorer |
| GET | /leagues/boundary-waivers/{waiverId} | Boundary waiver detail | DistrictAdministrator, LeagueAdministrator, TournamentDirector, OfficialScorer |
| GET | /leagues/volunteers/{volunteerId} | Volunteer detail | DistrictAdministrator, LeagueAdministrator, TournamentDirector, OfficialScorer |
| GET | /leagues/screenings/{screeningId} | Background screening detail | DistrictAdministrator, LeagueAdministrator, TournamentDirector, OfficialScorer |
| GET | /leagues/insurance-certificates/{certificateId} | Insurance certificate detail | DistrictAdministrator, LeagueAdministrator, TournamentDirector, OfficialScorer |
| GET | /leagues/all-star-rosters/{rosterId} | All-star roster detail | DistrictAdministrator, LeagueAdministrator, TournamentDirector, OfficialScorer |
| GET | /leagues/tournament-entries/{entryId} | Tournament entry detail | DistrictAdministrator, LeagueAdministrator, TournamentDirector, OfficialScorer |
| GET | /leagues/games/{gameId} | Tournament game detail | DistrictAdministrator, LeagueAdministrator, TournamentDirector, OfficialScorer |
| GET | /leagues/pitching-appearances/{appearanceId} | Pitching appearance detail | DistrictAdministrator, LeagueAdministrator, TournamentDirector, OfficialScorer |
| GET | /leagues/protests/{protestId} | Protest detail | DistrictAdministrator, LeagueAdministrator, TournamentDirector, OfficialScorer |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of §2 and §3; this table lists only identifiers and HTTP statuses.

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_INSUFFICIENT_PERMISSIONS | 403 |
| ERR_INVALID_REQUEST | 400 |
| ERR_LEAGUE_NOT_FOUND | 404 |
| ERR_DIVISION_NOT_FOUND | 404 |
| ERR_PLAYER_NOT_FOUND | 404 |
| ERR_RENEWAL_NOT_FOUND | 404 |
| ERR_WAIVER_NOT_FOUND | 404 |
| ERR_VOLUNTEER_NOT_FOUND | 404 |
| ERR_SCREENING_NOT_FOUND | 404 |
| ERR_ROSTER_NOT_FOUND | 404 |
| ERR_ENTRY_NOT_FOUND | 404 |
| ERR_GAME_NOT_FOUND | 404 |
| ERR_PROTEST_NOT_FOUND | 404 |
| ERR_LEAGUE_NOT_CHARTERED | 409 |
| ERR_RENEWAL_NOT_PENDING | 409 |
| ERR_PLAYER_NOT_VERIFIABLE | 409 |
| ERR_PLAYER_NOT_ELIGIBLE | 409 |
| ERR_WAIVER_NOT_PENDING | 409 |
| ERR_SCREENING_NOT_ADJUDICATABLE | 409 |
| ERR_ROSTER_NOT_OPEN | 409 |
| ERR_ROSTER_NOT_SUBMITTED | 409 |
| ERR_ENTRY_NOT_ACTIVE | 409 |
| ERR_GAME_NOT_IN_PROGRESS | 409 |
| ERR_PROTEST_NOT_OPEN | 409 |
| ERR_DUPLICATE_OPEN_PROTEST | 409 |
| ERR_AGE_DIVISION_MISMATCH | 422 |
| ERR_OUTSIDE_BOUNDARY | 422 |
| ERR_NO_ELIGIBILITY_DOCUMENT | 422 |
| ERR_DOCUMENT_EXPIRED | 422 |
| ERR_REGISTRATION_WINDOW_CLOSED | 422 |
| ERR_RENEWAL_WINDOW_CLOSED | 422 |
| ERR_WAIVER_OVERLAP | 409 |
| ERR_SCREENING_WINDOW_INCOMPLETE | 422 |
| ERR_DISQUALIFYING_OFFENSE | 422 |
| ERR_INSURANCE_NOT_ACTIVE | 409 |
| ERR_LATE_FEE_UNPAID | 402 |
| ERR_PITCH_COUNT_EXCEEDED | 422 |
| ERR_REST_REQUIREMENT_VIOLATION | 409 |
| ERR_ROSTER_BELOW_MINIMUM | 422 |
| ERR_ROSTER_ABOVE_MAXIMUM | 422 |
| ERR_PARTICIPATION_THRESHOLD_NOT_MET | 422 |
| ERR_PLAYER_DIVISION_MISMATCH | 422 |
| ERR_PLAYER_NOT_ON_ROSTER | 422 |
| ERR_ADVANCEMENT_PREREQUISITE_NOT_MET | 409 |
| ERR_ALREADY_HIGHEST_LEVEL | 409 |
| ERR_STALE_VERSION | 412 |
