# Electronic Mortgage Registry API — Product Requirements Document

## 1. Introduction

Mortgage servicing runs on a simple promise that is surprisingly hard to keep in practice: at any moment, someone must be able to say with certainty who owns the beneficial interest in a loan and who services it. When loans change hands weekly and servicing rights trade independently of beneficial ownership, paper assignments and county land records cannot answer that question at operational speed. This document specifies the Electronic Mortgage Registry API — a central, operator-run registry of record in the style of a national electronic mortgage registry — that member organizations (originators, servicers, investors, subservicers, and custodians) use to register loans at closing, report transfers of beneficial and servicing rights, and reconcile their own servicing platforms against the registry as the authoritative system of record.

The registry is fundamentally a compliance and audit instrument, not a trading venue. It assigns every registered loan a tamper-evident Mortgage Identification Number, timestamps every rights movement against a controllable logical clock, and computes the regulatory artifacts that flow from those movements: per-transfer timeliness fees, dual-variant annual reporting rates, member standing scores with standing bands, quality assurance reviews with weighted discrepancy scoring, monetary sanctions under segregation-of-duties controls, and system-of-record reconciliation runs that surface field-level disagreements between a member's servicing platform and the registry. Borrower-facing inquiry is supported so that a caller holding only a Mortgage Identification Number can learn the current investor and servicer of record.

The design goals are, in order: (1) every rights assertion on the registry is attributable to a member organization and, for sensitive operations, to a designated authorized signer of that member acting within a declared authority window; (2) every monetary and rate figure the registry publishes is computable from first principles by an external auditor, with pinned rounding rules; and (3) degraded states — suspended members, expired transfer matches, superseded reconciliation runs, rejected match reports — are represented explicitly in the state model rather than inferred, so that audits can reconstruct history without guesswork. All resources are mounted under the `/registry` prefix.

## 2. Global Specifications & System-Wide Principles

This section defines the cross-cutting contracts of the registry API: authentication and identity, the response envelope, pagination, the logical clock, identifier formats, monetary and rate precision, concurrency control, and validation ordering.

### 2.1. User and Role-Based Access Control

Every request to the registry must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the operational capacity in which the user acts. A request missing either header, or presenting a role string the registry does not recognize, is rejected with `ERR_MISSING_USER_CONTEXT` (HTTP 401). A request whose role is recognized but not authorized for the target endpoint is rejected with `ERR_ROLE_FORBIDDEN` (HTTP 403).

The registry recognizes exactly four roles, spelled as follows: `RegistryAdmin`, `MemberRep`, `QAAuditor`, and `BorrowerInquirer`.

- A `RegistryAdmin` is registry operator staff. When `X-User-Role` is `RegistryAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any resource's `id`.
- A `MemberRep` is an authorized representative acting as a member organization. When `X-User-Role` is `MemberRep`, `X-User-ID` is the `id` of the acting Member; ownership checks on any resource that references a Member — the loan being foreclosed, the transfer's sending side, the sanctioned member, the reconciliation run's owner — compare the resource's member foreign-key field to `X-User-ID`. This identity binding is what makes statements like "the acting member is the current servicer" mechanically checkable.
- A `QAAuditor` is a quality assurance auditor. When `X-User-Role` is `QAAuditor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server does, however, record it where a workflow requires accountability — as `created_by` on a QA review at creation and as `settled_by` on a QA review at settlement — because the segregation-of-duties rules compare those recorded identifiers against the acting auditor's `X-User-ID`.
- A `BorrowerInquirer` is a borrower inquiry service account. When `X-User-Role` is `BorrowerInquirer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity, and the role's write access is nil; it exists solely to resolve a Mortgage Identification Number to the current investor and servicer of record.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned in one page; it defaults to 10, accepts a minimum of 1, and refuses values above 100. The `offset` parameter skips a number of items from the head of the result set and defaults to 0. Unless a section states otherwise, every list endpoint returns its resources sorted by `created_at` in ascending order — the oldest record first — so that pagination is stable as new records arrive. The `meta` object of every list response carries `limit`, `offset`, `total_count`, and `has_more`, allowing clients to page exhaustively without probing.

### 2.4. The Logical Clock

All temporal judgments in the registry — lateness of a transfer report, expiry of a transfer match, the appeal window on a sanction, the effectiveness of a member termination — are evaluated against a **logical clock** maintained by the registry, never against wall-clock time. At server startup, before any administrative adjustment, the logical clock reads exactly 2026-09-01T00:00:00Z. A `RegistryAdmin` may reposition the clock by submitting a target instant in `to_iso8601`; the response echoes the new position as `current_utc`. Advancing the clock is itself an event: it re-evaluates every pending member termination whose effective moment has been reached, and every unanswered transfer match whose reporting window has now closed, applying the transitions described in §3. The clock never falls back to wall-clock time, even after idle periods.

### 2.5. Common Resource Properties and Identifier Discipline

Every primary resource — members, signers, loans, transfers, transfer matches, QA reviews, QA findings, annual reports, sanctions, reconciliation runs, and SOR exceptions — carries a common spine of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` and `updated_at` fields are ISO 8601 UTC timestamps with three fractional digits; `updated_at` refreshes on every mutation of the resource. The `version` field is an integer that starts at 1 on creation and increments by exactly 1 on every mutation, including system-driven cascades; it is the basis of the optimistic concurrency rules in §2.8.

Three identifiers deserve separate treatment because they are domain identifiers rather than surrogate keys. A member's `org_id` is a string of exactly seven digits assigned by the operator at registration, classified by `org_id_type` as one of `TAX_ID`, `CHARTER_NUMBER`, or `LEI`, and is globally unique across every member ever registered — including members that later reach `TERMINATED`; a reuse attempt is refused with `ERR_DUPLICATE_ORG_ID`. A loan's `min` is its eighteen-digit Mortgage Identification Number, minted at registration and unique across all loans (construction in §2.6). A transfer carries a client-supplied `idempotency_key` whose uniqueness is enforced only among transfers that are not in `REJECTED` status; resubmitting a key already held by a live transfer fails with `ERR_DUPLICATE_IDEMPOTENCY_KEY`, while reusing the key of a rejected transfer is permitted.

### 2.6. Mortgage Identification Number Construction

A loan's `min` concatenates three parts into exactly eighteen digits: the registering member's seven-digit `org_id`, then the member's ten-digit registration `serial` zero-padded on the left, then a single Luhn check digit computed over the first seventeen digits. The check digit is derived by walking the seventeen-digit payload from right to left, alternately weighting digits 2 and 1 (the rightmost digit takes weight 2), doubling where the weight is 2 and subtracting 9 whenever the doubled value exceeds 9, summing the results, and taking the digit that brings the total to the next multiple of ten — that is, ten minus the sum's remainder modulo ten, itself taken modulo ten. The serial that feeds this construction is per-member: each member's first successfully registered loan receives serial 1, each subsequent successful registration increments it, serials are never reused, and they survive member termination. The `min` therefore encodes provenance — any holder can read off which member registered the loan and which registration number it was for that member.

### 2.7. Precision, Rounding, and Derived Standing Bands

All monetary amounts are integers in cents — `loan_amount_cents` on a loan, `late_fee_cents` on a transfer, `total_amount_cents` on a sanction — and monetary arithmetic never produces fractional cents because every rounding step is pinned. Rates and scores are decimal numbers with pinned precision: `discrepancy_score` on a QA review, both reporting rates and `match_rate` on their respective artifacts, and `discrepancy_rate` on an annual report are each rounded half-up to four decimal places; `standing_score` on an annual report is rounded half-up to two decimal places. Where a calculation involves division by a possibly empty set, the registry defines a protective denominator of at least 1 rather than failing.

A member's derived `standing_band` is computed from `standing_score` with inclusive lower boundaries: a score of at least 80.00 yields `GOOD_STANDING`; a score of at least 60.00 but below 80.00 yields `PROBATION`; anything below 60.00 yields `DISENGAGEMENT_ELIGIBLE`. The boundary is exact — 80.00 is good standing, 79.99 is probation.

### 2.8. Optimistic Concurrency Control

Two write operations in the registry are guarded by optimistic concurrency, and only those two; endpoints not named here accept no version field.

Reporting a transfer requires the request to carry `expected_loan_version`, set to the value of the target loan's `version` the client last observed. If the loan's current `version` differs — because, for example, another writer has since confirmed a transfer on the same loan, moving its rights and advancing its version — the request is rejected with `ERR_STALE_LOAN_VERSION` (HTTP 412). This prevents a client from registering a rights movement against a view of the loan's current holders it has not re-read.

Filing a membership termination requires the request to carry `expected_member_version`, matched against the target member's current `version`. A mismatch — for instance because a suspend or reinstate has advanced the member's version since the operator last read it — is rejected with `ERR_STALE_MEMBER_VERSION` (HTTP 412).

### 2.9. Validation Order and Nested Path Discipline

Every request passes through a fixed priority cascade, and the cascade's ordering is observable: when several rules would each independently reject a request, the registry reports the failure from the earliest applicable tier. The tiers, in evaluation order, are:

1. **Shape.** Every required input field of the endpoint must be present and well-typed; a missing or malformed required field yields `ERR_INVALID_REQUEST` (HTTP 400). This check runs on all write endpoints before anything else.
2. **Authentication.** The user-context headers must be present and the role declared, else `ERR_MISSING_USER_CONTEXT`.
3. **Authorization.** The role must be listed for the endpoint, else `ERR_ROLE_FORBIDDEN`.
4. **Path existence.** Path-segment identifiers are validated strictly left to right — for example on a nested signer path, the member identifier is resolved before the signer identifier — and the first identifier that does not resolve produces the corresponding not-found error: `ERR_MEMBER_NOT_FOUND`, `ERR_SIGNER_NOT_FOUND`, `ERR_LOAN_NOT_FOUND`, `ERR_TRANSFER_NOT_FOUND`, `ERR_REVIEW_NOT_FOUND`, `ERR_FINDING_NOT_FOUND`, `ERR_SANCTION_NOT_FOUND`, `ERR_RUN_NOT_FOUND`, `ERR_EXCEPTION_NOT_FOUND`, or `ERR_REPORT_NOT_FOUND` (all HTTP 404). A nested path also enforces parentage: a signer identifier that exists but belongs to a different member than the path's member reports as `ERR_SIGNER_NOT_FOUND`, as if it did not exist in this context. The same applies to a finding addressed beneath the wrong review.
5. **Body reference existence.** Identifiers referenced in the request body — such as the `member_id` of a review subject, the `to_member_id` of a transfer, the `loan_id` of a finding, or the `transfer_id` filter context — must resolve, drawing from the same not-found family as tier 4, chosen by which reference failed.
6. **Member state.** Where an operation requires an `ACTIVE` member — registering a loan, receiving a transfer, submitting a reconciliation run, and signer-gated actions — a member in any other status triggers `ERR_MEMBER_NOT_ACTIVE` (HTTP 409).
7. **Resource state.** The target resource must be in the state its transition demands: a loan must be `ACTIVE` for a transfer, foreclosure, or satisfaction (`ERR_LOAN_NOT_ACTIVE`); a loan must be `FORECLOSING` to rescind (`ERR_LOAN_NOT_FORECLOSING`); a review must be `DRAFT` to accept findings or to issue (`ERR_REVIEW_NOT_DRAFT`); a review must be `FINDINGS_ISSUED` to settle or reopen (`ERR_REVIEW_NOT_ISSUED`); a transfer match must be `PENDING` to confirm or reject (`ERR_MATCH_NOT_PENDING`); a sanction must be `ASSESSED` to appeal or pay (`ERR_SANCTION_NOT_APPEALABLE`) and `APPEALED` to adjudicate (`ERR_SANCTION_NOT_APPEALED`); a reconciliation run must be `OPEN` for run-level operations (`ERR_RUN_NOT_OPEN`); and an SOR exception must be `OPEN` to resolve (`ERR_EXCEPTION_NOT_OPEN`). All are HTTP 409.
8. **Segregation of duties.** The auditor who created a review may not settle it, and the auditor who settled a review may not adjudicate the sanction that settlement produced; violations yield `ERR_SOD_SAME_ACTOR` (HTTP 403).
9. **Signer gate.** Foreclosure requires a named, currently authorized signer, else `ERR_SIGNER_NOT_AUTHORIZED` (HTTP 403).
10. **Foreclosure jurisdiction.** Assignment-out requirements for the loan's foreclosure mode are checked, yielding `ERR_ASSIGNMENT_OUT_REQUIRED` or `ERR_FORECLOSURE_MODE_FORBIDS_ASSIGN_OUT` (both HTTP 422).
11. **Clock discipline.** Dates supplied by the client must respect the logical clock: a registration's `closing_date` after the clock fails with `ERR_CLOSING_DATE_IN_FUTURE`; a transfer's `effective_date` after the clock fails with `ERR_FUTURE_EFFECTIVE_DATE`; an appeal filed beyond the appeal window fails with `ERR_APPEAL_WINDOW_EXPIRED`; and a termination request whose `effective_date` lies strictly in the past fails with `ERR_TERMINATION_DATE_PAST`. All are HTTP 422.
12. **Uniqueness and interval integrity.** Duplicate organizational identifiers, duplicate live idempotency keys, duplicate final annual reports for a member-year, malformed signer windows, and overlapping signer windows are rejected here with `ERR_DUPLICATE_ORG_ID`, `ERR_DUPLICATE_IDEMPOTENCY_KEY`, `ERR_DUPLICATE_ANNUAL_REPORT`, `ERR_INVALID_SIGNER_WINDOW`, or `ERR_SIGNER_WINDOW_OVERLAP` respectively.
13. **Transfer semantics.** The receiving member must be active and distinct from the current holder of the moved rights (`ERR_SELF_TRANSFER`), the mover must actually hold the rights being moved (`ERR_NOT_RIGHTS_HOLDER`), and a QA finding's loan must belong to the review's sample (`ERR_LOAN_NOT_IN_SAMPLE`).
14. **Termination gates.** A member holding rights on any loan, or holding unanswered transfer matches, cannot begin termination (`ERR_MEMBER_HOLDS_ACTIVE_RIGHTS`, `ERR_OPEN_TRANSFER_MATCHES`).
15. **Fiscal sanity of adjudication.** A reduction must actually reduce (`ERR_REDUCTION_NOT_LOWER`) and an abatement factor must lie within its allowed range (`ERR_INVALID_ABATEMENT_FACTOR`).
16. **Optimistic concurrency.** The version guards of §2.8 are evaluated **last**. A request that is both stale and, say, addressed to a loan in the wrong state reports the state error — not the stale-version error. Stale-version rejections are therefore a guarantee about otherwise-valid requests.

## 3. Business Logic & Workflows

### 3.1. Membership Admission and the Authorized Signer Roster

A `RegistryAdmin` admits an organization to the registry by registering it with its `legal_name`, its seven-digit `org_id`, the `org_id_type` classifying that identifier, and a `member_type` drawn from `ORIGINATOR`, `SERVICER`, `INVESTOR`, `SUBSERVICER`, or `CUSTODIAN`. A newly admitted member enters in `PENDING_ACTIVATION` status, with `termination_effective_date` null. Admission is deliberately decoupled from operability: a pending member can do nothing on the registry until activated.

Activation is gated on signing authority. A `RegistryAdmin` designates an **AuthorizedSigner** for a member by supplying the signer's `full_name`, contact `email`, the `effective_from` instant opening the authority window, a `role_scope` of `REGISTRATION`, `TRANSFER`, `FORECLOSURE`, or `ALL`, and optionally an `effective_until` instant closing it. The window is half-open: authority begins at `effective_from` inclusive and ends at `effective_until` exclusive, and a null `effective_until` means the authority is open-ended. When `effective_until` is supplied it must be strictly later than `effective_from`; otherwise designation fails with `ERR_INVALID_SIGNER_WINDOW`. A new signer enters in `ACTIVE` status immediately. One further integrity rule applies at designation time, and it is deliberately stricter than mere double-booking prevention: the new signer's half-open window must not intersect the window of any other signer of the same member, regardless of that other signer's status — two windows that merely touch at an endpoint, one closing exactly when the other opens, are clean and accepted; any positive-length overlap is rejected with `ERR_SIGNER_WINDOW_OVERLAP`. A member's signer roster is inspectable both in nested form beneath the member and in a flat cross-member listing that accepts `member_id` and `status` filters; individual signers are likewise retrievable either nested beneath their member or flat by identifier.

Moving a member from `PENDING_ACTIVATION` to `ACTIVE` requires that the member have at least one `ACTIVE` signer; an activation attempt against a signerless member is refused with `ERR_NO_AUTHORIZED_SIGNER`. The same requirement guards reinstatement. An `ACTIVE` member may be suspended by a `RegistryAdmin`, moving it to `SUSPENDED`, and later reinstated to `ACTIVE` — again only while at least one signer remains `ACTIVE`. Each of these lifecycle transitions refreshes the member's `updated_at` and advances its `version` by one.

Signer revocation is available to a `RegistryAdmin` while the signer is `ACTIVE`, flipping it to terminal `REVOKED`. Revocation carries one protective refusal: revoking the last `ACTIVE` signer of an `ACTIVE` member would strand an operational member with no capacity to act, so it is rejected with `ERR_NO_AUTHORIZED_SIGNER`. Members in `PENDING_ACTIVATION` or `SUSPENDED` may legitimately have zero active signers, and `TERMINATED` members always do (see §3.7).

### 3.2. Loan Registration at Closing

When a loan closes, a `MemberRep` acting for an `ACTIVE` member registers it with the original principal in `loan_amount_cents` (a positive integer), the two-letter uppercase US state code of the property in `property_state`, and the `closing_date` timestamp. The closing date may not lie in the future relative to the logical clock; a post-dated closing is refused with `ERR_CLOSING_DATE_IN_FUTURE`. Registration itself requires the registering member to be `ACTIVE` — a suspended or pending member cannot place loans on the registry.

On acceptance, the registry stamps the loan with its provenance and identity. The registering member's next `serial` is consumed (never reused, even if the member later terminates), the eighteen-digit `min` is minted per §2.6, `registering_member_id` records the acting member, and both `current_investor_id` and `current_servicer_id` are initialized to the registering member — at closing, the registrant holds both rights. The loan enters in `ACTIVE` status with `assigned_out_at` null.

Registration also fixes the loan's foreclosure posture for its entire registry lifetime. The derived `foreclosure_mode` is determined by `property_state`: loans secured by property in New York or California are classified `ASSIGN_OUT_REQUIRED`, reflecting jurisdictional requirements that foreclosure proceed on an assignment out of the registry; loans in every other state are `IN_REGISTRY_ALLOWED`. This derivation happens once, at registration, and never changes thereafter — a later transfer to a member domiciled elsewhere does not alter it.

Loans are listable with filters on `registering_member_id`, `current_investor_id`, `current_servicer_id`, and `status`, so members, auditors, administrators, and borrower-facing services can each reconstruct the slice of the registry they are entitled to see.

### 3.3. Foreclosure, Assignment-Out, Rescission, and Satisfaction

Foreclosure is the most tightly controlled operation on the registry. A `MemberRep` initiates foreclosure on a loan in `ACTIVE` status only if the acting member is the loan's current servicer or current investor — anyone else is turned away with `ERR_NOT_RIGHTS_HOLDER`. The request names a `signer_id`, which must resolve to an `ACTIVE` AuthorizedSigner of the acting member whose `role_scope` covers the action (`FORECLOSURE` or `ALL`) and whose authority window contains the current logical clock position; any failure on those points — missing signer, revoked signer, signer of a different member, insufficient scope, or a clock position outside the signer's window — is `ERR_SIGNER_NOT_AUTHORIZED`. A loan that is not `ACTIVE` cannot be foreclosed at all (`ERR_LOAN_NOT_ACTIVE`).

Jurisdiction then dictates the shape of the foreclosure. For an `ASSIGN_OUT_REQUIRED` loan the request must carry `assignment_out` set to true; omitting it or setting it false is refused with `ERR_ASSIGNMENT_OUT_REQUIRED`. When the flag is set, the loan does not pass through an in-registry foreclosure state at all: it transitions directly from `ACTIVE` to `INACTIVE_ASSIGNED_OUT`, its `assigned_out_at` is stamped with the current clock, and from that instant it leaves every future transfer and reconciliation inclusion set — the registry records the exit but no longer tracks the loan's rights. For an `IN_REGISTRY_ALLOWED` loan the opposite holds: `assignment_out` must be false or omitted entirely, and setting it true is refused with `ERR_FORECLOSURE_MODE_FORBIDS_ASSIGN_OUT`. An in-registry foreclosure moves the loan from `ACTIVE` to `FORECLOSING`, where it remains on the registry.

Foreclosure in the registry is not one-way. While a loan is `FORECLOSING`, its current servicer or investor may rescind, returning it to `ACTIVE`; a rescission attempted against a loan that is not `FORECLOSING` fails with `ERR_LOAN_NOT_FORECLOSING`, and one attempted by a non-holder fails with `ERR_NOT_RIGHTS_HOLDER`. The cycle `ACTIVE` → `FORECLOSING` → `ACTIVE` may repeat any number of times, and each re-entry into foreclosure re-runs the full signer gate — an authority window valid at the first foreclosure may have closed by the second.

Separately from foreclosure, a loan whose debt is paid off is satisfied: the current servicer or investor moves it from `ACTIVE` to terminal `INACTIVE_SATISFIED`, with the same not-active and not-rights-holder guards as foreclosure. A satisfied loan is excluded from reconciliation inclusion sets from that point on. Foreclosure, assignment-out, rescission, and satisfaction each advance the loan's `version` by one and refresh `updated_at`.

### 3.4. Transfer Reporting, Timeliness Fees, and the Match Protocol

Rights move on the registry by transfer report. A `MemberRep` reports a transfer by naming the `loan_id`, the receiving member `to_member_id`, a `transfer_type` of `BENEFICIAL`, `SERVICING`, or `BOTH`, the `effective_date` on which the transfer legally occurred, an `idempotency_key`, and the OCC guard `expected_loan_version` described in §2.8. The registry never trusts the client about the sending side: `from_member_id` is derived server-side from the loan's current holder of the right type being moved, and any client-supplied value for it is ignored.

The guards, beyond the generic cascade of §2.9, are these. The loan must be `ACTIVE` (`ERR_LOAN_NOT_ACTIVE`). The receiving member must exist and be `ACTIVE` (`ERR_MEMBER_NOT_ACTIVE`) and must differ from the current holder of the moved right or rights (`ERR_SELF_TRANSFER`). The acting member must hold what it purports to move: a `BOTH` transfer requires the mover to hold both the beneficial and servicing rights on the loan, while a single-type transfer requires holding that one right; overreach is refused with `ERR_NOT_RIGHTS_HOLDER`. The `effective_date` must not postdate the logical clock (`ERR_FUTURE_EFFECTIVE_DATE`). Because organizational identifiers are globally unique, a transfer between two registrations of the "same" organization cannot occur silently — a genuine self-move is exactly the `ERR_SELF_TRANSFER` case.

On acceptance the transfer is born in `CONFIRMED` status (there is no pending state for the transfer itself), the rights move immediately — `current_investor_id` takes the receiving member for `BENEFICIAL` or `BOTH`, `current_servicer_id` for `SERVICING` or `BOTH` — and the loan's `version` advances by one with `updated_at` refreshed. The stored transfer then carries two computed fields. `days_late` counts calendar days of lateness: the logical clock and the `effective_date` are each truncated to their calendar day, the difference in days is taken, the reporting grace window of ten days is subtracted, and the result is floored at zero. The boundary is exact: the tenth day after the effective date is the last on-time day, and the eleventh day is the first late day. `late_fee_cents` bills those late days marginally across three tiers — each late day is billed at exactly one tier's rate: days one through fifteen of lateness at 2,500 cents per day, days sixteen through thirty at 5,000 cents per day, and every day from the thirty-first onward at 10,000 cents per day. A transfer reported in time accrues zero fee but is still stored with its computed zeros.

Confirmation of the transfer simultaneously opens the **match protocol** on the sending side: the registry creates one TransferMatch, addressed to the from-side member as `reported_by_member_id`, stamped with the clock as `reported_at`, and set to `PENDING`. The protocol exists so the party losing rights can corroborate the report. The from-side member — and only that member — answers the match. Confirming the match requires the acting member to be the transfer's `from_member_id` (anyone else draws `ERR_NOT_MATCH_PARTY`, HTTP 403) and the match to still be `PENDING` (`ERR_MATCH_NOT_PENDING`); confirmation moves the match to `MATCHED`. If the logical clock passes the transfer's `effective_date` by more than the match window without an answer, the match flips to `EXPIRED` on the next timed evaluation, and expired matches count against the member in annual reporting (§3.6). A fourth status, `WAIVED`, exists in the enumeration for forward compatibility — it would describe a match whose reporting obligation was waived because both sides were the same organization — but no operation ever produces it, because self-transfers are rejected at creation.

The from-side member may instead reject the match. Rejection is deliberately asymmetric, and the asymmetry is the point: the transfer itself flips from `CONFIRMED` to `REJECTED`, the match flips to `EXPIRED`, but the rights movement on the loan is **not** rolled back — the loan keeps its new holders. What rejection does is escalate: if a QA review for the from-side member happens to be in `DRAFT` at that moment, the rejection appends one automatic finding to it, with `severity` `MAJOR` and `field_name` `CURRENT_SERVICER`, flagging the pair for quality assurance. A rejected transfer's `idempotency_key` is released, since uniqueness is enforced only among non-`REJECTED` transfers. Transfers are listable with `loan_id`, `from_member_id`, `to_member_id`, and `status` filters; matches are listable with `transfer_id`, `reported_by_member_id`, and `status` filters.

### 3.5. Quality Assurance Reviews, Findings, and Sanctions

A `QAAuditor` opens a QA review against a member by supplying the subject `member_id` and a review period bounded by `period_start` and `period_end`. The period is inclusive at both ends, and `period_end` must not precede `period_start`; an inverted period is refused with `ERR_INVALID_PERIOD`. The review is born in `DRAFT`, and the creating auditor's `X-User-ID` is recorded as `created_by` — this attribution is load-bearing at settlement time.

While `DRAFT`, the review accumulates findings. Each finding references a `loan_id` that must belong to the review's sample — defined as every loan ever registered by the reviewed member, in any status, ordered by registration serial ascending — and naming a loan outside that sample is refused with `ERR_LOAN_NOT_IN_SAMPLE`. The auditor records which loan attribute was wrong via `field_name` (one of `MIN`, `CURRENT_SERVICER`, `CURRENT_INVESTOR`, `PROPERTY_STATE`, or `CLOSING_DATE`), the `expected_value` the field should hold, the `actual_value` found on the registry, and a `severity` of `CRITICAL`, `MAJOR`, or `MINOR`. Findings can be listed nested beneath their review with `loan_id` and `severity` filters, across all reviews with `review_id`, `loan_id`, and `severity` filters, and retrieved individually either nested beneath the review or flat by identifier.

Issuing the review — moving it from `DRAFT` to `FINDINGS_ISSUED` — requires at least one finding (`ERR_NO_FINDINGS`) and freezes the review's two computed measures. `sample_size` is the count of loans in the sample at issue time. `discrepancy_score` is a weighted discrepancy rate: the findings are tallied by severity, with each `CRITICAL` finding contributing a full weight of 1.0, each `MAJOR` a half, and each `MINOR` a fifth; the weighted total is divided by the sample size and rounded half-up to four decimal places. Because a review cannot be issued with zero findings, and findings require sampled loans, the zero-sample division case is unreachable in practice. A review that needs correction can be reopened — `FINDINGS_ISSUED` back to `DRAFT` — retaining its findings; the cycle may repeat, and each re-issue recomputes and refreezes `sample_size` and `discrepancy_score` afresh. Issue and reopen each advance the review's `version`.

Settlement converts a review into money. A `QAAuditor` settles a `FINDINGS_ISSUED` review, optionally supplying an `abatement_factor` between 0 and 1 inclusive — omitted means 1.0, no abatement; anything outside the range fails with `ERR_INVALID_ABATEMENT_FACTOR`. Segregation of duties applies: the settling auditor's `X-User-ID` must differ from the review's `created_by`, else `ERR_SOD_SAME_ACTOR`. On settlement the review moves to `SETTLED`, `settled_by` records the settler, `settled_at` stamps the clock, and exactly one Sanction is created in `ASSESSED` status against the reviewed member. The sanction's math is pinned to the cent. A repeat-offender multiplier is determined from the member's sanction history: if the member has any prior sanction in `UPHELD`, `REDUCED`, or `PAID` status — proven priors — the multiplier is 1.5; otherwise it is 1.0. Then each finding on the review, taken in creation order, contributes one line whose base amount depends on severity — 500,000 cents for `CRITICAL`, 100,000 cents for `MAJOR`, 25,005 cents for `MINOR` — multiplied by the repeat multiplier and by the abatement factor, and **each line is rounded half-up to whole cents individually before any summation**. The sanction's `total_amount_cents` is the sum of those per-line rounded amounts, and `line_count` is the number of findings assessed. The round-then-sum order is a deliberate audit decision; summing raw products first and rounding once would yield different totals (three minor findings under repeat-offender abatement of 0.9 produce 33,756.75 cents per line — rounded per line and summed that is 101,271 cents, versus 101,270 under sum-then-round), and only the per-line order is compliant. When the settled review's sanction total is positive and the member's latest annual report places it in `DISENGAGEMENT_ELIGIBLE`, the registry takes no automatic action against the member — disengagement is operator policy, executed through the termination workflow, never automated.

The sanctioned member — and only that member, enforced by `ERR_NOT_SANCTION_PARTY` — may respond to an `ASSESSED` sanction in either of two ways. It may simply pay, moving the sanction to `PAID`. Or it may appeal within the appeal window: an appeal filed no more than thirty days after the sanction's `created_at` moves the sanction to `APPEALED`; a later filing is refused with `ERR_APPEAL_WINDOW_EXPIRED`, and an appeal against a sanction no longer `ASSESSED` is refused with `ERR_SANCTION_NOT_APPEALABLE`. Adjudication of an `APPEALED` sanction belongs to a `QAAuditor` — but, under the same segregation-of-duties principle, not the auditor who settled the parent review: the adjudicator's `X-User-ID` must differ from the review's `settled_by`, else `ERR_SOD_SAME_ACTOR`, and adjudication against a sanction not `APPEALED` fails with `ERR_SANCTION_NOT_APPEALED`. The adjudicator submits a `decision` of `UPHELD`, `REDUCED`, or `VACATED`. Upholding leaves the assessment untouched. Reducing requires `reduced_total_cents` strictly below the current `total_amount_cents` — anything greater than or equal is refused with `ERR_REDUCTION_NOT_LOWER` — and rewrites the total to the reduced figure. Vacating zeroes the total, a compensating write that keeps the sanction ledger consistent rather than deleting the record. Sanctions are listable with `member_id`, `review_id`, and `status` filters.

### 3.6. Annual Reporting: Timeliness Rates, Standing Scores, and Regeneration

Once per calendar year per member, a `RegistryAdmin` generates the member's annual report by supplying `report_year`. At generation the registry computes and stores six figures. `reporting_rate` is the count-based on-time transfer rate: among all `CONFIRMED` transfers whose `from_member_id` is the member and whose `effective_date` falls within the report's calendar year (from the first instant of January 1 through the last millisecond of December 31, UTC), the share whose `days_late` is zero — the count of on-time transfers divided by the count of all such transfers, rounded half-up to four decimal places; when the member had no confirmed transfers in the year at all, the rate is vacuously 1.0. `reporting_rate_amount_weighted` is the investor-materiality view of the same question, published alongside: the sum of `loan_amount_cents` over the on-time transferred loans divided by the sum over all transferred loans in the set, rounded half-up to four decimal places, again 1.0 when there were no confirmed transfers. The two variants deliberately weigh the same behavior differently — each transfer counts equally in the count-based rate, while a late transfer of a large loan drags the amount-weighted rate further; identical inputs can therefore legitimately yield different published rates (two on-time transfers out of three give 0.6667 by count but 0.5000 by amount when the late transfer carried the largest loan). `REJECTED` transfers never enter either computation.

`discrepancy_rate` imports the member's audit posture: it is the `discrepancy_score` of the member's latest `SETTLED` QA review, where "latest" is decided by `settled_at`, ties broken by earlier `created_at` first; with no settled review at all, it is 0.0. `open_exceptions` counts the member's TransferMatch rows sitting in `PENDING` or `EXPIRED` at generation time. These feed `standing_score`, which starts from a perfect 100 and subtracts three penalties: sixty points scaled by the shortfall of the count-based reporting rate below perfect timeliness, forty points scaled by the member's discrepancy rate (capped at full weight — a discrepancy rate above 1 cannot penalize beyond the forty points), and two points per open exception with at most ten exceptions penalized. The result is clamped into the range 0 to 100 and rounded half-up to two decimal places, and `standing_band` derives from it per §2.7. The report is born directly in `FINAL` status.

Exactly one `FINAL` report may exist for a given member and year: generating when one already exists fails with `ERR_DUPLICATE_ANNUAL_REPORT`. Regeneration is nonetheless supported for corrections: submitting with `force_regenerate` set to true first flips the prior `FINAL` report for that member-year to `VOID` and then creates the new report in `FINAL`, preserving the invariant of exactly one live report per member-year as a compensating pair of writes rather than an overwrite. Reports are listable with `member_id`, `report_year`, and `status` filters.

### 3.7. Membership Termination and Portfolio Deactivation

Termination is a two-phase exit with a built-in cooling-off window. A `RegistryAdmin` files a termination request against a member, supplying the `effective_date` at which termination takes effect and the OCC guard `expected_member_version` (§2.8). Two gates protect the request. First, the member must hold no rights anywhere on the registry: no loan in any status may name the member as `current_investor_id` or `current_servicer_id`, else `ERR_MEMBER_HOLDS_ACTIVE_RIGHTS`. Second, the member must have no TransferMatch rows in `PENDING` — unanswered match obligations must be resolved or expired first, else `ERR_OPEN_TRANSFER_MATCHES`. The effective date must not lie strictly in the past relative to the logical clock (`ERR_TERMINATION_DATE_PAST`); an effective date exactly equal to the clock is the immediate-termination case. The accepted request sets the member's `termination_effective_date` and moves it from `ACTIVE` to `TERMINATION_PENDING` — or directly to `TERMINATED` when the effective date is not after the clock, immediate termination included — and in either case advances the member's `version`.

Filing termination also deactivates the member's dormant portfolio in the same motion: every loan the member originally registered (`registering_member_id` equal to the terminating member) that is still `ACTIVE` cascades to `INACTIVE_TERMINATED`. The cascade propagates one hop further into reconciliation: each loan so flipped generates a `REGISTRY_ONLY` SOR exception on the member's currently `OPEN` reconciliation run, if one exists. Termination never completes a run, though — even if those new exceptions somehow left the run with zero open exceptions, the run stays `OPEN` until its exceptions are resolved through the normal channel.

Finalization is system-driven: when the logical clock reaches `termination_effective_date`, the next timed evaluation after the clock advance moves the member from `TERMINATION_PENDING` to terminal `TERMINATED`, and in the same motion every still-`ACTIVE` AuthorizedSigner of the member flips to `REVOKED`. A terminated member's `org_id` remains reserved forever (§2.5), and its historical loans, transfers, and reports remain queryable.

### 3.8. System-of-Record Reconciliation and Exception Resolution

Members reconcile their servicing platforms against the registry by submitting a reconciliation run. A `MemberRep` of an `ACTIVE` member submits a batch of platform `records`, each record naming a loan by its `min` together with the platform's view of that loan's servicer and investor as `servicer_org_id` and `investor_org_id`. The run's `member_id` is the acting member. Submission is superseding: any prior `OPEN` run for the same member immediately flips to `CANCELLED`, and that older run's still-open exceptions are marked `RESOLVED` with their `detail` set to note they were superseded, so no orphan open exceptions survive the change of batch.

The new run is born `OPEN` and its diff is computed at once, processing the submitted records in submission order. A record whose `min` is unknown to the registry counts toward `platform_only_count` and yields a `PLATFORM_ONLY` exception; a record whose `min` belongs to a loan that has left the registry — any of the `INACTIVE_ASSIGNED_OUT`, `INACTIVE_TERMINATED`, or `INACTIVE_SATISFIED` statuses — is treated the same way, as platform-only, since the registry no longer tracks the loan. A record whose `min` resolves to a live loan but whose `servicer_org_id` disagrees with the organizational identifier of the loan's `current_servicer_id`, or whose `investor_org_id` disagrees with that of `current_investor_id`, counts toward `field_mismatch_count` and yields a `FIELD_MISMATCH` exception. Every other record counts toward `matched_count`. The registry-side direction is then swept: every loan in `ACTIVE` or `FORECLOSING` status where the member is current servicer or current investor, and whose `min` appears in no submitted record, counts toward `registry_only_count` and yields a `REGISTRY_ONLY` exception. The run stores `total_records` (the number of submitted records), the four diff counts, and `match_rate` — the matched count divided by the sum of total records and registry-only count, with the denominator protected to at least 1, rounded half-up to four decimal places. Each generated exception is born `OPEN`, carries the run's identifier as `run_id`, the offending loan's identifier as `loan_id` (null only for `PLATFORM_ONLY` exceptions, where no registry loan exists), an `exception_type`, and a human-readable `detail`. If the diff produced no exceptions at all, the run skips its open life entirely and completes immediately to `COMPLETED`.

Exceptions are worked down one at a time. A `MemberRep` resolves an `OPEN` exception — optionally annotating it with a `resolution_note` — moving it to `RESOLVED`; resolving one not `OPEN` fails with `ERR_EXCEPTION_NOT_OPEN`. The run's state is derived from its children: when the resolution of an exception leaves its parent run with zero remaining `OPEN` exceptions, the run transitions from `OPEN` to `COMPLETED` automatically. Runs are listable with `member_id` and `status` filters; exceptions with `run_id`, `loan_id`, `exception_type`, and `status` filters.

### 3.9. Borrower Inquiry

The registry's borrower-facing surface is deliberately narrow. A `BorrowerInquirer` presents a Mortgage Identification Number and receives, for that `min`, the loan's `loan_id`, its `loan_status`, and the identities of the current holders of record: `current_investor_id` with `current_investor_org_id`, and `current_servicer_id` with `current_servicer_org_id`. An unknown `min` is reported as `ERR_LOAN_NOT_FOUND`. The borrower-inquiry role may also read loan listings and individual loans, but nothing else; it cannot enumerate members, transfers, reviews, or any other registry internals.

## 4. Endpoint Definitions

Operations that create a new resource — registering a member or loan, designating a signer, reporting a transfer, opening a review, recording a finding, generating an annual report, submitting a reconciliation run — return `201 Created`. Operations that act on an existing resource, including all state transitions, clock adjustments, match answers, adjudications, payments, and resolutions, return `200 OK`. Readers should reconstruct each endpoint's full request and response contract from the §3 narratives; this table is a routing and authorization summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/registry/_clock/set_current_utc` | Set the registry logical clock and evaluate due timed transitions | RegistryAdmin |
| POST | `/registry/members` | Register a new member organization | RegistryAdmin |
| GET | `/registry/members` | List members with optional `status` and `member_type` filters | RegistryAdmin, MemberRep, QAAuditor |
| GET | `/registry/members/{memberId}` | Get one member | RegistryAdmin, MemberRep, QAAuditor |
| POST | `/registry/members/{memberId}/activate` | Activate a pending member (requires an active signer) | RegistryAdmin |
| POST | `/registry/members/{memberId}/suspend` | Suspend an active member | RegistryAdmin |
| POST | `/registry/members/{memberId}/reinstate` | Reinstate a suspended member | RegistryAdmin |
| POST | `/registry/members/{memberId}/terminate` | File a membership termination request (OCC-guarded) | RegistryAdmin |
| POST | `/registry/members/{memberId}/signers` | Designate an authorized signer for a member | RegistryAdmin |
| GET | `/registry/members/{memberId}/signers` | List a member's signers | RegistryAdmin, QAAuditor |
| GET | `/registry/members/{memberId}/signers/{signerId}` | Get one signer of a member (nested) | RegistryAdmin, QAAuditor |
| GET | `/registry/signers/{signerId}` | Get one signer by id (flat) | RegistryAdmin, QAAuditor |
| GET | `/registry/signers` | List signers across members | RegistryAdmin, QAAuditor |
| POST | `/registry/members/{memberId}/signers/{signerId}/revoke` | Revoke a signer | RegistryAdmin |
| POST | `/registry/loans` | Register a loan at closing and mint its MIN | MemberRep |
| GET | `/registry/loans` | List loans with holder and status filters | RegistryAdmin, MemberRep, QAAuditor, BorrowerInquirer |
| GET | `/registry/loans/{loanId}` | Get one loan | RegistryAdmin, MemberRep, QAAuditor, BorrowerInquirer |
| POST | `/registry/loans/{loanId}/foreclose` | Enter foreclosure, or assign out where jurisdiction requires | MemberRep |
| POST | `/registry/loans/{loanId}/rescind-foreclosure` | Rescind an in-registry foreclosure | MemberRep |
| POST | `/registry/loans/{loanId}/satisfy` | Mark a loan satisfied and off the registry | MemberRep |
| POST | `/registry/transfers` | Report a transfer of beneficial and/or servicing rights (OCC-guarded) | MemberRep |
| GET | `/registry/transfers` | List transfers with loan and party filters | RegistryAdmin, MemberRep, QAAuditor |
| GET | `/registry/transfers/{transferId}` | Get one transfer | RegistryAdmin, MemberRep, QAAuditor |
| POST | `/registry/transfers/{transferId}/match-confirm` | From-side member confirms the transfer match | MemberRep |
| POST | `/registry/transfers/{transferId}/reject-match` | From-side member rejects the match, escalating to QA | MemberRep |
| GET | `/registry/transfer-matches` | List transfer matches | RegistryAdmin, MemberRep, QAAuditor |
| GET | `/registry/transfer-matches/{matchId}` | Get one transfer match | RegistryAdmin, MemberRep, QAAuditor |
| GET | `/registry/borrower-inquiries/{min}` | Resolve a MIN to the current investor and servicer of record | BorrowerInquirer |
| POST | `/registry/qa-reviews` | Open a QA review for a member over a period | QAAuditor |
| GET | `/registry/qa-reviews` | List QA reviews | RegistryAdmin, QAAuditor |
| GET | `/registry/qa-reviews/{reviewId}` | Get one QA review | RegistryAdmin, QAAuditor |
| POST | `/registry/qa-reviews/{reviewId}/findings` | Record a discrepancy finding against a sampled loan | QAAuditor |
| GET | `/registry/qa-reviews/{reviewId}/findings` | List findings of a review | RegistryAdmin, QAAuditor |
| GET | `/registry/qa-reviews/{reviewId}/findings/{findingId}` | Get one finding of a review (nested) | RegistryAdmin, QAAuditor |
| GET | `/registry/qa-findings/{findingId}` | Get one QA finding by id (flat) | RegistryAdmin, QAAuditor |
| GET | `/registry/qa-findings` | List QA findings across reviews | RegistryAdmin, QAAuditor |
| POST | `/registry/qa-reviews/{reviewId}/issue` | Issue findings, freezing sample size and discrepancy score | QAAuditor |
| POST | `/registry/qa-reviews/{reviewId}/reopen` | Reopen an issued review for corrective re-review | QAAuditor |
| POST | `/registry/qa-reviews/{reviewId}/settle` | Settle a review and create its sanction (segregation of duties) | QAAuditor |
| GET | `/registry/sanctions` | List sanctions | RegistryAdmin, MemberRep, QAAuditor |
| GET | `/registry/sanctions/{sanctionId}` | Get one sanction | RegistryAdmin, MemberRep, QAAuditor |
| POST | `/registry/sanctions/{sanctionId}/appeal` | Sanctioned member appeals within the appeal window | MemberRep |
| POST | `/registry/sanctions/{sanctionId}/adjudicate` | Adjudicate an appealed sanction (segregation of duties) | QAAuditor |
| POST | `/registry/sanctions/{sanctionId}/pay` | Sanctioned member pays an assessed sanction | MemberRep |
| POST | `/registry/members/{memberId}/annual-reports` | Generate (or force-regenerate) the annual report for a member and year | RegistryAdmin |
| GET | `/registry/annual-reports` | List annual reports | RegistryAdmin, MemberRep, QAAuditor |
| GET | `/registry/annual-reports/{reportId}` | Get one annual report | RegistryAdmin, MemberRep, QAAuditor |
| POST | `/registry/sor-reconciliation-runs` | Submit servicing-platform records for reconciliation | MemberRep |
| GET | `/registry/sor-reconciliation-runs` | List reconciliation runs | RegistryAdmin, MemberRep, QAAuditor |
| GET | `/registry/sor-reconciliation-runs/{runId}` | Get one reconciliation run | RegistryAdmin, MemberRep, QAAuditor |
| GET | `/registry/sor-exceptions` | List SOR exceptions | RegistryAdmin, MemberRep, QAAuditor |
| GET | `/registry/sor-exceptions/{exceptionId}` | Get one SOR exception | RegistryAdmin, MemberRep, QAAuditor |
| POST | `/registry/sor-exceptions/{exceptionId}/resolve` | Resolve one open exception, completing the run when the last one closes | MemberRep |

## 5. Error Code Catalogue

Trigger conditions for each error live in the §2 and §3 narratives where the guarded workflow is described; this catalogue is a lookup of identifier to HTTP status only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_USER_CONTEXT` | 401 Unauthorized |
| `ERR_ROLE_FORBIDDEN` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_MEMBER_NOT_FOUND` | 404 Not Found |
| `ERR_SIGNER_NOT_FOUND` | 404 Not Found |
| `ERR_LOAN_NOT_FOUND` | 404 Not Found |
| `ERR_TRANSFER_NOT_FOUND` | 404 Not Found |
| `ERR_REVIEW_NOT_FOUND` | 404 Not Found |
| `ERR_FINDING_NOT_FOUND` | 404 Not Found |
| `ERR_SANCTION_NOT_FOUND` | 404 Not Found |
| `ERR_RUN_NOT_FOUND` | 404 Not Found |
| `ERR_EXCEPTION_NOT_FOUND` | 404 Not Found |
| `ERR_REPORT_NOT_FOUND` | 404 Not Found |
| `ERR_MEMBER_NOT_ACTIVE` | 409 Conflict |
| `ERR_NO_AUTHORIZED_SIGNER` | 409 Conflict |
| `ERR_LOAN_NOT_ACTIVE` | 409 Conflict |
| `ERR_LOAN_NOT_FORECLOSING` | 409 Conflict |
| `ERR_MATCH_NOT_PENDING` | 409 Conflict |
| `ERR_REVIEW_NOT_DRAFT` | 409 Conflict |
| `ERR_REVIEW_NOT_ISSUED` | 409 Conflict |
| `ERR_NO_FINDINGS` | 409 Conflict |
| `ERR_SANCTION_NOT_APPEALABLE` | 409 Conflict |
| `ERR_SANCTION_NOT_APPEALED` | 409 Conflict |
| `ERR_RUN_NOT_OPEN` | 409 Conflict |
| `ERR_EXCEPTION_NOT_OPEN` | 409 Conflict |
| `ERR_MEMBER_HOLDS_ACTIVE_RIGHTS` | 409 Conflict |
| `ERR_OPEN_TRANSFER_MATCHES` | 409 Conflict |
| `ERR_DUPLICATE_ORG_ID` | 409 Conflict |
| `ERR_DUPLICATE_IDEMPOTENCY_KEY` | 409 Conflict |
| `ERR_DUPLICATE_ANNUAL_REPORT` | 409 Conflict |
| `ERR_INVALID_SIGNER_WINDOW` | 422 Unprocessable Entity |
| `ERR_SIGNER_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_CLOSING_DATE_IN_FUTURE` | 422 Unprocessable Entity |
| `ERR_FUTURE_EFFECTIVE_DATE` | 422 Unprocessable Entity |
| `ERR_TERMINATION_DATE_PAST` | 422 Unprocessable Entity |
| `ERR_APPEAL_WINDOW_EXPIRED` | 422 Unprocessable Entity |
| `ERR_INVALID_PERIOD` | 422 Unprocessable Entity |
| `ERR_INVALID_ABATEMENT_FACTOR` | 422 Unprocessable Entity |
| `ERR_REDUCTION_NOT_LOWER` | 422 Unprocessable Entity |
| `ERR_SELF_TRANSFER` | 422 Unprocessable Entity |
| `ERR_NOT_RIGHTS_HOLDER` | 409 Conflict |
| `ERR_NOT_MATCH_PARTY` | 403 Forbidden |
| `ERR_NOT_SANCTION_PARTY` | 403 Forbidden |
| `ERR_SIGNER_NOT_AUTHORIZED` | 403 Forbidden |
| `ERR_SOD_SAME_ACTOR` | 403 Forbidden |
| `ERR_ASSIGNMENT_OUT_REQUIRED` | 422 Unprocessable Entity |
| `ERR_FORECLOSURE_MODE_FORBIDS_ASSIGN_OUT` | 422 Unprocessable Entity |
| `ERR_LOAN_NOT_IN_SAMPLE` | 422 Unprocessable Entity |
| `ERR_STALE_LOAN_VERSION` | 412 Precondition Failed |
| `ERR_STALE_MEMBER_VERSION` | 412 Precondition Failed |
