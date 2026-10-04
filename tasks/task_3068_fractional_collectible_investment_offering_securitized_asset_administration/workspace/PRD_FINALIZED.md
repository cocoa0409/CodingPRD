# Fractional Collectible Securitization API — Product Requirements Document

## 1. Introduction

Blue-chip artwork has historically been the least accessible asset class in the world: a single canvas can trade for more than the entire annual operating budget of the institution that wants to own it, it cannot be divided, it cannot be moved cheaply, and it generates no cash flow until the day it is sold. This platform removes the indivisibility. The operator acquires a work, subjects it to authentication and provenance diligence, files a securities circular that qualifies a fixed share count for public subscription, sells those shares to screened investors, warehouses the physical object in a bonded vault under an insurance policy, and eventually sells the object and distributes the proceeds to the people who held shares at the moment of sale.

The product is therefore as much a compliance instrument as a marketplace. Every action that moves money or moves ownership must be attributable to a named officer, and the approval chain deliberately separates the officer who proposes a sale from the officer who may overturn it, and separates the issuer's desk from the independent transfer agent that settles secondary share movements. Investors must pass an eligibility screen — age, residency, and jurisdiction — before their money is accepted, and must clear a further accredited-investor threshold when a particular offering is structured under the exemption that requires it.

Technically, the service is a single REST API mounted under `/api`. It is a compliance-and-audit system at its core, with a quota-allocation secondary character: registrations are capped per investor, share allotment is ranked, waitlists are dense and ordered, and almost every temporal decision — a qualification deadline, a rescission window, an appraisal cadence, a holding period — is evaluated against a logical clock rather than wall time. The sections that follow fix the response contract, the access-control model, the concurrency guarantees, and then narrate the business lifecycle from acquisition through distribution.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request other than the single public onboarding surface must carry both `X-User-ID` and `X-User-Role`. A request that arrives without either header, or with a blank value for either, is refused with `ERR_UNAUTHENTICATED` and HTTP 401. The platform recognises seven operational identities: `Anonymous`, `Investor`, `IssuerOps`, `ComplianceOfficer`, `TransferAgent`, `PlatformAdmin`, and `System`.

When `X-User-Role` is `Investor`, `X-User-ID` is the `id` of the acting `Investor` row itself. Ownership checks on any resource that references an `Investor` therefore compare the resource's foreign-key field — `investor_id` on a subscription, `seller_id` or `buyer_id` on a transfer order — against the value supplied in `X-User-ID`. An investor acting on a subscription or transfer order it does not own is refused.

For every other role the identity is opaque. When `X-User-Role` is `Anonymous`, `IssuerOps`, `ComplianceOfficer`, `TransferAgent`, `PlatformAdmin`, or `System`, `X-User-ID` is an operator identifier that is not tied to any persisted entity. The server records it where a workflow requires attribution — for example as `created_by_user_id` on a holding decision or a transfer order, and as `approved_by_user_id` once that decision is approved — but never compares it to any entity's `id`. The recorded values exist solely to enforce the segregation-of-duties rules described later.

`Anonymous` is the unauthenticated caller and exists for exactly one purpose: registering an investor account. `IssuerOps` is the issuer's operations desk — acquisition, asset reports, appraisals, offering creation, custody administration, insurance, cost lots, fee accrual, and the propose step of the sale decision chain. `ComplianceOfficer` owns investor protection: screening, suitability revocation, qualification filing, allocation, waitlist movement, offering abandonment and withdrawal, and the overturn step of the sale decision chain. `TransferAgent` is the independent party that settles secondary share movements and may do nothing else. `PlatformAdmin` configures the segregated cash account and the logical clock and may invoke reconciliation for any offering, but may not screen investors, allocate shares, or settle transfers. `System` is the server-side actor for automatic transitions that no HTTP caller triggers directly — allocation-pass expirations, transfer-order lapse, holding-clock restamping, and cascade propagation.

Two distinct refusals apply here. Absent or blank credentials produce `ERR_UNAUTHENTICATED` (HTTP 401). A well-formed request whose acting role is not permitted for the operation produces `ERR_UNAUTHORIZED` (HTTP 403), and that permission failure is reported before any business check is evaluated.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC instant, written in the same form as every other timestamp the server emits (§2.5): sub-second precision is preserved when present, while an instant that lands exactly on a whole second — which is every instant the held logical clock yields — is written without a fractional part (`2026-09-01T00:00:00Z`).
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

List endpoints accept two query parameters. `limit` caps the number of items returned; it defaults to 10, must be at least 1, and must not exceed 100. `offset` states how many items to skip before the first returned item and defaults to 0. The paginated `meta` block carries `limit`, `offset`, `total_count`, and `has_more`.

Unless a description states otherwise, list endpoints return resources ordered by creation timestamp ascending. Where two rows share a creation timestamp — which is common because the logical clock can be held still across many writes — the server's monotone creation sequence (`created_at_seq` on subscriptions, or the raw insertion order for other rows) breaks the tie, so list output is stable across repeated reads.

### 2.4. Request Evaluation Order and Refusal Discipline

The server evaluates a request against a fixed, ordered catalogue of checks. When more than one check would fail on the same request the earliest failing check wins, and the request is refused with that check's error identifier; no later check is evaluated and no state is written. The order is:

1. Credential presence — both `X-User-ID` and `X-User-Role` supplied and non-blank. Failure: `ERR_UNAUTHENTICATED`.
2. Role permission — the acting role is permitted for the operation and, where the operation is owner-scoped, the acting identity owns the resource. Failure: `ERR_UNAUTHORIZED`. This check precedes every business check.
3. Investor eligibility screening, in its own internal order: the jurisdiction override first, then the age test, then the non-US residence rule. The screen is described in §2.8. Failure: `ERR_INVESTOR_INELIGIBLE`.
4. Existence — every path identifier and every body identifier resolves to a stored row of the expected entity type. Failure: `ERR_NOT_FOUND`. Body references are resolved left to right in the order the endpoint's declared input list presents them.
5. Jurisdiction override — an investor who is both a US citizen and a US resident and who is therefore refused service in this market. Failure: `ERR_OFFERING_NOT_AVAILABLE_IN_JURISDICTION`.
6. Declared state — the target resource sits in a state from which the requested operation is a declared transition. Failure: `ERR_INVALID_STATE`.
7. Optimistic concurrency — where the operation declares an expected parent version, the supplied value equals the parent's stored version. Failure: `ERR_STALE_VERSION`.
8. Qualification window — allocation and waitlist promotion must occur no later than the offering's qualification deadline. Failure: `ERR_QUALIFICATION_LAPSED`.
9. Minimum subscription — an offering must carry at least one accepted share before it may be allocated. Failure: `ERR_MINIMUM_NOT_MET`.
10. Registration cap — no investor's holding may exceed the offering's per-investor cap. Failure: `ERR_OFFERING_FULL`.
11. Coverage sufficiency — an insurance policy's sum insured must be at least the artwork's current selected appraised value at binding. Failure: `ERR_INSUFFICIENT_COVERAGE`.
12. Accrual support — a profit-participation accrual requires a closed sale cycle against which to take a participating share. Failure: `ERR_ACCRUAL_TYPE_UNSUPPORTED`.
13. Cash conservation — no debit may take the platform account's balance below zero. Failure: `ERR_ACCOUNT_UNDERFUNDED`.
14. Holding-period gate — sale approval and secondary transfer approval are unlocked in disjoint clock states, as set out in §2.10 and §3.8. Failure: `ERR_HOLD_PERIOD_ACTIVE`.
15. Secondary lot floor — a posted secondary lot must be at least the liquidity ratio of the issue. Failure: `ERR_LIQUIDITY_WINDOW_LOCKED`.
16. Waitlist availability — promotion requires at least one waiting subscription. Failure: `ERR_WAITLIST_EMPTY`.
17. Appraisal cadence — a new selected appraisal must be at least 90 days after the previous selected one. Failure: `ERR_APPRAISAL_CADENCE`.
18. Appraisal recency on re-custody — a released custody record may only be re-opened over a fresh selected appraisal. Failure: `ERR_APPRAISAL_STALE`.
19. Report window — a filed report's `as_of_date` may neither precede the offering's latest report nor post-date the current clock. Failure: `ERR_REPORT_WINDOW_FORECLOSED`.
20. Sibling exclusivity and interval overlap among insurance policies and custody records, described in §2.9. Failure: `ERR_SOLE_POLICY_CANNOT_LAPSE`, `ERR_POLICY_INTERVAL_OVERLAP`, or `ERR_CUSTODY_INTERVAL_OVERLAP` as the case may be.
21. Enum membership — every enum-typed body field carries a declared member. Failure: `ERR_VALUE_REJECTED`.
22. Route existence — the requested path has a declared route. Failure: `ERR_ROUTE_NOT_FOUND`, raised before any resource lookup.
23. Method allowance — the declared route accepts the supplied method. Failure: `ERR_METHOD_NOT_ALLOWED`.

Two further refusals sit outside that ordering. A request whose required body field is missing, or whose numeric field falls outside its declared range, is refused with `ERR_INVALID_REQUEST` (HTTP 400) as soon as the payload is parsed. A cascade that would push a child resource into a state its own invariants forbid causes the originating transition to be refused wholesale with `ERR_CASCADE_REJECTED` (HTTP 409) and no partial write is applied — the parent rolls back with the child.

### 2.5. Registrable Resources, Common Fields and Hierarchical Retrieval

Every primary resource in the system — `Artist`, `Investor`, `Artwork`, `Offering`, `Subscription`, `CustodyRecord`, `HoldingDecision`, `TransferOrder`, `Lot`, `InsurancePolicy`, and `PlatformAccount` — carries a standard identity block. The `id` is a server-minted UUID with no type prefix: the value is a bare universally unique identifier, never a string such as `artwork_…` or `off_…`. The `created_at` is the instant the row was inserted, written as an ISO 8601 UTC instant: an instant that lands on a whole second — which is every instant the logical clock yields while it is held still — is written without a fractional part (`2026-09-01T00:00:00Z`), and sub-second precision is preserved when present. The `updated_at` is the instant of the most recent mutation of any property, in the same form. The `version` is a system-managed integer that begins at its initial value and increments by one on every mutation that touches the row; it is never client-settable. Every resource that moves through a lifecycle also carries a `status` field, whose permitted values are exactly the states of that resource's own state machine and nothing else.

Five child record types are append-mostly and are deliberately excluded from that block: `ArtworkAssetReport`, `Appraisal`, `OfferingReport`, `FeeAccrual`, and `Distribution` carry only `id` and `created_at`. They expose no `updated_at` and no `version` field at all. Their immutability is the reason: a filed report, an appraisal, an accrual, or a computed distribution row records the state of the world at one instant and is never edited afterwards, so a modification stamp would be meaningless.

Requests that address nested resources are resolved against the URL hierarchy strictly left to right. When a path carries more than one resource placeholder, the server confirms the existence of the leftmost identifier first and refuses the request with `ERR_NOT_FOUND` for the first identifier that does not resolve, before attempting any lookup further right and before evaluating any business rule. A request naming a child under a parent that does not exist therefore reports the parent's absence, never the child's.

### 2.6. Optimistic Concurrency Control

Three write operations are guarded by an explicit expected-parent-version check. In each case the request body must carry the named field as a required input; the field holds the parent entity's `version` as the client last observed it, and if that value no longer equals the parent's stored `version` the request is refused with `ERR_STALE_VERSION` and HTTP 412, and nothing is written.

- Re-receiving a previously released custody record requires `expected_offering_version`, matched against the target `Offering`'s current `version`. The revision loop legitimately re-stamps the holding clock, and any intervening allocation, waitlist promotion, or insurance binding has already advanced the offering's version, so a client that read the offering before those writes holds a stale value.
- Filing an appraisal requires `expected_artwork_version`, matched against the target `Artwork`'s current `version`. Every prior appraisal filing, custody transition, and asset-report component re-evaluates the artwork's `artifacts_overview` and therefore advances its version.
- Approving a secondary transfer requires `expected_offering_version`, matched against the target `Offering`'s current `version`. A prior transfer approval, waitlist promotion, or cost-lot accrual has already moved the offering.

These three are the operations whose stale-version rejection is a declared business rule. Several further write operations — qualification filing, allocation, waitlist promotion and demotion, offering withdrawal, holding-decision approval, rejection and execution, distribution payment, custody receipt and release — also declare an expected-version input field of the same form, and they are enumerated with their inputs in §4.

### 2.7. Monetary Precision, Flooring and the Segregated Cash Account

Every monetary quantity in the system is an integer count of cents. No endpoint accepts or returns floating-point money.

Rounding is asymmetric by design and the direction is pinned wherever it appears. Allocation clamps and every cost, fee, participation, and per-share derivation are floored to whole units — whole cents for money, whole shares for allotments — with integer division and no rounding up. The single exception is presentation: the management-fee accrual is displayed to a human using round-half-up to the cent while the amount that settles in cash is floored to the cent. The two figures are reported side by side so the difference is auditable rather than hidden.

Platform cash is conserved through a single ledger account, `PlatformAccount`. Its `balance_cents` is the running sum of every debit and credit applied to it, and every money-moving endpoint appends one balancing pair so that no debit is ever applied without its matching credit. `investor_funds_held_cents` is the subset of `balance_cents` that represents investor money segregated for the benefit of subscribers, and `total_paid_out_cents` is a monotone running total of everything ever disbursed from the account, which never decreases. A collection into the account credits `balance_cents` and increases `investor_funds_held_cents` by the same amount; when collected money is refunded, the same amount is drawn back out of both figures — each floored at zero — so the refunded money leaves the balance and the segregated subset together. No write may take `balance_cents` below zero; a write that would do so is refused with `ERR_ACCOUNT_UNDERFUNDED` and no partial debit is applied. A newly opened account starts with `balance_cents` at zero, `investor_funds_held_cents` at zero, and `total_paid_out_cents` at zero.

### 2.8. Investor Suitability and Jurisdictional Eligibility

An investor is admitted to the platform in the `PENDING` suitability state and reaches `APPROVED` only through a successful screen. Registration is public and requires no credentials; it writes `email` as the account's login identity together with `legal_name`, `password`, `citizenship_country_code`, `residency_country_code`, an optional `residency_state_code` for US residents, `birth_date`, the declared `annual_income_cents` and `net_worth_cents`, and an optional `affiliated_with_issuer` flag that defaults to false. The account is created with `suitability_status` `PENDING`, `suitability_verified_at` and `suitability_expires_at` both null, `lifetime_invested_cents` at zero, and `restriction_until` initialised to the row's `created_at`.

A `PENDING` investor is screened implicitly on every qualifying action, and the screen runs its checks in a fixed order. The jurisdiction override is evaluated first, then whether the investor has reached the age of 18 at the current clock instant as measured from `birth_date`, then the residence rule: a `residency_country_code` other than `US` is refused outright. The implicit guard is skipped only when the request body explicitly names a screen outcome — the subscription payload's optional `screened` field carrying the value `VERIFIED` or `DISPUTED`.

The jurisdiction override is reached only when the explicit screen guard did not short-circuit, and it refuses an investor whose `citizenship_country_code` is `US` and whose `residency_country_code` is also `US`: that caller is redirected to its own jurisdiction and refused with `ERR_OFFERING_NOT_AVAILABLE_IN_JURISDICTION` (HTTP 422). A failed eligibility screen is reported as `ERR_INVESTOR_INELIGIBLE` (HTTP 400), covering non-US residency and an investor under 18 at the current clock instant.

A successful screen sets `suitability_status` to `APPROVED`, stamps `suitability_verified_at` from the logical clock, and computes `suitability_expires_at` as exactly 365 days after that stamp. The approval is time-boxed: once the clock passes the expiry instant the investor's suitability is `EXPIRED` and the account may not subscribe again until it is re-screened, which restamps both timestamps. A `ComplianceOfficer` may also revoke an approval outright, supplying a `reason`; the investor moves to `REVOKED`, and every subscription of that investor still in `RECEIVED` or `SUBSCRIBED` is forced to `REJECTED` with its collected funds returned. `is_accredited` is written only by a verified screen performed against an offering qualified under the `EXEMPT_REG_D` exemption, and defaults to false otherwise.

### 2.9. Regulatory Interval and Sibling-Exclusivity Discipline

Coverage and custody are governed by exclusivity rules that make overlapping intervals structurally impossible rather than merely discouraged, and all of them are enforced at write time.

An insurance policy may not be bound while another policy of the same offering is already in force; the attempt is refused with `ERR_POLICY_INTERVAL_OVERLAP` because the two coverage periods would intersect. Conversely, a policy in force may be lapsed only once a replacement is already on file, whether that replacement is in force or merely pending; lapsing the sole policy of an offering is refused with `ERR_SOLE_POLICY_CANNOT_LAPSE`. The direct consequence is that two policies of one offering can never both be in force: a replacement is bound only after the incumbent has been lapsed.

Custody records obey the same shape. A record may not be received while another record of the same offering is already holding the work; the attempt is refused with `ERR_CUSTODY_INTERVAL_OVERLAP`.

When such an overlap or exclusivity failure is caused not by the primary write but by a cascade into a child resource whose own invariants would break, the whole operation is refused with `ERR_CASCADE_REJECTED` (HTTP 409) and the parent transition rolls back with it, leaving no partial write behind.

### 2.10. The Logical Clock and Temporal Governance

Every deadline, expiry, cadence, window, and holding-period comparison in this system reads a single logical clock, exposed to the outside world as `current_utc`. The clock's startup default is exactly `2026-09-01T00:00:00Z`. Until an operator moves it, the server's clock reads that instant and must never fall back to real wall-clock time; a platform administrator may advance it to any supplied instant through a test-driving capability. Because the clock can be held still, several writes may share one `created_at` second, which is why the monotone creation sequence described in §2.3 matters.

Four deadlines are derived from the clock and drive most of the workflow. Filing the circular stamps `circular_filed_at` and sets `qualification_deadline_at` exactly 30 days later. An investor's rescission right over a subscribed position expires three days after `circular_filed_at`. An appraisal's selection window is bounded by a 90-day cadence, with a required-refresh boundary at 180 days. And the holding period runs from the instant the work enters custody to `holding_period_end_at`. The stale-version, deadline, and cadence checks of §2.4 all resolve against this clock, never against the host's system time.

## 3. Business Logic & Workflows

### 3.1. The Artist Register and the Artwork Trust Chain

Acquisition begins with the people behind the objects. An `Artist` is registered with a `legal_name`, an `attribution_status` drawn from `CONFIRMED`, `DISPUTED`, or `UNKNOWN`, an ISO 3166-1 alpha-2 `nationality_country_code`, the optional `birth_year` and `death_year` (the latter null for a living artist), and a `catalogue_raisonne_published` flag that defaults to false. Registration stores the attribution as supplied and computes no rollup on the artist itself; the flag exists so that downstream reviewers can see whether the artist's scholarship is complete.

An `Artwork` is then registered against that artist by its `artist_id`, together with the `title`, the `creation_year`, the `medium` — one of `PAINTING`, `SCULPTURE`, `WORK_ON_PAPER`, `PHOTOGRAPH`, or `MIXED_MEDIA` — the `acquisition_cost_cents` the operator expects to tender, and the `reserve_price_cents` below which the offering board will refuse to sell. A newly registered work starts in `APPRAISED` with its `condition_grade` at the null-equivalent `PENDING`, its `last_appraised_value_cents` at zero, and `last_appraisal_at` null. It also receives an aggregate projection, `artifacts_overview`, which is refreshed on every mutation of an asset report, custody record, appraisal, offering, or cost lot belonging to the work. That projection carries `is_authenticated`, `has_good_provenance`, `latest_appraisal_value_cents`, `latest_appraisal_filed_at`, `custody_started_at`, `holding_period_elapsed_days`, and `appraisal_due`, and it is the single place a reader can see whether the work has cleared its diligence gates.

Diligence itself is recorded as `ArtworkAssetReport` filings made by the issuer's operations desk. Each filing names its `report_type` — `AUTHENTICATION`, `PROVENANCE`, or `CONDITION_SURVEY` — its `outcome`, which is one of `VERIFIED`, `DISPUTED`, or `REJECTED`, the `firm_name` of the expertising firm or conservator, and, when the report is a condition survey, the `condition_grade` the conservator assigned, drawn from `EXCELLENT`, `GOOD`, `FAIR`, or `POOR`. That grade is required for a condition survey and must be null for the other two report types. The filing timestamp `filed_at` is stamped by the server from the logical clock and is immutable thereafter.

The first state change in the artwork's life is gated by a two-part trust chain. A work moves from `APPRAISED` to `AUTHENTICATED` only when it carries at least one asset report whose `report_type` is `AUTHENTICATION` with an outcome of `VERIFIED` **and** at least one asset report whose `report_type` is `PROVENANCE` with an outcome of `VERIFIED`. Both components are required together; either alone leaves the work where it is. When the second component lands, the artwork's `condition_grade` is taken from the most recent condition survey on file and remains `PENDING` if no condition survey exists, and `artifacts_overview.is_authenticated` becomes true. A work that never clears the chain can never be securitised, because the offering-creation gate below reads that same flag.

### 3.2. Appraisal Filing, Valuation Variants and Investor Reporting

Valuation enters the system through `Appraisal` filings against an artwork. Each appraisal records the `appraised_value_cents` for the whole object, the independent `appraiser_firm`, and an `appraisal_method` of `AUCTION_COMPARABLE`, `MARKET_INDEX`, or `PRIVATE_SALE`. An appraisal begins its life in the `FILED` state, which is also the state every filing returns it to — an appraisal is never edited after it is written, so its only transition is `FILED` back to `FILED`, and it has no terminal state. The server stamps `filed_at` and, on every filing, recomputes the selection dimension across the whole sibling set: the new row becomes the selected appraisal — its `is_selected` set true — and every sibling appraisal of that artwork is recomputed to `is_selected` false. Exactly one appraisal per artwork is selected at any moment. The filing also pushes `Artwork.last_appraised_value_cents` to the new figure, sets the artwork's `last_appraisal_at` to the new `filed_at`, and sets `next_appraisal_due_at` to that instant plus 90 days. The artwork's version advances with each filing, which is why appraisal filing is one of the three concurrency-guarded writes described in §2.6.

Cadence is enforced at filing time. A new appraisal is refused with `ERR_APPRAISAL_CADENCE` when a sibling selected appraisal was filed within the preceding 90 days; equivalently, a filing is admissible only when its `filed_at` is at least 90 days after the artwork's previous selected appraisal. A second, independent ordering rule forbids back-dating: a filing whose `filed_at` would precede `Artwork.last_appraisal_at` is refused. The filing dimension and the selection dimension evolve independently on the same row set — the append-only `filed_at` history only ever moves forward, while the single-true selection flag can be moved onto a newer row at any admissible moment.

Two valuation figures are surfaced for an offering, and they can differ. The legacy provisional figure takes the basis as the `appraised_value_cents` of the newest selected appraisal by `filed_at`, whichever that is. The restated final figure takes the basis as the newest selected appraisal that carries a vetted provenance attestation — an `ArtworkAssetReport` of `report_type` `PROVENANCE` with an `outcome` of `VERIFIED` filed at or before that appraisal's own `filed_at`. In both readings the per-share value is that basis divided by the offering's `total_shares` with the quotient floored to whole cents; the figure is never rounded up. The two differ by exactly the difference between flooring the newest basis and flooring the vetted basis, so a newer appraisal whose provenance attestation had not yet been filed when it was made is ignored by the restated reading but not by the legacy one. The legacy figure is the one a subscriber sees before any restatement election is recorded; the restated figure is the one used once that election exists. The valuation surface reports the legacy value, the restated value, their signed difference, and the filing instant of the basis it used. It does so through the fields `legacy_value_per_share_cents`, `restated_value_per_share_cents`, `valuation_delta_cents` (the legacy figure less the restated one, signed), and `valuation_basis_filed_at` (the `filed_at` of the appraisal the legacy reading used, null when no appraisal is selected).

Ongoing reporting to holders is filed as `OfferingReport` rows against the offering. Each names a `report_kind` of `QUARTERLY`, `APPRAISAL`, or `SALE`, an `as_of_date` for the valuation the report speaks to, and a `value_per_share_cents` that is required for a quarterly report and null for the other kinds. The server stamps `filed_at` and computes `shareholder_count` as the number of distinct investors holding at least one accepted share as of `as_of_date`. It also computes `is_quarter_marker`, which is true when the filing falls in a tax year whose quarter-end lies outside the window covered by the artwork's selected appraisals; that flag is what drives the appraisal-cadence gate. Report filing is windowed in both directions: an `as_of_date` that precedes the offering's most recent report is refused, and so is one that post-dates the current clock, both with `ERR_REPORT_WINDOW_FORECLOSED`.

### 3.3. Offering Establishment: Circular Filing, Abandonment and Withdrawal

Securitisation begins when the issuer's operations desk creates an `Offering` against an authenticated work, binding the new offering to that work through its `artwork_id`. The payload fixes the economics once and for all: `total_shares`, into which the object is fractionalised and which must be at least 1; `price_per_share_cents`, the subscription price of one share, also at least 1; the `exemption_type`, one of `REG_D_506C`, `REG_A_TIER2`, or `EXEMPT_REG_D`; `registration_cap_pct`, the per-investor registration cap expressed in basis points of the issue where 2000 means 20.00 percent; `liquidity_ratio_bps`, the minimum secondary order size in basis points of the issue; `hold_period_days`, the length of the holding period once custody begins; `management_fee_bps`, the annual management fee in basis points of the artwork's last appraised value; `profit_participation_bps`, the issuer's carried interest in basis points of distributable proceeds; `cost_pass_through_bps`, the share of eligible operating cost that may be charged to investors; and `preferred_return_bps`, the annual hurdle applied across the holding period. The derived `gross_proceeds_cents` is simply `total_shares` multiplied by `price_per_share_cents`.

An offering is born in `DRAFT` with `circular_filed_at` null, `accepted_shares` and `reserved_shares` at zero, `cash_ledger_cents` and `custody_cost_ledger_cents` at zero, and no holding clock. Creating it moves the artwork onto the `OFFERING_PENDING` leg of its fork: the work has left the pure diligence path but is not yet under offering. The artwork holds `OFFERING_PENDING` for as long as the offering stays `DRAFT`.

Qualification is the next gate, and it is owned by a `ComplianceOfficer` because it is the moment the issuer commits publicly. Filing the circular requires the offering to still be `DRAFT` with `circular_filed_at` null, requires `total_shares` and `price_per_share_cents` each to be at least 1, and requires `artifacts_overview.is_authenticated` to be true on the parent work; the request also carries the `circular_reference` of the filed document. On success the server stamps `circular_filed_at` from the logical clock and sets `qualification_deadline_at` to exactly 30 days after it, the offering moves to `QUALIFICATION_FILED`, the artwork moves to `UNDER_OFFERING`, and the offering's version is incremented. The artwork keeps `OFFERING_PENDING` while the offering is still `DRAFT` and flips to `UNDER_OFFERING` in the same request that puts the circular on file.

Not every filed offering proceeds. A `ComplianceOfficer` may abandon one that has been qualified but never allocated, supplying a `reason`. Abandonment is admissible only while the offering is in `QUALIFICATION_FILED` and only when the artwork carries no other offering that is itself in `QUALIFICATION_FILED`. It moves the offering to terminal `OFFERING_ABANDONED` and returns the artwork to `AUTHENTICATED` — back to the fork point — rather than to `HELD`. That direction matters: a work can reach `HELD` by two distinct routes, and there is no edge back from `HELD` to `OFFERING_PENDING`. An abandoned offering therefore leaves the work permanently distinguishable in its status from a work that was merely warehoused, because the only route back into `OFFERING_PENDING` runs through `AUTHENTICATED`.

Withdrawal is the other early exit, and its admissibility depends on how far the offering has travelled. Before allocation, an offering in `QUALIFICATION_FILED` may be withdrawn only when it has accepted zero shares; the collected funds of every subscription are returned, with `refunded_cents` set to each subscription's `collected_subscription_cents`, `cash_ledger_cents` falls to zero, the offering reaches terminal `WITHDRAWN`, and the artwork returns to `AUTHENTICATED`. After allocation the constraint inverts. An offering in `ALLOCATED` may be withdrawn only while the current clock instant still precedes the just-started holding period's end (`ERR_HOLD_PERIOD_ACTIVE` refuses it once the period has run); every subscription's collected funds are returned, `cash_ledger_cents` falls to zero, the offering reaches `WITHDRAWN`, and the artwork reverts to `HELD`. This is the market-out right: before the hold period completes, an offering can be taken off the board, but once `holding_period_end_at` has passed it can only be sold, never withdrawn. Both withdrawal paths take a `reason` and the expected offering version.

### 3.4. Investor Onboarding and Suitability Screening

An investor joins through the platform's only anonymous surface, described in §2.8, and lands in `PENDING`. The compliance desk then controls the investor's passage to `APPROVED`. Two paths lead there: the implicit screen that runs on a qualifying action, and an explicit screening of a received subscription, in which a `ComplianceOfficer` records an `outcome` of either `VERIFIED` or `DISPUTED`.

A `VERIFIED` outcome on a received subscription is the ordinary route to admission, and it has three preconditions. The subscription's offering must be in `DRAFT`, `QUALIFICATION_FILED`, or `ALLOCATED` — an offering that has closed or been withdrawn takes no new money. The investor's `suitability_status` must be `PENDING` or `APPROVED`, so an expired or revoked investor cannot be waved through. And the accredited threshold binds only for the exemption that requires it: unless the offering's `exemption_type` is `EXEMPT_REG_D`, no income or net worth test applies; when it is `EXEMPT_REG_D`, the investor must declare `annual_income_cents` of at least 20000000 or `net_worth_cents` of at least 100000000. A verified screen sets the investor's `suitability_status` to `APPROVED`, stamps `suitability_verified_at` from the logical clock, sets `suitability_expires_at` to that instant plus 365 days, and — only for an `EXEMPT_REG_D` offering — sets `is_accredited` true. The subscription itself moves from `RECEIVED` to `SUBSCRIBED`, and the offering's `accepted_shares` and `unsubscribed_shares` are recomputed.

A `DISPUTED` outcome is the negative branch, taken when the screen found the investor ineligible: the subscription moves from `RECEIVED` to terminal `REJECTED`, and any funds already collected against it are returned with `refunded_cents` set. A rejected subscription is a dead end and carries no further transitions.

Revocation is the third lever. When a `ComplianceOfficer` revokes an approved investor's suitability, the investor moves to `REVOKED` and the cascade fires: every one of that investor's subscriptions still in `RECEIVED` or `SUBSCRIBED` is forced to `REJECTED`, the collected funds on each are returned, and the `accepted_shares` and `cash_ledger_cents` of every affected offering are recomputed. This is the only investor transition that touches other entities.

### 3.5. Subscriptions, the Registration Cap and Share Allocation

An `Investor` submits a subscription by naming the `offering_id`, its own `investor_id`, and the `requested_shares` it wants. The subscription is created in `RECEIVED` with `accepted_shares` and `collected_subscription_cents` at zero, `refunded_cents` at zero, `waitlist_rank` null, and an `amount_due_cents` of zero until allotment; the intermediate `SUITABILITY_SCREENED` status exists for a subscription whose suitability review has been carried out but whose allotment has not yet been computed. The server stamps a monotone `created_at_seq` on the row at insert; that sequence is the deterministic tie-break whenever two subscriptions of one offering share a `created_at` instant, which is exactly what happens when the logical clock is held still. Creating or cancelling a subscription recomputes the offering's `accepted_shares` and `unsubscribed_shares`.

Funds are collected by the issuer's desk against a named subscription, the request carrying an `amount_cents`. Collection increases `collected_subscription_cents` by that amount and increases the offering's `cash_ledger_cents` by the same amount, and on the platform side it credits the segregated account's `balance_cents` and increases `investor_funds_held_cents`. An investor may rescind a subscribed position inside the rescission window: the acting investor must be the subscription's own `investor_id`, the offering must be in `DRAFT` or `QUALIFICATION_FILED`, and the current clock instant must be no later than `circular_filed_at` plus three days. Rescission moves the subscription to terminal `WITHDRAWN`, sets `refunded_cents` to `collected_subscription_cents`, and recomputes the offering's `accepted_shares` and `cash_ledger_cents`.

Allocation is the pivot of the offering's life, and it is run by a `ComplianceOfficer`. It may not be run after the qualification deadline — a pass attempted at or beyond `qualification_deadline_at` is refused with `ERR_QUALIFICATION_LAPSED` — and it may not be run on an offering that has attracted no accepted shares, which is refused with `ERR_MINIMUM_NOT_MET` when the accepted count would be zero.

The allotment itself is a per-investor clamp against the registration cap, and the cap is an allowed-holding bound, never a reservation. The share cap for an offering is the issue's `total_shares` multiplied by `registration_cap_pct` and divided by 10000, floored to whole shares. The cap bounds how much of the issue any one investor may end up holding; it does not carve a reserved slice out of the allocatable pool, and it never expands a request — it can only clamp one down. Applying it is done investor by investor, and within an investor subscription by subscription, so that the result depends on the ordering rules rather than on how the global set happens to be traversed. Investors are taken in the order of their earliest subscription's `created_at` ascending, tie-broken by `created_at_seq` ascending. For each investor the running accepted total starts at zero, and that investor's subscriptions of this offering are then taken in the same `created_at` ascending, `created_at_seq` ascending order; for each one the remaining room is the share cap less the investor's running accepted total, floored at zero, the accepted amount is the smaller of the subscription's `requested_shares` and that room, and the accepted amount is added to the running total. Each subscription's `accepted_shares` is stamped with the result and its `amount_due_cents` is recomputed as the accepted shares multiplied by the offering's `price_per_share_cents`. A subscription that comes out of the clamp with at least one share becomes `SUBSCRIBED`; one clamped all the way to zero becomes `WAITLISTED`.

Three further effects ride on the same pass. Every `SUBSCRIBED` subscription has its `accepted_shares` stamped; every subscription clamped to zero is moved to `WAITLISTED` and given a `waitlist_rank`; and any subscription still in `RECEIVED` when the clock has passed `qualification_deadline_at` is moved to `EXPIRED`, with the funds already collected on it returned. The offering then moves to `ALLOCATED`, its `accepted_shares`, `reserved_shares`, and `unsubscribed_shares` are recomputed — the unsubscribed count being the issue size less the accepted and reserved counts together, and the reserved count being the sum of `requested_shares` across the waitlisted subscriptions — and each investor's `lifetime_invested_cents` is increased by the `amount_due_cents` of their accepted subscriptions. On the artwork side, the allocation pass is what lands the work in `HELD`.

The waitlist is a dense, deterministic queue. Ranks are assigned and re-assigned so that they run without gaps from one upward, ordered by `created_at` ascending and then by `created_at_seq` ascending, which means rank 1 is always the earliest-created waiting subscription even when several share one clock second. Promotion takes the rank-1 waiting subscription of the offering and requires the clock to be strictly before `qualification_deadline_at`, at least one unsubscribed share to remain, and that subscription to actually hold rank 1. The promoted allotment is the smaller of the offering's `unsubscribed_shares` and the candidate's `requested_shares`, after the registration clamp is applied to it; the subscription moves to `REALLOCATED`, the remaining waitlisted subscriptions are re-ranked densely, and the offering's share counts are recomputed. Promotion with no subscription in `WAITLISTED` status at all is refused with `ERR_WAITLIST_EMPTY`. Demotion is the reverse edge and takes the `subscription_id` of the subscription to return: when a reallocated subscription's accepted shares turn out to be unfundable, its `accepted_shares` are reset to zero and it is assigned a fresh `waitlist_rank` at the tail of the queue. The queue is therefore genuinely cyclic — a subscription can be promoted, demoted, and promoted again.

Every one of these moves is bounded by the same hard ceiling. No investor's projected holding may exceed `total_shares` multiplied by `registration_cap_pct` and divided by 10000. Because the cap bounds a holding and never reserves a slice, a subscription request that would push an investor past its own cap is not honoured up to the cap — it is clamped, or refused outright where no clamping is possible — and the refusal carries `ERR_OFFERING_FULL` (HTTP 409). The scaffolding of the allocation pass deliberately rejects the alternative reading in which the cap sets aside a reserved slice of the issue up front; that misreading always produces a strictly smaller accepted count whenever any investor's request exceeds the clamp, and it is not what this platform does.

### 3.6. Custody, Insurance and Cost Pass-Through

The physical object has to live somewhere, be insured, and be maintained, and those three obligations share a ledger.

Custody opens with a `CustodyRecord` created by the operations desk against an offering, naming the `custodian_name`, the `facility_code`, whether the facility is a designated freeport through the `is_freeport` flag, and whether the custodian is registered under the applicable anti-money-laundering programme through `custodian_dea_registered`, which defaults to false. A new record starts `PENDING` with `custody_started_at` null. Receipt of the work is the transition that matters: the record may only be received when the offering carries no other record already in `IN_CUSTODY` — otherwise the two custody periods would intersect and the attempt is refused with `ERR_CUSTODY_INTERVAL_OVERLAP` — and the offering must be in `ALLOCATED` or `HELD`. On receipt the record's `custody_started_at` is stamped from the logical clock, the record becomes `IN_CUSTODY`, and the offering starts its holding clock: `holding_clock_started_at` is set if it was null, `holding_period_end_at` is computed as that instant plus `hold_period_days`, and the offering moves to `HELD`. This is the transition that starts the hold clock, and nothing may gate on the end of the holding period until it has run. This is also the second fork branch of the artwork's life: an authenticated work can be warehoused and reach `HELD` without any offering ever having been created for it, provided no offering of the work exists in any status other than `WITHDRAWN`. In that case the record's receipt is what moves the artwork to `HELD`.

Release is the reverse. A record in `IN_CUSTODY` may be released only while the offering is `HELD`; the record becomes `RELEASED`, its `custody_ended_at` is stamped, and the offering's holding clock is cleared — `holding_clock_started_at` and `holding_period_end_at` both return to null, and the offering drops back to `ALLOCATED`, which reopens the secondary window described in §3.7.

A released record can be re-received, and that re-receipt is the revision loop by which a work moving between vaults restarts its hold clock. Re-receipt has four gates. The artwork must carry a selected appraisal filed strictly after the record's `custody_ended_at`; without one the attempt is refused with `ERR_APPRAISAL_STALE`. The offering must be `ALLOCATED`. No other record of the offering may already be `IN_CUSTODY`, on pain of `ERR_CUSTODY_INTERVAL_OVERLAP`. And the request must carry the expected offering version, per §2.6. When all four pass, `custody_ended_at` is reset to null, `custody_started_at` is re-stamped, the offering's `holding_clock_started_at` is re-stamped and `holding_period_end_at` recomputed from it, and the offering returns to `HELD`.

Insurance is bound separately and is deliberately anchored to appraised value rather than to the purchase price. A policy is created with the `carrier_name`, the `coverage_cents` sum insured, and the `annual_premium_cents`, and starts `PENDING`. A market quote may be recorded without creating a policy at all, by supplying the proposed `carrier_name` and the `quoted_annual_premium_cents` and receiving back a `quote_reference`. Binding a policy into force requires four things at once: the artwork must carry a selected appraised value greater than zero, since binding against an unappraised work is refused with `ERR_APPRAISAL_MISSING`; the coverage must be at least that value, or the bind is refused with `ERR_INSUFFICIENT_COVERAGE`; the coverage must be no more than 120 percent of that value — that is, the value multiplied by 120 and divided by 100 — or the bind is refused with `ERR_COVERAGE_EXCEEDS_VALUE`; and no sibling policy of the same offering may already be in force, or the bind is refused with `ERR_POLICY_INTERVAL_OVERLAP`. On success the policy becomes `FORCE`.

Lapsing runs the exclusivity rule from §2.9 in the other direction, and it carries the platform's second cascade. A policy in force may be lapsed only when another policy of the same offering is already on file in `FORCE` or `PENDING`; lapsing the sole policy is refused with `ERR_SOLE_POLICY_CANNOT_LAPSE`. When the lapse is allowed, the policy becomes `LAPSED`, and every cost lot of the offering is recomputed in the knowledge that an offering without cover in force can no longer charge operating cost to investors: each lot's `pass_through_allowed` becomes false and its `pass_through_amount_cents` becomes zero, and the offering's `custody_cost_ledger_cents` is recomputed as the sum of the recomputed pass-through amounts across every lot of the offering. That cascade runs insurance policy to lot to offering, and it is the reason a lapse is not a local event.

Operating cost reaches the ledger through `Lot` journals filed against an offering, each naming a `lot_type` of `STORAGE`, `INSURANCE`, or `CONSERVATION`, a `cost_amount_cents`, and the `incurred_on` instant. A lot's eligibility for pass-through is decided by a chain of five hard gates, evaluated in order with the first failure short-circuiting the rest: the `lot_type` must be one of `STORAGE`, `INSURANCE`, or `CONSERVATION`; the offering's status must be `ALLOCATED` or `HELD`; an `InsurancePolicy` of the offering must be in `FORCE`; no `TransferOrder` of the offering may be in `OPEN` status; and the offering's `holding_clock_started_at` must be set, with the lot's `incurred_on` falling at or after it. Only when every gate passes does `pass_through_allowed` come out true; the persisted value is a single boolean rather than a gate-by-gate record, because the short-circuit discards which gate failed. When the lot is allowed, its `pass_through_amount_cents` is the `cost_amount_cents` multiplied by the offering's `cost_pass_through_bps` and divided by 10000, floored to whole cents; when any gate fails, the amount is zero and the issuer absorbs the full cost of the lot. Either way, the resulting pass-through amount is added to the offering's `custody_cost_ledger_cents`. Posting a fresh open transfer order against an offering therefore actively suspends pass-through for the whole offering for as long as that order rests, which is the intent: cost is not charged to investors while the offering is in play on the secondary market.

### 3.7. The Restricted Secondary Market

Holders may seek liquidity before the artwork sells, but only inside a narrow, explicitly bounded window, and only among people who already hold the issue.

An `Investor` posts a `TransferOrder` naming the `offering_id`, its own `seller_id`, the number of `shares` it is offering, and its `limit_price_cents` — the lowest price per share it will accept. The order is created in `OPEN` with `buyer_id` unbound and `bid_price_cents` null, and the server records the posting officer's `created_by_user_id` for the segregation-of-duties check that governs settlement. Posting an open order also suspends cost pass-through for the entire offering, as described in §3.6.

Acceptance is where the market is fenced. A counterparty accepts a resting order by supplying its own `buyer_id` and the `bid_price_cents` it is willing to pay, and no fewer than seven conditions must hold together. The order's `shares` must be at least the offering's minimum lot, which is `total_shares` multiplied by `liquidity_ratio_bps` and divided by 10000, floored to whole shares; the comparison is a strict less-than, so an order of exactly the floored minimum is admissible and one share fewer is refused with `ERR_LIQUIDITY_WINDOW_LOCKED`. The buyer must not be the seller. The buyer must already hold at least one accepted share of this offering — the secondary market is closed to non-holders, and a buyer that holds nothing is refused with `ERR_INVALID_STATE`. The offering must be in `ALLOCATED`. The current clock instant must be at or after the buyer's `restriction_until`. The offering's `holding_period_end_at` must be null, meaning the holding clock has never started. And the `bid_price_cents` must be at least the order's `limit_price_cents`. On success the order moves to `MATCHED`, `buyer_id` is bound, and `execution_price_cents` is provisionally set to the resting `limit_price_cents`.

The liquidity floor is read against the whole issue, never against any absolute share count: on an issue of 40000 shares with a 1000-basis-point ratio the minimum lot is 4000 shares, and a 1000-share order that a flat-share-count reading would admit is firmly refused. The buyer's cap is checked on the same terms as the primary market. The buyer's current holdings are the sum of `accepted_shares` across its subscriptions to this offering, its projected holdings add the order's `shares`, and the buyer's cap is `total_shares` multiplied by `registration_cap_pct` and divided by 10000, floored. A projected holding above that cap is refused with `ERR_OFFERING_FULL`, save for one carve-out: when the open-order queue is empty and the accepting counterparty is therefore the empty-queue fallback, that buyer is not subject to the projection cap and its acceptance is admitted.

Settlement is the transfer agent's act, and it enforces a separation of duties. A `TransferAgent` approves a transfer by naming the expected offering version, and the approval requires that `buyer_id` actually be bound; that the acting officer's `X-User-ID` differ from the `created_by_user_id` recorded when the order was posted; and that the offering's `holding_period_end_at` still be null — the holding clock must never have started. The price that settles depends on how the order arrived: an order that was accepted carries the price set at acceptance, while an order approved directly out of `OPEN` settles at the greater of `bid_price_cents` and `limit_price_cents`, so the seller is never worse off than the price it posted and captures the upside when the counterparty bids above the resting limit. Both share ledgers then move together — the seller's accepted shares decrease by `shares` and the buyer's increase by the same count — the order reaches `EXECUTED`, and the offering's version advances. Secondary movement never touches `lifetime_invested_cents`: that figure tracks only primary subscriptions, so a sale on the secondary market leaves the seller's lifetime total exactly where it was.

The window is genuinely narrow, and both sides of the holding-period comparison are pinned by §2.10. Because a transfer requires `holding_period_end_at` to be null, the mere existence of a holding period forecloses the market entirely: an offering whose clock has started — even one whose end instant has not yet arrived — cannot trade at all. The sale side is the mirror image: a sale approval requires the clock to be running, and to have run out, governed by the same field read the opposite way. The two gates are unlocked in disjoint states, and attempting to settle a transfer while the clock is running is refused with `ERR_HOLD_PERIOD_ACTIVE`.

Orders that fail to move are handled by two back edges and one system sweep. A matched order whose counterparty withdraws before settlement can be reposted, which unbinds `buyer_id` and returns it to `OPEN`; a `TransferAgent`-side failure has the same remedy. A resting order that has sat `OPEN` for at least 30 consecutive days with no acceptance is moved to `LAPSED` by the server during the offering's reconciliation pass, and no shares move as a result. A lapsed order may be reposted by its own `seller_id` — the acting investor must be that seller — after which it is no longer lapsed. An `Investor` may cancel its own order, and the operations desk may cancel a matched order whose settlement failed; both paths land the order in terminal `CANCELLED`.

### 3.8. The Holding Decision Chain, Sale Execution and the Distribution Waterfall

The endgame begins with a holding decision raised by the operations desk against an offering. A `HoldingDecision` names a `decision_type` of `HOLD` or `SELL` and, for a sale, a `proposed_gross_cents`; that field is required for a sale and must be null for a hold. The decision records `created_by_user_id` — the `X-User-ID` of the officer who raised it — and later `approved_by_user_id`, and those two references are what the segregation-of-duties rules consult.

The two decision types take very different routes. A `HOLD` decision is approved on the spot: it is created directly in `APPROVED` status and cycles the offering back to `ALLOCATED`, which is the legitimate edge by which an offering moves from `HELD` back into the trading state so that the secondary market reopens. A `SELL` decision is parked in `PENDING` and leaves the offering untouched until a separate approval happens.

Approving a sale is the most tightly gated step in the system. It requires `decision_type` to be `SELL` with the decision still `PENDING`; the current clock instant must be at or after the offering's `holding_period_end_at`, so an approval attempted before the holding period has run is refused with `ERR_HOLD_PERIOD_ACTIVE`; and the acting officer's `X-User-ID` must differ from the `created_by_user_id` recorded when the decision was raised. That last rule is the propose/approve separation: the desk that raises a sale may not also approve it. Approval sets the decision to `APPROVED`, moves the offering to `SALE_PENDING`, and moves the artwork to `SALE_PENDING` with it. Approving a `HOLD` decision instead requires only that the offering be in `ALLOCATED` or `HELD`, and it drives the offering to `ALLOCATED` with the artwork unchanged.

The overturn path is a cycle rather than a one-way door. A `ComplianceOfficer` — standing on the opposite side of the separation from the desk that approved — may reject a decision, and the rejection requires that the acting officer's `X-User-ID` differ from the `approved_by_user_id` recorded on the approval. Rejecting an approved sale reverts the offering to `ALLOCATED` and the artwork to `HELD`. Rejection is also open against a decision still `PENDING`, whether because the holding period has not yet passed or because the officer declines the proposal outright, and in that case the offering simply stays `ALLOCATED`. A rejected decision is not necessarily dead: the operations desk may revise it by supplying a new `proposed_gross_cents`, which returns it to `PENDING` and replaces the proposed figure, leaving the offering in `ALLOCATED`. That closes the loop by which a proposal can be approved, overturned, revised, and approved again.

Execution is where the money is decided, and it forks on a single comparison against the artwork's `reserve_price_cents`. It requires the decision to be `APPROVED` and the offering to be `SALE_PENDING`, and the request carries the `executed_gross_cents` the sale actually realised together with the expected offering version. Proceeds strictly below the reserve are declined: the decision moves to terminal `FAILED`, the offering reverts to `ALLOCATED`, the artwork reverts to `HELD`, and no distribution is created — the pair of entities rolls back together and the offering is available to be sold another day. Proceeds at or above the reserve complete the cycle: the decision moves to terminal `EXECUTED` with `executed_gross_cents` stored, the offering reaches terminal `CLOSED`, the artwork reaches terminal `SOLD`, and a `Distribution` is created against the offering in status `CALCULATED`. That last path is the platform's deepest cascade, running artwork to offering to distribution to the segregated cash account.

Before a distribution can be calculated the offering's final assets must be known, and two accruals feed it, each raised by naming an `accrual_type` of `MANAGEMENT` or `PROFIT_PARTICIPATION`. The management fee accrues against the artwork's last selected appraised value: the annual rate in `management_fee_bps` is applied in basis points over a period of 365 days, so the accrued amount is the appraised value multiplied by the fee rate and divided by 10000, multiplied by the number of holding days, and divided by 365, floored to whole cents. Holding days are measured from `holding_clock_started_at` to `holding_period_end_at`, and that interval is read two ways: the presentation figure uses the plain difference between the two instants, while the figure that settles in cash adds the start day back, making a 182-day clock settle on 183 days and thus one day's fee larger. Both readings are reported together on the accrual. The same fee is accrued again at the moment of execution. Profit participation is the other accrual and is computed off the distributable pool, but it may only be recorded once the offering's sale cycle has actually closed — because there is no `distributable_proceeds_cents` to take a participating share of until then. An attempt to accrue profit participation against a live offering is refused with `ERR_ACCRUAL_TYPE_UNSUPPORTED`. Each accrual row records what it was based on through `basis_value_cents` — the last appraised value for a management accrual, the distributable proceeds for a profit-participation accrual — together with its `amount_cents` and the `accrued_at` instant.

The distribution itself is a waterfall with a pinned evaluation order that must not be reordered, because each step is floored to whole cents before it is subtracted and rounding must never manufacture a negative residual.

The investor-borne operating cost comes out first: the offering's `custody_cost_ledger_cents` multiplied by its `cost_pass_through_bps` and divided by 10000, floored, becomes the `distributed_cost_cents` deducted at step zero. The realised gain pool, `distributable_cents`, is the `sale_gross_cents` of the sale event being distributed — the executed gross proceeds — less the artwork's `acquisition_cost_cents`. The issuer's management-fee claim, stored as `management_fee_cents`, is then taken as the `acquisition_cost_cents` multiplied by `management_fee_bps` and divided by 10000, floored. The preferred return follows, as the `acquisition_cost_cents` multiplied by `preferred_return_bps` and divided by 10000, multiplied by the number of days the work was held — measured from `holding_clock_started_at` to the current clock instant — and divided by 365, floored. The issuer's carried interest, `profit_participation_cents`, is next, as `distributable_cents` multiplied by `profit_participation_bps` and divided by 10000, floored, which is the same figure the profit-participation accrual stores. What remains for the holders, `investor_residual_cents`, is the `distributable_cents` less the four preceding amounts in the order stated: the distributed cost, the management fee, the preferred return, and the profit participation.

Only holders with at least one accepted share as of the execution instant participate; a subscription with `accepted_shares` of zero takes nothing. The per-share figure, `per_share_cents`, is the `investor_residual_cents` divided by the offering's `total_shares` using integer division. The division does not always come out even, and the whole remainder — the residual less the per-share amount multiplied by the total share count — is assigned to a single holder rather than spread: it goes in full to the holder whose earliest accepted subscription has the smallest `created_at`, tie-broken by the smallest `created_at_seq`. If any of the fee or return steps floors to zero it simply contributes nothing; it does not shift the position of any later step.

The distribution then has to be paid, and payment is the point at which the platform's segregated cash account is touched. A calculated distribution is paid out to the offering's holders by debiting the platform account's `balance_cents` by the `investor_residual_cents` and increasing `total_paid_out_cents` by the same amount, moving the distribution to `PAID` and advancing the offering's version. Because that account may never go negative, a payment that would overdraw it is refused with `ERR_ACCOUNT_UNDERFUNDED` (HTTP 409) and no partial debit is applied — which is the same conservation rule that guards cost-lot posting and offering withdrawal.

Two housekeeping capabilities close the loop. An offering's reconciliation pass computes the appraisal cadence flag from the gap, in whole days, between the current clock instant and the artwork's `last_appraisal_at`: a gap of 180 days or more flags the artwork as `REQUIRED`, a gap strictly greater than 90 days flags it as `DUE`, and any smaller gap — including a gap of exactly 90 days — flags it as `CURRENT`. Because the artwork's last appraisal instant is recomputed from selected appraisals only, an unselected filing never resets the cadence. The same pass sweeps the offering's resting transfer orders, lapsing every order that has sat open for at least 30 consecutive days, and reports the cadence flag, the gap in days, the number of orders lapsed, and the next appraisal due instant. Separately, a platform administrator may open the segregated cash account by supplying an `account_name`; the account starts with `balance_cents` at zero, `investor_funds_held_cents` at zero, and `total_paid_out_cents` at zero.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource or add a distinct resource to a collection return `201 Created`. Operations that modify an existing resource, or that drive a state transition on one, return `200 OK`. Reads return `200 OK`. The API is mounted under `/api`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/artists` | Register an artist or creator of record | IssuerOps, PlatformAdmin |
| GET | `/api/artists/{id}` | Read one artist | IssuerOps, ComplianceOfficer, TransferAgent, PlatformAdmin |
| GET | `/api/artists` | List artists, optionally filtered by attribution status | IssuerOps, ComplianceOfficer, PlatformAdmin |
| POST | `/api/investors` | Register an investor account (anonymous) | Anonymous |
| GET | `/api/investors/{id}` | Read one investor | Investor, ComplianceOfficer, IssuerOps, PlatformAdmin |
| GET | `/api/investors` | List investors, optionally filtered by suitability status | ComplianceOfficer, IssuerOps, PlatformAdmin |
| POST | `/api/investors/{id}/revoke-suitability` | Revoke suitability; open primary subscriptions are rejected and refunded | ComplianceOfficer |
| POST | `/api/artworks` | Register an artwork to be acquired and securitised | IssuerOps, PlatformAdmin |
| GET | `/api/artworks/{id}` | Read one artwork including its `artifacts_overview` aggregate | IssuerOps, ComplianceOfficer, TransferAgent, PlatformAdmin |
| GET | `/api/artworks` | List artworks, optionally filtered by status or artist | IssuerOps, ComplianceOfficer, PlatformAdmin |
| POST | `/api/artworks/{id}/asset-reports` | File an authentication, provenance or condition-survey report | IssuerOps |
| GET | `/api/artworks/{id}/asset-reports` | List asset reports filed on an artwork | IssuerOps, ComplianceOfficer, PlatformAdmin |
| POST | `/api/artworks/{id}/appraisals` | File an appraisal; the newest admissible filing becomes selected | IssuerOps |
| GET | `/api/artworks/{id}/appraisals` | List appraisals on an artwork, oldest first | IssuerOps, ComplianceOfficer, PlatformAdmin |
| POST | `/api/artworks/{id}/offerings` | Create a securities offering against an authenticated artwork | IssuerOps |
| GET | `/api/offerings/{id}` | Read one offering with its share and cost ledgers | IssuerOps, ComplianceOfficer, TransferAgent, PlatformAdmin |
| GET | `/api/offerings` | List offerings, optionally filtered by artwork or status | IssuerOps, ComplianceOfficer, TransferAgent, PlatformAdmin |
| POST | `/api/offerings/{id}/qualification-filing` | File the securities circular and start the qualification window | ComplianceOfficer |
| POST | `/api/offerings/{id}/allocate` | Run the share-allocation pass and move the offering to `ALLOCATED` | ComplianceOfficer |
| POST | `/api/offerings/{id}/waitlist-promotion` | Promote the rank-1 waiting subscription into `REALLOCATED` | ComplianceOfficer |
| POST | `/api/offerings/{id}/waitlist-demotion` | Return a reallocated subscription to the tail of the waitlist | ComplianceOfficer |
| POST | `/api/offerings/{id}/withdraw` | Withdraw an offering and refund every collected subscription | ComplianceOfficer |
| POST | `/api/offerings/{id}/abandon` | Abandon a filed but unallocated offering | ComplianceOfficer |
| GET | `/api/offerings/{id}/share-ledger` | Read the per-investor share ledger | Investor, IssuerOps, ComplianceOfficer, TransferAgent, PlatformAdmin |
| GET | `/api/offerings/{id}/valuation` | Read both valuation variants side by side | Investor, IssuerOps, ComplianceOfficer, TransferAgent |
| POST | `/api/offerings/{id}/cost-lots` | Journal a storage, insurance or conservation cost lot | IssuerOps |
| GET | `/api/offerings/{id}/cost-lots` | List cost lots journaled against the offering | IssuerOps, ComplianceOfficer, PlatformAdmin |
| POST | `/api/offerings/{id}/accrue-fees` | Accrue the management fee or the profit participation | IssuerOps |
| GET | `/api/offerings/{id}/fee-accruals` | List fee accruals recorded against the offering | IssuerOps, ComplianceOfficer, PlatformAdmin |
| POST | `/api/offerings/{id}/reports` | File an ongoing investor report | IssuerOps, ComplianceOfficer |
| GET | `/api/offerings/{id}/reports` | List reports filed against the offering | Investor, IssuerOps, ComplianceOfficer, PlatformAdmin |
| POST | `/api/offerings/{id}/reconcile-cadence` | Run the appraisal-cadence and stale-order reconciliation pass | IssuerOps, PlatformAdmin |
| POST | `/api/offerings/{id}/insurer-quote` | Record a market insurer quote before any policy is created | IssuerOps |
| GET | `/api/offerings/{id}/subscriptions` | List every subscription taken against the offering | IssuerOps, ComplianceOfficer, PlatformAdmin |
| POST | `/api/offerings/{id}/holding-decisions` | Raise a holding decision (`HOLD` approves immediately, `SELL` parks at `PENDING`) | IssuerOps |
| GET | `/api/offerings/{id}/holding-decisions` | List holding decisions raised against the offering | IssuerOps, ComplianceOfficer, PlatformAdmin |
| GET | `/api/offerings/{id}/custody-records` | List every custody record of the offering | IssuerOps, ComplianceOfficer, PlatformAdmin |
| POST | `/api/offerings/{id}/custody-records` | Open a custody record for the offering's artwork | IssuerOps |
| POST | `/api/offerings/{id}/insurance-policies` | Create an insurance policy for the offering's artwork | IssuerOps |
| POST | `/api/offerings/{id}/distributions/{distributionId}/pay` | Pay a calculated distribution out of the platform account | IssuerOps |
| GET | `/api/offerings/{id}/distributions` | List distributions computed against the offering | Investor, IssuerOps, ComplianceOfficer, PlatformAdmin |
| POST | `/api/subscriptions` | Submit a subscription for shares in an offering | Investor |
| GET | `/api/subscriptions/{id}` | Read one subscription | Investor, IssuerOps, ComplianceOfficer, PlatformAdmin |
| GET | `/api/subscriptions` | List subscriptions filtered by offering, investor or status | IssuerOps, ComplianceOfficer, PlatformAdmin, Investor |
| POST | `/api/subscriptions/{id}/screen` | Record an explicit suitability screen outcome | ComplianceOfficer |
| POST | `/api/subscriptions/{id}/collect` | Collect investor funds against a subscription | IssuerOps |
| POST | `/api/subscriptions/{id}/withdraw` | Rescind a subscription during the rescission window | Investor |
| GET | `/api/custody-records/{id}` | Read one custody record | IssuerOps, ComplianceOfficer, PlatformAdmin |
| POST | `/api/custody-records/{id}/receive` | Receive the artwork into custody | IssuerOps |
| POST | `/api/custody-records/{id}/release` | Release the artwork out of custody | IssuerOps |
| GET | `/api/insurance-policies/{id}` | Read one insurance policy | IssuerOps, ComplianceOfficer, PlatformAdmin |
| GET | `/api/offerings/{id}/insurance-policies` | List every insurance policy of the offering | IssuerOps, ComplianceOfficer, PlatformAdmin |
| POST | `/api/insurance-policies/{id}/bind` | Bind a policy into force | IssuerOps |
| POST | `/api/insurance-policies/{id}/lapse` | Lapse a policy in force and roll back cost-lot pass-through | IssuerOps |
| GET | `/api/holding-decisions/{id}` | Read one holding decision | IssuerOps, ComplianceOfficer, PlatformAdmin |
| PATCH | `/api/holding-decisions/{id}/approve` | Approve a holding decision | IssuerOps |
| PATCH | `/api/holding-decisions/{id}/reject` | Reject a holding decision and roll the offering back to `ALLOCATED` | ComplianceOfficer |
| PATCH | `/api/holding-decisions/{id}/revise` | Revise a rejected decision back to `PENDING` | IssuerOps |
| POST | `/api/holdings/{id}/execute` | Execute an approved sale and compute the distribution waterfall | IssuerOps |
| POST | `/api/transfer-orders` | Post a secondary-market sell order | Investor |
| GET | `/api/transfer-orders` | List transfer orders filtered by offering, seller, buyer or status | Investor, IssuerOps, ComplianceOfficer, TransferAgent, PlatformAdmin |
| GET | `/api/transfer-orders/{id}` | Read one transfer order | Investor, IssuerOps, ComplianceOfficer, TransferAgent, PlatformAdmin |
| POST | `/api/transfer-orders/{id}/accept` | Accept a resting transfer order | Investor |
| POST | `/api/transfer-orders/{id}/repost` | Repost a matched or lapsed order onto the book | Investor, IssuerOps |
| POST | `/api/transfer-orders/{id}/approve-transfer` | Settle a secondary transfer | TransferAgent |
| POST | `/api/transfer-orders/{id}/cancel` | Cancel a transfer order | Investor, IssuerOps |
| POST | `/api/platform-accounts` | Open the platform's segregated cash account | PlatformAdmin |
| GET | `/api/platform-accounts/{id}` | Read the platform account ledger balances | PlatformAdmin |
| POST | `/api/_clock/set_current_utc` | Test-driving capability: move the logical clock | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_ROUTE_NOT_FOUND` | 404 |
| `ERR_METHOD_NOT_ALLOWED` | 405 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVESTOR_INELIGIBLE` | 400 |
| `ERR_OFFERING_NOT_AVAILABLE_IN_JURISDICTION` | 422 |
| `ERR_OFFERING_FULL` | 409 |
| `ERR_LIQUIDITY_WINDOW_LOCKED` | 409 |
| `ERR_HOLD_PERIOD_ACTIVE` | 409 |
| `ERR_MINIMUM_NOT_MET` | 422 |
| `ERR_QUALIFICATION_LAPSED` | 409 |
| `ERR_APPRAISAL_CADENCE` | 409 |
| `ERR_APPRAISAL_STALE` | 409 |
| `ERR_APPRAISAL_MISSING` | 409 |
| `ERR_INSUFFICIENT_COVERAGE` | 422 |
| `ERR_COVERAGE_EXCEEDS_VALUE` | 422 |
| `ERR_ACCOUNT_UNDERFUNDED` | 409 |
| `ERR_SOLE_POLICY_CANNOT_LAPSE` | 409 |
| `ERR_POLICY_INTERVAL_OVERLAP` | 409 |
| `ERR_CUSTODY_INTERVAL_OVERLAP` | 409 |
| `ERR_WAITLIST_EMPTY` | 409 |
| `ERR_REPORT_WINDOW_FORECLOSED` | 409 |
| `ERR_ACCRUAL_TYPE_UNSUPPORTED` | 422 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_VALUE_REJECTED` | 400 |
| `ERR_CASCADE_REJECTED` | 409 |