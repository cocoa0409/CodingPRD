# Liquor License Brokerage & Transfer Escrow API — Product Requirements Document

## 1. Introduction

A quota liquor license is one of the few assets whose market price is set almost entirely by the fact that the state refuses to print more of them. In a county where the statutory ceiling has been reached, an existing license is the only way into the business, and the transaction that moves it from one licensee to another is not a simple sale: it is a months-long regulated proceeding involving a brokerage, an escrow holder, a landlord, a zoning authority, a licensing analyst, and any member of the public who cares to protest. The parties routinely lose money not because the price was wrong but because a posting window was missed, a landlord consent never arrived, a filing fee was tendered a few hundred cents short, or an escrow was released against an application that had in fact been denied.

This document specifies the API for a brokerage and transfer-escrow platform that models that proceeding end to end. The platform holds the license inventory of every county it operates in, tracks each county's quota utilization and the market scarcity that utilization implies, pre-qualifies buyers and their proposed premises before a dollar changes hands, drafts purchase agreements with a deposit requirement computed from the license class and the county's scarcity, holds the buyer's deposit in an append-only escrow ledger, prepares and files the transfer application with the licensing authority, opens and polices the statutory publication and protest windows, and finally disposes of the escrowed funds in exactly one of three mutually exclusive ways: released down a fixed disbursement waterfall on an approved transfer, refunded to the buyer on a denied one, or forfeited to the seller when the contingency period lapses with the application still in flight.

Two design commitments run through everything that follows. First, the money dimension and the contract dimension of an agreement move independently — a deposit can be held while the agreement is still a draft, and an agreement can be closed while the funds are still held — so the platform tracks them as two separate status fields on the same record and never collapses them. Second, every quantity the platform conserves must land back exactly where it started when a transfer fails: the compensating cascade that follows a refund or a forfeiture returns the license to the status it held before escrow, restores an unexpired safekeeping window, returns the listing to the market, and drives the escrow balance to zero without ever deleting or rewriting a ledger row. All collections are mounted at the root of the API — there is no shared URL prefix — and the only nested paths in the system are read-only reverse lookups.

## 2. Global Specifications & System-Wide Principles

This section defines the contract-level rules that hold for every endpoint in the API, regardless of which part of the transfer proceeding it belongs to.

### 2.1. Parties, Headers and Role-Based Access Control

Every request to the API, without exception, must carry two headers: `X-User-ID`, identifying the acting party, and `X-User-Role`, declaring the capacity in which that party is acting. A header that is absent, and equally a header whose value is the empty string, causes the request to be rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The same `ERR_UNAUTHENTICATED` rejection applies when `X-User-Role` carries a value that is not one of the six roles the platform recognises. Those six roles are `PlatformAdmin`, `Broker`, `Buyer`, `Seller`, `RegulatorAnalyst`, and `EscrowOfficer`. When the role is well-formed but is not among the roles authorised for the endpoint being called, the request is refused with `ERR_ROLE_NOT_PERMITTED` (HTTP 403).

Three of the six roles are **entity-backed**, meaning the value in `X-User-ID` is the `id` of a persisted record and is compared against foreign keys on the resource being acted upon:

- When `X-User-Role` is `Broker`, `X-User-ID` is the `id` of the acting `Brokerage`. Ownership checks compare it to the `brokerage_id` of the listing, purchase agreement, or — reached through the protested application and its agreement — protest being acted on. A `Broker` is the licensed intermediary: it lists licenses, drafts and executes agreements, files the agency disclosure, files and refiles transfer applications, answers protests, and may petition safekeeping.
- When `X-User-Role` is `Buyer`, `X-User-ID` is the `id` of the acting `BuyerProfile`. Ownership checks compare it to the `buyer_id` of the purchase agreement or of the premises being acted on. A `Buyer` registers candidate premises, records the landlord's consent decision, funds the escrow, and acknowledges the agency disclosure as the buyer side.
- When `X-User-Role` is `Seller`, `X-User-ID` is the `id` of the acting `SellerProfile`. Ownership checks compare it to the `owner_seller_id` of the license underlying the resource being acted on. A `Seller` acknowledges the agency disclosure as the seller side and may petition safekeeping on its own license.

Any ownership mismatch on an entity-backed role is refused with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

The remaining three roles are **opaque**, meaning `X-User-ID` is an operator identifier that is not tied to any persisted entity and is never compared against any record's `id`:

- When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque reference-data operator identifier. A `PlatformAdmin` registers counties, brokerages and license inventory, registers party profiles alongside a `Broker`, drives the logical clock, and may read every resource in the system. It is never a party to a transaction.
- When `X-User-Role` is `RegulatorAnalyst`, `X-User-ID` is an opaque licensing-authority analyst identifier. The server does record it — the analyst who takes an application into review has their `X-User-ID` written to that application's `accepted_by_analyst_id` field — but it is stored as an opaque string and is never resolved against any entity's `id`. A `RegulatorAnalyst` runs buyer qualification reviews, records zoning verification outcomes, drives the application review lifecycle, records third-party protests, issues transfer decisions, and decides safekeeping filings.
- When `X-User-Role` is `EscrowOfficer`, `X-User-ID` is an opaque escrow-holder identifier that the server does not persist on any record and does not compare to any entity's `id`. An `EscrowOfficer` is the sole operator of settlement and may also fund a deposit; it may never draft, execute or terminate an agreement.

Segregation of duties is enforced at one specific point: the `RegulatorAnalyst` issuing a transfer decision must present an `X-User-ID` different from the value stored in that application's `accepted_by_analyst_id`. An analyst who tries to decide an application they themselves accepted for review is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). The value survives the deficiency-and-resubmission loop unchanged, so an analyst cannot regain decision authority by pushing the application back through the revision cycle.

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

Every list endpoint in the API is paginated through two query parameters. `limit` sets the maximum number of records returned; when the caller omits it, it defaults to 10, and a supplied value must be at least 1 and at most 100. `offset` sets how many records to skip before the page begins and defaults to 0.

Unless a specific endpoint states otherwise, list results are ordered by `created_at` ascending. Two list endpoints order by a domain timestamp instead and say so where they are described: the escrow ledger views order by `occurred_at` ascending with `created_at` ascending as the tie-break.

Every list response carries four pagination fields inside the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`. `total_count` reflects the number of records matching the caller's filters before the page window is applied, and `has_more` is true whenever records matching those filters remain beyond the current window.

### 2.4. The Logical Clock and Statutory Date Arithmetic

Nothing in this system reads wall-clock time. Every deadline, posting window, protest deadline, contingency expiry, safekeeping window and nonuse computation reads a server-held **logical clock**. At server startup the logical clock reads exactly `2026-08-01T00:00:00Z`, and it must not fall back to real time under any circumstance. A `PlatformAdmin` moves it by supplying a `to_iso8601` instant to the clock-setting capability, which answers with the resulting `current_utc`. Setting the clock changes only what subsequent reads of "now" return; no already-stored record is recomputed retroactively, so a window that was open when it was written stays written as it was.

Two distinct kinds of temporal arithmetic appear in the domain and they must not be conflated. **Day arithmetic** adds a whole number of days to an instant: the posting end, the protest deadline, the protest response deadline and the contingency deadline are all computed this way, and the result carries the same time-of-day as the instant it was computed from. **Whole-day date differencing** is used only for the nonuse clock: the elapsed nonuse period is the difference in whole UTC calendar days between the date part of the current logical instant and the license's `last_active_date`, never an hour count. **Calendar-month arithmetic** appears only in safekeeping: adding a whole number of calendar months preserves the day-of-month and, when the target month is too short for that day-of-month, clamps to the last day of the target month.

Boundary inclusivity is specified individually at each rule and is never uniform. Some deadlines admit action at the exact instant of the deadline; others require the clock to have moved strictly past it. Each such rule states its own direction where it is described.

### 2.5. Common Resource Properties and Version Semantics

Every resource the API returns carries a server-minted `id`, formatted as a UUID with no type prefix of any kind, and a `created_at` timestamp rendered as an ISO 8601 UTC instant with exactly three fractional-second digits.

All resources except one additionally carry `updated_at`, an ISO 8601 UTC timestamp with three fractional digits recording the last modification, and `version`, an integer that starts at 1 on creation and increases by exactly one on every mutation of that resource. This applies to `County`, `SellerProfile`, `BuyerProfile`, `Brokerage`, `License`, `Premises`, `Listing`, `PurchaseAgreement`, `DualAgencyDisclosure`, `TransferApplication`, `Protest` and `SafekeepingFiling`.

The single exception is the escrow ledger row. An `EscrowLedgerEntry` is immutable once written: it carries `id` and `created_at` only. It has no `updated_at` and no `version`, and there is no endpoint that updates or deletes one. Corrections to an escrow position are made by appending a further row, never by touching an existing one.

A "mutation" for `version` purposes includes writes the server performs on its own initiative. When a computed field is rewritten — a county's quota counters, a premises' suitability verdict, a license's safekeeping window, a listing's offer counter, an agreement's escrow balance — that is a mutation of the owning resource: its `updated_at` is refreshed and its `version` advances by one. A single client request therefore commonly advances the `version` of several records, and the descriptions in section 3 name every record each operation touches.

### 2.6. Monetary Amounts, Basis Points and Rounding Discipline

All monetary amounts in this API are integer counts of whole cents. There are no fractional-cent values in any request or response body, and no amount is ever transported as a string.

Rates are expressed in **basis points**, where one basis point is one ten-thousandth. A `commission_rate_bps` of 600 is six percent of the purchase price; a `transfer_fee_bps` of 150 is one and one-half percent; a `deposit_pct_bps` of 1000 is ten percent. To convert a basis-point rate into an amount, multiply the base amount by the rate and divide by ten thousand.

Wherever a computation must produce a whole-cent result from a non-integral intermediate, the result is rounded **half up** — a value exactly halfway between two cents rounds to the larger magnitude cent. The number of rounding steps in each computation is fixed and normative, and so is where in the computation each rounding step falls: rounding one step earlier or one step later than specified produces a legitimately different number, and the specifications in section 3 pin the order explicitly for every amount the platform computes. Two places in particular are load-bearing. In the deposit requirement, the rounding happens before the floor-and-cap clamp is applied, never after it. In the commission disbursement, each commission line is rounded to whole cents individually and the rounded lines are then summed — summing first and rounding the total is the wrong reading and differs by one cent whenever both split lines land on a half cent.

Integer division without rounding appears in exactly one place: the scarcity contribution to the deposit rate is divided by five and truncated toward zero (that is, the fractional part is discarded), which is stated again where that computation is described. Basis-point counters that the platform stores, such as a county's quota utilization, are integers produced by half-up rounding.

### 2.7. Optimistic Concurrency on Parent Records

Two creation endpoints in this API attach a new child record to a parent whose state the caller must have observed first, because the parent's current values feed the child's computed fields. Both therefore require an optimistic-concurrency token in the request body. The token is not optional and cannot be omitted; a request that lacks it fails schema validation with `ERR_INVALID_REQUEST` (HTTP 400).

Drafting a purchase agreement (`POST /purchase-agreements`) requires `expected_listing_version`, carrying the `version` of the parent `Listing` as the client last observed it. If the listing's current `version` differs from the supplied value, the create is rejected with `ERR_STALE_LISTING_VERSION` (HTTP 412). This guard exists precisely because competing draft offers on one active listing are legitimate product behaviour: no state precondition blocks a second offer, so the only thing that can protect a caller from drafting against a listing whose `open_offer_count`, `market_price_cents` and frozen scarcity snapshot have moved underneath it — all three of which feed the deposit requirement — is the version token. Because a successful create itself advances the listing's `version`, a caller that replays the same `expected_listing_version` a second time is refused with `ERR_STALE_LISTING_VERSION`.

Filing a safekeeping petition (`POST /safekeeping-filings`) requires `expected_license_version`, carrying the `version` of the parent `License` as the client last observed it. If the license's current `version` differs from the supplied value, the filing is rejected with `ERR_STALE_LICENSE_VERSION` (HTTP 412). Here too a second filing is legitimate in principle — an extension petition deliberately supersedes the window installed by the previous one — so the rejection is triggered only by staleness: the filer's view of `safekeeping_expires_at`, `safekeeping_extensions_count` and `safekeeping_filing_pending` determines the fee step and the chained effective date, and acting on a stale view of them would produce a wrong fee and a wrong window. A successful filing advances the license's `version`, so a replay of the same `expected_license_version` is refused with `ERR_STALE_LICENSE_VERSION`.

No other endpoint in this API accepts a version field of any kind. Endpoints not named above take no concurrency token and perform no version comparison.

### 2.8. Cascade Discipline and Conserved Quantities

A single client request in this system routinely rewrites several records. The platform performs those secondary writes itself; a client never needs to — and must not be expected to — issue a follow-up request to bring a related record into line. Cascades are described here as ordered **hops**, because each hop's precondition is satisfied by the write the previous hop performed, and an implementation that reorders them will fail its own guards.

Executing an agreement performs three writes at once: the agreement's contract dimension advances, the underlying `License` leaves `ACTIVE` or `SAFEKEEPING` for `IN_ESCROW`, and the `Listing` leaves `ACTIVE` for `UNDER_CONTRACT`. Each of those three records has its `version` advanced by one, and the license's county has its counters recomputed.

An approved transfer decision runs a five-hop closing cascade. Hop 1 writes the application's own outcome. Hop 2 fires because hop 1 set the application to `APPROVED`, and moves the `License` from `IN_ESCROW` to `TRANSFERRED` while recording the acquiring buyer and the price the license just changed hands for. Hop 3 fires because hop 2 set the license to `TRANSFERRED`, and moves the `Listing` from `UNDER_CONTRACT` to `SOLD`. Hop 4 fires because hop 3 set the listing to `SOLD`, and moves the agreement's contract dimension from `EXECUTED` to `CLOSED` — deliberately leaving the money dimension at `HELD`, because only the escrow officer moves money. Hop 5 fires because hop 4 closed the agreement, and moves every protest on that application that is still `OPEN` or `RESPONDED` to `OVERRULED`. Every record touched by every hop has its `version` advanced by one, and the county's counters are recomputed once because a license changed status.

A refund or a forfeiture runs a four-hop compensating cascade in the opposite direction. Hop 1 moves the money dimension out of `HELD` and appends the settlement ledger row. Hop 2 fires because hop 1 moved the money dimension, and moves the contract dimension from `EXECUTED` to `TERMINATED`, voiding the agency disclosures on the way. Hop 3 fires because hop 2 terminated the agreement, and returns the `License` from `IN_ESCROW` to whichever pre-escrow status is still lawful. Hop 4 fires because hop 3 returned the license to a non-escrow status, and returns the `Listing` from `UNDER_CONTRACT` to `ACTIVE`, recomputing its open-offer counter over whatever draft agreements remain. As above, each record's `version` advances by one and the county's counters are recomputed.

Three quantities are **conserved** across that compensating pair and must land exactly where they started. The sum of `amount_cents` over an agreement's ledger rows always equals that agreement's `escrow_balance_cents`, and equals zero after any settlement of any kind. A county's `escrow_committed_count` rises by exactly one when a license enters escrow and falls by exactly one when it leaves, so a failed transfer returns the county to the count it had before the agreement was executed. A county's `quota_licenses_counted` is untouched by the entire proceeding, because a license that has been transferred still occupies its quota slot — a transfer never frees capacity, which is why the approval cascade leaves the counted figure flat while the escrow-committed figure falls.

### 2.9. Identifier Resolution and the Order of Refusal

Where a path carries more than one identifier, identifiers are resolved strictly left to right, and the response reports the first identifier that resolves to nothing. Body foreign keys are resolved after all path identifiers, in the order in which the endpoint declares its input fields, and again the first unresolvable one is reported. The resource-specific not-found codes are `ERR_COUNTY_NOT_FOUND`, `ERR_SELLER_NOT_FOUND`, `ERR_BUYER_NOT_FOUND`, `ERR_BROKERAGE_NOT_FOUND`, `ERR_LICENSE_NOT_FOUND`, `ERR_PREMISES_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_DISCLOSURE_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, `ERR_PROTEST_NOT_FOUND` and `ERR_FILING_NOT_FOUND`, each carrying HTTP 404. A read addressed by an `entry_id` that matches no ledger row is likewise answered with HTTP 404.

Many endpoints are guarded by several rules at once, and which rule a caller sees when more than one is violated is part of the contract, not an implementation detail. Checks are evaluated in the following order, and the first violated check ends the request:

1. **Headers present.** Both `X-User-ID` and `X-User-Role` must be present and non-empty on every request — `ERR_UNAUTHENTICATED` (401).
2. **Role recognised.** `X-User-Role` must be one of the six declared roles, on every request — `ERR_UNAUTHENTICATED` (401).
3. **Role permitted.** The role must appear in the endpoint's authorised set, on every request — `ERR_ROLE_NOT_PERMITTED` (403).
4. **Request body well-formed.** On every write endpoint: every required field present, every enum value drawn from its declared set, every integer inside its declared range, every datetime a valid ISO 8601 UTC instant, every date a valid `YYYY-MM-DD` value, and no value of the wrong scalar type (a string where an integer is declared, for instance) — `ERR_INVALID_REQUEST` (400).
5. **Path identifiers exist**, left to right, on every endpoint with a path identifier — the matching 404 code above.
6. **Body foreign keys exist**, in declared input order, on every write endpoint carrying foreign keys — the matching 404 code above.
7. **Ownership.** For entity-backed roles, the ownership comparison of section 2.1 — `ERR_NOT_RESOURCE_OWNER` (403). This check guards twelve operations: listing activation, listing withdrawal, agreement drafting, agreement execution, escrow deposit, agreement termination, disclosure filing, disclosure acknowledgement, transfer-application filing, application resubmission, protest response, and safekeeping filing.
8. **Segregation of duties.** On the transfer decision only — `ERR_SEGREGATION_OF_DUTIES` (403).
9. **Optimistic concurrency.** On agreement drafting and safekeeping filing only — `ERR_STALE_LISTING_VERSION` or `ERR_STALE_LICENSE_VERSION` (412).
10. **State precondition.** On every state-transition endpoint: the target record must sit in a non-terminal state from which the requested transition is declared, and the cross-dimension guards on a parallel-state record count here too — the money dimension must be `HELD` for execution, the contract dimension must be `CLOSED` for a release, and the money dimension must be `AWAITING_DEPOSIT` for a termination. The applicable code is `ERR_INVALID_LICENSE_STATE`, `ERR_INVALID_LISTING_STATE`, `ERR_INVALID_AGREEMENT_STATE`, `ERR_INVALID_APPLICATION_STATE`, `ERR_INVALID_PROTEST_STATE`, `ERR_ESCROW_NOT_HELD`, `ERR_ESCROW_ALREADY_SETTLED` or `ERR_ESCROW_MUST_BE_SETTLED_FIRST`, each carrying HTTP 409. Records that are already in a terminal state are deliberately out of scope for this check and are handled by the next one instead, so this step never answers with `ERR_ALREADY_TERMINAL` and the next step is always reachable.
11. **Terminal record.** A record already in a terminal state accepts no further transition: a `License` at `TRANSFERRED`, a `Listing` at `SOLD` or `WITHDRAWN`, an agreement whose contract dimension is `CLOSED` or `TERMINATED`, an application at `APPROVED` or `DENIED`, a protest at `SUSTAINED` or `OVERRULED`, a filing at `GRANTED` or `DENIED` — `ERR_ALREADY_TERMINAL` (409).
12. **Distance restriction** — `ERR_DISTANCE_RESTRICTION_VIOLATION` (422), on transfer-application filing and notice posting.
13. **Premises suitability** — `ERR_PREMISES_UNSUITABLE` (422), on agreement execution, transfer-application filing and notice posting.
14. **Buyer qualification** — `ERR_BUYER_NOT_QUALIFIED` (422), on agreement execution and transfer-application filing.
15. **Agency disclosure** — `ERR_DUAL_AGENCY_DISCLOSURE_REQUIRED` or `ERR_DUAL_AGENCY_PROHIBITED` (422), on agreement execution, transfer-application filing and disclosure filing.
16. **Settlement disposition dependency** — `ERR_TRANSFER_NOT_APPROVED` (409), on escrow settlement.
17. **Seller tax clearance** — `ERR_SELLER_TAX_CLEARANCE_MISSING` (422), on listing activation and transfer-application filing.
18. **Acknowledging party representation** — `ERR_PARTY_NOT_REPRESENTED` or `ERR_ALREADY_ACKNOWLEDGED` (422), on disclosure acknowledgement.
19. **County quota headroom** — `ERR_COUNTY_QUOTA_EXHAUSTED` (409), on license creation.
20. **License contract-window overlap** — `ERR_LICENSE_CONTRACT_OVERLAP` (409), on agreement drafting.
21. **Premises posting-window collision** — `ERR_POSTING_WINDOW_CONFLICT` (409), on notice posting.
22. **Deficiency round limit** — `ERR_DEFICIENCY_LIMIT_EXCEEDED` (409), on issuing a deficiency notice.
23. **Safekeeping limits** — `ERR_SAFEKEEPING_EXTENSION_LIMIT` or `ERR_SAFEKEEPING_FILING_PENDING` (409), on safekeeping filing and on listing activation.
24. **Open offers on withdrawal** — `ERR_LISTING_HAS_OPEN_OFFERS` (409), on listing withdrawal.
25. **Protest windows** — `ERR_PROTEST_WINDOW_CLOSED` or `ERR_PROTEST_RESPONSE_WINDOW_CLOSED` (409), on protest intake and protest response respectively.
26. **Posting period elapsed** — `ERR_POSTING_PERIOD_NOT_ELAPSED` (409), on the transfer decision.
27. **Unanswered protest** — `ERR_PROTEST_RESPONSE_PENDING` or `ERR_UNANSWERED_PROTEST_REQUIRES_DENIAL` (409), on the transfer decision.
28. **Contingency window** — `ERR_CONTINGENCY_DEADLINE_PASSED` or `ERR_CONTINGENCY_STILL_OPEN` (409), on agreement execution, application resubmission and escrow settlement.
29. **Nonuse period** — `ERR_NONUSE_PERIOD_NOT_REACHED` (422), on safekeeping filing.
30. **Deposit amount exactness** — `ERR_DEPOSIT_AMOUNT_MISMATCH` (422), on the escrow deposit.
31. **Filing fee exactness** — `ERR_FILING_FEE_MISMATCH` (422), on transfer-application filing and resubmission.
32. **Disbursement solvency** — `ERR_ESCROW_INSUFFICIENT_FOR_DISBURSEMENT` (422), on escrow settlement.

Because the ordering is fixed, a mid-flight regulatory problem always surfaces as the regulatory code rather than being masked by a later fiscal one: a filing tendered with the wrong fee against an unsuitable premises reports `ERR_PREMISES_UNSUITABLE`, not `ERR_FILING_FEE_MISMATCH`.

### 2.10. County Quota Position and Market Scarcity

A county's quota position is the platform's most widely read derived figure, and it is recomputed from scratch whenever a license is added to the county's inventory and whenever any license in the county changes status — that is, on execution, on the approval cascade, on the refund or forfeiture cascade, and on a granted safekeeping decision. Each recomputation writes four counters onto the `County` record and advances the county's `version` by one.

`quota_licenses_counted` is the number of licenses in the county whose `counts_against_quota` flag is set and whose `status` is one of `ACTIVE`, `IN_ESCROW`, `SAFEKEEPING` or `TRANSFERRED`. `quota_available` is `quota_licenses_total` minus that count, floored at zero so it is never negative. `quota_utilization_bps` is the counted figure multiplied by ten thousand, divided by `quota_licenses_total`, and rounded half up to an integer basis-point value; when `quota_licenses_total` is zero the utilization is reported as 10000 rather than attempting the division. `escrow_committed_count` is the number of licenses in the county whose `status` is `IN_ESCROW`, and unlike the other three it ignores the `counts_against_quota` flag entirely — grandfathered non-quota licenses are excluded from the counted, available and utilization figures but are still counted when they sit in escrow.

From the utilization figure the platform derives a **scarcity uplift**, also in basis points, on four inclusive lower-bound tiers. A utilization of 9000 basis points or more yields an uplift of 2500 basis points. Otherwise, a utilization of 7500 basis points or more yields 1200. Otherwise, a utilization of 5000 basis points or more yields 500. Below that the uplift is zero. The bounds are inclusive, so a county with nine of its ten quota slots occupied — utilization of exactly 9000 basis points — sits in the top tier at 2500, not the second tier at 1200. The uplift is read live when a valuation preview is computed, is snapshotted onto a listing at the moment of activation, and is thereafter read from that snapshot rather than recomputed.

## 3. Business Logic & Workflows

### 3.1. Reference Inventory: Counties, Parties, Brokerages and License Stock

Nothing can be brokered until the regulatory geography exists. A `PlatformAdmin` registers a licensing county by supplying a `county_code` — a short identifier of between 2 and 8 characters that must be unique across all counties — a display `name`, a `state_code` of exactly two uppercase letters, and `quota_licenses_total`, the statutory ceiling on how many quota-counted licenses may exist there, which must be at least 1. Seven further settings are optional and fall back to statutory defaults when omitted: `permitted_zoning_codes`, the list of zoning designations in which a licensed premises may operate without rezoning, defaulting to `C1`, `C2` and `MU1`; `distance_min_feet_school` and `distance_min_feet_church`, the minimum lawful distances from the nearest school and the nearest place of worship, each defaulting to 600 feet; `posting_period_days`, the length of the statutory publication window, defaulting to 30 days; `protest_window_days`, the number of days after posting begins during which a protest is still accepted, also defaulting to 30 days; `transfer_fee_bps`, the county's transfer fee in basis points of the purchase price, defaulting to 150; and `default_valuation_basis`, which selects the valuation variant applied when a broker activates a listing without naming one, defaulting to `COMPARABLE_SALES` and drawn from `COMPARABLE_SALES` or `INCOME_MULTIPLE`. Registration immediately runs the county quota computation against an empty inventory, so a freshly registered county reports `quota_licenses_counted` of 0, `quota_available` equal to its `quota_licenses_total`, `quota_utilization_bps` of 0 and `escrow_committed_count` of 0.

The selling side of the market is represented by a `SellerProfile`, registered by a `PlatformAdmin` or a `Broker` with the licensee's `legal_name` and a `contact_email` for escrow and regulator correspondence. Its `tax_clearance_status` is drawn from `PENDING`, `CLEARED` or `DELINQUENT` and defaults to `PENDING`. That single field gates two later operations: neither a listing activation nor a transfer-application filing may proceed while the selling licensee's clearance is anything other than `CLEARED`, and both refuse with `ERR_SELLER_TAX_CLEARANCE_MISSING`.

The buying side is a `BuyerProfile`, likewise registered by a `PlatformAdmin` or a `Broker`. It carries the applicant's `legal_name`, an `entity_type` of `INDIVIDUAL`, `LLC` or `CORP`, and a `residency_state` of exactly two uppercase letters. Three risk declarations are optional at registration and default to the benign reading: `felony_disclosure` defaults to false, `prior_revocation_count` defaults to 0 and may not be negative, and `citizenship_verified` defaults to false. A newly registered buyer has never been scored, so `qualification_status` reads `NOT_REVIEWED`, while `qualification_score`, `qualification_mode` and `qualification_reviewed_at` are all null.

A `Brokerage` is registered by a `PlatformAdmin` with a `firm_name`, a `state_broker_license_no` that must be unique across all brokerages, and a `commission_rate_bps` between 100 and 1500 inclusive — that is, between one and fifteen percent of the purchase price. Its `dual_agency_policy` is either `PROHIBITED` or `ALLOWED_WITH_DISCLOSURE` and defaults to `ALLOWED_WITH_DISCLOSURE`; a firm on the prohibited policy may never file a disclosure that represents both sides of the same agreement.

License stock is added to a county's inventory by a `PlatformAdmin`, who names the `county_id` whose quota, distance minima and fees will govern the license, the `owner_seller_id` of the current licensee of record, a `license_number` unique across all licenses, and a `license_class` drawn from `CLASS_47_ONSALE_GENERAL`, `CLASS_21_OFFSALE_GENERAL` or `CLASS_41_ONSALE_BEER_WINE`. Two commercial figures are also captured: `annual_gross_receipts_cents`, the trailing-twelve-month gross receipts of the licensed business, which may not be negative and is the sole input to the income-multiple valuation variant; and `last_active_date`, the calendar date in `YYYY-MM-DD` form on which the licensed premises last operated, which starts the nonuse clock. Optionally the admin supplies `last_transfer_price_cents` — the price the license last changed hands for, defaulting to null; a license with a non-null value here is a comparable for the comparable-sales valuation variant — and `counts_against_quota`, which defaults to true and is set false only for grandfathered non-quota licenses whose rows the quota arithmetic ignores. A license enters the inventory with `status` of `ACTIVE`, `transferred_to_buyer_id` null, `safekeeping_expires_at` null, `safekeeping_extensions_count` of 0 and `safekeeping_filing_pending` false. Creation is refused with `ERR_COUNTY_QUOTA_EXHAUSTED` when the license would count against quota and the county's `quota_available` is not at least 1; on success the county's four counters are rewritten and the county's `version` advances by one. The `status` enumeration for a license is `ACTIVE`, `IN_ESCROW`, `SAFEKEEPING` and `TRANSFERRED`, with `TRANSFERRED` terminal.

Reading back is deliberately generous, because every foreign key in the system must be reversible. The license inventory can be filtered by `county_id`, by `owner_seller_id`, by `transferred_to_buyer_id`, by `status` and by `license_class`, alongside the usual `limit` and `offset`. Premises can be filtered by `buyer_id`, `county_id` and `suitability_status`. Listings can be filtered by `license_id`, `brokerage_id` and `status`. Agreements can be filtered by `listing_id`, `buyer_id`, `premises_id`, `brokerage_id`, `license_id`, `seller_id`, `agreement_status` and `escrow_status`. Applications can be filtered by `agreement_id`, `license_id`, `premises_id` and `status`. Protests can be filtered by `application_id`, `status` and `grounds`. Disclosures can be filtered by `agreement_id` and `status`. Safekeeping filings can be filtered by `license_id`, `filing_type` and `status`. Ledger rows can be filtered by `agreement_id` and `entry_type`.

### 3.2. Buyer Qualification and Premises Suitability

Before an offer is drafted, two independent pre-checks must land: is this buyer fit to hold a license, and is this location fit to be licensed?

A candidate location is registered as a **Premises** by either a `Broker` or the `Buyer` itself, naming the `buyer_id` of the prospective operator, the `county_id` that supplies the distance minima and permitted zoning codes, an `address_line`, the parcel's current `zoning_code`, and the measured walking distances `distance_to_nearest_school_feet` and `distance_to_nearest_church_feet`, neither of which may be negative. The optional `census_tract_undue_concentration` flag, defaulting to false, records that the census tract already exceeds the per-capita license concentration ratio. Two standing fields start pessimistically: `conditional_use_permit_status` begins at `REQUIRED_NOT_FILED` — its full enumeration being `NOT_REQUIRED`, `REQUIRED_NOT_FILED`, `PENDING`, `GRANTED` and `DENIED` — and `landlord_consent_status` begins at `PENDING`, drawn from `NOT_REQUIRED`, `PENDING`, `GRANTED` and `REFUSED`. The `consent_document_ref`, an opaque reference to the stored consent instrument, starts null.

Suitability is not stored by the client; it is computed from the premises row and its county's thresholds alone, with no aggregation over other locations, and it is recomputed on registration, on zoning verification and on the recording of landlord consent. The evaluation walks a **pinned ladder of nine rules in this exact order**, and the first rule that matches decides both `suitability_status` and `suitability_reason_code`; later rules are not consulted once one has fired.

1. The school distance is less than the county's `distance_min_feet_school` — the verdict is `UNSUITABLE` with reason `SCHOOL_DISTANCE`.
2. The church distance is less than the county's `distance_min_feet_church` — `UNSUITABLE` with reason `CHURCH_DISTANCE`.
3. The conditional-use permit standing is `DENIED` — `UNSUITABLE` with reason `CUP_DENIED`.
4. The parcel's `zoning_code` is not one of the county's `permitted_zoning_codes` — `UNSUITABLE` with reason `ZONING_NOT_PERMITTED`.
5. Landlord consent has been `REFUSED` — `UNSUITABLE` with reason `LANDLORD_REFUSED`.
6. The conditional-use permit standing is either `REQUIRED_NOT_FILED` or `PENDING` — `CONDITIONAL` with reason `CUP_OUTSTANDING`.
7. The census tract is flagged for undue concentration — `CONDITIONAL` with reason `UNDUE_CONCENTRATION`.
8. Landlord consent is still `PENDING` — `CONDITIONAL` with reason `LANDLORD_PENDING`.
9. No rule above matched — `SUITABLE` with reason `NONE`.

The distance comparisons are strict, measured against an inclusive minimum: a premises exactly 600 feet from a school in a county whose minimum is 600 feet is lawfully sited and does not trip rule 1. Because the permit standing starts at `REQUIRED_NOT_FILED`, a lawfully sited new premises is computed as `CONDITIONAL` with reason `CUP_OUTSTANDING` at the moment of registration, while a too-close one is `UNSUITABLE` with `SCHOOL_DISTANCE` or `CHURCH_DISTANCE` immediately — and note that rule 6 outranks rules 7 and 8, so an outstanding permit masks both an undue-concentration flag and a pending landlord consent.

Only two operations may move those standing fields, and each may move only its own. A `RegulatorAnalyst` records the zoning conditional-use outcome by supplying a new `conditional_use_permit_status`, and may in the same act correct the surveyed facts from a field inspection by supplying any of `zoning_code`, `distance_to_nearest_school_feet`, `distance_to_nearest_church_feet` and `census_tract_undue_concentration`; whatever is supplied overwrites what was there, the suitability verdict and reason code are recomputed, and the premises' `version` advances by one. A `Broker` or the `Buyer` records the landlord's written decision by supplying a `landlord_consent_status` and optionally a `consent_document_ref`; again the suitability verdict and reason code are recomputed and the `version` advances. No other operation in the system writes either standing field.

Buyer qualification is the regulator's own act: a `RegulatorAnalyst` scores a buyer against a named location by supplying a `review_mode` of either `PRE_CHECK` or `FINAL_REVIEW` together with the `premises_id` of the location under consideration, which must be a premises registered to that same buyer. The review reads the buyer's own declarations, the named premises, and that premises' county, and writes `qualification_score`, `qualification_status`, `qualification_mode` and `qualification_reviewed_at` (set to the current logical instant) back onto the buyer, advancing the buyer's `version` by one.

The score starts at a nominal 100 points and is reduced by four deductions that both review modes apply identically. Twenty-five points are deducted for each previously revoked license the buyer holds, but the revocation count is capped at two for penalty purposes, so the deduction is at most fifty points however high `prior_revocation_count` climbs. Thirty points are deducted when `felony_disclosure` is true. Twenty points are deducted when `citizenship_verified` is false. Ten points are deducted when the buyer's `residency_state` differs from the `state_code` of the county in which the named premises sits.

The two modes diverge on exactly one component, the readiness of the premises. Under `PRE_CHECK` — the marketing-stage pre-qualification a broker runs before any location has been verified — the premises component is zero, so every unresolved condition is treated as neutral. Under `FINAL_REVIEW` — the regulator's pre-execution review — fifteen points are deducted when the premises' `conditional_use_permit_status` is neither `NOT_REQUIRED` nor `GRANTED`, and a further fifteen points are deducted when its `landlord_consent_status` is neither `NOT_REQUIRED` nor `GRANTED`. The same buyer against the same unresolved location therefore scores strictly higher under `PRE_CHECK` than under `FINAL_REVIEW`, and can drop two bands between the two. The four common deductions and the premises component are then summed onto the base and the result is clamped into the range 0 through 100 inclusive — anything below zero becomes zero, anything above one hundred becomes one hundred — yielding an integer `qualification_score`.

Banding is applied last, and one statutory override outranks the score entirely. When `prior_revocation_count` is 2 or more, or when `felony_disclosure` is true while `citizenship_verified` is false, the `qualification_status` is `DISQUALIFIED` regardless of what the score came to. Otherwise a score of 70 or more is `QUALIFIED`, a score of 50 or more is `PROVISIONALLY_QUALIFIED`, and anything below 50 is `UNQUALIFIED`; the band bounds are inclusive lower bounds, so a score of exactly 70 is `QUALIFIED` and a score of exactly 50 is `PROVISIONALLY_QUALIFIED`. The complete enumeration of `qualification_status` is `NOT_REVIEWED`, `QUALIFIED`, `PROVISIONALLY_QUALIFIED`, `UNQUALIFIED` and `DISQUALIFIED`, and `qualification_mode` records which variant produced the stored score as either `PRE_CHECK` or `FINAL_REVIEW`, or null before any review.

Both agreement execution and transfer-application filing require a buyer whose stored `qualification_status` is `QUALIFIED` or `PROVISIONALLY_QUALIFIED` and whose stored `qualification_mode` is `FINAL_REVIEW`; a buyer who has never been reviewed, one whose latest review was only a `PRE_CHECK`, and one who came out `UNQUALIFIED` or `DISQUALIFIED` are all refused with `ERR_BUYER_NOT_QUALIFIED`.

### 3.3. Listing a License and Freezing its Market Valuation

A `Broker` brings a license to market in two deliberate steps, because the market price must be frozen at a known instant rather than drifting with the county's quota position. The first step creates a **Listing** in `DRAFT` from a `license_id`, the `brokerage_id` of the listing firm, and an `ask_price_cents` of at least 100000 — one thousand dollars, a floor that exists only to reject obvious data entry errors. A draft listing carries `open_offer_count` of 0 and has `valuation_basis`, `market_price_cents`, `scarcity_bps_at_activation`, `comp_count_at_activation` and `activated_at` all null; no valuation is computed while the listing is a draft. The `status` enumeration for a listing is `DRAFT`, `ACTIVE`, `UNDER_CONTRACT`, `WITHDRAWN` and `SOLD`, of which `WITHDRAWN` and `SOLD` are terminal.

The second step publishes the listing, advancing `DRAFT → ACTIVE`, and it is the moment at which the market price is fixed. Four preconditions guard it. The underlying license must be in `ACTIVE` or `SAFEKEEPING` status — an `IN_ESCROW` license cannot be listed, and a `TRANSFERRED` one is terminal — and a violation reports `ERR_INVALID_LICENSE_STATE`. There must be no safekeeping filing awaiting decision on that license, since a pending filing means the license's own window is about to change; that violation reports `ERR_SAFEKEEPING_FILING_PENDING`. The selling licensee's `tax_clearance_status` must be `CLEARED`, or the activation is refused with `ERR_SELLER_TAX_CLEARANCE_MISSING`. And no other listing on the same license may already be `ACTIVE` or `UNDER_CONTRACT`, a collision reported as `ERR_INVALID_LISTING_STATE`. The broker may supply a `valuation_basis` to select the variant; when omitted, the county's `default_valuation_basis` is used. Activation then snapshots the county scarcity uplift onto `scarcity_bps_at_activation`, runs the valuation in the selected variant to write `market_price_cents` and `comp_count_at_activation`, records `activated_at` as the current logical instant, and advances the listing's `version` by one.

Pulling a listing back off the market moves it to `WITHDRAWN` from either `DRAFT` or `ACTIVE`, optionally recording a free-text `reason`. It is refused with `ERR_LISTING_HAS_OPEN_OFFERS` whenever `open_offer_count` is greater than zero — a broker must terminate its outstanding draft offers before retiring the listing — and on success the listing's `version` advances by one.

The valuation itself is built from a **comparable set** assembled as follows. Every license in the same county as the subject, of the same `license_class` as the subject, whose `last_transfer_price_cents` is not null, whose `status` is one of `ACTIVE`, `IN_ESCROW`, `SAFEKEEPING` or `TRANSFERRED`, and which is not the subject license itself, contributes its `last_transfer_price_cents` to the set. The subject is always excluded even when it carries its own prior transfer price. Those prices are then sorted into ascending numeric order and their count is the comparable count. When the count is zero, the comparable median is taken to be a statutory floor of 4500000 cents — forty-five thousand dollars — and a reported comparable count of zero is precisely the signal that this fallback was applied. When the count is odd, the median is the middle price. When the count is even, the median is the sum of the two middle prices divided by two, rounded half up to whole cents.

From that median, and from the scarcity uplift in basis points, the two variants are computed:

- **The comparable-sales variant** takes the comparable median, multiplies it by ten thousand plus the scarcity uplift, divides by ten thousand, and rounds half up once to whole cents. It ignores the subject license's own receipts entirely, so two licenses in the same county and class with wildly different revenue are priced identically.
- **The income-multiple variant** takes the subject license's `annual_gross_receipts_cents`, multiplies by 1800 and divides by ten thousand — eighteen percent of trailing annual receipts — then multiplies that by ten thousand plus the scarcity uplift and divides by ten thousand again, and rounds half up exactly once at the very end. The multiple is applied first and the scarcity uplift second, and there is no intermediate rounding between them. It ignores every peer sale, so it diverges from the comparable-sales figure on identical inventory.

Whichever variant the resolved basis selects becomes the listing's `market_price_cents`; the comparable count is stored as `comp_count_at_activation` in either case, including under the income-multiple variant where the comparables did not influence the price.

Because the two variants can differ dramatically, a read-only preview capability lets a `PlatformAdmin`, a `Broker` or a `RegulatorAnalyst` run both variants against the current comparable set and the license's current receipts without writing anything to the listing. Its response reports the `listing_id` and `license_id` under examination, the `default_valuation_basis` configured on the county, the live `comp_count` and `comp_median_cents`, the live `scarcity_bps`, both `comparable_sales_price_cents` and `income_multiple_price_cents`, and `divergence_cents`, which is exactly the income-multiple price minus the comparable-sales price and is therefore signed — negative when the comparable market values the license more highly than its own revenue does.

### 3.4. Drafting a Purchase Agreement and Funding the Escrow

A `Broker` drafts a **Purchase Agreement** against an `ACTIVE` listing, supplying the `listing_id`, the `buyer_id` making the offer, the `premises_id` the license would be transferred to, a `purchase_price_cents` of at least 100000, a `deposit_pct_bps` between 500 and 3500 inclusive, a `closing_window_start` instant, and the `expected_listing_version` concurrency token described in section 2.7. Optionally the broker sets `contingency_days`, the length of the regulator-approval contingency window, which defaults to 120 days and must be between 30 and 365 inclusive. A listing that is not `ACTIVE` refuses the draft with `ERR_INVALID_LISTING_STATE`.

Drafting is a copying act as much as a creating one. Three foreign keys are denormalised onto the agreement so that later steps never have to re-walk the chain: `brokerage_id` is copied from the listing, `license_id` is copied from the listing, and `seller_id` is copied from the `owner_seller_id` of that license. The `contingency_deadline_at` is computed as `closing_window_start` advanced by `contingency_days` days, and it is the exclusive end of the transfer window this agreement reserves on the license. The deposit requirement is computed once here and frozen for the life of the agreement. The new agreement's two status dimensions start at `agreement_status` of `DRAFT` — enumerated `DRAFT`, `EXECUTED`, `CLOSED` and `TERMINATED`, of which the last two are terminal — and `escrow_status` of `AWAITING_DEPOSIT` — enumerated `AWAITING_DEPOSIT`, `HELD`, `RELEASED`, `REFUNDED` and `FORFEITED`, of which the last three are terminal. Its `escrow_balance_cents` is 0, and `commission_mode`, `commission_total_cents`, `county_transfer_fee_cents`, `seller_net_cents`, `executed_at`, `settled_at` and `termination_reason` are all null. The parent listing's `open_offer_count` rises by one and its `version` advances by one, which is what makes a replayed `expected_listing_version` fail.

Competing draft offers on one listing are legitimate, but competing *reservations of the same license window* are not. Before the draft is accepted, the proposed half-open interval running from `closing_window_start` up to but not including `contingency_deadline_at` is compared against the same interval of every other agreement on the same `license_id` whose `agreement_status` is `DRAFT` or `EXECUTED`. Any intersection is refused with `ERR_LICENSE_CONTRACT_OVERLAP`. Because the intervals are half-open, two windows that merely touch — one ending at the exact instant the next begins — do not intersect and are both accepted.

The frozen deposit requirement combines four inputs and is computed in a fixed order. A **class surcharge** in basis points is looked up from the license class of the listed license: 300 basis points for `CLASS_47_ONSALE_GENERAL`, 200 for `CLASS_21_OFFSALE_GENERAL`, and none at all for `CLASS_41_ONSALE_BEER_WINE`. A **scarcity contribution** is the listing's frozen `scarcity_bps_at_activation` divided by five with the fractional part discarded — the snapshot value, never a live recomputation of the county's current position. The buyer's offered `deposit_pct_bps`, the class surcharge and the scarcity contribution are added together, and the sum is capped at 3500 basis points; that capped figure is the effective deposit rate, and it is why the raw offered rate may itself be no more than 3500 even though the surcharges can push the sum above it. The raw deposit amount is the `purchase_price_cents` multiplied by the effective rate and divided by ten thousand. That raw amount is rounded half up to whole cents, and only then is it clamped: the result is at least 500000 cents and at most 7500000 cents. The rounding happens inside the clamp, never after it. The clamped figure is stored as `required_deposit_cents`.

Funding is a separate act, performed by the `Buyer` or by the `EscrowOfficer`, and it advances only the money dimension: `escrow_status` moves `AWAITING_DEPOSIT → HELD` while `agreement_status` is still `DRAFT`. The request carries `amount_cents` and optionally a `deposit_reference`. The amount must equal the agreement's frozen `required_deposit_cents` exactly; partial funding and over-funding are equally refused, with `ERR_DEPOSIT_AMOUNT_MISMATCH`, and a discrepancy of a single cent is enough. Funding appends one ledger row with `entry_type` of `DEPOSIT`, an `amount_cents` equal to the positive deposit amount, a `balance_after_cents` equal to that same amount, a `memo` carrying the supplied `deposit_reference`, and an `occurred_at` of the current logical instant. The agreement's `escrow_balance_cents` is then recomputed from the ledger and its `version` advances by one. Funding touches no county counter whatsoever: the license does not become `IN_ESCROW` until execution, so `escrow_committed_count` is unchanged by money arriving.

The escrow ledger is append-only and is the only channel through which cascade-created money movements can be discovered. Its `entry_type` enumeration is `DEPOSIT`, `RELEASE_COUNTY_FEE`, `RELEASE_COMMISSION`, `RELEASE_SELLER`, `REFUND_BUYER` and `FORFEIT_SELLER`; `amount_cents` is signed, positive only for a deposit and negative for every disbursement, refund and forfeiture row. After every append, the balance projection is replayed from scratch: the agreement's rows are ordered by `occurred_at` ascending with `created_at` ascending as the tie-break, a running total is accumulated across them in that order, each row's `balance_after_cents` is set to the running total as of that row, and the agreement's `escrow_balance_cents` is set to the final running total. No row is ever mutated or deleted, so the projection is a pure replay, and a `memo` on every row carries a human-readable label of the movement.

Abandoning an offer before any money is held is the `Broker`'s prerogative: supplying a mandatory `reason`, the broker moves `agreement_status` `DRAFT → TERMINATED`. This is permitted only while `escrow_status` is `AWAITING_DEPOSIT`, since nothing is held and no settlement is owed; an attempt while funds are still `HELD` is refused with `ERR_ESCROW_MUST_BE_SETTLED_FIRST`, and an attempt after the escrow has already reached `RELEASED`, `REFUNDED` or `FORFEITED` is refused with `ERR_ESCROW_ALREADY_SETTLED`. Termination writes the supplied text to `termination_reason`, moves every agency disclosure on that agreement that is `PENDING_ACKS` or `FULLY_ACKED` to `VOID`, recomputes the parent listing's `open_offer_count` — which therefore falls by one — advancing the listing's `version`, and advances the agreement's own `version`.

### 3.5. Agency Disclosure and Execution of the Agreement

No agreement in this system can be executed until the brokerage's representation of the parties has been disclosed in writing and acknowledged by everyone it claims to represent. A `Broker` files a **Dual Agency Disclosure** against an agreement by naming the `agreement_id` and asserting two booleans: `represents_seller`, true when the listing brokerage represents the seller on this agreement, and `represents_buyer`, true when the same brokerage also represents the buyer. An opaque `disclosure_text_ref` pointing at the signed instrument may accompany the filing and defaults to null. A disclosure asserting both representations is dual agency, and filing one for a brokerage whose `dual_agency_policy` is `PROHIBITED` is refused outright with `ERR_DUAL_AGENCY_PROHIBITED`. A disclosure asserting neither representation is meaningless and is refused with `ERR_PARTY_NOT_REPRESENTED`. A newly filed disclosure carries `status` of `PENDING_ACKS` — the enumeration being `PENDING_ACKS`, `FULLY_ACKED` and `VOID` — with `seller_ack_at` and `buyer_ack_at` both null.

A represented party signs by supplying a `party` value of either `BUYER` or `SELLER`; the `Buyer` role signs as `BUYER` and the `Seller` role signs as `SELLER`. Signing as a party the disclosure does not actually represent is refused with `ERR_PARTY_NOT_REPRESENTED` — a `BUYER` acknowledgement requires `represents_buyer` to be true, and a `SELLER` acknowledgement requires `represents_seller` to be true — and a second acknowledgement by the same party is refused with `ERR_ALREADY_ACKNOWLEDGED`. A successful acknowledgement stamps `buyer_ack_at` or `seller_ack_at` with the current logical instant and advances the disclosure's `version` by one. As soon as every party the disclosure represents carries an acknowledgement timestamp, `status` is promoted `PENDING_ACKS → FULLY_ACKED`. For a single-sided disclosure that means one signature suffices; for a dual-agency disclosure both are required.

Execution is the pivot of the whole proceeding and takes no request body at all: every gate is read from records the platform already holds. A `Broker` executing an agreement must satisfy all of the following, and the order in which a violation is reported is governed by section 2.9. The agreement's `agreement_status` must be `DRAFT` — a non-draft agreement reports `ERR_INVALID_AGREEMENT_STATE`. The money dimension must already be `HELD`, so an unfunded agreement reports `ERR_ESCROW_NOT_HELD`; this is the cross-dimension guard that forces funding to precede execution. A `FULLY_ACKED` disclosure must exist on the agreement, or the attempt is refused with `ERR_DUAL_AGENCY_DISCLOSURE_REQUIRED`. The buyer's stored qualification must satisfy section 3.2, or `ERR_BUYER_NOT_QUALIFIED`. The premises' `suitability_status` must be `SUITABLE` or `CONDITIONAL`, never `UNSUITABLE`, or `ERR_PREMISES_UNSUITABLE`. The listing must still be `ACTIVE`, or `ERR_INVALID_LISTING_STATE`. The license must be in `ACTIVE` or `SAFEKEEPING` status, or `ERR_INVALID_LICENSE_STATE`; when it is in `SAFEKEEPING`, there must additionally be no safekeeping filing awaiting decision on it. And the logical clock must be strictly before `contingency_deadline_at`, or the attempt is refused with `ERR_CONTINGENCY_DEADLINE_PASSED` — equality with the deadline is already too late.

On success, `executed_at` is stamped with the current logical instant and `commission_mode` is frozen from the `FULLY_ACKED` disclosure: it becomes `DUAL_AGENCY` when that disclosure asserts both `represents_seller` and `represents_buyer`, and `SINGLE_AGENCY` in every other case. The agreement moves `DRAFT → EXECUTED`. The license moves `ACTIVE → IN_ESCROW` or `SAFEKEEPING → IN_ESCROW` as appropriate; when it comes from `SAFEKEEPING`, its `safekeeping_expires_at` is deliberately retained unchanged so that the window can be restored if the transfer later fails. The listing moves `ACTIVE → UNDER_CONTRACT`. The county's counters are recomputed, so `escrow_committed_count` rises by one for a counted license, and the county's `version` advances. The agreement, the license and the listing each have their own `version` advanced by one. Sibling draft offers on the same listing are left untouched at `DRAFT` — they are not cancelled — but because the listing is no longer `ACTIVE` none of them can be executed any more.

### 3.6. The Transfer Application: Filing, Deficiency Rounds and Publication

With the license in escrow, the `Broker` files the **Transfer Application** that asks the licensing authority to move the license to the buyer. The filing names the `agreement_id` of the executed agreement, tenders `fee_paid_cents`, and may carry an opaque `applicant_statement_ref` pointing at the prepared application packet. The agreement must be `EXECUTED` with its escrow `HELD`. The application copies `license_id` and `premises_id` off the agreement, lands directly in `SUBMITTED` — its `status` enumeration being `SUBMITTED`, `UNDER_REVIEW`, `DEFICIENT`, `POSTED`, `PROTESTED`, `APPROVED` and `DENIED`, of which the last two are terminal — and starts with `deficiency_round_count` of 0, `decision` null, `decided_at` null, `accepted_by_analyst_id` null, `last_deficiency_codes` null, and `posting_started_at`, `posting_ends_at` and `protest_deadline_at` all null. Its `fee_paid_total_cents` is initialised to the amount just tendered.

Filing is the most heavily gated create in the system, and it re-checks four regulatory conditions that were already relevant at execution. The premises must clear the county's distance minima — both the school distance and the church distance must be at least the county's respective minimum — or the filing is refused with `ERR_DISTANCE_RESTRICTION_VIOLATION`. The premises must not be `UNSUITABLE`, or `ERR_PREMISES_UNSUITABLE`. The buyer's qualification must satisfy section 3.2, or `ERR_BUYER_NOT_QUALIFIED`. A `FULLY_ACKED` disclosure must be on the agreement, or `ERR_DUAL_AGENCY_DISCLOSURE_REQUIRED`. And the selling licensee's `tax_clearance_status` must be `CLEARED`, or `ERR_SELLER_TAX_CLEARANCE_MISSING`.

The filing fee is computed in **three pinned steps, and the evaluation order is normative**. Step one sums an exact integer subtotal: a filing base of 30000 cents, plus a class fee determined by the license class — 120000 cents for `CLASS_47_ONSALE_GENERAL`, 90000 cents for `CLASS_21_OFFSALE_GENERAL`, 45000 cents for `CLASS_41_ONSALE_BEER_WINE` — plus a posting fee of 15000 cents, plus 30000 cents for each deficiency round already recorded on the application. Step two selects an expedite surcharge rate **from that step-one subtotal, not from the final fee**: a subtotal of 200000 cents or more attracts 800 basis points, otherwise a subtotal of 120000 cents or more attracts 500 basis points, otherwise the rate is 200 basis points. Step three adds to the subtotal the subtotal multiplied by the selected rate and divided by ten thousand, rounded half up to whole cents; the subtotal itself is exact integer arithmetic and is never rounded. The result is stored as `filing_fee_cents`. Tiering on the final total rather than on the subtotal produces a different number whenever the subtotal sits just below a tier edge, and that reading is wrong.

The deficiency round count used in step one is the count **as it stands at the moment the fee is computed** — zero on the original filing, one after the first deficiency notice, two after the second — so the resubmission fee is strictly larger than the original. The `fee_paid_cents` tendered must equal the computed fee exactly, on the original filing and on every resubmission alike; any difference is refused with `ERR_FILING_FEE_MISMATCH`.

The review cycle then runs, and it is deliberately cyclic. A `RegulatorAnalyst` takes the application into review, advancing `SUBMITTED → UNDER_REVIEW`; this act writes the caller's `X-User-ID` into `accepted_by_analyst_id` and advances the application's `version`. From `UNDER_REVIEW`, the analyst may kick the application back by issuing a deficiency notice carrying `deficiency_codes`, advancing `UNDER_REVIEW → DEFICIENT`, incrementing `deficiency_round_count` by one and storing the supplied codes in `last_deficiency_codes`. At most two deficiency rounds are permitted: the notice is allowed only while `deficiency_round_count` is less than 2, and a third attempt is refused with `ERR_DEFICIENCY_LIMIT_EXCEEDED`. From `DEFICIENT`, the `Broker` refiles, advancing `DEFICIENT → SUBMITTED` with a fresh `fee_paid_cents` and optionally a fresh `applicant_statement_ref`. Refiling requires the logical clock to be at or before `contingency_deadline_at` — equality is still in time here, unlike at execution — and a late refiling is refused with `ERR_CONTINGENCY_DEADLINE_PASSED`. A successful refiling recomputes and rewrites `filing_fee_cents` at the current round count, adds the newly tendered `fee_paid_cents` to the running `fee_paid_total_cents`, and deliberately **retains** `accepted_by_analyst_id`, so the segregation-of-duties comparand survives the revision loop and the accepting analyst cannot recover decision authority by sending the application through the cycle again. The full cycle is therefore `SUBMITTED → UNDER_REVIEW → DEFICIENT → SUBMITTED`, traversable at most twice.

Publication is the analyst's next act, advancing `UNDER_REVIEW → POSTED`. It carries no request body and enforces four preconditions. The premises' `suitability_status` must be `SUITABLE` or `CONDITIONAL`, and its `conditional_use_permit_status` must be either `NOT_REQUIRED` or `GRANTED` — an outstanding, pending or denied permit blocks publication with `ERR_PREMISES_UNSUITABLE` even though it does not block execution. The distance minima are re-checked, reporting `ERR_DISTANCE_RESTRICTION_VIOLATION` on violation. And the proposed publication must not collide with another live publication on the same premises: for every other application on the same `premises_id` whose `status` is `POSTED`, `PROTESTED` or `APPROVED`, the current logical instant must be strictly later than that other application's `posting_ends_at` advanced by a statutory quiet buffer of 30 days. The intervals here are closed and the buffer is additive, so equality collides — an instant exactly on the buffered boundary is a conflict, refused with `ERR_POSTING_WINDOW_CONFLICT`.

Publication then writes three instants. `posting_started_at` is the current logical instant. `posting_ends_at` is `posting_started_at` advanced by the county's `posting_period_days`. `protest_deadline_at` is `posting_started_at` advanced by whichever is smaller of the county's `posting_period_days` and its `protest_window_days`, so a county that accepts protests for a shorter span than it publishes closes the protest door before the publication window ends. The application's `version` advances by one.

### 3.7. Protests and the Regulator's Decision

While an application is published, any member of the public may object, and the regulator records the objection on their behalf. A `RegulatorAnalyst` files a **Protest** by naming the `application_id`, the `protestant_name` of the protesting party of record, and the statutory `grounds` asserted, drawn from `UNDUE_CONCENTRATION`, `DISTANCE_RESTRICTION`, `PUBLIC_WELFARE` and `ZONING`. An optional `response_due_days` sets how long the broker has to answer and defaults to 15 days. The application must be `POSTED`, and the current logical instant must be at or before that application's `protest_deadline_at` — the deadline instant itself is still open; anything later is refused with `ERR_PROTEST_WINDOW_CLOSED`. The accepted protest carries `status` of `OPEN` — its enumeration being `OPEN`, `RESPONDED`, `SUSTAINED` and `OVERRULED`, of which the last two are terminal — with `filed_at` set to the current logical instant, `response_due_at` set to `filed_at` advanced by `response_due_days` days, and `response_text_ref` and `response_submitted_at` both null. Accepting a protest also cascades onto the application, moving it `POSTED → PROTESTED` and advancing the application's `version` by one.

The `Broker` answers a protest by supplying `response_text_ref`, moving the protest `OPEN → RESPONDED`. This requires the current logical instant to be at or before that protest's `response_due_at`, with a late answer refused by `ERR_PROTEST_RESPONSE_WINDOW_CLOSED`, and requires the parent application to be in `PROTESTED` status. A protest that is not `OPEN` refuses the answer with `ERR_INVALID_PROTEST_STATE`. A successful answer stamps `response_submitted_at` with the current logical instant, stores the supplied reference, and advances the protest's `version`.

The decision is the analyst's final act on the application, supplying a `decision` of either `APPROVED` or `DENIED` and optionally a `decision_note`, and it is reachable from `POSTED` or from `PROTESTED`. Three preconditions are common to all four combinations. The publication period must have fully elapsed: the logical clock must be **strictly later** than `posting_ends_at`, and equality is explicitly not elapsed, so a decision at the exact posting end instant is refused with `ERR_POSTING_PERIOD_NOT_ELAPSED`. The caller's `X-User-ID` must differ from `accepted_by_analyst_id`, or the decision is refused with `ERR_SEGREGATION_OF_DUTIES`. And the application must not already be terminal.

Where an application has protests against it, two further temporal rules apply and they cut in opposite directions. If any protest on the application is still `OPEN` and the logical clock is at or before that protest's `response_due_at`, the protestant's answer window has not run out and any decision is premature, refused with `ERR_PROTEST_RESPONSE_PENDING`. If any protest is still `OPEN` and the clock has moved strictly past its `response_due_at`, the broker has simply failed to answer, and the only lawful outcome is denial: an `APPROVED` decision in that situation is refused with `ERR_UNANSWERED_PROTEST_REQUIRES_DENIAL`. Put positively: an approval from `PROTESTED` requires every protest on the application to be `RESPONDED`, whereas a denial from `PROTESTED` is lawful either when every protest is `RESPONDED` or when at least one is `OPEN` with its response deadline already past. From `POSTED`, where by definition no protest has been accepted, both outcomes need only the three common preconditions.

An approval writes `decision` of `APPROVED` and `decided_at` of the current logical instant, then runs the five-hop closing cascade of section 2.8 in full. The license moves `IN_ESCROW → TRANSFERRED`; its `transferred_to_buyer_id` is set to the agreement's `buyer_id`, and its `last_transfer_price_cents` is overwritten with the agreement's `purchase_price_cents`, which is what makes the license a comparable for future comparable-sales valuations in its county and class. The listing moves `UNDER_CONTRACT → SOLD`. The agreement moves `EXECUTED → CLOSED` while its `escrow_status` deliberately stays `HELD`, because approval does not move money. Every protest on the application still `OPEN` or `RESPONDED` moves to `OVERRULED`. The county's counters are recomputed: `escrow_committed_count` falls by one because the license left `IN_ESCROW`, while `quota_licenses_counted` is unchanged because a `TRANSFERRED` license still occupies its quota slot. The application, the license, the listing, the agreement, each affected protest and the county all have their `version` advanced by one.

A denial writes `decision` of `DENIED` and `decided_at` of the current logical instant, and its consequences are deliberately narrow. Every protest on the application that is `OPEN` or `RESPONDED` moves to `SUSTAINED` — a `RESPONDED` protest is sustained unconditionally, and an `OPEN` one is sustained precisely because its response deadline has already passed. No license field, no listing field and no agreement field is touched: the license stays `IN_ESCROW` until the escrow officer refunds, because denial alone never moves the license. The application's `version` advances by one, as does each sustained protest's.

### 3.8. Escrow Settlement and the Compensating Cascade

Settlement is the sole preserve of the `EscrowOfficer`, who supplies a `disposition` of `RELEASE`, `REFUND` or `FORFEIT` and optionally a `memo` recorded on the ledger row. In every branch the money dimension must currently be `HELD`: an attempt while it is still `AWAITING_DEPOSIT` is refused with `ERR_ESCROW_NOT_HELD`, and an attempt once it has already reached `RELEASED`, `REFUNDED` or `FORFEITED` is refused with `ERR_ESCROW_ALREADY_SETTLED`. Each branch has its own cross-entity dependency, its own ledger shape and its own cascade, and the three are mutually exclusive.

A **release** advances `HELD → RELEASED` and is the only branch that pays anybody. It requires the agreement's `agreement_status` to be `CLOSED`, or it is refused with `ERR_INVALID_AGREEMENT_STATE`, and it requires the agreement's transfer application to be `APPROVED`, or it is refused with `ERR_TRANSFER_NOT_APPROVED`. The contingency deadline does not gate a release; the release is gated on the agreement being closed and the application being approved.

The released funds run down a **three-bucket waterfall in a fixed order**, and the commission arithmetic is where rounding placement matters most. First the gross commission is computed as the agreement's frozen `purchase_price_cents` multiplied by the listing brokerage's `commission_rate_bps` and divided by ten thousand, and this gross figure is held as an exact value and is **not** yet rounded. When `commission_mode` is `DUAL_AGENCY`, the gross is split into two lines: the seller-side line is the gross multiplied by six thousand and divided by ten thousand — that is, ten thousand less the dual-agency split of 4000 basis points — rounded half up to whole cents; the buyer-side line is the gross multiplied by 4000 and divided by ten thousand, likewise rounded half up to whole cents; and `commission_total_cents` is the sum of those two already-rounded lines. When `commission_mode` is `SINGLE_AGENCY` there is only one line: the seller-side line is the gross rounded half up to whole cents, the buyer-side line is zero, and `commission_total_cents` equals the single rounded line. Rounding each line and then summing is normative; summing the exact lines and rounding the total is the wrong reading and yields a figure one cent different whenever both split lines land on a half cent, which is why the same price under the two commission modes can differ by exactly one cent.

Next, `county_transfer_fee_cents` is the `purchase_price_cents` multiplied by the county's `transfer_fee_bps` and divided by ten thousand, rounded half up to whole cents. The waterfall then takes the county fee as bucket one, the commission total as bucket two, and leaves `seller_net_cents` as bucket three: the escrow balance held at settlement time, less the county fee, less the commission total. If that residual would be negative, the entire release is refused with `ERR_ESCROW_INSUFFICIENT_FOR_DISBURSEMENT` and **no ledger row is written at all** — the escrow is left exactly as it was found.

On success the three bucket figures are written to the agreement and three ledger rows are appended **in this pinned order**: `RELEASE_COUNTY_FEE`, then `RELEASE_COMMISSION`, then `RELEASE_SELLER`. Each carries a negative `amount_cents` and a `balance_after_cents` lower than the row before it, so the balance walks down to zero across the three rows. The agreement's `escrow_balance_cents` is recomputed to 0, `settled_at` is stamped with the current logical instant, and the agreement's `version` advances by one. A release touches no county counter, because the license already left `IN_ESCROW` back at the approval decision.

A **refund** advances `HELD → REFUNDED` and requires the agreement's transfer application to be `DENIED`, or it is refused with `ERR_TRANSFER_NOT_APPROVED`. It appends exactly one ledger row of `entry_type` `REFUND_BUYER` whose `amount_cents` is the negative of the whole held balance and whose `balance_after_cents` is 0. The three settlement buckets — `county_transfer_fee_cents`, `commission_total_cents` and `seller_net_cents` — all stay null, because no commission is ever earned on a failed transfer.

A **forfeiture** advances `HELD → FORFEITED` and is the divergent branch of the same fork: the buyer loses the deposit to the seller instead of recovering it, and again no commission line is ever written. It requires the logical clock to be **strictly past** `contingency_deadline_at`, and an attempt at or before that instant is refused with `ERR_CONTINGENCY_STILL_OPEN`. It also requires the transfer application to still be in flight — its `status` must be one of `SUBMITTED`, `UNDER_REVIEW`, `DEFICIENT`, `POSTED` or `PROTESTED`. It appends exactly one ledger row of `entry_type` `FORFEIT_SELLER` whose `amount_cents` is the negative of the whole held balance and whose `balance_after_cents` is 0, and it too leaves all three settlement buckets null.

Both the refund and the forfeiture drive `escrow_balance_cents` to 0, stamp `settled_at` with the current logical instant, advance the agreement's `version`, and then run the four-hop compensating cascade of section 2.8. The contract dimension moves `EXECUTED → TERMINATED`, and `termination_reason` is written by the cascade rather than by a client: it reads `ESCROW_REFUNDED` after a refund and `ESCROW_FORFEITED` after a forfeiture. Every agency disclosure on the agreement that is `PENDING_ACKS` or `FULLY_ACKED` moves to `VOID`. The license then leaves `IN_ESCROW` for whichever pre-escrow status is still lawful, and this is a genuine branch on the logical clock: if the license's `safekeeping_expires_at` is null, or the clock has reached or passed it, the license returns `IN_ESCROW → ACTIVE`; if `safekeeping_expires_at` is non-null and the clock is still strictly before it, the pre-escrow safekeeping window has not lapsed and the license returns `IN_ESCROW → SAFEKEEPING` instead, resuming the window it was holding. Either way the county's counters are recomputed so that `escrow_committed_count` falls by one and the county's `version` advances, and the license's `version` advances. Finally the listing returns `UNDER_CONTRACT → ACTIVE`, its `open_offer_count` is recomputed over whatever draft agreements remain on it, and its `version` advances — so a failed transfer puts the license back on the market rather than stranding it.

### 3.9. Safekeeping and Nonuse Extension Filings

A license whose premises has stopped operating is at risk of statutory revocation for nonuse, and the remedy is to petition the regulator to hold it in safekeeping. A `Broker` or the owning `Seller` files a **Safekeeping Filing** by naming the `license_id`, a `filing_type` of either `INITIAL` or `EXTENSION`, a `requested_months` figure between 1 and 24 inclusive, and the `expected_license_version` concurrency token of section 2.7. Only one filing per license may be awaiting decision at a time; a second one opened while the license's `safekeeping_filing_pending` flag is set is refused with `ERR_SAFEKEEPING_FILING_PENDING`. A license that is `IN_ESCROW` may not be petitioned at all, which reports `ERR_INVALID_LICENSE_STATE`.

An `INITIAL` filing places an idle license into safekeeping and is admissible only once the license has actually been idle. The nonuse period is the number of whole UTC calendar days between the license's `last_active_date` and the date part of the current logical instant, and it must be at least 180 days — exactly 180 qualifies. A premature petition is refused with `ERR_NONUSE_PERIOD_NOT_REACHED`. For an initial filing, `extension_index` is 0, `granted_months` is the requested figure capped at 12 months, and `effective_from` is the current logical instant.

An `EXTENSION` filing prolongs a window that already exists. It is admissible only while the license's `safekeeping_extensions_count` is less than 2, so a license may hold an initial window and at most two extensions; a petition for a fourth window is refused with `ERR_SAFEKEEPING_EXTENSION_LIMIT`. For an extension, `extension_index` is the license's current `safekeeping_extensions_count` plus one, `granted_months` is the requested figure capped at 6 months, and `effective_from` is the license's current `safekeeping_expires_at` — windows are **chained, never overlapped**, so an extension begins exactly where the prior window ended rather than at the filing instant.

From those, `expires_at` is `effective_from` advanced by `granted_months` whole calendar months, preserving the day-of-month and clamping to the last day of the target month where the target month is too short. The filing fee doubles with each step: `fee_cents` is a base of 20000 cents multiplied by two raised to the power of `extension_index`, giving 20000 cents for an initial filing, 40000 cents for a first extension and 80000 cents for a second. The filing is created with `status` of `PENDING` — enumerated `PENDING`, `GRANTED` and `DENIED`, of which the last two are terminal — and `decided_at` null. Filing also sets the license's `safekeeping_filing_pending` flag to true and advances the license's `version` by one, which is what makes a replayed `expected_license_version` fail.

A `RegulatorAnalyst` then decides the filing by supplying a `decision` of `GRANT` or `DENY`; the filing must still be `PENDING`. A grant additionally requires the license to be in the right state for the filing type — `ACTIVE` for an `INITIAL` filing and `SAFEKEEPING` for an `EXTENSION` — and an extension grant additionally requires the license's `safekeeping_extensions_count` to still be less than 2. Granting stamps `decided_at` with the current logical instant and applies the computed window to the license: `safekeeping_expires_at` becomes the filing's `expires_at` and `safekeeping_extensions_count` becomes the filing's `extension_index`. For an initial grant the license moves `ACTIVE → SAFEKEEPING`; for an extension grant the license stays in `SAFEKEEPING` — a self-loop that prolongs the window without leaving the state — and its extension count therefore rises by one. Because a license's status changed, the county's counters are recomputed. Denying a filing also stamps `decided_at`, but leaves `safekeeping_expires_at` exactly as it was and moves the license nowhere. Both outcomes clear the license's `safekeeping_filing_pending` flag and advance the license's `version` by one, and both advance the filing's own `version` by one.

The pending flag has two consequences beyond the filing itself. While it is set, a listing on that license cannot be activated, refused with `ERR_SAFEKEEPING_FILING_PENDING`. And a license sitting in `SAFEKEEPING` cannot be moved into escrow by an execution while a filing on it is still awaiting decision, because the window that execution must preserve is not yet settled.

## 4. Endpoint Definitions

Operations that bring a genuinely new resource into existence — a county, a party profile, a brokerage, a license, a premises, a listing, a purchase agreement, an agency disclosure, a transfer application, a protest, a safekeeping filing — answer with `201 Created`. Every other successful operation, including every state transition, every recomputation of a derived field, every read and the logical-clock capability, answers with `200 OK`. There is no shared URL prefix: every collection is mounted at the root. Path variables are named for the resource they address — `county_id`, `seller_id`, `buyer_id`, `brokerage_id`, `license_id`, `premises_id`, `listing_id`, `agreement_id`, `entry_id`, `disclosure_id`, `application_id`, `protest_id` and `filing_id` — and "Any" in the role column means all six declared roles may call the endpoint.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/counties` | Register a licensing county with its quota ceiling, zoning codes, distance minima and fee rate | PlatformAdmin |
| GET  | `/counties/{county_id}` | Read one county including its live quota counters | Any |
| POST | `/seller-profiles` | Register a selling licensee party | PlatformAdmin, Broker |
| GET  | `/seller-profiles/{seller_id}` | Read one seller profile | PlatformAdmin, Broker, Seller, RegulatorAnalyst, EscrowOfficer |
| POST | `/buyer-profiles` | Register a prospective transferee | PlatformAdmin, Broker |
| GET  | `/buyer-profiles/{buyer_id}` | Read one buyer profile with its latest qualification result | PlatformAdmin, Broker, Buyer, RegulatorAnalyst, EscrowOfficer |
| POST | `/buyer-profiles/{buyer_id}/qualification-review` | Score the buyer against a named premises in the requested review mode | RegulatorAnalyst |
| POST | `/brokerages` | Register a brokerage firm with its commission rate and dual-agency policy | PlatformAdmin |
| GET  | `/brokerages/{brokerage_id}` | Read one brokerage | Any |
| POST | `/licenses` | Add a license to a county's inventory in ACTIVE status | PlatformAdmin |
| GET  | `/licenses/{license_id}` | Read one license including its safekeeping window | Any |
| GET  | `/licenses` | Filtered, paginated license inventory | Any |
| GET  | `/licenses/{license_id}/safekeeping-filings` | List the safekeeping filings on one license | PlatformAdmin, Broker, Seller, RegulatorAnalyst |
| POST | `/premises` | Register a candidate premises for one buyer in one county | Broker, Buyer |
| GET  | `/premises/{premises_id}` | Read one premises with its suitability verdict and reason code | PlatformAdmin, Broker, Buyer, RegulatorAnalyst, EscrowOfficer |
| GET  | `/premises` | Filtered, paginated premises list | PlatformAdmin, Broker, Buyer, RegulatorAnalyst, EscrowOfficer |
| POST | `/premises/{premises_id}/zoning-verification` | Record the conditional-use outcome and any corrected survey facts | RegulatorAnalyst |
| POST | `/premises/{premises_id}/landlord-consent` | Record the landlord's consent decision for the lease assignment | Broker, Buyer |
| POST | `/listings` | Create a DRAFT brokerage listing for one license | Broker |
| GET  | `/listings/{listing_id}` | Read one listing including its frozen activation-time valuation | Any |
| GET  | `/listings` | Filtered, paginated listing list | Any |
| GET  | `/listings/{listing_id}/valuation-preview` | Computed read: both valuation variants and their divergence, writing nothing | PlatformAdmin, Broker, RegulatorAnalyst |
| POST | `/listings/{listing_id}/activate` | Publish the listing and freeze its market valuation | Broker |
| POST | `/listings/{listing_id}/withdraw` | Pull the listing off the market | Broker |
| POST | `/purchase-agreements` | Draft a purchase agreement against an ACTIVE listing | Broker |
| GET  | `/purchase-agreements/{agreement_id}` | Read one agreement: both status dimensions, deposit, balance and buckets | Any |
| GET  | `/purchase-agreements` | Filtered, paginated agreement list | Any |
| GET  | `/purchase-agreements/{agreement_id}/escrow-ledger` | Immutable escrow ledger for one agreement in append order | Any |
| GET  | `/escrow-ledger-entries/{entry_id}` | Read one immutable escrow ledger row | Any |
| GET  | `/escrow-ledger-entries` | Filtered, paginated ledger list across agreements in append order | Any |
| GET  | `/purchase-agreements/{agreement_id}/dual-agency-disclosures` | List the agency disclosures filed on one agreement | PlatformAdmin, Broker, Buyer, Seller, RegulatorAnalyst |
| POST | `/purchase-agreements/{agreement_id}/escrow-deposit` | Fund the escrow with the exact required deposit | Buyer, EscrowOfficer |
| POST | `/purchase-agreements/{agreement_id}/execute` | Execute the agreement and commit the license and listing | Broker |
| POST | `/purchase-agreements/{agreement_id}/terminate` | Abandon a DRAFT agreement before any money is held | Broker |
| POST | `/purchase-agreements/{agreement_id}/escrow-settlement` | Dispose of the held funds by release, refund or forfeiture | EscrowOfficer |
| POST | `/dual-agency-disclosures` | File the brokerage's agency-representation disclosure on an agreement | Broker |
| GET  | `/dual-agency-disclosures/{disclosure_id}` | Read one disclosure with its acknowledgement timestamps | PlatformAdmin, Broker, Buyer, Seller, RegulatorAnalyst |
| GET  | `/dual-agency-disclosures` | Filtered, paginated disclosure list | PlatformAdmin, Broker, Buyer, Seller, RegulatorAnalyst |
| POST | `/dual-agency-disclosures/{disclosure_id}/acknowledge` | A represented party signs the disclosure | Buyer, Seller |
| POST | `/transfer-applications` | File the license-transfer application for an EXECUTED agreement | Broker |
| GET  | `/transfer-applications/{application_id}` | Read one application: rounds, accepting analyst, windows and decision | Any |
| GET  | `/transfer-applications` | Filtered, paginated application list | Any |
| GET  | `/transfer-applications/{application_id}/protests` | List the protests filed against one application | PlatformAdmin, Broker, Seller, RegulatorAnalyst |
| POST | `/transfer-applications/{application_id}/accept-review` | Take the application into review and record the accepting analyst | RegulatorAnalyst |
| POST | `/transfer-applications/{application_id}/deficiency` | Issue a deficiency notice and kick the application back | RegulatorAnalyst |
| POST | `/transfer-applications/{application_id}/resubmit` | Refile a DEFICIENT application with the recomputed fee | Broker |
| POST | `/transfer-applications/{application_id}/post-notice` | Publish the statutory notice and open the posting and protest windows | RegulatorAnalyst |
| POST | `/transfer-applications/{application_id}/decision` | Approve or deny the transfer after the posting period has elapsed | RegulatorAnalyst |
| POST | `/protests` | Record a third-party protest against a POSTED application | RegulatorAnalyst |
| GET  | `/protests/{protest_id}` | Read one protest with its response deadline and answer timestamp | PlatformAdmin, Broker, Seller, RegulatorAnalyst |
| GET  | `/protests` | Filtered, paginated protest list | PlatformAdmin, Broker, Seller, RegulatorAnalyst |
| POST | `/protests/{protest_id}/response` | Answer an OPEN protest on or before its response deadline | Broker |
| POST | `/safekeeping-filings` | File an initial safekeeping petition or a nonuse extension | Broker, Seller |
| GET  | `/safekeeping-filings/{filing_id}` | Read one safekeeping filing including its granted window and fee | PlatformAdmin, Broker, Seller, RegulatorAnalyst |
| GET  | `/safekeeping-filings` | Filtered, paginated safekeeping-filing list | PlatformAdmin, Broker, Seller, RegulatorAnalyst |
| POST | `/safekeeping-filings/{filing_id}/decide` | Grant or deny the safekeeping filing | RegulatorAnalyst |
| POST | `/_clock/set_current_utc` | Set the server's logical clock (test-driving capability) | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_ROLE_NOT_PERMITTED` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_COUNTY_NOT_FOUND` | 404 |
| `ERR_SELLER_NOT_FOUND` | 404 |
| `ERR_BUYER_NOT_FOUND` | 404 |
| `ERR_BROKERAGE_NOT_FOUND` | 404 |
| `ERR_LICENSE_NOT_FOUND` | 404 |
| `ERR_PREMISES_NOT_FOUND` | 404 |
| `ERR_LISTING_NOT_FOUND` | 404 |
| `ERR_AGREEMENT_NOT_FOUND` | 404 |
| `ERR_DISCLOSURE_NOT_FOUND` | 404 |
| `ERR_APPLICATION_NOT_FOUND` | 404 |
| `ERR_PROTEST_NOT_FOUND` | 404 |
| `ERR_FILING_NOT_FOUND` | 404 |
| `ERR_STALE_LISTING_VERSION` | 412 |
| `ERR_STALE_LICENSE_VERSION` | 412 |
| `ERR_INVALID_LICENSE_STATE` | 409 |
| `ERR_INVALID_LISTING_STATE` | 409 |
| `ERR_INVALID_AGREEMENT_STATE` | 409 |
| `ERR_ESCROW_NOT_HELD` | 409 |
| `ERR_ESCROW_ALREADY_SETTLED` | 409 |
| `ERR_ESCROW_MUST_BE_SETTLED_FIRST` | 409 |
| `ERR_INVALID_APPLICATION_STATE` | 409 |
| `ERR_INVALID_PROTEST_STATE` | 409 |
| `ERR_ALREADY_TERMINAL` | 409 |
| `ERR_DISTANCE_RESTRICTION_VIOLATION` | 422 |
| `ERR_PREMISES_UNSUITABLE` | 422 |
| `ERR_BUYER_NOT_QUALIFIED` | 422 |
| `ERR_SELLER_TAX_CLEARANCE_MISSING` | 422 |
| `ERR_DUAL_AGENCY_DISCLOSURE_REQUIRED` | 422 |
| `ERR_DUAL_AGENCY_PROHIBITED` | 422 |
| `ERR_PARTY_NOT_REPRESENTED` | 422 |
| `ERR_ALREADY_ACKNOWLEDGED` | 422 |
| `ERR_COUNTY_QUOTA_EXHAUSTED` | 409 |
| `ERR_LICENSE_CONTRACT_OVERLAP` | 409 |
| `ERR_POSTING_WINDOW_CONFLICT` | 409 |
| `ERR_DEFICIENCY_LIMIT_EXCEEDED` | 409 |
| `ERR_LISTING_HAS_OPEN_OFFERS` | 409 |
| `ERR_PROTEST_WINDOW_CLOSED` | 409 |
| `ERR_PROTEST_RESPONSE_WINDOW_CLOSED` | 409 |
| `ERR_POSTING_PERIOD_NOT_ELAPSED` | 409 |
| `ERR_PROTEST_RESPONSE_PENDING` | 409 |
| `ERR_UNANSWERED_PROTEST_REQUIRES_DENIAL` | 409 |
| `ERR_CONTINGENCY_DEADLINE_PASSED` | 409 |
| `ERR_CONTINGENCY_STILL_OPEN` | 409 |
| `ERR_TRANSFER_NOT_APPROVED` | 409 |
| `ERR_SAFEKEEPING_EXTENSION_LIMIT` | 409 |
| `ERR_SAFEKEEPING_FILING_PENDING` | 409 |
| `ERR_NONUSE_PERIOD_NOT_REACHED` | 422 |
| `ERR_DEPOSIT_AMOUNT_MISMATCH` | 422 |
| `ERR_FILING_FEE_MISMATCH` | 422 |
| `ERR_ESCROW_INSUFFICIENT_FOR_DISBURSEMENT` | 422 |
