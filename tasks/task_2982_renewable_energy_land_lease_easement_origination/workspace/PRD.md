# Renewable Land Origination API — Product Requirements Document

## 1. Introduction

Utility-scale wind and solar projects live or die on land control, and land control is won parcel by parcel long before a turbine or a tracker is ordered. A renewable land team must screen candidate ground for interconnection proximity, resource quality, terrain buildability and title condition; approach owners of record with option agreements whose commercial terms are negotiated in rounds; clear mineral severances, unreleased liens, mortgage subordinations and missing access easements; buy back buildable area from setback ordinances through neighbor consents; route collection lines and gen-tie corridors across the parcels it has assembled; and finally exercise its options, record notices of lease with the county, post reclamation security and administer rent for decades. Today that work is scattered across spreadsheets, a title attorney's inbox and a payables clerk's memory, and the most expensive failures come from the seams — an option exercised against acreage that a revoked consent had already shrunk, a memorandum recorded for a payee with no W-9 on file, a rent invoice billed on deeded acres when the as-built acreage is what the lease actually conveys.

This document specifies the **Renewable Land Origination API**, the system of record for that pipeline. It is mounted under `/land-origination`, with the single exception of the logical-clock control endpoint described in §2.6. The API's central promise is that every derived number — a parcel's buildable acreage, its screening tier, an option's fee ledger, a lease's decommissioning security, an annual rent invoice — is computed by the server from pinned formulas rather than supplied by a client, and that every state change which invalidates one of those numbers recomputes it immediately and cascades the consequence to every dependent record in the same request.

The second promise is procedural. Origination is a segregated-duties business: the attorney who raises a title defect may not be the attorney who signs it off, and the deal principal who executes an option may not be the principal who exercises it. Those separations, the ordinance-driven acreage arithmetic, and the strict order in which the server decides *which* objection to report when several apply at once, are the substance of the sections that follow.

## 2. Global Specifications & System-Wide Principles

### 2.1. Operators, Identity and Role-Based Access Control

Every request to the API — reads included — must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the function that principal is performing. If either header is absent, or is present but empty, the request is rejected with `ERR_MISSING_USER_ID` and HTTP 401. This is the very first thing the server checks, before the target resource is even looked up.

Five roles exist, spelled exactly as follows:

- **`LandAgent`** — the origination agent. Registers landowners and parcels, re-screens them, requests and administers neighbor consents, drafts option terms and revises them after a counter, plans corridors, proposes crossings, and books field crews. A `LandAgent` may not execute an instrument, may not clear title, and may not move money.
- **`TitleCounsel`** — the title attorney. Publishes jurisdictional setback rules, raises title curative items, and clears or waives them, subject to the separation described in §2.10.
- **`PortfolioManager`** — the deal principal. Executes, extends, exercises and withdraws option instruments, permits corridors, grants crossings, and drives a lease through memorandum submission and county recording.
- **`PaymentAdministrator`** — payables and compliance. Owns the landowner payable flags, decommissioning-security postings, and the entire rent-invoice lifecycle. Cannot originate, negotiate or execute an instrument.
- **`Landowner`** — the counterparty, not an employee. May counter or accept option terms on their own instruments, and read their own records.

If `X-User-Role` is not one of those five spellings, or is a valid role that is not authorised for the endpoint being called, the request is rejected with `ERR_UNAUTHORIZED` and HTTP 403. §4 lists the authorised roles for every endpoint.

Four of the five roles carry **opaque** identity. When `X-User-Role` is `LandAgent`, `TitleCounsel`, `PortfolioManager` or `PaymentAdministrator`, the value of `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server may record it (for example as `created_by_user_id` and `cleared_by_user_id` on a title curative item, or as `executed_by_user_id` on an option agreement, where the transitions in §3.4 and §3.6 write it) but never compares it to any entity's `id`.

The `Landowner` role is different: it is **entity-backed**. When `X-User-Role` is `Landowner`, `X-User-ID` is the `id` of the acting `Landowner` row, and ownership checks on any resource that references a `Landowner` compare the resource's own landowner reference to `X-User-ID`. A `Landowner` countering or accepting an option agreement must be the agreement's own `landowner_id`; acting on another owner's instrument is refused with `ERR_UNAUTHORIZED` (403) at the same authorisation rung that rejects an unlisted role. The same scoping governs the reads a `Landowner` is permitted: their own landowner record, their own option agreements, the option-payment ledger rows of those agreements, their own leases, and the rent invoices raised against those leases.

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

### 2.3. Pagination, Ordering and Collection Filters

Every collection read is paginated by two query parameters. `limit` is the page size: it defaults to 10 when omitted, may be no smaller than 1 and no larger than 100. `offset` is the number of records to skip: it defaults to 0 and may be no smaller than 0. A `limit` outside the inclusive range from 1 to 100, a non-integer `limit` or `offset`, or a negative `offset`, is rejected with `ERR_INVALID_REQUEST` and HTTP 400.

Collections are ordered by `created_at` ascending — oldest record first — and never by `id`. That ordering is not merely cosmetic: several of the calculations in §3 iterate over child collections and the iteration order is likewise `created_at` ascending, so a client paging a list sees rows in the same order the server accumulates them. The option-payment ledger is the one collection with a secondary key: its rows are ordered by `created_at` ascending and then by `sequence_no` ascending.

For list responses the `meta` object additionally carries `limit`, `offset`, `total_count` (the number of records matching the filters before pagination) and `has_more` (true when records remain beyond the current page). Single-resource reads omit those four keys.

Each collection accepts its own optional filters, and all of them are exact-match:

- Landowners may be filtered by `status` and by `payment_hold`.
- Parcels may be filtered by `landowner_id`, `county_fips`, `screening_tier` and `status`.
- Setback rules may be filtered by `jurisdiction_code` and `rule_type`.
- Neighbor consents may be filtered by `parcel_id`, `setback_rule_id` and `status`.
- Title curative items may be filtered by `parcel_id`, by the predecessor they wait on via `blocks_item_id`, by `severity` and by `status`.
- Option agreements may be filtered by `parcel_id`, `landowner_id` and `status`.
- Option payments may be filtered by `option_agreement_id` and `payment_kind`. Because payment rows are minted exclusively by cascades and never posted directly by a client, this list is their only discovery channel.
- Corridors may be filtered by `status` and `voltage_class`.
- Crossing agreements may be filtered by `corridor_id`, `parcel_id`, `crossing_kind` and `status`.
- Site-access bookings may be filtered by `parcel_id` and `status`.
- Leases may be filtered by `option_agreement_id`, `parcel_id`, `landowner_id`, `rent_status` and `recording_status`.
- Rent invoices may be filtered by `lease_agreement_id`, `period_year`, `rent_variant` and `status`.

### 2.4. Resource Identity, Timestamps and Version Semantics

Every persisted resource carries a server-minted `id`: a UUID string with no type prefix and no embedded meaning. Clients never supply an `id`, and no calculation, selector, ordering rule or tie-break anywhere in this specification reads an `id` — wherever order matters, `created_at` ascending decides it.

Eleven of the twelve resource kinds also carry the full set of common properties. `created_at` is the ISO 8601 UTC instant at which the row was inserted, rendered with exactly three fractional digits; `updated_at` is the same format and is refreshed on every mutation of the row, including mutations the row's owner did not request but a cascade performed; and `version` is an integer that starts at 1 on creation and increases by exactly 1 on every mutation, again including cascade-driven mutations. Landowners, parcels, setback rules, neighbor consents, title curative items, option agreements, corridors, crossing agreements, site-access bookings, lease agreements and rent invoices all behave this way.

The `OptionPayment` ledger row is the exception. It is immutable once written — a reversal is a new row, never an edit — and it therefore carries only `id` and `created_at`. A payment row has **no** `updated_at` and **no** `version`; neither key appears in its representation.

Because `version` moves under cascade as well as under direct writes, it is the signal the concurrency rules in §2.7 are built on. A client that reads a parcel, then watches an unrelated neighbor consent be granted, will find the parcel's `version` two or three higher than it was — the acreage recompute, the qualification re-evaluation and the landowner posture sync each touch rows on the way through.

### 2.5. Units, Precision and Rounding Discipline

Three families of quantity flow through this system, each with a fixed presentation.

**Money is always whole integer cents.** Every field whose name ends in `_cents` is an integer; there are no fractional cents anywhere. Where a monetary formula produces a real number, it is rounded half up to the nearest whole cent, and the specification always states exactly how many times and at which step that rounding happens. This matters because several formulas round intermediate components and then compare or sum them; rounding at a different step yields a different answer, and the pinned order is normative.

**Acreage is always carried to two decimal places**, rounded half up. Deeded `gross_acres` is supplied to at most two decimals, and every derived acreage figure — `slope_excluded_acres`, `raw_setback_acres`, `consent_released_acres`, `setback_encumbered_acres`, `buildable_acres`, a consent's `released_acres`, a lease's `acre_basis_at_exercise`, an invoice's `acre_basis` — is likewise a two-decimal figure. As with money, the acreage derivation in §3.2 rounds per term before summing, and that order is normative.

**Scores are carried to two decimal places**, rounded half up, and so are the intermediate sub-scores that feed them.

Rates are expressed in basis points wherever the field name ends in `_bps`: a basis point is one ten-thousandth, so a value of 1500 means fifteen percent and a value of 300 means three percent. Every `_bps` input must lie between 0 and 10000 inclusive, and every `_cents` input must be zero or greater; a violation is `ERR_INVALID_REQUEST` (400).

### 2.6. The Logical Clock and the Four Time Sweeps

The server does not read wall-clock time for business decisions. It maintains a **logical clock**, and every instant it stamps — `requested_at`, `granted_at`, `revoked_at`, `cleared_at`, `executed_at`, `exercised_at`, `permitted_at`, `cancelled_at`, `term_start_date`, `memo_submitted_at`, `recorded_at`, `issued_at`, `paid_at` — is the current value of that clock. At server startup the logical clock reads exactly `2026-08-01T00:00:00Z`, and it must not fall back to real wall-clock time before it is first set.

`POST /_clock/set_current_utc` is the test-driving control endpoint that advances the clock. It accepts a single field, `current_utc`, and is available to all four operator roles (`LandAgent`, `TitleCounsel`, `PortfolioManager`, `PaymentAdministrator`) but not to a `Landowner`. Having set the clock, the endpoint immediately runs four time sweeps **in this pinned order**, each iterating its candidate set in `created_at` ascending order, and reports what each one did:

1. **Sweep S1, option expiry.** Every option agreement in status `EXECUTED` whose `option_expiry_at` is at or before the new clock value becomes `EXPIRED`. Its parcel returns from `OPTIONED` to `QUALIFIED`, and the owning landowner's posture is resynchronised, typically from `UNDER_OPTION` back to `ENGAGED`. Because `option_expiry_at` is null until an option is executed, no pre-execution status is ever swept. Ledger rows are never reversed by expiry: the landowner's paid balance is unchanged. The count of agreements expired is reported as `expired_option_count`.
2. **Sweep S2, consent expiry.** Every neighbor consent still in status `REQUESTED` whose `consent_expiry_at` is at or before the new clock value becomes `EXPIRED`. No acreage recompute fires, because a consent that was never granted had released no acres in the first place. The count is reported as `expired_consent_count`.
3. **Sweep S3, booking completion.** Every site-access booking in status `BOOKED` whose `window_end` is at or before the new clock value becomes `COMPLETED`. The count is reported as `completed_booking_count`.
4. **Sweep S4, lease delinquency.** Every lease whose rent dimension reads `PENDING_FIRST_RENT` or `CURRENT`, and which has at least one rent invoice in status `ISSUED` whose `due_at` is at or before the new clock value, moves its rent dimension to `DELINQUENT`. The count is reported as `delinquent_lease_count`.

The response also echoes the clock value under `current_utc`. All four counts are integers, and a sweep that finds no candidates reports zero rather than omitting its key.

### 2.7. Optimistic Concurrency on Parcel and Lease Parents

Two write endpoints create a child record whose entire economic content is read off a parent at the moment of creation. For those two, and only those two, the request must carry the client's last observed `version` of the parent, and the server refuses the write if the parent has moved on since.

**Drafting an option agreement.** `POST /land-origination/option-agreements` requires the non-optional field `expected_parcel_version`, carrying the client's last observed `version` of the parcel named by `parcel_id`. If that value does not equal the parcel's current stored `version`, the create is rejected with `ERR_STALE_PARCEL_VERSION` and HTTP 412. This guard exists because a parcel's acreage, screening tier and curative counters all move under cascade, and a parcel may legitimately carry a newer draft option that supersedes an older one — so option terms computed against a stale parcel snapshot are no longer the terms the business intends to book. A successful draft itself increments the parcel's `version`, so a client drafting two options against one parcel must re-read the parcel between them.

**Raising a rent invoice.** `POST /land-origination/leases/{leaseId}/rent-invoices` requires the non-optional field `expected_lease_agreement_version`, carrying the client's last observed `version` of the lease named in the path. If that value does not equal the lease's current stored `version`, the create is rejected with `ERR_STALE_LEASE_VERSION` and HTTP 412. This guard exists because the variant an invoice is computed under is read from the lease's `recording_status` at the instant of creation, and because a replacement invoice for a period whose prior invoice was voided legitimately supersedes it: a stale lease snapshot would silently bill the wrong variant. Posting security, submitting the memorandum and recording the memorandum all bump the lease's `version`, and so does a successful invoice creation.

No other endpoint in this API takes a version field. In particular, none of the action endpoints that drive state machines, and none of the other creates, accept `expected_parcel_version`, `expected_lease_agreement_version`, or any other expected-version input.

### 2.8. Derived-Field Cascades: Four Named Recompute Procedures

Derived state is never left stale. Four named procedures do all of the recomputation in this system, and every invocation of any of them refreshes `updated_at` and increments `version` by 1 on each row it actually touches.

**Acreage re-derivation** re-runs the buildable-acreage derivation of §3.2 for a parcel and writes `slope_excluded_acres`, `raw_setback_acres`, `consent_released_acres`, `setback_encumbered_acres` and `buildable_acres`. It also rewrites `released_acres` on every neighbor consent of that parcel: a consent that is currently `GRANTED` and whose rule is consent-waivable receives its own rounded release term, and every other consent of the parcel receives `0.00`.

**Screening re-computation** re-runs the weighted screening formula of §3.2 for a parcel under whichever variant the parcel's persisted `screen_mode` names, and writes `screening_score` and `screening_tier`.

**Qualification re-evaluation** is the promotion-and-demotion gate on a parcel's `status`, and it fires in exactly two directions. A parcel sitting in `SCREENING` is promoted `SCREENING → QUALIFIED` when its `buildable_acres` is at least 80.00 acres, its `screening_tier` is `PRIORITY` or `STANDARD`, and its `blocking_curative_open_count` is zero. A parcel sitting in `QUALIFIED` is demoted `QUALIFIED → SCREENING` when its `buildable_acres` has fallen below 80.00 acres, or its `screening_tier` has become `DEFERRED` or `REJECTED`, or its `blocking_curative_open_count` has risen above zero. The threshold is inclusive on the promotion side: a parcel with exactly 80.00 buildable acres qualifies. The procedure never fires at all when the parcel's `status` is `DISQUALIFIED`, `OPTIONED` or `LEASED` — those three statuses are moved only by the explicit transitions described in §3.

**Landowner posture synchronisation** recomputes a landowner's `status` from the rows they own, evaluating four clauses in this fixed order and stopping at the first match: `UNDER_LEASE` if the landowner owns at least one lease whose `recording_status` is `RECORDED`; otherwise `UNDER_OPTION` if the landowner owns at least one option agreement whose `status` is `EXECUTED` or `EXERCISED`; otherwise `ENGAGED` if the landowner owns at least one parcel whose `status` is `QUALIFIED`, `OPTIONED` or `LEASED`; otherwise `PROSPECT`. Because the clauses are ordered and the first match wins, a landowner with both a recorded lease and a live option reads `UNDER_LEASE`. This procedure never touches `total_paid_cents`.

A single client request may run all four in sequence, and the ordering between them is fixed: acreage first, then screening, then qualification, then landowner posture. §3 states, transition by transition, which of the four each operation triggers.

### 2.9. Reference Resolution and the Rejection Priority Ladder

Path identifiers are resolved strictly left to right. In a two-segment path the outer identifier is looked up first, so `POST /land-origination/leases/{leaseId}/rent-invoices` reports a missing lease before it considers anything about the body. The path identifiers this API uses are `{landownerId}`, `{parcelId}`, `{ruleId}`, `{consentId}`, `{itemId}`, `{optionId}`, `{paymentId}`, `{corridorId}`, `{crossingId}`, `{bookingId}`, `{leaseId}` and `{invoiceId}`. Foreign keys carried in a request body are resolved after every path identifier, in the order the endpoint declares its input fields.

When more than one objection to a request is true, the server reports **exactly one** — the objection with the lowest priority number in the ladder below. Evaluation stops at the first violated rung; no later rung is even evaluated. The ladder runs authentication, then authorisation, then existence, then request shape, then optimistic concurrency, then instrument expiry, then generic state admissibility, then title and security compliance, then deal-structure constraints, then temporal conflicts, and finally money. Title and security compliance deliberately outranks money, because a developer must never be told that a payment is on hold for a parcel whose title defects make the deal illegal in the first place.

| Rung | Rejection | HTTP | Scope |
|---|---|---|---|
| 1 | `ERR_MISSING_USER_ID` | 401 | every request |
| 2 | `ERR_UNAUTHORIZED` | 403 | every request |
| 3 | `ERR_LANDOWNER_NOT_FOUND` | 404 | landowner read, landowner patch, parcel create, option-agreement create |
| 4 | `ERR_PARCEL_NOT_FOUND` | 404 | parcel read, rescreen, neighbor-consent create, curative-item create, option-agreement create, crossing-agreement create, site-access-booking create |
| 5 | `ERR_SETBACK_RULE_NOT_FOUND` | 404 | neighbor-consent create |
| 6 | `ERR_NEIGHBOR_CONSENT_NOT_FOUND` | 404 | consent grant, consent revoke |
| 7 | `ERR_TITLE_CURATIVE_ITEM_NOT_FOUND` | 404 | curative-item create (for `blocks_item_id`), curative-item clear, curative-item waive |
| 8 | `ERR_OPTION_AGREEMENT_NOT_FOUND` | 404 | every option-agreement action endpoint |
| 9 | `ERR_CORRIDOR_NOT_FOUND` | 404 | corridor read, corridor permit, crossing-agreement create |
| 10 | `ERR_CROSSING_AGREEMENT_NOT_FOUND` | 404 | crossing read, crossing grant |
| 11 | `ERR_SITE_ACCESS_BOOKING_NOT_FOUND` | 404 | booking read, booking cancel |
| 12 | `ERR_LEASE_AGREEMENT_NOT_FOUND` | 404 | lease read, rent projection, post security, submit memo, record memo, rent-invoice create |
| 13 | `ERR_RENT_INVOICE_NOT_FOUND` | 404 | invoice read, issue, pay, void |
| 14 | `ERR_INVALID_REQUEST` | 400 | every write: body parses as JSON, every required field present and non-null, every field of the declared JSON type, every enum field a declared member |
| 15 | `ERR_INVALID_REQUEST` | 400 | every list read: `limit` an integer from 1 to 100, `offset` an integer of 0 or more |
| 16 | `ERR_INVALID_REQUEST` | 400 | every write carrying the named numeric fields: numeric domains hold |
| 17 | `ERR_INVALID_STATION_RANGE` | 422 | crossing-agreement create |
| 18 | `ERR_INVALID_WINDOW_RANGE` | 422 | crossing-agreement create, site-access-booking create |
| 19 | `ERR_STALE_PARCEL_VERSION` | 412 | option-agreement create |
| 20 | `ERR_STALE_LEASE_VERSION` | 412 | rent-invoice create |
| 21 | `ERR_CONSENT_EXPIRED` | 422 | consent grant |
| 22 | `ERR_OPTION_EXPIRED` | 422 | option accept, execute, extend, exercise |
| 23 | `ERR_INVALID_STATE` | 409 | every action endpoint |
| 24 | `ERR_ALREADY_RECORDED` | 409 | submit memo, record memo |
| 25 | `ERR_SEGREGATION_OF_DUTIES` | 422 | curative-item clear, curative-item waive, option exercise |
| 26 | `ERR_TITLE_CURATIVE_BLOCKING` | 422 | crossing-agreement create, option exercise, submit memo |
| 27 | `ERR_CURATIVE_BLOCKED_PREDECESSOR` | 422 | curative-item clear, curative-item waive |
| 28 | `ERR_SECURITY_NOT_POSTED` | 422 | submit memo |
| 29 | `ERR_W9_MISSING` | 422 | record memo |
| 30 | `ERR_PARCEL_APN_DUPLICATE` | 409 | parcel create |
| 31 | `ERR_PROHIBITED_ZONING` | 422 | parcel create |
| 32 | `ERR_PARCEL_NOT_QUALIFIED` | 422 | option send |
| 33 | `ERR_EXTENSION_LIMIT_REACHED` | 422 | option extend |
| 34 | `ERR_NEGOTIATION_ROUND_LIMIT` | 422 | option counter |
| 35 | `ERR_WAIVER_LIMIT_REACHED` | 422 | curative-item waive |
| 36 | `ERR_CORRIDOR_NOT_PERMITTED` | 422 | crossing grant |
| 37 | `ERR_DUPLICATE_INVOICE_PERIOD` | 409 | rent-invoice create |
| 38 | `ERR_CORRIDOR_STATION_CONFLICT` | 409 | crossing-agreement create |
| 39 | `ERR_CREW_CAPACITY_EXCEEDED` | 409 | site-access-booking create |
| 40 | `ERR_WINDOW_IN_PAST` | 422 | site-access-booking create |
| 41 | `ERR_LANDOWNER_PAYMENT_HOLD` | 422 | option execute, option extend, option exercise, invoice pay |
| 42 | `ERR_SECURITY_OVERPOSTED` | 422 | post security |
| 43 | `ERR_PAYMENT_AMOUNT_MISMATCH` | 422 | invoice pay |

Three consequences of that ordering are worth stating explicitly, because they are the cases where two objections most often coincide:

- On an option exercise, an option whose term has run out reports `ERR_OPTION_EXPIRED` **in preference to** `ERR_LANDOWNER_PAYMENT_HOLD`, even when the landowner is also under a payment hold. Instrument staleness outranks money.
- On a crossing-agreement proposal, a parcel with an open blocking title defect reports `ERR_TITLE_CURATIVE_BLOCKING` **in preference to** `ERR_CORRIDOR_STATION_CONFLICT`, even when the proposed station range and window also collide with an existing crossing. Title compliance outranks scheduling.
- On an option extension, an agreement that has already used every extension it bought reports `ERR_EXTENSION_LIMIT_REACHED` **in preference to** `ERR_LANDOWNER_PAYMENT_HOLD`. Deal structure outranks money.

Rung 16 deserves its own enumeration, since a single rejection code covers many domains. The numeric domains that must hold are: `gross_acres` strictly greater than 0; `slope_pct` between 0 and 100 inclusive; `resource_capacity_factor` strictly greater than 0 and at most 1; `interconnection_distance_km` of 0 or more; every field ending in `_bps` between 0 and 10000 inclusive; every field ending in `_cents` of 0 or more; `option_term_days` of 1 or more; `extension_count_allowed` of 0 or more; `crew_count` between 1 and 3 inclusive; `buffer_m` of 0 or more; `total_length_m` strictly greater than 0; `period_year` of 1 or more; `production_mwh` of 0 or more; and `consent_expiry_days` of 1 or more.

### 2.10. Segregation of Duties

Two separations are enforced on the acting `X-User-ID`, and both are checked at rung 25 with `ERR_SEGREGATION_OF_DUTIES` (422).

The first is a **four-eyes rule on title**. A title curative item records the identifier of the `TitleCounsel` who raised it in `created_by_user_id`. When that item is later cleared or waived, the acting `X-User-ID` must differ from `created_by_user_id`; the attorney who found the defect may not be the attorney who signs it off. The identifier that does resolve it is stored in `cleared_by_user_id`.

The second is a **four-eyes rule on the option instrument**. Executing an option records the acting identifier in `executed_by_user_id`. When that option is later exercised, the acting `X-User-ID` must differ from `executed_by_user_id` — the principal who bound the company to the option may not unilaterally convert it into a thirty-five-year lease.

Beyond those two identifier comparisons, duties are separated by role. Commercial terms are negotiated between a `LandAgent` and the `Landowner`, but only a `PortfolioManager` may execute, extend or exercise the instrument, permit a corridor, grant a crossing, or drive the memorandum through submission and recording. Only a `PaymentAdministrator` may touch the landowner's payable flags, post decommissioning security, or run any part of the rent-invoice lifecycle. Only a `TitleCounsel` may publish a setback rule or raise, clear or waive a curative item. Withdrawal from an option is the one action shared between a `LandAgent` and a `PortfolioManager`; site-access bookings and their cancellation are shared between a `LandAgent` and a `TitleCounsel`.

## 3. Business Logic & Workflows

### 3.1. Landowner Onboarding and Payable Administration

Origination begins with an owner of record. A `LandAgent` registers one by supplying the `legal_name` exactly as it appears on the deed (between 1 and 200 characters, and not blank or whitespace-only), the `entity_type` that determines the signature block the instruments will need — one of `INDIVIDUAL`, `TRUST`, `LLC` or `PARTNERSHIP` — the `mailing_state` to which payments and notices are sent, given as exactly two uppercase letters of the USPS state code, and a `contact_email` for option and lease correspondence, which must contain an at-sign. Two payable flags may optionally be supplied at registration and default to false when omitted: `w9_on_file`, true once a signed W-9 has been collected, and `payment_hold`, true when payment administration has frozen all cash movement for this owner. A newly registered landowner starts in `PROSPECT` with `total_paid_cents` of 0.

Only a `PaymentAdministrator` may amend a landowner afterwards, and only the payable attributes are mutable: `contact_email`, `w9_on_file` and `payment_hold`. The `legal_name` and `entity_type` are fixed at registration — they are what the recorded instruments will say — and are not accepted on an amendment. Every accepted amendment increments the landowner's `version`.

The landowner's `status` is never set by a client. It is a **relationship posture** recomputed by the landowner posture synchronisation of §2.8 whenever a parcel, an option or a lease belonging to that owner changes state, and it moves along five edges. `PROSPECT → ENGAGED` fires once one of the owner's parcels enters `QUALIFIED`. `ENGAGED → UNDER_OPTION` fires when one of the owner's option agreements reaches `EXECUTED`, and holds while any of them is `EXECUTED` or `EXERCISED`. `UNDER_OPTION → UNDER_LEASE` fires when one of the owner's leases reaches a `RECORDED` recording state. Two compensating edges run the other way: `UNDER_OPTION → ENGAGED` fires when the owner no longer holds any option in `EXECUTED` or `EXERCISED` and no lease in `RECORDED`, but still holds at least one parcel in `QUALIFIED`, `OPTIONED` or `LEASED` — which is what happens when an executed option expires or is withdrawn — and it leaves `total_paid_cents` untouched. `ENGAGED → PROSPECT` fires when the owner's last parcel in `QUALIFIED`, `OPTIONED` or `LEASED` reverts to `SCREENING`. Each of these five hops refreshes `updated_at` and increments `version` by 1.

`total_paid_cents` is the landowner's signed option-consideration balance and is likewise never written by a client. It is the sum, across every option agreement belonging to this landowner, of that agreement's `total_option_paid_cents`, and every agreement contributes regardless of its own status — a withdrawn or expired agreement keeps its unreversed rows in the total. Each agreement's `total_option_paid_cents` is in turn the sum of its ledger rows in the debit direction minus the sum of its ledger rows in the credit direction, accumulated over that agreement's payment rows in `created_at` ascending and then `sequence_no` ascending order. Every term is already an integer number of cents, so no rounding occurs at any step. Rent has nothing to do with this figure: paying a rent invoice never moves `total_paid_cents`, because rent is not option consideration.

A landowner is a hard prerequisite for a parcel and for an option agreement. When a parcel is registered or an option drafted and the referenced `landowner_id` names no existing landowner, the request is refused with `ERR_LANDOWNER_NOT_FOUND` (404), and the same code answers a read or an amendment aimed at an unknown owner.

### 3.2. Parcel Intake, Acreage Derivation and the Screening Score

A `LandAgent` registers a candidate parcel with its `apn` (the assessor parcel number, between 1 and 40 characters), the five-digit `county_fips` code of the county it lies in, the `landowner_id` of its owner of record, the deeded `gross_acres` (strictly greater than zero, at most two decimal places), the `interconnection_distance_km` from the parcel centroid to the nearest point of delivery (zero or more, at most two decimal places), the modelled `resource_capacity_factor` for the resource at that site (strictly greater than 0 and at most 1, at most four decimal places), the mean terrain `slope_pct` (between 0 and 100 inclusive, at most one decimal place), the desktop `title_condition_grade` — one of `A`, `B`, `C` or `D` — and the local `zoning_code` (between 1 and 12 characters). Two admissibility rules guard intake. The pair of `apn` and `county_fips` must be unique across the portfolio; a second parcel claiming the same pair is refused with `ERR_PARCEL_APN_DUPLICATE` (409). And a parcel whose `zoning_code` is one of the two prohibited designations, `RES1` or `CONS1`, can never be optioned and is refused outright with `ERR_PROHIBITED_ZONING` (422).

Registration is not a bare insert: the parcel is screened immediately. The server derives the acreage figures, then computes the screening score under the desktop variant, persisting `screen_mode` as `DESKTOP`, then re-evaluates qualification, then resynchronises the landowner's posture. A brand-new parcel can therefore land in `SCREENING`, be promoted straight to `QUALIFIED`, or — if its screening tier comes out `REJECTED` — be sent to the terminal `DISQUALIFIED` status without any further operator action.

**Acreage derivation** proceeds in four steps, and the rounding order is pinned at every one of them.

Step one removes the ground the terrain excludes. A slope tier is read off `slope_pct` against three breakpoints: a slope of 5.0 percent or less excludes nothing, so the rate is zero; a slope greater than 5.0 and at most 10.0 percent carries a rate of one tenth; a slope greater than 10.0 and at most 15.0 percent carries a rate of one quarter; and a slope greater than 15.0 percent carries a rate of one half. `slope_excluded_acres` is the deeded `gross_acres` multiplied by that rate, rounded half up to two decimals.

Step two accumulates the ordinance setbacks. The applicable rules are every setback rule whose `jurisdiction_code` equals this parcel's `county_fips` — setback rules have no lifecycle, so there is no status filter — taken in `created_at` ascending order. For each such rule, the parcel's `gross_acres` is multiplied by that rule's `encumbrance_rate_per_acre` and the product is rounded half up to two decimals **first**; `raw_setback_acres` is then the sum of those already-rounded per-rule contributions. Summing the rates and rounding once at the end is wrong and yields a different answer: fifteen deeded acres against rates of 0.0550 and 0.0750 give 1.96 acres under the pinned order and 1.95 under the sum-then-round order.

Step three gives back what the neighbours have released. The releasing consents are every neighbor consent on this parcel whose `status` is `GRANTED` and whose referenced setback rule has `consent_waivable` true, taken in `created_at` ascending order. Each such consent releases the parcel's `gross_acres` multiplied by that rule's `encumbrance_rate_per_acre` multiplied by four fifths — a granted consent buys back eighty percent of the rule's encumbrance, not all of it — with that product rounded half up to two decimals. `consent_released_acres` is the sum of those already-rounded per-consent terms, and each contributing consent's own `released_acres` is set to exactly its own rounded term. Consents in `REQUESTED`, `REVOKED` or `EXPIRED`, and consents whose rule is not consent-waivable, release nothing and carry `released_acres` of `0.00`.

Step four applies two nested floors. `setback_encumbered_acres` is `raw_setback_acres` less `consent_released_acres`, rounded half up to two decimals and floored at `0.00`. `buildable_acres` is `gross_acres` less `slope_excluded_acres` less `setback_encumbered_acres`, again rounded half up to two decimals and floored at `0.00`. Whenever `buildable_acres` comes out greater than zero, the three figures conserve the deed exactly: `gross_acres` equals `buildable_acres` plus `slope_excluded_acres` plus `setback_encumbered_acres`.

**The screening score** is a weighted blend of four sub-scores, each on a nought-to-one-hundred scale. The interconnection sub-score is one hundred less eight points per kilometre of `interconnection_distance_km`, clamped into the range from 0 to 100 — so a parcel 12.5 kilometres out scores exactly zero on interconnection, and one further out is held at zero rather than going negative. The resource sub-score is `resource_capacity_factor` multiplied by 250, rounded half up to two decimals, so a capacity factor of 0.4000 yields 100.00. The buildability sub-score is one hundred less four points per percentage point of `slope_pct`, clamped into the range from 0 to 100. The title sub-score is a lookup on an **effective grade**: grade `A` scores 100, grade `B` scores 80, grade `C` scores 55 and grade `D` scores 20.

Which effective grade applies is the one place where screening has two variants, and the parcel's persisted `screen_mode` selects between them. Under `DESKTOP` the effective grade is the `title_condition_grade` exactly as the desktop title report gave it, and open curative work is ignored entirely. Under `FIELD_VERIFIED` the grade is stepped down the ladder `A`, `B`, `C`, `D` by one position for each title curative item on the parcel of severity `BLOCKING` still sitting in status `BLOCKED` or `OPEN` — that is, by the parcel's `blocking_curative_open_count` — with the walk floored at `D` so that no count can push it past the bottom of the ladder. Items already `CLEARED` or `WAIVED`, and items of severity `MATERIAL` or `ADVISORY`, are excluded from that count. The two variants therefore return different scores, and can land in different tiers, for byte-identical parcel input.

`screening_score` is the weighted sum of the four sub-scores — three tenths of the interconnection sub-score, one quarter of the resource sub-score, one fifth of the buildability sub-score and one quarter of the title sub-score — rounded half up to two decimals **once**, at the end. `screening_tier` is then read off a threshold ladder top-down, every comparison inclusive: a score of 82.00 or more is `PRIORITY`, otherwise a score of 65.00 or more is `STANDARD`, otherwise a score of 45.00 or more is `DEFERRED`, and anything below 45.00 is `REJECTED`.

A `LandAgent` may re-screen a parcel at any time by naming the `screen_mode` to use, which is persisted so that every later cascade recompute uses the same variant. Re-screening re-derives the acreage, recomputes the score under the requested variant, re-evaluates qualification and resynchronises the landowner posture, and increments the parcel's `version`. Re-screening is also the only operator-driven route into the terminal `DISQUALIFIED` status: when the recomputed `screening_tier` comes out `REJECTED`, the parcel moves `SCREENING → DISQUALIFIED` and no landowner cascade fires, because a disqualified parcel does not count toward `ENGAGED`. That status is final — a disqualified parcel can never be optioned even if later curative work would have raised its tier — and it is one of two terminal parcel statuses, the other being `LEASED`.

Three counters on the parcel are maintained by the title workflow of §3.4 rather than by screening: `blocking_curative_open_count`, the number of `BLOCKING` items still in `BLOCKED` or `OPEN`; `waived_blocking_count`, the number of `BLOCKING` items that reached `WAIVED`; and `curative_cost_cents`, the sum of `curative_cost_cents` over the items on this parcel that reached `CLEARED`. All three default to 0. Reads of a single parcel return the whole derived picture — the acreage breakdown, the score, the tier and the three counters — and the parcel collection may be filtered down by owner, county, tier or status. A parcel referenced by a path or by a body `parcel_id` that names nothing is answered with `ERR_PARCEL_NOT_FOUND` (404).

### 3.3. Setback Ordinances and Neighbor Consent

Buildable area is bounded by local ordinance, and a `TitleCounsel` publishes what the ordinance says. A setback rule names the `jurisdiction_code` — the same five-digit county FIPS code a parcel carries in `county_fips` — the `rule_type` it imposes, which is one of `PROPERTY_LINE`, `OCCUPIED_DWELLING`, `PUBLIC_ROAD` or `WETLAND`, the ordinance distance in `setback_feet` (zero or more, carried for documentation only and not used in any arithmetic), the `encumbrance_rate_per_acre` giving the acres encumbered per deeded acre (between 0 and 1 inclusive, at most four decimal places), and the boolean `consent_waivable` saying whether a neighbour's written consent can release part of this rule's encumbrance. A jurisdiction carries at most one rule of each `rule_type`, so the pair of `jurisdiction_code` and `rule_type` identifies a rule uniquely. Setback rules have no lifecycle at all: once published, a rule simply exists.

Publishing a rule is nevertheless one of the most consequential writes in the system, because it retroactively re-derives every parcel it now applies to. Every existing parcel whose `county_fips` equals the new rule's `jurisdiction_code` is re-processed in `created_at` ascending order, and each one runs the full four-procedure chain of §2.8: acreage re-derivation, screening re-computation, qualification re-evaluation and landowner posture synchronisation. A newly published ordinance can therefore push an already-`QUALIFIED` parcel below the eighty-acre floor and revert it `QUALIFIED → SCREENING`, which in turn can revert its owner `ENGAGED → PROSPECT`. Rules are readable individually and as a collection filtered by jurisdiction or type; a body `setback_rule_id` naming no rule is answered with `ERR_SETBACK_RULE_NOT_FOUND` (404).

Some of that encumbrance can be bought back. A `LandAgent` records a request for a neighbour's written consent by naming the `parcel_id` whose buildable area it would enlarge, the `setback_rule_id` the neighbour would be waiving, the `neighbor_name` of the adjoining owner or dwelling occupant (between 1 and 200 characters, not blank), and optionally `consent_expiry_days`, the number of days an ungranted request stays alive. That window defaults to 60 days when omitted and must be at least 1 and at most 365 — a year is the outside limit. The request is stamped with `requested_at` from the logical clock, its `consent_expiry_at` is set to `requested_at` advanced by `consent_expiry_days` days, its `released_acres` starts at `0.00`, and it opens in `REQUESTED`.

When the neighbour signs, the agent records the grant and the consent moves `REQUESTED → GRANTED` with `granted_at` stamped from the clock. Three conditions gate it. The consent must actually be in `REQUESTED`; anything else is `ERR_INVALID_STATE` (409). The logical clock must be **strictly before** `consent_expiry_at` — equality lapses, so at exactly the expiry instant the request is treated as expired rather than grantable, and the rejection is `ERR_CONSENT_EXPIRED` (422). And the parcel must not be in `DISQUALIFIED` or `LEASED`; consent on dead or already-conveyed ground is refused with `ERR_INVALID_STATE`.

The grant then cascades in three hops, and the whole cascade completes inside the same request. Hop one re-derives the parcel's acreage: `consent_released_acres` rises by this consent's own rounded release term, which is also written onto the consent's `released_acres`, `setback_encumbered_acres` falls by the same amount, and `buildable_acres` rises. Hop two, precisely because `buildable_acres` changed, re-evaluates the parcel's qualification, which may promote it `SCREENING → QUALIFIED`. Hop three, if that promotion happened, resynchronises the owner's posture, which may advance them `PROSPECT → ENGAGED`. Both the consent and the parcel have their `version` incremented and their `updated_at` refreshed.

Revocation is the exact compensating action. When a neighbour withdraws, the consent moves `GRANTED → REVOKED`, `revoked_at` is stamped from the clock, and `released_acres` is reset to `0.00`. The parcel must not be `LEASED` — a revocation against a conveyed parcel is `ERR_INVALID_STATE` — and the consent must be in `GRANTED`, else the same code answers. Hop one re-derives the acreage and restores `setback_encumbered_acres` and `buildable_acres` to exactly the values they held before the grant; this **acreage conservation invariant** is the point of routing revocation through the same derivation rather than through a stored delta. Hop two re-evaluates qualification and may revert the parcel `QUALIFIED → SCREENING`. Hop three resynchronises the owner and may revert them `ENGAGED → PROSPECT`.

A request that is never signed dies on its own. The consent-expiry sweep described in §2.6 moves every consent still in `REQUESTED` whose `consent_expiry_at` has been reached or passed into `EXPIRED`, and deliberately runs **no** acreage recompute, because an ungranted consent had never released any acres to give back. `REVOKED` and `EXPIRED` are both terminal: a consent in either state can never be granted again, and a replacement requires a fresh request. Consents are readable individually — the read exposes the `released_acres` contribution — and as a collection filtered by parcel, rule or status. A path identifier naming no consent is answered with `ERR_NEIGHBOR_CONSENT_NOT_FOUND` (404).

### 3.4. Title Curative Work and the Blocking Chain

Title defects are the gating risk in land origination, and a `TitleCounsel` raises each one as a curative item against a `parcel_id`. The item declares its `item_type` — one of `MINERAL_SEVERANCE`, `MORTGAGE_SUBORDINATION`, `ACCESS_EASEMENT_GAP`, `TAX_LIEN` or `HEIRSHIP_GAP` — its `severity`, which is one of `BLOCKING`, `MATERIAL` or `ADVISORY`, and its budgeted `curative_cost_cents` (zero or more). It may optionally name a `blocks_item_id`: the predecessor item on which it depends, which must reach `CLEARED` or `WAIVED` before this item may be worked. When `blocks_item_id` is omitted it is null and the item has no predecessor. A `blocks_item_id` naming no existing item is refused with `ERR_TITLE_CURATIVE_ITEM_NOT_FOUND` (404).

Only `BLOCKING` severity has teeth. A `BLOCKING` item that is still unresolved gates option exercise, crossing-agreement creation and memorandum submission; `MATERIAL` and `ADVISORY` items are recorded for the file and never gate anything. The item's `created_by_user_id` is stamped from the acting `X-User-ID`, and its status opens as `BLOCKED` when the predecessor named by `blocks_item_id` is still in `BLOCKED` or `OPEN`, and as `OPEN` otherwise. Raising an item recounts the parcel's `blocking_curative_open_count`, then re-computes screening, re-evaluates qualification and resynchronises the owner. Note what raising an item does **not** do: the parcel's `curative_cost_cents` is not touched at creation, because cost is capitalised only when the work is actually done. Note also that the screening recompute moves the score only when the parcel's `screen_mode` is `FIELD_VERIFIED`; under `DESKTOP` the score is blind to curative work, so raising a blocking defect changes the tier for one variant and not the other — though under either variant a newly raised `BLOCKING` item can revert the parcel `QUALIFIED → SCREENING` through the counter alone.

The two ways out of `OPEN` are siblings with deliberately different consequences, and both demand a different `X-User-ID` from the item's `created_by_user_id` per §2.10, failing with `ERR_SEGREGATION_OF_DUTIES` (422).

**Clearing** an item means the curative work was completed and title is cured. The item must be in `OPEN`; an item still in `BLOCKED` is refused with `ERR_CURATIVE_BLOCKED_PREDECESSOR` (422), and the parcel must not be `DISQUALIFIED`, which is `ERR_INVALID_STATE` (409). On success, hop one moves the item `OPEN → CLEARED`, stamps `cleared_at` from the logical clock and `cleared_by_user_id` from the acting identifier, and **adds this item's `curative_cost_cents` to the parcel's `curative_cost_cents`**. Hop two promotes successors: every item whose `blocks_item_id` is this item and whose status is `BLOCKED` moves `BLOCKED → OPEN`, processed in `created_at` ascending order. Hop three recounts the parcel's `blocking_curative_open_count`, because those successor statuses just changed. Hop four, because that count changed, re-computes screening under the parcel's persisted `screen_mode` and then re-evaluates qualification, which may itself resynchronise the landowner posture.

**Waiving** an item means counsel accepts the defect on the record instead of curing it, and the request carries the `waiver_note` justifying that decision. The item must be in `OPEN`, with a `BLOCKED` item again refused by `ERR_CURATIVE_BLOCKED_PREDECESSOR`. One further constraint applies only to waivers of `BLOCKING` items: at most one blocking defect per parcel may be waived rather than cured, so the waiver is admitted only while the parcel's `waived_blocking_count` is still below 1, and the second attempt is refused with `ERR_WAIVER_LIMIT_REACHED` (422). On success the item moves `OPEN → WAIVED`, `waiver_note` is recorded, `cleared_at` is stamped from the clock and `cleared_by_user_id` from the acting identifier, and the parcel's `waived_blocking_count` is incremented by 1 when the severity is `BLOCKING`. Successors are then promoted `BLOCKED → OPEN` in `created_at` ascending order **exactly as in the clearing branch**, the parcel's `blocking_curative_open_count` and `waived_blocking_count` are recounted, screening is re-computed under the persisted variant, and qualification is re-evaluated with its possible landowner cascade. The one place the waiver branch diverges from the clearing branch is cost: **the parcel's `curative_cost_cents` is not increased by a waiver.** No counsel time was spent curing anything, so nothing is capitalised.

`CLEARED` and `WAIVED` are both terminal. `BLOCKED → OPEN` is the only other edge in the item lifecycle and it is never operator-driven — it is the system promotion that fires when the predecessor named by `blocks_item_id` reaches `CLEARED` or `WAIVED`, with sibling successors promoted in `created_at` ascending order. Items are readable individually and as a collection filterable by parcel, by the predecessor they wait on, by severity and by status; a path identifier naming no item is answered with `ERR_TITLE_CURATIVE_ITEM_NOT_FOUND` (404).

### 3.5. Option Terms and the Negotiation Loop

Once a parcel qualifies, a `LandAgent` drafts an option agreement over it. The draft names the `parcel_id` under option and the `landowner_id` of the counterparty, which must be the parcel's own owner of record — a mismatch is refused as an invalid request with `ERR_INVALID_REQUEST` (400) — and carries `expected_parcel_version` for the concurrency guard of §2.7. The commercial terms follow. `option_term_days` is the number of days from execution during which the option may be exercised, at least 1 and at most 1825 (five years). `option_fee_per_acre_cents` is the initial option fee rate. `extension_count_allowed` is the number of extensions the developer may buy, at least 0 and at most 3, and `extension_fee_per_acre_cents` is the rate charged for the first of them. `rent_structure_type` is either `PER_ACRE`, which pays only the escalated per-acre component, or `ROYALTY_HYBRID`, which pays the greater of the per-acre component and the production royalty. `base_rent_per_acre_cents` is the year-one rent rate before escalation. `royalty_rate_bps` is the production royalty in basis points, at least 0 and at most 2000 — twenty percent is the ceiling — and it must be exactly 0 when the structure is `PER_ACRE`, a `ROYALTY_HYBRID` structure being the only one that can carry a royalty; a non-zero royalty under `PER_ACRE` is `ERR_INVALID_REQUEST`. `escalator_pct_bps` is the annual rent escalator in basis points, at least 0 and at most 1000, so ten percent a year is the ceiling. `escalator_mode` is `SIMPLE`, which multiplies the escalator by the number of elapsed years, or `COMPOUND`, which raises one plus the escalator to the power of the elapsed years.

A fresh draft opens in `DRAFT` with `round_index` 0, `extensions_used` 0 and `total_option_paid_cents` 0, and it bumps the parcel's `version` as the concurrency parent. An option agreement referenced by a path identifier that names nothing is answered with `ERR_OPTION_AGREEMENT_NOT_FOUND` (404), and so is a body `option_agreement_id` that names nothing.

Negotiation is a genuine cycle. Sending the terms moves the agreement `DRAFT → SENT`, and the same action also closes the loop by moving a revised agreement `REVISED → SENT`. Sending is admitted only from `DRAFT` or `REVISED` — any other status is `ERR_INVALID_STATE` (409) — and additionally requires the underlying parcel to be in `QUALIFIED` **at that instant**, meaning its `buildable_acres` is at least eighty acres, its `screening_tier` is `PRIORITY` or `STANDARD`, and it carries no open blocking curative item. A parcel that has drifted out of qualification since the draft was written blocks the send with `ERR_PARCEL_NOT_QUALIFIED` (422).

From `SENT`, the counterparty has two moves, and only the counterparty: the acting `X-User-Role` must be `Landowner` and the acting `X-User-ID` must be the agreement's own `landowner_id`. **Countering** moves the agreement `SENT → COUNTERED` and increments `round_index` by 1. Each of the seven counterable terms may be supplied to overwrite the agreement's current value immediately — `option_fee_per_acre_cents`, `extension_fee_per_acre_cents`, `base_rent_per_acre_cents`, `royalty_rate_bps`, `escalator_pct_bps`, `escalator_mode` and `option_term_days` — and every omitted term keeps whatever value it currently holds. The negotiation is capped at three completed counters: a counter is accepted only while `round_index` is still below 3, so the fourth counter is refused with `ERR_NEGOTIATION_ROUND_LIMIT` (422). **Accepting** instead moves the agreement `SENT → ACCEPTED` and changes no terms.

From `COUNTERED`, the agent answers with a revision, moving the agreement `COUNTERED → REVISED` and returning it to the loop. A revision may overwrite the same seven terms the counter could, **plus one more the counter could not**: `rent_structure_type`. The developer may restructure a per-acre deal into a royalty hybrid, or the reverse, in response to a counter; the landowner may only move the numbers within the structure the developer proposed. As with a counter, omitted terms keep their current value. The full negotiation cycle is therefore `SENT → COUNTERED → REVISED → SENT`, traversable up to three times.

Withdrawal is available from every pre-exercise status. A `LandAgent` or a `PortfolioManager` may withdraw an agreement in `DRAFT`, `SENT`, `COUNTERED`, `REVISED`, `ACCEPTED` or `EXECUTED`, supplying the free-text `withdraw_reason` that is recorded on the instrument. From the five pre-execution statuses the withdrawal does nothing but set the status to `WITHDRAWN` and store the reason; withdrawal from `EXECUTED` carries the far heavier consequences described in §3.6. `EXERCISED`, `EXPIRED` and `WITHDRAWN` are the three terminal statuses of the option lifecycle.

Agreements are readable individually — the read exposes the negotiated terms alongside `total_option_paid_cents` — and as a collection filterable by parcel, owner or status. An accept, execute, extend or exercise aimed at an agreement whose `option_expiry_at` has been reached or passed is refused with `ERR_OPTION_EXPIRED` (422); because `option_expiry_at` is null until the option is executed, that check can only bite after execution.

### 3.6. Execution, Extension Rights and the Option-Payment Ledger

Execution is where the deal becomes binding and where money first moves, and only a `PortfolioManager` may do it. The agreement must be in `ACCEPTED`, the parcel must still be in `QUALIFIED`, and the landowner's `payment_hold` must be false; a held owner blocks execution with `ERR_LANDOWNER_PAYMENT_HOLD` (422). On success the agreement moves `ACCEPTED → EXECUTED`, `executed_at` is stamped from the logical clock, `executed_by_user_id` is stamped from the acting `X-User-ID`, and `option_expiry_at` is set to `executed_at` advanced by `option_term_days` days.

Execution also mints the first row of the **option-payment ledger**. That ledger is append-only and immutable: rows are never edited or deleted, a reversal is always a new row, and a row carries no `updated_at` and no `version` (see §2.4). Each row records the `option_agreement_id` it belongs to, a `sequence_no` giving its 1-based insertion index within that agreement assigned in `created_at` ascending order, the `payment_kind` that minted it, the `ledger_direction` that carries its sign, a non-negative `amount_cents`, and the `acres_basis` the amount was computed on. Direction `DEBIT_DEVELOPER` increases the landowner's `total_paid_cents`; `CREDIT_DEVELOPER` decreases it. The row minted by execution has `payment_kind` `INITIAL_OPTION_FEE`, `ledger_direction` `DEBIT_DEVELOPER`, `sequence_no` 1, and `acres_basis` set to a snapshot of the parcel's `gross_acres`. Its `amount_cents` is `option_fee_per_acre_cents` multiplied by the parcel's `gross_acres`, rounded half up to a whole number of cents. **Option fees are always priced on deeded acreage, never on buildable acreage** — that is the commercial convention, and it does not change when consents or setbacks move the buildable figure. The agreement's `total_option_paid_cents` and the owner's `total_paid_cents` are then recomputed per §3.1, the parcel moves `QUALIFIED → OPTIONED`, and the owner's posture advances `ENGAGED → UNDER_OPTION`.

Extension rights are exercised against an already-executed agreement, and the transition is a **self-loop on `EXECUTED`**: the status does not change, but the instrument does. The agreement must be in `EXECUTED`, `extensions_used` must still be below `extension_count_allowed` — otherwise `ERR_EXTENSION_LIMIT_REACHED` (422) — and the owner's `payment_hold` must be false. On success `extensions_used` is incremented by 1 and `option_expiry_at` is pushed out by a further 180 days. A new ledger row is minted with `payment_kind` `EXTENSION_FEE`, `ledger_direction` `DEBIT_DEVELOPER`, a `sequence_no` one greater than the highest already on the agreement, and `acres_basis` again the parcel's `gross_acres`. Each extension is dearer than the last: taking the extension index to be the value of `extensions_used` **after** the increment, so that the first extension has index 1, the amount is `extension_fee_per_acre_cents` multiplied by the parcel's `gross_acres`, multiplied by one-point-one-five raised to the power of one less than the index — a fifteen-percent step-up compounding per extension — with the result rounded half up to a whole number of cents once. The first extension therefore charges the plain rate, the second charges fifteen percent more, and the third charges fifteen percent more again. The agreement's `total_option_paid_cents` and the owner's `total_paid_cents` are recomputed after each one.

Withdrawal from `EXECUTED` is the compensating action for execution plus every extension taken since, and it is the only withdrawal that touches money. Alongside `withdraw_reason` the request may carry the boolean `refund_extension_fees`. When that flag is true and `extensions_used` is greater than zero, exactly one reversal row is minted: `payment_kind` `REFUND_REVERSAL`, `ledger_direction` `CREDIT_DEVELOPER`, `acres_basis` of `0.00` because no acreage underlies a reversal, and `amount_cents` equal to the sum of the `amount_cents` of this agreement's `EXTENSION_FEE` rows, accumulated in `created_at` ascending order. Only rows of the same `option_agreement_id` enter that sum, and the agreement's `INITIAL_OPTION_FEE` row and any earlier `REFUND_REVERSAL` row are excluded from it. The consequence is the **option-payment conservation invariant**: after a withdrawal from `EXECUTED` with the refund flag set, the owner's `total_paid_cents` equals exactly the value it held immediately after that agreement's execution, for any number of intervening extensions. The withdrawal also releases the land — the parcel moves `OPTIONED → QUALIFIED` without any acreage or screening field being touched — and the owner's posture reverts `UNDER_OPTION → ENGAGED`.

An option that is simply left to run out is handled by the option-expiry sweep of §2.6 rather than by any operator action. In `created_at` ascending order, every agreement in `EXECUTED` whose `option_expiry_at` has been reached or passed cascades in three hops: the agreement moves `EXECUTED → EXPIRED`, the parcel moves `OPTIONED → QUALIFIED`, and the owner's posture reverts `UNDER_OPTION → ENGAGED`. Expiry is deliberately **not** a refund event: no reversal row is minted, and the owner's `total_paid_cents` is unchanged. The developer paid for time and the time elapsed.

Ledger rows are readable individually and as a collection filtered by agreement or by `payment_kind`, ordered by `created_at` ascending then `sequence_no` ascending. Because rows are minted only by cascades and never posted directly, that collection is the only way to discover them. Reads of the ledger are restricted to a `PortfolioManager`, a `PaymentAdministrator`, or the `Landowner` whose consideration it records.

### 3.7. Exercise, Decommissioning Security and the Memorandum of Lease

Exercising the option converts it into a lease, and it is the most heavily gated action in the system. Only a `PortfolioManager` may do it, and seven conditions must hold. The agreement must be in `EXECUTED`. The logical clock must be strictly before `option_expiry_at`, or the attempt is refused with `ERR_OPTION_EXPIRED` (422). The acting `X-User-ID` must differ from `executed_by_user_id`, or the attempt is refused with `ERR_SEGREGATION_OF_DUTIES` (422). The parcel must be in `OPTIONED`. The parcel's `blocking_curative_open_count` must be zero, or the attempt is refused with `ERR_TITLE_CURATIVE_BLOCKING` (422) — the company does not take a thirty-five-year interest in defective title. The parcel's `buildable_acres` must still be at least eighty acres; because qualification is never re-evaluated while a parcel sits in `OPTIONED`, a consent revoked mid-option can quietly push the figure below the floor, and an exercise in that condition is refused with `ERR_INVALID_STATE` (409). And the owner's `payment_hold` must be false, which is the last thing checked, so an expired option under a payment hold reports its expiry rather than the hold.

The request carries one field, `exercise_notice_reference`, the developer's exercise-notice document reference (between 1 and 60 characters, not blank). On success the agreement moves `EXECUTED → EXERCISED` with `exercised_at` stamped from the logical clock, and a lease agreement is created and returned. The new lease copies `option_agreement_id`, `parcel_id` and `landowner_id` from the exercised option, stores the supplied `exercise_notice_reference`, sets `term_start_date` to the instant of exercise and `term_years` to a fixed thirty-five-year term, and takes `acre_basis_at_exercise` as a snapshot of the parcel's `buildable_acres` at that instant. It opens with `security_posted_cents` of 0, `last_paid_invoice_year` of 0, and both of its state dimensions at their initial values: `rent_status` of `PENDING_FIRST_RENT` and `recording_status` of `UNRECORDED`. Crucially, **the parcel does not become `LEASED` at exercise** — it stays in `OPTIONED` until the memorandum is actually recorded with the county.

The snapshot drives the reclamation obligation. **Decommissioning security** is sized once, at exercise, in four pinned steps, and the definition only looks circular: the administrative loading is a rate applied to the security amount, and the total is the amount plus that loading, but the tier is keyed on the gross amount and **never** on the total. Step one sets `gross_security_cents` to five hundred dollars per acre — fifty thousand cents — multiplied by `acre_basis_at_exercise`, rounded half up to whole cents. Step two reads `admin_rate_bps` off a three-band ladder against that gross figure: a gross below fifty thousand dollars carries 600 basis points, a gross of fifty thousand dollars or more but below one hundred and fifty thousand dollars carries 450 basis points, and a gross of one hundred and fifty thousand dollars or more carries 300 basis points. Step three sets `admin_loading_cents` to `gross_security_cents` multiplied by `admin_rate_bps` divided by ten thousand, rounded half up to whole cents. Step four sets `total_security_required_cents` to `gross_security_cents` plus `admin_loading_cents`. Because the rate falls as the gross rises, the total is **not** monotonic in acreage across a band boundary: 99.99 buildable acres require 5,299,470 cents of security while 100.00 buildable acres require only 5,225,000 cents. Later changes to the parcel's acreage never restate an existing lease's requirement — the snapshot is the snapshot.

A `PaymentAdministrator` posts that security against the lease, supplying `amount_cents`, and may post it in instalments: each posting adds the supplied amount to `security_posted_cents` and increments the lease's `version`. Over-posting is refused: if `security_posted_cents` plus the supplied `amount_cents` would exceed `total_security_required_cents`, the posting fails with `ERR_SECURITY_OVERPOSTED` (422). Because over-posting is impossible, "fully posted" and "exactly posted" coincide.

The recording dimension of the lease then advances through two hops, both driven by a `PortfolioManager`. **Submitting the memorandum** — the notice of lease the county will index — moves `recording_status` `UNRECORDED → MEMO_SUBMITTED` and stamps `memo_submitted_at` from the logical clock. Three conditions gate it: `security_posted_cents` must have reached `total_security_required_cents`, or the submission is refused with `ERR_SECURITY_NOT_POSTED` (422); the parcel's `blocking_curative_open_count` must be zero, or it is refused with `ERR_TITLE_CURATIVE_BLOCKING` (422); and a lease whose `recording_status` is already `RECORDED` is refused with `ERR_ALREADY_RECORDED` (409), the same code that answers a second recording attempt.

**Recording the memorandum** moves `recording_status` `MEMO_SUBMITTED → RECORDED` and carries the county's `recording_instrument_no`, which the server stores alongside `recorded_at` from the logical clock. It has one cross-entity gate: the landowner's `w9_on_file` must be true, because no instrument may be recorded for a payee the developer cannot report to the tax authorities, and a missing W-9 is refused with `ERR_W9_MISSING` (422). Recording then cascades in three hops: the recording dimension reaches the terminal `RECORDED`, the parcel finally moves `OPTIONED → LEASED` — its own terminal status — and the owner's posture advances `UNDER_OPTION → UNDER_LEASE`. Recording also flips the invoice-variant selector described in §3.9: every rent invoice raised after this point is computed as a final as-built figure rather than a provisional one.

The two lease dimensions are genuinely independent. A lease can reach `CURRENT` on its rent dimension while still `UNRECORDED`, and it can be `RECORDED` while still `PENDING_FIRST_RENT`. Leases are readable individually and as a collection filterable by originating option, parcel, owner, rent status or recording status; a path identifier naming no lease is answered with `ERR_LEASE_AGREEMENT_NOT_FOUND` (404).

### 3.8. Corridors, Crossing Agreements and Site-Access Scheduling

Assembled land is worthless without a path for the electrons and for the crews. A `LandAgent` plans a corridor by naming its `route_name` (between 1 and 120 characters, not blank), its centreline `total_length_m` in whole metres (at least 1), its `voltage_class` — one of `COLLECTION_34_5KV`, `GENTIE_138KV` or `GENTIE_345KV` — and optionally its `buffer_m`, the exclusion buffer in metres applied on both sides of every occupied station interval when conflicts are tested. `buffer_m` defaults to 50 metres when omitted and must be between 0 and 500 inclusive. A corridor opens in `PLANNED` with `granted_crossing_count` of 0 and a null `permitted_at`. The route-permit action, available only to a `PortfolioManager`, moves it `PLANNED → PERMITTED` and stamps `permitted_at` from the logical clock; `PERMITTED` is terminal. A corridor referenced by a path or by a body `corridor_id` that names nothing is answered with `ERR_CORRIDOR_NOT_FOUND` (404).

A crossing agreement joins a corridor to a parcel. A `LandAgent` proposes one with the `corridor_id`, the `parcel_id` crossed by the route, the `crossing_kind` — one of `COLLECTION_LINE`, `INTERCONNECTION_ROUTE` or `ACCESS_ROAD`, which selects the per-metre compensation rate — the inclusive `station_start_m` and `station_end_m` bounding the stationing it occupies, and the half-open occupancy window given by `occupancy_window_start` (inclusive) and `occupancy_window_end` (exclusive). Two shape rules apply before anything else: `station_end_m` must be strictly greater than `station_start_m`, `station_start_m` must be zero or greater, and `station_end_m` must not exceed the corridor's `total_length_m`, with any violation refused as `ERR_INVALID_STATION_RANGE` (422); and `occupancy_window_end` must be strictly after `occupancy_window_start`, an empty or inverted window being refused as `ERR_INVALID_WINDOW_RANGE` (422).

Two admissibility gates then apply, and their relative order matters. First, the parcel's `blocking_curative_open_count` must be zero, or the proposal is refused with `ERR_TITLE_CURATIVE_BLOCKING` (422). Only after that does the server test the corridor for collisions. A conflict exists against any other crossing on the **same** corridor in status `PROPOSED` or `GRANTED` when **both** a buffer-expanded station overlap and a half-open time overlap hold: the new crossing's `station_start_m` is less than the existing crossing's `station_end_m` plus the corridor's `buffer_m`, **and** the new crossing's `station_end_m` plus that same buffer is greater than the existing crossing's `station_start_m`, **and** the new `occupancy_window_start` is before the existing `occupancy_window_end`, **and** the new `occupancy_window_end` is after the existing `occupancy_window_start`. Touching at exactly the buffer edge does not conflict, and windows that merely abut — one ending at the instant the other begins — do not conflict either. A genuine conflict is refused with `ERR_CORRIDOR_STATION_CONFLICT` (409). Because the title gate sits above the conflict gate, a proposal that is both title-blocked and station-conflicted reports the title problem.

Pricing is entirely local to the crossing being proposed: no other crossing on the corridor affects the amount, and corridor occupancy governs only admissibility, never price. `occupied_m` is `station_end_m` less `station_start_m`. `duration_days` is the length of the occupancy window in days, rounded **up** to a whole day, so any part-day of occupancy counts as a full day. A base amount is `occupied_m` multiplied by the per-metre rate for the `crossing_kind`: eighteen dollars per metre for a `COLLECTION_LINE`, thirty-four dollars per metre for an `INTERCONNECTION_ROUTE`, and nine dollars per metre for an `ACCESS_ROAD`. `long_occupancy_surcharge_bps` is zero for the first thirty days: when `duration_days` is 30 or less the surcharge is 0 basis points, and otherwise it is fifty basis points for each day beyond the thirtieth, capped at 2500 basis points — a twenty-five-percent ceiling, reached at eighty days of occupancy and never exceeded however long the window runs. `compensation_cents` is the base amount plus the base amount multiplied by `long_occupancy_surcharge_bps` divided by ten thousand, with that surcharge term rounded half up to whole cents once. A proposed crossing opens in `PROPOSED`.

Granting a crossing is a `PortfolioManager` action. The crossing must be in `PROPOSED`, and the corridor must have reached `PERMITTED` — a crossing on a still-`PLANNED` corridor is refused with `ERR_CORRIDOR_NOT_PERMITTED` (422). On success the crossing moves `PROPOSED → GRANTED`, `granted_at` is stamped from the logical clock, and the corridor's `granted_crossing_count` is recomputed. `GRANTED` is terminal. A path identifier naming no crossing is answered with `ERR_CROSSING_AGREEMENT_NOT_FOUND` (404).

Field work on a parcel is scheduled through site-access bookings, which a `LandAgent` or a `TitleCounsel` may create. A booking names the `parcel_id`, the `purpose` of the visit — one of `TITLE_SURVEY`, `GEOTECH`, `ENV_SURVEY` or `CONSTRUCTION_STAGING` — the half-open window given by `window_start` (inclusive) and `window_end` (exclusive), and the `crew_count` of simultaneous crews it occupies, which must be between 1 and 3 inclusive. An empty or inverted window is refused with `ERR_INVALID_WINDOW_RANGE` (422), and a `window_start` strictly before the current logical clock is refused with `ERR_WINDOW_IN_PAST` (422) — crews cannot be booked into the past, though a booking starting at exactly the current instant is admissible.

Crew capacity is an **aggregate** constraint, not a per-booking one. A parcel supports at most three simultaneous crews. Over every booking on the same parcel in status `BOOKED` or `COMPLETED` whose half-open window intersects the requested window, the sum of their `crew_count` plus the requested `crew_count` must not exceed 3; otherwise the booking is refused with `ERR_CREW_CAPACITY_EXCEEDED` (409). Each individual booking may be perfectly admissible while the collective sum is not — three separate single-crew bookings fit, a fourth does not — and back-to-back windows, where one ends at the instant the next begins, never intersect and therefore never compete. Cancelled bookings are excluded from the sum: cancelling a booking moves it `BOOKED → CANCELLED`, stamps `cancelled_at` from the logical clock, and its `crew_count` immediately stops counting against capacity for every overlapping window, which is the **crew-capacity conservation invariant**. Bookings also age out on their own: the booking-completion sweep of §2.6 moves every booking still in `BOOKED` whose `window_end` has been reached or passed to `COMPLETED`, and a completed booking likewise stops occupying crews going forward even though it continues to count in the intersection test for windows it overlaps. `CANCELLED` and `COMPLETED` are both terminal. A path identifier naming no booking is answered with `ERR_SITE_ACCESS_BOOKING_NOT_FOUND` (404).

### 3.9. Rent Invoicing, the Two Rent Variants, and Delinquency

Rent is administered one lease year at a time, and every invoice belongs to a `PaymentAdministrator`. Raising one against a lease requires `expected_lease_agreement_version` per §2.7, the `period_year` the invoice covers, and the `production_mwh` metered net generation attributable to the parcel for that period. `period_year` is 1-based and must be an integer from 1 to 35, matching the lease's thirty-five-year term; a `period_year` outside that range, or one for which the lease already carries an invoice in `DRAFT`, `ISSUED` or `PAID`, is refused with `ERR_DUPLICATE_INVOICE_PERIOD` (409). `production_mwh` is zero or more with at most two decimal places and defaults to 0 when the field is omitted. A newly raised invoice opens in `DRAFT` and bumps the lease's `version` as the concurrency parent.

Which of the two rent variants applies is decided **once, at creation**, by reading the lease's `recording_status` at that instant, and is frozen onto the invoice as `rent_variant`. A lease that is not yet `RECORDED` produces a `PROVISIONAL` invoice; a lease that has reached `RECORDED` produces a `FINAL_AS_BUILT` invoice. A voided invoice frees its `period_year`, so a period first billed provisionally can be re-billed as a final as-built figure once the memorandum has been recorded — that is the intended use of the void-and-replace path.

The invoice total is built from two components, and the rounding order between them is pinned. The **per-acre component** starts from a base amount: the originating option agreement's `base_rent_per_acre_cents` multiplied by the invoice's `acre_basis`, rounded half up to whole cents. An escalation factor is then applied for the elapsed lease years, where the number of elapsed years is one less than `period_year` — year one is unescalated. Under `escalator_mode` `COMPOUND` the factor is one plus `escalator_pct_bps` divided by ten thousand, raised to the power of the elapsed years. Under `escalator_mode` `SIMPLE` the factor is one plus `escalator_pct_bps` divided by ten thousand and multiplied by the elapsed years. `per_acre_component_cents` is the base amount multiplied by that factor, rounded half up to whole cents. The **royalty component**, `royalty_component_cents`, is `production_mwh` multiplied by forty-two dollars per megawatt-hour — the fixed reference price of 4200 cents — multiplied by the option's `royalty_rate_bps` divided by ten thousand, rounded half up to whole cents.

`gross_rent_cents` then depends on the option's `rent_structure_type`. Under `PER_ACRE` it is simply `per_acre_component_cents`. Under `ROYALTY_HYBRID` it is the greater of `per_acre_component_cents` and `royalty_component_cents`. **Both components are rounded to whole cents before that comparison is made**; comparing the unrounded real numbers and rounding the winner afterwards is wrong and can produce a different total by a cent.

The two variants differ in exactly two places. Under `PROVISIONAL`, `acre_basis` is the parcel's deeded `gross_acres`, and `royalty_component_cents` is forced to 0 regardless of `production_mwh` and regardless of `royalty_rate_bps` — so `gross_rent_cents` equals `per_acre_component_cents` even under a `ROYALTY_HYBRID` structure. Under `FINAL_AS_BUILT`, `acre_basis` is the parcel's as-built `buildable_acres`, and `royalty_component_cents` is computed and does enter the greater-of comparison. For identical lease terms and identical production, the two variants therefore return different totals. All other terms — `base_rent_per_acre_cents`, `royalty_rate_bps`, `escalator_pct_bps`, `escalator_mode` and `rent_structure_type` — are read from the lease's originating option agreement, and only the `production_mwh` on the invoice being created enters the formula; no other invoice's production is consulted.

Because that difference is material to a developer's model, the API exposes a **non-persisting projection capability** on a lease, available to a `PortfolioManager` or a `PaymentAdministrator`. It takes a `period_year` and a `production_mwh` assumption and returns both variants side by side for comparison without creating anything: `lease_agreement_id` and `period_year` echo the inputs, `provisional_acre_basis` and `provisional_gross_rent_cents` give the deeded-acre royalty-suppressed figure, `final_acre_basis`, `final_per_acre_component_cents`, `final_royalty_component_cents` and `final_gross_rent_cents` give the as-built figure with the royalty in play, and `variant_delta_cents` is `final_gross_rent_cents` less `provisional_gross_rent_cents`. Every figure is computed exactly as the corresponding variant would compute it for a real invoice.

The invoice lifecycle has four states. **Issuing** moves a `DRAFT` invoice to `ISSUED`, stamps `issued_at` from the logical clock, and sets `due_at` to `issued_at` advanced by forty-five days of net terms; `due_at` is null while the invoice is still `DRAFT`. **Paying** moves an `ISSUED` invoice to `PAID` and carries `paid_amount_cents`, which must equal the invoice's `gross_rent_cents` **exactly** — partial payments and overpayments are both refused with `ERR_PAYMENT_AMOUNT_MISMATCH` (422) — and additionally requires the landowner's `payment_hold` to be false, a held owner being refused with `ERR_LANDOWNER_PAYMENT_HOLD` (422). On success `paid_at` is stamped from the clock, `paid_amount_cents` is stored, and the lease's `last_paid_invoice_year` is recomputed as the highest `period_year` among that lease's invoices in `PAID`, or 0 when it has none. Rent never touches the option-payment ledger: paying an invoice leaves `total_paid_cents` and `total_option_paid_cents` alone. **Voiding** is available from `DRAFT` and from `ISSUED`, records the supplied `void_reason`, and frees the lease-and-period slot so a replacement invoice may be raised; voiding an `ISSUED` invoice additionally stops it counting toward the delinquency sweep. `PAID` and `VOID` are both terminal; any transition attempted from the wrong status, including a repeat of one already applied, is refused with `ERR_INVALID_STATE` (409).

The lease's rent dimension tracks all of this and is cyclic. A payment moves the lease `PENDING_FIRST_RENT → CURRENT`, recomputing `last_paid_invoice_year` as it goes. The delinquency sweep of §2.6 moves a lease whose rent dimension reads `PENDING_FIRST_RENT` or `CURRENT` to `DELINQUENT` as soon as it holds at least one invoice in `ISSUED` whose `due_at` has been reached or passed — so both `PENDING_FIRST_RENT → DELINQUENT` and `CURRENT → DELINQUENT` are reachable. The reverse edge closes the cycle: a payment moves the lease `DELINQUENT → CURRENT`, but only once, after that payment, the lease holds no invoice at all in `ISSUED` with a `due_at` at or before the current logical clock. A lease with two overdue invoices therefore stays `DELINQUENT` after the first of them is settled and only clears when the second is settled too. The rent dimension has no terminal state — a lease can cycle between `CURRENT` and `DELINQUENT` for the whole of its term.

Invoices are readable individually — the read exposes `rent_variant`, `acre_basis`, both components and `gross_rent_cents` — and as a collection filterable by lease, period, variant or status, with reads restricted to a `PortfolioManager`, a `PaymentAdministrator`, or the `Landowner` the invoice is addressed to. A path identifier naming no invoice is answered with `ERR_RENT_INVOICE_NOT_FOUND` (404).

## 4. Endpoint Definitions

Every endpoint listed below is authenticated and authorised as described in §2.1, and every response is wrapped in the envelope of §2.2. Status codes follow one rule: an operation that brings a **new** resource into existence answers 201 Created, and every other successful operation answers 200 OK. Ten creates therefore answer 201 — registering a landowner, registering a parcel, publishing a setback rule, requesting a neighbor consent, raising a curative item, drafting an option agreement, planning a corridor, proposing a crossing, booking site access, and raising a rent invoice — together with the option exercise, which answers 201 because it mints a lease agreement even though the option itself is only transitioning. Amendments, state transitions, security postings and the logical-clock control all answer 200.

The table is deliberately minimal: it carries no request bodies, no response shapes and no side effects. Those live in the §3 narratives, and a complete implementation of any endpoint has to be reconstructed from the workflow subsection that describes it.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| GET | `/land-origination/landowners/{landownerId}` | Fetch one landowner, including the derived `total_paid_cents` ledger balance. | `LandAgent`, `TitleCounsel`, `PortfolioManager`, `PaymentAdministrator`, `Landowner` |
| GET | `/land-origination/parcels/{parcelId}` | Fetch one parcel with its full derived acreage breakdown and screening result. | `LandAgent`, `TitleCounsel`, `PortfolioManager`, `PaymentAdministrator` |
| GET | `/land-origination/setback-rules/{ruleId}` | Fetch one jurisdictional setback rule. | `LandAgent`, `TitleCounsel`, `PortfolioManager` |
| GET | `/land-origination/neighbor-consents/{consentId}` | Fetch one neighbor consent request, including its `released_acres` contribution. | `LandAgent`, `TitleCounsel`, `PortfolioManager` |
| GET | `/land-origination/title-curative-items/{itemId}` | Fetch one title curative item. | `LandAgent`, `TitleCounsel`, `PortfolioManager` |
| GET | `/land-origination/option-agreements/{optionId}` | Fetch one option agreement with its negotiated terms and payment total. | `LandAgent`, `TitleCounsel`, `PortfolioManager`, `PaymentAdministrator`, `Landowner` |
| GET | `/land-origination/option-payments/{paymentId}` | Fetch one immutable option-payment ledger row. | `PortfolioManager`, `PaymentAdministrator`, `Landowner` |
| GET | `/land-origination/corridors/{corridorId}` | Fetch one collection or interconnection corridor. | `LandAgent`, `PortfolioManager` |
| GET | `/land-origination/crossing-agreements/{crossingId}` | Fetch one crossing agreement with its computed compensation. | `LandAgent`, `PortfolioManager`, `PaymentAdministrator` |
| GET | `/land-origination/site-access-bookings/{bookingId}` | Fetch one site-access crew booking. | `LandAgent`, `TitleCounsel`, `PortfolioManager` |
| GET | `/land-origination/leases/{leaseId}` | Fetch one lease agreement with its security, recording and rent dimensions. | `LandAgent`, `TitleCounsel`, `PortfolioManager`, `PaymentAdministrator`, `Landowner` |
| GET | `/land-origination/rent-invoices/{invoiceId}` | Fetch one rent invoice with its variant, components and gross amount. | `PortfolioManager`, `PaymentAdministrator`, `Landowner` |
| GET | `/land-origination/landowners` | List landowners. | `LandAgent`, `TitleCounsel`, `PortfolioManager`, `PaymentAdministrator` |
| GET | `/land-origination/parcels` | List parcels, filterable by owning landowner, county, screening tier or status. | `LandAgent`, `TitleCounsel`, `PortfolioManager`, `PaymentAdministrator` |
| GET | `/land-origination/setback-rules` | List setback rules, filterable by jurisdiction or rule type. | `LandAgent`, `TitleCounsel`, `PortfolioManager` |
| GET | `/land-origination/neighbor-consents` | List neighbor consents, filterable by parcel, setback rule or status. | `LandAgent`, `TitleCounsel`, `PortfolioManager` |
| GET | `/land-origination/title-curative-items` | List title curative items, filterable by parcel, predecessor, severity or status. | `LandAgent`, `TitleCounsel`, `PortfolioManager` |
| GET | `/land-origination/option-agreements` | List option agreements, filterable by parcel, landowner or status. | `LandAgent`, `TitleCounsel`, `PortfolioManager`, `PaymentAdministrator`, `Landowner` |
| GET | `/land-origination/option-payments` | List option-payment ledger rows, filterable by agreement or payment kind. | `PortfolioManager`, `PaymentAdministrator`, `Landowner` |
| GET | `/land-origination/corridors` | List corridors, filterable by status or voltage class. | `LandAgent`, `PortfolioManager` |
| GET | `/land-origination/crossing-agreements` | List crossing agreements, filterable by corridor, parcel, kind or status. | `LandAgent`, `PortfolioManager`, `PaymentAdministrator` |
| GET | `/land-origination/site-access-bookings` | List site-access bookings, filterable by parcel or status. | `LandAgent`, `TitleCounsel`, `PortfolioManager` |
| GET | `/land-origination/leases` | List lease agreements, filterable by option, parcel, landowner, rent status or recording status. | `LandAgent`, `TitleCounsel`, `PortfolioManager`, `PaymentAdministrator`, `Landowner` |
| GET | `/land-origination/rent-invoices` | List rent invoices, filterable by lease, period year, variant or status. | `PortfolioManager`, `PaymentAdministrator`, `Landowner` |
| GET | `/land-origination/leases/{leaseId}/rent-projection` | Computed, non-persisting read: projects one period's rent under both variants side by side. | `PortfolioManager`, `PaymentAdministrator` |
| POST | `/land-origination/landowners` | Register a prospective landowner. | `LandAgent` |
| PATCH | `/land-origination/landowners/{landownerId}` | Amend the landowner's payable administration attributes. | `PaymentAdministrator` |
| POST | `/land-origination/parcels` | Register a candidate parcel and screen it immediately under the desktop variant. | `LandAgent` |
| POST | `/land-origination/parcels/{parcelId}/rescreen` | Re-screen the parcel under the requested screen mode, persisting that mode. | `LandAgent` |
| POST | `/land-origination/setback-rules` | Publish a jurisdictional setback rule and re-derive every parcel it now applies to. | `TitleCounsel` |
| POST | `/land-origination/neighbor-consents` | Request a neighbour's written consent to waive a setback encumbrance. | `LandAgent` |
| POST | `/land-origination/neighbor-consents/{consentId}/grant` | Record the neighbour's consent and cascade the acreage release. | `LandAgent` |
| POST | `/land-origination/neighbor-consents/{consentId}/revoke` | Record the neighbour's withdrawal of consent and restore the encumbrance. | `LandAgent` |
| POST | `/land-origination/title-curative-items` | Raise a title defect against a parcel. | `TitleCounsel` |
| POST | `/land-origination/title-curative-items/{itemId}/clear` | Record that the curative work is complete and title is cured. | `TitleCounsel` |
| POST | `/land-origination/title-curative-items/{itemId}/waive` | Accept the defect on the record with counsel's written note instead of curing it. | `TitleCounsel` |
| POST | `/land-origination/option-agreements` | Draft an option agreement over a parcel. | `LandAgent` |
| POST | `/land-origination/option-agreements/{optionId}/send` | Send the drafted or revised terms to the landowner. | `LandAgent` |
| POST | `/land-origination/option-agreements/{optionId}/counter` | Landowner counters the sent terms. | `Landowner` |
| POST | `/land-origination/option-agreements/{optionId}/revise` | Answer a counter with revised terms. | `LandAgent` |
| POST | `/land-origination/option-agreements/{optionId}/accept` | Landowner accepts the terms on the table. | `Landowner` |
| POST | `/land-origination/option-agreements/{optionId}/execute` | Execute the option and mint the initial option fee. | `PortfolioManager` |
| POST | `/land-origination/option-agreements/{optionId}/extend` | Buy one extension of the option term at the stepped-up rate. | `PortfolioManager` |
| POST | `/land-origination/option-agreements/{optionId}/exercise` | Exercise the option and originate the lease. Returns the new lease agreement. | `PortfolioManager` |
| POST | `/land-origination/option-agreements/{optionId}/withdraw` | Withdraw from the option at any pre-exercise stage. | `LandAgent`, `PortfolioManager` |
| POST | `/land-origination/corridors` | Plan a collection-line or interconnection corridor. | `LandAgent` |
| POST | `/land-origination/corridors/{corridorId}/permit` | Record the corridor's route permit. | `PortfolioManager` |
| POST | `/land-origination/crossing-agreements` | Propose a crossing over a parcel for a station range and occupancy window. | `LandAgent` |
| POST | `/land-origination/crossing-agreements/{crossingId}/grant` | Grant the proposed crossing. | `PortfolioManager` |
| POST | `/land-origination/site-access-bookings` | Book a survey, geotech, environmental or staging crew onto a parcel. | `LandAgent`, `TitleCounsel` |
| POST | `/land-origination/site-access-bookings/{bookingId}/cancel` | Cancel a booking, freeing its crew allocation. | `LandAgent`, `TitleCounsel` |
| POST | `/land-origination/leases/{leaseId}/post-security` | Post decommissioning and reclamation security against the lease. | `PaymentAdministrator` |
| POST | `/land-origination/leases/{leaseId}/submit-memo` | Submit the memorandum of lease to the county for recording. | `PortfolioManager` |
| POST | `/land-origination/leases/{leaseId}/record-memo` | Record the memorandum of lease with the county recorder. | `PortfolioManager` |
| POST | `/land-origination/leases/{leaseId}/rent-invoices` | Raise the annual rent invoice for one lease period. | `PaymentAdministrator` |
| POST | `/land-origination/rent-invoices/{invoiceId}/issue` | Issue the invoice to the landowner and set its due date. | `PaymentAdministrator` |
| POST | `/land-origination/rent-invoices/{invoiceId}/pay` | Record payment of the invoice in full. | `PaymentAdministrator` |
| POST | `/land-origination/rent-invoices/{invoiceId}/void` | Void a draft or issued invoice, freeing its period for re-issue. | `PaymentAdministrator` |
| POST | `/_clock/set_current_utc` | Set the logical clock, then run the four time sweeps in their pinned order. | `LandAgent`, `TitleCounsel`, `PortfolioManager`, `PaymentAdministrator` |

## 5. Error Code Catalogue

Every rejection carries one of the identifiers below in `data.error_id`, together with a human-readable `message`. The trigger conditions are not repeated here — each one is stated in the §2 or §3 narrative that governs the rule it guards, and §2.9 fixes which identifier wins when more than one condition is true of the same request.

| Error ID | HTTP Status Code |
|---|---|
| `ERR_MISSING_USER_ID` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_LANDOWNER_NOT_FOUND` | 404 |
| `ERR_PARCEL_NOT_FOUND` | 404 |
| `ERR_SETBACK_RULE_NOT_FOUND` | 404 |
| `ERR_NEIGHBOR_CONSENT_NOT_FOUND` | 404 |
| `ERR_TITLE_CURATIVE_ITEM_NOT_FOUND` | 404 |
| `ERR_OPTION_AGREEMENT_NOT_FOUND` | 404 |
| `ERR_CORRIDOR_NOT_FOUND` | 404 |
| `ERR_CROSSING_AGREEMENT_NOT_FOUND` | 404 |
| `ERR_SITE_ACCESS_BOOKING_NOT_FOUND` | 404 |
| `ERR_LEASE_AGREEMENT_NOT_FOUND` | 404 |
| `ERR_RENT_INVOICE_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATION_RANGE` | 422 |
| `ERR_INVALID_WINDOW_RANGE` | 422 |
| `ERR_STALE_PARCEL_VERSION` | 412 |
| `ERR_STALE_LEASE_VERSION` | 412 |
| `ERR_CONSENT_EXPIRED` | 422 |
| `ERR_OPTION_EXPIRED` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ALREADY_RECORDED` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 422 |
| `ERR_TITLE_CURATIVE_BLOCKING` | 422 |
| `ERR_CURATIVE_BLOCKED_PREDECESSOR` | 422 |
| `ERR_SECURITY_NOT_POSTED` | 422 |
| `ERR_W9_MISSING` | 422 |
| `ERR_PARCEL_APN_DUPLICATE` | 409 |
| `ERR_PROHIBITED_ZONING` | 422 |
| `ERR_PARCEL_NOT_QUALIFIED` | 422 |
| `ERR_EXTENSION_LIMIT_REACHED` | 422 |
| `ERR_NEGOTIATION_ROUND_LIMIT` | 422 |
| `ERR_WAIVER_LIMIT_REACHED` | 422 |
| `ERR_CORRIDOR_NOT_PERMITTED` | 422 |
| `ERR_DUPLICATE_INVOICE_PERIOD` | 409 |
| `ERR_CORRIDOR_STATION_CONFLICT` | 409 |
| `ERR_CREW_CAPACITY_EXCEEDED` | 409 |
| `ERR_WINDOW_IN_PAST` | 422 |
| `ERR_LANDOWNER_PAYMENT_HOLD` | 422 |
| `ERR_SECURITY_OVERPOSTED` | 422 |
| `ERR_PAYMENT_AMOUNT_MISMATCH` | 422 |
