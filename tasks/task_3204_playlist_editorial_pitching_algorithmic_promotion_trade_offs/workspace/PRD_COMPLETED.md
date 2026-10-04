# Playlist Editorial Promotion API — Product Requirements Document

## 1. Introduction

This document specifies the product requirements for the Playlist Editorial Promotion API, the service layer that connects rights holders, editorial teams, trust-and-safety staff, and platform operators around a music catalog. The platform lets a rights holder submit an upcoming release — with full metadata, genre and mood tagging, and territory restrictions — well ahead of its go-live date so that editorial teams can evaluate the release's focus track for curated playlist placement. Editorial placement is deliberately scarce: every playlist has a fixed number of slots and a rotation cadence, so an accepted pitch produces a scheduled placement that must later be activated, rotated out, and possibly reinstated as the cadence window elapses.

Alongside the editorial pipeline, the platform runs an algorithmic promotion program in which a rights holder knowingly trades a reduced royalty rate for increased algorithmic exposure. The trade is disclosed, receipted, and reversible: enrolling in the program mints a disclosure token that the rights holder must present to suspend the enrollment. Early listener signals gathered during editorial placement feed a boost-score computation that the algorithmic pipelines consume, and the score responds more weakly when a track had no editorial placement at all — the system's explicit mechanism for expressing the editorial-versus-algorithmic trade-off.

Finally, the platform keeps the books. Streams are ingested into open royalty periods, periods close under an optimistic-concurrency guard that freezes a chosen share variant, and per-artist statements are generated from a waterfall allocation over the royalty pool. Artificial-streaming fraud is investigated through scored cases; a confirmed case taints the implicated streams, claws back royalties, terminates promotion enrollments, evicts placements, and accrues strikes against the artist that can cascade into suspension or termination of the entire catalog. All of this runs against a deterministic logical clock so that scheduled behavior — releases going live, placements rotating out — is reproducible.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. A request missing either header, or carrying a role the system does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The system recognizes exactly five roles, spelled as follows: `RightsHolder`, `PlaylistEditor`, `EditorialLead`, `FraudAnalyst`, and `PlatformAdmin`.

Each role carries a defined relationship between `X-User-ID` and persisted entities:

- When `X-User-Role` is `RightsHolder`, `X-User-ID` is the `id` of the acting `Artist`; ownership checks on any resource that references an `Artist` compare the resource's foreign-key field to `X-User-ID`. A `RightsHolder` acting on a resource owned by another artist is rejected with `ERR_FORBIDDEN` (HTTP 403), as is any role attempting an operation outside its authorized set. Ownership is enforced everywhere a rights holder touches the graph: on writes (create, mutate) and on reads alike — single-resource fetches and list endpoints both apply it, and on list endpoints it acts as a scoping filter (a `RightsHolder` sees only their own releases, tracks, pitches, placements, enrollments, statements, modules, and pre-saves), with the explicit `artist_id` filter on release listing still available to narrow further within that scope.
- When `X-User-Role` is `PlaylistEditor`, `EditorialLead`, `FraudAnalyst`, or `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it for audit purposes but does not compare it to any entity's `id`.

Role authorization is endpoint-specific; the authoritative mapping of operations to roles appears in §4. The segregation-of-duties model is deliberate: a `RightsHolder` owns releases, pitches, promotions, and profile modules but can never open a fraud case; a `FraudAnalyst` adjudicates fraud and suspends artists but shares release-removal and promotion-termination rights with the `RightsHolder`; a `PlaylistEditor` claims pitches and drives placement rotation but only an `EditorialLead` creates playlists and accepts or rejects pitches; a `PlatformAdmin` runs the operational backbone — artist registration, stream ingest, royalty period lifecycle, pre-save registration, signal rollups, and the logical clock.

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

Endpoints that return lists of resources accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items from the front of the result set and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by their creation timestamp in ascending order. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and Time-Driven Transitions

The platform never consults wall-clock time for business logic. All temporal decisions — whether a release may go live, whether a placement's cadence window has elapsed, whether a pitch is still inside its lead window — are evaluated against a logical clock. At server startup the logical clock reads exactly `2026-09-01T00:00:00Z`; until an operator first sets it, the clock remains pinned at that instant and never falls back to real time.

A `PlatformAdmin` advances the logical clock through an admin-only capability that accepts a `current_utc` instant and returns the new clock reading (echoed as `current_utc`). Advancing the clock fires the time-driven transitions deterministically, in the order the affected resources were created: passing a release's `release_date` flips a `SCHEDULED` release to `LIVE` (provided its artist is `ACTIVE`) and runs pre-save conversion, and passing a placement's `scheduled_rotation_on` rotates `ACTIVE` or `REINSTATED` placements out. Every datetime comparison elsewhere in this document — window bounds, thresholds, lead times — refers to this same logical clock.

### 2.5. Common Resource Properties

Primary resources — Artist, Release, Track, PitchSubmission, EditorialPlaylist, PlaylistPlacement, PromotionEnrollment, FraudCase, RoyaltyPeriod, RoyaltyStatement, and ProfileModule — share a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, recording when the resource was created. Because business time is logical (§2.4), `created_at` and `updated_at` are stamped from the logical clock — the instant at which the operation was processed — not from wall-clock time.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that starts at 1 at creation and increments with every modification, including modifications caused by cascades originating on other resources.

Two resources are deliberately lighter-weight. A `StreamEvent` carries only `id` and `created_at` from the common set — `updated_at` and `version` are absent because stream events are immutable once ingested. A `PreSave` likewise carries only `id` and `created_at`, with no `updated_at` or `version`.

### 2.6. Validation Order

When several validations could reject the same request, the system evaluates them in a fixed priority order so that the error a client receives is deterministic. Authentication comes first: missing or unrecognized headers surface as `ERR_UNAUTHENTICATED` before anything else is examined. Authorization follows: an unrecognized or unauthorized role surfaces as `ERR_FORBIDDEN` before existence checks run. Existence is next — path identifiers are validated left to right, and body foreign-key identifiers are validated in the order the endpoint's input list declares them — with the first missing identifier producing `ERR_NOT_FOUND`. Only then are required-field presence, typing, and enum membership checked (`ERR_INVALID_REQUEST`). Once the request is structurally sound, the generic invalid-state guard runs (`ERR_INVALID_STATE`), and only after it passes do the business rules — pitch windows, slot occupancy, fraud holds, fiscal guards, optimistic-concurrency version checks — evaluate in the order given in §3's narratives. A pitch submission, for example, enforces its checks in this order: the temporal pitch-window guard first, then the focus-track pitchability check, then the playlist genre/mood fit, then the fraud hold — so a pitch that is both late and aimed at a mismatched playlist is rejected with `ERR_PITCH_WINDOW_CLOSED`, not the fit error.

### 2.7. Optimistic Concurrency Control

Two write operations carry an optimistic-concurrency guard against a stale view of a parent entity, and only those two; endpoints not named here take no version field at all.

Changing a release's scheduled date requires the request body to carry `expected_release_version`, set to the `version` of the `Release` the client last observed. If the release's current `version` no longer matches — because another writer changed the date, or because a cascade such as a pitch withdrawal or pre-save conversion advanced it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from rewriting a schedule it has not observed. A successful date change increments the release's `version` by 1.

Closing a royalty period requires the request body to carry `expected_period_version`, set to the `version` of the `RoyaltyPeriod` the client last observed. Closing freezes the share variant and materializes statements, so a stale view of the period — for instance one whose `pool_cents` was amended by another administrator — must not be the basis of the close; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). A successful close increments the period's `version` by 1.

### 2.8. Precision, Rounding, and Money

Royalty pools and payouts are integer cents: `pool_cents` and `gross_payout_cents` are whole numbers of cents, while `clawback_cents` and `net_payout_cents` may carry fractional cents once a fraud clawback (§3.7) lands on a statement, since clawbacks are computed in fractional-cent units. Stream weights used in share computation are rounded to 2 decimal places using round-half-up before they are summed. The fraud `confidence_score` is rounded to 4 decimal places using round-half-up. Shares are expressed in integer basis points against a base of 10000, and per-artist payouts are floored to whole cents before any remainder is redistributed (see §3.6). Wherever this document gives a rounding rule, round-half-up is the method unless floor is stated explicitly.

### 2.9. Catalog Integrity and Cascading Consistency

The catalog is a web of dependencies: tracks belong to releases, releases belong to artists, placements reference tracks and playlists, enrollments reference tracks, and statements aggregate streams. When a parent resource becomes non-operational, the system resolves its dependents in the same transaction rather than leaving dangling rows. Suspending an artist terminates that artist's enrollments and evicts placements; terminating an artist additionally removes every available track and disables every enabled profile module; removing a release removes its tracks, cancels its pre-saves, withdraws its open pitches, and evicts its placements. These cascades are mutations: each affected resource's `updated_at` refreshes and, where the resource carries one, its `version` increments. Conversely, the system never silently resurrects a dependent: evicting a placement or terminating an enrollment is one-way, and reinstatement always requires an explicit, separately validated action.

### 2.10. Nested Resource Retrieval

Requests that address a resource through path identifiers validate existence sequentially, left to right: the request is rejected immediately with `ERR_NOT_FOUND` (HTTP 404) at the first path identifier that does not correspond to an existing resource. Identifiers supplied inside a request body as foreign keys — an `artist_id` on a release create, a `track_id` on a pitch, a `target_playlist_id`, and so on — are validated for existence in the order the endpoint's input list declares them, each failure also producing `ERR_NOT_FOUND`.

## 3. Business Logic & Workflows

### 3.1. Artist Registry and Reputation

Everything begins with the artist. A `PlatformAdmin` registers an artist by supplying a `stage_name`, a `primary_genre` drawn from `POP`, `HIPHOP`, `ROCK`, `ELECTRONIC`, `LATIN`, `COUNTRY`, `JAZZ`, or `CLASSICAL`, a `home_territory` expressed as an ISO 3166-1 alpha-2 code, and a `follower_count` (an integer of zero or more) captured at profile setup time — this value later drives the boost tier described in §3.8. A newly registered artist is `ACTIVE` with `fraud_strikes` at 0. The artist roster is browsable by staff, with optional `status` and `primary_genre` filters.

An artist's `status` moves among `ACTIVE`, `SUSPENDED`, and `TERMINATED`. A `FraudAnalyst` may suspend an `ACTIVE` artist — suspending an artist in any other status is `ERR_INVALID_STATE` — and the same transition fires automatically the moment the artist's `fraud_strikes` reaches the strike limit of 2 after a confirmed fraud verdict. Suspension cascades: every `ENROLLED` promotion enrollment on the artist's tracks transitions to `TERMINATED` (its disclosure record is preserved for audit, and an already `SUSPENDED` enrollment survives suspension), and every `ACTIVE` or `REINSTATED` playlist placement on the artist's tracks transitions to `EVICTED` (a still-`SCHEDULED` placement is likewise untouched by suspension). A suspended artist returns to `ACTIVE` through reinstatement by a `FraudAnalyst` — reinstatement requires the artist to be `SUSPENDED` (any other status is `ERR_INVALID_STATE`) — but only while the artist's `fraud_strikes` remains below the strike limit of 2 — an artist at the limit cannot be reinstated.

Termination is system-driven and irreversible: when `fraud_strikes` reaches the termination limit of 3, the artist moves from `ACTIVE` to `TERMINATED`, and the cascade is total — every `AVAILABLE` track becomes `REMOVED`, every non-terminal placement on the artist's tracks becomes `EVICTED` (here meaning `SCHEDULED`, `ACTIVE`, `REINSTATED`, and `ROTATED_OUT` alike — the one cascade that also evicts rotated-out rows), every `ENROLLED` or `SUSPENDED` enrollment becomes `TERMINATED`, every `ENABLED` profile module becomes `DISABLED`, and every `LIVE` release of the artist becomes `REMOVED` (a `SCHEDULED` release of the artist is left untouched by this cascade and remains `SCHEDULED`).

### 3.2. Releases, Tracks, Territories, and Pre-Saves

A `RightsHolder` creates a release under their own artist by supplying the `artist_id`, a `title`, a `release_type` of `SINGLE`, `EP`, or `ALBUM`, a future `release_date`, between one and three `genre_tags` drawn from the same genre enum as `primary_genre`, and up to four `mood_tags` drawn from `CHILL`, `ENERGETIC`, `MELANCHOLY`, `FOCUS`, `PARTY`, and `ROMANTIC` (zero mood tags is acceptable). The release may also carry a `territory_allowlist` of ISO alpha-2 codes naming the markets where it is streamable; omitting it defaults the allowlist to an empty array, which means worldwide. Every allowlist entry must be a valid ISO alpha-2 code; an invalid entry is rejected with `ERR_TERRITORY_RESTRICTED` (HTTP 422). A new release is `SCHEDULED` with `date_change_count` and `presave_count` both at 0. Releases are listable with optional `artist_id` and `status` filters.

While a release is `SCHEDULED`, the rights holder may move its date — but the schedule is not freely mutable. A change-date request supplies a new `release_date` alongside the concurrency field described in §2.7, and three temporal guards apply, evaluated under the business-rule ordering of §2.6: the release must still be `SCHEDULED` (a live or removed release rejects the transition with `ERR_INVALID_STATE`); the logical clock must be at least 7 days before the *old* release date, because date changes inside the pitch window would strand in-flight editorial work; the new date must lie strictly in the future of the logical clock; and the release's `date_change_count` must still be below the maximum of 3 changes. These temporal and count guards run together: violating any one of them — and only then — is rejected with `ERR_DATE_CHANGE_WINDOW` (HTTP 409); the stale-version check runs after they all pass. A successful change replaces `release_date`, increments `date_change_count` by 1, and then sweeps the release's pitches: any pitch still in `PITCHED`, `UNDER_REVIEW`, or `NEEDS_REVISION` whose `submitted_days_before_release` would fall below the minimum lead of 7 days under the new date is moved to `WITHDRAWN`. Because each withdrawal is a cascade mutation of the pitch, the release's own `version` advances once for the date change and once more per withdrawn pitch (§2.9).

Removal is the other fate for a scheduled release. The owning `RightsHolder` may remove a `SCHEDULED` release — any other status is `ERR_INVALID_STATE` for a rights holder — which removes every `AVAILABLE` track on it, cancels every `SAVED` pre-save, and withdraws every pitch still in `PITCHED`, `UNDER_REVIEW`, or `NEEDS_REVISION`; removing the tracks also evicts their placements in `SCHEDULED`, `ACTIVE`, or `REINSTATED` status and terminates their `ENROLLED` or `SUSPENDED` enrollments, as track removal always does. A `LIVE` release is removed only through the fraud cascade — either the system acting on a terminated artist or a `FraudAnalyst` invoking the removal — and that cascade additionally evicts every non-terminal placement on the release's tracks (including `ROTATED_OUT` rows, matching the artist-termination scope of §3.1) and terminates every `ENROLLED` or `SUSPENDED` enrollment on them. A `FraudAnalyst` may invoke removal on a release in any status other than `REMOVED`, and an already-`REMOVED` release rejects any removal with `ERR_INVALID_STATE`. `REMOVED` is terminal.

Tracks are added to a release by the owning `RightsHolder`, who supplies the `release_id`, a `title`, a `duration_ms` of at least 30000 milliseconds, and an optional `is_focus_track` flag defaulting to `false`. Exactly one track per release may be the focus track, and only the focus track is pitchable; attempting to designate a second focus track on the same release is rejected with `ERR_INVALID_REQUEST`. A new track is `AVAILABLE`; it becomes `REMOVED` only through the release- or artist-level cascades. Tracks are listable with optional `release_id` and `status` filters.

Fans register interest in an upcoming release through pre-saves. A `PlatformAdmin` registers a pre-save with the `release_id`, an opaque `fan_token` that must be unique per release, and the fan's `territory` as an ISO alpha-2 code. Registering a pre-save requires the release to be `SCHEDULED` (otherwise `ERR_INVALID_STATE`), requires the `fan_token` not to duplicate an existing pre-save on the same release (a duplicate is `ERR_INVALID_REQUEST`), and — when the release's `territory_allowlist` is non-empty — requires the fan's territory to be inside the allowlist, failing which the request is rejected with `ERR_TERRITORY_RESTRICTED`; the territory syntax itself is validated as an ISO alpha-2 code too, and a malformed territory surfaces the same `ERR_TERRITORY_RESTRICTED` (HTTP 422). A new pre-save is `SAVED`, and its creation recomputes the release's `presave_count` — the count of that release's pre-saves in `SAVED` or `CONVERTED` status — and recomputation counts as a mutation of the release (its `version` advances) whenever the count actually changes. A pre-save can be cancelled by a `PlatformAdmin` or the owning `RightsHolder` — only a `SAVED` pre-save may be cancelled, any other status being `ERR_INVALID_STATE` — moving it to `CANCELLED` and again recomputing `presave_count`.

When the logical clock reaches a release's `release_date`, the release goes live — provided its artist is `ACTIVE` at that moment; a release whose artist is not active cannot transition and remains `SCHEDULED`. Go-live converts the pre-save book: the release's `SAVED` pre-saves are processed in the order they were created, ties broken by `fan_token` in ascending order, and each row whose `territory` lies inside the `territory_allowlist` — or any row at all when the allowlist is empty — moves to `CONVERTED`, while every other `SAVED` row moves to `CANCELLED`. After conversion, `presave_count` is recomputed as the count of rows ending in `SAVED` or `CONVERTED`. A live release's `LIVE` status is terminal in the forward direction; the only exit is `REMOVED` via the fraud path described above.

### 3.3. The Editorial Pitching Cycle

With a scheduled release and its focus track in place, the rights holder pitches. Submitting a pitch requires a payload containing the `track_id`, the `pitch_text` narrative (between 1 and 2000 characters), and the `target_playlist_id` of the editorial playlist being asked for. Per §2.6, body foreign keys are validated for existence in declared order — `track_id` first, then `target_playlist_id`. Four checks guard submission, evaluated in this order. First, the temporal guard: the logical clock must be at least 7 days before the release's `release_date`; submitting inside that lead window — or after the release date — is rejected with `ERR_PITCH_WINDOW_CLOSED` (HTTP 409). Second, pitchability: the track must be the release's focus track, must be `AVAILABLE`, and must have no other non-terminal pitch; a violation yields `ERR_PITCH_NOT_PITCHABLE`. Third, fit: the target playlist must be `ACTIVE`, the release's `genre_tags` must include the playlist's `genre_focus`, and the playlist's `mood_focus` must be `ANY` or appear among the release's `mood_tags`; failure is `ERR_PLAYLIST_FIT_MISMATCH`. Fourth, the fraud hold: the track must have no fraud case in `OPEN` or `AUTO_FLAGGED` verdict; a track under investigation cannot be pitched and the attempt is rejected with `ERR_FRAUD_HOLD`. A track that fails more than one of these surfaces the earliest error in this ordering.

A new pitch is `PITCHED`, and the system computes `submitted_days_before_release` as the whole number of days between the submission instant and the release's `release_date` at submission time (computed by floor division on whole days; a same-calendar-day gap shorter than a full day contributes nothing); its `revision_round` starts at 0. From `PITCHED`, a `PlaylistEditor` claims the pitch into `UNDER_REVIEW` — but editorial work is segregated by team: the claiming editor supplies their `team`, and the claim succeeds only when that team matches the target playlist's `owning_team`. Only a `PITCHED` pitch can be claimed — any other status is `ERR_INVALID_STATE` — and the pitch-state guard is checked before the team comparison, so a claim on a non-`PITCHED` pitch surfaces `ERR_INVALID_STATE` even from the wrong team. A claim from the wrong team on a `PITCHED` pitch is rejected with `ERR_FORBIDDEN`. Pitches are listable with optional `track_id`, `target_playlist_id`, and `status` filters.

Once under review, an editor may send the pitch back for revision, moving it to `NEEDS_REVISION`. The rights holder then re-pitches with replacement `pitch_text`, which returns the pitch to `PITCHED` and increments `revision_round` by 1. This loop is bounded in two ways: a revise is rejected with `ERR_INVALID_STATE` once `revision_round` has reached the maximum of 2 rounds, and the same temporal lead rule as submission applies — the logical clock must be at least 7 days before the `release_date`, and the release must still be `SCHEDULED`; a revise inside the window is rejected with `ERR_PITCH_WINDOW_CLOSED`.

The decision belongs to editorial leadership. An `EditorialLead` decides an `UNDER_REVIEW` pitch by submitting a `decision`. An `ACCEPT` decision requires the pitch's release to still be `SCHEDULED` and the release's artist to be `ACTIVE`, and it requires a free slot on the target playlist: the system scans the playlist's slot indices from 0 up to one less than `slot_count` and selects the lowest index not occupied by any placement in `SCHEDULED`, `ACTIVE`, or `REINSTATED` status. If no such slot exists, the decision fails with `ERR_NO_FREE_SLOT` (HTTP 409) and the pitch remains `UNDER_REVIEW`. On success the pitch becomes `ACCEPTED` and a new placement is created in `SCHEDULED` for that slot, recording the `playlist_id`, the `track_id`, the `pitch_id` that justified it, and the chosen `slot_index`. A `REJECT` decision simply moves the pitch to `REJECTED`; both `ACCEPTED` and `REJECTED` are terminal.

Withdrawal closes the loop from the other side. The owning `RightsHolder` may withdraw a pitch in `PITCHED`, `UNDER_REVIEW`, or `NEEDS_REVISION`, moving it to `WITHDRAWN`; the same transition fires automatically when a release date change strands the pitch (as in §3.2) or when the release is removed. `WITHDRAWN` is terminal.

### 3.4. Playlists, Slots, and the Rotation Cycle

Editorial playlists are created by an `EditorialLead`, who supplies a `name`, a `genre_focus` from the artist genre enum, a `mood_focus` from the mood enum extended with `ANY`, a `slot_count` between 1 and 50, a `rotation_cadence_days` of at least 1, and the `owning_team` — `EDITORIAL_A` or `EDITORIAL_B` — that owns placement decisions on the playlist. A new playlist is `ACTIVE`. Playlists are listable with optional `owning_team` and `status` filters. Retiring a playlist moves it to `RETIRED` and evicts every placement on it still in `SCHEDULED`, `ACTIVE`, `REINSTATED`, or `ROTATED_OUT` status; `RETIRED` is terminal.

A placement born from an accepted pitch sits in `SCHEDULED` until a `PlaylistEditor` activates it. Activation requires the placement to be `SCHEDULED`, the playlist to be `ACTIVE`, the track to be `AVAILABLE` with its release `LIVE`, the slot `(playlist_id, slot_index)` to be free of any `ACTIVE` or `REINSTATED` placement — an occupied slot is rejected with `ERR_SLOT_OCCUPIED` — and the track to carry no `OPEN` or `AUTO_FLAGGED` fraud case, failing which activation is rejected with `ERR_FRAUD_HOLD`. A successful activation stamps `activated_on` with the current logical clock and computes `scheduled_rotation_on` as `activated_on` plus the playlist's `rotation_cadence_days`; the placement is now `ACTIVE`.

Rotation enforces the cadence. A placement rotates out — `ACTIVE` or `REINSTATED` to `ROTATED_OUT` — either automatically when the logical clock reaches `scheduled_rotation_on`, or manually at an editor's hand. The manual rotation is forbidden before the cadence window elapses: attempting it while the logical clock is still earlier than `scheduled_rotation_on` is rejected with `ERR_ROTATION_TOO_EARLY`. Because the automatic rotation fires the moment the logical clock reaches `scheduled_rotation_on` (§2.4), a manual rotation requested at or after cadence end finds the placement already `ROTATED_OUT` and is rejected with `ERR_INVALID_STATE` (only an `ACTIVE` or `REINSTATED` placement can be rotated). Rotation frees the slot for a new occupant. A `ROTATED_OUT` placement is not dead, though: an editor may reinstate it, subject to the same guards as activation — playlist `ACTIVE`, track `AVAILABLE` and release `LIVE`, slot free of `ACTIVE`/`REINSTATED` occupants (`ERR_SLOT_OCCUPIED` otherwise, noting that the placement's own `ROTATED_OUT` row never blocks its own reinstatement into the same slot) — and reinstatement restarts the cadence: `activated_on` is restamped to the logical clock and `scheduled_rotation_on` recomputed from the playlist's `rotation_cadence_days`. Placements are listable with optional `playlist_id`, `track_id`, `pitch_id`, and `status` filters.

Eviction is the involuntary exit and is always system-driven: when a track is removed, when its artist is suspended or terminated, or when its playlist is retired, every placement on the affected scope — whether `SCHEDULED`, `ACTIVE`, or `REINSTATED` — moves to `EVICTED`, which is terminal.

### 3.5. The Promotion Program: Discounted Royalty for Algorithmic Exposure

The promotion program is the platform's explicit trade: the rights holder accepts a royalty multiplier below 1 in exchange for algorithmic amplification, and the exchange is disclosed. Enrolling a track requires the `track_id`, a `discount_factor` strictly between 0 and 1 (a factor of 0.5 means the enrolled streams earn half royalty), a `starts_on` instant marking the closed start of the enrollment window, and an `ends_on` instant marking the open end, which must lie strictly after `starts_on`. The window must not overlap any other non-terminal enrollment for the same track — for overlap purposes, `ENROLLED` and `SUSPENDED` enrollments count as non-terminal while `TERMINATED` ones do not, and windows that merely touch at a boundary are permitted, since the end bound is open — and an overlapping or inverted window is rejected with `ERR_ENROLLMENT_WINDOW_OVERLAP`. Enrollment is also blocked while the track carries an `OPEN` or `AUTO_FLAGGED` fraud case (`ERR_FRAUD_HOLD`). A successful enrollment is `ENROLLED`, and the server mints a `disclosure_token` — an opaque server-generated string beginning with `disc_` — returned with the enrollment: the receipt proving the royalty-rate disclosure was made. Enrollments are listable with optional `track_id` and `status` filters.

The disclosure receipt is load-bearing. Suspending an enrollment requires the request to carry the `disclosure_token` minted at enroll time; a suspend attempted without it — or with the wrong token — is rejected with `ERR_DISCLOSURE_TOKEN_MISMATCH` (HTTP 403), and only an `ENROLLED` enrollment can be suspended. A `SUSPENDED` enrollment may be resumed by the rights holder, but resumption re-validates the world in a fixed order: the enrollment must be `SUSPENDED` and the logical clock must still be earlier than `ends_on` (either failure is `ERR_INVALID_STATE`), no other `ENROLLED` row for the same track may overlap the window (`ERR_ENROLLMENT_WINDOW_OVERLAP`), the track's artist must be `ACTIVE` (otherwise `ERR_INVALID_STATE`), and the track must carry no `OPEN` or `AUTO_FLAGGED` fraud case (`ERR_FRAUD_HOLD`). Termination, available to the rights holder or a `FraudAnalyst` from either `ENROLLED` or `SUSPENDED`, is final: streams already recorded keep the discount snapshot they accrued under, and future effective streams simply stop accruing the discount. The system also terminates enrollments as part of the fraud-confirmation, artist-suspension, artist-termination, and track-removal cascades.

### 3.6. Streams, Royalty Periods, and the Statement Waterfall

Stream ingestion is an operational act reserved for the `PlatformAdmin`. Each stream event carries the `track_id`, the `territory` where the stream occurred, a `source` of `EDITORIAL_PLAYLIST`, `ALGORITHMIC`, or `ORGANIC`, the `occurred_on` instant, and `ms_played` (zero or more milliseconds). Ingest requires an `OPEN` royalty period whose window covers `occurred_on`; a stream falling outside every open window is rejected with `ERR_NO_OPEN_PERIOD`. On success the event is bound to the covering period via `royalty_period_id` and recorded with `is_tainted` initially `false`. Streams are immutable once ingested and are listable with optional `track_id`, `royalty_period_id`, and `is_tainted` filters.

Royalty periods are opened by a `PlatformAdmin` with a `period_start` (closed bound), a `period_end` (open bound, strictly after the start), and the `pool_cents` total for the period. A period begins `OPEN`. Closing a period is the consequential act: it requires the logical clock to have reached `period_end`, requires that no other `OPEN` period's window overlaps this one — either failure yields `ERR_PERIOD_NOT_CLOSABLE` — and carries the optimistic-concurrency field of §2.7. The close request also names the share `variant`: `GROSS` or `EFFECTIVE`, frozen onto the period as `closed_variant`. Statements are then generated for every artist with at least one non-tainted stream in the period.

Statement generation is a waterfall with a pinned rounding order. The input set is the period's stream events with `is_tainted` equal to `false`. Each stream is weighted: if an enrollment row for the stream's track — in any of `ENROLLED`, `SUSPENDED`, or `TERMINATED` status — has a window covering the stream's `occurred_on` (closed at start, open at end), the stream's weight is that enrollment's `discount_factor`; otherwise the weight is 1.0. Because enrollment windows never overlap per track, at most one row matches. Each weight is rounded to 2 decimal places with round-half-up, then the weights are summed per artist to form `effective_streams` (reported on the statement as a decimal number, since the weighted sum is not in general an integer), while the plain count of the artist's matching streams forms `raw_streams`. The share variant then chooses the denominator: under `GROSS`, the denominator is the sum of `raw_streams` across all artists and each artist's `share_bps` is their raw count as a proportion of that denominator expressed in basis points of 10000, rounded half-up to an integer — the promotion discount has no effect on share. Under `EFFECTIVE`, the denominator is the sum of `effective_streams` across all artists and `share_bps` is computed the same way against it — enrolled streams count at their discounted weight, shrinking the enrolled artist's share and redistributing pool share to everyone else. Each artist's `gross_payout_cents` is then the floor of `pool_cents` multiplied by their `share_bps` divided by 10000. The remainder — `pool_cents` minus the sum of all floored payouts — is distributed one cent at a time to artists ordered by `share_bps` descending, ties broken by artist `created_at` ascending, and a further tie on `created_at` broken by the order the artists were registered, cycling back to the front of that ordering until the remainder is exhausted. The rounding order is pinned: per-artist floor first, remainder waterfall second.

A statement records the `period_id` and `artist_id` it belongs to alongside `raw_streams`, `effective_streams`, `share_bps`, `gross_payout_cents`, a `clawback_cents` figure that starts at 0 and grows as confirmed fraud cases land (§3.7), and a `net_payout_cents` equal to the gross payout minus the clawback — which may be negative. Statements are listable with optional `period_id` and `artist_id` filters. Settling a `CLOSED` period moves it to `SETTLED`: the statements become immutable and any pending clawbacks are locked into `net_payout_cents`.

### 3.7. Fraud Detection, Adjudication, and Clawback

Trust and safety works the fraud pipeline. A `FraudAnalyst` opens a case on a track by supplying the `track_id`, a suspected `window_start` (closed) and `window_end` (open), and three normalized signals: `signal_bot_ratio`, `signal_velocity_zscore`, and `signal_device_concentration`, each between 0 and 1 inclusive. At creation the system computes a `confidence_score`: 40 percent of the bot-ratio signal plus 35 percent of the velocity z-score signal plus 25 percent of the device-concentration signal, rounded to 4 decimal places with round-half-up. The score routes the verdict immediately: a score of at least 0.7000 opens the case as `AUTO_FLAGGED`; anything below opens it as `OPEN`. An `AUTO_FLAGGED` case does not suspend the track's enrollments — but it does put the track under the fraud hold of §2.6 and §3.3, blocking new pitch submissions, placement activation, and promotion enroll/resume while the case is unresolved. Cases are listable with optional `track_id` and `verdict` filters.

Adjudication is the analyst's decision, expressed through a `verdict` on the case. A `DISMISS` from either `OPEN` or `AUTO_FLAGGED` moves the case to `DISMISSED` with no further effect. A `CONFIRM` is gated: the case must be in `OPEN` or `AUTO_FLAGGED` (confirming a closed case is `ERR_INVALID_STATE`), and the `confidence_score` must be at least 0.8500 — a confirm attempted below that threshold is rejected with `ERR_FRAUD_THRESHOLD_NOT_MET`. A successful confirm moves the case to `CONFIRMED` (terminal) and detonates a precisely ordered cascade:

1. Every stream event for the track with `occurred_on` inside the case window — closed at `window_start`, open at `window_end` — that is not already tainted has `is_tainted` set to `true`. A stream already tainted by another case contributes nothing further; it is never double-charged.
2. The `clawback_cents` for the case is computed over the newly tainted streams: each contributes its effective rate — 1.0, or the covering enrollment's `discount_factor` if a promotion window covered the stream's instant — multiplied by the per-stream rate of 0.40 cents, and the products are summed and rounded half-up to 2 decimal places; the resulting `clawback_cents` amount is fractional (an exception to the integer-cents rule of §2.8), because 0.40-cent products do not in general sum to whole cents. If the artist has a statement in a period that is `CLOSED` but not yet `SETTLED`, the clawback is added to that statement's `clawback_cents` (the earliest-generated such statement, if several periods are closed) — a mutation that also advances the statement's `version` — and the statement's `net_payout_cents` is recomputed as gross minus clawback; otherwise the clawback is recorded on the case and swept into the artist's next generated statement at close time (that statement's `clawback_cents` starts from the swept amount rather than 0, with `net_payout_cents` reduced accordingly).
3. Every `ENROLLED` or `SUSPENDED` promotion enrollment on the track moves to `TERMINATED`.
4. Every `ACTIVE` or `REINSTATED` placement on the track moves to `EVICTED` (a still-`SCHEDULED` placement is untouched by this cascade, matching the artist-suspension scope).
5. The artist's `fraud_strikes` increments by 1. If the count reaches the strike limit of 2, the artist suspends with the full cascade of §3.1; if it reaches the termination limit of 3, the artist terminates with its wider cascade, including track removal — the strike at 3 supersedes, so the artist ends `TERMINATED` directly rather than passing through `SUSPENDED`.

### 3.8. Boost Scoring and Artist Profile Modules

The algorithmic side of the house consumes early listener signals through a signal rollup, submitted by a `PlatformAdmin` for a track with a `window_start`, a `window_end`, and three rates — `save_rate`, `completion_rate`, and `skip_rate` — each between 0 and 1 and computed over the track's non-tainted streams in the window. The boost computation blends the rates: half the save rate plus three-tenths of the completion rate minus one-fifth of the skip rate, scaled by 100, forms a raw score. A tier multiplier drawn from the artist's `follower_count` then applies: 0.8 when the artist has fewer than 10000 followers, 1.0 from 10000 up to but not including 100000, and 1.2 at 100000 or more. The raw score is multiplied by the tier multiplier, floored to an integer, then clamped: the floor of the product is bounded below by 0 (a skip rate heavy enough to push the raw score negative yields 0, never a negative score) and capped above at the boost cap of 90 — a raw result landing exactly on 90 keeps the score at 90, since the cap is inclusive. The floor is applied after the tier multiplier, not before.

The editorial-versus-algorithmic trade-off surfaces in the variant. A placement counts as held during the window when it was activated before the window's end and was not rotated out or evicted at or before the window's start — a still-running placement (no deactivation yet) qualifies on its activation alone, and both automatic and manual rotations and evictions record the deactivation instant that closes the interval. When the track held at least one `ACTIVE` or `REINSTATED` placement during the rollup window in that sense, the variant is `STANDARD` and the score stands as computed. When the track had no editorial placement during the window, the variant is `COLD_START` and the score is halved — floored to an integer after halving — because the algorithmic pipelines respond more weakly without an editorial signal. The rollup response carries the computed `boost_score` and the `variant`.

Artists also control their profile surface. A `RightsHolder` attaches a profile module to their own artist with the `artist_id`, a `module_type` of `CANVAS` or `MERCH`, and a `payload_uri` pointing at the media or storefront. A `CANVAS` module additionally requires the `track_id` of the track the canvas loops on — any existing track may be referenced, regardless of which artist owns it; for a `MERCH` module the `track_id` is ignored (the module is stored with no `track_id`). A new module is `ENABLED`. Modules are listable with optional `artist_id`, `track_id`, `module_type`, and `status` filters, and the rights holder may disable a module at will, moving it to `DISABLED`. The system disables modules too: artist termination disables every `ENABLED` module on the artist, and removing the track a `CANVAS` module loops on disables that module. `DISABLED` is terminal.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource or drive a state transition return `200 OK`. The full service is mounted under `/catalog`. Request bodies, preconditions, and side effects for each operation are specified in §3; this table is the index.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/catalog/artists` | Register an artist (rights-holder identity) | PlatformAdmin |
| GET | `/catalog/artists/{id}` | Fetch an artist | PlatformAdmin, RightsHolder, PlaylistEditor, EditorialLead, FraudAnalyst |
| GET | `/catalog/artists` | List artists | PlatformAdmin, PlaylistEditor, EditorialLead, FraudAnalyst |
| POST | `/catalog/artists/{id}/suspend` | Suspend an artist | FraudAnalyst |
| POST | `/catalog/artists/{id}/reinstate` | Reinstate a suspended artist | FraudAnalyst |
| POST | `/catalog/releases` | Create a release with metadata, genre/mood tags, territory allowlist | RightsHolder |
| GET | `/catalog/releases/{id}` | Fetch a release | PlatformAdmin, RightsHolder, PlaylistEditor, EditorialLead, FraudAnalyst |
| GET | `/catalog/releases` | List releases, filterable by artist_id/status | PlatformAdmin, RightsHolder, PlaylistEditor, EditorialLead, FraudAnalyst |
| POST | `/catalog/releases/{id}/change-date` | Change the scheduled release date (OCC-guarded); withdraws pitches that lose the minimum lead | RightsHolder |
| POST | `/catalog/releases/{id}/remove` | Remove a release (SCHEDULED by rights holder; LIVE only via fraud cascade) | RightsHolder, FraudAnalyst |
| POST | `/catalog/tracks` | Add a track to a release; exactly one focus track per release | RightsHolder |
| GET | `/catalog/tracks/{id}` | Fetch a track | PlatformAdmin, RightsHolder, PlaylistEditor, EditorialLead, FraudAnalyst |
| GET | `/catalog/tracks` | List tracks, filterable by release_id/status | PlatformAdmin, RightsHolder, PlaylistEditor, EditorialLead, FraudAnalyst |
| POST | `/catalog/tracks/{id}/signal-rollup` | Submit early-listener-signal rollup for a track; computes the boost score | PlatformAdmin |
| POST | `/catalog/playlists` | Create an editorial playlist | EditorialLead |
| GET | `/catalog/playlists/{id}` | Fetch a playlist | PlatformAdmin, RightsHolder, PlaylistEditor, EditorialLead, FraudAnalyst |
| GET | `/catalog/playlists` | List playlists | PlatformAdmin, PlaylistEditor, EditorialLead |
| POST | `/catalog/playlists/{id}/retire` | Retire a playlist; evicts all non-terminal placements | EditorialLead |
| POST | `/catalog/pitches` | Submit an editorial pitch for the focus track, ahead of release | RightsHolder |
| GET | `/catalog/pitches/{id}` | Fetch a pitch | PlatformAdmin, RightsHolder, PlaylistEditor, EditorialLead |
| GET | `/catalog/pitches` | List pitches, filterable | PlatformAdmin, RightsHolder, PlaylistEditor, EditorialLead |
| POST | `/catalog/pitches/{id}/claim` | Editor claims a pitch into UNDER_REVIEW (owning team only) | PlaylistEditor |
| POST | `/catalog/pitches/{id}/request-revision` | Send pitch back for revision | PlaylistEditor |
| POST | `/catalog/pitches/{id}/revise` | Rights holder re-pitches with new text (bounded revision loop) | RightsHolder |
| POST | `/catalog/pitches/{id}/decide` | Editorial lead accepts (creates SCHEDULED placement) or rejects | EditorialLead |
| POST | `/catalog/pitches/{id}/withdraw` | Rights holder withdraws a non-terminal pitch | RightsHolder |
| GET | `/catalog/placements/{id}` | Fetch a placement | PlatformAdmin, RightsHolder, PlaylistEditor, EditorialLead |
| GET | `/catalog/placements` | List placements, filterable by playlist_id/track_id/status | PlatformAdmin, RightsHolder, PlaylistEditor, EditorialLead |
| POST | `/catalog/placements/{id}/activate` | Activate a SCHEDULED placement into its slot | PlaylistEditor |
| POST | `/catalog/placements/{id}/rotate` | Rotate a placement out at/after cadence end | PlaylistEditor |
| POST | `/catalog/placements/{id}/reinstate` | Reinstate a ROTATED_OUT placement (rotation cycle) | PlaylistEditor |
| POST | `/catalog/promotions` | Enroll a track in the reduced-royalty algorithmic promotion program (disclosed) | RightsHolder |
| GET | `/catalog/promotions/{id}` | Fetch an enrollment | PlatformAdmin, RightsHolder, FraudAnalyst |
| GET | `/catalog/promotions` | List enrollments, filterable by track_id/status | PlatformAdmin, RightsHolder, FraudAnalyst |
| POST | `/catalog/promotions/{id}/suspend` | Suspend an enrollment; requires the disclosure token | RightsHolder |
| POST | `/catalog/promotions/{id}/resume` | Resume a suspended enrollment | RightsHolder |
| POST | `/catalog/promotions/{id}/terminate` | Terminate an enrollment | RightsHolder, FraudAnalyst |
| POST | `/catalog/streams` | Ingest a stream event into the OPEN royalty period | PlatformAdmin |
| GET | `/catalog/streams/{id}` | Fetch a single stream event | PlatformAdmin, FraudAnalyst |
| GET | `/catalog/streams` | List stream events, filterable | PlatformAdmin, FraudAnalyst |
| POST | `/catalog/fraud-cases` | Open a fraud case on a track window; confidence computed, AUTO_FLAGGED at/above threshold | FraudAnalyst |
| GET | `/catalog/fraud-cases/{id}` | Fetch a fraud case | PlatformAdmin, FraudAnalyst |
| GET | `/catalog/fraud-cases` | List fraud cases, filterable by track_id/verdict | PlatformAdmin, FraudAnalyst |
| POST | `/catalog/fraud-cases/{id}/adjudicate` | Confirm (threshold-gated, cascades taint+clawback+evictions) or dismiss | FraudAnalyst |
| POST | `/catalog/royalty-periods` | Open a royalty period | PlatformAdmin |
| GET | `/catalog/royalty-periods/{id}` | Fetch a period | PlatformAdmin, FraudAnalyst, RightsHolder |
| GET | `/catalog/royalty-periods` | List periods | PlatformAdmin, FraudAnalyst |
| POST | `/catalog/royalty-periods/{id}/close` | Close a period, freezing the share variant and generating statements (OCC-guarded) | PlatformAdmin |
| POST | `/catalog/royalty-periods/{id}/settle` | Settle a closed period; statements become immutable | PlatformAdmin |
| GET | `/catalog/royalty-statements/{id}` | Fetch a single royalty statement | PlatformAdmin, RightsHolder, FraudAnalyst |
| GET | `/catalog/royalty-statements` | List statements, filterable by period_id/artist_id | PlatformAdmin, RightsHolder, FraudAnalyst |
| POST | `/catalog/profile-modules` | Attach a CANVAS or MERCH module to the artist profile | RightsHolder |
| GET | `/catalog/profile-modules/{id}` | Fetch a single profile module | PlatformAdmin, RightsHolder |
| GET | `/catalog/profile-modules` | List profile modules, filterable by artist_id/track_id/module_type/status | PlatformAdmin, RightsHolder |
| POST | `/catalog/profile-modules/{id}/disable` | Disable a profile module | RightsHolder |
| POST | `/catalog/presaves` | Register a fan pre-save for a scheduled release | PlatformAdmin |
| GET | `/catalog/presaves/{id}` | Fetch a single pre-save | PlatformAdmin, RightsHolder |
| GET | `/catalog/presaves` | List pre-saves, filterable by release_id/status | PlatformAdmin, RightsHolder |
| POST | `/catalog/presaves/{id}/cancel` | Cancel a pre-save | PlatformAdmin, RightsHolder |
| POST | `/catalog/_clock/set_current_utc` | Set the logical clock; advancing it fires time-driven transitions | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_PITCH_WINDOW_CLOSED` | 409 |
| `ERR_PITCH_NOT_PITCHABLE` | 409 |
| `ERR_PLAYLIST_FIT_MISMATCH` | 409 |
| `ERR_FRAUD_HOLD` | 409 |
| `ERR_DATE_CHANGE_WINDOW` | 409 |
| `ERR_ENROLLMENT_WINDOW_OVERLAP` | 409 |
| `ERR_SLOT_OCCUPIED` | 409 |
| `ERR_ROTATION_TOO_EARLY` | 409 |
| `ERR_NO_FREE_SLOT` | 409 |
| `ERR_PERIOD_NOT_CLOSABLE` | 409 |
| `ERR_NO_OPEN_PERIOD` | 409 |
| `ERR_FRAUD_THRESHOLD_NOT_MET` | 409 |
| `ERR_DISCLOSURE_TOKEN_MISMATCH` | 403 |
| `ERR_TERRITORY_RESTRICTED` | 422 |
