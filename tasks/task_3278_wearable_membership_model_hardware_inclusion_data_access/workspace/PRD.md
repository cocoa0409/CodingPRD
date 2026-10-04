# Wearable Membership API — Product Requirements Document

## 1. Introduction

A membership-included-hardware wearable platform operates on a simple commercial premise with demanding operational consequences: the member never buys a device. Instead, a member subscribes for a committed term, and the sensing band is included with the subscription. While the term runs, the member is entitled to fault-based device replacement and, after enough time has elapsed, to a hardware upgrade. Because revenue is tied to a committed term, the platform must enforce early-cancellation charges under two distinct fee policies, honor a bounded budget of pause days, and react correctly when a monthly payment fails — suspending the member's privileges without losing their data.

Around that commercial core sit four data-centric obligations. First, the band streams daily physiological aggregates that are scored into strain, recovery, and sleep metrics; when the scoring algorithm is revised and published, every historical metric set must be recomputed and, where the revision meaningfully changes a member's recovery picture, the member's data sharing must be suppressed until the member acknowledges the new release. Second, coaches running sports teams or corporate wellness programs may view member metrics, but only through a per-scope consent projection that yields to the suppression posture. Third, members may opt into research studies, contributing de-identified rows that vanish entirely if the member withdraws. Fourth, an accessory and apparel storefront spends from a member wallet that is funded by pause-proration credits and refunded by order cancellations, and the wallet ledger must always reconcile.

This document specifies the REST API that implements those obligations. It is written for engineers building the server: §2 fixes the platform-wide contracts (roles, envelope, pagination, the logical clock, rounding, optimistic concurrency, and the order in which validations run), §3 narrates the business workflows in which every rule lives, §4 summarizes the endpoints, and §5 catalogs the error codes.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two context headers: `X-User-ID`, identifying the caller, and `X-User-Role`, naming the caller's role. If either header is missing, or the value of `X-User-Role` is not one of the declared roles, the request is rejected with `ERR_MISSING_OR_INVALID_CONTEXT_HEADER`. If the role is declared but not authorized for the target endpoint, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The platform recognizes exactly five roles:

- **Anonymous** — an unauthenticated caller permitted only to register a new member. When `X-User-Role` is `Anonymous`, `X-User-ID` is an opaque caller identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- **Member** — the subscribed end user who owns terms, devices, metric sets, enrollments, and merch orders. When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member`; ownership checks on any member-scoped resource compare the resource's `member_id` foreign key to `X-User-ID`, and a mismatch is rejected with `ERR_NOT_RESOURCE_OWNER`.
- **Coach** — a team or organization operator. When `X-User-Role` is `Coach`, `X-User-ID` is an opaque operator identifier; it is recorded as `coach_user_id` on the `Team` the coach creates, and team-ownership checks compare the team's stored `coach_user_id` to `X-User-ID`, with a mismatch rejected as `ERR_NOT_RESOURCE_OWNER`.
- **Support** — a customer-operations agent who diagnoses faults, runs replacement logistics, records payments, and assists with cancellations. When `X-User-Role` is `Support`, `X-User-ID` is an opaque operator identifier not compared to any entity's `id`.
- **PlatformAdmin** — the platform operator who provisions devices, publishes algorithm releases, manages research studies, and drives the logical clock. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not compared to any entity's `id`.

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

List endpoints accept `limit` and `offset` query parameters. `limit` defaults to 10, with a minimum of 1 and a maximum of 100; `offset` defaults to 0. List responses are sorted by `created_at` ascending unless a workflow states a more specific ordering, and the `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock

All time-dependent behavior — "today", enrollment windows, pause window openings, consent expirations, term completions — is governed by a server-side logical clock, never by wall-clock time. Before any clock call is made, the logical clock reads exactly `2026-09-01T00:00:00Z`. A `PlatformAdmin` moves time forward by setting the clock to a supplied `to_iso8601` instant; the server never falls back to the wall clock on its own.

Advancing the clock fires the system-side transitions described throughout §3: a scheduled pause window whose start has been reached opens (and its term becomes `PAUSED`), an open pause window whose scheduled end has been reached closes (and its term returns to `ACTIVE`), a consent entry whose `expires_on` has fallen behind today flips to `EXPIRED`, a term whose commitment has been both reached in time and fully paid completes, and every research study's `study_status` is recomputed against the new today.

### 2.5. Common Resource Properties

Every resource exposed by this API carries four server-managed properties. `id` is a server-minted UUID with no type prefix. `created_at` and `updated_at` are ISO 8601 UTC timestamps rendered with three fractional digits; `updated_at` refreshes on every mutation. `version` is an integer that increments by one on every mutation of the resource and is the basis of the optimistic concurrency checks described in §2.7. No entity in this API is exempt from these four properties.

### 2.6. Optimistic Concurrency Control

Two write operations take an explicit client-supplied expectation of the parent resource's `version`, because both are repeatable operations whose safety depends on the client having observed the latest state:

- A hardware upgrade request on a term must carry `expected_term_version` equal to that term's current `version`. Upgrades are repeatable — each success resets the eligibility clock via `last_upgrade_on` — so a client acting on a stale view of the term must re-read before upgrading again.
- A consent grant or revoke on a team membership must carry `expected_team_membership_version` equal to that membership's current `version`. Granting a scope supersedes any prior entry for that scope, so a client whose view of the membership predates another consent change must re-read before writing.

In both cases, a mismatch between the supplied expectation and the parent's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412). No other endpoint takes a version field.

### 2.7. The Member Wallet Ledger

Each member carries `wallet_credit_cents`, a spendable balance that starts at zero when the member registers. The wallet is funded in exactly one way — the proration credit issued when a member resumes early from an open pause — and it is spent and refunded by the merch storefront: placing a merch order debits the order's `total_cents`, and cancelling a paid order credits exactly that same `total_cents` back. The wallet may never go negative, so an order whose `total_cents` exceeds the member's current `wallet_credit_cents` is refused with `ERR_INSUFFICIENT_WALLET_CREDIT`. The wallet invariant is that a placement debit followed by that order's cancellation credit leaves the balance unchanged.

### 2.8. Hardware Continuity Windows

Every device describes the span of days it was responsible for the member's data as a closed interval from `continuity_start_on` through `continuity_end_on`. `continuity_start_on` is stamped at activation; `continuity_end_on` stays null (open-ended) until the device is retired, at which point it is stamped with the retirement day — and the closed semantics mean that last day is still covered by the retiring device. A member's data history is stitchable across devices precisely because the replacement's first covered day is defined as the faulty device's last covered day plus one. Because the intervals are closed, two devices of the same member may not both cover the same day; a brand-new device whose first covered day would coincide with another device of the same member still covering that day is rejected with `ERR_CONTINUITY_WINDOW_OVERLAP` — same-day adjacency counts as overlap.

### 2.9. Metric Computation, Precision, and Money Rounding

Daily physiological scores are derived quantities: `strain_score` is expressed with one decimal place on a scale that tops out at 21, while `recovery_score` and `sleep_performance_pct` are whole numbers on a 0–100 scale. Every score — and every monetary amount — is rounded half-up. Monetary values are integer cents throughout: cancellation fees, proration credits, and each component of merch pricing are each rounded half-up to whole cents at the moment they are computed. For merch pricing the rounding order is pinned: each discount component is rounded to cents individually, the components are then summed, and only then is the percentage cap applied.

### 2.10. Validation Evaluation Order

When several checks could reject the same request, they run in a fixed priority order so the rejection a caller sees is deterministic. First the context headers are validated (`ERR_MISSING_OR_INVALID_CONTEXT_HEADER`), then the caller's role against the endpoint (`ERR_FORBIDDEN_ROLE`), then entity-backed ownership (`ERR_NOT_RESOURCE_OWNER`). Path identifiers are then resolved left to right, with a missing id surfacing as `ERR_NOT_FOUND`, followed by request-body well-formedness — required fields present, enum values valid, dates parseable — as `ERR_INVALID_REQUEST`. Only after those pass does the server evaluate the optimistic-concurrency expectation (`ERR_STALE_VERSION`), then state-machine preconditions (`ERR_INVALID_STATE_TRANSITION`, including the member-suspension gate `ERR_MEMBER_SUSPENDED`), then the consent-and-suppression boundary (`ERR_DATA_SHARING_SUPPRESSED`), then temporal-window rules (pause overlap, continuity overlap, grant-window validity, enrollment window), then business constraints such as budgets, uniqueness, and thresholds, and finally the fiscal check that the wallet covers an order (`ERR_INSUFFICIENT_WALLET_CREDIT`). A request that fails an earlier check never reaches a later one.

## 3. Business Logic & Workflows

### 3.1. Member Onboarding and Membership Terms

Anyone may register as a member by supplying an `email` and a `full_name`; the email must be unique across members. Registration creates the member with `member_status` set to `ACTIVE`, `wallet_credit_cents` at zero, `data_sharing_posture` at `NORMAL`, and `algorithm_ack_release_id` null until the member's first acknowledgement of an algorithm release.

A member (or a `PlatformAdmin` acting for them) starts a membership term by naming a `plan_name` and quoting the commercial shape of the deal: `monthly_fee_cents`, `commitment_months` in whole calendar months, a `hardware_tier` of `BAND_STD` or `BAND_PRO` — the `BAND_PRO` tier is what unlocks the merchandise member discount — an `upgrade_eligibility_months` waiting period, a `pause_days_per_term` budget, a `cancel_fee_policy` of `REMAINING_MONTHS` or `PAID_MONTHS_FLOOR`, and an `early_cancel_fee_floor_cents` minimum. The term is born `ACTIVE` on the day it is created: `started_on` is stamped with today, `commitment_end_on` is computed as `started_on` advanced by `commitment_months` calendar months, `months_paid` starts at zero, `pause_days_used` starts at zero, `pause_windows` starts empty, `open_pause_end_on` and `cancel_fee_charged_cents` and `last_upgrade_on` are null.

A member may hold at most one open term: if the member already owns a term whose `term_status` is `ACTIVE`, `PAUSED`, or `PAST_DUE`, a further term creation is refused with `ERR_ACTIVE_TERM_EXISTS`. Actions that presuppose an open term fail with `ERR_NO_ACTIVE_TERM` when none exists.

Once a term exists, the member can list their terms and read back the running state — `months_paid`, `pause_days_used`, the scheduled and historical `pause_windows` — at any time.

### 3.2. Billing Outcomes and the Suspension Cascade

Billing events arrive from the payments side of the business and are recorded by `Support` or `PlatformAdmin` staff, who post an `outcome` against the term.

When a monthly payment succeeds on an `ACTIVE` term, the term stays `ACTIVE` and `months_paid` increments by one. When a payment succeeds on a `PAST_DUE` term, the term returns to `ACTIVE`, `months_paid` increments by one, and — as a second hop — the owning member's `member_status` returns to `ACTIVE`, but only if the member owns no other term still in `PAST_DUE`.

When a payment fails on an `ACTIVE` term, two hops fire in sequence. Hop one moves the term from `ACTIVE` to `PAST_DUE`. Hop two suspends the member: `member_status` becomes `SUSPENDED` whenever the member owns at least one term in `PAST_DUE`. While a member is `SUSPENDED`, five kinds of action are blocked and refused with `ERR_MEMBER_SUSPENDED`: starting a new term, upgrading hardware, placing a merch order, enrolling in a research study, and granting consent scopes. Suspension lifts automatically on the first successful payment that leaves the member with no `PAST_DUE` term at all.

### 3.3. Pausing and Resuming a Term

A member pauses a term by supplying a `start_on` date and a `days` count, describing a half-open window that covers `start_on` up to but not including `start_on + days`. If `start_on` is today, the pause opens immediately: the term moves from `ACTIVE` to `PAUSED`, the new window is recorded in `pause_windows` as `OPEN`, and `open_pause_end_on` is set to `start_on + days`. If `start_on` is in the future, the window is stored as `SCHEDULED`; when the logical clock later reaches `start_on`, the system opens the window and moves the term to `PAUSED`, and when the clock reaches the scheduled end, the system closes the window — its `window_status` becomes `CLOSED` with `end_on` at that scheduled end — and the term returns to `ACTIVE`.

Two checks guard pause scheduling. A new half-open window may not overlap any existing `SCHEDULED` or `OPEN` window on the same term; adjacency — one window ending exactly where another begins — is allowed. A violation is rejected with `ERR_PAUSE_WINDOW_OVERLAP`. Separately, the term's pause budget must hold: the committed days are the sum of the scheduled lengths of all `SCHEDULED` and `OPEN` windows plus the actual elapsed lengths (end minus start) of all `CLOSED` windows, and a new pause of `days` length is rejected with `ERR_PAUSE_BUDGET_EXCEEDED` only when committed days plus the new request is strictly greater than `pause_days_per_term` — hitting the budget exactly is allowed. The displayed `pause_days_used` is a different, live quantity: for each `OPEN` window it counts today minus its start, and for each `CLOSED` window it counts end minus start. When a window closes, `pause_days_used` accumulates the window's actual half-open day count.

A member may also resume early from an `OPEN` pause. Resuming moves the term from `PAUSED` back to `ACTIVE`, closes the window with `end_on` set to today, and — because the member gave back unused paused days — credits the member's wallet: the unused days are the whole days from today up to the scheduled `open_pause_end_on` of the window being closed, and the credit is the term's `monthly_fee_cents` multiplied by those unused days and divided by the thirty days of a billing cycle, rounded half-up to whole cents. The credit is computed and rounded per resumed window before being added to `wallet_credit_cents`. Calling resume on a term that is not `PAUSED` is rejected with `ERR_TERM_NOT_PAUSED`.

### 3.4. Early Cancellation and Term Completion

A member (or `Support` on their behalf) may cancel a term early, but only from `ACTIVE` or `PAST_DUE`; cancelling a term that is `PAUSED`, already `CANCELLED_EARLY`, or `COMPLETED` is rejected with `ERR_TERM_NOT_CANCELLABLE`. Cancellation is only meaningful while the commitment is unfulfilled — if `months_paid` has already reached `commitment_months`, the term completes rather than cancelling.

Early cancellation charges a fee chosen by the term's `cancel_fee_policy`, and stores it as `cancel_fee_charged_cents`. Under `REMAINING_MONTHS`, the fee is forward-looking: the months remaining are `commitment_months` minus `months_paid`, and the charge is fifty percent of the monthly fee for each remaining month — that is, `monthly_fee_cents` times the months remaining times one-half — rounded half-up to whole cents, then raised to at least `early_cancel_fee_floor_cents`. Under `PAID_MONTHS_FLOOR`, the fee is chronological: the charge is twenty-five percent of the monthly fee for each month already paid — `monthly_fee_cents` times `months_paid` times one-quarter — again rounded half-up to whole cents and floored at `early_cancel_fee_floor_cents`. The two policies deliberately price identical term states differently.

Cancellation has three side effects beyond the status change. The term becomes `CANCELLED_EARLY` and is terminal. Every device of the member's that is still `PROVISIONED`, `ACTIVE`, or `SUSPECT_FAULT` is retired — and for a device that was `ACTIVE`, retirement stamps `continuity_end_on` with today, closing its interval inclusive of today. And if the member was `SUSPENDED` solely because of this term, the member's `member_status` returns to `ACTIVE`.

A term that runs its course completes instead: when the logical clock reaches a day on or after `commitment_end_on` and `months_paid` is at least `commitment_months`, the system moves the term from `ACTIVE` to `COMPLETED`. Both `CANCELLED_EARLY` and `COMPLETED` are terminal.

### 3.5. Hardware: Provisioning, Activation, Upgrades, and Replacement

Hardware enters the platform when a `PlatformAdmin` provisions a device for a member under a specific term, supplying the `member_id`, the `term_id`, a `serial_number`, and a `hardware_tier`. Serial numbers are unique across all devices; reusing one is rejected with `ERR_SERIAL_NUMBER_TAKEN`. The new device is `PROVISIONED` — the initial value of `device_status` — with `activated_on`, `continuity_start_on`, `continuity_end_on`, and `diagnosis` all null. Anyone with device visibility — the owning member, `Support`, or a `PlatformAdmin` — can read a device or list devices, optionally narrowed by `member_id` or `term_id`.

Activation is performed by the owning member and requires the device to be `PROVISIONED`; attempting to activate a device in any other state — or to ingest from or fault-report a device that is not `ACTIVE` — is rejected with `ERR_DEVICE_NOT_ACTIVE`. Activation also requires the owning member's `member_status` to be `ACTIVE`. On success the device becomes `ACTIVE`, `activated_on` is stamped with today, `continuity_start_on` is set, and `continuity_end_on` stays null. What `continuity_start_on` becomes depends on whether the device is a replacement. For an ordinary first device, `continuity_start_on` is today — but only if no other device of the same member already covers today under the closed-interval semantics of §2.8; such an overlap is rejected with `ERR_CONTINUITY_WINDOW_OVERLAP`, and remember that same-day adjacency counts as overlap. For a replacement device — one that some replacement request names as its `replacement_device_id` — the faulty device must already be `RETIRED`; activating the replacement while the faulty device still holds an open continuity interval is rejected with `ERR_REPLACEMENT_DEVICE_NOT_RETIRED`. When that precondition holds, the replacement's `continuity_start_on` is stitched to the faulty device's `continuity_end_on` plus one day — which may be earlier than today, deliberately backfilling the data-continuity gap.

A member upgrades hardware mid-term by presenting `expected_term_version` as described in §2.6. Eligibility is measured in whole calendar months from an anchor: the anchor is `last_upgrade_on` if a previous upgrade happened, otherwise `started_on`; a month counts only once the same day-of-month has been reached or passed. The upgrade proceeds only when the full months elapsed are at least `upgrade_eligibility_months` — the boundary is inclusive — and otherwise the request is rejected with `ERR_UPGRADE_NOT_ELIGIBLE`. On success, `last_upgrade_on` is stamped with today, the term's `version` increments, and a new `PROVISIONED` device of hardware tier `BAND_PRO` is created for the member under this term and returned in the response. Because each success re-anchors the clock, an upgrade is repeatable.

When hardware misbehaves, the owning member opens a replacement request on the device with a `reason` of `HARDWARE_FAILURE`, `BATTERY_DRAIN`, or `SENSOR_DRIFT`. Opening the request does two things atomically: the device's `device_status` moves from `ACTIVE` to `SUSPECT_FAULT`, and the request is created with `request_status` `OPEN`, its `device_id` pointing at the faulty device. A device may carry at most one `OPEN` request — a second attempt is rejected with `ERR_REPLACEMENT_ALREADY_OPEN` — and the device must be `ACTIVE` to begin with; fault-reporting a device in another state fails under `ERR_DEVICE_NOT_ACTIVE`.

`Support` then decides the request, and deciding requires the request to be `OPEN`, the faulty device to be `SUSPECT_FAULT` (otherwise `ERR_DEVICE_NOT_FAULTY`), and — for an approval — the term the device was issued under to still be in `ACTIVE`, `PAUSED`, or `PAST_DUE`. A `decision` of `APPROVE` records the request's `diagnosis` as `CONFIRMED_FAILURE` and fires a two-sibling cascade: the faulty device moves to `RMA_INBOUND`, and a fresh `PROVISIONED` device is created for the same `member_id` and `term_id` with a server-minted serial, its id stored on the request as `replacement_device_id`. A `decision` of `REJECT` carries a `diagnosis` in the payload: with `NO_FAULT` the device returns to `ACTIVE` as a compensating restore and its `diagnosis` is set to `NO_FAULT`; with `USER_DAMAGE` the device remains `SUSPECT_FAULT`. Either way the request lands in the terminal `REJECTED` state.

Finally, when the faulty unit physically arrives back, `Support` confirms the return: the request moves from `APPROVED` to the terminal `COMPLETED` state, and the faulty device moves from `RMA_INBOUND` to `RETIRED` with `continuity_end_on` stamped today — closing its interval inclusive of today and making the replacement's pinned stitch (last covered day plus one) computable.

### 3.6. Daily Ingestion, Scoring, and Algorithm Releases

Each day, an `ACTIVE` device contributes one aggregate sensing record: the member posts the `day_on` being described together with `avg_hr`, `hrv_ms`, `resting_hr`, and `sleep_minutes`. The `day_on` must not be in the future and must not precede the device's `continuity_start_on`. A member may hold at most one metric set per day — a duplicate `day_on` for the same member is rejected with `ERR_DUPLICATE_METRIC_DAY`. The created `DailyMetricSet` is attributed to the device's owning member (its `member_id` is denormalized from the device), is stamped with the `algorithm_version` that produced its scores — version 1 while no release is published — and is born with `interpretation_status` `CURRENT`.

Three scores are computed from the four inputs, and the formula depends on whether any algorithm release is currently published. Under the baseline (algorithm version 1, used when no release is `PUBLISHED`): `strain_score` is the average heart rate divided by ten, capped at 21, rounded half-up to one decimal; `recovery_score` is the heart-rate variability expressed as a percentage of the sum of the variability and the resting heart rate — `hrv_ms` times one hundred divided by (`hrv_ms` plus `resting_hr`) — capped at 100 and rounded half-up to a whole number; `sleep_performance_pct` is the day's sleep minutes expressed as a percentage of a 480-minute full night, capped at 100 and rounded half-up to a whole number. Once any release is `PUBLISHED` (version 2 or later), all three denominators and the recovery shape change: `strain_score` divides the average heart rate by nine instead of ten; `recovery_score` first computes the same variability percentage, then scales it by nine-tenths and adds five, before the same cap and rounding; `sleep_performance_pct` is measured against 450 minutes instead of 480. Identical inputs therefore yield different scores before and after a publication — that is the point of the release machinery.

An algorithm release is drafted by a `PlatformAdmin` with a `version` number, a `requires_member_ack` flag (defaulting to true), and `release_notes` for member communication. The release is created with `release_status` `DRAFT` and `published_on` null, and its `version` must be strictly greater than every existing release's version. Publishing is likewise an admin action and requires the release to still be `DRAFT`; on publication `published_on` is stamped with today and any previously `PUBLISHED` release becomes `SUPERSEDED` (a terminal state).

Publication fires a three-hop cascade. Hop one sweeps every metric set whose `algorithm_version` is older than the newly published version: each such set is marked `STALE` and then immediately recomputed within the same sweep — processed in chronological order by `day_on` ascending with ties broken by `created_at` ascending — landing in `RECOMPUTED` with `algorithm_version` set to the published version and `strain_score`, `recovery_score`, and `sleep_performance_pct` rewritten under the published formula. Hop two guards member trust: when the release's `requires_member_ack` is true and any of a member's `recovery_score` values changed during the sweep, that member's `data_sharing_posture` flips from `NORMAL` to `SUPPRESSED`. Hop three is the read-time consequence: while a member is `SUPPRESSED`, every team dashboard row for that member hides its metrics, as detailed in §3.7.

A suppressed member clears the posture by acknowledging the release: the member posts the `release_id` of the release being acknowledged, the server records it as `algorithm_ack_release_id`, and — because acknowledging the latest `PUBLISHED` release discharges the obligation — `data_sharing_posture` returns to `NORMAL`. While a member is `SUPPRESSED`, any attempt by that member to grant a consent scope is refused with `ERR_DATA_SHARING_SUPPRESSED`.

Members (and staff with read access) can list a member's metric sets, optionally filtered by `day_on` or `algorithm_version`, to inspect both the raw inputs and the current scores.

### 3.7. Teams, Coach Dashboards, and Consent

A coach builds a team by supplying a `name`, a `team_type` of `SPORTS` or `CORPORATE_WELLNESS`, and a `coach_user_id` — which must equal the caller's own `X-User-ID`, since that opaque identifier is how team ownership is later checked. The coach then adds members to the team one at a time by `member_id`; each addition creates a `TeamMembership` whose `membership_status` starts `ACTIVE`, carrying the team's id as `team_id` and an empty `consent_scopes` list. A member may hold at most one `ACTIVE` membership in a given team — a duplicate is rejected with `ERR_DUPLICATE_MEMBERSHIP`. Memberships can be read individually or listed, optionally filtered by `team_id` or `member_id`.

Consent is per-scope and belongs to the member, never to the coach. The member posts a `scope` of `STRAIN`, `RECOVERY`, or `SLEEP`, an `action`, the OCC field `expected_team_membership_version`, and optionally an `expires_on`. The membership must be `ACTIVE`, and the acting member must be the membership's own member. Granting writes an entry for that scope with status `GRANTED`, `granted_on` stamped today, and the supplied `expires_on`; a scope carries at most one entry, so a new grant supersedes any prior entry for the same scope. An `expires_on` in the past is rejected with `ERR_GRANT_WINDOW_INVALID`; it may also be null, meaning no expiry. Revoking flips an existing `GRANTED` entry to `REVOKED`. Either action increments the membership's `version` by one — which is exactly why the OCC rule of §2.6 exists for this endpoint. When the logical clock advances past an entry's `expires_on`, the entry's status becomes `EXPIRED`. Granting while the member's `data_sharing_posture` is `SUPPRESSED` is refused with `ERR_DATA_SHARING_SUPPRESSED` — suppression overrides consent until the member acknowledges the latest release.

Removal ends everything at once. Either the owning coach or the member themself removes an `ACTIVE` membership; the membership becomes `REMOVED` (terminal), and every consent entry still `GRANTED` flips to `REVOKED` — consent dies with the membership.

The coach dashboard is a read-time projection, computed fresh on every call, over the team's `ACTIVE` memberships, and its rows are ordered by membership `created_at` ascending. For each such membership the dashboard either emits one row carrying `membership_id`, `member_id`, a `suppressed` flag, and the three metric fields, or omits the member entirely. Omission happens when the member owns no membership term at all, or when the member's latest term (ordering by term `created_at` ascending, latest last) is `CANCELLED_EARLY` or `COMPLETED`. When the row is emitted and the member's `data_sharing_posture` is `SUPPRESSED`, `suppressed` is true and all three of `strain_score`, `recovery_score`, and `sleep_performance_pct` are null — suppression overrides consent. Otherwise `suppressed` is false, and each metric field independently shows the member's latest metric value (by `day_on` descending) when that scope's consent entry exists with status `GRANTED` and either has no `expires_on` or an `expires_on` on or after today; failing that, the field is null.

### 3.8. Research Studies and De-identified Contribution

A `PlatformAdmin` creates a research study with a unique `code`, a `title`, a `min_paid_months` tenure requirement, and an enrollment window from `enrollment_window_start_on` (inclusive) through `enrollment_window_end_on` (inclusive). The study's `study_status` is computed, not stored as an input: it is `RECRUITING` whenever today falls inside that inclusive window and `CLOSED` otherwise, and it is recomputed as the logical clock moves.

A member enrolls in a study by posting their `member_id`. Enrollment requires the study to be `RECRUITING` today — otherwise `ERR_ENROLLMENT_WINDOW_CLOSED` — the member's `member_status` to be `ACTIVE`, the member's current term to have `months_paid` of at least the study's `min_paid_months`, and no existing `ENROLLED` enrollment for the same member in the same study (`ERR_ALREADY_ENROLLED`). The created enrollment is stamped with `enrollment_status` `ENROLLED`, linked to its study via `study_id` and to its owner via `member_id`, with `enrolled_on` stamped today and a `member_seq` assigned per study: enrollments are numbered by their `created_at` ascending starting at 1, giving each participant a de-identified per-study sequence. Anyone with read access can list a study's enrollments or read a study.

The contribution dataset is, like the dashboard, a read-time projection. For every enrollment of the study still in `ENROLLED` status, and for every metric set of that member whose `day_on` is on or after the enrollment's `enrolled_on`, the dataset emits one row of `member_seq`, `day_on`, `strain_score`, `recovery_score`, and `sleep_performance_pct`, ordered by `member_seq` ascending and then `day_on` ascending. No `member_id`, `email`, or name ever appears. A `WITHDRAWN` enrollment contributes zero rows — withdrawal removes all prior contribution retroactively — and its `member_seq` is never reused.

Withdrawal is the member's own action on their own enrollment: it requires the enrollment to be `ENROLLED` and the acting member to be the enrollment's member, and it moves the enrollment to the terminal `WITHDRAWN` state.

### 3.9. Accessory and Apparel Commerce

A member with wallet credit places a merch order by posting a list of `lines`, each naming a `sku`, a `category` of `BAND_ACCESSORY`, `APPAREL`, or `RECOVERY_GEAR`, a `unit_price_cents`, and a `qty`. The order is created with `order_status` `PAID` and attributed to the placing member — the wallet is debited at placement, not at shipment — so placement requires `wallet_credit_cents` to cover the order's `total_cents`, failing which the placement is refused with `ERR_INSUFFICIENT_WALLET_CREDIT` and nothing is created. A successful placement decrements `wallet_credit_cents` by `total_cents` and increments the member's `version` by one.

Pricing is computed line by line in a pinned order. The `subtotal_cents` is the sum over all lines of quantity times unit price. The member discount applies when the member's current term — one in `ACTIVE` or `PAUSED` status — has `hardware_tier` `BAND_PRO`; then `member_discount_cents` is ten percent of the subtotal, rounded half-up to whole cents, and otherwise (including when the member has no such term at all) it is zero. The bundle discount looks only at `APPAREL` lines: when the total apparel quantity is at least three, `bundle_discount_cents` is five percent of the apparel subtotal — the sum of quantity times unit price over the apparel lines — rounded half-up to whole cents, and otherwise it is zero. The combined discount is then capped: `discount_cents` is the smaller of the sum of the two discount components and thirty percent of the subtotal rounded half-up to whole cents. Finally `total_cents` is the subtotal minus the capped discount.

Cancellation is the compensating action: the owning member or `Support` cancels an order in `PAID` status, moving it to the terminal `CANCELLED` state, and the member's wallet is credited exactly the order's `total_cents` — placement debit plus cancellation credit leaves the wallet unchanged, per the invariant of §2.7. The member's `version` increments with the credit. Members can list their own merch orders to review both standing and cancelled purchases.

## 4. Endpoint Definitions

Creation of a new resource returns HTTP 201; modifications, decisions, and action-style operations return HTTP 200. Request payloads, response contents, and side effects are specified by the workflow narratives of §3 — this table is a locator, not a contract.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /_clock/set_current_utc | Advance the logical clock to `to_iso8601`; fires clock-driven transitions | PlatformAdmin |
| POST | /members | Register a member | Anonymous |
| GET | /members/{id} | Read a member (posture, wallet, status) | Member, Coach, Support, PlatformAdmin |
| POST | /members/{id}/acknowledge-algorithm | Acknowledge a published algorithm release; clears `SUPPRESSED` posture | Member |
| GET | /members/{id}/terms | List the member's terms | Member, Coach, Support, PlatformAdmin |
| GET | /members/{id}/metric-sets | List the member's daily metric sets (optional `day_on`, `algorithm_version` filters) | Member, Coach, Support, PlatformAdmin |
| GET | /members/{id}/merch-orders | List the member's merch orders | Member, Support, PlatformAdmin |
| GET | /members/{id}/research-enrollments | List the member's research enrollments | Member, Support, PlatformAdmin |
| POST | /members/{id}/terms | Start a membership term (hardware included) | Member, PlatformAdmin |
| POST | /members/{id}/merch-orders | Place an accessory/apparel order, debited from the wallet at placement | Member |
| POST | /terms/{id}/pause | Schedule a pause window `{start_on, days}`; same-day start opens immediately | Member |
| POST | /terms/{id}/resume | Resume early from an open pause; credits unused days to the wallet | Member |
| POST | /terms/{id}/record-payment | Record a billing `outcome`; drives `PAST_DUE` / recovery cascades | Support, PlatformAdmin |
| POST | /terms/{id}/cancel | Early-cancel a term; computes the cancellation fee; retires devices | Member, Support |
| POST | /terms/{id}/upgrade | Upgrade hardware mid-term (OCC via `expected_term_version`) | Member |
| POST | /devices | Provision a device for a member under a term | PlatformAdmin |
| GET | /devices/{id} | Read a device | Member, Support, PlatformAdmin |
| GET | /devices | List devices (optional `member_id`, `term_id` filters) | Member, Support, PlatformAdmin |
| POST | /devices/{id}/activate | Activate a provisioned device; opens its continuity window | Member |
| POST | /devices/{id}/ingest | Ingest one day's sensing aggregates; creates the daily metric set | Member |
| POST | /devices/{id}/replacement-requests | Open a replacement request; marks the device `SUSPECT_FAULT` | Member |
| GET | /devices/{id}/replacement-requests | List replacement requests for a device | Member, Support, PlatformAdmin |
| POST | /replacement-requests/{id}/decide | Support approves (creates replacement) or rejects an open request | Support |
| POST | /replacement-requests/{id}/receive-return | Confirm the faulty device arrived; retires it and closes continuity | Support |
| POST | /algorithm-releases | Create an algorithm release in `DRAFT` | PlatformAdmin |
| POST | /algorithm-releases/{id}/publish | Publish a release; supersedes prior; recomputes older metric sets | PlatformAdmin |
| POST | /teams | Create a team owned by the calling coach | Coach |
| POST | /teams/{id}/memberships | Add a member to the team | Coach |
| GET | /teams/{id}/dashboard | Coach dashboard: consent- and suppression-bounded member rows | Coach |
| GET | /team-memberships/{id} | Read a membership including its consent scopes | Member, Coach, Support, PlatformAdmin |
| GET | /team-memberships | List memberships (optional `team_id`, `member_id` filters) | Member, Coach, Support, PlatformAdmin |
| POST | /team-memberships/{id}/consents | Grant or revoke a consent scope (OCC via `expected_team_membership_version`) | Member |
| POST | /team-memberships/{id}/remove | Remove a member from a team; revokes all granted consents | Coach, Member |
| POST | /research-studies | Create a research study | PlatformAdmin |
| GET | /research-studies/{id} | Read a study | Member, Support, PlatformAdmin |
| POST | /research-studies/{id}/enroll | Member opts into a recruiting study | Member |
| GET | /research-studies/{id}/enrollments | List a study's enrollments | Member, Support, PlatformAdmin |
| GET | /research-studies/{id}/contribution-dataset | De-identified contribution rows for the study | PlatformAdmin |
| POST | /research-enrollments/{id}/withdraw | Member withdraws; all contributed rows disappear | Member |
| POST | /merch-orders/{id}/cancel | Cancel a paid merch order; wallet credited exactly `total_cents` | Member, Support |

## 5. Error Code Catalogue

Trigger conditions for each code live with the workflows in §2 and §3; this table fixes only the identifier and its HTTP status.

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_CONTEXT_HEADER | 400 |
| ERR_FORBIDDEN_ROLE | 403 |
| ERR_NOT_RESOURCE_OWNER | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_STALE_VERSION | 412 |
| ERR_INVALID_STATE_TRANSITION | 409 |
| ERR_MEMBER_SUSPENDED | 409 |
| ERR_ACTIVE_TERM_EXISTS | 422 |
| ERR_NO_ACTIVE_TERM | 409 |
| ERR_TERM_NOT_CANCELLABLE | 409 |
| ERR_PAUSE_BUDGET_EXCEEDED | 422 |
| ERR_PAUSE_WINDOW_OVERLAP | 409 |
| ERR_TERM_NOT_PAUSED | 409 |
| ERR_UPGRADE_NOT_ELIGIBLE | 422 |
| ERR_DEVICE_NOT_ACTIVE | 409 |
| ERR_DUPLICATE_METRIC_DAY | 409 |
| ERR_CONTINUITY_WINDOW_OVERLAP | 409 |
| ERR_REPLACEMENT_DEVICE_NOT_RETIRED | 409 |
| ERR_REPLACEMENT_ALREADY_OPEN | 422 |
| ERR_DEVICE_NOT_FAULTY | 409 |
| ERR_DATA_SHARING_SUPPRESSED | 403 |
| ERR_GRANT_WINDOW_INVALID | 400 |
| ERR_DUPLICATE_MEMBERSHIP | 409 |
| ERR_ENROLLMENT_WINDOW_CLOSED | 422 |
| ERR_ALREADY_ENROLLED | 409 |
| ERR_INSUFFICIENT_WALLET_CREDIT | 422 |
| ERR_SERIAL_NUMBER_TAKEN | 409 |





