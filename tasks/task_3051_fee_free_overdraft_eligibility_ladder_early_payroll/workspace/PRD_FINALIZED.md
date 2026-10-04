# Fee-Free Overdraft Early Payroll API — Product Requirements Document

## 1. Introduction

Community banks and neobanks increasingly compete on how early a member can spend their paycheck and how forgiving the account is when spending briefly outruns the settled balance. This document specifies the API for a fee-free overdraft cushion program operated on behalf of a chartered sponsor bank: members who establish a payroll direct-deposit history earn a spending cushion with no fees of any kind, payroll credits can be made spendable before ACH settlement when the originator's file arrives early, and the program carries the reversal risk when a deposit is returned after the funds were already spent.

Three pressures shape the design. First, eligibility cannot be a one-time decision: deposit regularity, account tenure, and repayment behavior must feed a score that moves members up and down a limit ladder, with decreases delayed behind a member-notice period while increases take effect immediately. Second, early posting of payroll creates genuine balance-sheet exposure — when an early-posted deposit is returned, the unrecoverable shortfall converts automatically into a reclaim advance, and deposit-rerouting abuse must be detectable and lockable. Third, every credit and debit is mirrored as a double-entry pair between the program and the sponsor bank, and periodic reconciliation runs compare the program's ledger against the bank's reported position, blocking further early posting while a discrepancy stands unresolved.

The system serves four operator populations: the member themselves, program operations staff, sponsor-bank operations staff, and a segregated disputes desk. A logical, test-driveable clock governs all time-derived behavior — scoring windows, notice periods, dispute deadlines, aging thresholds — so that every temporal rule in this document is deterministic under evaluation.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contract: authentication, response envelope, pagination, resource conventions, monetary handling, concurrency control, ledger invariants, and the logical clock. Rules here apply to every endpoint unless a more specific statement appears in §3.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the operational capacity in which they act. The system recognizes exactly four role values: `Member`, `ProgramOps`, `SponsorBankOps`, and `DisputesAgent`. A request missing either header, or carrying a role value outside this set, is rejected with `ERR_UNAUTHENTICATED` (401). A request whose role is recognized but not authorized for the targeted endpoint is rejected with `ERR_FORBIDDEN` (403); the full per-endpoint authorization appears in §4.

Role identity is bound to resources as follows. When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member` record; ownership checks on any resource that hangs beneath a member — an account, an advance on an account, a deposit on an account, a dispute filed by the member — compare the resource's owning chain back to that member's `id`, and a mismatch is `ERR_FORBIDDEN`. When `X-User-Role` is `ProgramOps`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. The same opaque treatment applies when `X-User-Role` is `SponsorBankOps` or `DisputesAgent` — these are institution-side operator identities recorded nowhere on domain entities and never matched against resource ownership.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items before returning results and defaults to 0. Unless a list endpoint states a different ordering in §3, results are sorted by `created_at` in ascending order.

Paginated list responses carry four fields in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Primary resources — Member, DepositAccount, DirectDeposit, EarlyPosting, OverdraftAdvance, EligibilityProfile, CushionLimitAdjustment, ReconciliationRun, and Dispute — share a standard set of system-managed fields. Each has an `id`, a server-minted UUID with no type prefix. Each carries `created_at`, an ISO 8601 UTC timestamp with three fractional digits recording creation, and `updated_at`, the same format, refreshed on every mutation. Each also carries `version`, an integer starting at 1 that increments by exactly 1 on every mutation of that resource; `version` is the basis of the optimistic concurrency control described in §2.8.

Two resource kinds are append-only records and deliberately lighter: `DepositReturn`, `RepaymentAllocation`, `AbuseEvent`, and `LedgerEntry` carry `id` and `created_at` only. They have no `updated_at` and no `version`, because they are never mutated after creation.

### 2.5. Nested Resource Retrieval

Paths in this API nest: accounts live under members; deposits, advances, and ledger entries live under accounts; returns, early postings, allocations, and disputes hang beneath deposits or members. Every nested path is validated strictly left to right: the member identifier is resolved first, then the account within that member, then the child resource within that account. A request that references a child under the wrong parent — for example, an account id that exists but belongs to a different member — is reported as the child being not found: the response is `ERR_NOT_FOUND` (404) naming the deepest unresolved resource, never a permission error and never the parent's error.

### 2.6. Money, Precision, and the No-Fee Guarantee

All monetary quantities in this system are integer cents. There are no decimal amounts anywhere: balances, cushion limits, deposit amounts, allocations, holds, and ledger legs are all whole cents. Derived point values in the eligibility score use integer arithmetic, and the single division that requires rounding — the tenure component of the score — rounds half-up to the nearest whole point. Per-line rounding in proportional repayment also rounds half-up, with the rounding remainder reconciled onto the oldest advance, as detailed in §3.6.

The program's founding product promise is the **no-fee guarantee**: no fee, interest charge, or penalty of any kind is ever assessed to the member. The `OverdraftAdvance` entity consequently has no fee field of any sort — it records `principal_cents` and `outstanding_cents` and nothing chargeable. Implementations must not introduce fee, interest, or penalty fields on any entity.

### 2.7. Double-Entry Ledger Discipline

Every movement of value between the program and the sponsor bank is recorded as a `LedgerEntry` against the affected account. Each entry carries an `entry_type` drawn from exactly nine values — `ADVANCE_CREDIT`, `ADVANCE_REPAYMENT_DEBIT`, `EARLY_POSTING_CREDIT`, `EARLY_POSTING_REVERSAL`, `DEPOSIT_SETTLEMENT`, `DEPOSIT_RETURN_DEBIT`, `PROVISIONAL_CREDIT`, `PROVISIONAL_REVERSAL`, and `ADJUSTMENT` — together with two signed legs: `program_leg_cents` (credit positive from the program's perspective) and `bank_leg_cents` (the bank-side mirror). The governing invariant is that the two legs of every entry sum to zero; an entry that violates this is a defect, never a valid state. An entry's `status` begins as `PENDING` and moves to `SETTLED` when the underlying funds movement settles, or to `VOIDED` when the movement is reversed before settlement. The `posted_at` timestamp — the logical-clock instant at which the entry posts — determines which reconciliation window the entry falls into. An adjustment entry created by reconciliation resolution additionally records the `reconciliation_run_id` of the run that created it; on all other entries that field is null.

### 2.8. Optimistic Concurrency Control

Four write operations require the caller to prove it has observed the current state of the parent entity before mutating beneath it. Each takes a non-optional request field carrying the parent's `version` as the client last read it; if that value does not match the parent entity's current `version` at the time the request is processed, the request is rejected with `ERR_STALE_VERSION` (HTTP 412) and nothing is written.

- Creating an advance on an account requires `expected_account_version`, matched against the owning DepositAccount's current `version`. A prior advance draw or repayment legitimately changed the account's headroom, so a client holding a stale view of the account must not create an advance against it.
- Running an eligibility evaluation for a member requires `expected_member_version`, matched against the Member's current `version`, because a batch evaluation supersedes the member's current profile and a stale view would act on a limit the server has already moved.
- Recording an abuse event against a member likewise requires `expected_member_version`; posture recomputation from a stale version could double-apply a posture step.
- Resolving a reconciliation run requires `expected_run_version`, matched against the ReconciliationRun's current `version`; a stale version would post duplicate adjusting entries for a discrepancy already resolved.

Endpoints not listed here take no version field. A successful mutation on any OCC-guarded operation increments the parent's `version` by 1, as does any other mutation of that entity.

### 2.9. Idempotency of Advance Creation

Advance creation accepts a client-supplied `idempotency_key`. A repeated request that reuses a key with an identical payload returns the originally created advance rather than creating a second one — the replay responds with HTTP 200 and the original advance, not 201, since nothing new is created. Reusing the same key with a different payload is rejected with `ERR_IDEMPOTENCY_CONFLICT` (409).

### 2.10. The Logical Clock

All time-derived behavior in this document — tenure windows, scoring windows, notice periods, aging thresholds, dispute deadlines, reconciliation windows — reads from a single server-side logical clock, never from wall-clock time. When the server starts and the clock has never been set, the clock reads 2026-09-01T00:00:00Z. A program-operations capability, mounted under the `/banking` prefix as a test-driving endpoint, advances the logical clock to a supplied `to_iso8601` instant; advancing the clock advances every time-derived computed field and fires every time-based transition described in §3 (decrease adjustments maturing to effective, dispute overdue flags, and similar). The clock never falls back to wall-clock time once set.

### 2.11. Validation Ordering

When a request violates more than one rule, the error returned is the one from the highest-priority check. The evaluation order is fixed: authentication of headers first; then role authorization (including Member ownership); then path resolution left-to-right; then request-body well-formedness; then the idempotency conflict check on advance creation; then the stale-version check; then state-machine from-state legality; then the terminal-lockdown check; then member posture gating; then the abuse lock; then the qualifying-deposit requirement; then temporal-window rules; then overlap-window rules; then uniqueness constraints; then cross-entity referential blocks; and finally the fiscal limit checks (cushion headroom, dispute amount, sufficient funds). A request that fails an earlier check never surfaces a later check's error.

## 3. Business Logic & Workflows

This section describes the domain workflows. Endpoint paths and HTTP methods appear only in §4; here, operations are named by the state changes and business actions they perform.

### 3.1. Enrollment, Accounts, and the Member Posture Ladder

A member's life in the program begins when a `ProgramOps` operator enrolls them by supplying an `external_ref` — a client-side unique reference, one to 128 characters, unique across all members — together with the member's `full_name` and an `enrolled_at` timestamp that anchors tenure; the enrollment timestamp must not lie in the future relative to the logical clock. The new member is created in the `ENROLLED` posture with a `current_limit_cents` of zero, meaning no cushion until the first evaluation. A second enrollment reusing an existing `external_ref` is refused with `ERR_DUPLICATE`. From `enrolled_at`, the system derives `tenure_days`: the whole number of days (fractional days discarded) between enrollment and the current logical clock.

A member's posture moves through five states: `ENROLLED`, `ELIGIBLE`, `RESTRICTED`, `SUSPENDED`, and the terminal `CLOSED`. Posture gates everything the cushion offers: advances may be drawn only while `ELIGIBLE`; early posting is available while `ELIGIBLE` or `RESTRICTED`; `ENROLLED` and `SUSPENDED` members are refused with `ERR_MEMBER_POSTURE` for both operations. Any mutation attempted on a `CLOSED` member is refused with `ERR_ALREADY_TERMINAL`.

Once enrolled, a `SponsorBankOps` operator opens deposit accounts for the member — the account persists its owner as `member_id`, and eligibility profiles, limit adjustments, abuse events, and disputes likewise record the member they belong to through their own `member_id` — naming an `account_type` of `SPENDING` or `SAVINGS` and optionally a `currency` (only `USD` exists today, and `USD` is the default when omitted). Every account also records a `sponsor_bank_code` — up to 32 characters identifying the chartered institution that holds the account, defaulting to `SB-1` — which links the account into reconciliation windows and into the post-early gate described in §3.7. Only `SPENDING` accounts participate in the cushion program: an advance requested against a `SAVINGS` account is rejected with `ERR_LIMIT_EXCEEDED`, regardless of the member's limit.

Each account continuously tracks four balances. The `posted_balance_cents` is the settled ledger balance at the sponsor bank; it may go negative when a reclaim or a cushion-drawing debit outruns settled funds. The `provisional_early_cents` is the sum, across that account's early postings still in `PROVISIONAL` status, of each posting's `posted_amount_cents` minus the portion already spent by debits (§3.6) — money made spendable ahead of settlement and not yet consumed. The `holds_cents` accumulates dispute provisional credits and administrative holds not yet final. The `outstanding_cushion_cents` is the sum of `outstanding_cents` over the account's advances in `OPEN` or `PARTIALLY_REPAID` status. From these, the member-facing spending power and the institution-facing exposure are both derived, as described in §3.6.

### 3.2. Eligibility Scoring and the Limit Ladder

Eligibility is recomputed when a `ProgramOps` operator runs an evaluation for a member, naming an `evaluation_mode` of `BATCH` or `REALTIME` and carrying the `expected_member_version` for optimistic concurrency. Each run records an `EligibilityProfile` for the member. At most one profile per evaluation mode per member holds the status `CURRENT`; creating a batch profile supersedes the prior `CURRENT` batch profile to `SUPERSEDED`. Realtime runs are previews: a realtime profile never supersedes the batch profile, never creates a limit adjustment, and never moves posture — it exists so the member can see what in-flight payroll will do to their standing once it settles.

The score, recorded as `score` on the profile, is an integer from 0 to 1000 assembled from four components. The window for deposit counting is the ninety days ending at the current logical clock, inclusive of the present instant. The **regularity component** counts qualifying deposits in the window — a deposit qualifies when its `originator_type` is `PAYROLL` and its `amount_cents` is at least 10000 (the one-hundred-dollar boundary is inclusive; the qualifying flag is recorded on the deposit as `qualifying`). Batch mode counts only deposits whose status is `SETTLED` with `settled_at` inside the window; realtime mode additionally counts in-flight deposits in `RECEIVED_FILE` or `POSTED_EARLY` status by their `created_at`, so a member with payroll on the wire scores higher in preview than in the authoritative batch run. Six or more qualifying deposits earn 400 points, four or five earn 300, two or three earn 150, and fewer than two earn zero. If any qualifying deposit settled inside the window was subsequently returned — settled first, then `RETURNED` — the bucket is demoted one step: 400 becomes 300, 300 becomes 150, and 150 becomes zero. The result is stored as `regularity_points`.

The **tenure component**, stored as `tenure_points`, grants up to 250 points for a full year of tenure: the member's `tenure_days` capped at 365, divided by 365, multiplied by 250, and rounded half-up to a whole point. The **repayment component**, stored as `repayment_points`, grants 25 points for each consecutive on-time repayment, counting at most ten repayments — a cap of 250 points. The **abuse penalty**, stored as `abuse_penalty`, subtracts 150 points for each abuse event recorded against the member within the trailing ninety days, counting at most three events. The final `score` is the sum of the three positive components minus the abuse penalty, clamped to the range 0 to 1000.

The score feeds the **limit ladder**, which computes `computed_limit_cents` as the smallest of three independent caps. The score cap is 20000 cents at a score of 750 or higher, 10000 at 500 or higher, 5000 at 300 or higher, 2000 at 200 or higher, and zero below 200. The repayment cap is 20000 cents at five or more consecutive on-time repayments, 10000 at three or four, 5000 at one or two, and 2000 at zero. The tenure cap is 20000 cents at 180 tenure days or more, 10000 at 90 or more, 5000 at 30 or more, and 2000 below 30 days. All boundaries are inclusive. The computed limit is the minimum of the three caps — a member strong on deposits but brand-new to the program is held back by tenure, and a tenured member who has never repaid on time is held back by the repayment cap. The profile also records `delta_vs_current_cents`, the signed difference between the computed limit and the member's `current_limit_cents` at evaluation time.

The first batch evaluation is what moves a member out of `ENROLLED`: when the computed `score` reaches at least 200, the member's posture transitions `ENROLLED → ELIGIBLE`, their `current_limit_cents` is set to the profile's `computed_limit_cents`, and a `CushionLimitAdjustment` recording the change is created. A batch evaluation scoring below 200 leaves the member `ENROLLED` with a zero limit; no adjustment row is created when the limit delta is flat.

Re-evaluation while `ELIGIBLE` or `RESTRICTED` re-runs the ladder against current inputs and creates a `CushionLimitAdjustment` whenever the delta is non-zero — with the asymmetric application described in §3.3. Re-evaluation while `SUSPENDED` is permitted as a batch run, but the posture dominates: the computed limit is forced to zero and applied immediately as a decrease created directly `EFFECTIVE`, with no notice period, because suspension has already withdrawn the cushion.

### 3.3. Limit Adjustments: Notice Periods and Member Communication

Every non-flat limit change produced by a batch evaluation is recorded as a `CushionLimitAdjustment` against the member, carrying `old_limit_cents`, `new_limit_cents`, and a `direction` of `INCREASE`, `DECREASE`, or `FLAT` — though no row is created at all when the direction would be `FLAT`.

Increases and decreases are deliberately asymmetric. An `INCREASE` row is created directly in `EFFECTIVE` status: the member's `current_limit_cents` rises to `new_limit_cents` at the moment of creation, and `effective_at` is the creation instant. A `DECREASE` row is created in `PENDING_NOTICE` with `effective_at` set to seven days after creation — a one-week member-notice period during which the old, higher limit continues to govern spending power. A `ProgramOps` operator records that the member has been notified by issuing the notify action, moving the row `PENDING_NOTICE → NOTIFIED` and stamping `notified_at`; notifying a row not in `PENDING_NOTICE` is refused with `ERR_INVALID_STATE`. Once the logical clock reaches `effective_at`, a `NOTIFIED` row matures to `EFFECTIVE` and the member's `current_limit_cents` falls to `new_limit_cents`. A decrease row still awaiting effectiveness is fragile: if a newer evaluation creates another adjustment for the same member, the pending or notified decrease is superseded to `SUPERSEDED` and the member's limit stays where it was — the newest evaluation's adjustment is the one that will govern.

Members and program staff can review a member's ladder history through the limit-adjustments listing, which returns rows oldest first, and can read any single adjustment by id.

### 3.4. Deposits, Early Posting, and Settlement

Inbound ACH credit files are registered by `SponsorBankOps` against a spending account — the deposit, and later any advance or ledger entry touching the account, records its destination as `account_id` — supplying the `originator_id` (the employer payroll identifier), the `originator_type` (`PAYROLL` or `OTHER`), the gross `amount_cents` (strictly positive), the `settlement_date` from the file, and the ACH `trace_id`, which must be unique across all deposits — a duplicate trace is refused with `ERR_DUPLICATE`. Registration always creates the deposit in `RECEIVED_FILE` status; an overlapping registration is refused outright with `ERR_WINDOW_OVERLAP` rather than persisted in any rejected state. Overlap is judged per account and originator: if an in-flight deposit — one in `RECEIVED_FILE` or `POSTED_EARLY` — exists for the same account and `originator_id` whose `settlement_date` lies within three days of the new deposit's settlement date in either direction, the new registration conflicts. A gap of exactly three days is a conflict; four days or more is allowed.

Early posting is the program's signature feature. A `ProgramOps` operator may make a deposit spendable ahead of settlement — transitioning the deposit `RECEIVED_FILE → POSTED_EARLY` — only when all of the following hold: the deposit qualifies (payroll, at least 10000 cents; otherwise `ERR_NOT_QUALIFYING`); the logical clock is still before the deposit's `settlement_date` (posting early on or after the settlement date is a temporal violation, `ERR_TEMPORAL_VIOLATION`); the member's posture is `ELIGIBLE` or `RESTRICTED` (otherwise `ERR_MEMBER_POSTURE`); the member's `deposit_reroute_flag` is not set (otherwise `ERR_ABUSE_LOCK`); and no reconciliation run in `DISCREPANCY` status for the account's sponsor bank has a window containing the current clock (otherwise `ERR_REFERENTIAL_BLOCK` — early posting freezes bank-wide while a ledger discrepancy stands).

When early posting succeeds, an `EarlyPosting` record is created for the deposit in `PROVISIONAL` status — at most one early posting ever exists per deposit — with `posted_amount_cents` equal to the deposit's full `amount_cents` and a `reversal_window_end` computed as the settlement date plus two calendar days; a return arriving before that instant is treated as a reversal-risk return of funds already spent. The account's `provisional_early_cents` rises by the amount: the early-posted funds live in `provisional_early_cents` (via the `PROVISIONAL` early posting), not in `posted_balance_cents`, which is unchanged at post-early time; they materialize into `posted_balance_cents` only at settlement. Funds made available early still honor repayment: the waterfall of §3.6 runs against the account's outstanding advances immediately (the amount so clawed back joins `posted_balance_cents` only at settlement, per below), and an `EARLY_POSTING_CREDIT` ledger entry is written with the program leg positive, the bank leg negative, and status `PENDING`.

Settlement is performed by `SponsorBankOps` on or after the settlement date; settling before the date is `ERR_TEMPORAL_VIOLATION`, and settling a deposit that is not in `RECEIVED_FILE` or `POSTED_EARLY` is `ERR_INVALID_STATE` (or `ERR_ALREADY_TERMINAL` once `RETURNED`). Settlement from `RECEIVED_FILE` credits the full `amount_cents` to `posted_balance_cents`, stamps `settled_at` with the current clock — `settled_at` is null until this moment and drives the batch scoring window thereafter — runs the repayment waterfall against the just-credited funds, reduces the balance by the total allocated to repayment, and writes a `DEPOSIT_SETTLEMENT` ledger entry in `SETTLED` status. Settlement from `POSTED_EARLY` is the quieter path because the funds largely moved already: the early posting cascades `PROVISIONAL → CONFIRMED`, `provisional_early_cents` falls by the amount, the full `amount_cents` minus the portion the waterfall allocated at post-early time materializes into `posted_balance_cents` (the allocated portion was already repaid to advances and is never credited), `settled_at` is stamped, and the existing `EARLY_POSTING_CREDIT` entry moves to `SETTLED`. The waterfall does not run again at settlement — repayment never double-fires on one deposit.

### 3.5. Returns, Reversals, and Reclaim Advances

A return processed by `SponsorBankOps` — naming a `return_code` of `R01_INSUFFICIENT`, `R02_CLOSED`, `R03_NO_ACCOUNT`, `R07_REVOKED`, or `R08_STOPPED` — moves a deposit to the terminal `RETURNED` state, and a `DepositReturn` record is persisted with the deposit's full amount as its `amount_cents` (returns are full-amount only). Returning a deposit already returned is refused with `ERR_ALREADY_TERMINAL`.

The cascade depends on where the deposit stood. A return against a `POSTED_EARLY` deposit is the reversal-risk path: the early posting cascades `PROVISIONAL → REVERSED`, `provisional_early_cents` falls by the amount, and the `EARLY_POSTING_CREDIT` ledger entry is `VOIDED` — voiding that pending credit is the reversal, and no separate `EARLY_POSTING_REVERSAL` entry is written. The exposed amount is the returned amount minus the portion of the provisional money already spent by debits (§3.6): money the member already spent is not clawed back here. The system then computes the recoverable portion — the lesser of the exposed amount and the account's positive settled balance at that instant — and debits exactly that from `posted_balance_cents`; the debit itself never drives the balance below zero. Whatever of the exposed amount remains unrecovered is the `shortfall_cents` on the return record (zero when the balance fully covers the exposure). When the shortfall is greater than zero, the system creates an `OverdraftAdvance` with `origin` `RECLAIM_SHORTFALL` and `principal_cents` equal to the shortfall, in `OPEN` status — the program's exposure converts into a member-owed cushion balance, which raises `outstanding_cushion_cents` and so reduces usable cushion on the next read. A zero shortfall creates no advance. A `DEPOSIT_RETURN_DEBIT` ledger entry with the program leg negative records the event.

A late return against an already `SETTLED` deposit skips the early-posting machinery — there is nothing provisional left — and directly debits the full returned amount from `posted_balance_cents`, which may drive the balance negative. The shortfall is computed the same way against the balance before the debit, and a `RECLAIM_SHORTFALL` advance is created when positive; a `DEPOSIT_RETURN_DEBIT` entry records the movement. One further consequence matters for scoring: a deposit settled and then returned no longer counts as a qualifying settled deposit in future batch evaluations — it becomes the demotion input for the regularity bucket described in §3.2.

### 3.6. Advances, Debits, and the Repayment Waterfall

A member draws the cushion explicitly by requesting an advance on a spending account, supplying `amount_cents`, an `idempotency_key`, and the `expected_account_version` for concurrency. Drawing requires the member's posture to be `ELIGIBLE` (otherwise `ERR_MEMBER_POSTURE`) and the `deposit_reroute_flag` to be clear (otherwise `ERR_ABUSE_LOCK`). The amount must not exceed the account's `usable_cushion_cents` at request time; an over-limit request, an advance against a `SAVINGS` account, or any advance when the member's limit is zero is refused with `ERR_LIMIT_EXCEEDED`. A successful draw creates an `OverdraftAdvance` with `origin` `MEMBER_INITIATED`, `principal_cents` equal to the amount, and status `OPEN`; the account's `outstanding_cushion_cents` rises by the amount, the `posted_balance_cents` is credited with the amount (cushion funds land as spendable money), and an `ADVANCE_CREDIT` ledger entry records the movement. The account's `version` increments.

Members also draw the cushion implicitly by spending. A debit request names `amount_cents` and a `merchant_ref` and is checked against the account's `available_optimistic_cents` — spending may draw on settled funds, provisional early money, and usable cushion together. A debit beyond that ceiling is refused with `ERR_INSUFFICIENT_FUNDS`. A successful debit spends provisional early money first — the account's `PROVISIONAL` early postings, oldest first; each posting records how much of it has been spent while its `posted_amount_cents` continues to record the full early-posted amount, and a posting's contribution to `provisional_early_cents` shrinks accordingly — then draws the remainder from `posted_balance_cents`, which may take the balance negative. Only the portion of the debit exceeding both the provisional early money and the settled balance converts into an advance: an `OverdraftAdvance` with `origin` `MEMBER_INITIATED` is created automatically for exactly that excess, fee-free, with `outstanding_cushion_cents` rising accordingly and a ledger entry recording the movement.

The account's two read models of spendable funds are computed in a pinned order to break the cushion–outstanding cycle. First, `usable_cushion_cents` is derived: zero whenever the member's posture is anything but `ELIGIBLE` or the `deposit_reroute_flag` is set; otherwise the member's `current_limit_cents` reduced by `outstanding_cushion_cents`, floored at zero. Then the optimistic figure, `available_optimistic_cents`, is the settled balance plus `provisional_early_cents`, minus `holds_cents`, plus the usable cushion — this is the member-facing spending power against which debits are checked. The conservative figure, `available_conservative_cents`, is simply the settled balance minus holds — provisional money and cushion are excluded entirely, and this is the figure reclaim processing and sponsor-bank reporting rely on. Because repayment mutates outstanding while depending on funds made available, a single request computes usable cushion from the pre-mutation outstanding snapshot, applies its mutations, then recomputes for the response.

Repayment is automatic and runs the moment funds become available — at early posting and at settlement from `RECEIVED_FILE`. When the deposit is qualifying, the waterfall walks the account's `OPEN` and `PARTIALLY_REPAID` advances oldest first by `created_at`, allocating to each the lesser of its `outstanding_cents` and the remaining deposit funds, recording each allocation as a `RepaymentAllocation` with `allocation_mode` `WATERFALL` — every allocation row carries the `advance_id` it repays and the `deposit_id` that funded it — until the deposit is exhausted. When the deposit is not qualifying, repayment is proportional: the pool is the lesser of the deposit amount and the total outstanding across open advances; each advance's share is the pool multiplied by its fraction of the total outstanding, rounded half-up per line; the rounding remainder — the pool minus the sum of the rounded shares — is added onto the oldest advance; and shares of zero produce no allocation row, recorded with `allocation_mode` `PRO_RATA`. The rounding order is pinned: each line is rounded first, then the remainder reconciles against the oldest advance — never sum-then-round. Every allocation, of either mode, also posts an `ADVANCE_REPAYMENT_DEBIT` ledger entry with a negative program leg and a positive bank leg in `SETTLED` status, so ledger parity holds across repayment activity. Each allocation reduces both the advance's `outstanding_cents` and the account's `outstanding_cushion_cents`.

Advance states track repayment progress. An allocation smaller than the outstanding moves the advance `OPEN → PARTIALLY_REPAID`; further partial allocations keep it `PARTIALLY_REPAID`. An allocation that exactly covers the outstanding moves the advance to `REPAID`, zeroes `outstanding_cents`, and stamps `repaid_at`. Symmetrically, each deposit tracks its own `repaid_cents` — the running total of allocation amounts that deposit has funded. Repayment timeliness is judged at that instant: an advance repaid within 35 days of its creation is on time (`on_time` true), which increments the member's `consecutive_on_time_repayments`; a repayment later than 35 days resets that counter to zero. The same counter resets to zero on any write-off.

An advance aged sixty days or more may be written off by `ProgramOps`, who supply a `reason`; writing off before the advance is sixty days old is `ERR_TEMPORAL_VIOLATION`, and writing off an advance already `REPAID` or `WRITTEN_OFF` is `ERR_ALREADY_TERMINAL`. Write-off moves the advance to `WRITTEN_OFF`, recognizes the outstanding as program loss by removing it from `outstanding_cushion_cents`, and resets the member's `consecutive_on_time_repayments` to zero. Members and program staff can read any advance by id, list an account's advances with an optional `status` filter, and list the repayment allocations recorded against an advance or funded by a deposit.

### 3.7. Sponsor-Bank Reconciliation

The chartered institution and the program keep separate books, and `SponsorBankOps` periodically opens a reconciliation run over a half-open window: a `sponsor_bank_code`, a `period_start` (inclusive) and `period_end` (exclusive), and the `bank_reported_net_cents` — the net position the bank reports for that window, bank-signed with credits positive from the bank's perspective, which may be negative. Two runs for the same sponsor bank may not have overlapping windows while either is non-terminal (`OPEN` or `DISCREPANCY`); adjacency — one run's `period_end` equal to another's `period_start` — is allowed, and an overlapping request is refused with `ERR_WINDOW_OVERLAP`.

At creation, the run computes the program side from the ledger. The authoritative computation, `SETTLED_ONLY`, sums `program_leg_cents` over `LedgerEntry` rows for accounts of that sponsor bank whose `posted_at` falls inside the window and whose status is `SETTLED`; the result is recorded as `program_net_cents`. The same rows' bank legs, negated into the bank's perspective, give `bank_net_cents`. A forward-looking diagnostic variant additionally includes `PENDING` rows, so an early-posted payroll not yet settled shows up and shifts the net for identical entry data — this variant informs operators but never classifies a run. The `discrepancy_cents` is the program net plus the bank-reported net. A discrepancy of exactly zero moves the run `OPEN → BALANCED` immediately and automatically; anything non-zero moves it `OPEN → DISCREPANCY`, which freezes early posting for every account of that sponsor bank whose window contains the current clock until resolution.

Resolution is a `ProgramOps` action carrying `expected_run_version` for concurrency and a `resolution_note`, permitted only while the run is in `DISCREPANCY` — resolving a `BALANCED` or already-`RESOLVED` run is `ERR_INVALID_STATE`. Resolution posts `ADJUSTMENT` ledger entries against the oldest account (by `created_at`, earliest first) that has entries in the window: the program leg is the negation of the discrepancy and the bank leg is the discrepancy itself, so that after resolution the sum of all legs across the run's entries is zero. The run moves to `RESOLVED` and its `version` increments. Adjusting entries are visible through the run's ledger-entry listing, identified by their `reconciliation_run_id`; runs themselves can be listed with optional `status` and `sponsor_bank_code` filters or read individually.

### 3.8. Abuse Events and the Rehabilitation Path

Program staff flag suspected abuse by recording an `AbuseEvent` against a member, naming an `event_type` of `DEPOSIT_REROUTE` (payroll rerouted away after the cushion was used), `CUSHION_CYCLING`, or `FIRST_PARTY_FRAUD`, with an optional `evidence_note` of up to 500 characters, and carrying `expected_member_version`. The member's `abuse_event_count` — the all-time total — increments, and `abuse_events_90d`, the count of events within the trailing ninety days, is recomputed; both are readable on the member record.

Posture responds to the trailing count. The first abuse event recorded while the member is `ELIGIBLE` — bringing the ninety-day count to exactly one — moves the member `ELIGIBLE → RESTRICTED`, resets `restricted_consecutive_repayments` to zero, and, when the event type is `DEPOSIT_REROUTE`, sets the `deposit_reroute_flag`. While that flag is set, advances and early posting are refused with `ERR_ABUSE_LOCK` regardless of posture. A further abuse event recorded while `RESTRICTED` escalates the member to `SUSPENDED` and sets the `deposit_reroute_flag`. Suspension withdraws the cushion entirely, as described in §3.2.

Restriction is a rehabilitation path, not a dead end. While `RESTRICTED`, each on-time advance repayment increments `restricted_consecutive_repayments`; when that counter reaches three, the member is automatically restored `RESTRICTED → ELIGIBLE` and the `deposit_reroute_flag` clears — the only way that flag ever clears. Abuse events are listable per member for program staff.

Closure is the terminal act. A `ProgramOps` operator may close a member only from `SUSPENDED`; the attempt from any other posture is `ERR_INVALID_STATE`, and acting on an already `CLOSED` member is `ERR_ALREADY_TERMINAL`. Closure moves the member `SUSPENDED → CLOSED`, transitions every `OPEN` or `PARTIALLY_REPAID` advance to `WRITTEN_OFF`, and resets `consecutive_on_time_repayments` to zero.

### 3.9. Disputes, Provisional Credit, and Resolution Timelines

A member who believes an early-posting reversal or a deposit return was mishandled files a dispute, supplying the `deposit_id` of the disputed deposit, a `dispute_type` of `EARLY_POSTING_REVERSAL` or `DEPOSIT_RETURN_CLAIM`, the disputed `amount_cents`, and a free-text `statement` of up to 1000 characters. The amount must be positive and must not exceed the disputed deposit's `amount_cents`, or the filing is refused with `ERR_DISPUTE_AMOUNT_EXCEEDS`. A dispute referencing a deposit the filing member does not own is refused with `ERR_REFERENTIAL_BLOCK`. Filing creates the dispute with `case_status` `FILED` and `provisional_status` `NONE`, and computes two deadlines from the filing instant: `provisional_due_at`, ten business days out (calendar days are advanced one at a time, skipping Saturdays and Sundays; no holiday calendar is observed), and `resolution_due_at`, forty-five calendar days out. The computed flag `provisional_overdue` reads true whenever the clock has passed `provisional_due_at` while `provisional_status` is still `NONE`.

A `DisputesAgent` issues provisional credit while the case is `FILED` or `UNDER_REVIEW` and `provisional_status` is `NONE`, provided the linked deposit is in `POSTED_EARLY` or `RETURNED` status — provisional credit exists only against early-posted or returned funds — and provided the clock has not passed `provisional_due_at`; issuance after the deadline is rejected outright with `ERR_TEMPORAL_VIOLATION` rather than issued late, while issuance exactly at the deadline is allowed. Issuance moves `provisional_status` to `PROVISIONAL_ISSUED`, moves a `FILED` case to `UNDER_REVIEW`, adds the disputed amount to the account's `holds_cents`, and writes a `PROVISIONAL_CREDIT` ledger entry.

Resolution, also by a `DisputesAgent` and carrying an `outcome` of `MEMBER` or `BANK` plus a `resolution_note`, must occur no later than `resolution_due_at`; acting on a dispute already in `RESOLVED_MEMBER` or `RESOLVED_BANK` is `ERR_ALREADY_TERMINAL`. Resolving for the member moves `case_status` to `RESOLVED_MEMBER`: when provisional credit was issued, `provisional_status` becomes `PROVISIONAL_MADE_FINAL`, the hold is released from `holds_cents`, and the amount is credited to `posted_balance_cents`; when no provisional credit existed, the amount is credited directly to `posted_balance_cents` with a `PROVISIONAL_CREDIT` ledger entry in `SETTLED` status. Resolving for the bank moves `case_status` to `RESOLVED_BANK` and, when provisional credit was issued, reclaims it: `provisional_status` becomes `PROVISIONAL_RECLAIMED`, the hold is released from `holds_cents`, and a `PROVISIONAL_REVERSAL` ledger entry records the clawback. Either resolution path, when taken on a still-`FILED` case, also passes the case through `UNDER_REVIEW` as it resolves. Disputes are readable by id, listable per member with an optional `case_status` filter, and listable per deposit.

## 4. Endpoint Definitions

All endpoints are mounted under the `/banking` prefix. Endpoints that create a new resource respond with 201 and the created resource; endpoints that modify an existing resource or perform an action respond with 200 and the updated resource. The authorization column names the roles permitted to call each endpoint; header requirements, ownership semantics, and error behavior are defined in §2.1.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /banking/members | Enroll a member. | ProgramOps |
| GET | /banking/members | List members with optional posture filter. | ProgramOps |
| GET | /banking/members/{id} | Read one member including computed posture fields. | Member, ProgramOps |
| POST | /banking/members/{id}/eligibility-evaluations | Run eligibility scoring (BATCH authoritative / REALTIME preview). | ProgramOps |
| GET | /banking/members/{id}/eligibility-profiles | List eligibility profiles for a member, newest first. | Member, ProgramOps |
| POST | /banking/members/{id}/abuse-events | Record an abuse event; recomputes posture cascade. | ProgramOps |
| GET | /banking/members/{id}/abuse-events | List abuse events for a member. | ProgramOps |
| POST | /banking/members/{id}/accounts | Open a deposit account for a member. | SponsorBankOps |
| GET | /banking/members/{id}/accounts | List a member's accounts. | Member, ProgramOps, SponsorBankOps |
| GET | /banking/accounts/{id} | Read an account including both available-balance variants. | Member, ProgramOps, SponsorBankOps |
| POST | /banking/accounts/{id}/advances | Draw a no-fee cushion advance (OCC on account version). | Member |
| POST | /banking/accounts/{id}/debits | Spend funds; may auto-create a cushion advance for the excess. | Member |
| GET | /banking/accounts/{id}/advances | List advances for an account. | Member, ProgramOps |
| GET | /banking/accounts/{id}/ledger-entries | List ledger entries for an account. | Member, ProgramOps, SponsorBankOps |
| GET | /banking/accounts/{id}/deposits | List deposits for an account. | Member, ProgramOps, SponsorBankOps |
| GET | /banking/advances/{id} | Read one advance. | Member, ProgramOps |
| POST | /banking/advances/{id}/write-off | Write off an advance aged 60 days or more. | ProgramOps |
| GET | /banking/advances/{id}/repayment-allocations | List allocations against an advance. | Member, ProgramOps |
| POST | /banking/accounts/{id}/deposits | Register an inbound ACH deposit file. | SponsorBankOps |
| GET | /banking/deposits/{id} | Read one deposit. | Member, ProgramOps, SponsorBankOps |
| POST | /banking/deposits/{id}/post-early | Make payroll funds available ahead of settlement. | ProgramOps |
| POST | /banking/deposits/{id}/settle | Settle a deposit on or after its settlement date. | SponsorBankOps |
| POST | /banking/deposits/{id}/return | Process an ACH return / reclaim. | SponsorBankOps |
| GET | /banking/deposits/{id}/returns | List returns for a deposit (0 or 1). | ProgramOps, SponsorBankOps |
| GET | /banking/deposits/{id}/early-postings | List early postings for a deposit (0 or 1). | ProgramOps |
| GET | /banking/deposits/{id}/repayment-allocations | List allocations funded by a deposit. | ProgramOps |
| GET | /banking/deposits/{id}/disputes | List disputes filed against a deposit. | Member, ProgramOps, DisputesAgent |
| POST | /banking/members/{id}/close | Close a SUSPENDED member; writes off all non-terminal advances. | ProgramOps |
| GET | /banking/members/{id}/limit-adjustments | List ladder adjustments for a member, oldest first. | Member, ProgramOps |
| GET | /banking/limit-adjustments/{id} | Read one adjustment. | Member, ProgramOps |
| POST | /banking/limit-adjustments/{id}/notify | Record member notification for a pending decrease. | ProgramOps |
| POST | /banking/reconciliation-runs | Create a sponsor-bank reconciliation run over a half-open window. | SponsorBankOps |
| GET | /banking/reconciliation-runs | List reconciliation runs. | ProgramOps, SponsorBankOps |
| GET | /banking/reconciliation-runs/{id} | Read one run. | ProgramOps, SponsorBankOps |
| POST | /banking/reconciliation-runs/{id}/resolve | Resolve a DISCREPANCY run by posting adjusting entries (OCC on run version). | ProgramOps |
| GET | /banking/reconciliation-runs/{id}/ledger-entries | List ledger entries attached to a run. | ProgramOps, SponsorBankOps |
| POST | /banking/disputes | File a dispute on an early-posted or returned deposit. | Member |
| GET | /banking/disputes/{id} | Read one dispute. | Member, ProgramOps, DisputesAgent |
| GET | /banking/members/{id}/disputes | List a member's disputes. | Member, ProgramOps, DisputesAgent |
| POST | /banking/disputes/{id}/issue-provisional-credit | Issue provisional credit within the 10-business-day timeline. | DisputesAgent |
| POST | /banking/disputes/{id}/resolve | Resolve a dispute for member or bank. | DisputesAgent |
| POST | /banking/_clock/set_current_utc | Test-driving endpoint: set the logical clock. | ProgramOps |

## 5. Error Code Catalogue

The table below enumerates every error identifier the API can return and its HTTP status. The conditions that trigger each error are defined in the narratives of §2 and §3.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_IDEMPOTENCY_CONFLICT | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_INVALID_STATE | 409 |
| ERR_ALREADY_TERMINAL | 409 |
| ERR_MEMBER_POSTURE | 409 |
| ERR_ABUSE_LOCK | 422 |
| ERR_TEMPORAL_VIOLATION | 422 |
| ERR_WINDOW_OVERLAP | 409 |
| ERR_DUPLICATE | 409 |
| ERR_REFERENTIAL_BLOCK | 422 |
| ERR_LIMIT_EXCEEDED | 422 |
| ERR_DISPUTE_AMOUNT_EXCEEDS | 422 |
| ERR_INSUFFICIENT_FUNDS | 422 |
| ERR_NOT_QUALIFYING | 422 |
