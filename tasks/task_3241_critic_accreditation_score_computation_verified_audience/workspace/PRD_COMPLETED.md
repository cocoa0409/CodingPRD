# Critic Accreditation, Score Computation & Verified Audience API — Product Requirements Document

## 1. Introduction

This platform aggregates professional film criticism and audience reaction into two publicly displayed scores per release: a critic-side percentage (the "tomatometer") and an audience-side percentage. Neither number is a raw average. The critic side gates certification behind minimum review counts and a minimum number of designated top critics; the audience side only counts ratings whose author has proven, via a partner-exhibitor ticket verification, that they actually saw the film. Both sides are recomputed from structured input sets every time their inputs change, and each recomputation appends a new immutable score snapshot while superseding the prior one.

The trust model has three legs. First, critics and their employing publications are accredited by an independent board, with periodic accreditation reviews that can uphold standing, place the subject on probation, or revoke accreditation entirely — revocation cascades into the score input sets because a revoked critic's reviews no longer count toward the certified score. Second, embargoes are enforced against a logical clock that test operators can advance deterministically; a review may not be published before its release's embargo instant, though publication at exactly that instant is permitted. Third, review-bombing detection computes a weighted index over the trailing twenty-four hours of rating activity; when the index crosses the bombing threshold and an administrator confirms the incident, the release's audience score display is suspended and in-window ratings are invalidated until the incident is resolved.

Studios and critics can dispute review classifications and displayed scores. Disputes follow a triage workflow with optimistic-concurrency protection on rulings, and a segregation-of-duties rule forbids a critic from disputing the classification of their own review. This document is the complete contract for implementers: global API conventions in §2, business workflows in §3, the endpoint table in §4, and the error catalogue in §5.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID` identifies the caller and `X-User-Role` declares the caller's role. A request missing either header, or declaring a role outside the role set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose declared role is not permitted for the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

Five roles exist, spelled exactly as follows:

- `PlatformAdmin` — platform operations: titles, releases, publications, critics, audience members, ticket-verification rulings, bombing incidents, and the logical clock. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- `AccreditationBoard` — the board governing accreditation reviews, accreditation transitions on publications and critics, and dispute rulings. When `X-User-Role` is `AccreditationBoard`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- `Critic` — an accredited critic authoring reviews and disputing others' classifications. When `X-User-Role` is `Critic`, `X-User-ID` is the `id` of the acting `Critic` entity; ownership checks on any resource that references a critic (for example, a review's `critic_id`) compare the resource's foreign-key field to `X-User-ID`. A mismatch on an author-only or owner-only operation is rejected with `ERR_FORBIDDEN` (HTTP 403).
- `StudioRep` — a studio representative filing disputes over classification and score display. When `X-User-Role` is `StudioRep`, `X-User-ID` is an opaque operator identifier; a studio filer identifies themselves in the dispute body via `filed_by_studio` rather than via the header.
- `AudienceMember` — a registered audience member submitting ticket verifications and ratings. When `X-User-Role` is `AudienceMember`, `X-User-ID` is the `id` of the acting `AudienceMember` entity; ownership checks compare a resource's `audience_member_id` to `X-User-ID`, with mismatches rejected as `ERR_FORBIDDEN`.

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

List endpoints accept `limit` and `offset` query parameters. `limit` defaults to 10, with a minimum of 1 and a maximum of 100; `offset` defaults to 0. List responses report `limit`, `offset`, `total_count`, and `has_more` inside `meta`. All list endpoints sort by `created_at` ascending unless otherwise stated.

### 2.4. Resource Identity, Timestamps, and Versioning

Every persisted entity carries an `id` that is a server-minted UUID with no type prefix, a `created_at` timestamp, an `updated_at` timestamp, and an integer `version`. All timestamps are ISO 8601 UTC with three fractional digits. The `id` is a UUID rendered as a 32-character lowercase hexadecimal string (no dashes). `version` starts at 1 on creation and increments by exactly 1 on every mutation of that entity; `updated_at` is refreshed to the current logical clock on every mutation. No entity in this domain omits the common fields.

List responses order items by `created_at` ascending with ties broken by `id` ascending, and `has_more` is true exactly when `offset + (number of items in the returned page)` is less than `total_count`.

### 2.5. The Logical Clock

The platform evaluates all temporal rules — embargo checks, theatrical-window checks, review windows, bombing-detection windows — against a logical clock, never wall-clock time. Before any clock-advance call, the logical clock reads exactly `2026-09-01T00:00:00Z`. A `PlatformAdmin` may advance the clock to a supplied `to_iso8601` instant; an unparsable `to_iso8601` is rejected with `ERR_INVALID_REQUEST`, and the response echoes the new instant as `current_utc`. After such a call, embargo and window checks evaluate against the new instant.

### 2.6. Optimistic Concurrency Control

Two write operations are protected by optimistic concurrency control, and only those two carry a version field:

- A manual score recalculation against a release must carry `expected_release_version` matching the release's current `version`. If another writer has advanced the release's version since the client last read it — for example by publishing or withdrawing a review, which legitimately supersedes the client's view of the score input set — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from recomputing from a release state it has not observed.
- A dispute transition (triage, return, or ruling) must carry `expected_dispute_version` matching the dispute's current `version`. A mismatch is likewise rejected with `ERR_STALE_VERSION` (HTTP 412), preventing a ruling from being applied on top of a dispute state the board member has not observed.

No other endpoint accepts a version field.

### 2.7. Precision, Rounding, and Score Snapshot Discipline

All computed percentages are integers from 0 to 100 produced by rounding half-up; where a ratio is formed, the ratio is computed as an exact rational and rounded exactly once at the end — per-bucket pre-rounding is forbidden because it drifts the total. Standing scores and bombing-detection indices are integers in basis points from 0 to 10000. When a score's input set is empty, the percentage is null — it is never reported as 0 — and attempting to persist a snapshot from an empty input set is rejected with `ERR_SCORE_NOT_COMPUTABLE` (HTTP 409) on the manual-recalculation path that guards it (see §3.5).

Every score recomputation appends a new `ScoreSnapshot` row recording the `release_id`, the `scope` (`TOMATOMETER` or `AUDIENCE_VERIFIED`), the `variant` (`PROVISIONAL` or `CERTIFIED` for the tomatometer; `ALL_RATINGS` or `VERIFIED_ONLY` for the audience score), the `positive_count`, the `total_count`, and the resulting `pct`. The previous non-superseded snapshot for the same release, scope, and variant is marked `superseded` (a boolean defaulting to false). Snapshots are never updated in place — marking the prior snapshot superseded is the sole mutation permitted on an existing snapshot; history is the audit trail.

### 2.8. Validation Order

Every request is validated against the applicable rules in a fixed priority order, and the first failing rule determines the response:

1. Authentication — headers present and role declared (`ERR_UNAUTHENTICATED`).
2. Authorization — role permitted for the endpoint (`ERR_UNAUTHORIZED`).
3. Existence — path identifiers exist, validated left-to-right along nested paths, and body foreign-key references exist (`ERR_NOT_FOUND`).
4. Request shape — required fields present, enum values valid, `stars` within 1 through 5 inclusive, exactly one of `subject_critic_id` or `subject_publication_id` set on an accreditation review, and dispute filer fields consistent with `dispute_kind` (`ERR_INVALID_REQUEST`).
5. State admissibility — the target entity is in a state that admits the requested transition (`ERR_INVALID_STATE`).
6. Optimistic concurrency — the expected-version field matches (`ERR_STALE_VERSION`).
7. through 19. The domain business rules described in §3, applied in the order their narratives present them.

Because authentication precedes authorization and existence, a caller without a valid role learns nothing about whether a resource exists.

## 3. Business Logic & Workflows

### 3.1. Publications and Critic Accreditation

A `PlatformAdmin` registers a publication by supplying its `outlet_name` and `reach_tier`. The outlet name must be unique across all publications that are not in `REVOKED` status; a duplicate is rejected with `ERR_INVALID_REQUEST`. The reach tier is one of `NATIONAL`, `REGIONAL`, or `NICHE` and records the publication's accreditation weight class. A new publication starts in `PENDING` status with `accredited_critic_count` of 0 and remains there until the `AccreditationBoard` acts.

The board drives the publication lifecycle through transition requests whose body carries an `action` selector. Accrediting a publication moves it from `PENDING` to `ACCREDITED`. Placing an accredited publication on probation moves it from `ACCREDITED` to `PROBATION`; this transition recomputes the publication's `accredited_critic_count`, which by itself leaves the count unchanged. Reinstating moves a publication from `PROBATION` back to `ACCREDITED`. Revocation is never invoked directly: when an accreditation review is ruled with a revoke outcome against a publication in either `ACCREDITED` or `PROBATION` status, the publication transitions to `REVOKED` automatically, and every linked critic whose `accreditation_status` is `ACCREDITED` or `PROBATION` transitions to `REVOKED` as well, each firing the critic-revocation cascade described below. `REVOKED` is terminal for a publication.

A `PlatformAdmin` registers a critic with a `full_name`, the employing `publication_id`, and an optional `is_top_critic` flag (defaulting to false) that marks top-critic designation used by the certification rule. A new critic starts with `accreditation_status` of `APPLIED`, carries `standing_score_bps` of 10000 (the unpredicated base value) until a standing-score rule recomputes it, and carries `last_review_period_start` null until the critic's first periodic review closes, at which point it records the start instant of that review.

The board accredits an applicant by transitioning the critic from `APPLIED` to `ACCREDITED`, but only when the employing publication is itself `ACCREDITED`; otherwise the transition is rejected with `ERR_PUBLICATION_NOT_ACCREDITED` (HTTP 409). A successful accreditation increments the employing publication's `accredited_critic_count`. The board may also move a critic from `ACCREDITED` to `PROBATION` (probation), from `PROBATION` back to `ACCREDITED` (reinstatement), and a revoked critic may re-apply — the critic themselves performs the re-application transition from `REVOKED` back to `APPLIED`, and only on their own record. Re-application followed by re-accreditation restores the publication's `accredited_critic_count` exactly once per critic. `REVOKED` is therefore not terminal for a critic.

Revocation of a critic fires the most consequential cascade in the system. Whether it arrives via an accreditation review ruled against the critic directly, or via revocation of the employing publication, the effect is identical: the publication's `accredited_critic_count` is decremented exactly once (floored at zero) — only when the critic currently counts toward it, i.e. is `ACCREDITED`, `PROBATION`, or `UNDER_REVIEW` — and every review by that critic in `PUBLISHED` or `FLAGGED` status is marked de-accredited for scoring, which recomputes the tomatometer (both variants) and the certification for every affected release, each recompute emitting new snapshots that supersede the prior ones. Reinstatement from `PROBATION` to `ACCREDITED` fires the mirror cascade: the critic's published or flagged reviews are marked accredited for scoring again and the affected releases' tomatometer and certification are recomputed. Anyone may retrieve a publication, a critic, or the roster of critics employed by a publication.

### 3.2. Periodic Accreditation Reviews

The `AccreditationBoard` files a periodic accreditation review against exactly one subject: either a `subject_critic_id` or a `subject_publication_id` — supplying both or neither is rejected with `ERR_INVALID_REQUEST`. The filing body carries the review window `period_start` (inclusive) and `period_end` (exclusive), forming a half-open interval, plus an optional `decision_note`. A new review starts in `FILED` status. Filing against an `ACCREDITED` critic immediately moves that critic to `UNDER_REVIEW`.

Beginning the review moves it from `FILED` to `IN_REVIEW`, and this is where the overlap guard fires: the window must not half-open-overlap any other non-`DISMISSED` review for the same subject. Two windows that merely touch — one review's `period_end` equal to the other's `period_start` — are adjacent, not overlapping, and are permitted. A true overlap is rejected with `ERR_ACC_REVIEW_PERIOD_OVERLAP` (HTTP 409).

From `IN_REVIEW` the board rules in one of three ways, recording the rationale in `decision_note` at ruling time:

- **Uphold** moves the review to `UPHELD`. For a critic subject, the critic returns to `ACCREDITED`, the critic's `standing_score_bps` is recomputed under the final standing-score variant over the review window, and the critic's `last_review_period_start` is set to the review's `period_start`.
- **Revoke** moves the review to `REVOKED` and drives the subject — critic or publication — to `REVOKED` with the full cascades described in §3.1.
- **Dismiss** moves the review to `DISMISSED`; a critic who is `UNDER_REVIEW` because of this review returns to `ACCREDITED` with no other effect.

`UPHELD`, `REVOKED`, and `DISMISSED` are terminal for a review. The board and platform administrators may list reviews, filtering by `subject_critic_id` or `subject_publication_id`, and may fetch any single review.

The critic standing score exists in two variants. The **final** variant runs at an uphold ruling over the half-open review window: for each `CLASSIFICATION` dispute in `UPHELD` status whose subject review is authored by the critic and whose `published_at` falls inside the half-open window, subtract 1500 basis points from a base of 10000, and clamp the result into the 0-to-10000 range. The **provisional** variant is a preview over the trailing 365 days ending at the logical clock: it has the same shape, except that reviews of the critic still sitting in `FLAGGED` status under a pending (non-terminal) dispute are penalised at 500 basis points each instead of 1500. The two variants therefore produce different scores for the same critic whenever pending disputes exist; the final variant is authoritative at ruling time.

### 3.3. Titles, Releases, and the Embargo Gate

A `PlatformAdmin` creates a title with a `canonical_name` and an integer `release_year`. A title's `posture` begins at `SETUP`, moves to `OPEN` when the administrator updates the posture, and finally to `RETIRED`; retirement is terminal. Re-releases, director's cuts, and other variants of the same film are separate releases under the same title rather than separate titles.

Under an existing title the administrator creates a release by supplying a `cut_label` (for example `THEATRICAL`, `DIRECTORS_CUT`, or `RERELEASE_2026` — any string is accepted; the value is not an enum), a `theatrical_window_start` and `theatrical_window_end` forming a closed interval — both endpoints inclusive — and an `embargo_until` instant. A new release starts in `UPCOMING` status, carries `audience_display_suspended` false, and has null `tomatometer_pct`, null `audience_score_pct`, and `certification` of `NONE` until its score input sets become non-empty; no score snapshots are created at release creation.

Opening a release moves it from `UPCOMING` to `OPEN` and is permitted only while the parent title's posture is `OPEN`; otherwise the transition is rejected with `ERR_TITLE_NOT_OPEN` (HTTP 409). Closing moves a release from `OPEN` to `CLOSED`, which is terminal. Releases may be listed (optionally filtered by `title_id`) and fetched by anyone; the fetched representation includes `tomatometer_pct`, `audience_score_pct`, `certification`, and `audience_display_suspended`, plus an `audience_display` field that is `SUSPENDED` while `audience_display_suspended` is true — in which case the representation also nulls `audience_score_pct` (§3.6) — and `ACTIVE` otherwise.

### 3.4. Critic Reviews: Ingestion, Publication, Withdrawal

A `Critic` ingests a review against a release by providing the `critic_id`, the `body_text`, and a `self_designation` of `FRESH` or `ROTTEN`. The `critic_id` must equal the caller's `X-User-ID`; impersonation is rejected with `ERR_FORBIDDEN`. Ingestion requires the critic to be `ACCREDITED` or on `PROBATION` — a critic in any other status is rejected with `ERR_CRITIC_NOT_ACCREDITED` (HTTP 409) — and a critic may hold at most one review not in `WITHDRAWN` status per release; a second live review is rejected with `ERR_DUPLICATE_REVIEW` (HTTP 409). The accreditation check precedes the duplicate-review check, so a non-accredited critic with an existing live review receives `ERR_CRITIC_NOT_ACCREDITED`. Ingestion never inspects the release's status: a review may be ingested against an `UPCOMING`, `OPEN`, or `CLOSED` release alike — the release-status gate applies only at publication. A new review starts in `INGESTED` status with `classification` and `published_at` both null.

Publishing moves a review from `INGESTED` to `PUBLISHED` and is the most heavily guarded transition in the system. The acting critic must be the review's author (`ERR_FORBIDDEN` otherwise). The guards then run in this exact order, the first failure determining the response: the author's `accreditation_status` must be `ACCREDITED` or `PROBATION` (`ERR_CRITIC_NOT_ACCREDITED`); the release must be `OPEN` (`ERR_INVALID_STATE`); and the logical clock must have reached the release's `embargo_until` — publication at exactly the embargo instant is allowed, anything earlier is rejected with `ERR_EMBARGO_ACTIVE` (HTTP 409). (Per §2.8, the review's own state admissibility — it must be `INGESTED` — is checked at priority 5, before these domain rules; thus a revoked author's publish attempt on a still-embargoed release yields `ERR_CRITIC_NOT_ACCREDITED`, not `ERR_EMBARGO_ACTIVE`.) On a successful publish the review's `classification` is set equal to its `self_designation`, `published_at` is stamped with the current logical clock, and the release's tomatometer is recomputed in both variants with new snapshots superseding the prior ones and `tomatometer_pct` and `certification` refreshed.

The author may withdraw a review from either `PUBLISHED` or `FLAGGED`, moving it to the terminal `WITHDRAWN` status; withdrawal by anyone other than the author is rejected with `ERR_FORBIDDEN`. Withdrawing a flagged review has a secondary effect: any classification dispute against that review still in `FILED` or `TRIAGED` status is automatically rejected as moot. Every withdrawal recomputes the release's tomatometer and certification with superseding snapshots.

Filing a classification dispute against a published review moves that review from `PUBLISHED` to `FLAGGED`. When the dispute is later rejected — or upheld with the classification unchanged — the review returns to `PUBLISHED`; when it is upheld with a different requested classification, the review's `classification` becomes the requested value and the release's tomatometer and certification are recomputed before the review returns to `PUBLISHED`. Reviews may be listed (filtered by `release_id` or `critic_id`) and fetched by anyone.

### 3.5. Tomatometer, Certification, and Manual Recalculation

The tomatometer is recomputed on every event that changes its input set: a review publish, a withdrawal, a reclassification via an upheld dispute, a critic revocation or reinstatement cascade, an upheld score-display dispute, or a manual recalculation request. It has two variants:

- The **provisional** variant counts every review on the release in `PUBLISHED` or `FLAGGED` status — `WITHDRAWN` reviews are excluded — including reviews by revoked critics and reviews whose critic is under review. There is no minimum-count gate. The percentage is one hundred times the number of reviews whose `classification` is `FRESH`, divided by the total counted, rounded half-up to an integer percent. This variant is always computed and powers the pre-certification display.
- The **certified** variant uses the same formula over a narrower input set: only reviews whose author's `accreditation_status` is `ACCREDITED` or `PROBATION` at compute time are counted. This variant powers the certification decision and the certified display: a release's `tomatometer_pct` is set from the certified-variant percentage (null when the certified input set is empty).

When a variant's input set is empty, its percentage is null rather than zero. Each recompute appends one new snapshot per variant and marks the previous same-variant snapshot `superseded`.

Certification re-evaluates after every certified-variant recompute, in a pinned order. First, from the certified input set, derive three numbers: `N`, the total counted reviews; `P`, the certified percentage; and `T`, the number of counted reviews authored by critics whose `is_top_critic` is true. Then the gates run in sequence: if `N` is fewer than 5, certification is `NONE` and evaluation stops. Otherwise, if `T` is fewer than 2, certification is `NONE` and evaluation stops. Otherwise, a percentage of at least 75 earns `CERTIFIED_FRESH`; a percentage of at most 60 earns `CERTIFIED_ROTTEN`; anything in between is `NONE`. All boundaries are inclusive exactly as written. Because accreditation changes alter the certified input set and the score in turn alters certification, this evaluation order is the only sanctioned order — implementations must not interleave the steps.

A `PlatformAdmin` or `AccreditationBoard` member may force a manual recalculation of a release's scores. The request carries `expected_release_version` and obeys the OCC rule of §2.6. After the version check passes, the recalculation is rejected with `ERR_SCORE_NOT_COMPUTABLE` (HTTP 409) when both score input sets are empty — that is, when the release has no review in `PUBLISHED` or `FLAGGED` status and no audience rating in `VERIFIED` or `UNVERIFIED` status; on that path no snapshots are persisted and the release's `version` is not incremented. (This is the concrete trigger for the §2.7 rule against persisting a snapshot from an empty input set; automatic recomputes triggered by other workflows are not gated this way — they append null-`pct` snapshots per §2.7 and §3.5.) On success both the tomatometer and the audience score are recomputed and new snapshots supersede the prior ones. Anyone may list a release's score snapshots to inspect the full audit history.

### 3.6. Audience Members, Ticket Verification, and the Verified Audience Score

A `PlatformAdmin` registers an audience member with a unique `email` and a public `display_name`; the member's `account_created_at` is stamped with the logical clock at registration and equals the record's `created_at` — bombing detection relies on this instant.

An `AudienceMember` submits a ticket verification against a release by supplying the `audience_member_id`, the `showtime_at` instant, and the partner `exhibitor_code`. The `audience_member_id` must equal the caller's `X-User-ID` (`ERR_FORBIDDEN` otherwise). A new verification starts in `SUBMITTED` status. A `PlatformAdmin` then rules on it: verifying requires the `showtime_at` to fall inside the release's theatrical window as a closed interval — a showtime exactly at `theatrical_window_start` or exactly at `theatrical_window_end` is inside — and a showtime outside that window is rejected with `ERR_VERIFICATION_WINDOW_MISS` (HTTP 409). A verification may instead be rejected outright. Both `VERIFIED` and `REJECTED` are terminal. Verifications can be listed, filtered by `release_id` or `audience_member_id`, and fetched.

An `AudienceMember` rates a release by providing the `audience_member_id`, an integer `stars` value from 1 through 5 inclusive, and optionally a `ticket_verification_id`. The member id must equal the caller's `X-User-ID`. At most one rating not in `INVALIDATED` status may exist per member per release; a second live rating is rejected with `ERR_DUPLICATE_VERIFIED_RATING` (HTTP 409). A new rating starts `UNVERIFIED`, and its creation recomputes the all-ratings diagnostic variant.

The rating's owner may verify it by transitioning it from `UNVERIFIED` to `VERIFIED`, supplying a `ticket_verification_id` that references a ticket verification in `VERIFIED` status for the same release and the same `audience_member_id`; anything else is rejected with `ERR_TICKET_NOT_VERIFIED` (HTTP 409). Verification is additionally blocked while the release's `audience_display_suspended` is true because a confirmed bombing incident covers it — such an attempt is rejected with `ERR_BOMBING_SUSPENSION_ACTIVE` (HTTP 409), though unverified ratings may still be created during a suspension. Ratings can move from `VERIFIED` to `INVALIDATED` in two ways: an administrator invalidates directly, or a confirmed bombing incident invalidates in-window ratings automatically (see §3.7). An administrator may also invalidate an `UNVERIFIED` rating directly. Both verification and invalidation recompute the verified audience variant and refresh the release's `audience_score_pct`. Ratings can be listed — filtered by `release_id`, `audience_member_id`, or `ticket_verification_id` — and fetched. On verify, the rating's `ticket_verification_id` field is set to the supplied id, replacing any prior value.

The audience score has two variants. The **verified-only** variant, which powers the public `audience_score_pct`, counts ratings in `VERIFIED` status: the percentage is one hundred times the number of those ratings with `stars` of at least 4, divided by the total verified count, rounded half-up once to an integer percent. The **all-ratings** variant is a diagnostic that additionally counts `UNVERIFIED` ratings and can diverge sharply from the verified figure under manipulation; it is surfaced on the score read for comparison. For both variants the per-star-bucket counts are formed as integers first, the single positive-over-total ratio is formed as an exact rational, and only the final percentage is rounded — pre-rounding buckets is forbidden. An empty input set yields null. While `audience_display_suspended` is true the score is still computed internally, but the score read reports `audience_display` as `SUSPENDED` and reports `audience_score_pct` as null in the payload.

### 3.7. Review-Bombing Detection and Suspension

A `PlatformAdmin` opens a review-bombing incident against a release; the detection index is computed once, at open time, and stored as `detection_index_bps`. The index looks at the trailing twenty-four hours of activity ending at the logical clock: the window covers ratings created at or after the window start and at or before the present instant — because entities are stamped at the logical clock, activity created exactly at the present instant is in-window, so the window is half-open only on the past side. Over the ratings created in that window, of any status, three quantities are derived: `V`, the total count; `N`, how many of those raters have an `account_created_at` inside the same window (with the same closed-at-the-present boundary); and `S`, how many rated 2 stars or fewer. Each of the two shares is rounded half-up to an integer percent before weighting — that rounding order is pinned — using a denominator of `V`, or 1 when `V` is zero. The index is the smaller of 10000 and the weighted sum: 20 times `V`, plus 40 times the new-account percent, plus 30 times the negative-skew percent. An index of at least 6000 basis points marks the incident as auto-flagged, which is informational only; the incident's `status` remains `OPEN` until an administrator acts.

An administrator may dismiss an open incident, moving it to the terminal `DISMISSED` status with no further effect, or confirm it, moving it to `CONFIRMED`. Confirmation suspends the release's audience display — `audience_display_suspended` becomes true — and invalidates the audience ratings created within the incident window: the trailing twenty-four hours ending at the logical clock *at confirmation time*, with the same boundary semantics as detection (a rating created exactly at the present instant is in-window). Only ratings in `VERIFIED` or `UNVERIFIED` status are invalidated — ratings already `INVALIDATED` are skipped — and each invalidated rating's `version` increments by 1 as a normal mutation; after all in-window invalidations are applied, the audience score is recomputed, refreshing `audience_score_pct` with new superseding snapshots. Later, the administrator resolves a confirmed incident, moving it to the terminal `RESOLVED` status: `audience_display_suspended` returns to false and the verified audience score is recomputed, refreshing `audience_score_pct`. Incidents for a release can be listed by anyone.

### 3.8. Disputes: Classification and Score Display

Disputes come in two kinds, named by `dispute_kind`: `CLASSIFICATION` disputes target a review via `subject_review_id`, and `SCORE_DISPLAY` disputes target a release via `subject_release_id`. The filer is either a critic, identified by `filed_by_critic_id`, or a studio representative, identified by the free-text studio name `filed_by_studio`; the filer fields must be consistent with the dispute kind and filer type, and malformed combinations are rejected with `ERR_INVALID_REQUEST`. Concretely, exactly one filer field must be set and it must match the caller's role: a `Critic` caller must set `filed_by_critic_id` and must not set `filed_by_studio`; a `StudioRep` caller must set `filed_by_studio` and must not set `filed_by_critic_id`. Likewise, a `CLASSIFICATION` dispute must set `subject_review_id` and must not set `subject_release_id`, and a `SCORE_DISPLAY` dispute must set `subject_release_id`, must not set `subject_review_id`, and must not set `requested_classification`. Only `Critic` and `StudioRep` callers may file.

Two filing-time guards apply to classification disputes. First, the `requested_classification` must be present, must be `FRESH` or `ROTTEN`, and must differ from the review's current `classification`; a request that is missing, invalid, or equal to the current classification is rejected with `ERR_INVALID_RECLASSIFICATION` (HTTP 400) — as is a filing against a review whose `classification` is still null (an unpublished review). Second, segregation of duties forbids a critic from filing a classification dispute against their own review — when `filed_by_critic_id` equals the review's `critic_id` the filing is rejected with `ERR_SELF_DISPUTE_FORBIDDEN` (HTTP 409); studio-filed disputes are unaffected by this rule. Filing a classification dispute against a `PUBLISHED` review moves that review to `FLAGGED`; the subject review must therefore be in `PUBLISHED` status, and these guards run in the stated order — reclassification check, then self-dispute, then the review-state check.

A new dispute starts `FILED`. The `AccreditationBoard` triages it, moving it to `TRIAGED`, and may return a triaged dispute to `FILED` for re-triage loops — the branch is deliberately bidirectional. Rulings happen only from `TRIAGED`; any action on an `UPHELD` or `REJECTED` dispute, both of which are terminal, is rejected with `ERR_DISPUTE_ALREADY_TERMINAL` (HTTP 409). An uphold ruling on a classification dispute requires the subject review to be in `FLAGGED` status with a `requested_classification` present; on success the review's `classification` becomes the requested value, the review returns to `PUBLISHED`, and the release's tomatometer and certification are recomputed with new superseding snapshots. An uphold ruling on a score-display dispute forces a fresh recalculation of the subject release's scores, refreshing both `tomatometer_pct` and `audience_score_pct` with new snapshots. A reject ruling returns the subject review of a classification dispute to `PUBLISHED` with its classification unchanged. Every dispute transition carries `expected_dispute_version` under the OCC rule of §2.6 and increments the dispute's `version` by 1; the terminal-state check precedes the version check, so any action on a terminal dispute yields `ERR_DISPUTE_ALREADY_TERMINAL` even when the expected version is stale. An uphold ruling on a score-display dispute marks the dispute `UPHELD` first and then forces the fresh recalculation of the subject release's scores. The board and platform administrators may list disputes — filtered by `subject_review_id`, `subject_release_id`, or `filed_by_critic_id` — and critics and studio representatives may fetch individual disputes.

## 4. Endpoint Definitions

All endpoints live under the API root. Creating a new resource returns HTTP 201; reads, transitions, recalculations, and other modifications return HTTP 200. Request and response field details are defined by the narratives in §3; this table is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/_clock/set_current_utc` | Advance the logical clock | PlatformAdmin |
| POST | `/publications` | Create a publication (status PENDING) | PlatformAdmin |
| GET | `/publications/{id}` | Get a publication | PlatformAdmin, AccreditationBoard, Critic, StudioRep, AudienceMember |
| POST | `/publications/{id}/transition` | Publication accreditation transitions (ACCREDIT, PROBATE, REINSTATE) | AccreditationBoard |
| GET | `/publications/{id}/critics` | List critics of a publication | PlatformAdmin, AccreditationBoard, Critic, StudioRep, AudienceMember |
| POST | `/critics` | Create a critic (accreditation_status APPLIED) | PlatformAdmin |
| GET | `/critics/{id}` | Get a critic | PlatformAdmin, AccreditationBoard, Critic, StudioRep, AudienceMember |
| POST | `/critics/{id}/transition` | Critic accreditation transitions (ACCREDIT, PROBATE, REINSTATE by board; REAPPLY by the critic) | AccreditationBoard, Critic |
| POST | `/accreditation-reviews` | File a periodic accreditation review for a critic or publication | AccreditationBoard |
| GET | `/accreditation-reviews` | List accreditation reviews, filterable by subject | PlatformAdmin, AccreditationBoard |
| GET | `/accreditation-reviews/{id}` | Get an accreditation review | PlatformAdmin, AccreditationBoard |
| POST | `/accreditation-reviews/{id}/transition` | Review workflow (BEGIN_REVIEW, RULE_UPHOLD, RULE_REVOKE, DISMISS) | AccreditationBoard |
| POST | `/titles` | Create a title (posture SETUP) | PlatformAdmin |
| PATCH | `/titles/{id}` | Update title posture (SETUP → OPEN → RETIRED) | PlatformAdmin |
| POST | `/titles/{id}/releases` | Create a release/cut under a title (status UPCOMING) | PlatformAdmin |
| GET | `/releases` | List releases, filterable by title | PlatformAdmin, AccreditationBoard, Critic, StudioRep, AudienceMember |
| GET | `/releases/{id}` | Get a release with current scores and suspension flag | PlatformAdmin, AccreditationBoard, Critic, StudioRep, AudienceMember |
| POST | `/releases/{id}/transition` | Release lifecycle (OPEN, CLOSE) | PlatformAdmin |
| POST | `/releases/{id}/score-recalculation` | Force a score recalculation; OCC on `expected_release_version` | AccreditationBoard, PlatformAdmin |
| GET | `/releases/{id}/score-snapshots` | List score snapshots for a release | PlatformAdmin, AccreditationBoard, Critic, StudioRep, AudienceMember |
| GET | `/releases/{id}/bombing-incidents` | List bombing incidents for a release | PlatformAdmin, AccreditationBoard, Critic, StudioRep, AudienceMember |
| POST | `/releases/{id}/reviews` | Ingest a critic review (status INGESTED) | Critic |
| GET | `/reviews` | List critic reviews, filterable by release and critic | PlatformAdmin, AccreditationBoard, Critic, StudioRep, AudienceMember |
| GET | `/reviews/{id}` | Get a critic review | PlatformAdmin, AccreditationBoard, Critic, StudioRep, AudienceMember |
| POST | `/reviews/{id}/transition` | Review lifecycle (PUBLISH, WITHDRAW) | Critic |
| POST | `/audience-members` | Register an audience member | PlatformAdmin |
| POST | `/releases/{id}/ticket-verifications` | Submit a ticket verification (status SUBMITTED) | AudienceMember |
| GET | `/ticket-verifications` | List ticket verifications, filterable by release and member | PlatformAdmin, AccreditationBoard, AudienceMember |
| GET | `/ticket-verifications/{id}` | Get a ticket verification | PlatformAdmin, AccreditationBoard, AudienceMember |
| POST | `/ticket-verifications/{id}/transition` | Ticket verification workflow (VERIFY, REJECT) | PlatformAdmin |
| POST | `/releases/{id}/audience-ratings` | Create an audience rating (status UNVERIFIED) | AudienceMember |
| GET | `/audience-ratings` | List audience ratings, filterable by release, member, and ticket verification | PlatformAdmin, AccreditationBoard, AudienceMember |
| GET | `/audience-ratings/{id}` | Get an audience rating | PlatformAdmin, AccreditationBoard, AudienceMember |
| POST | `/audience-ratings/{id}/transition` | Rating lifecycle (VERIFY by owner, INVALIDATE by PlatformAdmin) | AudienceMember, PlatformAdmin |
| POST | `/releases/{id}/bombing-incidents` | Open a review-bombing incident; detection index computed at open time | PlatformAdmin |
| POST | `/bombing-incidents/{id}/transition` | Incident workflow (CONFIRM, DISMISS, RESOLVE) | PlatformAdmin |
| POST | `/disputes` | File a dispute (CLASSIFICATION against a review, or SCORE_DISPLAY against a release) | Critic, StudioRep |
| GET | `/disputes` | List disputes, filterable by subject review, subject release, and filing critic | PlatformAdmin, AccreditationBoard |
| GET | `/disputes/{id}` | Get a dispute | PlatformAdmin, AccreditationBoard, Critic, StudioRep |
| POST | `/disputes/{id}/transition` | Dispute workflow (TRIAGE, RETURN, RULE_UPHOLD, RULE_REJECT); OCC on `expected_dispute_version` | AccreditationBoard |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the §2 and §3 narratives where the guarded workflow is described.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_TITLE_NOT_OPEN | 409 |
| ERR_EMBARGO_ACTIVE | 409 |
| ERR_CRITIC_NOT_ACCREDITED | 409 |
| ERR_PUBLICATION_NOT_ACCREDITED | 409 |
| ERR_DUPLICATE_REVIEW | 409 |
| ERR_VERIFICATION_WINDOW_MISS | 409 |
| ERR_TICKET_NOT_VERIFIED | 409 |
| ERR_DUPLICATE_VERIFIED_RATING | 409 |
| ERR_BOMBING_SUSPENSION_ACTIVE | 409 |
| ERR_ACC_REVIEW_PERIOD_OVERLAP | 409 |
| ERR_DISPUTE_ALREADY_TERMINAL | 409 |
| ERR_INVALID_RECLASSIFICATION | 400 |
| ERR_SELF_DISPUTE_FORBIDDEN | 409 |
| ERR_SCORE_NOT_COMPUTABLE | 409 |
