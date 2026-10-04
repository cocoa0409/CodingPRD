# Clearing, Netting and Settlement Operations API — Product Requirements Document

## 1. Introduction

A central counterparty exists to stand between every buyer and every seller, and the software that runs that function is judged by one question alone: after the trades, the netting, the funding, the fails and — on the worst days — the default, does every participant's obligation come out exactly right? This document specifies the API for clearing-house participant operations covering membership and financial standards, clearing-fund deposits, trade submission and comparison, multilateral netting, delivery-versus-payment settlement, fail management, corporate-action servicing of book-entry custody, clearing-fund sizing, and default management with liquidation and loss allocation.

The system is built around a small number of durable ledgers. A participant's membership standing is gated by a net-capital floor that depends on its class. Its collateral lives in an append-only deposit ledger whose derived balance determines whether it is covering its obligations. Its trades are recorded once and then compared, locked in, disputed, reverted or cancelled, with matching cascaded across the contra pair. At the end of each settlement cycle the whole set of locked trades on a security and settlement date collapses, per participant, into a single net quantity and a single cash leg, which is then funded and settled against the delivery-versus-payment convention. Everything that goes wrong — a suspended member, a failed delivery, a defaulted member whose estate cannot cover the loss — has a defined, ordered consequence rather than an ad-hoc one.

Because the clearing house is a system of record with real money attached, the specification is deliberately unforgiving about precision, ordering and precedence. Monetary values are integer cents; where a division or a rounding site exists it is named and ordered exactly; where a rule fires it names the exact error identifier and HTTP status; and where two writers may touch the same cycle or the same fund, the losing writer is rejected rather than silently overwriting.

## 2. Global Specifications & System-Wide Principles

The rules below apply across every domain area of the API. They are the contract-level surface — headers, envelope, pagination, precision, identifiers and validation precedence — that a caller can rely on without reading any particular workflow.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the acting role. A request whose `X-User-Role` header is missing or does not name one of the declared roles is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is known but not permitted for the attempted operation, per the RBAC matrix, is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes exactly three roles: `PlatformAdmin`, `ClearingMember`, and `RiskOfficer`. Their operating identities are materially different, and the difference matters wherever ownership is checked.

When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it for audit, but it is never compared to any entity's `id`. The same is true when `X-User-Role` is `RiskOfficer`: the identifier is opaque and no ownership comparison is ever performed against it. When `X-User-Role` is `ClearingMember`, by contrast, `X-User-ID` is the `id` of the acting `Participant`; ownership checks on any resource that references a `Participant` compare the resource's `participant_id` field to `X-User-ID`.

The roles are segregated so that no single operator both admits a member and prices its risk. `PlatformAdmin` owns participant lifecycle, security and window registration, netting and settlement cycles, corporate actions, and dispute resolution. `RiskOfficer` owns financial-standard reviews, clearing-fund establishment and sizing, and the default-management workflow. `ClearingMember` owns the economic side: trade submission and lock-in, dispute initiation, collateral postings, settlement funding, self-service affirmation, and sealed bidding in a default auction. `PlatformAdmin` holds no clearing-member economic role and therefore never posts collateral or bids.

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

List endpoints accept a `limit` parameter naming the maximum number of items to return, and an `offset` parameter naming the number of items to skip. When `limit` is omitted it defaults to 10; it must be at least 1 and at most 100, and a value outside that range is a request error. When `offset` is omitted it defaults to 0. Unless a specific list endpoint states otherwise, every list endpoint returns its resources sorted by creation timestamp in ascending order.

A paginated response carries the four pagination fields in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Membership Standing and Financial Standards

Every clearing member is a `Participant` classified as exactly one of `BANK`, `BROKER_DEALER`, `CUSTODIAN_BANK`, or `INSURANCE_CARRIER` in its `participant_class`. A participant's `membership_status` advances through `PENDING`, `ACTIVE`, `SUSPENDED`, `DEFAULTED` and `EXPELLED`; `EXPELLED` is terminal and is reached only through default management. A participant also carries `net_capital_cents`, the capital figure at its most recent financial-standard review, and `requires_segregated_custody`, a flag that, when true, obliges the member to hold at least one `SEGREGATED` custody account before it may be admitted.

Two fields on every participant are derived rather than supplied. `required_min_net_capital_cents` is the capital floor the member must meet, recomputed on every financial-standard review and on admission. `financial_standard_status` is either `PASS` or `FAIL`, resolved by comparing `net_capital_cents` against `required_min_net_capital_cents` at that same review. A third system field, `last_financial_review_at`, is an ISO 8601 UTC timestamp with three fractional digits, stamped by every financial-standard review.

The capital floor is the greater of a class base and a flat house floor of 500,000,000 cents. The class bases are 1,500,000,000 cents for a `BANK`, 250,000,000 cents for a `BROKER_DEALER`, 750,000,000 cents for a `CUSTODIAN_BANK`, and 1,000,000,000 cents for an `INSURANCE_CARRIER`. Because the comparison against the flat floor is inclusive, a class base that exactly equals the floor is kept as-is; in practice the only class whose base falls below the floor is the `BROKER_DEALER`, which is therefore held to 500,000,000 cents rather than to its own 250,000,000-cent base. `BANK`, `CUSTODIAN_BANK` and `INSURANCE_CARRIER` members are held to their class bases unchanged.

The financial-standard review is an operator action and is not gated on membership state: it may be run against a participant in any of `PENDING`, `ACTIVE`, `SUSPENDED`, `DEFAULTED` or `EXPELLED`. `is_defaulted` is a system boolean that begins false and becomes true the moment a default determination is applied to the member; it is never cleared by anything short of a served liquidation.

### 2.5. Collateral Deposits and Coverage Status

Each participant owns one clearing-member deposit pool, a `ClearingMemberDeposit` whose `status` is `PENDING` until first assessed and thereafter `SATISFIED`, `DEFICIENT_GRACE` or `DEFICIENT_DEFAULT`. The pool is fed by an append-only ledger of `DepositTransaction` rows. A posting carries `amount_cents`, a signed integer where a positive value posts collateral and a negative value releases it, and a `txn_type` of `POST` or `RELEASE` derived from the sign of `amount_cents`. A negative posting must carry a `reason_code`; a positive posting need not. Zero-amount postings cannot exist, because validation rejects them.

The pool's read-only `posted_amount_cents` is the sum of `amount_cents` over every transaction of that deposit, including negative releases. Coverage is evaluated in the same pass against the member's obligations: those obligations are the sum of `settlement_obligation_cents` across all of the member's net positions whose `dvp_status` is not `FAILED`. When the obligation total is zero, or when `posted_amount_cents` reaches at least that total, the pool is `SATISFIED`; a balance exactly equal to the obligations is therefore sufficient. When the balance falls below a non-zero obligation total, the pool takes the value `DEFICIENT_GRACE`. A shortfall against obligations is surfaced as `ERR_INSUFFICIENT_DEPOSIT`. The separate value `DEFICIENT_DEFAULT` is not derived from the balance arithmetic at all — it is imposed by the risk workflow when a member is suspended or declared in default.

The deposit ledger is immutable once written. A release that would drive `posted_amount_cents` below zero, or that omits its reason, is rejected with `ERR_DEPOSIT_RELEASE_INVALID`; a posting or funding amount of zero is rejected with `ERR_INVALID_AMOUNT`.

### 2.6. Trade Submission State Dimensions

A `TradeSubmission` is described by three independent state dimensions that coexist on the same row and evolve separately. The first is `lock_status`, whose values are `OPEN`, `LOCKED_IN`, `DISPUTED` and `CANCELLED`. The second is `match_status`, whose values are `UNMATCHED`, `MATCHED`, `ALLEGED` and `UNRESOLVED`. The third is `affirmation_status`, whose values are `UNCONFIRMED`, `AFFIRMED` and `UNCONFIRMED_BREACH`. A trade may therefore be `LOCKED_IN` while still `UNMATCHED`, or `MATCHED` while still `OPEN`; the dimensions are not locks on each other.

Alongside these dimensions, `allegations_received` is a read-only counter of the non-`CANCELLED` contra submissions whose comparison tuple equals this row's. Comparison identity is defined over five terms — the party pair, the instrument, the opposite side, the exact `quantity`, and the exact `trade_date` — and it is this tuple, never the row identity, that drives matching, disputing, reverting and cancelling as a pair. The submitted economic terms are `side` (`BUY` or `SELL`), `quantity` in units, `trade_price_cents` per unit, `trade_date` as an ISO 8601 UTC instant, the `security_id` being cleared, and the `counterparty_participant_id` of the contra member, which must differ from the submitter's own `participant_id`.

### 2.7. Settlement Cycle Timeline Governance

A `SettlementWindow` is the settlement cycle for one security and one settlement date. Its `settlement_date` is an ISO 8601 date of the form YYYY-MM-DD, and it is unique per (`security_id`, `settlement_date`) among windows that have not been `CLOSED`. The window carries two cut-offs: `trade_entry_deadline`, an ISO 8601 UTC instant after which trades on that security can no longer be locked in, and `affirmation_deadline`, the cut-off for participant affirmation, which must be strictly later than `trade_entry_deadline`. The `status` field moves from `OPEN` to `NETTED` to `SETTLED` to `CLOSED`, and a window may also pass directly from `NETTED` to `CLOSED` without settling. A window is only ever mutated while it is `OPEN`, and once it has been netted it is frozen against further trade mutation; the sole exception is the system's automatic close of an `OPEN` window when the last `ACTIVE` participant is removed, described in §3.6, which opening a window does not itself trigger.

Ordering of the two cut-offs is enforced at creation: a window whose `affirmation_deadline` is not strictly after its `trade_entry_deadline` is rejected with `ERR_AFFIRMATION_DEADLINE_ORDER` (HTTP 422). Opening a cycle by netting is additionally a function of the logical clock: if the clock reads at or after the window's `affirmation_deadline`, opening is refused with `ERR_AFFIRMATION_DEADLINE_PASSED`.

Every deadline, effective-date and grace evaluation in this document is made against a single logical clock, not against real wall-clock time. That clock is driven by an operator-only test capability that accepts a `to_iso8601` instant and reports the resolved `current_utc`; its startup default is exactly 2026-09-01T00:00:00Z, and until the capability is invoked the clock reads precisely that instant and never falls back to the host's real time.

### 2.8. Monetary Precision and Ledger Conventions

All monetary quantities in this system are integer cents. Where a calculation performs a division, the result is rounded half up, and the rounding is applied exactly once at the site the calculation rule names — never once per term and never after a clamp. The multilateral netting calculation performs no division at all, so no rounding step exists in it; every trade gross is an exact integer product and the sum is taken before any other operation. Quantity arithmetic that produces a fractional entitlement is truncated toward zero rather than rounded, because entitlement is a whole-unit concept.

Where a calculation admits two reporting conventions, this system uses the one named in the relevant rule. For netting, the house reports a single net position per participant per security — opposite-side trades combine into one net quantity and one signed cash leg — rather than the reporting convention that keeps receive and deliver legs separate. The two conventions agree on the net quantity but diverge on the settlement obligation whenever a buy exists, so implementers must use the net convention.

### 2.9. Optimistic Concurrency Control

Two write operations require the client to present the version it last observed, and only those two. Running a netting cycle requires the field `expected_window_version`, carrying the client's last-observed `version` of the target `SettlementWindow`. Re-sizing a clearing fund requires the field `expected_fund_version`, carrying the client's last-observed `version` of the target `ClearingFund`. Both fields are mandatory on their request. If the supplied value does not equal the parent entity's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). A client's view is stale precisely when another writer has advanced the parent's version since the client last read it; the rejection prevents the client from overwriting a cycle or a fund generation it has not observed. No other endpoint accepts a version field, and no other endpoint performs this check.

### 2.10. Common Resource Properties

Resources that carry the common field set include a standard quartet of system-managed properties. `id` is a server-minted identifier formatted as a UUID with no type prefix. `created_at` is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created. `updated_at` is the same format, recording when the resource was last modified, and it is refreshed by every mutation including derived-field recomputations. `version` is an integer that increments on every modification and is the value carried by the optimistic-concurrency fields of §2.9.

Certain fields are fixed at creation and can never be revised afterwards: a participant's `lei`, a security's `ticker`, `cusip` and `currency`, and a window's `security_id` and `settlement_date`. An update that supplies any of them is refused with `ERR_IMMUTABLE_FIELD` (HTTP 422).

Two ledger entities in this system are deliberately outside that convention. A `DepositTransaction` and a `LossAllocationTransaction` are append-only records that are immutable once written; each carries only `id` and `created_at`, and neither carries `updated_at` nor `version`. Nested sub-resources also receive a UUID `id`. Every mutation described anywhere in this document — a state change, a recomputed balance, a cascade to a contra row, a servicing adjustment — is a mutation that refreshes `updated_at` and increments `version` on the entity it touches.

### 2.11. Hierarchical Resource Retrieval

When a request path names more than one resource, the system validates existence left to right in path order and fails on the first identifier that does not resolve. A path-level miss is reported as `ERR_RESOURCE_NOT_FOUND` (HTTP 404). A participant identifier referenced in a request body or used as a path identifier that does not resolve to a participant is reported as `ERR_PARTICIPANT_NOT_FOUND` (HTTP 404), and a security identifier that does not resolve is reported as `ERR_SECURITY_NOT_FOUND` (HTTP 404). A trade whose designated settlement window does not exist for its (`security_id`, `settlement_date`) is reported as `ERR_WINDOW_NOT_FOUND` (HTTP 404).

### 2.12. Validation Precedence

When more than one rule could reject the same request, the checks fire in a fixed order, and the error a caller sees is the one belonging to the earliest failed check. Authentication is decided first: an absent or unrecognized role yields `ERR_UNAUTHENTICATED` before anything else is considered. Authorization is next: a role that is known but not permitted yields `ERR_UNAUTHORIZED` before any resource is inspected. Existence follows, left to right along the path, producing `ERR_RESOURCE_NOT_FOUND` and its participant- and security-specific variants. Only then is state evaluated, yielding `ERR_INVALID_STATE` when the target is not in the state a transition requires.

Business safety rules sit below state. This ordering is observable: a request that both targets a resource in the wrong state and comes from a member that is not `ACTIVE` surfaces as `ERR_INVALID_STATE`, not `ERR_PARTICIPANT_NOT_ACTIVE`, because state is decided first. Within the business rules, membership standing is checked before the more specific domain gates, so a `FAIL` financial standard on a member that is also not `ACTIVE` surfaces as `ERR_PARTICIPANT_NOT_ACTIVE`. Structural request validation — a missing required field, a mistyped value, or an unknown field, reported as `ERR_INVALID_REQUEST` — and the optimistic-concurrency version check, reported as `ERR_STALE_VERSION`, are evaluated after the state and business-safety gates for their operations. The one place where the version check pre-empts a state gate is the clearing-fund recompute: a caller that presents a version it has not observed is told its view is stale even when the fund is not in a recomputable state.

### 2.13. Clearing Fund Integrity and Default Management Principles

A `ClearingFund` is scoped to one security and one participant class, recorded in its `participant_class`; only members of that class are sized, and only they are debited when a loss is allocated. The fund carries a read-only `fund_balance_cents`, the aggregate of its non-`RELEASED` fund contributions, and a read-only `total_component_cents`, the sum of the latest component for every participant within the class filter. `last_computed_at` is stamped by every sizing computation, and `experiences_deficit` is a read-only flag that becomes true when the component balance of any sized participant's latest component is strictly negative after an allocation.

The fund is sized into `FundComponent` rows. Each row points at its parent fund through `clearing_fund_id`, at the member it sized through `participant_id`, and at the fund's security through `security_id`. A component's `component_amount_cents` is its frozen initial-form amount, fixed at the value first emitted for its fund, participant and generation and never rewritten afterwards. Its `component_balance_cents` is the initial amount plus every loss allocation posted against it minus every release posted against it, so it is the balance that later allocations proportion against. Each component carries a monotone `generation`; the first sizing generation is 1 and every subsequent recompute of the same fund increments the generation for every participant of the fund's class, with earlier generations left in place rather than renumbered. A component's `status` is `ASSESSED`, `COLLECTED` or `RELEASED`.

Two failure conditions are explicit. A loss allocation that would debit a candidate set whose component balances sum to zero or less cannot be covered and is refused with `ERR_CLEARING_FUND_DEFICIT`. An allocation requested against a default proceeding whose `deficit_amount_cents` is not positive has nothing to allocate and is refused with `ERR_NO_ALLOCATABLE_DEFICIT`. A default proceeding is advanced through `DECLARED`, `LIQUIDATING`, `LIQUIDATED` and `ALLOCATED`; running the auction before the proceeding has reached `LIQUIDATING`, or advancing a proceeding that is not in `DECLARED`, is refused with `ERR_PROCEEDING_NOT_LIQUIDATING`.

## 3. Business Logic & Workflows

### 3.1. Participant Admission and the Financial-Standard Review

A `PlatformAdmin` registers a clearing member by supplying its `legal_name`, its `lei`, its `participant_class`, and its `net_capital_cents`, and optionally flagging `requires_segregated_custody`. The `lei` is a legal entity identifier that is unique across participants and immutable after creation. Registration leaves the member in `PENDING` and immediately opens a clearing-member deposit pool for it in `PENDING` status; the capital floor and financial-standard status are computed at the same moment, so a newly registered member already reports `required_min_net_capital_cents` and a `financial_standard_status`.

Admission to clearing membership — the `PENDING` to `ACTIVE` transition — is an administrative act performed by a `PlatformAdmin`, and it is gated in a fixed order. The member must still be in `PENDING`, or the attempt fails with `ERR_INVALID_STATE`. Its `financial_standard_status` must be `PASS`, or the attempt fails with `ERR_FINANCIAL_STANDARD_NOT_MET`. If `requires_segregated_custody` is true, the member must already hold at least one custody account whose `account_type` is `SEGREGATED`, or the attempt fails with `ERR_SEGREGATED_CUSTODY_REQUIRED`. Only after those gates pass is the member set to `ACTIVE`. Admission re-derives the capital floor, the financial-standard status, and the `last_financial_review_at` stamp, and re-evaluates the member's deposit pool standing, which may surface `ERR_INSUFFICIENT_DEPOSIT` if the member's obligations already outrun its posted collateral.

Capital changes are handled separately by a `RiskOfficer`, who supplies a fresh `net_capital_cents` in a financial-standard review. The review recomputes the class floor and the pass/fail verdict and re-stamps `last_financial_review_at`; it also re-evaluates the member's deposit pool standing and advances the member's version. The review is not gated on membership state and may be run while the member is `PENDING`, `ACTIVE`, `SUSPENDED`, `DEFAULTED` or `EXPELLED`. Unlike admission and reinstatement, the review assigns the re-derived standing rather than surfacing a shortfall: an under-covered member is left at the `DEFICIENT_GRACE` standing and the call succeeds, because the `ERR_INSUFFICIENT_DEPOSIT` clause of this section attaches to admission and reinstatement only.

Suspension is the administrative response to a member that can no longer be relied upon. A `PlatformAdmin` may suspend a member only while it is `ACTIVE`; otherwise the attempt fails with `ERR_INVALID_STATE`. Suspension is a cascade, not a flag flip. The member is set to `SUSPENDED` and its deposit pool is forced to `DEFICIENT_DEFAULT`. Every one of the member's own submissions still in `OPEN` or `LOCKED_IN` is set to `CANCELLED` with `match_status` `UNRESOLVED`. Every other non-`CANCELLED` submission whose counterparty is this member and which was `LOCKED_IN` — in other words, the member's locked contras — has its `match_status` set to `ALLEGED`. Every net position belonging to the member that is not already `FAILED` is marked `FAILED`, with `failed_at` stamped at the current logical clock, `failed_at_price_cents` taken from the security's `prev_settlement_price_cents` at that instant, and `mark_to_market_cents` recomputed by the fail-mark rule of §3.7. The member's version is advanced.

Reinstatement, performed by a `PlatformAdmin`, returns a `SUSPENDED` member to `ACTIVE`. It requires the member to still be `SUSPENDED` (`ERR_INVALID_STATE` otherwise) and requires `financial_standard_status` to be `PASS` (`ERR_FINANCIAL_STANDARD_NOT_MET` otherwise). Reinstatement re-derives the capital floor and the financial-standard status, sets the member `ACTIVE`, and recomputes the `total_component_cents` of every clearing fund whose `participant_class` matches the member's class, since the member re-enters the sizing population.

### 3.2. Collateral Postings and Deposit Coverage

A `ClearingMember` posts or releases collateral against its pool by supplying an `amount_cents` and, when releasing, a `reason_code`. Each posting appends one immutable transaction to the pool's ledger; the transaction records the `deposit_id` of the pool it belongs to and the `participant_id` of the posting member, drawn from `X-User-ID`. No transaction is ever edited or deleted. A posting whose `amount_cents` is zero is refused with `ERR_INVALID_AMOUNT`; a release that omits its `reason_code` or that would drive the pool's posted balance below zero is refused with `ERR_DEPOSIT_RELEASE_INVALID`.

After each posting the pool's read-only `posted_amount_cents` is recomputed as the sum of every transaction amount against that pool, and its covered status is re-derived in the same pass against the member's outstanding non-`FAILED` settlement obligations. A member whose posted collateral has fallen short of those obligations shows the `DEFICIENT_GRACE` standing, or surfaces `ERR_INSUFFICIENT_DEPOSIT` where a covered standing is required. A shortfall is never resolved silently: the same recomputation runs when the member is admitted, suspended, financially reviewed, or when the member's obligations change through netting.

A `PlatformAdmin` may also drive collateral directly where a realized fund loss must be borne by a member holding a position in a book-entry security. The allocation names the `participant_id` to debit, an `amount_cents`, and a `reason_code`, and it debits that member's deposit pool and re-derives the pool's covered status, advancing the member's version. Where the member being debited is itself the defaulter in an open proceeding, the posting additionally refreshes that proceeding's `defaulter_resources_cents`.

The pool is queryable in three ways: as the set of pools belonging to one member, as a filtered list across all members by `participant_id`, and as a single pool by identifier showing its computed posted balance, its obligations and its covered status. Every posting against a member is visible both through the pool's own append-only ledger and through a member-wide posting view that spans all of that member's pools.

### 3.3. Trade Entry, Lock-In and Comparison

Trade entry begins when a `ClearingMember` submits a trade. The submission records the `counterparty_participant_id`, the `security_id`, the `side`, the `quantity`, the `trade_price_cents`, and the `trade_date`; the instrument clears in the security's settlement `currency`, which defaults to USD when a security is registered. Submitting fixes the trade's settlement date by the standard rolling convention of two calendar days after its `trade_date`, so a trade executed on 2026-09-08 is designated against the settlement date 2026-09-10; that designation, together with the security, is what locates the trade's settlement window, and the window's own cut-offs are what pin the cycle. The `trade_date` is canonicalized to a single ISO 8601 UTC spelling as it is recorded, and the comparison tuple and the settlement-date derivation see that same normalized value, so two spellings of the same instant always compare equal. The trade starts life `OPEN` and `UNMATCHED`, with `affirmation_status` placeholder-valued at `UNCONFIRMED` until the affirmation deadline for its settlement date is resolved.

Submission runs the same comparison the lock-in step runs, so a contra already on the book can match a new submission immediately. If a contra row matching the tuple exists at submission, the new trade's `match_status` is set to `MATCHED` and each matched contra row's `lock_status` is set to `LOCKED_IN` even where that contra was still `OPEN`, with `allegations_received` recomputed and versions advanced on every row the cascade touches. A submission with no contra remains `UNMATCHED` and waits for lock-in. Only a member whose `membership_status` is `ACTIVE` may submit: a member that is `SUSPENDED`, `DEFAULTED` or `EXPELLED` is refused with `ERR_PARTICIPANT_NOT_ACTIVE`, and a member whose `financial_standard_status` is `FAIL` is refused with `ERR_FINANCIAL_STANDARD_NOT_MET`. A submission whose `counterparty_participant_id` equals the submitter's own `participant_id` is a self-trade and is refused with `ERR_SELF_TRADE_FORBIDDEN`.

Locking a trade in is the comparison event, and it carries four gates. The trade must still be `OPEN`, or the attempt fails with `ERR_INVALID_STATE`. A settlement window must exist for the trade's security and settlement date and must itself still be `OPEN`, or the attempt fails with `ERR_WINDOW_NOT_FOUND`. The trade's `trade_date` must fall strictly before that window's `trade_entry_deadline`, compared as ISO 8601 strings, or the attempt fails with `ERR_TRADE_ENTRY_DEADLINE_PASSED`. The submitting member must be `ACTIVE`, or the attempt fails with `ERR_PARTICIPANT_NOT_ACTIVE`.

When lock-in succeeds, `lock_status` becomes `LOCKED_IN` and comparison resolves the `match_status`. A contra is a non-`CANCELLED` submission whose `counterparty_participant_id` is this trade's own `participant_id`, whose own `participant_id` is this trade's `counterparty_participant_id`, whose `security_id` equals this trade's, whose `side` is the opposite of this trade's, and whose `quantity` and `trade_date` match this trade's exactly. If such a contra exists and the counterparty member is `ACTIVE`, the trade becomes `MATCHED`. If such a contra exists but the counterparty member is not `ACTIVE`, the trade becomes `ALLEGED` — the lock-in still succeeds, but the pair is caught in the comparison sweep rather than confirmed. If no contra exists, the trade stays `UNMATCHED`. In every case `allegations_received` is recomputed as the count of non-`CANCELLED` contra rows matching that tuple.

Matching propagates across the pair. When a trade becomes `MATCHED`, every one of those contra rows is also set to `LOCKED_IN` — even a contra that was still `OPEN` — and each contra's `allegations_received` is recomputed in the same step. The trade's version is advanced, as is the version of every row the cascade touches.

### 3.4. Disputes, Reversals and Cancellation

A matched pair can be pulled out of the netting population by either member. A `ClearingMember` disputes a trade only while it is `OPEN`; the trade must also be `MATCHED`, and an attempt to dispute a trade that is not matched is refused with `ERR_NOT_MATCHED`. A successful dispute sets the trade's `lock_status` to `DISPUTED` and its `match_status` to `UNRESOLVED`, recomputes `allegations_received`, and sets `match_status` to `UNRESOLVED` on every non-`CANCELLED` contra row of the tuple, so the whole pair is suspended from settlement together.

Resolution is a `PlatformAdmin` act, and it has exactly one legal entry point. The disputed pair is identified by the two participant identifiers it spans, and the resolution may only be requested against the row belonging to the lower of those two identifiers; a request against the other side of the pair is refused with `ERR_DISPUTE_RESOLUTION_NOT_OWNER`. The trade must be `DISPUTED` (`ERR_INVALID_STATE` otherwise) and its settlement window must exist and still be `OPEN` (`ERR_WINDOW_NOT_FOUND` otherwise). Resolution restores the trade to `LOCKED_IN` and `MATCHED` and applies the same pair to every non-`CANCELLED` contra row of the tuple, recomputing `allegations_received` on every row.

A locked-in trade is reverted by a `PlatformAdmin` while its window is still `OPEN`; an attempt once the window has left `OPEN` is refused with `ERR_WINDOW_ALREADY_NETTED`, a trade that is not `LOCKED_IN` fails with `ERR_INVALID_STATE`, and a trade whose `match_status` is not `MATCHED` cannot be reverted under that rule and is refused with `ERR_NOT_MATCHED`. Reverting returns the trade to `OPEN` and `UNMATCHED` and applies the same to every non-`CANCELLED` contra row, recomputing `allegations_received` across the tuple.

Cancellation has three entry states and two acting roles, and the outcomes differ. While a trade is `OPEN`, a `ClearingMember` may cancel it, with no further gate beyond the `OPEN` requirement; the row becomes `CANCELLED` with `match_status` `UNRESOLVED`, and `allegations_received` is recomputed on every non-`CANCELLED` row of the tuple. While a trade is `LOCKED_IN` or `DISPUTED`, only a `PlatformAdmin` may cancel it, and only while its settlement window is still `OPEN` — otherwise the attempt fails with `ERR_WINDOW_ALREADY_NETTED`, and a trade in neither state fails with `ERR_INVALID_STATE`. Cancelling a `LOCKED_IN` trade reopens every non-`CANCELLED` contra row of the tuple that is not already cancelled to `OPEN` and `UNMATCHED`; cancelling a `DISPUTED` trade instead restores every non-`CANCELLED` contra row of the tuple to `LOCKED_IN` and `MATCHED`. In both cases the cancelled row itself becomes `CANCELLED` with `match_status` `UNRESOLVED`, and `allegations_received` is recomputed on every row of the tuple.

### 3.5. Cycle Timeline, Affirmation and Multilateral Netting

A settlement cycle is opened by a `PlatformAdmin` for one `security_id` and one `settlement_date`, with its `trade_entry_deadline` and `affirmation_deadline`. The `settlement_date` is unique per security and date among windows that are not `CLOSED`. The whole timeline of an `OPEN` window may be revised through an update that accepts `trade_entry_deadline` and `affirmation_deadline`, but a revision that leaves `affirmation_deadline` at or before `trade_entry_deadline` — or that tightens `trade_entry_deadline` once trade entry has closed — is refused with `ERR_WINDOW_DEADLINE_REGRESSION` (HTTP 422). The scoping fields `security_id` and `settlement_date` are immutable on an existing window.

Before the cycle is netted, a `ClearingMember` may affirm its own trades for a window's security and settlement date. Affirmation sets `affirmation_status` to `AFFIRMED` on every `UNCONFIRMED` trade of the acting member on that security and date, and advances the window's version; only a member whose `membership_status` is `ACTIVE` may affirm, and any other standing is refused with `ERR_PARTICIPANT_NOT_ACTIVE`.

A `PlatformAdmin` may either repeatedly refresh the cycle while the window remains `OPEN`, or close trade entry by netting it. Refreshing the cycle leaves the window `OPEN` so that the cycle may be run again — this is the self-loop the window's state machine describes. It requires the window to be `OPEN` (`ERR_INVALID_STATE` otherwise) and its `affirmation_deadline` to be strictly after its `trade_entry_deadline` (`ERR_AFFIRMATION_DEADLINE_ORDER` otherwise), and it must present the client's last-observed `expected_window_version`, with a mismatch rejected as `ERR_STALE_VERSION`. Netting the cycle requires the window to be `OPEN`, the deadline ordering to hold, and the logical clock to read strictly before the window's `affirmation_deadline`; if the clock has reached or passed that deadline, the attempt is refused with `ERR_AFFIRMATION_DEADLINE_PASSED`.

Both the refresh and the netting resolve affirmation for the window's settlement date and then compute net positions. Affirmation resolution sweeps every trade on the window's security and settlement date: a trade still `UNCONFIRMED` is advanced to `AFFIRMED`, a trade already `UNCONFIRMED_BREACH` retains that value, and a trade already `AFFIRMED` is left unchanged.

Multilateral netting then collapses the locked trades of each `ACTIVE` participant into a single position. For a given participant, the included trades are exactly those that are `LOCKED_IN`, on the window's `security_id`, for the window's `settlement_date`, belonging to that participant, and carrying a `match_status` of `MATCHED` or `UNRESOLVED`. Trades that are `ALLEGED` are excluded from the calculation but retained for comparison. The included trades are visited in `trade_date` ascending order with ties broken by `created_at` ascending. Two accumulators are formed: a signed quantity, where a `BUY` contributes its `quantity` positively and a `SELL` contributes it negatively; and a signed gross, where a `BUY` contributes its `quantity` multiplied by its `trade_price_cents` positively and a `SELL` contributes that product negatively. The participant's `net_quantity` is the signed quantity total, and its `cash_delta_cents` is the signed gross total. A `net_quantity` of zero is a flat position, positive is net long (a receive), and negative is net short (a deliver). The `settlement_obligation_cents` is the cash delta when the cash delta is positive and zero otherwise — funding is never required against a net receipt. No division and no rounding occur anywhere in this calculation; every gross is an exact integer product and the sums are taken before anything else. The signed gross left over after offsetting the position's signed quantity against the security's `prev_settlement_price_cents` seeds the position's `mark_to_market_cents` — that is, the signed gross minus the signed quantity multiplied by the prior settlement price — so a fresh position starts with a mark consistent with its own trades and is only later re-marked by the fail rule of §3.7. Running the cycle creates or replaces exactly one net position row per qualifying participant for the window, then recomputes the settlement obligation on every net position of the window, and for each participant whose obligation is positive re-derives its deposit pool standing, which may surface `ERR_INSUFFICIENT_DEPOSIT`. Running the cycle also reopens every clearing fund on the window's security so its sizing cycle can be refreshed, as described in §3.9, and advances the window's version. Netting the cycle additionally sets the window to `NETTED` and advances its version.

The netting convention is the settled convention: opposite-side trades combine into one net quantity and one signed cash leg, rather than the reporting convention that keeps a gross receive quantity and a gross deliver quantity apart. The two conventions coincide on the net quantity but diverge on the obligation whenever a buy exists.

### 3.6. Funding and Delivery versus Payment

After a window has been netted, each participant has settlement obligations to fund. A `ClearingMember` funds one of its net positions — addressed through the `window_id` of the cycle that produced it — by supplying an `amount_cents`, which is added to the position's read-only `funded_amount_cents`. The funded amount saturates at the settlement obligation: a posting that would push `funded_amount_cents` above `settlement_obligation_cents` is refused with `ERR_FUNDING_EXCEEDS_OBLIGATION`, and a funding posting of zero, or a funding against a position whose `settlement_obligation_cents` is not positive, is refused with `ERR_INVALID_AMOUNT`. Only an `ACTIVE` member may fund, with any other standing refused as `ERR_PARTICIPANT_NOT_ACTIVE`. When the funded amount reaches the settlement obligation, the member's deposit pool standing is re-derived in the same step. A position whose obligation has been fully funded but which has not yet been delivered or received holds the `FUNDED` delivery-versus-payment status until settlement resolves it.

The same capability also drives the daily mark-to-market when the caller sets `mark_to_market_only` true. In that mode the call performs only the fail mark recomputation of §3.7 and does not move any funds; it is not gated on the member's standing, so a member that is no longer `ACTIVE` may still re-mark its own failed position, while the `ACTIVE` requirement is enforced on the funding path alone.

An `PlatformAdmin` performs delivery versus payment by settling a `NETTED` window, and the gates are strict. The window must be `NETTED` (`ERR_INVALID_STATE` otherwise). The window must own at least one net position row, or the attempt fails with `ERR_EMPTY_NET_POSITION_SET`. Every net position of the window must have `funded_amount_cents` at or above its `settlement_obligation_cents`, or the attempt fails with `ERR_OBLIGATION_UNDERFUNDED`. And no net position of the window may be `FAILED` for a participant whose `membership_status` is `ACTIVE` at the current logical clock, or the attempt fails with `ERR_WINDOW_HAS_ACTIVE_FAILS`.

When settlement proceeds, each net position's delivery-versus-payment status `dvp_status` is resolved by the sign of its `net_quantity`: a positive net quantity is marked `RECEIVED`, a negative net quantity is marked `DELIVERED`, and a flat position keeps whatever status it already held. The settlement pass also runs the corporate-action servicing pass described in §3.8 for every applied corporate action on the window's security whose `effective_date` falls on or before the window's `settlement_date`, and recomputes the fail mark of §3.7 for any net position that is already `FAILED`. The window then becomes `SETTLED` and its version advances.

Closing a cycle is available from either `NETTED` or `SETTLED`, performed by a `PlatformAdmin`; a window in any other status fails with `ERR_INVALID_STATE`. Closing sets the window `CLOSED` and advances its version, and it is at close that the grace state bites: every participant whose posted collateral is below its obligations at that moment has its deposit pool set to `DEFICIENT_GRACE`.

A window is not only closed by an operator. When no participant at all remains `ACTIVE`, every `OPEN` window closes automatically as a system event — not surfaced as a failure against the call that removed the last `ACTIVE` membership, which still succeeds and reports only its own resource; the condition is the one named `ERR_NOT_ALL_PARTICIPANTS_ACTIVE`. That automatic close also recomputes the fail mark of every net position in the window and advances the window's version. The reaction is invoked when a member is suspended and again when a defaulter is expelled by a served liquidation, and it closes the windows only when no participant at all remains `ACTIVE`.

### 3.7. Fail Management and the Daily Mark-to-Market

A net position fails when a delivery cannot be made. Failures arise from member suspension, which marks the member's non-`FAILED` net positions as `FAILED` as described in §3.1. A failed position records the `security_id` of the instrument that failed to deliver and keeps its `net_quantity` and `cash_delta_cents` from the netting that produced it, so the mark below is formed on the same quantity the position was netted at. `failed_at` is stamped exactly once, when the position enters `FAILED`, and `failed_at_price_cents` is stamped once at that same instant from the security's `prev_settlement_price_cents`.

A failed position carries a daily mark in `mark_to_market_cents`, recomputed by the mark-to-market rule. The included trades for a position are exactly those that are `LOCKED_IN`, on the position's `security_id`, belonging to the position's participant, and carrying a `match_status` of `MATCHED` or `UNRESOLVED`; `ALLEGED` rows are excluded. Those trades are visited in `trade_date` ascending order with ties broken by `created_at` ascending, and a single signed failed quantity is formed, where a `BUY` contributes its `quantity` positively and a `SELL` contributes it negatively. A price move is then taken as the security's current `prev_settlement_price_cents` minus the position's `failed_at_price_cents`. The mark is the signed failed quantity multiplied by that price move, with the single product rounded half up to a whole cent. The order is pinned: the quantity sum is formed first, then multiplied once by the price move, then rounded once — the algorithm is never "mark each trade, then sum". A price fall makes a net-long fail report a negative mark, which is the risk convention the house uses; the reconciliation convention, which marks every fail at zero, is not the rule.

The mark is refreshed by the daily sweep, by a funding call made in `mark_to_market_only` mode, at settlement, and at the close of a cycle, so a fail that persists across days is re-marked against the moving settlement price.

### 3.8. Corporate Actions and Book-Entry Custody Servicing

Book-entry positions are held in custody accounts. A `PlatformAdmin` opens a custody account for a member, supplying the member as the owning participant, an `account_number`, and an `account_type` of `SEGREGATED`, `HOUSE` or `PLEDGED`; the account starts with an empty `positions` array. Each position records the `security_id`, the `settled_quantity` — long positive, short negative — and the `last_corporate_action_applied_id` of the action most recently applied to it. An account's status is `OPEN`, `PLEDGED` or `FROZEN`.

A `PlatformAdmin` announces a corporate action on a security by giving its `action_type` — `SPLIT`, `REVERSE_SPLIT` or `CASH_DIVIDEND` — an `effective_date`, and the action-specific terms: `ratio_numerator` and `ratio_denominator` for a split, ignored for a cash dividend, with the denominator required to be positive; and `cash_rate_cents_per_unit` for a cash dividend, ignored for a split. The action begins `ANNOUNCED`.

Applying an action is gated before it can touch a position. The action must still be `ANNOUNCED`, or the attempt fails with `ERR_INVALID_STATE`. Its `effective_date` must fall on or before the settlement date of the net position rows it would service, or the attempt fails with `ERR_ACTION_NOT_EFFECTIVE`. A `CASH_DIVIDEND` may not be applied while any net position on any window of the security is net short — that is, while any `net_quantity` is below zero — and a `SPLIT` or `REVERSE_SPLIT` may only be applied while every net position on every window of the security is non-negative; either violation is refused with `ERR_SHORT_POSITION_ADJUSTMENT`. When an action's ratio terms are omitted at announcement they take the value 1 for both `ratio_numerator` and `ratio_denominator`, and an omitted `cash_rate_cents_per_unit` takes the value 0, so a split with no ratio announced changes nothing and a dividend with no rate pays nothing.

Servicing is applied to every custody-account position in the security and to every net position whose security belongs to the action and whose window settlement date is on or after the action's `effective_date`. Targets are visited in `created_at` ascending order with ties broken by the owning participant's `legal_name` ascending. The per-share entitlement is formed on the quantity leg first and truncated toward zero before any cash leg exists. For a `SPLIT`, the quantity adjustment is the position's settled quantity multiplied by the `ratio_numerator` and divided by the `ratio_denominator`, truncated toward zero, with no cash adjustment, and the new settled quantity is the old quantity plus that adjustment. For a `REVERSE_SPLIT`, the adjustment is the negative of the settled quantity multiplied by the `ratio_numerator` minus the `ratio_denominator` and divided by the `ratio_numerator`, truncated toward zero, again with no cash adjustment and the same addition to the settled quantity. For a `CASH_DIVIDEND`, there is no quantity adjustment: the settled quantity is unchanged, and the cash adjustment is the already-adjusted settled quantity multiplied by the `cash_rate_cents_per_unit`. For a net position that cash adjustment is carried on the position itself — written into its `cash_delta_cents`, and removed again when the action is reversed — so a dividend paid on a netted position moves that position's signed cash leg in the same way it moves a custody position's settled quantity; the custody-account position records no cash figure of its own. The action's identifier is then recorded as the position's `last_corporate_action_applied_id`, the action's `applied_at` is stamped, and the action becomes `APPLIED`, advancing the action's version.

A serviced action may be reversed while it is `APPLIED`; any other status fails with `ERR_INVALID_STATE`. Reversal restores the pre-application quantity and the prior `last_corporate_action_applied_id` on every affected custody-account position, reverses the servicing on every affected net position and recomputes each affected `cash_delta_cents` by the netting rule of §3.5, and sets the action to `REVERSED`, advancing the action's version.

Servicing is not only an explicit act: as described in §3.6, the settlement pass applies the same servicing for every applied action on the window's security whose effective date has arrived, so custody and net positions are serviced without a separate call when a cycle settles.

### 3.9. Clearing Fund Sizing and Default Management

A `RiskOfficer` stands up a clearing fund for one `security_id` and one `participant_class`; only members of that class are ever sized against the fund. Sizing the fund is an explicit recompute, and it is required to present the client's last-observed `expected_fund_version`; a mismatch is rejected as `ERR_STALE_VERSION`, and that version rejection is decided before the fund's own eligibility gate, so a caller presenting a version it has not observed is told its view is stale rather than that the fund is not recomputable. The fund must be `OPEN`, or the attempt fails with `ERR_INVALID_STATE`, and a fund that has already been recomputed and has seen no intervening new or replaced net position on its security is refused a second recompute with `ERR_FUND_ALREADY_RECOMPUTED`. A fresh net position on the fund's security reopens a recomputed fund, so the next recompute is legitimate and begins a new generation.

A recompute sizes every participant whose `membership_status` is `ACTIVE` and whose `participant_class` equals the fund's class. Each sized participant's component is the open risk on the fund's security, measured over that member's `LOCKED_IN` trades on that security carrying a `match_status` of `MATCHED` or `UNRESOLVED`, with each `BUY` contributing its `quantity` multiplied by its `trade_price_cents` positively and each `SELL` contributing that product negatively, and the net of those products taken as an absolute value. That open risk is multiplied by a volatility multiplier of 15000 basis points when the security's `current_volatility_bps` is strictly above 2500, and by 10000 basis points otherwise. The product is divided by 10000 and rounded half up once, immediately after the multiply and before any clamp.

The result is then clamped in a pinned order: the minimum component of 250,000 cents is applied first, then the maximum component of 50,000,000 cents, so a small open risk is lifted to the floor and a large one is truncated at the cap. Finally a net-capital floor is applied last: a member whose `financial_standard_status` is `FAIL` is floored at its `required_min_net_capital_cents`, and any other member is floored at zero. The component amount is the greater of the clamped value and that floor. The clamps are not commutative with the rounding and are not applied in the other order; rounding before clamping, rounding the multiplier first, and applying the maximum before the minimum all yield different cents and are not this rule.

Each recompute creates one component row per sized participant, in a new generation — generation 1 for the first sizing and one higher for each subsequent sizing, with earlier generations left untouched — and each new row begins `ASSESSED`. The recompute then refreshes the fund's aggregate `total_component_cents` and `fund_balance_cents`, stamps `last_computed_at` at the logical clock, sets the fund `RECOMPUTED` and advances its version. The fund is also re-aggregated whenever its sizing population changes: reinstatement and activation recompute the `total_component_cents` for every fund of the member's class, as noted in §3.1.

A member in default is handled as a proceeding. A `RiskOfficer` declares a `SUSPENDED` member in default by naming the `participant_id` and a `reason_code`, only while the member is `SUSPENDED` (`ERR_INVALID_STATE` otherwise) and only while its `financial_standard_status` is `FAIL` (`ERR_FINANCIAL_STANDARD_NOT_MET` otherwise), which sets the member `DEFAULTED`, sets `is_defaulted` true, opens a `DefaultProceeding` in `DECLARED`, and forces the member's deposit pool to `DEFICIENT_DEFAULT`. A `RiskOfficer` then advances the proceeding from `DECLARED` to `LIQUIDATING` so the auction may be run; advancing a proceeding that has already left `DECLARED` is refused. The auction itself is an accumulation of sealed bids placed by `ClearingMember` firms, each carrying a `bid_price_cents`, a `quantity`, a `placed_at` instant, and the `fund_component_id` to be reserved. A standing high bid reserves its bidder's latest fund component at the lesser of the bid price and the component's current balance, and displacing a high bid releases the previous bidder's reservation.

Liquidating the book is a `RiskOfficer` act and requires the proceeding to be `LIQUIDATING`; otherwise it fails with `ERR_PROCEEDING_NOT_LIQUIDATING`. The house runs a second-price silent auction. Zero non-withdrawn bids yield zero proceeds. A single bid yields that bid's price multiplied by its quantity. With two or more bids, the settlement price is the second-highest distinct bid price and the winning quantity is the quantity of the single high bidder, so the proceeds are that uniform price multiplied by the winning quantity — a lone bidder therefore settles at its own price, and any lower second bidder drives the proceeds below the high bid. Bids are ordered by `bid_price_cents` descending, with ties broken by `placed_at` ascending and then by the bidder's `legal_name` ascending. The defaulter's resources are its posted deposit balance, saturating at the total of its settlement obligations across all of its net positions irrespective of delivery-versus-payment status, so a failed row still contributes resources to the defaulter's estate. The loss the fund must absorb is those resources minus the liquidation proceeds, floored at zero. The released fund components are not netted against that loss as a separate term. When the liquidation completes, the defaulter's own fund components are released, the proceeding becomes `LIQUIDATED`, every involved fund's `fund_balance_cents` and `total_component_cents` are recomputed, and the member is expelled. Every settlement window still holding a net position of the defaulter is transitioned according to its own rules.

Allocating the residual loss is the final step, and it is available only against a proceeding that is `LIQUIDATED` and that carries a positive `deficit_amount_cents`; a non-positive deficit is refused with `ERR_NO_ALLOCATABLE_DEFICIT`, and a `DEFAULTED` member precondition that does not hold fails with `ERR_INVALID_STATE`. The surviving members are every participant other than the defaulter that holds a non-`RELEASED` fund component on any clearing fund whose `participant_class` equals the defaulter's class, and a participant with no such component is excluded entirely. Those members are ordered by the `created_at` of their latest component ascending, then by `legal_name` ascending. Their current component balances are summed, read after the defaulter's own components were released; if that sum is zero or less the allocation cannot be covered and is refused with `ERR_CLEARING_FUND_DEFICIT`.

Each surviving member is debited in proportion to its current component balance: the deficit multiplied by that member's current balance and divided by the summed balance, rounded half up once per member and applied as a negative debit. The per-member rounding is deliberately not followed by a clamp, so the debited total may drift from the deficit by up to one cent per member. That drift is repaired immediately afterwards by a remainder step: the compensating amount is the exact negative of the deficit minus the signed total already debited, and it is posted on the single component holding the largest post-debit balance, with ties broken by the owning participant's `legal_name` ascending and then by the component's `created_at` ascending. After the repair the sum of the written allocation amounts equals the negative of the deficit exactly, and the sum of the component deltas equals the negative of the deficit exactly. Each debited component becomes `ASSESSED`, or `RELEASED` when its balance reaches zero; the funds' `fund_balance_cents`, `total_component_cents` and `experiences_deficit` are recomputed; the proceeding's `allocated_total_cents` is set equal to its `deficit_amount_cents` and the proceeding becomes `ALLOCATED`; and the defaulter is expelled. The allocation remembers, on each written row, the proceeding it belongs to through `default_proceeding_id`, the component it debited through `fund_component_id`, and the `posted_at` instant of the returned remainder. The completed proceeding reports the net cash its auction raised in `liquidation_proceeds_cents`, the residual loss the fund absorbed in `deficit_amount_cents`, the resources the defaulter's estate contributed in `defaulter_resources_cents`, and the total debited across survivors in `allocated_total_cents`.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource, or that add a distinct new resource to a collection, return `201 Created`. Operations that modify an existing resource — including state transitions, recomputations, and additions to an internal ledger — return `200 OK`. Every request is subject to the authentication and authorization rules of §2.1 and to the validation precedence of §2.12.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/clearing/_clock/set_current_utc` | Advance the logical clock used by every deadline and effective-date evaluation | PlatformAdmin |
| POST | `/clearing/participants` | Register a new clearing member | PlatformAdmin |
| GET | `/clearing/participants` | Register a new clearing member | PlatformAdmin, RiskOfficer, ClearingMember |
| GET | `/clearing/participants/{id}` | Read one participant | PlatformAdmin, RiskOfficer, ClearingMember |
| POST | `/clearing/participants/{id}/financial-review` | Re-run the financial-standard review after a capital change | RiskOfficer |
| PUT | `/clearing/participants/{id}` | None | PlatformAdmin |
| POST | `/clearing/participants/{id}/activate` | Admit a PENDING member to clearing membership | PlatformAdmin |
| POST | `/clearing/participants/{id}/suspend` | Suspend an ACTIVE member and cascade its trades, net positions and funds | PlatformAdmin |
| POST | `/clearing/participants/{id}/reinstate` | Return a SUSPENDED member to ACTIVE after a passing review | PlatformAdmin |
| GET | `/clearing/participants/{id}/deposits` | List the deposit pools belonging to a member | PlatformAdmin, RiskOfficer, ClearingMember |
| POST | `/clearing/deposits/{id}/postings` | Post or release collateral on a deposit pool | ClearingMember |
| GET | `/clearing/deposits` | List the deposit pools belonging to a member | PlatformAdmin, RiskOfficer, ClearingMember |
| GET | `/clearing/deposits/{id}` | Read one deposit pool | PlatformAdmin, RiskOfficer, ClearingMember |
| GET | `/clearing/participants/{id}/deposit-postings` | List every posting recorded against a member | PlatformAdmin, RiskOfficer, ClearingMember |
| POST | `/clearing/securities/{id}/allocate-fund-cost` | Allocate a realized fund loss onto a member's deposit pool | PlatformAdmin |
| GET | `/clearing/deposits/{id}/postings` | Post or release collateral on a deposit pool | PlatformAdmin, RiskOfficer, ClearingMember |
| POST | `/clearing/securities` | Register a book-entry security eligible for clearing | PlatformAdmin |
| GET | `/clearing/securities` | Register a book-entry security eligible for clearing | PlatformAdmin, RiskOfficer, ClearingMember |
| GET | `/clearing/securities/{id}` | Read one security | PlatformAdmin, RiskOfficer, ClearingMember |
| PUT | `/clearing/securities/{id}` | None | PlatformAdmin |
| POST | `/clearing/participants/{id}/custody-accounts` | Open a book-entry custody account for a member | PlatformAdmin |
| GET | `/clearing/participants/{id}/custody-accounts` | Open a book-entry custody account for a member | PlatformAdmin, RiskOfficer, ClearingMember |
| POST | `/clearing/settlement-windows` | Open a settlement cycle for a security and settlement date | PlatformAdmin |
| PUT | `/clearing/settlement-windows/{id}` | None | PlatformAdmin |
| GET | `/clearing/settlement-windows` | Open a settlement cycle for a security and settlement date | PlatformAdmin, RiskOfficer, ClearingMember |
| GET | `/clearing/settlement-windows/{id}` | Read one settlement window | PlatformAdmin, RiskOfficer, ClearingMember |
| POST | `/clearing/settlement-windows/{id}/net` | Close trade entry, resolve affirmation and compute multilateral net positions | PlatformAdmin |
| POST | `/clearing/settlement-windows/{id}/run-cycle` | Refresh the net positions of an OPEN cycle | PlatformAdmin |
| POST | `/clearing/settlement-windows/{id}/settle` | Perform delivery versus payment and run the corporate-action servicing pass | PlatformAdmin |
| POST | `/clearing/settlement-windows/{id}/close-cycle` | Close a settlement cycle and place under-funded members in grace | PlatformAdmin |
| POST | `/clearing/settlement-windows/{id}/affirm` | Member self-service affirmation of its trades before the deadline | ClearingMember |
| POST | `/clearing/trade-submissions` | Submit a trade for clearing | ClearingMember |
| GET | `/clearing/trade-submissions` | Submit a trade for clearing | PlatformAdmin, RiskOfficer, ClearingMember |
| GET | `/clearing/trade-submissions/{id}` | Read one trade submission | PlatformAdmin, RiskOfficer, ClearingMember |
| POST | `/clearing/trade-submissions/{id}/lock-in` | Lock a trade in and match it against its contra | ClearingMember |
| POST | `/clearing/trade-submissions/{id}/dispute` | Dispute a matched trade and suspend the pair from netting | ClearingMember |
| POST | `/clearing/trade-submissions/{id}/resolve-dispute` | Resolve a disputed pair from its single legal entry point | PlatformAdmin |
| POST | `/clearing/trade-submissions/{id}/unmatch` | Revert a locked-in trade to open while its cycle is open | PlatformAdmin |
| POST | `/clearing/trade-submissions/{id}/cancel` | Cancel a trade before its cycle is netted | ClearingMember, PlatformAdmin |
| GET | `/clearing/net-positions` | List net positions with filtering and pagination | PlatformAdmin, RiskOfficer, ClearingMember |
| GET | `/clearing/net-positions/{id}` | Read one net position | PlatformAdmin, RiskOfficer, ClearingMember |
| GET | `/clearing/participants/{id}/net-positions` | List the settlement obligations of one member | PlatformAdmin, RiskOfficer, ClearingMember |
| POST | `/clearing/net-positions/{id}/fund` | Fund a settlement obligation, or recompute the fail mark only | ClearingMember |
| POST | `/clearing/corporate-actions` | Announce a corporate action on a security | PlatformAdmin |
| GET | `/clearing/corporate-actions` | Announce a corporate action on a security | PlatformAdmin, RiskOfficer, ClearingMember |
| GET | `/clearing/securities/{id}/corporate-actions` | List the corporate actions announced on a security | PlatformAdmin, RiskOfficer, ClearingMember |
| POST | `/clearing/corporate-actions/{id}/apply` | Apply a corporate action and service custody and net positions | PlatformAdmin |
| POST | `/clearing/corporate-actions/{id}/reverse` | Reverse an applied corporate action | PlatformAdmin |
| POST | `/clearing/clearing-funds` | Stand up a clearing fund for a security and member class | RiskOfficer |
| GET | `/clearing/clearing-funds` | Stand up a clearing fund for a security and member class | PlatformAdmin, RiskOfficer, ClearingMember |
| GET | `/clearing/securities/{id}/clearing-funds` | List the clearing funds scoped to a security | PlatformAdmin, RiskOfficer, ClearingMember |
| POST | `/clearing/clearing-funds/{id}/recompute` | Size or re-size a clearing fund in a new generation | RiskOfficer |
| GET | `/clearing/clearing-funds/{id}` | Read one clearing fund | PlatformAdmin, RiskOfficer, ClearingMember |
| GET | `/clearing/clearing-funds/{id}/components` | List the fund component rows of a clearing fund | PlatformAdmin, RiskOfficer, ClearingMember |
| GET | `/clearing/fund-components` | List fund component rows across every fund | PlatformAdmin, RiskOfficer, ClearingMember |
| GET | `/clearing/fund-components/{id}` | Read one fund component row | PlatformAdmin, RiskOfficer, ClearingMember |
| GET | `/clearing/fund-components/{id}/loss-allocations` | List the loss allocations against one fund component | PlatformAdmin, RiskOfficer |
| GET | `/clearing/participants/{id}/fund-components` | List a member's fund component rows | PlatformAdmin, RiskOfficer, ClearingMember |
| POST | `/clearing/default-proceedings` | Declare a suspended member in default | RiskOfficer |
| GET | `/clearing/default-proceedings` | Declare a suspended member in default | PlatformAdmin, RiskOfficer |
| PUT | `/clearing/default-proceedings/{id}` | Advance a default proceeding to the liquidation stage | RiskOfficer |
| GET | `/clearing/participants/{id}/default-proceedings` | List the default proceedings opened against a member | PlatformAdmin, RiskOfficer |
| GET | `/clearing/default-proceedings/{id}` | Advance a default proceeding to the liquidation stage | PlatformAdmin, RiskOfficer |
| POST | `/clearing/default-proceedings/{id}/bids` | Place a sealed bid in the default auction | ClearingMember |
| POST | `/clearing/default-proceedings/{id}/liquidate` | Run the sealed-bid auction and compute the residual deficit | RiskOfficer |
| POST | `/clearing/default-proceedings/{id}/allocate-loss` | Allocate the residual deficit and expel the defaulter | RiskOfficer |
| GET | `/clearing/default-proceedings/{id}/loss-allocations` | List the loss allocations written for a proceeding | PlatformAdmin, RiskOfficer |
| GET | `/clearing/loss-allocations` | List loss allocations across all proceedings | PlatformAdmin, RiskOfficer |


## 5. Error Code Catalogue


| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_RESOURCE_NOT_FOUND` | 404 Not Found |
| `ERR_PARTICIPANT_NOT_FOUND` | 404 Not Found |
| `ERR_SECURITY_NOT_FOUND` | 404 Not Found |
| `ERR_WINDOW_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_PARTICIPANT_NOT_ACTIVE` | 409 Conflict |
| `ERR_FINANCIAL_STANDARD_NOT_MET` | 409 Conflict |
| `ERR_SEGREGATED_CUSTODY_REQUIRED` | 409 Conflict |
| `ERR_SELF_TRADE_FORBIDDEN` | 409 Conflict |
| `ERR_NOT_MATCHED` | 409 Conflict |
| `ERR_SHORT_POSITION_ADJUSTMENT` | 409 Conflict |
| `ERR_TRADE_ENTRY_DEADLINE_PASSED` | 409 Conflict |
| `ERR_AFFIRMATION_DEADLINE_PASSED` | 409 Conflict |
| `ERR_AFFIRMATION_DEADLINE_ORDER` | 422 Unprocessable Entity |
| `ERR_ACTION_NOT_EFFECTIVE` | 409 Conflict |
| `ERR_WINDOW_ALREADY_NETTED` | 409 Conflict |
| `ERR_WINDOW_HAS_ACTIVE_FAILS` | 409 Conflict |
| `ERR_EMPTY_NET_POSITION_SET` | 409 Conflict |
| `ERR_OBLIGATION_UNDERFUNDED` | 409 Conflict |
| `ERR_FUNDING_EXCEEDS_OBLIGATION` | 409 Conflict |
| `ERR_INVALID_AMOUNT` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_DEPOSIT` | 409 Conflict |
| `ERR_DEPOSIT_RELEASE_INVALID` | 409 Conflict |
| `ERR_FUND_ALREADY_RECOMPUTED` | 409 Conflict |
| `ERR_CLEARING_FUND_DEFICIT` | 409 Conflict |
| `ERR_NO_ALLOCATABLE_DEFICIT` | 409 Conflict |
| `ERR_PROCEEDING_NOT_LIQUIDATING` | 409 Conflict |
| `ERR_DISPUTE_RESOLUTION_NOT_OWNER` | 403 Forbidden |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_IMMUTABLE_FIELD` | 422 Unprocessable Entity |
| `ERR_WINDOW_DEADLINE_REGRESSION` | 422 Unprocessable Entity |
| `ERR_INVALID_REQUEST` | 422 Unprocessable Entity |

