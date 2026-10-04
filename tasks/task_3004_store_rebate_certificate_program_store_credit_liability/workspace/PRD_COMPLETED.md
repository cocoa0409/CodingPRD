# Store Rebate Certificates API — Product Requirements Document

## 1. Introduction

This document specifies the Store Rebate Certificates API: a platform that runs a mail-in-style rebate certificate program for a chain of home-improvement stores, in the tradition of the "11% everything week" promotions that drive enormous liability on paper long before any value is redeemed. The system manages the full life of a rebate — from flagging which items are rebate-eligible during an advertised week, through receipt-based submission with adjudication of mixed-tender and partially returned lines, to the issuance of store-credit certificates, their redemption, expiry, reissue, and the eventual recognition of breakage income on value that customers never come back to claim.

Two forces shape the design. First, rebate certificates are a real financial liability: every issued certificate sits on a store's books until it is redeemed, voided, or swept as breakage, and finance needs both the gross face-value number and a net-of-expected-breakage number at all times. Second, the program is a classic fraud surface — customers split purchases across receipts to game per-receipt caps, resubmit the same receipt twice, or return merchandise after the rebate has already been awarded. The API therefore pairs an append-only credit ledger with a fraud-flag workflow, and enforces the program's cardinal rule in both directions: a rebate certificate may never pay for a purchase that itself earns a rebate.

All temporal reasoning in the system — advertised weeks, submission deadlines, certificate expiry, fraud lookback windows — is evaluated against a logical clock, never the wall clock, so that the platform is deterministic and testable.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contracts that apply uniformly across every endpoint: authentication, response envelopes, pagination, resource identity, monetary precision, the logical clock, liability accounting, concurrency control, and hierarchical validation.

### 2.1. User and Role-Based Access Control

Every request carries two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, specifying the operational capacity in which they act. The system recognizes exactly six roles: `StoreAdmin`, `GuestService`, `FraudAnalyst`, `FinanceAdmin`, `Customer`, and `Contractor`. A request whose `X-User-Role` header is missing or does not name one of these six roles is rejected with `ERR_UNAUTHENTICATED` (401); the `X-User-ID` header itself is never required — when absent it is treated as an empty identifier (which for entity-backed roles simply fails any ownership comparison). A request whose role is recognized but not permitted for the targeted endpoint is rejected with `ERR_FORBIDDEN` (403).

Role identity is interpreted as follows. When `X-User-Role` is `StoreAdmin`, `GuestService`, `FraudAnalyst`, or `FinanceAdmin`, the `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit purposes but never compares it against any entity's `id`. When `X-User-Role` is `Customer` or `Contractor`, `X-User-ID` is the `id` of the acting `CreditAccount`; ownership checks on any resource that references a `CreditAccount` compare the resource's account foreign key to `X-User-ID`, and an entity-backed role acting on another account's resource is rejected with `ERR_FORBIDDEN`. A `Customer` holds a `RETAIL` account; a `Contractor` holds a `CONTRACTOR` account and additionally manages job purchases.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. Both are optional on every list endpoint.

Unless otherwise specified, every list endpoint returns resources sorted by their `created_at` timestamp in ascending order. Ledger listings are chronological on the same basis. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`, as shown in §2.2.

### 2.4. Common Resource Properties

Every primary resource carries a standard set of system-managed fields:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp updated on every mutation of the resource.
- `version` (integer): a system-managed integer that starts at 1 when the resource is created and increments by exactly 1 on every mutation of the resource.

Two entity families are exceptions. `ReceiptLine` and `SubmissionLine` are line-level sub-resources that carry only `id` and `created_at`; both `updated_at` and `version` are absent from them. `CreditLedgerEntry` is likewise an append-only record carrying only `id` and `created_at`, with no `updated_at` and no `version`. Any recomputation of a derived field on an entity — a store's liability figures, an account's balances — counts as a mutation of that entity and therefore refreshes its `updated_at` and increments its `version`.

### 2.5. Monetary Values and Precision

All monetary values are represented as integer cents throughout the API — request payloads, response bodies, and stored fields alike. There are no decimal monetary amounts anywhere in the system. Wherever a computation produces a fractional cent result (a percentage rebate, a net-of-breakage liability, a volume bonus), the value is rounded to a whole number of cents using the round-half-up method. Specific calculations pin down when rounding happens — per line before summation, or once at the end — and those orderings are stated with the workflows in §3 and are binding.

Non-monetary numeric configuration (percentages such as `rebate_pct`, rates such as `expected_breakage_rate`) preserves the caller's input precision.

### 2.6. The Logical Clock and Temporal Windows

The platform never consults the wall clock. A single logical clock governs every temporal decision in the system: advertised-week membership, submission deadlines, certificate expiry, fraud lookback windows, and breakage sweeps. Before any call has been made, the logical clock reads exactly `2026-09-01T00:00:00Z` as a fixed startup default. A `StoreAdmin`-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant and returns the resulting `current_utc`; the supplied instant is accepted as-is — it may be earlier than, equal to, or later than the current reading — and the lazy auto-close of §3.2 is not run by the clock set itself, only by the next read or write against a program. This capability exists so clients can drive time-dependent behavior deterministically.

Three temporal conventions recur throughout the document. An advertised week is a half-open interval: it opens at 00:00:00Z on the week's start date and closes at 00:00:00Z on the week's end date, with the closing instant itself outside the week. A submission deadline is computed from the purchase *date* at 00:00:00Z plus a whole number of days, and the deadline instant itself is still valid — a submission landing exactly on the deadline is accepted. Certificate expiry is the mirror image: the expiry instant itself is already expired, so redemption requires the clock to be strictly before the expiry instant while a breakage sweep claims certificates whose expiry instant is at or before the run time.

### 2.7. Store-Credit Liability Accounting

Every store maintains a set of derived liability fields that the platform recomputes on every mutation touching a certificate's redeemable value — issuance, redemption, expiry sweeps, reissue, and voiding alike. `outstanding_liability_cents` is the gross, regulatory face-value liability; `net_liability_cents` is the same figure net of expected breakage, derived from the store's `expected_breakage_rate`; `accrued_breakage_income_cents` accumulates the breakage income recognized by sweep runs; and `liability_epoch` is a monotonically increasing counter, starting at 0, stamped forward by each breakage run. The two liability variants are always both maintained; for any nonzero expected breakage rate they diverge on identical inputs. The full composition of each variant is specified in §3.7.

Value movement is recorded in an append-only ledger. Every accrual, redemption, reversal, breakage sweep, and reissue posts a `CreditLedgerEntry` whose `entry_type` is one of `ISSUANCE_ACCRUAL`, `REDEMPTION`, `REVERSAL_DEBIT`, `BREAKAGE_EXPIRY`, or `REISSUE_CREDIT`. Each entry carries a signed `amount_cents` — accruals and reissue credits positive, redemptions and reversals negative, breakage negative as liability relief — together with the `account_id` it posts to, the `certificate_id` it moves value against, the store's `liability_epoch` at the time of posting, and a free-text `created_note` recording provenance such as the originating return or breakage run. Ledger entries are never updated or deleted; corrections are made by posting further entries.

### 2.8. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control against the store's `version`. Updating a store's policy configuration requires the request to carry `expected_store_version` holding the `version` the caller last observed for that store; if another writer has advanced the store's version since that read, the update is rejected with `ERR_STALE_VERSION` (412), and the caller must re-read the current policy before overwriting it. Starting a breakage run is guarded the same way: the request must carry `expected_store_version` matching the store's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` (412). A store mutation between the caller's read and the run — a configuration change, another completed run, any cascade touching the store — means the caller's breakage projection was computed on a stale liability epoch and must be refreshed before sweeping expirations. Endpoints other than these two do not take a version field.

### 2.9. Nested Resource Retrieval and Validation Order

The API exposes a deep resource hierarchy — stores containing receipts, submissions, certificates, accounts, programs, and flags; submissions containing lines — alongside a flat read surface of canonical single-resource reads and reverse-lookup listings. For any request whose path addresses nested resources, the server validates path identifiers from left to right: each identifier must exist and must nest correctly under its parent before the next is considered. The first identifier that fails — a missing store, a receipt belonging to a different store, a submission under the wrong account — yields `ERR_NOT_FOUND` (404) before any business rule is evaluated.

Across all endpoints, request validation proceeds in a fixed priority order: authentication of the role header first, then role and ownership authorization, then left-to-right path existence, then structural payload well-formedness (`ERR_INVALID_REQUEST`, 400 — missing required fields, invalid enum values, quantities or amounts below 1 where a positive value is required), and only then the business, temporal, referential, state, safety, fiscal, and concurrency rules described in §3. Within a single endpoint that applies several business rules, the rules are evaluated in the priority order given in §2 and §3, so that an earlier failure always surfaces ahead of a later one.

## 3. Business Logic & Workflows

### 3.1. Store Provisioning and Rebate Policy Configuration

A `StoreAdmin` onboards a store by creating it with a human-facing `store_code`, unique across the platform, together with the five policy parameters that drive every downstream rule: `submission_window_days`, the number of days after the purchase date during which a receipt may still be submitted; `certificate_validity_months`, the whole calendar months an issued certificate stays redeemable; `expected_breakage_rate`, a fraction between 0 and 1 inclusive expressing what share of issued certificate value the store expects never to be redeemed; `split_txn_window_hours`, the lookback window for split-transaction screening; and `split_txn_min_receipts`, the minimum cluster size that raises a split-transaction flag. A new store starts with all liability fields at 0 and `liability_epoch` at 0.

Policy configuration can later be adjusted through the store update operation, which accepts `expected_store_version` plus any subset of `submission_window_days`, `certificate_validity_months`, `expected_breakage_rate`, `split_txn_window_hours`, and `split_txn_min_receipts`. The optimistic-concurrency rule of §2.8 applies: a stale `expected_store_version` is rejected with `ERR_STALE_VERSION` (412). A successful update increments the store's `version` by 1, and when the breakage rate changes, `net_liability_cents` is recomputed immediately from the unchanged gross liability.

### 3.2. Advertising a Rebate Week: Programs and Eligible Items

A rebate program is the store's publicized offer for one advertised week. A `StoreAdmin` creates a program with a `name`, a `week_start_date`, and a `week_end_date`, both ISO dates; the program is born in `DRAFT` status. While a program is in `DRAFT`, the store flags individual items as rebate-eligible by adding program items, each carrying a `sku`, a `rebate_pct` expressed as a fraction greater than 0 and at most 1 (0.11 for the classic eleven-percent week), an optional `excluded_categories` list defaulting to empty, an optional `min_quantity` defaulting to 1, and an optional `per_receipt_cap_cents` that is either null — uncapped — or a positive integer cap compared against the line's rebate *before* rounding. Items can only be added to a program that is still in `DRAFT`; the attempt against any other status is rejected with `ERR_INVALID_STATE` (409). Each program item records its owning program via `program_id`.

Activation moves a program from `DRAFT` to `ACTIVE` and is guarded by three checks. Activation enforces these checks in order: the program must contain at least one program item — an empty program is rejected with `ERR_PROGRAM_EMPTY` (409); then no other program of the same store may already be `ACTIVE` with an overlapping advertised week, where two weeks that merely touch — one's end date equal to the other's start date — do *not* overlap, and a genuine overlap is rejected with `ERR_PROGRAM_WEEK_OVERLAP` (409); finally, the advertised week must not have already fully passed, meaning the logical clock must be before 00:00:00Z on `week_end_date`, otherwise activation is rejected with `ERR_PROGRAM_WEEK_PAST` (409). Once `ACTIVE`, receipts purchased within the week's half-open interval become matchable against the program's items; program status is not consulted at matching time, so a program's items remain matchable in every status, `DRAFT` and `CLOSED` included.

A program closes in either of two ways. A `StoreAdmin` may close an `ACTIVE` program manually, moving it to `CLOSED`. Independently, the system auto-closes a program lazily: the first read or write against a program observed at a logical clock at or after 00:00:00Z on `week_end_date` plus the store's `submission_window_days` days transitions it to `CLOSED`. Crucially, closing a program does not close the rebate claims against it — eligibility is keyed on the receipt's `purchase_at`, not on submission time, so submissions for purchases made during the advertised week continue to be adjudicated after the program is `CLOSED`.

### 3.3. Credit Accounts and Contractor Job Envelopes

Guest service opens a store-credit account with an `owner_name` and an `account_type` of either `RETAIL` or `CONTRACTOR`. A new account starts `ACTIVE` with all balances at zero. Every account carries three derived figures, recomputed on every event that touches its certificates or submissions: `credit_balance_cents`, the sum of `remaining_balance_cents` over the account's certificates in `ACTIVE` or `PARTIALLY_REDEEMED` status — certificates that are `EXPIRED`, `REISSUED`, `VOIDED`, or `FULLY_REDEEMED` contribute nothing; `pending_award_cents`, the sum of `award_cents` over the account's submissions in `APPROVED` status whose settling certificate has not yet been issued — an `APPROVED` submission already settled by an issued certificate contributes only through the certificate leg of `credit_balance_cents`; and `lifetime_rebate_cents`, the cumulative adjudicated rebate value ever awarded to the account, which is never decremented, not even by reversals.

Fraud investigation can freeze an account, moving it from `ACTIVE` to `FROZEN` — freezing an account in any other status is rejected with `ERR_INVALID_STATE` (409); while frozen, submissions, certificate issuance, and redemption are all rejected, although accrual reversals driven by returns are not blocked. Unfreezing applies only to a `FROZEN` account — the attempt against any other status is rejected with `ERR_INVALID_STATE` (409) — and returns it to `ACTIVE`, but is refused with `ERR_FRAUD_FLAG_OPEN` (409) while any `DUPLICATE_RECEIPT` fraud flag on the account is still `OPEN`. A `StoreAdmin` closes an account only when it is in `ACTIVE` status — closing a `FROZEN` or already-`CLOSED` account is rejected with `ERR_INVALID_STATE` (409) — and only when both `credit_balance_cents` and `pending_award_cents` are exactly zero; otherwise the close is rejected with `ERR_ACCOUNT_BALANCE_NONZERO` (409).

Contractor accounts additionally organize their purchases into job envelopes. A `Contractor` registers a job purchase on their own account by supplying a `job_reference`, unique within that contractor account; the job is created in `OPEN` status, and the account must be a `CONTRACTOR` account in `ACTIVE` status — a registration attempt against any other account type or status is rejected with `ERR_INVALID_STATE` (409). Each job purchase records its owning account through `contractor_account_id`. Only an `OPEN` job accepts receipt links, and only the owning contractor can settle a job, moving it from `OPEN` to `SETTLED`, after which it stops accepting new receipt links. A computed contractor summary, readable by `StoreAdmin`, `FinanceAdmin`, and the owning `Contractor`, aggregates rebates per job: each job's awarded total is the sum of `award_cents` over `APPROVED` submissions whose receipts are charged to that job, minus the `award_cents` of `REVERSED` submissions on those same receipts — a net-of-reversal figure. The account-level total, `account_job_total_cents`, sums the per-job figures across all jobs, and a volume bonus applies to the whole total as an average rate, not marginally: totals below 500,000 cents earn no bonus (tier `NONE`); totals of at least 500,000 cents but below 2,000,000 cents fall in tier `PRO` and earn a bonus of the total multiplied by 0.02, rounded half-up to whole cents; totals of at least 2,000,000 cents fall in tier `PRO_PLUS` and earn the total multiplied by 0.05, rounded half-up once. A total landing exactly on 500,000 cents is in `PRO` — the tier boundary is inclusive upward. The summary response carries `account_job_total_cents`, `bonus_tier`, `bonus_cents`, and the per-job `jobs` array, each entry of which carries `job_id`, `job_reference`, `status`, and the job's net-of-reversal figure under `job_awarded_cents`. The summary is defined only for `CONTRACTOR` accounts; requesting it for a `RETAIL` account is rejected with `ERR_INVALID_REQUEST` (400).

### 3.4. Receipts, Tender Splits, and Split-Transaction Screening

Guest service records a sale by creating a receipt with a register-assigned `receipt_number`, unique within the issuing store — reusing one is rejected with `ERR_DUPLICATE_RECEIPT_NUMBER` (409) — plus the purchasing `account_id`, the `purchase_at` timestamp, the receipt's `lines`, and optionally a `job_purchase_id` when a contractor charges the purchase to a job. The purchase timestamp must not be in the future relative to the logical clock, or the receipt is rejected with `ERR_RECEIPT_IN_FUTURE` (422); a timestamp exactly equal to the logical clock is accepted — only a strictly later instant is in the future. When `job_purchase_id` is present, it must reference a job owned by the purchasing account, that account must be a `CONTRACTOR` account, and the job must still be `OPEN`; any violation is rejected with `ERR_INVALID_JOB_PURCHASE` (422). The `account_id` itself must reference an existing credit account; an unknown `account_id` is rejected with `ERR_NOT_FOUND` (404).

Each receipt line records its 1-based `line_number`, unique within the receipt, the purchased `sku`, the line's `category` code used for exclusion matching, a `quantity` of at least 1, a `unit_price_cents` of at least 0, and a `tender_splits` array describing how the line was paid. The receipt must carry at least one line, `sku` and `category` must be non-empty strings, and `line_number` must be an integer at least 1 and unique across the receipt's lines; any violation is `ERR_INVALID_REQUEST` (400). Each tender split names a `tender_type` of `CASH`, `CARD`, `GIFT_CARD`, or `STORE_CREDIT_CERTIFICATE` and an `amount_cents` of at least 0, with at least one split per line; the amounts across all of a line's tender splits must sum exactly to the line's quantity multiplied by its unit price, and any other total is rejected with `ERR_TENDER_SPLIT_MISMATCH` (422). From the splits, the system derives `certificate_tendered_cents`, the portion of the line funded by rebate certificates — the sum of splits of type `STORE_CREDIT_CERTIFICATE`. When certificate tender is applied across a receipt, it is allocated line by line in ascending `line_number` order, each line absorbing at most what remains of its own total after earlier tenders; the recorded `certificate_tendered_cents` on a line reduces that line's rebate base, so the certificate-funded portion of a purchase never earns another rebate. Each line also carries a `returned_quantity`, starting at 0 and accumulating through returns, never exceeding the sold `quantity`. The receipt's `total_cents` is the sum of line totals, gross of returns, and its `status` is derived from return activity: `OPEN` while nothing is returned, `PARTIALLY_RETURNED` when some but not all units have come back, and `FULLY_RETURNED` when every unit on every line has been returned, which is terminal.

Receipt creation is also a fraud checkpoint. The split-transaction scan looks back from the new receipt's `purchase_at` over the account's other receipts at the same store, considering the half-open window that excludes the instant exactly `split_txn_window_hours` before the new purchase and includes the new receipt itself. When the count of those candidate receipts plus the new one reaches `split_txn_min_receipts`, and at least two receipts in the cluster share at least one SKU, the system creates a `SPLIT_TRANSACTION` fraud flag in `OPEN` status listing the cluster's receipt ids in ascending `created_at` order, with a machine-generated `detail` explaining the window edges and receipt numbers. The flag does not block the sale — the receipt is created regardless; it marks the cluster for investigation.

### 3.5. Rebate Submission, Adjudication, and the Award Calculation

A `Customer` or `Contractor` submits a receipt for rebate with a payload naming the `receipt_id`; the receipt must belong to the submitter's own account. Creation is rejected with `ERR_SUBMISSION_WINDOW_CLOSED` (422) once the logical clock is past the deadline — the purchase date at 00:00:00Z plus the store's `submission_window_days` days, with the deadline instant itself still accepted. Duplicate screening runs next: if any submission not in `REVERSED` status already exists for the same receipt, the new submission is refused with `ERR_DUPLICATE_RECEIPT_SUBMISSION` (409) and a `DUPLICATE_RECEIPT` fraud flag in `OPEN` status is created listing the implicated receipts. A receipt whose earlier submission ended in `REVERSED` may be submitted again freely. A submission on a `FROZEN` account is rejected with `ERR_ACCOUNT_FROZEN` (409). These creation-time rules apply in the stated order — submission window, then duplicate screening, then the frozen-account check — so a duplicate submission that also lands past the window fails on the window, and a duplicate on a frozen account fails on the duplicate screen.

Every submission enters `SUBMITTED` and then, within the same request that creates or resubmits it, transitions automatically to `UNDER_REVIEW` after fraud screening. At that moment the system computes a **provisional award** and records it in `provisional_award_cents`. An `OPEN` fraud flag on the account does not block adjudication, though it remains on record.

The award is computed line by line over the receipt's lines in ascending `line_number` order, and each line yields a `SubmissionLine` recording the `receipt_line_id` it claims, the `program_item_id` it matched — null when no program item matched — an `eligible_base_cents`, an `awarded_cents`, and an `exclusion_reason`. The per-line procedure is:

1. Find the program item whose `sku` equals the line's `sku` and whose program's advertised week contains the receipt's `purchase_at` — the week opens at 00:00:00Z on `week_start_date` and closes at 00:00:00Z on `week_end_date`, the closing instant excluded. Matching is scoped to the receipt's store; programs of other stores are never visible. If several items match, the one with the greatest `rebate_pct` wins, ties broken by the program item's earlier `created_at`. If none matches, the line is excluded with reason `NO_PROGRAM_ITEM` and contributes a base of 0.
2. If the line's `category` appears in the matched item's `excluded_categories`, the line is excluded with reason `EXCLUDED_CATEGORY` and base 0 — the category overrides the SKU match.
3. Compute the net quantity as the line's `quantity` minus its `returned_quantity`. In the adjudicated variant only, if the net quantity is below the program item's `min_quantity`, the line is excluded with reason `BELOW_MIN_QUANTITY` and base 0.
4. If the line's `certificate_tendered_cents` is at least the line's full value — quantity multiplied by unit price — the line is excluded with reason `FULLY_CERTIFICATE_TENDERED` and base 0.
5. The gross base is the net quantity multiplied by `unit_price_cents`. The provisional variant computes this with returns invisible — `returned_quantity` treated as 0 — because returns cannot be known at submission time.
6. The eligible base is the gross base minus `certificate_tendered_cents`, floored at 0.
7. The raw award is the eligible base multiplied by the item's `rebate_pct`.
8. When the item's `per_receipt_cap_cents` is set, the raw award is capped at that value — the cap compares against the unrounded award.
9. The line's `awarded_cents` is the raw award rounded half-up to whole cents. Rounding is pinned per line: each line rounds first, and the submission's award is the sum of the rounded line awards — never the other way around. Ineligible lines contribute an `awarded_cents` of 0.

The provisional variant — computed on submission creation and on each resubmit — skips the minimum-quantity check, ignores returns, and stores its result in `provisional_award_cents`. The adjudicated variant — computed when guest service approves — subtracts the current `returned_quantity`, enforces `min_quantity`, and freezes its result into `award_cents`, which is null until adjudication.

Guest service adjudicates a submission in `UNDER_REVIEW` with a `decision` of `APPROVE` or `REJECT`; adjudicating a submission in any other status is rejected with `ERR_INVALID_STATE` (409). Approval is permitted only while the submission window is still open — the same deadline rule as creation, evaluated against the receipt's purchase date, with `ERR_SUBMISSION_WINDOW_CLOSED` (422) past it — and only while the account is not `FROZEN`, with `ERR_ACCOUNT_FROZEN` (409) otherwise. The state requirement is evaluated first: a submission not in `UNDER_REVIEW` fails with `ERR_INVALID_STATE` (409) before either of those checks runs. On approval, the adjudicated award is computed and frozen into `award_cents`, and the account's `pending_award_cents` and `lifetime_rebate_cents` each increase by the awarded amount. On rejection, the submission moves to `REJECTED` and the request's `rejection_reason` is recorded; the reason is null in every other status.

A rejected submission is not dead. The customer — retail or contractor — may resubmit it, cycling `REJECTED` back to `SUBMITTED` and then again automatically to `UNDER_REVIEW` within the same request. Resubmission requires `resubmit_count` to still be below the hard cap of 3 cycles — at the cap, the attempt is rejected with `ERR_RESUBMIT_LIMIT_REACHED` (409) — and the submission window must still be open, with `ERR_SUBMISSION_WINDOW_CLOSED` (422) past it, and the account must not be `FROZEN`, with `ERR_ACCOUNT_FROZEN` (409) otherwise. These checks are applied in the order given: state (`REJECTED`), then resubmit cap, then submission window, then the frozen-account check. Each resubmission increments `resubmit_count` by 1, refreshes `submitted_at` to the current logical clock, clears the `rejection_reason`, and recomputes the provisional award.

Once a submission is `APPROVED`, guest service issues the certificate that settles it. Issuance mints a `RebateCertificate` in `ACTIVE` status with `issued_amount_cents` equal to the submission's `award_cents`, `remaining_balance_cents` equal to the issued amount, `issued_at` set to the logical clock, and the certificate tied to its settling `submission_id` — null only on reissued certificates, which carry `reissued_from_id` instead — and to its issuing `store_id`, since certificates are redeemable only at their issuing store. Issuance requires the submission to be `APPROVED` — any other status is rejected with `ERR_INVALID_STATE` (409) — and the account to not be `FROZEN`, with `ERR_ACCOUNT_FROZEN` (409) otherwise. An `ISSUANCE_ACCRUAL` ledger entry posts the positive amount against the certificate. The account's balances update in a pinned order: `pending_award_cents` is decremented *before* `credit_balance_cents` is incremented, so a certificate never double-counts within the same request. The store's liability fields are recomputed in the same request.

### 3.6. Certificate Redemption, Expiry, Reissue, and Holds

A certificate's `expires_at` is projected at issuance: the `issued_at` instant advanced by the store's `certificate_validity_months` whole calendar months, snapped to 00:00:00Z of the resulting calendar day. When the day-of-month does not exist in the target month, the date clamps to that month's last day — a certificate issued on January 31 with one month of validity expires at 00:00:00Z on February 28. The expiry instant itself is already expired: redemption requires the logical clock to be strictly before `expires_at`, while a breakage sweep claims certificates whose `expires_at` is at or before the run time. A certificate meant to be redeemable "through" its final day is therefore modelled with its expiry at the following midnight.

Guest service redeems a certificate against a receipt by supplying the `receipt_id` and an `amount_cents`. Redemption is the most heavily guarded operation in the system, and its checks are evaluated in order: the certificate must be in `ACTIVE` or `PARTIALLY_REDEEMED` status — redeeming in any other status is rejected with `ERR_INVALID_STATE` (409); the holder's account must not be `FROZEN`, with `ERR_ACCOUNT_FROZEN` (409) otherwise; a certificate under a fraud hold — `fraud_hold` equal to `HELD` — is rejected with `ERR_CERTIFICATE_HELD` (409); the logical clock must be strictly before `expires_at`, with `ERR_CERTIFICATE_EXPIRED` (422) at or past it; the redeeming receipt must belong to the certificate's issuing store and to the certificate holder's own account, with `ERR_CERTIFICATE_WRONG_STORE` (422) otherwise; and the redemption bar applies — no line of the redeeming receipt may match any program item of a program whose advertised week contains that receipt's `purchase_at` at the redeeming store, because certificates may never pay for further rebate-eligible purchases, and a violating basket is rejected with `ERR_CERTIFICATE_REBATE_PURCHASE_BARRED` (422). The amount must be at least 1 cent and no more than the certificate's `remaining_balance_cents`; an overdraw is rejected with `ERR_REDEMPTION_EXCEEDS_BALANCE` (422).

A successful redemption decrements `remaining_balance_cents` by the amount, posts a `REDEMPTION` ledger entry for the negative amount, and recomputes the account's balance and the store's liability fields. An amount smaller than the remaining balance moves the certificate from `ACTIVE` to `PARTIALLY_REDEEMED`, or keeps it in `PARTIALLY_REDEEMED`; an amount exactly equal to the remaining balance moves it to `FULLY_REDEEMED` with the balance at 0 — the boundary case takes the full-redemption transition.

When a certificate's expiry passes unredeemed, a breakage sweep transitions it from `ACTIVE` or `PARTIALLY_REDEEMED` to `EXPIRED`. An expired certificate is not yet worthless to the customer: within a grace window of 30 days after `expires_at`, guest service may reissue it. Only a certificate in `EXPIRED` status may be reissued — the attempt against any other status is rejected with `ERR_INVALID_STATE` (409). Reissue is then refused, in this order, with `ERR_REISSUE_WINDOW_CLOSED` (422) once the logical clock reaches 30 days past expiry, with `ERR_ACCOUNT_FRAUD_CONFIRMED` (409) while any fraud flag on the account is `CONFIRMED`, and with `ERR_CERTIFICATE_HELD` (409) while the certificate is held. A successful reissue mints a brand-new certificate: status `ACTIVE`, `issued_amount_cents` equal to the source certificate's `remaining_balance_cents`, `reissued_from_id` pointing at the source, and a fresh `issued_at` and `expires_at` computed from the current store policy. A `REISSUE_CREDIT` ledger entry posts the positive value against the new certificate, the source certificate's `remaining_balance_cents` drops to 0, and the source's status becomes `REISSUED`. Account balances and store liability fields are recomputed.

Fraud holds form a parallel state dimension on the certificate, independent of its lifecycle status: `fraud_hold` moves between `NONE`, `HELD`, and `RELEASED` without touching `status`. A `FraudAnalyst` may place a hold — moving `fraud_hold` to `HELD` — or release it — moving it to `RELEASED` — from any non-terminal status; the attempt against a terminal certificate (`FULLY_REDEEMED`, `VOIDED`, or `REISSUED`) is rejected with `ERR_INVALID_STATE` (409). A hold blocks redemption and reissue without otherwise changing the certificate.

### 3.7. Liability Composition and the Breakage Sweep

The store's gross liability, `outstanding_liability_cents`, is the sum of two components: the `remaining_balance_cents` of every certificate of the store in `ACTIVE`, `PARTIALLY_REDEEMED`, or `EXPIRED` status — expired certificates stay on the books until they are reissued or age out of the reissue grace window, while `VOIDED`, `FULLY_REDEEMED`, and `REISSUED` certificates contribute nothing — plus the `award_cents` of every submission of the store in `APPROVED` status whose settling certificate has not yet been issued; once an `APPROVED` submission's certificate is issued, that submission leaves this leg and its value is carried only by the certificate leg, so an approved-but-settled award never double-counts. The net liability, `net_liability_cents`, is the gross figure multiplied by one minus the store's `expected_breakage_rate`, with a single round-half-up to whole cents applied at the very end. Both variants are maintained on every mutation that touches a certificate's redeemable value.

Breakage is recognized through an explicit sweep. A `FinanceAdmin` starts a breakage run for a store, carrying `expected_store_version` for the optimistic-concurrency check of §2.8; a mismatch is rejected with `ERR_STALE_VERSION` (412) before anything is swept. The run is atomic — it executes and completes within the request, so only `COMPLETED` runs are ever observable even though the run passes through `RUNNING` internally — and it sweeps every certificate of the store in `ACTIVE` or `PARTIALLY_REDEEMED` status whose `expires_at` is at or before the run's `run_at` timestamp, the boundary included. Swept certificates are processed in ascending `expires_at` order, ties broken by earlier `created_at`. For each swept certificate, the certificate transitions to `EXPIRED` and a `BREAKAGE_EXPIRY` ledger entry posts its negative `remaining_balance_cents`, tagged with the run's epoch. The run records `expired_count`, the number of certificates it swept, and `breakage_recognized_cents`, the total swept value, and the store's `accrued_breakage_income_cents` increases by that total. The run advances the store's `liability_epoch` by 1, records the new epoch in the run's `epoch` field, stamps the epoch onto every breakage entry it posts, increments the store's `version` by 1, and recomputes the liability fields. A run that finds nothing to sweep is legal: `expired_count` and `breakage_recognized_cents` are both 0, and the `liability_epoch` still advances by 1.

### 3.8. Returns and the Guest-Service Reversal Cascade

Guest service processes a merchandise return against a receipt by supplying the returned `lines`, each naming a `line_number` and a `quantity` of at least 1. For every line, the cumulative returned quantity — the line's current `returned_quantity` plus this return's quantity — must not exceed the sold `quantity`; a return that would overshoot is rejected with `ERR_RETURN_QUANTITY_EXCEEDS_SOLD` (422). A successful return is recorded as a `Return` resource carrying the `receipt_id`, the `lines`, a `processed_at` timestamp taken from the logical clock, and `reversal_entry_ids`, the ledger entries minted by the reversal cascade — empty when nothing had been awarded yet. Each touched line's `returned_quantity` increases, and the receipt's `status` is recomputed: `PARTIALLY_RETURNED` when any line still has unreturned units, `FULLY_RETURNED` when every unit on every line has come back.

The return becomes consequential when it touches at least one receipt line that contributed a positive `eligible_base_cents` to an `APPROVED` submission on that receipt — every such `APPROVED` submission on the receipt is reversed, whether or not its certificate has been issued. In that case the reversal cascade fires inside the same request, settling four levels of state. First, the submission transitions from `APPROVED` to `REVERSED`. Second, the certificate that settled the submission — whether `ACTIVE` or `PARTIALLY_REDEEMED` — transitions to `VOIDED`, a terminal state; its `remaining_balance_cents` stays at its pre-void value on the row, but a voided certificate is excluded from both the account balance and the store liability because of its status. Third, a `REVERSAL_DEBIT` ledger entry posts the certificate's `remaining_balance_cents` as a negative amount — value the customer already redeemed is *not* clawed back from the account; only the unredeemed remainder is reversed. Fourth, the account's `pending_award_cents` decreases by the submission's `award_cents`, the account's `credit_balance_cents` is recomputed, and the store's `outstanding_liability_cents` and `net_liability_cents` are recomputed. The `lifetime_rebate_cents` figure is not decremented — it records what was ever awarded, not what survived.

### 3.9. Fraud Investigation Workflow

Fraud flags are raised automatically by the two screenings — the split-transaction scan at receipt creation and the duplicate-receipt scan at submission creation — and are worked by a `FraudAnalyst`. A flag is born `OPEN` and records its `flag_type` (`SPLIT_TRANSACTION` or `DUPLICATE_RECEIPT`), the implicated `receipt_ids`, and a machine-generated `detail`. Resolution takes a `resolution` of `CONFIRM` or `CLEAR`. Confirming a flag moves it to `CONFIRMED`, a terminal state, and places every certificate of the account whose `fraud_hold` is `NONE` into `HELD`; a confirmed `DUPLICATE_RECEIPT` flag keeps the rejected submission rejected, while a confirmed `SPLIT_TRANSACTION` flag does not void certificates by itself. Clearing a flag moves it to `CLEARED` and releases no holds automatically — any hold requires an explicit release. A cleared flag may be reopened, returning it to `OPEN` for re-investigation; resolving a flag that is not `OPEN`, or reopening one that is not `CLEARED`, is rejected with `ERR_INVALID_STATE` (409).

The flags feed back into the operational rules: a `CONFIRMED` flag of any type blocks certificate reissue with `ERR_ACCOUNT_FRAUD_CONFIRMED`; an `OPEN` `DUPLICATE_RECEIPT` flag blocks account unfreezing with `ERR_FRAUD_FLAG_OPEN`; and account freezing — available to the `FraudAnalyst` at any time on an `ACTIVE` account — blocks submissions, issuance, and redemption while leaving return-driven reversal accruals untouched.

## 4. Endpoint Definitions

Operations that create a new resource — a store, a program, a program item, an account, a job purchase, a receipt, a submission, or a breakage run — return `201 Created`. Operations that modify an existing resource — state transitions, adjudications, redemptions, returns, holds, releases, configuration updates — return `200 OK`. Reads return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the logical clock (test-driving) | StoreAdmin |
| POST | `/stores` | Create a store with its rebate policy configuration | StoreAdmin |
| GET | `/stores` | List stores (paginated) | StoreAdmin, GuestService, FraudAnalyst, FinanceAdmin |
| GET | `/stores/{store_id}` | Read a store including computed liability fields | StoreAdmin, GuestService, FraudAnalyst, FinanceAdmin |
| PATCH | `/stores/{store_id}` | Update store policy configuration (OCC-guarded) | StoreAdmin |
| POST | `/stores/{store_id}/rebate-programs` | Create a rebate program for an advertised week | StoreAdmin |
| GET | `/stores/{store_id}/rebate-programs` | List programs of a store (optional status filter) | StoreAdmin, GuestService, FraudAnalyst, FinanceAdmin |
| GET | `/stores/{store_id}/rebate-programs/{program_id}` | Read one program | StoreAdmin, GuestService, FraudAnalyst, FinanceAdmin |
| POST | `/stores/{store_id}/rebate-programs/{program_id}/items` | Flag an item rebate-eligible for the program's week | StoreAdmin |
| GET | `/stores/{store_id}/rebate-programs/{program_id}/items` | List program items | StoreAdmin, GuestService, FraudAnalyst, FinanceAdmin |
| POST | `/stores/{store_id}/rebate-programs/{program_id}/activate` | Activate a DRAFT program | StoreAdmin |
| POST | `/stores/{store_id}/rebate-programs/{program_id}/close` | Manually close an ACTIVE program | StoreAdmin |
| POST | `/stores/{store_id}/credit-accounts` | Open a retail or contractor store-credit account | GuestService |
| GET | `/stores/{store_id}/credit-accounts/{account_id}` | Read an account with computed balances | StoreAdmin, GuestService, FraudAnalyst, FinanceAdmin, Customer, Contractor |
| POST | `/stores/{store_id}/credit-accounts/{account_id}/freeze` | Freeze an account | FraudAnalyst |
| POST | `/stores/{store_id}/credit-accounts/{account_id}/unfreeze` | Unfreeze an account | FraudAnalyst |
| POST | `/stores/{store_id}/credit-accounts/{account_id}/close` | Close a zero-balance account | StoreAdmin |
| POST | `/stores/{store_id}/credit-accounts/{account_id}/job-purchases` | Register a contractor job purchase envelope | Contractor |
| GET | `/stores/{store_id}/credit-accounts/{account_id}/jobs` | List job purchases of a contractor account | StoreAdmin, GuestService, Contractor, FinanceAdmin |
| POST | `/stores/{store_id}/job-purchases/{job_id}/settle` | Settle an OPEN job purchase envelope | Contractor |
| GET | `/stores/{store_id}/credit-accounts/{account_id}/contractor-summary` | Per-job and account-level rebate aggregation with volume-bonus tier | StoreAdmin, FinanceAdmin, Contractor |
| POST | `/stores/{store_id}/receipts` | Record a receipt with lines and tender splits; runs split-transaction screening | GuestService |
| GET | `/stores/{store_id}/receipts` | List receipts of a store; filterable by account | StoreAdmin, GuestService, FraudAnalyst, FinanceAdmin |
| GET | `/stores/{store_id}/receipts/{receipt_id}` | Read a receipt | StoreAdmin, GuestService, FraudAnalyst, FinanceAdmin |
| GET | `/stores/{store_id}/receipts/{receipt_id}/lines` | List the lines of a receipt | StoreAdmin, GuestService, FraudAnalyst, FinanceAdmin |
| POST | `/stores/{store_id}/receipts/{receipt_id}/returns` | Process a merchandise return; fires the rebate reversal cascade | GuestService |
| POST | `/stores/{store_id}/rebate-submissions` | Submit a receipt for rebate; provisional award computed | Customer, Contractor |
| GET | `/stores/{store_id}/rebate-submissions` | List submissions of a store; filterable by account and status | StoreAdmin, GuestService, FraudAnalyst, FinanceAdmin |
| GET | `/stores/{store_id}/rebate-submissions/{submission_id}` | Read a submission | StoreAdmin, GuestService, FraudAnalyst, FinanceAdmin, Customer, Contractor |
| GET | `/stores/{store_id}/rebate-submissions/{submission_id}/lines` | List adjudicated submission lines | StoreAdmin, GuestService, FraudAnalyst, FinanceAdmin, Customer, Contractor |
| POST | `/stores/{store_id}/rebate-submissions/{submission_id}/adjudicate` | Approve or reject an UNDER_REVIEW submission | GuestService |
| POST | `/stores/{store_id}/rebate-submissions/{submission_id}/resubmit` | Resubmit a REJECTED submission (bounded cycle) | Customer, Contractor |
| POST | `/stores/{store_id}/rebate-submissions/{submission_id}/issue-certificate` | Issue the certificate settling an APPROVED submission | GuestService |
| GET | `/stores/{store_id}/certificates` | List certificates of a store; filterable by account and status | StoreAdmin, GuestService, FraudAnalyst, FinanceAdmin |
| GET | `/stores/{store_id}/certificates/{certificate_id}` | Read a certificate | StoreAdmin, GuestService, FraudAnalyst, FinanceAdmin, Customer, Contractor |
| POST | `/stores/{store_id}/certificates/{certificate_id}/redeem` | Redeem certificate value against a receipt | GuestService |
| POST | `/stores/{store_id}/certificates/{certificate_id}/reissue` | Reissue an EXPIRED certificate within the grace window | GuestService |
| POST | `/stores/{store_id}/certificates/{certificate_id}/hold` | Place a fraud hold on a certificate | FraudAnalyst |
| POST | `/stores/{store_id}/certificates/{certificate_id}/release` | Release a fraud hold | FraudAnalyst |
| GET | `/stores/{store_id}/credit-accounts/{account_id}/ledger` | List ledger entries of an account (chronological) | StoreAdmin, GuestService, FraudAnalyst, FinanceAdmin |
| POST | `/stores/{store_id}/breakage-runs` | Run the breakage sweep over expired certificates (OCC-guarded, atomic) | FinanceAdmin |
| GET | `/stores/{store_id}/breakage-runs` | List breakage runs of a store | StoreAdmin, FinanceAdmin |
| GET | `/stores/{store_id}/breakage-runs/{run_id}` | Read a breakage run | StoreAdmin, FinanceAdmin |
| GET | `/stores/{store_id}/fraud-flags` | List fraud flags of a store; filterable by account, type, status | StoreAdmin, FraudAnalyst |
| POST | `/stores/{store_id}/fraud-flags/{flag_id}/resolve` | Confirm or clear an OPEN fraud flag | FraudAnalyst |
| POST | `/stores/{store_id}/fraud-flags/{flag_id}/reopen` | Reopen a CLEARED fraud flag | FraudAnalyst |
| GET | `/rebate-programs` | List all rebate programs platform-wide | StoreAdmin, GuestService, FraudAnalyst, FinanceAdmin |
| GET | `/rebate-programs/{program_id}` | Read a rebate program by id | StoreAdmin, GuestService, FraudAnalyst, FinanceAdmin |
| GET | `/program-items` | List program items; filterable by program | StoreAdmin, GuestService, FraudAnalyst, FinanceAdmin |
| GET | `/program-items/{item_id}` | Read a program item by id | StoreAdmin, GuestService, FraudAnalyst, FinanceAdmin |
| GET | `/credit-accounts/{account_id}` | Read a credit account by id | StoreAdmin, GuestService, FraudAnalyst, FinanceAdmin, Customer, Contractor |
| GET | `/credit-accounts/{account_id}/receipts` | List receipts charged to an account | StoreAdmin, GuestService, FraudAnalyst, FinanceAdmin |
| GET | `/credit-accounts/{account_id}/rebate-submissions` | List rebate submissions of an account | StoreAdmin, GuestService, FraudAnalyst, FinanceAdmin, Customer, Contractor |
| GET | `/credit-accounts/{account_id}/certificates` | List certificates held by an account | StoreAdmin, GuestService, FraudAnalyst, FinanceAdmin, Customer, Contractor |
| GET | `/credit-accounts/{account_id}/fraud-flags` | List fraud flags of an account | StoreAdmin, FraudAnalyst |
| GET | `/credit-accounts/{account_id}/ledger-entries` | List ledger entries of an account (chronological) | StoreAdmin, GuestService, FraudAnalyst, FinanceAdmin |
| GET | `/credit-accounts/{account_id}/jobs` | List job purchases owned by a contractor account | StoreAdmin, GuestService, Contractor, FinanceAdmin |
| GET | `/job-purchases` | List job purchases platform-wide; filterable by contractor account and status | StoreAdmin, GuestService, Contractor, FinanceAdmin |
| GET | `/job-purchases/{job_id}` | Read a job purchase by id | StoreAdmin, GuestService, Contractor, FinanceAdmin |
| GET | `/job-purchases/{job_id}/receipts` | List receipts linked to a job purchase | StoreAdmin, GuestService, Contractor, FinanceAdmin |
| GET | `/receipts` | List receipts platform-wide; filterable by store, account, job | StoreAdmin, GuestService, FraudAnalyst, FinanceAdmin |
| GET | `/receipts/{receipt_id}` | Read a receipt by id | StoreAdmin, GuestService, FraudAnalyst, FinanceAdmin |
| GET | `/receipts/{receipt_id}/returns` | List returns processed against a receipt | StoreAdmin, GuestService, FraudAnalyst, FinanceAdmin |
| GET | `/receipts/{receipt_id}/rebate-submissions` | List submissions claiming a receipt | StoreAdmin, GuestService, FraudAnalyst, FinanceAdmin |
| GET | `/receipt-lines` | List receipt lines; filterable by receipt | StoreAdmin, GuestService, FraudAnalyst, FinanceAdmin |
| GET | `/receipt-lines/{line_id}` | Read a receipt line by id | StoreAdmin, GuestService, FraudAnalyst, FinanceAdmin |
| GET | `/returns` | List returns platform-wide; filterable by receipt | StoreAdmin, GuestService, FraudAnalyst, FinanceAdmin |
| GET | `/returns/{return_id}` | Read a return by id | StoreAdmin, GuestService, FraudAnalyst, FinanceAdmin |
| GET | `/rebate-submissions` | List submissions platform-wide; filterable by account, receipt, status | StoreAdmin, GuestService, FraudAnalyst, FinanceAdmin |
| GET | `/rebate-submissions/{submission_id}` | Read a submission by id | StoreAdmin, GuestService, FraudAnalyst, FinanceAdmin, Customer, Contractor |
| GET | `/rebate-submissions/{submission_id}/certificates` | List certificates issued against a submission | StoreAdmin, GuestService, FraudAnalyst, FinanceAdmin |
| GET | `/submission-lines` | List submission lines; filterable by submission, receipt line, program item | StoreAdmin, GuestService, FraudAnalyst, FinanceAdmin |
| GET | `/submission-lines/{line_id}` | Read a submission line by id | StoreAdmin, GuestService, FraudAnalyst, FinanceAdmin |
| GET | `/certificates` | List certificates; filterable by store, account, status, submission, reissue source | StoreAdmin, GuestService, FraudAnalyst, FinanceAdmin |
| GET | `/certificates/{certificate_id}` | Read a certificate by id | StoreAdmin, GuestService, FraudAnalyst, FinanceAdmin, Customer, Contractor |
| GET | `/certificates/{certificate_id}/ledger-entries` | List ledger entries posted against a certificate | StoreAdmin, GuestService, FraudAnalyst, FinanceAdmin |
| GET | `/certificates/{certificate_id}/reissues` | List certificates reissued from this certificate | StoreAdmin, GuestService, FraudAnalyst, FinanceAdmin |
| GET | `/ledger-entries` | List ledger entries platform-wide; filterable by account, certificate, entry type | StoreAdmin, GuestService, FraudAnalyst, FinanceAdmin |
| GET | `/ledger-entries/{entry_id}` | Read a ledger entry by id | StoreAdmin, GuestService, FraudAnalyst, FinanceAdmin |
| GET | `/fraud-flags` | List fraud flags platform-wide; filterable by account, type, status | StoreAdmin, FraudAnalyst |
| GET | `/fraud-flags/{flag_id}` | Read a fraud flag by id | StoreAdmin, FraudAnalyst |
| GET | `/breakage-runs` | List breakage runs platform-wide; filterable by store | StoreAdmin, FinanceAdmin |
| GET | `/breakage-runs/{run_id}` | Read a breakage run by id | StoreAdmin, FinanceAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_TENDER_SPLIT_MISMATCH` | 422 |
| `ERR_RECEIPT_IN_FUTURE` | 422 |
| `ERR_DUPLICATE_RECEIPT_NUMBER` | 409 |
| `ERR_INVALID_JOB_PURCHASE` | 422 |
| `ERR_SUBMISSION_WINDOW_CLOSED` | 422 |
| `ERR_DUPLICATE_RECEIPT_SUBMISSION` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_RESUBMIT_LIMIT_REACHED` | 409 |
| `ERR_ACCOUNT_FROZEN` | 409 |
| `ERR_ACCOUNT_BALANCE_NONZERO` | 409 |
| `ERR_FRAUD_FLAG_OPEN` | 409 |
| `ERR_ACCOUNT_FRAUD_CONFIRMED` | 409 |
| `ERR_CERTIFICATE_HELD` | 409 |
| `ERR_CERTIFICATE_EXPIRED` | 422 |
| `ERR_CERTIFICATE_WRONG_STORE` | 422 |
| `ERR_CERTIFICATE_REBATE_PURCHASE_BARRED` | 422 |
| `ERR_REDEMPTION_EXCEEDS_BALANCE` | 422 |
| `ERR_REISSUE_WINDOW_CLOSED` | 422 |
| `ERR_RETURN_QUANTITY_EXCEEDS_SOLD` | 422 |
| `ERR_PROGRAM_EMPTY` | 409 |
| `ERR_PROGRAM_WEEK_OVERLAP` | 409 |
| `ERR_PROGRAM_WEEK_PAST` | 409 |
| `ERR_STALE_VERSION` | 412 |
