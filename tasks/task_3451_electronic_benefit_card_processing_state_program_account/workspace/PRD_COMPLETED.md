# EBT State Benefits API — Product Requirements Document

## 1. Introduction

This document specifies the Electronic Benefit Card Processing and State Program Account Operations platform: the system a benefits processor operates on behalf of a state to run food, cash, and disaster assistance programs on a single card-based account infrastructure. A state contract is the root of all configuration. It pins the posting schedule that staggers benefit availability across the month by case identifier, the inactivity period after which unused benefits are expunged, the notice owed to households before that happens, the card replacement fee schedule, the personal identification number lockout policy, the skimming-claim filing and provisional-credit timelines, the retailer integrity threshold, and the settlement and dispute terms under which retailers are paid through their acquirers. Against that configuration the system runs the daily operational life of the program: issuing, mailing, activating, and replacing cards; posting monthly allotments; enforcing eligible-item restrictions at the point of sale through retailer item files; investigating skimming claims with provisional and final credits; settling transactions into acquirer batches and reconciling them; and delivering daily transaction files and monthly program-integrity reports back to the state.

Two design commitments shape everything that follows. First, all money is ledgered. Every benefit credit, purchase debit, withdrawal debit, fee, reversal, expungement, expiry, and claim credit is an append-only entry on a program-specific purse, and every balance the API reports is a computation over that ledger rather than a stored number. Second, all time is logical. The system never reads the wall clock; a single test-driving endpoint advances a logical clock, and every scheduled behavior — posting availability, disaster expiry, expungement, card mailing, provisional credit, settlement cutoff, and monthly reporting — is a sweep step that runs in a pinned order when the logical clock crosses the relevant boundary.

Section 2 defines the system-wide contract: roles, response envelopes, pagination, the clock, resource conventions, balance semantics, validation ordering, concurrency control, and configuration defaults. Section 3 narrates the business workflows, scattering the detailed rules into the lifecycles they govern. Section 4 lists the endpoints, and Section 5 catalogues the error codes.

## 2. Global Specifications & System-Wide Principles

This section defines the rules, representations, and defaults that apply uniformly across the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting party, and `X-User-Role`, declaring the capacity in which it acts. The system recognizes exactly four roles, spelled exactly as follows: `StateAdmin`, `CardholderServices`, `Cardholder`, and `RetailerSystem`. A request missing either header, or presenting a role value outside those four, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is not among the roles authorized for the endpoint is rejected with `ERR_FORBIDDEN`.

The meaning of `X-User-ID` depends on the role presented:

- When `X-User-Role` is `StateAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example as `decided_by_user_id` on a skimming claim when a state administrator adjudicates it — but does not compare it to any entity's `id`.
- When `X-User-Role` is `CardholderServices`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity. It is recorded as `filed_by_user_id`, with `filed_by_role` set to `CardholderServices`, when the representative files a skimming claim, and it drives the segregation-of-duties check described in Section 3.8, but it is never compared to any entity's `id`.
- When `X-User-Role` is `Cardholder`, `X-User-ID` is the `id` of the acting `CaseAccount`; ownership checks on any resource that references a case compare the resource's case foreign-key field to `X-User-ID`, and a cardholder touching another case's resources is rejected with `ERR_FORBIDDEN`.
- When `X-User-Role` is `RetailerSystem`, `X-User-ID` is the `id` of the acting `Retailer`; the retailer identified in the request path, the retailer that owns a transaction being voided, and the retailer filing a settlement dispute must each equal `X-User-ID`, or the request is rejected with `ERR_FORBIDDEN`.

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

Endpoints that return lists of resources accept two query parameters. The `limit` parameter specifies the maximum number of items to return; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0. A `limit` or `offset` value that is not an integer, a `limit` below 1 or above 100, or a negative `offset` is rejected with `ERR_INVALID_REQUEST`.

Unless otherwise specified, all list endpoints return resources sorted by their `created_at` timestamp in ascending order. Two lists document their own orderings, both consistent with this principle: a purse's benefit postings are returned ordered by `available_at` ascending with ties broken by `created_at` ascending, and a settlement batch's `settled_authorization_ids` preserves the `created_at` ascending order of the transactions that settled into it.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and the Seven-Step Sweep

The system keeps a single logical clock. At server startup, before any clock-setting call, the clock reads exactly `2026-09-01T00:00:00Z`; it never falls back to wall-clock time. Time advances only through the test-driving endpoint `POST /_clock/set_current_utc`. That endpoint is mounted outside the `/ebt` API prefix: every business endpoint in this document lives under `/ebt`, but the clock endpoint's full path is exactly `/_clock/set_current_utc` with no prefix. It is restricted to `StateAdmin`, takes a single request-body field `to_iso8601`, and returns 200 with the resulting `current_utc`. The `to_iso8601` value may carry any ISO 8601 offset — a value with no offset is read as UTC — and is normalized to UTC before comparison and storage; a missing, empty, or unparseable value is rejected with `ERR_INVALID_REQUEST`. The clock is forward-only: a `to_iso8601` earlier than the current clock value is rejected with `ERR_INVALID_REQUEST`, while one exactly equal to the current clock value is accepted and still runs the sweep once.

Every clock set runs the scheduled-action sweep pipeline exactly once per call, in this pinned order:

1. Posting availability, including the reactivation of `DORMANT` cases (Section 3.4).
2. Disaster expiry, computing each expiring posting's unspent portion by first-in-first-out allocation (Section 3.5).
3. Expungement notices and expungement, including the dormancy cascade and card deactivation (Section 3.5).
4. Card mailing (Section 3.6).
5. Provisional-credit auto-issuance (Section 3.8).
6. Settlement cutoff batches and the daily transaction files (Sections 3.9 and 3.10).
7. Monthly integrity reports (Section 3.10).

When a single clock set crosses more than one day boundary, the pipeline runs once per crossed boundary in chronological order and once more at the target instant, so a multi-day jump behaves exactly as the corresponding sequence of single-day advances. The crossed boundaries are the union of every contract's daily settlement-cutoff instants (each contract's boundary recurs at its own `settlement_cutoff_hour_utc`), and at every such instant — boundary or target — all seven steps run in the pinned order above. Each contract tracks its settlement days and report months from its own creation, so no batch, transaction file, or integrity report is ever emitted for a period that closed before the contract existed.

The sweep runs while the clock still reads its pre-advance value; the clock lands on the target only after every step has run. Resources a sweep step creates — settlement batches and data deliveries — therefore record that pre-advance clock value as their `created_at`, and every resource a sweep step mutates takes that same value as its `updated_at`, while the instant-valued fields a sweep step stamps — a posting's `resolved_at`, a card's `mailed_at`, a claim's `provisional_credited_at`, a purse's `expungement_notice_sent_at`, a batch's `cutoff_at`, and the `created_at` of sweep-posted ledger entries (which in turn sets the purse's `last_activity_at`) — record the crossed-boundary or target instant at which that step ran.

### 2.5. Common Resource Properties and the Append-Only Ledger

Every primary resource carries a standard set of system-managed fields: `id`, a server-minted UUID with no type prefix, rendered in the canonical hyphenated hexadecimal form — five dash-separated groups in an 8-4-4-4-12 pattern, as in `550e8400-e29b-41d4-a716-446655440000`; `created_at`, an ISO 8601 UTC timestamp with three fractional digits recording creation; `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation; and `version`, an integer that increments by 1 on every mutation and supports optimistic concurrency control where Section 2.10 applies.

The single exception is the ledger entry. Ledger rows are immutable and append-only, so a `LedgerEntry` carries only `id` and `created_at`; both `updated_at` and `version` are absent. Every ledger row records its owning `purse_id`, an `entry_type`, and a positive integer `amount_cents` — the amount is always strictly greater than zero, and the sign of an entry derives entirely from its type. Because no entry may carry a zero amount, an operation whose computed ledger amount is zero posts no entry at all — a zero assessed replacement fee, a zero adjudication delta, a zero provisional credit (for example under a zero cap), a zero unspent disaster portion, or a zero expungement balance each skip their ledger entry while every other effect of the operation (status flips, stamps, and flags) still applies. A row may also carry `posting_id` (an informational reference to the benefit posting the entry credits or debits, null when not posting-related), `reference_id` (an informational authorization, claim, or card id kept for audit), and a short system `memo` such as "replacement fee" or "expungement sweep". The `entry_type` is exactly one of twelve values: `POST_CREDIT`, `PURCHASE_DEBIT`, `WITHDRAWAL_DEBIT`, `FEE_DEBIT`, `VOID_CREDIT`, `FORFEIT_DEBIT`, `EXPIRY_DEBIT`, `EXPUNGE_DEBIT`, `PROVISIONAL_CREDIT`, `PROVISIONAL_REVERSAL_DEBIT`, `CLAIM_CREDIT`, or `CLAIM_REVERSAL_DEBIT`.

Any new ledger entry on a purse sets that purse's `last_activity_at` to the entry's `created_at` and clears the purse's `expungement_notice_sent_at` back to null. This is the only channel through which those two fields change.

### 2.6. Money, Precision, and Rounding

All monetary quantities in the system are integer cents; no fractional cents exist anywhere. Where a computation produces a fractional cent, the rule is round half up to the nearest whole cent, and rounding happens at exactly two places in the system: first-month benefit proration, which rounds the prorated amount half up exactly once (Section 3.4), and the acquirer fee, which rounds each transaction's fee half up before the per-transaction fees are summed (Section 3.9). Date and hour arithmetic for posting schedules is exact UTC calendar arithmetic with no rounding. All timestamps are ISO 8601 UTC with three fractional digits, and all dates the system compares are UTC calendar dates.

### 2.7. Two Balance Views: Ledger and Spendable

Every purse exposes two computed balances, both derived from its ledger at read time.

`ledger_balance_cents` is the signed sum over all of the purse's ledger entries: the four credit types (`POST_CREDIT`, `VOID_CREDIT`, `PROVISIONAL_CREDIT`, `CLAIM_CREDIT`) count positive, and the eight debit types (`PURCHASE_DEBIT`, `WITHDRAWAL_DEBIT`, `FEE_DEBIT`, `FORFEIT_DEBIT`, `EXPIRY_DEBIT`, `EXPUNGE_DEBIT`, `PROVISIONAL_REVERSAL_DEBIT`, `CLAIM_REVERSAL_DEBIT`) count negative.

`spendable_balance_cents` is the signed sum over the same rows, except that two categories are excluded: (a) `POST_CREDIT` entries whose linked posting is currently in `SCHEDULED` or `FORFEITED` status, and (b) all `FORFEIT_DEBIT` entries. Equivalently, the spendable balance equals the ledger balance minus the `POST_CREDIT` amounts of postings currently `SCHEDULED`, minus the `POST_CREDIT` amounts of postings currently `FORFEITED`, plus the amounts of all `FORFEIT_DEBIT` entries.

The two views answer different questions, and which view a rule uses is part of the rule. The ledger view is the audit view: it drives expungement zeroing and the zero-balance precondition on case closure, and it counts future money — credits whose posting is still `SCHEDULED`. The spendable view is the point-of-sale view: purchase and withdrawal sufficiency checks, replacement-fee absorption checks, and the balance-inquiry display all use it, so scheduled money is invisible until availability, while expunged or expired money is fully removed in both views. The lifecycle cross-checks that follow from the definition: while a posting is `SCHEDULED`, its credit raises only the ledger balance; once `AVAILABLE`, it raises both; when a `SCHEDULED` posting is forfeited, its credit and the reversing `FORFEIT_DEBIT` cancel in the ledger view and are both excluded from the spendable view; when an `AVAILABLE` posting is expunged or expires, its credit and the expunge or expiry debit cancel in both views.

### 2.8. The Validation Pipeline and Error Priority

Incoming requests are validated against an ordered pipeline, and when several checks would fail at once, the earliest check in this order determines the error returned. The order is:

1. Authentication: both headers present and the role declared, else `ERR_UNAUTHENTICATED`.
2. Role authorization: the acting role is listed for the endpoint, else `ERR_FORBIDDEN`.
3. Path existence: path-template resources exist, validated left to right, else `ERR_NOT_FOUND`.
4. Ownership and tenancy: a `Cardholder` may only touch resources of the case whose `id` equals `X-User-ID`, and a `RetailerSystem` may only act as or on the retailer whose `id` equals `X-User-ID`, else `ERR_FORBIDDEN`.
5. Body references: every request-body reference exists, else `ERR_REFERENCE_NOT_FOUND`.
6. Optimistic concurrency: a stale `expected_case_account_version` is rejected with `ERR_STALE_VERSION` (Section 2.10).
7. Generic transition legality: the target resource is in a from-state the requested transition allows, else `ERR_INVALID_STATE`; terminal resources reject all further transitions this way.
8. Contract-active gate, else `ERR_CONTRACT_NOT_ACTIVE`.
9. Case-open gate, else `ERR_CASE_NOT_OPEN`.
10. Retailer-approved gate, else `ERR_RETAILER_NOT_ACTIVE`.
11. Card-mailed gate for activation, else `ERR_CARD_NOT_MAILED`.
12. Card-active gate for authorizations, else `ERR_CARD_NOT_ACTIVE`.
13. Frozen-purse gate: no purse to be debited may be `FROZEN`, else `ERR_PURSE_FROZEN`.
14. Card-state gate for replacement and PIN reset, else `ERR_REPLACEMENT_NOT_ALLOWED`.
15. Voidable-transaction gate, else `ERR_TXN_NOT_VOIDABLE`.
16. Open-dispute gate for reconciliation, else `ERR_BATCH_HAS_OPEN_DISPUTES`.
17. Closure-obligation gates: `ERR_CASE_HAS_OPEN_CLAIMS` on case closure and `ERR_CONTRACT_HAS_OPEN_OBLIGATIONS` on contract closure.
18. PIN verification, else `ERR_PIN_MISMATCH` or the short-circuit `ERR_PIN_LOCKED` (Section 3.6).
19. Field formats and request shape: `ERR_INVALID_REQUEST` plus the dedicated format identifiers `ERR_CASE_IDENTIFIER_INVALID`, `ERR_UPC_INVALID`, and `ERR_WITHDRAWAL_MULTIPLE`.
20. Interval and uniqueness constraints: `ERR_ITEM_WINDOW_OVERLAP`, `ERR_DISASTER_WINDOW_OVERLAP`, `ERR_PROGRAM_TYPE_DUPLICATE`, and `ERR_CASE_IDENTIFIER_DUPLICATE`.
21. Temporal windows: `ERR_VOID_WINDOW_EXPIRED`, `ERR_CLAIM_WINDOW_EXPIRED`, `ERR_DISPUTE_WINDOW_EXPIRED`, and `ERR_POSTING_MONTH_INVALID`.
22. Cross-reference rules: `ERR_CLAIM_TXN_CASE_MISMATCH` and `ERR_DUPLICATE_POSTING_RUN`.
23. Funds and limits: `ERR_INSUFFICIENT_FUNDS`, `ERR_DAILY_LIMIT_EXCEEDED`, `ERR_NO_CASH_PURSE`, `ERR_ITEM_NOT_ELIGIBLE`, `ERR_CLAIM_AMOUNT_EXCEEDS_REFERENCED`, and `ERR_CASE_BALANCE_NONZERO`.

Two consequences of this ordering are worth stating plainly. A state rejection always beats a fiscal one: a debit that would hit a `FROZEN` purse surfaces `ERR_PURSE_FROZEN` even when that purse also lacks funds. And on case closure, the open-claims check (step 17) fires before the zero-balance check (step 23), so a case with both problems reports `ERR_CASE_HAS_OPEN_CLAIMS`. Three envelope-level rules sit outside the numbered pipeline: a request to an unknown path, or to a known path with an unsupported method, is rejected with `ERR_NOT_FOUND`; a malformed or non-object JSON body is rejected with `ERR_INVALID_REQUEST`; and on every status endpoint a `to` value outside the target resource's state vocabulary is rejected with `ERR_INVALID_REQUEST` before transition legality is evaluated, while a vocabulary member the current state cannot reach is rejected with `ERR_INVALID_STATE`.

### 2.9. Nested Resource Retrieval and Reference Integrity

For any endpoint whose path contains resource identifiers, the system validates the existence of each identifier in sequential left-to-right order and rejects the request with `ERR_NOT_FOUND` at the first identifier that does not correspond to an existing resource. Request-body references are validated next: `contract_id`, `case_account_id`, `card_id`, `settlement_batch_id`, and every element of a claim's `authorization_ids` must each identify an existing resource, or the request is rejected with `ERR_REFERENCE_NOT_FOUND`.

Several stored references are informational rather than navigable. A transaction's `case_account_id` and `card_id` are captured at authorization time, a ledger row's `posting_id` and `reference_id` are audit pointers, a card's `replacement_of_card_id` records replacement lineage (traceable through the case's card list rather than by direct lookup), a dispute's `retailer_id` records the filer, and a settled transaction's `batch_id` records which batch absorbed it. None of these guarantees reverse lookup.

### 2.10. Optimistic Concurrency Control

Exactly one write endpoint is version-guarded: the case status change. A request to change a case account's status must carry `expected_case_account_version` as a non-optional field, holding the `version` the client last observed on the case. If the supplied value no longer matches the case's current `version` — because another writer has advanced the case's version since the client last read it, for example through a legal transition such as `SUSPENDED` to `OPEN` — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from acting on a stale view of the account. No other endpoint takes a version field; card, claim, settlement, dispute, contract, and clock mutations apply without an optimistic-concurrency check.

### 2.11. Contract Configuration: Defaults, Constraints, and Program Overrides

A state contract carries the deployment's operating parameters. Each has a pinned default that applies when the creation request does not override it, and each override is validated against the stated constraint:

- `default_posting_modulus` — the posting-schedule modulus; default 10; must be between 1 and 28 inclusive.
- `default_availability_hour_utc` — the UTC hour at which a posting becomes spendable on its available date; default 6; between 0 and 23 inclusive.
- `default_expungement_inactivity_days` — days without ledger activity after which a food or cash purse is expunged; default 90; at least 31.
- `expungement_notice_lead_days` — days before expungement eligibility at which the notice is recorded; default 30; at least 1.
- `default_disaster_expiry_days` — days after `available_at` at which a disaster posting expires; default 30; at least 1.
- `default_replacement_fee_cents` — the card replacement fee charged when a program does not override it; default 250 cents; at least 0.
- `free_replacements_per_365d` — free card replacements per case per trailing 365-day window; default 1; at least 0.
- `pin_max_failures` — consecutive PIN mismatches that lock a card; default 3; at least 1.
- `claim_window_days` — the skimming-claim filing window measured from each referenced transaction's `created_at`; default 60 days; at least 1.
- `provisional_credit_delay_days` — days a claim may remain under investigation before provisional credit is auto-issued; default 10; at least 1.
- `provisional_credit_cap_cents` — the maximum provisional credit per claim; default 50000 cents; at least 0.
- `skimming_suspend_threshold` — lifetime substantiated-claim incidents at which a retailer is auto-suspended; default 3; at least 1.
- `dispute_window_days` — days after a batch's `cutoff_at` during which a retailer dispute may be filed, with an inclusive boundary; default 15; at least 1.
- `acquirer_fee_basis_points` — the per-transaction acquirer fee in basis points of the transaction's `total_cents`; default 75; at least 0.
- `cash_withdrawal_daily_limit_cents` — the per-case cumulative cash-withdrawal limit per UTC calendar day; default 50000 cents; at least 0.
- `cash_withdrawal_multiple_cents` — cash withdrawals must be exact multiples of this amount; default 500 cents; at least 1.
- `settlement_cutoff_hour_utc` — the UTC hour of the daily settlement cutoff; default 0; between 0 and 23 inclusive. A settlement day runs from the cutoff hour on one day to the cutoff hour on the next, including the start instant and excluding the end instant.
- `card_mail_delay_hours` — hours after issuance at which a card flips from `ISSUED` to `MAILED` on a clock sweep; default 24; at least 0.

Five of these parameters accept a per-program override, stored on the program as a value or null: `posting_modulus`, `availability_hour_utc`, `expungement_inactivity_days`, `disaster_expiry_days`, and `replacement_fee_cents`. A null override means the program inherits the contract default. Two overrides are program-type-scoped: `expungement_inactivity_days` is ignored for `DISASTER` programs (disaster purses are exempt from expungement), and `disaster_expiry_days` is consulted only for `DISASTER` programs. A non-integer value, or one violating the stated constraint, for any of these fields — at contract creation or as a program override — is rejected with `ERR_INVALID_REQUEST`, and each program override is validated against the same constraint as its contract-level counterpart.

## 3. Business Logic & Workflows

### 3.1. Standing Up a State Contract and Its Programs

A `StateAdmin` opens a deployment by creating a state contract, supplying the two-letter uppercase `state_code` — exactly two capital letters — and optionally overriding any of the configuration parameters of Section 2.11. The contract's `contract_status` is born `CONFIGURING`.

While the contract is `CONFIGURING`, the administrator defines its benefit programs. Creating a program requires the `contract_id` and a `program_type` of `FOOD`, `CASH`, or `DISASTER`, and accepts the optional per-program overrides `posting_modulus`, `availability_hour_utc`, `expungement_inactivity_days`, `disaster_expiry_days`, and `replacement_fee_cents`, plus the `item_restriction_mode` — `STRICT` or `LENIENT`, defaulting to `STRICT` and consulted only for `FOOD` programs. A `DISASTER` program must also carry `disaster_window_start` and `disaster_window_end` as ISO dates forming a closed interval whose end is on or after its start; both fields are required for `DISASTER` programs and forbidden for the other two types. Program type is constrained per contract: at most one `FOOD` and at most one `CASH` program may exist, and a second of either is rejected with `ERR_PROGRAM_TYPE_DUPLICATE`. `DISASTER` programs may repeat, but their closed windows may not touch or overlap another `DISASTER` window of the same contract — unlike item windows, even adjacency conflicts, where adjacency means beginning the day immediately after the other window's end: a proposed window conflicts whenever its start falls on or before the day after an existing window's end and its end falls on or after the day before that existing window's start, so two `DISASTER` windows of the same contract must leave at least one full calendar day belonging to neither between them — and a violation is rejected with `ERR_DISASTER_WINDOW_OVERLAP`.

Program creation is the one operation permitted in two contract states: the contract must be `CONFIGURING` or `ACTIVE`, and a contract in any other state rejects program creation with `ERR_CONTRACT_NOT_ACTIVE`. Field violations on creation — an unknown `program_type` or `item_restriction_mode`, a disaster window missing where required or present where forbidden, an unparseable window date, a window end before its start, or an override outside its constraint — are rejected with `ERR_INVALID_REQUEST`. A program created while its contract is `CONFIGURING` is born with `program_status` `DRAFT`; a program created while its contract is already `ACTIVE` is born `ACTIVE`, and at that moment one `OPEN` purse is created for every case account of the contract whose `account_status` is `OPEN`, `SUSPENDED`, or `DORMANT`.

Activating the contract — driving `contract_status` from `CONFIGURING` to `ACTIVE` — requires that at least one benefit program exists for the contract in any program status — the attempt is rejected with `ERR_INVALID_STATE` when none does — and flips every `DRAFT` program of the contract to `ACTIVE` as a cascade. This request, like every status-driving request in the system — for contracts, cases, retailers, claims, and disputes alike — carries a single `to` field naming the target state. An active contract may be suspended (`ACTIVE` to `SUSPENDED`) and reinstated (`SUSPENDED` to `ACTIVE`) without preconditions. Every other business operation is stricter than program creation: case creation, retailer onboarding, item-file upload, allotment runs, and authorizations each require the contract to be `ACTIVE` and are otherwise rejected with `ERR_CONTRACT_NOT_ACTIVE`.

Closing a contract — from `ACTIVE` or `SUSPENDED` to `CLOSED`, which is terminal — carries three obligation preconditions, each surfaced as `ERR_CONTRACT_HAS_OPEN_OBLIGATIONS`: every case account of the contract must already be `CLOSED`, no settlement batch of the contract may remain in `CUTOFF` or `DISPUTED`, and no skimming claim of the contract may remain in `FILED` or `UNDER_INVESTIGATION`. Every contract status change increments the contract's `version` by 1.

### 3.2. Retailer Onboarding and Item Eligibility

A `StateAdmin` onboards a retailer into an `ACTIVE` contract by supplying the retailer's `retailer_name` and `acquirer_reference` — a non-empty acquirer identifier that later groups settlement batches. The retailer is born with `retailer_status` `APPROVED` and a `skimming_incident_count` of 0.

The retailer then maintains its item-eligibility file. A `RetailerSystem` actor uploads a file for its own retailer as an atomic operation: the file is an `items` list in which every entry carries a `upc` (exactly twelve decimal digits), a `food_eligible` flag marking whether the item may be charged to a food or disaster purse, an `effective_from` date at which eligibility begins (inclusive), and an optional `effective_to` date at which eligibility ends (exclusive); a null `effective_to` is open-ended and treated as 9999-12-31. Every entry is validated, and any failure rejects the whole file: a `upc` failing the twelve-digit format rejects the file with `ERR_UPC_INVALID`, and an entry whose half-open window — running from `effective_from` inclusive up to but not including `effective_to` — overlaps an existing record for the same `retailer_id` and `upc` pair is rejected with `ERR_ITEM_WINDOW_OVERLAP`, where pure adjacency is allowed; the same overlap rule is also applied pairwise among the file's own entries, and an `effective_to` on or before its `effective_from` is rejected with `ERR_INVALID_REQUEST`. A successful upload responds 201 with a body reporting `created_count`. Uploads require the contract `ACTIVE` and the retailer `APPROVED`, failing with `ERR_CONTRACT_NOT_ACTIVE` or `ERR_RETAILER_NOT_ACTIVE` respectively.

Each stored item record exposes a computed `item_status`: `ACTIVE` when the current clock's UTC date is on or after `effective_from` and strictly before `effective_to` (or `effective_to` is null), and `EXPIRED` otherwise — a single value covering both not-yet-effective and already-ended records. The point-of-sale rules of Section 3.7 consult the record covering the current clock date.

Retailer status itself is managed two ways. A `StateAdmin` may suspend an `APPROVED` retailer or reinstate a `SUSPENDED` one, incrementing the retailer's `version` by 1 on each change; the skimming cascade of Section 3.8 suspends a retailer automatically. A `SUSPENDED` retailer rejects new authorizations and item-file uploads with `ERR_RETAILER_NOT_ACTIVE`, while its existing transactions and settlement batches are unaffected. `APPROVED` and `SUSPENDED` are the only two retailer states, and neither is terminal.

### 3.3. Case Accounts, Purses, and the Ledger

A `StateAdmin` opens a case account within an `ACTIVE` contract by supplying the `contract_id`, a `case_identifier`, and the `head_of_household_name`. The `case_identifier` is exactly ten decimal digits; a malformed identifier is rejected with `ERR_CASE_IDENTIFIER_INVALID`, and one that already exists within the same contract is rejected with `ERR_CASE_IDENTIFIER_DUPLICATE`. The case is born with `account_status` `OPEN`, and one `OPEN` purse is created immediately for every `ACTIVE` program of the contract. The digits of `case_identifier` are not cosmetic: they drive the posting bucket of Section 3.4.

Each purse ties its `case_account_id` to a `program_id`, is born with `purse_status` `OPEN`, tracks `last_activity_at` (null until the purse's first ledger entry) and `expungement_notice_sent_at` (null until a notice is recorded), and exposes the two computed balances of Section 2.7. A balance inquiry returns the purse with both `ledger_balance_cents` and `spendable_balance_cents` plus the expungement-notice fields. The purse's ledger is the append-only record of Section 2.5, listed in `created_at` ascending order and filterable by `entry_type`; its postings are listed in `available_at` ascending order with `created_at` ascending as the tie-break, filterable by `posting_status`. When listing purses, a `Cardholder` must filter to their own case and may only ever see purses of the case whose `id` equals their `X-User-ID`; likewise a cardholder reads only their own case, their own cards, and their own claims.

A `StateAdmin` may suspend an `OPEN` case (`OPEN` to `SUSPENDED`) and reinstate it (`SUSPENDED` to `OPEN`) without preconditions. Suspension is an administrative hold: purses of a `SUSPENDED` case are skipped by allotment runs, and the case-open gate of Section 2.8 blocks authorizations, claim filing, card issuance, card activation, and card replacement for the case with `ERR_CASE_NOT_OPEN` while the hold lasts. The `DORMANT` state is system-managed through expungement (Section 3.5) rather than reachable by request. Every case exposes a computed `replacements_in_window`: the count of the case's cards whose `replacement_of_card_id` is not null and whose `created_at` falls within the trailing 365 days before the current clock — the input to the replacement-fee waterfall of Section 3.6.

### 3.4. Allotment Runs and the Posting Lifecycle

Benefits reach purses through allotment runs. A `StateAdmin` executes a run against an `ACTIVE` contract by naming a `program_id`, a `benefit_month` in `YYYY-MM` form, and the run's `amount_cents`. The `program_id` must identify a program of the path contract — one that does not exist, or that belongs to a different contract, is rejected with `ERR_REFERENCE_NOT_FOUND` — and the `amount_cents` must be a positive integer, else `ERR_INVALID_REQUEST`. A `benefit_month` that is not in `YYYY-MM` form is rejected with `ERR_INVALID_REQUEST`; a well-formed `benefit_month` must be the current or the next calendar month, and a run against a `DISASTER` program additionally requires the current clock date to fall inside that program's disaster window; either violation is rejected with `ERR_POSTING_MONTH_INVALID`. A repeat run for the same program and benefit month is rejected with `ERR_DUPLICATE_POSTING_RUN`.

The run creates one benefit posting per eligible purse. Eligible purses are the purses of the named program whose owning case's `account_status` is `OPEN` or `DORMANT` and whose own `purse_status` is not `CLOSED`; purses of `SUSPENDED` cases are skipped, as are closed purses. Each posting is born with `posting_status` `SCHEDULED`, and a `POST_CREDIT` ledger entry is created immediately for each posting — scheduled money, which raises the purse's ledger balance at once but remains invisible to the spendable balance until availability — and each such entry refreshes the purse's `last_activity_at`. The run's response reports `created_count`, `skipped_count`, and the `posting_ids` created.

The posting's schedule is computed deterministically. The modulus is the program's `posting_modulus` override when set, otherwise the contract's `default_posting_modulus`. The case's bucket is the integer value of its `case_identifier` taken modulo the modulus, yielding a value from zero up to one less than the modulus. The base date is the first day of `benefit_month` advanced by the bucket number of days, so bucket zero lands on the first of the month. When the case's `created_at` UTC date falls inside the benefit month, the available date is the later of the base date and the case-created date; otherwise the available date is simply the base date. The availability hour is the program's `availability_hour_utc` override when set, otherwise the contract's `default_availability_hour_utc`. The posting's `available_at` is the available date at that hour, zero minutes, zero seconds UTC, and its `scheduled_date` is the available date.

First-month proration applies when the case was created inside the benefit month: the credited `amount_cents` is the run amount multiplied by the number of days from the case-created date through the end of the month inclusive, divided by the number of calendar days in the month, rounded half up to whole cents exactly once; the posting's `prorated` flag is true precisely when the result differs from the run amount. For any other case the posting credits the full run amount and `prorated` is false.

From there, the posting lifecycle is sweep-driven. On the availability sweep — step 1 of the clock pipeline — a `SCHEDULED` posting whose `available_at` the current clock has reached or passed flips to `AVAILABLE`, provided its owning purse is not `CLOSED`; a `FROZEN` purse still receives availability. If the owning case is `DORMANT`, the availability bubbles up: the case flips from `DORMANT` back to `OPEN`, though its cards remain `DEACTIVATED`, so spending power returns only through a replacement card under the fee rules of Section 3.6. A `SCHEDULED` posting whose availability arrives while its purse is `CLOSED` instead flips to `FORFEITED`, and its `POST_CREDIT` is reversed by a `FORFEIT_DEBIT` ledger entry of equal amount. `EXPUNGED`, `EXPIRED`, and `FORFEITED` are the posting's terminal states, and `resolved_at` records the clock timestamp of the transition into any of them.

### 3.5. Expungement, Disaster Expiry, and the Dormancy Cascade

The expungement sweep — step 3 of the clock pipeline — retires unused food and cash benefits. For each `FOOD` or `CASH` purse that is not `CLOSED` and whose `last_activity_at` is not null, the effective inactivity window is the program's `expungement_inactivity_days` override when set, otherwise the contract's `default_expungement_inactivity_days` (90 days by default), and the notice lead is the contract's `expungement_notice_lead_days` (30 days by default). The eligibility instant is the purse's `last_activity_at` plus the inactivity window; the notice instant is the eligibility instant minus the lead. When the current clock is at or after the notice instant but still before the eligibility instant, and no notice has been recorded, the sweep records the notice by stamping `expungement_notice_sent_at`. When the current clock reaches or passes the eligibility instant — the boundary is inclusive — the sweep expunges the purse: every `AVAILABLE` posting of that purse flips to `EXPUNGED` together, a single `EXPUNGE_DEBIT` of the purse's full `ledger_balance_cents` zeroes the ledger, and the notice flag resets to null. Because every new ledger entry refreshes `last_activity_at` and clears the notice, any activity restarts the inactivity clock from that entry's timestamp.

`DISASTER` purses are exempt from expungement entirely. Instead, the disaster-expiry sweep — step 2 of the pipeline, running before expungement — flips an `AVAILABLE` posting of a `DISASTER` purse to `EXPIRED` once the current clock reaches or passes the posting's `available_at` plus the effective disaster expiry window: the program's `disaster_expiry_days` override when set, otherwise the contract's `default_disaster_expiry_days` (30 days by default), again with an inclusive boundary. An `EXPIRY_DEBIT` of the posting's unspent portion posts to the disaster purse at that moment.

The unspent portion is computed by first-in-first-out allocation. The purse's consuming debits — the purchase, withdrawal, and fee debits — are replayed in `created_at` ascending order against the purse's postings that ever reached `AVAILABLE`, ordered by `available_at` ascending with `created_at` ascending as the tie-break (never by id), and each debit is allocated to the oldest posting that still has remaining unspent balance before any amount flows to a newer posting. Expunge, expiry, and forfeit debits do not consume postings, and credit entries never do. A posting's unspent amount is its `amount_cents` minus the total allocated to it.

Expungement feeds the dormancy cascade. When the expungement sweep has just expunged a case's purses and, afterwards, every purse of the case has a `ledger_balance_cents` of zero and no posting of the case remains in `SCHEDULED` or `AVAILABLE`, an `OPEN` case flips to `DORMANT`; in the same cascade every card of the case in `ISSUED`, `MAILED`, `ACTIVE`, or `PIN_LOCKED` flips to `DEACTIVATED`. The way back is the availability bubble-up of Section 3.4: the next posting of one of the case's purses to become available flips the case from `DORMANT` to `OPEN`, while the deactivated cards stay deactivated.

### 3.6. The Card Lifecycle: Issuance, Mailing, PIN, and Replacement

`CardholderServices` issues the initial card for a case by supplying the `case_account_id`; the case must be `OPEN`. The card is born with `card_status` `ISSUED`, a server-minted `pan_token`, a null `fee_charged_cents`, and `fee_waived` false. The card-mail sweep — step 4 of the clock pipeline — flips a card from `ISSUED` to `MAILED` once the current clock reaches or passes the card's `created_at` plus the contract's `card_mail_delay_hours` (24 hours by default), stamping `mailed_at` with the sweep's clock timestamp.

Activation moves a `MAILED` card to `ACTIVE`. The owning cardholder or a `CardholderServices` representative performs it, supplying the `pin` to store. The owning case must be `OPEN` — activation against a `SUSPENDED` or `DORMANT` case is rejected with `ERR_CASE_NOT_OPEN` — and a card still in `ISSUED`, where the mail delay has not yet elapsed, is rejected with `ERR_CARD_NOT_MAILED`. Activation stores the supplied secret in `pin_secret` (masked as `****` in every response once set, and null until a PIN is first stored), resets `pin_fail_count` to zero, and stamps `activated_at`.

The PIN then guards spending. Every authorization presents a `pin`, which the system compares against the card's stored `pin_secret`. A mismatch increments `pin_fail_count` by 1 and is rejected with `ERR_PIN_MISMATCH`; when the count reaches the contract's `pin_max_failures` (3 by default), the card flips from `ACTIVE` to `PIN_LOCKED`. A `PIN_LOCKED` card short-circuits any later authorization with `ERR_PIN_LOCKED` before the PIN is even compared. The counter tracks consecutive mismatches, so a successful verification resets it to zero. A PIN reset is allowed on `ACTIVE` or `PIN_LOCKED` cards: a `CardholderServices` caller supplies only the `new_pin`, while a cardholder caller must also supply a `current_pin` matching the stored secret, with a mismatch rejected as `ERR_PIN_MISMATCH`. A failed `current_pin` verification on a PIN reset increments `pin_fail_count` exactly like an authorization mismatch and can itself flip an `ACTIVE` card to `PIN_LOCKED`. The reset stores the new secret, zeroes `pin_fail_count`, and returns a locked card to `ACTIVE`. Requesting a PIN reset — or a replacement — for a card in `ISSUED`, `MAILED`, `REPLACED`, or `DEACTIVATED` is rejected with `ERR_REPLACEMENT_NOT_ALLOWED`.

Replacement swaps a compromised or locked card for a successor. The owning cardholder or a `CardholderServices` representative may replace a card in `ACTIVE` or `PIN_LOCKED`, provided the owning case is `OPEN`. The old card flips to `REPLACED`, which is terminal, and a new card is created in `ISSUED` with the `case_account_id` copied and `replacement_of_card_id` set to the old card's id. The replacement fee assessment then runs in a pinned evaluation order, because the fee amount depends on which purse absorbs it and absorbability depends on that purse's balance:

1. Free allowance first. If the case's `replacements_in_window` is below the contract's `free_replacements_per_365d` (one free replacement per trailing 365 days by default) — counted before the successor card is created, so the successor never counts toward its own allowance, and with the trailing window inclusive at exactly 365 days — the fee is zero: the new card's `fee_charged_cents` records 0 and `fee_waived` is false. Evaluation stops.
2. Program-priority debit. For each program in the fixed priority order `CASH` first, then `FOOD`: if the case holds a purse of that program that is not `CLOSED`, the candidate fee is the program's `replacement_fee_cents` override when set, otherwise the contract's `default_replacement_fee_cents` (250 cents by default). If that purse's `spendable_balance_cents` covers the full fee, a `FEE_DEBIT` of the fee posts to the purse with `reference_id` set to the new card's id, the new card's `fee_charged_cents` records the fee, `fee_waived` is false, and evaluation stops. A `FROZEN` purse cannot absorb the fee — fee debits are blocked on frozen purses — so a frozen purse is skipped and evaluation moves on rather than failing.
3. Waiver last. If no purse absorbed the fee, the fee is waived: the new card's `fee_charged_cents` is 0 and `fee_waived` is true.

`DISASTER` purses never absorb replacement fees, and there are no partial debits: a purse either absorbs the full fee or evaluation moves on. Replacement mutates only card rows; the case account's `version` is not incremented by a replacement.

The card's terminal state `DEACTIVATED` arrives only by cascade: when the owning case flips to `DORMANT` or `CLOSED`, every card of the case in `ISSUED`, `MAILED`, `ACTIVE`, or `PIN_LOCKED` flips to `DEACTIVATED`.

### 3.7. Authorizations at the Point of Sale

A `RetailerSystem` actor runs an authorization as a specific retailer — the retailer named in the path must equal `X-User-ID`, or the request is rejected with `ERR_FORBIDDEN`. The card's case need not belong to the retailer's contract: the contract-active gate, the configuration values (the PIN lockout threshold, the withdrawal multiple, and the daily limit), and the item-restriction mode are all taken from the retailer's contract, while the case-open gate and the purses debited are the card-owning case's own. The request carries the `card_id`, the `pin`, and the `authorization_type`. A `PURCHASE` authorization must carry an `items` array of line items, each with a `upc`, a `quantity`, and a `unit_price_cents`, and must not carry `withdrawal_amount_cents`; a `CASH_WITHDRAWAL` authorization must carry `withdrawal_amount_cents` and must not carry `items`. A presence mismatch is rejected with `ERR_INVALID_REQUEST`. These request-shape checks — the `authorization_type` value, the presence rules, each line item's field types (a string `upc`, a positive integer `quantity`, a non-negative integer `unit_price_cents`), and a positive integer `withdrawal_amount_cents` — are evaluated up front, after the card-active gate and before the frozen-purse and PIN gates; `ERR_WITHDRAWAL_MULTIPLE` remains a format check and fires later, after PIN verification.

The full gate chain runs in the pipeline order of Section 2.8: the contract must be `ACTIVE` (`ERR_CONTRACT_NOT_ACTIVE`), the case must be `OPEN` (`ERR_CASE_NOT_OPEN`), the retailer must be `APPROVED` (`ERR_RETAILER_NOT_ACTIVE`), and the card must be able to spend — a card in `ISSUED`, `MAILED`, `REPLACED`, or `DEACTIVATED` is rejected with `ERR_CARD_NOT_ACTIVE`, while a `PIN_LOCKED` card short-circuits with `ERR_PIN_LOCKED` before the PIN comparison. The frozen-purse gate of step 13 runs next, before the PIN gate: the charge plan below is computed tentatively, and any purse that would be debited must not be `FROZEN` — a debit that would hit a frozen purse is rejected with `ERR_PURSE_FROZEN`, which takes priority over the PIN gate and over any funds insufficiency, so a `PIN_LOCKED` card whose charge plan would debit a frozen purse surfaces `ERR_PURSE_FROZEN`, not `ERR_PIN_LOCKED`. Then the PIN gate of Section 3.6 runs — an absent or non-string `pin` is rejected with `ERR_INVALID_REQUEST` at this gate — with mismatches rejected as `ERR_PIN_MISMATCH` and counted toward lockout. Only then do the fiscal rules below execute.

A purchase resolves each line item against the retailer's item file on the current clock date, consulting the `item_restriction_mode` of the contract's `FOOD` program. Under `STRICT`, a line whose UPC has no covering `ACTIVE` item record — unknown or expired — is rejected with `ERR_ITEM_NOT_ELIGIBLE`; the rejection fires at the funds-and-limits stage (step 23), after the frozen and PIN gates, and until then the failing line is provisionally bucketed as food for the charge plan. Under `LENIENT`, a line with an unknown UPC is treated as food-eligible and counted in the transaction's `exception_flag_count`. If the contract has no `FOOD` program at all, no restriction mode applies, and a line with no covering record simply sums into the cash total without flagging an exception. Lines with `food_eligible` records sum, quantity times `unit_price_cents` per line, into the food total; all remaining lines sum into the cash total.

Charging follows a no-spill waterfall: each bucket is bounded by its own purse and buckets never cross-charge. If the case has a disaster purse that is not `CLOSED`, the `disaster_charge_cents` is the smaller of the food total and that purse's `spendable_balance_cents`. Then, if the case has a food purse that is not `CLOSED`, the `food_charge_cents` is the smaller of the remaining food total — the food total minus the disaster charge — and the food purse's spendable balance. If the disaster and food charges together cannot cover the food total, the authorization is rejected with `ERR_INSUFFICIENT_FUNDS`. If the cash total is positive and the case has no cash purse that is not `CLOSED`, the authorization is rejected with `ERR_NO_CASH_PURSE` — a non-food charge with no cash purse to absorb it reports this error rather than an eligibility error. When several fiscal rejections would apply at once, the eligibility rejection fires first, then the food-funds check, then `ERR_NO_CASH_PURSE`, then the cash-funds check; a withdrawal instead orders them `ERR_NO_CASH_PURSE`, then `ERR_DAILY_LIMIT_EXCEEDED`, then `ERR_INSUFFICIENT_FUNDS`. Otherwise the `cash_charge_cents` is the smaller of the cash total and the cash purse's spendable balance, and a shortfall is rejected with `ERR_INSUFFICIENT_FUNDS`. On success, one `PURCHASE_DEBIT` posts per charged purse — disaster, then food, then cash — and the transaction is born with `txn_status` `AUTHORIZED`, recording the retailer's id, the `case_account_id` captured from the card at authorization time, the three charge amounts, and a `total_cents` that is exactly the food charge plus the cash charge; the disaster charge is a subdivision of the food charge and is never added separately.

A cash withdrawal follows its own rule chain. The case must hold a cash purse that is not `CLOSED`, else `ERR_NO_CASH_PURSE`. The `withdrawal_amount_cents` must be an exact multiple of the contract's `cash_withdrawal_multiple_cents` (500 cents by default), else `ERR_WITHDRAWAL_MULTIPLE`. The daily usage is the sum of `WITHDRAWAL_DEBIT` amounts on the case's cash purse whose `created_at` falls within the current UTC calendar day — from midnight inclusive to the next midnight exclusive — and whose transaction is not `VOIDED`; if that usage plus the requested amount exceeds the contract's `cash_withdrawal_daily_limit_cents` (50000 cents by default), the request is rejected with `ERR_DAILY_LIMIT_EXCEEDED`, while landing exactly on the limit is allowed because only a strictly greater total rejects. Finally the cash purse's `spendable_balance_cents` must cover the amount, else `ERR_INSUFFICIENT_FUNDS`. On success a `WITHDRAWAL_DEBIT` of the amount posts to the cash purse.

A void lets the owning retailer reverse a same-day authorization: the transaction's `retailer_id` must equal the caller's `X-User-ID`, the transaction must still be `AUTHORIZED` — an already `VOIDED` or already `SETTLED` transaction is rejected with `ERR_TXN_NOT_VOIDABLE` — and the current clock's UTC calendar date must equal the transaction's `created_at` UTC calendar date, with any later day rejected as `ERR_VOID_WINDOW_EXPIRED`. A successful void flips the transaction from `AUTHORIZED` to `VOIDED`, stamps `voided_at`, and posts a `VOID_CREDIT` of the exact debited amount to each purse the authorization debited, restoring each purse's balance exactly. Every debit and credit posted in this section refreshes the owning purse's `last_activity_at`.

### 3.8. Skimming Claims: Filing, Freezing, Investigation, and Credits

A cardholder whose card was skimmed — or a `CardholderServices` representative acting for them — files a skimming claim by supplying the `case_account_id`, the claimed `card_id`, the `authorization_ids` of between one and twenty allegedly fraudulent transactions, a positive `claimed_amount_cents`, a free-text `incident_description`, and an optional `freeze_purse` flag that defaults to true. A cardholder may file only for their own case. The case must be `OPEN`; filing against a `SUSPENDED`, `DORMANT`, or `CLOSED` case is rejected with `ERR_CASE_NOT_OPEN`. Every referenced transaction must exist (`ERR_REFERENCE_NOT_FOUND`), must belong to the filing case (`ERR_CLAIM_TXN_CASE_MISMATCH`), and must be recent: each referenced transaction's `created_at` must lie within the contract's `claim_window_days` (60 days by default) of the current clock, with an inclusive boundary — a transaction whose `created_at` is exactly `claim_window_days` before the current clock is still fileable — else the filing is rejected with `ERR_CLAIM_WINDOW_EXPIRED`. The `claimed_amount_cents` must not exceed the sum of the referenced transactions' `total_cents`, else `ERR_CLAIM_AMOUNT_EXCEEDS_REFERENCED`. The claim is born with `investigation_status` `FILED` and `credit_status` `NONE`, with `provisional_credit_cents` at 0 and `filed_by_user_id` and `filed_by_role` recorded. When `freeze_purse` is true, every purse the referenced transactions charged flips from `OPEN` to `FROZEN` at filing. A `FROZEN` purse rejects purchase, withdrawal, and fee debits with `ERR_PURSE_FROZEN`, while credits — posting, void, provisional, and claim credits — and expunge and expiry debits still apply to it.

Investigation begins when a `CardholderServices` representative drives the claim from `FILED` to `UNDER_INVESTIGATION`, which stamps `investigated_at` and starts the provisional-credit clock. Segregation of duties applies at exactly this step: when the claim's `filed_by_role` is `CardholderServices`, the acting representative's `X-User-ID` must differ from the claim's `filed_by_user_id`, and a filer attempting to move their own claim into investigation is rejected with `ERR_SOD_VIOLATION`.

If the claim is still under investigation when the current clock reaches or passes `investigated_at` plus the contract's `provisional_credit_delay_days` (10 days by default) — an inclusive boundary — the provisional-credit sweep (step 5 of the clock pipeline) auto-issues credit: a `PROVISIONAL_CREDIT` of the smaller of `claimed_amount_cents` and the contract's `provisional_credit_cap_cents` (50000 cents by default) posts to the claim's target purse, `provisional_credit_cents` and `provisional_credited_at` are set, and `credit_status` moves from `NONE` to `PROVISIONAL`. The target purse is chosen deterministically from the referenced transactions: the system sums their `food_charge_cents` and their `cash_charge_cents`, and the target is the case's cash purse when the cash sum is at least the food sum, otherwise the case's food purse. A `CLOSED` purse remains eligible as the target; if the case holds no purse of the selected type at all, the other type's purse is used instead, and if the case holds neither a `CASH` nor a `FOOD` purse, no credit entry posts while the claim's fields still update.

Adjudication belongs to `StateAdmin` alone and proceeds from `UNDER_INVESTIGATION`. A substantiation requires `substantiated_amount_cents` to be present, greater than zero, and no more than `claimed_amount_cents` — otherwise `ERR_INVALID_REQUEST` — and the final credit is the smaller of the substantiated and claimed amounts. The system then settles the delta against any provisional credit already on the target purse: when the final credit exceeds the provisional, a `CLAIM_CREDIT` of the difference posts; when the provisional exceeds the final, a `CLAIM_REVERSAL_DEBIT` of the difference posts; when they are equal, no entry posts; and when no provisional exists, the full final credit posts as a `CLAIM_CREDIT`. The claim's `credit_status` becomes `FINAL`. A finding of `UNSUBSTANTIATED` posts nothing when no provisional credit exists — `credit_status` simply stays `NONE` — and posts a `PROVISIONAL_REVERSAL_DEBIT` of the full `provisional_credit_cents` with `credit_status` moving to `REVERSED` when one does. Either decision stamps `decided_by_user_id` and `decided_at`, and every purse the claim froze flips from `FROZEN` back to `OPEN`, provided the purse's case is not `CLOSED` — except that a purse frozen by several claims flips back only once every claim that froze it has reached a terminal decision. `SUBSTANTIATED` and `UNSUBSTANTIATED` are terminal, as are the credit states `FINAL` and `REVERSED`.

Substantiation also feeds the retailer-integrity cascade: for each distinct retailer among the referenced transactions, the retailer's `skimming_incident_count` increases by 1, and any retailer whose count reaches the contract's `skimming_suspend_threshold` (3 lifetime incidents by default) flips automatically from `APPROVED` to `SUSPENDED`, with the consequences of Section 3.2.

### 3.9. Settlement, Disputes, and Reconciliation

A settlement day runs from the contract's `settlement_cutoff_hour_utc` (hour 0 by default) on one day to the same hour on the next, including the start instant and excluding the end instant. When the clock crosses a cutoff boundary — step 6 of the sweep pipeline — every transaction still `AUTHORIZED` whose settlement day has just closed flips to `SETTLED`. A transaction's settlement day is the one containing its `created_at`. The settled transactions are grouped per contract and `acquirer_reference` into a settlement batch born with `batch_status` `CUTOFF`; each transaction's `batch_id` is set to its batch, and the batch's `settled_authorization_ids` lists the settled transaction ids in `created_at` ascending order. The batch records the `settlement_date` (the UTC calendar date of the settlement day's start instant) and the `cutoff_at` (the clock instant of the cutoff boundary that created it, at the start of the following day).

Two batch figures are computed at cutoff and are immutable thereafter: `gross_settled_cents`, the sum of the settled transactions' `total_cents`, and `txn_count`, their count. A third is computed then too: `acquirer_fee_cents`. For each settled transaction, the fee is the transaction's `total_cents` multiplied by the contract's `acquirer_fee_basis_points` (75 basis points by default) and divided by 10000, rounded half up to whole cents; the batch's `acquirer_fee_cents` is the sum of those per-transaction fees. This round-per-transaction-then-sum order is pinned. Summing the transaction totals first and rounding once is forbidden because it yields different cents: five 67-cent transactions produce a 5-cent total fee under the pinned rule against 3 cents under the forbidden one.

The batch's live position is two further computed figures. `adjustment_total_cents` is the signed sum of `adjustment_cents` over the batch's `UPHELD` disputes — positive meaning an additional amount owed to the retailer — and starts at 0. `net_position_cents` is the gross settled amount minus the acquirer fee plus the adjustment total. The gross figure alone is the acquirer-facing obligation before fees and adjustments; the net figure is the retailer-facing payable, and it is the net figure a reconcile must match.

Reconciliation is performed by a `StateAdmin` supplying the `actual_settled_cents` the acquirer actually paid; the supplied value is recorded on the batch's `actual_settled_cents` (null until the first attempt) on every reconcile attempt, matched or not. The batch must first have zero `OPEN` disputes — any open dispute rejects the reconcile with `ERR_BATCH_HAS_OPEN_DISPUTES`, and this check fires before any amount comparison, so a mismatched reconcile attempted while a dispute is open still surfaces the dispute error. If `actual_settled_cents` equals the batch's `net_position_cents` at reconcile time, a `CUTOFF` or `DISPUTED` batch flips to `RECONCILED` — terminal — with `reconciled_at` stamped. On a mismatch, no error is raised for the amount itself: instead the batch moves to `DISPUTED` — or stays there, since a mismatched reconcile against an already-disputed batch keeps it in `DISPUTED` — and the system creates a settlement dispute of `dispute_type` `RECONCILIATION_MISMATCH` in `OPEN`, whose `disputed_amount_cents` is the actual settled amount minus the net position and whose `retailer_id` and `filed_by_user_id` are null because the system filed it. Each further mismatched reconcile attempt adds one more open mismatch dispute, and the batch can leave `DISPUTED` only through a matched reconcile with zero open disputes.

Retailers raise their own disputes. A `RetailerSystem` files against a batch in `CUTOFF` or `DISPUTED`, supplying the `settlement_batch_id`, a signed `disputed_amount_cents`, and a free-text `reason`. The filing window is the contract's `dispute_window_days` (15 days by default) after the batch's `cutoff_at`, with an inclusive boundary; filing later is rejected with `ERR_DISPUTE_WINDOW_EXPIRED`. The batch must belong to the filer in the sense that at least one transaction settled into it belongs to the retailer whose id equals the caller's `X-User-ID`. The dispute is born with `dispute_status` `OPEN` and `dispute_type` `RETAILER_DISPUTE`, the filing retailer's id recorded in `retailer_id` and `filed_by_user_id`; filing against a `CUTOFF` batch flips the batch to `DISPUTED` with no additional record. A batch's disputes may be listed and filtered by `dispute_status`.

Adjudication belongs to the `StateAdmin`. Upholding a dispute requires a signed `adjustment_cents` — its absence is rejected with `ERR_INVALID_REQUEST` — which is stored on the dispute; the batch's `adjustment_total_cents` is then recomputed as the signed sum over the batch's `UPHELD` disputes, and `net_position_cents` is recomputed accordingly. Overturning applies no adjustment and leaves the batch totals unchanged. `UPHELD` and `OVERTURNED` are terminal, and adjudicating an already-decided dispute is rejected with `ERR_INVALID_STATE`. Each decision stamps `decided_at`.

### 3.10. Closure and Data Delivery

Case closure is the mirror of everything above. A `StateAdmin` may close a case in `OPEN`, `SUSPENDED`, or `DORMANT`. Two preconditions apply, in the pipeline order of Section 2.8: first, no skimming claim of the case may be in `FILED` or `UNDER_INVESTIGATION`, else `ERR_CASE_HAS_OPEN_CLAIMS`; second, every purse of the case must have a `ledger_balance_cents` of zero, else `ERR_CASE_BALANCE_NONZERO` — the ledger view governs here, so scheduled future money blocks closure even though it was never spendable. (For a `DORMANT` case the balances are already zero by construction.) Closure then cascades: every purse of the case in `OPEN` or `FROZEN` flips to `CLOSED`; every posting of those purses still in `SCHEDULED` flips to `FORFEITED`, with its `POST_CREDIT` reversed by a `FORFEIT_DEBIT` ledger entry of equal amount; postings in `AVAILABLE` flip to `FORFEITED` without further entries, their funds already fully consumed as the zero-balance precondition guarantees; and every card of the case in `ISSUED`, `MAILED`, `ACTIVE`, or `PIN_LOCKED` flips to `DEACTIVATED`. The closure increments the case's `version` by 1 and, like every case status change, requires the `expected_case_account_version` of Section 2.10. `CLOSED` is terminal for the case: any further status change is rejected with `ERR_INVALID_STATE`, as is any transition a resource's current state does not allow anywhere in the system. Contract closure follows the obligation preconditions of Section 3.1.

Data delivery runs on the clock. The settlement-cutoff sweep (step 6) also emits each contract's daily transaction file: a data delivery with `delivery_type` `DAILY_TRANSACTION_FILE` whose `period` is the settled date in `YYYY-MM-DD` form, carrying `txn_count` — the transactions settled on that period across all acquirers — plus `settled_food_cents` and `settled_cash_cents`, the sums of `food_charge_cents` and `cash_charge_cents` over the period's settled transactions. Emission carries no activity condition: the file is produced for every contract at every crossed cutoff boundary, and a settlement day in which no transaction settled still yields a file whose `txn_count` is 0 and whose sums are 0. When a clock advance crosses a month boundary, step 7 of the pipeline emits the `MONTHLY_INTEGRITY_REPORT` for the calendar month that just ended — the half-open window from the first instant of that month to the first instant of the next — carrying `expunged_cents` (the sum of `EXPUNGE_DEBIT` amounts created in the month), `expired_cents` (the sum of `EXPIRY_DEBIT` amounts created in the month), `substantiated_claims_count` (claims of the contract decided in the month with `investigation_status` `SUBSTANTIATED`), `provisional_credits_outstanding_cents` (the sum of `provisional_credit_cents` over claims whose `credit_status` is `PROVISIONAL` at the month-end instant), `retailer_suspensions_count` (retailers of the contract whose transition from `APPROVED` to `SUSPENDED` occurred in the month), and `lenient_exceptions_count` (the sum of `exception_flag_count` over the contract's transactions created in the month). The monthly report's `period` is the ended month in `YYYY-MM` form, and its figures are computed from system state at the instant step 7 emits it — for a crossed month boundary, the first sweep instant on or after the month end. The monthly report is likewise unconditional: every contract produces one for every crossed month boundary, even when the month had no relevant activity. Metrics that belong to the other delivery type are null: the daily file carries no integrity fields and the monthly report carries no settlement sums. Every delivery is created with `delivery_status` `GENERATED` and flips to `DELIVERED` in the same sweep that creates it. A `StateAdmin` lists a contract's deliveries, filterable by `delivery_type`.

## 4. Endpoint Definitions

Operations that create a new resource — a contract, program, retailer, case account, initial card, allotment run's postings, item file, authorization, skimming claim, retailer dispute, or the successor card produced by a replacement — return `201 Created`. Operations that modify an existing resource in place — status transitions on contracts, cases, retailers, claims, and disputes, card activation, PIN reset, void, reconciliation — as well as the logical-clock set return `200 OK`, as do all reads. Request and response field semantics for every operation are defined in Sections 2 and 3; the table below is only an index.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the logical clock (mounted outside `/ebt`) and run the seven-step sweep | StateAdmin |
| POST | `/ebt/contracts` | Create a state contract in `CONFIGURING` with configuration defaults | StateAdmin |
| GET | `/ebt/contracts/{id}` | Read a contract | StateAdmin, CardholderServices |
| POST | `/ebt/contracts/{id}/status` | Drive contract transitions (`ACTIVE`, `SUSPENDED`, `CLOSED`) | StateAdmin |
| GET | `/ebt/contracts/{id}/programs` | List programs of a contract | StateAdmin, CardholderServices |
| POST | `/ebt/programs` | Create a benefit program (`DRAFT` or directly `ACTIVE`) | StateAdmin |
| GET | `/ebt/contracts/{id}/retailers` | List retailers of a contract | StateAdmin, CardholderServices |
| POST | `/ebt/retailers` | Onboard a retailer (`APPROVED`) | StateAdmin |
| POST | `/ebt/contracts/{id}/allotment-runs` | Bulk-create one posting per eligible purse for a program and benefit month | StateAdmin |
| GET | `/ebt/contracts/{id}/data-deliveries` | List a contract's daily transaction files and monthly integrity reports | StateAdmin |
| GET | `/ebt/retailers/{id}` | Read a retailer | StateAdmin, CardholderServices, RetailerSystem |
| POST | `/ebt/retailers/{id}/status` | Suspend or reinstate a retailer | StateAdmin |
| POST | `/ebt/retailers/{id}/item-files` | Atomically upload an item-eligibility file | RetailerSystem |
| GET | `/ebt/retailers/{id}/items` | List a retailer's item-eligibility records | StateAdmin, CardholderServices, RetailerSystem |
| POST | `/ebt/retailers/{id}/authorizations` | Run a purchase or cash-withdrawal authorization | RetailerSystem |
| GET | `/ebt/retailers/{id}/authorizations` | List a retailer's authorizations | StateAdmin, CardholderServices, RetailerSystem |
| GET | `/ebt/case-accounts` | List case accounts, filterable by contract and status | StateAdmin, CardholderServices |
| POST | `/ebt/case-accounts` | Open a case account with one purse per active program | StateAdmin |
| GET | `/ebt/case-accounts/{id}` | Read a case account | StateAdmin, CardholderServices, Cardholder |
| POST | `/ebt/case-accounts/{id}/status` | Drive case transitions (`SUSPENDED`, `OPEN`, `CLOSED`) with OCC | StateAdmin |
| GET | `/ebt/case-accounts/{id}/cards` | List cards of a case, including replacement lineage | StateAdmin, CardholderServices, Cardholder |
| GET | `/ebt/case-accounts/{id}/claims` | List skimming claims of a case | StateAdmin, CardholderServices, Cardholder |
| POST | `/ebt/cards` | Issue the initial card for a case (`ISSUED`) | CardholderServices |
| POST | `/ebt/claims` | File a skimming claim | Cardholder, CardholderServices |
| GET | `/ebt/purses` | List purses, filterable by case, program, and status | StateAdmin, CardholderServices, Cardholder |
| GET | `/ebt/purses/{id}` | Balance inquiry: both balance views plus expungement-notice fields | StateAdmin, CardholderServices, Cardholder |
| GET | `/ebt/purses/{id}/ledger` | List the purse's append-only ledger entries | StateAdmin, CardholderServices, Cardholder |
| GET | `/ebt/purses/{id}/postings` | List the purse's benefit postings | StateAdmin, CardholderServices, Cardholder |
| GET | `/ebt/cards/{id}` | Read a card (PIN masked) | StateAdmin, CardholderServices, Cardholder |
| POST | `/ebt/cards/{id}/activate` | Activate a `MAILED` card and set its PIN | Cardholder, CardholderServices |
| POST | `/ebt/cards/{id}/replace` | Replace an `ACTIVE` or `PIN_LOCKED` card, running the fee assessment | Cardholder, CardholderServices |
| POST | `/ebt/cards/{id}/pin-reset` | Reset the PIN of an `ACTIVE` or `PIN_LOCKED` card | Cardholder, CardholderServices |
| POST | `/ebt/authorizations/{id}/void` | Void an `AUTHORIZED` transaction on its UTC calendar day | RetailerSystem |
| POST | `/ebt/claims/{id}/status` | Investigate or adjudicate a skimming claim | CardholderServices, StateAdmin |
| GET | `/ebt/settlement-batches` | List settlement batches, filterable by contract, acquirer, and status | StateAdmin, CardholderServices |
| GET | `/ebt/settlement-batches/{id}` | Read a settlement batch with computed positions | StateAdmin, CardholderServices |
| POST | `/ebt/settlement-batches/{id}/reconcile` | Reconcile a batch against the acquirer's actual payment | StateAdmin |
| POST | `/ebt/disputes` | File a retailer dispute against a batch | RetailerSystem |
| GET | `/ebt/settlement-batches/{id}/disputes` | List disputes of a batch | StateAdmin, CardholderServices, RetailerSystem |
| POST | `/ebt/disputes/{id}/status` | Uphold or overturn a dispute | StateAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of Sections 2 and 3; this catalogue is only an index of identifiers to HTTP status codes.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_SOD_VIOLATION` | 403 Forbidden |
| `ERR_PIN_MISMATCH` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_CONTRACT_NOT_ACTIVE` | 409 Conflict |
| `ERR_CASE_NOT_OPEN` | 409 Conflict |
| `ERR_RETAILER_NOT_ACTIVE` | 409 Conflict |
| `ERR_CARD_NOT_MAILED` | 409 Conflict |
| `ERR_CARD_NOT_ACTIVE` | 409 Conflict |
| `ERR_PIN_LOCKED` | 409 Conflict |
| `ERR_PURSE_FROZEN` | 409 Conflict |
| `ERR_REPLACEMENT_NOT_ALLOWED` | 409 Conflict |
| `ERR_TXN_NOT_VOIDABLE` | 409 Conflict |
| `ERR_BATCH_HAS_OPEN_DISPUTES` | 409 Conflict |
| `ERR_CASE_HAS_OPEN_CLAIMS` | 409 Conflict |
| `ERR_CONTRACT_HAS_OPEN_OBLIGATIONS` | 409 Conflict |
| `ERR_CASE_IDENTIFIER_DUPLICATE` | 409 Conflict |
| `ERR_ITEM_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_DISASTER_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_PROGRAM_TYPE_DUPLICATE` | 409 Conflict |
| `ERR_DUPLICATE_POSTING_RUN` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_CASE_IDENTIFIER_INVALID` | 400 Bad Request |
| `ERR_UPC_INVALID` | 400 Bad Request |
| `ERR_WITHDRAWAL_MULTIPLE` | 400 Bad Request |
| `ERR_REFERENCE_NOT_FOUND` | 422 Unprocessable Entity |
| `ERR_ITEM_NOT_ELIGIBLE` | 422 Unprocessable Entity |
| `ERR_NO_CASH_PURSE` | 422 Unprocessable Entity |
| `ERR_DAILY_LIMIT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_FUNDS` | 422 Unprocessable Entity |
| `ERR_VOID_WINDOW_EXPIRED` | 422 Unprocessable Entity |
| `ERR_CLAIM_WINDOW_EXPIRED` | 422 Unprocessable Entity |
| `ERR_CLAIM_TXN_CASE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_CLAIM_AMOUNT_EXCEEDS_REFERENCED` | 422 Unprocessable Entity |
| `ERR_DISPUTE_WINDOW_EXPIRED` | 422 Unprocessable Entity |
| `ERR_POSTING_MONTH_INVALID` | 422 Unprocessable Entity |
| `ERR_CASE_BALANCE_NONZERO` | 422 Unprocessable Entity |
