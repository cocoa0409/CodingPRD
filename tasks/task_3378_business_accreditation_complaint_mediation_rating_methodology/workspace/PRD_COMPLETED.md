# Business Accreditation, Complaint Mediation & Rating Methodology API — Product Requirements Document

## 1. Introduction

Local bureaus across the country perform three intertwined public-interest functions: they accredit businesses that meet published standards for advertising honesty, complaint history, and licensing; they mediate disputes between consumers and businesses; and they publish letter-grade ratings that consumers consult before they buy. This document specifies the Business Accreditation, Complaint Mediation & Rating Methodology API, the system of record for that work.

The API covers the full lifecycle of the bureau's mandate. Bureaus are configured with exclusive state territories and optional local dues fees; consumers are registered; businesses are onboarded with automatic territory assignment and size classification. Accreditation proceeds through an application with a three-part standards checklist, a dues invoice with annual-prepaid and quarterly billing plans, and a reapplication path after denial. Complaints move from intake through forwarding, business response, consumer rebuttal, and verdict, escalating to mediation and then binding arbitration when direct resolution fails. A dual-variant rating methodology — provisional for live preview, published for the public record — converts complaint volume, resolution behavior, business age, advertising findings, and scam patterns into a score and a letter grade, with a formal dispute and appeal process. Because accreditation standing reacts to published ratings, each bureau runs a daily close against a simulated logical clock that expires response windows, voids lapsed invoices, and suspends or revokes accreditation.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, structural contracts, and cross-cutting principles that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting party, and `X-User-Role`, declaring the capacity in which they act. The system recognizes exactly four roles, spelled exactly as follows: `BureauAdmin`, `StandardsReviewer`, `BusinessRep`, and `Consumer`. A request missing either header, or carrying a role value outside this set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not listed among an operation's authorized roles is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

Role identity works differently per role. When `X-User-Role` is `BureauAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the same is true when `X-User-Role` is `StandardsReviewer`. The server may record such identifiers — for example, as the `mediator_id` assigned to a mediation session — but never compares them against any entity's `id`. When `X-User-Role` is `BusinessRep`, `X-User-ID` is the `id` of the acting Business; ownership checks on any resource that references a Business compare the resource's business field to `X-User-ID`. When `X-User-Role` is `Consumer`, `X-User-ID` is the `id` of the acting Consumer; ownership checks compare the filing consumer's `id` — the `consumer_id` on creation payloads, or the complaint's filer on response and mediation actions — to `X-User-ID`. An entity-backed role acting on a resource it does not own is rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403). Ownership is enforced on exactly these operations: creating an accreditation application, submitting an application, posting a payment ledger entry, filing a complaint, appending a complaint response, answering a mediation offer, filing a rating dispute, and filing a scam report.

`BureauAdmin` is the bureau operations role: bureau and territory configuration, consumer registration, business onboarding, complaint forwarding and reopening, mediation and arbitration scheduling and decisions, rating computation and publication, appeal rulings, scam-report publication, refunds, the daily close, and control of the logical clock. `StandardsReviewer` owns accreditation decisions and advertising-review conclusions — a duty segregated from bureau operations — and shares with `BureauAdmin` the ability to open an advertising review. `BusinessRep` and `Consumer` act only on their own resources, as described above. Read access is broad: every role can read businesses and complaints, list a complaint's mediation and arbitration cases, read the business-scoped scam-report listing, and read the scam-pattern publication; the business-scoped listings of applications, dues invoices, rating snapshots, rating disputes, and advertising reviews are open to `BureauAdmin`, `StandardsReviewer`, and `BusinessRep`.

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

List endpoints paginate through two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10 when omitted, accepts a minimum of 1, and is bounded above at 100. A `limit` outside that range is clamped to the nearest bound rather than rejected, and a negative `offset` is likewise clamped up to 0; a `limit` or `offset` that is not an integer at all is rejected with `ERR_INVALID_REQUEST`. The `offset` parameter skips that many items from the start of the result set and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order, with ties on `created_at` broken in favor of the resource created earlier. The `meta` object of every list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and the Daily Close

The server runs on a simulated logical clock rather than wall-clock time. At startup, before any clock operation has been issued, the logical clock reads exactly 2026-09-01T00:00:00Z, and it never falls back to the host's wall clock. Every occurrence of "now" in this document refers to the logical clock, and every duration, deadline, window, and cooling period is measured against it.

An admin-only test-driving capability, restricted to `BureauAdmin`, sets the logical clock to a supplied `to_iso8601` instant in ISO 8601; the clock may move forward or backward, and the response reports the new `current_utc` — rendered at second precision when the instant lands on a whole second and with three fractional digits otherwise. Setting the clock mutates no entity: time-driven state changes never fire on their own, no matter how far the clock moves.

All scheduled transitions are delivered by the bureau's daily close, a `BureauAdmin` operation that advances one bureau's operations day. Each run increments the bureau's `ops_day_index` by exactly 1 and then performs four sweeps across the bureau's territory: complaints whose response window has lapsed are closed as unanswered (§3.4); mediation offers past their acceptance deadline expire (§3.5); invoices past their due date are marked overdue, and invoices more than 15 days past due are voided, which expires the linked accreditation application (§3.3); and the suspension scan evaluates every accredited or suspended business in the territory against its latest published rating (§3.7). Wherever a sweep changes a business's complaint counters, advertising status, or scam counts, the business's provisional rating is regenerated as part of the same run.

### 2.5. Common Resource Properties

Every resource in the system — Bureau, Consumer, Business, AccreditationApplication, DuesInvoice, Complaint, MediationCase, ArbitrationCase, RatingSnapshot, RatingDispute, AdvertisingReview, and ScamReport — carries four system-managed properties:

- `id` (string): a server-minted UUID with no type prefix, assigned at creation.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that starts at 1 at creation and increments by 1 on every mutation of the resource. Clients never write `version` directly; the only write-path use of a version value is the optimistic-concurrency field described in §2.8.

Mutations that cascade across resources — for example, a complaint verdict that recomputes the business's counters — update each touched resource's `updated_at` and `version` according to the side effects stated in §3.

### 2.6. Nested Resource Retrieval and Existence Checks

The API is mounted at the server root with no URL prefix. Several operations address a child resource through its parent — an application within a business, a mediation case within a complaint, a dispute within a business. For every such path, identifiers are validated strictly left to right: the request is rejected at the first path identifier that names no existing resource, and a nested resource must belong to the parent named in its path. Each missing resource yields its own not-found error: `ERR_BUREAU_NOT_FOUND`, `ERR_BUSINESS_NOT_FOUND`, `ERR_CONSUMER_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, `ERR_MEDIATION_NOT_FOUND`, `ERR_ARBITRATION_NOT_FOUND`, `ERR_SNAPSHOT_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`, `ERR_AD_REVIEW_NOT_FOUND`, or `ERR_SCAM_REPORT_NOT_FOUND`, all HTTP 404. Identifiers supplied in a request body are checked with the same rigor: a `business_id`, `consumer_id`, `application_id`, or `snapshot_id` that names nothing at all is rejected with the matching not-found error rather than a generic validation failure.

### 2.7. Validation Cascade and Priority Order

When a single request would violate several rules, the checks are evaluated in a fixed priority order and the earliest failing check produces the response — an authentication failure, for instance, is never masked by a later business rule. The cascade runs as follows:

1. **Authentication.** The `X-User-Role` and `X-User-ID` headers must be present and the role must be one of the four known roles (`ERR_UNAUTHENTICATED`, 401).
2. **Role authorization.** The role must be listed among the endpoint's authorized roles (`ERR_UNAUTHORIZED`, 403).
3. **Entity-backed ownership.** A `BusinessRep`'s `X-User-ID` must equal the target business's `id`; a `Consumer`'s `X-User-ID` must equal the filing consumer's `id` (`ERR_FORBIDDEN_OWNERSHIP`, 403). On the operations gated by a request-body discriminator — the `kind` of a complaint response or of a ledger entry, and the `party` of a mediation answer — the request-body schema rules of priority 5 and the role binding the discriminator selects (§3.3, §3.4, §3.5) are evaluated as the body is read, ahead of this ownership check.
4. **Existence.** Every path identifier must exist, validated left to right, and nested resources must belong to the path parent (the 404 family of §2.6).
5. **Request-body schema.** Required fields must be present — an explicit null counts as missing — and a required string field must be a non-empty string; enum values must be in range, and integer bounds must hold — `employee_count` at least 1, `amount_cents` at least 1, `local_dues_fee_cents` at least 0; a `DENY` decision must carry `denial_reason`; an `APPROVE` decision must carry all three checklist results as `PASS`; a deceptive advertising conclusion must carry `regulator_name`; a session or hearing end must be strictly after its start; a consumer's `email` must be unique (`ERR_INVALID_REQUEST`, 400).
6. **Optimistic concurrency.** Where an OCC field is defined, it must match the parent's current `version` (`ERR_STALE_VERSION`, 412 — see §2.8).
7. **State-machine from-state.** The target resource must be in a valid from-state for the requested transition — submit needs `DRAFT`, decision needs `SUBMITTED`, reapplication needs `DENIED`; forward needs `RECEIVED`; a business response needs `FORWARDED` or `CONSUMER_REBUTTED`; a consumer verdict or rebuttal needs `RESPONSE_RECEIVED`; reopen needs `RESOLVED` or `UNANSWERED`; a mediation offer needs `UNRESOLVED`; arbitration needs `MEDIATION_FAILED`; and the invoice, mediation, arbitration, dispute, advertising-review, and scam-report machines carry their own from-state rules (`ERR_APPLICATION_INVALID_STATE`, `ERR_COMPLAINT_INVALID_STATE`, `ERR_INVOICE_INVALID_STATE`, `ERR_MEDIATION_INVALID_STATE`, `ERR_ARBITRATION_INVALID_STATE`, `ERR_DISPUTE_INVALID_STATE`, `ERR_AD_REVIEW_INVALID_STATE`, `ERR_SCAM_REPORT_INVALID_STATE`, all 409).
8. **Accreditation compliance gates.** The business must be at least 183 days old at submit; at approval, no adverse advertising review and a clean complaint history (`ERR_BUSINESS_TOO_YOUNG`, `ERR_ADVERTISING_REVIEW_ADVERSE`, `ERR_ADVERSE_COMPLAINT_HISTORY`, all 422).
9. **Referential integrity.** The business's home state must be covered by exactly one bureau; no second application may exist while one is live; a disputed snapshot and disputed complaint must belong to the disputing business; a state code must not already be assigned to another bureau (`ERR_TERRITORY_UNCOVERED`, `ERR_APPLICATION_ALREADY_ACTIVE`, `ERR_SNAPSHOT_BUSINESS_MISMATCH`, `ERR_STATE_ALREADY_ASSIGNED`, 409 or 422 per the catalogue in §5).
10. **Temporal windows.** The business response must arrive within the response window; the mediation offer within its window; reapplication only after the cooling period; reopen within its window; a rating dispute within its filing window; and a complaint admits at most 3 consumer rebuttals (`ERR_RESPONSE_WINDOW_EXPIRED`, `ERR_MEDIATION_WINDOW_EXPIRED`, `ERR_REAPPLICATION_COOLING`, `ERR_REOPEN_WINDOW_EXPIRED`, `ERR_DISPUTE_WINDOW_EXPIRED`, `ERR_REBUTTAL_LIMIT_REACHED`, all 409).
11. **Fiscal bounds.** A payment may not exceed the invoice's outstanding balance; a refund may not exceed the net amount paid; approval is blocked by an outstanding overdue or recently voided dues balance (`ERR_PAYMENT_EXCEEDS_BALANCE`, `ERR_REFUND_EXCEEDS_PAID`, `ERR_OUTSTANDING_DUES_BALANCE`, all 422).
12. **Scheduling conflicts.** Mediator overlap and hearing-room buffer checks come last (`ERR_MEDIATOR_SCHEDULE_CONFLICT`, `ERR_HEARING_ROOM_CONFLICT`, both 409).

### 2.8. Optimistic Concurrency Control

Exactly one operation participates in optimistic concurrency control: filing a rating dispute against a business. The request must carry `expected_business_version`, a non-optional field holding the `version` of the Business as the client last observed it. If the business's current `version` differs — because, for example, a new published snapshot or an appeal recomputation has advanced it since the client read the rating — the filing is rejected with `ERR_STALE_VERSION` (HTTP 412). This guarantees a dispute is always anchored to rating state the client has actually seen, rather than to a snapshot that has already been superseded. No other endpoint accepts a version field; every other write proceeds without an OCC check.

### 2.9. Money, Integers, and Rounding

All monetary values are represented as integer numbers of cents — dues bases, local fees, invoice totals, ledger entries, and collected totals alike; fractional cents never appear on the wire. Where rounding is required, the system uses the round-half-up method, and rounding occurs only at the two pinned points of the dues computation described in §3.3: once at the plan total, and — for quarterly plans — once at the per-installment amount. Rating computation uses integer arithmetic throughout, with no rounding of any kind. Timestamp comparisons for deadlines, windows, and cooling periods are evaluated at second precision on ISO 8601 instants; the one exception is business age in whole years, which is counted at calendar-year granularity as described in §3.6.

## 3. Business Logic & Workflows

### 3.1. Bureaus, Territories, and the Parties

Everything begins with the bureaus. A `BureauAdmin` creates a bureau with a display `name`, a set of `territory_state_codes` (the two-letter US state codes the bureau serves), and an optional `local_dues_fee_cents` — a flat bureau-local fee added to accreditation dues, defaulting to 0 when omitted and never negative (`ERR_INVALID_REQUEST`). Territories are exclusive across the whole system: each state code may appear in at most one bureau, and creating a bureau that claims a state code already assigned elsewhere is rejected with `ERR_STATE_ALREADY_ASSIGNED`. Two further bureau fields are system-maintained: `dues_collected_cents`, the sum over every non-`VOID` dues invoice of businesses assigned to the bureau of the paid amount minus the refunded amount; and `ops_day_index`, a monotone counter of daily closes per §2.4.

Consumers are registered by a `BureauAdmin` with a `full_name`, an `email`, and a `home_state_code` giving the consumer's state of residence. Email addresses are unique across consumers; registering a duplicate is rejected with `ERR_INVALID_REQUEST`. The system tracks each consumer's `complaints_filed_count`, the number of complaints that consumer has filed.

A `BureauAdmin` onboards a business by supplying its `legal_name`, its `home_state_code` (the principal place of business), its `employee_count` (at least 1; anything smaller is rejected with `ERR_INVALID_REQUEST`), and its `founded_on` founding date in ISO 8601 — the founding date later drives both accreditation eligibility and the business-age rating factor. Two properties are derived at creation, never supplied by the client. First, `bureau_id` is assigned to the unique bureau whose `territory_state_codes` contains the business's home state; because state codes never overlap between bureaus there is at most one candidate and no ranking or tie-break is needed, and when no bureau covers the state the creation is rejected with `ERR_TERRITORY_UNCOVERED` (HTTP 422). Second, `size_tier` is computed from headcount: `MICRO` for 1 to 4 employees, `SMALL` for 5 to 19 employees, `MEDIUM` for 20 to 99 employees, and `LARGE` for 100 or more employees. The business listing can be filtered by `bureau_id`, `accreditation_status`, or `home_state_code`, and reading a single business returns all of its computed counters and current scores.

A newly created business carries `accreditation_status` `NOT_ACCREDITED` and `advertising_compliance_status` `CLEAR`. These are parallel dimensions recorded on the same row: each evolves under its own rules, and a transition on one never reads or writes the other except where this document explicitly says so. The business's complaint counters — `complaints_received_36m`, `complaints_unanswered_36m`, `complaints_unresolved_36m`, `complaints_open_count`, and `complaints_closed_count` — all start at 0, as do `published_scam_count_12m` and `suspension_count_24m`, while `last_suspension_at` stays null until the first suspension. `current_published_score` and `current_published_grade` remain null until the first rating publication, and `current_provisional_score` and `current_provisional_grade` remain null until the first provisional computation.

### 3.2. The Accreditation Application Journey

A `BusinessRep` opens an accreditation application for their own business by supplying a `billing_plan` — either `ANNUAL_PREPAID` or `QUARTERLY` — and the `license_number` to be presented for verification; acting on another business's application surface violates ownership (`ERR_FORBIDDEN_OWNERSHIP`). The application is born in `DRAFT`, and its lifecycle runs through `SUBMITTED`, `APPROVED_PENDING_DUES`, `ACCREDITED`, `DENIED`, and `EXPIRED`. A business may have at most one live application: while any application of the business sits in `DRAFT`, `SUBMITTED`, or `APPROVED_PENDING_DUES`, creating another is rejected with `ERR_APPLICATION_ALREADY_ACTIVE`. This rule guards the creation of a new application only; the reapplication reset described below is not a creation and is permitted even while another application of the business is live. A business's applications can be listed and filtered by `status`.

Reapplication reuses the same creation operation. When the payload includes the `application_id` of an existing `DENIED` application of the same business, no new application is created; instead that application is reset to `DRAFT`. An `application_id` that does not name an application of the same business — whether it names nothing at all or another business's application — is rejected with `ERR_APPLICATION_NOT_FOUND`. The reset requires that at least 30 days have elapsed since the application's `decided_at` — earlier attempts are rejected with `ERR_REAPPLICATION_COOLING` — and is likewise ownership-gated. On reset, `reapplication_count` increments by 1, `billing_plan` and `license_number` are overwritten from the payload, and `submitted_at`, `decided_at`, `denial_reason`, and all three checklist results are cleared to null. The reset answers with `201 Created` carrying the reset application — the creation operation's status — even though no new row is minted. A denial is therefore never final, but it always costs a 30-day cooling period.

Submitting — a `BusinessRep` acting for the owning business — moves the application from `DRAFT` to `SUBMITTED` and stamps `submitted_at` with the current instant. Eligibility is gated on age: the business must be at least 183 days old at the submit instant, meaning `founded_on` falls no later than 183 days before now; a younger business is rejected with `ERR_BUSINESS_TOO_YOUNG` (HTTP 422). Submitting an application that is not in `DRAFT` is rejected with `ERR_APPLICATION_INVALID_STATE`.

Decisions belong exclusively to `StandardsReviewer`. The decision payload carries a `decision` of `APPROVE` or `DENY` together with the three checklist verdicts — `advertising_practices_result`, `complaint_history_result`, and `licensing_result` — each either `PASS` or `FAIL`. Two schema rules bind the payload before any business gate runs. An `APPROVE` is only well-formed when all three checklist results are `PASS`: a standards outcome containing any `FAIL` must be expressed as a `DENY`, and sending `APPROVE` with a `FAIL` is rejected with `ERR_INVALID_REQUEST`. A `DENY` must include a `denial_reason`; omitting it is likewise `ERR_INVALID_REQUEST`. Deciding an application that is not in `SUBMITTED` is rejected with `ERR_APPLICATION_INVALID_STATE`.

Approval is further gated by three compliance checks, evaluated against live business state. The business must have no advertising review in `UNDER_REVIEW` or `REFERRED_TO_REGULATOR`, or the decision is rejected with `ERR_ADVERTISING_REVIEW_ADVERSE` (HTTP 422). This gate inspects the business's advertising-review records, not its `advertising_compliance_status`: a review concluded `REFERRED_TO_REGULATOR` never leaves that terminal state (§3.8), so it keeps blocking approval even after the business's compliance status has returned to `CLEAR`. Both `complaints_unanswered_36m` and `complaints_unresolved_36m` must be exactly 0, or the decision is rejected with `ERR_ADVERSE_COMPLAINT_HISTORY` (HTTP 422). And the business must carry no dues invoice with a positive `balance_cents` in `OVERDUE`, nor any `VOID` invoice whose `voided_at` falls within the trailing 365 days, or the decision is rejected with `ERR_OUTSTANDING_DUES_BALANCE` (HTTP 422). When approval passes, `decided_at` is stamped, the checklist results are persisted, a dues invoice is issued exactly as §3.3 describes, the application's `dues_invoice_id` records the new invoice's id, and the application settles into `APPROVED_PENDING_DUES`. A denial stamps `decided_at` and persists the checklist results together with the `denial_reason`. From `APPROVED_PENDING_DUES` an application can reach only two terminal states: `ACCREDITED`, automatically, the moment the linked invoice is paid in full; or `EXPIRED`, automatically, when the daily close voids that invoice.

### 3.3. Accreditation Dues, Invoicing, and the Payment Ledger

Approval mints the dues invoice in a single step, freezing every pricing input at issue time. The invoice's `size_tier_at_issue` copies the business's `size_tier`; its `base_amount_cents` is the tier base dues — 42500 cents for `MICRO`, 68000 cents for `SMALL`, 115000 cents for `MEDIUM`, and 240000 cents for `LARGE`; and its `local_fee_cents` copies the bureau's `local_dues_fee_cents` at that moment. The `billing_plan` is copied from the application, the `application_id` records the lineage of the application whose approval issued the invoice (informational only, not a referential key), `issued_at` is the decision instant, and `due_date` is exactly 30 days after `issued_at`. The invoice opens in `ISSUED` with `paid_cents` and `refunded_cents` at 0, and a business's invoices can be listed and filtered by `status`.

The `amount_due_cents` depends on the billing plan, and the two plans price the same inputs differently. The subtotal is the tier base plus the local fee. Under `ANNUAL_PREPAID`, the business earns a 5 percent prepay discount: the amount due is the subtotal multiplied by 0.95, rounded half-up to whole cents in a single rounding at the total, and `installments` holds exactly one entry — installment 1 — whose `amount_cents` is the full amount due. Under `QUARTERLY`, a 4 percent plan surcharge applies with a pinned rounding order: first the plan total is computed as the subtotal multiplied by 1.04 and rounded half-up to whole cents; then the base installment is the plan total divided by 4 and rounded half-up to whole cents; the first three installments each carry the base installment, and the fourth installment carries the remainder — the plan total minus three times the base installment — so every rounding residue lands on the final installment. A worked example pins the arithmetic: with a `MEDIUM` base of 115000 cents and a bureau local fee of 333 cents, the subtotal is 115333 cents; `ANNUAL_PREPAID` yields an amount due of 109566 cents in a single installment, while `QUARTERLY` yields a plan total of 119946 cents with installments of 29987, 29987, 29987, and 29985 cents. At all times, `balance_cents` is the amount due minus the net collected (`paid_cents` minus `refunded_cents`), and it never goes negative.

Payment flows through ledger entries posted against the invoice. A `BusinessRep` of the owning business posts an entry with `kind` `PAYMENT` and an `amount_cents` of at least 1 (a smaller amount is `ERR_INVALID_REQUEST`); a payment larger than the outstanding `balance_cents` is rejected with `ERR_PAYMENT_EXCEEDS_BALANCE`. The `kind` binds the role: a `PAYMENT` entry posted by any role other than `BusinessRep`, or a `REFUND` entry posted by any role other than `BureauAdmin`, is rejected with `ERR_UNAUTHORIZED`. A partial payment adds to `paid_cents` and moves an `ISSUED` invoice to `PARTIALLY_PAID`, where further partial payments keep it. A payment that exactly covers the balance moves the invoice to `PAID` with `balance_cents` at 0 — and this is the moment accreditation lands: the linked application advances from `APPROVED_PENDING_DUES` to `ACCREDITED`, the business's `accreditation_status` moves from `NOT_ACCREDITED` to `ACCREDITED` (or, for a business recovering from suspension, from `SUSPENDED` back to `ACCREDITED`), and the business's `version` increments by 1. If the business is already `ACCREDITED` — or is `REVOKED` — at that moment, its `accreditation_status` is left unchanged and its `version` does not increment, though the linked application still advances to `ACCREDITED`. The posted entry is applied to the invoice and the response carries the updated invoice with `201 Created`; ledger entries are not themselves persisted as a separately readable resource.

Refunds are the bureau's lever. A `BureauAdmin` posts an entry with `kind` `REFUND`, again with `amount_cents` of at least 1, bounded by the net amount actually collected: a refund larger than `paid_cents` minus `refunded_cents` is rejected with `ERR_REFUND_EXCEEDS_PAID`. From `PARTIALLY_PAID`, a partial refund keeps the invoice `PARTIALLY_PAID` with the balance recomputed upward, while a refund equal to the net paid amount returns the invoice to `ISSUED` with the balance restored to the full `amount_due_cents`. From `PAID`, a partial refund moves the invoice back to `PARTIALLY_PAID`, and a refund of the entire net paid amount settles it as `REFUNDED`. A refund posted against an `OVERDUE` invoice — possible whenever some payment has landed — recomputes the balance upward but leaves the invoice `OVERDUE`, even when the refund equals the entire net paid amount: an `OVERDUE` invoice never returns to `ISSUED` or `PARTIALLY_PAID` through a refund. Critically, refunds never revert the linked application or the business's `accreditation_status`: once a business is `ACCREDITED`, its standing is governed only by the suspension scan of §3.7. Every payment and refund recomputes the bureau's `dues_collected_cents`. Ledger entries against a `VOID` or `REFUNDED` invoice are rejected with `ERR_INVOICE_INVALID_STATE`, and a `PAID` invoice accepts only refunds, since any further payment would exceed its zero balance.

The daily close enforces the calendar. An invoice whose `due_date` has passed flips from `ISSUED` — or from `PARTIALLY_PAID` — to `OVERDUE`. Late payment is still accepted while an invoice is `OVERDUE`: a payment covering the full balance moves it to `PAID` with the same accreditation cascade, while a partial payment merely reduces the balance and the invoice stays `OVERDUE`, never returning to `PARTIALLY_PAID`. An invoice still unpaid more than 15 days after its `due_date` is voided by the daily close: its status becomes `VOID`, `voided_at` is stamped, the linked application falls from `APPROVED_PENDING_DUES` to `EXPIRED`, and the unpaid balance counts against the business's future accreditation applications for the next 365 days through the approval gate of §3.2.

### 3.4. Complaint Intake, Forwarding, and the Response Cycle

A `Consumer` files a complaint by naming its `consumer_id` — which must equal the caller's `X-User-ID`, else `ERR_FORBIDDEN_OWNERSHIP` — and its `business_id`, choosing a `category` of `SERVICE`, `PRODUCT`, `BILLING`, `ADVERTISING`, `DELIVERY`, `WARRANTY`, or `OTHER`, and writing a free-text `description`. The complaint opens in `RECEIVED` with `filed_at` stamped at the current instant; the business's `complaints_open_count` rises by 1, and the filing consumer's `complaints_filed_count` reflects the new row. The complaint lifecycle spans `RECEIVED`, `FORWARDED`, `RESPONSE_RECEIVED`, `CONSUMER_REBUTTED`, `RESOLVED`, `UNRESOLVED`, `UNANSWERED`, `MEDIATION_OFFERED`, `IN_MEDIATION`, `MEDIATION_RESOLVED`, `MEDIATION_FAILED`, `IN_ARBITRATION`, and `ARBITRATED`, with `RESOLVED`, `UNANSWERED`, `MEDIATION_RESOLVED`, and `ARBITRATED` as the closed, terminal states. Complaints can be listed with `business_id`, `consumer_id`, or `status` filters, and reading a single complaint returns the embedded `responses` list — an append-only record of every exchange, each entry carrying its `kind`, its `body`, its `received_at`, and an `on_time` flag recording whether the entry arrived no later than the complaint's response deadline.

A `BureauAdmin` forwards a received complaint to the business: the status moves from `RECEIVED` to `FORWARDED`, `forwarded_at` is stamped, and `response_deadline_at` is set exactly 14 days later — precisely 1209600 seconds after `forwarded_at`. Forwarding a complaint in any other state is rejected with `ERR_COMPLAINT_INVALID_STATE`.

The business answers through its `BusinessRep`, with ownership enforced (`ERR_FORBIDDEN_OWNERSHIP`). The response `kind` binds the role: a `BUSINESS_RESPONSE` posted by a caller whose role is not `BusinessRep` — and symmetrically any `CONSUMER_*` kind posted by a caller whose role is not `Consumer` — is rejected with `ERR_UNAUTHORIZED`. A response of `kind` `BUSINESS_RESPONSE` with a free-text `body` moves the complaint from `FORWARDED` to `RESPONSE_RECEIVED`; after a rebuttal round, a further `BUSINESS_RESPONSE` moves it from `CONSUMER_REBUTTED` back to `RESPONSE_RECEIVED`. The response window is enforced with an inclusive boundary: a response received exactly at `response_deadline_at` is on time, and only a response arriving after the deadline is rejected with `ERR_RESPONSE_WINDOW_EXPIRED`. Each appended business response records `received_at` at the arrival instant and computes `on_time` from that same deadline comparison.

The filing consumer then holds the verdict, again under ownership enforcement. A response of `kind` `CONSUMER_REBUTTAL` returns the complaint from `RESPONSE_RECEIVED` to `CONSUMER_REBUTTED` and increments `rebuttal_count`; a complaint admits at most 3 consumer rebuttals, and a fourth attempt is rejected with `ERR_REBUTTAL_LIMIT_REACHED`. A `CONSUMER_ACCEPT` closes the complaint as `RESOLVED`: `resolution_outcome` becomes `CONSUMER_ACCEPTED`, `closed_at` is stamped, the business's `complaints_open_count` drops by 1 and its `complaints_closed_count` rises by 1, the trailing counters recompute, and a fresh `PROVISIONAL` rating snapshot is generated for the business. A `CONSUMER_REJECT` instead drops the complaint into `UNRESOLVED`: `resolution_outcome` becomes `CONSUMER_REJECTED`, `last_unresolved_at` is stamped on the first entry into `UNRESOLVED` only — later returns to `UNRESOLVED` do not refresh it — `complaints_unresolved_36m` rises by 1, and the provisional rating regenerates. Every consumer-side append records `on_time` as true; the deadline constrains the business, not the consumer's verdict. A response whose `kind` does not match the complaint's current state is rejected with `ERR_COMPLAINT_INVALID_STATE`.

Silence has a price. When the daily close finds a `FORWARDED` complaint whose deadline has passed, it closes the complaint as `UNANSWERED`: `resolution_outcome` becomes `AUTO_UNANSWERED`, `closed_at` is stamped, `complaints_unanswered_36m` rises by 1, `complaints_open_count` drops by 1, `complaints_closed_count` rises by 1, the trailing counters recompute, and the provisional rating regenerates.

Closure is not necessarily final. A `BureauAdmin` may reopen a complaint in `RESOLVED` or `UNANSWERED` no later than 30 days after its `closed_at`; a later attempt is rejected with `ERR_REOPEN_WINDOW_EXPIRED`, and reopening from any other state is `ERR_COMPLAINT_INVALID_STATE`. Reopening increments `reopen_count` by 1, clears `resolution_outcome` and `closed_at` to null, stamps a fresh `forwarded_at` and a fresh 14-day `response_deadline_at`, and returns the complaint to `FORWARDED`; the `responses` history and `rebuttal_count` survive the reopen unchanged, so a complaint that has already absorbed 3 rebuttals admits no more after reopening; `complaints_open_count` rises by 1 and `complaints_closed_count` drops by 1, reopening an `UNANSWERED` complaint additionally reduces `complaints_unanswered_36m`, and the provisional rating regenerates.

The counter definitions pinned here drive both the approval gates of §3.2 and the rating inputs of §3.6. `complaints_received_36m` counts the business's complaints filed within the trailing 1095 days that sit in an outcome state — `RESOLVED`, `UNANSWERED`, `UNRESOLVED`, `MEDIATION_RESOLVED`, `MEDIATION_FAILED`, or `ARBITRATED`. `complaints_unanswered_36m` counts those in `UNANSWERED` within the same window. `complaints_unresolved_36m` counts those in `UNRESOLVED` or `MEDIATION_FAILED` within the same window. `complaints_open_count` counts complaints in any open state — `RECEIVED`, `FORWARDED`, `RESPONSE_RECEIVED`, `CONSUMER_REBUTTED`, `MEDIATION_OFFERED`, `IN_MEDIATION`, `UNRESOLVED`, `MEDIATION_FAILED`, or `IN_ARBITRATION`. `complaints_closed_count` counts those in `RESOLVED`, `UNANSWERED`, `MEDIATION_RESOLVED`, or `ARBITRATED`.

### 3.5. Mediation and Arbitration Escalation

When direct negotiation fails, the bureau offers structured escalation. A `BureauAdmin` may offer mediation on an `UNRESOLVED` complaint, but only within the mediation window: the offer must arrive no later than 14 days after the complaint's `last_unresolved_at`, and a later offer is rejected with `ERR_MEDIATION_WINDOW_EXPIRED`. The offer creates a MediationCase in `OFFERED` — its `complaint_id` is implied by the complaint under which it is created — stamps `offered_at`, and sets `offer_deadline_at` exactly 7 days later; the complaint moves to `MEDIATION_OFFERED`. Because any live mediation case holds its complaint in `MEDIATION_OFFERED` or `IN_MEDIATION`, the state gate itself prevents a second concurrent mediation on the same complaint. A mediation case's lifecycle spans `OFFERED`, `ACCEPTED`, `DECLINED`, `DECLINED_EXPIRED`, `SCHEDULED`, `CONCLUDED_AGREEMENT`, and `CONCLUDED_NO_AGREEMENT`, and a complaint's mediation cases can be listed with `limit` and `offset` pagination.

Both parties must opt in. The business's `BusinessRep` answers with `party` `BUSINESS` and the filing consumer answers with `party` `CONSUMER`; a `party` value that does not match the caller's role is rejected with `ERR_UNAUTHORIZED`, and a caller whose entity does not own the named side is rejected with `ERR_FORBIDDEN_OWNERSHIP`. Each side supplies a `response` of `ACCEPTED` or `DECLINED` that is recorded into `business_response` or `consumer_response` respectively — both of which begin as `PENDING`. A party may answer only once: responding when that side's field is no longer `PENDING` is rejected with `ERR_MEDIATION_INVALID_STATE`, as is any party response while the case is not `OFFERED`. When one party has answered and the other is still `PENDING`, the case stays `OFFERED`. The instant both sides have accepted, the case becomes `ACCEPTED` and the complaint moves from `MEDIATION_OFFERED` to `IN_MEDIATION`. The instant any side declines, the case becomes `DECLINED` and the complaint falls back from `MEDIATION_OFFERED` to `UNRESOLVED` — importantly without refreshing `last_unresolved_at`, so a declined offer does not buy a new mediation window. If the daily close finds an `OFFERED` case past its `offer_deadline_at` without both parties accepted, it expires the case to `DECLINED_EXPIRED` with the same fall-back to `UNRESOLVED`, again leaving `last_unresolved_at` untouched.

Scheduling is a `BureauAdmin` act on an `ACCEPTED` case — from any other state it is rejected with `ERR_MEDIATION_INVALID_STATE` — supplying `mediator_id` (an opaque staff identifier), `session_start_at`, and `session_end_at`. The end must be strictly after the start (`ERR_INVALID_REQUEST`). A mediator cannot hold overlapping sessions: the new session conflicts with any other `SCHEDULED` case carrying the same `mediator_id` whose half-open interval — start inclusive, end exclusive — intersects the requested one, and such a request is rejected with `ERR_MEDIATOR_SCHEDULE_CONFLICT`; back-to-back sessions, where one session ends exactly as another begins, do not conflict. A successful scheduling persists all three scheduling fields and moves the case to `SCHEDULED`.

Concluding — also `BureauAdmin`, and only from `SCHEDULED` — supplies an `outcome` of `AGREEMENT` or `NO_AGREEMENT`. An agreement ends the case `CONCLUDED_AGREEMENT` and closes the complaint as `MEDIATION_RESOLVED` with `resolution_outcome` `MEDIATION_AGREEMENT` and `closed_at` stamped; `complaints_open_count` drops by 1, `complaints_closed_count` rises by 1, and the provisional rating regenerates. No agreement ends the case `CONCLUDED_NO_AGREEMENT` and moves the complaint to `MEDIATION_FAILED` with `resolution_outcome` `MEDIATION_NO_AGREEMENT`; `complaints_unresolved_36m` reflects the failure and the provisional rating regenerates.

A failed mediation is arbitrable. A `BureauAdmin` escalates a `MEDIATION_FAILED` complaint to binding arbitration, creating an ArbitrationCase in `FILED` whose `source_mediation_case_id` records the id of the latest `CONCLUDED_NO_AGREEMENT` mediation case as informational lineage — not a referential key — while the complaint moves to `IN_ARBITRATION`; since any live arbitration case holds its complaint in `IN_ARBITRATION`, a second concurrent arbitration is impossible by state. An arbitration case's lifecycle runs `FILED`, `HEARING_SCHEDULED`, and `DECIDED`, and a complaint's arbitration cases can be listed with pagination.

Hearing scheduling is a `BureauAdmin` act, valid only from `FILED` (otherwise `ERR_ARBITRATION_INVALID_STATE`), supplying `hearing_room_id`, `hearing_start_at`, and `hearing_end_at`, with the end strictly after the start (`ERR_INVALID_REQUEST`). Hearing rooms are scheduled with a safety buffer on both sides: for every other `HEARING_SCHEDULED` case in the same room, the new hearing must start no earlier than 30 minutes after the existing hearing's end, or else end no later than 30 minutes before the existing hearing's start, and any violation is rejected with `ERR_HEARING_ROOM_CONFLICT`. Unlike mediation sessions, adjacency itself conflicts: a hearing that begins exactly when another hearing in the same room ends leaves no buffer and is rejected. A successful scheduling persists the room and the hearing window and moves the case to `HEARING_SCHEDULED`.

Rendering the decision — `BureauAdmin`, valid only from `HEARING_SCHEDULED` (otherwise `ERR_ARBITRATION_INVALID_STATE`) — supplies an `outcome` of `ADVERSE_TO_BUSINESS` or `NO_FAULT`, stamps `decided_at`, and closes the case as `DECIDED`. The complaint then closes as `ARBITRATED`, with `resolution_outcome` `ARBITRATION_ADVERSE` when the outcome is adverse to the business or `ARBITRATION_NO_FAULT` on a no-fault finding; `closed_at` is stamped, `complaints_open_count` drops by 1, `complaints_closed_count` rises by 1, and the provisional rating regenerates. Adverse arbitration outcomes feed the rating directly, as §3.6 describes.

### 3.6. The Rating Methodology: Score and Grade Computation

Every rating is captured as a RatingSnapshot of one of two `variant` values — `PROVISIONAL` or `PUBLISHED` — computed from the same underlying business data with different input sets. A snapshot stamps `computed_at` with the computation instant and sets `window_start_at` exactly 1095 days earlier: the rating window is the trailing 1095 days, inclusive at both ends, and only complaints with `filed_at` inside that window participate. Within the window, complaints partition into an outcome set — those in `RESOLVED`, `UNANSWERED`, `UNRESOLVED`, `MEDIATION_RESOLVED`, `MEDIATION_FAILED`, or `ARBITRATED` — and a pending set of still-open complaints in `RECEIVED`, `FORWARDED`, `RESPONSE_RECEIVED`, `CONSUMER_REBUTTED`, `MEDIATION_OFFERED`, `IN_MEDIATION`, or `IN_ARBITRATION`. When a dispute is overruled, the complaint it names is removed from both sets for the recomputed snapshot, as §3.7 describes.

The score starts at 100 and loses points through eight deduction components, each computed with integer arithmetic and no rounding:

- `volume_deduction` punishes complaint volume relative to business size. The volume threshold is 3 complaints for a `MICRO` business, 6 for `SMALL`, 12 for `MEDIUM`, and 24 for `LARGE`. For a `PUBLISHED` snapshot the volume input counts the outcome set; for a `PROVISIONAL` snapshot it counts the outcome set plus the pending set. The deduction is 6 points for every complaint above the threshold, capped at 30 points; a business at or below its threshold loses nothing to volume.
- `unanswered_deduction` charges 12 points for each `UNANSWERED` complaint in the window, capped at 36 points.
- `unresolved_deduction` charges 8 points for each complaint in `UNRESOLVED` or `MEDIATION_FAILED` in the window, capped at 24 points.
- `arbitration_deduction` charges 10 points for each `ARBITRATED` complaint whose `resolution_outcome` is `ARBITRATION_ADVERSE`, capped at 20 points.
- `age_deduction` reflects business youth. The age in years is the number of full calendar years elapsed between `founded_on` and now — a year counts only once the calendar anniversary of the founding date has been reached, and a February 29 founding observes its anniversary on February 28 in non-leap years — and the deduction is 2 points for each full year by which the business is younger than 3 years, capped at 6 points; a business 3 or more full years old loses nothing here.
- `advertising_deduction` is 15 points while the business's `advertising_compliance_status` is `REFERRED_TO_REGULATOR`, 5 points while it is `UNDER_AD_REVIEW`, and 0 points while it is `CLEAR`.
- `scam_deduction` is 10 points when `published_scam_count_12m` is 3 or more, and 0 points otherwise.
- `pending_deduction` exists only on `PROVISIONAL` snapshots: 4 points for each pending-set complaint, capped at 12 points. On `PUBLISHED` snapshots it is always 0.

The `total_deductions` is the sum of all eight components, and the `score` is 100 minus that sum, floored at 0 — the score can never go negative. The `grade` is a letter derived from the score with inclusive lower bounds: `A_PLUS` at 97 or higher, `A` at 94 or higher, `A_MINUS` at 90 or higher, `B_PLUS` at 85 or higher, `B` at 80 or higher, `B_MINUS` at 75 or higher, `C_PLUS` at 70 or higher, `C` at 65 or higher, `C_MINUS` at 60 or higher, `D_PLUS` at 55 or higher, `D` at 50 or higher, and `F` below 50. Because every boundary is inclusive on its lower end, a score of exactly 90 earns `A_MINUS` while 89 earns `B_PLUS`. Each snapshot records all eight components alongside its `total_deductions`, `score`, and `grade`, so every published number is auditable back to its parts; the snapshot's `business_id` ties it to the rated business. A business's snapshots can be listed and filtered by `variant`.

The two variants answer different questions. `PUBLISHED` is the public record: pending complaints are invisible to it, contributing neither to the volume input nor to any pending deduction, so the score reflects closed outcomes only. `PROVISIONAL` is the live preview: pending complaints count toward the volume input and draw the pending deduction, so identical underlying data yields a different provisional score whenever any complaint is open.

Computation happens two ways. A `BureauAdmin` may compute a snapshot on demand, choosing the `variant` in the request. In addition, the system regenerates a `PROVISIONAL` snapshot automatically at exactly the points the workflows of §3.4, §3.5, and §3.8 and the daily close of §2.4 note one, and nowhere else: complaint intake, forwarding, business responses, consumer rebuttals, mediation offers and party answers, session and hearing scheduling, arbitration filing, and dispute filing and ruling never regenerate the provisional snapshot, even where — as at intake, at a mediation offer, or on a party's decline — they move the live complaint counters. The business mirrors the latest results: `current_published_score` and `current_published_grade` come from the most recent `PUBLISHED` snapshot, selected by `published_at` with ties broken by the later `created_at` and any remaining tie broken in favor of the snapshot written later, while `current_provisional_score` and `current_provisional_grade` come from the latest `PROVISIONAL` snapshot; both pairs stay null until their first respective computation.

### 3.7. Rating Publication, the Suspension Scan, and the Dispute Process

Only a `BureauAdmin` publishes. Computing a snapshot with `variant` `PUBLISHED` stamps `published_at` with the current instant, updates the business's `current_published_score` and `current_published_grade`, and increments the business's `version` by 1. Computing a `PROVISIONAL` snapshot updates `current_provisional_score` and `current_provisional_grade`. Publication is consequential: the daily close's suspension scan reads only published ratings.

The suspension scan runs within each bureau's daily close, over every business of that bureau whose `accreditation_status` is `ACCREDITED` or `SUSPENDED`. For each business it takes the latest `PUBLISHED` snapshot — by `published_at`, ties broken by the later `created_at`, and any remaining tie broken in favor of the snapshot written later — and a business with no published snapshot at all is left unchanged. An `ACCREDITED` business whose latest published score is below 75 is suspended: `accreditation_status` becomes `SUSPENDED`, `suspension_count_24m` increments by 1, `last_suspension_at` is stamped, and the business's `version` increments by 1. If that suspension would be the business's second within the trailing 730 days, the business is instead revoked: `accreditation_status` becomes `REVOKED`, with the same counter, timestamp, and version updates. A `SUSPENDED` business whose latest published score is 80 or higher is reinstated to `ACCREDITED`, its `version` incrementing. A `SUSPENDED` business whose latest published score remains below 75 while its trailing suspension count reaches 2 is revoked outright. Scores from 75 through 79 form a hysteresis band: they neither suspend an accredited business nor reinstate a suspended one, so a business must genuinely recover to 80 before regaining its standing. The trailing count is itself time-bounded — suspensions more than 730 days old drop out of `suspension_count_24m` before the check runs. That refresh is applied in place: the business's `version` increments only when the scan also changes `accreditation_status` (suspending, reinstating, or revoking), never for the count refresh alone. `REVOKED` is terminal: no transition leaves it.

A business that believes its published rating is wrong may file a rating dispute through its `BusinessRep`, with ownership enforced. The filing names the disputed `snapshot_id`, gives a free-text `reason`, carries the OCC field `expected_business_version` exactly as §2.8 requires, and may optionally name a `disputed_complaint_id` identifying the complaint the business contests. The dispute must be filed no later than 10 days after the snapshot's `published_at`; a later filing is rejected with `ERR_DISPUTE_WINDOW_EXPIRED`. The named snapshot must be one of the disputing business's own published snapshots and the disputed complaint must belong to that business — a `snapshot_id` or `disputed_complaint_id` belonging to another business is rejected with `ERR_SNAPSHOT_BUSINESS_MISMATCH` (HTTP 422), while an identifier naming nothing at all draws the matching not-found error of §2.6. Filing commits the dispute directly into `UNDER_APPEAL_REVIEW` — `FILED` is a zero-duration state, entered and left within the act of creation — stamps `filed_at`, and increments the business's `version` by 1. A business's disputes can be listed and filtered by `status`.

Appeal rulings belong to `BureauAdmin` and require the dispute to be in `UNDER_APPEAL_REVIEW`; ruling on a dispute in any other state is rejected with `ERR_DISPUTE_INVALID_STATE`. A `decision` of `UPHELD` closes the dispute with the contested snapshot unchanged. A `decision` of `OVERRULED` requires `disputed_complaint_id` to name a complaint of the disputing business (else `ERR_SNAPSHOT_BUSINESS_MISMATCH`) and rewrites the record: the rating is recomputed with the disputed complaint excluded from every input set of §3.6, a fresh `PUBLISHED` snapshot is written with `published_at` stamped and `excluded_complaint_id` naming the excluded complaint, the superseded snapshot's `superseded_by_id` is set to the replacement snapshot's id, the business's `current_published_score` and `current_published_grade` update to the new values, and the business's `version` increments by 1. `UPHELD` and `OVERRULED` are both terminal.

### 3.8. Advertising Review and Scam-Pattern Surveillance

Either a `BureauAdmin` or a `StandardsReviewer` may open an advertising-practices review against a business, supplying the `claim_description` under scrutiny. The review opens in `UNDER_REVIEW` with `opened_at` stamped; the business's `advertising_compliance_status` moves from `CLEAR` to `UNDER_AD_REVIEW` with its `version` incrementing by 1, and a fresh `PROVISIONAL` rating snapshot is generated. The regeneration — and with it the business's `version` increment — fires on every opening, even one that leaves the status unchanged, such as a second concurrently open review. Referral is sticky: opening a fresh review against a business already in `REFERRED_TO_REGULATOR` leaves that status untouched until the new review concludes. A review's lifecycle spans `UNDER_REVIEW`, `CLEARED`, and `REFERRED_TO_REGULATOR`, and a business's reviews can be listed and filtered by `status`.

Concluding a review belongs to `StandardsReviewer` alone and requires the review to be in `UNDER_REVIEW`; concluding from any other state is rejected with `ERR_AD_REVIEW_INVALID_STATE`. An `outcome` of `CLEARED` closes the review as `CLEARED` with `concluded_at` stamped; the business returns to `CLEAR` only when no other review of that business remains `UNDER_REVIEW` — if one does, the business stays `UNDER_AD_REVIEW` — and the same condition lets a referred business return to `CLEAR`. An `outcome` of `SUBSTANTIATED_DECEPTIVE` requires a `regulator_name` in the payload, and omitting it is rejected with `ERR_INVALID_REQUEST`: the review closes as `REFERRED_TO_REGULATOR` with both `concluded_at` and `referred_at` stamped at the conclusion instant, the `regulator_name` persisted, and the business's `advertising_compliance_status` set to `REFERRED_TO_REGULATOR`. Either conclusion regenerates the business's provisional rating, since the advertising deduction of §3.6 may have changed.

Scam reports give consumers a channel outside the complaint process. A `Consumer` files one by naming a `consumer_id` equal to their `X-User-ID` (else `ERR_FORBIDDEN_OWNERSHIP`), a `business_id`, a free-text `description`, and the `incident_date` of the alleged scam in ISO 8601; the report opens in `RECEIVED`. Consumers have no per-consumer read surface for their own filings — the only listing is the business-scoped one, filterable by `status`, which all four roles may read. A `BureauAdmin` publishes a report that is in `RECEIVED` — publishing from any other state is rejected with `ERR_SCAM_REPORT_INVALID_STATE` — at which point the report becomes `PUBLISHED` with `published_at` stamped, the business's `published_scam_count_12m` (the count of its `PUBLISHED` reports whose `published_at` falls within the trailing 365 days) recomputes, and the provisional rating regenerates.

Finally, the bureau publishes scam patterns as a computed listing, readable by all four roles and paginated through `limit` and `offset` like any list. For each business, the system counts its `PUBLISHED` scam reports with `published_at` within the trailing 365 days; every business with at least 1 such report appears as a row carrying `business_id`, `legal_name`, `published_report_count_12m`, and a `pattern_flag` that is true when the count reaches 3 or more. Rows sort by `published_report_count_12m` descending, with ties broken by `legal_name` ascending — never by id; rows identical on both keys keep the order in which the businesses were created. The response carries these rows in a `patterns` array.

## 4. Endpoint Definitions

Operations that create a new resource — a bureau, consumer, business, accreditation application, invoice ledger entry, complaint, complaint response, mediation case, arbitration case, rating snapshot, rating dispute, advertising review, or scam report — return `201 Created`. Operations that transition, decide, or annotate an existing resource return `200 OK`, as do all reads. Request bodies, preconditions, and side effects for every operation are specified narratively in §3; this table is a routing and authorization summary only. All paths are relative to the server root.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/bureaus` | Create a bureau with its territory state codes and optional local dues fee | BureauAdmin |
| POST | `/bureaus/{id}/run_daily_close` | Run the bureau's daily close against the logical clock: expire lapsed complaint response windows, expire mediation offers, mark invoices overdue then void them, and run the suspension scan | BureauAdmin |
| POST | `/consumers` | Register a consumer | BureauAdmin |
| POST | `/businesses` | Create a business; territory assignment and size tier are computed | BureauAdmin |
| GET | `/businesses/{id}` | Read a business including computed counters and current scores | BureauAdmin, StandardsReviewer, BusinessRep, Consumer |
| GET | `/businesses` | List businesses with filters and pagination | BureauAdmin, StandardsReviewer, BusinessRep, Consumer |
| POST | `/businesses/{id}/accreditation-applications` | Create a DRAFT application, or reset a named DENIED application past its cooling period back to DRAFT | BusinessRep |
| GET | `/businesses/{id}/accreditation-applications` | List a business's accreditation applications | BureauAdmin, StandardsReviewer, BusinessRep |
| POST | `/accreditation-applications/{id}/submit` | Submit a DRAFT application | BusinessRep |
| POST | `/accreditation-applications/{id}/decision` | Render the standards decision; APPROVE issues the dues invoice | StandardsReviewer |
| GET | `/businesses/{id}/dues-invoices` | List a business's dues invoices | BureauAdmin, StandardsReviewer, BusinessRep |
| POST | `/dues-invoices/{id}/ledger-entries` | Post a PAYMENT or REFUND ledger entry against an invoice | BureauAdmin, BusinessRep |
| POST | `/complaints` | File a complaint against a business | Consumer |
| GET | `/complaints/{id}` | Read a complaint including its embedded responses | BureauAdmin, StandardsReviewer, BusinessRep, Consumer |
| GET | `/complaints` | List complaints with filters and pagination | BureauAdmin, StandardsReviewer, BusinessRep, Consumer |
| POST | `/complaints/{id}/forward` | Forward a RECEIVED complaint to the business, starting the response window | BureauAdmin |
| POST | `/complaints/{id}/responses` | Append a business response or a consumer rebuttal, acceptance, or rejection | BusinessRep, Consumer |
| POST | `/complaints/{id}/reopen` | Reopen a RESOLVED or UNANSWERED complaint within its reopen window | BureauAdmin |
| POST | `/complaints/{id}/mediation-cases` | Offer mediation on an UNRESOLVED complaint | BureauAdmin |
| GET | `/complaints/{id}/mediation-cases` | List a complaint's mediation cases | BureauAdmin, StandardsReviewer, BusinessRep, Consumer |
| POST | `/mediation-cases/{id}/party-response` | Record a party's acceptance or decline of the mediation offer | BusinessRep, Consumer |
| POST | `/mediation-cases/{id}/schedule` | Schedule the mediation session with a mediator | BureauAdmin |
| POST | `/mediation-cases/{id}/conclude` | Conclude a scheduled mediation with an outcome | BureauAdmin |
| POST | `/complaints/{id}/arbitration-cases` | Escalate a MEDIATION_FAILED complaint to binding arbitration | BureauAdmin |
| GET | `/complaints/{id}/arbitration-cases` | List a complaint's arbitration cases | BureauAdmin, StandardsReviewer, BusinessRep, Consumer |
| POST | `/arbitration-cases/{id}/schedule-hearing` | Schedule the arbitration hearing in a hearing room | BureauAdmin |
| POST | `/arbitration-cases/{id}/render-decision` | Render the arbitration decision, closing the complaint | BureauAdmin |
| POST | `/businesses/{id}/rating-snapshots` | Compute a rating snapshot, PROVISIONAL or PUBLISHED | BureauAdmin |
| GET | `/businesses/{id}/rating-snapshots` | List a business's rating snapshots | BureauAdmin, StandardsReviewer, BusinessRep |
| POST | `/businesses/{id}/rating-disputes` | Dispute a published rating snapshot | BusinessRep |
| POST | `/rating-disputes/{id}/appeal-decision` | Rule on a rating dispute appeal | BureauAdmin |
| GET | `/businesses/{id}/rating-disputes` | List a business's rating disputes | BureauAdmin, StandardsReviewer, BusinessRep |
| POST | `/businesses/{id}/advertising-reviews` | Open an advertising-practices review against a business | BureauAdmin, StandardsReviewer |
| POST | `/advertising-reviews/{id}/conclude` | Conclude an advertising review, referring deceptive claims to a regulator | StandardsReviewer |
| GET | `/businesses/{id}/advertising-reviews` | List a business's advertising reviews | BureauAdmin, StandardsReviewer, BusinessRep |
| POST | `/scam-reports` | File a scam report against a business | Consumer |
| GET | `/businesses/{id}/scam-reports` | List a business's scam reports | BureauAdmin, StandardsReviewer, BusinessRep, Consumer |
| POST | `/scam-reports/{id}/publish` | Publish a received scam report | BureauAdmin |
| GET | `/scam-patterns` | Read the computed scam-pattern publication | BureauAdmin, StandardsReviewer, BusinessRep, Consumer |
| POST | `/_clock/set_current_utc` | Set the logical clock (forward or backward) | BureauAdmin |

## 5. Error Code Catalogue

Trigger conditions for every error are specified in §2 and §3 alongside the workflows they guard; this catalogue is a status-code reference only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_FORBIDDEN_OWNERSHIP` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_BUREAU_NOT_FOUND` | 404 Not Found |
| `ERR_BUSINESS_NOT_FOUND` | 404 Not Found |
| `ERR_CONSUMER_NOT_FOUND` | 404 Not Found |
| `ERR_COMPLAINT_NOT_FOUND` | 404 Not Found |
| `ERR_APPLICATION_NOT_FOUND` | 404 Not Found |
| `ERR_INVOICE_NOT_FOUND` | 404 Not Found |
| `ERR_MEDIATION_NOT_FOUND` | 404 Not Found |
| `ERR_ARBITRATION_NOT_FOUND` | 404 Not Found |
| `ERR_SNAPSHOT_NOT_FOUND` | 404 Not Found |
| `ERR_DISPUTE_NOT_FOUND` | 404 Not Found |
| `ERR_AD_REVIEW_NOT_FOUND` | 404 Not Found |
| `ERR_SCAM_REPORT_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_TERRITORY_UNCOVERED` | 422 Unprocessable Entity |
| `ERR_STATE_ALREADY_ASSIGNED` | 409 Conflict |
| `ERR_APPLICATION_ALREADY_ACTIVE` | 409 Conflict |
| `ERR_APPLICATION_INVALID_STATE` | 409 Conflict |
| `ERR_REAPPLICATION_COOLING` | 409 Conflict |
| `ERR_BUSINESS_TOO_YOUNG` | 422 Unprocessable Entity |
| `ERR_ADVERTISING_REVIEW_ADVERSE` | 422 Unprocessable Entity |
| `ERR_ADVERSE_COMPLAINT_HISTORY` | 422 Unprocessable Entity |
| `ERR_OUTSTANDING_DUES_BALANCE` | 422 Unprocessable Entity |
| `ERR_INVOICE_INVALID_STATE` | 409 Conflict |
| `ERR_PAYMENT_EXCEEDS_BALANCE` | 422 Unprocessable Entity |
| `ERR_REFUND_EXCEEDS_PAID` | 422 Unprocessable Entity |
| `ERR_COMPLAINT_INVALID_STATE` | 409 Conflict |
| `ERR_RESPONSE_WINDOW_EXPIRED` | 409 Conflict |
| `ERR_REBUTTAL_LIMIT_REACHED` | 409 Conflict |
| `ERR_REOPEN_WINDOW_EXPIRED` | 409 Conflict |
| `ERR_MEDIATION_WINDOW_EXPIRED` | 409 Conflict |
| `ERR_MEDIATION_INVALID_STATE` | 409 Conflict |
| `ERR_MEDIATOR_SCHEDULE_CONFLICT` | 409 Conflict |
| `ERR_ARBITRATION_INVALID_STATE` | 409 Conflict |
| `ERR_HEARING_ROOM_CONFLICT` | 409 Conflict |
| `ERR_DISPUTE_WINDOW_EXPIRED` | 409 Conflict |
| `ERR_DISPUTE_INVALID_STATE` | 409 Conflict |
| `ERR_SNAPSHOT_BUSINESS_MISMATCH` | 422 Unprocessable Entity |
| `ERR_AD_REVIEW_INVALID_STATE` | 409 Conflict |
| `ERR_SCAM_REPORT_INVALID_STATE` | 409 Conflict |
