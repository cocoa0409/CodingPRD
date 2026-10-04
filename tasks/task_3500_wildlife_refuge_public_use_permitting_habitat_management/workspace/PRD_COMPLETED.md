# Wildlife Refuge Permitting API — Product Requirements Document

## 1. Introduction

The National Wildlife Refuge System operates under a dual mandate: conserve habitat and wildlife populations, and — where a proposed use is found compatible with that purpose — welcome the public onto refuge lands for photography, research, commercial filming, guided activity, and carefully managed agricultural use. Administering that mandate is a year-round operational problem. Compatibility determinations must be drafted, opened for public comment, adjudicated, and finalized before any use is authorized. Permit applications arrive from the public and must be reviewed, priced, paid, and — when nesting season or a hunt-safety closure intervenes — suspended and reinstated. Habitat treatments run on seasonal windows. Volunteers staff interpretive programs only while their background clearances remain valid. Graziers bid for cooperative agreements, accrue per-period cost-share assessments, and answer to law-enforcement citations that can suspend their standing. State agency partners track whether surveyed populations hold against jointly set objectives.

This document specifies the API for a refuge operations platform that administers all of that end to end. The platform is organized around **management units** — named tracts of refuge land classified by dominant habitat — and nearly every operational record hangs off one: treatment windows, facility closures, interpretive programs, grazing offerings, population objectives, and the permits that authorize public use. A single logical clock, never the wall clock, drives the seasonal calendar; advancing it closes comment periods, opens and expires treatment windows, lapses volunteer clearances, completes programs, and runs permits to their end, in a pinned evaluation order. Money is tracked in integer cents under a strict rounding discipline, and the two write paths that accumulate onto a cooperative agreement are guarded by optimistic concurrency. Access is role-based, separating refuge staff with a hierarchical manager override from the applicants, cooperators, volunteers, and anonymous members of the public who transact with the refuge.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID`, identifying the caller, and `X-User-Role`, naming the caller's role. A request whose `X-User-Role` header is missing, or whose value does not match one of the declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401); the same rejection applies when `X-User-ID` is absent for any role other than `Anonymous`, the one role that calls without an identity header. A caller whose role is not among an endpoint's authorized roles — or who violates an ownership anchor defined below — is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

The platform recognizes ten roles. `RefugeManager` is the refuge's senior authority: the manager alone creates management units, closes and selects grazing awards, posts refunds, completes cooperative agreements, and advances the logical clock, and additionally may perform any operation available to `Biologist`, `PermitOfficer`, `VolunteerCoordinator`, `LawEnforcementOfficer`, or `StateAgencyPartner` — a hierarchical override across all staff operations. `Biologist` owns habitat treatments, facility closures, the grazing offering lifecycle, and period assessments on agreements. `PermitOfficer` owns compatibility determinations, comment adjudication, and permit review, approval, and revocation. `VolunteerCoordinator` coordinates volunteers and interpretive programs. `LawEnforcementOfficer` holds citation authority. `StateAgencyPartner` is the state wildlife agency partner who sets population objectives and records survey counts. `PermitApplicant` is a member of the public applying for a use permit. `Cooperator` is a farmer or grazier bidding on grazing offerings and paying down an agreement. `Volunteer` is a registered volunteer reading their own assignments. `Anonymous` is the unauthenticated public, limited to submitting comments, self-registering as a volunteer, and the public read endpoints.

Identity works differently for exactly one role. When `X-User-Role` is `Volunteer`, `X-User-ID` is the `id` of the acting `Volunteer`; ownership checks on any resource that references a `Volunteer` compare the resource's foreign-key field to `X-User-ID`. For the other nine roles — `RefugeManager`, `Biologist`, `PermitOfficer`, `VolunteerCoordinator`, `LawEnforcementOfficer`, `StateAgencyPartner`, `PermitApplicant`, `Cooperator`, and `Anonymous` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it on resources but never compares it to any entity's `id`.

Two of the opaque roles nevertheless carry explicit ownership anchors. Every permit application records an `applicant_ref` that must equal the calling `PermitApplicant`'s `X-User-ID` at creation, and subsequent applicant-only actions on that application compare `X-User-ID` against the stored `applicant_ref`. Symmetrically, every cooperator bid and every cooperative agreement records a `cooperator_ref` that must equal the calling `Cooperator`'s `X-User-ID`; bids submitted under another cooperator's reference, or payments directed at an agreement the caller does not own, are rejected with `ERR_UNAUTHORIZED_ROLE`. Volunteer-scoped reads are anchored as well: a `Volunteer` caller may only query assignments under their own `volunteer_id`, and a request framed on anyone else's is rejected with `ERR_UNAUTHORIZED_ROLE`.

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

Endpoints that return lists of resources accept two query parameters. The `limit` parameter specifies the maximum number of items to return; when omitted it defaults to 10, and any supplied value must be at least 1 and at most 100. The `offset` parameter specifies how many items to skip and defaults to 0. A `limit` or `offset` that is not an integer, a `limit` outside 1 through 100, or a negative `offset` is rejected with `ERR_INVALID_REQUEST` (400). Unless otherwise specified, every list endpoint returns its resources sorted by `created_at` in ascending order; because the logical clock makes `created_at` ties common, ties break by creation order, earliest-created first. Optional filter parameters match exactly, and a filter value that matches no resource simply yields an empty page rather than an error. List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope, alongside `api_request_id` and `api_request_timestamp`.

### 2.4. Common Resource Properties and the Audit Trail

Every resource the API serves — management units, compatibility determinations, public comments, permit applications, habitat treatments, facility closures, interpretive programs, volunteers, volunteer assignments, grazing offerings, cooperator bids, cooperative agreements, citations, and population objectives — carries a standard set of system-managed fields:

- **`id` (string):** a unique, server-minted identifier formatted as a UUID, with no type prefix of any kind.
- **`created_at` (string):** an ISO 8601 UTC timestamp with three fractional digits, read from the logical clock (§2.5) at the moment of creation.
- **`updated_at` (string):** an ISO 8601 UTC timestamp with three fractional digits, refreshed from the logical clock on every modification of the resource.
- **`version` (integer):** a system-managed integer that starts at 1 on creation and increments by one on every modification.

Cascade-driven changes count as modifications. When a closure activation suspends a permit, when a volunteer expiry releases an assignment, or when a citation debits an agreement's compliance points, each affected resource's `updated_at` refreshes and its `version` advances. The cooperative agreement's audit counters are pinned explicitly: recording a period assessment, posting a ledger entry, issuing an agreement-subject citation, and voiding such a citation each increment the agreement's `version` by exactly one, and any cascade that changes an agreement's status does so as an ordinary mutation of the same record. A recomputation of a derived field — `access_posture`, `committed_visitor_days`, or the habitat priority scores — that lands on the field's existing value is not a modification: it refreshes neither `updated_at` nor `version`.

Two timestamp families coexist. The audit fields above (`created_at`, `updated_at`, and the envelope's `api_request_timestamp`) always render with three fractional digits. Domain date fields — comment windows, permit dates, treatment windows, closure dates, program dates, grazing windows, deadlines, and a volunteer's `cleared_on` — are calendar dates rendered as `YYYY-MM-DD`, and all comparisons among them use the UTC date portion of the logical clock. On input, a domain date field accepts any ISO 8601 calendar-date form; the value is canonicalized, stored, and always rendered as `YYYY-MM-DD`.

### 2.5. The Refuge Logical Clock and Time-Driven Transitions

The server never consults wall-clock time. A single logical clock governs every server-minted timestamp and every date comparison in the system: window openings, deadline enforcement, clearance expiry, and permit completion all read the same clock. Before any client call, the clock starts at exactly `2026-09-01T00:00:00Z` and must not fall back to wall-clock time under any circumstances.

A `RefugeManager` advances the clock through an admin-only, test-driving capability that sits outside the business surface of the API. The request supplies a target instant as `to_iso8601`, and the response reports the clock back as `current_utc`, rendered as the clock reads. The target is not required to be later than the current reading — the capability sets the clock to whatever instant is supplied, and transitions that have already fired are never rewound. A missing or unparseable `to_iso8601` is rejected with `ERR_INVALID_REQUEST` (400). Date-scoped rules throughout this document — "the current logical clock date" — refer to the UTC date portion of that instant.

Advancing the clock fires five classes of automatic transitions, applied in this pinned order:

1. **Determinations.** A determination in `PUBLIC_COMMENT` whose `comment_close_date` now precedes the clock date moves to `ADJUDICATION`; comment intake closes.
2. **Treatments.** A `SCHEDULED` treatment whose execution window now contains the clock date — the clock date on or after `window_start` and on or before `window_end` — moves to `WINDOW_OPEN`. A treatment still `SCHEDULED` whose `window_end` now precedes the clock date moves to `EXPIRED`, as does a treatment in `WINDOW_OPEN` past its `window_end`.
3. **Volunteers.** A volunteer in `CLEARED` whose clearance has lapsed — the clock date reaching or passing the date exactly 365 days after `cleared_on`; the boundary date itself expires — moves to `EXPIRED`, and its cascades run: every `ACTIVE` assignment of that volunteer is released, and any `SCHEDULED` program thereby left with fewer active assignments than its `min_volunteers` is cancelled, releasing its own remaining active assignments.
4. **Programs.** A program still `SCHEDULED` whose `program_date` now precedes the clock date moves to `COMPLETED`, and every still-`ACTIVE` assignment on it completes with it.
5. **Permits.** A permit still `ACTIVE` whose `end_date` now precedes the clock date moves to `COMPLETED`, releasing its committed visitor days on the unit.

Because volunteers are evaluated before programs, a clearance expiry that strips a past-due program below its minimum staffing cancels the program; the completion step later in the same clock advance cannot complete it. The order is part of the contract, not an implementation detail.

### 2.6. Validation Order and Error Selection

Every request passes through a single ordered validation cascade, and the first failing check determines the error returned; later checks are never consulted once an earlier one has fired. When a request violates several rules, the response reports the highest-priority failure, never a list.

The cascade runs in this order:

1. **Authentication** — the role header is present and names a declared role, and the identity header is present for every role except `Anonymous` (`ERR_UNAUTHENTICATED`, 401).
2. **Authorization and ownership** — the caller's role is among the endpoint's authorized roles and the ownership anchors of §2.1 hold: a `PermitApplicant`'s `X-User-ID` matches the application's `applicant_ref` (and a permit creation payload's `applicant_ref` equals `X-User-ID`), a `Cooperator`'s `X-User-ID` matches the bid or agreement `cooperator_ref`, and a `Volunteer`'s list and read calls stay within their own `volunteer_id` (`ERR_UNAUTHORIZED_ROLE`, 403). Anchors defined against a stored resource — an application's `applicant_ref`, an agreement's `cooperator_ref`, an assignment's `volunteer_id` — are evaluated once that resource is loaded; against a path identifier that resolves to nothing they can never fire, and the request surfaces `ERR_NOT_FOUND`.
3. **Request shape** — required fields are present, types match, enum members are valid, and citation creation supplies exactly one of its two subject references (`ERR_INVALID_REQUEST`, 400). Body members beyond those an operation defines are ignored, not rejected.
4. **Existence** — every path identifier and every body-supplied resource reference resolves to an existing resource, validated left to right, path first and then body (`ERR_NOT_FOUND`, 404).
5. **State preconditions** — the invoked transition's from-state holds; terminal states reject every transition (`ERR_INVALID_STATE`, 409).
6. **Optimistic concurrency** — where an endpoint declares `expected_agreement_version`, the supplied value equals the agreement's current `version` (`ERR_STALE_VERSION`, 412).

Only after those six come the business rules, in their pinned sequence: (7) the nesting blackout buffer for prescribed burns (`ERR_NESTING_BLACKOUT`); (8) closure-posture gating of program creation and treatment starts (`ERR_POSTURE_CLOSED`); (9) determination finality (`ERR_DETERMINATION_NOT_FINAL`); (10) determination compatibility (`ERR_USE_INCOMPATIBLE`); (11) volunteer clearance for new assignments (`ERR_VOLUNTEER_NOT_CLEARED`); (12) agreement between a permit's use type and its determination's use type (`ERR_USE_TYPE_MISMATCH`); (13) one open bid per cooperator per offering (`ERR_DUPLICATE_BID`); (14) one active assignment per volunteer per program (`ERR_DUPLICATE_ASSIGNMENT`); (15) the program staffing ceiling (`ERR_PROGRAM_CAPACITY_EXCEEDED`); (16) the commercial filming day capacity (`ERR_COMMERCIAL_CAPACITY_EXCEEDED`); (17) unresolved comments at determination finalization (`ERR_UNRESOLVED_COMMENTS`); (18) date-range sanity (`ERR_DATE_RANGE_INVALID`); (19) windows and deadlines that would open in the past (`ERR_WINDOW_IN_PAST`); and (20) overlapping treatment windows on a unit (`ERR_TREATMENT_WINDOW_OVERLAP`). The fiscal rules close the cascade: (21) exact permit payment (`ERR_PAYMENT_AMOUNT_MISMATCH`); (22) refunds bounded by what was actually paid (`ERR_REFUND_EXCEEDS_PAID`); (23) a zero balance required to complete an agreement (`ERR_OUTSTANDING_BALANCE`); and (24) no overpayment of an agreement's outstanding balance (`ERR_OVERPAYMENT`).

The ordering has observable consequences. A permit approval whose referenced determination is neither final nor compatible surfaces `ERR_DETERMINATION_NOT_FINAL`, because finality outranks compatibility. A treatment request that is both mis-dated and inside a nesting buffer surfaces `ERR_NESTING_BLACKOUT`, because the safety rules outrank the temporal sanity rules. An assignment that duplicates an existing one on an over-full program surfaces `ERR_DUPLICATE_ASSIGNMENT`, because uniqueness outranks capacity. Implementations must evaluate in exactly this sequence.

### 2.7. Nested Resource Retrieval

The API enforces strict, hierarchical, left-to-right validation on every request that targets a nested resource. When a path contains more than one resource identifier — for example, a treatment created under a specific management unit — the existence of each identifier is confirmed in path order before any body-supplied reference is examined, and the request is rejected with `ERR_NOT_FOUND` at the first identifier that does not resolve. A request to schedule a treatment under a unit that does not exist fails on the unit identifier before the treatment payload is ever considered, and a body that references a non-existent determination fails only after every path segment has resolved. Existence checking (rule 4 in §2.6) always precedes state checks and business rules, so a well-formed request against a missing parent can never surface a business-rule error.

### 2.8. Money, Cents, and Rounding Discipline

All monetary values in the system — permit fees, bid rates, period assessments, and agreement balances — are integer cents. No fractional cents ever persist, and no monetary field is ever a float.

Rounding is pinned per calculation site and always uses the round-half-up method. For permit fees, the per-day rate multiplied by the inclusive day count and by the crew tier multiplier is rounded half-up to whole cents exactly once, before the base fee and any surcharge are added; nothing else in the fee computation is rounded. For cooperative cost-share assessments, each period's amount is rounded half-up to whole cents first and only then added into the running total — summing unrounded period amounts and rounding once at the end is explicitly wrong. The pinned example: a period of three animal-unit-months at a rate of 1001 cents per animal-unit-month yields a half-cent product of 1501.5, which rounds to 1502 cents; two such periods produce an assessed total of 3004 cents, where sum-then-round would incorrectly produce 3003.

Permit fees are additionally bounded: after the full assessed computation, the result is capped at a fee ceiling of 100000 cents and then raised to at least a fee floor of 5000 cents — the cap applies first, the floor second. The provisional estimate shown at submission time is exempt from tiering, surcharges, floor, and cap alike; it is the flat base fee of the requested use type and nothing more.

### 2.9. Optimistic Concurrency Control on Cooperative Agreements

Two write paths on a cooperative agreement require the client to prove it is acting on a current view of the record. Each carries a non-optional `expected_agreement_version` field in the request body, holding the `version` of the agreement the client last observed. If the supplied value does not equal the agreement's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412).

The first guarded path is the recording of a period assessment. Assessing a new period is legitimate against any `ACTIVE` agreement, so a request issued with fresh knowledge of the record sees identical state and succeeds; the version field exists to reject a stale view, because the assessment math accumulates into totals — `assessed_total_cents` and the derived `outstanding_balance_cents` — that the client may never have observed.

The second guarded path is the issuance of a citation that names an agreement subject. Issuing a further citation is legitimate against an agreement regardless of how many citations came before, so again a strictly later, freshly-read request succeeds; the version check rejects the stale view, since the agreement's `compliance_points` may have been debited or restored since the officer last read it. When a citation names a permit subject instead, the request carries no version field at all — the guard simply does not apply.

No other endpoint in the API takes a version field. Endpoints not named here are processed without any optimistic concurrency check.

### 2.10. Cascading Consistency Across Closures, Programs, and Permits

Refuge operations are physically coupled: closing a unit changes what may happen on it, and the system maintains that coupling through automatic cascades rather than manual cleanup. Whenever a parent record undergoes a transition that renders part of its scope non-operational, dependent records are resolved in the same breath, and every record a cascade touches is mutated in the ordinary sense — its `updated_at` refreshes and its `version` increments.

Activating a facility closure is the widest cascade in the system. It recomputes the host unit's derived posture; it cancels every interpretive program still `SCHEDULED` on the unit whose program date falls inside the closure window; it releases every still-active volunteer assignment on each cancelled program; and — for full-scope closures only — it suspends every `ACTIVE` permit on the unit whose authorized window intersects the closure window, stamping each suspended permit with the closure that caught it and releasing its committed visitor days from the unit's tally. Lifting a closure runs the reverse half of that cascade: posture is recomputed, and every permit pinned to the lifted closure is reinstated when its authorized window still extends to the current clock date, or expired when that window has already passed — with reinstated permits adding their visitor days back. One direction is deliberately asymmetric: programs cancelled by a closure activation are never restored by its lift; a cancelled program is permanent.

Volunteer expiry cascades through staffing rather than closures. When a clearance lapses, the volunteer's active assignments are released, and any still-scheduled program whose remaining active staffing drops below its declared minimum is cancelled, releasing its own remaining assignments in turn. The reverse anchor here is the pinned clock order of §2.5: because volunteers are evaluated before programs within a single clock advance, a program cannot be completed by the clock in the same advance that cancels it for a staffing shortfall.

### 2.11. Seasonal Safety Policy: Posture, Nesting Buffers, and Windows

Two standing safety policies govern what may be scheduled or started on a unit, independent of any particular workflow.

The first is the **access posture** of a unit, a derived snapshot recomputed on every closure activation and lift. If any `ACTIVE` closure on the unit has scope `FULL`, the posture is `CLOSED`. Otherwise, if any `ACTIVE` closure has scope `TRAILS_ONLY`, the posture is `RESTRICTED`. Otherwise the posture is `OPEN`. Closures in `SCHEDULED` or `LIFTED` status never contribute. Posture gates two operations: scheduling an interpretive program is rejected with `ERR_POSTURE_CLOSED` when the chosen program date intersects the window of an `ACTIVE` full-scope closure on the same unit — a date-scoped check, not a point-in-time read — and starting a treatment is rejected with `ERR_POSTURE_CLOSED` when the unit's posture at the current clock date is `CLOSED`, meaning an active full-scope closure covers that date.

The second policy protects nesting habitat from fire. A prescribed burn scheduled on a unit must keep a fourteen-day buffer ahead of any nesting closure — whether merely `SCHEDULED` or already `ACTIVE` — on the same unit. Whenever the burn's window precedes or overlaps the closure's window, the request is rejected with `ERR_NESTING_BLACKOUT` if the burn's `window_end` falls later than fourteen days before the closure's `start_date`. A burn whose window ends exactly fourteen days before the closure begins satisfies the buffer; one day later violates it.

Treatment windows on the same unit additionally follow half-open semantics: a window covers the days from its `window_start` up to but not including its `window_end` for overlap purposes. Adjacency — one window ending exactly where another begins — is allowed, and any strict intersection between two windows on the same unit is rejected with `ERR_TREATMENT_WINDOW_OVERLAP`.

## 3. Business Logic & Workflows

### 3.1. Management Units and Their Derived Snapshot

The management unit is the geographic anchor of the refuge. A `RefugeManager` creates one by supplying a `name` — a human-readable label such as "North Marsh" — a `habitat_type` of exactly one of `WETLAND`, `GRASSLAND`, `FOREST`, or `MIXED`, and an `acreage` that must be an integer greater than zero. Creation initializes the unit's computed fields: `access_posture` starts at `OPEN`, `committed_visitor_days` starts at zero, and both habitat priority scores start at zero.

Three derived quantities ride on every unit and are recomputed as events unfold. The `access_posture` snapshot follows the derivation in §2.11 exactly: `CLOSED` whenever any active full-scope closure exists on the unit, else `RESTRICTED` whenever any active trails-only closure exists, else `OPEN`; it is recomputed on every closure activation and every closure lift, and never changes in any other way.

The `committed_visitor_days` tally measures public-use load. It is the sum, over the unit's permit applications currently in `ACTIVE` status, of each permit's `crew_size` multiplied by its trip length — the inclusive day count from `start_date` through `end_date`, counting both endpoints. Permits in `APPROVED`, `SUSPENDED`, `COMPLETED`, `REVOKED`, or `EXPIRED` contribute nothing. The tally is recomputed whenever the set of contributing permits or their contribution changes: on payment of an approved permit, on closure-driven suspension, on lift-driven reinstatement, on revocation, and on clock-driven completion. Two invariants are pinned. A suspension followed by its matching reinstatement — the same closure, lifted — leaves the tally unchanged. And a payment followed by a closure activation that suspends the permit returns the unit to its pre-payment value.

The habitat priority scores summarize finished habitat work. Only treatments that have reached `COMPLETED` on the unit contribute; treatments in `SCHEDULED`, `WINDOW_OPEN`, `IN_PROGRESS`, or `EXPIRED` are excluded from both. Each completed treatment contributes a weight by type: `WATER_MANIPULATION` contributes 30, `PRESCRIBED_BURN` contributes 50, and `INVASIVE_CONTROL` contributes 20. The `habitat_priority_annual` score is the flat sum of those weights. The `habitat_priority_breeding` score applies the same weights but doubles the contribution of any treatment whose execution window intersects the breeding window — March 1 through June 30 of the year of that treatment's `window_start`. For an identical set of completed treatments the two variants differ whenever any window touches the breeding season: one prescribed burn executed in March together with one invasive-control treatment executed in August yields a breeding-weighted score of 120 against an annual score of 70. Both scores are recomputed each time a treatment completes on the unit.

A computed read on the unit exposes the whole snapshot at once: the current `access_posture`, the `committed_visitor_days` tally, `habitat_priority_breeding`, `habitat_priority_annual`, and `active_closure_count`, the number of closures currently in `ACTIVE` status on the unit. This read never mutates anything; it reports the derivations as they stand.

### 3.2. Compatibility Determinations and the Public Comment Record

Before any public use is authorized on the refuge, a compatibility determination must support it. A `PermitOfficer` or `RefugeManager` opens the process by creating a determination with the `use_type` it covers — one of `RESEARCH`, `PHOTOGRAPHY`, `COMMERCIAL_FILMING`, `GUIDED_ACTIVITY`, or `GRAZING` — a `title`, and the declared comment window: `comment_open_date`, the first day public comment may be taken, and `comment_close_date`, the last day of that window. The close date must fall strictly after the open date, or creation fails with `ERR_DATE_RANGE_INVALID`; the open date must not precede the current logical clock date, or creation fails with `ERR_WINDOW_IN_PAST`. A new determination starts in `DRAFT`, with `finding` and `rationale` both null and an `unresolved_comment_count` of zero.

Opening the comment window is an explicit officer action that moves the determination from `DRAFT` to `PUBLIC_COMMENT`. The action is only valid while the determination is in `DRAFT` — any other status is rejected with `ERR_INVALID_STATE` — and only while the current clock date falls within the declared window, on or after `comment_open_date` and on or before `comment_close_date`; a clock date outside the window is rejected with `ERR_WINDOW_IN_PAST` or `ERR_INVALID_STATE` according to the validation order of §2.6. No fields change beyond the status; the window is simply open.

While the determination stands in `PUBLIC_COMMENT`, the public weighs in. An `Anonymous` caller submits a comment with an `author_name` and a `body`; each submission creates a comment in `SUBMITTED` status — its `disposition` still null — and increments the determination's `unresolved_comment_count` by one. Submission is a creature of the window: comments attach only to a determination in `PUBLIC_COMMENT`, and an attempt against a determination in any other status is rejected with `ERR_INVALID_STATE`. The same public may read a determination and page through its comments; the comment listing accepts an optional `status` filter alongside `limit` and `offset`.

When the clock advances past `comment_close_date`, the determination moves on its own from `PUBLIC_COMMENT` to `ADJUDICATION`, closing intake. Adjudication is the officer's workspace: a `PermitOfficer` or `RefugeManager` adjudicates each submitted comment, recording a `disposition` of `ACCEPTED`, `REJECTED`, or `NOTED` along with an optional `note`. A comment can be adjudicated only while it is `SUBMITTED` and only while its parent determination — the one its `determination_id` references — stands in `PUBLIC_COMMENT` or `ADJUDICATION`; each adjudication moves the comment to `ADJUDICATED` and decrements the determination's `unresolved_comment_count` by one.

Finalization moves the determination from `ADJUDICATION` to `FINAL` and is the point of decision. The officer supplies the `finding` — `COMPATIBLE` or `NOT_COMPATIBLE` — and a `rationale`, both recorded onto the determination as the window's lasting record. Finalization is refused while any comment remains unresolved: an `unresolved_comment_count` above zero is rejected with `ERR_UNRESOLVED_COMMENTS`. `FINAL` is terminal; a finalized determination never changes again, and it becomes the reference against which permit approvals and grazing offerings are gated elsewhere in this document.

### 3.3. The Public Use Permit Journey: Application to Expiration

A member of the public enters the system as a `PermitApplicant` by submitting an application. The submission names the applicant through `applicant_ref` — which must equal the caller's `X-User-ID`, or the request is refused with `ERR_UNAUTHORIZED_ROLE` — and the place and purpose through `management_unit_id` and `determination_id`, referencing the unit where the use will occur and the compatibility determination that covers it. The requested `use_type` must be one of `RESEARCH`, `PHOTOGRAPHY`, `COMMERCIAL_FILMING`, or `GUIDED_ACTIVITY`, and it must equal the referenced determination's `use_type` exactly; a mismatch is rejected with `ERR_USE_TYPE_MISMATCH`. The party size is given as `crew_size`, an integer of at least one, and the authorized window runs from `start_date` through `end_date` inclusive — the `end_date` may equal the `start_date` but may not precede it, or the submission fails with `ERR_DATE_RANGE_INVALID`. A valid application starts in `SUBMITTED`.

At submission the applicant sees a provisional estimate, stored as `provisional_fee_cents`. The estimate is deliberately flat: it is the base fee for the requested use type and nothing else — 15000 cents for `RESEARCH`, 7500 cents for `PHOTOGRAPHY`, 20000 cents for `COMMERCIAL_FILMING`, and 3000 cents for `GUIDED_ACTIVITY`. Crew size, trip length, tiering, surcharge, floor, and cap are all ignored at this stage, so the provisional figure and the eventual assessed figure differ for identical application data: a research application for a crew of four over three days shows 15000 cents provisionally and will assess at 21000 cents.

Review is a dialogue. A `PermitOfficer` or `RefugeManager` may return an application that sits in `SUBMITTED` or `UNDER_REVIEW` for revision, moving it to `REVISION_REQUESTED` and recording the payload's `note` onto the application as its `revision_note`. The applicant — and only that applicant, with `X-User-ID` matching the stored `applicant_ref` — resubmits, moving the application from `REVISION_REQUESTED` to `UNDER_REVIEW`. The resubmission may carry revised `crew_size`, `start_date`, and `end_date`, and an optional `note`; `use_type` and `determination_id` are immutable after creation and are simply not part of the resubmission input, and the use-type agreement rule of `ERR_USE_TYPE_MISMATCH` applies to resubmission exactly as it does to initial submission. When any of the crew or date values are supplied, the provisional estimate is recomputed by the same flat rule — still the base fee of the use type.

Approval is the officer's decision point, moving an application from `UNDER_REVIEW` to `APPROVED`. Three gates guard it. The referenced determination must have reached `FINAL`, else `ERR_DETERMINATION_NOT_FINAL`. That determination's `finding` must be `COMPATIBLE`, else `ERR_USE_INCOMPATIBLE`. And for a `COMMERCIAL_FILMING` application, a capacity rule applies: no calendar day within the requested window may already carry two or more commercial-filming permits in `APPROVED` or `ACTIVE` status on the same unit — approving into such a day is rejected with `ERR_COMMERCIAL_CAPACITY_EXCEEDED`. Non-commercial use types face no day-capacity check at all.

Approval is also the moment the real fee is computed and stored as `assessed_fee_cents`, which remains null until this point. The assessed fee starts from the same base fee by use type, then adds the per-day rate for that use type — 2000 cents for `RESEARCH`, 1500 for `PHOTOGRAPHY`, 5000 for `COMMERCIAL_FILMING`, 800 for `GUIDED_ACTIVITY` — multiplied by the inclusive day count of the authorized window and by a crew tier multiplier: 1.0 for a crew of nine or fewer, 1.25 for a crew of ten through nineteen, and 1.5 for a crew of twenty or more. That per-day-times-days-times-tier product is rounded half-up to whole cents exactly once before it joins the base fee. A flat surcharge of 10000 cents is added for `COMMERCIAL_FILMING` only. The raw result is then capped at the ceiling of 100000 cents, and finally raised to at least the floor of 5000 cents — cap first, floor second.

Payment converts approval into authorization. The applicant — again only the matching `applicant_ref` — pays by supplying `amount_cents`, which must equal the `assessed_fee_cents` exactly; any other amount is rejected with `ERR_PAYMENT_AMOUNT_MISMATCH` (HTTP 402). A successful payment moves the permit from `APPROVED` to `ACTIVE` and commits the party's load onto the unit: the permit's `crew_size` multiplied by its inclusive day count is added into the unit's `committed_visitor_days`.

Once `ACTIVE`, a permit lives at the mercy of the calendar and the closures. Activating a full-scope closure on the same unit whose window intersects the permit's authorized window suspends the permit, moving it from `ACTIVE` to `SUSPENDED`: the closure's identity is stamped onto the permit as `suspended_by_closure_id`, and the permit's visitor days are released from the unit's tally. Lifting that closure reverses the suspension for every permit pinned to it: when the permit's `end_date` is on or after the current clock date, the permit returns to `ACTIVE`, its `suspended_by_closure_id` is cleared, and its visitor days are added back; when the `end_date` has already passed, the permit moves instead to `EXPIRED`, with `suspended_by_closure_id` likewise cleared. A permit still `ACTIVE` when the clock advances past its `end_date` completes on its own, moving to `COMPLETED` and releasing its days. Note that trails-only closures never suspend permits at all — only the full scope does.

Revocation is the officer's instrument for ending an authorization early. A `PermitOfficer` or `RefugeManager` may revoke from any of `UNDER_REVIEW`, `APPROVED`, `ACTIVE`, or `SUSPENDED`, moving the permit to `REVOKED`; the payload's `reason` is required input, recorded by the request and not persisted on the permit. Revoking an `ACTIVE` permit releases its committed visitor days from the unit; revoking an `APPROVED` one changes no tallies, because approved-but-unpaid permits hold no committed days; revoking a `SUSPENDED` one clears its `suspended_by_closure_id`. `COMPLETED`, `REVOKED`, and `EXPIRED` are terminal: from any of them, every further transition is rejected with `ERR_INVALID_STATE`.

Applicants and staff read permits individually or through the listing, which accepts optional filters on `applicant_ref`, `management_unit_id`, `determination_id`, and `status` alongside `limit` and `offset`. A `PermitApplicant` caller only ever sees their own applications: the listing is confined to the caller's `applicant_ref`, and reading another applicant's permit by id is refused with `ERR_UNAUTHORIZED_ROLE`.

### 3.4. Habitat Treatments on the Seasonal Calendar

Habitat work is planned against the seasons. A `Biologist` or `RefugeManager` schedules a treatment on a unit by choosing a `treatment_type` — `WATER_MANIPULATION`, `PRESCRIBED_BURN`, or `INVASIVE_CONTROL` — and an execution window from `window_start` to `window_end`, with optional prescription `notes`. The window must open in the future: a `window_start` earlier than the current clock date is rejected with `ERR_WINDOW_IN_PAST`. The window must also be non-degenerate: `window_end` must fall strictly after `window_start`, so a window cannot be empty, and a violation surfaces as `ERR_DATE_RANGE_INVALID`. A scheduled treatment starts in `SCHEDULED`.

Two further guards protect the calendar, and §2.6's ordering decides which one speaks first. The nesting blackout of §2.11 forbids a `PRESCRIBED_BURN` whose window crowds a `NESTING` closure on the same unit: whenever the burn window precedes or overlaps the closure window, the burn is rejected with `ERR_NESTING_BLACKOUT` if its `window_end` falls later than fourteen days before the closure's `start_date` — an ending exactly fourteen days ahead passes, one day later fails. The rule consults nesting closures in either `SCHEDULED` or `ACTIVE` status; a lifted closure no longer constrains anything. Independently, treatment windows on the same unit may not overlap: under the half-open semantics of §2.11, two windows that share only a boundary day — one `window_end` equal to the other's `window_start` — coexist, while any strict intersection is rejected with `ERR_TREATMENT_WINDOW_OVERLAP`. Both guards apply at scheduling time on the creation of a treatment.

The clock then works the window. When the clock date enters the window — on or after `window_start` and on or before `window_end` — a `SCHEDULED` treatment opens, moving to `WINDOW_OPEN`. When the clock moves past `window_end` while the treatment is still `SCHEDULED`, the opportunity is lost and the treatment moves to `EXPIRED`; the same fate meets a `WINDOW_OPEN` treatment that was never started once `window_end` passes. Execution itself is a deliberate act: a `Biologist` or `RefugeManager` starts a `WINDOW_OPEN` treatment, moving it to `IN_PROGRESS` — but only while the unit's access posture at the current clock date is not `CLOSED`. Starting against an active full-scope closure covering that date is rejected with `ERR_POSTURE_CLOSED`, even though the window is open.

Completion is the payoff. A `Biologist` or `RefugeManager` completes an `IN_PROGRESS` treatment, moving it to `COMPLETED`, and the unit's two habitat priority scores of §3.1 are recomputed immediately, folding the finished work into both the breeding-weighted and the annual figure. `COMPLETED` and `EXPIRED` are terminal. Staff read a unit's treatment calendar through the listing on the unit, which accepts an optional `status` filter together with `limit` and `offset`.

### 3.5. Facility Closures and Their Cascades

Closures are how the refuge takes a unit — or just its visitor facilities — out of service for a season. A `Biologist` or `RefugeManager` schedules one with a `closure_type` of `NESTING`, `MIGRATION`, `HUNT_SAFETY`, or `SPECIAL_EVENT`; a `scope` of `FULL`, which closes the whole unit, or `TRAILS_ONLY`, which closes visitor facilities only; and a window from `start_date` through `end_date`. The closure's dates are inclusive for every overlap and gating purpose — a closure whose `end_date` is today still closes today — and the `end_date` may equal but not precede the `start_date`, else `ERR_DATE_RANGE_INVALID`. A new closure starts in `SCHEDULED`. Unlike treatments, closures are never clock-driven: activation and lift are explicit ranger actions, and a `SCHEDULED` closure simply waits.

Activation moves a closure from `SCHEDULED` to `ACTIVE` and fires the cascade of §2.10 on the host unit. First the unit's `access_posture` is recomputed — a trails-only activation can turn an `OPEN` unit `RESTRICTED`, and a full-scope activation turns it `CLOSED`. Then, regardless of scope, every interpretive program on the unit still `SCHEDULED` whose `program_date` falls within the closure's inclusive window is cancelled, moving to `CANCELLED`, and every volunteer assignment still `ACTIVE` on each cancelled program is released to `RELEASED`. Finally, when and only when the scope is `FULL`, every permit on the unit in `ACTIVE` status whose authorized window intersects the closure window is suspended to `SUSPENDED`, stamped with `suspended_by_closure_id` set to this closure's `id`, and each suspension releases that permit's visitor days from the unit's `committed_visitor_days`.

Lifting moves an `ACTIVE` closure to `LIFTED`, the terminal state, and runs the reverse half. The unit's `access_posture` is recomputed against whatever closures remain active. Every permit whose `suspended_by_closure_id` points at the lifted closure is then resolved: if the permit's `end_date` is on or after the current clock date it reinstates to `ACTIVE`, clears the pin, and adds its visitor days back into the unit's tally; if the `end_date` has already passed it expires to `EXPIRED` and clears the pin without restoring any days. Programs are the deliberate exception: a program cancelled by the activation is not restored by the lift — cancellation is permanent, and the program stays `CANCELLED`.

Staff review a unit's closures through the listing on the unit, which takes an optional `status` filter with `limit` and `offset`. The posture consequences of everything in this subsection are readable at any time through the unit's computed snapshot described in §3.1.

### 3.6. Interpretive Programs, Volunteers, and Assignments

Interpretive programs are the refuge's scheduled public-education events, and they are staffed by volunteers whose clearances are always on a clock. A `VolunteerCoordinator` or `RefugeManager` schedules a program on a unit with a `title`, a `program_date`, and a staffing band: `min_volunteers`, the minimum number of active assignments that keeps the program viable and an integer of at least one, and `max_volunteers`, the ceiling on accepted assignments, which must be at least the minimum — a `max_volunteers` below `min_volunteers` is malformed and rejected with `ERR_INVALID_REQUEST`. The program date must not precede the current clock date, or scheduling fails with `ERR_WINDOW_IN_PAST`; and it must not intersect the inclusive window of an active full-scope closure on the same unit, or scheduling fails with `ERR_POSTURE_CLOSED` — the date-scoped posture check of §2.11. A new program starts in `SCHEDULED`. Programs on a unit are listed with an optional `status` filter plus `limit` and `offset`, and this listing is one of the reads open to `Anonymous`.

A program has no manual cancel. It leaves `SCHEDULED` in exactly three ways. A closure activation cancels it, as §3.5 describes, when its `program_date` falls inside the activated closure's window on the same unit. A volunteer expiry can cancel it indirectly, as described below, when a release strips it below its `min_volunteers`. And the clock completes it: once the clock date passes `program_date`, a still-`SCHEDULED` program moves to `COMPLETED`, and every assignment still `ACTIVE` on it completes as well. The pinned clock order of §2.5 resolves the race between the last two: volunteers are evaluated before programs, so a clearance expiry cancels an understaffed past-due program before the completion step can complete it.

Anyone may register as a volunteer: an `Anonymous` caller supplies a `full_name` and an `email`, and the record starts with `background_status` of `PENDING` and a null `cleared_on`. Clearing is the coordinator's act — a `VolunteerCoordinator` or `RefugeManager` clears a volunteer whose `background_status` is `PENDING` or `EXPIRED`, moving it to `CLEARED` and stamping `cleared_on` with the current logical clock date; clearing an `EXPIRED` volunteer is a renewal under exactly the same rule. Clearance lasts 365 days: when the clock date reaches or passes the date exactly 365 days after `cleared_on` — the boundary day itself expires — the volunteer moves from `CLEARED` to `EXPIRED`. That expiry cascades: every assignment of the volunteer still `ACTIVE` is released to `RELEASED`, and every program still `SCHEDULED` whose remaining count of active assignments drops below its `min_volunteers` because of those releases is cancelled to `CANCELLED`, releasing its own remaining active assignments in the second hop.

Assignment is how a cleared volunteer joins a program. A `VolunteerCoordinator` or `RefugeManager` creates the assignment with a `volunteer_id`; the program is the one named in the nested path, and the new record links to it as its `program_id`. The program must still be `SCHEDULED` — assigning into a cancelled or completed program violates the state machine and is rejected with `ERR_INVALID_STATE`. Three business guards then apply in the §2.6 order: the referenced volunteer's `background_status` must be `CLEARED`, else `ERR_VOLUNTEER_NOT_CLEARED`; the volunteer may hold at most one `ACTIVE` assignment on the program, so a second active assignment for the same volunteer is rejected with `ERR_DUPLICATE_ASSIGNMENT`; and the program must have headroom — creating an assignment when the program already carries `max_volunteers` active assignments is rejected with `ERR_PROGRAM_CAPACITY_EXCEEDED`. A valid assignment starts in `ACTIVE`.

Assignments have no direct transitions of their own; both of their exits are cascades. An `ACTIVE` assignment moves to `RELEASED` when its volunteer expires, when its program is cancelled, or when a closure activation cancels its program as in §3.5. It moves to `COMPLETED` when its program completes under the clock. `RELEASED` and `COMPLETED` are terminal.

Assignments are readable one at a time or through the listing, which filters optionally on `volunteer_id`, `program_id`, and `status` with `limit` and `offset`. Reads are staff affairs with one anchored exception: a caller in the `Volunteer` role may list and read only assignments under their own `volunteer_id`, and any attempt to frame the query on someone else's — or to read another volunteer's assignment by id — is rejected with `ERR_UNAUTHORIZED_ROLE`.

### 3.7. Cooperative Grazing: Offerings, Bids, and Award

Grazing on the refuge is a habitat tool, awarded competitively. A `Biologist` or `RefugeManager` posts an offering on a unit with a `description` of the habitat objective the grazing serves, an `aum_cap` fixing the maximum animal-unit-months authorized over the window — an integer greater than zero — and a grazing window from `grazing_window_start` to `grazing_window_end`, where the end must fall strictly after the start or the posting fails with `ERR_DATE_RANGE_INVALID`. Bidding closes on the `application_deadline`, which must not precede the current clock date at posting, else `ERR_WINDOW_IN_PAST`. The offering also declares a `min_stewardship_rating`, an integer from 1 to 10, setting the eligibility floor for award. A posted offering starts in `OPEN`.

Posting an offering is gated on the compatibility record for the `GRAZING` use. The refuge's determination covering `GRAZING` must have reached `FINAL`; an offering posted while that determination stands in any earlier status is rejected with `ERR_DETERMINATION_NOT_FINAL`. And the finalized finding must be `COMPATIBLE`; a `NOT_COMPATIBLE` finding rejects the posting with `ERR_USE_INCOMPATIBLE`. When several determinations covering `GRAZING` exist, only those in `FINAL` are consulted, and the latest-created `FINAL` one governs.

Cooperators bid while the offering stands `OPEN`. A `Cooperator` submits a bid naming themselves through `cooperator_ref`, which must equal the caller's `X-User-ID`, quoting a `rate_cents_per_aum` — the price in cents per animal-unit-month, an integer greater than zero — and declaring a `stewardship_rating` from 1 to 10, which the offering's floor will judge at selection. A bid submitted after the clock has passed the offering's `application_deadline` is rejected with `ERR_WINDOW_IN_PAST`. Each cooperator may hold at most one `SUBMITTED` bid per offering; a second open bid from the same cooperator is rejected with `ERR_DUPLICATE_BID`. Every bid starts in `SUBMITTED`, and each bid records the offering it was placed against as its `offering_id`, taken from the nested path at submission. Offerings are listed on their unit and bids on their offering, each listing accepting an optional `status` filter with `limit` and `offset`, and individual offerings are readable on their own.

Award is the manager's call and a single atomic act: a `RefugeManager` closes an `OPEN` offering and selects the participant. The eligible pool is exactly the offering's bids still in `SUBMITTED` whose `stewardship_rating` is at least the offering's `min_stewardship_rating`. Each eligible bid is ranked by a rank score — its `stewardship_rating` multiplied by 1000, minus its `rate_cents_per_aum` — and the highest score wins; ties are broken toward the bid with the earliest `created_at`, and random identifiers never participate in the selection. The winning bid moves to `WINNING`, every other `SUBMITTED` bid moves to `REJECTED`, and the award creates the cooperative agreement. The close-and-select response carries the updated offering; the created agreement is read through the cooperative-agreement endpoints, for example by filtering the agreement listing on `winning_bid_id`.

When the eligible pool is empty — no bids at all, or every bid below the stewardship floor — there is no winner: the offering moves to `EXPIRED`, every `SUBMITTED` bid moves to `REJECTED`, and no agreement is created. `AWARDED` and `EXPIRED` are both terminal for the offering, and `WINNING` and `REJECTED` are both terminal for its bids.

The agreement created on award starts `ACTIVE` with `compliance_points` at 100 and all three ledger totals — `assessed_total_cents`, `paid_total_cents`, and `refunded_total_cents` — at zero. It is built by copying: `management_unit_id`, `aum_cap`, `grazing_window_start`, and `grazing_window_end` come from the offering, `cooperator_ref` comes from the winning bid, and `winning_bid_id` records the winning bid itself, one agreement per winning bid. There is no other way to create an agreement.

### 3.8. Running an Agreement: Assessments, Ledger, Citations, and Completion

Once awarded, an agreement is a running fiscal and compliance record. Its `outstanding_balance_cents` is derived, never set directly: it is the `assessed_total_cents` minus the `paid_total_cents` plus the `refunded_total_cents`. The pinned invariant is that a payment followed by an equal refund leaves the outstanding balance unchanged.

Assessment is how the refuge bills the cooperator's cost share, period by period. A `Biologist` or `RefugeManager` records one period against an `ACTIVE` agreement — assessments are blocked while an agreement is `SUSPENDED`, rejected with `ERR_INVALID_STATE` — supplying a `period_key` identifying the period, the `aum_used` that period, the `rate_cents_per_aum` charged, and the OCC guard `expected_agreement_version` of §2.9. `aum_used` and `rate_cents_per_aum` are validated as integers only, with no range bound. The period amount is the refuge's fifty percent share: the animal-unit-months multiplied by the rate, halved, rounded half-up to whole cents for that period, and only then added into `assessed_total_cents`. Per §2.8 the rounding order is pinned — round each period, then sum — so two periods of three animal-unit-months at 1001 cents assess 3004 cents in total, never 3003. Each assessment recomputes the outstanding balance and increments the agreement's `version` by one.

Money moves through ledger entries, each recorded with a `type` and an `amount_cents`, and allowed while the agreement is `ACTIVE` or `SUSPENDED` — a `COMPLETED` agreement accepts no further entries and rejects them with `ERR_INVALID_STATE`. `amount_cents` is validated as an integer only, with no range bound beyond the fiscal guards below. A `PAYMENT` entry may be posted only by the owning `Cooperator`, whose `X-User-ID` must match the agreement's `cooperator_ref`; it adds to `paid_total_cents`, and it may not exceed the current outstanding balance — an overpaying payment is rejected with `ERR_OVERPAYMENT`, so balances can never go negative. A `REFUND` entry may be posted only by a `RefugeManager`; it adds to `refunded_total_cents` and is capped at the refundable balance — the `paid_total_cents` minus the `refunded_total_cents` so far — with any excess rejected as `ERR_REFUND_EXCEEDS_PAID`. Both kinds recompute `outstanding_balance_cents` and increment the agreement's `version` by one.

Citations are the law-enforcement instrument. A `LawEnforcementOfficer` or `RefugeManager` issues one with a `severity` of `MINOR`, `MAJOR`, or `CRITICAL` and a free-text `note`, naming exactly one subject: either `subject_permit_id` for a permit or `subject_agreement_id` for an agreement — supplying neither or both is malformed and rejected with `ERR_INVALID_REQUEST`. The citation's `points` are computed from severity and never taken from the input, even if a value is supplied: 10 for `MINOR`, 25 for `MAJOR`, 50 for `CRITICAL`. Every citation starts in `ISSUED`. Against a permit subject, the citation records the violation and nothing more — no fee changes, no permit status change, and no version field on the request. Against an agreement subject, the request must carry `expected_agreement_version` per §2.9; issuance debits the agreement's `compliance_points` by the citation's points and increments the agreement's `version` by one.

Compliance points govern the agreement's standing. An agreement starts at 100 points. After every debit, if the agreement is `ACTIVE` and its `compliance_points` have fallen below the suspension threshold of 60, it moves to `SUSPENDED` — exactly 60 points remains `ACTIVE`, while 59 suspends. Suspension blocks new assessments but not payments: the ledger paths stay open in `SUSPENDED`, so a cooperator can always pay down a balance. Citations against an agreement remain issuable regardless of its standing — `ACTIVE`, `SUSPENDED`, and `COMPLETED` alike; issuance against a `COMPLETED` agreement still debits its `compliance_points` and never changes its status.

Voiding unwinds a citation. A `LawEnforcementOfficer` or `RefugeManager` voids an `ISSUED` citation — the only transition it supports, moving it to `VOIDED`; the payload's `reason` is required input, recorded by the request and not persisted on the citation. When the voided citation named an agreement subject, the agreement is credited the citation's points back and its `version` increments by one; and if the agreement was `SUSPENDED` and the restored `compliance_points` reach at least 60, it returns to `ACTIVE`. Permit-subject voids change the citation only.

Completion closes the fiscal year of the agreement. A `RefugeManager` completes an agreement that stands `ACTIVE` — never one already `SUSPENDED` — and only when the `outstanding_balance_cents` is exactly zero; any nonzero balance is rejected with `ERR_OUTSTANDING_BALANCE`. `COMPLETED` is terminal. Agreements are readable individually and through a listing filtered optionally by `management_unit_id`, `winning_bid_id`, and `status` with `limit` and `offset`; citations are likewise readable individually and through a listing filtered by `subject_permit_id`, `subject_agreement_id`, and `status` with `limit` and `offset`.

### 3.9. Population Objectives and State Agency Surveys

Population management is shared with the states. A `StateAgencyPartner` or `RefugeManager` sets an annual objective on a unit by naming a `species` — a common name such as "Sandhill Crane" — and a `target_count`, the state-agency population target for the unit, an integer greater than zero. A fresh objective stands in `NO_SURVEY` with its `current_survey_count` still null: until the first survey lands, there is nothing to measure.

Surveys arrive through the same partners. Recording a survey supplies a `survey_count`, which becomes the objective's `current_survey_count`, and recomputes the objective's standing. `survey_count` is validated as an integer only, with no range bound. The test is an integer comparison with no floating point: the objective is `AT_TARGET` when ten times the survey count is at least seven times the target count, and `BELOW_TARGET` otherwise — so a survey count of exactly seventy percent of the target satisfies the objective, and one short of that does not. Each new survey overwrites the count and re-derives the standing; objectives are listed on their unit with `limit` and `offset`.

## 4. Endpoint Definitions

Operations that create a new resource — a management unit, a determination, a comment, a permit application, a treatment, a closure, a program, a volunteer, an assignment, an offering, a bid, a citation, or a population objective — return a `201 Created` status code. Operations that act on an existing resource — state transitions, assessments, ledger entries, payments, adjudications, and the clock advance — return a `200 OK` status code. All endpoints live under the `/refuge` mount except the clock control, which sits outside the business surface. Request payloads, preconditions, side effects, and the exact validation each operation enforces are defined by the workflows of §3 and the principles of §2; this table is the navigational index only. A request to a declared path using a method the table does not declare for it is rejected with `ERR_NOT_FOUND` (404).

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/refuge/management-units` | Create a management unit | RefugeManager |
| GET | `/refuge/management-units/{id}` | Read one management unit | RefugeManager, Biologist, PermitOfficer, VolunteerCoordinator, LawEnforcementOfficer, StateAgencyPartner |
| GET | `/refuge/management-units/{id}/posture` | Read the unit's computed posture snapshot | RefugeManager, Biologist, PermitOfficer, VolunteerCoordinator, LawEnforcementOfficer, StateAgencyPartner |
| POST | `/refuge/determinations` | Create a compatibility determination (starts DRAFT) | PermitOfficer, RefugeManager |
| GET | `/refuge/determinations/{id}` | Read one determination | PermitOfficer, RefugeManager, Anonymous |
| POST | `/refuge/determinations/{id}/open-comment` | Open the public comment window (DRAFT -> PUBLIC_COMMENT) | PermitOfficer, RefugeManager |
| POST | `/refuge/determinations/{id}/finalize` | Finalize a determination (ADJUDICATION -> FINAL) | PermitOfficer, RefugeManager |
| POST | `/refuge/determinations/{id}/comments` | Submit a public comment on a determination in PUBLIC_COMMENT | Anonymous |
| GET | `/refuge/determinations/{id}/comments` | List comments on a determination | PermitOfficer, RefugeManager, Anonymous |
| POST | `/refuge/comments/{id}/adjudicate` | Adjudicate a submitted comment (SUBMITTED -> ADJUDICATED) | PermitOfficer, RefugeManager |
| POST | `/refuge/permits` | Submit a public use permit application (starts SUBMITTED) | PermitApplicant |
| GET | `/refuge/permits/{id}` | Read one permit application | PermitApplicant, PermitOfficer, RefugeManager |
| GET | `/refuge/permits` | List permit applications with optional filters | PermitApplicant, PermitOfficer, RefugeManager |
| POST | `/refuge/permits/{id}/return-for-revision` | Return an application for revision (SUBMITTED/UNDER_REVIEW -> REVISION_REQUESTED) | PermitOfficer, RefugeManager |
| POST | `/refuge/permits/{id}/resubmit` | Resubmit a returned application (REVISION_REQUESTED -> UNDER_REVIEW) | PermitApplicant |
| POST | `/refuge/permits/{id}/approve` | Approve an application (UNDER_REVIEW -> APPROVED); assesses the final fee | PermitOfficer, RefugeManager |
| POST | `/refuge/permits/{id}/pay` | Pay the assessed fee (APPROVED -> ACTIVE) | PermitApplicant |
| POST | `/refuge/permits/{id}/revoke` | Revoke a permit (UNDER_REVIEW/APPROVED/ACTIVE/SUSPENDED -> REVOKED) | PermitOfficer, RefugeManager |
| POST | `/refuge/management-units/{id}/treatments` | Schedule a habitat treatment window on a unit (starts SCHEDULED) | Biologist, RefugeManager |
| GET | `/refuge/management-units/{id}/treatments` | List treatments on a unit | RefugeManager, Biologist, PermitOfficer, VolunteerCoordinator, LawEnforcementOfficer, StateAgencyPartner |
| POST | `/refuge/treatments/{id}/start` | Begin execution of a window-open treatment (WINDOW_OPEN -> IN_PROGRESS) | Biologist, RefugeManager |
| POST | `/refuge/treatments/{id}/complete` | Complete a treatment (IN_PROGRESS -> COMPLETED); recomputes unit habitat scores | Biologist, RefugeManager |
| POST | `/refuge/management-units/{id}/closures` | Schedule a facility closure on a unit (starts SCHEDULED) | Biologist, RefugeManager |
| GET | `/refuge/management-units/{id}/closures` | List closures on a unit | RefugeManager, Biologist, PermitOfficer, VolunteerCoordinator, LawEnforcementOfficer, StateAgencyPartner |
| POST | `/refuge/closures/{id}/activate` | Activate a scheduled closure (SCHEDULED -> ACTIVE); fires program, assignment, and permit cascades | Biologist, RefugeManager |
| POST | `/refuge/closures/{id}/lift` | Lift an active closure (ACTIVE -> LIFTED); reinstates or expires pinned permits | Biologist, RefugeManager |
| POST | `/refuge/management-units/{id}/programs` | Schedule an interpretive program (starts SCHEDULED) | VolunteerCoordinator, RefugeManager |
| GET | `/refuge/management-units/{id}/programs` | List programs on a unit | VolunteerCoordinator, RefugeManager, Anonymous |
| POST | `/refuge/volunteers` | Register a volunteer (background_status PENDING) | Anonymous |
| POST | `/refuge/volunteers/{id}/clear-background` | Clear or renew a volunteer's background check (PENDING/EXPIRED -> CLEARED) | VolunteerCoordinator, RefugeManager |
| POST | `/refuge/programs/{id}/assignments` | Assign a volunteer to a program (starts ACTIVE) | VolunteerCoordinator, RefugeManager |
| GET | `/refuge/assignments/{id}` | Read one assignment | VolunteerCoordinator, RefugeManager, Volunteer |
| GET | `/refuge/assignments` | List assignments with optional filters | VolunteerCoordinator, RefugeManager, Volunteer |
| POST | `/refuge/management-units/{id}/grazing-offerings` | Post a cooperative grazing offering (starts OPEN) | Biologist, RefugeManager |
| GET | `/refuge/management-units/{id}/grazing-offerings` | List offerings on a unit | Biologist, RefugeManager, Cooperator |
| GET | `/refuge/grazing-offerings/{id}` | Read one offering | Biologist, RefugeManager, Cooperator |
| POST | `/refuge/grazing-offerings/{id}/bids` | Submit a cooperator bid on an OPEN offering | Cooperator |
| GET | `/refuge/grazing-offerings/{id}/bids` | List bids on an offering | Biologist, RefugeManager, Cooperator |
| POST | `/refuge/grazing-offerings/{id}/close-and-select` | Close bidding and select the participant; creates the agreement or expires the offering | RefugeManager |
| GET | `/refuge/cooperative-agreements/{id}` | Read one cooperative agreement | RefugeManager, Biologist, Cooperator |
| GET | `/refuge/cooperative-agreements` | List cooperative agreements with optional filters | RefugeManager, Biologist, Cooperator |
| POST | `/refuge/cooperative-agreements/{id}/assess` | Record one period's cost-share assessment (OCC-guarded) | Biologist, RefugeManager |
| POST | `/refuge/cooperative-agreements/{id}/ledger-entries` | Record a PAYMENT (owning Cooperator) or REFUND (RefugeManager) ledger entry | Cooperator, RefugeManager |
| POST | `/refuge/cooperative-agreements/{id}/complete` | Complete an agreement at zero balance (ACTIVE -> COMPLETED) | RefugeManager |
| POST | `/refuge/citations` | Issue a citation against a permit or an agreement (exactly one subject) | LawEnforcementOfficer, RefugeManager |
| GET | `/refuge/citations/{id}` | Read one citation | LawEnforcementOfficer, RefugeManager, PermitOfficer |
| GET | `/refuge/citations` | List citations with optional filters | LawEnforcementOfficer, RefugeManager, PermitOfficer |
| POST | `/refuge/citations/{id}/void` | Void an issued citation (ISSUED -> VOIDED); restores agreement points | LawEnforcementOfficer, RefugeManager |
| POST | `/refuge/management-units/{id}/population-objectives` | Set an annual population objective for a species on a unit | StateAgencyPartner, RefugeManager |
| GET | `/refuge/management-units/{id}/population-objectives` | List population objectives on a unit | RefugeManager, Biologist, PermitOfficer, VolunteerCoordinator, LawEnforcementOfficer, StateAgencyPartner |
| POST | `/refuge/population-objectives/{id}/surveys` | Record a survey count; recomputes AT_TARGET / BELOW_TARGET | StateAgencyPartner, RefugeManager |
| POST | `/_clock/set_current_utc` | Advance the logical clock; fires the five pinned auto-transition classes in order | RefugeManager |

## 5. Error Code Catalogue

The catalogue below is the complete set of machine-readable error identifiers the API returns. Trigger conditions are deliberately not repeated here; each error's conditions are defined in the workflow narratives of §3 and the validation ordering of §2.6, whose first-failure-wins rule decides which identifier a multiply-invalid request receives.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_NESTING_BLACKOUT` | 422 Unprocessable Entity |
| `ERR_POSTURE_CLOSED` | 422 Unprocessable Entity |
| `ERR_DETERMINATION_NOT_FINAL` | 422 Unprocessable Entity |
| `ERR_USE_INCOMPATIBLE` | 422 Unprocessable Entity |
| `ERR_VOLUNTEER_NOT_CLEARED` | 422 Unprocessable Entity |
| `ERR_USE_TYPE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_BID` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_ASSIGNMENT` | 422 Unprocessable Entity |
| `ERR_PROGRAM_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_COMMERCIAL_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_UNRESOLVED_COMMENTS` | 422 Unprocessable Entity |
| `ERR_DATE_RANGE_INVALID` | 422 Unprocessable Entity |
| `ERR_WINDOW_IN_PAST` | 422 Unprocessable Entity |
| `ERR_TREATMENT_WINDOW_OVERLAP` | 422 Unprocessable Entity |
| `ERR_PAYMENT_AMOUNT_MISMATCH` | 402 Payment Required |
| `ERR_REFUND_EXCEEDS_PAID` | 422 Unprocessable Entity |
| `ERR_OUTSTANDING_BALANCE` | 422 Unprocessable Entity |
| `ERR_OVERPAYMENT` | 422 Unprocessable Entity |
