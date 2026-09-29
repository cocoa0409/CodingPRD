# Trade Association Government Affairs API — Product Requirements Document

## 1. Introduction

An industry trade association speaks for its member companies in three arenas at once, and each arena is governed by a different rule book. Inside the association, policy priorities are set by member committees that must reach a weighted consensus and must record the dissent of members who lose the argument. Outside the association, every hour of lobbying and every dollar of advocacy spend must be registered with a jurisdiction, accumulated against a reporting threshold, and filed on a regulatory calendar. Around the edges sit the political money: a separate segregated fund that may only solicit members who have granted written prior approval, and candidate contributions that must clear a scoring floor, a per-candidate legal ceiling, and a board vote taken by someone other than the person who proposed them.

Today those three arenas live in spreadsheets that disagree with each other. A committee ballot that was superseded still shows up in a tally; an activity log is voided but the quarterly report keeps the money; a contribution is approved out of a fund that no longer has the balance to cover it. The result is not merely untidy bookkeeping — a lobbying report filed on the wrong basis, or a solicitation of an unapproved member, is a regulatory exposure with a statutory penalty attached.

This document specifies the **Government Affairs & Political Committee Administration API**, a single system of record mounted under the `/advocacy` path prefix. It is a compliance-first design: every accumulated total is derived from a declared input set rather than incremented by hand, every state change that touches a second entity declares its cascade, and every compensating action (a voided activity, a voided contribution) restores each accumulator term by term rather than merely restoring a grand total. The API is consumed by association staff, by compliance counsel, by the board, and by the member companies themselves, and the access rules differ sharply between them.

## 2. Global Specifications & System-Wide Principles

### 2.1. Actors, Authentication and Role-Based Access Control

Every request to the API — business endpoints and the test-only clock endpoint alike — must carry two headers: `X-User-ID`, identifying the caller, and `X-User-Role`, naming the capacity in which the caller is acting. If either header is absent, or is present but blank once surrounding whitespace has been trimmed, the request is rejected with `ERR_UNAUTHENTICATED` and HTTP 401. The same `ERR_UNAUTHENTICATED` / 401 result applies when `X-User-Role` carries a value that is not one of the five roles the system recognises.

The five roles are:

- **`AssociationAdmin`** — membership operations. Enrolls member companies and maintains the roster data that the rest of the advocacy machinery reads.
- **`GovAffairsDirector`** — runs the government-affairs program: policy committees and their rosters, policy positions and their ballot rounds, lobbying activity logging, grassroots campaigns and action alerts, candidate registration, and candidate contribution proposals.
- **`ComplianceOfficer`** — owns the regulatory surface: lobbying registrations and their amendments, expenditure reports and their certification, PAC prior approvals, the separate segregated fund, its filing calendar, and contribution disbursement and voiding.
- **`BoardTrustee`** — board-level ratification only: adopting a committee position that reached consensus, and approving a proposed candidate contribution. A trustee holds no proposal power whatsoever, which is precisely what makes segregation of duties observable rather than aspirational.
- **`MemberDelegate`** — a member company acting for itself: casting committee ballots, filing and withdrawing formal dissent, and granting or revoking its own PAC prior approval.

When a caller's role is not listed among the roles authorised for the endpoint being addressed, the request is rejected with `ERR_FORBIDDEN_ROLE` and HTTP 403. This check is about the *endpoint*; it is distinct from the ownership check described next, which is about the *resource*.

Four of the five roles carry an opaque identity. When `X-User-Role` is `AssociationAdmin`, `GovAffairsDirector`, `ComplianceOfficer` or `BoardTrustee`, the value of `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server may record it on a resource — as `created_by_user_id` and `certified_by_user_id` on an expenditure report, and as `proposed_by_user_id` and `board_approved_by_user_id` on a PAC contribution — but it never compares it to any entity's `id`, and it never looks it up.

`MemberDelegate` is different. When `X-User-Role` is `MemberDelegate`, `X-User-ID` is the `id` of the acting `Member`; ownership checks on any resource that references a `Member` compare the resource's member reference to `X-User-ID`. Concretely, a `MemberDelegate` may only read the member record addressed by the member `id` in the path when that `id` equals its own `X-User-ID`, and the same restriction governs that member's deductibility notice, its committee-seat list, its ballot list, and its prior-approval list. When acting on a prior approval, the approval's `member_id` must equal `X-User-ID`; when withdrawing a dissent, the vote's `member_id` must equal `X-User-ID`. A `MemberDelegate` that reaches for another member's resource is rejected with `ERR_MEMBER_SCOPE_VIOLATION` and HTTP 403. A ballot cast by a `MemberDelegate` needs no such comparison, because the voting member is *derived* from `X-User-ID` rather than supplied in the body — the delegate cannot vote as anyone but itself.

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

### 2.3. Pagination, Ordering and List Filters

Every endpoint that returns a collection is paginated through two query parameters. `limit` caps the number of items returned; when it is omitted it defaults to 10, its minimum accepted value is 1 and its maximum accepted value is 100. `offset` is the number of items to skip before the first item returned, and defaults to 0. Both appear in the `meta` object of the response envelope alongside `total_count` (the number of items that match the request before pagination is applied) and `has_more` (true when items remain beyond the returned page).

Unless a specific endpoint says otherwise, list results are ordered by `created_at` ascending. This is deliberate for an audit-oriented system: the roster of a committee, the ballots cast on a position, the alerts of a campaign, and the contributions drawn on a fund all read as chronological registers.

Several list endpoints accept an additional filter. A `status` filter narrows a list to rows whose own status value matches — committee seats, positions, votes, activities, reports, alerts, prior approvals, and contributions all support it. The expenditure-report list of a registration additionally accepts a `period_code` filter. The ballot list of a member additionally accepts `position_id` and `ballot_status`; the ballot list of a position additionally accepts `round_number` and `ballot_status`. Filters are applied before pagination, so `total_count` reflects the filtered set.

### 2.4. Resource Identity, System Timestamps and the Logical Clock

Every resource the API persists carries a server-minted `id`: a UUID string with no type prefix and no client influence. Alongside it, most resources carry three further system-managed properties:

- `created_at` (string) — an ISO 8601 UTC timestamp with exactly three fractional-second digits, for example `2026-08-01T00:00:00.000Z`, recorded when the row was first written.
- `updated_at` (string) — an ISO 8601 UTC timestamp in the same format, refreshed on every mutation of the resource, including mutations the server performs on its own initiative to keep a derived total or a derived status aligned.
- `version` (integer) — a counter that starts at 1 and increments by exactly 1 on every mutation of the resource. Recomputing a derived field such as a committee's `total_voting_weight`, a registration's `ytd_reportable_cents`, or a fund's `available_balance_cents` is a mutation for this purpose: it refreshes `updated_at` and increments `version` on the resource that owns the field.

Action alerts are the single exception. An alert is an immutable dispatch record: once written it is never modified, so it carries only `id` and `created_at`. It has no `updated_at` field and no `version` field at all, and neither field should appear in an alert response.

Time in this system is not wall-clock time. Every rule that compares "now" against a stored date or instant reads a **logical clock**, and a test-only endpoint at `/_clock/set_current_utc` sets it: the request body carries `to_iso8601`, an ISO 8601 UTC instant, and the response body carries the resulting `current_utc`. Before any call to that endpoint the logical clock reads `2026-08-01T00:00:00Z`. Every instant the server stamps — `filed_at`, `terminated_at`, `logged_at`, `certified_at`, `adopted_at`, `dispatched_at`, `granted_at`, `revoked_at`, `disbursed_at`, `voided_at` — is the logical clock instant at the moment of the transition, not the host's system time. Where a rule compares a date rather than an instant, it uses the UTC calendar date part of the logical clock. This endpoint sits outside `/advocacy` and outside the business domain, and is available to `AssociationAdmin`, `GovAffairsDirector`, `ComplianceOfficer` and `BoardTrustee`.

### 2.5. The Jurisdiction Rule Book

Three jurisdictions are recognised throughout the system — `FEDERAL`, `STATE_CA` and `STATE_NY` — and almost every jurisdiction-dependent number in the specification comes from one shared rule book, keyed by the jurisdiction code of the resource being evaluated. A single lookup supplies five things: the year-to-date expenditure at which a lobbying registration must be amended; the reporting cadence, which in turn fixes both the legal shape of a period label and the filing lag; the per-candidate per-cycle contribution ceiling; the cumulative grassroots spend at which a campaign becomes disclosable; and the dues-deductibility method that applies to a member headquartered in that jurisdiction.

| Jurisdiction | Registration threshold | Reporting cadence | Per-candidate election limit | Grassroots disclosure threshold | Deductibility method |
| --- | --- | --- | --- | --- | --- |
| `FEDERAL` | 1,400,000 cents | `QUARTERLY` | 500,000 cents | 250,000 cents | `RATIO` |
| `STATE_CA` | 200,000 cents | `QUARTERLY` | 250,000 cents | 100,000 cents | `FLAT_FLOOR` |
| `STATE_NY` | 500,000 cents | `SEMIANNUAL` | 100,000 cents | 400,000 cents | `RATIO` |

The filing lag that turns the end of a reporting period into a regulatory deadline is a function of cadence rather than jurisdiction: a `QUARTERLY` filer has 20 days after the period ends, a `SEMIANNUAL` filer has 30. One further association-wide floor sits outside the table: a coalition contribution becomes a disclosable third-party arrangement once its out-of-pocket spend reaches 500,000 cents.

### 2.6. Monetary Units, Percentages and Rounding Discipline

All money in this system is held as an integer number of cents, in fields whose names end in `_cents`, and is returned in JSON as an integer — never as a decimal string and never as a floating-point dollar amount. No rounding is ever needed to *store* money; rounding only appears where a rate or a share produces a fractional cent, and in every such place the method is **round half up** (a value exactly on the half-cent rounds away from zero, upward) applied to produce an integer number of cents.

Percentages and scores are held as numbers with **two decimal places**, likewise rounded half up: a committee's `quorum_threshold_pct` and `consensus_threshold_pct`, a position's computed `quorum_pct` and `consensus_pct`, a candidate's `voting_alignment_pct`, and a contribution's `support_score` all obey this rule, and all accepted percentage inputs must lie between 0.00 and 100.00 inclusive. Staff hours are the one quantity carried to **three decimal places**, again rounded half up, because a registration's `ytd_reportable_hours` accumulates fractional hours across many activity logs.

Two ordering rules about rounding matter enough to state globally, because getting them backwards produces a total that is wrong by a few cents and therefore wrong. First, where a rate is applied per row and the results are then summed, the rounding happens **once per row, before the sum** — never once at the end over a summed quantity. Second, where a threshold comparison is made against a rounded percentage, the comparison is made against the **rounded** value, not the unrounded one, and every such comparison in this specification is "greater than or equal to" unless the text says otherwise.

### 2.7. Cascade Discipline: One Write, Several Entities

This is a flat domain — committees, positions, registrations, activities, reports, campaigns, approvals, candidates, funds and contributions are peers, and no aggregate owns another aggregate's lifecycle. What binds them is not containment but **cascade**: a single write frequently mutates a chain of entities, and the specification names every link in that chain. Where a later section says "cascade link 1 … cascade link 4", each link is a separate, observable mutation of a separate entity, and each link refreshes that entity's `updated_at` and increments its `version`. An implementation that performs the first link and skips the third has not partially satisfied the rule; it has broken it.

Three cascade families run through the system. Adoption of a policy position walks from the position to its ballots, from the ballots to the dissenting members, from the members to their committee seats, and from the seats back to the committee's roster health. A change in a segregated fund's balance walks from the fund's posture to every pending contribution drawn on it, and from those contributions to the candidates whose pending totals they fed. Logging or voiding a lobbying activity walks from the activity to its registration's year-to-date accumulators and onward to the totals of every still-open expenditure report whose period window contains that activity.

Derived values are always **recomputed from their declared input set**, never patched by a remembered delta. Reversal of a compensating action must restore every individual term, not merely the arithmetic total: a voided contribution that once fed a candidate's committed total must remove itself from that specific total, and a voided activity must remove exactly its own expenditure and exactly its own hours from its registration's accumulators.

Some cascades change a status without any client asking. The server flips a registration into an amendment-pending state when a spend threshold is crossed, flips a fund's posture when its balance crosses the reserve floor, suspends and reinstates pending contributions as a consequence of that posture, expires prior approvals whose window has closed, and moves a campaign from planned to live on its first successfully matched alert. All of these are legitimate server-initiated transitions.

### 2.8. Nested Path Resolution

Three resources are addressed beneath a parent in the URL: a committee seat beneath its policy committee, a ballot beneath its policy position, and an action alert beneath its grassroots campaign. For any request whose path carries more than one identifier, existence is validated **strictly left to right**, and the first identifier that does not resolve determines the error. A dissent withdrawal aimed at a `vote_id` under a position `id` that does not exist fails with `ERR_POSITION_NOT_FOUND`, never with `ERR_VOTE_NOT_FOUND`; only once the position resolves does the ballot lookup run and, on failure, produce `ERR_VOTE_NOT_FOUND`. A `vote_id` that exists but belongs to a different position is not found *on the addressed position*, and therefore also yields `ERR_VOTE_NOT_FOUND`.

The same left-to-right discipline applies to identifiers supplied in a request body. Body-level references — `committee_id`, `member_id`, `position_id`, `registration_id`, `fund_id` and `candidate_id` — are resolved before any business rule that depends on the referenced row is evaluated, and each has its own not-found error: `ERR_COMMITTEE_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_POSITION_NOT_FOUND`, `ERR_REGISTRATION_NOT_FOUND`, `ERR_FUND_NOT_FOUND` and `ERR_CANDIDATE_NOT_FOUND`. Path identifiers for the remaining top-level resources resolve to `ERR_ACTIVITY_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, `ERR_CAMPAIGN_NOT_FOUND`, `ERR_PRIOR_APPROVAL_NOT_FOUND` and `ERR_CONTRIBUTION_NOT_FOUND` respectively. All of these carry HTTP 404.

### 2.9. Optimistic Concurrency on the Lobbying Registration

Opening an expenditure report is the one write in the system that requires the client to prove it has seen the current state of another entity. Creating a report requires the field `expected_registration_version` in the request body; it is not optional, and it must carry the `version` of the target `LobbyingRegistration` as the client last observed it. If that value does not equal the registration's current `version` at the moment of the write, the request is rejected with `ERR_STALE_REGISTRATION_VERSION` and HTTP 412.

The reason this guard exists is that report creation is destructive by design: a new report for a registration and period label that already has an open report **supersedes** that open report. A client working from a stale view of the registration would therefore discard a report it has never seen, and freeze a set of totals it never inspected. Because the registration's `version` is incremented by every activity log, every activity void, every registration transition, and every report creation, a stale expectation is exactly the signal that some other writer has changed the picture. No other endpoint in this system accepts a version field, and no other endpoint performs a version comparison.

### 2.10. Segregation of Duties

Two operations in this system may not be performed by the operator who set them up. An expenditure report may not be certified by the `ComplianceOfficer` who created it: certification compares the caller's `X-User-ID` against the report's `created_by_user_id` and, when they are equal, rejects with `ERR_SEGREGATION_OF_DUTIES` and HTTP 403. A PAC contribution may not be board-approved by the operator who proposed it: board approval compares the caller's `X-User-ID` against the contribution's `proposed_by_user_id` and rejects identically. Note that the second case is also protected structurally, since proposing is a `GovAffairsDirector` capability and approving is a `BoardTrustee` capability — the identity comparison is still performed, because an operator may hold more than one role.

A third separation is enforced by ownership rather than by comparison: the association requests a member's PAC prior approval, but only the member itself can grant or revoke it. The association can never grant its own solicitation authority.

### 2.11. Order of Precedence Among Validations

When a single request violates more than one rule, the response must report the **first** violation in the following order. This ordering is normative: a request that is both unauthenticated and malformed reports `ERR_UNAUTHENTICATED`, and a request whose committee roster is still forming and whose position is in the wrong state reports the state error first, because the state gate sits above the roster gate.

1. Both authentication headers are present and non-empty after trimming — otherwise `ERR_UNAUTHENTICATED` (401).
2. `X-User-Role` names one of the five declared roles — otherwise `ERR_UNAUTHENTICATED` (401).
3. The role is authorised for the endpoint — otherwise `ERR_FORBIDDEN_ROLE` (403).
4. Every path-templated resource exists, checked left to right — otherwise the matching not-found error (404).
5. A `MemberDelegate` is acting within its own member scope — otherwise `ERR_MEMBER_SCOPE_VIOLATION` (403). This gate governs reading a member record, reading a member's deductibility notice, listing a member's committee seats, listing a member's ballots, listing a member's prior approvals, granting a prior approval, revoking a prior approval, and withdrawing a dissent.
6. The request body is well shaped: required fields present, types correct, enum values legal, contribution amounts of at least 1 cent, hours non-negative with at most three decimals, percentages within 0.00 to 100.00, and dates written as ISO `YYYY-MM-DD` calendar dates — otherwise `ERR_INVALID_REQUEST` (400).
7. Every foreign key supplied in the body resolves — otherwise the matching not-found error (404). This gate governs seating a member, drafting a position, logging an activity, opening a report, launching a campaign, requesting a prior approval, crediting a fund receipt, and proposing a contribution.
8. The target resource is in a state from which the requested transition is declared — otherwise the matching state error (409). Two operations are deliberately excluded from this gate: logging a lobbying activity, whose registration-state check is the regulatory gate at rank 11, and opening a ballot round on a position that has exhausted its rounds, which is refused by the ballot-bookkeeping gate at rank 25 rather than by a generic state error.
9. The committee roster gate: opening a ballot round requires a roster that is not still forming, and adoption requires a fully quorate roster — otherwise `ERR_COMMITTEE_FORMING` or `ERR_COMMITTEE_NOT_QUORATE` (409).
10. Segregation of duties on report certification and on contribution board approval — otherwise `ERR_SEGREGATION_OF_DUTIES` (403).
11. The regulatory registration gate on activity logging — otherwise `ERR_REGISTRATION_NOT_ACTIVE` (409).
12. PAC solicitation eligibility on a fund receipt — otherwise `ERR_PRIOR_APPROVAL_NOT_GRANTED` (409).
13. The fund posture gate on contribution board approval — otherwise `ERR_FUND_RESTRICTED` (409).
14. The referenced policy position has been adopted, on activity logging and on campaign launch — otherwise `ERR_POSITION_NOT_ADOPTED` (409).
15. The acting member is seated and in good standing, on ballot casting and on prior-approval granting — otherwise `ERR_MEMBER_NOT_SEATED` or `ERR_MEMBER_NOT_ACTIVE` (409).
16. Coalition and third-party disclosure completeness on activity logging — otherwise `ERR_COALITION_PARTNER_REQUIRED` (422).
17. Jurisdiction coherence, on drafting a position, launching a campaign, and crediting a fund receipt — otherwise `ERR_JURISDICTION_SCOPE_MISMATCH` (422).
18. Prior-approval window collision on requesting an approval — otherwise `ERR_PRIOR_APPROVAL_WINDOW_CONFLICT` (409).
19. Prior-approval window shape on requesting an approval — otherwise `ERR_PRIOR_APPROVAL_WINDOW_INVALID` (422).
20. Lobbying registration coverage overlap on filing a registration — otherwise `ERR_REGISTRATION_COVERAGE_OVERLAP` (409).
21. The action-alert cooling window on dispatching an alert — otherwise `ERR_ALERT_COOLING_PERIOD` (409).
22. The activity date lies inside the registration's coverage window, on activity logging — otherwise `ERR_ACTIVITY_OUTSIDE_COVERAGE` (422).
23. Reporting-period rules: the period label matches the jurisdiction's cadence shape on opening a report and on running a filing cycle, giving `ERR_PERIOD_CADENCE_MISMATCH` (422); and certification waits until the period has closed, giving `ERR_PERIOD_NOT_CLOSED` (409).
24. Committee roster uniqueness on seating a member — otherwise `ERR_DUPLICATE_SEAT` or `ERR_CHAIR_SEAT_TAKEN` (409).
25. Ballot bookkeeping: rounds are exhausted, no ballot is live in the round being tallied, or a dissent was supplied without an opposing ballot — `ERR_MAX_BALLOT_ROUNDS`, `ERR_NO_BALLOTS_CAST` or `ERR_DISSENT_REQUIRES_OPPOSE` (409). This gate governs opening a ballot round, tallying, and casting a ballot.
26. Zero-quantity and dependency guards: an activity that records nothing, certification of an empty report, termination of a registration that still has an open report, and voiding an activity that a certified report already includes — `ERR_EMPTY_ACTIVITY`, `ERR_EMPTY_REPORT`, `ERR_OPEN_REPORT_BLOCKS_TERMINATION` or `ERR_ACTIVITY_IN_CERTIFIED_REPORT` (422).
27. The solicitable class size fits the member's restricted class, on requesting a prior approval — otherwise `ERR_CLASS_SIZE_EXCEEDED` (422).
28. The candidate scoring floor on proposing a contribution — otherwise `ERR_SCORE_BELOW_FLOOR` (422).
29. The contribution ceiling, on proposing a contribution and again on disbursing it — otherwise `ERR_CONTRIBUTION_LIMIT_EXCEEDED` (422).
30. The fund balance covers the amount, on board approval — otherwise `ERR_INSUFFICIENT_FUND_BALANCE` (422).
31. The optimistic-concurrency check on opening an expenditure report — otherwise `ERR_STALE_REGISTRATION_VERSION` (412).

## 3. Business Logic & Workflows

### 3.1. Enrolling Members and What the Advocacy Machinery Reads From Them

Everything downstream begins with the member roster, which an `AssociationAdmin` maintains — and only an `AssociationAdmin` may enroll a member company. Enrollment records the company's `legal_name` (non-empty, at most 200 characters) and its `membership_tier`, one of `ASSOCIATE`, `FULL` or `PREMIER`. The tier is a dues concept on its face, but it is also the source of committee voting weight, so it is worth stating the mapping early: an `ASSOCIATE` member carries one unit of weight, a `FULL` member two, and a `PREMIER` member three.

Enrollment also captures where the company sits, politically and geographically. Its `home_jurisdiction_code` is one of `FEDERAL`, `STATE_CA` or `STATE_NY` and decides which dues-deductibility method the company's annual notice will use; the server resolves that decision immediately and stores the answer on the member as `notice_method`, either `RATIO` or `FLAT_FLOOR`, taken from the jurisdiction rule book of §2.5. `notice_method` is never accepted from the client, even if supplied. Its `home_district_code` is a non-empty uppercase legislative-district label written as a state abbreviation, a hyphen, and a number — `CA-12` is the canonical shape — and it is the join key on which grassroots constituent matching later depends.

The dues facts are `annual_dues_cents`, a non-negative integer, and `dues_year`, a calendar year between 2020 and 2100 inclusive, which together form the base of the deductibility notice. `restricted_class_size` — also a non-negative integer — is the count of executives and stockholders the company could in principle make solicitable, and it is the ceiling that any later prior approval must respect. Three fields are optional at enrollment and take documented defaults: `status`, one of `ACTIVE`, `LAPSED` or `SUSPENDED`, defaults to `ACTIVE`; `advocacy_optout`, a boolean, defaults to false; and `engagement_score`, an integer from 0 to 100, defaults to 50. Only an `ACTIVE` member may be seated on a committee, cast a ballot, be matched by an action alert, or be solicited for the political fund. A member with `advocacy_optout` set to true is excluded from every constituent-match candidate set regardless of its district. `engagement_score` is the primary sort key of that same match set.

Two member fields are pure bookkeeping and start at their floor: `recorded_dissent_count` is initialised to 0 and rises only when a formal dissent of this member is registered by an adoption, and `pac_solicitable` is initialised to false. `pac_solicitable` is not a stored decision but a derived one: it reads true exactly when some prior approval of this member sits in `GRANTED` status and the logical clock's date falls on or after that approval's `effective_date` and on or before its `expires_at_date`.

A member has a narrow window onto its own data, described in §2.1: its own record, its own deductibility notice, its own committee seats, its own ballots across all positions, and its own prior approvals. Staff roles and the board may read any member's records through the same capabilities.

### 3.2. Policy Committees, Seats and the Arithmetic of Roster Health

A `GovAffairsDirector` creates a **policy committee** with a `name` (non-empty, at most 200 characters), a `jurisdiction_scope` of `FEDERAL`, `STATE_CA`, `STATE_NY` or `MULTI`, and the two percentages that will later decide its ballots: `quorum_threshold_pct`, the minimum participation share a round must reach before its result is scored at all, and `consensus_threshold_pct`, the minimum support share required to declare consensus. Both are percentages with two decimals in the 0.00 to 100.00 range. A committee scoped to `MULTI` may set positions for any jurisdiction; a committee scoped to a single jurisdiction may only set positions for that one.

Seating is also a director's act. A seat names the `member_id` of the company being seated — the `committee_id` is taken from the path and is never read from the body — and may name a `seat_role` of `CHAIR` or `MEMBER`, defaulting to `MEMBER`. A `CHAIR` seat confers no extra weight and breaks no tie; it exists to be reported on the roster. A committee may have at most one chair, and a second chair request is refused with `ERR_CHAIR_SEAT_TAKEN`; a member may hold at most one seat on a given committee, and a repeat seating is refused with `ERR_DUPLICATE_SEAT`.

At seating time the server writes the seat's `voting_weight` by looking up the member's current tier — one for `ASSOCIATE`, two for `FULL`, three for `PREMIER` — and it does **not** follow later tier changes; it also sets `dissent_strikes` to 0 and the seat `status` to `ACTIVE`. A seat's status is either `ACTIVE` or `DAMPENED`, and damping, described in §3.4, is one-way for the life of the seat: a seat is never deleted and a dampened seat never recovers.

Every seating recomputes three derived fields on the committee. `seat_count` is the number of seats on the committee whose status is `ACTIVE` or `DAMPENED`. `total_voting_weight` is the sum of `voting_weight` over exactly that same set of seats. `roster_state` is then decided in this order: it is `FORMING` while `seat_count` is below three; otherwise, if `total_voting_weight` is below six, it is `IMPAIRED`; otherwise it is `QUORATE`. A brand-new committee therefore starts `FORMING`. Note the consequence of the weight rule: three `ASSOCIATE` members supply three seats but only three units of weight, so the committee reaches `IMPAIRED` rather than `QUORATE` — enough to ballot, not enough to adopt.

### 3.3. The Consensus Ballot Cycle: Rounds, Ballots and Dissent

A **policy position** is the association's proposed stance on one issue, and a `GovAffairsDirector` drafts it under a committee by supplying that committee's `committee_id`, a `title` (non-empty, at most 200 characters), the `jurisdiction_code` the position addresses (`FEDERAL`, `STATE_CA` or `STATE_NY`), and a `summary` of the consensus language to be circulated (non-empty, at most 2000 characters). The jurisdiction must sit inside the committee's scope: a committee scoped `MULTI` accepts any of the three, while a single-jurisdiction committee accepts only its own, and a mismatch is refused with `ERR_JURISDICTION_SCOPE_MISMATCH`. A freshly drafted position sits in `DRAFT` with `round_number` at 0, every weight and percentage field at 0, `last_tally_outcome` at `NONE`, `dissent_register_count` at 0, and `adopted_at` null.

Opening a ballot round is the director's act of putting the language to the committee, and it moves the position `DRAFT → BALLOTING` the first time and `RECONSIDERATION → BALLOTING` on every later attempt — that second edge is what closes the negotiation loop `BALLOTING → RECONSIDERATION → BALLOTING`. Two gates guard the opening. The committee's `roster_state` must not be `FORMING`; both `QUORATE` and `IMPAIRED` are acceptable here, and a still-forming roster is refused with `ERR_COMMITTEE_FORMING`. And the position's `round_number` must still be below three, because three rounds is the whole allowance the association gives a contested position. A position whose `round_number` has already reached three is sitting in the terminal `FAILED_CONSENSUS` state, and an attempt to open a fourth round is refused specifically with `ERR_MAX_BALLOT_ROUNDS` rather than with the generic state error; opening a round from any other ineligible state — `BALLOTING`, `CONSENSUS_REACHED` or `ADOPTED` — yields `ERR_INVALID_POSITION_STATE`.

Opening a round does four things. It increments `round_number` by one. It records `ballot_deadline_date` when the request supplies one — an ISO `YYYY-MM-DD` date that is advisory only and is left unchanged when the field is omitted. It clears the tally snapshot, setting `support_weight`, `oppose_weight`, `abstain_weight`, `quorum_pct` and `consensus_pct` back to 0 and `last_tally_outcome` back to `NONE`. And it retires the previous round's ballots: every ballot of this position belonging to an earlier round whose `ballot_status` is `CAST` flips to `SUPERSEDED`. Critically, that flip does **not** touch the ballot's `dissent_status`; the two statuses on a ballot are independent axes, and a superseded ballot keeps whatever dissent state it had.

Within an open round, a `MemberDelegate` casts a ballot. The body carries `ballot` — one of `SUPPORT`, `OPPOSE` or `ABSTAIN` — and optionally `dissent_statement`, formal dissent language of at most 1000 characters. The voting `member_id` is resolved from `X-User-ID` rather than supplied, and the `position_id` comes from the path. Casting requires the position to be in `BALLOTING`; anything else is `ERR_INVALID_POSITION_STATE`. It also requires the caller to be a seated committee member in good standing: the caller must hold a seat on the position's committee whose status is `ACTIVE` or `DAMPENED`, failing which the cast is refused with `ERR_MEMBER_NOT_SEATED`, and the caller's member record must itself be `ACTIVE`, failing which it is refused with `ERR_MEMBER_NOT_ACTIVE`.

Each accepted ballot is stamped with the state of the world at cast time. Its `round_number` is copied from the position's current `round_number`, and its `weight_snapshot` is copied from the caster's seat `voting_weight` — a snapshot in the strict sense, since a later damping of that seat does not rewrite ballots already cast. Its `ballot_status` is `CAST`. Its `dissent_status` is `FILED` when a non-empty `dissent_statement` was supplied and `NONE` when it was not; a dissent statement is only meaningful alongside an opposing ballot, so supplying one together with `SUPPORT` or `ABSTAIN` is refused with `ERR_DISSENT_REQUIRES_OPPOSE`. A delegate may change its mind within the same round simply by casting again: the earlier ballot of that same member in that same round flips from `CAST` to `SUPERSEDED` — again leaving its `dissent_status` exactly as it was — and the new ballot becomes the live one. Because adoption only ever registers ballots that are still `CAST`, a dissent sitting on a superseded ballot can never be recorded.

A dissenting delegate may also stand down without changing its vote. Withdrawing a dissent moves that ballot's `dissent_status` from `FILED` to `WITHDRAWN` and leaves `ballot_status` untouched, which means a still-`CAST` opposing ballot keeps contributing its full weight to the opposition side of the tally — the withdrawal is a statement about the formal record, not about the vote. Three conditions apply: the ballot's `dissent_status` must currently be `FILED`, and a `NONE`, `WITHDRAWN` or `RECORDED` dissent is refused with `ERR_DISSENT_NOT_FILED`; the position must still be inside the ballot cycle, in either `BALLOTING` or `RECONSIDERATION`, since a dissent may not be rewritten once the position has left it, and any other position state yields `ERR_INVALID_POSITION_STATE`; and the caller must be the dissenting member itself, enforced as described in §2.1.

### 3.4. Tallying the Round, the Consensus Fork, and Board Adoption

Closing a round is a `GovAffairsDirector` act, permitted only while the position is `BALLOTING` — any other state gives `ERR_INVALID_POSITION_STATE` — and only when at least one ballot of the **current** round still has `ballot_status` `CAST`. A round in which every ballot has been superseded, or in which nothing was ever cast, cannot be scored, and the attempt is refused with `ERR_NO_BALLOTS_CAST`.

The input set for scoring is narrow and must be read literally: ballots of this position whose `round_number` equals the position's current `round_number` and whose `ballot_status` is `CAST`. Superseded ballots are excluded. A ballot's `dissent_status` is irrelevant here — a withdrawn dissent still leaves an opposing ballot counting at its full weight. From that set the server writes three sums onto the position: `support_weight` is the total of `weight_snapshot` across ballots marked `SUPPORT`, `oppose_weight` the total across ballots marked `OPPOSE`, and `abstain_weight` the total across ballots marked `ABSTAIN`.

Two percentages follow. Participation is the sum of all three weights; `quorum_pct` is one hundred times that participation divided by the committee's `total_voting_weight`, rounded half up to two decimals. Consensus is measured only among members who took a side: when `support_weight` and `oppose_weight` are both zero — an all-abstain round has no consensus base — `consensus_pct` is written as 0.00; otherwise `consensus_pct` is one hundred times `support_weight` divided by the sum of `support_weight` and `oppose_weight`, rounded half up to two decimals. Abstentions therefore count toward reaching quorum but are excluded from the consensus denominator, which is the whole point of allowing an abstention at all.

The fork is then decided **in exactly this order**, against the rounded percentages. If `quorum_pct` is less than the committee's `quorum_threshold_pct`, the outcome is `NO_QUORUM`. Otherwise, if `consensus_pct` is greater than or equal to the committee's `consensus_threshold_pct`, the outcome is `CONSENSUS`. Otherwise the outcome is `DISSENSUS`. The order matters because a round can fail both tests, and the recorded `last_tally_outcome` must say `NO_QUORUM` in that case. Both threshold comparisons are inclusive at the boundary: a `quorum_pct` exactly equal to the quorum threshold passes, and a `consensus_pct` exactly equal to the consensus threshold reaches consensus.

The outcome selects the destination state. A `CONSENSUS` outcome moves the position `BALLOTING → CONSENSUS_REACHED`. A `NO_QUORUM` or `DISSENSUS` outcome moves it `BALLOTING → RECONSIDERATION` while `round_number` is still below three, leaving the committee free to renegotiate the language and open another round; on the third round, the same failure moves it `BALLOTING → FAILED_CONSENSUS` instead, which is terminal. In every case the four weight fields, both percentages and `last_tally_outcome` are written, and no ballot's `ballot_status` or `dissent_status` changes at tally time.

Adoption belongs to the board. A `BoardTrustee` ratifies a position that reached consensus, moving it `CONSENSUS_REACHED → ADOPTED` and stamping `adopted_at` with the logical clock instant; any other starting state gives `ERR_INVALID_POSITION_STATE`. Adoption applies a stricter roster test than balloting did: the committee's `roster_state` must be exactly `QUORATE`, and both `IMPAIRED` and `FORMING` are refused with `ERR_COMMITTEE_NOT_QUORATE`. This is the gate that dissent damping can close, as the cascade below shows. Adoption is what unlocks the outward-facing work: only an `ADOPTED` position may be cited by a lobbying activity or advanced by a grassroots campaign.

Adoption is also the system's longest cascade, and all four links fire inside the one request:

- **Cascade link 1 (position to ballots).** Every ballot of this position whose `round_number` equals the position's `round_number`, whose `ballot_status` is `CAST`, whose `ballot` is `OPPOSE`, and whose `dissent_status` is `FILED` moves to `dissent_status` `RECORDED`. The count of ballots so moved is written to the position's `dissent_register_count`. Ballots that are superseded, from an earlier round, not opposing, or whose dissent was withdrawn are all left alone — a `WITHDRAWN` dissent can never become `RECORDED`.
- **Cascade link 2 (ballots to members).** Because those ballots reached `RECORDED`, each distinct member behind them has its `recorded_dissent_count` incremented by one.
- **Cascade link 3 (members to seats).** Because that member's recorded dissent grew, its seat on *this position's committee* has `dissent_strikes` incremented by one. Once a seat's `dissent_strikes` reaches two, the seat flips `ACTIVE → DAMPENED` and its `voting_weight` is re-derived as half the member's tier weight rounded down, but never below one: a `PREMIER` member's seat drops from three to one, a `FULL` member's from two to one, and an `ASSOCIATE` member's stays at one. Damping is permanent for the life of the seat.
- **Cascade link 4 (seats to committee).** Because a seat's `voting_weight` changed, the committee's `total_voting_weight` and `roster_state` are recomputed by the rules of §3.2. A committee that was `QUORATE` may become `IMPAIRED` as a direct consequence of adopting a position over recorded dissent — and once it is `IMPAIRED` it can still open ballot rounds but can no longer adopt anything, until enough new weight is seated.

### 3.5. Lobbying Registration and the Activity Record

Registering with a jurisdiction is compliance work, and only a `ComplianceOfficer` touches it. A registration is drafted with a `jurisdiction_code` of `FEDERAL`, `STATE_CA` or `STATE_NY`, a `registrant_name` as it will be filed (non-empty, at most 200 characters), and the two ISO `YYYY-MM-DD` dates that bound its coverage: `coverage_start_date`, the first day activity is covered, and `coverage_end_date`, the last, which must be strictly later than the start. A draft starts in `DRAFT` with `amendment_round` at 0, `filed_at` and `terminated_at` null, and both year-to-date accumulators at 0. Nothing about overlap is checked at draft time.

Filing moves the registration `DRAFT → ACTIVE`, stamps `filed_at` with the logical clock instant, and is the moment the overlap rule bites. Two registrations that share the same `jurisdiction_code` and the same `registrant_name` may not both be live over the same days, where "live" means a status of `ACTIVE` or `AMENDMENT_PENDING`. The comparison treats each coverage window as **half-open**: it includes `coverage_start_date` and excludes `coverage_end_date`. The practical consequence is that abutting windows are legal — a registration ending on the very day the next one starts does not collide — while any genuine overlap of covered days is refused with `ERR_REGISTRATION_COVERAGE_OVERLAP`. Filing anything other than a `DRAFT` gives `ERR_INVALID_REGISTRATION_STATE`.

A live registration goes through amendment cycles. A compliance officer opens an amendment, moving `ACTIVE → AMENDMENT_PENDING`, and certifies it afterwards, moving `AMENDMENT_PENDING → ACTIVE` and incrementing `amendment_round` by one. While the amendment is pending the filing on record is stale, so no activity may be logged against the registration. Certifying an amendment has a second, less obvious effect described below: raising `amendment_round` above zero permanently disarms the automatic threshold amendment. Opening an amendment on a registration that is not `ACTIVE`, or certifying one on a registration that is not `AMENDMENT_PENDING`, gives `ERR_INVALID_REGISTRATION_STATE`.

Termination moves `ACTIVE → TERMINATED` and stamps `terminated_at`; it is blocked while any expenditure report of this registration is still `OPEN`, which is refused with `ERR_OPEN_REPORT_BLOCKS_TERMINATION`. Once terminated, no further activity may be logged and no further report may be opened, and the state is terminal. Every one of these four transitions — file, amend, certify-amendment, terminate — increments the registration's `version` by one, which matters for the concurrency rule of §2.9.

Logging an activity is the `GovAffairsDirector`'s job, and it is the busiest write in the system. The payload names the `registration_id` under which the activity is reportable, the `position_id` of the adopted position it advances, an `activity_kind` of `DIRECT_LOBBYING`, `COALITION_CONTRIBUTION`, `THIRD_PARTY_ADVOCACY` or `GRASSROOTS_SUPPORT`, the `activity_date` on which it occurred as an ISO `YYYY-MM-DD` date, the in-house `hours` spent (at least 0, at most 999.999, with at most three decimals), the out-of-pocket `expenditure_cents` (a non-negative integer), and optionally a `coalition_partner_name` identifying the third party or coalition counterpart.

Four regulatory gates run before anything is written. The registration must be `ACTIVE`: a `DRAFT` registration means unregistered lobbying, an `AMENDMENT_PENDING` one means the filing on record is stale, and a `TERMINATED` one means coverage has ended — all three are refused with `ERR_REGISTRATION_NOT_ACTIVE`. The cited position must be `ADOPTED`, or the log is refused with `ERR_POSITION_NOT_ADOPTED`. A `coalition_partner_name` is mandatory, non-blank, whenever `activity_kind` is `COALITION_CONTRIBUTION` or `THIRD_PARTY_ADVOCACY`, because the third-party disclosure would otherwise be incomplete; its absence is refused with `ERR_COALITION_PARTNER_REQUIRED`. The `activity_date` must fall inside the registration's coverage window with **both endpoints inclusive** — note the deliberate asymmetry with the half-open overlap test above — and a date outside it is refused with `ERR_ACTIVITY_OUTSIDE_COVERAGE`. Finally, an activity that records nothing at all, with `hours` of 0 and `expenditure_cents` of 0, is refused with `ERR_EMPTY_ACTIVITY`, since it would move no accumulator.

An accepted activity is written with `status` `LOGGED`, `void_reason` null, and `logged_at` set to the logical clock instant. Two fields are derived. `staff_cost_cents` is the in-house labour value of this one activity: its `hours` multiplied by the association's standard staff rate of 8500 cents per hour — 85 dollars — rounded half up to a whole number of cents. This rounding is performed for this activity alone and is never re-derived from a summed hour total. `third_party_disclosure_required` reads true in exactly two situations: whenever `activity_kind` is `THIRD_PARTY_ADVOCACY`, and when `activity_kind` is `COALITION_CONTRIBUTION` and this activity's `expenditure_cents` is at least 500,000; in every other case it reads false.

Writing the activity then propagates. The activity's `expenditure_cents` is added to the registration's `ytd_reportable_cents` and its `hours` are added to the registration's `ytd_reportable_hours`, the latter held to three decimals rounded half up; both accumulators must always equal the sum over the registration's `LOGGED` activities alone. The registration's `version` increments. Every still-`OPEN` expenditure report of this registration whose period window contains the new `activity_date` recomputes its totals and its `included_activity_count`.

One further consequence is a genuine threshold trigger. Immediately after the accumulator increment, if the registration's `amendment_round` is still 0 and its new `ytd_reportable_cents` has reached the registration threshold for its jurisdiction — 1,400,000 cents federally, 200,000 in California, 500,000 in New York — the registration flips `ACTIVE → AMENDMENT_PENDING` inside the very same request that created the activity. The boundary is inclusive: landing exactly on the threshold flips it. The activity itself is still created, and still `LOGGED`. Because the trigger requires `amendment_round` to be 0, it fires at most once in a registration's life; a certified amendment disarms it forever, and further spending past the threshold no longer disturbs the registration.

Voiding an activity is the director's compensating action, and it requires a `void_reason` in the body. It moves the activity `LOGGED → VOIDED` and records that reason; an already-voided activity gives `ERR_ACTIVITY_ALREADY_VOIDED`. It is blocked outright when any expenditure report that included this activity has already been certified, because a certified filing's totals are frozen — that refusal is `ERR_ACTIVITY_IN_CERTIFIED_REPORT`. When the void proceeds it compensates exactly what the log added: the activity's `expenditure_cents` is subtracted from `ytd_reportable_cents` and its `hours` from `ytd_reportable_hours`, the registration's `version` increments, and every `OPEN` report that included the activity recomputes `method_a_total_cents`, `method_b_total_cents`, `filed_total_cents` and `included_activity_count`. Reports that are `CERTIFIED` or `SUPERSEDED` are never recomputed by a void.

### 3.6. Expenditure Reports, the Filing Calendar, and the Dues Deductibility Notice

An expenditure report is the periodic filing a `ComplianceOfficer` makes for one registration. Opening one names the `registration_id`, the `period_code` being reported, the `basis` on which the total will be filed, and the `expected_registration_version` demanded by §2.9. The `period_code` must match the shape the registration's jurisdiction requires: a quarterly filer — federal and California registrants — writes a four-digit year followed by the letter `Q` and a quarter index from 1 to 4, as in `2026Q3`, while a semiannual filer — New York registrants — writes a four-digit year followed by the letter `H` and a half index of 1 or 2, as in `2026H1`. A label of the wrong shape, or one naming an out-of-range period index, is refused with `ERR_PERIOD_CADENCE_MISMATCH`.

From the label the server derives three dates. `period_start_date` is the first calendar day of the named period and `period_end_date` is its last, both inclusive; a third quarter therefore runs from the 1st of July to the 30th of September, and a first half from the 1st of January to the 30th of June. `due_date` is the regulatory deadline: `period_end_date` advanced by the filing lag for that cadence, which is 20 days for a quarterly filer and 30 days for a semiannual one.

The report's inclusion set is fixed at the same moment and is identical for both bases: those activities of the report's registration whose `status` is `LOGGED` and whose `activity_date` falls on or after `period_start_date` and on or before `period_end_date`. Voided activities never enter it. `included_activity_count` is the size of that set. Two totals are then computed side by side, and both are stored on every report regardless of which one is filed:

- `method_a_total_cents` — the **tax-code basis**. It is the sum of `expenditure_cents` over the included activities, and nothing else; in-house staff time is excluded entirely.
- `method_b_total_cents` — the **statutory lobbying-disclosure basis**. For each included activity, take its `expenditure_cents` and add that activity's own staff cost, which is its `hours` multiplied by 8500 cents and rounded half up to whole cents; then sum those per-activity amounts. The rounding order is pinned and is not negotiable: round once per activity and only then add up. Summing the hours of every activity first and rounding the product once at the end produces a different cent total, and that form is wrong here. On any non-empty set of activities with non-zero hours, this basis yields a strictly larger total than the tax-code basis.

`filed_total_cents` is then whichever of the two the `basis` selects — `method_a_total_cents` when `basis` is `METHOD_A`, `method_b_total_cents` when it is `METHOD_B`. The report is written in `OPEN` status with `created_by_user_id` taken from the caller's `X-User-ID`, `certified_by_user_id` and `certified_at` null, and `late` false. Two side effects follow: any earlier report for the same registration and the same `period_code` that is still `OPEN` moves `OPEN → SUPERSEDED`, and its totals are frozen at their present values and never recomputed again; and the registration's `version` increments, which is what makes the concurrency guard both necessary and sufficient.

Certification is the act of filing, and it moves the report `OPEN → CERTIFIED`. Three conditions gate it beyond the state itself, which is refused with `ERR_INVALID_REPORT_STATE` when the report is already `CERTIFIED` or has been `SUPERSEDED`. The report must contain at least one activity: an `included_activity_count` of 0 is refused with `ERR_EMPTY_REPORT`. The certifier must not be the creator, per §2.10, on pain of `ERR_SEGREGATION_OF_DUTIES`. And the period must have closed: the logical clock's UTC date must have reached `period_end_date` — being exactly on that date is sufficient — while an earlier date is refused with `ERR_PERIOD_NOT_CLOSED`. On success the server sets `certified_by_user_id` from `X-User-ID`, stamps `certified_at` with the logical clock instant, and sets `late` to true when the UTC calendar date of `certified_at` falls strictly after `due_date`, and false otherwise.

Certification has one reach beyond the report itself: a certified report's `filed_total_cents` immediately enters the input set of every member's dues-deductibility notice for the year that report covers. Nothing is stored on the member; the notice is computed on read, so the effect of a certification is visible on the next read of any affected member's notice.

That notice answers the question every member's tax department asks — how much of this year's dues is non-deductible because the association spent it on lobbying. It is computed as follows for the member being read. Gather every report whose `status` is `CERTIFIED` and whose `period_code` begins with the four digits of the member's `dues_year`; reports that are `OPEN` or `SUPERSEDED` are excluded. `lobbying_spend_cents` is the sum of `filed_total_cents` over those reports. `ratio_pct` is one hundred times `lobbying_spend_cents` divided by the association's annual budget of 120,000,000 cents — 1.2 million dollars — rounded half up to two decimals, and then capped so that it never exceeds 100.00.

From there the member's `notice_method` selects one of two variants, and they are genuinely different arithmetic rather than two spellings of the same thing:

- **`RATIO`** — the method for members headquartered under `FEDERAL` or `STATE_NY`. `nondeductible_pct` is `ratio_pct` unchanged, with no floor. `nondeductible_amount_cents` is the member's `annual_dues_cents` multiplied by `nondeductible_pct`, divided by one hundred, rounded half up to whole cents. The full dues amount is the base; there is no exempt portion.
- **`FLAT_FLOOR`** — the method for members headquartered under `STATE_CA`. `nondeductible_pct` is the greater of `ratio_pct` and 25.00, so a low-spend year still yields a 25 percent notice. The base is not the full dues: it is the member's `annual_dues_cents` less an exempt base of 25,000 cents, floored at 0 so that a small-dues member never produces a negative base. `nondeductible_amount_cents` is that reduced base multiplied by `nondeductible_pct`, divided by one hundred, rounded half up to whole cents.

In both variants `deductible_amount_cents` is the member's `annual_dues_cents` minus `nondeductible_amount_cents`. The notice is returned as an inline object rather than a stored entity, and it carries exactly these fields: `member_id`, `dues_year`, `notice_method`, `ratio_pct`, `nondeductible_pct`, `nondeductible_amount_cents`, `deductible_amount_cents` and `lobbying_spend_cents`. Two members with identical dues and identical years will therefore receive different notices when they are headquartered in different jurisdictions, which is exactly the outcome the tax rules intend.

### 3.7. Grassroots Mobilisation: Campaigns, Action Alerts and Constituent Matching

Once a position has been adopted, the association can ask its members to speak to their own legislators. A `GovAffairsDirector` launches a **grassroots campaign** by naming the `position_id` it advances, a campaign `name` shown on the alerts that go out (non-empty, at most 200 characters), and a `target_jurisdiction_code`. The position must be `ADOPTED`, or the launch is refused with `ERR_POSITION_NOT_ADOPTED`, and the campaign's `target_jurisdiction_code` must equal the position's own `jurisdiction_code` — a campaign cannot lobby a different capital than the position it carries — with a mismatch refused as `ERR_JURISDICTION_SCOPE_MISMATCH`. A campaign's status is one of `PLANNED`, `LIVE` or `CLOSED`, and a new campaign starts in `PLANNED` with `alert_count`, `matched_member_total`, `unmatched_alert_count` and `cumulative_cost_cents` all at 0, `disclosure_required` false, and `last_alert_at` null.

Dispatching an **action alert** is the campaign's unit of work. Each alert names the `target_district_code` it mobilises, written in the same state-hyphen-number shape as a member's home district; a `target_chamber` of `US_HOUSE`, `US_SENATE` or `STATE_ASSEMBLY`; a `message_subject` for the alert (non-empty, at most 200 characters); and a `unit_cost_cents`, the non-negative cost the association is charged per matched member. The alert's `campaign_id` is taken from the path and is never read from the body. Alerts may not be dispatched on a `CLOSED` campaign, which is refused with `ERR_INVALID_CAMPAIGN_STATE`.

Alerts are also rate-limited, because burning through a member list is counterproductive. A new alert's dispatch instant must be at least 48 hours — two full days — after the campaign's `last_alert_at`. A gap of exactly 48 hours is allowed; anything shorter is refused with `ERR_ALERT_COOLING_PERIOD`. When `last_alert_at` is still null no cooling window exists and the alert proceeds.

The heart of the alert is the **constituent match set**, and its membership is an explicit four-part predicate rather than a fuzzy notion of relevance. A member qualifies when all four hold: the member's `status` is `ACTIVE`; the member's `advocacy_optout` is false; the member's `home_district_code` is exactly equal to the alert's `target_district_code`; and that member holds a committee seat whose `status` is `ACTIVE` or `DAMPENED` on the very committee that owns the campaign's position. Every other member is excluded, including a member whose district matches perfectly but who sits on no seat of that committee, and including a dampened-seat member — damping reduces weight, it does not remove a member from the mobilisation list.

Qualifying members are then ordered: by `engagement_score` from highest to lowest, and, where two members share an engagement score, by `created_at` from earliest to latest. The tie-break is `created_at` and never the identifier, which makes the ordering total and reproducible. That ordered list of member identifiers is stored on the alert as `matched_member_ids` — an ordering payload, in selector order — and its length is stored as `matched_member_count`. The alert's `cost_cents` is its `unit_cost_cents` multiplied by `matched_member_count`, which is 0 when the match set is empty. The alert's own `status` follows directly: `DISPATCHED` when at least one member matched, `NO_MATCH` when none did. An empty match set is emphatically **not** an error — the alert is still persisted, as a `NO_MATCH` record, so the association can see which districts it cannot reach. Either way `dispatched_at` is stamped with the logical clock instant. As noted in §2.4, an alert is immutable and carries no `updated_at` and no `version`.

Every alert updates the campaign, but not all of them update it the same way. `alert_count` increments for every alert, `DISPATCHED` and `NO_MATCH` alike. `matched_member_total` grows by the alert's `matched_member_count`, and `cumulative_cost_cents` grows by its `cost_cents`, so a `NO_MATCH` alert contributes nothing to either. `unmatched_alert_count` increments only for a `NO_MATCH` alert. `last_alert_at` is set to the alert's `dispatched_at` **only** for a `DISPATCHED` alert; a `NO_MATCH` alert leaves `last_alert_at` exactly as it was and therefore never starts a cooling window, so a district with no reachable members can be retried immediately. And the first `DISPATCHED` alert moves the campaign `PLANNED → LIVE`; a `NO_MATCH` alert leaves it in `PLANNED`.

Disclosure is a latch. After the accumulators are updated, if the campaign's `cumulative_cost_cents` has reached the grassroots disclosure threshold for its `target_jurisdiction_code` — 250,000 cents federally, 100,000 in California, 400,000 in New York — then `disclosure_required` is set to true. The boundary is inclusive, and the latch never reverts: once a campaign is disclosable it stays disclosable, even if later events would leave the total looking smaller.

Closing a campaign is the director's final act, and it is legal from either live state: `PLANNED → CLOSED` for a campaign that never dispatched anything, and `LIVE → CLOSED` for one that did. Closing an already-`CLOSED` campaign is refused with `ERR_INVALID_CAMPAIGN_STATE`. Closure freezes `cumulative_cost_cents` and `disclosure_required` at their current values and bars any further alert.

### 3.8. PAC Solicitation Eligibility and the Separate Segregated Fund

The association may not simply ask a member company's executives for political money. It must first obtain that company's **prior approval**, in writing, for a bounded window, and it may hold only one such window per member at a time. A `ComplianceOfficer` requests the approval, naming the `member_id`, the `calendar_year` it belongs to (between 2020 and 2100), the `solicitable_class_size` — how many of that member's executives the approval covers, at least 1 — and the two ISO dates bounding the window: `effective_date`, the day solicitation may begin, and `expires_at_date`, the last day it remains open. Both endpoints are inclusive. The request is refused with `ERR_CLASS_SIZE_EXCEEDED` when `solicitable_class_size` is greater than the member's own `restricted_class_size`.

Two window rules apply, and the collision test is evaluated **before** the shape test, so a request that both collides with an existing window and is itself malformed reports the collision. The collision test compares the requested window against the member's existing approvals in `REQUESTED` or `GRANTED` status under **closed-closed** semantics: both endpoints count as covered days, so two windows that merely touch at a single shared date do collide, and the request is refused with `ERR_PRIOR_APPROVAL_WINDOW_CONFLICT`. (Contrast this deliberately with the half-open coverage test on lobbying registrations in §3.5, where abutting windows are legal.) The shape test then requires that `effective_date` is not after `expires_at_date`, that both dates fall inside the stated `calendar_year`, and that the window spans no more than 365 days; a violation is refused with `ERR_PRIOR_APPROVAL_WINDOW_INVALID`. A new approval is written in `REQUESTED` status with `authorized_by_name`, `granted_at`, `granted_by_user_id` and `revoked_at` all null.

Only the member grants it. A `MemberDelegate` whose `X-User-ID` equals the approval's `member_id` moves the approval `REQUESTED → GRANTED`, supplying `authorized_by_name`, the name of the officer at the member company who signed off. The delegate's own member record must be `ACTIVE`, or the grant is refused with `ERR_MEMBER_NOT_ACTIVE`; and the logical clock's date must not have passed `expires_at_date`, or it is refused with `ERR_PRIOR_APPROVAL_EXPIRED` — an approval whose window has already elapsed cannot be resurrected by signing it late. On success the server stamps `granted_at` with the logical clock instant, records `granted_by_user_id` from `X-User-ID` (which by construction equals the `member_id`), and recomputes the member's `pac_solicitable`, which becomes true as soon as the clock's date lies within the window. Revocation is the mirror image and also belongs to the member: `GRANTED → REVOKED`, stamping `revoked_at`, and recomputing `pac_solicitable` back to false unless some other `GRANTED` approval of that member still covers the clock date. Both `REVOKED` and `EXPIRED` are terminal: an approval in either state never moves again. Granting anything that is not `REQUESTED`, or revoking anything that is not `GRANTED` — including one already expired — is refused with `ERR_INVALID_PRIOR_APPROVAL_STATE`.

The money itself lives in a **separate segregated fund**, opened by a `ComplianceOfficer` with a `name`, the `fund_year` it accounts for (2020 to 2100), the `jurisdiction_code` it files in, and a `min_reserve_cents` reserve floor. A new fund starts with `receipts_total_cents`, `committed_balance_cents`, `disbursed_total_cents`, `filing_fee_accrued_cents` and `available_balance_cents` all at 0, `filings_completed_count` at 0, `last_filed_period_code` null, and `posture` `OPEN`.

The fund's spendable balance is not stored independently of its parts. `available_balance_cents` is always `receipts_total_cents` reduced by `committed_balance_cents`, then by `disbursed_total_cents`, then by `filing_fee_accrued_cents`. And `posture` is a pure function of that balance: it reads `RESTRICTED` whenever `available_balance_cents` is strictly below `min_reserve_cents`, and `OPEN` otherwise. The system must satisfy a conservation identity before and after every fund-touching write: `receipts_total_cents` equals the sum of `available_balance_cents`, `committed_balance_cents`, `disbursed_total_cents` and `filing_fee_accrued_cents`.

Crediting a **receipt** is how money enters. The compliance officer names the contributing `member_id`, the `amount_cents` received, and the `received_date`. Eligibility is checked against the prior-approval record: that member must have an approval in `GRANTED` status whose window contains the logical clock's date, and a member with no such approval — including one whose approval was revoked or expired — is refused with `ERR_PRIOR_APPROVAL_NOT_GRANTED`. The receipt must also belong to the fund's accounting year: a `received_date` whose calendar year differs from the fund's `fund_year` is refused with `ERR_JURISDICTION_SCOPE_MISMATCH`. On success the `amount_cents` is added to `receipts_total_cents` and `available_balance_cents` is recomputed; the response is the fund itself. If the new balance has reached `min_reserve_cents`, the fund flips `RESTRICTED → OPEN`, and that flip reinstates every contribution of this fund sitting in `SUSPENDED` back to `PENDING_BOARD`, restoring each affected candidate's `pending_support_cents` by that contribution's `amount_cents`.

Running a **filing cycle** is the fund's regulatory calendar, and it is the only clock-driven sweep in the system. The compliance officer supplies the `period_code` being filed and the `filed_on_date` on which it was filed. The `period_code` must match the cadence shape of the fund's own jurisdiction, exactly as described in §3.6, or the run is refused with `ERR_PERIOD_CADENCE_MISMATCH`. What makes the cycle delicate is that its fee depends on the fund's posture while the posture depends on the fee, so the evaluation order is **pinned** and must be followed exactly:

1. Compute `available_balance_cents` from the accumulators as they stand before this cycle, using the existing `filing_fee_accrued_cents`.
2. Read the posture **as it was before this cycle** and assemble the fee from it. The fee is a base of 15,000 cents; plus a surcharge of 5,000 cents if and only if that pre-cycle posture was `RESTRICTED`; plus a late penalty of 25,000 cents if and only if `filed_on_date` falls after the due date of the named period, which is that period's last calendar day advanced by the filing lag for the fund's cadence — 20 days quarterly, 30 days semiannual. The posture recomputed later in this same request is never the value used here, so the surcharge is charged at most once per cycle and is never re-charged by the flip it may itself cause.
3. Add the fee to `filing_fee_accrued_cents`, increment `filings_completed_count` by one, set `last_filed_period_code` to the supplied `period_code`, and recompute `available_balance_cents` from the accumulators again.
4. Recompute `posture` from that post-fee balance and propagate the consequence. A flip `OPEN → RESTRICTED` suspends every contribution of this fund whose status is `PENDING_BOARD`, moving each to `SUSPENDED` and decrementing the corresponding candidate's `pending_support_cents` by that contribution's `amount_cents`; a flip `RESTRICTED → OPEN` reinstates every `SUSPENDED` contribution to `PENDING_BOARD` and increments each corresponding candidate's `pending_support_cents` again.
5. Sweep the prior approvals. Every approval whose status is `REQUESTED` or `GRANTED` and whose `expires_at_date` is earlier than the logical clock's date moves to `EXPIRED`; where the swept approval was `GRANTED`, the affected member's `pac_solicitable` is recomputed to false. `REQUESTED → EXPIRED` and `GRANTED → EXPIRED` are the only transitions the sweep performs, and no other endpoint performs them.

While the fund's posture is `RESTRICTED`, board approval of any contribution drawn on it is refused with `ERR_FUND_RESTRICTED`.

### 3.9. Candidate Contribution Decisions: Scoring, Ceilings, and the Three-Role Chain

Before money can be voted to anyone, the recipient must be on the books. A `GovAffairsDirector` registers a **candidate** with the `name` that will appear on the contribution check (non-empty, at most 200 characters), the `office` sought — `US_HOUSE`, `US_SENATE` or `STATE_ASSEMBLY` — the `jurisdiction_code` whose contribution limit applies, the `district_code` the candidate runs in, an `election_cycle` label such as `2026-GENERAL` (non-empty), an `incumbency` of `INCUMBENT`, `CHALLENGER` or `OPEN_SEAT`, a `voting_alignment_pct` recording the candidate's alignment with adopted association positions (a percentage from 0.00 to 100.00 with two decimals), and a `committee_relevance_score` from 0 to 100 rating how relevant the candidate's committee assignments are to association priorities. Four candidate fields are derived and start at 0: `latest_support_score`, `pending_support_cents`, `committed_support_cents` and `disbursed_support_cents`.

Proposing a contribution is likewise the director's act, and it names the `fund_id` the money would leave, the `candidate_id` receiving it, the `amount_cents` proposed (an integer of at least 1), and optionally a `memo` recording the decision rationale. Two figures are computed at proposal time and then **frozen** onto the row, never recomputed afterwards.

The first is `support_score`, the association's scoring criterion, assembled from four weighted components. Three come from the candidate record. The fourth is a cross-entity input, and it is what ties political money back to grassroots work: count the total `matched_member_count` across every action alert in the system whose `status` is `DISPATCHED` and whose `target_district_code` equals this candidate's `district_code` — alerts that resolved to `NO_MATCH` contribute nothing — then multiply that count by 10 and cap the result at 100. Call that capped figure the district engagement. The score is then forty-five hundredths of `voting_alignment_pct`, plus twenty-five hundredths of `committee_relevance_score`, plus twenty hundredths of an incumbency factor of 100 for an `INCUMBENT`, 60 for a `CHALLENGER` or 80 for an `OPEN_SEAT`, plus ten hundredths of the district engagement; that assembled sum is rounded half up to two decimals exactly once, at the end. The result is written to the contribution's `support_score` and also copied to the candidate's `latest_support_score`, which therefore always reflects the most recently created contribution for that candidate.

The second frozen figure is `max_allowed_cents`, the ceiling this proposal was measured against. Start from the per-candidate per-election limit for the candidate's jurisdiction — 500,000 cents federally, 250,000 in California, 100,000 in New York. The score then selects a share of that limit: a `support_score` of at least 85.00 earns the full limit, a score of at least 70.00 earns half of it, and a score of at least 55.00 earns a quarter of it. A score below 55.00 earns nothing and the proposal is refused outright with `ERR_SCORE_BELOW_FLOOR`; that floor check happens before any ceiling arithmetic. The tier allowance is the limit multiplied by the selected share, rounded half up to whole cents. Separately, compute what the candidate has already absorbed in this election cycle: the sum of `amount_cents` over that candidate's contributions whose status is `PENDING_BOARD`, `SUSPENDED`, `BOARD_APPROVED` or `DISBURSED`. Voided contributions are excluded from that sum, which is precisely why a void frees headroom again. The remaining room is the jurisdiction limit less that already-absorbed total, floored at 0. `max_allowed_cents` is then the smaller of the tier allowance and the remaining room. If the proposed `amount_cents` exceeds `max_allowed_cents` the proposal is refused with `ERR_CONTRIBUTION_LIMIT_EXCEEDED`; an amount exactly equal to `max_allowed_cents` is accepted, because the boundary is inclusive.

An accepted proposal is written in `PENDING_BOARD` status with `proposed_by_user_id` taken from `X-User-ID`, `board_approved_by_user_id`, `disbursed_at`, `voided_at` and `void_reason` all null, and it adds its `amount_cents` to the candidate's `pending_support_cents`.

Board approval belongs to a `BoardTrustee` and moves the contribution `PENDING_BOARD → BOARD_APPROVED`, recording `board_approved_by_user_id` from `X-User-ID`. Four gates apply, in the precedence order of §2.11. The contribution must be `PENDING_BOARD`: a row the fund's restricted posture pushed to `SUSPENDED` is refused specifically with `ERR_CONTRIBUTION_SUSPENDED`, while a row that is `BOARD_APPROVED`, `DISBURSED` or `VOIDED` is refused with `ERR_CONTRIBUTION_NOT_PENDING`. The approving trustee must differ from the proposer, per §2.10. The fund's `posture` must be `OPEN`, else `ERR_FUND_RESTRICTED`. And the amount must fit the fund: `amount_cents` must not exceed the fund's current `available_balance_cents`, with equality accepted, and an amount larger than the balance is refused with `ERR_INSUFFICIENT_FUND_BALANCE`.

Approval then runs a four-link cascade that is the mirror of adoption's:

- **Cascade link 1.** The fund's `committed_balance_cents` grows by the contribution's `amount_cents` and `available_balance_cents` is recomputed from the four accumulators. In the same step the candidate's `pending_support_cents` falls by that amount and its `committed_support_cents` rises by it, so the money moves between two candidate accumulators rather than being counted twice.
- **Cascade link 2.** If the recomputed `available_balance_cents` is now strictly below the fund's `min_reserve_cents`, the fund's `posture` flips `OPEN → RESTRICTED`.
- **Cascade link 3.** Because the posture became `RESTRICTED`, every *other* contribution of that fund still in `PENDING_BOARD` moves `PENDING_BOARD → SUSPENDED`.
- **Cascade link 4.** Because those rows left `PENDING_BOARD`, each of their candidates has `pending_support_cents` decremented by that row's `amount_cents`. A suspended row contributes to no candidate accumulator and to no fund accumulator at all.

Disbursement — cutting the check — belongs to a `ComplianceOfficer` and moves the contribution `BOARD_APPROVED → DISBURSED`, stamping `disbursed_at` with the logical clock instant. A contribution in any other status is refused with `ERR_CONTRIBUTION_NOT_APPROVED`. The contribution ceiling is re-examined at this point rather than trusted from proposal time: the row's `amount_cents` must still not exceed its frozen `max_allowed_cents`, and the candidate's counted total — the sum of `amount_cents` across its contributions in `PENDING_BOARD`, `SUSPENDED`, `BOARD_APPROVED` or `DISBURSED` status — must not exceed the jurisdiction's per-candidate per-cycle limit; a failure of either test is refused with `ERR_CONTRIBUTION_LIMIT_EXCEEDED`. On success the fund's `committed_balance_cents` falls by the amount and its `disbursed_total_cents` rises by it, which by design leaves `available_balance_cents` unchanged — the money was already reserved at approval. On the candidate, `committed_support_cents` falls by the amount and `disbursed_support_cents` rises by it.

Voiding is the universal compensating action, available to a `ComplianceOfficer` from four statuses and requiring a `void_reason` in the body. In every case the row moves to `VOIDED`, `voided_at` is stamped with the logical clock instant and the reason is recorded, and what is reversed depends strictly on which accumulators the row was feeding at the time:

- From `PENDING_BOARD`: the candidate's `pending_support_cents` falls by `amount_cents`. Nothing on the fund changes, because a pending row was never committed.
- From `SUSPENDED`: no accumulator changes at all, because a suspended row already contributes to no candidate total and no fund total.
- From `BOARD_APPROVED`: the fund's `committed_balance_cents` falls by `amount_cents`, `available_balance_cents` is recomputed upward, and the candidate's `committed_support_cents` falls by the amount.
- From `DISBURSED` — a returned check: the fund's `disbursed_total_cents` falls by `amount_cents`, `available_balance_cents` is recomputed upward, and the candidate's `disbursed_support_cents` falls by the amount.

In the two cases that raise the balance, the fund's `posture` is re-evaluated afterwards, and a flip `RESTRICTED → OPEN` reinstates every `SUSPENDED` contribution of that fund to `PENDING_BOARD` while restoring each affected candidate's `pending_support_cents`. After any void the conservation identity of §3.8 must still hold, and each of the three candidate accumulators must still equal the sum of `amount_cents` over that candidate's contributions in the single matching status — `pending_support_cents` over `PENDING_BOARD` rows, `committed_support_cents` over `BOARD_APPROVED` rows, `disbursed_support_cents` over `DISBURSED` rows — with `SUSPENDED` and `VOIDED` rows appearing in none of them. Restoring the grand total while leaving an individual term wrong is a failure, not a rounding difference.

## 4. Endpoint Definitions

Operations that bring a new, independently addressable resource into existence — enrolling a member, creating a committee, seating a member, drafting a position, casting a ballot, drafting a registration, logging an activity, opening a report, launching a campaign, dispatching an alert, requesting a prior approval, registering a candidate, opening a fund, proposing a contribution — return HTTP `201 Created`. Every other successful operation, including all reads, every state transition on an existing resource, and every write that mutates an existing aggregate such as a fund receipt or a filing cycle, returns HTTP `200 OK`. The table below is a routing summary only: the request payloads, the response contents and the side effects of each operation are specified in §2 and §3, and this table deliberately does not repeat them.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/advocacy/members` | Enroll an association member | AssociationAdmin |
| GET | `/advocacy/members/{id}` | Read one member | All roles |
| GET | `/advocacy/members/{id}/deductibility-notice` | Computed read: the member's dues-deductibility notice for its dues_year per calculation dues_deductibility_notice | AssociationAdmin, ComplianceOfficer, MemberDelegate |
| GET | `/advocacy/members/{id}/committee-seats` | List the member's committee seats, ordered by created_at ASC | All roles |
| GET | `/advocacy/members/{id}/position-votes` | List the member's ballots across all positions, ordered by created_at ASC | All roles |
| GET | `/advocacy/members/{id}/prior-approvals` | List the member's PAC prior-approval records, ordered by created_at ASC | AssociationAdmin, ComplianceOfficer, BoardTrustee, MemberDelegate |
| POST | `/advocacy/committees` | Create a policy committee | GovAffairsDirector |
| GET | `/advocacy/committees/{id}` | Read one committee including seat_count, total_voting_weight and roster_state | All roles |
| POST | `/advocacy/committees/{id}/seats` | Seat a member on the committee | GovAffairsDirector |
| GET | `/advocacy/committees/{id}/seats` | List the committee roster, ordered by created_at ASC | All roles |
| GET | `/advocacy/committees/{id}/policy-positions` | List the positions owned by this committee, ordered by created_at ASC | All roles |
| POST | `/advocacy/policy-positions` | Draft a policy position under a committee | GovAffairsDirector |
| GET | `/advocacy/policy-positions/{id}` | Read one position including the latest tally snapshot and dissent bookkeeping | All roles |
| POST | `/advocacy/policy-positions/{id}/open-ballot` | Open the next consensus ballot round (DRAFT or RECONSIDERATION -> BALLOTING) | GovAffairsDirector |
| POST | `/advocacy/policy-positions/{id}/votes` | Cast a ballot in the position's current round | MemberDelegate |
| GET | `/advocacy/policy-positions/{id}/votes` | List the ballots cast on this position, ordered by created_at ASC | All roles |
| POST | `/advocacy/policy-positions/{id}/votes/{vote_id}/withdraw-dissent` | The dissenting member withdraws its formal dissent (FILED -> WITHDRAWN) without changing the ballot itself | MemberDelegate |
| POST | `/advocacy/policy-positions/{id}/tally` | Close the current round and evaluate consensus per calculation position_ballot_tally: BALLOTING -> CONSENSUS_REACHED, RECONSIDERATION or FAILED_CONSENSUS | GovAffairsDirector |
| POST | `/advocacy/policy-positions/{id}/adopt` | The board ratifies a position that reached consensus (CONSENSUS_REACHED -> ADOPTED), unlocking lobbying activity and grassroots campaigns | BoardTrustee |
| GET | `/advocacy/policy-positions/{id}/lobbying-activities` | List the lobbying activities logged in support of this position, ordered by created_at ASC | GovAffairsDirector, ComplianceOfficer, BoardTrustee |
| GET | `/advocacy/policy-positions/{id}/grassroots-campaigns` | List the grassroots campaigns advancing this position, ordered by created_at ASC | All roles |
| POST | `/advocacy/lobbying-registrations` | Draft a lobbying registration for one jurisdiction | ComplianceOfficer |
| GET | `/advocacy/lobbying-registrations/{id}` | Read one registration including version, amendment_round and the year-to-date reportable accumulators | ComplianceOfficer, GovAffairsDirector, BoardTrustee |
| POST | `/advocacy/lobbying-registrations/{id}/file` | File the registration with the jurisdiction (DRAFT -> ACTIVE) | ComplianceOfficer |
| POST | `/advocacy/lobbying-registrations/{id}/amend` | Open a manual amendment (ACTIVE -> AMENDMENT_PENDING) | ComplianceOfficer |
| POST | `/advocacy/lobbying-registrations/{id}/certify-amendment` | Certify the pending amendment (AMENDMENT_PENDING -> ACTIVE) | ComplianceOfficer |
| POST | `/advocacy/lobbying-registrations/{id}/terminate` | Terminate coverage (ACTIVE -> TERMINATED) | ComplianceOfficer |
| GET | `/advocacy/lobbying-registrations/{id}/activities` | List the activities logged under this registration, ordered by created_at ASC | ComplianceOfficer, GovAffairsDirector, BoardTrustee |
| GET | `/advocacy/lobbying-registrations/{id}/expenditure-reports` | List the expenditure reports of this registration, ordered by created_at ASC | ComplianceOfficer, GovAffairsDirector, BoardTrustee |
| POST | `/advocacy/lobbying-activities` | Log one lobbying contact or spend under an ACTIVE registration in support of an ADOPTED position | GovAffairsDirector |
| POST | `/advocacy/lobbying-activities/{id}/void` | Void a logged activity (LOGGED -> VOIDED) and compensate every accumulator it fed | GovAffairsDirector |
| POST | `/advocacy/expenditure-reports` | Open an expenditure report for one registration and period | ComplianceOfficer |
| POST | `/advocacy/expenditure-reports/{id}/certify` | Certify and file the report (OPEN -> CERTIFIED) | ComplianceOfficer |
| POST | `/advocacy/grassroots-campaigns` | Launch a grassroots campaign for an ADOPTED position | GovAffairsDirector |
| GET | `/advocacy/grassroots-campaigns/{id}` | Read one campaign including alert_count, matched_member_total, cumulative_cost_cents, disclosure_required and last_alert_at | All roles |
| POST | `/advocacy/grassroots-campaigns/{id}/alerts` | Dispatch a member action alert for one district and chamber | GovAffairsDirector |
| GET | `/advocacy/grassroots-campaigns/{id}/alerts` | List the campaign's action alerts, ordered by created_at ASC | All roles |
| POST | `/advocacy/grassroots-campaigns/{id}/close` | Close the campaign (PLANNED or LIVE -> CLOSED), freezing cumulative_cost_cents and disclosure_required | GovAffairsDirector |
| POST | `/advocacy/prior-approvals` | Request a member's PAC prior approval for one calendar year | ComplianceOfficer |
| POST | `/advocacy/prior-approvals/{id}/grant` | The member itself grants the prior approval (REQUESTED -> GRANTED) | MemberDelegate |
| POST | `/advocacy/prior-approvals/{id}/revoke` | The member withdraws its prior approval (GRANTED -> REVOKED), closing PAC solicitation eligibility | MemberDelegate |
| POST | `/advocacy/candidates` | Register a candidate for contribution scoring | GovAffairsDirector |
| GET | `/advocacy/candidates/{id}` | Read one candidate including latest_support_score and the three support accumulators | GovAffairsDirector, ComplianceOfficer, BoardTrustee |
| GET | `/advocacy/candidates/{id}/pac-contributions` | List the contributions decided for this candidate, ordered by created_at ASC | GovAffairsDirector, ComplianceOfficer, BoardTrustee |
| POST | `/advocacy/segregated-funds` | Open the separate segregated fund for one accounting year and jurisdiction | ComplianceOfficer |
| GET | `/advocacy/segregated-funds/{id}` | Read the fund's four accumulators, available_balance_cents and posture | ComplianceOfficer, GovAffairsDirector, BoardTrustee |
| GET | `/advocacy/segregated-funds/{id}/pac-contributions` | List the contributions drawn on this fund, ordered by created_at ASC | ComplianceOfficer, GovAffairsDirector, BoardTrustee |
| POST | `/advocacy/segregated-funds/{id}/receipts` | Credit a solicited receipt from a member whose PAC prior approval is GRANTED and covers the logical clock date | ComplianceOfficer |
| POST | `/advocacy/segregated-funds/{id}/filing-cycle` | Run the regulatory filing calendar for one period | ComplianceOfficer |
| POST | `/advocacy/pac-contributions` | Propose a candidate contribution | GovAffairsDirector |
| GET | `/advocacy/pac-contributions/{id}` | Read one contribution including its frozen support_score and max_allowed_cents | GovAffairsDirector, ComplianceOfficer, BoardTrustee |
| POST | `/advocacy/pac-contributions/{id}/board-approve` | Board approval of a pending contribution (PENDING_BOARD -> BOARD_APPROVED) | BoardTrustee |
| POST | `/advocacy/pac-contributions/{id}/disburse` | Cut the check (BOARD_APPROVED -> DISBURSED) | ComplianceOfficer |
| POST | `/advocacy/pac-contributions/{id}/void` | Compensating void from PENDING_BOARD, SUSPENDED, BOARD_APPROVED or DISBURSED | ComplianceOfficer |
| POST | `/_clock/set_current_utc` | Test-only logical clock | AssociationAdmin, GovAffairsDirector, ComplianceOfficer, BoardTrustee |

## 5. Error Code Catalogue

Every error response carries the envelope of §2.2, with the identifier below in the `error_id` field and a human-readable `message`. The conditions that trigger each identifier are stated where the rule they guard is described — the precedence order among them is in §2.11 — and are deliberately not repeated here.

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_MEMBER_SCOPE_VIOLATION` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_MEMBER_NOT_FOUND` | 404 |
| `ERR_COMMITTEE_NOT_FOUND` | 404 |
| `ERR_POSITION_NOT_FOUND` | 404 |
| `ERR_VOTE_NOT_FOUND` | 404 |
| `ERR_REGISTRATION_NOT_FOUND` | 404 |
| `ERR_ACTIVITY_NOT_FOUND` | 404 |
| `ERR_REPORT_NOT_FOUND` | 404 |
| `ERR_CAMPAIGN_NOT_FOUND` | 404 |
| `ERR_PRIOR_APPROVAL_NOT_FOUND` | 404 |
| `ERR_CANDIDATE_NOT_FOUND` | 404 |
| `ERR_FUND_NOT_FOUND` | 404 |
| `ERR_CONTRIBUTION_NOT_FOUND` | 404 |
| `ERR_INVALID_POSITION_STATE` | 409 |
| `ERR_INVALID_REGISTRATION_STATE` | 409 |
| `ERR_INVALID_REPORT_STATE` | 409 |
| `ERR_INVALID_CAMPAIGN_STATE` | 409 |
| `ERR_INVALID_PRIOR_APPROVAL_STATE` | 409 |
| `ERR_DISSENT_NOT_FILED` | 409 |
| `ERR_ACTIVITY_ALREADY_VOIDED` | 409 |
| `ERR_CONTRIBUTION_NOT_PENDING` | 409 |
| `ERR_CONTRIBUTION_NOT_APPROVED` | 409 |
| `ERR_CONTRIBUTION_SUSPENDED` | 409 |
| `ERR_COMMITTEE_FORMING` | 409 |
| `ERR_COMMITTEE_NOT_QUORATE` | 409 |
| `ERR_REGISTRATION_NOT_ACTIVE` | 409 |
| `ERR_PRIOR_APPROVAL_NOT_GRANTED` | 409 |
| `ERR_PRIOR_APPROVAL_EXPIRED` | 409 |
| `ERR_FUND_RESTRICTED` | 409 |
| `ERR_POSITION_NOT_ADOPTED` | 409 |
| `ERR_MEMBER_NOT_SEATED` | 409 |
| `ERR_MEMBER_NOT_ACTIVE` | 409 |
| `ERR_COALITION_PARTNER_REQUIRED` | 422 |
| `ERR_JURISDICTION_SCOPE_MISMATCH` | 422 |
| `ERR_PRIOR_APPROVAL_WINDOW_CONFLICT` | 409 |
| `ERR_PRIOR_APPROVAL_WINDOW_INVALID` | 422 |
| `ERR_REGISTRATION_COVERAGE_OVERLAP` | 409 |
| `ERR_ALERT_COOLING_PERIOD` | 409 |
| `ERR_ACTIVITY_OUTSIDE_COVERAGE` | 422 |
| `ERR_PERIOD_CADENCE_MISMATCH` | 422 |
| `ERR_PERIOD_NOT_CLOSED` | 409 |
| `ERR_DUPLICATE_SEAT` | 409 |
| `ERR_CHAIR_SEAT_TAKEN` | 409 |
| `ERR_MAX_BALLOT_ROUNDS` | 409 |
| `ERR_NO_BALLOTS_CAST` | 409 |
| `ERR_DISSENT_REQUIRES_OPPOSE` | 409 |
| `ERR_EMPTY_ACTIVITY` | 422 |
| `ERR_EMPTY_REPORT` | 422 |
| `ERR_OPEN_REPORT_BLOCKS_TERMINATION` | 422 |
| `ERR_ACTIVITY_IN_CERTIFIED_REPORT` | 422 |
| `ERR_CLASS_SIZE_EXCEEDED` | 422 |
| `ERR_SCORE_BELOW_FLOOR` | 422 |
| `ERR_CONTRIBUTION_LIMIT_EXCEEDED` | 422 |
| `ERR_INSUFFICIENT_FUND_BALANCE` | 422 |
| `ERR_STALE_REGISTRATION_VERSION` | 412 |
