# Tax Return Accuracy Guarantee & Audit Representation Program API — Product Requirements Document

## 1. Introduction

Tax preparation firms live and die on trust: a client who receives a notice from a taxing authority after filing wants to know two things — whether the preparer's work is covered, and who will sit across the table from the auditor. This document specifies the API for a **Tax Return Accuracy Guarantee & Audit Representation Program**, a system that manages the full arc from return preparation through protection-product sale, authority-notice intake, claim scoping, enrolled-agent representation, and financial settlement, all under office-level quality oversight.

The program must answer several hard bookkeeping questions correctly and reproducibly. What fee was quoted for a return, and what fee was actually locked at filing when the assigned preparer's credential tier may have changed in between? When a taxing authority assesses additional tax, penalty, and interest, which of those components does the protection product reimburse — and does the answer change depending on whether the root cause was preparer error or client-supplied data error? How much money should each office's program escrow have paid out, and how much should it be accruing against historical resolutions? And when an office's defect rate climbs, how does the system restrict that office's ability to sell new protection and upgrade preparers until quality recovers?

The API is mounted under `/tax`. It is designed for a segregation-of-duties operating model in which office staff prepare and file returns, case managers run the claims desk, enrolled agents represent clients before taxing authorities, and a corporate program administrator provisions offices, agents, and escrow funding. The store starts empty on every boot — no seeding; all entities are constructed through the API surface. A test-driving logical clock underpins all time-dependent behavior — interest accrual, power-of-attorney expiry, remediation deadlines — so that outcomes are deterministic and auditable.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two identity headers: `X-User-ID` and `X-User-Role`. A request missing either header, or presenting an `X-User-Role` value that is not one of the declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted for the endpoint — or that fails an entity-backed ownership check — is rejected with `ERR_FORBIDDEN` (HTTP 403). These authentication and authorization checks run before any existence, state, or business validation.

The declared roles are exactly: `ProgramAdmin`, `OfficeManager`, `CaseManager`, `Client`, `Preparer`, and `EnrolledAgent`.

Three roles are entity-backed, meaning the value of `X-User-ID` is the `id` of a persisted resource and ownership checks compare resource foreign keys against it. When `X-User-Role` is `Client`, `X-User-ID` is the `id` of the acting `Client`; a client may respond to an information request only on a claim whose owning client's `id` equals `X-User-ID`. When `X-User-Role` is `Preparer`, `X-User-ID` is the `id` of the acting `Preparer`; completing a remediation action requires that the remediation's `preparer_id` equal `X-User-ID`. When `X-User-Role` is `EnrolledAgent`, `X-User-ID` is the `id` of the acting `EnrolledAgent`; abating a notice requires that the acting agent hold the `ACTIVE` representation assignment on the claim linked to that notice.

The remaining roles are opaque. When `X-User-Role` is `ProgramAdmin`, `OfficeManager`, or `CaseManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, a case manager's `X-User-ID` is captured into a claim's `scoped_by_user_id` when that manager scopes the claim — but it is never compared to any entity's `id` for ownership purposes.

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

Endpoints that return lists of resources accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips that many items from the front of the result set and defaults to 0. A non-integer, out-of-range `limit`, or a negative `offset` is rejected with `ERR_VALIDATION`.

Unless otherwise specified, all list endpoints return resources sorted by `created_at` in ascending order, with ties broken by ascending `id`. List responses include `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties

Every resource in this program is a top-level entity and carries the standard set of system-managed fields:

- `id` — a server-minted UUID, with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, set at creation.
- `updated_at` — an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation.
- `version` — an integer starting at 1 (except where a per-entity rule states otherwise, see §3.6) that increments by exactly 1 on every mutation of the resource, including mutations caused by cascades from operations on other resources.

Any state transition, derived-field recomputation, or cross-resource cascade that changes a resource is a mutation: it refreshes that resource's `updated_at` and bumps its `version`. This applies to the affected resource itself (for example, a claim moving from `ASSIGNED` to `REPRESENTING`) and to every cascaded target (for example, the office escrow whose `paid_out_cents` is debited when a claim resolves). Lifecycle entities additionally carry a `status` field whose enumerated values are defined per entity in §3; `status` transitions are mutations like any other and therefore increment `version`. The lifecycle values are: a return is `PREPARING` or `FILED` (terminal); a protection product is `ACTIVE` or `VOID` (terminal); an authority notice is `OPEN`, then `PAID`, `ABATED`, or `WITHDRAWN` (all terminal); a claim moves through `TRIAGE`, `INFO_NEEDED`, `SCOPE_CONFIRMED`, `ASSIGNED`, `REPRESENTING`, and `REOPENED`, and terminates in `DENIED` or `RESOLVED`; a representation assignment is `ACTIVE`, then `CANCELLED` or `COMPLETED` (both terminal); a POA is `DRAFT`, `EXECUTED`, `REVOKED`, or `EXPIRED` (the latter two terminal); and a remediation is `OPEN`, then `COMPLETED` (terminal).

### 2.5. Money, Rates, and Rounding Discipline

All monetary amounts are integer cents; the API never exchanges fractional cents. Two rounding disciplines are pinned and must not be interchanged. Where a fee or premium is stated to be rounded to the nearest whole dollar, the final amount is rounded half-up to the nearest 100 cents. Where an interest, accrual, or score is rounded to cents or to an integer, the value is rounded half-up to the nearest cent (or nearest integer, for scores). Quality metrics such as a defect rate or claim rate are carried as exact decimals with no intermediate rounding; rounding is applied only at the final step that produces the integer score.

Rounding order is part of the contract wherever a calculation aggregates before rounding: the program multiplies and sums full-precision intermediate values and rounds exactly once at the end, unless a rule explicitly states a per-item rounding step. Where a rule does prescribe per-item rounding, summing first and rounding once is forbidden because the two orders diverge in the cents.

### 2.6. Optimistic Concurrency Control

Two write operations require the caller to attest to the version of a parent entity it last observed, using a dedicated request field. A claim-intake request must carry `expected_return_version`, the version of the target tax return the client last read; if the return's current `version` differs — for example because the return was re-quoted by an office operator after the client fetched it — the intake is rejected with `ERR_STALE_VERSION` (HTTP 412) rather than attaching a claim to a return the caller no longer recognizes. A power-of-attorney execution request must carry `expected_poa_version`, matching the current `version` of the claim's current `DRAFT` POA; a newer draft created for the same claim supersedes the prior one, so executing against a stale draft view is likewise rejected with `ERR_STALE_VERSION` (HTTP 412). Endpoints not named here accept no version field at all.

### 2.7. The Logical Clock

Time-dependent behavior never consults wall-clock time. A single logical clock governs interest accrual windows, power-of-attorney expiry, and remediation deadlines. Before any clock-setting call is made, the logical clock reads exactly `2026-09-01T00:00:00Z`, and it never falls back to wall-clock time thereafter. A `ProgramAdmin` may advance the logical clock to a supplied `to_iso8601` instant through a test-driving capability; the response reports the new `current_utc`. Lazy evaluations tied to the clock — in particular POA expiry — are performed on subsequent reads and on relevant transition attempts after the clock moves.

### 2.8. Validation Ordering

When a request violates several rules, the rejection a caller observes is deterministic because validation categories run in a fixed order. Authentication (missing or malformed identity headers) is checked first and yields `ERR_UNAUTHENTICATED`. Authorization — role permission and entity-backed ownership — is checked second and yields `ERR_FORBIDDEN`. Existence of every referenced identifier is checked third, from left to right across path and body, and yields `ERR_NOT_FOUND`. State preconditions on the target resource come fourth (`ERR_INVALID_STATE`), followed by terminal-state lockdown (`ERR_ALREADY_TERMINAL`), then the optimistic-concurrency check (`ERR_STALE_VERSION`). Business rules — segregation of duties, office-posture gating, POA temporal validity, referential requirements such as terminal notices or protection coverage, capacity and window constraints, close-period monotonicity, and component-set rules — are evaluated next, in the priority order stated alongside each rule in §3. Generic malformed input — a missing required field, a wrong type, a negative amount where a non-negative one is required, an unrecognized enum value — is caught last and yields `ERR_VALIDATION` (HTTP 400).

### 2.9. Referential Integrity and Nested Retrieval

Every identifier appearing in a path or request body must resolve to an existing resource before business rules run; the first unresolved identifier, scanning left to right, produces `ERR_NOT_FOUND` (HTTP 404). Foreign-key relationships — a return's `client_id`, `office_id`, and `preparer_id`; a product's `return_id`; a claim's `return_id`, `notice_id`, and `protection_product_id`; an assignment's `claim_id` and `agent_id`; an escrow's `office_id` — are validated at this existence step. Operations on one resource routinely cascade into others (a notice payment recomputes claim payouts; a claim resolution debits an escrow and completes an assignment); each cascade target is mutated as its own resource with its own `updated_at` refresh and `version` increment, never silently.

## 3. Business Logic & Workflows

### 3.1. Standing Up an Office: Preparers, Agents, and Escrow Funding

A `ProgramAdmin` provisions the program's backbone. Creating an office requires a `name` and a two-letter `region_code` such as `CA`; the new office starts with `posture` equal to `OK`, its `last_close_period` is null until the first quality close, and its `version` starts at 1. The `posture` is never set directly — it is recomputed exclusively by the quality-close workflow described in §3.8, and it gates product sales and preparer upgrades as described there.

An `OfficeManager` staffs the office by creating preparers, supplying `office_id`, `full_name`, and a credential `tier` of `ASSOCIATE`, `SENIOR`, `MASTER`, or `ENROLLED_AGENT`. A new preparer's `credential_status` starts as `ACTIVE` and their `remediation_status` starts as `NONE`; these are two parallel dimensions that evolve independently and never block each other's transitions. A preparer may later be upgraded to a strictly higher-multiplier tier by an `OfficeManager`; attempting a lateral or downward move is rejected with `ERR_DOWNGRADE_FORBIDDEN` (HTTP 422), and any upgrade attempted while the preparer's office is in `PROBATION` posture is rejected with `ERR_OFFICE_POSTURE_BLOCKED` (HTTP 409). The tier in force at the moment of a quote or filing is what pricing uses, so an upgrade only affects future quotes and filings, never retroactively.

The `ProgramAdmin` also enrolls agents, each with a `full_name`, a unique `license_number` (reusing an existing license number is refused with `ERR_VALIDATION` (HTTP 400)), and an optional `max_parallel` capping how many claims the agent may simultaneously hold in `REPRESENTING` status — at least 1, defaulting to 3 when omitted. Client registration, performed by an `OfficeManager` or `CaseManager` with `full_name` and `email`, enforces one email per client across the program: a repeat address is refused with `ERR_DUPLICATE_CLIENT_EMAIL` (HTTP 409).

Program funding lives in exactly one `OfficeEscrow` per office, created by a `ProgramAdmin` with the `office_id` and a strictly positive `funded_cents`. Attempting to fund a second escrow for the same office fails with `ERR_DUPLICATE_ESCROW` (HTTP 409). A new escrow starts with `paid_out_cents` at 0 and `expected_accrual_cents` at 0; the meaning and maintenance of those two ledgers is covered in §3.7.

### 3.2. Preparing, Quoting, and Filing Returns

Return preparation begins when an `OfficeManager` creates a return with `client_id`, `office_id`, `preparer_id`, the calendar `tax_year` (an integer), and a `components` array. The component vocabulary is fixed: `1040_SIMPLE`, `1040_ITEMIZED`, `1040_BUSINESS`, `1040_MULTI_STATE`, `AMENDED_RETURN`, and `PRIOR_YEAR_REVIEW`. The array must be non-empty, drawn only from these codes, and free of duplicates; a violation is rejected with `ERR_INVALID_COMPONENTS` (HTTP 422). The `filing_kind` defaults to `ORIGINAL` and may be `AMENDED`; an amended filing requires `original_return_id` pointing at an existing return that is itself already `FILED`, and is otherwise rejected with `ERR_AMEND_REQUIRES_ORIGINAL` (HTTP 422) — or `ERR_NOT_FOUND` when the referenced original does not exist. For an `ORIGINAL` filing any supplied `original_return_id` is ignored and stored as null. A return is born in `PREPARING` status.

Every return carries two fee figures. At creation — and again on every update that changes `components` or `preparer_id` while the return remains `PREPARING` — the system computes `quoted_fee_cents` from the preparer's tier at that moment. The quote is built from per-component credit weights: `1040_SIMPLE` contributes 7500 cents, `1040_ITEMIZED` 15000, `1040_BUSINESS` 30000, `1040_MULTI_STATE` 20000, `AMENDED_RETURN` 12000, and `PRIOR_YEAR_REVIEW` 8000. The credits for all listed components are summed into a single integer total; that total is then multiplied by the tier multiplier — 1.0 for `ASSOCIATE`, 1.25 for `SENIOR`, 1.5 for `MASTER`, 1.75 for `ENROLLED_AGENT` — producing a possibly fractional cent figure; and the product is rounded half-up to the nearest whole dollar (100 cents). The rounding order is pinned: multiply the total credits by the multiplier first, then round once. Rounding each component's contribution separately and summing is forbidden because it yields different cents.

Updates to a `PREPARING` return go through the patch capability, which accepts `components` and/or `preparer_id`, re-quotes `quoted_fee_cents` using the then-current tier, and bumps the return's `version`. A patch that changes neither field — or carries an empty body — leaves the resource untouched: no re-quote, no `updated_at` refresh, no `version` bump. Once a return is `FILED` it is locked: any further patch or re-file attempt is rejected with `ERR_ALREADY_TERMINAL` (HTTP 409), and an action attempted against a return in the wrong state more generally yields `ERR_INVALID_STATE` (HTTP 409).

Filing is the point of no return, performed by an `OfficeManager`. The return must still be `PREPARING`; the assigned preparer must resolve to someone whose `credential_status` is currently `ACTIVE` (a suspended preparer cannot have returns filed under their name — attempting to file under a non-`ACTIVE` preparer is rejected with `ERR_INVALID_STATE`); and for an `AMENDED` filing the referenced original return must exist and be `FILED` at filing time, under the same rule as at creation. Filing recomputes the fee with the same credit table and the same rounding rule, but using the preparer's tier **at filing time**, and locks the result into `final_fee_cents`, which stays null until that moment and is never recomputed afterwards. Because a preparer swap between quote and filing changes the tier input, identical components can legitimately produce a `quoted_fee_cents` that differs from `final_fee_cents`; this divergence is by design, not an error. Filing sets the return's status to `FILED` and increments its `version`.

### 3.3. Selling the Protection Product

At or after filing, an `OfficeManager` may sell the client a protection product for the return, specifying the `return_id` and a product `tier` of `STANDARD` or `PLUS`. Eligibility is strict: the return must be `FILED`, and it must not carry the `AMENDED_RETURN` component — a violation of either condition is refused with `ERR_PRODUCT_INELIGIBLE` (HTTP 422). Exactly one `ACTIVE` product may exist per return; a second purchase while one is still active is rejected with `ERR_DUPLICATE_PRODUCT` (HTTP 409) — and because that duplicate gate runs before the eligibility re-check, an ineligible return that already carries an `ACTIVE` product surfaces `ERR_DUPLICATE_PRODUCT` first. (The conflicting purchase is simply refused — the existing product stays `ACTIVE`; nothing about a duplicate attempt moves it to `VOID`.) A product sale attempted for a return of an office whose posture is `PROBATION` is rejected with `ERR_OFFICE_POSTURE_BLOCKED` (HTTP 409).

The `premium_cents` charged at purchase derives from the return's component credits — the same per-component weights used for the preparation fee — summed into a total, then bucketed by two thresholds: a simple cap at 15000 total credits and a standard cap at 30000. When the total is at or below the simple cap, the premium is the flat base premium for the tier: 4900 cents for `STANDARD`, 9900 cents for `PLUS`. When the total exceeds the simple cap but is at or below the standard cap, the premium is one and a half times the base premium, rounded half-up to cents where fractional. When the total exceeds the standard cap, the premium is double the base premium. All three band results are rounded half-up to the nearest cent (integral base premiums pass through unchanged). The tier boundary rule is inclusive downward: a total exactly equal to a cap falls into the lower band. A `PLUS` product adds penalty coverage on top of `STANDARD`, a distinction that matters at payout time in §3.7. A product is born `ACTIVE`.

A `ProgramAdmin` may void an `ACTIVE` product, but only while no claim referencing it sits in any non-terminal status — a claim in `TRIAGE`, `INFO_NEEDED`, `SCOPE_CONFIRMED`, `ASSIGNED`, `REPRESENTING`, or `REOPENED` blocks the void with `ERR_VOID_CLAIMS_OPEN` (HTTP 409); claims in `RESOLVED` or `DENIED` do not. A successful void moves the product to `VOID` and increments its `version`; `VOID` is terminal, and attempting to void an already-`VOID` product is rejected with `ERR_ALREADY_TERMINAL` (HTTP 409).

### 3.4. When the Authority Writes: Notice Intake, Payment, and Abatement

A `CaseManager` registers an authority notice against a `FILED` return (registering against a return in any other status is rejected with `ERR_INVALID_STATE`), supplying `return_id`, the `authority_type` (`FEDERAL` or `STATE`), the authority's free-text `notice_reference`, the additional tax assessed in `tax_delta_cents`, the `penalty_cents` assessed, the `issued_at` date, and the authority's payment deadline `due_at`. Both amounts must be non-negative. A notice opens in `OPEN` status with `interest_cents` and `paid_at` null and `claim_id` null until a claim intake links it.

Interest accrues only on payment. When an `OfficeManager` records payment on an `OPEN` notice, `paid_at` is set to the logical clock and `interest_cents` is computed from the elapsed days between `due_at` and `paid_at`: the due date itself is excluded and the payment date included, so paying on or before `due_at` yields zero days and zero interest — `interest_cents` is stored as the integer 0, never null, once payment is recorded. The elapsed day count is the whole-day difference between the `due_at` and `paid_at` instants, with any sub-day remainder truncated toward zero. For a positive day count, the interest is the notice's `tax_delta_cents` multiplied by a daily rate of 0.000273972602739726 and by the number of days, with the full-precision product rounded half-up once to cents. Rounding a per-day amount first and then multiplying is forbidden — the pinned order is product-then-round. Payment moves the notice to `PAID`, bumps its `version`, and — as covered in §3.7 — triggers a payout recomputation on any linked claim.

An enrolled agent who holds the `ACTIVE` assignment on a claim in `REPRESENTING` may win an abatement on that claim's linked notice: the notice's `interest_cents` and `penalty_cents` are zeroed (the authority granted relief), the notice moves from `OPEN` to `ABATED`, and the linked claim's payout figures recompute. An agent attempting this on a notice whose linked claim is not in `REPRESENTING`, or where the acting agent does not hold its active assignment, fails the ownership or state check — `ERR_FORBIDDEN` or `ERR_INVALID_STATE` as applicable. An `OfficeManager` may instead withdraw an `OPEN` notice, moving it to `WITHDRAWN` — but only while the notice's `claim_id` is still null; a claim-linked notice must be resolved through the claim, not withdrawn, and attempting to withdraw a linked notice is rejected with `ERR_INVALID_STATE`.

One ordering rule protects settled claims: recording payment or abatement on a notice whose linked claim is already `RESOLVED` is rejected with `ERR_CLAIM_ALREADY_RESOLVED` (HTTP 409). The remedy is to reopen the claim first (§3.7), then take the notice action. Notices in any terminal state — `PAID`, `ABATED`, `WITHDRAWN` — are immutable; further action attempts draw `ERR_ALREADY_TERMINAL`.

### 3.5. Claim Intake, the Information Loop, and Scope Determination

A claim begins when a `CaseManager` opens one against a noticed, protected return, naming the `return_id`, the triggering `notice_id`, and `expected_return_version` for the OCC check described in §2.6. Intake enforces three protection prerequisites, all surfaced as `ERR_PROTECTION_REQUIRED` (HTTP 422): the return must be `FILED`; the notice must be `OPEN` and not already linked to another claim; and the return must carry an `ACTIVE` protection product. On success the intake writes the new claim's `id` into the notice's `claim_id` (bumping the notice's `version`), resolves the claim's `protection_product_id` from the return's active product, and bumps the return's `version` as well — the intake is itself a mutation of the return, which is exactly what a second client's stale `expected_return_version` protects against. The claim is born in `TRIAGE`, with `scope` and `error_attribution` null, all payout fields at 0, `scoped_by_user_id` null, and `final_liability_cents` null.

From `TRIAGE` a `CaseManager` has three moves. Requesting information moves the claim to `INFO_NEEDED`; the client — and only the owning client, by entity-backed identity — then provides information to return the claim to `TRIAGE`. This pair forms the information loop; `INFO_NEEDED` is never terminal, and either move bumps the claim's `version`. Scoping the claim with `scope` set to `IN_SCOPE` requires `error_attribution` to be present in the payload — one of `PREPARER_ERROR` or `CLIENT_DATA_ERROR` — and moves the claim to `SCOPE_CONFIRMED`, recording the acting manager's `X-User-ID` into `scoped_by_user_id` as the segregation-of-duties anchor. Scoping with `scope` set to `OUT_OF_SCOPE` denies the claim outright: `scope` is recorded, the payout fields stay 0, and the claim moves to `DENIED`, which is terminal — every further transition attempt on it returns `ERR_INVALID_STATE`. All scoping moves bump the claim's `version`. Claims admit two terminal statuses, `DENIED` and `RESOLVED`; they are pinned by lockdown, with the `DENIED` lockdown surfacing `ERR_INVALID_STATE` and the `RESOLVED` lockdown surfacing `ERR_ALREADY_TERMINAL` on every transition attempt (assignment cancellation, by contrast, gates on the linked claim still being `ASSIGNED`, so a cancellation against a `RESOLVED` claim yields `ERR_INVALID_STATE`).

### 3.6. Representation: Assignment, Capacity, and Power of Attorney

An in-scope, confirmed claim is staffed by a `CaseManager` through assignment of an enrolled agent, supplying `agent_id`, `window_start`, and `window_end`. Four gates apply at assignment time. The claim must be in `SCOPE_CONFIRMED` with `scope` equal to `IN_SCOPE` — and it must not already carry an `ACTIVE` assignment, which likewise surfaces `ERR_INVALID_STATE`. The window must be strictly ordered — `window_end` after `window_start` — or the request fails with `ERR_INVALID_WINDOW` (HTTP 422). The agent's parallel capacity must have room: the count of claims currently in `REPRESENTING` under that agent must be below their `max_parallel`, or the assignment is rejected with `ERR_AGENT_CAPACITY` (HTTP 409). And the half-open window — covering the start instant up to but not including the end instant — must not overlap any other `ACTIVE` assignment window for the same agent; two windows that merely touch, one's end equal to the other's start, do not overlap, but any true intersection is rejected with `ERR_WINDOW_OVERLAP` (HTTP 409). The window-order check runs before the capacity and overlap checks. A successful assignment creates a `RepresentationAssignment` in `ACTIVE` status with the payload window and moves the claim from `SCOPE_CONFIRMED` to `ASSIGNED`. An assignment may be cancelled while its claim is still `ASSIGNED` — moving the assignment to `CANCELLED` while the claim stays `ASSIGNED` and may be re-assigned to another agent — but cancellation is impossible once the claim has advanced to `REPRESENTING`, drawing `ERR_INVALID_STATE`.

Representation formally begins with a power of attorney. A `CaseManager` drafts a POA on the claim with the `agent_id` of the attorney-in-fact and an `expires_at` instant; the new draft supersedes any existing `DRAFT` POA on the same claim, which is automatically moved to `REVOKED`. Drafting requires no particular claim status beyond the claim being neither `DENIED` nor `RESOLVED` — it is available from `TRIAGE` onward. A superseding draft continues the claim's draft-POA version line rather than restarting at 1 — its `version` is set to the superseded draft's `version` plus 1 — so an execution request attesting to a pre-supersede version is detected as stale per §2.6. A draft may also be revoked directly while still `DRAFT`. Execution is the pivotal act: the claim must be `ASSIGNED`; a `DRAFT` POA must exist on the claim — if no `DRAFT` exists but the claim carries a POA in `REVOKED` or `EXPIRED` (for example a draft that was directly revoked), execution is rejected with `ERR_INVALID_STATE` (HTTP 409), while a claim that has never had a POA yields `ERR_POA_NOT_DRAFT` (HTTP 409); the request must carry `expected_poa_version` matching that draft's current `version` per §2.6; the draft's `expires_at` must be strictly later than the logical clock, or execution fails with `ERR_POA_EXPIRED` (HTTP 422); and the POA's `agent_id` must be the agent of the claim's `ACTIVE` assignment, with a mismatch rejected as `ERR_INVALID_STATE` (HTTP 409). Execution stamps `executed_at` with the logical clock, moves the POA from `DRAFT` to `EXECUTED`, advances the claim from `ASSIGNED` to `REPRESENTING`, and increments both resources' versions.

An executed POA does not last forever. When the logical clock passes its `expires_at` — strictly passes; at the exact expiry instant the POA is still valid — the POA is lazily moved from `EXECUTED` to `EXPIRED` on read or on the next claim transition attempt (a lazy expiry is itself a mutation, refreshing `updated_at` and bumping the POA's `version`); the claim itself remains `REPRESENTING`, and a fresh POA may be drafted for it.

### 3.7. Resolution, Reimbursement, and the Office Escrow

Resolution converts representation into money. A `CaseManager` may resolve a claim in `REPRESENTING`, subject to three checks evaluated in order after the global gates: the segregation-of-duties rule, the notice-terminal rule, and then the payout computation itself. Segregation of duties forbids the same operator who scoped the claim from resolving it — if the acting `X-User-ID` equals the claim's `scoped_by_user_id`, the resolve is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Every linked authority notice must be in a terminal state — `PAID`, `ABATED`, or `WITHDRAWN`; a still-`OPEN` notice blocks resolution with `ERR_NOTICE_NOT_TERMINAL` (HTTP 409).

The reimbursement waterfall then runs against the claim's single linked notice, branching on the claim's `error_attribution`. For a `PREPARER_ERROR` claim, `payout_base_cents` covers the notice's `tax_delta_cents` in full, `payout_interest_cents` covers its `interest_cents` (zero while the notice was still `OPEN`, and zeroed entirely if the notice was abated), and `payout_penalty_cents` covers its `penalty_cents` only when the claim's product tier is `PLUS` — a `STANDARD` product pays no penalty. For a `CLIENT_DATA_ERROR` claim, the base and penalty stay the taxpayer's own liability — `payout_base_cents` and `payout_penalty_cents` are both 0 — and only `payout_interest_cents` is covered. In both branches `payout_total_cents` is the sum of the three components. These payout figures recompute on every linked-notice status change — payment or abatement — not only at resolution.

The escrow liability fold is deliberately asymmetric. `final_liability_cents` equals `payout_total_cents` plus `payout_base_cents` once more: the additional-tax component is counted twice in the escrow debit (once as the reimbursement to the taxpayer, once as the program's make-whole cost), while interest and penalty count once each. Resolution writes this figure onto the claim (it is null until then), completes the claim's `ACTIVE` assignment by moving it to `COMPLETED`, and debits the office escrow: `paid_out_cents` increases by `final_liability_cents`, while `expected_accrual_cents` increases by the claim's `payout_total_cents` marked up by one tenth — that is, multiplied by 1.1 and rounded half-up to cents, rounded per claim and then summed. Summing first and rounding once is forbidden here; the pinned order is per-claim rounding. The escrow's `version` increments, and the claim moves to `RESOLVED` with its own `version` bump.

`expected_accrual_cents` is the running per-claim sum just described across all of the office's resolved claims, and it is historical: reopening never reduces it. `paid_out_cents`, by contrast, is the live cash view. A `RESOLVED` claim may be reopened by a `CaseManager` (reopening any other status yields `ERR_INVALID_STATE`); reopening credits the escrow by subtracting the claim's retained `final_liability_cents` from `paid_out_cents` (with an escrow `version` bump) while leaving `expected_accrual_cents` untouched, keeps `final_liability_cents` on the claim for audit, and moves the claim to `REOPENED`. From `REOPENED` the claim cycles forward again: it may be re-scoped in either direction — re-confirming scope requires `error_attribution` afresh and re-records `scoped_by_user_id`, with payout figures recomputed at the next resolution, while scoping out denies the claim — and the full assign, execute, resolve path runs again. The office's accrual coverage — expected accrual against funded-minus-paid-out headroom — is derived on read from these escrow figures.

### 3.8. Quality Close, Office Posture, and Preparer Remediation

Oversight closes the loop. An `OfficeManager` periodically closes a quality period for an office by submitting the `period_month` (a `YYYY-MM` string; any other shape is rejected with `ERR_VALIDATION`), the count of `returns_examined` in the sample (strictly positive), and the count of `returns_with_defects` (at least zero and at most the number examined). Periods must move strictly forward: a `period_month` that does not lexicographically exceed the office's `last_close_period` is rejected with `ERR_CLOSE_PERIOD_REGRESSION` (HTTP 422); a null `last_close_period` accepts any first period. A successful close creates an `OfficeQualitySnapshot` carrying the office's `office_id`, the period and sample counts, the exact-decimal `defect_rate` (defects divided by examined, with no intermediate rounding), the computed `quality_score`, and the `posture_after` recording the office's posture immediately after this close.

The score combines defect and claim pressure. Let the defect rate be defects over examined as an exact decimal, and the claim rate be the number of the office's claims resolved with resolution falling inside the closed period — that is, whose recorded resolution instant falls within that calendar month — divided by the same examined count, also an exact decimal. The `quality_score` starts from 100, subtracts the defect rate weighted four hundredfold and the claim rate weighted three hundredfold, rounds half-up to an integer, and clamps into the inclusive range 0 to 100. Posture thresholds are pinned with at-least semantics: a score of at least 80 leaves or moves the office to `OK`; a score of at least 60 but below 80 yields `WATCH`; below 60 yields `PROBATION`. The office's posture machine is fully connected — any of `OK`, `WATCH`, `PROBATION` can move to any other, driven solely by quality close; there is no direct set operation. Each close bumps the office's `version` and refreshes `last_close_period` whether or not the posture changes, and the `posture` gates named in §3.1 and §3.3 take immediate effect.

Probation carries a personnel consequence: when a close lands the office in `PROBATION`, every preparer of that office holding an `OPEN` remediation whose `due_at` is earlier than the logical clock has their `credential_status` flipped to `SUSPENDED` (with a preparer `version` bump), which immediately blocks filing under their name per §3.2. A preparer already `SUSPENDED` takes no further bump from a later PROBATION close.

Remediation itself is a lightweight discipline loop. An `OfficeManager` opens a remediation action for a preparer with `preparer_id` and a `due_at` deadline; opening one flips the preparer's `remediation_status` from `NONE` or `COMPLETED` to `ACTIVE`. If that preparer already has an `OPEN` remediation, the existing one auto-completes on the spot — its `completed_at` is stamped with the logical clock and its status becomes `COMPLETED`, cascading the preparer's `remediation_status` momentarily to `COMPLETED` — before the new `OPEN` remediation sets it back to `ACTIVE`; the preparer ends the operation in `ACTIVE` either way (with a single preparer `version` bump for the operation, not one per flip). The preparer — and only that preparer, by entity-backed identity — completes their own open remediation, which requires the logical clock to be at or before `due_at`; a completion attempted after the deadline is rejected with `ERR_REMEDIATION_OVERDUE` (HTTP 422), because an overdue remediation can no longer be completed — it can only be overtaken by the probation cascade above. Completion stamps `completed_at`, moves the remediation to `COMPLETED`, and sets the preparer's `remediation_status` to `COMPLETED`. The two preparer dimensions stay independent throughout: a suspension from the quality close changes `credential_status` without touching `remediation_status`, and remediation activity never alters `credential_status`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify or transition an existing resource return `200 OK`. All paths are mounted under the `/tax` prefix. Request and response bodies are not repeated here — the fields, defaults, and side effects for each operation are specified in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/tax/offices` | Create an office | ProgramAdmin |
| GET | `/tax/offices` | List offices (filterable by `region_code`) | ProgramAdmin, OfficeManager, CaseManager |
| GET | `/tax/offices/{id}` | Get one office | ProgramAdmin, OfficeManager, CaseManager, Preparer, EnrolledAgent |
| POST | `/tax/offices/{id}/quality-close` | Close a quality period: create snapshot (201 with the new snapshot), recompute posture, suspend overdue-remediation preparers on PROBATION | OfficeManager |
| GET | `/tax/offices/{id}/snapshots` | List quality snapshots for an office | ProgramAdmin, OfficeManager, CaseManager |
| POST | `/tax/preparers` | Create a preparer | OfficeManager |
| GET | `/tax/preparers` | List preparers (filterable by `office_id`) | ProgramAdmin, OfficeManager, CaseManager |
| GET | `/tax/preparers/{id}` | Get one preparer | ProgramAdmin, OfficeManager, CaseManager, Preparer |
| POST | `/tax/preparers/{id}/upgrade` | Upgrade preparer credential tier (strictly higher; blocked under PROBATION) | OfficeManager |
| POST | `/tax/clients` | Register a client | OfficeManager, CaseManager |
| GET | `/tax/clients/{id}` | Get one client | OfficeManager, CaseManager, Client |
| GET | `/tax/clients/{id}/returns` | List a client's returns | OfficeManager, CaseManager, Client |
| POST | `/tax/returns` | Create a return; computes the quoted fee | OfficeManager |
| GET | `/tax/returns` | List returns (filterable by `office_id`, `preparer_id`, `client_id`, `original_return_id`) | ProgramAdmin, OfficeManager, CaseManager |
| GET | `/tax/returns/{id}` | Get one return | ProgramAdmin, OfficeManager, CaseManager, Client, Preparer, EnrolledAgent |
| GET | `/tax/returns/{id}/products` | List protection products for a return (0 or 1 active) | ProgramAdmin, OfficeManager, CaseManager |
| GET | `/tax/returns/{id}/notices` | List authority notices for a return | OfficeManager, CaseManager, EnrolledAgent |
| PATCH | `/tax/returns/{id}` | Update components or preparer while PREPARING; re-quotes | OfficeManager |
| POST | `/tax/returns/{id}/file` | File the return; locks the final fee | OfficeManager |
| POST | `/tax/products` | Sell a protection product for a FILED return; computes the premium | OfficeManager |
| POST | `/tax/products/{id}/void` | Void an ACTIVE product with no non-terminal claims | ProgramAdmin |
| POST | `/tax/notices` | Register an authority notice against a FILED return | CaseManager |
| GET | `/tax/notices` | List notices (filterable by `return_id`, `claim_id`) | OfficeManager, CaseManager, EnrolledAgent |
| GET | `/tax/notices/{id}` | Get one notice | OfficeManager, CaseManager, EnrolledAgent |
| POST | `/tax/notices/{id}/pay` | Record payment at the logical clock; computes interest | OfficeManager |
| POST | `/tax/notices/{id}/abate` | Enrolled agent wins abatement: interest and penalty zeroed | EnrolledAgent |
| POST | `/tax/notices/{id}/withdraw` | Withdraw an unlinked OPEN notice | OfficeManager |
| POST | `/tax/claims` | Open a claim for a noticed, protected return; links the notice | CaseManager |
| GET | `/tax/claims` | List claims (filterable by `return_id`, `office_id`, `notice_id`, `protection_product_id`) | ProgramAdmin, OfficeManager, CaseManager |
| GET | `/tax/claims/{id}` | Get one claim | ProgramAdmin, OfficeManager, CaseManager, Client, EnrolledAgent |
| GET | `/tax/claims/{id}/poas` | List POAs for a claim | OfficeManager, CaseManager, EnrolledAgent |
| GET | `/tax/claims/{id}/assignments` | List assignments for a claim | OfficeManager, CaseManager, EnrolledAgent |
| POST | `/tax/claims/{id}/scope` | Scope determination: IN_SCOPE (requires attribution) confirms scope; OUT_OF_SCOPE denies | CaseManager |
| POST | `/tax/claims/{id}/request-info` | Move claim to INFO_NEEDED | CaseManager |
| POST | `/tax/claims/{id}/provide-info` | Client returns claim to TRIAGE | Client |
| POST | `/tax/claims/{id}/assign` | Assign an enrolled agent with a half-open representation window | CaseManager |
| POST | `/tax/claims/{id}/poa` | Draft a POA for the claim; supersedes any existing draft | CaseManager |
| POST | `/tax/claims/{id}/poa/execute` | Execute the claim's DRAFT POA; moves claim to REPRESENTING | CaseManager |
| POST | `/tax/poas/{id}/revoke` | Revoke a DRAFT POA | CaseManager |
| GET | `/tax/poas/{id}` | Get one POA | OfficeManager, CaseManager, EnrolledAgent |
| GET | `/tax/poas` | List POAs (filterable by `agent_id`, `claim_id`) | OfficeManager, CaseManager, EnrolledAgent |
| POST | `/tax/claims/{id}/resolve` | Resolve claim: compute payouts and liability, complete assignment, debit escrow | CaseManager |
| POST | `/tax/claims/{id}/reopen` | Reopen a RESOLVED claim; credits escrow paid-out | CaseManager |
| POST | `/tax/assignments/{id}/cancel` | Cancel an ACTIVE assignment while the claim is still ASSIGNED | CaseManager |
| POST | `/tax/agents` | Create an enrolled agent | ProgramAdmin |
| GET | `/tax/agents/{id}` | Get one enrolled agent | ProgramAdmin, OfficeManager, CaseManager, EnrolledAgent |
| GET | `/tax/agents/{id}/assignments` | List assignments for an enrolled agent | ProgramAdmin, OfficeManager, CaseManager, EnrolledAgent |
| POST | `/tax/remediations` | Open a remediation for a preparer; auto-completes any existing OPEN one | OfficeManager |
| GET | `/tax/remediations` | List remediations (filterable by `preparer_id`) | OfficeManager, CaseManager, Preparer |
| GET | `/tax/remediations/{id}` | Get one remediation action | OfficeManager, CaseManager, Preparer |
| POST | `/tax/remediations/{id}/complete` | Preparer completes own remediation before its deadline | Preparer |
| POST | `/tax/escrows` | Fund an office escrow (one per office) | ProgramAdmin |
| GET | `/tax/escrows/{id}` | Get one escrow | ProgramAdmin, OfficeManager, CaseManager |
| GET | `/tax/escrows` | List escrows (filterable by `office_id`) | ProgramAdmin, OfficeManager, CaseManager |
| POST | `/tax/_clock/set_current_utc` | Test-driving capability: set the logical clock | ProgramAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3; this catalogue fixes only the identifier-to-status mapping.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ALREADY_TERMINAL` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_OFFICE_POSTURE_BLOCKED` | 409 |
| `ERR_POA_EXPIRED` | 422 |
| `ERR_POA_NOT_DRAFT` | 409 |
| `ERR_NOTICE_NOT_TERMINAL` | 409 |
| `ERR_CLAIM_ALREADY_RESOLVED` | 409 |
| `ERR_PROTECTION_REQUIRED` | 422 |
| `ERR_DUPLICATE_PRODUCT` | 409 |
| `ERR_PRODUCT_INELIGIBLE` | 422 |
| `ERR_AGENT_CAPACITY` | 409 |
| `ERR_WINDOW_OVERLAP` | 409 |
| `ERR_INVALID_WINDOW` | 422 |
| `ERR_CLOSE_PERIOD_REGRESSION` | 422 |
| `ERR_INVALID_COMPONENTS` | 422 |
| `ERR_AMEND_REQUIRES_ORIGINAL` | 422 |
| `ERR_DUPLICATE_ESCROW` | 409 |
| `ERR_REMEDIATION_OVERDUE` | 422 |
| `ERR_DUPLICATE_CLIENT_EMAIL` | 409 |
| `ERR_DOWNGRADE_FORBIDDEN` | 422 |
| `ERR_VOID_CLAIMS_OPEN` | 409 |
