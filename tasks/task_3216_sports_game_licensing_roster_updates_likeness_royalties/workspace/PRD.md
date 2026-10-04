# Sports Game Licensing API — Product Requirements Document

## 1. Introduction

Sports video games sit at the intersection of three intellectual-property estates: league simulation rights, players-association group likeness rights, and individual rights held by retired players and college athletes under NIL programs. This document specifies the Sports Game Licensing API, which a major sports publisher (in the style of EA Sports) uses to administer those estates across a live-service football/basketball/soccer title. The system tracks license agreements from draft through termination, governs which athletes may appear in the game and at what royalty share, drives weekly roster publications that update player ratings and transactions through a season, schedules and prices live content drops against an in-game virtual currency, sanctions competitive tournament programs with prize administration, and clears audio usage (commentary, music, stadium sound) by region.

The dominant business concern is audit defensibility. Every dollar of royalty owed to a league or union must be reconstructible from a paper trail of statements, holds, recoupments, and audit adjustments, and every athlete whose likeness appears in a shipped build must trace to an active grant whose terms fit inside an active agreement. The publisher's finance controllers compute provisional and final royalty accruals; league and union auditors hold contractual rights to open audit cases within a negotiated window and to file findings that change the accrued number; and rights officers suspend or revoke likeness grants when off-field events demand it, with cascading effects on sellable content and held royalties. Regional editions with censorship directives add a second axis of compliance: a content drop that is lawful globally may be unlawful in a specific region, and vice versa.

The API is mounted under `/licensing`. All behavior described below assumes a logical clock that tests and operators can advance explicitly; time-driven transitions (agreement expiry, grant expiry, audio license lapse, drop end, registration close) evaluate lazily against that clock rather than against wall time.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting operator and `X-User-Role` to specify the operational capacity in which they act. The system recognizes nine distinct roles, spelled exactly as follows: `LicensingAdmin`, `RightsOfficer`, `RosterOperator`, `RosterReviewer`, `LiveOpsManager`, `FinanceController`, `LeagueAuditor`, `UnionAuditor`, and `ComplianceReviewer`. Failure to provide both headers, or providing them in a malformed form, is rejected with `ERR_MISSING_CONTEXT` (HTTP 400). An authenticated caller whose role is not permitted to invoke the requested endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

Every one of the nine roles carries an opaque identity: when `X-User-Role` is `LicensingAdmin`, `RightsOfficer`, `RosterOperator`, `RosterReviewer`, `LiveOpsManager`, `FinanceController`, `LeagueAuditor`, `UnionAuditor`, or `ComplianceReviewer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `submitted_by` on a `RosterBatch`, or as the acting identity examined by segregation-of-duties checks) but does not compare it to any entity's `id`. Ownership checks therefore never reduce to "the caller is the resource"; they reduce to "the caller's role is authorized and, where segregation of duties applies, the caller's `X-User-ID` differs from the prior step's recorded operator id".

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

List endpoints are paginated via query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, accepts a minimum of 1, and refuses values above 100. The `offset` parameter skips a number of leading items and defaults to 0. Both parameters are optional on every list endpoint. Unless otherwise specified, list endpoints return resources sorted by their `created_at` timestamp in ascending order — the earliest-created row appears first. Paginated list responses always populate `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope, so a client can distinguish "empty page" from "no such data" and can compute whether further pages exist.

### 2.4. The Logical Clock and Temporal Semantics

The system does not consult wall-clock time. A logical clock governs every temporal decision in the API: license term containment, exclusivity overlap windows, season opening and closing, drop sale windows, registration windows, embargo dates, and audit windows. At process startup the clock reads exactly `2026-09-01T00:00:00Z`, and it never falls back to wall-clock time on its own. A `LicensingAdmin` may advance the clock to a supplied `to_iso8601` instant through a dedicated administrative capability; the response echoes the new clock reading as `current_utc`. Time-based system transitions — agreement expiry past `term_end_on`, likeness-grant expiry, audio-license lapse, content-drop end at `scheduled_end_at`, tournament registration close at `registration_closes_at` — are evaluated lazily: the next read or write that touches the affected resource observes the new clock and applies any transition whose precondition has become true. Date comparisons throughout this document are inclusive on both bounds unless stated otherwise, and all ISO 8601 dates and datetimes are interpreted in UTC.

### 2.5. Common Resource Properties

Primary resources — `LicenseAgreement`, `Athlete`, `LikenessGrant`, `LiveSeason`, `RosterBatch`, `RosterEntry`, `ContentDrop`, `PlayerWallet`, `TournamentProgram`, `TournamentPrize`, `AudioAsset`, `AudioLicense`, `RegionalEdition`, `RoyaltyStatement`, and `AuditCase` — share a standard envelope of system-managed fields:

- `id` (string): a server-minted UUID, with no type prefix. Path parameters that address a resource carry the entity's `id` under names such as `agreement_id`, `athlete_id`, `grant_id`, `season_id`, `batch_id`, `drop_id`, `wallet_id`, `program_id`, `asset_id`, `license_id`, `edition_id`, `statement_id`, and `case_id`; the value in the path is always the resource's server-minted `id`.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set at creation and never modified thereafter.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): starts at 1 on creation and increments by 1 on every mutation, including state transitions and computed-field reconciliations. This is the value OCC checks compare against.

Two resources break the pattern. `WalletLedgerEntry` is an append-only posting with no in-place mutation, so it carries only `id` and `created_at`; `updated_at` and `version` are absent. `TournamentEntry` likewise records registration facts and a final placement rather than undergoing rich in-place revision, and it too carries only `id` and `created_at` — both `updated_at` and `version` are absent on it as well.

State-machine-bearing entities expose their current state through a dedicated system-managed status field: `agreement_status` on `LicenseAgreement`, `athlete_status` on `Athlete`, `grant_status` on `LikenessGrant`, `season_status` on `LiveSeason`, `batch_status` on `RosterBatch`, `entry_status` on `RosterEntry`, `drop_status` on `ContentDrop`, `wallet_status` on `PlayerWallet`, `program_status` on `TournamentProgram`, `entry_status` on `TournamentEntry`, `prize_status` on `TournamentPrize`, `asset_status` on `AudioAsset`, `license_status` on `AudioLicense`, `edition_status` on `RegionalEdition`, `statement_status` on `RoyaltyStatement`, and `audit_status` on `AuditCase`. These fields are never accepted as client input; only the transitions documented in §3 may move them.

### 2.6. Nested Resource Retrieval and Hierarchical Validation

Many endpoints address a child resource through its parent (a roster batch under a season, a prize row under a tournament program, a royalty statement under an agreement). For any such path, the server validates path identifiers strictly left to right: each identifier must resolve to an existing resource before the next segment is examined, and the first identifier that fails to resolve produces `ERR_NOT_FOUND` (HTTP 404) without examining later segments. The same left-to-right discipline applies to foreign keys carried in the request body: an `athlete_id` or `agreement_id` or `season_id` or `wallet_id` or `program_id` or `asset_id` or `statement_id` that does not resolve is `ERR_NOT_FOUND`, and the server does not proceed to state or fiscal checks against a phantom parent. This principle guarantees that a request failing for both a missing parent and an invalid state reports the missing parent first.

### 2.7. Monetary and Virtual-Currency Precision

Two units of account coexist. Real-money royalty amounts are carried in integer cents — fields such as `minimum_guarantee_cents`, `outstanding_royalty_cents`, `recouped_against_mg_cents`, `gross_sales_cents`, `returns_cents`, `pending_sales_cents`, `accrued_royalty_cents`, `held_royalty_cents`, `paid_royalty_cents`, and `finding_delta_cents` are all integer cent values. In-game currency is carried in integer virtual-currency units — fields such as `vc_balance`, `amount_vc`, `entry_fee_vc`, `prize_pool_vc`, `price_vc`, `projected_amount_vc`, and `final_amount_vc` are integer units. Both units perform internal arithmetic at integer precision; royalty accrual applies a single round-half-up at the final step only, never at intermediate tier or recoupment steps. Prize-pool allocations use a different rounding rule — floor per row, with the residual remainder assigned to the first-place row — because under-allocating the pool is preferable to inventing currency. Royalty rates and share rates are expressed in basis points throughout: a field such as `royalty_rate_bps` of 1200 represents 12.00 percent, and a `share_bps` of 6000 represents a 60 percent pool share.

### 2.8. Optimistic Concurrency Control

Two write endpoints carry an explicit optimistic-concurrency contract; all other endpoints do not take a version field and process mutations unconditionally once their other validations pass.

The first protected write is the roster-batch publication. A publish request must carry `expected_season_version`, a non-optional field equal to the `version` the caller last observed on the parent `LiveSeason`. If the season's current `version` no longer matches — for example because another reviewer has just published a different batch, which legitimately superseded the prior published batch and advanced the season — the publish is rejected with `ERR_STALE_SEASON_VERSION` (HTTP 412), preventing the caller from overwriting a season state it has not observed.

The second protected write is tournament payout finalization. A finalize-payout request must carry `expected_program_version`, a non-optional field equal to the `version` the caller last observed on the parent `TournamentProgram`. If the program's current `version` has advanced — for example because a late registration correction changed the final prize pool — the request is rejected with `ERR_STALE_PROGRAM_VERSION` (HTTP 412). Both fields are mandatory on their respective endpoints; omitting them is a validation failure, not a waived check.

### 2.9. Segregation of Duties

Three workflow choke points require that the acting operator differ from the operator who performed the prior step, even when both operators hold the correct role. First, roster publication: the `RosterReviewer` who publishes a batch must not be the same `X-User-ID` recorded as `submitted_by` on that batch. Second, regional-edition approval: the `ComplianceReviewer` who approves an edition must not be the operator who submitted it for review. Third, audit settlement: the `FinanceController` who settles an audit case must not be the auditor who opened it. A violation of any of these is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409). The intent is audit defensibility: no single operator may both prepare and approve a roster publication, both submit and approve a regional build, or both open and settle a financial audit.

### 2.10. Validation Ordering

When several validations could fail on the same request, the server reports them in a fixed priority order so that callers see a stable, deterministic error surface. The order is: first, authentication context (`ERR_MISSING_CONTEXT`); second, role authorization (`ERR_FORBIDDEN_ROLE`); third, resource existence for path and body identifiers (`ERR_NOT_FOUND`); fourth, shape and range validation of input fields (`ERR_INVALID_INPUT`); fifth, target-state legality for the requested transition (`ERR_INVALID_STATE`); sixth, segregation of duties (`ERR_SEGREGATION_OF_DUTIES`); seventh, cross-entity state preconditions such as agreement-active or athlete-eligible (`ERR_REFERENCE_STATE`); eighth, temporal windows such as term containment, embargo, or audit-window (`ERR_TEMPORAL_CONFLICT`); ninth, fiscal guards such as wallet balance, blocking audits, or prize-share totals (`ERR_FISCAL_BLOCK`); and tenth, optimistic-concurrency staleness (`ERR_STALE_SEASON_VERSION` or `ERR_STALE_PROGRAM_VERSION`). A request that fails on both an invalid state and an insufficient balance therefore reports the state error; a request that fails on both a temporal conflict and a stale version reports the temporal conflict. Domain-specific error identifiers listed in §5 refine these categories where the scaffold names them; where both a generic and a domain-specific identifier could apply, the domain-specific identifier is the one emitted.

## 3. Business Logic & Workflows

### 3.1. License Agreements: Drafting, Activation, and the Exclusivity Rule

A `LicensingAdmin` opens a relationship with a league, players association, or college body by creating a `LicenseAgreement`. The creation payload carries the `licensor_type` (one of `LEAGUE`, `PLAYERS_ASSOCIATION`, or `COLLEGE_BODY`), the human-facing `licensor_name`, the `exclusivity_scope` (one of `NONE`, `CATEGORY`, or `FULL`), the `sport_category` the agreement covers (for example `AMFOOT_PRO`, `BASKET_PRO`, or `SOCCER_INTL`), the inclusive term bounds `term_start_on` and `term_end_on`, the `royalty_model` (one of `PERCENT_OF_NET`, `PER_UNIT`, or `HYBRID`), the base `royalty_rate_bps`, the `minimum_guarantee_cents` owed over the term, whether the guarantee `mg_recoupable` against future accruals, and the `audit_window_days` the licensor retains after each statement finalizes. The new agreement begins in `DRAFT` with `outstanding_royalty_cents` at 0 and `recouped_against_mg_cents` at 0.

Activation moves the agreement from `DRAFT` to `ACTIVE` and is the moment exclusivity is enforced. The activation succeeds only when the current clock date falls within the agreement's inclusive term — that is, on or after `term_start_on` and on or before `term_end_on` — and, for agreements whose `exclusivity_scope` is `CATEGORY` or `FULL`, when no other agreement already in `ACTIVE` or `SUSPENDED` covers the same `sport_category` with a non-`NONE` exclusivity scope over a date interval that intersects this one's term with an intersection of more than zero days. Two terms that abut — one ending on a given date and the other starting the next day — do not conflict; two terms that share even a single calendar date do, because both bounds are inclusive. A conflict is rejected with `ERR_EXCLUSIVITY_CONFLICT` (HTTP 409); a clock date outside the term is `ERR_TEMPORAL_CONFLICT`. Successful activation increments the agreement's `version`.

Suspension, reinstatement, expiry, and termination form the rest of the agreement lifecycle. Suspending an `ACTIVE` agreement moves it to `SUSPENDED` and triggers a broad cascade described in §3.2 and §3.4: every `GRANTED` likeness grant under the agreement moves to `SUSPENDED` with `suspended_reason` set to `AGREEMENT_SUSPENDED`, every `RELEASED` content drop whose featured athlete has thereby lost all granted coverage moves to `HELD`, and `held_royalty_cents` on the open royalty statement increases by the held-attribution amount computed in §3.8. Reinstating a `SUSPENDED` agreement — permitted only while the clock date is still on or before `term_end_on`, else `ERR_TEMPORAL_CONFLICT` — restores grants whose `suspended_reason` is `AGREEMENT_SUSPENDED` back to `GRANTED`, returns the affected `HELD` drops to `RELEASED`, and unwinds `held_royalty_cents` correspondingly; each of these steps also increments the agreement's `version`. When the clock passes `term_end_on`, an `ACTIVE` agreement expires on its own: the system moves it to `EXPIRED`, moves any `LIVE` season governed by it to `SUNSET`, ends any `RELEASED` drop under those seasons, and expires the `GRANTED` likeness grants beneath it. Termination is a separate, deliberate act: a `SUSPENDED` agreement may be moved to the terminal `TERMINATED` state by a `LicensingAdmin`, but only when no `AuditCase` on the agreement sits in `OPEN` or `FINDINGS_FILED` — otherwise the request fails with `ERR_AUDIT_BLOCKS_TERMINATION`. Termination moves the grants beneath the agreement to `REVOKED`, moves its `PRELAUNCH` or `LIVE` seasons to `ARCHIVED`, and cancels every drop that is not already `ENDED` or `CANCELED`.

### 3.2. Athletes, Likeness Grants, and the NIL Opt-In

A `RightsOfficer` registers each `Athlete` with a `full_name`, a `sport_category`, an `athlete_class` of `ACTIVE_PRO`, `RETIRED`, or `COLLEGE`, and a `college_opt_in` flag. The flag must be false unless the class is `COLLEGE`; for a college athlete it is true only when the athlete has opted in under the NIL program. A newly registered athlete has `athlete_status` of `INELIGIBLE` and a null `current_overall_rating`; only roster publication populates the rating.

A likeness grant binds an athlete to an agreement. The creation payload identifies the `athlete_id` and the `agreement_id`, names the `grant_kind` (`GROUP_PA` for players-association group rights, `INDIVIDUAL_RETIRED` for retired-player individual deals, or `NIL_COLLEGE` for college athletes), supplies inclusive grant term bounds `term_start_on` and `term_end_on`, the athlete's `royalty_share_bps` of the likeness pool, and the `payment_destination` remittance reference. The grant begins in `PENDING`. Granting the likeness — the explicit `PENDING → GRANTED` step — requires three things in order: the referenced agreement must currently be `ACTIVE` (otherwise `ERR_REFERENCE_STATE`); the athlete must exist and, when the athlete's class is `COLLEGE`, `college_opt_in` must be true (a missing opt-in surfaces `ERR_COLLEGE_OPT_IN_REQUIRED`, while a missing eligibility basis more generally surfaces `ERR_ATHLETE_NOT_ELIGIBLE`); and the grant's inclusive term must be contained within the agreement's inclusive term — a grant whose start precedes the agreement's start or whose end follows the agreement's end is rejected with `ERR_GRANT_TERM_OUTSIDE_AGREEMENT`. Once at least one grant for an athlete is `GRANTED`, the athlete's `athlete_status` becomes `ELIGIBLE`.

Suspension, reinstatement, and revocation are the operational levers. A `RightsOfficer` may suspend a `GRANTED` grant, supplying a `suspended_reason`; the same transition fires as a cascade when the parent agreement is suspended, in which case the system writes `AGREEMENT_SUSPENDED` as the reason. Suspension moves the athlete to `INELIGIBLE` when no other `GRANTED` grant remains for that athlete, moves every `RELEASED` drop featuring the athlete to `HELD` (blocking further purchases), and increases `held_royalty_cents` on the agreement's open royalty statement by the per-athlete held amount computed from the current accrued figure and the grant's `royalty_share_bps`. Reinstatement is the mirror image: a `SUSPENDED` grant returns to `GRANTED` provided its agreement is `ACTIVE`, the athlete returns to `ELIGIBLE`, drops `HELD` because of this grant return to `RELEASED`, and `held_royalty_cents` decreases correspondingly. Revocation is terminal and one-way: only a `SUSPENDED` grant may be moved to `REVOKED`, the athlete drops to `INELIGIBLE` if no other grant remains, and drops held for this athlete move to `CANCELED` rather than back to `RELEASED`. Finally, a `GRANTED` grant whose `term_end_on` passes moves to `EXPIRED`, dropping the athlete to `INELIGIBLE` if it was the last granted coverage.

### 3.3. Live Seasons and Roster Operations

A `LiveOpsManager` stands up a season by creating a `LiveSeason` with a `title_code` (for example `PIGSKIN26`), a `sport_category`, a human `season_label` such as `2026-27`, the `agreement_id` of the governing license, and the `season_opens_on` and `season_closes_on` dates. The new season is `PRELAUNCH` with `roster_epoch` at 0.

Roster publication follows a strict operator/reviewer split. A `RosterOperator` creates a `RosterBatch` under a season with a `batch_label` such as `WEEK_05_UPDATE` and the operator's own id recorded in `submitted_by`; the batch starts in `DRAFT`. The operator then appends `RosterEntry` rows — each with an `athlete_id`, an `entry_kind` of `ADD`, `UPDATE_ATTRIBUTE`, `TRANSACTION`, `REMOVE`, or `APPEARANCE`, an `overall_rating` required for `ADD` and `UPDATE_ATTRIBUTE`, and a free-text `transaction_detail` for `TRANSACTION` entries recording trades, injured-reserve moves, or suspensions. New entries are `STAGED`. Validation moves the batch from `DRAFT` to `VALIDATED`; it requires at least one entry (an empty batch is `ERR_EMPTY_BATCH`), every referenced athlete must exist, every athlete referenced by an `ADD` or `UPDATE_ATTRIBUTE` entry must currently be `ELIGIBLE` (an ineligible athlete surfaces `ERR_ATHLETE_NOT_ELIGIBLE`), and every `overall_rating` must lie in the inclusive range 40 through 99 (a violation surfaces `ERR_INVALID_INPUT`).

A `RosterReviewer` then acts. Rejection — permitted from either `DRAFT` or `VALIDATED` — moves the batch to `REJECTED` and drops every entry to `DROPPED`. Publication is heavier: the batch must be `VALIDATED`, the request must carry `expected_season_version` matching the season's current `version` per §2.8, and the reviewer's id must differ from `submitted_by` (a self-publish is `ERR_SEGREGATION_OF_DUTIES`). On a successful publish the season's `roster_epoch` increments by 1 and the batch's `published_epoch` is set to the new value; the previously `PUBLISHED` batch for the season, if any, moves to `SUPERSEDED` with the new batch's `supersedes_batch_id` pointing back at it (the first publish leaves `supersedes_batch_id` null); each entry moves from `STAGED` to `APPLIED`; and for every `ADD` or `UPDATE_ATTRIBUTE` entry the athlete's `current_overall_rating` is set to the entry's `overall_rating`. When the same athlete is rated by multiple entries in one batch, the entries apply in `created_at` ascending order and the chronologically last write wins — ties are broken only by `created_at`, never by id. Publication also increments the season's `version`.

Rollback undoes the most recent publication. A batch may roll back only while it is `PUBLISHED` and is the head — its `published_epoch` equals the season's current `roster_epoch`. Attempting rollback on any other batch is `ERR_ROLLBACK_NOT_HEAD`. A successful rollback moves the head batch to `ROLLED_BACK`, returns the batch named by its `supersedes_batch_id` from `SUPERSEDED` to `PUBLISHED`, reverts every athlete's `current_overall_rating` to the value the superseded batch had applied, and decrements the season's `roster_epoch` by 1.

Launch, sunset, and archive complete the season lifecycle. Launching moves a `PRELAUNCH` season to `LIVE` and requires the governing agreement to be `ACTIVE` (otherwise `ERR_REFERENCE_STATE`), the clock date to be on or after `season_opens_on` (otherwise `ERR_TEMPORAL_CONFLICT`), and at least one batch of the season to be `PUBLISHED`; it increments the season's `version`. Sunsetting a `LIVE` season — either by explicit operator action or as a cascade from agreement expiry — ends every `RELEASED` drop, freezes every `OPEN` wallet, and cancels every tournament program still in `ANNOUNCED` or `REGISTRATION_OPEN`, refunding entry fees via `REFUND` credits. Archiving is permitted from `SUNSET` only when no tournament program of the season remains in `REGISTRATION_OPEN`, `REGISTRATION_CLOSED`, or `COMPLETED` — each must be `PAYOUT_FINALIZED` or `CANCELED` — and when no royalty statement on the governing agreement sits in `OPEN`, `PROVISIONAL`, or `DISPUTED`; a successful archive moves the season to `ARCHIVED` and moves every `FROZEN` wallet to `CLOSED`.

### 3.4. Content Drops, Wallets, and the In-Game Economy

Live content is scheduled per season. A `LiveOpsManager` creates a `ContentDrop` with a `season_id`, a `drop_kind` of `ITEM_PACK`, `PLAYER_CARD`, `VANITY`, or `STADIUM_THEME`, a `drop_label`, an optional `featured_athlete_id` (required exactly when the kind is `PLAYER_CARD`, null otherwise), a `price_vc` in virtual currency (0 for free drops), and the sale window `scheduled_start_at` to `scheduled_end_at`. The drop begins in `SCHEDULED`. Releasing a drop moves it to `RELEASED` and requires the parent season to be `LIVE`, the clock datetime to fall at or after `scheduled_start_at` and strictly before `scheduled_end_at` — outside that half-open window the release is rejected with `ERR_DROP_WINDOW` — and, for a `PLAYER_CARD`, the featured athlete must be `ELIGIBLE`. A further global constraint guards regional compliance: no `RELEASED` `RegionalEdition` of the parent season may carry a censorship flag that conflicts with the drop's content; releasing into such a conflict is `ERR_CENSORSHIP_CONFLICT`.

A drop's downstream states are mostly cascading. When the featured athlete loses all granted coverage — via grant suspension or agreement suspension — a `RELEASED` drop moves to `HELD` and purchases of it are blocked. Reinstatement returns a `HELD` drop to `RELEASED`. Revocation moves a `HELD` drop to the terminal `CANCELED`, as does a manual cancel from either `SCHEDULED` or `HELD`. When the clock reaches `scheduled_end_at`, or when the parent season sunsets, a `RELEASED` drop moves to the terminal `ENDED`.

Wallets scope the in-game economy to a season. Opening a `PlayerWallet` requires a `season_id` and an external `owner_tag`; the wallet starts `OPEN` with `vc_balance` at 0. A wallet's balance is never stored as a mutable counter — it is recomputed from the ledger: the sum of `CREDIT` amounts minus the sum of `DEBIT` amounts across all `POSTED` entries. Every `WalletLedgerEntry` is append-only and immediately `POSTED`, carrying a `wallet_id`, a `direction` of `CREDIT` or `DEBIT`, a strictly positive `amount_vc`, a `reason_code` of `GRANT`, `PURCHASE`, `SPEND_DROP`, `REFUND`, `CLAWBACK`, or `PRIZE_PAYOUT`, and an optional `reference_id` naming a related drop or prize. A debit may post only while the wallet is `OPEN` and only when the wallet's current balance is at least the debit's `amount_vc`; an attempt against a `FROZEN` wallet is `ERR_WALLET_FROZEN`, and an attempt exceeding the balance is `ERR_INSUFFICIENT_VC` (HTTP 422). This compensating invariant guarantees `vc_balance` never goes negative, and a `SPEND_DROP` debit paired with a `REFUND` credit of equal `amount_vc` restores the prior balance exactly. A `REFUND` credit whose `reference_id` names a `TournamentEntry` additionally flips that entry's `fee_paid` flag to false.

Freezing a wallet — by explicit operator action or as a cascade from season sunset — moves it from `OPEN` to `FROZEN` and blocks all subsequent debits. Unfreezing returns a `FROZEN` wallet to `OPEN` only while the parent season is `LIVE`; otherwise the request fails with `ERR_REFERENCE_STATE`. Wallet closure is terminal and cascades from season archive.

Purchasing a drop is the cross-entity operation where drop, wallet, and ledger meet. The caller supplies a `wallet_id`; the target drop must be `RELEASED`, the wallet must be `OPEN`, and the balance must cover `price_vc`. A successful purchase posts a `SPEND_DROP` `DEBIT` ledger entry and decreases `vc_balance` accordingly.

### 3.5. Tournament Programs, Entries, and Prize Administration

Competitive play runs under tournament programs. A `LiveOpsManager` announces a `TournamentProgram` with a `season_id`, a `program_label` such as `LEAGUE_CUP_Q3`, a `league_sanctioned` flag (true only when the governing league sanctions the program — this later gates prize administration), an `entry_fee_vc` (0 for open qualifiers), and the registration window `registration_opens_at` to `registration_closes_at`. The program starts `ANNOUNCED` with `prize_pool_vc` at 0. Opening registration moves it to `REGISTRATION_OPEN` and requires the parent season to be `LIVE` and the clock to fall at or after `registration_opens_at` and strictly before `registration_closes_at`.

Registration creates a `TournamentEntry` under the program with a `wallet_id`. When `entry_fee_vc` is greater than zero, the entry fee is debited from the entrant's wallet at registration time; the entry's `fee_paid` flag records whether that debit succeeded (it is always true for zero-fee programs). The new entry is `REGISTERED`. The first registration — and each subsequent one — also flips the program's prize rows from `PLANNED` to `PROJECTED` and recomputes `projected_amount_vc` under the projected pool variant described below.

Prize rows are defined per program with a `placement` (1 pays first) and a `share_bps`. The prize pool itself has two variants. Under the `PROJECTED` variant — used while registration is live — the pool is the sum of `entry_fee_vc` across entries in either `REGISTERED` or `CONFIRMED` status, so it optimistically includes registered-but-unpaid entries. Under the `FINAL` variant — used at record-results — the pool counts only `CONFIRMED` entries. In both variants the allocation across rows is identical: prize rows are sorted by placement ascending, each row's raw amount is the pool multiplied by its `share_bps` and divided by ten thousand, each row is rounded down (floored) to an integer, and the residual — the pool minus the sum of floored rows — is assigned in full to the placement-1 row. This pins the rounding order: floor per row first, remainder to first place.

Closing registration moves the program to `REGISTRATION_CLOSED` — by operator action or lazily when the clock reaches `registration_closes_at` — and triages entries: `REGISTERED` entries whose wallet paid the entry fee move to `CONFIRMED`; unpaid `REGISTERED` entries move to `REFUNDED`. The full set of values a `TournamentEntry` may carry over its lifetime is `REGISTERED`, `CONFIRMED`, `DISQUALIFIED`, and `REFUNDED`. Recording results moves the program from `REGISTRATION_CLOSED` to `COMPLETED`; the request carries `placements`, an array of `entry_id`-and-`placement` pairs covering every `CONFIRMED` entry (any confirmed entry left without a placement blocks the transition as `ERR_INVALID_INPUT`), and the `share_bps` values across the program's prize rows must total exactly 10000 — a violation is `ERR_PRIZE_SHARES_INVALID` (HTTP 422). At that moment every prize row moves from `PROJECTED` to `PAYABLE` with `final_amount_vc` computed under the final pool variant.

Payout finalization belongs to the `FinanceController` and is the fiscally sensitive step. The program must be `COMPLETED`, the `league_sanctioned` flag must be true (finalizing an unsanctioned program is `ERR_UNSANCTIONED_PAYOUT`, HTTP 422), every `PAYABLE` prize row must have a `CONFIRMED` entry at its placement, and the request must carry `expected_program_version` matching the program's current `version` per §2.8. On success each `PAYABLE` prize posts a `PRIZE_PAYOUT` `CREDIT` ledger entry to the winner's wallet for `final_amount_vc` and moves to `PAID`; the program moves to `PAYOUT_FINALIZED` and its `version` increments. Cancellation is the escape hatch for programs in `ANNOUNCED` or `REGISTRATION_OPEN`: every entry is refunded via `REFUND` credits and every prize row moves to `VOIDED`.

### 3.6. Audio Assets and Regional Editions

Audio licensing is deliberately simpler than athlete likeness but shares the same posture: an asset is usable only while an active license covers it. A `RightsOfficer` registers an `AudioAsset` with an `asset_kind` of `COMMENTARY_LINE`, `MUSIC_TRACK`, or `STADIUM_SOUND`, an `asset_title`, and the `rights_holder` (label, commentator estate, or stadium operator); the asset begins `CLEARED`. Creating an `AudioLicense` requires the `asset_id`, inclusive term bounds `term_start_on` and `term_end_on`, a `usage_scope` of `MENU_ONLY`, `IN_GAME`, `BROADCAST_SIM`, or `ALL`, and a `region_scope` code or the literal `GLOBAL`. The new license starts `ACTIVE`, and its creation un-blocks the referenced asset: a `BLOCKED` asset returns to `CLEARED` when the new license's region and usage scope are compatible. Two paths strip coverage: the clock passing `term_end_on` moves an `ACTIVE` license to the terminal `LAPSED` state, and a `RightsOfficer` may move an `ACTIVE` license to the terminal `TERMINATED` state early. In both cases the referenced asset moves from `CLEARED` to `BLOCKED` when no other `ACTIVE` license covers it; operations that require coverage on an uncovered asset are rejected with `ERR_AUDIO_UNCOVERED`. A `BLOCKED` asset may be retired outright, moving to the terminal `RETIRED`.

Regional editions carry censorship compliance. A `LiveOpsManager` creates a `RegionalEdition` under a season with a `region_code` such as `NA`, `EU`, `DE`, `AU`, or `CN`, a list of `censorship_flags` (for example `NO_REAL_PLAYER_NAMES` or `NO_BLOOD_OVERLAYS`), and an `embargo_until_on` date. The edition starts `DRAFT`, moves to `IN_REVIEW` when submitted for compliance review, and from there a `ComplianceReviewer` either approves it or returns it to `DRAFT` for rework — the reviewer who approves must differ from the operator who submitted, else `ERR_SEGREGATION_OF_DUTIES`. An `APPROVED` edition may be released once the clock date is on or after `embargo_until_on` — the threshold is inclusive, so releasing exactly on the embargo date is permitted — and only while the parent season is `LIVE`. Withdrawing a `RELEASED` edition moves the edition to the terminal `WITHDRAWN` state and forces a re-evaluation of content: any `RELEASED` drop whose content conflicts with the edition's censorship flags moves to `HELD`.

### 3.7. Royalty Statements and the Two Accrual Variants

Royalty reporting is the financial spine. A `FinanceController` opens a `RoyaltyStatement` against an agreement for a period delimited by `period_start_on` and `period_end_on`, reporting `gross_sales_cents`, `returns_cents`, and `pending_sales_cents` — the portion of gross still in pending settlement at period close. The statement starts `OPEN`.

Accrual runs in two variants that share one tiered core. Net sales are the gross minus the returns, floored at zero. The base depends on the agreement's `royalty_model`: under `PERCENT_OF_NET` the base is net sales; under `PER_UNIT` the base is the product of units sold and the per-unit royalty rate reported on the statement; under `HYBRID` the base is the larger of half of net sales and the per-unit product. The base then flows through three tiers: the portion up to 500,000,000 cents (five hundred thousand dollars) accrues at 1000 basis points; the portion above that cap and up to 2,000,000,000 cents (two million dollars) accrues at 1200 basis points; the portion above the second cap accrues at 1500 basis points. Summing the three tier contributions yields the raw accrual. Recoupment then applies: when the agreement's `mg_recoupable` is true and `recouped_against_mg_cents` is still below `minimum_guarantee_cents`, the payable accrual is the raw accrual minus the remaining recoupment room, floored at zero; otherwise the payable accrual equals the raw accrual. The final `accrued_royalty_cents` is the payable accrual rounded half-up to integer cents — the only rounding step in the entire calculation.

The `PROVISIONAL` variant runs while the period is still open via compute-provisional and includes pending sales: net sales use `gross_sales_cents` as reported. The `FINAL` variant runs at finalize — permitted only once the clock date is past `period_end_on`, otherwise `ERR_TEMPORAL_CONFLICT` — and excludes pending sales: net sales use `gross_sales_cents` minus `pending_sales_cents`. The delta between final and provisional is posted as a correcting line, and finalization increases the agreement's `outstanding_royalty_cents` by the final accrual minus `held_royalty_cents`.

Held royalty attribution pins a subtle evaluation order. When a likeness-grant suspension or revocation cascade fires, the held amount for each suspended grant is computed against the statement's current `accrued_royalty_cents` snapshot multiplied by the grant's `royalty_share_bps` and divided by ten thousand, rounded half-up to integer cents — and the accrual itself is not recomputed as a consequence of the hold. Accrue first, then attribute holds.

Payment and dispute complete the cycle. Paying a `FINALIZED` statement — blocked while any `OPEN` or `FINDINGS_FILED` audit case references it, surfacing `ERR_FISCAL_BLOCK` — sets `paid_royalty_cents` to the accrual minus the held amount, decreases the agreement's `outstanding_royalty_cents` by the paid amount, and updates `recouped_against_mg_cents` under the recoupment rule. A `DISPUTED` statement may be paid once its audit has settled, with the audit's `finding_delta_cents` applied to `accrued_royalty_cents` before `paid_royalty_cents` is set. The conserved quantity across finalize, pay, and audit settle is that `outstanding_royalty_cents` always equals the sum, across statements in `FINALIZED`, `DISPUTED`, or `PAID`, of accrued minus held minus paid; a finalize followed later by a pay of the same statement leaves the outstanding balance unchanged relative to before the finalize.

### 3.8. Audit Cases: League and Union Inspection Rights

Audits are the licensor's contractual check on the publisher's royalty math. A `LeagueAuditor` or `UnionAuditor` opens an `AuditCase` by naming the `agreement_id`, the `statement_id` under audit, and the `opened_by_role` (`LEAGUE_AUDITOR` or `UNION_AUDITOR`). Opening requires the referenced statement to be `FINALIZED` and the clock date to fall within the agreement's `audit_window_days` after finalization; a missed window is `ERR_AUDIT_WINDOW_MISSED`. A successful open moves the statement from `FINALIZED` to `DISPUTED` and the case starts `OPEN`. Filing findings moves the case to `FINDINGS_FILED` and records the signed `finding_delta_cents` adjustment — zero when the audit found no discrepancy. Settlement belongs to a `FinanceController` who is not the auditor who opened the case (a self-settle is `ERR_SEGREGATION_OF_DUTIES`) and moves the case from `FINDINGS_FILED` to `SETTLED`, applying the delta: the referenced statement's `accrued_royalty_cents` is adjusted by `finding_delta_cents`, after which the statement becomes payable per §3.7. Closure is the final step, permitted only once the referenced statement is `PAID`, and moves the case from `SETTLED` to the terminal `CLOSED` state. As noted in §3.1, an agreement may not be terminated while any of its cases sits in `OPEN` or `FINDINGS_FILED`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource — including all state-transition endpoints — return `200 OK`. List and single-resource reads return `200 OK`. All endpoints are mounted under `/licensing`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/licensing/_clock/set_current_utc` | Advance the logical clock | LicensingAdmin |
| POST | `/licensing/agreements` | Create a license agreement (DRAFT) | LicensingAdmin |
| GET | `/licensing/agreements` | List agreements | LicensingAdmin, RightsOfficer, FinanceController, LeagueAuditor, UnionAuditor |
| GET | `/licensing/agreements/{agreement_id}` | Get one agreement | LicensingAdmin, RightsOfficer, FinanceController, LeagueAuditor, UnionAuditor, RosterOperator, RosterReviewer, LiveOpsManager, ComplianceReviewer |
| POST | `/licensing/agreements/{agreement_id}/activate` | Activate an agreement (checks exclusivity overlap) | LicensingAdmin |
| POST | `/licensing/agreements/{agreement_id}/suspend` | Suspend an agreement; cascades to grants, drops, held royalties | LicensingAdmin |
| POST | `/licensing/agreements/{agreement_id}/reinstate` | Reinstate a suspended agreement | LicensingAdmin |
| POST | `/licensing/agreements/{agreement_id}/terminate` | Terminate a suspended agreement (terminal) | LicensingAdmin |
| GET | `/licensing/agreements/{id}/royalty-statements` | List royalty statements of an agreement | LicensingAdmin, FinanceController, LeagueAuditor, UnionAuditor |
| GET | `/licensing/agreements/{id}/audit-cases` | List audit cases of an agreement | LicensingAdmin, FinanceController, LeagueAuditor, UnionAuditor |
| GET | `/licensing/agreements/{id}/likeness-grants` | List likeness grants under an agreement | LicensingAdmin, RightsOfficer, FinanceController |
| GET | `/licensing/agreements/{id}/seasons` | List live seasons governed by an agreement | LicensingAdmin, LiveOpsManager, FinanceController |
| POST | `/licensing/athletes` | Register an athlete | RightsOfficer |
| GET | `/licensing/athletes` | List athletes | LicensingAdmin, RightsOfficer, RosterOperator, RosterReviewer, LiveOpsManager |
| GET | `/licensing/athletes/{athlete_id}` | Get an athlete | LicensingAdmin, RightsOfficer, RosterOperator, RosterReviewer, LiveOpsManager, FinanceController |
| GET | `/licensing/athletes/{id}/likeness-grants` | List likeness grants for an athlete | LicensingAdmin, RightsOfficer, FinanceController |
| GET | `/licensing/athletes/{id}/roster-entries` | List roster entries referencing an athlete | LicensingAdmin, RightsOfficer, RosterOperator, RosterReviewer |
| GET | `/licensing/athletes/{id}/content-drops` | List content drops featuring an athlete | LicensingAdmin, RightsOfficer, LiveOpsManager |
| POST | `/licensing/likeness-grants` | Create a likeness grant (PENDING) | RightsOfficer |
| GET | `/licensing/likeness-grants/{grant_id}` | Get a likeness grant | LicensingAdmin, RightsOfficer, FinanceController, LeagueAuditor, UnionAuditor |
| POST | `/licensing/likeness-grants/{grant_id}/grant` | Grant the likeness | RightsOfficer |
| POST | `/licensing/likeness-grants/{grant_id}/suspend` | Suspend a grant; cascades to drops and held royalties | RightsOfficer |
| POST | `/licensing/likeness-grants/{grant_id}/reinstate` | Reinstate a suspended grant | RightsOfficer |
| POST | `/licensing/likeness-grants/{grant_id}/revoke` | Revoke a suspended grant (terminal) | RightsOfficer |
| POST | `/licensing/seasons` | Create a live season (PRELAUNCH) | LiveOpsManager |
| GET | `/licensing/seasons/{season_id}` | Get a season | LicensingAdmin, LiveOpsManager, RosterOperator, RosterReviewer, FinanceController, ComplianceReviewer |
| POST | `/licensing/seasons/{season_id}/launch` | Launch a season (requires a published roster batch) | LiveOpsManager |
| POST | `/licensing/seasons/{season_id}/sunset` | Sunset a season; cascades to drops, wallets, tournaments | LiveOpsManager |
| POST | `/licensing/seasons/{season_id}/archive` | Archive a sunset season (terminal) | LiveOpsManager |
| GET | `/licensing/seasons/{id}/roster-batches` | List roster batches of a season | LicensingAdmin, LiveOpsManager, RosterOperator, RosterReviewer |
| GET | `/licensing/seasons/{id}/content-drops` | List content drops of a season | LicensingAdmin, LiveOpsManager, FinanceController, ComplianceReviewer |
| GET | `/licensing/seasons/{id}/wallets` | List wallets of a season | LicensingAdmin, LiveOpsManager, FinanceController |
| GET | `/licensing/seasons/{id}/tournaments` | List tournament programs of a season | LicensingAdmin, LiveOpsManager, FinanceController |
| GET | `/licensing/seasons/{id}/editions` | List regional editions of a season | LicensingAdmin, LiveOpsManager, ComplianceReviewer |
| POST | `/licensing/roster-batches` | Create a roster batch (DRAFT) | RosterOperator |
| GET | `/licensing/roster-batches` | List roster batches; supports filtering by `season_id`, `batch_status`, or `supersedes_batch_id` | LicensingAdmin, LiveOpsManager, RosterOperator, RosterReviewer |
| GET | `/licensing/roster-batches/{batch_id}` | Get a roster batch | LicensingAdmin, LiveOpsManager, RosterOperator, RosterReviewer |
| POST | `/licensing/roster-batches/{id}/entries` | Add a roster entry to a DRAFT batch | RosterOperator |
| GET | `/licensing/roster-batches/{id}/entries` | List entries of a batch | LicensingAdmin, LiveOpsManager, RosterOperator, RosterReviewer |
| POST | `/licensing/roster-batches/{batch_id}/validate` | Validate a DRAFT batch | RosterOperator |
| POST | `/licensing/roster-batches/{batch_id}/reject` | Reject a DRAFT or VALIDATED batch | RosterReviewer |
| POST | `/licensing/roster-batches/{batch_id}/publish` | Publish a VALIDATED batch; supersedes the prior published batch; OCC on season | RosterReviewer |
| POST | `/licensing/roster-batches/{batch_id}/rollback` | Roll back the most recently published batch | RosterReviewer |
| POST | `/licensing/content-drops` | Schedule a content drop | LiveOpsManager |
| GET | `/licensing/content-drops/{drop_id}` | Get a content drop | LicensingAdmin, LiveOpsManager, FinanceController, ComplianceReviewer |
| POST | `/licensing/content-drops/{drop_id}/release` | Release a scheduled drop within its window | LiveOpsManager |
| POST | `/licensing/content-drops/{drop_id}/cancel` | Cancel a SCHEDULED or HELD drop | LiveOpsManager |
| POST | `/licensing/content-drops/{drop_id}/purchase` | Purchase a RELEASED drop; posts a SPEND_DROP debit | LiveOpsManager |
| POST | `/licensing/wallets` | Open a player wallet | LiveOpsManager |
| GET | `/licensing/wallets/{wallet_id}` | Get a wallet | LicensingAdmin, LiveOpsManager, FinanceController |
| POST | `/licensing/wallets/{wallet_id}/freeze` | Freeze a wallet | LiveOpsManager |
| POST | `/licensing/wallets/{wallet_id}/unfreeze` | Unfreeze a wallet (season must be LIVE) | LiveOpsManager |
| POST | `/licensing/wallets/{id}/ledger-entries` | Post a GRANT or PURCHASE credit, or an admin CLAWBACK debit | LiveOpsManager, FinanceController |
| GET | `/licensing/wallets/{id}/ledger-entries` | List ledger entries of a wallet | LicensingAdmin, LiveOpsManager, FinanceController |
| GET | `/licensing/wallets/{id}/tournament-entries` | List tournament entries of a wallet | LicensingAdmin, LiveOpsManager, FinanceController |
| POST | `/licensing/tournaments` | Announce a tournament program | LiveOpsManager |
| GET | `/licensing/tournaments/{program_id}` | Get a tournament program | LicensingAdmin, LiveOpsManager, FinanceController |
| POST | `/licensing/tournaments/{program_id}/open-registration` | Open registration within its window | LiveOpsManager |
| POST | `/licensing/tournaments/{id}/entries` | Register an entrant; debits the entry fee when greater than zero | LiveOpsManager |
| GET | `/licensing/tournaments/{id}/entries` | List entries of a program | LicensingAdmin, LiveOpsManager, FinanceController |
| POST | `/licensing/tournaments/{id}/prizes` | Define a prize row | LiveOpsManager |
| GET | `/licensing/tournaments/{id}/prizes` | List prize rows of a program | LicensingAdmin, LiveOpsManager, FinanceController |
| POST | `/licensing/tournaments/{program_id}/close-registration` | Close registration; unpaid REGISTERED entries become REFUNDED | LiveOpsManager |
| POST | `/licensing/tournaments/{program_id}/record-results` | Record final placements; computes FINAL prize amounts | LiveOpsManager |
| POST | `/licensing/tournaments/{program_id}/finalize-payout` | Pay all PAYABLE prizes; OCC on program version | FinanceController |
| POST | `/licensing/tournaments/{program_id}/cancel` | Cancel a program in ANNOUNCED or REGISTRATION_OPEN; refunds entries | LiveOpsManager |
| POST | `/licensing/audio-assets` | Register an audio asset (CLEARED) | RightsOfficer |
| GET | `/licensing/audio-assets/{asset_id}` | Get an audio asset | LicensingAdmin, RightsOfficer, LiveOpsManager |
| POST | `/licensing/audio-assets/{asset_id}/retire` | Retire a BLOCKED audio asset | RightsOfficer |
| GET | `/licensing/audio-assets/{id}/licenses` | List licenses covering an audio asset | LicensingAdmin, RightsOfficer |
| POST | `/licensing/audio-licenses` | Create an audio license (ACTIVE); un-blocks the asset | RightsOfficer |
| GET | `/licensing/audio-licenses/{license_id}` | Get an audio license | LicensingAdmin, RightsOfficer |
| POST | `/licensing/audio-licenses/{license_id}/terminate` | Terminate an audio license | RightsOfficer |
| POST | `/licensing/editions` | Create a regional edition (DRAFT) | LiveOpsManager |
| GET | `/licensing/editions/{edition_id}` | Get a regional edition | LicensingAdmin, LiveOpsManager, ComplianceReviewer |
| POST | `/licensing/editions/{edition_id}/submit-review` | Submit an edition for compliance review | LiveOpsManager |
| POST | `/licensing/editions/{edition_id}/approve` | Approve an edition (different actor than submitter) | ComplianceReviewer |
| POST | `/licensing/editions/{edition_id}/return-to-draft` | Return an edition to draft | ComplianceReviewer |
| POST | `/licensing/editions/{edition_id}/release` | Release an approved edition once the embargo date is reached | LiveOpsManager |
| POST | `/licensing/editions/{edition_id}/withdraw` | Withdraw a released edition; conflicting drops HELD | ComplianceReviewer |
| POST | `/licensing/royalty-statements` | Open a royalty statement for a period | FinanceController |
| GET | `/licensing/royalty-statements/{statement_id}` | Get a royalty statement | LicensingAdmin, FinanceController, LeagueAuditor, UnionAuditor |
| POST | `/licensing/royalty-statements/{statement_id}/compute-provisional` | Compute PROVISIONAL accrual | FinanceController |
| POST | `/licensing/royalty-statements/{statement_id}/finalize` | Finalize after period end; FINAL variant recompute | FinanceController |
| POST | `/licensing/royalty-statements/{statement_id}/pay` | Pay a FINALIZED (or settled DISPUTED) statement | FinanceController |
| GET | `/licensing/royalty-statements/{id}/audit-cases` | List audit cases referencing a royalty statement | LicensingAdmin, FinanceController, LeagueAuditor, UnionAuditor |
| POST | `/licensing/audit-cases` | Open an audit on a FINALIZED statement within the audit window | LeagueAuditor, UnionAuditor |
| GET | `/licensing/audit-cases/{case_id}` | Get an audit case | LicensingAdmin, FinanceController, LeagueAuditor, UnionAuditor |
| POST | `/licensing/audit-cases/{case_id}/file-findings` | File audit findings with a signed delta | LeagueAuditor, UnionAuditor |
| POST | `/licensing/audit-cases/{case_id}/settle` | Settle the audit (different actor than opener) | FinanceController |
| POST | `/licensing/audit-cases/{case_id}/close` | Close a settled audit after the statement is paid | FinanceController |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_CONTEXT` | 400 Bad Request |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_INPUT` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 409 Conflict |
| `ERR_REFERENCE_STATE` | 409 Conflict |
| `ERR_TEMPORAL_CONFLICT` | 409 Conflict |
| `ERR_FISCAL_BLOCK` | 422 Unprocessable Entity |
| `ERR_STALE_SEASON_VERSION` | 412 Precondition Failed |
| `ERR_STALE_PROGRAM_VERSION` | 412 Precondition Failed |
| `ERR_EXCLUSIVITY_CONFLICT` | 409 Conflict |
| `ERR_ATHLETE_NOT_ELIGIBLE` | 409 Conflict |
| `ERR_DROP_WINDOW` | 409 Conflict |
| `ERR_CENSORSHIP_CONFLICT` | 409 Conflict |
| `ERR_EMPTY_BATCH` | 409 Conflict |
| `ERR_ROLLBACK_NOT_HEAD` | 409 Conflict |
| `ERR_AUDIT_WINDOW_MISSED` | 409 Conflict |
| `ERR_AUDIT_BLOCKS_TERMINATION` | 409 Conflict |
| `ERR_WALLET_FROZEN` | 409 Conflict |
| `ERR_INSUFFICIENT_VC` | 422 Unprocessable Entity |
| `ERR_PRIZE_SHARES_INVALID` | 422 Unprocessable Entity |
| `ERR_UNSANCTIONED_PAYOUT` | 422 Unprocessable Entity |
| `ERR_GRANT_TERM_OUTSIDE_AGREEMENT` | 409 Conflict |
| `ERR_COLLEGE_OPT_IN_REQUIRED` | 409 Conflict |
| `ERR_AUDIO_UNCOVERED` | 409 Conflict |
