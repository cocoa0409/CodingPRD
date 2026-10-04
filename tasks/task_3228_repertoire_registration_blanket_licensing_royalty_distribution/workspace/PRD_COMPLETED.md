# Repertoire Licensing Royalty API — Product Requirements Document

## 1. Introduction

A performing rights organization sits between two parties that rarely meet: songwriters and publishers who own musical works, and broadcasters, digital services, and live venues that perform them. The value the organization adds is not merely custody of the repertoire — it is the ability to convert millions of scattered performances into a defensible, auditable stream of royalty payments, and to defend those payments against over-claims, fee disputes, and the slow decay of unclaimed money. This document specifies the API surface of that organization's operational core: a system that registers works and their ownership claims, issues blanket licenses against self-reported licensee economics, ingests performance data from a mixture of monitored and unmonitored sources, and runs scheduled distribution cycles that turn pools of collected license fees into per-affiliate royalty statements.

Three pressures shape the design. First, the work-level ownership data is adversarial by nature: multiple publishers and co-writers routinely assert shares that, taken together, exceed the whole work, and the system must surface that conflict, serialize its resolution, and refuse to confirm a work whose claims do not sum to a defensible total. Second, blanket licensing is an act of pricing under imperfect information — the licensee self-reports revenue and usage, the system computes a fee from a category-specific rate structure, and either side may open a rate dispute that escalates through negotiation to a rate court. Third, royalty distribution is a ledger discipline: money flows from a distributable pool, through per-work credit weighting, through per-affiliate share allocation, into statements that must reconcile to the cent, with late claims, audit findings, and escheatment rules governing every cent that does not find its payee on the first pass.

The system is operated by PRO staff in several segregated roles — registration, licensing administration, rate court adjudication, royalty distribution, and finance — alongside affiliated publishers and songwriters acting on their own repertoire and licensees acting on their own licenses. A server-maintained logical clock, settable through a test-driving endpoint, governs every time-sensitive rule in the document; the clock never falls back to wall-clock time, and before any clock-setting call is made it reads exactly `2026-09-01T00:00:00Z`. Advancing the clock triggers an expiry sweep across licenses whose `expiry_date` has passed.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. All resources are mounted under the `/pro` path prefix.

### 2.1. User and Role-Based Access Control

Every request to the API carries two mandatory HTTP headers: `X-User-ID` identifying the acting user, and `X-User-Role` naming the capacity in which they act. The recognized roles, spelled exactly as the server expects them, are `ProRegistrar`, `ProLicensingAdmin`, `RateCourtOfficer`, `RoyaltyDistributor`, `FinanceOfficer`, `Publisher`, `Songwriter`, `Licensee`, and `ProSystemAdmin`. A request missing either header, or presenting a role outside this set, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is authenticated but not permitted for the target endpoint is rejected with `ERR_FORBIDDEN`.

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `Publisher` or `Songwriter`, `X-User-ID` is the `id` of the acting `Affiliate`; ownership checks on any resource that references an `Affiliate` — a work's `registered_by_affiliate_id`, a share claim's `affiliate_id`, a statement's payee — compare the resource's foreign-key field against `X-User-ID`. When `X-User-Role` is `Licensee`, `X-User-ID` is the `id` of the acting `Licensee`, and ownership checks on licensee-linked resources compare against that `id`. When `X-User-Role` is `ProRegistrar`, `ProLicensingAdmin`, `RateCourtOfficer`, `RoyaltyDistributor`, `FinanceOfficer`, or `ProSystemAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it where a workflow calls for attribution (for example, when comparing an adjustment's creator against its approver), but it is never compared to any entity's `id`.

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

List endpoints accept two query parameters controlling the result window. The `limit` parameter caps the number of items returned; it defaults to 10, and accepted values range from a minimum of 1 to a maximum of 100. A `limit` that is not an integer or falls outside that range, and an `offset` that is not an integer or is negative, are rejected with `ERR_VALIDATION`. The `offset` parameter says how many items to skip from the front of the ordered result and defaults to 0. Unless otherwise specified, list endpoints return resources sorted by their `created_at` timestamp in ascending order, with ties broken by `id` in ascending order. The `meta` object of a list response carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every resource in this system — `Affiliate`, `Work`, `ShareClaim`, `Licensee`, `License`, `RateDispute`, `RateCourtCase`, `PerformanceEvent`, `DistributionCycle`, `RoyaltyStatement`, `RoyaltyAdjustment`, `AuditRequest`, and `UnclaimedRoyaltyPool` — carries the standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` timestamp records creation time as an ISO 8601 UTC instant with three fractional digits, and is read from the logical clock described in §2.8 — not from wall-clock time; `updated_at` follows the same format and refreshes on every mutation from that same logical clock. The `version` is an integer that starts at 1 on creation and increments by exactly 1 on every modification of the resource and underpins the optimistic concurrency rules described below. Cascades that touch a parent from a child operation (for example, a share-claim insertion that flips its work into `IN_CONFLICT`) mutate the parent as well, refreshing its `updated_at` and incrementing its `version` independently of any change to the child.

### 2.5. Hierarchical Validation and Nested Retrieval

Requests that address nested resources are validated left to right along the path. The server first confirms that the path-referenced resources exist — a work before its share claims, a cycle before its statements, a licensee before its licenses — and rejects with `ERR_NOT_FOUND` at the first identifier that does not resolve. Only after every path segment resolves does the server examine the request body; a body field referencing another resource by identifier (`work_id`, `license_id`, `affiliate_id`, `cycle_id`, `statement_id`, `dispute_id`, `licensee_id`) that names a non-existent target is rejected with `ERR_REFERENCE_NOT_FOUND`. State checks come after existence: an operation that the target's current state does not permit is rejected with `ERR_INVALID_STATE`. Field-shape problems — an invalid enum member, a malformed ISO date, an `effective_date` that is not strictly earlier than the `expiry_date`, a `period_start` later than the `period_end`, a `play_count` below 1, a negative `disputed_fee_cents` — are rejected with `ERR_VALIDATION`.

### 2.6. Optimistic Concurrency Control

Three write operations require the caller to present the version of a parent entity as observed at the time the client decided to act. Resolving a work conflict requires the request to carry `expected_work_version` matching the work's current `version`. Closing collection on a distribution cycle requires `expected_cycle_version` matching the cycle's current `version`. Issuing a license requires `expected_licensee_version` matching the licensee's current `version`. If the parent entity's version has advanced since the client last read it — because another claim mutated the work's share aggregate, because a prior close re-ran the allocation and bumped the cycle's epoch, or because a revenue or usage update recomputed the licensee's blanket fee — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), and the client retries against fresh state. Each expected-version field, when present, must be an integer — a non-integer value is rejected with `ERR_VALIDATION` — and when the field is omitted entirely the request is processed without an OCC check. No other endpoint takes a version field; requests to endpoints not listed here are processed without an OCC check.

### 2.7. Monetary Values, Rates, and Rounding

All money in this system is stored and transmitted as integer cents — never fractional units of currency. Share proportions are expressed in basis points, where 10000 basis points constitute the whole of a work. Where a calculation yields a fractional cent, the result is rounded half-up to whole cents, and each calculation rounds exactly once, at the point its own rules specify; intermediate values are not pre-rounded. Per-event credit weights are the single exception to integer precision: they are kept at four decimal places, rounded half-up per event, and cycle-level sums add the already-rounded per-event values. Constants embedded in the rate structures — tier caps, tier rates, minimum fees, per-stream micro-cent charges, per-event charges, the administration rates, the claims window, the escheat grace period, and the licensee delinquency threshold — are fixed system parameters described in §3 alongside the workflows that consume them.

### 2.8. The Logical Clock and Time-Driven Rules

The server is stateful only in memory: its data store starts empty on every boot with no seeding of any kind, and all entities created during a run vanish on restart.

The server's logical clock is the only clock the business rules consult. It is advanced exclusively by the clock-setting capability reserved for `ProSystemAdmin`, which accepts a `to_iso8601` target instant — an ISO 8601 datetime with optional offset, with `Z` treated as UTC and a missing offset interpreted as UTC — and returns a `200 OK`; a `to_iso8601` that is not a string or does not parse is rejected with `ERR_VALIDATION`. The clock may be set backward as well as forward, and the response carries an empty data object. Before any such call, the clock reads exactly `2026-09-01T00:00:00Z`. Setting the clock forward triggers an expiry sweep: any license whose `expiry_date` is earlier than the new clock date transitions to `EXPIRED`, whether it was `ACTIVE` or `DISPUTED`, and expiry does not settle an unresolved dispute. License reads also evaluate this expiry rule lazily, so a license past its `expiry_date` reports `EXPIRED` even without an explicit sweep. The claims window on a distribution cycle, the escheatment grace period on an unclaimed pool, and the audit lookback horizon all measure themselves against the logical clock date.

### 2.9. Validation Priority Ordering

When several validations could reject the same request, the server evaluates them in a fixed priority order so that callers see a deterministic error. Authentication comes first (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_FORBIDDEN`), then path existence (`ERR_NOT_FOUND`), then body foreign-key existence (`ERR_REFERENCE_NOT_FOUND`), then state-machine permission (`ERR_INVALID_STATE`), then optimistic concurrency (`ERR_STALE_VERSION`), then segregation of duties (`ERR_SEGREGATION_OF_DUTIES`), then the business safety, temporal, constraint, referential, and fiscal checks in the order described through §3, with field-shape validation (`ERR_VALIDATION`) last. In practical terms, a request that fails both authorization and a business rule is always rejected with the authorization error; a request presenting both a stale parent version and a bad enum value is always rejected with `ERR_STALE_VERSION`.

## 3. Business Logic & Workflows

### 3.1. Affiliation: Registering Songwriters and Publishers

A `ProRegistrar` affiliates a new party by supplying the party's `legal_name`, a `party_type` of either `SONGWRITER` or `PUBLISHER`, and an `affiliation_code` — a party-assigned mnemonic that must be unique across all affiliates; a duplicate code is rejected with `ERR_VALIDATION`. The affiliate begins life with `status` set to `ACTIVE`, and two ledger fields that track its money: `royalty_balance_cents`, the unpaid net royalty balance that payable statements credit and post-distribution adjustments debit or credit, and `total_paid_cents`, the cumulative lifetime amount actually paid across all distributions. Both start at zero and are computed by the system. The registrar may later update the `legal_name` or move the `status` through `SUSPENDED` to `TERMINATED`; each such update increments the affiliate's `version`. Affiliates can be listed with optional `party_type` and `status` filters, and a single affiliate fetch exposes the computed `royalty_balance_cents` and `total_paid_cents` to the registrar, the royalty distributor, the finance officer, and the affiliate acting as `Publisher` or `Songwriter` on its own record.

### 3.2. Work Registration and Share Claims

A `Publisher` registers a musical work by providing its `title`, an optional list of `alternate_titles` used later for performance matching (defaulting to an empty list, and rejected with `ERR_VALIDATION` if it is not a list of strings), and the `registered_by_affiliate_id` of the affiliate — usually the publisher itself — submitting the registration; the named affiliate must exist (else `ERR_REFERENCE_NOT_FOUND`), but the server does not require it to be the caller's own affiliate nor to be a `PUBLISHER` affiliate. The work is born in `REGISTERED` status, with `confirmed_at` null and `aggregate_interest_bps` at zero. That aggregate is the running sum of `interest_share_bps` across the work's `ACCEPTED` share claims: `SUBMITTED` claims awaiting adjudication and `DISPUTED` claims under challenge are excluded until resolved, and the aggregate is recomputed on every share mutation.

Ownership of the work is asserted through share claims. Either a `Publisher` or a `Songwriter` may assert a claim by naming the `affiliate_id` of the claiming affiliate (which must be the caller's own affiliate — a mismatch is rejected with `ERR_FORBIDDEN`), a `role` of `WRITER` or `PUBLISHER`, a `collection_share_bps` stating the share of collections routed to this affiliate, and an `interest_share_bps` stating the ownership interest asserted. Claims may be asserted on a work in any status — the server applies no work-state gate at claim creation. Both share figures are basis points of the whole work, each bounded between 1 and 10000 inclusive, and at most one claim per combination of work, affiliate, and role may exist in a non-`REVOKED` status; violations are rejected with `ERR_INVALID_SHARE`.

A newly created claim enters `SUBMITTED` and is immediately tested against the work's aggregate. If including the claim leaves the aggregate at or below 10000 basis points, the claim auto-accepts to `ACCEPTED` and its interest joins the aggregate. If the insertion pushes the aggregate strictly above 10000, the system flips the work from `REGISTERED` to `IN_CONFLICT`, marks the newly inserted `SUBMITTED` claims whose insertion caused the overflow as `DISPUTED`, and leaves any previously `ACCEPTED` claims untouched — the work's `version` increments as part of this cascade. The `REGISTERED`-to-`IN_CONFLICT` flip can recur across successive over-claim episodes, and the reverse transition happens automatically when the last `DISPUTED` claim on a conflicted work is revoked and the aggregate has returned to at most 10000.

A claim holder who believes another party's already-`ACCEPTED` claim on the same work is wrong can challenge it, moving the target claim from `ACCEPTED` to `DISPUTED` and flipping the work to `IN_CONFLICT` from whatever status it currently holds — including `CONFIRMED`. The challenger must themselves hold a non-`REVOKED` claim on that work and must not be the affiliate that owns the challenged claim; either violation is rejected with `ERR_FORBIDDEN`, and challenging a claim that is not `ACCEPTED` is rejected with `ERR_INVALID_STATE`. This adversarial challenge does not change the aggregate arithmetic — the challenged claim's interest was already counted — but it re-opens the conflict so a registrar must resolve it.

A claim owner may also revoke their own claim outright from any non-`REVOKED` status (`SUBMITTED`, `ACCEPTED`, or `DISPUTED`), provided no `FINALIZED`-or-later royalty statement for any cycle has routed royalties on it; concretely, the claim is locked exactly when the claim's work was referenced by an `ACCEPTED` or `VOIDED` performance event captured into a cycle that has at least one statement in `FINALIZED`, `PAID`, or `ADJUSTED` status, and a claim so locked is rejected with `ERR_CLAIM_LOCKED_BY_DISTRIBUTION`. Revoking a claim the caller does not own is rejected with `ERR_FORBIDDEN`, and revoking an already-`REVOKED` claim is rejected with `ERR_INVALID_STATE`. Revocation recomputes the work's aggregate and, if the work was `IN_CONFLICT` and is now clean, returns it to `REGISTERED`.

### 3.3. Confirming Works and Resolving Conflicts

A `ProRegistrar` confirms a work directly only when its shares never conflicted: the work must be `REGISTERED`, its `aggregate_interest_bps` must be at most 10000, at least one of its claims must be `ACCEPTED`, and no claim may be in `DISPUTED` status. A confirm attempted while the aggregate exceeds the whole or disputes remain is rejected with `ERR_WORK_SHARES_INCOMPLETE`. A successful direct confirm stamps `confirmed_at` with the current clock instant and bumps the work's `version`.

Conflicted works reach `CONFIRMED` through a resolution act instead. The registrar submits two lists, `accept_claim_ids` and `revoke_claim_ids`, that together dispose of every `DISPUTED` claim on the work exactly once — each listed identifier must belong to this work, each disputed claim must appear in exactly one of the two lists, and the post-resolution aggregate must sit at or below 10000 with no `DISPUTED` claims remaining. A resolution that fails any of these conditions is rejected with `ERR_CONFLICT_RESOLUTION_INVALID`. Because the resolution depends on share state the client observed earlier, the request must carry `expected_work_version` matching the work's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), and the client re-reads and retries. Accepted claims have their `interest_share_bps` counted into the aggregate for the first time; revoked claims move to `REVOKED` and, as compensation, their interest is removed from consideration — the aggregate is recomputed as the sum over `ACCEPTED` claims only, `confirmed_at` is stamped, and the work transitions `IN_CONFLICT` to `CONFIRMED`.

The registering publisher may withdraw a work entirely, moving it to the terminal `WITHDRAWN` status, provided the work is `REGISTERED` or `IN_CONFLICT` — withdrawing a `CONFIRMED` or already-`WITHDRAWN` work is rejected with `ERR_INVALID_STATE` — the caller is the work's `registered_by_affiliate_id` and is a `PUBLISHER` affiliate (either violation is rejected with `ERR_FORBIDDEN`), and no `ACCEPTED` performance event references the work — a withdrawal blocked by existing performances is rejected with `ERR_WORK_HAS_PERFORMANCES`. Withdrawal revokes every non-`REVOKED` claim on the work; for a work withdrawn out of `IN_CONFLICT`, the aggregate is also reset to zero, while a work withdrawn out of `REGISTERED` has its aggregate recomputed from its remaining `ACCEPTED` claims (which is zero, since all claims were just revoked). Works can be listed filtered by `status` or `registered_by_affiliate_id`, and share claims can be listed per work, per affiliate, or across the system filtered by `work_id`, `affiliate_id`, or `status`.

### 3.4. Licensees and the Blanket Fee Engine

A `ProLicensingAdmin` onboards a licensee with its `legal_name`, a `category` of `BROADCASTER`, `DIGITAL_SERVICE`, or `VENUE`, a self-reported `reported_revenue_cents` giving the licensee's latest annual gross revenue, and `usage_units` giving its annual usage volume — streams for digital services, events for venues, and zero for broadcasters. Both figures are non-negative integers. Onboarding runs the blanket fee engine, which computes the licensee's `blanket_fee_cents`; the licensee's `credit_standing` begins at `GOOD`.

The fee engine is category-parameterized and always produces the greater of a computed fee and a category minimum, with one final rounding half-up to whole cents at the end — no per-tier rounding. For a `BROADCASTER`, the fee is a marginal-tier sum over `reported_revenue_cents`: the portion up to 500,000,000,000 cents is charged at a rate of 0.0160, the portion above that cap up to 2,000,000,000,000 cents is charged at 0.0140, and any portion beyond the second cap is charged at 0.0110; the result is compared against a minimum fee of 25,000,000 cents. For a `DIGITAL_SERVICE`, the marginal tiers charge the portion of revenue up to 100,000,000,000 cents at 0.0175 and the portion above at 0.0150, and on top of the tier sum the engine adds a per-stream charge of 20 micro-cents per usage unit (that is, `usage_units` multiplied by 20 and divided by 10000 to convert micro-cents to cents) before taking the maximum against a minimum of 10,000,000 cents. For a `VENUE`, the structure is flat rather than tiered: the fee is 0.0080 times the revenue plus a per-event charge of 15,000 cents per usage unit, floored at a minimum of 5,000,000 cents.

The engine re-runs whenever the licensee's revenue or usage is updated — either by the licensing admin or by the licensee patching its own record — and on license issuance and renewal. There is one override: when a settled rate dispute has set the licensee's `blanket_fee_cents` to a negotiated or adjudicated figure, the engine is bypassed and the settled figure stands until the next revenue or usage update, at which point the engine re-runs and the licensee's fee becomes the greater of the engine's fresh computation and the settled figure. The licensee resource carries a nullable `settled_fee_cents` field recording that figure; it starts null, is stamped at every dispute settlement or rate-court decision, is compared only on revenue or usage updates, and is never cleared thereafter. Each revenue or usage patch increments the licensee's `version`; a patch that names neither field changes nothing and leaves the version untouched. Note that for a `DIGITAL_SERVICE` licensee the `usage_units` patch reweighs the fee only through the per-stream micro-charge, whereas for a `VENUE` licensee each usage unit is charged the full 15,000-cent per-event amount.

### 3.5. Issuing, Suspending, and Terminating Blanket Licenses

Issuance of a blanket license requires the licensee's `credit_standing` to be `GOOD`; issuance attempted for a `DELINQUENT` licensee is rejected with `ERR_LICENSEE_DELINQUENT`. The licensing admin supplies the `effective_date` — the first covered day, inclusive — and the `expiry_date`, the last covered day, also inclusive, which must be strictly later than the effective date. Because issuance pins the licensee's current fee into the license, the request must carry `expected_licensee_version` matching the licensee's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), protecting the caller from pinning a `blanket_fee_cents` recomputed by a revenue or usage update it never saw. The issued license records its `licensee_id`, copies the licensee's `category` immutably, starts in `ACTIVE` status, and snapshots `fee_basis_cents` equal to the licensee's `blanket_fee_cents` at that moment. That pinned basis is permanent: every performance and every pool computation under this license uses the pinned `fee_basis_cents`, even if the licensee's fee later changes. Issuance itself bumps the issuing licensee's `version`.

Licenses live a managed lifecycle. When the licensee's standing deteriorates to `DELINQUENT`, the licensing admin may suspend the license, moving it from `ACTIVE` — or from `DISPUTED` if a dispute is in flight — to `SUSPENDED`; suspending while the licensee is not `DELINQUENT`, or from any other license status, is rejected with `ERR_INVALID_STATE`. While suspended, new performance ingestion under the license is rejected with `ERR_LICENSE_SUSPENDED`. Reinstatement from `SUSPENDED` to `ACTIVE` requires the licensee to have returned to `GOOD` standing; any other combination is rejected with `ERR_INVALID_STATE`. Termination is permitted from `ACTIVE` only when no audit against the licensee is open (any audit must be `CLOSED` or absent; an open audit blocks termination with `ERR_INVALID_STATE`), and from `SUSPENDED` without condition; termination from any other status is likewise rejected with `ERR_INVALID_STATE`, and `TERMINATED` is terminal. Expiry is driven by the clock: once the clock date passes the `expiry_date`, the license transitions to `EXPIRED` from either `ACTIVE` or `DISPUTED`, and expiry does not settle an unresolved dispute — the dispute continues and may still produce retroactive adjustments. License lists support filters on `status`, `category`, and `licensee_id`.

### 3.6. Rate Disputes and the Rate Court

Either side may open a rate dispute against an `ACTIVE` license: the licensee acting on its own license, or the licensing admin acting for the PRO. The opening payload names the `opened_by_role` (`LICENSEE` or `PRO`) and the `disputed_fee_cents` the initiating party asserts is correct. Opening creates a `RateDispute` in `OPEN` status with `negotiation_rounds` at zero and `settled_fee_cents` null, and moves the license from `ACTIVE` to `DISPUTED`. Only one live dispute may exist per license — a second opening while an `OPEN`, `NEGOTIATION`, or `RATE_COURT` dispute exists is rejected with `ERR_DISPUTE_ALREADY_OPEN`, and this duplicate check is evaluated before the license-state check, so opening against a non-`ACTIVE` license that already carries a live dispute yields `ERR_DISPUTE_ALREADY_OPEN` rather than `ERR_INVALID_STATE`. The `opened_by_role` must be coherent with the caller: a `Licensee` caller must open a `LICENSEE` dispute and a `ProLicensingAdmin` caller must open a `PRO` dispute — a mismatch is rejected with `ERR_FORBIDDEN`. The dispute also records a `last_offer_cents` field, initialized to the `disputed_fee_cents`, that tracks the most recent fee offer on the table.

Negotiation is a cyclic loop. The licensing admin opens the first round by moving the dispute from `OPEN` to `NEGOTIATION`, incrementing `negotiation_rounds`; this opening move may carry an optional `counter_fee_cents`, which when present replaces the dispute's standing offer but carries no differ-from-last constraint. A licensee attempting the opening move from `OPEN` is rejected with `ERR_INVALID_STATE`. Thereafter, either the admin or the licensee may advance further rounds from `NEGOTIATION` with a `counter_fee_cents` payload that must differ from the last offered fee — an identical counter-offer is rejected with `ERR_VALIDATION` — and each such round increments `negotiation_rounds` again and updates the standing offer. When the parties converge, the admin settles the dispute from `NEGOTIATION` by presenting the `agreed_fee_cents`, which must be non-negative. Settlement records the figure in `settled_fee_cents`, moves the dispute to `SETTLED`, returns the license from `DISPUTED` to `ACTIVE`, and — when the agreed figure differs from the licensee's current `blanket_fee_cents` — sets the licensee's `blanket_fee_cents` to the agreed figure. The license's pinned `fee_basis_cents` does not change; retroactive deltas from a lower settled fee are handled through the distribution machinery rather than by mutating the license.

A dispute stuck in `OPEN` or `NEGOTIATION` may be escalated to the rate court by the licensee, provided no non-`DISMISSED` rate court case already exists for the dispute — a duplicate escalation is rejected with `ERR_RATE_COURT_CASE_EXISTS`. Escalation creates a `RateCourtCase` in `FILED` status and moves the dispute to `RATE_COURT`. A `RateCourtOfficer` then drives the case: opening a hearing moves it `FILED` to `HEARING`; deciding the case from `HEARING` requires a non-negative `adjudicated_fee_cents` payload, moves the case to the terminal `DECIDED` status, stamps the figure onto the case, moves the dispute from `RATE_COURT` to `SETTLED` with `settled_fee_cents` equal to the adjudicated figure, returns the license to `ACTIVE` (or leaves it `EXPIRED` if the clock already passed expiry, with retro handled through adjustments), and sets the licensee's `blanket_fee_cents` to the adjudicated figure. Dismissing a case while it is `FILED` sends the dispute back to `NEGOTIATION` and increments `negotiation_rounds` — the negotiation loop can thus cycle through the court more than once across separate cases, though never with two live cases at once.

A licensee that opened a dispute may withdraw it from `OPEN` or `NEGOTIATION`, moving the dispute to `WITHDRAWN` and the license back to `ACTIVE`. Withdrawal is available only when the dispute's `opened_by_role` is `LICENSEE` and the caller is the licensee that owns the license; attempts to withdraw a PRO-opened dispute, or by a non-owning licensee, are rejected with `ERR_DISPUTE_NOT_WITHDRAWABLE`. Disputes and rate court cases are listable per license or per dispute, and a system-wide dispute list supports `license_id` and `status` filters.

### 3.7. Performance Ingestion, Sampling, and Credit Weighting

Royalty collection begins with performance data. A `RoyaltyDistributor` ingests a single performance event by naming the `work_id` performed, the `license_id` covering it, the `performance_date`, the carriage `medium` (one of `TERRESTRIAL_RADIO`, `NETWORK_TV`, `CABLE_TV`, `DIGITAL_STREAMING`, `LIVE_VENUE`), the `daypart` bucket (`PRIME`, `DAY`, `LATE_NIGHT`, or `OVERNIGHT`), the reporting `source` (`MONITORING`, `CUE_SHEET`, `DIGITAL_REPORT`, or `SAMPLE`), the reported `play_count` of at least 1, and — when the source is `SAMPLE` — the `frame_units_reported` describing how many sampling frame units the report covers.

Ingestion guards the ledger with three referential checks. The referenced work must be `CONFIRMED`; ingestion against any other work status is rejected with `ERR_WORK_NOT_CONFIRMED`. The referenced license must be `ACTIVE` or `DISPUTED` — performances continue to accrue during a good-faith dispute — while `SUSPENDED`, `EXPIRED`, or `TERMINATED` licenses reject ingestion with `ERR_LICENSE_SUSPENDED`. The `performance_date` must fall within the referenced license's covered window from `effective_date` through `expiry_date` inclusive; a date outside the window is rejected with `ERR_PERFORMANCE_OUTSIDE_LICENSE_WINDOW`. When several of these checks fail on one request, the deterministic outcome is fixed: the license status check is evaluated first (`ERR_LICENSE_SUSPENDED`), then the covered-window check (`ERR_PERFORMANCE_OUTSIDE_LICENSE_WINDOW`), and the work-confirmation check (`ERR_WORK_NOT_CONFIRMED`) last. When the source is `SAMPLE`, a missing, non-integer, or sub-1 `frame_units_reported` is rejected with `ERR_VALIDATION`; for census sources the field is optional and is stored as given (or null). Valid events are born `ACCEPTED` with `cycle_id` null and `rejection_error_id` null.

Two computations run at ingest. The first converts the reported plays into `universe_estimated_plays`. For the census sources — `MONITORING`, `CUE_SHEET`, and `DIGITAL_REPORT` — the universe equals the reported `play_count` exactly. For a `SAMPLE` row, the system expands the sample to a universe estimate: the reported count is multiplied by 52 (the number of sampling frame units in a full frame) divided by `frame_units_reported`, rounded to the nearest integer with round-half-up, and the result is floored at the reported `play_count` itself so a projection never falls below what was actually observed.

The second computation assigns `credit_units`, the weight the event will carry in royalty allocation. Each medium carries a factor — 1.0 for `TERRESTRIAL_RADIO`, 2.5 for `NETWORK_TV`, 1.5 for `CABLE_TV`, 0.6 for `DIGITAL_STREAMING`, and 1.2 for `LIVE_VENUE` — and each daypart carries its own: 2.0 for `PRIME`, 1.0 for `DAY`, 0.7 for `LATE_NIGHT`, and 0.4 for `OVERNIGHT`. The product of the two factors forms the event's base weight. A feature bonus then recognizes densely-written works: when the performed work has more than two `ACCEPTED` writer claims, the base is multiplied by 1.1 before being scaled by the universe. The final `credit_units` is the base times the `universe_estimated_plays`, rounded half-up to four decimal places, and that per-event rounded value is what cycle-level summations later add together.

Bulk ingestion accepts a list of `events`, each carrying the same fields as a single ingest, and processes rows independently: valid rows are accepted with their computed fields, while rows failing validation are persisted directly in the terminal `REJECTED` status with the failing error's identifier recorded in `rejection_error_id` (for example `ERR_WORK_NOT_CONFIRMED`), never consuming credit. Every ingested event — accepted or rejected — stores both `universe_estimated_plays` (an integer) and `credit_units` (a number with up to four decimal places); a rejected row carries `universe_estimated_plays` 0 and `credit_units` 0.0, echoes back the request fields it was given (including nulls), and keeps `cycle_id` null. The bulk response itself is a `200 OK` array envelope listing every row in submission order, with the meta pagination fields carrying `limit` equal to the number of rows returned, `offset` 0, and `total_count` equal to the row count. A distributor may void an `ACCEPTED` event while it is still free (`cycle_id` null) or while the cycle holding it is still `COLLECTING`; a voided event moves to `VOIDED`, and if it had been captured into a cycle, the cycle's captured credit total is recomputed at the next calculation entry. Performance lists support filters on `work_id`, `license_id`, `cycle_id`, `status`, and `medium`, with per-work and per-license list views as well.

### 3.8. Distribution Cycles: Pool Formation and Allocation

Royalty distribution proceeds in cycles. A `RoyaltyDistributor` creates a `DistributionCycle` with a human `label` (unique across cycles — a duplicate label is rejected with `ERR_VALIDATION` — e.g. a quarter tag), a `period_start`, and a `period_end` no earlier than the start (a `period_start` later than the `period_end` is rejected with `ERR_VALIDATION`); the cycle begins in `DRAFT` with `version_epoch` at zero, `claims_open_until` null, and `pool_amount_cents` unset. Opening the cycle — permitted from `DRAFT` once `period_start` is no later than `period_end` — moves it to `COLLECTING` and creates the cycle's `UnclaimedRoyaltyPool` with a zero balance in `OPEN` status if one does not already exist; exactly one pool row ever exists per cycle.

While the cycle collects, the distributor captures free `ACCEPTED` performance events into it by listing their `performance_event_ids`; capture requires each listed event to exist (else `ERR_REFERENCE_NOT_FOUND`), to be `ACCEPTED` (else `ERR_INVALID_STATE`), to be free or already captured into this same cycle (an event captured into another cycle is rejected with `ERR_INVALID_STATE`), and to have a `performance_date` within the cycle's period from `period_start` through `period_end` inclusive (a date outside the period is rejected with `ERR_VALIDATION`). Capture sets each event's `cycle_id` to the cycle and bumps the cycle's `version` whenever at least one event was listed. Closing collection requires at least one `ACCEPTED` event captured in the cycle — an empty close is rejected with `ERR_CYCLE_NO_PERFORMANCES` — and requires `expected_cycle_version` matching the cycle's current `version`, because a prior close legitimately re-ran the allocation and bumped the epoch, making any earlier pool assumptions stale; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). A successful close moves the cycle to `CALCULATING`, increments `version_epoch` by 1, and runs two calculations back to back.

The pool calculation determines `pool_amount_cents`, the distributable money. Every license whose covered window from `effective_date` through `expiry_date` intersects the cycle's period — meaning the effective date falls on or before `period_end` and the expiry date falls on or after `period_start` — and whose status is anything other than `TERMINATED` contributes its pinned `fee_basis_cents`, prorated: the license contributes its basis multiplied by the number of covered days in the intersection (counting both endpoints of the overlap inclusively) divided by 365, with the per-license result truncated to an integer before any summing. The truncated per-license amounts are summed into a gross pool, the administration deduct of 15 percent is removed, and the remainder is rounded half-up once to whole cents. The evaluation order is pinned — prorate each license, truncate each license, sum, apply the administration rate, round once.

The allocation calculation then converts captured performances into per-affiliate gross amounts. The cycle's total credit units are the sum of `credit_units` over `ACCEPTED` events captured into it, and the unit value is the pool divided by that total, held as an exact rational. Each work's value is the sum of its events' credit units times the unit value, and each affiliate's share of that work is the work value multiplied by the claim's `collection_share_bps` over 10000, taken across the work's `ACCEPTED` claims. Each affiliate's per-work amount is rounded half-up to cents; a work with no `ACCEPTED` claim instead has its whole work value rounded half-up to cents and credited to the pool; and the cycle-level rounding residue — the pool minus the sum of all rounded amounts, including the rounded no-claim pool credits — is reconciled cent by cent: a positive residue is awarded one cent at a time to statements ordered by rounded amount descending and then by the affiliate's `created_at` ascending, with remaining ties broken by the affiliate's `id` ascending, and a negative residue is clawed back one cent at a time from statements in that same order — walking the ordering cyclically, so a residue larger than the statement count wraps around to the largest statement again — so the largest statements absorb rounding drift in both directions. Allocation creates a `RoyaltyStatement` in `DRAFT` for each affiliate under the new epoch, recording the cycle's `version_epoch` in the statement's `epoch`; statements of earlier epochs are superseded.

Two routings divert money from affiliates. An affiliate whose `status` is not `ACTIVE` still has a statement created recording its gross, but the entire gross is recorded as `unclaimed_amount_cents` and the same cents credit the cycle's unclaimed pool rather than the affiliate; a claim whose affiliate record no longer exists is treated the same way, its gross routed to the pool as unclaimed. A work with no `ACCEPTED` claim at all has its entire work value routed directly to the pool with no statement created. Both routings credit the pool immediately at calculation time, when the allocation runs — not at distribution. The administration fee never touches the unclaimed portion: pool credits are gross cents, and each statement's `admin_fee_cents` is computed only on the payable remainder.

The per-statement administration fee is 5 percent of the payable amount — the `gross_amount_cents` minus the `unclaimed_amount_cents` — rounded half-up to whole cents, and capped so the fee never exceeds the payable amount itself; a statement whose payable amount is zero carries a zero fee. The statement's `net_amount_cents` is its gross minus the administration fee, with the unclaimed cents remaining part of net on the statement but crediting the pool rather than the affiliate at distribution time. The ledger credit the affiliate ultimately receives is the net minus the unclaimed amount.

### 3.9. Statement Finalization, Distribution, and Adjustments

A cycle in `CALCULATING` holds its freshly computed statements in `DRAFT`. The distributor finalizes each statement individually — permitted only while the owning cycle is `CALCULATING` and only for statements whose `epoch` equals the cycle's current `version_epoch` — moving it to `FINALIZED`. When every statement of the current epoch is `FINALIZED`, the distributor distributes the cycle; attempting distribution while any current-epoch statement remains `DRAFT` is rejected with `ERR_STATEMENTS_NOT_FINALIZED`. Distribution moves the cycle to `DISTRIBUTED`, moves every `FINALIZED` statement to `PAID`, credits each affiliate's `royalty_balance_cents` and `total_paid_cents` by the statement's net minus its unclaimed amount, and sets the cycle's `claims_open_until` to 90 days after `period_end` if not already set — the window during which late claims remain valid.

Corrections after distribution travel through royalty adjustments. A distributor, finance officer, publisher, or songwriter may file an adjustment against a statement by supplying a signed `delta_cents` (negative claws money back), a `reason` of `LATE_CLAIM`, `AUDIT_FINDING`, `RATE_COURT_RETRO`, or `DATA_CORRECTION`, and — when and only when the reason is `AUDIT_FINDING` — the `audit_id` of the audit that produced the finding; the `audit_id` rule is enforced as field-shape validation — supplying `audit_id` under any other reason, or omitting it under `AUDIT_FINDING`, is rejected with `ERR_VALIDATION` before the affiliate filing restrictions are examined, and under `AUDIT_FINDING` a nonexistent `audit_id` is rejected with `ERR_REFERENCE_NOT_FOUND`. Publishers and songwriters may file only against their own statements and only for `LATE_CLAIM` — violations are rejected with `ERR_FORBIDDEN` — and a `LATE_CLAIM` filing is checked against the claims window at filing time, not only at approval: a filing after the cycle's `claims_open_until` has passed is rejected with `ERR_CLAIMS_WINDOW_CLOSED`. The adjustment records the statement's `affiliate_id` and the filing user's `created_by_user_id`, starts in `PENDING`, and is thereafter governed by segregation of duties: the `FinanceOfficer` who approves or rejects must not be the same user who created it, and a violation is rejected with `ERR_SEGREGATION_OF_DUTIES`.

Approval rules differ by reason. A `LATE_CLAIM` adjustment pays out of the cycle's unclaimed pool, and approval requires the clock date to be on or before the cycle's `claims_open_until` — the claim is still valid on the final day — and the claimed amount to be no greater than the pool's current `balance_cents`. The full-coverage rule forbids partial approvals: a claim exceeding the pool balance is rejected with `ERR_UNCLAIMED_POOL_INSUFFICIENT`, and the claimant must re-file for the available amount. A late claim filed or approved after the window has closed is rejected outright with `ERR_CLAIMS_WINDOW_CLOSED`, at which point escheatment may claim the pool instead. The claims-window check applies only to `LATE_CLAIM` adjustments; adjustments of the other reasons may be filed and approved at any time. Rejection moves a `PENDING` adjustment to `REJECTED`; approval moves it to `APPROVED`.

Application is a separate act. Applying an `APPROVED` adjustment moves it to the terminal `APPLIED`, adds the `delta_cents` to the affiliate's `royalty_balance_cents`, and — for a positive `LATE_CLAIM` delta — debits the same cents from the cycle's unclaimed pool (which must still exist; the pool's balance is not re-validated at apply time). The adjusted statement moves to `ADJUSTED`, and the first applied adjustment against any statement of a `DISTRIBUTED` cycle moves the cycle itself to `ADJUSTED`, where subsequent applied adjustments keep it; applied adjustments against statements of cycles in other statuses leave the cycle's status unchanged. Adjustments can be listed per statement or system-wide filtered by `affiliate_id`, `audit_id`, `status`, or `reason`.

### 3.10. Licensee Audits

A `FinanceOfficer` may open an audit against a licensee by supplying the `scope_period_start` and `scope_period_end` bounding the examination, with the start no later than the end (a reversed scope is rejected with `ERR_VALIDATION`). The scope may not reach further back than 1095 days before the current clock date — an end date beyond that horizon is rejected with `ERR_AUDIT_SCOPE_TOO_OLD`, while an end date exactly on the horizon is accepted. The audit opens in `OPEN` status with `findings_delta_cents` at zero. Filing findings moves it to `FINDINGS_FILED` and stamps the officer-asserted signed aggregate — a positive figure meaning the licensee underpaid — into `findings_delta_cents`. Closing is gated on state: the audit must be `FINDINGS_FILED` to close, and closing from any other status is rejected with `ERR_INVALID_STATE`.

Closing is gated on remedy: if the findings are positive, a royalty adjustment with reason `AUDIT_FINDING` referencing the underpayment must already exist in some status other than `REJECTED`; closing without one is rejected with `ERR_AUDIT_CLOSE_REQUIRES_ADJUSTMENT`. The monetary remedy always travels through that adjustment — audits never mutate statements in place. When the filed `findings_delta_cents` is strictly greater than 1,000,000 cents, closing the audit flips the licensee's `credit_standing` to `DELINQUENT`; a figure exactly equal to the threshold does not flip it. Audits are listable per licensee with a `status` filter.

### 3.11. Unclaimed Pools and Escheatment

Every cycle's unclaimed pool holds money that found no payee: the gross cents of statements whose affiliate was not `ACTIVE`, the whole value of works with no accepted claim, and any unclaimed remainders. The pool's `balance_cents` grows with distribution routing and shrinks with successful late claims and escheatment. While the pool is `OPEN` — or later `PARTIALLY_ESCHEATED`, whose funds remain escheatable under the same rule; an `ESCHEATED` pool rejects further escheatment with `ERR_INVALID_STATE` — a `FinanceOfficer` may escheat funds only after the claims window plus a 30-day grace period — the clock date must be strictly later than `claims_open_until` plus those 30 days, and on the exact grace-final day the pool is not yet escheatable; a premature request (including one against a cycle whose claims window was never set) is rejected with `ERR_ESCHEAT_NOT_YET_DUE`, and that due-date check is evaluated before the amount is examined. Each escheatment names an `amount_cents` that must be positive and no greater than the current balance, else it is rejected with `ERR_ESCHEAT_AMOUNT_INVALID`. A partial escheat reduces the balance (never below zero) and moves the pool from `OPEN` to `PARTIALLY_ESCHEATED`; an escheat whose amount equals the full remaining balance zeroes the pool and moves it to the terminal `ESCHEATED`, whether from `OPEN` or `PARTIALLY_ESCHEATED`. Pools are listable filtered by `cycle_id` or `status`.

## 4. Endpoint Definitions

Operations that create new, stand-alone resources return a `201 Created` status code. Operations that modify an existing resource — state transitions, updates, captures, sweeps — return a `200 OK` status code. All endpoints are mounted under `/pro`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/pro/_clock/set_current_utc` | Set the server logical clock; triggers license expiry sweep | ProSystemAdmin |
| POST | `/pro/affiliates` | Affiliate a songwriter or publisher | ProRegistrar |
| GET | `/pro/affiliates` | List affiliates with pagination and filters | ProRegistrar, ProLicensingAdmin, RoyaltyDistributor, FinanceOfficer, RateCourtOfficer |
| GET | `/pro/affiliates/{id}` | Fetch one affiliate including computed balances | ProRegistrar, RoyaltyDistributor, FinanceOfficer, Publisher, Songwriter |
| PATCH | `/pro/affiliates/{id}` | Update affiliate status or legal name | ProRegistrar |
| POST | `/pro/works` | Register a musical work | Publisher |
| GET | `/pro/works` | List works; filter by status or registering affiliate | ProRegistrar, RoyaltyDistributor, Publisher, Songwriter |
| GET | `/pro/works/{id}` | Fetch one work including aggregate interest | ProRegistrar, RoyaltyDistributor, Publisher, Songwriter |
| POST | `/pro/works/{id}/confirm` | Confirm a REGISTERED work whose shares are clean | ProRegistrar |
| POST | `/pro/works/{id}/withdraw` | Withdraw a work (registering publisher only, no accepted performances) | Publisher |
| POST | `/pro/works/{id}/resolve-conflict` | Resolve an over-claim conflict by accepting/revoking disputed claims (OCC on work version) | ProRegistrar |
| POST | `/pro/works/{id}/share-claims` | Assert a share claim on a work | Publisher, Songwriter |
| GET | `/pro/works/{id}/share-claims` | List share claims of a work | ProRegistrar, RoyaltyDistributor, Publisher, Songwriter |
| GET | `/pro/share-claims` | Filtered list of share claims across works | ProRegistrar, RoyaltyDistributor |
| GET | `/pro/affiliates/{id}/share-claims` | List share claims asserted by an affiliate | ProRegistrar, RoyaltyDistributor, Publisher, Songwriter |
| POST | `/pro/share-claims/{id}/revoke` | Revoke an own claim | Publisher, Songwriter |
| POST | `/pro/share-claims/{id}/dispute` | Challenge an accepted claim on a work where the caller holds a claim | Publisher, Songwriter |
| POST | `/pro/licensees` | Onboard a licensee; computes the blanket fee | ProLicensingAdmin |
| GET | `/pro/licensees` | List licensees; filter by `category` or `credit_standing` | ProLicensingAdmin, FinanceOfficer, RateCourtOfficer, Licensee |
| GET | `/pro/licensees/{id}` | Fetch one licensee including the computed blanket fee | ProLicensingAdmin, FinanceOfficer, Licensee |
| PATCH | `/pro/licensees/{id}` | Update reported revenue or usage; recomputes the blanket fee | ProLicensingAdmin, Licensee |
| POST | `/pro/licensees/{id}/licenses` | Issue a blanket license (OCC on licensee version); pins the fee basis | ProLicensingAdmin |
| GET | `/pro/licensees/{id}/licenses` | List licenses of a licensee | ProLicensingAdmin, FinanceOfficer, Licensee |
| GET | `/pro/licenses` | Filtered list of licenses | ProLicensingAdmin, RoyaltyDistributor, FinanceOfficer |
| GET | `/pro/licenses/{id}` | Fetch one license | ProLicensingAdmin, FinanceOfficer, Licensee |
| POST | `/pro/licenses/{id}/suspend` | Suspend a license (requires delinquent licensee) | ProLicensingAdmin |
| POST | `/pro/licenses/{id}/reinstate` | Reinstate a suspended license (requires good standing) | ProLicensingAdmin |
| POST | `/pro/licenses/{id}/terminate` | Terminate a license | ProLicensingAdmin |
| POST | `/pro/licenses/{id}/disputes` | Open a rate dispute on an active license | Licensee, ProLicensingAdmin |
| GET | `/pro/licenses/{id}/disputes` | List disputes of a license | ProLicensingAdmin, RateCourtOfficer, Licensee |
| GET | `/pro/disputes` | Filtered list of disputes | ProLicensingAdmin, RateCourtOfficer, FinanceOfficer |
| GET | `/pro/disputes/{id}` | Fetch one dispute | ProLicensingAdmin, RateCourtOfficer, Licensee |
| POST | `/pro/disputes/{id}/negotiate` | Advance a negotiation round with a counter-offer | ProLicensingAdmin, Licensee |
| POST | `/pro/disputes/{id}/settle` | Settle a dispute in negotiation at an agreed fee | ProLicensingAdmin |
| POST | `/pro/disputes/{id}/escalate` | Escalate to rate court; creates a filed case | Licensee |
| POST | `/pro/disputes/{id}/withdraw` | Withdraw a licensee-opened dispute | Licensee |
| GET | `/pro/disputes/{id}/rate-court-cases` | List rate court cases of a dispute | ProLicensingAdmin, RateCourtOfficer, Licensee |
| POST | `/pro/rate-court-cases/{id}/open-hearing` | Move a filed case to hearing | RateCourtOfficer |
| POST | `/pro/rate-court-cases/{id}/decide` | Adjudicate a fee; settles the dispute and overrides the blanket fee | RateCourtOfficer |
| POST | `/pro/rate-court-cases/{id}/dismiss` | Dismiss a filed case; dispute returns to negotiation | RateCourtOfficer |
| POST | `/pro/performances` | Ingest a single performance event | RoyaltyDistributor |
| POST | `/pro/performances/bulk` | Bulk ingest with per-row success or rejected-row persistence | RoyaltyDistributor |
| GET | `/pro/performances` | Filtered list of performance events | RoyaltyDistributor, FinanceOfficer, ProLicensingAdmin |
| GET | `/pro/works/{id}/performances` | List performances of a work | RoyaltyDistributor, Publisher, Songwriter |
| GET | `/pro/licenses/{id}/performances` | List performances under a license | RoyaltyDistributor, Licensee, ProLicensingAdmin |
| POST | `/pro/performances/{id}/void` | Void an accepted performance not locked by a calculating cycle | RoyaltyDistributor |
| POST | `/pro/cycles/{id}/performances/capture` | Capture accepted performances into a collecting cycle | RoyaltyDistributor |
| GET | `/pro/cycles/{id}/performances` | List performances captured into a cycle | RoyaltyDistributor, FinanceOfficer |
| GET | `/pro/adjustments` | Filtered list of adjustments across statements | RoyaltyDistributor, FinanceOfficer |
| GET | `/pro/pools` | Filtered list of unclaimed royalty pools | FinanceOfficer, RoyaltyDistributor |
| POST | `/pro/cycles` | Create a distribution cycle | RoyaltyDistributor |
| GET | `/pro/cycles` | List distribution cycles | RoyaltyDistributor, FinanceOfficer, ProLicensingAdmin |
| GET | `/pro/cycles/{id}` | Fetch one cycle including pool amount and epoch | RoyaltyDistributor, FinanceOfficer |
| POST | `/pro/cycles/{id}/open` | Open a cycle for collection; creates its unclaimed pool | RoyaltyDistributor |
| POST | `/pro/cycles/{id}/close-collection` | Close collection and run pool and allocation (OCC on cycle version) | RoyaltyDistributor |
| POST | `/pro/cycles/{id}/distribute` | Distribute a fully-finalized cycle; pays statements to affiliate ledgers | RoyaltyDistributor |
| GET | `/pro/cycles/{id}/statements` | List statements of a cycle; filter by `status`, `epoch`, or `affiliate_id` | RoyaltyDistributor, FinanceOfficer |
| GET | `/pro/cycles/{id}/pool` | Fetch the cycle's unclaimed royalty pool | RoyaltyDistributor, FinanceOfficer |
| GET | `/pro/statements` | Filtered list of statements | RoyaltyDistributor, FinanceOfficer |
| GET | `/pro/affiliates/{id}/statements` | List statements payable to an affiliate | RoyaltyDistributor, FinanceOfficer, Publisher, Songwriter |
| GET | `/pro/statements/{id}` | Fetch one statement | RoyaltyDistributor, FinanceOfficer |
| POST | `/pro/statements/{id}/finalize` | Finalize a draft statement of the current epoch | RoyaltyDistributor |
| POST | `/pro/statements/{id}/adjustments` | File an adjustment (late claim, audit finding, rate-court retro, data correction) | RoyaltyDistributor, FinanceOfficer, Publisher, Songwriter |
| GET | `/pro/statements/{id}/adjustments` | List adjustments of a statement | RoyaltyDistributor, FinanceOfficer |
| GET | `/pro/adjustments/{id}` | Fetch one adjustment | RoyaltyDistributor, FinanceOfficer |
| POST | `/pro/adjustments/{id}/approve` | Approve an adjustment (approver differs from creator) | FinanceOfficer |
| POST | `/pro/adjustments/{id}/reject` | Reject an adjustment (segregation of duties) | FinanceOfficer |
| POST | `/pro/adjustments/{id}/apply` | Apply an approved adjustment to the affiliate ledger and pool | FinanceOfficer |
| POST | `/pro/licensees/{id}/audits` | Open an audit against a licensee | FinanceOfficer |
| GET | `/pro/licensees/{id}/audits` | List audits of a licensee | FinanceOfficer, ProLicensingAdmin, Licensee |
| GET | `/pro/audits/{id}` | Fetch one audit | FinanceOfficer |
| POST | `/pro/audits/{id}/file-findings` | File audit findings with an aggregate signed delta | FinanceOfficer |
| POST | `/pro/audits/{id}/close` | Close an audit; flips licensee standing when findings exceed threshold | FinanceOfficer |
| GET | `/pro/pools/{id}` | Fetch an unclaimed royalty pool | FinanceOfficer, RoyaltyDistributor |
| POST | `/pro/pools/{id}/escheat` | Escheat unclaimed funds after the claims window and grace period | FinanceOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_REFERENCE_NOT_FOUND` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_VALIDATION` | 400 |
| `ERR_INVALID_SHARE` | 422 |
| `ERR_WORK_SHARES_INCOMPLETE` | 422 |
| `ERR_CONFLICT_RESOLUTION_INVALID` | 422 |
| `ERR_WORK_NOT_CONFIRMED` | 422 |
| `ERR_WORK_HAS_PERFORMANCES` | 422 |
| `ERR_CLAIM_LOCKED_BY_DISTRIBUTION` | 422 |
| `ERR_LICENSEE_DELINQUENT` | 422 |
| `ERR_LICENSE_SUSPENDED` | 422 |
| `ERR_PERFORMANCE_OUTSIDE_LICENSE_WINDOW` | 422 |
| `ERR_DISPUTE_ALREADY_OPEN` | 409 |
| `ERR_RATE_COURT_CASE_EXISTS` | 409 |
| `ERR_DISPUTE_NOT_WITHDRAWABLE` | 422 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_CLAIMS_WINDOW_CLOSED` | 422 |
| `ERR_UNCLAIMED_POOL_INSUFFICIENT` | 422 |
| `ERR_ESCHEAT_NOT_YET_DUE` | 422 |
| `ERR_ESCHEAT_AMOUNT_INVALID` | 422 |
| `ERR_AUDIT_SCOPE_TOO_OLD` | 422 |
| `ERR_AUDIT_CLOSE_REQUIRES_ADJUSTMENT` | 422 |
| `ERR_STATEMENTS_NOT_FINALIZED` | 422 |
| `ERR_CYCLE_NO_PERFORMANCES` | 422 |
