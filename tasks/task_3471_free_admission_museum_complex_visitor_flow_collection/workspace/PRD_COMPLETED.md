# Museum Campus Collections API — Product Requirements Document

## 1. Introduction

This document specifies the application programming interface for the visitor-flow and collections-management platform of a campus of free-admission museums, operated in the spirit of a national institution such as the Smithsonian. General admission is never charged: any visitor may walk in, and only selectively deployed, high-demand museums and exhibitions meter their intake through timed entry passes. Around that free core, the campus coordinates security-screening throughput at museum entrances, a fee-based special exhibition program with member presale windows and member pricing, a volunteer docent corps, weekly education programs with school-group scheduling, and research access to the collection for external scholars.

On the collections side, the platform governs the full life of an object beyond the gallery wall. Loan agreements with borrowing institutions are negotiated through formal counter-offer rounds, gated on condition reporting, courier requirements, and insurance-or-indemnity coverage. Acquisitions and deaccessions pass through collections-committee review with strict segregation of duties and explicit cultural-property (repatriation) compliance. All money lives in fund accounts that enforce the separation between federal appropriations and trust (private or revenue) funds — including which activities each may lawfully support — and every date and datetime rule in the system reads a server-side logical clock rather than the wall clock, so that time-dependent behavior is deterministic and testable.

The API is mounted under the `/campus` prefix, with a single test-driving capability for the logical clock mounted outside it.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID` and `X-User-Role`. If either header is missing or empty, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the named role is not in the endpoint's authorized roles list, or an ownership rule is violated, the request is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

The fifteen roles, spelled exactly as the server recognizes them, are: `PlatformAdmin`, `VisitorServices`, `SecurityScreener`, `ExhibitionManager`, `ProgramCoordinator`, `Docent`, `Public`, `Member`, `LoansOfficer`, `BorrowerRep`, `Registrar`, `Curator`, `CommitteeChair`, `FinanceOfficer`, and `Scholar`.

Two roles are entity-backed. When `X-User-Role` is `Docent`, `X-User-ID` is the `id` of the acting `Docent`; ownership checks on any resource that references a `Docent` compare the resource's `docent_id` field to `X-User-ID`. When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member`; ownership checks on any resource that references a `Member` compare the resource's `member_id` or `holder_member_id` field to `X-User-ID`. For the remaining thirteen roles — `PlatformAdmin`, `VisitorServices`, `SecurityScreener`, `ExhibitionManager`, `ProgramCoordinator`, `Public`, `LoansOfficer`, `BorrowerRep`, `Registrar`, `Curator`, `CommitteeChair`, `FinanceOfficer`, and `Scholar` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example as `created_by_user_id` on a timed entry pass, school group reservation, or research access request, or as `submitted_by_user_id` and `decided_by_user_id` on a collection review) but does not compare it to any entity's `id` — except where an explicit ownership rule says otherwise: a `Public` caller may cancel only a pass or school group reservation whose recorded creator equals the caller's `X-User-ID`, a `Member` caller may purchase only with a `member_id` equal to their own `X-User-ID`, may cancel a pass only as its holder, and may read only the member record whose `id` equals their `X-User-ID`, a `Docent` caller may confirm only their own assignment, and a `Curator` caller may submit only a review they created.

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

List endpoints accept two query parameters, `limit` and `offset`. The `limit` parameter defaults to 10, with a minimum of 1 and a maximum of 100; the `offset` parameter defaults to 0 and may not be negative. A `limit` or `offset` that is not an integer, or a value outside these bounds, is rejected with `ERR_INVALID_REQUEST`. List results are always sorted by `created_at` ascending; resources created within the same timestamp are ordered by creation sequence. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`, where `has_more` is true exactly when `offset` plus the number of items in the returned page is less than `total_count`. In addition to the pagination parameters, each list endpoint accepts the filter fields named for it in the endpoint table and the workflow narratives (for example `museum_id`, `visit_date`, `holder_member_id`, `revenue_fund_id`, `exhibition_id`, `member_id`, `program_id`, `docent_id`, `object_id`, `fund_id`, `review_id`, or `loan_id` where applicable).

### 2.4. The Logical Clock and the Quarter-Hour Entry Grid

The campus runs on a server-side logical clock, never the wall clock. At startup — before any clock-setting call — the logical clock reads exactly 2026-09-01T00:00:00Z. A `PlatformAdmin` may advance or set the clock through the test-driving capability mounted at `/_clock/set_current_utc`, outside the `/campus` prefix, by supplying a `current_utc` datetime; the endpoint responds with the echo of that `current_utc`. Every date and datetime comparison in this document — presale windows, pass expiry, member lapse, visit dates, closure dates — reads the logical clock. Two lazy evaluations hang off it: a reserved pass is evaluated for expiry against the clock when admission is attempted, and a member's standing is recomputed from the clock on every member read and every member-linked purchase.

All calendar dates are ISO calendar dates in YYYY-MM-DD form, and all datetimes are ISO 8601 UTC. A museum entry day runs from 10:00 to 17:30 UTC, divided into thirty quarter-hour slots. A pass reserves one slot through `entry_quarter_hour`, an integer slot index from 0 to 29 inclusive, where slot 0 begins at 10:00 UTC. The current slot index at any moment is the whole number of complete fifteen-minute intervals elapsed since 10:00 UTC that day. Admission carries a grace window of two slots — thirty minutes — beyond the reserved slot.

### 2.5. Resource Identity, Timestamps, Versions, and Path Validation

Every resource in the system carries four common properties. The `id` is a server-minted UUID with no type prefix. The `created_at` and `updated_at` timestamps are ISO 8601 UTC datetimes with three fractional digits. The `version` is an integer that increments by one on every mutation of the resource. Consistency is immediate: every mutation is visible in the response to the very request that performed it.

Where an endpoint path nests one resource beneath another — a museum above its timed entry passes, exhibitions, or education programs, an exhibition above its tickets, a program above its docent assignments, a collection object above its loan agreements, a loan above its condition reports, a fund above its expenditures — path-referenced resources are validated for existence left to right along the path: the museum before the exhibition before the ticket, and so on. A missing path-referenced or body-referenced resource yields `ERR_NOT_FOUND` (HTTP 404); body-referenced foreign keys such as `member_id`, `program_id`, `docent_id`, `object_id`, and `fund_id` are validated the same way.

### 2.6. Optimistic Concurrency Control

Three write endpoints carry optimistic concurrency control on a parent entity's `version`; no other endpoint takes a version field. Within the validation pipeline of §2.8, the staleness check runs immediately after transition legality and before the remaining request-shape checks; a request that omits the expected-version field, or carries one that is not an integer, fails at the request-shape stage with `ERR_INVALID_REQUEST`.

Countering a loan agreement — whether by the `BorrowerRep` or the `LoansOfficer` — requires the request to carry `expected_loan_version`, holding the `version` of the loan agreement the writer last observed. If the loan's current `version` has advanced beyond that value (the canonical case: the lender's counter legitimately supersedes the borrower's view, and a second counter carrying the pre-counter version is stale), the request is rejected with `ERR_STALE_LOAN_VERSION` (HTTP 412).

Accepting a loan agreement likewise requires `expected_loan_version` matching the loan's current `version`. An intervening counter bumps both `version` and `negotiated_round`, so an acceptor working from an older read has not seen the current terms; the mismatch is rejected with `ERR_STALE_LOAN_VERSION` (HTTP 412).

Deciding a collection review requires `expected_review_version` matching the review's current `version`. If the review's version has advanced since the chair last read it — for example because the curator re-submitted amended terms, which bumps the version — the decision is rejected with `ERR_STALE_REVIEW_VERSION` (HTTP 412).

### 2.7. Money, Precision, and the Federal–Trust Separation

All monetary quantities are integer cents. Where a calculation produces a fractional cent, the result is rounded half up to whole cents, and each calculation in this document pins exactly where that rounding is applied.

Funds are divided by `fund_type` into `FEDERAL` (congressional appropriation) and `TRUST` (private or revenue money), and the separation is legally load-bearing. Appropriated funds may support only `OPERATIONS` and `EDUCATION` activity; charging `ACQUISITION` or `EXHIBITION` activity to a `FEDERAL` fund is rejected with `ERR_FUND_ACTIVITY_NOT_PERMITTED` (HTTP 422). A `TRUST` fund permits all four activity types — `OPERATIONS`, `EDUCATION`, `ACQUISITION`, and `EXHIBITION`. Exhibition ticket revenue is trust money: an exhibition's `revenue_fund_id` must reference a `TRUST` fund, and referencing a `FEDERAL` fund is rejected with `ERR_NOT_TRUST_FUND` (HTTP 422).

Every fund reports two availability figures. The settled figure, `settled_available_cents`, is the fund's `appropriation_cents` plus its `receipts_cents`, minus the summed `amount_cents` of its expenditures still in `POSTED` status (`VOIDED` expenditures are excluded). The committed figure, `committed_available_cents`, subtracts from the settled figure the summed `estimated_cost_cents` of every `ACQUISITION` collection review in `APPROVED` status that has not yet been executed against this fund. All spending gates — expenditure creation, acquisition approval, and acquisition execution — are validated against the conservative committed figure, never the settled one. For example, given an appropriation of 1,000,000,000 cents, posted expenditures of 120,000,000 cents, and one approved-but-unexecuted acquisition estimated at 300,000,000 cents, the settled figure reads 880,000,000 cents while the committed figure reads 580,000,000 cents; an expenditure of 700,000,000 cents would pass the settled reading but is rejected with `ERR_INSUFFICIENT_FUND_AVAILABLE` (HTTP 409) because the committed reading governs.

A `TRUST` fund's `receipts_cents` is computed as the sum of `price_paid_cents` over tickets in `PURCHASED` or `REDEEMED` status for exhibitions naming the fund. Ticket purchases credit receipts; refunds and the exhibition-close cascade debit them — each refund debit is exactly the refunded ticket's `price_paid_cents`, cancelling that ticket's earlier purchase credit, so a `REFUNDED` ticket nets to zero and contributes nothing to the sum.

### 2.8. Validation Order: First Failure Wins

Request validation is a single ordered pipeline. When several checks would fail, the earliest check in this order produces the error, and later checks are never evaluated:

1. **Authentication** — the `X-User-Role` and `X-User-ID` headers are present and non-empty, else `ERR_UNAUTHENTICATED`.
2. **Authorization and ownership** — the role appears in the endpoint's authorized list, and ownership rules hold (a member acting as themself, a docent acting as themself, a group organizer acting as the recorded creator, a curator submitting only their own review), else `ERR_UNAUTHORIZED_ROLE`.
3. **Path existence** — path-referenced resources exist, validated left to right, else `ERR_NOT_FOUND`.
4. **Body reference existence** — foreign-key identifiers carried in the request body reference existing resources, else `ERR_NOT_FOUND`.
5. **Transition legality** — the target resource stands in a state from which the requested transition exists, else `ERR_INVALID_STATE`.
6. **Fund availability of status** — the fund is `ACTIVE` for expenditure creation and for acquisition decision and execution, else `ERR_FUND_FROZEN`.
7. **Segregation of duties** — the deciding chair is not the review's recorded submitter, else `ERR_SEGREGATION_OF_DUTIES`.
8. **Cultural property clearance** — deaccession of an object flagged as cultural property requires the cultural-property review to be complete, else `ERR_CULTURAL_PROPERTY_REVIEW_PENDING`.
9. **Request shape** — required fields are present, enumerations and ranges are valid (slot index between 0 and 29 inclusive, dates well-formed, an end strictly after its start), declared-unique fields do not collide with an existing resource (`museum_code`, member `email`, object `accession_number`, `fund_code`), and the review-kind field pairing holds (an `ACQUISITION` review carries `fund_id`, `estimated_cost_cents`, and `proposed_object_title` with a null `object_id`; a `DEACCESSION` review carries `object_id` and `disposal_method` with a null `fund_id`), else `ERR_INVALID_REQUEST`.
10. **Duplicate pass** — at most one non-terminal pass exists per visitor name, museum, and visit date, else `ERR_DUPLICATE_PASS`.
11. **Gallery schedule** — a new education program's buffer-expanded gallery interval does not intersect another scheduled program in the same museum, gallery, and weekday, else `ERR_GALLERY_SCHEDULE_CONFLICT`.
12. **Docent eligibility** — the docent's certification meets the program's requirement, the docent is active, and the docent is not already assigned to another scheduled program on the same service date, else `ERR_DOCENT_NOT_CERTIFIED`.
13. **Closure dates** — the museum is not closed on the relevant visit date for pass reservation, ticket purchase, or school reservation creation, else `ERR_MUSEUM_CLOSED_ON_DATE`; passes already reserved on a date that later closes are expired by the closure cascade instead.
14. **Sale windows** — a purchase before the member presale opens fails `ERR_SALE_NOT_OPEN`; a non-member purchase during the presale window fails `ERR_PRESALE_MEMBER_ONLY`; a lapsed member on a presale or member-priced purchase fails `ERR_MEMBER_LAPSED`.
15. **Visit-day temporal rules** — admission within the grace window, refunds on or before the visit date, redemption exactly on the visit date, else `ERR_PASS_EXPIRED`, `ERR_REFUND_WINDOW_CLOSED`, or `ERR_VISIT_DATE_MISMATCH` respectively.
16. **Capacities** — slot quota before daily quota for passes (`ERR_SLOT_QUOTA_EXHAUSTED` then `ERR_DAILY_QUOTA_EXHAUSTED`), the daily ticket quota (`ERR_TICKET_QUOTA_EXHAUSTED`), screening throughput at admission (`ERR_SCREENING_THROUGHPUT_FULL`), and group size against the program's hard cap (`ERR_GROUP_TOO_LARGE`).
17. **Loan referential integrity** — at loan acceptance, no window overlap with agreed or active loans of the same object (`ERR_LOAN_PERIOD_CONFLICT`) and terms that satisfy the courier and indemnity minimums (`ERR_COURIER_REQUIRED`, `ERR_INDEMNITY_MINIMUM_NOT_MET`, `ERR_INDEMNITY_REQUIRES_COURIER`); activation and closure require the accepted condition reports (`ERR_CONDITION_REPORT_REQUIRED`); and object-in-collection requirements (`ERR_OBJECT_NOT_IN_COLLECTION`).
18. **Object availability for deaccession and research** — no active loan on the object at deaccession decision or execution (`ERR_OBJECT_ON_ACTIVE_LOAN`), and no visit-visit or visit-loan overlap at research approval (`ERR_RESEARCH_VISIT_CONFLICT`, `ERR_OBJECT_RESERVED_FOR_LOAN`).
19. **Fund activity permission** — the activity type is permitted for the fund's type, else `ERR_FUND_ACTIVITY_NOT_PERMITTED`.
20. **Fund sufficiency** — the amount does not exceed the fund's committed availability, else `ERR_INSUFFICIENT_FUND_AVAILABLE`.

Five checks attach to single endpoint families and are not numbered above; their pipeline positions are pinned here. The timed-pass-flag check at pass reservation (`ERR_TIMED_PASS_NOT_USED_HERE`) runs after request shape and before the duplicate-pass check. The trust-fund check at exhibition creation (`ERR_NOT_TRUST_FUND`) runs after request shape. The program-state check (`ERR_PROGRAM_NOT_SCHEDULED`) runs immediately after body-reference existence at docent-assignment and school-reservation creation, and immediately after transition legality at docent-assignment confirmation. The weekday check (`ERR_PROGRAM_DAY_MISMATCH`) runs after request shape — before docent eligibility at assignment creation, and after the group-size cap at school-reservation creation. The parent-loan liveness check at condition-report decision runs after request shape and is reported as `ERR_INVALID_STATE`.

### 2.9. Cascades and Batch State Changes

Several operations fan out beyond their primary target, and every cascade link is normative. Emergency-closing a museum day appends the date to the museum's `closed_dates` and flips every reserved pass at that museum on that date to `EXPIRED` in one batch. Closing a special exhibition flips every still-`PURCHASED` ticket of the exhibition to `REFUNDED` and, transitively, debits the revenue fund's computed receipts by each refunded ticket's `price_paid_cents`. Cancelling an education program flips its `CONFIRMED` and `WAITLISTED` school group reservations to `CANCELLED`, and conditionally flips its docent assignments: those still `ASSIGNED` move to `RELEASED`, while `CONFIRMED` assignments are deliberately left untouched. Executing an approved deaccession review produces the deepest chain: the object leaves the collection, every non-terminal loan agreement for the object is cancelled, and every non-terminal condition report of each cancelled loan is cancelled in turn. Separately, a cancelled confirmed school reservation releases its headcount and re-runs waitlist promotion for its program and date, and a docent confirmation can likewise free the head of the waitlist.

## 3. Business Logic & Workflows

### 3.1. Museums, Closure Days, and the Timed Entry Grid

A `PlatformAdmin` onboards each museum of the campus with a unique `museum_code` (for example NMAH), a public `display_name`, and the flag `requires_timed_pass`, which is true when the museum admits only visitors holding a timed entry pass. Capacity comes in three numbers: `quarter_hour_pass_quota`, the maximum number of reserved passes in any single entry slot and at least 1; `daily_pass_quota`, the maximum number of reserved-plus-admitted passes across a whole visit date and at least as large as the quarter-hour quota; and `screening_rate_per_quarter_hour`, the maximum number of admissions security can process per slot, also at least 1. A new museum's `closed_dates` list starts empty.

When a museum must close on short notice, the `PlatformAdmin` performs a close-day action carrying a `closure_date`. The date is appended to `closed_dates`, the museum's `version` increments by 1, and every reserved pass at that museum on that date flips to `EXPIRED` in a single batch — holders of those passes never need to cancel, and the date is thereafter unusable for new reservations. Closing a date already present in `closed_dates` succeeds without appending a duplicate entry; the version still increments.

Reserving a pass is open to `Public` callers, `Member` callers, and `VisitorServices` staff, and is always free. The request names a `visitor_name`, a `visit_date`, and an `entry_quarter_hour` slot index, and may optionally carry a `holder_member_id`, which is validated for existence when present but is not compared against the caller's `X-User-ID` at reservation time; the server records the caller in `created_by_user_id`. Reservation at a museum whose `requires_timed_pass` is false is rejected with `ERR_TIMED_PASS_NOT_USED_HERE`. A `visit_date` appearing in the museum's `closed_dates` is rejected with `ERR_MUSEUM_CLOSED_ON_DATE`. One visitor may hold only one non-terminal pass per museum and date: a second reservation for the same `visitor_name`, museum, and `visit_date` while a `RESERVED` or `ADMITTED` pass exists is rejected with `ERR_DUPLICATE_PASS`.

Quota evaluation then runs in a fixed order. Counting only passes in `RESERVED` or `ADMITTED` status — `CANCELLED` and `EXPIRED` never consume quota — the server first compares the requested slot's occupancy against `quarter_hour_pass_quota`: when the slot is already full the reservation fails with `ERR_SLOT_QUOTA_EXHAUSTED`. Only if the slot has room does the server compare the date's total occupancy against `daily_pass_quota`, failing with `ERR_DAILY_QUOTA_EXHAUSTED` when the date is full even though the slot is not. The boundary is exact: a slot occupancy one below the quota succeeds, and occupancy equal to the quota fails. A successful reservation lands in `RESERVED` status with `admitted_slot` still null.

Admission is performed by a `SecurityScreener` at the checkpoint. A pass admits only on its `visit_date`, and only while the current slot index is no more than two slots — thirty minutes — beyond the pass's `entry_quarter_hour`. An admission attempted after that grace window first flips the pass to `EXPIRED` and then fails with `ERR_PASS_EXPIRED`; an admission attempted on any date other than the visit date likewise flips the pass to `EXPIRED` and fails with `ERR_PASS_EXPIRED`, since the visit date and the current date no longer align. Within the window, the screening lane itself is the last gate: when the number of passes already admitted at this museum on this date in the current slot equals `screening_rate_per_quarter_hour` — equality means full — admission is rejected with `ERR_SCREENING_THROUGHPUT_FULL`. A successful admission moves the pass `RESERVED` to `ADMITTED`, records the current slot index in `admitted_slot`, and bumps the pass's `version`.

Cancellation releases capacity. The caller must be a `Public` caller whose `X-User-ID` equals the pass's `created_by_user_id`, a `Member` caller whose `X-User-ID` equals the pass's `holder_member_id`, or `VisitorServices`; the pass moves `RESERVED` to `CANCELLED`, and both the slot quota and the daily quota for the pass's museum, date, and slot become reservable again.

For operational awareness, a museum read exposes `screening_backlog_minutes` for the current slot. The reported figure is the forward-looking variant: count the passes still `RESERVED` at the museum for the current logical date whose `entry_quarter_hour` is at or before the current slot, subtract one slot of screening throughput, floor the difference at zero, and multiply by fifteen minutes. An alternative realized reading — extrapolating from admissions so far today divided by the number of slots elapsed so far today, never fewer than one, projected forward — is documented for operations dashboards but is never the server-reported value; the two diverge whenever the reserved and admitted paces differ.

### 3.2. Membership, Presale Windows, and Special Exhibition Ticketing

Anyone may register as a member through a `Public` self-registration or a `VisitorServices` assisted registration, supplying a `full_name`, a unique `email`, and a `membership_term_months` of at least one whole month. The server computes `expires_on` as the join date plus the term in calendar months — clamping the day-of-month to the target month's length when the join day does not exist in it — and derives `member_status` on every read and every member-linked purchase: the member is `ACTIVE` when the current logical date is on or before `expires_on`, and `LAPSED` from the day after. There are no member mutation endpoints beyond creation; lapse is purely a function of the clock.

Special exhibitions are the one place the campus charges money. An `ExhibitionManager` creates an exhibition under its host museum with a `title`, a full public unit price `fee_cents` in cents (which may be zero), a `daily_ticket_quota` of at least 1, and the two sale instants `member_presale_opens_at` and `public_sale_opens_at`, where the public instant must be strictly after the member instant. The exhibition's `revenue_fund_id` names the fund that receives ticket receipts and absorbs refund debits, and it must reference a `TRUST` fund — pointing it at a `FEDERAL` fund is rejected with `ERR_NOT_TRUST_FUND`, because ticket revenue is trust money. A new exhibition stands in `DRAFT`. The manager then moves it `DRAFT` to `ON_SALE` by opening the sale, and finally `ON_SALE` to `CLOSED` by closing it.

Purchasing a ticket is open to `Public` and `Member` callers and carries a `buyer_name`, a `visit_date`, and optionally a `member_id`; when the caller's role is `Member`, the `member_id` must equal the caller's `X-User-ID`. The sale windows are half-open at their opening instants. Before `member_presale_opens_at`, every purchase fails with `ERR_SALE_NOT_OPEN` — as does any purchase against an exhibition that is not in `ON_SALE`. From `member_presale_opens_at` until strictly before `public_sale_opens_at`, only a purchase naming an `ACTIVE` member succeeds; a non-member purchase in that window fails with `ERR_PRESALE_MEMBER_ONLY`, and at exactly `public_sale_opens_at` a non-member purchase succeeds. A purchase that names a member whose `member_status` has become `LAPSED` fails with `ERR_MEMBER_LAPSED`, whether it sought presale access or member pricing.

Pricing is locked at purchase into `price_paid_cents`. When a `member_id` is present and the member is `ACTIVE`, the unit price is the exhibition's `fee_cents` reduced by a member discount of twenty percent, rounded half up to whole cents per single ticket: a fee of 2,500 cents prices at 2,000, a fee of 2,499 prices at 1,999, and a fee of 2,501 prices at 2,001. Otherwise the full `fee_cents` applies. Each purchase also consumes one unit of the daily quota: counting tickets of the exhibition for the requested `visit_date` in `PURCHASED` or `REDEEMED` status, a purchase is allowed only while that count is strictly below `daily_ticket_quota`; a count equal to the quota means exhaustion and is rejected with `ERR_TICKET_QUOTA_EXHAUSTED`. `REFUNDED` tickets never count. The invariant for every exhibition and date is that the sold count plus the remaining count always equals `daily_ticket_quota`. A successful purchase lands in `PURCHASED` status and credits the revenue fund's `receipts_cents` by the `price_paid_cents`.

Two exits exist from `PURCHASED`. A `VisitorServices` refund is permitted only while the current logical date is on or before the ticket's `visit_date`; a later attempt is rejected with `ERR_REFUND_WINDOW_CLOSED`. The refund moves the ticket to `REFUNDED`, debits the revenue fund's receipts by the `price_paid_cents`, and frees the daily quota for the exhibition and date. A `SecurityScreener` redemption happens at the exhibition entrance exactly on the ticket's `visit_date` — any other date fails with `ERR_VISIT_DATE_MISMATCH` — and only while the exhibition is still `ON_SALE` (redemption against an exhibition in any other status is rejected with `ERR_INVALID_STATE`); redemption moves the ticket `PURCHASED` to `REDEEMED`.

Closing the exhibition is the bulk exit: every ticket still `PURCHASED` flips to `REFUNDED`, and each such automatic refund debits the exhibition's revenue fund receipts by that ticket's `price_paid_cents`. After the cascade, no purchasable or redeemable inventory remains.

### 3.3. Education Programs, Docents, and School Group Visits

A `ProgramCoordinator` builds the campus's weekly education calendar. Each program is created under a museum with a `title`, a `gallery_code` identifying the room, a `day_of_week` drawn from `MON`, `TUE`, `WED`, `THU`, `FRI`, `SAT`, and `SUN` on which the program recurs weekly, and a session window given as `start_minute` and `end_minute` in minutes since midnight UTC — each between 0 and 1439, with the end strictly after the start. Capacity and staffing policy arrive as `student_capacity` (the maximum summed headcount of confirmed reservations per visit date, at least 1), `docent_ratio` (one confirmed docent required per this many students, at least 1), `max_group_size` (a hard cap on any single reservation's headcount, at least 1), and `required_docent_certification`, the minimum certification a docent must hold: `BASIC`, `ADVANCED`, or `EXPERT`. A new program stands in `SCHEDULED`.

Gallery time is protected by a setup buffer. Each program occupies its gallery from thirty minutes before its `start_minute` until its `end_minute`, as a half-open interval — the buffer extends the session's start only, never its end. Two programs conflict when they share the same museum, the same `gallery_code`, and the same `day_of_week`, and their buffer-expanded intervals intersect; creation of the second is rejected with `ERR_GALLERY_SCHEDULE_CONFLICT`. A gap of exactly thirty minutes between sessions is allowed — the expanded intervals touch but do not overlap.

Docents are volunteers registered by a `ProgramCoordinator` with a `full_name`, a `certification_level` of `BASIC`, `ADVANCED`, or `EXPERT`, and an `active` flag that defaults to true. Assigning a docent to a program service date names a `docent_id` and a `service_date`; the assignment is born in `ASSIGNED` status. Three eligibility gates guard assignment, all reported as `ERR_DOCENT_NOT_CERTIFIED` (HTTP 422): the docent's certification must meet the program's `required_docent_certification`, the docent must be active, and the docent must not already hold a live assignment — one still `ASSIGNED` or `CONFIRMED` — to another `SCHEDULED` program on the same `service_date` (a `RELEASED` assignment does not block). Two further guards sit alongside: the `service_date` must fall on the program's `day_of_week`, else `ERR_PROGRAM_DAY_MISMATCH`, and the program must still be `SCHEDULED` — assigning against a cancelled program is rejected with `ERR_PROGRAM_NOT_SCHEDULED`.

Confirmation belongs to the docent alone: a `Docent` caller whose `X-User-ID` equals the assignment's `docent_id` moves the assignment `ASSIGNED` to `CONFIRMED`, provided the program is still `SCHEDULED` (else `ERR_PROGRAM_NOT_SCHEDULED`). Confirmation is load-bearing beyond the assignment itself — it re-evaluates the waitlist of school group reservations for that program and service date, as described below.

School group reservations are created by `Public` organizers with a `museum_id`, a `program_id`, a `school_name`, a `headcount` of at least 1, and a `visit_date`; the server records the organizer in `created_by_user_id`. The `museum_id` names the visit's museum — its `closed_dates` govern the closure check below — and is not cross-checked against the program's museum. Creation is synchronously evaluated, and the stored state is always `CONFIRMED` or `WAITLISTED` — never `REQUESTED`, which exists only transiently during evaluation. The evaluation order is pinned and must not be reordered. First, hard validation: a `headcount` exceeding the program's `max_group_size` is rejected with `ERR_GROUP_TOO_LARGE`, and a `visit_date` whose weekday differs from the program's `day_of_week` is rejected with `ERR_PROGRAM_DAY_MISMATCH`; a reservation against a cancelled program fails with `ERR_PROGRAM_NOT_SCHEDULED`, and one on a museum closure date fails with `ERR_MUSEUM_CLOSED_ON_DATE`. Second, capacity: the summed headcount of already-`CONFIRMED` reservations for the program and date plus the new `headcount` must not exceed `student_capacity`. Third, staffing: the docents required are the `headcount` divided by `docent_ratio` rounded up, and the docents available are the assignments for the program whose `service_date` equals the `visit_date` and whose status is `CONFIRMED`. Fourth, queuing: if any earlier-created `WAITLISTED` reservation already exists for the same program and date, the new reservation queues behind it. The reservation lands `CONFIRMED` exactly when capacity fits, confirmed docents are at least the required number, and no earlier waitlisted reservation blocks the queue; otherwise it lands `WAITLISTED`. The ordering resolves a deliberately circular dependency: confirmed docents gate confirmation, and each confirmation consumes capacity that later groups' docent arithmetic is checked against — capacity first, then docents, then the queue.

Waitlist promotion is a strict first-in-first-out waterfall with head-of-line blocking, triggered when a confirmed reservation is cancelled or when a docent confirms an assignment for the program and date. The waitlisted reservations for the program and date are scanned in `created_at` ascending order — millisecond timestamps, never resource identifiers, break ties, and a residual tie under a frozen clock breaks by creation sequence. The head of the queue is promoted to `CONFIRMED` only if it now satisfies the capacity, docent, and queue conditions above; if the head does not fit, promotion stops immediately and later entries are never skipped to. After each successful promotion the new head is re-evaluated, and the scan repeats until the head does not fit or the queue empties.

Cancelling a reservation is open to the organizing `Public` caller whose `X-User-ID` equals the reservation's `created_by_user_id`, or to a `ProgramCoordinator`. From `CONFIRMED` the cancellation releases the headcount and immediately runs the promotion waterfall for that program and date; from `WAITLISTED` it simply dequeues the entry. Either way the reservation lands in terminal `CANCELLED`. Cancelling the program itself — a `ProgramCoordinator` action moving the program `SCHEDULED` to `CANCELLED` — cascades: every `CONFIRMED` or `WAITLISTED` reservation of the program flips to `CANCELLED`, and every docent assignment still `ASSIGNED` flips to `RELEASED`, while `CONFIRMED` assignments are left untouched as a matter of record.

### 3.4. Collection Objects and the Loan Negotiation Cycle

A `Registrar` accessions objects directly — outside any acquisition workflow — with a unique `accession_number`, a `title`, a curatorial `declared_value_cents` of at least 0, and an `is_cultural_property` flag defaulting to false for objects subject to cultural property and repatriation law. New objects stand in `IN_COLLECTION`.

Loans to borrowing institutions are negotiated on the platform. A `LoansOfficer` opens a negotiation under an object by naming the `borrower_institution` (a plain institution name; no borrower entity exists), a half-open loan window from `loan_start_date` inclusive to `loan_end_date` exclusive with the end strictly after the start, an agreed `declared_value_cents` of at least 0 for insurance or indemnity purposes, a `coverage_type` of `INSURANCE` or `INDEMNITY`, and whether `courier_required` demands a museum courier accompany the object. The object must be `IN_COLLECTION`, else `ERR_OBJECT_NOT_IN_COLLECTION`. Window overlap with other loans is deliberately not checked at proposal time — only at acceptance. The agreement is born in `PROPOSED` with `negotiated_round` set to 1 and `premium_cents` null; the premium stays null until an acceptance locks it.

Negotiation proceeds in counter-rounds. The `BorrowerRep` counters a `PROPOSED` agreement, moving it to `COUNTERED`; the `LoansOfficer` counters a `COUNTERED` agreement, moving it back to `PROPOSED` — the lender's counter of the borrower's counter. A counter attempted by the side that does not hold the turn — the `BorrowerRep` facing `COUNTERED`, the `LoansOfficer` facing `PROPOSED` — is a transition violation, rejected with `ERR_INVALID_STATE` rather than an authorization error. Every counter must carry `expected_loan_version` equal to the agreement's current `version`, or it is rejected with `ERR_STALE_LOAN_VERSION` (HTTP 412). On a successful counter, whichever of the term fields — `loan_start_date`, `loan_end_date`, `declared_value_cents` (still at least 0 when provided), `coverage_type`, `courier_required` — are provided replace the current terms, `negotiated_round` increments by 1, and the agreement's `version` increments by 1.

Acceptance is symmetric: the `BorrowerRep` accepts from `PROPOSED`, and the `LoansOfficer` accepts from `COUNTERED`; an accept attempted by the wrong side for the current state is likewise a transition violation rejected with `ERR_INVALID_STATE`. Acceptance likewise requires `expected_loan_version` matching the current `version`, with mismatches rejected as `ERR_STALE_LOAN_VERSION` (HTTP 412) — an intervening counter means the acceptor has not seen the current terms. Three gates then apply. First, terms validation: an agreement whose declared value is at least 100,000,000 cents requires a courier, so acceptance with `courier_required` false at or above that threshold fails with `ERR_COURIER_REQUIRED`; an `INDEMNITY` agreement requires a declared value of at least 500,000,000 cents, failing otherwise with `ERR_INDEMNITY_MINIMUM_NOT_MET`, and always requires a courier, failing otherwise with `ERR_INDEMNITY_REQUIRES_COURIER` — federal indemnity replaces commercial insurance and is reserved for high-value, courier-accompanied loans. Second, window overlap: the half-open window must not overlap any other `AGREED` or `ACTIVE` loan of the same object, where overlap means this loan starts before the other ends and the other starts before this loan ends; adjacency — one loan starting exactly when another ends — is not overlap, so back-to-back loans are allowed. A conflict is rejected with `ERR_LOAN_PERIOD_CONFLICT`. Third, the premium is computed and locked.

During negotiation, staff may quote a provisional premium: a flat 0.8 percent of `declared_value_cents`, with no tiering and no courier surcharge. The provisional figure is a documented estimate and is never persisted. The premium persisted to `premium_cents` at acceptance is the final variant, computed in a pinned order that must not be reordered. The base is tiered in exact arithmetic: the first 100,000,000 cents of declared value price at 0.6 percent, the next 400,000,000 cents price at 0.35 percent, and any remainder above those tiers prices at 0.15 percent. The tiered base is then rounded half up to whole cents — exactly once, at this point. If `courier_required` is true, a courier surcharge of 12 percent of that rounded base is itself rounded half up to whole cents; otherwise the surcharge is zero. The premium is the sum of the rounded base and the rounded surcharge. Under `INDEMNITY` coverage the premium is always 0. The pinned order matters: for a declared value of 1,000,075 cents with a courier, the pinned computation yields 6,720 cents, while summing the unrounded parts and rounding once at the end yields 6,721 — and is wrong. For contrast, a declared value of 250,000,000 cents with a courier quotes provisionally at 2,000,000 cents but locks at 1,260,000 cents under the final tiered computation. A successful acceptance moves the agreement to `AGREED` and bumps its `version`.

### 3.5. Condition Reports, Shipment, Return, and Conservation

Condition reporting brackets every shipment. Either the `LoansOfficer` or the `BorrowerRep` files a condition report under a loan, naming a `report_kind` — `OUTBOUND` for the pre-shipment report, `RETURN` for the post-return report — a narrative `condition_summary`, and a `damage_noted` flag that is true when new damage is recorded. A report is born in `SUBMITTED` status, and filing is not gated on the loan's state. Filing a fresh report of the same kind for the same loan supersedes any earlier report of that kind still standing in `DISPUTED`: the earlier report moves to `SUPERSEDED`, so only one live dispute per kind exists at a time.

Only the `LoansOfficer` decides a report, via an `outcome` of `ACCEPTED` or `DISPUTED`, and only while the parent loan is live — in `AGREED` or `ACTIVE`; reports of a loan outside those states are not decidable, and a decision attempted against one is rejected with `ERR_INVALID_STATE`. Acceptance and dispute are terminal-or-supersedable states: `ACCEPTED`, `SUPERSEDED`, and `CANCELLED` are terminal, while `DISPUTED` awaits a superseding re-filing.

Shipment requires paperwork. Moving an agreement `AGREED` to `ACTIVE` — the `LoansOfficer` shipping the object — requires an `OUTBOUND` report for the loan standing in `ACCEPTED`, else `ERR_CONDITION_REPORT_REQUIRED`, and requires the object still `IN_COLLECTION`, else `ERR_OBJECT_NOT_IN_COLLECTION`. Activation flips the object to `OUT_ON_LOAN` and bumps the loan's `version`.

Return closes the loop. Moving an agreement `ACTIVE` to `CLOSED` requires a `RETURN` report standing in `ACCEPTED`, else `ERR_CONDITION_REPORT_REQUIRED`. The object's next state reads off that accepted return report (if several `RETURN` reports stand `ACCEPTED`, the most recently filed governs): when `damage_noted` is false the object returns to `IN_COLLECTION`, and when `damage_noted` is true it moves to `UNDER_CONSERVATION`. An object under conservation blocks new loans and blocks research approvals until a `Registrar` performs the release action, moving it `UNDER_CONSERVATION` back to `IN_COLLECTION`.

One cascade can interrupt the whole cycle: when a deaccession review executes against the underlying object, every non-terminal agreement for the object — `PROPOSED`, `COUNTERED`, or `AGREED` — is cancelled, and every non-terminal condition report of each cancelled agreement — `SUBMITTED` or `DISPUTED` — is cancelled in turn. The chain is transitive: object disposal cancels loans, and loan cancellation cancels reports.

### 3.6. Collections Committee: Acquisition and Deaccession Review

Acquisitions and deaccessions are decided by a collections committee through a formal review. A `Curator` opens a review with a `review_kind` of `ACQUISITION` or `DEACCESSION`, and the kind determines the required field pairing. An `ACQUISITION` review must carry a `fund_id` naming the paying fund, an `estimated_cost_cents` of at least 1, and a `proposed_object_title`, and its `object_id` must be null — the object does not exist yet. A `DEACCESSION` review must carry an `object_id` and a `disposal_method` of `TRANSFER`, `SALE`, `DESTRUCTION`, or `REPATRIATION`, and its `fund_id` must be null. Either pairing violation is rejected with `ERR_INVALID_REQUEST`. A review may also record `cultural_property_review_completed`, defaulting to false, once the cultural-property and repatriation review is done. New reviews stand in `DRAFT`.

Submission belongs to the creating curator alone: the server records the creator's `X-User-ID` at creation, and the submission is accepted only from that same `X-User-ID`, at which point `submitted_by_user_id` is set to it and the review's `version` increments. The review moves `DRAFT` to `SUBMITTED`.

Decision belongs to the `CommitteeChair`, who supplies an `outcome` of `APPROVED` or `REJECTED` together with `expected_review_version`; a version that no longer matches the review's current `version` — for example because the curator re-submitted amended terms — is rejected with `ERR_STALE_REVIEW_VERSION` (HTTP 412). Segregation of duties is absolute: the chair's `X-User-ID` must differ from the review's `submitted_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES` (HTTP 403) — no one decides their own submission. Approval of a `DEACCESSION` review for an object whose `is_cultural_property` is true additionally requires `cultural_property_review_completed` to be true, else `ERR_CULTURAL_PROPERTY_REVIEW_PENDING` (HTTP 422). Approval of a deaccession is also blocked while any `ACTIVE` loan exists for the object, failing with `ERR_OBJECT_ON_ACTIVE_LOAN`; loans still in negotiation or merely agreed — `PROPOSED`, `COUNTERED`, or `AGREED` — do not block approval, because execution will cancel them. For an `ACQUISITION` review the named fund must be `ACTIVE` at decision time — whatever the outcome — else `ERR_FUND_FROZEN`; approval additionally requires that `ACQUISITION` activity be permitted for the fund's type, else `ERR_FUND_ACTIVITY_NOT_PERMITTED` (so an acquisition can never be approved against a `FEDERAL` fund), and that the fund's committed availability cover the `estimated_cost_cents`, else `ERR_INSUFFICIENT_FUND_AVAILABLE`. A decided review records the chair in `decided_by_user_id` and bumps its `version`; an approved deaccession additionally moves the object — whether it stands `IN_COLLECTION` or `UNDER_CONSERVATION` — to `PENDING_DEACCESSION`. Rejection applies no approval-specific gate — no cultural-property, active-loan, activity-permission, or fund-sufficiency check — and lands the review in terminal `REJECTED`.

Execution is performed by the `Registrar` and differs by kind. For an acquisition, the execute payload may carry `actual_cost_cents` — an integer of at least 1 when present, defaulting to the review's `estimated_cost_cents` when omitted; the fund must still be `ACTIVE`, `ACQUISITION` activity must be permitted for its type, and its committed availability must cover the actual cost, else `ERR_FUND_FROZEN`, `ERR_FUND_ACTIVITY_NOT_PERMITTED`, or `ERR_INSUFFICIENT_FUND_AVAILABLE` respectively. Execution then creates the collection object — its `title` taken from `proposed_object_title`, its `declared_value_cents` set to the actual cost, a server-minted `accession_number`, `is_cultural_property` false, standing `IN_COLLECTION` — and posts an expenditure of the actual cost with `activity_type` `ACQUISITION` and a null `memo` against the review's `fund_id`, stamped with this review's `review_id`. For a deaccession, execution re-checks that no `ACTIVE` loan exists for the object at that moment, else `ERR_OBJECT_ON_ACTIVE_LOAN`; the object then leaves the collection, moving to `DEACCESSIONED`, or to `REPATRIATED` when the `disposal_method` is `REPATRIATION`, and the cancellation cascade described above fires across the object's loans and their condition reports. Executed reviews land in terminal `EXECUTED`.

### 3.7. Fund Accounts, Expenditures, and Fiscal Controls

A `PlatformAdmin` creates fund accounts with a unique `fund_code`, a `fund_type` of `FEDERAL` or `TRUST`, and an `appropriation_cents` budget authority of at least 0. A fund is born `ACTIVE` with `receipts_cents` at 0. Reading a fund reports, alongside its static fields, the computed `receipts_cents` (reported on every fund; nonzero only for `TRUST` funds, per the netting rule in §2.7), the `settled_available_cents`, and the `committed_available_cents`. Freezing is a `PlatformAdmin` action that supplies a `status` of `FROZEN` or `ACTIVE`: while a fund is `FROZEN`, new expenditures and acquisition decisions and executions against it are blocked with `ERR_FUND_FROZEN`; unfreezing restores the fund to `ACTIVE`. Requesting the status the fund already holds has no transition and is rejected with `ERR_INVALID_STATE`.

Expenditures are posted by a `FinanceOfficer` directly in `POSTED` status, carrying an `amount_cents` of at least 1, an `activity_type` of `OPERATIONS`, `EDUCATION`, `ACQUISITION`, or `EXHIBITION`, and a free-text `memo`. An expenditure's `review_id` is set only when the posting was created by an acquisition execution, and is null otherwise. The posting is gated, in pipeline order, by the fund being `ACTIVE`, by the activity-type permission for the fund's type, and by the amount not exceeding the fund's committed availability — committed, not settled, so approved-but-unexecuted acquisitions already encumber the money. A posted expenditure lowers both availability figures by its amount. The compensating action is voiding, again by a `FinanceOfficer`: the expenditure moves `POSTED` to `VOIDED`, and the fund's settled and committed availability rise by the voided `amount_cents`, since only `POSTED` expenditures count against the fund.

### 3.8. Research Access to the Collection

External scholars request access to collection objects through a request naming the `object_id`, a `scholar_name`, a `research_topic`, and a closed visit interval from `visit_start_date` to `visit_end_date`, both ends inclusive, with the end on or after the start. The server records the scholar in `created_by_user_id`, and the request stands in `REQUESTED`.

The `Registrar` decides each request with an `outcome` of `APPROVED` or `DENIED`. Denial needs no gate. Approval applies three. The object must stand `IN_COLLECTION`, else `ERR_OBJECT_NOT_IN_COLLECTION`. The visit interval must not intersect any other already-`APPROVED` research visit for the same object: because visit intervals are closed, two visits conflict whenever each starts on or before the other's last day — a second visit beginning exactly on the day the first visit ends is a conflict, in deliberate contrast to the half-open loan windows — and a violation is rejected with `ERR_RESEARCH_VISIT_CONFLICT`. Finally, the visit interval must not intersect any `AGREED` or `ACTIVE` loan window for the object: a conflict exists when the visit starts before the loan's end date and the loan's start date falls on or before the visit's last day, and a violation is rejected with `ERR_OBJECT_RESERVED_FOR_LOAN`. An approved request lands in terminal `APPROVED`; a denied one in terminal `DENIED`.

## 4. Endpoint Definitions

Endpoints that create a new resource respond with HTTP 201 and the created resource; all other successful operations — modifications, actions, state transitions, and reads — respond with HTTP 200. The table below is a contract summary only: request payloads, computed fields, and side effects are defined by the narratives in §2 and §3, which are normative. All paths are relative to the server root; every business path lives under `/campus`, and the logical-clock capability is mounted outside that prefix.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/_clock/set_current_utc` | Set the server logical clock | PlatformAdmin |
| POST | `/campus/museums` | Create a museum | PlatformAdmin |
| GET | `/campus/museums/{id}` | Read a museum, including closure dates and the current slot's screening backlog | PlatformAdmin, VisitorServices, SecurityScreener, ExhibitionManager, ProgramCoordinator, LoansOfficer, Registrar, Curator, CommitteeChair, FinanceOfficer, Docent, Scholar, Member, Public |
| POST | `/campus/museums/{id}/close-day` | Emergency-close the museum on a date; reserved passes that day expire | PlatformAdmin |
| POST | `/campus/museums/{id}/timed-entry-passes` | Reserve a free timed entry pass | Public, Member, VisitorServices |
| GET | `/campus/timed-entry-passes` | List passes, filterable by museum, visit date, and holding member | PlatformAdmin, VisitorServices, SecurityScreener, Member, Public |
| GET | `/campus/timed-entry-passes/{id}` | Read a single timed entry pass | PlatformAdmin, VisitorServices, SecurityScreener, Member, Public |
| POST | `/campus/timed-entry-passes/{id}/cancel` | Cancel a reserved pass | Public, Member, VisitorServices |
| POST | `/campus/timed-entry-passes/{id}/admit` | Admit a pass holder through screening for the current slot | SecurityScreener |
| POST | `/campus/members` | Register a member | Public, VisitorServices |
| GET | `/campus/members/{id}` | Read a member, including computed standing | PlatformAdmin, VisitorServices, ExhibitionManager, Member |
| POST | `/campus/museums/{id}/exhibitions` | Create a special exhibition | ExhibitionManager |
| GET | `/campus/exhibitions` | List exhibitions, filterable by museum and revenue fund | PlatformAdmin, VisitorServices, ExhibitionManager, Member, Public |
| GET | `/campus/exhibitions/{id}` | Read an exhibition | PlatformAdmin, VisitorServices, ExhibitionManager, Member, Public |
| POST | `/campus/exhibitions/{id}/open-sale` | Open ticket sales for the exhibition | ExhibitionManager |
| POST | `/campus/exhibitions/{id}/close` | Close the exhibition and auto-refund all purchased tickets | ExhibitionManager |
| POST | `/campus/exhibitions/{id}/tickets` | Purchase an exhibition ticket | Public, Member |
| GET | `/campus/tickets` | List tickets, filterable by exhibition and member | PlatformAdmin, VisitorServices, ExhibitionManager |
| GET | `/campus/tickets/{id}` | Read a ticket | PlatformAdmin, VisitorServices, ExhibitionManager, Member, Public |
| POST | `/campus/tickets/{id}/refund` | Refund a purchased ticket on or before its visit date | VisitorServices |
| POST | `/campus/tickets/{id}/redeem` | Redeem a ticket at the exhibition entrance on its visit date | SecurityScreener |
| POST | `/campus/docents` | Register a volunteer docent | ProgramCoordinator |
| GET | `/campus/docents/{id}` | Read a docent | PlatformAdmin, ProgramCoordinator, Docent |
| POST | `/campus/museums/{id}/education-programs` | Create a weekly education program | ProgramCoordinator |
| GET | `/campus/education-programs` | List education programs, filterable by museum | PlatformAdmin, ProgramCoordinator, Docent, Public |
| GET | `/campus/education-programs/{id}` | Read a single education program | PlatformAdmin, ProgramCoordinator, Docent, Public |
| POST | `/campus/education-programs/{id}/cancel` | Cancel a program, cascading to reservations and assignments | ProgramCoordinator |
| POST | `/campus/education-programs/{id}/docent-assignments` | Assign a docent to a program service date | ProgramCoordinator |
| GET | `/campus/docent-assignments` | List docent assignments, filterable by program and docent | PlatformAdmin, ProgramCoordinator, Docent |
| GET | `/campus/docent-assignments/{id}` | Read a single docent assignment | PlatformAdmin, ProgramCoordinator, Docent |
| POST | `/campus/docent-assignments/{id}/confirm` | Docent confirms their own assignment, re-evaluating the waitlist | Docent |
| POST | `/campus/school-reservations` | Reserve a school group visit; lands confirmed or waitlisted | Public |
| GET | `/campus/school-reservations` | List school group reservations, filterable by museum and program | PlatformAdmin, ProgramCoordinator, Public |
| GET | `/campus/school-reservations/{id}` | Read a single school group reservation | PlatformAdmin, ProgramCoordinator, Public |
| POST | `/campus/school-reservations/{id}/cancel` | Cancel a confirmed or waitlisted reservation | Public, ProgramCoordinator |
| POST | `/campus/collection-objects` | Accession a collection object directly | Registrar |
| GET | `/campus/collection-objects/{id}` | Read a collection object | PlatformAdmin, Registrar, LoansOfficer, Curator, CommitteeChair, Scholar |
| POST | `/campus/collection-objects/{id}/release-conservation` | Release an object from conservation back into the collection | Registrar |
| POST | `/campus/collection-objects/{id}/loan-agreements` | Open loan negotiation for an object | LoansOfficer |
| GET | `/campus/loan-agreements` | List loan agreements, filterable by object | PlatformAdmin, Registrar, LoansOfficer, CommitteeChair, BorrowerRep |
| GET | `/campus/loan-agreements/{id}` | Read a single loan agreement | PlatformAdmin, Registrar, LoansOfficer, CommitteeChair, BorrowerRep |
| POST | `/campus/loan-agreements/{id}/counter` | Counter the current loan terms | LoansOfficer, BorrowerRep |
| POST | `/campus/loan-agreements/{id}/accept` | Accept the current loan terms and lock the final premium | LoansOfficer, BorrowerRep |
| POST | `/campus/loan-agreements/{id}/activate` | Ship the object, activating the loan | LoansOfficer |
| POST | `/campus/loan-agreements/{id}/close` | Register the object's return and close the loan | LoansOfficer |
| POST | `/campus/loan-agreements/{id}/condition-reports` | File a condition report for a loan | LoansOfficer, BorrowerRep |
| GET | `/campus/condition-reports` | List condition reports, filterable by loan | PlatformAdmin, Registrar, LoansOfficer, BorrowerRep |
| GET | `/campus/condition-reports/{id}` | Read a single condition report | PlatformAdmin, Registrar, LoansOfficer, BorrowerRep |
| POST | `/campus/condition-reports/{id}/decide` | Accept or dispute a submitted condition report | LoansOfficer |
| POST | `/campus/collection-reviews` | Open a collections-committee review | Curator |
| GET | `/campus/collection-reviews` | List collection reviews, filterable by object and fund | PlatformAdmin, Registrar, Curator, CommitteeChair, FinanceOfficer |
| GET | `/campus/collection-reviews/{id}` | Read a single collection review | PlatformAdmin, Registrar, Curator, CommitteeChair, FinanceOfficer |
| POST | `/campus/collection-reviews/{id}/submit` | Submit a draft review to the committee | Curator |
| POST | `/campus/collection-reviews/{id}/decide` | Approve or reject a submitted review | CommitteeChair |
| POST | `/campus/collection-reviews/{id}/execute` | Execute an approved review | Registrar |
| POST | `/campus/funds` | Create a fund account | PlatformAdmin |
| GET | `/campus/funds/{id}` | Read a fund, including computed receipts and availability | PlatformAdmin, FinanceOfficer, CommitteeChair, Registrar, Curator, ExhibitionManager |
| POST | `/campus/funds/{id}/set-status` | Freeze or unfreeze a fund | PlatformAdmin |
| POST | `/campus/funds/{id}/expenditures` | Post an expenditure | FinanceOfficer |
| GET | `/campus/expenditures` | List expenditures, filterable by fund and review | PlatformAdmin, FinanceOfficer, CommitteeChair |
| GET | `/campus/expenditures/{id}` | Read a single expenditure | PlatformAdmin, FinanceOfficer, CommitteeChair |
| POST | `/campus/expenditures/{id}/void` | Void a posted expenditure | FinanceOfficer |
| POST | `/campus/research-access-requests` | Request research access to an object | Scholar |
| GET | `/campus/research-access-requests` | List research access requests, filterable by object | PlatformAdmin, Registrar, Scholar |
| GET | `/campus/research-access-requests/{id}` | Read a single research access request | PlatformAdmin, Registrar, Scholar |
| POST | `/campus/research-access-requests/{id}/decide` | Approve or deny a research access request | Registrar |

## 5. Error Code Catalogue

The table below enumerates every error identifier the API returns. Trigger conditions are defined by the narratives in §2 and §3; this catalogue fixes only the identifier-to-status mapping.

| Error ID | HTTP Status Code |
|---|---|
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_TIMED_PASS_NOT_USED_HERE` | 409 |
| `ERR_DUPLICATE_PASS` | 409 |
| `ERR_SLOT_QUOTA_EXHAUSTED` | 409 |
| `ERR_DAILY_QUOTA_EXHAUSTED` | 409 |
| `ERR_MUSEUM_CLOSED_ON_DATE` | 409 |
| `ERR_PASS_EXPIRED` | 409 |
| `ERR_SCREENING_THROUGHPUT_FULL` | 409 |
| `ERR_SALE_NOT_OPEN` | 409 |
| `ERR_PRESALE_MEMBER_ONLY` | 409 |
| `ERR_MEMBER_LAPSED` | 409 |
| `ERR_TICKET_QUOTA_EXHAUSTED` | 409 |
| `ERR_REFUND_WINDOW_CLOSED` | 409 |
| `ERR_VISIT_DATE_MISMATCH` | 409 |
| `ERR_GROUP_TOO_LARGE` | 422 |
| `ERR_PROGRAM_DAY_MISMATCH` | 422 |
| `ERR_PROGRAM_NOT_SCHEDULED` | 409 |
| `ERR_DOCENT_NOT_CERTIFIED` | 422 |
| `ERR_OBJECT_NOT_IN_COLLECTION` | 409 |
| `ERR_LOAN_PERIOD_CONFLICT` | 409 |
| `ERR_COURIER_REQUIRED` | 409 |
| `ERR_INDEMNITY_MINIMUM_NOT_MET` | 409 |
| `ERR_INDEMNITY_REQUIRES_COURIER` | 409 |
| `ERR_STALE_LOAN_VERSION` | 412 |
| `ERR_CONDITION_REPORT_REQUIRED` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_CULTURAL_PROPERTY_REVIEW_PENDING` | 422 |
| `ERR_OBJECT_ON_ACTIVE_LOAN` | 409 |
| `ERR_FUND_FROZEN` | 409 |
| `ERR_FUND_ACTIVITY_NOT_PERMITTED` | 422 |
| `ERR_INSUFFICIENT_FUND_AVAILABLE` | 409 |
| `ERR_STALE_REVIEW_VERSION` | 412 |
| `ERR_GALLERY_SCHEDULE_CONFLICT` | 409 |
| `ERR_RESEARCH_VISIT_CONFLICT` | 409 |
| `ERR_OBJECT_RESERVED_FOR_LOAN` | 409 |
| `ERR_NOT_TRUST_FUND` | 422 |
