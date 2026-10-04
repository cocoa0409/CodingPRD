# Peer-Group Microlending API — Product Requirements Document

## 1. Introduction

This document specifies the Peer-Group Microlending API, a platform for running a group-lending program in the tradition of Grameen-style center meetings. The program lends to low-income borrowers who offer no collateral; instead, borrowers are recruited into five-person peer groups whose members are jointly liable for one another's continued access to credit. Borrowers graduate through compulsory formation training, approve each other's loan applications by unanimous consensus, and repay in cash at weekly center meetings where attendance is taken and a mandatory savings deposit accompanies every repayment.

The operational stakes of the domain drive several design commitments that run through every section of this document. Joint liability means a single member's delinquency must visibly cascade — to the delinquent member, to their group's standing, to sibling loans on the size ladder, and to any application still awaiting votes. Cash collected in the field must reconcile exactly against what managers declare, under a segregation-of-duties regime in which the person who closes a meeting may never be the person who reconciles it. Every repayment builds two assets for the borrower at once: a savings balance that is partially locked as loan collateral, and a credit bureau file whose provisional and final scores follow pinned formulas. Finally, branch growth is planned analytically: manager caseloads, center capacity, and expansion feasibility are all derived quantities with conserved invariants, not free-form inputs.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational role. A request missing either header, or carrying an empty value in either, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. A request whose role is not permitted to invoke the target endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS`.

The platform recognizes exactly five roles: `ProgramAdmin`, `BranchManager`, `CenterManager`, `FieldOfficer`, and `Member`.

- A `ProgramAdmin` is the platform administrator: creates branches, hires center managers, creates and reassigns centers, decides expansion plans, drives the logical clock, and unfreezes savings accounts. When `X-User-Role` is `ProgramAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- A `BranchManager` runs branch-level fiscal operations: disburses approved loans, reconciles meetings, voids transactions, restructures loans, and submits expansion plans. When `X-User-Role` is `BranchManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- A `CenterManager` is the field officer's counterpart at the center: schedules and completes training, schedules, opens, closes, and cancels meetings, records attendance, and collects repayments. When `X-User-Role` is `CenterManager`, `X-User-ID` is the `id` of the acting `CenterManager` entity; ownership checks on any resource that references a `CenterManager` — most importantly the `center_manager_id` of the center that hosts a meeting — compare that foreign-key field to `X-User-ID`.
- A `FieldOfficer` recruits members, forms and dissolves peer groups, manages membership, and drafts and submits loan applications. When `X-User-Role` is `FieldOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- A `Member` is a borrower. When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member` entity; ownership checks on any resource that references a `Member` compare the resource's foreign-key field to `X-User-ID`. A vote's `voter_member_id` is set from the caller's `X-User-ID`, and savings withdrawals and closures operate on the caller's own account.

All roles may invoke every read (GET) endpoint. Write operations are restricted per role as described throughout §3 and summarized in §4; in particular, a `CenterManager` may never reconcile, void, or disburse, a `FieldOfficer` may never collect money or disburse, and a `Member` may never perform any staff operation.

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
- The `response_type` is either "object" for a single resource or "array" for a list of resources. The discriminator is structural: `response_type` is "array" exactly when `data` is an array, even when the array is empty, and "object" otherwise.
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

List endpoints accept two query parameters. `limit` caps the number of returned items; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` skips that many items before returning results and defaults to 0. A non-integer `limit` or `offset`, a `limit` outside 1–100, or a negative `offset` is rejected with `ERR_INVALID_REQUEST`. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order, with ties broken by `id` ascending. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Logical Time and Scheduled Sweeps

The platform runs on a logical clock, never on wall-clock time. Before any adjustment, the logical clock starts at exactly 2026-09-01T00:00:00Z. An admin-only test-driving capability moves the logical clock to a caller-supplied `to_iso8601` instant; the response echoes the new `current_utc` alongside sweep tallies `loans_delinquent`, `loans_defaulted`, and `applications_expired`. Every time-dependent rule in the system — due-date aging, voting deadlines, scoring windows — reads this logical clock.

Each clock move runs two sweeps immediately, inside the same request: the delinquency sweep over all open loans (§3.6) and the voting-expiry sweep over undecided applications (§3.3). Every cascade those sweeps trigger — member status flips, group restriction, application expiry, blacklist freezes — completes inside the triggering request. The same immediate-consistency rule applies to cascades triggered by ordinary write operations: no side effect is ever deferred to a later request.

### 2.5. Common Resource Properties

All primary resources — branches, center managers, centers, peer groups, members, training sessions, loan applications, loans, restructures, center meetings, repayment transactions, savings accounts, and expansion plans — carry a standard set of system-managed fields:

- `id`: a unique, server-minted UUID with no type prefix.
- `created_at`: an ISO 8601 UTC timestamp with three fractional digits, set at creation.
- `updated_at`: an ISO 8601 UTC timestamp refreshed on every mutation, including system-driven cascade mutations. All `created_at`/`updated_at` stamps carry wall-clock precision, never the logical clock of §2.4.
- `version`: an integer that increments on every mutation of the resource.

Three record types are append-only audit records and carry only `id` and `created_at` — both `updated_at` and `version` are absent from them: consensus votes (a `decision` cast against a `loan_application_id` by a `voter_member_id`), meeting attendance rows (a `present` flag joining a `center_meeting_id` to a `member_id`), and credit bureau reports (a `report_type` with a `score_reported`, filed against a `member_id` and a `loan_id`). Caller-supplied timestamps (such as `scheduled_start`, `voting_deadline`, or a meeting's `next_due_date`) are echoed with the caller's own precision — no fractional seconds when the input carried none, three fractional digits otherwise.

### 2.6. Monetary Representation and Rounding

All monetary values are integer cents — no fractional cents exist anywhere in the system. Where a computed amount is not already an integer, it is rounded half up to the nearest cent. Two rounding disciplines are pinned:

- **Component-first rounding.** Each computed component (an installment, a savings requirement, a locked amount) is rounded individually before it participates in any downstream sum or comparison.
- **Per-transaction rounding.** A repayment's split into savings, installment, and principal buckets is rounded within that transaction first; meeting-level totals are then the sum of already-rounded per-transaction amounts, never recomputed from unrounded components.

Credit scores are integer points, days-past-due are whole days, and headcounts are integer counts, each governed by the rounding rule stated where the calculation is defined.

### 2.7. Optimistic Concurrency on Loan Restructuring

Exactly one endpoint in the API performs optimistic concurrency control: the creation of a loan restructure. The request must carry `expected_loan_version`, a non-optional field holding the `version` of the target loan as the client last observed it. If the loan's current `version` has advanced since that observation, the creation is rejected with `ERR_STALE_LOAN_VERSION` (HTTP 412). The reason this protection exists here and nowhere else is the restructure's create-with-supersede semantics (§3.9): a successful restructure silently supersedes any prior active restructure and rewrites the loan's term and installment, so a writer holding a stale loan version would supersede terms it never saw. No endpoint other than restructure creation accepts a version field.

### 2.8. Validation Order and Error Precedence

When a request fails several rules at once, the error the caller sees is determined by a fixed evaluation order, from first to last:

1. **Header presence** — missing or empty `X-User-ID` / `X-User-Role` fails with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.
2. **Role permission** — a role not entitled to the endpoint fails with `ERR_INSUFFICIENT_PERMISSIONS`.
3. **Existence** — path identifiers are resolved left to right; the first unknown id fails with its `404` error (§2.9).
4. **Optimistic concurrency** — on restructure creation only, a stale `expected_loan_version` fails with `ERR_STALE_LOAN_VERSION`.
5. **State** — the target resource must be in the source state the operation requires (for example, an application in `DRAFT` to submit, a meeting in `OPEN` to collect, a transaction in `POSTED` to void), failing with the operation's state error such as `ERR_APPLICATION_NOT_DRAFT`, `ERR_APPLICATION_NOT_APPROVED`, `ERR_APPLICATION_NOT_VOTING`, `ERR_MEETING_NOT_SCHEDULED`, `ERR_MEETING_NOT_OPEN`, `ERR_MEETING_NOT_CLOSED`, `ERR_ALREADY_RECONCILED`, `ERR_MEETING_ALREADY_RECONCILED`, `ERR_TXN_NOT_POSTED`, `ERR_ACCOUNT_NOT_OPEN`, `ERR_ACCOUNT_NOT_FROZEN`, `ERR_PLAN_NOT_SUBMITTED`, `ERR_TRAINING_NOT_SCHEDULED`, `ERR_LOAN_NOT_REPAYABLE`, or the generic `ERR_INVALID_STATE`.
6. **Compliance gates** — blacklist screening (`ERR_MEMBER_BLACKLISTED`) and segregation of duties (`ERR_SEGREGATION_OF_DUTIES`). Within a group-membership add, the blacklist screen is evaluated before the already-in-a-group check, so a blacklisted ex-member surfaces as `ERR_MEMBER_BLACKLISTED` rather than `ERR_MEMBER_ALREADY_IN_GROUP`.
7. **Referential coherence** — cross-references must agree: the voter must be a non-applicant peer of the applicant's group who has not already voted (`ERR_VOTER_NOT_GROUP_PEER`, `ERR_VOTER_IS_APPLICANT`), the collected loan must belong to the paying member (`ERR_LOAN_MEMBER_MISMATCH`), the attended or paying member's group must sit at the meeting's center (`ERR_MEMBER_NOT_AT_CENTER`), and the training facilitator must manage the group's center (`ERR_MANAGER_CENTER_MISMATCH`).
8. **Temporal rules** — meeting and training slot overlap (`ERR_MEETING_OVERLAP`, `ERR_TRAINING_SLOT_OVERLAP`), voting windows (`ERR_VOTING_WINDOW_EXPIRED`), meeting weekday matching (`ERR_MEETING_DAY_MISMATCH`), and well-formed time ranges (`ERR_INVALID_TIME_RANGE`).
9. **Aggregate and structural constraints** — group size and fullness, attendance streaks, one-open-application and one-open-loan rules, eligibility, group standing, caseload and center caps, expansion feasibility, and similar checks (`ERR_GROUP_NOT_FORMING`, `ERR_GROUP_SIZE_INVALID`, `ERR_GROUP_FULL`, `ERR_GROUP_NOT_ACTIVE`, `ERR_GROUP_RESTRICTED`, `ERR_GROUP_HAS_ACTIVE_LOANS`, `ERR_MEMBER_NOT_RECRUITED`, `ERR_MEMBER_NOT_ELIGIBLE`, `ERR_MEMBER_HAS_OPEN_APPLICATION`, `ERR_MEMBER_HAS_ACTIVE_LOAN`, `ERR_ATTENDANCE_INELIGIBLE`, `ERR_NOT_CENTER_MANAGER`, `ERR_CASELOAD_CAP_EXCEEDED`, `ERR_EXPANSION_INFEASIBLE`, `ERR_ACCOUNT_NOT_EMPTY`, `ERR_ALREADY_VOTED`).
10. **Fiscal checks, always last** — ladder ceilings (`ERR_LADDER_CEILING_EXCEEDED`), collection bounds (`ERR_COLLECTION_BELOW_SAVINGS_MINIMUM`, `ERR_COLLECTION_EXCEEDS_OUTSTANDING`), withdrawal bounds (`ERR_WITHDRAWAL_EXCEEDS_AVAILABLE`), and reconciliation equality (`ERR_RECONCILIATION_MISMATCH`).

One consequence worth stating explicitly: at disbursement, the state check (`ERR_APPLICATION_NOT_APPROVED`) outranks the fiscal ladder check, so a non-approved application can never surface `ERR_LADDER_CEILING_EXCEEDED`. Malformed payloads — a missing required field, a type mismatch, an unknown enum value, a duplicated `national_id`, or a `requested_amount_cents` that is not a positive multiple of 100 — are rejected with `ERR_INVALID_REQUEST`.

### 2.9. Resource Addressing and Existence Checking

The resource graph is flat: entities reference one another through identifier fields rather than nested ownership paths. Wherever a path does contain an identifier, identifiers are validated left to right, and the request fails immediately with the `404` error of the first identifier that does not resolve — a group id before the application beneath it, a meeting id before the transaction beneath it. The per-type errors are `ERR_BRANCH_NOT_FOUND`, `ERR_CENTER_MANAGER_NOT_FOUND`, `ERR_CENTER_NOT_FOUND`, `ERR_PEER_GROUP_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, `ERR_LOAN_NOT_FOUND`, `ERR_MEETING_NOT_FOUND`, `ERR_TRAINING_SESSION_NOT_FOUND`, `ERR_TRANSACTION_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, and `ERR_ACCOUNT_NOT_FOUND`.

List endpoints filter through optional query parameters: centers accept `branch_id` and `center_manager_id`; peer groups accept `center_id` and `status`; members accept `branch_id`, `peer_group_id`, and `status`; training sessions accept `peer_group_id` and `center_manager_id`; loan applications accept `peer_group_id`, `member_id`, and `status`; loans accept `member_id`, `loan_application_id`, and `status`; center meetings accept `center_id` and `status`; repayment transactions accept `center_meeting_id`, `loan_id`, and `member_id`.

### 2.10. Segregation of Duties

Three separations are load-bearing and are enforced as hard rules, not conventions. First, **cash closing versus cash reconciliation**: the meeting records the `closer_user_id` of the `CenterManager` who closed it, and reconciliation by that same identifier is rejected with `ERR_SEGREGATION_OF_DUTIES`. Second, **recruitment versus money movement**: a `FieldOfficer` recruits members, builds groups, and files applications but can never collect a repayment, disburse a loan, or void a transaction; disbursement, reconciliation, voids, and restructuring belong to the `BranchManager`, whose operation set is deliberately disjoint from the `CenterManager`'s meeting-floor operations. Third, **borrowers versus staff**: a `Member` votes and manages only their own savings; every staff endpoint refuses them.

## 3. Business Logic & Workflows

### 3.1. Branch Footprint, Staffing, and Caseload Capacity

A branch is the unit of geographic expansion. A `ProgramAdmin` creates one with a `name`; its `active_member_count` starts at zero and its `tier` is derived, never set: `SMALL` while the branch has fewer than 200 active members, `MEDIUM` from 200 up to but not including 500, and `LARGE` at 500 or more. The `active_member_count` counts members of the branch whose status is `IN_TRAINING`, `ELIGIBLE`, `ACTIVE_BORROWER`, or `DELINQUENT` — recruits not yet in a group and blacklisted members do not count.

Center managers are hired into a branch with `branch_id`, `full_name`, and an informational `hired_on` date; the `branch_id` must resolve to an existing branch or the hire fails with `ERR_BRANCH_NOT_FOUND`. Each manager's capacity is governed by two derived caps evaluated against the branch's *current* tier: `center_cap` allows 3 centers under a `SMALL` branch, 4 under `MEDIUM`, and 5 under `LARGE`; `member_cap` allows a caseload of 60, 80, or 100 members respectively. A manager's `current_caseload` counts the distinct members — again in `IN_TRAINING`, `ELIGIBLE`, `ACTIVE_BORROWER`, or `DELINQUENT` — whose peer group sits at a center assigned to that manager, and the branch's `total_manager_caseload` is the sum of its managers' caseloads.

A `ProgramAdmin` creates a center under a branch by supplying `branch_id`, `center_manager_id`, a `name`, and the `meeting_day_of_week` — an integer from 0 (Monday) through 6 (Sunday), interpreted as the UTC weekday of the center's weekly meeting. The named manager must belong to the same branch as the center; a cross-branch pairing is rejected with `ERR_INVALID_REQUEST`. Creation fails with `ERR_CASELOAD_CAP_EXCEEDED` if the target manager would exceed either cap. Centers may later be reassigned to another manager of the *same* branch (a cross-branch reassignment is likewise rejected with `ERR_INVALID_REQUEST`); reassignment recomputes both managers' `current_caseload`, enforces the target manager's caps (`ERR_CASELOAD_CAP_EXCEEDED`), and conserves the branch's `total_manager_caseload` — moving a center between two managers of one branch never changes the branch total. Caseload recomputation also fires when a member is added to a group, when a member is blacklisted, and when a group is dissolved.

### 3.2. Recruitment and Group Formation

A `FieldOfficer` recruits a borrower by supplying `branch_id`, `full_name`, and `national_id`; the national id is a government identifier that must be globally unique across all members, and a duplicate is rejected with `ERR_INVALID_REQUEST`. A new member starts in `RECRUITED` status with `cycle_level` 1, `cured_delinquency_count` 0, `consecutive_absence_streak` 0, `attendance_strikes` 0, and no `peer_group_id`.

Groups are formed at a center: the officer creates a peer group with `center_id` and `name`, and it begins in `FORMING` with a `member_count` of zero. Adding a member to a group (`member_id` in the payload) runs a battery of checks whose order matters. The blacklist screen comes first: a member whose status is `BLACKLISTED`, or who carries a `FINAL` bureau report with a `score_reported` below 300, is refused with `ERR_MEMBER_BLACKLISTED` — this fires before any membership check. Then the member must be `RECRUITED` (`ERR_MEMBER_NOT_RECRUITED`), must have no `peer_group_id` (`ERR_MEMBER_ALREADY_IN_GROUP`), the group must be `FORMING` or `TRAINING` (`ERR_GROUP_NOT_FORMING`), and the group's `member_count` must be below 5 (`ERR_GROUP_FULL`) — the checks fire in exactly this order, so a non-recruited member already in a group surfaces `ERR_MEMBER_NOT_RECRUITED`. A successful add moves the member `RECRUITED → IN_TRAINING`, stamps their `peer_group_id`, increments `member_count`, and recomputes the branch's `active_member_count` and the center manager's `current_caseload`. The `member_count` never includes `BLACKLISTED` members, so a later blacklisting silently shrinks it. A member is never removed from a group once added: group membership ends only with the group itself (dissolution, §3.6), and a `DISSOLVED` group's members keep their stamped `peer_group_id` as an audit trail — such a member can never be re-added to any group, because the no-`peer_group_id` precondition can never again hold.

Formation training converts a roster into a borrowing group. The center's manager schedules a session with `peer_group_id`, `center_manager_id`, `start_time`, and `end_time`. The facilitator-mismatch check fires before the time-range check: the `center_manager_id` must be the manager of the group's center (`ERR_MANAGER_CENTER_MISMATCH`), and only then must the `end_time` be strictly later than `start_time` (`ERR_INVALID_TIME_RANGE`) — a request that violates both surfaces `ERR_MANAGER_CENTER_MISMATCH`. Sessions occupy their facilitator's calendar as **closed intervals padded by a 30-minute buffer on both sides**: the new session is padded by 30 minutes on both sides as well, and it collides with any of the same manager's `SCHEDULED` or `COMPLETED` sessions whose padded interval intersects the new session's padded interval. Padded intervals are closed, so two that merely touch at a single boundary instant still intersect — a raw gap of exactly 60 minutes between one session's end and the next session's start collides at the shared padded boundary — and any adjacency inside the combined buffer is rejected with `ERR_TRAINING_SLOT_OVERLAP`. The very first session for a group requires the group still `FORMING` (`ERR_GROUP_NOT_FORMING`) and a `member_count` of exactly 5 (`ERR_GROUP_SIZE_INVALID`); scheduling it moves the group `FORMING → TRAINING`.

Completing a session — only possible while it is `SCHEDULED`, else `ERR_TRAINING_NOT_SCHEDULED` — increments the group's `completed_training_sessions`. When that counter reaches 2 with `member_count` still 5 and the group still `TRAINING`, the group moves `TRAINING → ACTIVE` and every member graduates `IN_TRAINING → ELIGIBLE`; completions of any further `SCHEDULED` sessions push the counter past 2 without repeating the graduation. A session may instead be cancelled from `SCHEDULED`, moving it to `CANCELLED`.

### 3.3. Loan Applications and Unanimous Peer Consensus

Once a group is `ACTIVE`, a `FieldOfficer` drafts an application for one of its members, supplying `member_id` and `requested_amount_cents`. The requested principal must be a positive multiple of 100 cents, or the draft is refused with `ERR_INVALID_REQUEST`. Drafting is intentionally lax beyond that: neither the group's state nor the applicant's status is consulted at draft time, so even a blacklisted member may hold a `DRAFT` application — every gate fires at submission instead. The application records the group from the URL path and rests in `DRAFT`.

Submitting the application to group consensus is the most heavily gated transition in the lending pipeline, and its gates fire in pinned order. First the application must be `DRAFT` (`ERR_APPLICATION_NOT_DRAFT`). Then the blacklist screen (`ERR_MEMBER_BLACKLISTED`) outranks even the applicant-eligibility check: a `BLACKLISTED` applicant is refused with `ERR_MEMBER_BLACKLISTED` rather than `ERR_MEMBER_NOT_ELIGIBLE`. Next the applicant must be `ELIGIBLE` or `ACTIVE_BORROWER` (`ERR_MEMBER_NOT_ELIGIBLE`); must carry a `consecutive_absence_streak` below 2 — a streak of exactly 2 blocks submission with `ERR_ATTENDANCE_INELIGIBLE`; must have no other application in `DRAFT`, `VOTING`, or `APPROVED` (`ERR_MEMBER_HAS_OPEN_APPLICATION`); must hold no loan in `ACTIVE` or `DELINQUENT` (`ERR_MEMBER_HAS_ACTIVE_LOAN`); and their group must be `ACTIVE` (`ERR_GROUP_NOT_ACTIVE`). A successful submission moves the application `DRAFT → VOTING` and sets `voting_deadline` to the logical clock plus 7 days.

Voting belongs to the peers, and only the peers. A vote is cast by a `Member` with a `decision` of `APPROVE` or `REJECT`; the recorded `voter_member_id` is the caller's `X-User-ID`, and the vote binds to the application's `loan_application_id`. The application must be `VOTING` (`ERR_APPLICATION_NOT_VOTING`); the voter must belong to the applicant's group (`ERR_VOTER_NOT_GROUP_PEER`); the applicant may not vote on their own application (`ERR_VOTER_IS_APPLICANT`); each peer votes at most once (`ERR_ALREADY_VOTED`); and the vote must land strictly before the `voting_deadline` — a vote cast at or after that instant is rejected with `ERR_VOTING_WINDOW_EXPIRED`.

Two outcomes end the vote. When the fourth distinct non-applicant peer casts `APPROVE` — unanimous approval of all 4 non-applicant members, with the group's `ACTIVE` standing re-checked at that exact instant — the application becomes `APPROVED`; if the group is not `ACTIVE` at that instant the unanimous vote simply does not flip the application, which remains `VOTING` until the sweep or contagion ends it. Any single `REJECT` vote kills it immediately as `REJECTED`, even if the group is no longer `ACTIVE`. Two further forces can end a `VOTING` application without a verdict: the attendance cascade of §3.7 rejects it the moment the applicant picks up an attendance strike, and either the voting-expiry sweep or group contagion (§3.6) moves it to `EXPIRED`. On expiry semantics, note the asymmetry: the sweep expires an undecided application only when the logical clock is **strictly later** than `voting_deadline`, while a vote is already invalid **at** the deadline — so a vote landing exactly at the deadline fails with `ERR_VOTING_WINDOW_EXPIRED` against an application that is still `VOTING`.

### 3.4. Disbursement, the Loan Ladder, and Credit Bureau Reporting

Disbursement is a `BranchManager` act. The application must be `APPROVED` (`ERR_APPLICATION_NOT_APPROVED` — and per §2.8 this state check outranks the fiscal check); the applicant's group must be `ACTIVE` — a group under joint-liability restriction blocks disbursement with `ERR_GROUP_RESTRICTED`; the applicant must be `ELIGIBLE` or `ACTIVE_BORROWER` (`ERR_MEMBER_NOT_ELIGIBLE`); and the `requested_amount_cents` must not exceed the applicant's current ladder ceiling (`ERR_LADDER_CEILING_EXCEEDED`).

The ladder has two variants, selected by the member's rehabilitation history. **Standard** applies while `cured_delinquency_count` is 0: the ceiling is a pure lookup on `cycle_level` — 100,000 cents at rung 1, 200,000 at rung 2, 300,000 at rung 3, 400,000 at rung 4, and 500,000 at rung 5. **Rehabilitated** applies once `cured_delinquency_count` is at least 1: the ceiling is the *smaller* of the rung lookup and one-and-a-half times the `principal_cents` of the member's most recently created `PAID_OFF` loan, with the multiplier product rounded down (floored) to whole cents. Because a cured delinquency implies a previously repaid loan, the rehabilitated variant always has a history to draw on. Whichever ceiling governed the disbursement is recorded on the application as `applied_ceiling_cents`, computed against the member's `cycle_level` at the disbursement instant; the field is empty until then, and the application itself moves from `APPROVED` to its terminal `DISBURSED` status.

A successful disbursement creates the loan in one atomic bundle: `principal_cents` equal to the application's `requested_amount_cents`; a `cycle_level` snapshot of the member's rung; `term_weeks` fixed at 24 weekly installments; status `ACTIVE`; `next_due_date` set to the disbursement instant plus 7 days; `installments_on_time` and `installments_missed` at 0; and `principal_outstanding_cents` initialized to `term_weeks` times `weekly_installment_cents`. This is flat-rate lending: the outstanding balance is the full scheduled total, and every applied dollar retires it — after any history of collections, `principal_outstanding_cents` equals that initial value minus the sum of `principal_applied_cents` across the loan's `POSTED` transactions. Retrieving the loan born of an application yields an array of zero or one loans.

The installment and savings split is computed at disbursement (and again at restructure, §3.9) with a pinned evaluation order. The base cost of credit is a flat rate of 0.004 of principal per week. The rehabilitation branch adjusts the rate, not the principal: with a `cured_delinquency_count` of at least 1 the rate becomes the flat rate plus 0.001 per week, and with a count of at least 3 the rate is instead the flat rate plus 0.002 per week — the higher step replaces the lower one rather than stacking on it. The `weekly_installment_cents` is then the principal grown by that weekly rate over the full term — principal times one-plus-rate-times-`term_weeks` — divided by `term_weeks`, rounded half up to whole cents. The mandatory savings per collection, `savings_required_cents`, is the larger of 200 cents and a percentage of the weekly installment rounded half up: 2% at rung 1, 3% at rung 2, 4% at rung 3, and 5% at rungs 4 and 5. The rung that drives this percentage is the loan's `cycle_level` — at disbursement the member's own rung, at restructure (§3.9) the loan's snapshot rung, which may differ from the member's by then.

Disbursement also opens the member's `SavingsAccount` if none exists yet (`OPEN`, balance zero — one account per member), moves a first-time borrower `ELIGIBLE → ACTIVE_BORROWER`, and files a `PROVISIONAL` credit bureau report whose `score_reported` is the provisional score. The member's readable `credit_score` is the provisional score while any of their loans is `ACTIVE` or `DELINQUENT`; with no open loan it is the final score of their most recently terminated loan, re-evaluated at read time through the final-score formula below (so attendance strikes or `CLOSED`-transition attendance that landed after filing still move the readable figure, rather than the readable figure replaying the filed report's frozen value); and a member who has never held a loan reads 600.

The two scoring formulas share a 600-point base and a hard clamp to the band 300 through 850, but differ in what they count. The **provisional** score credits the future: start at 600, add 10 points per `installments_on_time`, add 5 points per remaining scheduled installment — where the remaining count is `term_weeks` minus the sum of `installments_on_time` and `installments_missed`, floored at zero so a loan whose counters exceed its term never subtracts projected credit — subtract 30 points per `installments_missed`, and subtract 15 points per `attendance_strikes`. A member mid-cycle with no activity at all therefore reads 720 provisionally. The **final** score, filed when a loan reaches `PAID_OFF` or `DEFAULTED` as a `FINAL` report, counts only actuals: 600 plus 10 per on-time installment, minus 30 per missed installment, plus 2 per meeting attended during the loan's lifetime — attendance rows with `present` true whose meeting's `CLOSED` transition falls inside the window from the loan's disbursement instant on the logical clock through its terminal transition on the logical clock, inclusive at both ends — minus 15 per `attendance_strikes`, with no projected credit and the same 300–850 clamp. A member's `attendance_strikes` accumulate over their whole membership and feed every score, not just the striking loan's cycle. When the member has several terminated loans, the most recently terminated one governs (ties broken by creation order). A filed `FINAL` report's `score_reported` is evaluated against the state of the world at the filing instant: in particular, the meeting whose collection drives a payoff is still `OPEN` at that instant and closes only afterward, so its attendance never counts toward the filed report — though when its `CLOSED` transition later lands within the (inclusive) window, it does count toward the read-time re-evaluation of the readable `credit_score`.

### 3.5. Weekly Center Meetings: Scheduling, Attendance, and Collections

The center meeting is where the program touches cash. The center's manager schedules one with `center_id`, `scheduled_start`, and `scheduled_end`. The `scheduled_end` must be strictly later than `scheduled_start` (`ERR_INVALID_TIME_RANGE`); the UTC weekday of `scheduled_start` must equal the center's `meeting_day_of_week` (`ERR_MEETING_DAY_MISMATCH`); and the meeting occupies its center's calendar as a **half-open interval** — it collides with any other non-`CANCELLED` meeting of the same center whose interval intersects it, failing with `ERR_MEETING_OVERLAP`, while two meetings that merely touch at a boundary are allowed. This half-open rule is deliberately different from the padded closed-interval rule for training sessions (§3.2). A scheduled meeting may be cancelled while `SCHEDULED` (`ERR_MEETING_NOT_SCHEDULED`), moving it to `CANCELLED`; a meeting carries two independent state dimensions at once — a `status` dimension (`SCHEDULED → OPEN → CLOSED`, or `CANCELLED`) and a `settlement_status` dimension (`PENDING → POSTED → RECONCILED`, with `DISPUTED` as a retryable branch) that only advances after close.

Opening a meeting requires it to be `SCHEDULED` (`ERR_MEETING_NOT_SCHEDULED`) and requires the acting `CenterManager` — identified by `X-User-ID` — to be the manager of the meeting's center (`ERR_NOT_CENTER_MANAGER`). Cancelling a meeting carries no such ownership check: any `CenterManager` may cancel a `SCHEDULED` meeting. While `OPEN`, the manager records attendance rows upsert-style with `member_id` and a boolean `present` (true marking the member `PRESENT`, false `ABSENT`) — re-recording a member overwrites the existing row's flag rather than creating a second row; the meeting must be `OPEN` (`ERR_MEETING_NOT_OPEN`) and the member's group must sit at this meeting's center (`ERR_MEMBER_NOT_AT_CENTER`).

Collections are the in-person repayments, also taken only while the meeting is `OPEN`. The manager posts one with `member_id`, `loan_id`, and `amount_cents`. The loan must belong to the paying member (`ERR_LOAN_MEMBER_MISMATCH`), the member's group must sit at the meeting's center (`ERR_MEMBER_NOT_AT_CENTER`), and the loan must be `ACTIVE` or `DELINQUENT` (`ERR_LOAN_NOT_REPAYABLE`). Every collection then flows through a four-bucket waterfall in pinned order:

1. **Savings first.** `savings_applied_cents` is always exactly the loan's `savings_required_cents`. A collection whose `amount_cents` is less than `savings_required_cents` plus 1 is refused outright with `ERR_COLLECTION_BELOW_SAVINGS_MINIMUM` — every repayment must fund the savings deposit and retire at least one cent of debt.
2. **Arrears.** What remains applies to consumed-but-unpaid installments, oldest due date first. Each fully covered installment consumes one `weekly_installment_cents`; a partial remainder smaller than one installment is still applied against the oldest remaining due — such a partial payment reduces the balance but neither retires that installment nor counts toward cure: only whole-installment units count (an installment is "covered" when the total applied in buckets 2–3 reaches the next whole multiple of `weekly_installment_cents`, so two partial collections that together complete one installment do retire it).
3. **Current installment.** Up to one `weekly_installment_cents` against the currently due installment.
4. **Prepayment.** Any remainder retires outstanding principal directly, capped at the outstanding left after buckets 2 and 3; the cap can only bind when the remainder is negative, which never occurs for an admissible collection, so the bound `ERR_COLLECTION_EXCEEDS_OUTSTANDING` below is the operative ceiling. Collections never overpay: an `amount_cents` exceeding `savings_required_cents` plus the loan's current `principal_outstanding_cents` is rejected with `ERR_COLLECTION_EXCEEDS_OUTSTANDING`.

The recorded `installment_applied_cents` is the sum applied in buckets 2 and 3, and the recorded `principal_applied_cents` adds the bucket-4 prepayment to it. An installment counts toward `installments_on_time` only when the collection's logical posting time is at or before the loan's current `next_due_date`; when the posting time is later, the covered installments are recorded against neither `installments_on_time` nor `installments_missed` — they simply reduce the outstanding balance as plain payment. Due dates the sweep consumed unpaid instead accrue to `installments_missed`. Each posted transaction remembers its `center_meeting_id`, `loan_id`, and `member_id`, begins in `POSTED`, credits the savings bucket to the member's account (§3.8), and refreshes the member's readable `credit_score` (a derived read-time value, §3.4). A collection that clears every consumed arrears installment fires the cure chain of §3.6; one that drives `principal_outstanding_cents` to zero fires the payoff chain of §3.4.

### 3.6. Delinquency, Cure, and Joint-Liability Contagion

The delinquency sweep runs after every logical-clock move. It walks all loans in `ACTIVE` or `DELINQUENT` ordered by `next_due_date` ascending, ties broken by the loan's `created_at` ascending. Lateness is measured in whole days: the floor of elapsed seconds since a due date divided by 86,400. For each loan, while its `next_due_date` is at least 8 days past due, the sweep consumes that due — `installments_missed` increments and `next_due_date` advances by 7 days — and the first consumed due on an `ACTIVE` loan flips it to `DELINQUENT`. The boundary is exact: a due date 7 days past leaves the loan `ACTIVE`; at 8 days it flips. After the consumption loop, a `DELINQUENT` loan whose oldest consumed-but-unpaid due has reached at least 30 days past due hardens into `DEFAULTED`; at 29 days it remains `DELINQUENT`.

The flip to `DELINQUENT` is where joint liability bites, in a three-hop contagion that completes inside the sweep request. Hop one: the borrowing member moves `ACTIVE_BORROWER → DELINQUENT`. Hop two: the member's group's `delinquent_loan_count` — the count of group members' loans in `DELINQUENT` or `DEFAULTED` — increments, and since a group is restricted whenever that count is at least 1 (exactly one delinquent loan is enough), an `ACTIVE` group moves to `RESTRICTED`. Hop three: every *other* group member's `ACTIVE` loan has its ladder advancement frozen — no `cycle_level` increment at payoff while the group is `RESTRICTED` — and every `VOTING` application belonging to any member of the group is moved to `EXPIRED`, because joint liability forbids new lending while any member is delinquent.

Cure runs the chain in reverse. When a collection's arrears bucket retires every consumed unpaid installment, the loan moves `DELINQUENT → ACTIVE`; once the member holds no remaining `DELINQUENT` loan, the member moves `DELINQUENT → ACTIVE_BORROWER` with `cured_delinquency_count` incremented — the counter that later selects the rehabilitated ladder variant and the penalty rate; and the group's `delinquent_loan_count` is recomputed, returning the group `RESTRICTED → ACTIVE` and lifting the ladder freeze the moment the count reaches zero.

Default is the point of no return. When a loan reaches `DEFAULTED`, the member becomes `BLACKLISTED` — whether they were `ACTIVE_BORROWER` or `DELINQUENT` — their savings account is frozen `OPEN → FROZEN`, a `FINAL` bureau report is filed, and the group's `member_count` is recomputed excluding the blacklisted member. The group's `delinquent_loan_count` is deliberately unchanged — a `DEFAULTED` loan still counts — so the group stays `RESTRICTED` even after the default.

Payoff is the happy ending: when a collection drives `principal_outstanding_cents` to zero, the loan becomes `PAID_OFF`, a `FINAL` bureau report is filed with the final score, and the member's `credit_score` is re-evaluated as no longer provisional. At the payoff instant, every scheduled installment neither yet covered nor consumed by the sweep is credited to `installments_on_time` when the payoff's posting time is at or before that installment's future due date (walking 7-day steps from the current `next_due_date`), and skipped when later. The ladder then advances — `cycle_level` increments by one, capped at rung 5 — but only if `installments_missed` is zero *and* the member's group is not `RESTRICTED` at that moment; a payoff with any missed installment, or under a restricted group, leaves the rung unchanged.

A group that has run its course may be dissolved by a `FieldOfficer`. The group must be `ACTIVE` or `RESTRICTED` (dissolving a `FORMING` or `TRAINING` group fails with `ERR_INVALID_STATE`) and no member may hold a loan in `ACTIVE` or `DELINQUENT` (`ERR_GROUP_HAS_ACTIVE_LOANS`). Dissolution moves the group to `DISSOLVED` and is archival, not destructive: members keep their status and history, and each retains their `peer_group_id` for audit.

### 3.7. Meeting Close-Out, Cash Reconciliation, and Corrections

Closing a meeting is the trigger for the attendance cascade, and it belongs to the center's own manager — a meeting must be `OPEN` (`ERR_MEETING_NOT_OPEN`) and the caller must manage its center (`ERR_NOT_CENTER_MANAGER`). The close stamps `closer_user_id` with the caller's `X-User-ID` — the value the segregation-of-duties rule will check at reconciliation — and flips `settlement_status` from `PENDING` to `POSTED`. Every member of the center's groups in a counted status (`IN_TRAINING` through `DELINQUENT`) who has no attendance row for the meeting is auto-marked `ABSENT`; `RECRUITED` and `BLACKLISTED` members, though present in the group roster, are not auto-marked. Then the cascade walks three hops: each such counted member's `consecutive_absence_streak` is recomputed — a `PRESENT` resets it to 0, an `ABSENT` increments it; any member whose streak reaches exactly 2 gains one `attendance_strikes` and refreshes their readable `credit_score` (§3.4's derived read-time value); and any `VOTING` application whose applicant just received a strike is moved to `REJECTED`. Because the streak is recomputed only for members in a counted status, a `BLACKLISTED` member's streak is frozen at its blacklisting value and a re-add to a group inherits it.

Reconciliation is a `BranchManager` act on a `CLOSED` meeting (`ERR_MEETING_NOT_CLOSED`), and it is where segregation of duties is enforced: the reconciler's `X-User-ID` must differ from the meeting's `closer_user_id`, or the attempt fails with `ERR_SEGREGATION_OF_DUTIES`. The checks fire in a pinned order: a meeting that is already `RECONCILED` rejects with `ERR_ALREADY_RECONCILED` before the segregation rule is consulted, so even the meeting's own closer sees `ERR_ALREADY_RECONCILED` there. Otherwise the settlement must be `POSTED` or `DISPUTED`. The manager supplies `declared_cash_cents` — the physical cash counted — and the server compares it against the posted total: the sum of `amount_cents` over the meeting's `POSTED` repayment transactions, with `VOIDED` transactions excluded. Equality must be exact, with no tolerance band. A match moves `settlement_status` to `RECONCILED` and records the `declared_cash_cents`. A mismatch still records the declared figure but moves the settlement to `DISPUTED` and answers with `ERR_RECONCILIATION_MISMATCH` (HTTP 409) — a dispute is a state, not just an error, and reconciliation may be retried from `DISPUTED` until the figures agree.

Corrections to the cash record happen by voiding. A `BranchManager` may void a transaction while it is `POSTED` (`ERR_TXN_NOT_POSTED`), but only until the meeting is reconciled: once the meeting's settlement is `RECONCILED`, voiding is blocked with `ERR_MEETING_ALREADY_RECONCILED`. A void is an exact ledger reversal, not an approximation: the loan's `principal_outstanding_cents` grows back by the transaction's `principal_applied_cents`, the installment counters are decremented by the amounts that transaction had applied, the savings account's `balance_cents` is debited by the transaction's `savings_applied_cents`, and the member's readable `credit_score` shifts accordingly. A void is a mechanical reversal only: it never rewinds a state transition the transaction triggered — a loan paid off stays `PAID_OFF` even as its outstanding balance grows back positive, a cured loan stays `ACTIVE`, a filed `FINAL` report remains filed, and a ladder advancement stands. The transaction itself moves `POSTED → VOIDED`.

### 3.8. Member Savings: Locks, Withdrawals, and Closure

Every borrower carries exactly one savings account, opened automatically at their first disbursement in `OPEN` status; reading a member's account yields an array of zero or one accounts, and an operation that needs an account the member does not yet have fails with `ERR_ACCOUNT_NOT_FOUND`. Three figures define the account. `balance_cents` is the sum of `savings_applied_cents` over the member's `POSTED` repayment transactions minus the sum of withdrawal `amount_cents`. `locked_cents` collateralizes open debt: ten percent of the total `principal_outstanding_cents` across the member's loans in `ACTIVE` or `DELINQUENT`, rounded half up to whole cents. `withdrawable_cents` is the balance minus the locked amount, floored at zero.

Withdrawals belong to the account holder alone: a `Member` withdraws by supplying `amount_cents`; the account must be `OPEN` (`ERR_ACCOUNT_NOT_OPEN`) and the amount may not exceed `withdrawable_cents` (`ERR_WITHDRAWAL_EXCEEDS_AVAILABLE`) — a zero amount therefore succeeds against a zero `withdrawable_cents`, since it does not exceed it. A successful withdrawal reduces `balance_cents` by exactly `amount_cents`. Closure likewise belongs to the member and requires the account `OPEN` (`ERR_ACCOUNT_NOT_OPEN`), no loan in `ACTIVE` or `DELINQUENT` (`ERR_MEMBER_HAS_ACTIVE_LOAN`), and a `balance_cents` of exactly zero (`ERR_ACCOUNT_NOT_EMPTY`); closure moves the account `OPEN → CLOSED`. The frozen state enters only through blacklisting (§3.6): a `FROZEN` account can be restored to `OPEN` by a `ProgramAdmin` override, which requires the account to actually be `FROZEN` (`ERR_ACCOUNT_NOT_FROZEN`).

### 3.9. Loan Restructuring

When a borrower's repayment capacity changes mid-cycle, a `BranchManager` restructures the loan. The request supplies `new_term_weeks` — one of 12, 24, 36, or 48, and strictly greater than the number of whole installments already applied across the loan's history (each fully covered installment per §3.5 counts as one; partial payments do not) — together with the mandatory `expected_loan_version` guard of §2.7. Per §2.8, the malformed-payload check fires before the guard: an out-of-enum or too-small `new_term_weeks` is `ERR_INVALID_REQUEST`; a stale version is rejected with `ERR_STALE_LOAN_VERSION` (HTTP 412) once the payload is well-formed, before any other business rule engages. Restructures follow create-with-supersede semantics: the new record is born `ACTIVE` (the nominal `PROPOSED → ACTIVE → SUPERSEDED` lifecycle collapses its proposal phase into creation), and any previously `ACTIVE` restructure of the same loan is immediately moved to `SUPERSEDED`. The loan's `term_weeks` becomes `new_term_weeks`, and its `weekly_installment_cents` and `savings_required_cents` are recomputed through the same installment-and-savings split of §3.4, applied to the *remaining* outstanding principal over the new term — rehabilitation rate steps included, based on the member's `cured_delinquency_count` at that instant, and the savings percentage taken from the loan's snapshot `cycle_level`. Nothing else is re-anchored: the loan's `next_due_date`, `principal_outstanding_cents`, and installment counters carry over unchanged. The loan's `version` increments, which is exactly what makes a concurrent stale restructure detectable. The full restructure history of a loan remains listable.

### 3.10. Branch Expansion Planning

Growth is planned, not improvised. A `BranchManager` submits an expansion plan for their branch with three inputs: `new_centers` (at least 1), `new_managers_hired` (at least 0), and `target_new_members` (at least 0) — violations of those floors are `ERR_INVALID_REQUEST`. Feasibility is computed at submission in a pinned evaluation order that deliberately uses only *current* membership for tiering, breaking what would otherwise be a circular dependency between tier, caps, and capacity:

1. Take `m`, the branch's current `active_member_count`.
2. Derive the tier from `m` alone — `SMALL` below 200, `MEDIUM` from 200 up to but not including 500, `LARGE` at 500 or more.
3. Read the caps for that tier: `member_cap` 60 / 80 / 100 and `center_cap` 3 / 4 / 5.
4. Count `mgrs`: the branch's existing center managers plus the plan's `new_managers_hired`.
5. Available capacity is `mgrs` times `member_cap` members, and `mgrs` times `center_cap` minus the branch's current center count in center slots.
6. Required capacity is `m` plus `target_new_members` members, and `new_centers` center slots.
7. The plan is feasible only when the required member capacity is at most the available member capacity **and** the required center slots are at most the available center slots — equality on either axis still counts as feasible.

The computed block is persisted on the plan as `feasibility`, carrying `required_member_capacity`, `available_member_capacity`, `required_center_slots`, `available_center_slots`, and the boolean `feasible`. A plan that fails the evaluation is refused outright with `ERR_EXPANSION_INFEASIBLE`; a feasible plan is created directly in `SUBMITTED` — the nominal `DRAFT → SUBMITTED → APPROVED | REJECTED` lifecycle means the draft phase is never observable through the API. A `ProgramAdmin` then decides a `SUBMITTED` plan with a `decision` of `APPROVE` or `REJECT`, moving it to `APPROVED` or `REJECTED`; deciding a plan in any other state fails with `ERR_PLAN_NOT_SUBMITTED`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify or transition an existing resource return `200 OK`. Reads return `200 OK`. Request payloads, preconditions, and side effects for every endpoint are defined by the narratives in §2 and §3; this table is only an index of the HTTP contract.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock; runs the delinquency and voting-expiry sweeps | ProgramAdmin |
| POST | `/branches` | Create a branch | ProgramAdmin |
| GET | `/branches/{id}` | Get a branch | ProgramAdmin, BranchManager, CenterManager, FieldOfficer, Member |
| GET | `/branches/{id}/center-managers` | List center managers of a branch | ProgramAdmin, BranchManager, CenterManager, FieldOfficer, Member |
| GET | `/branches/{id}/expansion-plans` | List expansion plans of a branch | ProgramAdmin, BranchManager, CenterManager, FieldOfficer, Member |
| POST | `/branches/{id}/expansion-plans` | Submit an expansion plan (feasibility computed at creation) | BranchManager |
| POST | `/expansion-plans/{id}/decide` | Approve or reject a submitted expansion plan | ProgramAdmin |
| POST | `/center-managers` | Hire a center manager into a branch | ProgramAdmin |
| GET | `/center-managers/{id}` | Get a center manager with computed caseload and caps | ProgramAdmin, BranchManager, CenterManager, FieldOfficer, Member |
| POST | `/centers` | Create a center under a branch (caps enforced) | ProgramAdmin |
| GET | `/centers` | List centers with optional filters | ProgramAdmin, BranchManager, CenterManager, FieldOfficer, Member |
| GET | `/centers/{id}` | Get a center | ProgramAdmin, BranchManager, CenterManager, FieldOfficer, Member |
| PATCH | `/centers/{id}` | Reassign a center to another manager of the same branch | ProgramAdmin |
| GET | `/centers/{id}/peer-groups` | List peer groups at a center | ProgramAdmin, BranchManager, CenterManager, FieldOfficer, Member |
| GET | `/center-managers/{id}/training-sessions` | List training sessions facilitated by a center manager | ProgramAdmin, BranchManager, CenterManager, FieldOfficer, Member |
| POST | `/peer-groups` | Create a peer group at a center | FieldOfficer |
| GET | `/peer-groups` | List peer groups with optional filters | ProgramAdmin, BranchManager, CenterManager, FieldOfficer, Member |
| GET | `/peer-groups/{id}` | Get a peer group with computed counters | ProgramAdmin, BranchManager, CenterManager, FieldOfficer, Member |
| GET | `/peer-groups/{id}/members` | List members of a peer group | ProgramAdmin, BranchManager, CenterManager, FieldOfficer, Member |
| POST | `/peer-groups/{id}/members` | Add a recruited member to a forming or training group | FieldOfficer |
| POST | `/peer-groups/{id}/dissolve` | Dissolve a group with no outstanding loans | FieldOfficer |
| GET | `/peer-groups/{id}/training-sessions` | List training sessions of a peer group | ProgramAdmin, BranchManager, CenterManager, FieldOfficer, Member |
| POST | `/peer-groups/{id}/loan-applications` | Draft a loan application for a member of the group | FieldOfficer |
| POST | `/members` | Recruit a member | FieldOfficer |
| GET | `/members` | List members with optional filters | ProgramAdmin, BranchManager, CenterManager, FieldOfficer, Member |
| GET | `/members/{id}` | Get a member with computed credit score | ProgramAdmin, BranchManager, CenterManager, FieldOfficer, Member |
| GET | `/members/{id}/votes` | List consensus votes cast by a member | ProgramAdmin, BranchManager, CenterManager, FieldOfficer, Member |
| GET | `/members/{id}/attendance` | List attendance rows of a member | ProgramAdmin, BranchManager, CenterManager, FieldOfficer, Member |
| GET | `/members/{id}/savings-account` | Get the member's savings account (array of 0 or 1) | ProgramAdmin, BranchManager, CenterManager, FieldOfficer, Member |
| POST | `/members/{id}/savings/withdrawals` | Withdraw savings as the account holder | Member |
| POST | `/members/{id}/savings/unfreeze` | Unfreeze a frozen savings account | ProgramAdmin |
| POST | `/members/{id}/savings/close` | Close an empty savings account with no open loans | Member |
| GET | `/members/{id}/bureau-reports` | List credit bureau reports filed for a member | ProgramAdmin, BranchManager, CenterManager, FieldOfficer, Member |
| POST | `/group-training-sessions` | Schedule a formation training session | CenterManager |
| GET | `/group-training-sessions` | List training sessions with optional filters | ProgramAdmin, BranchManager, CenterManager, FieldOfficer, Member |
| POST | `/group-training-sessions/{id}/complete` | Mark a training session completed | CenterManager |
| POST | `/group-training-sessions/{id}/cancel` | Cancel a scheduled training session | CenterManager |
| GET | `/loan-applications` | List applications with optional filters | ProgramAdmin, BranchManager, CenterManager, FieldOfficer, Member |
| GET | `/loan-applications/{id}` | Get an application | ProgramAdmin, BranchManager, CenterManager, FieldOfficer, Member |
| POST | `/loan-applications/{id}/submit` | Submit a draft application to group consensus | FieldOfficer |
| POST | `/loan-applications/{id}/votes` | Cast a consensus vote as a peer member | Member |
| GET | `/loan-applications/{id}/votes` | List votes on an application | ProgramAdmin, BranchManager, CenterManager, FieldOfficer, Member |
| GET | `/loan-applications/{id}/loan` | Get the loan created by this application (array of 0 or 1) | ProgramAdmin, BranchManager, CenterManager, FieldOfficer, Member |
| POST | `/loan-applications/{id}/disburse` | Disburse an approved application | BranchManager |
| GET | `/loans` | List loans with optional filters | ProgramAdmin, BranchManager, CenterManager, FieldOfficer, Member |
| GET | `/loans/{id}` | Get a loan with computed outstanding principal | ProgramAdmin, BranchManager, CenterManager, FieldOfficer, Member |
| POST | `/loans/{id}/restructures` | Create a restructure (create-with-supersede, OCC-guarded) | BranchManager |
| GET | `/loans/{id}/restructures` | List restructures of a loan | ProgramAdmin, BranchManager, CenterManager, FieldOfficer, Member |
| GET | `/loans/{id}/bureau-reports` | List credit bureau reports filed against a loan | ProgramAdmin, BranchManager, CenterManager, FieldOfficer, Member |
| POST | `/center-meetings` | Schedule a center meeting | CenterManager |
| GET | `/center-meetings` | List meetings with optional filters | ProgramAdmin, BranchManager, CenterManager, FieldOfficer, Member |
| GET | `/center-meetings/{id}` | Get a meeting (both state dimensions) | ProgramAdmin, BranchManager, CenterManager, FieldOfficer, Member |
| POST | `/center-meetings/{id}/open` | Open a scheduled meeting | CenterManager |
| POST | `/center-meetings/{id}/cancel` | Cancel a scheduled meeting | CenterManager |
| POST | `/center-meetings/{id}/attendance` | Record attendance for a member of the center | CenterManager |
| GET | `/center-meetings/{id}/attendance` | List attendance rows of a meeting | ProgramAdmin, BranchManager, CenterManager, FieldOfficer, Member |
| POST | `/center-meetings/{id}/collections` | Collect an in-person repayment | CenterManager |
| POST | `/center-meetings/{id}/close` | Close the meeting (absence auto-marking and strike cascade) | CenterManager |
| POST | `/center-meetings/{id}/reconcile` | Reconcile declared cash against posted collections | BranchManager |
| GET | `/repayment-transactions` | List transactions with optional filters | ProgramAdmin, BranchManager, CenterManager, FieldOfficer, Member |
| GET | `/repayment-transactions/{id}` | Get a transaction | ProgramAdmin, BranchManager, CenterManager, FieldOfficer, Member |
| POST | `/repayment-transactions/{id}/void` | Void a posted transaction | BranchManager |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of §2 and §3; this table is only an index of identifiers to status codes.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_BRANCH_NOT_FOUND` | 404 Not Found |
| `ERR_CENTER_MANAGER_NOT_FOUND` | 404 Not Found |
| `ERR_CENTER_NOT_FOUND` | 404 Not Found |
| `ERR_PEER_GROUP_NOT_FOUND` | 404 Not Found |
| `ERR_MEMBER_NOT_FOUND` | 404 Not Found |
| `ERR_APPLICATION_NOT_FOUND` | 404 Not Found |
| `ERR_LOAN_NOT_FOUND` | 404 Not Found |
| `ERR_MEETING_NOT_FOUND` | 404 Not Found |
| `ERR_TRAINING_SESSION_NOT_FOUND` | 404 Not Found |
| `ERR_TRANSACTION_NOT_FOUND` | 404 Not Found |
| `ERR_PLAN_NOT_FOUND` | 404 Not Found |
| `ERR_ACCOUNT_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_TIME_RANGE` | 400 Bad Request |
| `ERR_STALE_LOAN_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_APPLICATION_NOT_DRAFT` | 409 Conflict |
| `ERR_APPLICATION_NOT_APPROVED` | 409 Conflict |
| `ERR_APPLICATION_NOT_VOTING` | 409 Conflict |
| `ERR_MEETING_NOT_SCHEDULED` | 409 Conflict |
| `ERR_MEETING_NOT_OPEN` | 409 Conflict |
| `ERR_MEETING_NOT_CLOSED` | 409 Conflict |
| `ERR_ALREADY_RECONCILED` | 409 Conflict |
| `ERR_MEETING_ALREADY_RECONCILED` | 409 Conflict |
| `ERR_TXN_NOT_POSTED` | 409 Conflict |
| `ERR_ACCOUNT_NOT_OPEN` | 409 Conflict |
| `ERR_ACCOUNT_NOT_FROZEN` | 409 Conflict |
| `ERR_ACCOUNT_NOT_EMPTY` | 409 Conflict |
| `ERR_ALREADY_VOTED` | 409 Conflict |
| `ERR_PLAN_NOT_SUBMITTED` | 409 Conflict |
| `ERR_TRAINING_NOT_SCHEDULED` | 409 Conflict |
| `ERR_LOAN_NOT_REPAYABLE` | 409 Conflict |
| `ERR_MEMBER_BLACKLISTED` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_MEMBER_ALREADY_IN_GROUP` | 422 Unprocessable Entity |
| `ERR_VOTER_NOT_GROUP_PEER` | 422 Unprocessable Entity |
| `ERR_VOTER_IS_APPLICANT` | 422 Unprocessable Entity |
| `ERR_LOAN_MEMBER_MISMATCH` | 422 Unprocessable Entity |
| `ERR_MEMBER_NOT_AT_CENTER` | 422 Unprocessable Entity |
| `ERR_MANAGER_CENTER_MISMATCH` | 422 Unprocessable Entity |
| `ERR_MEETING_OVERLAP` | 409 Conflict |
| `ERR_TRAINING_SLOT_OVERLAP` | 409 Conflict |
| `ERR_VOTING_WINDOW_EXPIRED` | 409 Conflict |
| `ERR_MEETING_DAY_MISMATCH` | 422 Unprocessable Entity |
| `ERR_GROUP_NOT_FORMING` | 409 Conflict |
| `ERR_GROUP_SIZE_INVALID` | 409 Conflict |
| `ERR_GROUP_FULL` | 409 Conflict |
| `ERR_GROUP_NOT_ACTIVE` | 409 Conflict |
| `ERR_GROUP_RESTRICTED` | 409 Conflict |
| `ERR_GROUP_HAS_ACTIVE_LOANS` | 409 Conflict |
| `ERR_MEMBER_NOT_RECRUITED` | 409 Conflict |
| `ERR_MEMBER_NOT_ELIGIBLE` | 409 Conflict |
| `ERR_MEMBER_HAS_OPEN_APPLICATION` | 409 Conflict |
| `ERR_MEMBER_HAS_ACTIVE_LOAN` | 409 Conflict |
| `ERR_ATTENDANCE_INELIGIBLE` | 409 Conflict |
| `ERR_NOT_CENTER_MANAGER` | 409 Conflict |
| `ERR_CASELOAD_CAP_EXCEEDED` | 409 Conflict |
| `ERR_EXPANSION_INFEASIBLE` | 409 Conflict |
| `ERR_LADDER_CEILING_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_COLLECTION_BELOW_SAVINGS_MINIMUM` | 422 Unprocessable Entity |
| `ERR_COLLECTION_EXCEEDS_OUTSTANDING` | 422 Unprocessable Entity |
| `ERR_WITHDRAWAL_EXCEEDS_AVAILABLE` | 422 Unprocessable Entity |
| `ERR_RECONCILIATION_MISMATCH` | 409 Conflict |
