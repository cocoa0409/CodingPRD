# Education Savings Account Administration API — Product Requirements Document

## 1. Introduction

A state education savings account (ESA) programme sits at an awkward intersection of three institutions that normally never share a database: an eligibility bureau that decides which children may participate, a treasury that moves public money into thousands of family-controlled accounts four times a year, and an inspectorate that has to claw that money back when it is misspent. Today those three functions are run on spreadsheets and email. Seats are over-allocated because the waitlist is maintained by hand; a provider delisted on Tuesday is still being paid on Thursday; families discover in July that the balance they were counting on was forfeited in June because nobody explained the rollover cap. Every one of those failures is a decision that was made correctly in isolation and then lost on the way to the next desk.

This document specifies the API that replaces all three desks with one auditable system of record, mounted under the `/esa` path prefix. It governs the whole arc of participation: publishing an award year with a fixed seat pool and a submission window, taking applications from guardians, adjudicating residency and prior-enrolment and income-or-category criteria, ranking the eligible pool into offers and an ordered waitlist, opening a funded account when an offer is accepted, crediting quarterly disbursements net of an administration fee, screening and admitting the providers that may bill against those accounts, pre-approving or reimbursing individual purchases, detecting and clawing back misuse, verifying annual assessment or portfolio evidence for continued eligibility, and hearing appeals against denials, clawbacks and delistings.

Two design commitments run through every requirement that follows. The first is that public money is accounted for in whole cents with no floating-point residue: every entitlement, fee, penalty and forfeiture is an integer, and the order in which components are rounded is part of the specification rather than an implementation detail. The second is segregation of duties — no single operator may both authorise a payment and execute it, and no officer may sit in judgement on an appeal against their own earlier decision. Where those two commitments conflict with convenience, they win.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request, without exception, carries two mandatory headers: `X-User-ID` identifies the acting principal and `X-User-Role` declares the capacity in which it is acting. If either header is absent, or if `X-User-Role` is not one of the eight role names below, the request is rejected with `ERR_UNAUTHENTICATED`. When both headers are well formed but the declared role is not among the roles permitted for the endpoint being called, the rejection is `ERR_FORBIDDEN_ROLE`.

The eight recognised roles are `ProgramAdmin`, `EligibilityOfficer`, `ExpenseReviewer`, `VendorScreener`, `ComplianceOfficer`, `AppealsOfficer`, `Guardian`, and `Provider`.

A `ProgramAdmin` is the state programme operator: it owns programme-year setup, the allowable-expense catalogue, intake of student and provider records, and every operational run — award allocation, quarterly disbursement, year-end close, and the logical clock. An `EligibilityOfficer` adjudicates eligibility determinations and decides continued-eligibility renewals. An `ExpenseReviewer` decides the approval track of purchase requests and settles provider claims. A `VendorScreener` screens candidate providers for fraud indicators and admits them to participation with a pinned category authorisation. A `ComplianceOfficer` opens, reviews and adjudicates misuse cases, issues clawbacks, suspends and reinstates accounts, and sanctions or delists providers. An `AppealsOfficer` decides appeals.

Six of those eight are staff roles whose identity is opaque. When `X-User-Role` is `ProgramAdmin`, `EligibilityOfficer`, `ExpenseReviewer`, `VendorScreener`, `ComplianceOfficer`, or `AppealsOfficer`, the `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The server records it wherever a transition captures the acting operator — as `decided_by_user_id` on an eligibility determination or a renewal review or an appeal, as `screened_by_user_id` on a fraud screening, as `approved_by_user_id` and `settled_by_user_id` on a purchase request, as `opened_by_user_id`, `reviewed_by_user_id` and `adjudicated_by_user_id` on a misuse case, and as `created_by_user_id` on a clawback ledger row — but it is never compared against any entity's `id`.

The remaining two roles are entity-backed, and this is what ties `X-User-ID` to ownership. When `X-User-Role` is `Guardian`, `X-User-ID` is the `id` of the acting `Student`; every guardian write is checked by comparing the `student_id` of the application under operation — or the `student_id` of the application that funds the account under operation — against `X-User-ID`, and a mismatch is rejected with `ERR_NOT_ACCOUNT_HOLDER`. When `X-User-Role` is `Provider`, `X-User-ID` is the `id` of the acting `Provider`; a provider may act only on a purchase request whose `provider_id` equals `X-User-ID`, or file an appeal about itself, and a mismatch is rejected with `ERR_NOT_ASSIGNED_PROVIDER`.

Beyond role membership, the programme enforces separation between paired steps performed by different humans in the same staff role. The `ExpenseReviewer` whose `X-User-ID` was recorded as `approved_by_user_id` on a purchase request may not settle that request; the `ComplianceOfficer` adjudicating a misuse case may not be the reviewer who approved the purchase request the case names; and the `AppealsOfficer` deciding an appeal may not be the operator who authored the determination or adjudication under appeal. All three collapse to one rejection code, `ERR_SEGREGATION_OF_DUTIES`.

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

List-returning endpoints accept two query parameters. `limit` caps the number of records in the response; when omitted it defaults to 10, its minimum accepted value is 1 and its maximum accepted value is 100. `offset` is the number of records to skip before the page begins; when omitted it defaults to 0 and its minimum accepted value is 0. A `limit` outside the inclusive range 1 through 100, or a negative `offset`, is a malformed request and is rejected with `ERR_INVALID_REQUEST`.

Unless a specific endpoint states otherwise, every list is ordered by `created_at` ascending — oldest record first. This is why the determination history of an application, the screening history of a provider, the disbursements credited to an account and the clawback ledger rows of a case all read chronologically from the earliest event forward.

List responses carry `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the envelope, where `total_count` is the size of the whole filtered result set rather than of the returned page, and `has_more` states whether records remain beyond the current page.

### 2.4. Common Resource Properties and Append-Only Event Records

Every resource the API mints carries a server-generated `id`, formatted as a UUID with no type prefix of any kind, and a `created_at` timestamp expressed as an ISO 8601 UTC instant with exactly three fractional-second digits.

Most resources are mutable and therefore also carry two more system-managed fields. `updated_at` is an ISO 8601 UTC timestamp, refreshed on every change to the resource. `version` is an integer that starts at 1 when the resource is created and increases by exactly 1 on each subsequent mutation of that resource, including mutations the server performs on its own initiative as part of a cascade. The mutable resources are the programme year, the student record, the application, the account, the provider, the expense-category entry, the purchase request, the misuse case, the renewal review, and the appeal.

Four record types are append-only event evidence rather than mutable state, and they deliberately carry **only** `id` and `created_at` — they have no `updated_at` and no `version` field at all. Those four are the eligibility determination, the fraud screening, the disbursement, and the clawback ledger entry. Nothing in the system ever edits one of these rows; a correction is expressed by appending a further row, which is why a reversed clawback produces a new ledger entry rather than an amendment to the original.

### 2.5. The Logical Programme Clock

Deadlines, submission windows, service intervals and risk decay are all evaluated against a server-side logical UTC clock rather than against wall-clock time. Before any operator sets it, the logical clock reads exactly `2026-08-01T00:00:00Z`, and it never falls back to real time. A `ProgramAdmin` may move it by supplying a `to_iso8601` instant; the response reports the new setting as `current_utc`, and every subsequent evaluation of "now" — window gating, acceptance deadlines, `submitted_at`, `screened_at`, `issued_at`, and the months-since-screening term in the surveillance score — reads the value that was set.

### 2.6. Money, Precision and Rounding

All monetary quantities in this programme are integers denominated in whole cents, and they are transported as JSON integers, never as strings and never as decimal fractions of a dollar. There is no intermediate value that survives a step as a floating-point number: wherever a percentage, multiplier or rate is applied, the product is immediately reduced to whole cents before it participates in any further arithmetic.

The default reduction is **round half up**: a fractional cent of exactly one half is rounded away from zero to the next whole cent. Round half up is used for the income-scaled base component of an award, for each individual category add-on component, for the proration of an award across the quarters that remain, for the administration fee withheld from a disbursement, for the rollover cap at year-end close, for the penalty component of a clawback, and for the decayed screening term of a provider's surveillance score. One step deliberately uses a different rule: the even quarterly slice of a disbursement is computed by taking the integer floor of the division, with the indivisible remainder handled explicitly as described in §3.5.

Because each component is rounded before it is summed, the order of operations is load-bearing and is specified as such in every calculation below. Percentages are never added together and applied once.

Two ratios in the programme year are not money and keep the precision they were supplied with: `rollover_cap_pct` and `admin_fee_pct` are fractions, not cents. So is the `penalty_rate` recorded on a substantiated misuse case.

### 2.7. Version Guards Against Stale Reads

Two write operations in the programme commit new obligations against a record whose money or verified attributes another writer may have moved in the meantime, and in both cases no state precondition can catch the problem, because the second write is individually legitimate. Those two are guarded by an explicit optimistic-concurrency check on the parent record's `version`.

The first is filing a purchase request against an account. That request must carry `expected_account_version`, a non-optional integer field holding the `version` of the target `Account` as the client last observed it. If that value does not equal the account's current `version` at the moment the request is processed, the creation is rejected with `ERR_STALE_ACCOUNT_VERSION` and HTTP status 412. Two purchase requests on one account are perfectly legal, so nothing about the account's state would signal a problem; what the guard catches is a client whose picture of `balance_cents` and `encumbered_cents` predates another writer's approval hold, disbursement credit, or clawback debit. The client must re-read the account and retry against the moved balance. A successful creation itself advances the account's `version` by 1, so a client filing two requests back to back must re-read between them.

The second is filing a renewal review. That request must carry `expected_application_version`, a non-optional integer field holding the `version` of the `Application` behind the named account as the client last observed it. A mismatch against that application's current `version` is rejected with `ERR_STALE_APPLICATION_VERSION` and HTTP status 412. Here too the operation cannot be blocked by state: a second renewal review legitimately supersedes the first, moving the earlier review to `SUPERSEDED`. What the guard stops is a filing built on a stale view of the application, whose verified attributes drive the renewed award. A successful filing itself advances that application's `version` by 1.

No other endpoint takes a version field. Requests to endpoints outside these two must not be rejected for a version reason, and any version-like field they receive is simply not part of their contract.

### 2.8. The Order in Which a Request Is Rejected

Most requests can fail for several reasons at once, and which code the caller sees is part of the contract rather than an accident of implementation. Checks are evaluated strictly in the following order, and the first one that fails ends the request. This matters most in the middle of the ladder: a purchase request naming a suspended account, an ineligible provider, and an over-cap amount all at once reports the account suspension, because that check sits earlier.

1. Header presence and role recognition — `ERR_UNAUTHENTICATED`.
2. Role permitted on this endpoint — `ERR_FORBIDDEN_ROLE`.
3. Request shape: required fields present, enum values within their declared sets, integers non-negative where declared, ISO 8601 instants parseable, plain dates in `YYYY-MM-DD` form, `limit` within 1 through 100, `offset` at least 0 — `ERR_INVALID_REQUEST`.
4. The programme year named by the path or by `program_year_id` or `next_program_year_id` exists — `ERR_PROGRAM_YEAR_NOT_FOUND`. This applies to every programme-year path and to application creation and renewal-review filing.
5. The student named by the path or by `student_id` exists — `ERR_STUDENT_NOT_FOUND`, on student reads and application creation.
6. The application named by the path or by `application_id` exists — `ERR_APPLICATION_NOT_FOUND`, on every application path and on appeal filing.
7. The account named by the path or by `account_id` exists — `ERR_ACCOUNT_NOT_FOUND`, on every account path, on misuse-case creation and on renewal-review filing.
8. The provider named by the path or by `provider_id` exists — `ERR_PROVIDER_NOT_FOUND`, on every provider path, on purchase-request creation and on appeal filing.
9. The expense category named by `expense_category_id` exists, and every code supplied in `authorized_category_codes` matches an existing catalogue `code` — `ERR_EXPENSE_CATEGORY_NOT_FOUND`, on catalogue reads, purchase-request creation and provider admission.
10. The purchase request named by the path or by `purchase_request_id` exists — `ERR_PURCHASE_REQUEST_NOT_FOUND`, on every purchase-request path and on misuse-case creation.
11. The misuse case named by the path or by `misuse_case_id` exists — `ERR_MISUSE_CASE_NOT_FOUND`, on every misuse-case path and on appeal filing.
12. The renewal review named by the path exists — `ERR_RENEWAL_REVIEW_NOT_FOUND`, on renewal-review reads and renewal decisions.
13. The appeal named by the path exists — `ERR_APPEAL_NOT_FOUND`, on appeal reads and appeal decisions.
14. Guardian ownership — `ERR_NOT_ACCOUNT_HOLDER`, on application submission, award acceptance, withdrawal, purchase-request creation, and on appeals whose `subject_type` is `APPLICATION_DENIAL` or `CLAWBACK`.
15. Provider ownership — `ERR_NOT_ASSIGNED_PROVIDER`, on the provider's invoice claim and on appeals whose `subject_type` is `PROVIDER_DELISTING`.
16. `expected_account_version` matches the account's current `version` — `ERR_STALE_ACCOUNT_VERSION`, on purchase-request creation.
17. `expected_application_version` matches the current `version` of the account's application — `ERR_STALE_APPLICATION_VERSION`, on renewal-review filing.
18. The governing programme year is in the status the operation demands — `ERR_PROGRAM_YEAR_NOT_ACTIVE`. Disbursement runs, year-end close and award acceptance demand `ACTIVE`; recording an eligibility determination demands `WINDOW_OPEN` or `AWARDING`; approving a renewal demands that the target year be `WINDOW_OPEN` or `ACTIVE`.
19. The submission window is open — `ERR_APPLICATION_WINDOW_CLOSED`, on application creation and on application submission.
20. The target record's current state permits the requested transition — `ERR_INVALID_STATE_TRANSITION`. This is the catch-all state guard on every action endpoint, and it also covers an acceptance deadline that has already passed, a disbursement run whose `quarter` is not exactly one more than `current_quarter`, and reinstatement attempted while a misuse case on the account is still live.
21. The account whose money would move is `ACTIVE` rather than `SUSPENDED` — `ERR_ACCOUNT_SUSPENDED`, on purchase-request creation, on the approval-track decision and on settlement.
22. The application has appeal rounds left — `ERR_APPEAL_ROUNDS_EXHAUSTED`, on appeal filing.
23. Segregation of duties — `ERR_SEGREGATION_OF_DUTIES`, on settlement, on misuse-case adjudication and on appeal decisions.
24. Fraud risk within tolerance — `ERR_FRAUD_RISK_TOO_HIGH`, on provider admission and on reinstatement from probation.
25. The named provider is participation-eligible for the requested `flow` — `ERR_PROVIDER_NOT_ELIGIBLE`, on purchase-request creation, on the approval-track decision and on settlement.
26. The category code is in the provider's `authorized_category_codes` — `ERR_CATEGORY_NOT_AUTHORIZED`, on purchase-request creation, on the approval-track decision and on settlement.
27. The category is marked `allowable` — `ERR_EXPENSE_NOT_ALLOWABLE`, on purchase-request creation.
28. Reimbursement is permitted for the category — `ERR_PREAPPROVAL_REQUIRED`, on purchase-request creation.
29. No overlapping enrolment period for the student — `ERR_OVERLAPPING_ENROLLMENT_PERIOD`, on application creation.
30. No colliding service interval — `ERR_DUPLICATE_SERVICE_PERIOD`, on purchase-request creation.
31. The service interval lies inside the instructional term — `ERR_SERVICE_PERIOD_OUTSIDE_TERM`, on purchase-request creation.
32. No duplicate live application for the same year — `ERR_DUPLICATE_APPLICATION`, on application creation.
33. Residency matches — `ERR_RESIDENCY_NOT_ELIGIBLE`, on application creation and on renewal decisions.
34. Renewal evidence clears the bar — `ERR_ASSESSMENT_EVIDENCE_INSUFFICIENT`, on a renewal decision of `APPROVED`.
35. The category's annual cap is not exceeded — `ERR_CATEGORY_CAP_EXCEEDED`, on purchase-request creation and on an approval-track decision of `APPROVED`.
36. The account balance covers the hold — `ERR_INSUFFICIENT_BALANCE`, on an approval-track decision of `APPROVED`.
37. A seat is available in the target year — `ERR_NO_SEATS_AVAILABLE`, on a renewal decision of `APPROVED`.
38. The claimed amount is within bounds — `ERR_CLAIM_AMOUNT_MISMATCH`, on the provider's invoice claim.

Where a URL nests one resource inside another — the determinations of an application, the disbursements or clawback entries of an account, the screenings of a provider, the clawback entries of a misuse case — path identifiers are resolved strictly left to right, and the first identifier that names nothing produces its own not-found code before any deeper identifier or body field is examined. A request for the disbursements of a non-existent account therefore reports `ERR_ACCOUNT_NOT_FOUND`, never an empty list.

### 2.9. Cascade Discipline

A great many writes in this programme touch more than one record, and the secondary movements are as much part of the contract as the primary one. Three cascade families recur, and each is specified in full where its workflow is described: **seat release and waitlist promotion**, where losing an offer hands the seat to the head of the waitlist; **hold release**, where voiding an approved purchase returns its encumbrance to spendable balance; and **suspension propagation**, where substantiating misuse suspends an account, which voids its open purchases, which releases their holds.

Cascades are transitive and are applied to completion within the originating request: if step one moves an account, and moving that account voids a purchase request, and voiding that purchase request moves money on the account again, all three effects land before the response is written. Every record touched anywhere in the chain has its own `updated_at` refreshed and its own `version` incremented by 1, including records the caller never named. Where a cascade runs a compensating movement, the compensation is exact — a released hold returns precisely the `amount_cents` that the approval encumbered, and a reversed clawback returns precisely the `account_debit_cents` that was debited, neither re-derived nor recomputed.

Cascades are not reversible by a later transition unless this document says so. Reinstating a suspended account does not revive the purchase requests that its suspension voided, and returning a delisted provider to probation does not revive the purchase requests that its delisting voided; in both cases the guardian must file fresh requests.

### 2.10. The Seat Pool Invariant

Each programme year publishes a hard capacity in `total_seats` and maintains two counters that the server owns outright. `seats_committed` is the number of applications for that year currently in either `AWARD_OFFERED` or `ACCEPTED`, and `seats_available` is `total_seats` less `seats_committed`, which is never allowed to go below zero. Both counters read 0 on a freshly created year; opening the submission window sets `seats_committed` to 0 and `seats_available` to the full `total_seats`.

Every event that puts an application into `AWARD_OFFERED` or `ACCEPTED` raises `seats_committed` by 1 and lowers `seats_available` by 1, and every event that takes an application out of those two states does the reverse. Offers made by an award run, promotions off the waitlist, and renewal applications minted in `AWARD_OFFERED` all consume a seat; expiries and withdrawals all release one. A seat released while any application is still waitlisted is not left idle — it is immediately handed to the waitlisted application holding the lowest `waitlist_position`, which itself consumes the seat again.

### 2.11. The Account Ledger Identity

An ESA account is a small ledger, and its fields are related by identities that must hold after every operation. `balance_cents` is unencumbered spendable money. `encumbered_cents` is money held against purchase requests that are approved but not yet settled; it is not part of the balance, it is never spent directly, and it is never rolled over or forfeited. Approving a purchase moves `amount_cents` out of `balance_cents` and into `encumbered_cents`; voiding that approval moves the same amount straight back; settling it removes `amount_cents` from `encumbered_cents`, records the invoiced portion as spend and returns only the unspent difference to `balance_cents`.

Alongside those two live counters, the account keeps cumulative history that only ever moves in the direction its name implies, except where an explicit reversal is specified: `lifetime_disbursed_cents` accumulates the gross entitlement credited by disbursement runs, `lifetime_admin_fee_cents` accumulates the administration fee withheld from those credits, `lifetime_spent_cents` accumulates settled spend net of reversals, and `lifetime_clawed_back_cents` accumulates amounts recovered by clawback net of reversals. `disbursement_count` counts the disbursement rows issued to the account. Year-end close writes `rollover_carried_cents` and `forfeited_cents`; renewal acceptance writes `rolled_out_cents` on the outgoing account and `rollover_in_cents` on the incoming one. `final_award_cents` and `quarters_remaining_at_award` are stamped once, at acceptance, and never change afterwards. `suspension_reason` holds free text while the account is `SUSPENDED` and is null while it is `ACTIVE`.

An account is in exactly one of `ACTIVE`, `SUSPENDED` or `CLOSED`. `SUSPENDED` blocks every debit and every credit — no purchase may be filed, approved or settled against it, and disbursement runs skip it. `CLOSED` is terminal: no disbursement, purchase, or clawback operation is accepted against a closed account and every such write returns `ERR_INVALID_STATE_TRANSITION`.

## 3. Business Logic & Workflows

### 3.1. Standing Up an Award Year and Publishing the Expense Catalogue

Everything in the programme hangs off a **programme year**, and a `ProgramAdmin` creates one before anything else can happen. The year is identified by a human-readable `label` such as "2026-27", which must be non-empty and must not duplicate the label of any other programme year, and it names the `residency_state` in which a student must live to be eligible for that year, given as exactly two uppercase letters. Capacity is fixed at creation through `total_seats`, which may be zero or any larger whole number. The submission period is bounded by `window_open_at` and `window_close_at`, both ISO 8601 UTC instants, and the second must fall strictly after the first; the window is inclusive of its opening instant and exclusive of its closing instant. The instructional period is bounded by `term_start_date` and `term_end_date`, plain `YYYY-MM-DD` dates, both inclusive, with the end date strictly after the start date.

Six further parameters may be supplied and otherwise take programme defaults. `base_award_cents` is the per-pupil base entitlement before any income multiplier or category add-on and defaults to 731500 — that is, seven thousand three hundred and fifteen dollars — and must be at least 1. `rollover_cap_pct` is the fraction of an account's prorated entitlement that may survive year-end close as carried balance; it defaults to 0.25, one quarter, and any value from 0 through 1 inclusive is accepted. `admin_fee_pct` is the fraction withheld from each quarterly credit as a programme administration fee; it defaults to 0.0175, one and three-quarter percent, and accepted values run from 0 up to but not including 1. `acceptance_deadline_days` is the number of days a guardian has to accept an offer before it lapses and defaults to 14, with a minimum of 1. `min_assessment_percentile` is the lowest norm-referenced percentile accepted as renewal evidence, inclusive, defaults to 40, and must lie between 0 and 100 inclusive. `min_portfolio_artifacts` is the smallest accepted portfolio artefact count, inclusive, defaults to 6, and must be at least 1.

A new year is born in `DRAFT` with its ops-run epoch `current_quarter` at 0 and both seat counters at 0. The `current_quarter` field only ever holds a value from 0 through 4 inclusive; 0 means no disbursement has yet been run for the year.

Publishing the year for applications advances it `DRAFT → WINDOW_OPEN`. The only precondition is that the year is currently in `DRAFT`; attempting it from any other state is rejected with `ERR_INVALID_STATE_TRANSITION`. On success `seats_committed` is set to 0, `seats_available` is set to the full `total_seats`, and the year's `version` rises by 1. Note that opening the window is necessary but not sufficient for a submission to be accepted: the logical clock must also stand at or after `window_open_at` and strictly before `window_close_at`.

Separately, and at any time, a `ProgramAdmin` publishes the allowable-expense catalogue. Each catalogue entry carries a stable uppercase-snake `code` such as "TUITION" that must be unique across the catalogue, a display `name`, and a `per_year_cap_cents` ceiling of at least 1 cent that limits how much one account may commit to that category within one programme year. Three booleans shape how the category behaves. `allowable` defaults to true; setting it false marks the code as catalogued-but-disallowed, and any purchase charged to it is refused with `ERR_EXPENSE_NOT_ALLOWABLE`. `requires_preapproval` defaults to true, and while it is true the reimbursement route is closed for that category — a purchase filed with the reimbursement flow against it is refused with `ERR_PREAPPROVAL_REQUIRED`. `requires_service_period` defaults to false; setting it true switches on the non-overlapping service-interval rule described in §3.7, and categories that leave it false are exempt from that collision check and may reuse the very same interval as often as the family likes.

### 3.2. Student Intake, Filing an Application and the Provisional Award

Student records are created by a `ProgramAdmin`, not by families. Each record carries a `household_id` — an opaque, non-empty grouping key used for sibling-priority bookkeeping — along with `first_name`, `last_name`, a `date_of_birth` in `YYYY-MM-DD` form, and the `residency_state` in which the child lives, again exactly two uppercase letters. Prior schooling is captured in `prior_enrollment`, which is one of `PUBLIC_SCHOOL_FULL_YEAR`, `PUBLIC_SCHOOL_PARTIAL`, `PRIVATE_SCHOOL`, `HOMESCHOOL`, or `ENTERING_KINDERGARTEN`. Household means are captured in `income_band`, one of `BAND_A`, `BAND_B`, or `BAND_C`. Two optional facts complete the record: `category_flags` is a duplicate-free subset of `DISABILITY_IEP`, `FOSTER`, `MILITARY`, and `PRIOR_PUBLIC_SCHOOL` and defaults to the empty list, and `has_enrolled_sibling` defaults to false and is set true when a sibling already holds an accepted award in any programme year.

A `Guardian` opens an application by naming the `program_year_id` it competes in and the `student_id` the award would follow, and by asserting the household's own view of its circumstances: `claimed_income_band`, again one of the three bands, and `claimed_category_flags`, a subset of the same four flag codes. The optional `is_renewal` flag defaults to false and marks the application as a continuation of a prior year's participation. A newly created application sits in `DRAFT` with `appeal_round_count` at 0, both award figures at 0, and no verified attributes yet — `verified_income_band` is null until a determination is recorded, and `verified_category_flags` starts as the empty list. The full set of states an application can occupy is `DRAFT`, `SUBMITTED`, `ELIGIBLE`, `DENIED`, `UNDER_APPEAL`, `DENIED_FINAL`, `AWARD_OFFERED`, `WAITLISTED`, `ACCEPTED`, `EXPIRED`, `WITHDRAWN`, and `COMPLETED`, of which `DENIED_FINAL`, `EXPIRED`, `WITHDRAWN`, and `COMPLETED` are terminal.

Four gates protect the creation itself, and they fire in the ladder order of §2.8. The programme year must be `WINDOW_OPEN` with the logical clock inside the window, or the request fails `ERR_APPLICATION_WINDOW_CLOSED`. The student must not already hold an offered, accepted, or completed application in a *different* programme year whose instructional term intersects the requested year's term — both terms are treated as fully inclusive date intervals, and applications for the same `program_year_id` are excluded from the comparison — or the request fails `ERR_OVERLAPPING_ENROLLMENT_PERIOD`. The student must not already have a live application for the same `program_year_id`, where "live" means any status other than `WITHDRAWN`, `DENIED_FINAL`, or `EXPIRED`, or the request fails `ERR_DUPLICATE_APPLICATION`. And the student's `residency_state` must equal the programme year's `residency_state`, or the request fails `ERR_RESIDENCY_NOT_ELIGIBLE`.

Submitting the application advances it `DRAFT → SUBMITTED`. The application must currently be in `DRAFT`, or the attempt is refused with `ERR_INVALID_STATE_TRANSITION`; the acting `X-User-ID` must equal the application's `student_id`, or it is refused with `ERR_NOT_ACCOUNT_HOLDER`; and the governing year must be `WINDOW_OPEN` with the logical clock at or after `window_open_at` and strictly before `window_close_at`, or it is refused with `ERR_APPLICATION_WINDOW_CLOSED`. On success the current logical instant is stamped into `submitted_at` — which later serves as the primary tie-break when the eligible pool is ranked — a provisional award figure is computed and stored in `provisional_award_cents`, and the application's `version` rises by 1.

The provisional figure is the **claimed** variant of the annual award computation, and it is derived entirely from what the guardian asserted, before anyone has verified anything. It proceeds in four steps.

- **Step one, the income tier.** The programme year's `base_award_cents` is multiplied by the multiplier for the applicable income band — a multiplier of 1.00, the full base, for `BAND_A`, 0.90, nine tenths of it, for `BAND_B`, and 0.75, three quarters of it, for `BAND_C` — and the product is rounded half up to whole cents. This is the base component. For the provisional figure the applicable band is `claimed_income_band`.
- **Step two, a deterministic add-on order.** The admitted category flags are sorted by their add-on percentage from largest to smallest, and any tie on percentage is broken by the flag code in ascending alphabetical order. The add-on percentages are 0.375 of the base — three eighths — for `DISABILITY_IEP`, 0.225 for `FOSTER`, 0.125 for `MILITARY`, and 0.0625 for `PRIOR_PUBLIC_SCHOOL`. This ordering is never taken from insertion order and never from any record identifier. For the provisional figure the admitted flags are `claimed_category_flags`.
- **Step three, a waterfall against the aggregate cap.** Add-ons in total may not exceed 0.45 of the base, that is forty-five percent. A running total of consumed percentage starts at zero. For each flag in the order fixed by step two, the percentage actually allowed is the smaller of that flag's own percentage and the cap less the running total. If the allowed percentage is zero or less, consumption stops and the remaining flags contribute nothing. Otherwise the base is multiplied by the allowed percentage, the product is rounded half up to whole cents to give that flag's add-on component, and the allowed percentage is added to the running total. The crucial detail is that the flag which meets the cap is **truncated to the cap remainder** — it is neither dropped entirely nor admitted in full.
- **Step four, a rounding order that is load-bearing.** The annual figure is the base component plus the sum of the individually rounded add-on components. Percentages are never summed first and applied to the base once. The two orders genuinely differ: for `BAND_B` with the flags `DISABILITY_IEP` and `PRIOR_PUBLIC_SCHOOL`, rounding each component before summing yields 978382 cents, whereas summing the percentages first would yield 978381.

The claimed variant stops there and always assumes the whole four-quarter year, so `provisional_award_cents` receives the step-four figure with no proration whatsoever. Two boundary behaviours are worth stating plainly. With no admitted flags at all the annual figure equals the base component exactly — 731500 for `BAND_A` and 548625 for `BAND_C` against the default base. With a flag set whose raw percentages together exceed the cap, the lowest-percentage admitted flag is truncated so the running total lands exactly on 0.45: `BAND_A` with `DISABILITY_IEP` and `FOSTER` yields 1060676, not 1060675. A flag code outside the declared four is not silently scored as zero — it is rejected at input validation with `ERR_INVALID_REQUEST`.

Applications are discoverable in bulk, filtered by any combination of `program_year_id`, `student_id`, and `status`, and that listing is the canonical reverse lookup for both of the application's own foreign keys as well as for the identifier a renewal review records once it mints a successor.

### 3.3. Adjudicating Eligibility, Priority Tiers and Award Scoring

An `EligibilityOfficer` adjudicates a submitted application by recording a **determination**, which is append-only evidence: each determination is a new row and no earlier row is ever edited. The officer supplies five findings. `residency_check` and `prior_enrollment_check` are each either `PASS` or `FAIL`. `verified_income_band` is the band confirmed from documentation, one of `BAND_A`, `BAND_B`, or `BAND_C`. `verified_prior_enrollment` is the prior-schooling status confirmed from documentation, one of the same five values the student record uses. `verified_category_flags` is the subset of the four category codes confirmed from documentation. The row also captures `application_id` and the officer's own `X-User-ID` as `decided_by_user_id`, and it carries a `round_number` that is 1 for the first determination on an application and one higher on each post-appeal re-determination.

Recording a determination requires the application to be in `SUBMITTED`, or the attempt is refused with `ERR_INVALID_STATE_TRANSITION`, and it requires the governing programme year to be either `WINDOW_OPEN` or `AWARDING`, or it is refused with `ERR_PROGRAM_YEAR_NOT_ACTIVE`.

The determination's `outcome` is derived, not supplied. It is `ELIGIBLE` when `residency_check` is `PASS`, `prior_enrollment_check` is `PASS`, and the income-or-category criterion is met — that criterion being satisfied when `verified_income_band` is either `BAND_A` or `BAND_B`, or, whatever the band, when `verified_category_flags` is not empty. Otherwise the outcome is `INELIGIBLE`, which happens when residency fails, or prior enrolment fails, or the band is `BAND_C` with no confirmed category flags at all.

An `ELIGIBLE` outcome advances the application `SUBMITTED → ELIGIBLE`. The determination's `verified_income_band`, `verified_category_flags`, `priority_tier`, `priority_score`, and `annual_award_cents` are copied onto the application, and the application's `version` rises by 1.

An `INELIGIBLE` outcome advances the application `SUBMITTED → DENIED`. The row records `denial_reason_code` by strict first-match order: `RESIDENCY` when `residency_check` is `FAIL`; otherwise `PRIOR_ENROLLMENT` when `prior_enrollment_check` is `FAIL`; otherwise `INCOME_OR_CATEGORY`. On an eligible outcome `denial_reason_code` is null. Even on a denial, `verified_prior_enrollment` is still recorded on the row for the audit trail. The application's `annual_award_cents` stays at 0 and its `priority_tier` and `priority_score` both stay at 0, and its `version` rises by 1.

For an eligible outcome the officer's findings feed two derived quantities that decide who gets a seat. The **priority tier** is chosen by walking a five-rung ladder from the top and stopping at the first rung that matches, so a lower tier number always wins outright:

1. Tier 1, renewal — the application's `is_renewal` is true.
2. Tier 2, sibling — the student's `has_enrolled_sibling` is true *and* some other application in the same programme year, whose student shares this student's `household_id`, currently sits in `AWARD_OFFERED` or `ACCEPTED`.
3. Tier 3, prior public and low income — the determination's `verified_prior_enrollment` is `PUBLIC_SCHOOL_FULL_YEAR` *and* its `verified_income_band` is `BAND_A`.
4. Tier 4, category — `verified_category_flags` is not empty.
5. Tier 5, open — none of the above.

The **priority score** is the sum of three terms. The income term is one hundred points scaled by the weight of the verified band — a weight of 1.0 for `BAND_A`, 0.6 for `BAND_B`, and 0.25 for `BAND_C` — rounded half up to a whole number; this is the only rounding in the whole computation, and it happens before the other terms are added. The category term adds 40 points for `DISABILITY_IEP`, 30 for `FOSTER`, 15 for `MILITARY`, and 10 for `PRIOR_PUBLIC_SCHOOL`, once for each confirmed flag. The sibling term adds a flat 25 points, and only when the ladder above landed on tier 2. The result is always a whole number.

When the eligible pool is later ranked, the ordering is by `priority_tier` ascending first, then by `priority_score` descending, then by `submitted_at` ascending, and finally by `created_at` ascending. The record identifier is never a sort key and never a tie-break. Because `created_at` is unique per insert, two applications identical on tier, score and submit instant still resolve deterministically. The tier is the primary key of the ordering and the score never overrides it: an application in tier 1 with a low score outranks an application in tier 5 with a score of 100. A `BAND_C` application with no confirmed flags scores exactly 25 and lands in tier 5, the last rank position. And because tier and score are stamped only by a determination, an application still sitting in `SUBMITTED` carries 0 for both and simply is not in the ranked pool at all.

The `annual_award_cents` the determination stamps is the **verified** variant of the award computation: the same four-step ladder as the provisional figure, but reading `verified_income_band` and `verified_category_flags` from this determination instead of the guardian's claims, and still with no proration. On the same application the two variants routinely disagree — a claimed set that produces 978382 may verify down to 932663 — which is exactly why the provisional figure is never treated as an entitlement.

The full determination history of one application is retrievable, oldest round first.

### 3.4. The Award Run, Offers and the Ordered Waitlist

Award allocation is a single operational run driven by a `ProgramAdmin`, and it carries the programme year through two transitions inside one request: `WINDOW_OPEN → AWARDING` and then, once allocation completes, `AWARDING → ACTIVE`. The year must be in `WINDOW_OPEN` when the run starts, or the run is refused with `ERR_INVALID_STATE_TRANSITION`. `AWARDING` is transient — it is entered and left within the same request and is never observable as a resting state — but it is a real transition and the year's `version` rises by 1 for each of the two moves.

One consequence of the first move deserves emphasis because it closes intake permanently: from the moment the year leaves `WINDOW_OPEN`, no application can be submitted any more. Every later submission attempt fails with `ERR_APPLICATION_WINDOW_CLOSED`, because the year is no longer `WINDOW_OPEN` — independently of whether the logical clock has yet reached `window_close_at`.

The candidate set is every application belonging to this programme year whose status is `ELIGIBLE`, ranked by the tier-then-score-then-submit-instant-then-creation-instant ordering of §3.3. Working down that ranked list, the first `seats_available` candidates move `ELIGIBLE → AWARD_OFFERED`; each one stamps `acceptance_deadline_at` at the current logical instant plus the year's `acceptance_deadline_days` days, raises `seats_committed` by 1, lowers `seats_available` by 1, and has its own `version` incremented. Every candidate beyond that point moves `ELIGIBLE → WAITLISTED` and receives a `waitlist_position` of 1, 2, 3 and so on in the very same rank order; a waitlisted application consumes no seat, and its `version` is incremented too. When the year has no eligible candidates at all the run is still valid and still succeeds: nothing is offered, nothing is waitlisted, and the year still reaches `ACTIVE`.

The run reports what it did. `awarded_count` and `waitlisted_count` give the two population sizes, `program_year_status` echoes the year's resulting status, `seats_committed` and `seats_available` give the recomputed counters — `seats_committed` being the count of applications now in `AWARD_OFFERED` or `ACCEPTED` and `seats_available` being `total_seats` less that count — while `awarded_application_ids` lists the offered applications and `waitlist_ordered_application_ids` lists the waitlisted ones in waitlist order.

Promotion off the waitlist is never an explicit request; it is a cascade that fires whenever a seat is released, whether by a withdrawal, by an offer expiring, or by any other seat return. The application promoted is the one holding the **minimum** `waitlist_position` among the waitlisted applications of that programme year, and promotion requires at least one seat to be available. On promotion the application moves `WAITLISTED → AWARD_OFFERED`, its `waitlist_position` is set to null, a fresh `acceptance_deadline_at` is stamped at the current logical instant plus `acceptance_deadline_days` days, `seats_committed` rises by 1 and `seats_available` falls by 1 — which means a single released seat is consumed again immediately — and the application's `version` rises by 1. The applications still on the waitlist keep the `waitlist_position` values they already hold; positions are never renumbered to close the gap, so after the holder of position 1 is promoted the head of the queue is the application at position 2.

### 3.5. Accepting an Offer, Opening the Account and Quarterly Funding

An offer is worthless until the family takes it. Acceptance moves the application `AWARD_OFFERED → ACCEPTED` and is available only to the `Guardian` behind it. Five conditions gate it. The application must currently be in `AWARD_OFFERED`, the acting `X-User-ID` must equal the application's `student_id` — a mismatch is `ERR_NOT_ACCOUNT_HOLDER` — the logical clock must be strictly before `acceptance_deadline_at`, the programme year must be `ACTIVE`, and the year's `current_quarter` must be no greater than 3. A stale deadline, a wrong current state, and a year already past its third quarter all report `ERR_INVALID_STATE_TRANSITION`; a year in the wrong lifecycle state reports `ERR_PROGRAM_YEAR_NOT_ACTIVE`. The last of those five exists because an award with no quarters left to fund cannot be honoured, which is also why a fully prorated award can never come out at zero.

Acceptance is where the verified award becomes money. The number of quarters that remain is four less the year's `current_quarter`. The prorated entitlement is the application's verified `annual_award_cents` multiplied by the quarters that remain, divided by four, and rounded half up to whole cents; it is written to the application's `final_award_cents`. With a verified annual figure of 932663 that yields 932663 when four quarters remain, 699497 when three remain, and 466332 when two remain — the identity being that a full four quarters leaves the annual figure untouched.

The same transition opens the ESA account, and it is the only way an account ever comes into existence. The new account starts in `ACTIVE`, records the `application_id` of the accepted award and, denormalised from it for disbursement-run scoping, the `program_year_id`. It copies `final_award_cents` from the application, sets `quarters_remaining_at_award` to four less the year's `current_quarter` — a value between 1 and 4 — and starts with `balance_cents` at 0, `encumbered_cents` at 0, every lifetime counter at 0, `disbursement_count` at 0, and `suspension_reason` null. Because both `AWARD_OFFERED` and `ACCEPTED` count as committed, acceptance leaves `seats_committed` and `seats_available` unchanged. The application's `version` rises by 1.

Acceptance of a **renewal** application does one thing more. When the application's `is_renewal` is true and a renewal review exists whose recorded `renewed_application_id` is this application, the prior-year account named by that review moves `ACTIVE → CLOSED`; its `rollover_carried_cents` becomes the new account's `rollover_in_cents`; the prior account's `rolled_out_cents` rises by that same amount and its `balance_cents` falls by that same amount. The carried money therefore only ever reaches a successor account at this moment, never at year-end close itself.

The response reports `application_id`, the resulting `application_status`, the `account_id` just created, the verified `annual_award_cents`, the prorated `final_award_cents`, and `quarters_remaining_at_award`.

Withdrawal is the mirror image and is likewise a `Guardian` action on an application in `ACCEPTED`; a wrong state is `ERR_INVALID_STATE_TRANSITION` and a mismatched `X-User-ID` against `student_id` is `ERR_NOT_ACCOUNT_HOLDER`. The application moves `ACCEPTED → WITHDRAWN`, and the cascade runs to completion in one request. The account funded by that application moves to `CLOSED`, and — unlike suspension — closure deliberately leaves `balance_cents` and `encumbered_cents` exactly as they stood, so the ledger remains readable as an audit trail. That closure itself voids every purchase request of the account whose `approval_status` is `PENDING_REVIEW` or `APPROVED`, setting `approval_status` to `VOID` and `settlement_status` to `CANCELLED`, and no money moves as part of that voiding. The seat is then released: `seats_committed` falls by 1 and `seats_available` rises by 1, and that release itself promotes the waitlisted application with the lowest `waitlist_position` when one exists, which re-consumes the seat and so lowers `seats_available` again. The application's `version`, the account's `version`, and the programme year's `version` each rise by 1, as does the `version` of every purchase request the cascade touched. The response reports `application_id`, `application_status`, `account_id`, the resulting `account_status`, the recomputed `seats_committed` and `seats_available`, and `promoted_application_id` for the application that took the freed seat.

Funding arrives through quarterly operational runs driven by a `ProgramAdmin`, each one identified by the `quarter` it funds. The year must be `ACTIVE`, or the run is refused with `ERR_PROGRAM_YEAR_NOT_ACTIVE`, and the supplied `quarter` must be exactly one more than the year's `current_quarter`, or the run is refused with `ERR_INVALID_STATE_TRANSITION`. Quarters therefore cannot be skipped, repeated, or run out of order. A successful run leaves the year in `ACTIVE` — it is a self-loop, not a lifecycle advance — sets `current_quarter` to the supplied `quarter`, and raises the year's `version` by 1.

Each run does two passes, and the order between them is load-bearing. **The expiry pass runs first.** Every application in `AWARD_OFFERED` whose `acceptance_deadline_at` is at or before the current logical instant moves `AWARD_OFFERED → EXPIRED`; that expiry lowers `seats_committed` by 1 and raises `seats_available` by 1, and that release in turn promotes the waitlisted application holding the lowest `waitlist_position` to `AWARD_OFFERED`. Because expiries are processed before any money is credited, an application promoted by this pass has a live offer but no account yet, and so receives nothing in this run's credit pass.

**The credit pass runs second.** It considers every account whose `program_year_id` is this year, whose status is `ACTIVE`, and whose `disbursement_count` is still below its `quarters_remaining_at_award`. For each such account one disbursement row is appended and the account is credited, as follows.

- The quarters still owed is `quarters_remaining_at_award` less `disbursement_count`; this figure is stamped on the row as `quarters_left_at_issue`.
- The entitlement still unpaid is `final_award_cents` less `lifetime_disbursed_cents`.
- The even slice is the entitlement still unpaid divided by the quarters still owed, taken as the integer floor — this is the one place the programme floors rather than rounding half up.
- The indivisible remainder is the entitlement still unpaid less the even slice multiplied by the quarters still owed.
- `gross_amount_cents` is the even slice, plus the indivisible remainder if and only if this is the account's very first disbursement, meaning its `disbursement_count` was 0 when the pass reached it. The remainder is front-loaded onto the first disbursement only; it is never spread across quarters and never appended to the last one. The amount actually folded in is recorded on the row as `remainder_applied_cents`, which is 0 on every disbursement after the first.
- `admin_fee_cents` is `gross_amount_cents` multiplied by the year's `admin_fee_pct`, rounded half up to whole cents. The fee is charged per disbursement against that disbursement's own gross; it is never computed once against the annual entitlement and then split. The difference is real: against a `final_award_cents` of 932663 across four quarters, the per-disbursement method totals 16320 in fees while the annual-then-split method would total 16322.
- `net_credited_cents` is `gross_amount_cents` less `admin_fee_cents`, and that net amount is what is added to the account's `balance_cents`.
- The account's `lifetime_disbursed_cents` rises by `gross_amount_cents`, its `lifetime_admin_fee_cents` rises by `admin_fee_cents`, its `disbursement_count` rises by 1, and its `version` rises by 1. The row also records the `account_id`, the `program_year_id`, the `quarter` of the issuing run, and `issued_at` at the current logical instant.

The four gross amounts always sum to `final_award_cents` exactly. A `final_award_cents` of 932663 over four quarters therefore pays 233168, then 233165, then 233165, then 233165, with a fee of 4080 on each. When only one quarter is still owed the whole remaining entitlement is paid out, so no residue can survive the final quarter.

Accounts that are skipped are named rather than silently ignored: an account whose status is `SUSPENDED` or `CLOSED`, or whose `disbursement_count` has already reached its `quarters_remaining_at_award`, receives nothing and is listed in `skipped_account_ids`. A suspended account's missed quarter is not recovered as a catch-up payment later, because the quarters still owed shrinks only through `disbursement_count`; the money it did not receive stays inside the unpaid entitlement and is redistributed across whichever quarters are still funded.

The run reports the `quarter` it advanced to, a `disbursement_count` giving the number of disbursement rows this run issued, the aggregate `total_gross_cents`, `total_admin_fee_cents` and `total_net_credited_cents`, plus `skipped_account_ids`, `expired_application_ids` for the offers that lapsed, and `promoted_application_ids` for the waitlisted applications the expiries promoted. Disbursements are separately listable both for the whole programme year and for a single account, oldest quarter first in each case.

### 3.6. Provider Participation: Screening, Admission Banding and Sanctions

Public money may only be paid to vendors the state has vetted. A `ProgramAdmin` registers a candidate provider with its registered `legal_name`, its `ein` — nine digits, unique across all providers — the two-letter `address_state` of its principal address, and a `provider_type` drawn from `SCHOOL`, `TUTOR`, `THERAPY`, `CURRICULUM_VENDOR`, and `TRANSPORT`. A fresh registration sits in `DRAFT` with `screening_score` 0, `surveillance_score` 0, `substantiated_case_count` 0, an empty `authorized_category_codes`, an empty `screening_flags`, a null `screened_at`, and a null `sanction_reason`. A provider passes through the states `DRAFT`, `SCREENED`, `APPROVED`, `PROBATION`, `DELISTED`, and `PERMANENTLY_BARRED`, of which only `APPROVED` and `PROBATION` may receive purchases at all, and `PERMANENTLY_BARRED` is terminal.

A `VendorScreener` runs the integrity check by submitting `flags`, a duplicate-free subset of six indicators: `NO_STATE_REGISTRATION`, `ADDRESS_MISMATCH`, `PRIOR_DELISTING`, `OFAC_HIT`, `NEW_ENTITY_UNDER_12_MONTHS`, and `SHARED_BANK_ACCOUNT`. Screening is permitted while the provider is in `DRAFT` or already in `SCREENED`, and is refused with `ERR_INVALID_STATE_TRANSITION` from any other state — so a provider may be re-screened, but an approved, probationary, delisted, or barred one may not.

The screening row's `screening_score` is the sum of the weights of the distinct flags submitted, capped at 100. The weights are 60 for `OFAC_HIT`, 40 for `PRIOR_DELISTING`, 35 for `NO_STATE_REGISTRATION`, 25 for `SHARED_BANK_ACCOUNT`, 20 for `ADDRESS_MISMATCH`, and 15 for `NEW_ENTITY_UNDER_12_MONTHS`. A list summing above the ceiling clamps to exactly 100 — `OFAC_HIT` together with `PRIOR_DELISTING` and `NO_STATE_REGISTRATION` sums to 135 and is recorded as 100 — and an empty flag list scores 0 and clears cleanly. The row also carries a `recommended_status` of `APPROVE` when the score is below 40, `PROBATION` when it is at least 40 and below 60, and `REJECT` when it is 60 or more; it records `provider_id`, the screener's `X-User-ID` as `screened_by_user_id`, and `screened_at` at the current logical instant.

Recording a screening advances the provider `DRAFT → SCREENED` and copies `screening_score`, `screening_flags`, and `screened_at` onto the provider. It also sets `surveillance_score` equal to `screening_score`, which is correct at that moment because there has been no decay and no substantiated case history. Re-screening an already-`SCREENED` provider replaces `screening_score` and resets the elapsed-months term to zero, restarting the decay curve from the new screening instant. The provider's `version` rises by 1.

Admission is a single action by a `VendorScreener` that lands in one of two states depending purely on the score band, and both branches carry equal weight. The provider must be in `SCREENED`, or the attempt is `ERR_INVALID_STATE_TRANSITION`. Its `screening_score` must be below 60, or the attempt is `ERR_FRAUD_RISK_TOO_HIGH` and the provider stays in `SCREENED` — a score of exactly 60 is already too high. Every code supplied in `authorized_category_codes` must match the `code` of an existing catalogue entry, or the attempt is `ERR_EXPENSE_CATEGORY_NOT_FOUND`. Then:

- With a `screening_score` below 40 the provider moves `SCREENED → APPROVED`. The supplied `authorized_category_codes` are pinned onto the provider, fixing for good the catalogue lines it may bill, and its `version` rises by 1.
- With a `screening_score` of at least 40 and below 60 the provider moves `SCREENED → PROBATION` instead. The supplied `authorized_category_codes` are pinned in exactly the same way, `sanction_reason` is set to the literal string `ELEVATED_SCREENING_SCORE`, and its `version` rises by 1. A provider on probation may only be used with the pre-approval flow; a reimbursement purchase naming it is refused with `ERR_PROVIDER_NOT_ELIGIBLE`.

A `ComplianceOfficer` may afterwards apply or lift a sanction by supplying an `action` of `PROBATION`, `REINSTATE`, or `DELIST` together with a `reason`, which is stored on the provider as `sanction_reason`.

`PROBATION` moves the provider `APPROVED → PROBATION`; the provider must be in `APPROVED` or the attempt is `ERR_INVALID_STATE_TRANSITION`, and the `version` rises by 1. `REINSTATE` closes that cycle by moving the provider `PROBATION → APPROVED`; the provider must be in `PROBATION`, or the attempt is `ERR_INVALID_STATE_TRANSITION`, and its `surveillance_score` must be below 75, or the attempt is `ERR_FRAUD_RISK_TOO_HIGH`. On reinstatement `sanction_reason` is set back to null and the `version` rises by 1.

`DELIST` moves the provider to `DELISTED` from either `APPROVED` or `PROBATION` — from any other state it is `ERR_INVALID_STATE_TRANSITION` — and its cascade is identical whichever of the two it started from. The delisting records `sanction_reason` and then voids every purchase request naming this provider whose `approval_status` is `PENDING_REVIEW` or `APPROVED`, setting `approval_status` to `VOID` and `settlement_status` to `CANCELLED`. Each voided request that had actually reached `APPROVED` releases its hold on its own account: that account's `encumbered_cents` falls by the request's `amount_cents` and its `balance_cents` rises by the same amount. A request that was still only `PENDING_REVIEW` moves no money, because no hold had been placed. The provider's `version` rises by 1 and so does the `version` of every account the hold releases touched.

Two sanctions are not requested at all but fall out of the provider's live risk score. Whenever a misuse case naming one of this provider's purchase requests is substantiated, the provider's `substantiated_case_count` rises by 1 and its `surveillance_score` is recomputed on the spot from three ingredients. The elapsed time is the number of whole months from `screened_at` to the current logical instant, taking the floor. The decay factor is 1 less 0.1 for each of those whole months, floored at 0.5 — so a provider twelve months past its screening still retains a factor of 0.5, half of its screening term, not none of it. The decayed screening term is `screening_score` multiplied by that decay factor, rounded half up to a whole number, and it is rounded **before** anything else is added. To that term is added 25 points for each substantiated case, and the total is capped at 100. A provider screened at 25 with no elapsed months and two substantiated cases therefore stands at exactly 75, while one screened at 40 that has aged four months with a single case stands at 49.

The recomputed `surveillance_score` then drives an automatic sanction with no operator involved. A score of 90 or more cascades the provider to `DELISTED`, with the full void-and-release cascade described above. A score of at least 75 but below 90 cascades an `APPROVED` provider to `PROBATION`. A score of 74 leaves the provider `APPROVED` untouched. The boundaries are inclusive on the lower side in both bands.

Delisting is not necessarily the end. A provider that appeals successfully moves `DELISTED → PROBATION`, with `sanction_reason` set to the literal string `DELISTING_OVERTURNED_ON_APPEAL`; the purchase requests its delisting voided are **not** revived and must be filed afresh. A provider whose appeal is refused moves `DELISTED → PERMANENTLY_BARRED`, after which every further sanction or admission attempt returns `ERR_INVALID_STATE_TRANSITION`.

### 3.7. The Purchase Lifecycle: Pre-Approval, Claim and Settlement

A purchase request is unusual in that it carries **two independent state dimensions** that advance separately. The approval track lives in `approval_status`, which is one of `PENDING_REVIEW`, `APPROVED`, `DENIED`, or `VOID`. The money track lives in `settlement_status`, which is one of `UNSETTLED`, `CLAIMED`, `PAID`, `REVERSED`, or `CANCELLED`. A new request begins at `PENDING_REVIEW` on the approval track and `UNSETTLED` on the money track. `DENIED` and `VOID` are terminal on the approval track; `CANCELLED` and `REVERSED` are terminal on the money track.

A `Guardian` files a request against their own account. The payload names the `provider_id` of the vendor to be paid, the `expense_category_id` of the catalogue line the spend is charged to, a `flow` of either `PREAPPROVAL` — asking for a decision before the service is rendered — or `REIMBURSEMENT`, which attaches an invoice for a service already delivered, an `amount_cents` of at least 1 cent that is also the maximum billable amount, and the service interval bounded by `service_start_at` and `service_end_at`, the second strictly after the first. It also carries `expected_account_version` as described in §2.7. An `invoice_reference` — the vendor's own invoice identifier — is required when the flow is `REIMBURSEMENT` and may be omitted at creation when the flow is `PREAPPROVAL`, in which case it is null until a claim supplies it.

Filing runs a dense battery of checks, in the ladder order of §2.8. The account must belong to the acting guardian's student, and it must be `ACTIVE` rather than `SUSPENDED` — otherwise `ERR_ACCOUNT_SUSPENDED`. The named provider must be participation-eligible for the requested `flow`: `APPROVED` when the flow is `REIMBURSEMENT`, and either `APPROVED` or `PROBATION` when the flow is `PREAPPROVAL`; a provider in `DRAFT`, `SCREENED`, `DELISTED`, or `PERMANENTLY_BARRED`, or one on probation with a reimbursement flow, is refused with `ERR_PROVIDER_NOT_ELIGIBLE`. The catalogue entry's `code` must appear in the provider's pinned `authorized_category_codes`, or the filing is refused with `ERR_CATEGORY_NOT_AUTHORIZED`. The catalogue entry's `allowable` must be true, or the filing is refused with `ERR_EXPENSE_NOT_ALLOWABLE`. A `REIMBURSEMENT` flow is only accepted when the entry's `requires_preapproval` is false; otherwise the filing is refused with `ERR_PREAPPROVAL_REQUIRED`.

Two temporal rules then apply to the service interval. When the catalogue entry's `requires_service_period` is true, no other purchase request for the same `account_id` and the same `expense_category_id` whose `approval_status` is `PENDING_REVIEW` or `APPROVED` may cover an intersecting interval; intervals are treated as half-open, including their start instant and excluding their end instant, so two requests that merely touch end-to-start do not collide. A collision is refused with `ERR_DUPLICATE_SERVICE_PERIOD`. Categories that leave `requires_service_period` false are wholly exempt and may reuse an identical interval as often as needed. Separately, the interval must lie inside the programme year's instructional term: `service_start_at` must be at or after midnight UTC on `term_start_date`, `service_end_at` must be at or before 23:59:59 UTC on `term_end_date`, and `service_end_at` must be strictly after `service_start_at`. A violation is refused with `ERR_SERVICE_PERIOD_OUTSIDE_TERM`.

The last gate at filing is the category ceiling. The account's already-committed spend in that category is the sum of `amount_cents` across the account's purchase requests for the same category whose `approval_status` is `APPROVED`. The new `amount_cents` must not exceed the catalogue entry's `per_year_cap_cents` less that committed sum, or the filing is refused with `ERR_CATEGORY_CAP_EXCEEDED`. The same ceiling is re-checked when the approval track is later decided in the affirmative, since other requests may have been approved in between.

A successful filing lands at `PENDING_REVIEW` and `UNSETTLED`, and — because it consumes the account's version guard — the account's own `version` rises by 1 even though no money has moved.

An `ExpenseReviewer` then decides the approval track by supplying a `decision` of `APPROVED`, `DENIED`, or `VOID`, optionally with a `reason` that is stored on the request as `decision_reason`. The three branches are specified in full and independently.

`APPROVED` advances the approval dimension `PENDING_REVIEW → APPROVED`. The request must currently be `PENDING_REVIEW`; the account must be `ACTIVE`, else `ERR_ACCOUNT_SUSPENDED`; the provider must be participation-eligible for the request's `flow` under the same rule as at filing, else `ERR_PROVIDER_NOT_ELIGIBLE`; the category `code` must still be in the provider's `authorized_category_codes`, else `ERR_CATEGORY_NOT_AUTHORIZED`; the category ceiling must still admit the amount, else `ERR_CATEGORY_CAP_EXCEEDED`; and `amount_cents` must not exceed the account's `balance_cents`, else `ERR_INSUFFICIENT_BALANCE`. On success the reviewer's `X-User-ID` is stored as `approved_by_user_id`, and the hold is placed: `balance_cents` falls by `amount_cents` and `encumbered_cents` rises by the same `amount_cents`. Both the request's `version` and the account's `version` rise by 1. One shortcut applies here: when the request's `flow` is `REIMBURSEMENT` and its `settlement_status` is already `CLAIMED`, this same approval immediately advances the money track `CLAIMED → PAID` inside the very same request, applying every settlement effect described below.

`DENIED` advances the approval dimension `PENDING_REVIEW → DENIED`, and requires the request to be `PENDING_REVIEW`. It closes the money track alongside it, setting `settlement_status` to `CANCELLED`. No funds move at all — `balance_cents` and `encumbered_cents` are both unchanged — and the request's `version` rises by 1.

`VOID` advances the approval dimension `APPROVED → VOID`. The request must be in `APPROVED` and its `settlement_status` must be either `UNSETTLED` or `CLAIMED`; a request already `PAID` cannot be voided, and either violation is `ERR_INVALID_STATE_TRANSITION`. The money track is set to `CANCELLED` and the hold is released as an exact compensation of the approval: `encumbered_cents` falls by `amount_cents` and `balance_cents` rises by the same `amount_cents`. Both the request's `version` and the account's `version` rise by 1. The same `PENDING_REVIEW → VOID` and `APPROVED → VOID` moves also arrive as system cascades from an account suspension, an account closure, or a provider delisting; when the cascade catches a request that was still `PENDING_REVIEW`, `settlement_status` becomes `CANCELLED` and no funds move because no hold had been placed.

The money track is driven from the other side. A `Provider` claims against a request by supplying an `invoice_reference` and a `claimed_amount_cents`, which advances `UNSETTLED → CLAIMED`. The request's `settlement_status` must be `UNSETTLED`; its `approval_status` must be `PENDING_REVIEW` or `APPROVED`, and the approval dimension expressly does **not** need to have advanced yet — a provider may invoice while review is still pending, which is the whole point of two independent dimensions. The acting `X-User-ID` must equal the request's `provider_id`, else `ERR_NOT_ASSIGNED_PROVIDER`. And `claimed_amount_cents` must be at least 1 and no greater than the request's `amount_cents`, else `ERR_CLAIM_AMOUNT_MISMATCH`. On success both `claimed_amount_cents` and `invoice_reference` are recorded and the request's `version` rises by 1.

Settlement is performed by an `ExpenseReviewer` and advances the money track `CLAIMED → PAID`. Six conditions apply: `settlement_status` must be `CLAIMED`; `approval_status` must be `APPROVED`, which is the cross-dimension guard that stops money leaving on an unapproved request and reports `ERR_INVALID_STATE_TRANSITION` when it is not met; the account must be `ACTIVE`, else `ERR_ACCOUNT_SUSPENDED`; the acting `X-User-ID` must differ from `approved_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`; the provider must be in `APPROVED` or `PROBATION`, else `ERR_PROVIDER_NOT_ELIGIBLE`; and the category `code` must still appear in the provider's `authorized_category_codes`, re-validated at this moment, else `ERR_CATEGORY_NOT_AUTHORIZED`.

Settlement converts the hold into spend and returns the difference. `paid_amount_cents` is set to `claimed_amount_cents`, and the reviewer's `X-User-ID` is stored as `settled_by_user_id`. The account's `encumbered_cents` falls by the full `amount_cents` that was held, its `lifetime_spent_cents` rises by `claimed_amount_cents`, and its `balance_cents` rises by `amount_cents` less `claimed_amount_cents` — the unspent portion of the hold, which the response reports as `released_cents`. Both the request's `version` and the account's `version` rise by 1.

Settlement is also where the first misuse-detection rule fires. If some other purchase request exists with the same `account_id`, the same `provider_id`, the same `invoice_reference`, and a `settlement_status` of `PAID`, then this settlement sets the request's `flagged_rule` to `DUPLICATE_INVOICE` and automatically opens a misuse case in `OPEN` with `auto_opened` true, a `detection_rule` of `DUPLICATE_INVOICE`, and `disallowed_principal_cents` equal to this settlement's `paid_amount_cents`. When nothing fires, `flagged_rule` stays null. The settlement response reports `purchase_request_id`, the resulting `settlement_status`, `paid_amount_cents`, `released_cents`, the account's resulting `account_balance_cents` and `account_encumbered_cents`, and `opened_misuse_case_id` for a case the detection opened.

One further money-track move is never requested directly. A settled request that a clawback later disowns moves `PAID → REVERSED`, as described in §3.8. Purchase requests are listable filtered by `account_id`, `provider_id`, `expense_category_id`, `approval_status`, or `settlement_status`, which is the reverse lookup for all three of the request's own references.

### 3.8. Misuse Cases, Account Suspension and Clawback

A `ComplianceOfficer` opens a misuse case against an account by naming the `account_id` under investigation, the `detection_rule` the case rests on, the `disallowed_principal_cents` alleged to have been misused — at least 1 cent, and the sole input to the penalty tier — and an investigator `narrative`. The optional `purchase_request_id` names the implicated purchase and is left null for account-level cases. The `detection_rule` is one of `DUPLICATE_INVOICE`, `NON_ALLOWABLE_EXPENSE`, `PROVIDER_COLLUSION`, `FALSIFIED_ENROLLMENT`, or `CAP_CIRCUMVENTION`. A case opened this way begins in `OPEN` with `auto_opened` false and `opened_by_user_id` set to the officer's `X-User-ID`; a case opened by settlement-time duplicate-invoice detection instead begins with `auto_opened` true and `opened_by_user_id` set to the literal string `system`. A case moves through `OPEN`, `UNDER_REVIEW`, `SUBSTANTIATED`, `DISMISSED`, `CLAWBACK_ISSUED`, `UNDER_APPEAL`, `RESOLVED`, and `REVERSED`, of which `DISMISSED`, `RESOLVED`, and `REVERSED` are terminal.

Taking a case under review advances it `OPEN → UNDER_REVIEW` and records the officer's `X-User-ID` as `reviewed_by_user_id`; from any state other than `OPEN` the attempt is `ERR_INVALID_STATE_TRANSITION`, and the case's `version` rises by 1.

Adjudication supplies an `outcome` of either `SUBSTANTIATED` or `DISMISSED` together with a `rationale`, and the two branches share a from-state but have entirely disjoint consequences.

`DISMISSED` advances the case `UNDER_REVIEW → DISMISSED`. The case must be in `UNDER_REVIEW`, or the attempt is `ERR_INVALID_STATE_TRANSITION`. The officer's `X-User-ID` is recorded as `adjudicated_by_user_id`, and nothing else in the system changes at all: no account state, no purchase request, no provider score. The case's `version` rises by 1.

`SUBSTANTIATED` advances the case `UNDER_REVIEW → SUBSTANTIATED` and sets off the longest cascade in the programme. The case must be in `UNDER_REVIEW`, or the attempt is `ERR_INVALID_STATE_TRANSITION`. When the case names a `purchase_request_id`, the acting `X-User-ID` must differ from that request's `approved_by_user_id`, or the attempt is `ERR_SEGREGATION_OF_DUTIES` — the reviewer who approved the spend may not be the officer who condemns it. On success the officer's `X-User-ID` is recorded as `adjudicated_by_user_id` and four linked effects follow in order. First, the substantiation itself moves the account `ACTIVE → SUSPENDED` with `suspension_reason` set to the literal string `MISUSE_SUBSTANTIATED`. Second, that suspension itself voids every purchase request of the account whose `approval_status` is `PENDING_REVIEW` or `APPROVED`, setting `approval_status` to `VOID` and `settlement_status` to `CANCELLED`. Third, each voided request that had actually reached `APPROVED` releases its hold, so the account's `encumbered_cents` falls by that request's `amount_cents` and its `balance_cents` rises by the same amount. Fourth, when the case names a `purchase_request_id`, the provider behind that request has its `substantiated_case_count` raised by 1 and its `surveillance_score` recomputed by the decay-plus-case-points rule of §3.6, with a resulting score of 90 or more cascading the provider to `DELISTED` and a score of at least 75 but below 90 cascading an `APPROVED` provider to `PROBATION`. The case's `version`, the account's `version`, and the `version` of every purchase request the cascade touched each rise by 1.

Independently of any case, a `ComplianceOfficer` may act on an account's participation directly by supplying an `action` of `SUSPEND` or `REINSTATE` together with a `reason`. `SUSPEND` moves the account `ACTIVE → SUSPENDED` — from any other state it is `ERR_INVALID_STATE_TRANSITION` — stores the `reason` as `suspension_reason`, and runs exactly the same void-and-release cascade the substantiation cascade runs: open purchase requests whose `approval_status` is `PENDING_REVIEW` or `APPROVED` become `VOID` with `settlement_status` `CANCELLED`, and each one that had been `APPROVED` returns its `amount_cents` from `encumbered_cents` to `balance_cents`. While suspended, the account is excluded from every subsequent disbursement run and appears in that run's `skipped_account_ids`. Its `version` rises by 1.

`REINSTATE` moves the account `SUSPENDED → ACTIVE`, and it is guarded across aggregates rather than by the account's own state alone. The account must be `SUSPENDED`, **and** every misuse case naming this `account_id` must already be in `DISMISSED`, `RESOLVED`, or `REVERSED`; a single case still sitting in `OPEN`, `UNDER_REVIEW`, `SUBSTANTIATED`, `CLAWBACK_ISSUED`, or `UNDER_APPEAL` blocks reinstatement with `ERR_INVALID_STATE_TRANSITION`. On success `suspension_reason` is set back to null and the `version` rises by 1. Reinstatement does **not** revive the purchase requests the suspension voided; the guardian must file new ones.

Issuing the clawback advances the case `SUBSTANTIATED → CLAWBACK_ISSUED`. The case must be in `SUBSTANTIATED`, and the account must be `SUSPENDED` — which the substantiation cascade guarantees — with either violation reported as `ERR_INVALID_STATE_TRANSITION`. The assessment then runs in five pinned steps, and the order matters because the tier looks circular but is not: the tier is selected from the **principal alone**, never from the running total.

1. `penalty_rate` is the first matching band for `disallowed_principal_cents`: 0.10 when the principal is 50000 cents or less, 0.20 when it is 250000 cents or less, and 0.35 for anything above that. Both band boundaries are inclusive on their upper edge.
2. `penalty_cents` is `disallowed_principal_cents` multiplied by `penalty_rate`, rounded half up to whole cents.
3. `clawback_total_cents` is `disallowed_principal_cents` plus `penalty_cents`.
4. `account_debit_cents` is the smaller of the account's `balance_cents` and `clawback_total_cents`.
5. `receivable_cents` is `clawback_total_cents` less `account_debit_cents`, so the debit and the receivable always sum back to the total exactly.

Re-deriving the tier from `clawback_total_cents` instead of the principal would be wrong: a principal of exactly 250000 sits in the 0.20 band and produces a total of 300000, whereas re-deriving from the total would push it into the 0.35 band and produce 337500. The boundaries are exact. A principal of 50000 takes 0.10, giving a penalty of 5000 and a total of 55000; a principal of 50001 takes 0.20, giving a penalty of 10000 and a total of 60001. A principal of 250001 takes 0.35, giving a penalty of 87500 and a total of 337501. A principal of 150000 gives a penalty of 30000 and a total of 180000.

The ledger consequences follow. A clawback entry is appended with `entry_type` `ACCOUNT_DEBIT` and `amount_cents` equal to `account_debit_cents`, and when `receivable_cents` is greater than zero a second entry is appended with `entry_type` `RECEIVABLE` and that shortfall as its `amount_cents`. Each entry records the `misuse_case_id` that produced it, the `account_id` it moves or records against, and `created_by_user_id` — the acting officer's `X-User-ID`, or the literal string `system` for a cascaded reversal. The account's `balance_cents` falls by `account_debit_cents` and its `lifetime_clawed_back_cents` rises by the same amount; that lifetime counter is by construction the sum of `ACCOUNT_DEBIT` entries less the sum of `REVERSAL` entries. A balance below the total splits the recovery — a `balance_cents` of 100000 against a total of 180000 debits 100000, books 80000 as receivable and leaves the balance at exactly 0, never negative — and a balance of 0 debits nothing and books the whole total as receivable. Finally, when the case names a `purchase_request_id` whose `settlement_status` is `PAID`, that request moves `PAID → REVERSED` and the account's `lifetime_spent_cents` falls by that request's `paid_amount_cents`, because the spend is disowned rather than double-counted; the recovery is tracked as `lifetime_clawed_back_cents` instead. The case's `version` and the account's `version` each rise by 1.

The clawback response reports `misuse_case_id`, the resulting `misuse_case_status`, the derived `penalty_rate`, `penalty_cents`, `clawback_total_cents`, `account_debit_cents` and `receivable_cents`, the account's resulting `account_balance_cents`, and `clawback_entry_ids` naming the ledger rows just appended. Misuse cases are listable filtered by `account_id`, `purchase_request_id`, or `status`, and the clawback ledger is readable both per case and per account, oldest entry first, so that reversals appear after the debits they compensate.

### 3.9. Continued Eligibility, Appeals and Closing the Year

Participation is annual, and a family that wants a second year must show what the first year achieved. A `Guardian` files a renewal review naming the `account_id` of the current-year account seeking continued eligibility and the `next_program_year_id` of the year the renewal would fund, and declaring which evidence route the family elected in `assessment_type`: either `NORM_REFERENCED_TEST` or `PORTFOLIO`. When the route is `NORM_REFERENCED_TEST` the filing supplies `assessment_score`, a percentile between 0 and 100 inclusive; when the route is `PORTFOLIO` it supplies `portfolio_artifact_count` instead, a count of at least 0, which is otherwise omitted and defaults to null. The filing also re-attests residency for the coming year in `residency_state_attested`, exactly two uppercase letters, and carries `expected_application_version` as described in §2.7.

A review is created in `SUBMITTED`, and filing it raises the `version` of the account's application by 1. Filing a second review for the same `account_id` is legitimate: the newly created review becomes the live one and any prior review for that account still sitting in `SUBMITTED` is moved `SUBMITTED → SUPERSEDED`, its own `version` rising by 1. The review states are `SUBMITTED`, `APPROVED`, `DENIED`, and `SUPERSEDED`, and the last three are all terminal.

An `EligibilityOfficer` then decides the review with a `decision` of `APPROVED` or `DENIED`, optionally attaching a `decision_note`, and records their `X-User-ID` as `decided_by_user_id`.

A `DENIED` decision moves the review `SUBMITTED → DENIED`. The review must be in `SUBMITTED`, or the attempt is `ERR_INVALID_STATE_TRANSITION`. The `decision_note` is stored, no application is minted, no seat is consumed anywhere, and the review's `version` rises by 1.

An `APPROVED` decision moves the review `SUBMITTED → APPROVED` and must clear five conditions. The review must be in `SUBMITTED`. The evidence must clear the bar set by the **target** year: with `assessment_type` `NORM_REFERENCED_TEST` the `assessment_score` must be at least the target year's `min_assessment_percentile`, and with `PORTFOLIO` the `portfolio_artifact_count` must be at least the target year's `min_portfolio_artifacts`; a shortfall, or the absence of the evidence field the declared route requires, is refused with `ERR_ASSESSMENT_EVIDENCE_INSUFFICIENT`. Both thresholds are inclusive, so a score exactly equal to the minimum passes. The target year must be either `WINDOW_OPEN` or `ACTIVE`, or the decision is refused with `ERR_PROGRAM_YEAR_NOT_ACTIVE`. The `residency_state_attested` must equal the target year's `residency_state`, or it is refused with `ERR_RESIDENCY_NOT_ELIGIBLE`. And the target year must have at least one seat in `seats_available`, or it is refused with `ERR_NO_SEATS_AVAILABLE`.

Approval mints a successor application directly into an offer, skipping the whole competitive pipeline. The new application belongs to `next_program_year_id`, has `is_renewal` true, is created already in `AWARD_OFFERED` with `priority_tier` 1, and takes both its claimed and its verified attributes from the student record — `claimed_income_band` and `verified_income_band` are both set to the student's `income_band`, and `claimed_category_flags` and `verified_category_flags` are both set to the student's `category_flags`. Its `annual_award_cents` is the verified variant of the award computation of §3.2 evaluated against those attributes and the target year's `base_award_cents`, with no proration at this stage; proration into `final_award_cents` happens when the offer is accepted. Its `acceptance_deadline_at` is the current logical instant plus the target year's `acceptance_deadline_days` days. Because the new application already occupies an offer, the target year's `seats_committed` rises by 1 and its `seats_available` falls by 1. The review records the new application's identifier as `renewed_application_id`, which is null on any review that is not `APPROVED`. The review's `version`, the new application's `version`, and the target year's `version` each rise by 1.

The decision response reports `renewal_review_id`, the resulting `status`, `renewed_application_id`, the `prior_account_status` of the account whose renewal was reviewed, and `next_program_year_seats_available` for the target year's recomputed seat count. Reviews are listable filtered by `account_id`, `next_program_year_id`, or `status`, which is the reverse lookup for both of the review's references.

Three kinds of adverse outcome can be contested, and all three go through one appeal record whose `subject_type` selects exactly which one of three references must be populated. `APPLICATION_DENIAL` requires `application_id` and leaves both `misuse_case_id` and `provider_id` null. `CLAWBACK` requires `misuse_case_id` and leaves `application_id` and `provider_id` null. `PROVIDER_DELISTING` requires `provider_id` and leaves `application_id` and `misuse_case_id` null. Every appeal carries the appellant's stated `grounds`, is created in `FILED`, records the appellant's `X-User-ID` as `filed_by_user_id`, and carries a 1-based `round_number` giving its ordinal among the appeals against the same subject. A `Guardian` may file the first two kinds; a `Provider` files the third about itself.

Filing against an application denial moves the application `DENIED → UNDER_APPEAL`. The application must be in `DENIED`, or the filing is refused with `ERR_INVALID_STATE_TRANSITION`, and its `appeal_round_count` must be strictly below the programme-wide appeal round cap, which is fixed at 2, or the filing is refused with `ERR_APPEAL_ROUNDS_EXHAUSTED`. On success `appeal_round_count` rises by 1, the appeal's `round_number` is set to that new count, and the application's `version` rises by 1. Filing against a clawback moves the misuse case `CLAWBACK_ISSUED → UNDER_APPEAL`; the case must be in `CLAWBACK_ISSUED`, or the filing is refused with `ERR_INVALID_STATE_TRANSITION`, the appeal's `round_number` is one more than the number of prior appeals against that case, and the case's `version` rises by 1. Filing against a delisting requires the provider to be in `DELISTED`.

An `AppealsOfficer` decides with a `decision` of `OVERTURNED` or `UPHELD` plus a `rationale`, both recorded on the appeal along with `decided_by_user_id`. The appeal must be in `FILED`, or the decision is refused with `ERR_INVALID_STATE_TRANSITION`. Segregation of duties is subject-specific: on an `APPLICATION_DENIAL` appeal the acting `X-User-ID` must differ from the `decided_by_user_id` of the latest eligibility determination on that application, and on a `CLAWBACK` appeal it must differ from the case's `adjudicated_by_user_id`; a match is refused with `ERR_SEGREGATION_OF_DUTIES`.

`OVERTURNED` moves the appeal `FILED → OVERTURNED` and cascades by `subject_type`, and each of the three cascades is specified in full.

- `APPLICATION_DENIAL` moves the application `UNDER_APPEAL → SUBMITTED`, putting it back into the pipeline so that a fresh determination can be recorded with an incremented `round_number`. Its `verified_income_band`, `verified_category_flags`, `annual_award_cents`, `priority_tier`, and `priority_score` are all reset to their defaults — the band back to null, the flags back to the empty list, and the three numbers back to 0 — because the earlier verification no longer stands. This is the programme's one genuine cycle: an application can travel `DENIED → UNDER_APPEAL → SUBMITTED → DENIED` twice before the round cap bites.
- `CLAWBACK` moves the misuse case `UNDER_APPEAL → REVERSED`. A clawback entry with `entry_type` `REVERSAL` is appended whose `amount_cents` equals the case's `account_debit_cents`; the account's `balance_cents` rises by that same `account_debit_cents` and its `lifetime_clawed_back_cents` falls by the same amount, an exact compensation rather than a recomputation — the penalty is never re-derived at reversal time. The case's `receivable_cents` is set to 0. That reversal then moves the account `SUSPENDED → ACTIVE`, but only when no other misuse case on the account is still in `OPEN`, `UNDER_REVIEW`, `SUBSTANTIATED`, `CLAWBACK_ISSUED`, or `UNDER_APPEAL`.
- `PROVIDER_DELISTING` moves the provider `DELISTED → PROBATION` with `sanction_reason` set to `DELISTING_OVERTURNED_ON_APPEAL`, and does not revive the purchase requests the delisting voided.

The appeal's `version` and the subject record's `version` each rise by 1.

`UPHELD` moves the appeal `FILED → UPHELD` and cascades by `subject_type` with equal reach.

- `APPLICATION_DENIAL` moves the application `UNDER_APPEAL → DENIED_FINAL`, which is terminal: no further transition is possible and any later appeal naming that application is refused with `ERR_INVALID_STATE_TRANSITION`.
- `CLAWBACK` moves the misuse case `UNDER_APPEAL → RESOLVED`. No ledger movement of any kind occurs, the clawback stands in full, and the account remains `SUSPENDED`.
- `PROVIDER_DELISTING` moves the provider `DELISTED → PERMANENTLY_BARRED`, after which every further sanction or admission attempt is refused with `ERR_INVALID_STATE_TRANSITION`.

Here too the appeal's `version` and the subject record's `version` each rise by 1. Appeals are listable filtered by `application_id`, `misuse_case_id`, `provider_id`, `subject_type`, or `status`, which is the reverse lookup for all three polymorphic references.

The year finally ends when a `ProgramAdmin` closes it, moving the programme year `ACTIVE → CLOSED`. The year must be `ACTIVE`, or the close is refused with `ERR_PROGRAM_YEAR_NOT_ACTIVE`. Three things then happen across the year's records.

Every account of the closing year whose status is `ACTIVE` has its unused balance tested against a cap. The cap is the account's `final_award_cents` multiplied by the year's `rollover_cap_pct`, rounded half up to whole cents. When `balance_cents` is **strictly greater** than that cap, `rollover_carried_cents` is set to the cap and `forfeited_cents` is set to `balance_cents` less the cap; otherwise `rollover_carried_cents` is set to the whole `balance_cents` and `forfeited_cents` is set to 0. In either case `balance_cents` is then set to `rollover_carried_cents`. The strictness of that comparison is load-bearing: against a `final_award_cents` of 932663 the cap is exactly 233166, because a quarter of that award is 233165.75 and rounds half up, so a balance of exactly 233166 forfeits nothing while a balance of 233167 forfeits exactly 1 cent — the smallest non-zero forfeiture the programme can produce. A balance of 0 yields 0 carried and 0 forfeited with no error. A `rollover_cap_pct` of 0 forfeits the entire balance, and a `rollover_cap_pct` of 1 forfeits nothing whatever the balance. `encumbered_cents` takes no part in this: it is not included in the balance and it is never rolled or forfeited. The carried amount stays parked on the account and reaches a successor only if and when a renewal application is accepted.

Each such account's application moves `ACCEPTED → COMPLETED`, provided the year was `ACTIVE` at the start of the close. Every misuse case whose account belongs to the closing year and whose status is `CLAWBACK_ISSUED` moves `CLAWBACK_ISSUED → RESOLVED`, sweeping up clawbacks that were never appealed. The programme year's `version` rises by 1, and so does the `version` of every account and every other record the close touched.

The close reports `program_year_status`, a `closed_account_count` giving the number of active accounts it processed, the aggregate `total_rolled_cents` and `total_forfeited_cents`, and `resolved_misuse_case_ids` naming the cases it swept to `RESOLVED`.

## 4. Endpoint Definitions

Every path below is absolute and already includes the `/esa` mount. Requests that bring a brand-new resource into existence respond with HTTP 201 Created and return the created record; every other successful call responds with HTTP 200 OK, returning either the updated record or the operation summary described in the relevant §3 narrative. The table gives only the method, the path, a one-line purpose and the roles admitted; request payloads, response shapes and side effects are specified in §2 and §3 and are deliberately not repeated here.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/esa/program-years` | Create a program year in DRAFT with its award parameters, submission window and instructional term. | ProgramAdmin |
| GET | `/esa/program-years/{id}` | Read one program year including live seat counters and the ops-run epoch. | ProgramAdmin, EligibilityOfficer, ComplianceOfficer, AppealsOfficer, ExpenseReviewer, VendorScreener, Guardian, Provider |
| POST | `/esa/program-years/{id}/open-window` | Move the program year DRAFT to WINDOW_OPEN and publish its seat pool. | ProgramAdmin |
| POST | `/esa/program-years/{id}/awarding-runs` | Run award prioritization: rank every ELIGIBLE application, offer up to seats_available of them and waitlist the rest in rank order. | ProgramAdmin |
| POST | `/esa/program-years/{id}/disbursement-runs` | Advance the ops epoch to the given quarter: expire overdue offers, promote the waitlist, then credit one quarterly slice to every eligible ACTIVE account. | ProgramAdmin |
| POST | `/esa/program-years/{id}/year-end-close` | Close the year: apply rollover and forfeiture to every ACTIVE account, complete their applications and resolve outstanding clawbacks. | ProgramAdmin |
| GET | `/esa/program-years/{id}/disbursements` | List every disbursement issued under this program year, oldest first. | ProgramAdmin, ComplianceOfficer |
| POST | `/esa/students` | Register a student record with household, residency and prior-enrollment facts. | ProgramAdmin |
| GET | `/esa/students/{id}` | Read one student record. | ProgramAdmin, EligibilityOfficer, ComplianceOfficer, AppealsOfficer, Guardian |
| POST | `/esa/applications` | Open a DRAFT application for a student in a program year with the guardian's claimed income band and category flags. | Guardian |
| GET | `/esa/applications/{id}` | Read one application with its verified attributes, priority tier and score, award figures and waitlist position. | ProgramAdmin, EligibilityOfficer, ComplianceOfficer, AppealsOfficer, Guardian |
| GET | `/esa/applications` | List applications filtered by program year, student or status. | ProgramAdmin, EligibilityOfficer, ComplianceOfficer, AppealsOfficer, Guardian |
| POST | `/esa/applications/{id}/submit` | Submit a DRAFT application inside the open window and stamp the provisional award from the claimed attributes. | Guardian |
| POST | `/esa/applications/{id}/eligibility-determinations` | Record an eligibility determination, driving the application to ELIGIBLE or DENIED and stamping tier, score and verified award. | EligibilityOfficer |
| GET | `/esa/applications/{id}/eligibility-determinations` | List the determination history of one application, oldest round first. | ProgramAdmin, EligibilityOfficer, ComplianceOfficer, AppealsOfficer, Guardian |
| POST | `/esa/applications/{id}/accept-award` | Accept an award offer before its deadline: prorate the verified award for the quarters that remain and open the ESA account. | Guardian |
| POST | `/esa/applications/{id}/withdraw` | Withdraw an accepted award: close the account, void its open purchase requests, release the seat and promote the head of the waitlist. | Guardian |
| POST | `/esa/providers` | Register a candidate education provider or vendor in DRAFT. | ProgramAdmin |
| GET | `/esa/providers/{id}` | Read one provider with its screening and surveillance scores, sanction reason and authorized categories. | ProgramAdmin, VendorScreener, ComplianceOfficer, AppealsOfficer, ExpenseReviewer, Guardian, Provider |
| POST | `/esa/providers/{id}/fraud-screenings` | Screen a provider against the fraud flag catalog and record the resulting score. | VendorScreener |
| GET | `/esa/providers/{id}/fraud-screenings` | List the screening history of one provider, oldest first. | ProgramAdmin, VendorScreener, ComplianceOfficer, AppealsOfficer |
| POST | `/esa/providers/{id}/approve` | Admit a screened provider to participation, landing in APPROVED or PROBATION by score band, and pin the expense categories it may serve. | VendorScreener |
| POST | `/esa/providers/{id}/sanctions` | Apply or lift a participation sanction: PROBATION, REINSTATE or DELIST. | ComplianceOfficer |
| POST | `/esa/expense-categories` | Publish an allowable-expense catalog entry with its annual cap and flow requirements. | ProgramAdmin |
| GET | `/esa/expense-categories/{id}` | Read one catalog entry. | ProgramAdmin, ExpenseReviewer, ComplianceOfficer, VendorScreener, Guardian, Provider |
| GET | `/esa/accounts/{id}` | Read one ESA account with its full ledger: balance, encumbrance, lifetime totals, rollover and forfeiture. | ProgramAdmin, ComplianceOfficer, ExpenseReviewer, EligibilityOfficer, AppealsOfficer, Guardian |
| GET | `/esa/accounts` | List accounts filtered by application, program year or status. | ProgramAdmin, ComplianceOfficer, ExpenseReviewer, EligibilityOfficer, Guardian |
| GET | `/esa/accounts/{id}/disbursements` | List the quarterly disbursements credited to one account, oldest quarter first. | ProgramAdmin, ComplianceOfficer, Guardian |
| GET | `/esa/accounts/{id}/clawback-entries` | List every clawback ledger entry booked against one account, including reversals. | ProgramAdmin, ComplianceOfficer, AppealsOfficer, Guardian |
| POST | `/esa/accounts/{id}/status-actions` | Suspend or reinstate an account. | ComplianceOfficer |
| POST | `/esa/accounts/{id}/purchase-requests` | File a pre-approval or reimbursement purchase request against an account, guarded by an optimistic-concurrency check on the account version. | Guardian |
| GET | `/esa/purchase-requests/{id}` | Read one purchase request with both of its state dimensions, claim data and settlement figures. | ProgramAdmin, ExpenseReviewer, ComplianceOfficer, AppealsOfficer, Guardian, Provider |
| GET | `/esa/purchase-requests` | List purchase requests filtered by account, provider, category or either state dimension. | ProgramAdmin, ExpenseReviewer, ComplianceOfficer, AppealsOfficer, Guardian, Provider |
| POST | `/esa/purchase-requests/{id}/decision` | Decide the approval dimension: APPROVED places a hold on the account, DENIED and VOID close the request and release any hold. | ExpenseReviewer |
| POST | `/esa/purchase-requests/{id}/claim` | Provider submits an invoice claim against a purchase request; permitted while the approval dimension is still pending. | Provider |
| POST | `/esa/purchase-requests/{id}/settle` | Settle an approved claim: convert the hold to spend, return the unspent remainder and run duplicate-invoice misuse detection. | ExpenseReviewer |
| POST | `/esa/misuse-cases` | Open a misuse case against an account, optionally naming the purchase request that triggered it and the disallowed principal. | ComplianceOfficer |
| GET | `/esa/misuse-cases/{id}` | Read one misuse case with its adjudication trail and clawback figures. | ProgramAdmin, ComplianceOfficer, AppealsOfficer, ExpenseReviewer, Guardian |
| GET | `/esa/misuse-cases` | List misuse cases filtered by account, purchase request or status. | ProgramAdmin, ComplianceOfficer, AppealsOfficer, ExpenseReviewer, Guardian |
| POST | `/esa/misuse-cases/{id}/review` | Take a misuse case under review and record the reviewing officer. | ComplianceOfficer |
| POST | `/esa/misuse-cases/{id}/adjudication` | Substantiate or dismiss a misuse case. | ComplianceOfficer |
| POST | `/esa/misuse-cases/{id}/clawbacks` | Issue the clawback for a substantiated case: tiered penalty, account debit up to the available balance and a receivable for the shortfall. | ComplianceOfficer |
| GET | `/esa/misuse-cases/{id}/clawback-entries` | List the clawback ledger entries booked for one misuse case, oldest first. | ProgramAdmin, ComplianceOfficer, AppealsOfficer, Guardian |
| POST | `/esa/renewal-reviews` | File the annual testing-or-portfolio evidence for continued eligibility, guarded by an optimistic-concurrency check on the account's application version. | Guardian |
| GET | `/esa/renewal-reviews/{id}` | Read one renewal review with its evidence, decision and minted application id. | ProgramAdmin, EligibilityOfficer, ComplianceOfficer, AppealsOfficer, Guardian |
| GET | `/esa/renewal-reviews` | List renewal reviews filtered by account, target program year or status. | ProgramAdmin, EligibilityOfficer, ComplianceOfficer, AppealsOfficer, Guardian |
| POST | `/esa/renewal-reviews/{id}/decision` | Approve or deny continued eligibility. | EligibilityOfficer |
| POST | `/esa/appeals` | File an appeal against exactly one subject: an application denial, a clawback, or a provider delisting. | Guardian, Provider |
| GET | `/esa/appeals/{id}` | Read one appeal with its subject reference, decision and rationale. | ProgramAdmin, AppealsOfficer, ComplianceOfficer, EligibilityOfficer, Guardian, Provider |
| GET | `/esa/appeals` | List appeals filtered by subject type, subject id or status. | ProgramAdmin, AppealsOfficer, ComplianceOfficer, EligibilityOfficer, Guardian, Provider |
| POST | `/esa/appeals/{id}/decision` | Decide an appeal: OVERTURNED re-opens the application, reverses the clawback, or returns the provider to probation; UPHELD makes the original outcome final. | AppealsOfficer |
| POST | `/esa/_clock/set_current_utc` | Set the server's logical UTC clock, which every deadline, window and decay rule reads. | ProgramAdmin |

## 5. Error Code Catalogue

The table lists every error identifier the API can return together with its HTTP status code. The conditions that trigger each one are stated in the §2 and §3 narratives that own the corresponding rule, and the relative order in which competing conditions are evaluated is fixed by §2.8.

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_PROGRAM_YEAR_NOT_FOUND` | 404 |
| `ERR_STUDENT_NOT_FOUND` | 404 |
| `ERR_APPLICATION_NOT_FOUND` | 404 |
| `ERR_ACCOUNT_NOT_FOUND` | 404 |
| `ERR_PROVIDER_NOT_FOUND` | 404 |
| `ERR_EXPENSE_CATEGORY_NOT_FOUND` | 404 |
| `ERR_PURCHASE_REQUEST_NOT_FOUND` | 404 |
| `ERR_MISUSE_CASE_NOT_FOUND` | 404 |
| `ERR_RENEWAL_REVIEW_NOT_FOUND` | 404 |
| `ERR_APPEAL_NOT_FOUND` | 404 |
| `ERR_NOT_ACCOUNT_HOLDER` | 403 |
| `ERR_NOT_ASSIGNED_PROVIDER` | 403 |
| `ERR_STALE_ACCOUNT_VERSION` | 412 |
| `ERR_STALE_APPLICATION_VERSION` | 412 |
| `ERR_PROGRAM_YEAR_NOT_ACTIVE` | 409 |
| `ERR_APPLICATION_WINDOW_CLOSED` | 409 |
| `ERR_INVALID_STATE_TRANSITION` | 409 |
| `ERR_ACCOUNT_SUSPENDED` | 409 |
| `ERR_APPEAL_ROUNDS_EXHAUSTED` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_FRAUD_RISK_TOO_HIGH` | 422 |
| `ERR_PROVIDER_NOT_ELIGIBLE` | 422 |
| `ERR_CATEGORY_NOT_AUTHORIZED` | 422 |
| `ERR_EXPENSE_NOT_ALLOWABLE` | 422 |
| `ERR_PREAPPROVAL_REQUIRED` | 422 |
| `ERR_OVERLAPPING_ENROLLMENT_PERIOD` | 409 |
| `ERR_DUPLICATE_SERVICE_PERIOD` | 409 |
| `ERR_SERVICE_PERIOD_OUTSIDE_TERM` | 422 |
| `ERR_DUPLICATE_APPLICATION` | 409 |
| `ERR_RESIDENCY_NOT_ELIGIBLE` | 422 |
| `ERR_ASSESSMENT_EVIDENCE_INSUFFICIENT` | 422 |
| `ERR_CATEGORY_CAP_EXCEEDED` | 422 |
| `ERR_INSUFFICIENT_BALANCE` | 402 |
| `ERR_NO_SEATS_AVAILABLE` | 409 |
| `ERR_CLAIM_AMOUNT_MISMATCH` | 422 |
