# Digital Preservation Lending API — Product Requirements Document

## 1. Introduction

A digital preservation platform in the tradition of the Internet Archive operates at the intersection of two very different worlds: the open, adversarial web — where sites vanish without warning, robots directives and rights-holder wishes must be honored, and storage is metered by the petabyte — and the quiet, rules-bound world of the research library, where a physical book can be in exactly one reader's hands at a time. This platform runs both halves under a single roof. Web crawl jobs harvest at-risk sites under strict politeness limits and exclusion directives, producing deduplicated captures that patrons can play back later, subject to live suppression by rights actions. In parallel, partner libraries deposit physical volumes for scanning, and the resulting digital copies are circulated under a controlled digital lending model: one copy, one reader, time-limited loans, waitlists, and elevated access for print-disabled patrons whose qualifications are verified by a dedicated officer.

The platform answers to several masters at once. Rights holders may file removal requests against a cataloged work or against a URL prefix of captured pages, and those requests move through a segregated legal pipeline — the reviewer may not be the filer, the decider may not be the reviewer — with collection availability and playback suppression hanging on each transition. Patrons accrue strikes when loans lapse, and three strikes suspend the account, cancelling any offers in flight. Partner libraries commit to long-term storage but may withdraw, provided none of their items is currently out on loan. And the entire operation is funded by donation grants whose infrastructure budget lines are reserved, settled, and released under optimistic concurrency control, with grants flipping between open and exhausted as utilization reaches the donated amount exactly.

This document specifies the platform's REST API, mounted under `/archive`, in enough detail for an engineering team to implement it without further design input. Global contracts — the response envelope, pagination, the logical clock, optimistic concurrency, and the validation ordering every request passes through — are given in Section 2. The business workflows, with their cascades and calculation rules, are narrated in Section 3. Section 4 tabulates every endpoint, and Section 5 catalogs every error code.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request is authenticated by two HTTP headers: `X-User-ID` and `X-User-Role`. A missing or invalid header — including an `X-User-Role` value that is not one of the declared roles — is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The sole exception is the `Anonymous` role, which carries no `X-User-ID` at all and is used only for self-service patron registration. Once authenticated, a caller whose role is not listed among the endpoint's permitted roles — or whose identity fails an entity-backed ownership check — is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The declared roles, spelled exactly as the API expects them in `X-User-Role`, are: `Anonymous`, `Admin`, `Patron`, `AccessibilityOfficer`, `LibraryAdmin`, `ScanOperator`, `CrawlOperator`, `LegalReviewer`, and `FinanceAdmin`.

Only one role is entity-backed. When `X-User-Role` is `Patron`, `X-User-ID` is the `id` of the acting `Patron`; ownership checks on any resource that references a `Patron` — loans, waitlist entries, accessibility credentials, the patron record itself — compare the resource's patron foreign-key field to `X-User-ID`, and a mismatch is `ERR_UNAUTHORIZED`. For every other role the identity is opaque: when `X-User-Role` is `Admin`, `AccessibilityOfficer`, `LibraryAdmin`, `ScanOperator`, `CrawlOperator`, `LegalReviewer`, or `FinanceAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example as `filed_by`, `reviewed_by`, or `decided_by` on a rights request, or `decided_by` on an accessibility credential — but it never compares such an identifier to any entity's `id`. The segregation-of-duties comparisons described later (`filed_by` versus reviewer, reviewer versus decider, officer versus the credential's patron) are comparisons between these recorded operator identifiers, not entity ownership checks.

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

All list endpoints accept two query parameters, `limit` and `offset`. The `limit` defaults to 10, must be at least 1, and must not exceed 100. The `offset` defaults to 0. List responses report `limit`, `offset`, `total_count`, and `has_more` in the `meta` object. Unless a workflow states otherwise, every list is sorted by `created_at` ascending — for waitlist queues this ordering is not merely cosmetic but is the queue's priority order, as Section 3 makes precise.

### 2.4. Resource Identity, Timestamps, and the Logical Clock

Every persisted resource carries an `id` that is a server-minted UUID with no type prefix, a `created_at` timestamp, an `updated_at` timestamp, and an integer `version` that starts at 1 and increments by exactly 1 on every mutation of that resource. Both timestamps are ISO 8601 UTC with three fractional digits. One entity departs from this shape: a `Capture` carries only `id` and `created_at` — `updated_at` and `version` are absent on captures, because captures are immutable once recorded.

The platform never consults wall-clock time for business decisions. A logical clock governs every temporal comparison — loan due dates, offer windows, crawl schedules, credential decision timestamps, capture times. At server startup, before any operator intervention, the logical clock reads exactly 2026-09-01T00:00:00Z, and it never falls back to wall-clock time thereafter. An `Admin` may advance it through a test-driving capability that sets the logical clock to a supplied `to_iso8601` instant; the response echoes the new clock as `current_utc`. All millisecond-precision timestamp comparisons in Section 3 read this clock.

### 2.5. Validation Order of Operations

Every incoming request passes through a fixed gauntlet of checks, and the order matters: when a request violates several rules at once, the earliest check in this order wins and determines the error returned. The full ordering is:

1. Authentication — headers present, role declared; otherwise `ERR_UNAUTHENTICATED`.
2. Authorization — role permitted on the endpoint, and entity-backed ownership satisfied for patron-self operations; otherwise `ERR_UNAUTHORIZED`.
3. Existence — every path id and every body foreign-key id references an existing resource, validated left-to-right in the order the ids are declared for that endpoint; otherwise `ERR_NOT_FOUND`. For nested paths this means the parent segment is validated before the child segment.
4. Transition state — the target resource is in a from-state that permits the requested transition; otherwise `ERR_INVALID_STATE`.
5. Segregation of duties — filer-versus-reviewer, reviewer-versus-decider, officer-versus-credential-patron; otherwise `ERR_SO_DUTY_VIOLATION`.
6. Schema validity — required fields, types, enum membership, numeric ranges, subject-kind field consistency, and the strictly-future scheduling rule; otherwise `ERR_VALIDATION`.
7. Patron standing — checkout, waitlist join, and claim require an `ACTIVE` patron; otherwise `ERR_PATRON_SUSPENDED`.
8. Work availability — new loans and waitlist joins require the work's `availability` to be `AVAILABLE`; otherwise `ERR_WORK_UNAVAILABLE`.
9. Item lendability — the item must be `LENDABLE` with an `ACTIVE` owning library, and at claim time a lendable item of the work must still exist; otherwise `ERR_ITEM_NOT_LENDABLE`.
10. Waitlist priority — direct checkout is refused while any waitlist entry for the work is `OPEN` or `OFFERED`; `ERR_WAITLIST_PRIORITY`.
11. Duplicate possession — the patron must not already hold an `ACTIVE` loan on any item of the same work; `ERR_WORK_ALREADY_BORROWED`.
12. Loan cap — `active_loan_count` strictly below `max_concurrent_loans`; `ERR_LOAN_CAP_REACHED`.
13. Short-read credential gate — `ERR_ACCESS_CREDENTIAL_REQUIRED`.
14. Crawl schedule due — `ERR_SCHEDULE_NOT_DUE`.
15. Crawl exclusion gate — `ERR_CRAWL_EXCLUDED`.
16. Offer window — `ERR_OFFER_EXPIRED`.
17. Renewal eligibility — `ERR_LOAN_NOT_RENEWABLE`.
18. Renewal absolute cap — `ERR_RENEWAL_WINDOW_EXCEEDED`.
19. Grant capacity — `ERR_GRANT_EXHAUSTED`.
20. Library withdrawal gate — `ERR_LIBRARY_HAS_ACTIVE_LOANS`.
21. Uniqueness — patron email, library code, live waitlist pair; `ERR_DUPLICATE`.
22. Non-empty batch seal — `ERR_SEAL_EMPTY_BATCH`.
23. Optimistic concurrency — stale expected-version values; `ERR_STALE_VERSION`.

Note what this ordering implies: a stale optimistic-concurrency token is reported only after every other defect has been ruled out, and an authentication failure masks everything downstream of it.

### 2.6. Optimistic Concurrency Control

Two write operations carry an explicit expected-version token, and only these two families do — no other endpoint accepts a version field.

Claiming an offered waitlist entry requires the request to carry `expected_entry_version`, equal to the `WaitlistEntry`'s `version` as the claimant last observed it. If the entry's version has advanced since that observation — for example because a sweep expired the offer and a subsequent promotion re-offered the entry, bumping its version — the claim is rejected with `ERR_STALE_VERSION` (HTTP 412), even though the entry is once again `OFFERED` and the claim would otherwise succeed. A successful claim itself increments the entry's `version` by 1.

Settling or releasing a budget line requires `expected_grant_version`, equal to the funding grant's current `version` as the finance administrator last observed it. A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), because grant counters (`reserved_cents`, `spent_cents`) may have moved under the caller and the resulting status recomputation would be based on a stale baseline. Every budget-line creation, settlement, and release increments the parent `FundingGrant`'s `version` by 1, so the token genuinely rotates on each mutation.

### 2.7. Monetary Amounts and Tiered Storage Pricing

All monetary quantities are integer cents — `amount_cents`, `budget_reservation_cents`, `actual_spend_cents`, `reserved_cents`, `spent_cents`, and a crawl job's `storage_cost_cents`. Grant arithmetic is exact integer arithmetic with no rounding; the boundary between a grant's `OPEN` and `EXHAUSTED` statuses is exact equality of utilization with `amount_cents`, never an overrun.

Crawl storage pricing is the one place rounding enters, and it is pinned down precisely. Each unique capture is estimated at a fixed 524288 bytes (512 KiB). The first 1000000000 bytes of a job's unique capture volume are priced at 3 cents per 1000000 bytes; any bytes beyond that cap are priced at 1 cent per 1000000 bytes. Each tier's cost is rounded half-up to whole cents independently, and the two rounded tier costs are then summed. The bytes are never summed first and rounded once across tiers — per-tier rounding is part of the contract.

### 2.8. The Expiry Sweep

A single admin-only sweep capability drives all time-based expiry at the current logical clock. The sweep first expires loans: every `ACTIVE` loan whose `due_at` is at or before the clock transitions to `EXPIRED`, processed in order of `due_at` ascending, then `created_at` ascending for ties. Each individual loan expiry applies its full cascade — item returned to lendability, patron counters, strike accrual, possible suspension, and waitlist promotion — before the next loan is considered. The sweep then expires waitlist offers: every `OFFERED` entry whose `offer_expires_at` is at or before the clock transitions to `EXPIRED_OFFER`, processed in order of `offer_expires_at` ascending, each followed by re-promotion for the same work. The sweep's response reports four lists: `expired_loan_ids`, `expired_offer_ids`, `suspended_patron_ids`, and `offered_entry_ids` (entries newly promoted during the run).

### 2.9. Hierarchical Reads and Nested Path Validation

Several list endpoints expose children through a parent path — a patron's loans, credentials, and waitlist entries; a work's items, waitlist entries, and rights requests; a batch's items; a library's items; an item's loans; a crawl job's captures; a grant's budget lines. On every such nested path, identifiers are validated left-to-right: the parent id must resolve before the child segment is examined, and the first unresolvable id yields `ERR_NOT_FOUND`. Optional filters (`status?`, `batch_id?`, `owning_library_id?`, `patron_id?`, `subject_kind?`, `category?`, `url?`, `playback_status?`) narrow the listing but never relax the existence checks. Where the `Patron` role touches these reads, ownership applies: a patron reads only its own record, its own loans, and its own waitlist entries — the path id or the `patron_id` filter must equal `X-User-ID`, and a work's waitlist listing under the `Patron` role is implicitly restricted to that patron's own entries.

## 3. Business Logic & Workflows

### 3.1. Patron Accounts, Standing, and Accessibility

Anyone on the open internet may register as a patron: self-service account creation accepts an `email` and a `full_name`, and the email must be unique across all patrons under a case-insensitive comparison — a registration whose `email` differs from an existing one only by letter case is rejected with `ERR_DUPLICATE`. A new patron starts in status `ACTIVE` with `active_loan_count` of 0, `strike_count` of 0, and `max_concurrent_loans` of 5.

A patron's borrowing capacity is a derived quantity, not a stored setting. The base cap is 5 concurrent `ACTIVE` loans; a patron who holds at least one accessibility credential in `VERIFIED` status instead enjoys a cap of 50. The cap gates only new checkouts and waitlist claims — nothing ever closes existing loans because a cap dropped. The `active_loan_count` itself is maintained by every loan lifecycle transition: incremented at checkout and at waitlist claim, decremented at return, expiry, and revocation.

Print-disabled patrons obtain the elevated cap by submitting an accessibility credential, supplying `patron_id` — which must equal the caller's `X-User-ID`, since patrons file only for themselves — and a `certifier_reference`, an opaque reference code from the qualifying authority. The credential starts in `PENDING_REVIEW`. An `AccessibilityOfficer` then decides it: a decision of `VERIFY` moves the credential from `PENDING_REVIEW` to `VERIFIED`, a decision of `REJECT` moves it to `REJECTED`, and a decision of `REVOKE` moves a `VERIFIED` credential to `REVOKED`. On a `VERIFY` decision an officer may never act on their own credential — if the officer's `X-User-ID` equals the credential's `patron_id`, the verification is refused with `ERR_SO_DUTY_VIOLATION`. Every decision stamps `decided_by` with the officer's `X-User-ID` and `decided_at` with the current logical clock; both are null until the first decision. Verification immediately recomputes the patron's `max_concurrent_loans` to 50; revocation recomputes it back to 5 unless another `VERIFIED` credential remains for the same patron. The `REJECT` and `REVOKE` decisions carry no self-decision prohibition beyond the verify case.

Strikes are the platform's answer to unreturned loans. Only the expiry sweep ever increments `strike_count`, and nothing ever decrements it: each loan the sweep expires adds exactly one strike to the borrowing patron. The moment a patron's `strike_count` reaches exactly 3 as a consequence of a loan expiry, the patron's `status` flips from `ACTIVE` to `SUSPENDED`, and — as the fourth hop of that same cascade — every waitlist entry the patron holds in `OFFERED` status is cancelled outright. The patron record also declares a terminal `CLOSED` state for platform account closure, reachable only when the patron has no `ACTIVE` loans and carrying the side effect of cancelling all of the patron's `OPEN` or `OFFERED` waitlist entries; no v1 endpoint performs this closure.

### 3.2. Cataloging Works and Partnering Libraries

An `Admin` catalogs each bibliographic work with a `title`, an `author`, and a `publication_year`; the year must fall within 1450 through 2100 inclusive, and anything outside that range is a schema violation. A freshly cataloged work's `availability` is initialized to `AVAILABLE`. Thereafter `availability` is never set directly — it is recomputed after every rights-request transition that touches the work, per the derivation in Section 3.8.

Partner libraries are the source of physical originals. A `LibraryAdmin` registers a library with a `library_code` — a short code such as BPL-MA that must be unique across partner libraries, with duplicates refused as `ERR_DUPLICATE` — a human-readable `display_name`, and a `storage_commitment_years`, the library's long-term storage commitment in whole years, which must be at least 5. New libraries start `ACTIVE`. Withdrawal is a single atomic transition to `WITHDRAWN`, executed by a `LibraryAdmin`, and it is gated: if any scan item owned by the library is currently `ON_LOAN`, the withdrawal is rejected with `ERR_LIBRARY_HAS_ACTIVE_LOANS`. When the withdrawal succeeds, every item the library owns in `LENDABLE` or `DEPOSITED` status is retired to `RETIRED` — an availability-reducing cascade that shrinks the lendable pool without touching items out with readers.

### 3.3. Scanning Operations: Batches, Items, and Lendability

Physical scanning is organized into batches. A `ScanOperator` opens a batch by supplying an `operator_code`; the batch starts `OPEN` with `item_count` and `page_count` both 0. Items are deposited one at a time into an `OPEN` batch — depositing into a batch in any other state is `ERR_INVALID_STATE` — each deposit carrying `batch_id`, `work_id` (the cataloged work the physical item embodies), `owning_library_id` (the partner library depositing the original), a `page_count` of at least 1, and a `condition_grade` of `FINE`, `GOOD`, `FAIR`, or `FRAGILE` recording the physical condition observed at scan time. Each accepted deposit starts the item in `DEPOSITED` status and maintains the batch's aggregates: `item_count` increases by 1 and the batch's `page_count` grows by the deposited item's `page_count`.

Sealing is the gate between the scan room and the lending shelf. Sealing requires the batch to be `OPEN` and non-empty — a batch whose `item_count` is 0 cannot be sealed, and the attempt is rejected with `ERR_SEAL_EMPTY_BATCH`. A successful seal moves the batch to `SEALED` and then evaluates every `DEPOSITED` item in it: an item whose work's `availability` is `AVAILABLE` and whose owning library is `ACTIVE` advances to `LENDABLE`, and each such promotion runs waitlist promotion for the item's work, since a newly lendable copy may satisfy a waiting patron. Items whose work is embargoed or withdrawn, or whose library is no longer active, simply remain `DEPOSITED` inside the sealed batch. The batch lifecycle also declares a rejection transition — a `ScanOperator` rejecting an `OPEN` batch moves it to `REJECTED` and retires every `DEPOSITED` item it contains — but no v1 endpoint exercises it; the state machine declares it for completeness. `SEALED` is the only terminal state a v1 batch can reach.

An item's `lendable` flag is a computed projection, never stored by hand: it is true exactly when the item's own `status` is `LENDABLE`, its work's `availability` is `AVAILABLE`, and its owning library's `status` is `ACTIVE`. Any of the three legs failing flips the flag false without changing the item's stored status. The item lifecycle also declares a `LibraryAdmin`-initiated retirement transition — from `LENDABLE` the item simply moves to `RETIRED`, while retirement from `ON_LOAN` additionally revokes the active loan on that item, the loan transitioning from `ACTIVE` to `REVOKED` with the patron's `active_loan_count` decreasing by 1 and the item proceeding to `RETIRED` rather than returning to the shelf — but no v1 endpoint exposes this transition; it is declared in the state machine for completeness. When a loan instead ends by return, expiry, or a rights-driven revocation, the item comes back from `ON_LOAN` to `LENDABLE` and waitlist promotion runs for the item's work.

### 3.4. Controlled Digital Lending: Checkout, Return, Renewal

A loan is the platform's central controlled artifact: at most one `ACTIVE` loan may exist against a given item at any time — the one-copy-one-user rule — and, one level up, a patron may hold at most one `ACTIVE` loan across all items of the same work. Direct checkout is a patron operation taking `item_id`, `patron_id` (which must equal `X-User-ID`), and a `loan_kind` of `STANDARD` or `SHORT_READ`. The gauntlet runs in the fixed order of Section 2.5: the patron must be `ACTIVE` (else `ERR_PATRON_SUSPENDED`), the item's work must be `AVAILABLE` (else `ERR_WORK_UNAVAILABLE`), the item must itself be `LENDABLE` with an `ACTIVE` owning library (else `ERR_ITEM_NOT_LENDABLE`), no waitlist entry for the work may be `OPEN` or `OFFERED` — the queue always wins over a walk-up checkout, and a live queue means `ERR_WAITLIST_PRIORITY` — the patron must not already hold an `ACTIVE` loan on any other item of the same work (`ERR_WORK_ALREADY_BORROWED`), and the patron's `active_loan_count` must be strictly below `max_concurrent_loans`, so a count equal to the cap blocks with `ERR_LOAN_CAP_REACHED`. A `SHORT_READ` checkout carries one further gate: the patron must hold a credential in `VERIFIED` status, and without one the request is refused with `ERR_ACCESS_CREDENTIAL_REQUIRED`.

A successful checkout stamps `checked_out_at` with the current logical clock and sets `due_at` to 14 days after checkout for a `STANDARD` loan or exactly 1 hour after checkout for a `SHORT_READ` loan. The item moves from `LENDABLE` to `ON_LOAN`, and the patron's `active_loan_count` increases by 1. The loan's `renewed` flag starts false.

Return is the borrower's own operation and requires only that the loan be `ACTIVE` and that `X-User-ID` match the loan's `patron_id`. The loan moves from `ACTIVE` to `RETURNED`, the item comes back from `ON_LOAN` to `LENDABLE`, the patron's `active_loan_count` decreases by 1, and waitlist promotion runs for the returned item's work.

Renewal is a self-transition on an `ACTIVE` loan, available once per loan and only to `STANDARD` loans — a `SHORT_READ` loan is never renewable. Renewal is legal only when every one of these conditions holds: `renewed` is still false; the loan kind is `STANDARD`; the current logical clock is strictly before `due_at`; and no waitlist entry for the loan's work is in `OPEN` or `OFFERED` status. A failure of any of these is `ERR_LOAN_NOT_RENEWABLE`. One further absolute cap applies: the current logical clock plus 14 days must not exceed `checked_out_at` plus 42 days — total possession of the item may never stretch beyond 42 days from checkout — and a renewal that would overshoot that cap is refused with `ERR_RENEWAL_WINDOW_EXCEEDED`. When renewal succeeds, `renewed` flips to true and `due_at` is recomputed as the current logical clock plus 14 days — not the old `due_at` plus 14 days, so renewing early does not bank unused time.

### 3.5. Waitlists: Queueing, Offers, and Claims

Waitlists are per work, never per copy. A patron joins a work's queue by supplying `work_id` and `patron_id` (again equal to `X-User-ID`). The join is subject to the patron-standing gate (`ERR_PATRON_SUSPENDED`), the availability gate (`ERR_WORK_UNAVAILABLE` for an `EMBARGOED` or `WITHDRAWN` work), and a uniqueness rule: at most one entry per (`work_id`, `patron_id`) pair may be live in `OPEN` or `OFFERED` status, and a duplicate live entry is `ERR_DUPLICATE`. A new entry starts `OPEN` with `offered_at` and `offer_expires_at` both null. Joining a queue immediately runs waitlist promotion for the work, because a lendable copy may already exist.

Promotion is the queue's engine, and it runs after any of three events: a loan on the work reaches `RETURNED`, `EXPIRED`, or `REVOKED`; an item of the work becomes `LENDABLE` (batch seal or availability recovery); or an `OFFERED` entry for the work lapses. A promotion run first checks supply — if no item of the work currently has `lendable` true, the run ends with no offer. Otherwise it walks the work's `OPEN` entries oldest first, strictly by `created_at` ascending; timestamps are millisecond-unique and no tie-break on id is ever used. Each entry's patron is examined in turn. A patron who is no longer `ACTIVE` — suspended or closed — is terminally ineligible: that entry is cancelled as a cascade of the patron's standing, not of the promotion itself, and the walk continues. A patron whose `active_loan_count` has reached their `max_concurrent_loans` is transiently ineligible: the entry stays `OPEN` and is simply skipped, to be reconsidered on the next promotion run. The first eligible patron wins: the entry moves from `OPEN` to `OFFERED`, `offered_at` is stamped with the current logical clock, and `offer_expires_at` is set exactly 48 hours after `offered_at`. One promotion run issues at most one offer per work, no matter how many lendable copies remain.

Claiming is the offered patron's operation, guarded by the entry's OCC token `expected_entry_version` as described in Section 2.6. The claim requires the entry to be `OFFERED` (any other status is `ERR_INVALID_STATE`), the caller to be the entry's patron, the patron to still be `ACTIVE` (`ERR_PATRON_SUSPENDED`), the patron's loan count to be strictly below their cap (`ERR_LOAN_CAP_REACHED`), and the current logical clock to be strictly before `offer_expires_at` — a claim attempted exactly at the expiry instant is already too late and is rejected with `ERR_OFFER_EXPIRED`. The claim then selects the copy: among the work's items with `lendable` true, it picks the earliest-created one, ordered by `created_at` ascending and never by id; if no lendable item of the work remains at claim time, the claim fails with `ERR_ITEM_NOT_LENDABLE`. A successful claim creates a new loan of kind `STANDARD` against the selected item with `due_at` 14 days out, moves the item from `LENDABLE` to `ON_LOAN`, moves the entry from `OFFERED` to `CLAIMED`, increments the entry's `version` by 1, raises the patron's `active_loan_count` by 1, and runs another promotion for the same work so any remaining lendable copies feed the queue. The claim is a creation: it returns the new loan with a 201 status.

Two exits close an entry without a loan. The lifecycle declares a patron-initiated cancellation — a patron cancelling their own `OPEN` entry moves it to `CANCELLED`, and only the entry's own patron may do so — though no v1 endpoint exposes it. And when the sweep finds an `OFFERED` entry whose `offer_expires_at` has been reached, the entry moves to `EXPIRED_OFFER` and promotion runs again for the same work, giving the next eligible patron their 48-hour window. `CLAIMED`, `EXPIRED_OFFER`, and `CANCELLED` are all terminal.

### 3.6. Crawl Jobs: Scheduling, Politeness, and Exclusion

Web preservation begins with scheduling. A `CrawlOperator` schedules a job by supplying the `seed_url` of the site to crawl, a `scheduled_at` instant, a politeness limit `requests_per_minute`, and optionally the `at_risk` flag. The schedule must be strictly in the future relative to the logical clock at creation — a `scheduled_at` at or before the present is a schema violation. The politeness limit must lie between 1 and 120 requests per minute inclusive. Marking a site `at_risk` — it defaults to false — signals double capture frequency intent for the scheduler, but the politeness cap still applies in full; urgency never overrides courtesy. A new job starts `SCHEDULED` with `captures_produced`, `duplicates_skipped`, and `storage_cost_cents` all at 0.

Exclusion directives are the site's voice in the crawl pipeline. A directive records a `url_prefix` — matching is plain string-prefix comparison against the full URL — a `scope` of `CRAWL_ONLY`, `PLAYBACK_ONLY`, or `BOTH`, and a free-text `reason` kept for audit. A directive starts `ACTIVE` the moment it is created, and creation has two immediate side effects. First, every crawl job still `SCHEDULED` whose `seed_url` begins with the directive's `url_prefix` and whose scope is `CRAWL_ONLY` or `BOTH` is blocked on the spot, moving from `SCHEDULED` to `BLOCKED`. Second, when the scope is `PLAYBACK_ONLY` or `BOTH`, every existing capture whose `url` begins with the prefix has its `playback_status` set to `SUPPRESSED`. The creation response reports the new `directive_id` together with the `blocked_job_ids` it blocked and the `suppressed_capture_count` it suppressed. The exclusion is also enforced prospectively: scheduling a new job whose seed falls under an `ACTIVE` directive scoped `CRAWL_ONLY` or `BOTH` is rejected outright with `ERR_CRAWL_EXCLUDED`.

Starting a scheduled job is gated twice over. The logical clock must have reached `scheduled_at` — starting early is `ERR_SCHEDULE_NOT_DUE` — and the crawl-scoped exclusion check is run again at start time, so a directive that arrived between scheduling and starting blocks the start with `ERR_CRAWL_EXCLUDED` even though the job itself was not yet moved to `BLOCKED`. A legal start moves the job from `SCHEDULED` to `RUNNING`. Completion of a `RUNNING` job moves it to `COMPLETED` and recomputes `captures_produced` from the capture rows actually recorded against the job. The lifecycle also declares a `CrawlOperator` cancellation of a `SCHEDULED` job, moving it to `CANCELLED`, but no v1 endpoint exposes it. `COMPLETED`, `BLOCKED`, and `CANCELLED` are all terminal.

Retracting an `ACTIVE` directive moves it to `RETRACTED` and restores playback where the retracted directive was the last thing standing: every capture that had been suppressed by this directive flips its `playback_status` back to `PLAYABLE`, unless some other `ACTIVE` directive scoped for playback or an upheld rights request on a URL prefix still covers that capture's URL, in which case it stays `SUPPRESSED`.

### 3.7. Captures, Deduplication, Storage Cost, and Playback

Captures are recorded against a `RUNNING` job — attempting to record against a job in any other state is `ERR_INVALID_STATE`. Each record supplies `crawl_job_id`, the captured page's `url`, a `content_hash` (the SHA-256 hex of the normalized content), and `has_dynamic_content`, which marks pages that require client-side scripting. The capture's `captured_at` is stamped from the logical clock, and its `playback_status` starts `PLAYABLE`.

Deduplication is by the pair of `url` and `content_hash`. If a capture with the same pair already exists, no new row is created: the job's `duplicates_skipped` increases by 1, and the pre-existing capture row is returned with a 200 status instead of the 201 that accompanies a genuinely new row. A new row raises the job's `captures_produced` by 1; a dedupe hit never does.

Storage cost follows the tiered pricing of Section 2.7 and accumulates on the job as `storage_cost_cents`. The billable volume is the sum over the job's unique captures of the fixed per-capture estimate of 524288 bytes — roughly half a mebibyte each, so a job needs a little over nineteen hundred unique captures before the second tier begins to matter. The first 1000000000 bytes are charged at 3 cents per million bytes and everything beyond at 1 cent per million bytes, each tier rounded half-up to whole cents before the tiers are summed. Duplicated submissions contribute nothing to the byte total — only unique captures are billed.

Playback resolves a reader's request for a historical page. Given a `url` and an optional `requested_at` instant, the resolver first collects the candidate set: captures whose `url` exactly equals the requested URL and whose `playback_status` is `PLAYABLE`. Suppression is then evaluated live — never cached — before any candidate is served: if an `ACTIVE` exclusion directive scoped `PLAYBACK_ONLY` or `BOTH` has a `url_prefix` that is a string prefix of the requested URL, or if a rights request of subject kind `CAPTURE_URL_PREFIX` in `LEGAL_HOLD` or `UPHELD_REMOVED` status has a `url_prefix` covering the URL, the resolution is `SUPPRESSED` with no capture. Otherwise the resolver picks the snapshot. With `requested_at` omitted, the pick is the candidate with the maximum `captured_at`. With `requested_at` supplied, the pick is the candidate whose `captured_at` is nearest in absolute time, and on an exact tie between an earlier and a later capture the earlier one wins — the rule is closed on the past side — with any further tie broken by `created_at` ascending. If no candidate exists, the mode is `NOT_FOUND`. If the picked capture has `has_dynamic_content` true, the mode is `DEGRADED`; otherwise it is `FULL`. The response carries the `mode`, the chosen `capture_id` (null unless a capture was selected), its `captured_at`, and its `has_dynamic_content` flag.

### 3.8. Rights Requests: Filing, Review, Holds, and Decisions

Rights holders reach the platform through a `LegalReviewer`, who files a removal request naming a `claimant_name` and a `subject_kind` of `WORK` or `CAPTURE_URL_PREFIX`. Subject-kind consistency is enforced at the schema level: a `WORK` request must carry `work_id` and a null `url_prefix`, while a `CAPTURE_URL_PREFIX` request must carry `url_prefix` and a null `work_id`; any other combination is `ERR_VALIDATION`. The filer's `X-User-ID` is recorded as `filed_by`, and the request starts in `FILED` with `reviewed_by` and `decided_by` null. A `FILED` request has no effect on availability or playback — only `UNDER_REVIEW`, `LEGAL_HOLD`, and `UPHELD_REMOVED` requests do.

Review begins when a `LegalReviewer` moves the request from `FILED` to `UNDER_REVIEW`. Segregation of duties is absolute at this step: the reviewer's `X-User-ID` must differ from `filed_by`, because no one may review their own filing, and a breach is `ERR_SO_DUTY_VIOLATION`. The reviewer's identity is recorded as `reviewed_by`. For a `WORK` subject, beginning review immediately embargoes the work — `availability` becomes `EMBARGOED`, the `lendable` flag of the work's `LENDABLE` items flips false, and waitlist promotion skips embargoed works — but loans already `ACTIVE` are untouched, and the catalog record remains visible. A `CAPTURE_URL_PREFIX` subject sees no suppression at this stage; provisional effects attach only to works.

Escalation to `LEGAL_HOLD` is the assigned reviewer's privilege: only the operator whose `X-User-ID` equals `reviewed_by` may escalate, anyone else draws `ERR_SO_DUTY_VIOLATION`. Escalation triggers the hard-withdrawal cascade. For a `WORK` subject, `availability` becomes `WITHDRAWN` and every `ACTIVE` loan on the work's items is revoked: each such loan moves from `ACTIVE` to `REVOKED`, its item returns from `ON_LOAN` to `LENDABLE`, the borrower's `active_loan_count` decreases by 1, and waitlist promotion runs per affected work. For a `CAPTURE_URL_PREFIX` subject, every capture whose `url` begins with the request's `url_prefix` is suppressed — `playback_status` becomes `SUPPRESSED`.

Final decisions are made from either `UNDER_REVIEW` or `LEGAL_HOLD` under a two-person rule: the decider's `X-User-ID` must differ from `reviewed_by`, and the decider is recorded as `decided_by`. A decision of `UPHOLD` moves the request to `UPHELD_REMOVED` and applies exactly the same cascades as an escalation to `LEGAL_HOLD` — withdrawal with loan revocation for works, capture suppression for URL prefixes; from `LEGAL_HOLD` those cascades are already in force and the decision simply finalizes them. A decision of `DISMISS` moves the request to `DISMISSED` and triggers availability recovery: the subject work's `availability` is recomputed from scratch, and if it recovers to `AVAILABLE`, the platform re-evaluates `DEPOSITED` items in sealed batches for promotion to `LENDABLE`, each such promotion running waitlist promotion for the work in the usual way. `UPHELD_REMOVED` and `DISMISSED` are terminal.

The availability recompute itself is a pure derivation over all of a work's rights requests, in any status: if any request for the work is in `LEGAL_HOLD` or `UPHELD_REMOVED`, the work is `WITHDRAWN`; otherwise, if any request is `UNDER_REVIEW`, the work is `EMBARGOED`; otherwise the work is `AVAILABLE`. Requests in `FILED` or `DISMISSED` never influence the result. This is why a dismissal restores availability only when no other live request still holds the work down.

### 3.9. Funding Grants and Budget Lines

The platform's infrastructure runs on donated money, tracked to the cent. A `FinanceAdmin` records a funding grant with a `donor_name` and an `amount_cents` that must be strictly greater than zero. A new grant is `OPEN` with `reserved_cents` and `spent_cents` both 0.

Budget lines reserve slices of a grant for infrastructure categories — `category` is one of `STORAGE`, `BANDWIDTH`, `SCAN_LABOR`, or `PETABYTE_INSURANCE`. Creating a line supplies `grant_id`, the `category`, and a `budget_reservation_cents` strictly greater than zero; the `actual_spend_cents` field exists on the line but is ignored at creation and becomes meaningful only at settlement, where it is required and must be at least zero. Creation is gated by grant capacity: if the grant's current utilization — the sum of `reserved_cents` and `spent_cents` — plus the new reservation would be strictly greater than `amount_cents`, the line is rejected with `ERR_GRANT_EXHAUSTED`. Equality is allowed, and it matters: a reservation that brings utilization exactly to `amount_cents` flips the grant from `OPEN` to `EXHAUSTED`. Every accepted creation adds its `budget_reservation_cents` to the grant's `reserved_cents`, recomputes the grant's status, and increments the grant's `version` by 1. The line itself starts `OPEN`.

Utilization accounting is disciplined about which lines count. `reserved_cents` is the sum of `budget_reservation_cents` over the grant's lines in `OPEN` status; `spent_cents` is the sum of `actual_spend_cents` over lines in `SETTLED`; a `RELEASED` line contributes nothing to either. The grant's status is then a pure function: utilization below `amount_cents` means `OPEN`, utilization exactly equal to `amount_cents` means `EXHAUSTED`, and utilization can never exceed the amount because creation rejects overflow. `CLOSED` is reachable only by the manual close.

Settlement records what was actually spent. Settling an `OPEN` line requires `actual_spend_cents` and the OCC token `expected_grant_version` (Section 2.6). The line moves to `SETTLED`, the grant's `reserved_cents` decreases by the line's `budget_reservation_cents`, its `spent_cents` increases by the line's `actual_spend_cents`, its status is recomputed — a settle for less than the reservation can drop an `EXHAUSTED` grant back to `OPEN` — and the grant's `version` increments by 1. Release is the quieter twin: releasing an `OPEN` line requires only `expected_grant_version`, moves the line to `RELEASED`, subtracts the reservation from `reserved_cents`, recomputes the grant's status — which can likewise cycle an `EXHAUSTED` grant back to `OPEN` — and increments the grant's `version`. Both `SETTLED` and `RELEASED` are terminal.

A `FinanceAdmin` may close a grant manually, but only when nothing is still reserved: the grant must be `OPEN` or `EXHAUSTED` with `reserved_cents` exactly 0, and the close moves it to `CLOSED`, terminal.

## 4. Endpoint Definitions

New resources are returned with status 201 — including the waitlist claim, which creates a loan — while modifications to existing resources return 200. The single exception to the create-means-201 rule is capture recording, where a dedupe hit returns the pre-existing row with 200 instead. All endpoints are mounted under `/archive`. The table is a summary only; request bodies, response payloads, cascades, and preconditions are specified by the narratives of Sections 2 and 3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /archive/_clock/set_current_utc | Set the logical clock to a supplied `to_iso8601` instant | Admin |
| POST | /archive/_sweeps/run | Run the expiry sweep at the current logical clock | Admin |
| POST | /archive/patrons | Register a patron account | Anonymous |
| GET | /archive/patrons/{id} | Read a patron record (self only for patrons) | Admin, Patron |
| POST | /archive/accessibility-credentials | Submit a print-disabled qualification credential | Patron |
| GET | /archive/patrons/{id}/accessibility-credentials | List a patron's credentials, filterable by `status` | Admin, AccessibilityOfficer |
| GET | /archive/accessibility-credentials/{id} | Read a single credential | Admin, AccessibilityOfficer |
| POST | /archive/accessibility-credentials/{id}/decide | Decide a credential (`decision`: VERIFY, REJECT, REVOKE) | AccessibilityOfficer |
| POST | /archive/partner-libraries | Register a partner library | LibraryAdmin |
| GET | /archive/partner-libraries/{id} | Read a partner library | Admin, LibraryAdmin |
| POST | /archive/partner-libraries/{id}/withdraw | Withdraw a partner library and retire its idle items | LibraryAdmin |
| POST | /archive/works | Catalog a bibliographic work | Admin |
| GET | /archive/works/{id} | Read a work including its computed `availability` | Admin, LibraryAdmin, Patron |
| POST | /archive/scan-batches | Open a physical scanning batch | ScanOperator |
| GET | /archive/scan-batches/{id} | Read a scan batch | Admin, ScanOperator |
| POST | /archive/scan-batches/{id}/seal | Seal a non-empty batch and promote eligible items | ScanOperator |
| POST | /archive/items | Deposit a scanned item into an open batch | ScanOperator |
| GET | /archive/items/{id} | Read a scan item including its computed `lendable` flag | Admin, LibraryAdmin, ScanOperator, Patron |
| GET | /archive/works/{id}/items | List a work's scan items, filterable by `batch_id`, `owning_library_id`, `status` | Admin, LibraryAdmin, ScanOperator, Patron |
| GET | /archive/scan-batches/{id}/items | List a batch's scan items, filterable by `status` | Admin, ScanOperator |
| GET | /archive/partner-libraries/{id}/items | List a library's scan items, filterable by `status` | Admin, LibraryAdmin |
| POST | /archive/loans | Direct checkout of a lendable item | Patron |
| GET | /archive/patrons/{id}/loans | List a patron's loans, filterable by `status` (self only for patrons) | Admin, Patron |
| GET | /archive/items/{id}/loans | List an item's loans, filterable by `status` | Admin |
| GET | /archive/loans/{id} | Read a single loan (self only for patrons) | Admin, Patron |
| POST | /archive/loans/{id}/return | Return an active loan | Patron |
| POST | /archive/loans/{id}/renew | Renew an active standard loan once | Patron |
| POST | /archive/waitlist-entries | Join a work's waitlist | Patron |
| GET | /archive/works/{id}/waitlist-entries | List a work's waitlist entries, filterable by `patron_id`, `status` | Admin, Patron |
| GET | /archive/patrons/{id}/waitlist-entries | List a patron's waitlist entries, filterable by `status` (self only for patrons) | Admin, Patron |
| GET | /archive/waitlist-entries/{id} | Read a single waitlist entry (self only for patrons) | Admin, Patron |
| POST | /archive/waitlist-entries/{id}/claim | Claim an offered entry, creating a loan | Patron |
| POST | /archive/crawl-jobs | Schedule a crawl job | CrawlOperator |
| GET | /archive/crawl-jobs/{id} | Read a crawl job with its counters and storage cost | Admin, CrawlOperator |
| POST | /archive/crawl-jobs/{id}/start | Start a scheduled job whose schedule is due | CrawlOperator |
| POST | /archive/crawl-jobs/{id}/complete | Complete a running job and recompute its metrics | CrawlOperator |
| POST | /archive/captures | Record a capture against a running job, with dedupe | CrawlOperator |
| GET | /archive/crawl-jobs/{id}/captures | List a job's captures, filterable by `url`, `playback_status` | Admin, CrawlOperator |
| GET | /archive/captures/{id} | Read a single capture | Admin, CrawlOperator |
| GET | /archive/playback | Resolve playback for a `url`, optionally nearest to `requested_at` | Admin, CrawlOperator, Patron, LibraryAdmin |
| POST | /archive/exclusion-directives | Create an exclusion directive with immediate blocking/suppression | CrawlOperator |
| POST | /archive/exclusion-directives/{id}/retract | Retract an active directive and restore uncovered captures | CrawlOperator |
| POST | /archive/rights-requests | File a rights-holder removal request | LegalReviewer |
| GET | /archive/works/{id}/rights-requests | List a work's rights requests, filterable by `status`, `subject_kind` | Admin, LegalReviewer |
| GET | /archive/rights-requests/{id} | Read a single rights request | Admin, LegalReviewer |
| POST | /archive/rights-requests/{id}/begin-review | Begin review of a filed request (filer excluded) | LegalReviewer |
| POST | /archive/rights-requests/{id}/escalate-hold | Escalate a request under review to legal hold (assigned reviewer only) | LegalReviewer |
| POST | /archive/rights-requests/{id}/decide | Final decision (`decision`: UPHOLD or DISMISS), decider differing from reviewer | LegalReviewer |
| POST | /archive/funding-grants | Record a donation grant | FinanceAdmin |
| GET | /archive/funding-grants/{id} | Read a grant with counters, status, and OCC version | FinanceAdmin, Admin |
| POST | /archive/budget-lines | Reserve infrastructure budget against a grant | FinanceAdmin |
| GET | /archive/funding-grants/{id}/budget-lines | List a grant's budget lines, filterable by `status`, `category` | FinanceAdmin, Admin |
| GET | /archive/budget-lines/{id} | Read a single budget line | FinanceAdmin, Admin |
| POST | /archive/budget-lines/{id}/settle | Settle an open line at its `actual_spend_cents` | FinanceAdmin |
| POST | /archive/budget-lines/{id}/release | Release an open line, returning its reservation | FinanceAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of Sections 2 and 3; this table fixes only the identifier-to-status mapping.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_VALIDATION | 400 |
| ERR_INVALID_STATE | 409 |
| ERR_SO_DUTY_VIOLATION | 403 |
| ERR_STALE_VERSION | 412 |
| ERR_PATRON_SUSPENDED | 403 |
| ERR_WORK_UNAVAILABLE | 409 |
| ERR_ITEM_NOT_LENDABLE | 409 |
| ERR_WAITLIST_PRIORITY | 409 |
| ERR_WORK_ALREADY_BORROWED | 409 |
| ERR_LOAN_CAP_REACHED | 409 |
| ERR_ACCESS_CREDENTIAL_REQUIRED | 403 |
| ERR_SCHEDULE_NOT_DUE | 409 |
| ERR_CRAWL_EXCLUDED | 409 |
| ERR_OFFER_EXPIRED | 409 |
| ERR_LOAN_NOT_RENEWABLE | 409 |
| ERR_RENEWAL_WINDOW_EXCEEDED | 409 |
| ERR_GRANT_EXHAUSTED | 409 |
| ERR_LIBRARY_HAS_ACTIVE_LOANS | 409 |
| ERR_DUPLICATE | 409 |
| ERR_SEAL_EMPTY_BATCH | 409 |
