# Commercial Property Data Licensing API — Product Requirements Document

## 1. Introduction

Commercial real estate decisions — acquisitions, leases, financings and valuations — are underwritten with property-level facts: who occupies a building, what they pay, what comparable space has traded for, and what a sale actually cleared at. The Commercial Property Data Licensing API is the operational backbone of an organization that gathers those facts and licenses them onward. It spans the full value chain: field research that verifies property attributes, tenancy, lease comparables and sale transactions through direct contact and public records; data-quality control that demands documented sourcing and recency; and subscription licensing that sells the resulting corpus by seat, market and product.

The economics of that business create a permanent tension. Research coverage is expensive to build and trivially cheap to copy, so the platform treats distribution control as a first-class product capability rather than an afterthought. Usage monitoring watches for credential sharing across distinct networks; audits quantify unauthorized redistribution; litigation escalation suspends the offending organization and terminates its contracts; and settlement restores the account once the penalty has been satisfied. Analytics products — market forecasts and constructed indices — are built on top of the verified research corpus, and a brokerage-side listing product feeds published availabilities back into that corpus as fresh research input.

This document specifies the API contract for that system. It defines the resource model and its shared conventions, the state machines that govern research records, contracts, seats, listings and enforcement cases, the deterministic calculations that drive data-quality scoring, usage pricing, index construction and penalty assessment, and the error surface that a client must handle. A logical clock is exposed so that time-dependent behaviors — source ageing, renewal lapse, listing expiry and cycle checkpoints — can be exercised deterministically rather than being tied to wall-clock time.

## 2. Global Specifications & System-Wide Principles

The rules in this section apply across every endpoint in the API and take precedence over any narrower statement elsewhere.

### 2.1. User and Role-Based Access Control

Every request must present two headers. `X-User-ID` identifies the acting principal, and `X-User-Role` names the operational capacity in which that principal is acting. A request in which either header is absent, or in which either header is present but empty, is rejected with `ERR_UNAUTHENTICATED` and carries HTTP status 401. A request whose acting role is not permitted for the operation being attempted is rejected with `ERR_UNAUTHORIZED` and carries HTTP status 403. A request whose payload omits a required input field, or whose field fails its declared type or enumeration constraint, is rejected with `ERR_INVALID_REQUEST` and carries HTTP status 400.

The API recognizes exactly six roles, and their names must be spelled as follows: `PlatformAdmin`, `ResearchAnalyst`, `SeatUser`, `LicensingAdmin`, `EnforcementOfficer` and `BrokerPublisher`.

`PlatformAdmin` is an opaque operator identity. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server may record it, but it is never compared to any entity's `id`. This is the only role permitted to create base `Organization` records, to set the logical clock, and to run the periodic research cycle.

The remaining five roles are entity-backed. When `X-User-Role` is `ResearchAnalyst`, `SeatUser`, `LicensingAdmin`, `EnforcementOfficer` or `BrokerPublisher`, `X-User-ID` is the `id` of the acting `User` row, and ownership and scope checks on any resource that references a `User` compare the resource's foreign-key field to `X-User-ID`. The persisted `User.role` enumeration carries the corresponding spellings — `RESEARCH_ANALYST`, `SEAT_USER`, `LICENSING_ADMIN`, `ENFORCEMENT_OFFICER` and `BROKER_PUBLISHER` — and a request presenting one of these roles whose `X-User-ID` does not resolve to a `User` whose `status` is `ACTIVE` is rejected with `ERR_UNAUTHORIZED`. A `User` whose `status` has been moved to `INACTIVE` may no longer be assigned as a seat occupant.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, its minimum is 1, and its maximum is 100. The `offset` parameter states how many items to skip from the front of the result set, and it defaults to 0. A request that supplies a `limit` below the minimum or above the maximum is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

All list endpoints return resources sorted by `created_at` ascending, and no endpoint reorders that default. Whatever query filters an endpoint accepts — a market, a status, an owning organization, a parent resource — narrow the result set without changing the sort. The `meta` object of a list response carries `limit`, `offset`, `total_count` and `has_more`, and `total_count` counts the matching rows before pagination is applied.

### 2.4. The Logical Clock

Time-dependent behavior in this API is driven by a logical clock rather than by wall-clock time. Before any request is served, the clock reads exactly `2026-09-01T00:00:00Z`, and it never falls back to real time. A `PlatformAdmin` may advance or rewind it by supplying a `current_utc` instant. Every rule in this document that speaks of "now", of an instant, or of an interval boundary is evaluated against that clock. This is what makes source ageing, renewal lapse, listing expiry and deadline enforcement reproducible.

### 2.5. Research Scope and the Lead Analyst

The `ResearchAnalyst` role is entity-backed: `X-User-ID` is the `id` of the acting `User` row. Each such `User` carries an `assigned_market` string — the market code the analyst is assigned to research — and that field is required whenever the user's `role` is `RESEARCH_ANALYST`; for every other role it may be omitted and defaults to null. Property access for scoped research operations is bounded by that territory: the API resolves the acting analyst's `assigned_market` as its defined address and rejects a scoped operation on a `Property` whose `market` differs from it with `ERR_PROPERTY_NOT_FOUND` and HTTP 404, exactly as though no such record existed.

Market codes themselves are free-form strings of the shape `TX-DALLAS` rather than an enumerated type, so organizations, properties, attributes, seats, listings and analytics runs all carry the same literal string when they refer to the same market. An equality test between two market strings is a byte comparison of that string.

### 2.6. Common Resource Properties

Every resource in this system carries a system-minted `id`. That identifier is a UUID with no type prefix and no embedded meaning; it is opaque, and no ranking, selection or tie-break rule anywhere in this document consumes one. Alongside the `id`, and unless a resource is explicitly called out below as an exception, every resource carries a `created_at` ISO 8601 UTC timestamp with exactly three fractional digits, an `updated_at` timestamp in the same format that is refreshed on every mutation, and an integer `version` that starts at 1 and increments by exactly one on every accepted mutation. Derived-field recomputations are mutations: they refresh `updated_at` and advance `version`.

`UsageEvent` is the one exception. It is created with `common_fields: false`, and therefore carries only `id` and `created_at`; it has neither `updated_at` nor `version`, because a usage record is an immutable ledger entry rather than a mutable resource.

### 2.7. Precision, Rounding and Monetary Representation

Monetary amounts are carried as integer cents throughout the API. Rates expressed as percentages are carried as decimal numbers in which a whole number means one hundred percent — a `fee_rate_pct` of 1.5 means 150 percent. Data-quality scores, index values and attribution percentages are decimal numbers reported to exactly two decimal places.

Every rounding operation in this document is round half up, applied to the value named by the rule that invokes it. Where a calculation does not name a stage, rounding is applied once, to the final result; where it names a pinned evaluation order, rounding is applied at each named stage and the stages are applied in the order given. `round_half_up` is never replaced by truncation, floor rounding or banker's rounding.

### 2.8 Account Standing and the Organization Aggregate

Every firm in the system — a data provider, a brokerage or a subscriber — is modelled as an `Organization`. An organization is registered with a `legal_name`, an `org_type` drawn from `DATA_PROVIDER`, `BROKERAGE` or `SUBSCRIBER`, and a `home_market`. It also carries a `service_tier` drawn from `ENTERPRISE`, `MID_MARKET` or `SMB`; when the creating request omits that field it defaults to `ENTERPRISE`, and the tier feeds every fee rebase described in §3. A newly created organization is `ACTIVE` and both of its aggregate counters begin at zero.

The `status` of an organization is `ACTIVE` or `SUSPENDED`, and `SUSPENDED` is a gate rather than a label: a suspended organization's seats can no longer record usage. Escalating an enforcement case to litigation is the only operation that suspends an organization, and settling the case is the only operation that restores it.

Two counters are derived and recomputed whenever the underlying contracts change. `authorized_market_count` counts the distinct markets taken across this organization's licensing contracts whose status is `PENDING`, `ACTIVE`, `GRACE` or `RENEWED`, reading each contract's `licensed_markets` array. `active_contract_count` counts this organization's contracts whose status is `ACTIVE` or `GRACE`. Both are response-visible attributes of the `Organization` resource, so a client that activates, renews, terminates or lapses a contract will see them move.

Membership is explicit: a `User` is created beneath an organization with an `email` that must be unique within that organization, a `full_name`, a `role` from the enumeration in §2.1, and an optional `assigned_market`. The `organization_id` recorded on the user is the affiliation the seat-scope rules of §3.6 test against, and a new user's `status` is `ACTIVE`.

### 2.9 Evidence Provenance and Freshness

Every factual claim in the research corpus traces to a `SourceDocument` attached to a property. A source row states a `source_type` from `DEED`, `PUBLIC_RECORD`, `DIRECT_CONTACT`, `BROKER_LISTING` or `THIRD_PARTY_FEED`; a `source_name` naming the recording office, contact or feed vendor; a `contact_method` from `PHONE`, `EMAIL`, `SITE_VISIT`, `RECORDS_REQUEST` or `FEED_IMPORT`; and the `obtained_at` instant at which the evidence was gathered. It may also carry a `distributed_markets` array, which defaults to an empty list when the request omits it.

Provenance is decided by the server, not by the client. The computed `source_classification` is `THIRD_PARTY_LICENSED` whenever the `source_type` is `THIRD_PARTY_FEED` or the `distributed_markets` array is non-empty, and is `FIRST_PARTY` in every other case. That classification is what the redistribution controls of §2.11 act on.

Freshness is a strict inequality against the logical clock. A source obtained exactly 180 days before the clock still counts as fresh; only a source obtained strictly more than 180 days before the clock is stale. The per-property tally of such sources is exposed as `Property.stale_source_count`, and one clerical rule protects the corpus from impossible evidence: an `obtained_at` later than the logical clock is refused, with the rejection carrying `ERR_SOURCE_FUTURE_DATED` (HTTP 409).

### 2.10 Two-Person Control on Attribute Verification

A `PropertyAttribute` is a single researched claim about a property — one `field_name`, such as `tenant_name`, `occupancy_pct` or `asking_rent_psf`, bound to one `value`. Each attribute names the `source_document_id` of the evidence authorizing it, states its own `attribute_market`, and carries a `revision_index` that begins at 1 and advances by one on every accepted change of the committed value. The claim's lifecycle is the `proposed_status` enumeration `NONE`, `PENDING`, `VERIFIED`, `REJECTED`; it begins at `NONE`, and `proposed_value` — the candidate value under review — begins null.

Four referential rules police attribute creation. The `field_name` must be unique per property, or the request is refused with `ERR_ATTRIBUTE_DUPLICATE_FIELD` (HTTP 409). The named `source_document_id` must belong to the same property as the attribute, or the request is refused with `ERR_ATTRIBUTE_SOURCE_MISMATCH` (HTTP 422). The `attribute_market` string must be byte-equal to the parent property's `market`, or the request is refused with `ERR_ATTRIBUTE_MARKET_MISMATCH` (HTTP 422). And when the claim derives from a `THIRD_PARTY_LICENSED` source, `from_third_party` must be true and `third_party_approved` must also be true, or the request is refused with `ERR_THIRD_PARTY_UNLICENSED` (HTTP 409). Both flags default to false, so a caller that says nothing about provenance gets a first-party claim and pays no licensing gate.

Verification is deliberately not a one-person operation. The user recorded as `created_by_user_id` — the analyst who framed the claim — may never be the user who verifies it, and an attempt to do so is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409). The `verifier_user_id` is stamped on the attribute when a review concludes, and `last_verified_at` records the instant of that review.

### 2.11 Redistribution Control and Licensed Reach

The platform sells access to data it has gathered, and its contracts are scoped by market. Three controls enforce that scope, and each carries its own identifier. A `THIRD_PARTY_LICENSED` source document may not be used to support an attribute or a listing in a market outside the acting organization's licensed markets; the rejection carries `ERR_UNAUTHORIZED_REDISTRIBUTION` (HTTP 409). An attribute that asserts `from_third_party` true while `third_party_approved` is false is refused with `ERR_THIRD_PARTY_UNLICENSED` (HTTP 409). A `LicenseSeat` whose `market` does not appear in its contract's `licensed_markets` array is refused with `ERR_SEAT_MARKET_NOT_LICENSED` (HTTP 409).

A fourth control is absolute and is never relaxed by the acting role. An `OFFICE` or `INDUSTRIAL` property may never be published or syndicated with a `monthly_rent_psf` above 500.00 dollars per square foot; any such request is refused outright with `ERR_UNAUTHORIZED_REDISTRIBUTION` (HTTP 409), regardless of who asks, who owns the listing, or what research state the property is in. This cap is a sanity guardrail on the listing product rather than a licensing matter, and it fires even for a `PlatformAdmin`.

Finally, contract terms have a reach ceiling. A subscription's market occupy-limit share may not exceed the roll-up share it is entitled to; a request that would breach that ceiling is refused with `ERR_SUBSCRIPTION_REACH_EXCEEDED` (HTTP 409), and the reach report described in §3.8 exposes both shares so an administrator can see how close a contract sits to it.

### 2.12 Nested Resource Retrieval

Many resources in this API are addressed beneath a parent: a source document or an attribute beneath a property, a seat beneath a contract, a subordination beneath a transaction. When a path names more than one resource identifier, the server resolves those identifiers from left to right and stops at the first one that does not resolve. That first failure produces the entity-specific not-found error and nothing else in the path is evaluated.

The not-found identifiers are specific to the entity being resolved: `ERR_ORGANIZATION_NOT_FOUND`, `ERR_USER_NOT_FOUND`, `ERR_PROPERTY_NOT_FOUND`, `ERR_ATTRIBUTE_NOT_FOUND`, `ERR_SOURCE_DOCUMENT_NOT_FOUND`, `ERR_TRANSACTION_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_SEAT_NOT_FOUND` and `ERR_ENFORCEMENT_CASE_NOT_FOUND`, each carrying HTTP 404. Two of these also cover a containment failure: an attribute that exists but belongs to a different property than the path names reports `ERR_ATTRIBUTE_NOT_FOUND`, and a seat that exists but belongs to a different contract than the path names reports `ERR_SEAT_NOT_FOUND`.

The path variables themselves are camel-cased and entity-specific, and the API uses the same spelling for a given entity everywhere it appears: `organizationId`, `userId`, `propertyId`, `attributeId`, `sourceDocumentId`, `leaseComparableId`, `transactionId`, `contractId`, `seatId`, `listingId`, `caseId`, `runId` and `usageEventId`. A path parameter is always resolved as described above before any body field is inspected, so a request that names a valid child beneath an invalid parent reports the parent's not-found error.

### 2.13 Optimistic Concurrency Control

Write operations that depend on a parent's state carry an explicit optimistic-concurrency precondition. Each such operation accepts a version field naming the parent it depends on and carrying the client's last observed `version` of that parent. If the parent's version has advanced since the client read it, the operation is rejected with `ERR_STALE_VERSION` and HTTP status 412. The comparison is a plain equality test between the supplied value and the parent's current `version`. It does not depend on two requests overlapping in time: a strictly sequential client that reads a version, waits for another writer to advance it, and then submits observes the same 412 rejection.

Three of these preconditions are the platform's designated race guards, and they are called out here in full. Submitting an attribute proposal against a property requires `expected_property_version`; if the property's version has moved since the client read it, the proposal is rejected with `ERR_STALE_VERSION` (412). Recording a renewal against a licensing contract requires `expected_contract_version`; this guard exists because a market addition changes both the contract's `licensed_markets` list and its `annual_fee_cents`, so a renewal priced from a stale view would be priced from terms that no longer hold. Assigning an occupant to a license seat requires `expected_contract_version` as well, because another writer may have changed the contract's seat composition since the client's view.

The remaining version-carrying operations follow the same mechanism against the same contract parent. Activating a pending contract, adding a licensed market to an active contract, exercising a termination, releasing a seat's occupant, and rebasing a seat's cycle fee each require `expected_contract_version`. Recording a licensed-market subordination on a sale transaction requires `expected_transaction_version`, compared against that transaction's own current `version`. All of these fields are non-optional on their respective operations, and every one of them rejects a mismatch with `ERR_STALE_VERSION` at HTTP status 412. No other operation accepts a version field.

### 2.14 Validation Order and Precedence

When a request fails more than one rule, the reported error is determined by a fixed precedence. The checks are evaluated in the following order, and the first failure is the one returned.

Authentication and request shape come first: a missing or empty `X-User-ID` or `X-User-Role` header surfaces as `ERR_UNAUTHENTICATED` (401), and a missing required field or a field that fails its declared type or enumeration surfaces as `ERR_INVALID_REQUEST` (400). Only once the request is well formed is authorization evaluated, and a role that is not permitted for the operation surfaces as `ERR_UNAUTHORIZED` (403). Existence follows, resolved left to right per §2.12, so a bad path identifier surfaces as its 404 not-found error ahead of any business rule.

Business safety comes next, before any state check: the redistribution and third-party licensing controls of §2.11 — `ERR_UNAUTHORIZED_REDISTRIBUTION`, `ERR_THIRD_PARTY_UNLICENSED` and `ERR_SEAT_MARKET_NOT_LICENSED`, each HTTP 409 — are evaluated before the target resource's state is inspected. State requirements come after safety, and a target that is not in the state a transition requires surfaces as `ERR_INVALID_STATE` (409), alongside the other state-family rejections `ERR_RENEWAL_LAPSED`, `ERR_RENEWAL_TERMINATED`, `ERR_TERMINATION_WINDOW_CLOSED`, `ERR_LITIGATION_NOT_ESCALATABLE` and `ERR_SUBSCRIPTION_INACTIVE`.

Referential integrity within the business model comes next, at HTTP 422: a subdivision originating from a property that is not `DRAFT` reports `ERR_SUBDIVISION_PARENT_INVALID`; an attribute whose `attribute_market` diverges from its property's `market` reports `ERR_ATTRIBUTE_MARKET_MISMATCH`; a lease whose `lease_end` is not strictly after its `lease_start` reports `ERR_LEASE_WINDOW_INVALID`; and a sale recorded on a property whose research state is neither `RESEARCHING` nor `VERIFIED` reports `ERR_SALE_PROPERTY_NOT_RESEARCHED`.

Uniqueness and occupancy constraints follow, at HTTP 409, and cover as many seats as the contract allows, reach ceilings, property-scoped field uniqueness and listing interval collisions. Temporal constraints come after that: a future-dated source, a subordination past its deadline, and a comparable whose lease ended before it was recorded report `ERR_SOURCE_FUTURE_DATED`, `ERR_SUBORDINATION_DEADLINE_PASSED` and `ERR_COMP_TEMPORAL_IMPOSSIBLE` respectively, all at HTTP 409. Fiscal floors are evaluated after temporal constraints: a non-positive annual fee reports `ERR_FEE_NOT_POSITIVE`, a non-positive gross sale price reports `ERR_SALE_PRICE_NOT_POSITIVE`, a settlement below the assessed penalty reports `ERR_SETTLEMENT_INSUFFICIENT`, and an escalation whose penalty sits below the litigation floor reports `ERR_PENALTY_BELOW_LITIGATION_FLOOR`.

The optimistic-concurrency precondition described in §2.13 is evaluated last of all. A request that both violates an earlier rule and carries a stale `expected_property_version` or `expected_contract_version` reports the earlier error, so `ERR_STALE_VERSION` (412) is observed only when every earlier check has passed.

## 3. Business Logic & Workflows

### 3.1 Opening a Research Record

A research cycle begins when a `ResearchAnalyst` registers a commercial building, supplying its `market`, its `address_line`, a `property_type` drawn from `OFFICE`, `RETAIL`, `INDUSTRIAL`, `MULTIFAMILY` or `HOSPITALITY`, a `rentable_sqft` figure that must be greater than zero, and an optional `classification` drawn from `CLASS_A`, `CLASS_B` or `CLASS_C`. When the caller omits `classification`, the record is created as `CLASS_B`. The record opens in the `DRAFT` research state with a `land_posture` of `OPEN` and an empty research dossier: `parent_property_id` is null because this is a root record, `attribute_verified_count`, `attribute_total_count` and `stale_source_count` all begin at zero, `completeness_pct` begins at 0.0, and `verified_sale_value_cents` begins at zero.

From `DRAFT` the record can move forward in one of three ways, and the choice between them is the analyst's. Starting research explicitly advances `research_status` to `RESEARCHING`. Finalizing attempts to publish the record, and the two rules that guard publication are stated in §3.4. Subdividing splits the record, and its rules are stated in §3.3.

The path from `RESEARCHING` to `VERIFIED` runs through the same finalize operation as the `DRAFT` to `VERIFIED` path, and the two are distinguished only by which research state the record currently holds. Both demand that the record hold the state the transition requires — a record in the wrong state is refused with `ERR_INVALID_STATE` (HTTP 409) — both demand that `land_posture` be `OPEN`, and both demand that the attribute set be non-empty. A finalize attempted on a property whose `attribute_total_count` is zero is refused with `ERR_EMPTY_ATTRIBUTE_SET` (HTTP 409), and a finalize attempted while any attribute on the property still sits in `PENDING` is refused with `ERR_ATTRIBUTES_UNRESOLVED` (HTTP 409). There is deliberately no `DRAFT` to `VERIFIED` edge that bypasses the attribute requirement, which means a wholly unevidenced record can never be published.

Publication is a mutation like any other. Whichever state the record held before finalization, the transition sets `research_status` to `VERIFIED`, recomputes `completeness_pct` under the `FINAL` variant described in §3.4, refreshes `updated_at`, and increments `version` by one. Starting research is the mirror image: it sets `research_status` to `RESEARCHING`, recomputes `completeness_pct` under the `PROVISIONAL` variant, refreshes `updated_at`, and increments `version` by one.

The first attribute claim laid against a `DRAFT` record advances it without anyone asking. The moment a new `PropertyAttribute` is created on a property whose `research_status` is still `DRAFT`, and provided that property's `land_posture` is not `FROZEN`, the server moves the record to `RESEARCHING` on its own, increments `attribute_total_count` by one, and recomputes `completeness_pct` under the `PROVISIONAL` variant. This automatic advance fires only while the property is `DRAFT`; a record already in `RESEARCHING` or `VERIFIED` is untouched by it.

### 3.2 The Attribute Review Cycle

Research claims move through a review cycle rather than a straight line, and the machine that governs a `PropertyAttribute` is genuinely cyclic. A newly created attribute sits at `proposed_status` `NONE`, holding its committed `value` and no pending candidate, because `proposed_value` starts out null. Submitting a candidate for review moves the attribute from `NONE` to `PENDING`, and rejecting that candidate moves it back to `NONE`, which is the first half of the cycle.

Proposing a value has its own guard set. The attribute must be in `NONE` — the `VERIFIED` to `NONE` re-open described below is the only other way in — and a proposal against an attribute already in `PENDING` is refused with `ERR_INVALID_STATE` (HTTP 409). The attribute's `attribute_market` must equal its property's `market` or the request is refused with `ERR_ATTRIBUTE_MARKET_MISMATCH` (HTTP 422). A claim whose `from_third_party` is true must also have `third_party_approved` true, or the request is refused with `ERR_THIRD_PARTY_UNLICENSED` (HTTP 409). The parent property's `land_posture` must be `OPEN`: a proposal against a `FROZEN` property is refused with `ERR_PROPERTY_FROZEN` (HTTP 409) and a proposal against a `RESTRICTED` property is refused with `ERR_PROPERTY_RESTRICTED` (HTTP 409). Finally, the proposal must carry `expected_property_version`, and a stale value is refused with `ERR_STALE_VERSION` (HTTP 412) per §2.13.

When a proposal is accepted, the attribute stores the submitted value in `proposed_value`, moves `proposed_status` to `PENDING`, and the parent property's `attribute_total_count`, `attribute_verified_count`, `land_posture` and `completeness_pct` are all recomputed under the `PROVISIONAL` variant. The parent's `version` is advanced by the proposal as well, because the recomputation is a mutation of the property.

Verification closes the loop from the other side. Moving an attribute from `PENDING` to `VERIFIED` requires that it be `PENDING` — anything else is refused with `ERR_INVALID_STATE` (HTTP 409) — requires the parent property's `land_posture` to be `OPEN` (a `FROZEN` parent yields `ERR_PROPERTY_FROZEN` and a `RESTRICTED` parent yields `ERR_PROPERTY_RESTRICTED`), and requires the reviewing user to differ from the attribute's `created_by_user_id`. A verifier who is also the author is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409). On success the pending value is promoted: `value` takes the contents of `proposed_value`, `proposed_value` is cleared back to null, `proposed_status` becomes `VERIFIED`, `revision_index` advances by one, `last_verified_at` is stamped with the logical clock, and `verifier_user_id` records the acting analyst. Both `attribute_verified_count` and `completeness_pct` are then recomputed under the `PROVISIONAL` variant.

Rejection is the shorter branch and is specified with equal force. A rejection requires only that the attribute be `PENDING` — a rejection of anything else is refused with `ERR_INVALID_STATE` (HTTP 409) — and it accepts an optional `reason` recording why the candidate was turned down, clears `proposed_value` back to null while setting `proposed_status` to `NONE`. The parent property's `attribute_verified_count` and `completeness_pct` are recomputed under the `PROVISIONAL` variant, exactly as on the verification branch. A rejected candidate is not lost: the attribute is back in `NONE` and may be proposed again, and a `REJECTED` proposal is counted in neither the numerator nor the denominator of the completeness score.

The cycle's second half is re-opening. A fresh proposal submitted against an attribute already in `VERIFIED` sets `proposed_status` back to `NONE` and clears `proposed_value` to null, and the parent property's `attribute_verified_count` and `completeness_pct` are recomputed under the `PROVISIONAL` variant so that the championed value no longer counts as verified while a new candidate is in flight. Together with the rejection branch this is why the attribute machine is a cycle rather than a pipeline: `NONE` to `PENDING` to `VERIFIED` back to `NONE`, and `NONE` to `PENDING` back to `NONE`, are both reachable.

A candidate value enters the corpus without a formal rejection, and it can leave it the same way. The only two states that hold an unreviewed candidate are `PENDING`, which is cleared by rejection or promoted by verification.

### 3.3 Evidence in the Field, and Subdivision

Attaching evidence requires the analyst to state where it came from and when it was gathered. A `SourceDocument` records a `source_type`, a `source_name`, a `contact_method` and an `obtained_at` instant, may carry a `distributed_markets` array, and is bound to its property through the `property_id` recorded on it. The server derives `source_classification` from those inputs per §2.9, and then recomputes the property's `stale_source_count` and `completeness_pct`. A source whose `obtained_at` lies in the future of the logical clock is refused with `ERR_SOURCE_FUTURE_DATED` (HTTP 409) — the rules for computed counts are in §3.4.

Attaching evidence to a `RESTRICTED` property is refused with `ERR_PROPERTY_RESTRICTED` (HTTP 409), and attaching evidence to a `FROZEN` property is refused with `ERR_PROPERTY_FROZEN` (HTTP 409). A property is pushed into `RESTRICTED` or `FROZEN` posture by the market escalations described in §3.7, and while it sits there its evidence ledger is closed to new rows.

Lease comparables are the second form of fieldwork. A comp is recorded against a property with a `tenant_name`, a `lease_start`, a `lease_end`, an `escalated_rent_psf`, an `effective_rent_psf` and an optional `renewal_option` boolean that defaults to false. The server stamps `recorded_at` with the logical clock. Two temporal rules guard the row. The `lease_end` must be strictly after the `lease_start`, or the request is refused with `ERR_LEASE_WINDOW_INVALID` (HTTP 422). And a comparable whose `lease_end` precedes the instant it was recorded is impossible, so it is refused with `ERR_COMP_TEMPORAL_IMPOSSIBLE` (HTTP 409). The `effective_rent_psf` is the concession-adjusted figure that feeds index construction in §3.5; the `escalated_rent_psf` is the contracted schedule and is carried for reference.

Sale transactions are the third. A sale is recorded against a property with a `buyer_name`, a `close_date` and a `gross_sale_price_cents` that must be strictly positive — a non-positive price is refused with `ERR_SALE_PRICE_NOT_POSITIVE` (HTTP 409). A sale may only be recorded on a property whose `research_status` is `RESEARCHING` or `VERIFIED`, so a sale against a `DRAFT` record is refused with `ERR_SALE_PROPERTY_NOT_RESEARCHED` (HTTP 422). On creation the server derives `subordination_deadline` as exactly ten days after the `close_date`, sets `subordination_status` to `PENDING`, sets `subordinated_at` and `subordinating_case_id` to null, starts `rolled_attributions` at zero, and computes `cap_rate_bps` by the rule in §3.5.

Subdividing a record is the analyst's way of splitting a building into separately researched components. It is available only from a root record still in `DRAFT`: a subdivision originating from a property whose `research_status` is not `DRAFT` is refused with `ERR_SUBDIVISION_PARENT_INVALID` (HTTP 422). A root record under `FROZEN` posture is likewise refused, with `ERR_PROPERTY_FROZEN` (HTTP 409). The payload supplies the child's `market`, `address_line`, `property_type`, `rentable_sqft` and optional `classification`, and the server creates a new property whose `parent_property_id` points back at the source record, whose `research_status` is `DRAFT`, and whose `land_posture` is `OPEN`. The source record keeps its own `research_status` of `DRAFT` so that it remains able to branch again, and it is otherwise unchanged apart from a refreshed `updated_at` and an incremented `version`. The dependency runs one way — a child is never the parent of its own ancestor — which is what keeps the subdivision graph a forest.

### 3.4 Data-Quality Scoring: The Weighted Completeness Score

Every property carries a `completeness_pct` score that is the platform's summary judgement of how well-evidenced its record is. The score is built from the property's own attribute set. The numerator walks the attributes whose `proposed_status` is `NONE`, `PENDING` or `VERIFIED`, and the denominator walks that same set, so attributes in those three states are counted on both sides. Attributes in the `REJECTED` state are excluded from the numerator and from the denominator alike.

Each attribute in the set contributes one of three weights to the numerator. A `VERIFIED` attribute whose named source document exists on the property and was obtained within the freshness window — that is, at most 180 days, the `SOURCE_FRESHNESS_DAYS` constant, before the logical clock — contributes 1.0, the `WEIGHT_VERIFIED_SOURCED` weight. A `VERIFIED` attribute whose source is missing, or whose source is strictly more than 180 days old, contributes 0.6, the `WEIGHT_VERIFIED_UNSOURCED` weight. Every attribute in any other state contributes 0.0, the `WEIGHT_UNVERIFIED` weight. The freshness test is written as a strict comparison: a source obtained exactly 180 days before the clock counts as fresh and earns the full weight.

The base score is one hundred multiplied by the numerator sum, divided by the count of attributes in the scoring set. When that count is zero the score is 0.0 outright — a property with no attributes in the scoring set, whether because it has none at all or because every one of them is `REJECTED`, scores zero rather than dividing by zero. A staleness penalty is then subtracted: 0.1, the `WEIGHT_STALE_PENALTY`, for every source document on the property whose `obtained_at` is strictly more than 180 days before the logical clock. The result is rounded half up to two decimal places, and the rounded value is then clamped upward at zero so that the reported score is never negative.

The score has two variants, and the choice between them is not the caller's — it is decided by which operation is running. The `PROVISIONAL` variant applies whenever the score is recomputed as a side effect of a child mutation or of starting research: it fires on a proposal, a verification, a rejection, a source attachment, the automatic research advance and the explicit start of research. The `FINAL` variant applies only when a property is finalized from `RESEARCHING` to `VERIFIED`.

The two variants differ in exactly one respect, and it is a severe one. Under `PROVISIONAL`, a `VERIFIED` attribute whose source is missing or stale scores 0.6, the `WEIGHT_VERIFIED_UNSOURCED` weight. Under `FINAL`, that same unevidenced claim scores 0.0 — once a record is published, a claim with no fresh evidence behind it is worth nothing. The 1.0 weight for a fresh sourced claim and the exclusion of `REJECTED` attributes are identical in both variants. On the canonical fixture of a two-attribute property in which one verified attribute rests on a fresh deed and the other verified attribute rests on a source that is 243 days old, with no other sources present, the provisional score is 79.90 and the final score is 49.90 — the published value is exactly 30.00 points lower on identical rows.

The property's `land_posture` is derived from the same raw material, and it is a gate rather than a statistic. It is `OPEN` when no unverified attribute burden and no stale-source burden is present, `RESTRICTED` when the property has been placed under a market escalation while it was still `DRAFT` or `RESEARCHING`, and `FROZEN` when a formerly `VERIFIED` property has been placed under a market escalation. `OPEN` is the state a property holds at creation and the state it must hold for finalize to be permitted; `RESTRICTED` blocks new evidence attachment and attribute proposals; `FROZEN` blocks finalize, the start of research and subdivision.

The property's own counters move with all of this. `attribute_total_count` counts this property's `PropertyAttribute` rows without regard to status, while `attribute_verified_count` counts only those whose `proposed_status` is `NONE` or `VERIFIED` — the two states that represent a claim the record is willing to stand behind. Every recomputation of those counters, of `land_posture`, or of `completeness_pct` is a mutation that refreshes the property's `updated_at` and advances its `version`, which is why the optimistic-concurrency guard of §2.13 remains meaningful across a busy research session.

### 3.5 Analytics: Indices, Forecasts and Capitalization

An `AnalyticsRun` is the record of one analytical product produced for a market. A run states its `market`, its `run_type` — `INDEX` or `FORECAST` — and, for an index, an `adjustment_mode` from `UNADJUSTED` or `HEDONIC` that defaults to `UNADJUSTED`. An index run is bounded by a `window_start`, which is the inclusive lower bound of its comparable window, and a `window_end`, which is the exclusive upper bound.

The `market_index_value` calculation assembles the comparable set for that window. A lease comparable qualifies when its property's `market` equals the run's market, when its comparable interval overlaps the window under the half-open test `lease_start` at or before `window_end` and `lease_end` strictly after `window_start`, and when three refinements hold: the comparable's property has `research_status` `VERIFIED`; the comparable's property is not named in the request's optional `excluded_property_ids` list; and the comparable's property does not sit under `FROZEN` or `RESTRICTED` posture. The interval test is deliberately asymmetric: a comparable whose `lease_end` equals `window_start` is excluded, while one whose `lease_start` equals `window_end` is included.

Each qualifying comparable contributes to the mean exactly once, no matter how many attributes its property carries — the mean is taken over comparables, not over attributes. When two or more comparables tie on `effective_rent_psf`, none is dropped and none wins: every tied comparable enters the arithmetic mean, and the reported count includes all of them, because the order of an arithmetic mean is irrelevant to its value.

When the refined set is empty, the run carries no index value: `index_value` is null and `comp_count` is 0, and the endpoint reports `ERR_EMPTY_INDEX_SET` (HTTP 409). Otherwise `index_value` and `mean_effective_rent_psf` are both the arithmetic mean of the refined set's `effective_rent_psf` values, rounded half up to two decimal places, `comp_count` is the exact size of the refined set, and `median_effective_rent_psf` is the median of those same values. The `adjustment_mode` selects between two variants of the same computation. Under `UNADJUSTED` — the `unadjusted` variant, and the one a request gets by default — the value is exactly the raw mean just described. Under `HEDONIC` — the `hedonic_adjusted` variant — each comparable is first adjusted by a per-comparable log-linear correction for its property's classification and for bundle co-location before the mean is taken, so identical inputs yield a different index value than the unadjusted variant produces, and the two diverge whenever any comparable's class differs from the market's modal class.

A forecast run projects one of those index values forward. The `market_forecast` calculation begins by selecting the base run according to the request's `selector`, which is one of `LATEST`, `EARLIEST` or `UPPER_BOUND` and defaults to `LATEST` when the request omits it. Under `LATEST` — the `latest_actual` variant — the base is the `index_value` of the most recent qualifying run for the market; under `EARLIEST` — the `oldest_actual` variant — the base is the `index_value` of the earliest qualifying run for the market; under `UPPER_BOUND`, the base is the `index_value` of the qualifying run carrying the greatest `index_value`, and if two or more runs tie on that value the selection is ambiguous and is reported as `AMBIGUOUS_SELECTION` rather than being resolved by any row identifier. Only runs whose market matches the requested market are candidates, and runs published after the request's due date are excluded from candidacy. The choice among the selectors is consequential rather than cosmetic: the same market and the same inputs forecast strictly higher under `EARLIEST` than under `LATEST` whenever the market's index series has risen across its runs.

With a base selected, the projection applies a compounding growth: the growth factor is one plus 0.015, the `base_growth_rate`, raised to the power of the `horizon_quarters`, which is four when the request omits it. That factor is floored at 0.90, the `MIN_GROWTH_FACTOR`, and capped at 1.35, the `MAX_GROWTH_FACTOR`. The base index value is multiplied by the clamped factor, and the product is rounded half up to two decimal places to give `forecast_value`. A forecast run leaves `forecast_value` null when the run is an index run. The run's `forecast_due_at` is the window end advanced by the forecast horizon, and the `horizon_quarters` input is accepted so that a caller may shorten or lengthen that projection.

Building an index or a forecast also leaves a trace in the record-count ledger. `attributed_records_delta` records how many records the run contributes to its market's attributed-record count; it is set to the run's `comp_count` when the run is created and is set to 0 when the run's attribution is removed. A run's `attribution_status` is `ATTRIBUTED` while it contributes and `UNWOUND` once its records have been removed, and an attribution removal by a licensing or enforcement administrator is what performs that transition. Removal never touches the historical index value; it only withdraws the run's contribution to the market's current count.

Two further calculations belong to property-level records. The `cap_rate_bps` calculation is triggered both when a sale transaction is recorded against a property and when a subordination is recorded against a transaction. It takes the property's in-place income from the attribute whose `field_name` is `in_place_income_annual_cents` and whose `proposed_status` is `VERIFIED`. When that verified figure is strictly greater than 250,000,000 cents, the calculation takes the `verified_income` variant: it uses the researched figure and records its income source as `VERIFIED`. When the figure is 250,000,000 cents or lower — including the case where the property carries no verified `in_place_income_annual_cents` attribute at all, in which case the figure is read as 0 — the calculation instead takes the `substitute_income` variant: it substitutes 250,000,000 cents, the `SUBSTITUTE_INCOME_CENTS` constant, and records its income source as `SUBSTITUTE`. The boundary is deliberately strict: an in-place income of exactly 250,000,000 cents takes the substitute branch. One hundred times the ten-thousands scaled ratio of income to `gross_sale_price_cents` is then rounded half up to a whole number of basis points and stored as `cap_rate_bps`. On a five-billion-cent sale price the two variants disagree plainly: a researched income of 300,000,100 cents yields 600 basis points, while the substitute income of 250,000,000 cents yields 500.

The `property_stale_source_count` calculation is equally simple and equally strict. It counts the `SourceDocument` rows attached to a property whose `obtained_at` is strictly more than 180 days before the logical clock, and reports that count as `stale_source_count`. A source obtained exactly 180 days before the clock is fresh and is not counted; only strictly older sources contribute. The trigger for this recomputation is any source-document creation and the periodic research cycle.

### 3.6 Subscription Licensing: Contracts and Seats

A `LicensingContract` is how a subscriber organization buys access to the corpus. It is created against a subscriber organization by supplying the `subscriber_organization_id`, a `product` from `CORE_MARKET_DATA`, `ANALYTICS_INDEX`, `LISTING_SERVICE` or `GLOBAL_ALL`, the `licensed_markets` array the subscription reaches, a `seat_count`, an `annual_fee_cents`, and a `term_start` and `term_end`. Several fields are optional and carry defaults. `monthly_index_fee_cents`, the per-active-market monthly index fee, defaults to 0 and is meaningful only when the product is `ANALYTICS_INDEX`. `auto_renew` defaults to true. `renewal_notice_days` defaults to 30. `audit_intensity`, which governs whether a redistribution finding may be escalated to litigation, defaults to `STANDARD` and may instead be set to `ENHANCED`.

Every market in `licensed_markets` must be unique within the array. The `seat_count` must be at least one, and the `annual_fee_cents` must be strictly positive — a non-positive fee is refused with `ERR_FEE_NOT_POSITIVE` (HTTP 409). The `term_end` must be strictly after the `term_start`. A newly created contract holds the status `PENDING`, its `renewal_decision` is `NONE`, and its `renewal_due_at` is computed as the `term_end` minus `renewal_notice_days` days. Creating the contract recomputes the subscriber organization's `authorized_market_count`.

Activation turns a pending contract into a live one, and it is guarded four ways. The contract must currently hold `PENDING` — any other state is refused with `ERR_INVALID_STATE` (HTTP 409). At least one `LicenseSeat` must exist on the contract, or the request is refused with `ERR_NO_SEATS` (HTTP 409). Every seat's `market` must appear in the contract's `licensed_markets`, or the request is refused with `ERR_SEAT_MARKET_NOT_LICENSED` (HTTP 409). And the request must carry `expected_contract_version` matching the contract's current `version`, or it is refused with `ERR_STALE_VERSION` (HTTP 412). A successful activation sets the status to `ACTIVE`, recomputes `renewal_due_at` as the term end minus the notice days, recomputes the subscriber organization's `authorized_market_count` and `active_contract_count`, and increments the contract's `version`.

A `LicenseSeat` is a per-market entitlement drawn from a contract. It is created with a `market`, an optional `index_tier` from `TIER_1`, `TIER_2` or `TIER_3` that defaults to `TIER_2`, and the `last_usage_cycle` instant that begins the billing cycle its counters belong to. The seat's `market` must appear in the contract's `licensed_markets` or the request is refused with `ERR_SEAT_MARKET_NOT_LICENSED`. Creating the seat also enforces the contract's capacity: a creation that would push the number of seats on the contract past its `seat_count` is refused with `ERR_SEAT_CAPACITY_EXCEEDED` (HTTP 409). A new seat starts unoccupied, with `occupant_user_id` null, `monthly_active_days` zero, `monthly_unauthorized_markets` an empty array, `distinctive_ip_count` zero, `shared_flag` false, `access_revoked` false, `overage_fee_cents` zero, `owner_user_id` null, and both `owner_share_pct` and `billed_owner_share_pct` zero. Creating a seat increments the contract's `version`.

Seat occupancy is the assignment machine. A seat begins `UNASSIGNED`, with no occupant. Assigning an occupant moves it to `ASSIGNED` and requires four conditions: the seat must currently have `occupant_user_id` null, or the request is refused with `ERR_SEAT_ALREADY_ASSIGNED` (HTTP 409); the nominated user's `status` must be `ACTIVE`, or the request is refused with `ERR_USER_INACTIVE` (HTTP 409); the nominated user's `organization_id` must equal the contract's `subscriber_organization_id`, or the request is refused with `ERR_USER_OUT_OF_SCOPE` (HTTP 409); and the contract's status must be `ACTIVE` or `GRACE`, or the request is refused with `ERR_SUBSCRIPTION_INACTIVE` (HTTP 409). The request also carries `expected_contract_version` and is refused with `ERR_STALE_VERSION` (HTTP 412) if the contract has moved since the client read it. On success the seat records the assigned user in `occupant_user_id`, sets `access_revoked` to false, and increments the contract's `version`.

Releasing an occupant moves a seat from `ASSIGNED` back to `UNASSIGNED` and requires only that the seat currently have a non-null occupant — anything else is refused with `ERR_INVALID_STATE` (HTTP 409). It clears `occupant_user_id` to null and increments the contract's `version`, again guarded by `expected_contract_version` with `ERR_STALE_VERSION` (HTTP 412) on a mismatch. The third movement out of `ASSIGNED` is to the terminal state `REVOKED`, which is never requested directly: the server revokes a seat automatically when its contract reaches `LAPSED` or `TERMINATED`, and when a litigation escalation targets the seat's contract. Revocation sets `access_revoked` to true and clears `shared_flag` back to false. A `REVOKED` seat is terminal — it can never be reassigned, and the only way to restore service is to provision a fresh seat row on a new contract.

Term and renewal are what keep a subscription alive. The contract's `status` runs across `PENDING`, `ACTIVE`, `GRACE`, `RENEWED`, `LAPSED` and `TERMINATED`, and `TERMINATED` is its only terminal state. Recording an auto-renewal out of `ACTIVE` requires that `auto_renew` be true, or the request is refused with `ERR_AUTO_RENEW_DISABLED` (HTTP 409); requires that `renewal_decision` not be `TERMINATED`, or the request is refused with `ERR_RENEWAL_TERMINATED` (HTTP 409); and requires the logical clock to be strictly before `renewal_due_at`, or the request is refused with `ERR_RENEWAL_LAPSED` (HTTP 409). The request supplies a `new_term_end` and a `new_annual_fee_cents` and carries `expected_contract_version`, with a stale value refused as `ERR_STALE_VERSION` (HTTP 412). On success the previous term end becomes the new `term_start`, `term_end` takes the supplied `new_term_end`, `annual_fee_cents` takes the supplied `new_annual_fee_cents`, the status becomes `RENEWED`, `renewal_decision` resets to `NONE`, `renewal_due_at` is recomputed, the subscriber organization's `active_contract_count` is recomputed, and the contract's `version` increments.

A renewed contract does not stay renewed for long. As soon as the renewed term start reaches the logical clock, the server moves the contract automatically from `RENEWED` back to `ACTIVE` and recomputes the subscriber organization's `active_contract_count`. That edge is what makes the contract machine cyclic: `ACTIVE` to `RENEWED` and back to `ACTIVE` is a loop the system can traverse repeatedly across successive terms.

Exercising a termination is the administrator's route out of the relationship, and it is available from two states with different windows. From `ACTIVE`, the logical clock must be strictly before `renewal_due_at`, or the request is refused with `ERR_TERMINATION_WINDOW_CLOSED` (HTTP 409), and the contract must be `ACTIVE` or the request is refused with `ERR_INVALID_STATE` (HTTP 409). From `GRACE`, the logical clock must be strictly before `term_end`, or the request is refused with `ERR_TERMINATION_WINDOW_CLOSED` (HTTP 409). Both branches set the status to `TERMINATED` and `renewal_decision` to `TERMINATED`, revoke every seat on the contract, and recompute the subscriber organization's `active_contract_count`; the `ACTIVE` branch additionally increments the contract's `version`, and the request from either branch carries `expected_contract_version`.

Adding a market to an active contract is a priced mutation. The request supplies a `market` that must not already be present in `licensed_markets` — a duplicate is refused with `ERR_MARKET_ALREADY_LICENSED` (HTTP 409) — and the contract must be `ACTIVE`, or the request is refused with `ERR_INVALID_STATE` (HTTP 409). The contract's status must be current and the client's `expected_contract_version` must match, or the request is refused as `ERR_STALE_VERSION` (HTTP 412). On success the market is appended to `licensed_markets` and the contract's `annual_fee_cents` is increased by the market-addition fee computed in §3.8, the subscriber organization's `authorized_market_count` is recomputed, and the contract's `version` increments. A market addition is precisely the kind of change that invalidates a renewal quoted from an earlier read, which is why renewal carries an OCC guard.

Seat usage counters are refreshed by the field monitoring described in §3.8 and §3.9, and their cycle fees are rebased either by the periodic cycle or by an explicit fee rebase. A fee rebase recomputes `overage_fee_cents` from the seat's cycle counters and recomputes `billed_owner_share_pct` under the `monthly_cycle` variant of the attribution rule, guards the request with `expected_contract_version` and `ERR_STALE_VERSION` (HTTP 412), and increments the contract's `version`.

### 3.7 Enforcement, Litigation and Market Re-Grading

When redistribution is detected, an `EnforcementOfficer` opens an `EnforcementCase` against the organization that redistributed and the `contract_id` implicated in the finding. The case states a `case_type` of `AUDIT` or `LITIGATION`, a `finding_cents` value that is the assessed worth of the unauthorized redistribution and must be at least zero, and a `fee_rate_pct` that is the contractual penalty multiplier — 1.5 means 150 percent. A newly opened case holds the status `OPEN`, and the server computes its `penalty_cents` as `finding_cents` multiplied by `fee_rate_pct`, rounded half up to a whole number of cents. The same computation decides whether the case is eligible for escalation: the case is escalatable when its `penalty_cents` is at least 75,000,000 cents, the `LITIGATION_PENALTY_THRESHOLD_CENTS` constant, and that floor is inclusive — a penalty exactly equal to the threshold is escalatable.

Escalating an audit to litigation is the heaviest action in the system. Four conditions guard it, and all four must hold. The case must be an `AUDIT` case, so an attempt to escalate a case already typed `LITIGATION` is refused with `ERR_LITIGATION_NOT_ESCALATABLE` (HTTP 409). The case must currently be `OPEN`, or the request is refused with `ERR_INVALID_STATE` (HTTP 409). The case's `penalty_cents` must be at least the litigation floor, or the request is refused with `ERR_PENALTY_BELOW_LITIGATION_FLOOR` (HTTP 409). And the underlying contract's `audit_intensity` must be `ENHANCED` — a contract written on `STANDARD` audit intensity cannot be escalated at all, and an attempt is refused with `ERR_LITIGATION_NOT_PERMITTED` (HTTP 409).

A successful escalation cascades in three directions. The case itself moves to `ESCALATED` and records `escalated_at` as the logical clock. A new `LITIGATION` case is created with `escalated_from_case_id` pointing back at the audit case and with status `ESCALATED`, so the escalation lineage is addressable. And the respondent `Organization` is suspended: its `status` becomes `SUSPENDED`, which gates every seat of that organization from recording usage, while every one of its licensing contracts that currently holds `ACTIVE` or `GRACE` is driven to `TERMINATED` with every seat on those contracts revoked by setting `access_revoked` to true. The organization's `active_contract_count` is recomputed at the end of that cascade, and a later attempt to move a seat of that organization produces `ERR_SUBSCRIPTION_INACTIVE` (HTTP 409) because the contract no longer holds `ACTIVE` or `GRACE`.

Settlement is the way back. Settling an escalated case requires that the case currently hold `ESCALATED` — anything else is refused with `ERR_INVALID_STATE` (HTTP 409) — and requires the supplied `settlement_cents` to be at least the case's `penalty_cents`, or the request is refused with `ERR_SETTLEMENT_INSUFFICIENT` (HTTP 409). On success the case becomes `SETTLED` and the respondent organization returns to `ACTIVE`. The suspension's contract casualties are repaired rather than merely masked: every licensing contract of that organization which this escalation terminated is restored to `ACTIVE`, the `access_revoked` flag on the seats of those contracts is reset to false, and the organization's `authorized_market_count` is recomputed. Settlement and withdrawal are the terminal outcomes available to a case; a `SETTLED` or `WITHDRAWN` case accepts no further transitions.

Not every case ends in litigation. Withdrawing an `OPEN` case sets its status to `WITHDRAWN` and requires only that the case still hold `OPEN`, with anything else refused as `ERR_INVALID_STATE` (HTTP 409). Withdrawal is the low-cost exit for a finding that does not merit pursuit.

Market escalation is the enforcement officer's instrument for re-grading an entire market rather than a single organization. A market-escalations report accepts a `markets` array and a `reason_code`, and it responds with the `escalated_property_ids` it acted on together with the `escalated_count`. The report re-grades in two directions. Every property whose `market` lies in the named array and whose `research_status` is `DRAFT` or `RESEARCHING` has its `land_posture` set to `RESTRICTED`, which immediately closes its evidence ledger to new source documents and blocks further attribute proposals. Every property in those markets whose `research_status` is `VERIFIED` is instead frozen: its `research_status` drops back to `RESEARCHING`, its `land_posture` becomes `FROZEN`, and every `PropertyAttribute` on it whose `proposed_status` is `PENDING` is reset to `NONE` with its `proposed_value` cleared. Those recomputations refresh each affected property's `completeness_pct` under the `PROVISIONAL` variant, because the property's stale-source burden enters the score and source documents may have aged since the last computation. A request that targets a property the escalation does not cover — one not in any named market, or one whose research state is not one the transition accepts — is refused with `ERR_INVALID_STATE` (HTTP 409), and the caller's own organization must be `ACTIVE`. The frozen property's discipline is strict: while it sits at `FROZEN`, finalize, the explicit start of research and subdivision are all refused with `ERR_PROPERTY_FROZEN` (HTTP 409), and while it sits at `RESTRICTED`, new evidence attachment and attribute proposals are refused with `ERR_PROPERTY_RESTRICTED` (HTTP 409).

Sale subordination is the fourth enforcement instrument, and it is a per-transaction action rather than a per-organization one. Recording a subordination moves a `SaleTransaction` from `PENDING` to `SUBORDINATED`, and it is guarded three ways. The transaction's `subordination_status` must currently be `PENDING`, or the request is refused with `ERR_INVALID_STATE` (HTTP 409). The logical clock must be strictly before the transaction's `subordination_deadline`, or the request is refused with `ERR_SUBORDINATION_DEADLINE_PASSED` (HTTP 409). And the request must carry `expected_transaction_version` matching the transaction's own current `version`, or it is refused with `ERR_STALE_VERSION` (HTTP 412). On success the transaction records `SUBORDINATED`, stamps `subordinated_at` with the logical clock, and stores the supplied `subordinating_case_id` as the case that subordinated it. The property is not left stale by this: its `verified_sale_value_cents` is recomputed as the sum of `gross_sale_price_cents` across that property's transactions whose `subordination_status` is `SUBORDINATED`, so the property's verified sale total only ever includes subordinated sales. Where the subordination is rolled into a market index, the transaction's `rolled_attributions` counter is incremented by one.

A transaction that is never subordinated does not wait forever. When the logical clock reaches a `PENDING` transaction's `subordination_deadline`, the periodic cycle moves it automatically from `PENDING` to `LAPSED`, and the property's `verified_sale_value_cents` is recomputed. `SUBORDINATED` and `LAPSED` are both terminal for the transaction.

### 3.8 The Listing Product and Subscription Reach

Brokerages publish availabilities through a `Listing`, and those published availabilities are themselves research input. A `BrokerPublisher` creates a listing against a property by supplying `organization_id`, a `listing_type` from `AVAILABLE`, `LEASED` or `SOLD`, a `monthly_rent_psf`, an `available_sqft` that must be greater than zero, and a `duration_days` that must be at least one. A new listing holds the status `DRAFT`; the `published_at` instant, the `expires_at` instant, the `redistributed_markets` array and the status all take their values at publication, not at creation.

Publication is where the rules bite. Publishing a `DRAFT` listing as research input requires all six of the following. The listing must currently hold `DRAFT`, or the request is refused with `ERR_INVALID_STATE` (HTTP 409). The listing's `organization_id` must equal the acting user's organization, or the request is refused with `ERR_UNAUTHORIZED` (HTTP 403). The property's `land_posture` must be `OPEN` — a `FROZEN` property yields `ERR_PROPERTY_FROZEN` and a `RESTRICTED` one yields `ERR_PROPERTY_RESTRICTED`, both HTTP 409. The origin market must lie inside the publishing organization's licensed markets, or the request is refused with `ERR_UNAUTHORIZED_REDISTRIBUTION` (HTTP 409). No other `PUBLISHED` listing of the same property may hold an availability interval overlapping the interval from `published_at` to `expires_at`, or the request is refused with `ERR_LISTING_OVERLAP` (HTTP 409). And for an `OFFICE` or `INDUSTRIAL` property, the `monthly_rent_psf` must not exceed 500.00 — the absolute guardrail of §2.11 — with a breach refused as `ERR_UNAUTHORIZED_REDISTRIBUTION` (HTTP 409) no matter which role asks.

A successful publication sets the status to `PUBLISHED`, stamps `published_at` with the logical clock, and sets `expires_at` to that instant plus the requested `duration_days` days. It also reconciles the property's own record from the listing: the property's `asking_rent_psf` and `available_sqft` attributes are updated from the listing's values, which is how a broker's availability becomes a research input rather than sitting beside the corpus.

Syndicating a `PUBLISHED` listing into an additional market appends that market to the listing's `redistributed_markets` array, and the `OFFICE` and `INDUSTRIAL` rent-cap guardrail applies to a syndication exactly as it does to a publication, regardless of the acting role. Withdrawal releases the property's availability interval so a later publication can claim it: a `BrokerPublisher` moving a listing from `PUBLISHED` to `WITHDRAWN` requires only that the listing currently hold `PUBLISHED`, or the request is refused with `ERR_INVALID_STATE` (HTTP 409). A listing that is neither withdrawn nor renewed does not linger indefinitely: when the logical clock reaches a `PUBLISHED` listing's `expires_at`, the system moves it automatically to `EXPIRED`. Both `WITHDRAWN` and `EXPIRED` are terminal, and the listing machine never returns to `DRAFT` — its path is `DRAFT` to `PUBLISHED`, and then to `WITHDRAWN` or to `EXPIRED`.

Reach is reported rather than merely enforced. A subscription-reach report, filed by a licensing administrator with a `contract_id`, returns the contract's `occupy_limit_share_bps` together with the `rollup_share_bps` it is measured against and a `reach_ok` boolean, and it recomputes the organization's `authorized_market_count` as a side effect. A subscription whose occupy-limit share exceeds its entitled roll-up share is refused with `ERR_SUBSCRIPTION_REACH_EXCEEDED` (HTTP 409), so the report is the tool an administrator uses to see how close a contract sits to that ceiling before it is breached.

### 3.9 Usage Monitoring and Seat Attribution

Every dataset download, report export, bulk lookup or API query by a subscriber-side seat is recorded as a `UsageEvent` against the `seat_id` of the seat that produced it. The event states the `market` accessed, an `event_type` from `DATASET_DOWNLOAD`, `REPORT_EXPORT`, `BULK_LOOKUP` or `API_QUERY`, a `record_count` that must be at least zero, a `distinguishing_ip`, and the `occurred_at` instant of the access. The event's `user_id` records the credential presented, which may differ from the seat's `occupant_user_id` — that divergence is precisely the signal the monitoring exists to catch. A `UsageEvent` is immutable, so it carries only `id` and `created_at` and has no `updated_at` or `version`; the mutable counters it feeds live on the seat.

Recording an event refreshes the seat's whole monitoring picture. `monthly_active_days` counts the distinct calendar days, in UTC, on which the seat recorded at least one event — several events on one day count once, and the logical clock's date defines "today". `monthly_unauthorized_markets` is the deduplicated set of markets the seat was observed accessing that are absent from the contract's `licensed_markets`, so an access outside the licensed footprint lands in that array exactly once no matter how many times it repeats. `distinctive_ip_count` is the number of distinct source IP addresses seen for the seat in the cycle, and `shared_flag` is set to true when that count exceeds the tier's sharing threshold. Recording an event also appends the event to the ledger, recomputes the seat's `overage_fee_cents` by the rule in §3.10, and recomputes the seat's interim sharing attribution.

That interim attribution is the `seat_owner_attribution` calculation, and it runs in two variants that differ only in the width of the window they examine. The `weekly_snapshot` variant — the base variant, fired on every usage event — examines the seven-day window that begins at the seat's `last_usage_cycle` and runs to that instant plus seven days. The `monthly_cycle` variant — the billed variant, run by the periodic research cycle — examines the thirty-day window that begins at the same `last_usage_cycle`. In both variants the window's lower bound is inclusive and its upper bound is exclusive, calendar days are UTC dates, and the same eight steps are evaluated in the same pinned order.

The first step builds the window's event set, selecting events by the seat's identifier and by `occurred_at` falling inside the window. The second derives, for each IP address, the set of calendar days on which that IP produced at least one event. The third counts `party_days` — the calendar days in the window on which two or more distinct IPs each produced at least one event. The fourth computes the party fraction as `party_days` divided by the number of calendar days in the window, which is seven under `weekly_snapshot` and thirty under `monthly_cycle`. The fifth selects the `busiest_ip`, which is the IP with the largest set of active days, breaking a tie by taking the lexicographically smallest IP string. The sixth derives `owner_user_id` as the `user_id` of the earliest event on the busiest IP by `occurred_at`, breaking a tie by the earliest `created_at` and breaking a further tie by the lexicographically smallest `distinguishing_ip` — never by any row identifier. The seventh computes the owner's share as the party fraction multiplied by the count of events attributable to the owner, divided by the count of all events in the window. The eighth rounds that share, multiplied by one hundred, half up to two decimal places to give `owner_share_pct`. When the window contains no events at all, `owner_user_id` is null and `owner_share_pct` is 0.

Because the window width changes the party fraction and the event count, the two variants disagree on identical rows: a seat whose activity is concentrated in the first week will show a different `owner_share_pct` under the billed thirty-day view than it does under the seven-day snapshot. The interim value is exposed as `owner_share_pct` and the billed value as `billed_owner_share_pct`, so an administrator can compare them. Rounding is applied exactly once, at the end: every intermediate day count, IP set and share fraction is computed exactly and only the final percentage is rounded.

### 3.10 Metering: Cycle Overage and Market-Addition Fees

A subscription's metered charge is the `seat_overage_fee`, and it is assessed per seat per cycle. The subscription includes the first 2 active days in a cycle, the `INCLUDED_ACTIVE_DAYS` constant, so the chargeable quantity is the number of active days that exceed that allowance: the seat's `monthly_active_days` minus 2, floored at zero so a seat that never exceeds the allowance carries no charge. A seat with zero chargeable days owes nothing and its `overage_fee_cents` is 0.

The chargeable days are priced at a per-day rate that depends on the seat's `index_tier`. A `TIER_1` seat is charged 1,250 cents per chargeable day — the `TIER_1_DAILY_RATE_CENTS` constant. A `TIER_2` seat is charged 900 cents, the `TIER_2_DAILY_RATE_CENTS` constant. A `TIER_3` seat is charged 600 cents, the `TIER_3_DAILY_RATE_CENTS` constant. The uncapped overage is simply the chargeable day count multiplied by the seat's rate.

Metered charges are capped as a share of the contract's annual fee, and the share depends on how many unauthorized markets the seat touched in the cycle, which is the length of its `monthly_unauthorized_markets` array. A seat with no unauthorized-market observations is capped at 250 basis points — 2.50 percent — of the contract's `annual_fee_cents`, the `LICENSED_MARKET_USAGE_LIMIT_BPS` constant. A seat with exactly one unauthorized-market observation is capped at 500 basis points, twice that constant. A seat with two or more observations is capped at 750 basis points, three times the constant. The cap amount itself is the contract's annual fee multiplied by the cap basis points and divided by ten thousand, using integer floor division so the cap never overshoots by a rounding unit. The seat's `overage_fee_cents` is then the lesser of the uncapped overage and the cap, and the cap is inclusive: an overage exactly equal to the cap is charged at the cap rather than above it. The result is an exact integer number of cents.

Two consequences of that cap design are worth stating explicitly. A seat with three or more unauthorized-market observations — the `cycle_cap_three_violations` case — is capped three times higher than a clean seat, so the same uncapped overage produces a fee up to three times larger before the cap begins to bind; the tier rates themselves do not change. And a clean `TIER_1` seat with five active days on a contract whose annual fee is 100,000 cents — the `no_violation_cycle` case — is capped early: its uncapped overage would be 3,750 cents, but the 250-basis-point cap binds it to 2,500 cents, exactly 2.50 percent of the contract fee. The fee is recomputed on every usage event recorded against the seat and again for every seat during the periodic research cycle.

Adding a market to a contract carries an addition fee of its own, and it is computed in a pinned order that rounds at every stage. The first stage takes 8 percent of the contract's current `annual_fee_cents` — the `MARKET_ADD_BASE_PCT` constant — and rounds half up to a whole cent. The second stage multiplies that base by a product factor: 0.50 for a contract whose `product` is `GLOBAL_ALL`, 1.00 for `ANALYTICS_INDEX`, 0.75 for `LISTING_SERVICE`, and 1.25 for `CORE_MARKET_DATA`, which is the fall-through case; the product is then rounded half up to a whole cent. The third stage multiplies that gross figure by a factor drawn from the subscriber organization's `service_tier`: 0.80 for `ENTERPRISE`, 1.00 for `MID_MARKET`, and 1.15 for `SMB`, the fall-through case; the result is rounded half up to a whole cent and becomes the addition fee. The rounding at each stage is mandatory — the stages are applied and rounded in the order base, then product factor, then gross, then tier factor, then final — because applying the multiplication once at the end and rounding only once produces a whole cent of difference on some annual fees. The clearest illustration of the tier stage is the `enterprise_discount` variant, in which an `ENTERPRISE` `CORE_MARKET_DATA` contract applies the 0.80 factor after the product factor so that an added market costs eighty percent of the gross addition.

### 3.11 The Periodic Research Cycle

A `PlatformAdmin` drives the platform's periodic housekeeping through a single research-cycle checkpoint, and it is the only operation that ages the whole corpus at once. Running the cycle applies, in one pass, the following.

Property staleness is re-aged first: `stale_source_count` is recomputed for every property by counting the sources whose `obtained_at` is strictly more than 180 days before the current logical clock, and for every property whose stale-source count changed, `completeness_pct` and `land_posture` are recomputed under the `PROVISIONAL` variant.

The renewal scan follows, and its processing order is load-bearing. Contracts are visited in order of `renewal_due_at` ascending, with `created_at` ascending as the tie-break, and no row identifier participates in that ordering. A contract is moved from `ACTIVE` to `GRACE` when it is `ACTIVE`, when `auto_renew` is true, when the logical clock has reached or passed `renewal_due_at`, and when its `renewal_decision` is still `NONE`; both boundary comparisons in this scan are non-strict. Each replacement into `GRACE` deliberately leaves the contract's seats readable — every seat on it keeps `access_revoked` false, because a grace period retains read access rather than cutting it off. A contract that is still `GRACE` when the logical clock has reached or passed its `term_end` is then driven onward to `LAPSED`, its `renewal_decision` is set to `FAILED`, and every seat on it is revoked by setting `access_revoked` to true. Because the scan processes a contract's due-date threshold and its term-end threshold within the same pass, a contract that is already past both boundaries is driven from `ACTIVE` through `GRACE` and on to `LAPSED` in one sweep rather than across two cycles, and the subscriber organization's `active_contract_count` is recomputed as each move lands.

Listing expiry comes next: every `PUBLISHED` listing whose `expires_at` the logical clock has reached is moved to `EXPIRED`. Sale deadlines follow: every `PENDING` sale transaction whose `subordination_deadline` the logical clock has reached is moved to `LAPSED`, and the owning property's `verified_sale_value_cents` is recomputed.

Seat metering is refreshed after that. Each seat's `overage_fee_cents` is recomputed by the rule in §3.10, and each seat's billed sharing attribution is recomputed under the `monthly_cycle` variant of the attribution rule in §3.9, writing `billed_owner_share_pct`. Market index values are then recomputed for every market holding an `AnalyticsRun` in the cycle. The pass finishes by advancing the platform's cycle index counter.

Deactivation is the administration-side terminal action, and it is archival rather than destructive. Moving a `User` from `ACTIVE` to `INACTIVE` requires only that the user currently hold `ACTIVE`, or the request is refused with `ERR_INVALID_STATE` (HTTP 409). A deactivated user remains readable and continues to be named on the historical records they touched — attributes they created, verdicts they reached and cases they filed all keep their reference — and any seat whose `occupant_user_id` equals that user keeps its occupant but may never be reassigned to them. A seat that needs a deactivated person back in it must be released and filled by a different active user.

## 4. Endpoint Definitions

Two status-code conventions govern the table below. An operation that brings a new, stand-alone resource into existence returns `201 Created`; this covers registering an organization, a user, a property, a source document, an attribute, a lease comparable, a sale transaction, a licensing contract, a seat, a usage event, an enforcement case, a listing and an analytics run. An operation that modifies a resource that already exists returns `200 OK`; this covers state transitions, fee rebases, subordinations, settlements and every read. The table names each operation, its path, its purpose and the roles permitted to invoke it, and nothing more — the request body, response body and side effects of each operation are specified in §3, and a client should reconstruct them from the workflow narratives there rather than from this table.

All paths are mounted under the API's root and the research routes sit beneath `/data-research` except for the logical-clock control.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock to a supplied instant | `PlatformAdmin` |
| POST | `/data-research/organizations` | Create an Organization | `PlatformAdmin` |
| GET | `/data-research/organizations/{organizationId}` | Get an Organization | `PlatformAdmin`, `LicensingAdmin`, `EnforcementOfficer` |
| GET | `/data-research/organizations/{organizationId}/users` | List the Users of an Organization | `PlatformAdmin`, `LicensingAdmin` |
| POST | `/data-research/organizations/{organizationId}/users` | Create a User within an Organization | `PlatformAdmin`, `LicensingAdmin` |
| GET | `/data-research/users/{userId}` | Get a User | `PlatformAdmin`, `LicensingAdmin`, `EnforcementOfficer`, `ResearchAnalyst` |
| GET | `/data-research/users` | List Users filtered by organization or role | `PlatformAdmin`, `LicensingAdmin` |
| POST | `/data-research/users/{userId}/deactivation` | Deactivate a User | `PlatformAdmin`, `LicensingAdmin` |
| POST | `/data-research/properties` | Create a Property research record | `ResearchAnalyst`, `PlatformAdmin` |
| GET | `/data-research/properties` | List Properties with market filtering and pagination | `ResearchAnalyst`, `SeatUser`, `LicensingAdmin` |
| GET | `/data-research/properties/{propertyId}` | Get a Property | `ResearchAnalyst`, `SeatUser`, `LicensingAdmin`, `EnforcementOfficer` |
| POST | `/data-research/properties/{propertyId}/research/start` | Move a Property from `DRAFT` to `RESEARCHING` | `ResearchAnalyst` |
| POST | `/data-research/properties/{propertyId}/finalize` | Move a Property from `DRAFT` or `RESEARCHING` to `VERIFIED` | `ResearchAnalyst` |
| POST | `/data-research/properties/{propertyId}/subdivision` | Split a `DRAFT` root Property into a child Property | `ResearchAnalyst` |
| GET | `/data-research/properties/{propertyId}/subdivisions` | List the child Properties subdivided from a Property | `ResearchAnalyst`, `PlatformAdmin`, `LicensingAdmin` |
| POST | `/data-research/properties/{propertyId}/source-documents` | Attach a source-document evidence row to a Property | `ResearchAnalyst` |
| GET | `/data-research/properties/{propertyId}/source-documents` | List the SourceDocuments attached to a Property | `ResearchAnalyst`, `EnforcementOfficer`, `LicensingAdmin` |
| GET | `/data-research/source-documents` | List SourceDocuments filtered by property | `ResearchAnalyst`, `EnforcementOfficer`, `LicensingAdmin` |
| GET | `/data-research/source-documents/{sourceDocumentId}` | Get a SourceDocument | `ResearchAnalyst`, `EnforcementOfficer`, `LicensingAdmin` |
| POST | `/data-research/properties/{propertyId}/attributes` | Create a PropertyAttribute claim on a Property | `ResearchAnalyst` |
| GET | `/data-research/attributes` | List PropertyAttributes filtered by property, analyst or status | `ResearchAnalyst`, `SeatUser`, `LicensingAdmin`, `EnforcementOfficer` |
| GET | `/data-research/attributes/{attributeId}` | Get a PropertyAttribute | `ResearchAnalyst`, `SeatUser`, `LicensingAdmin`, `EnforcementOfficer` |
| POST | `/data-research/properties/{propertyId}/attributes/{attributeId}/proposals` | Propose a new value for a PropertyAttribute | `ResearchAnalyst` |
| POST | `/data-research/attributes/{attributeId}/verifications` | Verify a `PENDING` PropertyAttribute | `ResearchAnalyst` |
| POST | `/data-research/attributes/{attributeId}/rejections` | Reject a `PENDING` PropertyAttribute | `ResearchAnalyst` |
| POST | `/data-research/properties/{propertyId}/lease-comparables` | Record a lease comparable against a Property | `ResearchAnalyst` |
| GET | `/data-research/lease-comparables` | List LeaseComparables filtered by property or market | `ResearchAnalyst`, `SeatUser`, `LicensingAdmin` |
| GET | `/data-research/lease-comparables/{leaseComparableId}` | Get a LeaseComparable | `ResearchAnalyst`, `SeatUser`, `LicensingAdmin` |
| POST | `/data-research/properties/{propertyId}/sale-transactions` | Record a sale transaction against a Property | `ResearchAnalyst` |
| GET | `/data-research/sale-transactions` | List SaleTransactions filtered by property, status or case | `ResearchAnalyst`, `LicensingAdmin`, `EnforcementOfficer` |
| GET | `/data-research/sale-transactions/{transactionId}` | Get a SaleTransaction | `ResearchAnalyst`, `LicensingAdmin`, `EnforcementOfficer` |
| POST | `/data-research/sale-transactions/{transactionId}/subordinations` | Record a licensed-market subordination | `EnforcementOfficer`, `LicensingAdmin` |
| POST | `/data-research/licensing-contracts` | Create a subscription licensing contract | `LicensingAdmin`, `PlatformAdmin` |
| GET | `/data-research/licensing-contracts` | List LicensingContracts filtered by organization or status | `LicensingAdmin`, `EnforcementOfficer`, `PlatformAdmin` |
| GET | `/data-research/licensing-contracts/{contractId}` | Get a LicensingContract | `LicensingAdmin`, `EnforcementOfficer`, `PlatformAdmin` |
| GET | `/data-research/licensing-contracts/{contractId}/seats` | List the LicenseSeats of a contract | `LicensingAdmin`, `EnforcementOfficer`, `PlatformAdmin` |
| POST | `/data-research/licensing-contracts/{contractId}/seats` | Create a LicenseSeat on a contract | `LicensingAdmin` |
| POST | `/data-research/licensing-contracts/{contractId}/activate` | Activate a `PENDING` contract | `LicensingAdmin` |
| POST | `/data-research/licensing-contracts/{contractId}/markets` | Add a licensed market to an `ACTIVE` contract and rebase its fee | `LicensingAdmin` |
| POST | `/data-research/licensing-contracts/{contractId}/renewals` | Record an auto-renewal into a new term | `LicensingAdmin` |
| POST | `/data-research/licensing-contracts/{contractId}/terminations` | Exercise a termination decision | `LicensingAdmin` |
| POST | `/data-research/licensing-contracts/{contractId}/seats/{seatId}/assignment` | Assign an occupant User to a LicenseSeat | `LicensingAdmin` |
| POST | `/data-research/licensing-contracts/{contractId}/seats/{seatId}/unassignment` | Release a LicenseSeat's occupant | `LicensingAdmin` |
| POST | `/data-research/licensing-contracts/{contractId}/seats/{seatId}/fee-assignments` | Rebase a seat's cycle overage fee and billed attribution | `LicensingAdmin` |
| GET | `/data-research/seats` | List LicenseSeats filtered by contract, occupant or market | `LicensingAdmin`, `EnforcementOfficer`, `PlatformAdmin` |
| GET | `/data-research/seats/{seatId}` | Get a LicenseSeat | `LicensingAdmin`, `EnforcementOfficer`, `SeatUser`, `PlatformAdmin` |
| POST | `/data-research/seats/{seatId}/usage-events` | Record a data-access event for a seat and refresh monitoring | `SeatUser`, `PlatformAdmin` |
| GET | `/data-research/seats/{seatId}/usage-events` | List the UsageEvents of a seat | `LicensingAdmin`, `EnforcementOfficer`, `SeatUser`, `PlatformAdmin` |
| GET | `/data-research/usage-events` | List UsageEvents filtered by seat or presenting user | `LicensingAdmin`, `EnforcementOfficer`, `PlatformAdmin` |
| GET | `/data-research/usage-events/{usageEventId}` | Get a UsageEvent | `LicensingAdmin`, `EnforcementOfficer`, `PlatformAdmin` |
| POST | `/data-research/enforcement-cases` | Open an enforcement case against an organization | `EnforcementOfficer` |
| GET | `/data-research/enforcement-cases` | List EnforcementCases filtered by organization, contract or status | `EnforcementOfficer`, `LicensingAdmin`, `PlatformAdmin` |
| GET | `/data-research/enforcement-cases/{caseId}` | Get an EnforcementCase | `EnforcementOfficer`, `LicensingAdmin`, `PlatformAdmin` |
| GET | `/data-research/enforcement-cases/{caseId}/escalations` | List the LITIGATION cases escalated from an AUDIT case | `EnforcementOfficer`, `LicensingAdmin` |
| POST | `/data-research/enforcement-cases/{caseId}/escalations` | Escalate an AUDIT case to LITIGATION and suspend the organization | `EnforcementOfficer` |
| POST | `/data-research/enforcement-cases/{caseId}/settlements` | Settle an escalated case and reinstate the organization | `EnforcementOfficer` |
| POST | `/data-research/enforcement-cases/{caseId}/withdrawals` | Withdraw an `OPEN` enforcement case | `EnforcementOfficer` |
| POST | `/data-research/properties/{propertyId}/listings` | Create a broker availability listing against a Property | `BrokerPublisher` |
| GET | `/data-research/listings` | List Listings filtered by property, organization or status | `BrokerPublisher`, `ResearchAnalyst`, `SeatUser`, `LicensingAdmin` |
| GET | `/data-research/listings/{listingId}` | Get a Listing | `BrokerPublisher`, `ResearchAnalyst`, `LicensingAdmin` |
| POST | `/data-research/listings/{listingId}/publication` | Publish a `DRAFT` listing as research input | `BrokerPublisher` |
| POST | `/data-research/listings/{listingId}/withdrawals` | Withdraw a `PUBLISHED` listing | `BrokerPublisher` |
| POST | `/data-research/listings/{listingId}/syndication` | Syndicate a `PUBLISHED` listing into an additional market | `LicensingAdmin`, `EnforcementOfficer` |
| POST | `/data-research/analytics/index-runs` | Run the market index calculation for a market and window | `ResearchAnalyst`, `SeatUser` |
| GET | `/data-research/analytics/index-runs` | List AnalyticsRun index rows for a market | `ResearchAnalyst`, `SeatUser`, `LicensingAdmin` |
| POST | `/data-research/analytics/forecasts` | Produce a forward-looking market forecast from a prior index run | `ResearchAnalyst`, `SeatUser` |
| GET | `/data-research/analytics/forecasts` | List forecast AnalyticsRuns filtered by market | `ResearchAnalyst`, `SeatUser`, `LicensingAdmin` |
| POST | `/data-research/analytics/index-runs/{runId}/attribution-removals` | Remove an index run's records from the market attributed count | `LicensingAdmin`, `EnforcementOfficer` |
| POST | `/data-research/reports/market-escalations` | Raise a market-level escalations report that re-grades properties | `EnforcementOfficer`, `ResearchAnalyst` |
| POST | `/data-research/reports/subscription-reach` | Report a subscription's occupy-limit share against the roll-up share | `LicensingAdmin` |
| POST | `/data-research/run_research_cycle` | Periodic operations checkpoint: ages sources, scans renewals, recomputes fees and indexes | `PlatformAdmin` |

## 5. Error Code Catalogue

The table below lists every machine-readable error identifier the API can return, together with the HTTP status that carries it. The condition under which each error is raised is deliberately not repeated here: those conditions are stated in the workflows they guard in §2 and §3, and a client should read the two together.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_ORGANIZATION_NOT_FOUND` | 404 Not Found |
| `ERR_USER_NOT_FOUND` | 404 Not Found |
| `ERR_PROPERTY_NOT_FOUND` | 404 Not Found |
| `ERR_ATTRIBUTE_NOT_FOUND` | 404 Not Found |
| `ERR_SOURCE_DOCUMENT_NOT_FOUND` | 404 Not Found |
| `ERR_TRANSACTION_NOT_FOUND` | 404 Not Found |
| `ERR_LISTING_NOT_FOUND` | 404 Not Found |
| `ERR_CONTRACT_NOT_FOUND` | 404 Not Found |
| `ERR_SEAT_NOT_FOUND` | 404 Not Found |
| `ERR_ENFORCEMENT_CASE_NOT_FOUND` | 404 Not Found |
| `ERR_PROPERTY_FROZEN` | 409 Conflict |
| `ERR_PROPERTY_RESTRICTED` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_EMPTY_ATTRIBUTE_SET` | 409 Conflict |
| `ERR_ATTRIBUTES_UNRESOLVED` | 409 Conflict |
| `ERR_ATTRIBUTE_DUPLICATE_FIELD` | 409 Conflict |
| `ERR_ATTRIBUTE_MARKET_MISMATCH` | 422 Unprocessable Entity |
| `ERR_ATTRIBUTE_SOURCE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_SUBDIVISION_PARENT_INVALID` | 422 Unprocessable Entity |
| `ERR_SEGREGATION_OF_DUTIES` | 409 Conflict |
| `ERR_THIRD_PARTY_UNLICENSED` | 409 Conflict |
| `ERR_UNAUTHORIZED_REDISTRIBUTION` | 409 Conflict |
| `ERR_SOURCE_FUTURE_DATED` | 409 Conflict |
| `ERR_LEASE_WINDOW_INVALID` | 422 Unprocessable Entity |
| `ERR_COMP_TEMPORAL_IMPOSSIBLE` | 409 Conflict |
| `ERR_SALE_PROPERTY_NOT_RESEARCHED` | 422 Unprocessable Entity |
| `ERR_SALE_PRICE_NOT_POSITIVE` | 409 Conflict |
| `ERR_SUBORDINATION_DEADLINE_PASSED` | 409 Conflict |
| `ERR_SUBSCRIPTION_INACTIVE` | 409 Conflict |
| `ERR_NO_SEATS` | 409 Conflict |
| `ERR_SEAT_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_SEAT_MARKET_NOT_LICENSED` | 409 Conflict |
| `ERR_SEAT_ALREADY_ASSIGNED` | 409 Conflict |
| `ERR_USER_INACTIVE` | 409 Conflict |
| `ERR_USER_OUT_OF_SCOPE` | 409 Conflict |
| `ERR_MARKET_ALREADY_LICENSED` | 409 Conflict |
| `ERR_AUTO_RENEW_DISABLED` | 409 Conflict |
| `ERR_RENEWAL_LAPSED` | 409 Conflict |
| `ERR_RENEWAL_TERMINATED` | 409 Conflict |
| `ERR_TERMINATION_WINDOW_CLOSED` | 409 Conflict |
| `ERR_FEE_NOT_POSITIVE` | 409 Conflict |
| `ERR_SUBSCRIPTION_REACH_EXCEEDED` | 409 Conflict |
| `ERR_LISTING_OVERLAP` | 409 Conflict |
| `ERR_LITIGATION_NOT_ESCALATABLE` | 409 Conflict |
| `ERR_LITIGATION_NOT_PERMITTED` | 409 Conflict |
| `ERR_PENALTY_BELOW_LITIGATION_FLOOR` | 409 Conflict |
| `ERR_SETTLEMENT_INSUFFICIENT` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_EMPTY_INDEX_SET` | 409 Conflict |