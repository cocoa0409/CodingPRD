# Single-Family Rental Investment Marketplace API — Product Requirements Document

## 1. Introduction

Out-of-state investors buying single-family rental homes face a structural information asymmetry: the seller knows the property's condition, the tenant's payment habits, and the title history, while the buyer — often several states away — knows only what the seller chooses to disclose. This document specifies a marketplace API that closes that gap through a certification program, mandatory inspection and lease disclosure, and guarantee programs that backstop the buyer's underwriting assumptions after closing.

The marketplace orchestrates the full investment lifecycle: a seller registers and drafts a listing (a single property or a bulk portfolio), attaches inspection reports and tenant-in-place lease records, and submits the listing for certification review by an independent reviewer. Once certified and published, buyers run underwriting reports against disclosed data — under a disclosure-limitation regime when the seller elects confidentiality — place offers under optimistic-concurrency protection, negotiate through a bounded number of counter rounds, and close through escrow with remote signing support. At closing, the existing lease is assigned to the buyer without interruption, a property-management referral is onboarded with a fee computed from scheduled rent, and any issued vacancy or lease-up guarantee is activated. Post-close, buyers may claim guarantees within their coverage windows and raise disputes over disclosed conditions, adjudicated by claims adjusters under segregation-of-duties controls.

All temporal behavior in the system is driven by a logical clock rather than wall-clock time. The clock starts at exactly `2026-09-01T00:00:00Z` before any call sets it, and advancing the clock triggers expiry sweeps for offers and guarantees. The API is mounted under the `/marketplace` prefix.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` and `X-User-Role`. A request missing either header, carrying an empty value, or declaring a role not present in the role model below is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is not permitted for the target endpoint — or whose entity-backed caller does not own the resource where ownership is declared — is rejected with `ERR_FORBIDDEN` (HTTP 403).

The role model comprises seven roles, spelled exactly as follows: `PlatformAdmin`, `Seller`, `Buyer`, `CertificationReviewer`, `EscrowOfficer`, `PropertyManager`, and `ClaimsAdjuster`.

Three roles are entity-backed, meaning `X-User-ID` is the `id` of a persisted entity and ownership checks compare a resource's foreign-key field to `X-User-ID`:

- When `X-User-Role` is `Seller`, `X-User-ID` is the `id` of the acting `Seller`; ownership checks on any resource that references a `Seller` (for example, a listing's `seller_id`) compare the resource's foreign-key field to `X-User-ID`.
- When `X-User-Role` is `Buyer`, `X-User-ID` is the `id` of the acting `Buyer`; ownership checks on any resource that references a `Buyer` (for example, an offer's `buyer_id`) compare the resource's foreign-key field to `X-User-ID`.
- When `X-User-Role` is `PropertyManager`, `X-User-ID` is the `id` of the acting `PropertyManager`; ownership checks on any resource that references a `PropertyManager` (for example, a referral's `property_manager_id`) compare the resource's foreign-key field to `X-User-ID`.

The remaining four roles use opaque operator identifiers not tied to any persisted entity. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier; the server does not compare it to any entity's `id`. The same holds for `CertificationReviewer`, `EscrowOfficer`, and `ClaimsAdjuster` — each carries an opaque operator identifier that is never compared to an entity `id`. Note, however, that segregation-of-duties controls (§2.7) do compare an opaque reviewer's or adjuster's `X-User-ID` against recorded user ids on resources, and an opaque id equal to the recorded counterpart id is forbidden.

`PlatformAdmin` provisions parties (sellers, buyers, certification programs, property managers), issues guarantees, drives the logical clock, and may read any resource. `Seller` owns listings, inspections, and leases and negotiates offers. `Buyer` runs underwriting, makes offers, signs and funds escrow, and claims guarantees. `CertificationReviewer` verifies inspections and certifies listings. `EscrowOfficer` coordinates closing documents and cancellation. `PropertyManager` receives management referrals and may record payment records post-onboarding. `ClaimsAdjuster` adjudicates guarantee claims and disputes.

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

List endpoints accept `limit` and `offset` query parameters. `limit` defaults to 10, with a minimum of 1 and a maximum of 100. `offset` defaults to 0. All list responses are sorted by `created_at` ascending. The `meta` object of a list response includes the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and the Logical Clock

Every resource carries an `id` that is a server-minted UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. All resources except `PaymentRecord` additionally carry `updated_at` (ISO 8601 UTC, three fractional digits, refreshed on every mutation) and `version` (an integer that increments on every mutation of the resource). `PaymentRecord` is the sole exception: it carries only `id` and `created_at` — both `updated_at` and `version` are absent on payment records.

All temporal logic — offer expiry, guarantee claim windows, inspection staleness, late-payment flags, certification timestamps, and signing timestamps — is evaluated against a logical clock, never against wall-clock time. Before any call sets it, the logical clock reads exactly `2026-09-01T00:00:00Z`. A `PlatformAdmin` may advance the logical clock to a supplied `to_iso8601` instant through an admin-only test-driving capability; setting the clock runs the offer-expiry sweep (every offer still `SUBMITTED` whose `expires_at` has been reached or passed moves to `EXPIRED`) and the guarantee-expiry sweep (every `ACTIVE` guarantee whose claim window has passed moves to `EXPIRED`). The offer-expiry sweep is also evaluated lazily on any offer read or offer action.

### 2.5. Monetary Precision, Rounding, and Tier Boundaries

All monetary amounts are integer cents. All ratios and yields are integer basis points. Where a calculation produces a fractional intermediate, the result is floored to an integer. Several calculations pin a multi-step rounding order: floor the vacancy line first, then floor the operating-expense line on the post-vacancy base, then subtract — flooring only the final total is forbidden because it produces different cents. Tier thresholds elsewhere in the system are inclusive: a count exactly equal to a threshold qualifies for that threshold's tier.

### 2.6. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and only those two carry a version field.

Creating an offer against a listing requires `expected_listing_version` as a non-optional input carrying the buyer's last observed `version` of the listing. If the listing's current `version` has advanced since the client last read it — for example because another offer's creation bumped the listing version, invalidating the buyer's underwriting basis — the create is rejected with `ERR_STALE_LISTING_VERSION` (HTTP 412); the writer must re-read the listing and retry with the fresh version. Offer creation itself increments the listing's `version` by 1.

Signing an escrow requires `expected_escrow_version` as a non-optional input carrying the signer's last observed `version` of the escrow. If the escrow's current `version` has advanced since the signer last observed it — for example because a prior sign attempt already advanced it — the sign is rejected with `ERR_STALE_ESCROW_VERSION` (HTTP 412); the signer must re-read the escrow before signing. A successful sign increments the escrow's `version` by 1.

Endpoints not named above do not take a version field.

### 2.7. Segregation of Duties

Two controls prevent one individual from acting on both sides of a checkpoint. First, an inspection report can only be verified by someone other than the seller who submitted it: at verify time, the verifier's `X-User-ID` is compared against the report's recorded `submitted_by_seller_id`, and equality — including an opaque reviewer id equal to the submitting seller id — is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409). Second, a dispute can only be resolved by someone other than the party who opened it: at resolution time, the resolver's `X-User-ID` is compared against the dispute's recorded `opener_user_id`, and equality is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409).

### 2.8. Validation Ordering

Every request is checked against a fixed priority order, so that a request failing several checks surfaces the earliest failure rather than an arbitrary one. The order is: (1) presence and well-formedness of the `X-User-ID` and `X-User-Role` headers, failing with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`; (2) role permission and entity-backed ownership, failing with `ERR_FORBIDDEN`; (3) existence of every path id, validated left-to-right along the URL hierarchy, failing with `ERR_NOT_FOUND`; (4) whether the target entity is in a state from which the requested transition is defined, failing with `ERR_INVALID_STATE`; (5) segregation-of-duties checks, failing with `ERR_SEGREGATION_OF_DUTIES`; (6) shape, type, enum, and range constraints on create payloads, failing with `ERR_VALIDATION`; (7) the lease-period overlap rule on lease creation, failing with `ERR_LEASE_PERIOD_OVERLAP`; (8) the due-month bucket rule on payment-record creation, failing with `ERR_DUPLICATE_DUE_MONTH`; (9) temporal rules against the logical clock — offer expiry at accept, guarantee claim window, inspection staleness at certification — failing with `ERR_EXPIRED`; (10) cross-entity preconditions, failing with `ERR_PRECONDITION`; and finally (11) funds and fee checks — earnest money, cash-offer proof of funds, and funded-amount equality — failing with `ERR_INSUFFICIENT_FUNDS`. A stale-version rejection under §2.6 (HTTP 412) is reported before any business-rule failure for the guarded write.

Entity lifecycle transitions are driven through each entity's transition capability by supplying an `action` string naming the requested move (submit, begin review, certify, publish, withdraw, verify, reject, revise, disclose, redact, terminate, counter, resubmit, accept, decline, send documents, close, cancel, claim, pay, deny, start evidence, resolve, and so on); the set of valid actions per entity and their authorized roles are listed in §4. A request whose `action` is not defined from the entity's current state fails the state check with `ERR_INVALID_STATE`.

### 2.9. Nested Resource Retrieval

Nested URL paths are validated left-to-right: each path identifier must resolve to an existing resource before the next identifier is examined, and the first missing identifier yields `ERR_NOT_FOUND`. Where a nested resource's parent is implied by the path (for example, an inspection report under a listing, or a payment record under a lease), the child must actually belong to the named parent — a payment record's `lease_id` must equal the lease in the path, an escrow's `offer_id` the offer in the path, and so on; a mismatch is surfaced as `ERR_NOT_FOUND` rather than a permission error.

## 3. Business Logic & Workflows

### 3.1. Seller Onboarding, Listing Drafting, and Portfolio Tiers

A `PlatformAdmin` registers a seller with the seller's `legal_name`, the two-letter `seller_state` of the seller's domicile, and a `seller_type` of exactly `INDIVIDUAL`, `LLC`, or `TRUST`. A freshly registered seller starts with `listed_count` equal to zero and `bulk_discount_bps` equal to zero. The same administrative capability registers a buyer with `legal_name`, the two-letter `buyer_state`, an `entity_type` of exactly `INDIVIDUAL`, `LLC`, or `TRUST`, a self-attested `proof_of_funds_cents` describing the buyer's liquid funds (floor-checked later on cash offers), and an optional `accredited` attestation that defaults to false when omitted.

A seller then drafts a listing by supplying `seller_id` (which must be the seller's own id — a seller drafting into another seller's portfolio is rejected with `ERR_FORBIDDEN`), the property's `address_line`, the two-letter `listing_state` of the property (which later drives remote-signing and out-of-state logic), an `asking_price_cents` strictly greater than zero, and a `listing_kind` of exactly `SINGLE` or `PORTFOLIO`. When `listing_kind` is `PORTFOLIO`, an aggregate `bulk_price_cents` is required and must be present and positive before the listing can be submitted; omitting it on a portfolio draft is a shape violation rejected with `ERR_VALIDATION`. The draft may optionally name a `certification_program_id` — optional at draft time but mandatory before certification — and may set the `seller_asks_confidential` feature flag, which defaults to false; when true, tenant payment history is redacted in underwriting outputs and the REDACTED underwriting variant applies (§3.5). A new listing enters in `DRAFT` status.

A seller's `listed_count` is the count of that seller's listings whose status is anything other than `SOLD` or `WITHDRAWN`, and it is recomputed whenever a listing is submitted, withdrawn, or sold. The seller's `bulk_discount_bps` derives from `listed_count` as a tiered discount in basis points: at least 10 listed properties yields 500 basis points, at least 5 yields 300, at least 2 yields 100, and fewer than 2 yields 0. Thresholds are inclusive — a seller with exactly 5 listed properties earns 300 basis points, and exactly 2 earns 100. Both figures are recomputed together and can be re-read from the seller resource after any mutation that touches the listing set.

### 3.2. Certification Programs, Inspection Reports, and the Certification Gate

A `PlatformAdmin` defines a certification program with a unique `name`, a `min_inspection_score` between 0 and 100, a `min_title_grade` of exactly `A`, `B`, or `C` (graded so that `A` is best, then `B`, then `C`), a `requires_lease_disclosure` flag, a `guarantee_months_cap` bounding any guarantee issued under the program, and an `active` flag that defaults to true and controls whether the program accepts new certifications.

The seller attaches an inspection report to a listing, naming the `inspector_name`, the `inspection_date`, an `overall_score` between 0 and 100, a `roof_score` and a `systems_score` on the same 0–100 scale, an array `disclosed_defects` whose entries each carry a `code`, a `severity` of exactly `LOW`, `MEDIUM`, or `HIGH`, and a `description`, and a `title_grade` of `A`, `B`, or `C`. The report enters in `DRAFT` status. Submitting the report — `DRAFT` → `SUBMITTED` — is the seller's action and is only permitted while the listing itself is in `DRAFT`, `SUBMITTED`, or `IN_REVIEW`; submission stamps the report's `submitted_by_seller_id` with the acting seller's `X-User-ID`. A `CertificationReviewer` then either verifies the report (`SUBMITTED` → `VERIFIED`) or rejects it (`SUBMITTED` → `REJECTED`). Verification is segregation-of-duties controlled: the reviewer's `X-User-ID` must differ from `submitted_by_seller_id`, otherwise `ERR_SEGREGATION_OF_DUTIES`. A rejected report is not terminal for the listing — the seller may revise it (`REJECTED` → `DRAFT`), and a report may cycle through draft, submission, and rejection repeatedly until it verifies. `VERIFIED` and `REJECTED` are the terminal states of an individual report, though revision reopens a rejected one.

Listing certification is gated on the latest verified evidence. When the seller submits a listing (`DRAFT` → `SUBMITTED`), the listing's `listing_kind` must be `SINGLE`, or be `PORTFOLIO` with a positive `bulk_price_cents`, and the seller must own the listing; submission also recomputes the seller's `listed_count` and `bulk_discount_bps`. A `CertificationReviewer` begins review (`SUBMITTED` → `IN_REVIEW`) only once at least one inspection report for the listing has reached `VERIFIED`. Certification (`IN_REVIEW` → `CERTIFIED`) enforces, as cross-entity preconditions failing with `ERR_PRECONDITION`: the listing's `certification_program_id` is set and that program's `active` flag is true; the latest `VERIFIED` report — latest by `inspection_date`, with ties broken by `created_at` descending — has an `overall_score` of at least the program's `min_inspection_score`; that same report's `title_grade` is at least as good as the program's `min_title_grade` in the ordering `A` best, then `B`, then `C`; and, when the program's `requires_lease_disclosure` is true, at least one lease on the listing has `disclosure_status` of `DISCLOSED` with a tenancy `status` of `ACTIVE`. A temporal check rides on top: the latest verified report's `inspection_date` must lie within 180 days of the logical clock, or certification fails with `ERR_EXPIRED`. Successful certification stamps `certified_at` with the logical clock. At any point from `IN_REVIEW`, the seller may withdraw the listing to `WITHDRAWN`, which recomputes `listed_count` and `bulk_discount_bps`. Once `CERTIFIED`, the seller publishes the listing (`CERTIFIED` → `LISTED`), making it visible for offers.

### 3.3. Tenant-in-Place Leases, Disclosure, and Payment History

A seller attaches a lease to a listing by supplying a pseudonymous `tenant_alias` (tenant identity is never exposed directly), a `monthly_rent_cents` strictly greater than zero, a `lease_start` and a `lease_end` where the end must be strictly after the start (equality or inversion is a shape violation rejected with `ERR_VALIDATION`), and a `deposit_cents` of zero or more. A new lease enters with tenancy `status` of `ACTIVE` and `disclosure_status` of `PENDING`.

Lease periods on a single listing must not collide. Creating a lease is rejected with `ERR_LEASE_PERIOD_OVERLAP` if an existing `ACTIVE` lease on the same listing has a half-open occupancy interval — from its `lease_start` up to but not including its `lease_end` — that intersects the new lease's half-open interval. Pure adjacency is permitted: a new lease starting exactly when the existing one ends, or ending exactly when the existing one starts, does not overlap.

The lease carries two independent dimensions. The disclosure dimension moves from `PENDING` to `DISCLOSED` when the seller discloses the lease — permitted only while the tenancy dimension is `ACTIVE` — and from `PENDING` to `REDACTED` when the seller redacts it, permitted only when the listing's `seller_asks_confidential` flag is true. A redacted lease can later be disclosed (`REDACTED` → `DISCLOSED`, again requiring the tenancy dimension to be `ACTIVE`), so the disclosure dimension may cycle pending-to-redacted-to-disclosed independently of tenancy. The tenancy dimension moves from `ACTIVE` to `TERMINATED` when the seller terminates the lease, which is permitted only pre-sale, while the listing is in `DRAFT`, `SUBMITTED`, or `IN_REVIEW`; the other tenancy transition, `ACTIVE` → `ASSIGNED`, is the system's doing at closing and is described in §3.7.

Payment history accumulates against a lease. A seller — or, post-onboarding, a property manager — records a payment with a `due_date`, an optional `paid_date` (omitted or null means unpaid), and an `amount_cents` of zero or more. Each lease accepts at most one payment record per due month: creating a record is rejected with `ERR_DUPLICATE_DUE_MONTH` if another record on the same lease already has a `due_date` falling in the same UTC calendar month, regardless of the day or time component. Every payment record computes a `late` flag: the record is late when `paid_date` is set and falls strictly more than 5 days after `due_date`; a payment landing exactly at the five-day mark is not late. The flag is computed at creation and whenever `paid_date` is set.

### 3.4. Publication, Withdrawal, and Listing Lifecycle Cascade

A certified listing becomes market-visible when the owning seller publishes it (`CERTIFIED` → `LISTED`). From `LISTED`, the listing moves to `OFFER_PENDING` automatically the moment a first offer on it reaches `SUBMITTED`, and falls back from `OFFER_PENDING` to `LISTED` automatically whenever no offer on the listing remains in `SUBMITTED` or `COUNTERED` and none is `ACCEPTED` — the listing is never stranded in a pending state with no live negotiation. When an offer is accepted, the listing moves from `OFFER_PENDING` to `UNDER_CONTRACT`; when the escrow closes it moves to `SOLD`; and if the escrow is cancelled instead, it returns from `UNDER_CONTRACT` to `LISTED`. `SOLD` and `WITHDRAWN` are terminal.

A seller may withdraw a listing from `LISTED` or `OFFER_PENDING`, provided no offer on the listing is in `ACCEPTED` — attempting withdrawal past acceptance is a cross-entity precondition failure rejected with `ERR_PRECONDITION`. Withdrawal cascades: every offer on the listing still in `SUBMITTED` or `COUNTERED` moves to `WITHDRAWN`, any guarantee on the listing in `ISSUED` or `ACTIVE` moves to `VOID`, and the seller's `listed_count` and `bulk_discount_bps` are recomputed. Withdrawal from `IN_REVIEW` (§3.2) carries the same recomputation but has no offers or guarantees to cascade onto.

### 3.5. Buyer Underwriting Under Disclosure Limitations

A buyer runs an underwriting report against a listing by supplying `buyer_id` (the buyer's own id), a market-rent `rent_estimate_cents` strictly greater than zero, a `vacancy_rate_bps` assumption between 0 and 5000 basis points, and an `opex_rate_bps` assumption between 0 and 9000 basis points; out-of-range assumptions are shape violations rejected with `ERR_VALIDATION`. The report derives a `disclosure_limited` flag from the listing: it is true exactly when the listing's `seller_asks_confidential` is true, and when true the report omits tenant payment history from any output view. Two projections are computed at creation, in pinned order — net operating income first, then yield.

Projected net operating income, `projected_noi_cents`, comes in two variants selected by `disclosure_limited`. Under the BASE variant (the listing is not confidential): gross scheduled rent is `rent_estimate_cents` multiplied by 12; the vacancy allowance is gross multiplied by `vacancy_rate_bps` and divided by 10000, floored to integer cents; the operating-expense allowance is the post-vacancy remainder (gross minus the vacancy allowance) multiplied by `opex_rate_bps` and divided by 10000, floored to integer cents; and `projected_noi_cents` is gross minus the vacancy allowance minus the operating-expense allowance. Under the REDACTED variant (the listing is confidential, so tenant history is withheld and a vacancy risk uplift applies): the vacancy line instead multiplies gross by the sum of `vacancy_rate_bps` and a 300-basis-point uplift, divided by 10000 and floored, before the same operating-expense and subtraction steps follow on that higher vacancy base. The rounding order is pinned in both variants — floor vacancy first, floor operating expense on the post-vacancy base second, subtract last — and flooring only the final total is forbidden because it produces different cents.

Projected yield, `projected_yield_bps`, is then computed against a price basis: the listing's `asking_price_cents` when `listing_kind` is `SINGLE`, or the listing's `bulk_price_cents` when `listing_kind` is `PORTFOLIO`. The yield is `projected_noi_cents` multiplied by 10000 and divided by the price basis, floored to integer basis points. The price basis is never zero — asking prices are strictly positive and portfolio listings carry a positive bulk price — so no division guard is needed. Reports can be listed with optional `listing_id` and `buyer_id` filters, and read back individually.

### 3.6. Offers, Negotiation Rounds, and Expiry

A buyer creates an offer on a listing by supplying `buyer_id` (the buyer's own id), an `amount_cents` strictly greater than zero, an `earnest_money_cents` meeting the earnest floor described below, a `financing_type` of exactly `CASH`, `CONVENTIONAL`, or `HARD_MONEY`, and — per §2.6 — an `expected_listing_version` matching the listing's current `version`, with a mismatch rejected as `ERR_STALE_LISTING_VERSION`. A new offer enters in `DRAFT` with `round_number` set to 1, and its creation increments the listing's `version` by 1. At creation the offer pins `is_out_of_state`: true when the buyer's `buyer_state` differs from the listing's `listing_state`, false otherwise, and never recomputed afterward even if either party's state record later changes.

Submitting the offer (`DRAFT` → `SUBMITTED`) is the buyer's action and is permitted only while the listing is `LISTED` or `OFFER_PENDING`; earnest money must be at least 50000 cents (a 500-dollar floor), and when `financing_type` is `CASH` the buyer's `proof_of_funds_cents` must be at least the offer's `amount_cents` — a shortfall on either check is rejected with `ERR_INSUFFICIENT_FUNDS`. Submission stamps `expires_at` to the logical clock plus 72 hours and moves a `LISTED` listing to `OFFER_PENDING`. Offers do not live forever: when the logical clock reaches or passes `expires_at`, a `SUBMITTED` offer moves to `EXPIRED`, evaluated both when the clock is set and lazily on any offer read or offer action; if no other offer on the listing remains in `SUBMITTED` or `COUNTERED`, the listing falls back from `OFFER_PENDING` to `LISTED`.

Negotiation proceeds in bounded rounds. The seller counters a `SUBMITTED` offer (`SUBMITTED` → `COUNTERED`) with a `counter_amount_cents` strictly greater than zero, which increments `round_number` by 1. The buyer then resubmits (`COUNTERED` → `SUBMITTED`) with a new `amount_cents` in the payload, which replaces the offer's amount, refreshes `expires_at` to the logical clock plus 72 hours, and is subject to the same guards as the initial submission — the listing must still be in `LISTED` or `OFFER_PENDING`, and the funds checks (the earnest floor and, for cash offers, proof of funds covering the new amount) are re-evaluated. Resubmission is capped: when `round_number` has reached 5, further resubmission is rejected with `ERR_NEGOTIATION_ROUND_EXCEEDED`. Either side can walk away: the buyer declines a countered offer (`COUNTERED` → `DECLINED`), the seller declines an offer in `SUBMITTED` or `COUNTERED`, and the buyer withdraws an offer in `DRAFT`, `SUBMITTED`, or `COUNTERED`; each of these endings, when it leaves no other offer on the listing in `SUBMITTED` or `COUNTERED`, returns the listing from `OFFER_PENDING` to `LISTED`.

Acceptance is the seller's action on an offer in `SUBMITTED` or `COUNTERED` and carries two guards: no other offer on the listing may already be `ACCEPTED` (a violation is `ERR_PRECONDITION`), and the offer must not be past its `expires_at` at acceptance time (a violation is `ERR_EXPIRED`). Acceptance cascades: the listing moves from `OFFER_PENDING` to `UNDER_CONTRACT`, every sibling offer still in `SUBMITTED` or `COUNTERED` moves to `EXPIRED`, and an escrow is created for the accepted offer in `OPENED` status with `remote_signing_required` derived from the offer's pinned `is_out_of_state`. `ACCEPTED`, `DECLINED`, `WITHDRAWN`, and `EXPIRED` are terminal offer states.

### 3.7. Escrow, Remote Signing, and the Closing Cascade

Exactly one escrow exists per accepted offer, created at acceptance in `OPENED` status. The escrow's `remote_signing_required` flag is true when the accepted offer's pinned `is_out_of_state` is true. An `EscrowOfficer` sends closing documents (`OPENED` → `DOCS_SENT`), recording the `escrow_officer_name` supplied in the payload as the officer of record. The escrow for an accepted offer can be read back through the offer, returning an array of length zero or one.

Signing (`DOCS_SENT` → `SIGNED`) is the buyer's action on behalf of the accepted offer, guarded per §2.6 by `expected_escrow_version` matching the escrow's current `version` — a mismatch is rejected with `ERR_STALE_ESCROW_VERSION`. When `remote_signing_required` is true, the payload must carry a present, non-empty `remote_notarization_ref`; an out-of-state buyer attempting to sign without it is rejected with `ERR_REMOTE_SIGNING_REQUIRED`. A successful sign stamps `signed_at` with the logical clock and increments the escrow's `version` by 1.

Funding (`SIGNED` → `FUNDED`) is likewise the buyer's action: the payload's `funded_amount_cents` must equal the accepted offer's `amount_cents` exactly — any shortfall or overpayment is rejected with `ERR_INSUFFICIENT_FUNDS` — and the funded amount is recorded. Closing (`FUNDED` → `CLOSED`) is the `EscrowOfficer`'s action and fires the sale cascade: the listing moves from `UNDER_CONTRACT` to `SOLD`; the listing's `ACTIVE` lease moves to `ASSIGNED`, continuing the tenancy to the buyer, and the onboarding referral for the listing has its `lease_continuity_confirmed` set to true once that assignment lands; any management referral on the listing in `REFERRED` or `ACCEPTED` moves to `ONBOARDED` with its onboarding fee computed (§3.8); any guarantee on the listing in `ISSUED` moves to `ACTIVE`; and the seller's `listed_count` and `bulk_discount_bps` are recomputed. An escrow may instead be cancelled by the `EscrowOfficer` from `OPENED`, `DOCS_SENT`, or `SIGNED`, which returns the listing from `UNDER_CONTRACT` to `LISTED` and voids any guarantee on the listing in `ISSUED` or `ACTIVE`. `CLOSED` and `CANCELLED` are terminal.

### 3.8. Property-Management Referral and Onboarding at Closing

A `PlatformAdmin` registers a property manager with a `company_name`, an array `markets` of two-letter state codes the company serves, an `onboarding_fee_bps` between 0 and 2000 basis points of first-year scheduled rent, a `monthly_fee_bps` between 0 and 3000 basis points of collected rent, and an `active` flag defaulting to true that controls whether the company accepts referrals. Out-of-range fee schedules are shape violations rejected with `ERR_VALIDATION`.

A `PlatformAdmin` or the seller refers a property manager for a listing by supplying `property_manager_id`; the referral enters in `REFERRED` status. The property manager responds by accepting (`REFERRED` → `ACCEPTED`) or declining (`REFERRED` → `DECLINED`); the responder must be the referred company — a `property_manager_id` other than the caller's own id is `ERR_FORBIDDEN`. Acceptance additionally requires that the company's `active` flag is true and that the listing's `listing_state` appears in the company's `markets`; a mismatch on either is rejected with `ERR_PRECONDITION`. `ONBOARDED` and `DECLINED` are terminal.

Onboarding itself happens at closing, not by direct action: when the escrow for the listing closes, a referral in `REFERRED` or `ACCEPTED` moves to `ONBOARDED` and its `onboarding_fee_cents` is computed. The fee resolves the listing's lease first — the lease in `ACTIVE` or `ASSIGNED` status, and if several qualify, the one with the highest `monthly_rent_cents`, with ties broken by `created_at` ascending. Scheduled annual rent is that lease's `monthly_rent_cents` multiplied by 12, or zero if no such lease exists. The fee is then the scheduled annual rent multiplied by the property manager's `onboarding_fee_bps` and divided by 10000, floored to integer cents. The fee is derived from lease rent and the manager's fee basis only; it never feeds back into the lease, the offer, or the listing price. When the closing cascade assigns the lease to the buyer, the referral's `lease_continuity_confirmed` becomes true.

### 3.9. Guarantees, Claims, and Post-Close Disputes

A `PlatformAdmin` issues a guarantee on a listing that is `CERTIFIED` or `LISTED` — issuing against a listing in any other state is a cross-entity precondition failure rejected with `ERR_PRECONDITION` — choosing a `guarantee_kind` of exactly `VACANCY` or `LEASE_UP` and a `coverage_months` between 1 and the listing's certification program `guarantee_months_cap` inclusive — exceeding the cap is a shape violation rejected with `ERR_VALIDATION`. The guarantee enters in `ISSUED` status and becomes `ACTIVE` when the escrow for the listing closes.

A claim (`ACTIVE` → `CLAIMED`) is the buyer's action, permitted only to the buyer who owns the accepted offer for the listing and only within the claim window: the logical clock must lie within `coverage_months` multiplied by 30 days of the listing's sale timestamp; a claim outside the window is rejected with `ERR_EXPIRED`. The claim conditions differ by kind. For a `VACANCY` guarantee, no lease on the listing may be in `ACTIVE` or `ASSIGNED` status at claim time — a still-running tenancy makes the claim invalid. For a `LEASE_UP` guarantee, there must exist a payment record on the listing's leases with a `due_date` falling between the sale timestamp and the claim timestamp inclusive that is unpaid or flagged `late`. A claim whose kind-specific conditions are unmet is rejected with `ERR_GUARANTEE_NOT_CLAIMABLE`; likewise, a claim on a listing with no lease history at all — no lease in any status from which a claim amount could be priced — is rejected with `ERR_GUARANTEE_NOT_CLAIMABLE` before any claim amount is computed, regardless of `guarantee_kind`, and a rejected claim leaves the guarantee untouched in `ACTIVE`. A valid claim stamps `claimed_at` with the logical clock and computes `claim_amount_cents`.

The claim amount is computed per variant. For `VACANCY`, the monthly coverage is the `monthly_rent_cents` of the lease that was assigned at closing; if none exists, the listing's most recent `TERMINATED` lease is used instead — most recent by `lease_end`, with ties broken by `created_at` descending; if no lease exists at all, the claim is invalid as above. Elapsed months are the days between the sale timestamp and the claim timestamp divided by 30 and floored. Payable months are `coverage_months` minus elapsed months, floored at zero. The claim amount is the monthly coverage multiplied by the payable months — a forward-looking rent replacement. For `LEASE_UP`, the claim amount is the lesser of two quantities: the sum of `amount_cents` over payment records on the listing's leases with `due_date` between the sale timestamp and the claim timestamp inclusive that are unpaid (no `paid_date`) or flagged `late`; and a cap equal to the resolved lease's `monthly_rent_cents` — the assigned lease, else the most recent terminated lease as above — multiplied by `coverage_months`. Where `VACANCY` pays forward-looking rent months, `LEASE_UP` reimburses historical unpaid or late records.

A `ClaimsAdjuster` settles a claim by paying it (`CLAIMED` → `PAID`) or denying it (`CLAIMED` → `VOID`). A guarantee whose claim window passes while still `ACTIVE` moves to `EXPIRED`, evaluated when the clock is set. Guarantees can also be voided before closing by listing withdrawal or escrow cancellation (§3.4, §3.7). `PAID`, `EXPIRED`, and `VOID` are terminal.

Post-close, either party may open a dispute on a `SOLD` listing over a disclosed condition — a dispute on a listing that has not reached `SOLD` is rejected with `ERR_PRECONDITION` — supplying `opened_by` of exactly `BUYER` or `SELLER`, the contested `condition_code`, and a proposed `remedy_cents` of zero or more; the opener's `X-User-ID` is recorded as `opener_user_id` and the dispute enters in `OPENED` status. A `ClaimsAdjuster` starts evidence gathering (`OPENED` → `EVIDENCE`) only when the `condition_code` exists among the `disclosed_defects` codes of the listing's latest `VERIFIED` inspection report — latest by `inspection_date`, ties broken by `created_at` descending; a code the seller never disclosed is rejected with `ERR_DISPUTE_CONDITION_UNDISCLOSED`. Resolution (`EVIDENCE` → `RESOLVED_BUYER` or `EVIDENCE` → `RESOLVED_SELLER`) is the adjuster's action under segregation of duties: the resolver's `X-User-ID` must differ from `opener_user_id`, else `ERR_SEGREGATION_OF_DUTIES`. Resolving for the buyer carries a cascade: if a guarantee in `ACTIVE` covers the listing and the contested `condition_code` maps to a disclosed defect, that guarantee moves from `ACTIVE` to `CLAIMED` with its `claim_amount_cents` recomputed per §3.9's claim formula. Resolving for the seller has no such cascade. The opener — and only the opener, matched by `X-User-ID` against `opener_user_id` — may withdraw a dispute from `OPENED` or `EVIDENCE` to `WITHDRAWN`. `RESOLVED_BUYER`, `RESOLVED_SELLER`, and `WITHDRAWN` are terminal.

## 4. Endpoint Definitions

All endpoints live under the `/marketplace` prefix. Endpoints that create a new resource return HTTP 201 with the created resource; endpoints that modify an existing resource (transitions, sign, fund, clock set) return HTTP 200 with the updated resource; reads return HTTP 200. Error responses carry the HTTP status listed in §5 with the error envelope of §2.2.

| Method | Path | Description | Authorized Role(s) |
|--------|------|-------------|--------------------|
| POST | /marketplace/_clock/set_current_utc | Advance the logical clock; runs offer-expiry and guarantee-expiry sweeps | PlatformAdmin |
| POST | /marketplace/sellers | Register a seller | PlatformAdmin |
| GET | /marketplace/sellers/{id} | Get a seller (listed_count, bulk_discount_bps re-read after mutations) | PlatformAdmin, Seller |
| POST | /marketplace/buyers | Register a buyer | PlatformAdmin |
| POST | /marketplace/certification-programs | Create a certification program | PlatformAdmin |
| POST | /marketplace/listings | Create a listing (DRAFT) | Seller |
| GET | /marketplace/listings | List listings; filterable and paginated | PlatformAdmin, Seller, Buyer, CertificationReviewer |
| GET | /marketplace/listings/{id} | Get a listing | PlatformAdmin, Seller, Buyer, CertificationReviewer |
| POST | /marketplace/listings/{id}/transition | Drive listing lifecycle; action in {SUBMIT, BEGIN_REVIEW, CERTIFY, PUBLISH, WITHDRAW}. SUBMIT/PUBLISH/WITHDRAW = Seller; BEGIN_REVIEW/CERTIFY = CertificationReviewer | Seller, CertificationReviewer |
| POST | /marketplace/listings/{id}/inspection-reports | Attach an inspection report (DRAFT) | Seller |
| GET | /marketplace/listings/{id}/inspection-reports | List inspection reports for a listing | PlatformAdmin, Seller, Buyer, CertificationReviewer |
| POST | /marketplace/inspection-reports/{id}/transition | Drive inspection lifecycle; action in {SUBMIT, VERIFY, REJECT, REVISE}. SUBMIT/REVISE = Seller; VERIFY/REJECT = CertificationReviewer | Seller, CertificationReviewer |
| POST | /marketplace/listings/{id}/leases | Attach a lease (tenant-in-place) | Seller |
| GET | /marketplace/listings/{id}/leases | List leases for a listing | PlatformAdmin, Seller, Buyer |
| POST | /marketplace/leases/{id}/transition | Drive lease dimensions; action in {DISCLOSE, REDACT, TERMINATE} | Seller |
| GET | /marketplace/leases/{id} | Get a lease | PlatformAdmin, Seller, Buyer, PropertyManager |
| POST | /marketplace/leases/{id}/payment-records | Record a tenant payment | Seller, PropertyManager |
| GET | /marketplace/leases/{id}/payment-records | List payment records for a lease | PlatformAdmin, Seller, Buyer, PropertyManager |
| POST | /marketplace/listings/{id}/underwriting-reports | Run buyer underwriting (rent estimate, expense assumptions, projected yield) | Buyer |
| GET | /marketplace/underwriting-reports | List underwriting reports; filterable by listing_id, buyer_id | PlatformAdmin, Buyer |
| GET | /marketplace/underwriting-reports/{id} | Get an underwriting report | PlatformAdmin, Buyer |
| POST | /marketplace/listings/{id}/offers | Create an offer (OCC on listing version) | Buyer |
| GET | /marketplace/offers | List offers; filterable by listing_id, buyer_id, status | PlatformAdmin, Seller, Buyer |
| GET | /marketplace/offers/{id} | Get an offer | PlatformAdmin, Seller, Buyer |
| POST | /marketplace/offers/{id}/transition | Drive offer negotiation; action in {SUBMIT, COUNTER, RESUBMIT, ACCEPT, DECLINE, WITHDRAW}. SUBMIT/RESUBMIT/WITHDRAW = Buyer; COUNTER/ACCEPT = Seller; DECLINE = Buyer (on COUNTERED) or Seller (on SUBMITTED/COUNTERED) | Buyer, Seller |
| GET | /marketplace/offers/{id}/escrow | Get the escrow for an accepted offer (array of length 0 or 1) | PlatformAdmin, Seller, Buyer, EscrowOfficer |
| POST | /marketplace/escrows/{id}/sign | Buyer signs (remote notarization ref required when out-of-state); OCC on escrow version | Buyer |
| POST | /marketplace/escrows/{id}/fund | Buyer funds escrow; amount must equal the offer amount exactly | Buyer |
| POST | /marketplace/escrows/{id}/transition | Escrow officer actions; action in {SEND_DOCS, CLOSE, CANCEL} | EscrowOfficer |
| POST | /marketplace/property-managers | Register a property manager | PlatformAdmin |
| POST | /marketplace/listings/{id}/management-referrals | Refer a property manager at closing | PlatformAdmin, Seller |
| GET | /marketplace/management-referrals | List referrals; filterable by listing_id, property_manager_id | PlatformAdmin, Seller, Buyer, PropertyManager |
| GET | /marketplace/management-referrals/{id} | Get a referral | PlatformAdmin, Seller, Buyer, PropertyManager |
| POST | /marketplace/management-referrals/{id}/transition | Property manager responds to a referral; action in {ACCEPT, DECLINE} | PropertyManager |
| POST | /marketplace/listings/{id}/guarantees | Issue a vacancy/lease-up guarantee (listing must be CERTIFIED or LISTED) | PlatformAdmin |
| GET | /marketplace/listings/{id}/guarantees | List guarantees for a listing | PlatformAdmin, Seller, Buyer, ClaimsAdjuster |
| POST | /marketplace/guarantees/{id}/transition | Guarantee lifecycle; action in {CLAIM, PAY, DENY}. CLAIM = Buyer; PAY/DENY = ClaimsAdjuster | Buyer, ClaimsAdjuster |
| POST | /marketplace/listings/{id}/disputes | Open a post-close dispute on a disclosed condition (listing must be SOLD) | Buyer, Seller |
| GET | /marketplace/listings/{id}/disputes | List disputes for a listing | PlatformAdmin, Seller, Buyer, ClaimsAdjuster |
| POST | /marketplace/disputes/{id}/transition | Dispute lifecycle; action in {START_EVIDENCE, RESOLVE_BUYER, RESOLVE_SELLER, WITHDRAW}. START_EVIDENCE/RESOLVE_* = ClaimsAdjuster; WITHDRAW = opener (Buyer or Seller) | ClaimsAdjuster, Buyer, Seller |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|----------|------------------|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_SEGREGATION_OF_DUTIES | 409 |
| ERR_VALIDATION | 422 |
| ERR_EXPIRED | 409 |
| ERR_PRECONDITION | 409 |
| ERR_INSUFFICIENT_FUNDS | 402 |
| ERR_STALE_LISTING_VERSION | 412 |
| ERR_STALE_ESCROW_VERSION | 412 |
| ERR_NEGOTIATION_ROUND_EXCEEDED | 409 |
| ERR_GUARANTEE_NOT_CLAIMABLE | 409 |
| ERR_REMOTE_SIGNING_REQUIRED | 409 |
| ERR_DISPUTE_CONDITION_UNDISCLOSED | 409 |
| ERR_LEASE_PERIOD_OVERLAP | 409 |
| ERR_DUPLICATE_DUE_MONTH | 409 |
