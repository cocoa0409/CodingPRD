# Micro-Task Marketplace API — Product Requirements Document

## 1. Introduction

The Micro-Task Marketplace API is the transactional backbone of a crowdsourced
work platform. Requesters publish small, well-defined tasks — each carrying a
per-assignment reward, a working window, and a set of competencies a worker must
already hold — and fund them upfront from a prepaid balance. Workers discover
those tasks, accept them under a strict per-worker concurrency budget, submit
finished work, and are paid once the requester approves it. Because money moves
before the work exists, the platform must be conservative with every cent: reward
pools, platform commission, per-assignment fees, and discretionary bonuses are
reserved and released with exact integer arithmetic, and no task can be published
unless the requester has already committed the full sum the task will ever cost.

The commercial risk in this domain runs in both directions, and the specification
treats each side as a first-class concern. A requester who rejects an
implausibly large share of the work they receive can damage a worker's public
approval rate, so the platform caps how much of that damage a worker can undo:
one dispute per rejected assignment, inside a narrow window, with the final call
landing on a platform operator rather than on the requester. In the other
direction, a requester whose rolling rejection behaviour crosses published
thresholds is flagged, and one that crosses the higher threshold is suspended
outright — which cascades into the cancellation of every task they were running.
Around all of this sit the bureaucratic realities of a payout economy: country-
specific withdrawal floors, per-country eligible payment rails, an identity
verification hold before money leaves the platform, qualification exams with
attempt caps and cooldown periods, and a set of automatically granted
competencies that track a worker's live approval rate.

This document specifies the complete external contract of that service: its
resources and their relationships, the state machines that govern every
lifecycle, the arithmetic that decides balances, the ordering in which
validations fire, the access-control model, and the HTTP surface. It is written
for an engineer who will build the service from this text alone, so every
identifier, threshold, boundary condition, and error code used by the platform is
stated somewhere in the narrative — though deliberately not all in one place.

## 2. Global Specifications & System-Wide Principles

The platform is mounted as a single service and every resource path in it is
rooted at `/mkt`. The subsections below fix the cross-cutting contracts that
apply regardless of which resource is being touched.

### 2.1. User and Role-Based Access Control

Every request carries two headers. `X-User-ID` identifies the acting principal
and `X-User-Role` declares the capacity in which that principal is acting. Both
must be present and must name a registered actor; a missing or unrecognised
pairing is refused with `ERR_UNAUTHENTICATED` (HTTP 401). The platform recognises
four role names: `Anonymous`, `Requester`, `Worker`, and `PlatformAdmin`.
Registration is where the two principal accounts come into being: a requester is
created with a legal `name`, and a worker is created with a public `display_name`
and a `country`.

Each role carries a fixed identity semantics. When `X-User-Role` is `Requester`,
`X-User-ID` is the `id` of the acting `Requester`; ownership checks on any
resource that references a `Requester` compare the resource's foreign-key field
to `X-User-ID`. When `X-User-Role` is `Worker`, `X-User-ID` is the `id` of the
acting `Worker`, and ownership checks compare the resource's `worker_id` to
`X-User-ID`. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque
operator identifier that is not tied to any persisted entity; the server records
it where a workflow attributes an action to an operator — for example as the
`actor_requester_id` of a review row appended during an administrative
resolution — but never compares it to any entity's `id`. When `X-User-Role` is
`Anonymous`, `X-User-ID` is likewise opaque and untied to any persisted entity,
and the only operations it may reach are requester registration and worker
registration.

Authorisation itself is a second, separate gate: the acting role must appear in
the operation's permitted role set, and for requester-owned or worker-owned
resources the acting principal must be the owner. A request that clears
authentication but fails this gate is refused with `ERR_FORBIDDEN` (HTTP 403).

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

List endpoints accept a `limit` query parameter giving the maximum number of
items to return, defaulting to 10 when omitted, with a minimum of 1 and a maximum
of 100, and an `offset` query parameter giving the number of leading items to
skip, defaulting to 0. Unless a filter or an endpoint description says otherwise,
list responses are ordered by `created_at` ascending. Every list response carries
`limit`, `offset`, `total_count`, and `has_more` in the `meta` object alongside
the standard request metadata.

### 2.4. Identity, Ownership, and Nested Path Resolution

Path identifiers are resolved strictly left to right, and the first identifier
that does not name an existing row of its collection short-circuits the request
with `ERR_NOT_FOUND` (HTTP 404). A request that reaches an assignment through a
task that does not exist, or a review through an assignment that does not exist,
therefore fails on the outer segment before any inner logic runs. Several
collections are addressed by a bare `id` — deposits, worker-qualification grants,
exams, reviews — and those anchors resolve against their own collection in the
same way. Across the surface, the path variables a caller will encounter are
`requester_id`, `worker_id`, `hit_id`, `assignment_id`, `qualification_type_id`,
`exam_id`, `deposit_id`, `payout_id`, and the generic `id` used by the
collection anchors; each resolves against the collection its name denotes, in
left-to-right path order. This ordering is what allows ownership, state, and fiscal checks to
assume that every referenced resource already exists.

Ownership is enforced per resource time, not per role in the abstract. Cancelling,
publishing, or sweeping a task, approving, rejecting, or bonusing submitted work,
disputing a rejection, returning or submitting an assignment, and requesting a
withdrawal are all gated on the acting principal being the resource's owner, as
described in §2.1. Administrative operations — deposit settlement, abuse review
and reinstatement, identity verification, worker suspension, exam authoring,
dispute resolution, payout release and payout rejection, and the logical clock
controls — are reserved to `PlatformAdmin` and are not ownership-scoped.

### 2.5. Common Resource Properties and Timestamps

Resources created with the standard field set carry a system-managed `id` — a
server-minted UUID with no type prefix, so the identifier alone never reveals
which entity it belongs to — together with `created_at`, `updated_at`, and
`version`. Both timestamps are ISO 8601 UTC strings with exactly three fractional
digits (for example `2026-09-01T00:00:00.000Z`). `created_at` is stamped once at
creation and never changes. `updated_at` is refreshed on every mutation of the
resource, and `version` is an integer that starts at its initial value and
increments by one on every mutation; the two are always advanced together, so a
recomputation of a derived figure is itself a mutation. Every derived or computed
field described in §3 — escrow balances, spend counters, approval rates, abuse
scores, and the like — obeys this rule: whenever the platform rewrites one of
them it advances the owning row's `version` and refreshes its `updated_at`.

One entity is deliberately exempt from part of this convention. A `Review` is an
append-only audit record and is created without the standard field set: it
carries `id` and `created_at` only, and has neither `updated_at` nor `version`.
Reviews are never mutated after they are appended, so there is nothing for those
fields to describe. `Assignment` follows the full convention and additionally
exposes its `version` in the ordinary field list because it is the resource
carrying the optimistic-concurrency check on submission.

### 2.6. Monetary Precision and Half-Up Rounding

Every monetary quantity in this system is an integer count of cents: `reward_cents`,
`bonus_cents`, `amount_cents`, `funds_required_cents`, `escrowed_cents`,
`spent_rewards_cents`, `spent_bonus_cents`, `total_earned_cents`,
`withdrawable_cents`, `prepaid_balance_cents`, `lifetime_spent_cents`, and
`lifetime_spent_cents`-adjacent figures are all whole integers, and no monetary
field ever holds a fractional cent in storage or in a response body. Where a
multiplication would produce a fraction — the platform's commission on a reward
pool, and the worker-side commission on an individual earning — the product is
rounded to the nearest whole cent using the round-half-up rule: a value exactly
halfway between two cents rounds to the larger one. Percentage figures such as
`approval_rate_pct`, `lifetime_rejection_rate_pct`, and the windowed rejection
rate are likewise integers produced by round-half-up. There is no other rounding
anywhere: sums are exact integer addition, and no intermediate value is truncated.

### 2.7. Optimistic Concurrency Control on Task Writes

Two task-level write operations — cancelling a task and running a task's
expiration sweep — require the client to present the task's last-observed version
as a non-optional body field named `expected_hit_version`. If that value does not
equal the task's current `version`, the request is rejected with `ERR_STALE_VERSION`
(HTTP 412). This is a stale-version guard: publishing and every child acceptance
legitimately advance a task's `version` between the moment a client reads the task
and the moment it calls one of these operations, so a client that has not observed
the intervening writes is refused rather than allowed to act on a task it has not
seen the current shape of. The same guard protects two further writes with their
own field names: submitting an assignment requires `expected_assignment_version`
to equal the assignment's current `version`, and releasing a held payout requires
`expected_payout_request_version` to equal the payout's current `version`. No
other endpoint accepts a version field, and no version field is optional.

### 2.8. Requester Prepayment, Escrow, and Lifetime Spend

Requester money is modelled as a fungible pool rather than as a set of earmarked
lots. A `Requester` exposes three related balances. `prepaid_balance_cents` is the
spendable remainder: the sum of all of that requester's settlement-succeeded
deposits, less their currently `escrowed_cents` and less their
`lifetime_spent_cents`. `escrowed_cents` is the sum of `escrowed_cents` across
every task the requester owns that is still non-terminal — that is, in `DRAFT`,
`PUBLISHED`, or `DISPATCHED` — representing funds committed but neither spent nor
yet refunded. `lifetime_spent_cents` is a monotone counter: it is the sum, across
all of the requester's tasks, of their `spent_rewards_cents` and their
`spent_bonus_cents`, and it only ever grows, never shrinking.

A `RequesterDeposit` is minted in `PENDING`; settling it advances it to
`SUCCEEDED` or `FAILED`, and only `SUCCEEDED` deposits credit the requester's
balance. Each deposit carries a `refunded_cents` figure accumulating the portion
of it paid back as tasks are cancelled or complete with unclaimed slots. A deposit
also carries an `escrowed_cents` figure, but that figure is informational only: it
mirrors the requester's pool at the time it is read and is never consulted by any
conservation check, precisely because the underlying pool is fungible and cannot
be traced back to individual deposits.

### 2.9. The Qualification Register and the Approval-Rate Cascade

A `QualificationType` is a named competency — `name` — classified by a `kind` of
either `SYSTEM` or `REQUESTER`; the classification is descriptive only, and an
exam may be authored against a type of either kind. A type declares whether it
can carry an exam through `exam_available`, an `auto_assign_threshold_pct` at
which it is granted automatically, and a `default_score` stamped onto grants it
hands out. A `WorkerQualification` is a single grant, linking a `worker_id` to a
`qualification_type_id` and carrying a `score`, an originating `source` of either
`CASCADE` or `EXAM`, and a `status` of either `ACTIVE` or `REVOKED`.

Whenever a worker's `approval_rate_pct` is recomputed — on an approval, on a
rejection, or on an administrative resolution — the platform re-evaluates every
`SYSTEM` qualification against the worker's rate. Reaching a type's
`auto_assign_threshold_pct` mints or refreshes a `CASCADE` grant in `ACTIVE`
status scored at the type's `default_score`. Falling back below the threshold
revokes the `CASCADE` grants for types no longer met. Only grants whose `source`
is `CASCADE` are ever revoked by this cascade: a grant earned by passing an exam
is permanent, and the cascade never removes it. Because a recomputation rewrites
a derived field, the worker row's `version` and `updated_at` advance with it.

### 2.10. Validation Ordering and the Priority Ladder

Validations across the platform do not fire as an unordered set; they fire in a
fixed nine-step order, and a request that violates an earlier step never reaches a
later one. The ladder, in order:

1. **Authentication** (`ERR_UNAUTHENTICATED`, HTTP 401) — `X-User-Role` and
   `X-User-ID` are present and name a registered actor. This check guards every
   endpoint except requester registration, worker registration, qualification-type
   creation, and the logical-clock controls.
2. **Authorisation** (`ERR_FORBIDDEN`, HTTP 403) — the acting role is permitted
   for the operation, and requester-owned or worker-owned resources are being
   touched by their owner. This guards every role-restricted endpoint.
3. **Existence** (`ERR_NOT_FOUND`, HTTP 404) — every path identifier resolves to
   a row of its collection, resolved left to right.
4. **State** (`ERR_INVALID_STATE`, HTTP 409) — the target resource sits in a
   state from which the requested transition is declared. This guards every
   transition endpoint.
5. **Actor safety** (`ERR_WORKER_SUSPENDED`, HTTP 409) — the acting worker is
   `ACTIVE`, and where a requester is acting their status is `ACTIVE` with
   `task_abuse_flag` false. Its requester-side counterpart, `ERR_REQUESTER_TASK_BLOCKED`,
   is raised when publication is attempted by a flagged requester. Both of these
   checks outrank every fiscal check; they guard acceptance, submission, and
   return on the worker side, and publication on the requester side.
6. **Business constraints** (`ERR_QUALIFICATION_REQUIRED` / `ERR_EXAM_NOT_AVAILABLE`,
   HTTP 409) — required qualification grants are held, the per-worker concurrency
   cap is not exceeded, the task pool is not exhausted, the duplicate-accept guard
   passes, and an exam is only created for a type whose `exam_available` is true.
   This guards acceptance and the concurrency check.
7. **Temporal windows** (`ERR_REVIEW_TOO_EARLY`, HTTP 409) — the assignment is not
   already expired, approval is not attempted before the half-window elapses,
   rejection is not disputed after the dispute window closes, and the vetting hold
   is not bypassed. This guards approval, dispute, and payout release.
8. **Optimistic concurrency** (`ERR_STALE_VERSION`, HTTP 412) — the presented
   `expected_*_version` equals the parent row's current `version`. This guards
   assignment submission, task cancellation, and payout release.
9. **Fiscal constraints** (`ERR_INSUFFICIENT_FUNDS`, HTTP 402) — money is checked
   last: the requester's prepaid balance covers the task's required funds, a bonus
   fits the task's bonus budget, a payout clears its country threshold, and the
   payout method is eligible. This guards publication, bonus payment, and payout
   requests.

Two further refusals sit outside the ladder because they are structural rather
than ordering-relevant: `ERR_INVALID_REQUEST` (HTTP 400) rejects a malformed body,
a missing required field, or a value outside its declared enum or type; and the
fiscal siblings `ERR_BONUS_BUDGET_EXCEEDED` and `ERR_PAYOUT_METHOD_INELIGIBLE`
(HTTP 409) are raised by their respective step-9 checks.

### 2.11. The Logical Clock and Automatic Sweeps

The platform runs on a logical clock, not wall-clock time. On startup the clock
reads exactly `2026-09-01T00:00:00Z` and it never falls back to real time; it only
moves when an operator sets it to an absolute instant or advances it to a later
instant, and advancing it to a later instant additionally runs every automatic
sweep that has come due. Those sweeps are: collecting accepted assignments whose
time limit has elapsed into `EXPIRED`; auto-approving submitted assignments whose
review window has lapsed; settling held payouts whose vetting hold has elapsed
for identity-verified workers; and bubbling tasks up to completion when their
completion gate is satisfied. Setting the clock to an absolute instant moves it
without running sweeps for the interval skipped. Because every window in this
document — the half-window approval gate, the task time limit, the review window,
the dispute window, the vetting hold, the rolling review window — is measured
against this clock, a test driver can exercise any timing rule deterministically.

## 3. Business Logic & Workflows

### 3.1. Publishing and Funding a Task

A `Requester` drafts a task by supplying a `title` for display, a per-assignment
`reward_cents`, a `max_assignments` pool size, an `assignment_duration_minutes`
working window, and a `time_limit_minutes` hold window. Three further inputs are
optional: `required_qualification_ids`, an array of qualification-type
identifiers naming competencies a worker must already hold (an empty array means
the task is open to everyone), and `bonus_budget_cents`, a cap on discretionary
bonus money for the task, which defaults to zero when omitted. The owning
`Requester` is named by `requester_id`, and a task is always minted in `DRAFT`
status with `escrowed_cents` at zero and no funds yet committed. Creation also
computes `funds_required_cents` immediately, and recomputes it on any subsequent
change to the pinned inputs (`reward_cents`, `max_assignments`, or
`bonus_budget_cents`) — the figure is a pure function of the pinned inputs and is
never influenced by what later happens to the task's assignments. Malformed
pricing is rejected with `ERR_REWARD_INVALID` (HTTP 400): `reward_cents` must be a
positive whole number of cents, and `max_assignments`, `assignment_duration_minutes`,
and `time_limit_minutes` must all be positive.

The required-funds figure is what makes a task affordable, and its evaluation
order is pinned left to right. The gross reward pool is the per-assignment reward
multiplied by the pool size, plus the bonus budget. That gross pool selects a
platform commission rate in three bands: below 10,000 cents the rate is 20
percent; from 10,000 cents up to but not including 50,000 cents the rate is 15
percent; and at 50,000 cents or above the rate is 10 percent. The band boundary is
inclusive on its lower edge, so a gross pool of exactly 10,000 cents takes the 15
percent rate and a gross pool of exactly 50,000 cents takes the 10 percent rate.
The commission is the gross pool multiplied by the selected rate, rounded
half-up to a whole cent. Adding that commission to the gross pool yields the
intermediate pre-fee amount, and it is the *intermediate* amount — not the gross
pool — that selects the per-assignment fee tier: below 20,000 cents every
assignment is charged 5 cents, and at 20,000 cents or above the fee drops to 3
cents per assignment. The final `funds_required_cents` is that intermediate
amount plus the per-assignment fee multiplied by the pool size. Because the fee
tier keys on the intermediate sum, a task whose reward pool alone sits below the
20,000-cent line can still pay the lower 3-cent fee purely because commission
lifted the intermediate figure across it — the two thresholds are genuinely
independent, and this coupling is intentional.

Funding is a two-step affair. First the requester prepays: creating a deposit
records `amount_cents` and mints the deposit in `PENDING` status. A platform
operator then settles it — the settlement body carries an `outcome` — and only a
settlement that succeeds advances the deposit to `SUCCEEDED` and credits
`amount_cents` to the requester's `prepaid_balance_cents`; a settlement that fails
moves the deposit to `FAILED` and credits nothing. Deposits can be listed and
filtered by `requester_id`, and each one is also addressable on its own for
cross-reference.

Publishing a drafted task is the second step, and it moves the task from `DRAFT`
to `PUBLISHED`. Three checks gate it, in the platform's fixed order: the acting
requester must own the task, failing with `ERR_FORBIDDEN`; the requester's own
account must be in good standing — `ACTIVE` status with `task_abuse_flag` false —
failing with `ERR_REQUESTER_TASK_BLOCKED` if the requester has been flagged; and
finally, since money is checked last, the requester's `prepaid_balance_cents` must
be at least the task's `funds_required_cents`, failing with `ERR_INSUFFICIENT_FUNDS`
(HTTP 402) otherwise. Publication is not free-standing bookkeeping: on success the
requester's `escrowed_cents` rises by `funds_required_cents` and the task's own
`escrowed_cents` is set to that same figure, so the platform now holds the entire
lifetime cost of the task — every reward, the commission on the pool, every
per-assignment fee, and the whole bonus budget — before a single worker has seen
it. A `Requester` whose account is suspended or under review cannot publish at
all; writes that would open a new lifecycle are closed to them and fail with
`ERR_REQUESTER_NOT_ACTIVE` (HTTP 409).

Cancellation is available while the task is still unfilled, and it is the
requester's exit ramp. A `DRAFT` or `PUBLISHED` task can be cancelled only if it
has never accepted a worker — the task's `accepted_count` must still be zero, or
the request is refused with `ERR_INVALID_STATE` — because a task that has ever
dispatched work must run to completion instead. Cancelling a drafted task
releases nothing, since a `DRAFT` holds no funds. Cancelling a published task is a
refund: the task's entire `escrowed_cents` returns to the requester's
`prepaid_balance_cents`, the requester's `escrowed_cents` falls by the same
amount, the task's `escrowed_cents` is zeroed, and the task reaches `CANCELLED`, a
terminal state from which it never moves again. Both cancellation and the
expiration sweep of §3.3 demand the caller present `expected_hit_version`, as
described in §2.7, and a mismatch is refused with `ERR_STALE_VERSION` before any
money moves.

### 3.2. The Qualification Register: Skill Types, Exams, and Automatic Grants

Competencies on the platform are typed. A `QualificationType` is authored with a
human-readable `name`, a `kind` of `SYSTEM` or `REQUESTER` that is descriptive
only, an `auto_assign_threshold_pct` expressed as a whole number from 0 to 100,
and — optionally — an `exam_available` flag, false when omitted, and a
`default_score`, zero when omitted. The `default_score` is the score the platform
stamps onto every grant it hands out for that type, including both automatically
granted ones and ones earned by passing an exam. The `auto_assign_threshold_pct`
is the approval-rate level at which the type is awarded without anyone asking: a
worker whose live approval rate reaches it receives the qualification through the
cascade described in §2.9, and loses it again if the rate later falls back below.

A type that has `exam_available` set to true can carry a `QualificationExam`,
created by a platform operator and configured with a `passing_score` — the
minimum whole-number score, from 0 to 100, that counts as a pass — together with
two optional windows: `max_attempts`, the per-worker cap on scored attempts, which
defaults to 3, and `retake_cooldown_days`, the minimum number of whole days that
must separate one scored attempt from the next, which defaults to 0. Authoring an
exam against a type whose `exam_available` is false is refused with
`ERR_EXAM_NOT_AVAILABLE` (HTTP 409). An exam belongs to its type — it carries the
`qualification_type_id` — and a type's exams can be listed from the type itself.

A `Worker` attempts an exam by submitting a raw `score` between 0 and 100; the
platform performs no clock-relative normalisation of that number. Each attempt is
recorded with a per-worker `sequence` starting at 1, and an `outcome` of `PASSED`
or `FAILED` — those are the only two values ever written, and the attempt counter
that enforces the cap is the count of attempt rows, not any outcome value. An
attempt passes when its `score` is greater than or equal to the exam's
`passing_score`. Two gates protect the cap and the cooldown. A worker whose scored
attempt count for an exam has already reached `max_attempts` cannot attempt again
and is refused with `ERR_QUALIFICATION_EXAM_ATTEMPTS_EXCEEDED` (HTTP 409); a
worker attempting again before `retake_cooldown_days` whole days have elapsed
since their last scored attempt is refused with
`ERR_QUALIFICATION_EXAM_COOLDOWN_ACTIVE` (HTTP 409). On a pass, a
`WorkerQualification` is granted with `source` of `EXAM`, `status` of `ACTIVE`,
and `score` equal to the passing attempt's score; repeating a successful attempt
refreshes that grant's score and status rather than minting a duplicate. Grants
recorded with a `source` of `EXAM` are permanent — the approval-rate cascade is
the only thing that revokes anything, and it touches only `CASCADE` rows.

Because grants are consulted only at the moment a worker accepts a task (see
§3.3), a worker whose automatically granted qualification is revoked mid-flight
still holds the assignment they already accepted; the revocation is inert with
respect to work in progress, and only a *fresh* acceptance of the same task would
be refused.

### 3.3. Accepting Work Under the Concurrency Budget

A `Worker` secures a task slot by accepting it, and the acceptance mints an
`Assignment` in `ACCEPTED` status. The new assignment names its task through
`hit_id` and its owner through `worker_id`, receives a stable per-worker `sequence`
ordinal, and is stamped with `deadline_at` equal to the acceptance instant plus
the task's `assignment_duration_minutes`. Acceptance also raises the task from
`PUBLISHED` to `DISPATCHED` when it was still published, incrementing the task's
`accepted_count`, its `assignment_count`, and its `committed_assignments` by one
each. The pool is finite and is never refilled: once `accepted_count` has reached
`max_assignments`, further acceptance attempts are refused with
`ERR_HIT_MAX_ASSIGNMENTS_REACHED` (HTTP 409), and that ceiling is not lifted by
returns or expiries, both of which leave `accepted_count` untouched.

Five gates stand between a worker and a slot, evaluated in the platform's fixed
order. The worker must be `ACTIVE`; a suspended worker is refused with
`ERR_WORKER_SUSPENDED` (HTTP 409). The worker must hold a live `ACTIVE`
`WorkerQualification` for every identifier in the task's
`required_qualification_ids`; a missing grant is refused with
`ERR_QUALIFICATION_REQUIRED` (HTTP 409). The task's `accepted_count` must be below
`max_assignments`. The worker's count of live assignments must be below the
platform's `MAX_CONCURRENT_ASSIGNMENTS` cap. And a duplicate-accept guard prevents
a worker from re-accepting a task they have already worked: when the assignment
being returned is the worker's last live assignment against a task they already
accepted, the operation is refused with `ERR_ALREADY_COMPLETED_HIT`.

This gate is a *snapshot*, taken once, at acceptance. The worker's qualification
grants are read exactly once, on the acceptance path, and the answer is frozen
for the life of the assignment: submitting and approving that work later proceed
normally even if a grant has since been revoked. A second snapshot is captured at
full capacity — when `accepted_count` first reaches `max_assignments`, the
worker's live `approval_rate_pct` at that instant is recorded as the admission
rate for the task, and it is that frozen value, not the worker's later live rate,
that drives any subsequent appraisal of the pool.

A worker who overcommits has a documented escape hatch. When the worker is at the
concurrency cap and asks to take on another task, the platform runs a selector
rather than refusing outright. The candidate set is the worker's own assignments
whose status is exactly `ACCEPTED` — assignments already `SUBMITTED` are never
candidates, because the platform will not silently drop work a worker has handed
in. Candidates are ranked by `deadline_at` ascending, so the assignment that would
be lost soonest is chosen first, and ties are broken by the stable per-worker
`sequence` ascending. The chosen assignment is expired to free the slot. The
selector consults neither the assignment's `id` nor the worker's `id` — the
ranking is entirely deadline-driven, with the ordinal as a deterministic
tie-break. If the candidate set is empty because every live assignment is
`SUBMITTED`, nothing is expired and the attempted acceptance is refused with
`ERR_CONCURRENCY_LIMIT_EXCEEDED` (HTTP 409). A free slot short-circuits all of
this: the worker simply receives a new `ACCEPTED` assignment for the requested
`hit_id`.

An accepted assignment can also be handed back voluntarily. Returning is allowed
while the worker owns the assignment, while the current logical time is still
strictly before the acceptance instant plus the task's `time_limit_minutes`, and
while the assignment is not the worker's last live one against a task they have
already worked — the same duplicate-accept guard as above, refused with
`ERR_ALREADY_COMPLETED_HIT`. A return increments the worker's `returned_count`,
decrements the task's `assignment_count` and `committed_assignments` by one,
leaves `accepted_count` untouched, clears the assignment's `committed` flag to
false, and lands the assignment in `RETURNED`. Because the pool is not refilled,
the abandoned slot is gone: a replacement attempt on that task will fail with
`ERR_HIT_MAX_ASSIGNMENTS_REACHED` once the pool is exhausted.

Time itself can take a slot back. When the logical clock reaches or passes the
acceptance instant plus `time_limit_minutes`, an accepted assignment becomes
collectible, and the platform expiring it sets the assignment's `assignment_expired`
flag true, increments the worker's `expired_count`, decrements the task's
`assignment_count` and `committed_assignments` by one, clears `committed` to
false, and lands the assignment in `EXPIRED`. The same predicate guards the write
path: a worker who tries to act on an assignment whose window has already elapsed
finds it expired first and the operation refused with `ERR_ASSIGNMENT_EXPIRED`
(HTTP 409). Expiry can be driven either by advancing the logical clock, which
runs the sweep automatically, or by running the task's own expiration sweep
explicitly. That explicit sweep is non-optional in its effect: it demands
`expected_hit_version`, advances the task's `version` by one, and — when the task
has no accepted assignment whose window has actually elapsed — refuses with
`ERR_ASSIGNMENT_NOT_EXPIRED` (HTTP 409) rather than reporting a no-op.

### 3.4. Submitting Work, Review, and Bonuses

Submitting completed work advances an assignment from `ACCEPTED` to `SUBMITTED`.
The submission is gated on the acting worker owning the assignment and on the
expiry predicate described above — if the logical clock is at or after the
acceptance instant plus the task's `time_limit_minutes`, expiry wins and the
submission is refused with `ERR_ASSIGNMENT_EXPIRED`. A submission also demands
`expected_assignment_version` matching the assignment's current `version`, refused
with `ERR_STALE_VERSION` on a mismatch (§2.7), and it advances the assignment's
`version` by one. On success the platform stamps `submitted_at` with the current
logical instant and sets `review_expires_at` to that instant plus 72 hours —
`REVIEW_WINDOW_HOURS` — which is the deadline by which the requester must act
before the platform acts for them.

Approval is the requester's acceptance of submitted work, and it moves the
assignment from `SUBMITTED` to `APPROVED`, a terminal state. One temporal gate
protects the worker: an assignment is only approvable once the elapsed time since
acceptance has reached at least half of the task's `assignment_duration_minutes`.
Elapsed time is measured in whole minutes by flooring the difference between the
current logical instant and the acceptance instant, and the comparison is at
least, so an assignment that has elapsed exactly half the window is already
approvable — a strict reading would wrongly reject the boundary case. The flag
that carries this verdict is `eligible_for_approval`, and approval attempted
before it turns true is refused with `ERR_REVIEW_TOO_EARLY` (HTTP 409). A second
gate is structural: an assignment that already carries a rejection cannot later be
approved, and approval attempted on such an assignment is refused with
`ERR_INVALID_STATE`.

A successful approval does more than change one status. It increments the
worker's `approved_count`, recomputes the worker's `approval_rate_pct` and lets
that recomputation cascade through the system-qualification grants as described in
§2.9, and it appends a `Review` row of `kind` `APPROVAL` attributed to the acting
`actor_requester_id` with an `actor_role` of `REQUESTER`. The task's spend grows
by its `reward_cents`, and, because approval touches a derived field, the
assignment's `approval_rate_effect_applied` flag is set true so the same
assignment is never counted twice. Approval also stamps `approved_at` with the
current logical timestamp, which is the ordering key for every chronological
spend computation in §3.8. Finally, approval can complete the task: if the task's
`accepted_count` has reached `max_assignments`, every one of its assignments is
terminal, and its `committed_assignments` has fallen to zero, the task bubbles up
to `COMPLETED` by the gate in §3.8.

Rejection is the requester's refusal of submitted work, and it moves an
assignment from `SUBMITTED` to `REJECTED`. The rejection body must carry a
non-empty `reason`; an empty or missing one is refused with
`ERR_REJECTION_REASON_REQUIRED` (HTTP 400). Mirroring approval's structural gate,
an assignment that already carries an approval cannot then be rejected —
`ERR_INVALID_STATE`. A rejection appends a `Review` row of `kind` `REJECTION`
attributed to `actor_requester_id` with `actor_role` `REQUESTER` and records the
supplied `reason`; that review row carries an `abuse_points` value, described in
§3.7. The rejection increments the worker's `rejected_count` and recomputes
`approval_rate_pct`, which cascades into the system-qualification grants exactly
as an approval does and additionally triggers the requester-side suspension
evaluation. The task's `assignment_count` and `committed_assignments` each fall
by one while `accepted_count` is left alone — a rejected slot is not refilled —
the assignment's `committed` flag clears to false, its
`approval_rate_effect_applied` flag is set true, and the free-text
`rejection_reason` is recorded on the assignment.

Bonuses are discretionary top-ups, and they are accepted in exactly two states:
`APPROVED`, and `SUBMITTED`. A bonus payment adds `bonus_cents` to the
assignment's cumulative `bonus_cents`, appends a `Review` row of `kind` `BONUS`
(the only review kind whose `bonus_cents` field is non-zero), and adds the same
amount to the task's `spent_bonus_cents`. Because bonuses are the only
monotonically growing part of a worker's earnings, the worker's
`total_earned_cents` and `withdrawable_cents` rise by the net after the
per-assignment commission of §3.6. A bonus is not uncapped: the task's
`bonus_budget_cents` is a hard ceiling on the sum of all bonuses across the task,
and a payment that would push the task's `spent_bonus_cents` above that ceiling is
refused with `ERR_BONUS_BUDGET_EXCEEDED` (HTTP 409) — a fiscal check, and
therefore evaluated last.

### 3.5. Disputing a Rejection and Administrative Resolution

Rejection damage is real but only partly reversible, and the recourse is
deliberately narrow. A `Worker` disputes a rejected assignment by moving it from
`REJECTED` to `DISPUTED`, supplying free text that is recorded as the
assignment's `dispute_reason`. Three gates apply, all of which the worker must
clear: the acting worker must own the assignment, or the request fails with
`ERR_FORBIDDEN`; the dispute must be raised within `DISPUTE_WINDOW_HOURS` of the
rejection itself, or it is refused with `ERR_DISPUTE_WINDOW_CLOSED` (HTTP 409);
and the assignment may be disputed only once in its entire life, a second attempt
failing with `ERR_DISPUTE_ALREADY_USED` (HTTP 409). Critically, disputing is not
itself a repair. The originating rejection review is not withdrawn, and the
worker's `rejected_count` stays exactly as the rejection left it — a dispute opens
an appeal, it does not undo the damage while the appeal is pending.

The appeal is decided by a `PlatformAdmin` through an administrative resolution
whose body carries a `decision` and an optional `reason`. Two outcomes are
possible, and each is declared only for its own decision value; any other
`decision` supplied against a disputed assignment is refused with
`ERR_INVALID_STATE`. A decision to approve returns the assignment to `APPROVED`.
This is the only path in the entire system that reverses approval-rate damage: it
decrements the worker's `rejected_count` by one and increments their
`approved_count` by one, recomputes `approval_rate_pct`, and lets that
recomputation cascade into the system-qualification grants and into the
requester-side suspension rollback. It also appends a `Review` row of `kind`
`APPROVAL` whose `actor_role` is `PLATFORM_ADMIN`, grows the task's
`spent_rewards_cents` by the task's `reward_cents` in the chronological order
described in §3.8, and — if every assignment of the task is now terminal with
`committed_assignments` at zero — lets the task bubble up to completion.

A decision to uphold leaves the rejection standing. The worker's `rejected_count`
is unchanged, the assignment returns to `REJECTED` as a terminal state, and no
further dispute of that assignment is ever permitted — a subsequent attempt fails
with `ERR_DISPUTE_ALREADY_USED`. There is no third outcome and no partial relief.

### 3.6. Worker Earnings, Withdrawable Balances, and Payouts

A worker's earnings accrue one approved assignment at a time. For each assignment
in `APPROVED` status, taken in the order of `approved_at` ascending with the
assignment's `sequence` ascending as the tie-break, the gross earning is the
task's `reward_cents` plus the assignment's `bonus_cents`, and the platform's
commission is that gross multiplied by a 10 percent rate, rounded half-up to a
whole cent. The worker's net for that assignment is the gross minus the
commission, and the worker's `total_earned_cents` is the sum of those per-
assignment nets. Two details of this arithmetic are load-bearing. First, the
rounding is nested per assignment and only then summed — rounding the gross total
once at the end is a different and incorrect answer; four assignments each
grossing 5 cents, for example, each yield a 1-cent commission under half-up
rounding and therefore a 4-cent net, so the sum is 16 cents rather than the 18
cents a single rounding would produce. Second, the per-assignment net is floored
at zero, so no commission can ever drive an individual earning negative.
`total_earned_cents` is monotone non-decreasing; nothing a worker does reduces it.
Only assignments in `APPROVED` contribute anything at all — assignments that are
`REJECTED`, `SUBMITTED`, `ACCEPTED`, `RETURNED`, or `EXPIRED` contribute zero.

What a worker can actually withdraw is `withdrawable_cents`, which is
`total_earned_cents` reduced by the sum of the worker's payout requests that are
currently reserved — that is, every one whose status is `PAID` or
`HELD_FOR_VETTING`. A payout request that was rejected does not reserve anything
and releases its amount back into the withdrawable pool.

Requesting a withdrawal is a `Worker` action that names a `payment_method` — one
of `BANK_TRANSFER`, `PAYPAL`, or `GIFT_CARD` — and an `amount_cents`. Two gates
apply before the request is minted, and a third applies later at release. The
amount must clear the floor set by the worker's `country`, expressed in cents: a
worker registered in `US` needs at least 100 cents; a worker in `IN` or `PH`
needs at least 500; a worker in `BR` needs at least 1000; and any other country
falls back to the same 500-cent floor. The comparison is at-least, so an amount
exactly equal to the minimum is payable, and an amount below it is refused with
`ERR_PAYOUT_THRESHOLD_NOT_MET` (HTTP 409). These floors are genuinely
per-country: an identical 500-cent request succeeds for a `US` worker and fails
for a `BR` worker. Separately, the chosen `payment_method` must be one the
worker's country is eligible for, and an ineligible rail is refused with
`ERR_PAYOUT_METHOD_INELIGIBLE` (HTTP 409). Both of these are fiscal checks and
therefore sit at the bottom of the priority ladder.

Every payout request is minted in `HELD_FOR_VETTING` — there is no way to create
one already paid — and its `hold_until_at` is stamped three days (`HOLD_DAYS`)
after its creation. Creating it immediately reduces the worker's
`withdrawable_cents` by `amount_cents`, reserving the funds. Release to `PAID` is
a `PlatformAdmin` operation that demands `expected_payout_request_version` under
the rule in §2.7, and two further gates protect it. The worker's
`identity_verified` must already be true, or the release fails with
`ERR_IDENTITY_NOT_VERIFIED` (HTTP 409) — the operator must first record a
successful identity verification, described in §3.9. And the logical clock must
be at or past the payout's `hold_until_at`, or the release fails with
`ERR_VETTING_HOLD_ACTIVE` (HTTP 409). A successful release stamps
`identity_verified_at` with the current logical instant, advances the payout to
`PAID` as a terminal state, and increments the payout's `version`. The same
release also happens automatically: once the logical clock reaches
`created_at` plus `HOLD_DAYS`, a held payout whose worker is identity-verified is
settled by the sweep without any operator action. A payout may instead be
rejected by a `PlatformAdmin` supplying a `rejection_reason`; that records the
reason, returns `amount_cents` to the worker's `withdrawable_cents`, and lands the
payout in `REJECTED`, the other terminal state. While a payout is held,
`identity_verified_at` remains null.

### 3.7. Requester Rejection Behaviour, Risk Scoring, and Suspension

A `Requester` accumulates two counters scoped to their own tasks: `approved_count`
counts reviews of kind `APPROVAL`, and `rejected_count` counts reviews of kind
`REJECTION`. From those the platform derives a lifetime rejection rate, used when
the requester's own profile is read. When the two counters sum to zero the
lifetime rate is 100 by definition; otherwise it is 100 times `rejected_count`
divided by the sum of the two counts, rounded half-up to a whole percent. The
suspension machinery, by contrast, looks only at a rolling window: review rows
belonging to that requester whose `created_at` falls within 30 days
(`REVIEW_WINDOW_DAYS`) of the logical clock, with the boundary counted in — a
review created exactly 30 days before the clock is still inside the window. Within
that window, only approvals and rejections form the population: bonus reviews are
excluded from both the numerator and the denominator. The windowed rejection rate
is 100 when the window is empty, and otherwise 100 times the number of windowed
rejections divided by the number of windowed approvals and rejections, rounded
half-up. This windowing is what prevents an old clean record from masking a recent
rejection spree.

The windowed rate drives two published thresholds: a flag threshold of 20 percent
and a fraud-review threshold of 40 percent. A `PlatformAdmin` evaluates a
requester's behaviour by running the requester's abuse review, and the outcome
depends entirely on where the windowed rate falls. Below 20 percent there is
nothing to act on, and the evaluation is refused with
`ERR_REQUESTER_REVIEW_NOT_TRIGGERED` (HTTP 409); the requester's status is not
touched and the flag stays clear. At 20 percent or above but below 40 percent, the
requester's `task_abuse_flag` is set true while their status remains `ACTIVE` —
the flag blocks new publication but deliberately leaves the in-flight lifecycle
open, so tasks already dispatched continue to be worked and paid. At 40 percent or
above, the evaluation suspends the requester outright: their status becomes
`SUSPENDED`, their `suspension_reason` is stamped `ABUSE_AUTO`, and their
`abuse_score` is set to 10 at the moment of suspension.

Suspension is a deep, cascading event. Every task the requester owns that is still
in `DRAFT`, `PUBLISHED`, or `DISPATCHED` is cancelled. For each of those
cancellations, the task's held `escrowed_cents` is returned to the requester's
`prepaid_balance_cents` and removed from the requester's `escrowed_cents`, and the
task's own `escrowed_cents` is zeroed. Each cancelled task also strands its live
work: every assignment still in `ACCEPTED`, `SUBMITTED`, or `RETURNED` is moved
to `EXPIRED`, with the owning worker's `expired_count` incremented and the
assignment's `committed` flag cleared. The `suspension_reason` field is an
enumeration whose values are `NONE`, `ABUSE_AUTO`, and `ADMIN_MANUAL`, and it is
null whenever the requester's status is not `SUSPENDED`.

The abuse score itself is a weighted risk figure recomputed at each evaluation.
The score starts from the windowed rejection rate multiplied by a rejection weight
of 1.2, adds three times the number of distinct workers who received a rejection
from this requester inside the window, and adds half of the value by which a
seven-day decay horizon exceeds the median review latency — that last term being
floored at zero, so a slow requester never earns additional score for being slow.
The median review latency is the median, in days, of the interval between an
assignment's submission and its approval or rejection, taken over the same window,
and it is zero when the window is empty. The three weight constants are 1.2 for
rejection rate, 3.0 for distinct rejected workers, and 0.5 for review speed, and
the score is finally clamped to the range from 0 to 100 inclusive, with the clamp
applied last so that an extreme weighted sum saturates at 100 rather than growing
without bound, and an empty window yields a score of 0 rather than an undefined
one. Review rows also carry their own `abuse_points` contribution: an individual
review contributes 2 points when its `kind` is `REJECTION` and the requester's
`task_abuse_flag` is currently true, and zero otherwise. The requester's
`abuse_score` is the running sum of those review-level points, decayed back by all
of them if an appeal overturns the underlying rejection.

A `Requester`'s status is one of `ACTIVE`, `SUSPENDED`, or `PENDING_REVIEW`; a
requester left in `PENDING_REVIEW`, like one already `SUSPENDED`, is closed to
publication and to the lifecycle writes that would open new work, and such an
attempt is refused with `ERR_REQUESTER_NOT_ACTIVE`.

The suspension is reversible but the collateral is not. A `PlatformAdmin` may
reinstate a suspended requester, clearing `task_abuse_flag`, resetting
`abuse_score` to zero, setting `suspension_reason` to `NONE`, and returning the
status to `ACTIVE`. Tasks that were cancelled by the suspension are not revived:
terminal states are never re-entered. A requester facing an ordinary
administrative suspension would carry the `ADMIN_MANUAL` reason instead.

### 3.8. Task Spend, Escrow Release, and Completion

A task tracks two spend figures, and only one of them is authoritative. The
persisted `spent_rewards_cents` is the sum of `reward_cents` over assignments in
`APPROVED` status, replayed in the order `approved_at` ascending with
`sequence` as the tie-break. Assignments still sitting in `SUBMITTED` — work that
has been handed in but not yet reviewed — contribute nothing to it, even though
their rewards will very likely be paid; that conservatism is deliberate. The
requester-facing view of a task may instead show a provisional figure that adds
the `reward_cents` of `SUBMITTED` assignments to that same sum, replayed in the
order `deadline_at` ascending with `sequence` as the tie-break. That provisional
figure is a projection only and is never persisted; whenever any assignment is
`SUBMITTED`, it is strictly greater than the persisted `spent_rewards_cents`. Both
figures filter strictly to the task's own assignments — no other task ever
contributes to a given task's spend. The task's `spent_bonus_cents`, for its
part, is the sum of `bonus_cents` over assignments carrying a non-zero bonus, and
it is monotone because a bonus is only ever added. Relatedly, the task's
`committed_assignments` counts the assignments whose `committed` flag is true; a
return or an expiry clears that flag, and because the pool does not refill, the
slot is simply gone.

Completion of a task is gated by three simultaneous conditions. The task's
`accepted_count` must have reached its `max_assignments`, every one of its
assignments must be in a terminal state, and its `committed_assignments` must have
fallen to zero. Until all three hold the task remains open, and its residual
escrow cannot be released. When they do hold, the task moves to `COMPLETED` and
the ledger is closed out: the amount released at completion is the task's held
`escrowed_cents` minus its `spent_rewards_cents` and minus its `spent_bonus_cents`,
the task's `escrowed_cents` drops to zero, the requester's `escrowed_cents` falls
by the funds the task was holding at completion, and the requester's
`prepaid_balance_cents` rises by the released amount. That released figure is
exactly the money that was never earned — the rewards of slots that were rejected
or returned, plus whatever bonus budget went unspent — and it can legitimately be
zero when every slot in the pool was approved. The `HIT` machine has no further
transitions: `COMPLETED` and `CANCELLED` are both terminal.

One further write bridles this lifecycle. Just as cancellation requires the
caller's last-observed task version, running a task's expiration sweep does too:
both demand `expected_hit_version` and both bump the task's `version` by one, and
either will refuse a client whose expectation is stale with `ERR_STALE_VERSION`
(HTTP 412). The sweep is not a passive read — even when its target is genuinely
expired and correct to collect, the version guard applies first.

### 3.9. Trust-and-Safety Controls and the Review Ledger

Every review ever appended — approvals, rejections, and bonuses alike — is an
immutable record naming its `assignment_id`, the acting `actor_requester_id`, an
`actor_role` of `REQUESTER`, `REVIEWER`, or `PLATFORM_ADMIN`, a `kind` of
`APPROVAL`, `REJECTION`, or `BONUS`, a `bonus_cents` amount that is zero for
everything except a bonus, an `abuse_points` contribution as described in §3.7,
and a `reason` string that is required non-empty whenever the `kind` is
`REJECTION`. Review rows are written by the workflows above and are never edited
afterwards; they can be read back from the requester who authored them and from
the assignment they concern. The ledger is the reason a requester's behavior can
be scored at all, and the reason an overturned rejection can be traced back to
its originating decision.

Two account-level controls sit with the operator. A `Worker` account can be
suspended and reinstated by a `PlatformAdmin`, moving its `status` between
`SUSPENDED` and `ACTIVE`; a suspended worker is refused at acceptance,
submission, and return with `ERR_WORKER_SUSPENDED`. Identity verification is a
separate operator action whose body carries an `outcome`: an outcome recording the
worker as verified sets `identity_verified` to true, and an outcome recording a
failure leaves it false. It is this flag, not any payout request, that gates the
release of withheld money, and it is per-worker rather than per-payout.

Finally, the platform exposes two operator-only capabilities for driving time.
One sets the logical clock to an absolute instant supplied as `current_utc` and
returns no resource — it moves the clock without running the sweeps for the
interval it skipped. The other advances the clock to a later instant supplied as
`target_utc`, also returning no resource, and additionally runs every automatic
sweep that has come due by that instant: accepted assignments past their time
limit are collected into `EXPIRED`; submitted assignments whose review window has
lapsed are approved automatically; held payouts past their hold, for
identity-verified workers, settle to `PAID`; and tasks whose completion gate now
holds bubble up to `COMPLETED` with their escrow released. The automatic
approval on a lapsed review window is the mirror image of the manual one: it
increments the worker's `approved_count`, recomputes and cascades
`approval_rate_pct`, adds the task's `reward_cents` to `spent_rewards_cents` in
the order `review_expires_at` ascending with `sequence` as the tie-break, stamps
`approved_at` with the expiry instant rather than the current one, and lands the
assignment in `APPROVED`. It deliberately ignores the `eligible_for_approval`
gate, because in this path the clock rather than the requester is the deciding
authority, and it is a no-op for any assignment an explicit review has already
resolved.

### 3.10. Qualification Types, Exams, and the HIT Declaration

The qualification catalogue and the tasks that consume it are linked by a single
declaration. When a task is drafted, its `required_qualification_ids` names the
`QualificationType` identifiers a worker must hold live grants for, and a task
that names none is open to every worker. The catalogue itself is authored by
`PlatformAdmin` and `Requester` alike through qualification-type creation, which
records the `name`, the `kind`, and the `auto_assign_threshold_pct`, with the
`exam_available` flag and `default_score` supplied optionally and defaulting to
false and zero respectively. A type is readable on its own, and its
belonging exams are readable from the type; each exam and each attempt is likewise
addressable individually, and a type's exams are listed as a collection.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource — a requester, a worker, a
qualification type, its exam, an exam attempt, a task, a deposit, an acceptance,
or a payout request — respond with `201 Created`. Operations that modify an
existing resource, including every state-transition endpoint, every settlement,
review, resolution and clock control, respond with `200 OK`. The table below
lists the complete HTTP surface with the role or roles permitted to call each
operation; request bodies, response shapes, and side effects are deliberately
omitted here and must be reconstructed from the §2 and §3 narratives.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/mkt/requesters` | Register a requester account | Anonymous |
| GET | `/mkt/requesters/{requester_id}` | Get a requester profile, including the lifetime rejection rate | Requester, PlatformAdmin |
| POST | `/mkt/requesters/{requester_id}/deposits` | Create a prepayment deposit | Requester, PlatformAdmin |
| GET | `/mkt/requester-deposits` | List deposits, optionally filtered by requester | Requester, PlatformAdmin |
| GET | `/mkt/requester-deposits/{id}` | Get a deposit by id | Requester, PlatformAdmin |
| POST | `/mkt/requester-deposits/{deposit_id}/settle` | Settle or fail a deposit | PlatformAdmin |
| POST | `/mkt/requesters/{requester_id}/abuse-review` | Evaluate the rolling rejection rate and suspend when the fraud threshold is crossed | PlatformAdmin |
| POST | `/mkt/requesters/{requester_id}/reinstate` | Reinstate a suspended requester | PlatformAdmin |
| POST | `/mkt/workers` | Register a worker account | Anonymous |
| GET | `/mkt/workers/{worker_id}` | Get a worker profile | Worker, PlatformAdmin |
| POST | `/mkt/workers/{worker_id}/identity-verifications` | Submit an identity verification outcome for a worker | PlatformAdmin |
| GET | `/mkt/worker-qualifications` | List worker-qualification grants, optionally filtered by worker or type | Worker, Requester, PlatformAdmin |
| GET | `/mkt/worker-qualifications/{id}` | Get a worker-qualification grant by id | Worker, Requester, PlatformAdmin |
| POST | `/mkt/workers/{worker_id}/suspend` | Suspend a worker account | PlatformAdmin |
| POST | `/mkt/workers/{worker_id}/reinstate` | Reinstate a suspended worker account | PlatformAdmin |
| POST | `/mkt/qualification-types` | Create a qualification type | PlatformAdmin, Requester |
| GET | `/mkt/qualification-types/{qualification_type_id}` | Get a qualification type | Worker, Requester, PlatformAdmin |
| POST | `/mkt/qualification-types/{id}/exams` | Create the qualification exam for a type | PlatformAdmin |
| GET | `/mkt/qualification-types/{id}/exams` | List the exams belonging to a qualification type | Worker, Requester, PlatformAdmin |
| GET | `/mkt/qualification-exams/{exam_id}` | Get a qualification exam | Worker, PlatformAdmin |
| POST | `/mkt/qualification-exams/{exam_id}/attempts` | Submit a scored exam attempt; a pass grants the qualification | Worker |
| GET | `/mkt/qualification-exams/{id}/attempts` | List the attempts against an exam | Worker, PlatformAdmin |
| POST | `/mkt/hits` | Create a task in DRAFT | Requester |
| GET | `/mkt/hits` | List tasks with filters | Requester, Worker, PlatformAdmin |
| GET | `/mkt/hits/{hit_id}` | Get a task | Requester, Worker, PlatformAdmin |
| GET | `/mkt/requesters/{requester_id}/hits` | List the tasks owned by a requester | Requester, Worker, PlatformAdmin |
| POST | `/mkt/hits/{hit_id}/publish` | Publish a DRAFT task, holding funds from the requester's prepaid balance | Requester |
| POST | `/mkt/hits/{hit_id}/cancel` | Cancel a DRAFT or PUBLISHED task and refund unclaimed escrow | Requester |
| POST | `/mkt/hits/{hit_id}/sweep-expired` | Run the expiration sweep for a task's overdue accepted assignments | Requester |
| GET | `/mkt/hits/{hit_id}/assignments` | List the assignments of a task | Requester, Worker, PlatformAdmin |
| POST | `/mkt/hits/{hit_id}/assignments` | Accept a task: mint an assignment and consume a pool slot | Worker |
| GET | `/mkt/assignments` | List assignments with filters | Requester, Worker, PlatformAdmin |
| GET | `/mkt/assignments/{assignment_id}` | Get an assignment | Requester, Worker, PlatformAdmin |
| POST | `/mkt/workers/{worker_id}/assignments/concurrency-check` | Resolve a worker's concurrency cap: expire the nearest-deadline accepted assignment or refuse | Worker, PlatformAdmin |
| POST | `/mkt/assignments/{assignment_id}/submit` | Submit completed work for review | Worker |
| POST | `/mkt/assignments/{assignment_id}/return` | Return an accepted assignment before its time limit | Worker |
| POST | `/mkt/assignments/{assignment_id}/approve` | Approve submitted work | Requester |
| POST | `/mkt/assignments/{assignment_id}/reject` | Reject submitted work | Requester |
| POST | `/mkt/assignments/{assignment_id}/bonus` | Pay a bonus for an approved or submitted assignment | Requester |
| POST | `/mkt/assignments/{assignment_id}/dispute` | Dispute a rejection | Worker |
| POST | `/mkt/assignments/{assignment_id}/admin-resolve` | Resolve a dispute administratively | PlatformAdmin |
| GET | `/mkt/requesters/{id}/reviews` | List the reviews authored by a requester | Requester, PlatformAdmin |
| GET | `/mkt/assignments/{id}/reviews` | List the reviews of an assignment | Requester, Worker, PlatformAdmin |
| POST | `/mkt/workers/{id}/payouts` | Request a withdrawal | Worker |
| GET | `/mkt/workers/{id}/payouts` | List a worker's payout requests | Worker, PlatformAdmin |
| GET | `/mkt/payouts/{payout_id}` | Get a payout request | Worker, PlatformAdmin |
| POST | `/mkt/payouts/{payout_id}/verify` | Verify identity and release a held payout | PlatformAdmin |
| POST | `/mkt/payouts/{payout_id}/reject` | Reject a held payout and release the reserved funds | PlatformAdmin |
| POST | `/mkt/_clock/set_current_utc` | Set the logical clock to an absolute instant | PlatformAdmin |
| POST | `/mkt/_clock/advance_to` | Advance the logical clock and run every automatic sweep due by that instant | PlatformAdmin |

## 5. Error Code Catalogue

The table below lists every error identifier the platform can emit together with
the HTTP status it carries. The conditions that trigger each one are deliberately
not repeated here; they are stated next to the workflow each error guards in §2
and §3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_REQUESTER_NOT_ACTIVE` | 409 Conflict |
| `ERR_REQUESTER_TASK_BLOCKED` | 409 Conflict |
| `ERR_WORKER_SUSPENDED` | 409 Conflict |
| `ERR_QUALIFICATION_REQUIRED` | 409 Conflict |
| `ERR_EXAM_NOT_AVAILABLE` | 409 Conflict |
| `ERR_QUALIFICATION_EXAM_ATTEMPTS_EXCEEDED` | 409 Conflict |
| `ERR_QUALIFICATION_EXAM_COOLDOWN_ACTIVE` | 409 Conflict |
| `ERR_CONCURRENCY_LIMIT_EXCEEDED` | 409 Conflict |
| `ERR_HIT_MAX_ASSIGNMENTS_REACHED` | 409 Conflict |
| `ERR_REWARD_INVALID` | 400 Bad Request |
| `ERR_ASSIGNMENT_EXPIRED` | 409 Conflict |
| `ERR_ASSIGNMENT_NOT_EXPIRED` | 409 Conflict |
| `ERR_REVIEW_TOO_EARLY` | 409 Conflict |
| `ERR_REJECTION_REASON_REQUIRED` | 400 Bad Request |
| `ERR_DISPUTE_WINDOW_CLOSED` | 409 Conflict |
| `ERR_DISPUTE_ALREADY_USED` | 409 Conflict |
| `ERR_REQUESTER_REVIEW_NOT_TRIGGERED` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INSUFFICIENT_FUNDS` | 402 Payment Required |
| `ERR_BONUS_BUDGET_EXCEEDED` | 409 Conflict |
| `ERR_PAYOUT_THRESHOLD_NOT_MET` | 409 Conflict |
| `ERR_PAYOUT_METHOD_INELIGIBLE` | 409 Conflict |
| `ERR_IDENTITY_NOT_VERIFIED` | 409 Conflict |
| `ERR_VETTING_HOLD_ACTIVE` | 409 Conflict |