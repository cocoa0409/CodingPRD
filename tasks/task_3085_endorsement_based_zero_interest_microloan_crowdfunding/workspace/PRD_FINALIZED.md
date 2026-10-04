# Endorsement Microloan Crowdfunding API — Product Requirements Document

## 1. Introduction

Small-business owners without credit history are routinely shut out of conventional lending, yet they are often surrounded by a community willing to vouch for them. This platform operationalizes that observation: it is a zero-interest microloan crowdfunding service in which underwriting is social rather than financial. A borrower does not pass a credit-score threshold; instead, they gather community members who accept underwriting invitations, and — in the stronger variant — a community organization (a trustee) formally vouches for them. Capital is then raised in two stages: a private fundraising period in which a quorum of personal endorsers must each lend a small amount before the campaign is visible to the public, and a public campaign in which any lender may contribute until the requested principal is fully funded or the campaign expires.

Because the loans carry no interest, every dollar a lender puts in is principal, and every dollar of repayment is returned to lenders as credit in their lending account — never as yield. The platform's integrity rests on a handful of enforced invariants: a borrower may have only one live application at a time; a trustee's vouching capacity is capped and automatically suspended when too many of their endorsed loans default; a funded application that is cancelled before disbursement refunds every lender; and a borrower whose loan defaults is permanently restricted from borrowing again. Delinquency triggers borrower coaching, never collections referral.

This document is the complete product specification for the API: global contracts (response envelope, pagination, concurrency control, the logical clock), the business workflows from registration through impact reporting, the endpoint catalogue, and the error code catalogue.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID` and `X-User-Role`. The declared roles, spelled exactly, are `Anonymous`, `Borrower`, `Lender`, `Trustee`, and `PlatformAdmin`.

Four kinds of callers exist. A self-registering participant or an invitee following an invitation link calls as `Anonymous`; in that case `X-User-ID` is an opaque identifier not tied to any persisted entity and is not compared to any resource field. A borrower acts with `X-User-Role` set to `Borrower`, and `X-User-ID` must be the `id` of the acting `Borrower` record; ownership checks on any resource that references a borrower compare the resource's `borrower_id` to `X-User-ID`. A lender acts with `X-User-Role` set to `Lender`, and `X-User-ID` must be the `id` of the acting `Lender` record; ownership checks compare a resource's `lender_id` to `X-User-ID`. A trustee acts with `X-User-Role` set to `Trustee`, and `X-User-ID` must be the `id` of the acting `Trustee` record. A platform operator acts with `X-User-Role` set to `PlatformAdmin`; `X-User-ID` is an opaque operator identifier not tied to any persisted entity — the server may record it but never compares it to any entity's `id`.

Only four endpoints accept anonymous calls: borrower self-registration, lender self-registration, and the two invite-resolution actions (accept and decline) reached via an invite link. Every other endpoint requires a valid role header, and requests missing a declared role or a required `X-User-ID` are rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A caller whose role is not permitted for the operation, or whose `X-User-ID` fails an entity-backed ownership check, is rejected with `ERR_FORBIDDEN` (HTTP 403).

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

List endpoints accept the query parameters `limit` and `offset`. The `limit` parameter defaults to 10, with a minimum of 1 and a maximum of 100; `offset` defaults to 0. List responses include `limit`, `offset`, `total_count`, and `has_more` in the `meta` object. Unless a more specific ordering is stated for a particular calculation, list endpoints return resources sorted by `created_at` ascending.

### 2.4. Logical Clock and the Maintenance Sweep

The platform runs on a logical clock, not wall-clock time. Before the clock is ever set, the logical clock reads exactly `2026-09-01T00:00:00Z` and never falls back to wall-clock time. A `PlatformAdmin` may advance it by supplying a `current_utc` timestamp to the clock-setting capability; setting the clock does not, by itself, trigger any state changes.

All time-driven transitions are executed by an explicit maintenance sweep, invoked by a `PlatformAdmin`, which evaluates the current logical time and performs, in a single pass: expiring underwriting invites that have sat unanswered for 30 days; expiring private fundraising periods whose deadline has passed; expiring underfunded public campaigns whose deadline has passed; refreshing installment status labels as due dates approach and pass; moving loans with a sufficiently overdue installment into delinquency; moving long-delinquent loans into default; and automatically suspending trustees whose default rate has breached the program threshold. The sweep returns counters describing its work: `invites_expired`, `applications_expired`, `loans_delinquent`, `loans_defaulted`, and `trustees_suspended`. Every deadline, grace window, and status flip described in §3 is evaluated only when the sweep runs — nothing in this system transitions merely because time passed.

### 2.5. Resource Identity, Timestamps, and Versioning

Every resource carries a server-minted `id` — a UUID with no type prefix — and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. Most resources additionally carry `updated_at` (same format) and an integer `version` that starts low and increments by exactly 1 on every mutation of that resource, including mutations caused by cascading side effects of operations on other resources.

Two resource types are intentionally leaner: an `UnderwritingInvite` and a `Payment` carry only `id` and `created_at`. Both `updated_at` and `version` are absent from these two entities, and no optimistic-concurrency field ever references them.

### 2.6. Monetary Units, Precision, and the Zero-Interest Principle

All money is represented as integer cents — never fractional units. Wherever a computation must divide cents (per-installment bases, per-lender repayment shares), the division is a floor division in integer cents and the rounding remainder is handled explicitly by the rule that owns the computation; the repayment-distribution rule rounds each lender's share down to whole cents and the unallocated remainder is retained by the platform. Scores and rates that are not monetary use round-half-up to integers as specified in their own rules.

The platform is strictly zero-interest. A lender's return on any loan can never exceed the principal they lent: repayment distribution credits each lender's `lending_balance_cents` with a pro-rata share of each borrower payment, and the platform — not any lender — keeps whatever rounding remainder the shares leave behind. There is no interest field, no yield field, and no collections referral anywhere in the system.

### 2.7. Optimistic Concurrency Control

Three write operations are guarded by optimistic concurrency control, and each requires a non-optional expected-version input:

- Submitting a loan application requires `expected_application_version`, carrying the version of the `LoanApplication` the client last observed. If the application's current `version` has advanced since that observation — for example because the draft was edited, and each edit bumps the version — the submission is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Disbursing a funded application likewise requires `expected_application_version`. Because every endorsement and every contribution bumps the application's `version`, a version read before the final contribution arrived is stale by the time disbursement is requested, and the request is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Finalizing a loan's repayment schedule requires `expected_loan_version`, matched against the `Loan`'s current `version`. Any mutation of the loan — a payment, a status flip — advances the version, and a finalize request carrying an earlier-observed version is rejected with `ERR_STALE_VERSION` (HTTP 412).

Endpoints not listed here do not take a version field.

### 2.8. Identifier Resolution and Uniqueness

Path identifiers and body foreign keys — `borrower_id`, `lender_id`, `trustee_id`, `loan_application_id`, `loan_id`, and the invite `token` — are validated left-to-right: the leftmost unresolved reference in the URL path is reported first, and body references are checked after path references. Any reference that does not resolve to an existing record is rejected with `ERR_NOT_FOUND` (HTTP 404).

Four uniqueness constraints are enforced, each surfacing as `ERR_DUPLICATE` (HTTP 409): a borrower's `email` is unique across all borrowers (which also means a restricted borrower can never re-register with the same address); a lender's `email` is unique across all lenders; the pair (`borrower_id`, `invitee_email`) is unique among a borrower's underwriting invites; and the pair (`loan_application_id`, `lender_id`) may have at most one `ACTIVE` endorsement — a lender who already holds a live endorsement on an application cannot place a second one, though a cancelled or refunded endorsement does not block a new one.

### 2.9. Validation Ordering

When a request could fail for several reasons, checks are evaluated in a fixed global order so the reported error is deterministic. First, authentication: the role header must be present, declared, and accompanied by an `X-User-ID` where the role is entity-backed (`ERR_UNAUTHENTICATED`). Second, authorization and entity-backed ownership (`ERR_FORBIDDEN`). Third, existence of every path and body reference, left-to-right (`ERR_NOT_FOUND`). Fourth, state permissibility of the target resource (`ERR_INVALID_STATE`). Fifth, request shape — required fields present, values well-typed, enum members valid, numeric ranges respected (`ERR_INVALID_REQUEST`). Sixth, uniqueness (`ERR_DUPLICATE`). Seventh, the domain safety and fiscal rules in their stated per-endpoint order (§3 names the order where several apply to one endpoint). Last of all, the optimistic-concurrency check (`ERR_STALE_VERSION`) — a stale request that also violates a business rule reports the business rule.

Request-shape rules worth stating globally: `requested_amount_cents` must be a positive multiple of 100; `term_months` must be an integer from 3 to 36 inclusive; a payment's `amount_cents` must be at least 100. Violations of these are `ERR_INVALID_REQUEST` (HTTP 400).

## 3. Business Logic & Workflows

### 3.1. Participant Registration and Accounts

Anyone may self-register as a borrower by providing their `legal_name`, `business_name`, contact `email`, the `business_tenure_months` the business has operated, and optionally a self-declared `prior_repaid_loans_count` of previously fully repaid microloans (defaulting to 0 when omitted). A new borrower starts in `REGISTERED` status with both loan counters — `completed_loan_count` and `defaulted_loan_count` — at 0, a `social_underwriting_score` of 0, an `underwriting_variant` of `NONE`, and `restricted_since` null. The tenure and prior-repayment inputs are not decorative: both feed the social underwriting score computed at application submission.

Lender self-registration requires only a `display_name` and an `email`, and opens a lending account whose `lending_balance_cents`, `total_deposited_cents`, `lifetime_lent_cents`, and `lifetime_repaid_cents` all start at 0. Funds enter the account through deposits: each deposit adds its `amount_cents` to both `lending_balance_cents` and `total_deposited_cents` and bumps the lender's `version`. The spendable balance is debited whenever the lender lends and credited whenever money comes back — through repayment shares or refunds. The `lifetime_lent_cents` counter tracks capital the lender has deployed, and `lifetime_repaid_cents` accumulates principal credited back through repayment distribution.

Trustees are not self-registered. A `PlatformAdmin` registers a community organization with its `org_name` and an `endorsement_limit_cents` cap on the total it may have vouched at any moment. A new trustee is `ACTIVE` with `suspension_reason` of `NONE` and all exposure and outcome counters at 0.

Borrowers may update their own profile (`legal_name`, `business_name`, `business_tenure_months`, `prior_repaid_loans_count`) — or a `PlatformAdmin` may do it for them — and each update increments the borrower's `version`.

### 3.2. Social Underwriting: Invites, Quota, and the Score

Before a borrower can submit an application, they must assemble community vouches. The borrower invites community members by supplying an `invitee_email`; each invitation creates an `UnderwritingInvite` owned by that borrower (recorded as its `borrower_id`), mints an opaque server-generated `invite_token` that appears in the invite link, and starts in `SENT` status with `responded_at` null. Inviting the same address twice is a duplicate and is rejected.

The invitee — an anonymous caller following the token link — either accepts or declines. Both actions require the invite to still be `SENT`; an invite already resolved is rejected with `ERR_INVITE_NOT_PENDING` (HTTP 409). Acceptance moves the invite to `ACCEPTED`, declining moves it to `DECLINED`, and both stamp `responded_at` with the resolution time. Invites are perishable: the maintenance sweep moves any invite still `SENT` 30 days after its creation to `EXPIRED`, stamping `responded_at` with the sweep time.

The number of `ACCEPTED` invites gates submission through the acceptance quota: a borrower needs at least the larger of 3 and the requested principal divided by 1,000,000 cents (that is, one additional accepted vouch per full $10,000 requested beyond the baseline three), with the division floored. Meeting the quota exactly is sufficient. Falling short rejects the submission with `ERR_UNDERWRITING_ACCEPTANCE_QUOTA` (HTTP 409).

Submission also computes the borrower's social underwriting score, an integer from 0 to 100 assembled from four components and rounded half-up. The tenure component is 20 times the ratio of the borrower's `business_tenure_months` — capped at 24 months — to 24. The community component is 30 times the ratio of the borrower's `ACCEPTED` invite count — capped at 10 — to 10. The trustee component is 25 when the submission is trustee-vouched and 0 otherwise. The repayment component is 25 times the ratio of `prior_repaid_loans_count` — capped at 2 — to 2, but only for self-endorsed submissions; a trustee's vouch substitutes for repayment track record, so trustee-vouched submissions score 0 on this component. The four components are summed, rounded half-up, and clamped into the 0-to-100 range, then stored on the borrower as `social_underwriting_score` together with the `underwriting_variant` actually used: `STANDARD` for a self-endorsed submission, `TRUSTEE_AUGMENTED` for a trustee-vouched one.

### 3.3. The Application Review Pipeline

A borrower begins by creating a draft application with their `borrower_id`, the `requested_amount_cents`, a `term_months` repayment term, and a free-text `business_purpose`. The draft starts in `DRAFT` with all fundraising counters — `distinct_endorser_count`, `private_total_cents`, `public_total_cents`, and `funded_total_cents` — at 0 and all lifecycle timestamps null. While the application remains in `DRAFT`, the owner (or a `PlatformAdmin`) may edit `requested_amount_cents`, `term_months`, and `business_purpose`; every edit increments the application's `version`.

Submitting the draft is the borrower's act and carries the OCC guard `expected_application_version`. Submission enforces five checks, in this order: the borrower must be `REGISTERED` — a borrower with a defaulted loan is rejected with `ERR_BORROWER_RESTRICTED` (HTTP 409); the borrower must have no other live application — any application in `DRAFT`, `IN_REVIEW`, `APPROVED_PENDING_FUNDRAISE`, `PRIVATE_FUNDRAISING`, `PUBLIC_FUNDRAISING`, or `FUNDED` blocks a second submission with `ERR_ACTIVE_APPLICATION_EXISTS` (HTTP 409); the acceptance quota of §3.2 must be met; and, when the submission names a `trustee_id`, the trustee must exist, must be `ACTIVE` (a suspended trustee yields `ERR_TRUSTEE_SUSPENDED`, HTTP 409), and must have remaining capacity — the application's `requested_amount_cents` plus the trustee's `active_endorsement_exposure_cents` must not exceed the trustee's `endorsement_limit_cents`, or the submission fails with `ERR_TRUSTEE_LIMIT_EXCEEDED` (HTTP 422). The presence or absence of `trustee_id` is itself the mode selector: providing it pins `endorsement_mode` to `TRUSTEE_VOUCHED` and `required_endorser_count` to 5; omitting it pins `SELF_ENDORSED` and `required_endorser_count` to 15. These two values are fixed at submission and never recomputed. A successful submission moves the application `DRAFT` → `IN_REVIEW`, recomputes the borrower's score and variant as in §3.2, and bumps the application's `version`.

Review belongs to the `PlatformAdmin`, with three outcomes. Requesting changes sends the application `IN_REVIEW` → `DRAFT` for revision. Approval requires the borrower's `social_underwriting_score` to be at least 60 — a score below the threshold rejects the approval with `ERR_SCORE_TOO_LOW` (HTTP 409) — and moves the application to `APPROVED_PENDING_FUNDRAISE`. Rejection moves it to `REJECTED` and stamps `terminal_at`. All three actions accept optional `notes`, recorded into the application's `review_notes`.

### 3.4. Private Fundraising and the Endorser Quorum

Once approved, the borrower opens the private fundraising period, moving the application `APPROVED_PENDING_FUNDRAISE` → `PRIVATE_FUNDRAISING` and stamping `private_started_at`; the `private_deadline` is set to exactly 15 days later.

During the private period, lenders lend through endorsements. Creating an endorsement requires the target application to be in `PRIVATE_FUNDRAISING`, names the lending `lender_id` and an `amount_cents` of at least 2,500 cents ($25) — anything smaller is rejected with `ERR_MIN_CONTRIBUTION` (HTTP 422) — and debits the lender's `lending_balance_cents` by that amount; a balance short of the amount is rejected with `ERR_INSUFFICIENT_BALANCE` (HTTP 422). The endorsement starts `ACTIVE` with `resolved_at` null. Each new endorsement recomputes the application's `private_total_cents` (the sum of `amount_cents` over its `ACTIVE` endorsements) and `distinct_endorser_count`, and bumps the application's `version` as well as the lender's.

A trustee may instead vouch directly, creating an endorsement flagged `is_trustee_endorsement` with the vouching `trustee_id` recorded. Trustee endorsements move no money — no lender balance is debited — but they count toward the endorser quorum and their `amount_cents` counts against the trustee's cap: the trustee's `active_endorsement_exposure_cents` (the sum of `amount_cents` over that trustee's `ACTIVE` trustee endorsements) plus the new amount must stay within `endorsement_limit_cents`, else `ERR_TRUSTEE_LIMIT_EXCEEDED`; and a `SUSPENDED` trustee may not vouch at all (`ERR_TRUSTEE_SUSPENDED`). A trustee endorsement raises the trustee's exposure, the application's `private_total_cents`, and its `distinct_endorser_count` exactly as a lender endorsement would.

The quorum itself is a count of distinct endorsers: the number of distinct lenders holding `ACTIVE` non-trustee endorsements, plus the number of `ACTIVE` trustee endorsements. When the borrower opens the public campaign — moving the application `PRIVATE_FUNDRAISING` → `PUBLIC_FUNDRAISING` — the count must meet the `required_endorser_count` pinned at submission (15 self-endorsed, 5 trustee-vouched); meeting it exactly suffices, and falling short is rejected with `ERR_QUORUM_NOT_MET` (HTTP 409). A successful opening stamps `public_started_at` and sets the `public_deadline` 30 days out.

### 3.5. The Public Campaign: Contributions, Funding, and Early Exit

In `PUBLIC_FUNDRAISING`, any lender may contribute. A contribution names the `lender_id` and an `amount_cents` of at least 2,500 cents, debits the lender's `lending_balance_cents` (insufficient balance: `ERR_INSUFFICIENT_BALANCE`), and starts `ACTIVE`. It raises the application's `public_total_cents` — the sum over `ACTIVE` contributions — and bumps the application's `version`. Overfunding is impossible by construction: a contribution that would push `funded_total_cents` (the sum of `private_total_cents` and `public_total_cents`) above `requested_amount_cents` is rejected with `ERR_OVERFUND` (HTTP 422). The moment a contribution brings `funded_total_cents` to exactly the requested amount, the application transitions automatically to `FUNDED` and stamps `funded_at`.

Deadlines are enforced by the maintenance sweep, not by the passage of time alone. A private period still running past its `private_deadline` is moved to `EXPIRED_PRIVATE`; every `ACTIVE` endorsement on it becomes `REFUNDED` with `resolved_at` stamped at sweep time, each non-trustee endorsement credits its `amount_cents` back to the lender's `lending_balance_cents`, and the application's `private_total_cents` and `distinct_endorser_count` recompute to 0. A public campaign past its `public_deadline` whose `funded_total_cents` is still short of the requested amount is moved to `EXPIRED_PUBLIC`; every `ACTIVE` endorsement and every `ACTIVE` contribution becomes `REFUNDED`, each non-trustee endorsement and each contribution credits its lender back in full, and `private_total_cents`, `public_total_cents`, and `distinct_endorser_count` all recompute to 0. Both transitions stamp `terminal_at`. A public campaign that reached `FUNDED` before its deadline is untouched by expiry.

Borrowers retain two voluntary exits. Withdrawal is available from `DRAFT`, `IN_REVIEW`, `APPROVED_PENDING_FUNDRAISE`, and `PRIVATE_FUNDRAISING`, moving the application to `WITHDRAWN` with `terminal_at` stamped; withdrawing from `PRIVATE_FUNDRAISING` additionally moves every `ACTIVE` endorsement to `CANCELLED` (stamping each `resolved_at`) and credits each non-trustee endorsement's amount back to its lender. Cancellation is the post-funding exit: a `FUNDED` application for which no `Loan` has yet been created may be cancelled into `CANCELLED`, refunding every `ACTIVE` endorsement and contribution exactly as an expiry would. Attempting either action from any other state is `ERR_INVALID_STATE`.

### 3.6. Disbursement and the Two-Stage Repayment Schedule

Disbursement is a `PlatformAdmin` act on a `FUNDED` application — attempting it in any other state is rejected with `ERR_APPLICATION_NOT_FUNDED` (HTTP 409) — and carries the OCC guard `expected_application_version`. Disbursement creates the `Loan`: at most one loan ever exists per application, its `borrower_id`, `principal_cents` (equal to the application's `requested_amount_cents`), and `term_months` are copied from the application, `disbursed_at` is stamped, and the loan starts in `REPAYING` with `schedule_status` of `PROVISIONAL`. In the same act, every `ACTIVE` endorsement and contribution on the application becomes `CONVERTED` with `resolved_at` set to the disbursement timestamp (a converted trustee endorsement leaves the trustee's exposure untouched — the amount has counted against the cap since creation), and each lender's `lifetime_lent_cents` increases by the total of their converted amounts on the loan.

The loan is born with a full installment schedule of `term_months` installments, numbered 1 upward in `installment_number`, each due one month after the previous: the `due_date` of installment *i* is `disbursed_at` plus *i* months. Under the provisional schedule the split is even: the `provisional_base_cents` is the principal floor-divided by the term, installments 1 through *N*−1 carry that base as their `amount_due_cents`, and the final installment absorbs the entire rounding remainder. Every installment starts `PENDING` with `amount_paid_cents` at 0 and `remaining_cents` equal to its `amount_due_cents`; the loan's `outstanding_cents` is always the sum of `remaining_cents` across its installments.

A `PlatformAdmin` may replace the provisional schedule with the final schedule exactly once, guarded by `expected_loan_version`, and only while the loan is `REPAYING`, the `schedule_status` is still `PROVISIONAL`, and no payment has touched any installment (every `amount_paid_cents` still 0) — otherwise the request fails with `ERR_SCHEDULE_ALREADY_FINAL` (HTTP 409). The final schedule deliberately front-loads the first installment by 100 cents plus the remainder: the `final_base_cents` is `principal_cents` minus 100, floor-divided by the term; installments 2 through *N* carry that base; and installment 1 carries the `final_first_cents` — whatever remains of the principal after the other *N*−1 installments take the reduced base. Finalization rewrites every installment's `amount_due_cents`, stores both computed bases on the loan, flips `schedule_status` to `FINAL`, and bumps the loan's `version`.

### 3.7. Repayment Waterfall, Lender Distribution, Delinquency, and Default

The borrower repays by making payments of at least 100 cents against a loan they own; each payment records its `loan_id`, copies the loan's `borrower_id` onto itself for reverse lookup, and is stamped `paid_at` at the server's current time. Funds apply oldest-installment-first: walking the installments in ascending `installment_number`, skipping any already `PAID`, each installment absorbs the smaller of the remaining payment and its own `remaining_cents`. An installment fully covered becomes `PAID` with `paid_at` stamped and `remaining_cents` zeroed; one partially covered becomes `PARTIAL`. Should a payment overpay the whole schedule, the excess carries onto the last installment's `amount_paid_cents` (an installment's paid amount may therefore exceed its due amount). After the walk, the loan's `outstanding_cents` is recomputed.

Two automatic loan transitions hang off every payment. If `outstanding_cents` reaches 0, the loan becomes `PAID_OFF` — from `REPAYING` or from `DELINQUENT` alike — the borrower's `completed_loan_count` increments, and, when a trustee endorsed the underlying application, the trustee's `endorsed_terminal_count` increments and its `default_rate_bps` is recomputed. Separately, if the loan was `DELINQUENT` and the payment leaves no non-`PAID` installment more than 14 days past its `due_date`, the loan cures back to `REPAYING` and `delinquent_since` clears to null.

Each payment is simultaneously distributed to lenders as principal credit. Each lender's lent total on the loan is the sum of their `CONVERTED` endorsement and contribution amounts. Walking the lenders in order of their earliest conversion's `created_at` ascending — ties broken by the lender's `display_name` ascending — each receives a share equal to the payment amount times their lent total divided by the loan's `principal_cents`, floored to whole cents, credited to `lending_balance_cents` and accumulated into `lifetime_repaid_cents`. Whatever the floored shares leave unallocated is retained by the platform: no lender ever receives more than principal.

Delinquency and default belong to the sweep. A `REPAYING` loan whose earliest non-`PAID` installment is more than 14 days past due moves to `DELINQUENT`, stamps `delinquent_since`, and records a delinquency coaching message for the borrower — coaching, never collections. A `DELINQUENT` loan whose earliest non-`PAID` installment is more than 74 days past due — the 14-day delinquency window plus a 60-day default horizon — moves to `DEFAULTED`, stamps `defaulted_at`, and cascades hard: the borrower's `status` becomes `RESTRICTED` with `restricted_since` set to the sweep time and `defaulted_loan_count` incremented, and the email-uniqueness rule then ensures this borrower can never simply re-register. When a trustee endorsed the underlying application, the default also increments the trustee's `endorsed_terminal_count` and `endorsed_defaulted_count` and recomputes its `default_rate_bps`. `RESTRICTED` is effectively terminal — no transition ever returns a borrower to `REGISTERED`. Both transitions are evaluated sequentially within a single sweep pass against the same earliest non-`PAID` installment, so a `REPAYING` loan whose earliest non-`PAID` installment is already more than 74 days past due moves through `DELINQUENT` to `DEFAULTED` in that one pass and is counted in both `loans_delinquent` and `loans_defaulted`.

Installment labels track the calendar between payments: the sweep moves a `PENDING` installment to `DUE` once the current time enters the 7 days before its `due_date`, and moves any `DUE` or `PARTIAL` installment past its `due_date` with `remaining_cents` above 0 to `LATE`.

### 3.8. Trustee Vouching, Exposure, and Program Health

A trustee's standing is measured continuously. The `default_rate_bps` is 0 while the trustee has no terminally resolved endorsed loans, and otherwise ten thousand times `endorsed_defaulted_count` divided by `endorsed_terminal_count`, rounded half-up to integer basis points — where the terminal count covers endorsed loans that reached `PAID_OFF` or `DEFAULTED`.

Suspension has two doors. A `PlatformAdmin` may suspend an `ACTIVE` trustee manually, setting `suspension_reason` to `MANUAL`. The sweep suspends a trustee automatically when its `default_rate_bps` exceeds 2,000 basis points (20%) across at least 3 terminally resolved endorsed loans, setting `suspension_reason` to `DEFAULT_RATE`. While `SUSPENDED`, the trustee cannot vouch: new trustee endorsements referencing it are rejected with `ERR_TRUSTEE_SUSPENDED`, and submissions naming it fail the same way. Reinstatement is manual only — a `PlatformAdmin` returns a `SUSPENDED` trustee to `ACTIVE` and resets `suspension_reason` to `NONE`. Requesting either transition from the wrong state is `ERR_INVALID_STATE`.

Exposure is accounted at vouch time and released at resolution: a trustee's `active_endorsement_exposure_cents` rises with each trustee endorsement it issues and falls as those endorsements leave `ACTIVE`, and the capacity check in §3.4 applies both when a borrower submits trustee-vouched (using the full `requested_amount_cents` as the prospective amount) and when the trustee issues an endorsement directly.

### 3.9. Impact Reporting and Lender Impact Aggregation

Borrowers report outcomes back to the crowd. On a live or completed loan they own, a borrower files a report with `months_after_disbursement`, a `revenue_change_pct` between −100 and 1000, a `jobs_created` count between 0 and 100, and a free-text `narrative`. The timing claim is verified: `months_after_disbursement` must equal the whole months actually elapsed since the loan's `disbursed_at`, or the filing is rejected with `ERR_TIMING_MISMATCH` (HTTP 409). Each report records its `loan_id` and the copied `borrower_id`, and computes `is_mid_term` — true when the report was filed no later than the whole-month midpoint of the loan's term (half of `term_months`, floored).

Lenders see their money's effect through the aggregated impact view, which considers every `ImpactReport` filed on loans whose applications that lender helped fund via a converted endorsement or contribution, and returns a `report_count`, a `jobs_created_weighted`, and a `revenue_change_pct_weighted`. Two variants exist. When every candidate report is mid-term, the aggregation is a simple unweighted mean — each report counts equally and both figures are the average across reports, rounded half-up. Once any candidate report is past mid-term, the aggregation switches to principal-share weighting: each report is weighted by the lender's lent cents on that report's loan, and both figures are the weighted average across reports, rounded half-up.

## 4. Endpoint Definitions

All endpoints are served under the API root. Creating a new resource returns HTTP 201 with the created resource; operations that modify an existing resource (state transitions, deposits, disbursement, payments notwithstanding their creation semantics, invite resolution) return HTTP 200 with the updated resource — with the exceptions noted by creation semantics: deposits, endorsements, contributions, payments, and impact reports return 201 because each creates a new subordinate record. List endpoints return HTTP 200 with an array envelope.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/_clock/set_current_utc` | Set the server's logical clock | PlatformAdmin |
| POST | `/_sweeps/run` | Run one maintenance pass at the current logical time | PlatformAdmin |
| POST | `/borrowers` | Register a borrower (self-registration) | Anonymous |
| GET | `/borrowers/{id}` | Get a borrower | Borrower, PlatformAdmin, Trustee, Lender |
| PATCH | `/borrowers/{id}` | Update a borrower's profile | Borrower, PlatformAdmin |
| GET | `/borrowers/{id}/underwriting-invites` | List a borrower's underwriting invites | Borrower, PlatformAdmin |
| GET | `/borrowers/{id}/loan-applications` | List a borrower's loan applications | Borrower, PlatformAdmin |
| GET | `/borrowers/{id}/loans` | List loans disbursed to this borrower | Borrower, PlatformAdmin |
| GET | `/borrowers/{id}/impact-reports` | List impact reports filed on this borrower's loans | Borrower, PlatformAdmin |
| GET | `/borrowers/{id}/payments` | List payments made by this borrower | Borrower, PlatformAdmin |
| POST | `/borrowers/{id}/underwriting-invites` | Invite a community member to vouch during social underwriting | Borrower |
| POST | `/underwriting-invites/{token}/accept` | Invitee accepts the underwriting vouch via the token link | Anonymous |
| POST | `/underwriting-invites/{token}/decline` | Invitee declines the underwriting vouch via the token link | Anonymous |
| POST | `/lenders` | Register a lender (self-registration) | Anonymous |
| GET | `/lenders/{id}` | Get a lender | Lender, PlatformAdmin |
| POST | `/lenders/{id}/deposits` | Deposit funds into the lender's lending account | Lender, PlatformAdmin |
| GET | `/lenders/{id}/endorsements` | List endorsements made by this lender | Lender, PlatformAdmin |
| GET | `/lenders/{id}/contributions` | List contributions made by this lender | Lender, PlatformAdmin |
| GET | `/lenders/{id}/impact` | Aggregated impact across loans this lender helped fund | Lender, PlatformAdmin |
| POST | `/trustees` | Register a community organization as a trustee | PlatformAdmin |
| GET | `/trustees/{id}` | Get a trustee | PlatformAdmin, Trustee, Borrower |
| POST | `/trustees/{id}/suspend` | Manually suspend a trustee | PlatformAdmin |
| POST | `/trustees/{id}/reinstate` | Reinstate a suspended trustee | PlatformAdmin |
| POST | `/trustees/{id}/endorsements` | Trustee vouches for an application; counts toward the quorum, debits no balance | Trustee |
| GET | `/trustees/{id}/endorsements` | List trustee endorsements issued by this trustee | Trustee, PlatformAdmin |
| GET | `/trustees/{id}/loan-applications` | List applications vouched by this trustee | Trustee, PlatformAdmin |
| POST | `/loan-applications` | Create a draft loan application | Borrower |
| GET | `/loan-applications/{id}` | Get a loan application | Borrower, Lender, Trustee, PlatformAdmin |
| GET | `/loan-applications` | List loan applications, optionally filtered by `status` and `borrower_id` | Borrower, Lender, Trustee, PlatformAdmin |
| PATCH | `/loan-applications/{id}` | Edit a DRAFT application | Borrower, PlatformAdmin |
| POST | `/loan-applications/{id}/submit` | Submit a draft for social underwriting review (OCC on application version) | Borrower |
| POST | `/loan-applications/{id}/approve` | Approve an application in review | PlatformAdmin |
| POST | `/loan-applications/{id}/reject` | Reject an application in review | PlatformAdmin |
| POST | `/loan-applications/{id}/request-changes` | Send an application in review back to draft for revision | PlatformAdmin |
| POST | `/loan-applications/{id}/open-private` | Open the private fundraising period | Borrower |
| POST | `/loan-applications/{id}/open-public` | Open the public campaign once the endorser quorum is met | Borrower |
| POST | `/loan-applications/{id}/withdraw` | Withdraw a live application before funding | Borrower |
| POST | `/loan-applications/{id}/cancel` | Cancel a FUNDED application before disbursement | Borrower |
| POST | `/loan-applications/{id}/disburse` | Disburse a fully funded application; creates the Loan with a PROVISIONAL schedule (OCC) | PlatformAdmin |
| GET | `/loan-applications/{id}/endorsements` | List endorsements on an application | Borrower, Lender, Trustee, PlatformAdmin |
| GET | `/loan-applications/{id}/contributions` | List contributions on an application | Borrower, Lender, Trustee, PlatformAdmin |
| GET | `/loan-applications/{id}/loan` | Get the loan disbursed from this application, if any (array of 0 or 1) | Borrower, Lender, Trustee, PlatformAdmin |
| POST | `/loan-applications/{id}/endorsements` | Lender lends during the private fundraising period | Lender |
| POST | `/loan-applications/{id}/contributions` | Lender contributes during the public campaign period | Lender |
| GET | `/loans/{id}` | Get a loan | Borrower, Lender, Trustee, PlatformAdmin |
| POST | `/loans/{id}/finalize-schedule` | Replace the provisional schedule with the final schedule (OCC on loan version) | PlatformAdmin |
| POST | `/loans/{id}/payments` | Borrower makes a repayment, applied oldest-installment-first and distributed pro-rata | Borrower |
| GET | `/loans/{id}/installments` | List a loan's repayment installments | Borrower, Lender, Trustee, PlatformAdmin |
| GET | `/loans/{id}/payments` | List payments made on a loan | Borrower, Lender, Trustee, PlatformAdmin |
| GET | `/loans/{id}/impact-reports` | List impact reports filed on a loan | Borrower, Lender, Trustee, PlatformAdmin |
| POST | `/loans/{id}/impact-reports` | Borrower files a business-outcome report for a live or completed loan | Borrower |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_DUPLICATE` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_BORROWER_RESTRICTED` | 409 |
| `ERR_ACTIVE_APPLICATION_EXISTS` | 409 |
| `ERR_UNDERWRITING_ACCEPTANCE_QUOTA` | 409 |
| `ERR_TRUSTEE_SUSPENDED` | 409 |
| `ERR_TRUSTEE_LIMIT_EXCEEDED` | 422 |
| `ERR_SCORE_TOO_LOW` | 409 |
| `ERR_QUORUM_NOT_MET` | 409 |
| `ERR_MIN_CONTRIBUTION` | 422 |
| `ERR_INSUFFICIENT_BALANCE` | 422 |
| `ERR_OVERFUND` | 422 |
| `ERR_APPLICATION_NOT_FUNDED` | 409 |
| `ERR_TIMING_MISMATCH` | 409 |
| `ERR_INVITE_NOT_PENDING` | 409 |
| `ERR_SCHEDULE_ALREADY_FINAL` | 409 |
