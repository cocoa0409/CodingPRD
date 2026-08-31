# Lockbox Property Access API — Product Requirements Document

## 1. Introduction

Electronic lockboxes are the quiet load-bearing infrastructure of residential real estate. A REALTOR association buys a few thousand of them, hands them out to its licensed members, and from that moment every showing, inspection, appraisal and contractor visit in the jurisdiction depends on a small metal box bolted to a front door behaving correctly. When the system around those boxes is weak, the failures are not abstract: a suspended member still opens doors, a contractor with lapsed liability insurance walks into an occupied home, a box stays on a property for six weeks after closing and nobody bills for it, and when a homeowner reports a theft the association discovers it cannot reconstruct who touched the box or when.

This document specifies the server that removes those failure modes. It is a single API covering lockbox inventory and assignment, credential issuance tied to membership standing, temporary code generation for one-day member access and contractor windows, the immutable access log that the hardware writes into, post-incident audit reviews over that log, loss and theft handling with replacement billing, and the removal-at-closing workflow that determines whether the association hits its board-published recovery target. Twelve resource families cooperate here, and almost every interesting rule in the system is a rule about how a change in one of them propagates into the others — suspending a member silently revokes their outstanding access codes and cancels the showings those codes were supposed to enable; reporting a box stolen simultaneously bills the holder, orphans the listing, and tightens the association's operating posture for everyone.

Two design commitments run through everything that follows. First, **money and safety decisions are never approximate**: every charge is computed by a pinned formula with a pinned rounding order, and every gate that could put a person inside a house they should not enter is evaluated at a fixed point in a fixed ladder. Second, **the audit trail is evidence**, not telemetry: access events are append-only, the server — never the device — decides whether an attempt was granted, and once an auditor locks evidence over a window those events belong to that review until it is deliberately reopened.

## 2. Global Specifications & System-Wide Principles

### 2.1. Actors, Identity and Role-Based Access Control

Every request to this API carries two headers: `X-User-ID`, identifying the caller, and `X-User-Role`, naming the capability set the caller is acting under. If either header is absent or present but empty, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before anything else is examined. If both headers are present but the role is not one of the four recognised names, or is a recognised name that the addressed endpoint does not admit, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The four roles are `AssociationAdmin`, `Member`, `SecurityAuditor` and `LockboxDevice`, spelled exactly so.

An `AssociationAdmin` is association staff. This role owns inventory intake, membership administration, credential issuance, grant approval and denial, every money action on a charge, the logical clock, and the periodic compliance checkpoint. When `X-User-Role` is `AssociationAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it, but it never compares it to any entity's `id`, and administrators are consequently exempt from every ownership check in the system. An `AssociationAdmin` may never open or close an incident review.

A `Member` is a licensed keyholder agent — the person who physically holds boxes, hangs them on their own listings, issues temporary codes and books showings. When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member` record; ownership checks on any resource that references a `Member` compare the resource's foreign-key field to `X-User-ID`. Concretely, a `Member` may act on a listing only when its `listing_agent_id` equals `X-User-ID`, on a lockbox only when its `assigned_member_id` equals `X-User-ID`, on a placement only when its `placed_by_member_id` equals `X-User-ID`, and on a showing only when its `showing_member_id` equals `X-User-ID`. A violation of any of these is `ERR_NOT_RESOURCE_OWNER` (HTTP 403). Members are the only callers subject to the daily temporary-code quota. Members can never approve or deny a grant, never touch a billing charge, and never audit.

A `SecurityAuditor` is the association's independent compliance officer, deliberately segregated from operations. When `X-User-Role` is `SecurityAuditor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it as `opened_by_user_id` when a review is created and as `closed_by_user_id` when a review is closed, but does not compare it to any entity's `id`. Auditors open, lock, close and reopen incident reviews and may read broadly, but may not mutate inventory, membership, credentials, grants or money. Because the same person must not both raise and dispose of an allegation, the auditor closing a review must not be the auditor recorded in `opened_by_user_id`; when they are the same, the close is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

A `LockboxDevice` is the hardware gateway itself. When `X-User-Role` is `LockboxDevice`, `X-User-ID` is an opaque device identifier not tied to any persisted entity; it is never compared to an entity's `id`. Its sole capability is appending an access attempt to the audit log, and it has no read access at all.

Read endpoints are broadly shared. `AssociationAdmin`, `Member` and `SecurityAuditor` may all read associations, members, contractors, lockboxes, listings, placements, credentials, grants, showings, access events and billing charges. Incident reviews are readable by `AssociationAdmin` and `SecurityAuditor` only. The recovery summary is readable by `AssociationAdmin` and `SecurityAuditor` only. The endpoint table in §4 is authoritative for which roles reach which operation.

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

Every list endpoint accepts two optional query parameters. `limit` controls page size: it defaults to 10 when omitted, may be no smaller than 1, and may be no larger than 100. `offset` controls how many rows are skipped before the page begins: it defaults to 0 and may be no smaller than 0. A `limit` outside the inclusive range of 1 through 100, or a negative `offset`, is a malformed request and is rejected with `ERR_INVALID_REQUEST` (HTTP 422).

Unless a subsection below states otherwise, list results are ordered by `created_at` ascending. The `meta` block of a list response carries `limit` and `offset` as they were applied, `total_count` as the number of rows matching the filters before the page window was applied, and `has_more` as a boolean that is true when rows remain beyond the current page.

### 2.4. Resource Identity, Timestamps and the Logical Clock

Every resource this API mints is identified by a server-generated UUID exposed as `id`. Identifiers carry no type prefix — a lockbox `id` and a listing `id` are indistinguishable by shape, and clients must not attempt to infer a resource's family from its identifier. Clients never supply an `id` on creation.

Most resources also carry `created_at` and `updated_at`, both ISO 8601 UTC timestamps with three fractional-second digits, and `version`, an integer that begins at 1 when the resource is created and increases by exactly 1 on every mutation the server accepts. Access-log entries — the `AccessEvent` family — are the one exception and are deliberately austere: an access event carries `id` and `created_at` only. It has no `updated_at` and no `version`, because it is append-only evidence and is never modified after it is written. The stamping of `incident_review_id` and the derivation of `matched_appointment_id` on an event are the server completing the record at write time and during evidence lock, not a client-visible mutation of a versioned resource.

Time in this system is a **logical clock**, not wall-clock time. Before any caller sets it, the clock reads exactly `2026-08-01T00:00:00Z`, and it never falls back to the host's real time. An administrator may advance or rewind it by supplying a `to_iso8601` instant; the response reports the resulting `current_utc`. Setting the clock mutates no entity — a credential whose `expires_at` has just fallen into the past does not become `EXPIRED` merely because the clock moved. Expiries, delinquency and the consequences that flow from them are realised only when the compliance checkpoint next runs, or when some other operation reads the clock as part of its own decision.

Path identifiers are validated left to right. Where a URL nests one identifier inside another's collection, the outer identifier is resolved first, and the first identifier that fails to resolve determines the 404 that is returned: `ERR_ASSOCIATION_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_CONTRACTOR_NOT_FOUND`, `ERR_LOCKBOX_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`, `ERR_PLACEMENT_NOT_FOUND`, `ERR_CREDENTIAL_NOT_FOUND`, `ERR_GRANT_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`, `ERR_REVIEW_NOT_FOUND` or `ERR_CHARGE_NOT_FOUND`, each carrying HTTP 404. The same catalogue governs foreign keys supplied in a request body: each is resolved in the order the endpoint declares its inputs, and the first unresolvable reference produces the corresponding not-found error. A `supersedes_grant_id` that does not resolve yields `ERR_GRANT_NOT_FOUND`; a `listing_agent_id` or `showing_member_id` that does not resolve yields `ERR_MEMBER_NOT_FOUND`.

### 2.5. Stale-View Rejection on Parent Records

Several operations in this system are legitimately repeatable, in the sense that performing them twice is meaningful rather than nonsensical — issuing a second credential to the same member supersedes the first, reassigning a lockbox supersedes the prior holder, approving a second grant on the same listing supersedes an earlier one. Repeatability is exactly what makes a stale client view dangerous: without a guard, a client acting on information it read before someone else's write would silently overwrite a decision it never saw. The system therefore requires the client to declare which revision of the governing parent record it believes it is acting on.

Three write operations are governed by an explicit optimistic-concurrency rule:

- **Requesting an access grant.** A `POST /access-grants` request must carry `expected_listing_version` as a required field, holding the client's last observed `version` of the listing named by `listing_id`. If it does not equal the listing's current `version` — for example because another writer has already had a grant approved on that listing, which advances the listing's version — the create is rejected with `ERR_STALE_VERSION` (HTTP 412).
- **Issuing an access credential.** A `POST /access-credentials` request must carry `expected_member_version` as a required field, holding the client's last observed `version` of the member named by `member_id`. If it does not equal that member's current `version`, the issuance is rejected with `ERR_STALE_VERSION` (HTTP 412). This is what prevents a client that has not observed a prior issuance from unknowingly triggering the credential-cap supersede against a credential set it has never seen.
- **Driving a lockbox state action.** A `POST /lockboxes/{lockboxId}/state` request must carry `expected_lockbox_version` as a required field, holding the client's last observed `version` of the addressed lockbox. If it does not equal the lockbox's current `version`, the action is rejected with `ERR_STALE_VERSION` (HTTP 412). Because reassignment is a legitimate self-action that supersedes the prior holder, this check is the only thing distinguishing a deliberate reassignment from one issued against an outdated view of the unit.

Beyond those three, every action endpoint that drives a state machine likewise requires the expected version of the entity it addresses, and a mismatch is the same `ERR_STALE_VERSION` (HTTP 412). The field names are `expected_member_version` on member events, `expected_contractor_version` on contractor actions, `expected_listing_version` on listing actions, `expected_placement_version` on placement actions, `expected_credential_version` on credential actions, `expected_grant_version` on grant actions, `expected_appointment_version` on showing actions, `expected_review_version` on incident-review actions and `expected_charge_version` on charge actions. Endpoints not named above — plain creates such as members, contractors, lockboxes, listings, placements, showings and incident reviews, the device ingress, the clock, the compliance checkpoint and every read — take no version field at all.

### 2.6. The Order in Which a Request Is Rejected

Every endpoint that drives a state machine names the operation it wants performed in a required `action` field; member standing is the single exception, naming it `event_type` instead. When a request violates several rules at once, exactly one error comes back, and which one is not a matter of implementation convenience. Checks are evaluated in a strict ascending order and the first failure wins. The full ladder, in order, is:

1. **Authentication** — both headers present and non-empty, else `ERR_UNAUTHENTICATED`.
2. **Role admission** — the role is one of the four recognised names and is admitted by the endpoint, else `ERR_FORBIDDEN_ROLE`.
3. **Path existence** (priority 10) — every identifier in the URL resolves, left to right, else the matching not-found error.
4. **Body foreign-key existence** (priority 15) — every foreign key in the body resolves, in the order the endpoint declares its inputs, else the matching not-found error. This applies to member creation, contractor creation, lockbox intake, listing creation, placement creation, credential issuance, grant requests, showing requests, incident-review creation, device access attempts and lockbox state actions.
5. **Request shape** (priority 20) — required fields present, enum members legal, integers inside their declared bounds, ISO 8601 timestamps parseable, `limit` inside 1 through 100 and `offset` at least 0, else `ERR_INVALID_REQUEST`.
6. **Member ownership** (priority 25) — the ownership comparisons of §2.1, else `ERR_NOT_RESOURCE_OWNER`. This guards listing creation, listing actions, lockbox actions, placement creation, placement actions, grant requests, grant actions, showing requests and showing actions.
7. **Segregation of duties** (priority 30) — on closing an incident review only, else `ERR_SEGREGATION_OF_DUTIES`.
8. **Stale parent version** (priority 35) — every supplied expected-version field matches, else `ERR_STALE_VERSION`.
9. **Declared transition exists** (priority 40) — the addressed entity's current state admits the requested action, else `ERR_INVALID_STATE`.
10. **Referenced member eligibility** (priority 42) — else `ERR_MEMBER_NOT_ELIGIBLE`.
11. **Terminal lockdown** (priority 45) — else `ERR_ENTITY_TERMINAL`.
12. **Physical-safety gate** (priority 50) — else `ERR_LOCKBOX_MISSING` or `ERR_CONTRACTOR_INSURANCE_EXPIRED`.
13. **Association posture gate** (priority 55) — else `ERR_ASSOCIATION_FROZEN` or `ERR_ASSOCIATION_RESTRICTED`.
14. **Window geometry** (priority 60) — else `ERR_INVALID_WINDOW`, `ERR_GRANT_WINDOW_TOO_LONG`, `ERR_GRANT_WINDOW_CONFLICT` or `ERR_SHOWING_CAPACITY_EXCEEDED`.
15. **Quota and uniqueness** (priority 65) — else `ERR_TEMP_CODE_LIMIT_REACHED`, `ERR_DUPLICATE_SERIAL` or `ERR_DUPLICATE_MLS_NUMBER`.
16. **Linkage integrity** (priority 70) — else `ERR_LOCKBOX_NOT_ON_LISTING`, `ERR_SHOWING_NO_LOCKBOX` or `ERR_PLACEMENT_ALREADY_ACTIVE`.
17. **Member solvency** (priority 75) — else `ERR_MEMBER_BALANCE_DELINQUENT`.
18. **Charge adjustability** (priority 80) — else `ERR_CHARGE_NOT_ADJUSTABLE`.
19. **Evidence immutability** (priority 85) — else `ERR_EVIDENCE_LOCKED`.
20. **Recovery window** (priority 90) — else `ERR_RECOVERY_WINDOW_CLOSED`.

Two consequences of this ordering deserve calling out because they are easy to get backwards. First, when a placement is being created the *addressed* entity for the transition check at step 9 is the lockbox, not the listing: a unit sitting in `IN_STOCK`, `MISSING`, `QUARANTINE` or `RETIRED` fails there with `ERR_INVALID_STATE`, whereas a unit that is already `PLACED` passes step 9 and is instead caught later at step 16 with `ERR_PLACEMENT_ALREADY_ACTIVE`. Second, the transition check at step 9 outranks evidence immutability at step 19: locking evidence on a review that is already `EVIDENCE_LOCKED` returns `ERR_INVALID_STATE`, not `ERR_EVIDENCE_LOCKED`.

Terminal lockdown at step 11 means that a `Lockbox` in `RETIRED`, a `Listing` in `CLOSED` or `WITHDRAWN`, a `LockboxPlacement` in `REMOVED`, an `AccessCredential` in `REVOKED` or `EXPIRED`, an `AccessGrant` in `DENIED`, `REVOKED`, `EXPIRED` or `CONSUMED`, a `ShowingAppointment` in `COMPLETED`, `CANCELLED` or `NO_SHOW`, a `BillingCharge` in `PAID`, `WAIVED` or `VOID`, and a `Member` in `TERMINATED` accept no further action of any kind.

### 2.7. Money, Rounding and the Member Statement

All monetary amounts in this system are integer cent counts. Wherever a computation produces a fractional cent, the result is rounded **half up** to a whole cent — a value ending in exactly half a cent rounds away from zero. Percentages and rates that are reported rather than charged — the recovery rate, the incident risk score — are decimal numbers rounded **half up to two decimal places**.

A member's `outstanding_balance_cents` is not a stored ledger; it is recomputed from that member's charges every time a charge is created, invoiced, paid, waived or voided. Only charges in `PENDING` or `INVOICED` are in the open set; `PAID`, `WAIVED` and `VOID` lines leave the open set immediately and stop contributing. Each open line is grossed up by an administration surcharge of 2.5 percent of its `amount_cents`, and **the rounding order is pinned: the grossed-up figure is rounded half up to a whole cent for each line individually, and only then are the rounded line totals added together.** Summing the raw grossed-up amounts and rounding once at the end is explicitly the wrong reading — two open lines of 1500 cents each yield 3076 under the rule as written and 3075 under the wrong one. Because every line is rounded before it is added, the order in which lines are summed does not affect the result.

Money never moves silently. A charge is created by the operation that earns it — a loss report, a delinquency accrual during the compliance checkpoint, or an over-cap temporary code — and thereafter only an `AssociationAdmin` may act on it.

### 2.8. Association Posture

Each association carries a computed `posture` of `OPEN`, `RESTRICTED` or `FROZEN` that acts as a system-wide brake reflecting how much hardware the association has lost control of. It is recomputed at the end of every lockbox transition, every placement transition and every compliance checkpoint.

The computation uses two live counts over the association's own inventory. The `active_placement_count` is the number of placements, reached through lockboxes belonging to this association, whose `placement_status` is `PLACED`, `REMOVAL_DUE` or `DELINQUENT`. The `delinquent_placement_count` is the number of those whose `placement_status` is `DELINQUENT`. The delinquent ratio is the delinquent count divided by the active placement count, except that the divisor is treated as 1 whenever the active placement count is 0, so an association with no active placements has a ratio of 0 rather than an undefined value. No rounding is applied to the ratio before it is compared.

The two tests are then applied in order, and the first match wins. If `missing_box_count` is at least 3, or the delinquent ratio is at least 0.50, the posture is `FROZEN`. Otherwise, if `missing_box_count` is at least 1, or the delinquent ratio is at least 0.25, the posture is `RESTRICTED`. Otherwise the posture is `OPEN`.

Posture bites at exactly two places. A `FROZEN` association may not have new placements created and may not have grants created or approved; the rejection is `ERR_ASSOCIATION_FROZEN` (HTTP 409). A `RESTRICTED` association blocks only grants whose `grant_type` is `CONTRACTOR_WINDOW`, whether at creation or at approval, with `ERR_ASSOCIATION_RESTRICTED` (HTTP 409); one-day member codes and inspector codes continue to flow, and placements are unaffected by `RESTRICTED`.

### 2.9. Cascades and Compensation

Several operations in this system are multi-hop: a single accepted request changes an entity, and that change forces changes in other entities, which force further changes in turn. The hops are not optional and are not deferred — they complete inside the originating request, and each entity they touch has its own `version` advanced and its own `updated_at` refreshed exactly as if it had been acted on directly.

Three cascades share the same shape, running credential or placement, then grant, then appointment: suspending or expiring a member, reporting a placed lockbox lost or stolen, and closing or withdrawing a listing. In each case the third hop cancels only future showings — a `ShowingAppointment` whose `window_start` is strictly later than the current logical clock — and stamps `cancel_reason` as `ACCESS_LOST` to distinguish it from a human cancellation, which stamps `AGENT_CANCELLED`.

Two compensations run the other way, and both are exact rather than approximate. Reinstating a suspended member restores precisely the credentials the suspension took down and no others, returning that member's `active_credential_count` to the value it held before the suspension. Recovering a missing lockbox voids the replacement charge the loss report raised, returning that member's `outstanding_balance_cents` to its pre-report value. What compensation does **not** do is equally load-bearing: revoked grants and cancelled showings are never resurrected, and the association's `unplaced_inventory_count` is conserved across the place-and-remove cycle — a placement removes one unit from unplaced inventory and its removal returns exactly one.

### 2.10. Window Arithmetic

Three different interval conventions coexist in this system, and confusing them produces wrong answers that look plausible, so each is pinned explicitly.

**Access-grant windows are half-open.** A grant covers the instant `window_start` and every instant up to but not including `window_end`. When testing whether two approved grants collide on the same physical unit, each grant is treated as occupying its window plus a mandatory service buffer of `grant_buffer_minutes` minutes appended to the end — so the occupied span runs from `window_start` inclusive to `window_end` plus the buffer, exclusive. Two occupied spans collide when the first begins strictly before the second ends and the second begins strictly before the first ends. Because both comparisons are strict, a window that begins exactly at another's buffered end does not collide.

**Showing windows are closed.** A showing covers both `window_start` and `window_end` and everything between them. Two showings overlap when the first begins at or before the second ends and the second begins at or before the first ends — so an appointment starting at the exact minute another ends *does* count as an overlap.

**Date-valued fields resolve to the end of their day where a deadline is being tested and to the start of their day where a deadline is being set.** A member's `dues_paid_through`, and a contractor's `insurance_expires_on`, are ISO dates in `YYYY-MM-DD` form; when compared against an instant they are read at `23:59:59.999Z` on that date. A placement's `removal_deadline`, by contrast, is set at `00:00:00.000Z` on the computed day.
## 3. Business Logic & Workflows

### 3.1. Standing Up an Association, Its Policy Dials and Its Hardware

Everything in this system hangs off an association. Registering one records its `name` and its `jurisdiction_code` — a state-and-county string such as `WA-KING` — together with the policy dials the board has voted on. Those dials are all optional at registration and each has a published default: `temp_code_daily_limit` defaults to 3 and caps how many one-day member codes a single member may self-issue in a UTC calendar day; `temp_code_overage_fee_cents` defaults to 500 and is what staff pay to push a code past that cap on a member's behalf; `removal_grace_days` defaults to 3 whole days and is the breathing room a listing agent gets to retrieve a box after a deal closes; `late_removal_daily_fee_cents` defaults to 1500 and `late_removal_cap_cents` defaults to 15000, together bounding the penalty for leaving a box behind; `credential_cap_per_member` defaults to 2 and bounds how many active keyholder credentials one member may hold; `grant_buffer_minutes` defaults to 15 and is the service buffer appended to every approved access window; and `recovery_target_pct` defaults to 95.00 and is the board's aspiration for on-time box recovery. That last dial is reported and never enforced — no operation in this system fails because the recovery rate sits below the target. The `temp_code_daily_limit` may legitimately be set to 0, which means members may issue no self-service one-day codes at all.

A freshly registered association starts with `posture` set to `OPEN`, `recovery_rate_pct` set to 0.00, and every counter at zero. Those counters are live derivations, not stored tallies, and reading an association returns them at their current values. The `lockbox_total_count` is the number of that association's lockboxes not in `RETIRED`. The `boxes_in_field_count` is the number in `ASSIGNED` or `PLACED`. The `unplaced_inventory_count` is the number in `IN_STOCK` or `ASSIGNED` — the pool of hardware the association can still deploy. The `missing_box_count` is the number in `MISSING`. Alongside them sit `active_placement_count` and `delinquent_placement_count`, defined in §2.8, and `recovery_rate_pct`, which reports the closing-cohort recovery figure over the ninety days ending at the current logical clock.

Hardware enters inventory one unit at a time. Intake records the owning `association_id`, the hardware `serial_number`, the `model` — either `LB_STD` or `LB_PRO` — the board-published `replacement_cost_cents`, which must be greater than zero, and `in_service_since`, the ISO date the unit entered service and the origin of the depreciation clock. Serial numbers must be unique within an association; a collision is `ERR_DUPLICATE_SERIAL`. The unit lands in `IN_STOCK`, raising both `lockbox_total_count` and `unplaced_inventory_count` by one, with `assigned_member_id` and `current_listing_id` both empty.

Vendors are registered separately. A contractor record carries its `association_id`, its `company_name` and `insurance_expires_on`, the ISO date on which the vendor's liability coverage lapses, and begins life with `status` set to `ACTIVE`. Staff may move a vendor to `SUSPENDED` and back to `ACTIVE` at will; neither state is terminal, and the pair forms a cycle `ACTIVE → SUSPENDED → ACTIVE`. Suspending a vendor does **not** revoke access windows that were already approved for it — the association's position is that a window already granted has already been relied upon, and pulling it mid-visit is worse than letting it run out. Suspension therefore only blocks future approvals, through the safety gate described in §3.5.

### 3.2. The Membership Lifecycle and What Suspension Costs

Enrolling a member records their `association_id`, `full_name`, `email` — which must be unique within the association — and `dues_paid_through`, the ISO date through which association dues are paid. A member is conceptually born in `PENDING`, but never observably rests there: the system resolves the standing inside the creating request. If `dues_paid_through`, read at the end of that date, is later than the current logical clock, the member is created with `membership_status` of `ACTIVE`; otherwise they are created `EXPIRED`. Either way this is part of creation rather than a mutation, so the new member's `version` remains 1. New members start with `active_credential_count` of 0 and `outstanding_balance_cents` of 0.

Thereafter an `AssociationAdmin` drives standing through membership events, each naming an `event_type` and optionally a free-text `reason`. Placing an `ACTIVE` member on probation moves them to `PROBATION`; reinstating a member in `PROBATION` returns them to `ACTIVE`. Probation is deliberately toothless with respect to hardware: a member in `PROBATION` keeps every credential `ACTIVE`, keeps their boxes, and can still work. It is a warning, not a sanction.

Suspension is the sanction, and it is expensive. A member in `ACTIVE` or `PROBATION` may be moved to `SUSPENDED`, and that single event runs three hops. First, every credential belonging to that member that is currently `ACTIVE` becomes `SUSPENDED`, and each such credential is stamped `suspended_by_cascade` as true so the system can later tell a cascade casualty from a credential an administrator suspended deliberately; the member's `active_credential_count` is recomputed. Second — precisely because those credentials have left `ACTIVE` — every grant the member issued that still sits in `REQUESTED` or `APPROVED` becomes `REVOKED`. Third — precisely because those grants were revoked — every showing where the member is the attending agent that is still in `REQUESTED` or `CONFIRMED` and whose `window_start` is strictly after the current logical clock becomes `CANCELLED` with `cancel_reason` of `ACCESS_LOST`. Showings already under way or already past are left alone.

Reinstatement from `SUSPENDED` compensates exactly and asymmetrically. Every credential belonging to that member that is `SUSPENDED`, carries `suspended_by_cascade` as true, and whose `expires_at` is still in the future returns to `ACTIVE` with `suspended_by_cascade` cleared to false; the member's `active_credential_count` is recomputed and must land back on its pre-suspension value. Credentials an administrator had suspended by hand stay `SUSPENDED`, and credentials whose `expires_at` has passed in the meantime stay `SUSPENDED` too. Revoked grants and cancelled showings are never restored — the codes were burned and the showings were told they were off.

Expiry is the softer sibling of suspension. A member in `ACTIVE` or `PROBATION` moves to `EXPIRED` either because staff say so or because the compliance checkpoint finds `dues_paid_through`, read at the end of that date, has fallen before the current logical clock. Expiry runs only the first hop: every `ACTIVE` credential becomes `SUSPENDED` with `suspended_by_cascade` set to true. Grants and showings are untouched. Renewing an `EXPIRED` member requires a `paid_through_date` that, read at the end of that date, is later than the current logical clock; the renewal writes it into `dues_paid_through`, returns the member to `ACTIVE`, and restores the same cascade-suspended, not-yet-expired credentials that reinstatement restores.

Termination is the one-way door. A member in `ACTIVE`, `PROBATION`, `SUSPENDED` or `EXPIRED` may be moved to `TERMINATED`, but only if they are holding no hardware — no lockbox may name them in `assigned_member_id` while sitting in `ASSIGNED`, `PLACED` or `MISSING`. A member holding a missing box cannot be terminated out of their liability. Termination revokes every credential of theirs not already `REVOKED` and drives `active_credential_count` to 0. `TERMINATED` is terminal in the strict sense of §2.6: nothing further may be done to that member.

Every one of these membership events requires `expected_member_version` and advances the member's `version` by one on success. Members can be listed and filtered by `association_id` and `membership_status`.

### 3.3. Keyholder Credentials

A credential is the durable key a member carries — either the phone application, recorded as `credential_type` `KEY_APP`, or a physical key fob, recorded as `KEY_FOB`. Issuance names the `member_id` it belongs to, the `credential_type`, and `expires_at`, the UTC instant at which the credential lapses. It arrives in `PENDING_ACTIVATION` and does nothing until an administrator activates it.

Issuance is where the association's credential cap is enforced, and it is enforced by superseding rather than by refusing. If, at the moment of issuance, the member already holds a number of credentials in `ACTIVE` equal to `credential_cap_per_member`, the **earliest-created** of those active credentials — ordered by `created_at` ascending — is revoked to make room, and that revoked credential is stamped with a `supersede_reason` of `CREDENTIAL_CAP_SUPERSEDE`. The member's `active_credential_count` is recomputed accordingly. Because issuance advances the owning member's `version`, and because it is the member record whose credential set has changed, this is the operation guarded by the member stale-view rule of §2.5.

Activation moves a credential from `PENDING_ACTIVATION` to `ACTIVE`. It requires that the owning member's `membership_status` be `ACTIVE` or `PROBATION`, failing with `ERR_MEMBER_NOT_ELIGIBLE` otherwise, and that `expires_at` still be later than the current logical clock, failing with `ERR_INVALID_WINDOW` otherwise. On success the member's `active_credential_count` rises by one.

An administrator may suspend an `ACTIVE` credential, which lowers `active_credential_count` by one and leaves `suspended_by_cascade` false because the suspension was deliberate. Reinstating a `SUSPENDED` credential returns it to `ACTIVE`, sets `suspended_by_cascade` to false, and raises `active_credential_count` by one — but only when the owning member is `ACTIVE` or `PROBATION`, failing `ERR_MEMBER_NOT_ELIGIBLE` otherwise, and only when `expires_at` is still ahead of the clock. This gives the cycle `ACTIVE → SUSPENDED → ACTIVE`.

Revocation is permanent. A credential in `PENDING_ACTIVATION`, `ACTIVE` or `SUSPENDED` may be revoked outright, whether by explicit action, by the member-termination cascade, or by the credential-cap supersede; `active_credential_count` is recomputed, which means revoking from `ACTIVE` lowers it while revoking from `SUSPENDED` leaves it unchanged. Expiry is the other terminal end: the compliance checkpoint moves any credential in `ACTIVE` or `SUSPENDED` whose `expires_at` has reached or passed the current logical clock into `EXPIRED`, recomputing `active_credential_count` where the credential had been `ACTIVE`. Credentials may be listed and filtered by `member_id`, `status` and `credential_type`.
### 3.4. From Inventory to Front Door: Assignment, Placement and Removal at Closing

A box in `IN_STOCK` is inert. Assigning it to a keyholder moves it to `ASSIGNED` and writes the supplied `member_id` into `assigned_member_id`. Assignment is administrator-only and gated twice on the receiving member: their `membership_status` must be `ACTIVE` or `PROBATION`, else `ERR_MEMBER_NOT_ELIGIBLE`, and their `outstanding_balance_cents` must be exactly zero, else `ERR_MEMBER_BALANCE_DELINQUENT` (HTTP 402) — the association will not hand more hardware to someone who has not settled for the last piece. The member must belong to the same association as the box. Assignment raises `boxes_in_field_count` by one and leaves `unplaced_inventory_count` untouched, since an assigned box is still deployable inventory.

Reassignment is a self-loop: an already-`ASSIGNED` box may be assigned again to a *different* `member_id`, which supersedes the prior holder. The same eligibility and solvency checks apply, association counters do not move, and — as §2.5 explains — the stale-view check on the unit is the only thing separating a deliberate reassignment from one issued against an outdated view. Returning a box moves it from `ASSIGNED` back to `IN_STOCK`, clears `assigned_member_id`, and lowers `boxes_in_field_count` by one; it is refused unless no placement for that box is currently in `PLACED`, `REMOVAL_DUE` or `DELINQUENT`. A `Member` caller may only return a box they hold.

Listings are the other half of the pairing. Creating one records the `association_id`, the `listing_agent_id` naming the member who owns the listing, the `address_line` of the property, the `mls_number` — unique within the association, else `ERR_DUPLICATE_MLS_NUMBER` — and optionally `concurrent_showing_limit`, which defaults to 1 and must be at least 1. A listing opens in `ACTIVE`. Only the listing's agent, or an administrator, may act on it, and only the listing's agent may issue codes against it; placing a box on the listing, by contrast, carries no listing-agent ownership check at all — it is gated solely on the box's own holder as described below, so a `Member` who holds the unit may hang it on a listing another agent owns. Listings may be listed and filtered by `association_id`, `listing_agent_id` and `status`.

Hanging a box on a property creates a placement from a `lockbox_id` and a `listing_id`. The listing must be `ACTIVE` and must belong to the same association as the box; the box must be in `ASSIGNED`, and when the caller is a `Member` the box's `assigned_member_id` must be that member. A `FROZEN` association blocks the operation with `ERR_ASSOCIATION_FROZEN`. A box that already carries a placement in `PLACED`, `REMOVAL_DUE` or `DELINQUENT` is rejected with `ERR_PLACEMENT_ALREADY_ACTIVE`. On success the box moves `ASSIGNED → PLACED` with `current_listing_id` set to the listing, and a placement record is written with `placement_status` of `PLACED`, `billing_status` of `NONE`, `placed_at` at the current logical clock, and `placed_by_member_id` recorded — copied from `X-User-ID` when a `Member` places the box, and from the box's `assigned_member_id` when an administrator places it on the holder's behalf. The association's `unplaced_inventory_count` falls by one, `active_placement_count` rises by one, and `posture` is recomputed.

**A placement tracks two dimensions that move independently.** The `placement_status` dimension answers "where is the box?" and runs `PLACED`, `REMOVAL_DUE`, `DELINQUENT` and `REMOVED`. The `billing_status` dimension answers "did leaving it there cost money?" and runs `NONE`, `ACCRUED` and `SETTLED`. Neither constrains the other: a placement can be `DELINQUENT` with `billing_status` still `NONE` — that is the missing-box path, where a replacement charge is raised instead of a late-removal charge — and a placement can be `REMOVED` with `billing_status` still `ACCRUED`, because retrieving the box late does not undo a penalty already accrued.

When a listing goes under contract, its `status` moves `ACTIVE → UNDER_CONTRACT`, and nothing else happens at all: existing placements and grants are untouched, because the property is still being shown and inspected. If the deal falls through the listing reactivates, `UNDER_CONTRACT → ACTIVE`, giving the cycle `ACTIVE → UNDER_CONTRACT → ACTIVE`.

Closing is where the box has to come home. A listing in `UNDER_CONTRACT` closes with a supplied `close_date`, which is stored, and the transition runs the standard three hops. The placement on that listing sitting in `PLACED` moves to `REMOVAL_DUE`, and its `removal_deadline` is computed as `close_date` advanced by the association's `removal_grace_days` whole days, taken at `00:00:00.000Z` on the resulting day. Because that placement has entered `REMOVAL_DUE`, every grant on the listing still in `REQUESTED` or `APPROVED` becomes `REVOKED`; because those grants were revoked, every showing on the listing still in `REQUESTED` or `CONFIRMED` whose `window_start` is strictly after the current logical clock becomes `CANCELLED` with `cancel_reason` of `ACCESS_LOST`. The association's `recovery_rate_pct` is recomputed. Withdrawal behaves identically — a listing in `ACTIVE` or `UNDER_CONTRACT` may move to `WITHDRAWN`, running exactly the same three hops — with one difference: because no deal closed, the `removal_deadline` is anchored on the calendar date of the current logical clock advanced by `removal_grace_days` whole days, again at `00:00:00.000Z`. Both `CLOSED` and `WITHDRAWN` are terminal.

Recording physical removal is the placement's own action. It is accepted from `PLACED`, `REMOVAL_DUE` or `DELINQUENT`, and when the caller is a `Member` the placement's `placed_by_member_id` must be that member. Removal writes `removed_at` at the current logical clock and drives the box `PLACED → ASSIGNED` with `current_listing_id` cleared, returning one unit to `unplaced_inventory_count` and lowering `active_placement_count` by one; `delinquent_placement_count`, `recovery_rate_pct` and `posture` are all recomputed. The `on_time` flag is then true exactly when `removed_at` is set and either no `removal_deadline` was ever set or `removed_at` is at or before it. Removing from `PLACED` — an early retrieval before any deadline existed — is therefore always on time. Removing from `DELINQUENT` is never on time, lowers `delinquent_placement_count` by one, and leaves `billing_status` at `ACCRUED`: the penalty stands.

**The late-removal penalty.** When the compliance checkpoint finds a placement in `REMOVAL_DUE` whose `removal_deadline` is strictly before the current logical clock, it moves that placement to `DELINQUENT` and computes the penalty once, freezing it. The count of late days is the elapsed time from `removal_deadline` to the current logical clock expressed in days with any partial day rounded **up** to a whole day, floored at zero; that count is stored in `late_days`. The base component is the number of late days multiplied by the association's `late_removal_daily_fee_cents`, capped at the association's `late_removal_cap_cents` — whichever is smaller. A tier is then selected **from the base component alone**: base amounts of 4500 cents or less are tier `T1`, base amounts above 4500 cents and up to 10500 cents are tier `T2`, and base amounts above 10500 cents are tier `T3`. The administration fee percentage attached to those tiers is zero percent for `T1`, five percent for `T2` and ten percent for `T3`. The administration fee in cents is the base component multiplied by that percentage, rounded half up to a whole cent. The charge total is the base component plus the administration fee. Keying the tier on the total rather than on the base is the wrong reading and produces different money. The derivation is recorded in the charge's `basis` as a string of the form `base=7500 tier=T2 admin_fee=375`. Once frozen, `late_days` does not drift with the clock, and a placement already `DELINQUENT` is skipped by later checkpoints.

Alongside the delinquency the checkpoint moves the placement's `billing_status` from `NONE` to `ACCRUED` and writes a charge of `charge_type` `LATE_REMOVAL`, linked by `placement_id`, `lockbox_id` and the `member_id` taken from `placed_by_member_id`, in `PENDING`; the member's `outstanding_balance_cents` is recomputed. `delinquent_placement_count` rises by one and `posture` is recomputed. Later, when an administrator pays or waives that charge, the placement's `billing_status` moves `ACCRUED → SETTLED` without touching `placement_status`; when an administrator voids it, `billing_status` returns `ACCRUED → NONE` and the member's balance is recomputed. Placements may be listed and filtered by `lockbox_id`, `listing_id`, `placed_by_member_id`, `placement_status` and `billing_status`.
### 3.5. Temporary Codes: One-Day Members, Inspectors and Contractor Windows

Not everyone who needs to open a box carries a credential. A temporary access grant is the mechanism for everyone else, and it comes in three flavours recorded in `grant_type`. A `ONE_DAY_MEMBER` code lets a licensed agent without a standing credential in this association get in for a single day. An `INSPECTOR` code covers home inspectors, appraisers and photographers. A `CONTRACTOR_WINDOW` covers a vendor company doing scheduled work.

Requesting a grant names the `listing_id` it is issued against, the `lockbox_id` it will open, the `grant_type`, and the `window_start` and `window_end` bounding the access window. A `contractor_id` is **required** when the `grant_type` is `CONTRACTOR_WINDOW` and **forbidden** otherwise; supplying it for a one-day or inspector code, or omitting it for a contractor window, is `ERR_INVALID_REQUEST`. Optionally the request names `max_uses`, which defaults to 1 and must be at least 1, and `supersedes_grant_id`, pointing at an approved grant that this issuance is intended to replace. The request also carries `expected_listing_version`, per §2.5. The grant is written in `REQUESTED` with `issued_by_member_id` set — to `X-User-ID` when a `Member` requests it, and to the listing's `listing_agent_id` when an administrator requests it on the agent's behalf — and `uses_count` at 0. The listing's `version` advances by one.

Two structural checks run at request time. The named box must actually be on the named property: there must be a placement whose `placement_status` is `PLACED` joining that `lockbox_id` to that `listing_id`, else `ERR_LOCKBOX_NOT_ON_LISTING`. And a box in `MISSING` can back nothing, so a grant naming one is refused with `ERR_LOCKBOX_MISSING`.

**Window geometry is checked at request time.** The `window_start` must be strictly earlier than the `window_end`, else `ERR_INVALID_WINDOW`. Duration is capped by flavour: a `ONE_DAY_MEMBER` or `INSPECTOR` window may span at most twenty-four hours, and a `CONTRACTOR_WINDOW` may span at most seven days; exceeding the applicable cap is `ERR_GRANT_WINDOW_TOO_LONG`.

**The daily quota applies to members and only to members.** A member's `temp_codes_issued_today` counts the grants that member issued with `grant_type` of `ONE_DAY_MEMBER` whose status is anything other than `DENIED`, created on the same UTC calendar date as the current logical clock. Note carefully that a denial does not give the quota back — a member who burns their allowance on codes that staff then reject has still burned it. When a `Member` caller would push that count past the association's `temp_code_daily_limit`, the request is rejected with `ERR_TEMP_CODE_LIMIT_REACHED`. An `AssociationAdmin` issuing on a member's behalf is **not** blocked by the cap; instead, an over-cap administrator issuance succeeds and raises a charge of `charge_type` `TEMP_CODE_OVERAGE` against that member for the association's `temp_code_overage_fee_cents`, after which the member's `outstanding_balance_cents` is recomputed. That charge is the only one in the system with no lockbox attached, so its `lockbox_id` is empty, and its `variant_applied` is `NOT_APPLICABLE`.

Approval is the association's decision and belongs to an `AssociationAdmin`. It is accepted only from `REQUESTED`, and it runs three gates in the ladder order of §2.6. The vendor gate applies to contractor windows: the named contractor must have `status` of `ACTIVE`, and their `insurance_expires_on`, read at the end of that date, must be at or after the grant's `window_end`; a suspended vendor or coverage that lapses before the window ends is `ERR_CONTRACTOR_INSURANCE_EXPIRED`. The posture gate follows: a `FROZEN` association refuses every approval with `ERR_ASSOCIATION_FROZEN`, and a `RESTRICTED` association refuses contractor windows specifically with `ERR_ASSOCIATION_RESTRICTED`. The occupation gate comes last: no other grant on the *same* `lockbox_id` that is currently in `APPROVED` may occupy an overlapping span under the half-open buffered arithmetic of §2.10, else `ERR_GRANT_WINDOW_CONFLICT`. Grants in `REQUESTED`, `DENIED`, `REVOKED`, `EXPIRED` or `CONSUMED` never occupy the unit, so they never conflict.

On a successful approval the grant moves `REQUESTED → APPROVED`, a six-digit `access_code` is minted for display, and the listing's `version` advances by one because the property's access surface has changed. If the request had named a `supersedes_grant_id` and that target grant is itself in `APPROVED`, the target is moved to `REVOKED` at this moment — which is precisely how a rescheduled contractor visit replaces the original window without ever being refused for conflicting with itself. Note that the `access_code` is audit metadata for humans to read out; no business decision in this system ever takes it as an input.

Denial moves the grant `REQUESTED → DENIED` and is final. Revocation is accepted from either `REQUESTED` or `APPROVED` and is available to an administrator, to the owning `Member`, and to the member, lockbox and listing cascades described in §2.9; an explicit revocation advances the listing's `version` by one, while a cascade-driven revocation does not. Two further transitions are driven by the system rather than by a person. A grant reaches `CONSUMED` when a granted access attempt raises its `uses_count` to `max_uses` — formally, when the attempt about to be recorded would bring the count of granted events on the grant to at least `max_uses`. And the compliance checkpoint moves any grant still in `REQUESTED` or `APPROVED` whose `window_end` has reached or passed the current logical clock into `EXPIRED`. Grants may be listed and filtered by `listing_id`, `lockbox_id`, `issued_by_member_id`, `contractor_id`, `supersedes_grant_id`, `grant_type` and `status`.

### 3.6. Showings and What the Hardware Reports

A showing appointment is a booking, not an authorisation — it records that a buyer-side agent intends to be at a property in a window, so that the access log can later be reconciled against it. Requesting one names the `listing_id`, the `showing_member_id` of the attending agent, and the `window_start` and `window_end` of the visit, which is a closed interval per §2.10. It opens in `REQUESTED` with `access_event_count` at 0.

Confirmation moves it `REQUESTED → CONFIRMED` and is where the real checks live. The listing must be in `ACTIVE` or `UNDER_CONTRACT`. There must be a placement on that listing whose `placement_status` is `PLACED` — an agent cannot be booked into a house with no box on the door, and the absence of one is `ERR_SHOWING_NO_LOCKBOX`. Finally, capacity: counting the *other* appointments on the same listing that are currently in `CONFIRMED` and whose closed interval intersects this one, the confirmation is refused with `ERR_SHOWING_CAPACITY_EXCEEDED` when that count has already reached the listing's `concurrent_showing_limit`. Appointments in `REQUESTED`, `CANCELLED`, `COMPLETED` or `NO_SHOW` consume no capacity.

A confirmed showing may be completed, but only once the log agrees it happened: completion requires `access_event_count` of at least 1, and a completion attempt on a showing with no attributed access is refused with `ERR_INVALID_STATE`. Symmetrically, a confirmed showing may be marked as a no-show, but only after its `window_end` has reached or passed the current logical clock and only when `access_event_count` is exactly 0; violating either condition is likewise `ERR_INVALID_STATE`. Cancellation is accepted from `REQUESTED` or `CONFIRMED`, and the `cancel_reason` records why: `AGENT_CANCELLED` when a person cancelled it, `ACCESS_LOST` when one of the §2.9 cascades did. `COMPLETED`, `CANCELLED` and `NO_SHOW` are all terminal. Showings may be listed and filtered by `listing_id`, `showing_member_id` and `status`.

**The device gateway writes the access log.** When someone presents themselves at a box, the hardware reports the attempt: the `lockbox_id` it is attached to, the `actor_type` the device believes it saw — `MEMBER`, `CONTRACTOR` or `UNKNOWN` — optionally the `credential_id` it read, optionally the `grant_id` behind a temporary code that was keyed in, and optionally the `occurred_at` instant, which defaults to the current logical clock when the device omits it. The device does **not** report whether access was allowed. That is the server's decision, and only the `LockboxDevice` role may file an attempt.

The server resolves the `outcome` by walking a fixed ladder from the top; the first rung that matches wins, and no later rung can override it.

1. If the box's `status` is `MISSING`, the outcome is `DENIED_BOX_MISSING`.
2. Otherwise, if a `credential_id` was supplied and that credential's `status` is anything other than `ACTIVE`, the outcome is `DENIED_CREDENTIAL_INACTIVE`.
3. Otherwise, if a `grant_id` was supplied and either that grant's `status` is anything other than `APPROVED`, or the `occurred_at` instant falls outside the grant's half-open window — meaning it is earlier than `window_start` or at or later than `window_end` — the outcome is `DENIED_OUTSIDE_WINDOW`.
4. Otherwise, if neither a `credential_id` nor a `grant_id` was supplied, the outcome is `DENIED_NO_CREDENTIAL`.
5. Otherwise the outcome is `GRANTED`.

The ordering matters more than it looks. An attempt at a missing box with an inactive credential reports `DENIED_BOX_MISSING`, not `DENIED_CREDENTIAL_INACTIVE`, because the physical fact outranks the credential fact. An attempt carrying both a stale credential and a valid grant reports `DENIED_CREDENTIAL_INACTIVE`, because rung two precedes rung three.

Two further attributes are derived on every event regardless of outcome. The event's `listing_id` is snapshotted from the box's `current_listing_id` at the moment of the attempt, so a later removal does not rewrite history. And `after_hours` is true exactly when the UTC hour field of `occurred_at` is less than 8 or is 20 or greater — an attempt at 07:59 UTC and an attempt at 20:00 UTC are both after hours, while 08:00 and 19:59 are not.

Showing attribution runs only for granted events. When the outcome is `GRANTED`, a `credential_id` was supplied, and the event has a `listing_id`, the server looks for confirmed appointments on that listing whose `showing_member_id` is the member who owns the presented credential and whose closed window contains `occurred_at`. Among those candidates it takes the one with the earliest `window_start`, breaking ties by the earliest `created_at`, and writes its identifier into the event's `matched_appointment_id`, which in turn raises that appointment's `access_event_count`. If no candidate qualifies the field is simply left empty — an unmatched entry is a finding for an auditor, never an error at the door. Events on denied outcomes, events with no credential, and events on a box with no current listing never attribute to a showing. A granted event on a grant also raises that grant's `uses_count` and may drive it into `CONSUMED` as described in §3.5.

Access events are append-only and are never edited afterwards. They may be listed and filtered by `lockbox_id`, `credential_id`, `grant_id`, `listing_id`, `matched_appointment_id`, `incident_review_id` and `outcome`.
### 3.7. Loss, Theft, Recovery, Retirement — and Who Pays

A box goes missing from either of two states. It may be `ASSIGNED` — sitting in an agent's car boot — or `PLACED` on a live property. In both cases the holder or an administrator reports it, choosing between a plain loss report and a theft report. A theft report **requires** a `police_report_number`, and a plain loss report **forbids** one; getting that pairing wrong is `ERR_INVALID_REQUEST`. On acceptance the box moves to `MISSING`, its `loss_type` is written as `LOST` or `STOLEN` respectively, any `police_report_number` is stored, `missing_box_count` rises by one while `boxes_in_field_count` and `unplaced_inventory_count` each fall by one, and `posture` is recomputed. A `Member` caller may only report a box they hold.

Reporting a box that was `PLACED` additionally runs the three-hop cascade. The placement on that box sitting in `PLACED` or `REMOVAL_DUE` becomes `DELINQUENT` — and its `billing_status` deliberately stays at `NONE`, because a missing box accrues a replacement charge, never a late-removal charge. Because that placement went delinquent, every grant naming that `lockbox_id` still in `REQUESTED` or `APPROVED` becomes `REVOKED`; because those grants were revoked, every showing on the placement's listing still in `REQUESTED` or `CONFIRMED` with a `window_start` strictly after the current logical clock becomes `CANCELLED` with `cancel_reason` of `ACCESS_LOST`. The box's `current_listing_id` is cleared, and `delinquent_placement_count` and `posture` are recomputed.

**The replacement charge.** Either kind of report raises a charge with `charge_type` of `REPLACEMENT` against the member in `assigned_member_id`, linked by `lockbox_id`, in `PENDING`, after which that member's `outstanding_balance_cents` is recomputed. The amount is computed by one of two variants that are both defensible readings of the board's replacement policy and that produce genuinely different money for the same unit on the same day, so the selector is pinned here and nowhere else.

*The selector.* When the `loss_type` is `STOLEN` **and** a `police_report_number` was filed, the depreciated-book variant applies and the charge's `variant_applied` is `DEPRECIATED_BOOK`. In every other case — a plain loss, or a theft with no report number — the flat-schedule variant applies and `variant_applied` is `FLAT_SCHEDULE`.

*The flat-schedule variant* charges the full published `replacement_cost_cents` of the unit, escalated by the holder's history, and ignores the unit's age entirely. The holder's history is `loss_report_count`: the number of that member's lockboxes sitting in `MISSING` or `QUARANTINE`, counted **before** the current report flips this unit to `MISSING`. A first loss carries a repeat multiplier of 1.00; a second loss, where the prior count is exactly 1, carries 1.50; a third or subsequent loss, where the prior count is 2 or more, carries 2.00. The amount is the published replacement cost multiplied by that repeat multiplier, rounded half up to a whole cent.

*The depreciated-book variant* charges depreciated book value halved by a theft security offset, and it deliberately ignores the holder's prior loss history altogether. The months in service are the number of whole days from `in_service_since` to the calendar date of the current logical clock, divided by 30 and rounded **down** to a whole number. The depreciation fraction is the months in service multiplied by a monthly depreciation rate of 0.02, capped at 0.60 — whichever is smaller. The amount is the published `replacement_cost_cents` multiplied by one minus that depreciation fraction, multiplied by a theft security offset of 0.50, rounded half up to a whole cent. Rounding is applied exactly once, at the end of whichever branch was selected. To make the divergence concrete: a twelve-month-old unit with a published cost of 12000 cents yields 4560 under the depreciated-book variant and 12000 under the flat-schedule variant with no prior losses.

**Recovery is the compensation path.** A box in `MISSING` may be recovered, moving it to `QUARANTINE`. Recovery is administrator-only, and it may only be requested while the box is actually `MISSING`; asking to recover a box in any other state is `ERR_RECOVERY_WINDOW_CLOSED`. Recovery voids the open replacement charge for that box — the charge with `charge_type` of `REPLACEMENT` still in `PENDING` or `INVOICED` moves to `VOID` — and because that line has left the open set, the holder's `outstanding_balance_cents` is recomputed and returns to exactly its pre-report value. The association's `missing_box_count` falls by one and `posture` is recomputed. Once the unit has been inspected, returning it from `QUARANTINE` puts it back in `IN_STOCK`, clearing `loss_type`, `police_report_number` and `assigned_member_id`, and raising `unplaced_inventory_count` by one.

**Retirement is the other end.** A box in `IN_STOCK`, `MISSING` or `QUARANTINE` may be retired, which clears `assigned_member_id`, lowers `lockbox_total_count` by one and is terminal. Retiring from `IN_STOCK` also lowers `unplaced_inventory_count` by one. Retiring from `MISSING` or `QUARANTINE` lowers `missing_box_count` by one where the unit was `MISSING`, and recomputes `posture`. Critically, **retiring a missing box does not void its replacement charge** — writing the hardware off the books does not write the member's liability off with it. That asymmetry against recovery is deliberate. Lockboxes may be listed and filtered by `association_id`, `assigned_member_id`, `current_listing_id` and `status`.

**Money actions on a charge** belong to an `AssociationAdmin` alone. A charge is created in `PENDING`. Invoicing moves it `PENDING → INVOICED` and does not change the member's balance at all, because `PENDING` and `INVOICED` are both inside the open set. Paying moves a charge in `PENDING` or `INVOICED` to `PAID`, and waiving moves a charge in `PENDING` or `INVOICED` to `WAIVED`; both recompute the member's `outstanding_balance_cents` because the line has left the open set, and both move a linked placement's `billing_status` from `ACCRUED` to `SETTLED`. Voiding moves a charge in `PENDING` or `INVOICED` to `VOID`, recomputes the balance, and moves a linked placement's `billing_status` from `ACCRUED` back to `NONE`. `PAID`, `WAIVED` and `VOID` are terminal, and any money action against a charge already in one of them is refused with `ERR_CHARGE_NOT_ADJUSTABLE`; the same refusal applies to voiding a `REPLACEMENT` charge whose lockbox has since been retired. Charges may be listed and filtered by `member_id`, `lockbox_id`, `placement_id`, `charge_type` and `status`, and each one exposes the `amount_cents` it was computed at, the `variant_applied` that produced it, and the human-readable `basis` string recording the derivation.

### 3.8. Post-Incident Review of the Access Log

When a homeowner reports something wrong — a door found unlocked, property missing, an unexplained entry at three in the morning — the association's `SecurityAuditor` opens an `IncidentReview` over the access log. A review names the `association_id` it belongs to and the `window_start` and `window_end` bounding the audited period, both inclusive, and is scoped by naming a `lockbox_id`, a `listing_id`, or both; a review scoped to a lockbox only leaves `listing_id` empty, and one scoped to a listing only leaves `lockbox_id` empty. It opens in `OPEN` with `opened_by_user_id` set to the auditor's `X-User-ID`, `event_count` at 0, `risk_score` at 0.00 and `severity` at `LOW`.

Evidence is not gathered at opening. Opening is refused, however, when the proposed scope and window would reach events that already belong to another review: an access event carrying a non-empty `incident_review_id` may never be pulled into a second review, and an attempt to open one over such events is rejected with `ERR_EVIDENCE_LOCKED`.

Locking evidence is the auditor's next act, accepted only from `OPEN`. It stamps this review's identifier into the `incident_review_id` of every access event that matches the review's scope — the review's `lockbox_id` when one was named, or its `listing_id` when one was named — and whose `occurred_at` falls inside the inclusive window bounded by the review's `window_start` and `window_end`. The review moves `OPEN → EVIDENCE_LOCKED`, `event_count` is set to the number of stamped events, and `risk_score` and `severity` are computed over that frozen set. Events outside the window, events on other boxes or listings, and events that land after the lock are all excluded.

**The risk score.** Every event in the locked evidence set is first weighted individually. Its `risk_weight` is the outcome weight for its `outcome`, multiplied by 1.5 when the event's `after_hours` flag is true and by 1.0 otherwise, multiplied by the actor multiplier for its `actor_type`, and the product is rounded half up to two decimal places **per event**. The outcome weights are 2 for `GRANTED`, 9 for `DENIED_OUTSIDE_WINDOW`, 12 for `DENIED_NO_CREDENTIAL`, 18 for `DENIED_CREDENTIAL_INACTIVE` and 25 for `DENIED_BOX_MISSING` — a box that is known missing yet still being tried is the loudest signal in the catalogue. The actor multipliers are 1.0 for `MEMBER`, 1.25 for `CONTRACTOR` and 2.0 for `UNKNOWN`.

The base is the sum of those already-rounded per-event weights; per-event rounding first, then summation, is the pinned order. A penalty is then added for entries that cannot be explained by a booking: the count of events in the evidence set whose `outcome` is `GRANTED`, whose `actor_type` is `MEMBER`, and whose `matched_appointment_id` is empty, multiplied by 10. That total is rounded half up to two decimal places and then clamped into the range from 0.00 to 100.00 inclusive, and the clamped figure is the review's `risk_score`. Severity follows from thresholds compared with at-or-above semantics: a score of 70.00 or more is `CRITICAL`, a score of 35.00 or more but below 70.00 is `ELEVATED`, and anything below 35.00 is `LOW`. A score of exactly 70.00 is `CRITICAL`.

Closing a review moves it `EVIDENCE_LOCKED → CLOSED` and records the auditor's narrative in `findings` and their identity in `closed_by_user_id`. Two conditions guard it. The closing auditor's `X-User-ID` must differ from `opened_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES` — the association's rule is that the officer who raises a concern is not the officer who disposes of it. And when the computed `severity` is `CRITICAL`, the `findings` text is mandatory and must be a non-empty string; closing a critical review with no narrative is `ERR_INVALID_REQUEST`. For `LOW` and `ELEVATED` reviews `findings` is optional.

`CLOSED` is not terminal here. A closed review may be reopened, moving it `CLOSED → EVIDENCE_LOCKED`, which clears `closed_by_user_id`, re-stamps the evidence set to pick up any access event that has landed inside the review's window since the last lock, and recomputes `event_count`, `risk_score` and `severity` over the enlarged set. This gives the cycle `EVIDENCE_LOCKED → CLOSED → EVIDENCE_LOCKED`. Reviews may be listed and filtered by `association_id`, `listing_id`, `lockbox_id` and `status`.

### 3.9. The Compliance Checkpoint and Recovery Reporting

Because time in this system is logical and nothing expires spontaneously, the association runs a **compliance checkpoint** to realise everything the clock has made true. It is administrator-only, it takes no input, and it executes five steps in a pinned order. Within each step, rows are processed by `created_at` ascending.

1. **Expire grants.** Every grant in `REQUESTED` or `APPROVED` whose `window_end` has reached or passed the current logical clock moves to `EXPIRED`.
2. **Expire credentials.** Every credential in `ACTIVE` or `SUSPENDED` whose `expires_at` has reached or passed the current logical clock moves to `EXPIRED`.
3. **Expire memberships.** Every member in `ACTIVE` or `PROBATION` whose `dues_paid_through`, read at the end of that date, has fallen before the current logical clock moves to `EXPIRED`, cascading their still-`ACTIVE` credentials to `SUSPENDED` with `suspended_by_cascade` set to true.
4. **Accrue delinquencies.** Every placement in `REMOVAL_DUE` whose `removal_deadline` is strictly before the current logical clock moves to `DELINQUENT`, freezing `late_days`, moving `billing_status` from `NONE` to `ACCRUED`, and raising the `LATE_REMOVAL` charge described in §3.4.
5. **Recompute the association.** The association's `recovery_rate_pct` and `posture` are recomputed.

Step ordering is load-bearing: because credentials are expired before memberships, a credential that lapses on the same run is already `EXPIRED` when the membership cascade looks for `ACTIVE` credentials to suspend. The checkpoint reports what it did, returning the `run_at` instant it executed at together with `expired_grant_count`, `expired_credential_count`, `expired_member_count`, `delinquent_placement_count`, `accrued_charge_count`, and the resulting `recovery_rate_pct` and `posture`.

**Recovery reporting** answers the board's standing question — are boxes coming home on time? — and it does so under two deliberately different readings, selected by a `variant` field. The window is bounded by an optional `window_start` and `window_end`; when they are omitted the window is the ninety days ending at the current logical clock. Only placements reached through lockboxes belonging to the association in question are considered, and placements still in `PLACED` or `REMOVAL_DUE` fall into neither the numerator nor the denominator under either reading.

The **closing-cohort** reading — the default, used when `variant` is omitted or is given as `closing_cohort` — asks: of the deals that closed in this window, how many boxes came back on time? Its denominator is the set of placements whose listing is in `CLOSED` and whose listing's `close_date` falls inside the window inclusive of both bounds. Its numerator is those denominator members whose `placement_status` is `REMOVED` and whose `on_time` flag is true. A withdrawn listing's placement never counts at all, and a late removal counts as a miss.

The **removal-activity** reading, selected by giving `variant` as `removal_activity`, asks instead: of the boxes whose removal came due in this window, how many actually came back? Its denominator is the set of placements that either are in `REMOVED` with a `removed_at` inside the window, or are in `DELINQUENT` with a `removal_deadline` inside the window — both bounds inclusive in each case — regardless of the listing's status, so withdrawn listings do participate. Its numerator is those denominator members whose `placement_status` is `REMOVED`, which means a late removal counts here as a success. The two readings genuinely diverge: the same three placements can yield 50.00 under the closing cohort and 66.67 under removal activity.

Under either reading, the rate is the numerator count multiplied by 100 and divided by the denominator count, rounded half up to two decimal places. When the denominator count is zero the rate is exactly 0.00 — never empty, never an error. The summary response reports the `variant` that was applied, the `window_start` and `window_end` that bounded it, the `denominator_count`, the `numerator_count`, the computed `recovery_rate_pct`, the board's `recovery_target_pct` for comparison, and the association's current `posture`. The value the checkpoint writes into the association's stored `recovery_rate_pct` is always the closing-cohort reading over the ninety days ending at the current logical clock.
## 4. Endpoint Definitions

All endpoints are mounted at the server root; there is no shared collection prefix. Operations that bring a new resource into existence answer with HTTP 201 and the created resource in `data`. Operations that modify an existing resource, drive a state machine, or read data answer with HTTP 200 and the affected or requested resource in `data`. Every response — success or failure — is wrapped in the envelope of §2.2, and every failure carries one of the identifiers catalogued in §5. The table below is a routing summary only: the request payload each operation expects, the checks it runs and the side effects it fires are specified in §2 and §3 and are not repeated here.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/associations` | Register a REALTOR association and its lockbox policy configuration | `AssociationAdmin` |
| GET | `/associations/{associationId}` | Read one association with its live counters and posture | `AssociationAdmin`, `Member`, `SecurityAuditor` |
| GET | `/associations/{associationId}/recovery-summary` | Computed read: lockbox recovery rate for a window under the requested variant (closing_cohort default) | `AssociationAdmin`, `SecurityAuditor` |
| POST | `/associations/{associationId}/compliance-runs` | Ops-run checkpoint. | `AssociationAdmin` |
| POST | `/members` | Enroll a member; the system auto-transitions PENDING -> ACTIVE or PENDING -> EXPIRED from dues_paid_through inside this request | `AssociationAdmin` |
| GET | `/members/{memberId}` | Read one member with live balance and credential counters | `AssociationAdmin`, `Member`, `SecurityAuditor` |
| GET | `/members` | List members, filterable by association and membership status | `AssociationAdmin`, `Member`, `SecurityAuditor` |
| POST | `/members/{memberId}/membership-events` | Drive the Member state machine: RENEW, PLACE_ON_PROBATION, SUSPEND, REINSTATE, EXPIRE, TERMINATE | `AssociationAdmin` |
| POST | `/contractors` | Register a vendor authorised for contractor access windows | `AssociationAdmin` |
| GET | `/contractors/{contractorId}` | Read one contractor | `AssociationAdmin`, `Member`, `SecurityAuditor` |
| GET | `/contractors` | List contractors, filterable by association and status | `AssociationAdmin`, `Member`, `SecurityAuditor` |
| POST | `/contractors/{contractorId}/state` | Suspend or reactivate a vendor (action: SUSPEND / REACTIVATE) | `AssociationAdmin` |
| POST | `/lockboxes` | Intake a lockbox into association inventory (status IN_STOCK) | `AssociationAdmin` |
| GET | `/lockboxes/{lockboxId}` | Read one lockbox | `AssociationAdmin`, `Member`, `SecurityAuditor` |
| GET | `/lockboxes` | List lockboxes, filterable by association, holder, current listing and status | `AssociationAdmin`, `Member`, `SecurityAuditor` |
| POST | `/lockboxes/{lockboxId}/state` | Drive the Lockbox state machine (action: ASSIGN / RETURN / REPORT_LOST / REPORT_STOLEN / RECOVER / RETIRE). ASSIGN requires member_id; REPORT_STOLEN requires police_report_number. | `AssociationAdmin`, `Member` |
| POST | `/listings` | Create a listing owned by a member agent | `AssociationAdmin`, `Member` |
| GET | `/listings/{listingId}` | Read one listing | `AssociationAdmin`, `Member`, `SecurityAuditor` |
| GET | `/listings` | List listings, filterable by association, agent and status | `AssociationAdmin`, `Member`, `SecurityAuditor` |
| POST | `/listings/{listingId}/state` | Drive the Listing state machine (action: MARK_UNDER_CONTRACT / REACTIVATE / CLOSE / WITHDRAW). CLOSE requires close_date. | `AssociationAdmin`, `Member` |
| POST | `/lockbox-placements` | Place an assigned lockbox on an active listing | `AssociationAdmin`, `Member` |
| GET | `/lockbox-placements/{placementId}` | Read one placement with both status dimensions | `AssociationAdmin`, `Member`, `SecurityAuditor` |
| GET | `/lockbox-placements` | List placements, filterable by lockbox, listing, placing member and either status dimension | `AssociationAdmin`, `Member`, `SecurityAuditor` |
| POST | `/lockbox-placements/{placementId}/state` | Record physical removal of the lockbox from the property (action: REMOVE) | `AssociationAdmin`, `Member` |
| POST | `/access-credentials` | Issue a keyholder credential to a member. | `AssociationAdmin` |
| GET | `/access-credentials/{credentialId}` | Read one credential | `AssociationAdmin`, `Member`, `SecurityAuditor` |
| GET | `/access-credentials` | List credentials, filterable by member, status and type | `AssociationAdmin`, `Member`, `SecurityAuditor` |
| POST | `/access-credentials/{credentialId}/state` | Drive the credential state machine (action: ACTIVATE / SUSPEND / REINSTATE / REVOKE) | `AssociationAdmin` |
| POST | `/access-grants` | Request a temporary access code: a one-day member code, an inspector code, or a contractor window. | `AssociationAdmin`, `Member` |
| GET | `/access-grants/{grantId}` | Read one grant | `AssociationAdmin`, `Member`, `SecurityAuditor` |
| GET | `/access-grants` | List grants, filterable by listing, lockbox, issuer, contractor, superseded grant, type and status | `AssociationAdmin`, `Member`, `SecurityAuditor` |
| POST | `/access-grants/{grantId}/state` | Approve, deny or revoke a grant (action: APPROVE / DENY / REVOKE). APPROVE runs the insurance gate, the posture gate and the half-open buffered lockbox-occupation check. | `AssociationAdmin`, `Member` |
| POST | `/showing-appointments` | Request a showing window on a listing for a buyer-side agent | `AssociationAdmin`, `Member` |
| GET | `/showing-appointments/{appointmentId}` | Read one showing appointment | `AssociationAdmin`, `Member`, `SecurityAuditor` |
| GET | `/showing-appointments` | List showings, filterable by listing, showing agent and status | `AssociationAdmin`, `Member`, `SecurityAuditor` |
| POST | `/showing-appointments/{appointmentId}/state` | Drive the showing state machine (action: CONFIRM / CANCEL / COMPLETE / MARK_NO_SHOW). CONFIRM runs the closed-interval capacity check and requires a PLACED lockbox on the listing. | `AssociationAdmin`, `Member` |
| POST | `/_devices/access-attempts` | Device-gateway ingress for a physical access attempt at a lockbox. The outcome is derived by access_outcome_resolution, never supplied. occurred_at defaults to the logical clock when omitted. | `LockboxDevice` |
| GET | `/access-events/{eventId}` | Read one access-log entry | `AssociationAdmin`, `Member`, `SecurityAuditor` |
| GET | `/access-events` | Access-log review: list events filterable by lockbox, credential, grant, listing, matched showing, stamping incident review and outcome | `AssociationAdmin`, `Member`, `SecurityAuditor` |
| POST | `/incident-reviews` | Open a post-incident access-log review scoped to a lockbox and/or a listing over an inclusive event window | `SecurityAuditor` |
| GET | `/incident-reviews/{reviewId}` | Read one incident review with its scored evidence set | `AssociationAdmin`, `SecurityAuditor` |
| GET | `/incident-reviews` | List incident reviews, filterable by association, listing, lockbox and status | `AssociationAdmin`, `SecurityAuditor` |
| POST | `/incident-reviews/{reviewId}/state` | Drive the review state machine (action: LOCK_EVIDENCE / CLOSE / REOPEN). CLOSE enforces segregation of duties against opened_by_user_id and requires findings when severity is CRITICAL. | `SecurityAuditor` |
| GET | `/billing-charges/{chargeId}` | Read one charge with its derivation basis and applied variant | `AssociationAdmin`, `Member`, `SecurityAuditor` |
| GET | `/billing-charges` | List charges, filterable by member, lockbox, placement, type and status | `AssociationAdmin`, `Member`, `SecurityAuditor` |
| POST | `/billing-charges/{chargeId}/state` | Money action on a charge (action: INVOICE / PAY / WAIVE / VOID) | `AssociationAdmin` |
| POST | `/_clock/set_current_utc` | Set the server's logical clock. Before any call to this endpoint the clock reads exactly 2026-08-01T00:00:00Z; it never falls back to wall-clock time. | `AssociationAdmin` |

## 5. Error Code Catalogue

Every error response carries exactly one of the identifiers below in `data.error_id`, together with a human-readable `message`. The conditions that trigger each identifier are specified in the narrative of §2 and §3 rather than here; when several conditions hold at once, the ladder in §2.6 decides which identifier is returned.

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_ASSOCIATION_NOT_FOUND` | 404 |
| `ERR_MEMBER_NOT_FOUND` | 404 |
| `ERR_CONTRACTOR_NOT_FOUND` | 404 |
| `ERR_LOCKBOX_NOT_FOUND` | 404 |
| `ERR_LISTING_NOT_FOUND` | 404 |
| `ERR_PLACEMENT_NOT_FOUND` | 404 |
| `ERR_CREDENTIAL_NOT_FOUND` | 404 |
| `ERR_GRANT_NOT_FOUND` | 404 |
| `ERR_APPOINTMENT_NOT_FOUND` | 404 |
| `ERR_EVENT_NOT_FOUND` | 404 |
| `ERR_REVIEW_NOT_FOUND` | 404 |
| `ERR_CHARGE_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ENTITY_TERMINAL` | 409 |
| `ERR_MEMBER_NOT_ELIGIBLE` | 409 |
| `ERR_LOCKBOX_MISSING` | 409 |
| `ERR_CONTRACTOR_INSURANCE_EXPIRED` | 409 |
| `ERR_ASSOCIATION_FROZEN` | 409 |
| `ERR_ASSOCIATION_RESTRICTED` | 409 |
| `ERR_INVALID_WINDOW` | 422 |
| `ERR_GRANT_WINDOW_TOO_LONG` | 422 |
| `ERR_GRANT_WINDOW_CONFLICT` | 409 |
| `ERR_SHOWING_CAPACITY_EXCEEDED` | 409 |
| `ERR_TEMP_CODE_LIMIT_REACHED` | 409 |
| `ERR_DUPLICATE_SERIAL` | 409 |
| `ERR_DUPLICATE_MLS_NUMBER` | 409 |
| `ERR_LOCKBOX_NOT_ON_LISTING` | 409 |
| `ERR_SHOWING_NO_LOCKBOX` | 409 |
| `ERR_PLACEMENT_ALREADY_ACTIVE` | 409 |
| `ERR_MEMBER_BALANCE_DELINQUENT` | 402 |
| `ERR_CHARGE_NOT_ADJUSTABLE` | 409 |
| `ERR_EVIDENCE_LOCKED` | 409 |
| `ERR_RECOVERY_WINDOW_CLOSED` | 409 |
