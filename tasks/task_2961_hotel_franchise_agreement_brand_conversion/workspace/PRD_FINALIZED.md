# Hotel Franchise Conversion API — Product Requirements Document

## 1. Introduction

A hotel franchisor grows almost entirely by conversion: an independent or competitor-branded property changes its sign, its systems and its service standards and joins the chain. Every one of those conversions is simultaneously a real-estate transaction, a credit decision, a market-planning exercise, a construction project and a decades-long contract. Today the franchise development team runs that pipeline out of spreadsheets, shared inboxes and a legal-document repository, which means the royalty rate a manager quotes cannot be reconciled against the impact study the market planners ran, an existing franchisee's territory protest surfaces after the license has already been drafted, and nobody can say with confidence whether a hotel that has failed three consecutive quality inspections is contractually terminable.

This document specifies the Hotel Franchise Conversion API, the system of record for the entire arc from application intake to post-termination close-out. It carries ten resource families — brands, ownership entities, already-operating units, conversion applications, encroachment claims, license agreements, property improvement plans and their scope lines, quality assurance inspections, and ownership-consent requests — and it treats every derived number as the franchisor's official position rather than as a convenience. Royalty rates, marketing fund contributions, key money, liquidated damages, impact scores and capacity scores are all computed by the server from stored inputs; no caller is ever permitted to assert them.

Two design commitments shape everything that follows. First, the system is **deliberately multi-axial**: a license agreement advances along four independent state axes at once (contractual status, brand-standard compliance, a three-track onboarding ladder, and post-termination de-identification), and an application carries a cyclic review axis crossed with two independent review axes. A reader must never assume that one axis's terminal state implies anything about another's. Second, the system is **time-driven but not wall-clock-driven**: every deadline, cure window, claim window and timestamp is evaluated against a server-held logical clock that test harnesses and operators set explicitly, so that a 60-day cure period or a 21-day claim window can be exercised deterministically.

## 2. Global Specifications & System-Wide Principles

This section defines the contracts that hold across every endpoint: authentication, response shape, pagination, the logical clock, decimal discipline, concurrency guards, cascade semantics and the order in which validations fire. Where §3 narrates business workflows, this section fixes the mechanics those workflows rely on.

### 2.1. Authentication, Franchisor Roles and Franchisee Identity

Every request to the API must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which that principal is acting. If either header is absent, or is present but empty, the request is rejected with `ERR_MISSING_AUTH_HEADER`. If `X-User-Role` carries any value other than the four the system recognises, the request is rejected with `ERR_INVALID_ROLE`. Both of those failures are authentication failures and carry HTTP 401.

The four recognised roles are `FranchiseDevelopmentManager`, `BrandStandardsDirector`, `QaInspector` and `Owner`, spelled exactly as shown.

- A `FranchiseDevelopmentManager` is a franchise development officer. This role owns the deal pipeline: registering ownership entities and re-verifying their financial profiles, filing applications, opening the review file, recording the financial capacity review, requesting revisions, issuing the approval or decline decision, drafting and executing the license, advancing onboarding milestones and deciding ownership-consent requests.
- A `BrandStandardsDirector` owns brand standards and market planning: the brand registry, the existing-unit map and its status changes, the market impact study, encroachment claim docketing and resolution, the property improvement plan and its scope lines, scope verification and compliance sweeps, extension decisions, opening the hotel, terminating the license and closing out the post-termination file.
- A `QaInspector` scores quality assurance inspections and reviews submitted cures. This role holds no development, planning, plan-scoping or termination authority whatsoever.
- An `Owner` is the franchisee or applicant ownership entity itself. It resubmits revised applications, accepts the improvement scope, reports scope lines complete, requests deadline extensions, files monthly revenue reports, submits inspection cure evidence, seeks consent to transfers and refinancings, and certifies de-identification after termination.

When the role presented on a request is not among the roles the addressed operation admits, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403). §4's endpoint table is the authoritative list of which roles each operation admits.

The three franchisor roles carry **opaque** identity. When `X-User-Role` is `FranchiseDevelopmentManager`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server records it where a workflow calls for an actor of record — as `financial_reviewer_user_id` and `decision_user_id` on an application, and as `decision_user_id` on a consent request — but it never compares it to any entity's `id`. The same holds when `X-User-Role` is `BrandStandardsDirector`, whose identifier is recorded as `filed_by_user_id` on an encroachment claim, and when `X-User-Role` is `QaInspector`, whose identifier is recorded as `inspector_user_id` on an inspection it scores and as `cure_reviewer_user_id` on a cure it reviews. None of these three identifiers is resolved against a stored row.

The `Owner` role is **entity-backed**. When `X-User-Role` is `Owner`, `X-User-ID` is the `id` of the acting ownership entity, and ownership checks on any resource that reaches back to an ownership entity compare that resource's owning identifier to `X-User-ID`. Concretely: for actions addressed at an application, the comparison is against that application's `owner_id`; for actions addressed at a license agreement, a property improvement plan, a scope line, an inspection cure or a consent request, the comparison is against the `owner_id` of the application behind the agreement in question, reached through the agreement's `application_id`. A mismatch is rejected with `ERR_FORBIDDEN_RESOURCE_OWNER` (HTTP 403). The identifier an `Owner` presents when filing a consent request is additionally stored on that request as `submitted_by_user_id`.

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

List endpoints are paginated through two query-string parameters. The `limit` parameter caps how many rows come back; it defaults to 10 when omitted, must be an integer, and must be at least 1 and at most 100. The `offset` parameter says how many rows to skip before the window begins; it defaults to 0 when omitted, must be an integer, and must be at least 0. A `limit` outside the 1-to-100 band or a negative `offset` is a request-shape failure and is rejected with `ERR_INVALID_REQUEST`.

Unless a specific endpoint says otherwise, every list endpoint returns its rows sorted by `created_at` in ascending order.

Every list response carries `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the envelope. `total_count` reports the number of rows matching the filters before the pagination window is applied, and `has_more` is true exactly when rows matching the filters remain beyond the returned window.

### 2.4. The Logical Clock and Calendar Arithmetic

Nothing in this system reads the host machine's wall clock. There is exactly one source of "now": a server-held **logical clock**, settable through an administrative test-driving capability exposed at `POST /_clock/set_current_utc`, which accepts a single field `to_iso8601` carrying the instant to move to and answers with an object of the shape `{ current_utc: string }`. All four roles may drive it. Before the first such call, the logical clock reads exactly `2026-08-01T00:00:00Z`; it never falls back to real time. Setting the clock mutates no entity and re-evaluates no deadline on its own — deadlines are only re-examined when a workflow operation touches them, which is why the property improvement plan carries an explicit compliance sweep rather than a background timer.

Three arithmetic conventions govern every deadline in the specification.

**Adding days to an instant.** Where a rule says a deadline is some anchor instant advanced by a number of days, whole days are added to that ISO-8601 instant and the time of day is preserved exactly. A plan accepted at `2026-09-04T14:30:00.000Z` with a 90-day allowance yields a due instant at 14:30:00.000 UTC on the ninetieth day after. This applies to scope-line due dates, the property-improvement default cure deadline, inspection cure deadlines, the encroachment claim window, the de-identification deadline and the minimum inspection gap alike.

**Adding calendar years to a date.** Where a rule advances a calendar date by a number of years — the license expiry derived from the effective date, and the requested license interval derived from the requested conversion date — the year component is advanced and the month and day are kept unchanged.

**Whole-month spans.** Where a rule counts months between two dates, it counts whole calendar months by month index and never by elapsed days: the span is the expiry year multiplied by twelve plus the expiry month, minus the termination year multiplied by twelve plus the termination month, and the result is floored at zero so that an already-expired term contributes nothing.

Boundary inclusivity is stated individually at every window in §3, because it is not uniform. Some windows admit the boundary instant and some exclude it, and the difference is observable.

### 2.5. Resource Identity, Audit Fields and Record Versioning

All ten resource families in this system — brands, ownership entities, existing units, applications, encroachment claims, license agreements, property improvement plans, scope lines, quality assurance inspections and ownership-consent requests — carry the same four server-managed properties. There are no exceptions: every one of the ten exposes all four.

- `id` (string): a server-minted unique identifier formatted as a UUID. It carries no type prefix, no domain flavour and no embedded semantics; clients must treat it as opaque.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits (for example `2026-08-01T00:00:00.000Z`) recording when the row was first written. It is stamped from the logical clock and never changes afterwards.
- `updated_at` (string): an ISO 8601 UTC timestamp in the same format, refreshed from the logical clock on every mutation of the row.
- `version` (integer): a monotonically increasing counter that advances by one on every mutation of the row.

A "mutation" here includes changes that no client asked for directly. When a derived counter such as a brand's `operating_unit_count`, a plan's `items_verified_count` or an agreement's `royalty_fee_to_date` is recomputed as the downstream consequence of an operation on another resource, that recomputation is itself a mutation of the carrying row: its `updated_at` is refreshed and its `version` advances. The same is true of every cascade described in §2.8 — an application knocked from `PASSED` to `STALE`, a draft agreement knocked to `VOIDED`, a consent request refused by a default notice, or a plan suspended by a termination all take an `updated_at` refresh and a `version` increment on the affected row.

Two `version` counters carry additional contractual weight because they are the anchors of the concurrency guards described in §2.7: the `version` of an application and the `version` of a license agreement. Both advance under the general rule above **and** are advanced explicitly by particular operations, as §3 records at the point each operation is described.

### 2.6. Decimal Discipline: Money, Rates and Scores

Every monetary amount, percentage rate and score in this system is a decimal quantity, never a binary floating-point one, and every value is transported in JSON as a number rather than a string.

The default precision is **two decimal places, rounded half up**. That applies to every money field — liquid assets, net worth, cost estimates, key money, fees, liquidated damages, settlement amounts and penalties — and to every rate and score field, including royalty and marketing-fund rates, capacity scores, impact scores, inspection weighted and total scores, and computed distances in miles.

Three refinements to the default are normative and observable, and getting any of them wrong produces a different answer than the specification demands:

1. **Intermediate factors at four decimal places.** The two per-unit factors inside the market impact study — the proximity factor and the room share — are each rounded half up to four decimal places before they are multiplied together. Only the resulting per-unit contribution returns to two decimal places.
2. **Round-then-accumulate, never accumulate-then-round.** Wherever a total is built from parts, each part is rounded first and the rounded parts are then added. This governs the four weighted components of a capacity score, the per-unit contributions of an impact score, the three tier slices of a monthly royalty, the per-month terms of a discounted liquidated-damages figure, and every running fee total on a license agreement. Summing unrounded parts and rounding once at the end is wrong.
3. **Running totals are exact sums, never re-rounded.** An agreement's `royalty_fee_to_date`, `marketing_fund_contributed_total`, `reservation_fee_to_date` and `total_fees_assessed` are the exact arithmetic sums of the already-rounded per-period components. They are never re-derived from raw revenue and never rounded a second time.

Integer-valued quantities — term lengths in years, day counts, key-count minimums, month spans, credit scores, section scores and defect counts — are integers and take no rounding at all. Key-money band percentages are likewise integers.

### 2.7. Version Guards on Execution and Consent Decisions

Two write operations in this system are guarded by optimistic concurrency control, because in both cases a client can legitimately be holding a stale picture of a parent record that several sibling children compete over.

**Executing a license agreement.** A request to execute a drafted license must carry `expected_application_version` in its body. The field is not optional; a request that omits it fails request-shape validation. Its value must equal the current `version` of the `Application` the agreement was drafted from. Several agreements may legitimately be drafted from a single approved application, and any one of them may legitimately be the one that gets executed; a writer holding a stale view of the application must therefore be turned away rather than allowed to execute against a superseded understanding of the approval, the capacity snapshot or the derived license terms. If the supplied value does not equal the application's current `version`, the request is rejected with `ERR_STALE_APPLICATION_VERSION` and HTTP 412. A successful execution advances the application's `version` by one, so a second execution attempt replaying the same expected value will fail this guard.

**Deciding an ownership-consent request.** A request to decide a consent request must carry `expected_agreement_version` in its body, again as a required field, and its value must equal the current `version` of the `LicenseAgreement` the request was filed against. An agreement may legitimately carry several open consent requests of different types at once, and consenting to one changes the ownership picture the others were assessed against, so a decision carrying a stale agreement version is refused with `ERR_STALE_AGREEMENT_VERSION` and HTTP 412. Both decision outcomes advance the agreement's `version` by one, so consecutive decisions on sibling requests must each re-read the agreement first.

No other operation in this API accepts a version field of any kind. Endpoints outside these two are not version-guarded, and supplying an unrecognised field to them has no effect.

### 2.8. Parallel State Axes and Cascade Discipline

This system declares seventeen independent state axes across eight of its ten resource families. Because several of them live on the same row, the phrase "the status of the agreement" is always ambiguous unless the axis is named. The complete inventory, with exact enumeration values, is:

- An application's primary review axis, `status`, starts at `SUBMITTED` and moves among `UNDER_REVIEW` and `REVISION_REQUESTED` before reaching one of the two terminal values `APPROVED` or `DECLINED`.
- An application's `financial_review_status` axis starts at `NOT_STARTED` and moves among `PASSED`, `FAILED` and `STALE`. It has no terminal value.
- An application's `impact_study_status` axis starts at `NOT_STARTED` and moves among `PRELIMINARY` and `FINAL`. It has no terminal value.
- An encroachment claim's `status` starts at `FILED` and reaches one of the two terminal values `SUSTAINED` or `OVERRULED`.
- A license agreement's contractual axis, `status`, starts at `DRAFT` and moves through `EXECUTED`, `OPEN` and `TERMINATION_PENDING` to the terminal value `TERMINATED`, or from `DRAFT` directly to the other terminal value `VOIDED`.
- A license agreement's `compliance_status` axis starts at `COMPLIANT` and moves among `CURE_PERIOD`, `DEFAULT_NOTICE` and `TERMINATION_ELIGIBLE`.
- A license agreement's `training_status` axis starts at `NOT_STARTED` and reaches the terminal value `COMPLETED`.
- A license agreement's `systems_status` axis is an ordered ladder from `NOT_STARTED` through `PROVISIONED` to the terminal value `VALIDATED`.
- A license agreement's `channel_status` axis is an ordered ladder from `NOT_CONNECTED` through `TESTING` to `CONNECTED`, with a fourth value `SUSPENDED` reachable from `CONNECTED` and returnable to `CONNECTED`.
- A license agreement's `de_identification_status` axis starts at `NOT_REQUIRED` and moves through `PENDING` to either `SUBMITTED` or `BREACHED`, and from either of those to the terminal value `VERIFIED`.
- A property improvement plan's `status` starts at `SCOPED` and moves through `ACCEPTED`, `IN_PROGRESS` and `DEFAULTED`, reaching the terminal values `COMPLETED` or `SUSPENDED`.
- A scope line's `status` starts at `PENDING` and moves among `SUBMITTED` and `OVERDUE` before reaching the terminal value `VERIFIED`.
- A scope line's `extension_status` axis starts at `NONE` and moves among `PENDING`, `GRANTED` and `DENIED`.
- An inspection's `status` is created either at the terminal value `CLOSED` or at `CURE_PENDING`, and from `CURE_PENDING` moves through `CURE_SUBMITTED` to one of the terminal values `CURE_PASSED` or `CURE_FAILED`.
- A consent request's `status` starts at `SUBMITTED` and reaches one of the terminal values `CONSENTED` or `REFUSED`.
- An existing unit's `status` starts at `OPERATING` and moves between `OPERATING` and `SUSPENDED` before reaching the terminal value `TERMINATED`.
- An ownership entity's `status` starts at `PROSPECT` and reaches the terminal value `ACTIVE`.

A license agreement additionally carries `post_termination_status`, which is `NOT_APPLICABLE` until termination opens the post-termination file, becomes `OPEN` at that point and `CLOSED` at close-out.

Three axes are explicitly **cyclic**, and each exposes an observable loop counter or a reversible pair. An application can bounce between `UNDER_REVIEW` and `REVISION_REQUESTED` without bound, and `revision_round` counts the laps. A scope line can be rejected from `SUBMITTED` back to `PENDING` any number of times, and `rejection_count` counts those. A scope line can also go `OVERDUE` and return to `PENDING` on a granted extension, and go `OVERDUE` again once the extended deadline passes; correspondingly a plan can move from `IN_PROGRESS` or `ACCEPTED` to `DEFAULTED` and recover to `IN_PROGRESS` more than once.

**Cascade discipline.** A great many operations in this system mutate more than the resource they address, and every such secondary effect is part of the contract rather than an implementation detail. The system performs these reconciliations immediately and synchronously within the triggering request; there is no eventual-consistency window and no background job. When a cascade transitions a resource nobody named in the request, that resource's `updated_at` and `version` advance as described in §2.5, and the transition is observable on the next read of that resource. §3 states each cascade at the workflow that fires it; the families are: the re-verification cascade from an ownership entity onto its applications' financial review axis; the three-level sustained-claim cascade from a claim onto its application's impact study and onto that application's draft agreements; the compensating pair of failed-cure and passed-cure cascades from an inspection onto its agreement's compliance and reservation-channel axes; the plan-default cascade from a compliance sweep onto the agreement's compliance axis and onto that agreement's open consent requests; the termination cascade from an agreement onto its reservation channel, its de-identification clock and its improvement plan; the bubble-up cascade from scope lines onto their plan's counters and status; the execution cascade from an agreement onto its application's `version` and its owner's `status`; and the two count-maintenance cascades that keep a brand's `operating_unit_count` and `open_application_count` accurate.

### 2.9. Path Resolution and Validation Precedence

Resource identifiers in a URL path are resolved **left to right**, and the first identifier that names no existing row terminates the request with that resource family's own 404 error: `ERR_BRAND_NOT_FOUND`, `ERR_OWNER_NOT_FOUND`, `ERR_EXISTING_UNIT_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_PIP_NOT_FOUND`, `ERR_PIP_ITEM_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND` or `ERR_TRANSFER_REQUEST_NOT_FOUND`. Foreign keys arriving in a request body are resolved after the path and before any business rule fires, and they answer with the same family-specific 404 codes: an application create resolves both `owner_id` and `brand_id`, an existing-unit create resolves `brand_id`, a claim create resolves `existing_unit_id`, and a consent-request create resolves `proposed_owner_id` when one is supplied.

Because many operations in this API are guarded by half a dozen checks at once, the order in which those checks fire is normative — a caller must be able to predict which single error identifier comes back when more than one condition is violated. The system evaluates in the following bands, and within a band in the order listed:

1. Both authentication headers present and non-empty (`ERR_MISSING_AUTH_HEADER`).
2. `X-User-Role` is one of the four recognised roles (`ERR_INVALID_ROLE`).
3. The acting role appears on the addressed operation's role list (`ERR_UNAUTHORIZED`).
4. Every identifier in the path resolves, left to right (the family-specific 404 codes).
5. Every foreign key in the request body resolves (the family-specific 404 codes).
6. When the acting role is `Owner`, the addressed resource belongs to that ownership entity (`ERR_FORBIDDEN_RESOURCE_OWNER`).
7. Request-body shape: every required field present, every field of its declared JSON type, every enumerated value inside its declared set, every number inside its declared range and decimal width, every date and datetime a valid ISO-8601 value, and pagination parameters within their bands. Unknown fields are ignored rather than rejected. Any failure here is `ERR_INVALID_REQUEST`.
8. State preconditions on the addressed resource and its parents, in the order the axes are listed in §3 for that operation (the `..._STAGE_INVALID`, `..._NOT_*` and transition-validity codes).
9. The concurrency guard of §2.7, where one applies (`ERR_STALE_APPLICATION_VERSION`, `ERR_STALE_AGREEMENT_VERSION`).
10. Business safety rules — the life-safety and critical scope gates, the life-safety extension prohibition, and segregation of duties.
11. Remaining business constraints — consent blocking, territory conflict, open claims, duplicate revenue periods, brand code uniqueness, extension limits, de-identification completeness and the brand key-count minimum.
12. Referential business rules — onboarding sequencing and completeness, channel readiness, plan acceptance, financial review status, impact study finality and verdict, claimant eligibility, and termination eligibility.
13. Temporal window rules — the claim window, the cure window, the minimum inspection gap, the scope-line due date and the extension window.
14. Fiscal rules — live owner capacity, proposed transferee capacity, and the post-termination settlement floor.

### 2.10. Segregation of Duties

The franchisor operates a two-person rule at exactly two points in the system, and in both cases the rule is expressed against the opaque `X-User-ID` of the earlier actor rather than against any stored role assignment.

The operator who recorded an application's financial capacity review — the identifier the system stored as `financial_reviewer_user_id` — may not be the operator who issues that application's decision. Both are `FranchiseDevelopmentManager` actions, so the role check passes and the identity check is the only thing standing between the two steps. If the identifier on the decision request equals the stored reviewer identifier, the decision is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). The rule applies to both decision outcomes, not just to approval: a decline taken by the reviewer is refused just as an approval would be. Because a fresh review overwrites `financial_reviewer_user_id`, the identity the rule blocks is always the most recent reviewer's.

The inspector who scored a quality assurance inspection — the identifier stored as `inspector_user_id` — may not be the inspector who reviews the cure submitted against it. Both are `QaInspector` actions, and again the identity comparison carries the whole rule. A cure review from the scoring inspector is refused with the same `ERR_SEGREGATION_OF_DUTIES` and HTTP 403. The reviewing inspector's identifier is then stored as `cure_reviewer_user_id`.

Beyond these two pairings the three franchisor roles are peers over disjoint resource surfaces, and no other operation compares one actor identifier against another.

### 2.11. Dual-Variant Derivations

Three of this system's nine derivations are **two-variant** calculations: the same inputs are legitimately evaluated under two different rule sets, both variants are meaningful, and the choice of variant is recorded so that the resulting number can be defended later. This is a recurring shape rather than a special case, and each variant is specified to the same depth in §3.

**Owner capacity scoring** runs under `STANDALONE` and `PORTFOLIO_ADJUSTED`. The two variants are always both computed and both stored side by side on an ownership entity, and they diverge in *both* directions on the same row: for a multi-unit owner with thin liquidity the portfolio reserve deduction dominates and the adjusted score is lower, while for a liquid multi-unit owner the experience bonus dominates and the adjusted score is higher. An application records which variant its financial review was taken on in `capacity_basis`; transferee screening on a consent request always uses `STANDALONE`.

**Market impact scoring** runs under `PRELIMINARY` and `FINAL`. The variants differ only in which existing units enter the input set, and because the `FINAL` set is a superset of the `PRELIMINARY` set over the same unit population, the `FINAL` score before the claim penalty is always greater than or equal to the preliminary one. Only the final figure feeds the encroachment verdict and the marketing-fund surcharge.

**Liquidated damages** runs under `CONTRACTUAL_MULTIPLE` and `DISCOUNTED_PV`, selected by the termination cause rather than by any caller choice. For any positive capped month count the contractual multiple is strictly the larger of the two amounts, since the discounted variant reduces each future month to present value before summing.

### 2.12. Enumerated Vocabularies

Beyond the seventeen state axes of §2.8, the following fields are enumerations, and only the listed values are accepted:

- A brand's `tier` is one of `ECONOMY`, `MIDSCALE`, `UPSCALE` or `LUXURY`.
- An ownership entity's `capacity_band_standalone` and `capacity_band_portfolio_adjusted`, an application's `capacity_band_at_review`, and a consent request's `proposed_owner_capacity_band` are each one of `STRONG`, `ADEQUATE` or `INSUFFICIENT`; the two snapshot fields are null before the snapshot is taken.
- An application's `current_affiliation` is one of `INDEPENDENT`, `COMPETITOR` or `OUR_BRAND`.
- An application's `capacity_basis` is `STANDALONE` or `PORTFOLIO_ADJUSTED`, or null before the first financial review.
- An application's `encroachment_verdict` is one of `CLEAR`, `MITIGATION_REQUIRED` or `ENCROACHMENT_CONFIRMED`, or null while the impact study is not `FINAL`.
- An application's `decision_outcome` is `APPROVE` or `DECLINE`, or null before a decision.
- A scope line's `category` is one of `GUESTROOM`, `EXTERIOR`, `FOOD_BEVERAGE`, `LIFE_SAFETY` or `TECHNOLOGY`, and its `priority` is one of `CRITICAL`, `MAJOR` or `MINOR`.
- An inspection's `grade` is one of `PASS`, `CONDITIONAL` or `FAIL`.
- A consent request's `request_type` is one of `TRANSFER`, `CHANGE_OF_CONTROL` or `REFINANCE`, and its `refusal_reason` is one of `DEFAULT_NOTICE`, `CAPACITY` or `DISCRETION`, or null while no refusal has been recorded.
- An agreement's `termination_cause` is one of `FOR_CAUSE_QA`, `FOR_CAUSE_PIP` or `MUTUAL`, or null before termination, and its `liquidated_damages_formula` is `CONTRACTUAL_MULTIPLE` or `DISCOUNTED_PV`, or null before termination.
- The elements of an agreement's `de_identification_items_completed` array are drawn from `SIGNAGE`, `INTERIOR_BRANDING`, `DIGITAL_LISTINGS`, `LINENS_AND_COLLATERAL` and `RESERVATION_CODES`.

## 3. Business Logic & Workflows

The narrative below follows the commercial arc of a conversion: the brand and market picture that must exist first, the ownership entity and its creditworthiness, the application and its two independent review studies, the approval gate, the license and its onboarding, the construction scope, the operating years, and finally the exit. Rules that belong to more than one stage are stated where they bind rather than collected into a single reference block.

### 3.1. The Brand Registry and the Existing Unit Map

Everything in this system hangs off a **brand**. A `BrandStandardsDirector` registers one by supplying a `code`, a `name`, a `tier`, a rate card and a set of development thresholds. The `code` is the short identifier that appears on signage and in reservation-channel records: it is 3 to 12 characters long and may contain only the uppercase letters A through Z and the digits 0 through 9. No two brands may carry the same `code`; an attempt to register a second brand with a code already in use is refused with `ERR_BRAND_CODE_TAKEN`. The consumer-facing `name` runs from 1 to 120 characters.

The rate card consists of two published rates that are the *starting point* for every license derived from the brand rather than the rate any particular franchisee actually pays. `base_royalty_rate_pct` is the published continuing-fee royalty rate before conversion and capacity adjustments, expressed as a percentage between 0.00 and 10.00 inclusive with exactly two decimal places. `marketing_fund_rate_pct` is the published brand marketing fund contribution rate before any impact surcharge, between 0.00 and 5.00 inclusive with exactly two decimal places. Alongside them sit three development thresholds: `protected_radius_miles`, the radius in miles of the area of protection granted to each operating unit of the brand, between 0.01 and 50.00 inclusive with exactly two decimal places; `min_room_count`, the minimum key count a converting property must have to fly the brand, an integer of at least 1; and `standard_term_years`, the standard license term in years and the ceiling on any granted term, an integer between 5 and 30 inclusive.

Registration returns 201 and sets both of the brand's derived counters to 0. `operating_unit_count` is the number of existing units whose `brand_id` names this brand and whose `status` is `OPERATING`; it is recomputed on every unit registration and on every unit status change. `open_application_count` is the number of applications whose `brand_id` names this brand and whose `status` is one of `SUBMITTED`, `UNDER_REVIEW` or `REVISION_REQUESTED`; it is recomputed on every application creation and on every application status change. Both counters are readable on the brand, and both are maintained by the system rather than supplied by a caller.

The **existing unit map** is the franchisor's inventory of hotels already flying a brand, and it exists so that the market impact study and the territory-conflict rule have something to measure against. A `BrandStandardsDirector` registers a unit against a brand by supplying that brand's identifier as `brand_id`, an operating hotel `unit_name` of 1 to 120 characters, a franchisor `market_code` of 3 to 8 characters drawn only from uppercase A through Z and the digits 0 through 9, a position on the franchisor's planar market grid as `x_miles` (the east coordinate) and `y_miles` (the north coordinate), each between -500.00 and 500.00 inclusive with exactly two decimal places, a `room_count` of at least 1, a trailing `adr_amount` in US dollars of at least 0.00 with exactly two decimal places, a trailing `occupancy_pct` between 0.00 and 100.00 inclusive with exactly two decimal places, and the two endpoints of the unit's area-of-protection term as `territory_start_date` and `territory_end_date`, both calendar dates in `YYYY-MM-DD` form. The closing date must not precede the opening date; an end date earlier than the start date is rejected with `ERR_INVALID_REQUEST`. Both endpoints are **inclusive** wherever a territory term is tested for overlap, a point that matters materially at the approval gate. Registration returns 201, stamps the unit's `status` as `OPERATING` and advances the brand's `operating_unit_count` by one.

Units do not stay operating forever. A `BrandStandardsDirector` moves a unit along its status axis by naming the target in `to_status` and optionally supplying a `reason`, which is stored on the unit as `status_reason` and is null until the first such call. Only four moves are declared: `OPERATING → SUSPENDED`, `SUSPENDED → OPERATING`, `OPERATING → TERMINATED` and `SUSPENDED → TERMINATED`. Nothing leaves `TERMINATED`, and any move that is not one of the four — including any attempt to move out of `TERMINATED` — is refused with `ERR_UNIT_STATUS_TRANSITION_INVALID`. Suspending an operating unit lowers the brand's `operating_unit_count` by one; restoring a suspended unit raises it by one; terminating an operating unit lowers it by one; terminating a unit that was already suspended leaves the counter alone, because a suspended unit was never in it. The consequences for market analysis are just as important: a suspended unit leaves the preliminary impact input set but remains in the final one, while a terminated unit leaves both input sets and may no longer file an encroachment claim.

The units of one brand can be listed from that brand, which is how a client discovers which units carry a given `brand_id`; the listing accepts an optional `status` filter alongside the standard `limit` and `offset` pagination parameters.

### 3.2. Ownership Entities and the Two Capacity Scores

An **ownership entity** is the legal person that applies for and eventually holds a license. A `FranchiseDevelopmentManager` registers one by supplying a `legal_name` of 1 to 160 characters, a primary development `contact_email` of 5 to 160 characters that must contain exactly one `@` character with at least one `.` character somewhere after it, and four verified financial inputs: `liquid_assets_amount`, the unencumbered liquid assets in US dollars, at least 0.00 with exactly two decimal places; `net_worth_amount`, the verified net worth in US dollars under the same constraints; `credit_score`, the guarantor's credit score as an integer between 300 and 850 inclusive; and `existing_units_count`, the number of hotels the entity already operates under any brand, an integer of at least 0. Registration returns 201, stamps `status` as `PROSPECT`, sets `financial_profile_revision` to 0 and immediately computes **both** capacity variants.

Capacity scoring is the franchisor's underwriting opinion, expressed on a 0-to-100 scale. Three components are computed, each rounded half up to two decimal places on its own before it is weighted.

The **liquidity component** measures liquid assets against a benchmark of 5,000,000.00 US dollars. Under the `STANDALONE` variant the effective liquidity is simply `liquid_assets_amount`. Under the `PORTFOLIO_ADJUSTED` variant the franchisor first sets aside an operating reserve of 250,000.00 US dollars for every hotel the entity already operates, so the effective liquidity is `liquid_assets_amount` reduced by 250,000.00 multiplied by `existing_units_count`, floored at 0.00 so that a heavily committed owner never scores negative liquidity. In either variant the component is the effective liquidity divided by 5,000,000.00, multiplied by 100, rounded half up to two decimal places, and then capped at 100.00.

The **balance-sheet component** measures `net_worth_amount` against a benchmark of 15,000,000.00 US dollars: net worth divided by 15,000,000.00, multiplied by 100, rounded half up to two decimal places, capped at 100.00. It is identical under both variants.

The **credit component** maps the guarantor score onto the band from 500 to 800: subtract a floor of 500 from `credit_score`, divide by a span of 300, multiply by 100, round half up to two decimal places, and then clamp the result to at least 0.00 and at most 100.00 — so a score at or below 500 contributes 0.00 and a score at or above 800 contributes 100.00. It, too, is identical under both variants.

The three rounded components are then weighted — liquidity at 0.45, balance sheet at 0.30 and credit at 0.25 — and that weighted sum is rounded half up to two decimal places exactly once, producing a weighted subtotal. Only after that does the **experience bonus** land. Under `STANDALONE` the bonus is 0.00. Under `PORTFOLIO_ADJUSTED` the bonus is 1.5 points for every hotel the entity already operates, counting at most 5 of them, with the product rounded half up to two decimal places — so an entity with three existing hotels earns 4.50 points and an entity with nine earns the maximum 7.50. The capacity score is the weighted subtotal plus the bonus, rounded half up to two decimal places and then capped at 100.00.

Each score is finally banded. A score of at least 75.00 bands as `STRONG`; a score of at least 55.00 but below 75.00 bands as `ADEQUATE`; anything below 55.00 bands as `INSUFFICIENT`. The two variants are stored side by side as `capacity_score_standalone` with its `capacity_band_standalone`, and `capacity_score_portfolio_adjusted` with its `capacity_band_portfolio_adjusted`, and reading one ownership entity returns all four so that a development officer can see the divergence before choosing a review basis.

Financial verification is not a one-time event. A `FranchiseDevelopmentManager` may record a re-verified profile at any time, replacing all four financial inputs — `liquid_assets_amount`, `net_worth_amount`, `credit_score` and `existing_units_count` — in a single call that answers 200 with the updated entity. Every such call advances `financial_profile_revision` by one and recomputes both scores and both bands.

Re-verification also fires a cross-entity cascade that is easy to miss and expensive to get wrong. Every application belonging to this ownership entity whose own `status` is `UNDER_REVIEW` and whose `financial_review_status` is `PASSED` is knocked from `PASSED` to `STALE`. Crucially, the stale application keeps its old snapshot: `capacity_score_at_review` and `capacity_band_at_review` retain the values captured at the earlier review, precisely so that the divergence between the frozen opinion and the live profile is observable. Applications whose review is `NOT_STARTED`, `FAILED` or already `STALE` are untouched, as are applications that have left `UNDER_REVIEW`. A `STALE` review blocks approval, license drafting and execution exactly as a `FAILED` one does, and the only way out is to run the financial review again on the updated profile.

An ownership entity's own `status` axis is driven from elsewhere entirely: it remains `PROSPECT` until the first license agreement drafted from one of its applications is executed, at which point the execution cascade flips it to `ACTIVE` and it stays there.

### 3.3. Application Intake, the Two Review Axes and the Revision Cycle

A `FranchiseDevelopmentManager` files a **conversion application** on behalf of an ownership entity by naming that entity as `owner_id` and the brand applied for as `brand_id`, then describing the property: `property_name` of 1 to 120 characters, a `market_code` of 3 to 8 characters restricted to uppercase A through Z and the digits 0 through 9, the property's grid position as `property_x_miles` and `property_y_miles`, each between -500.00 and 500.00 inclusive with exactly two decimal places, a `room_count` of at least 1, the property's `current_affiliation` describing what it flies today, a `building_age_years` between 0 and 150 inclusive recorded for the underwriting file, a `requested_term_years` between 5 and 30 inclusive naming the term the applicant asks for, and a `requested_conversion_date` in `YYYY-MM-DD` form naming the requested first day of brand operation. Filing returns 201, stamps `status` as `SUBMITTED`, both review axes as `NOT_STARTED`, `revision_round` as 0 and `sustained_claim_count` as 0, and advances the brand's `open_application_count` by one.

Applications can be read individually and listed with optional `owner_id`, `brand_id` and `status` filters, which is how a client discovers the applications belonging to a given ownership entity or brand.

Opening the review file advances the application from `SUBMITTED` to `UNDER_REVIEW` and is available only from `SUBMITTED`; attempting it from any other value of the primary axis is refused with `ERR_APPLICATION_STAGE_INVALID`. Because both `SUBMITTED` and `UNDER_REVIEW` count toward `open_application_count`, this transition leaves the brand's counter unchanged.

Once the file is open, two studies run **independently and in either order**: the financial capacity review and the market impact study. Neither is a precondition of the other, and neither advances the primary axis.

The **financial capacity review** is recorded by a `FranchiseDevelopmentManager` who chooses the basis by supplying `capacity_basis` — either `STANDALONE` or `PORTFOLIO_ADJUSTED` — and may attach `reviewer_notes`. The application must be `UNDER_REVIEW`, or the call is refused with `ERR_APPLICATION_STAGE_INVALID`. The outcome is never supplied by the caller: the system reads the ownership entity's score and band under the chosen variant, copies them onto the application as `capacity_score_at_review` and `capacity_band_at_review`, stores the chosen basis in `capacity_basis`, and sets `financial_review_status` to `PASSED` when the snapshot band is anything other than `INSUFFICIENT` and to `FAILED` when it is `INSUFFICIENT`. It also records the acting operator's identifier as `financial_reviewer_user_id`, which arms the segregation-of-duties rule of §2.10 on the eventual decision. The review may be re-run as often as needed while the application remains `UNDER_REVIEW`: `NOT_STARTED → PASSED`, `NOT_STARTED → FAILED`, `FAILED → PASSED`, `STALE → PASSED` and `STALE → FAILED` are all reachable this way, and every re-run re-snapshots the three capacity fields and overwrites `financial_reviewer_user_id` with the identifier of whoever ran it last. The only transition into `STALE` comes from outside — the re-verification cascade of §3.2.

The **revision cycle** is the primary axis's loop. A `FranchiseDevelopmentManager` may send an open application back to the applicant, which requires the application to be `UNDER_REVIEW`, moves it `UNDER_REVIEW → REVISION_REQUESTED`, and stores the supplied `revision_notes` on the application. Only the applicant can close the loop: the ownership entity named by `owner_id` resubmits with a `revision_response`, which requires the application to be `REVISION_REQUESTED` and moves it `REVISION_REQUESTED → UNDER_REVIEW`. A resubmission from any other ownership entity is refused with `ERR_FORBIDDEN_RESOURCE_OWNER`.

A resubmission is deliberately destructive of prior work, because the facts under review have changed. It advances `revision_round` by one, stores the `revision_response`, resets `financial_review_status` to `NOT_STARTED` and nulls `capacity_basis`, `capacity_score_at_review`, `capacity_band_at_review` and `financial_reviewer_user_id`; and it resets `impact_study_status` to `NOT_STARTED` and nulls `preliminary_impact_score`, `impact_unit_count_preliminary`, `base_impact_score`, `final_impact_score`, `impact_unit_count_final`, `encroachment_verdict` and `claim_window_closes_at`. Both studies must be run again from scratch. The cycle is unbounded — an application may lap between `UNDER_REVIEW` and `REVISION_REQUESTED` any number of times — and `revision_round` is the observable lap counter.

### 3.4. The Market Impact Study and Encroachment Claims

The market impact study answers one question: how much of the candidate property's business would come at the expense of hotels already flying the brand. It runs in two passes over the same arithmetic, and the difference between the passes is which existing units are admitted and what is added afterwards.

**Geometry.** For each candidate existing unit, the separation from the applicant property is the Euclidean distance on the market grid: take the difference between the unit's `x_miles` and the application's `property_x_miles`, take the difference between the unit's `y_miles` and the application's `property_y_miles`, square both differences, add them, take the square root, and round half up to two decimal places. A unit is admitted into the impact set when that distance is **less than or equal to** the brand's `protected_radius_miles`; the comparison is inclusive, and a unit sitting exactly on the radius is in the set even though, as the next paragraph shows, it contributes exactly 0.00 points.

**Per-unit contribution.** For each admitted unit, the proximity factor is the brand's `protected_radius_miles` less the unit's distance, divided by that same `protected_radius_miles`, rounded half up to **four** decimal places. The room-share factor is the application's `room_count` divided by the sum of the application's `room_count` and the unit's `room_count`, likewise rounded half up to four decimal places. The unit's contribution is 100.00 multiplied by the proximity factor multiplied by the room share, rounded half up to two decimal places.

**Aggregation.** The raw score is the sum of the per-unit contributions taken in ascending order of the units' `created_at`, with the completed sum rounded half up to two decimal places; the reported score is that raw sum capped at 100.00. When the impact set is empty the score is 0.00 and the unit count is 0 — never null.

**Membership differs between the passes.** Both passes consider only existing units whose `brand_id` matches the application's `brand_id`. The preliminary pass admits only units whose `status` is `OPERATING`. The final pass admits units whose `status` is `OPERATING` **or** `SUSPENDED`, on the reasoning that a suspended hotel is expected to return to service inside the license term. A `TERMINATED` unit is admitted by neither pass. A suspension recorded between the two passes therefore legitimately produces a final base score higher than the preliminary score over the identical property and brand.

**The preliminary pass** is run by a `BrandStandardsDirector`, who may attach `analyst_notes`. The application must be `UNDER_REVIEW`, or the call is refused with `ERR_APPLICATION_STAGE_INVALID`. The pass stores its result in `preliminary_impact_score` and the size of its admitted set in `impact_unit_count_preliminary`, moves `impact_study_status` from `NOT_STARTED` to `PRELIMINARY`, and opens the encroachment claim window by setting `claim_window_closes_at` to the logical clock's current instant plus 21 days. Running it again while the study is already `PRELIMINARY` is permitted and idempotent in shape but not in effect: it recomputes both preliminary figures against the current unit map and **moves `claim_window_closes_at` forward** to 21 days past the new instant, which reopens a window that had closed. It does not touch `sustained_claim_count` and does not disturb any claim already filed.

**Encroachment claims** are how the operators of nearby hotels object. A `BrandStandardsDirector` files a claim against an application by naming the aggrieved hotel as `existing_unit_id`, quantifying the harm as `claimed_revenue_loss_pct` between 0.00 and 100.00 inclusive with exactly two decimal places, and supplying a `narrative` of 1 to 2000 characters. Filing returns 201, computes and stores the claim's `distance_miles` from the aggrieved unit to the applicant property using the same rounded Euclidean distance defined above, stamps `status` as `FILED` and `penalty_points_applied` as 0.00, and records the acting operator as `filed_by_user_id`.

Three preconditions guard a filing. First, the application's primary axis must be `UNDER_REVIEW`, or else `APPROVED` — an already-approved application still accepts claims for as long as its window is open, which is the mechanism by which a late-arriving objection can undo a draft license. Any other value of the primary axis is refused with `ERR_APPLICATION_STAGE_INVALID`. Second, the claim window must still be open: the logical clock's current instant must be at or before `claim_window_closes_at`, with the boundary instant itself inside the window, and a filing at any later instant — or against an application whose `claim_window_closes_at` is still null because no preliminary pass has run — is refused with `ERR_CLAIM_WINDOW_CLOSED`. Third, the aggrieved hotel must be a live competitor: its `status` must be `OPERATING` and its `brand_id` must match the application's `brand_id`, and a claim naming a suspended unit, a terminated unit or a unit of another brand is refused with `ERR_UNIT_NOT_OPERATING`.

Claims can be read individually and listed with optional `application_id`, `existing_unit_id` and `status` filters.

**Resolving a claim** is also a `BrandStandardsDirector` action, taking an `outcome` of either `SUSTAIN` or `OVERRULE` together with mandatory `resolution_notes`. The claim must still be `FILED`; a second resolution of the same claim is refused with `ERR_CLAIM_NOT_FILED`. Either outcome stores the `resolution_notes` and stamps `resolved_at` with the logical clock's current instant.

The two outcomes then diverge sharply, and the asymmetry is the point.

Sustaining a claim moves it `FILED → SUSTAINED`, sets its `penalty_points_applied` to 7.50, and advances the application's `sustained_claim_count` by one. If the application's `impact_study_status` was already `FINAL`, sustaining knocks it **backwards** to `PRELIMINARY` and nulls `base_impact_score`, `final_impact_score`, `impact_unit_count_final` and `encroachment_verdict`, forcing the analyst to finalise again so that the new penalty is reflected. On top of that, every license agreement already drafted from that application whose `status` is `DRAFT` is moved to `VOIDED`; agreements that have reached `EXECUTED`, `OPEN`, `TERMINATION_PENDING`, `TERMINATED` or `VOIDED` are left exactly as they are. Neither `preliminary_impact_score` nor `impact_unit_count_preliminary` is disturbed, and `claim_window_closes_at` does not move.

Overruling a claim moves it `FILED → OVERRULED` and does nothing else at all. Its `penalty_points_applied` stays 0.00, `sustained_claim_count` does not move, `impact_study_status` is not knocked back, no score is nulled and no draft agreement is voided.

**The final pass** is run by a `BrandStandardsDirector`, again optionally attaching `analyst_notes`. It requires the application to be `UNDER_REVIEW` — otherwise `ERR_APPLICATION_STAGE_INVALID` — and requires `impact_study_status` to be exactly `PRELIMINARY`; running it when the study is `NOT_STARTED` or already `FINAL` is refused with `ERR_IMPACT_STUDY_STAGE_INVALID`. The pass recomputes the aggregate over the wider `OPERATING`-or-`SUSPENDED` set, stores that figure as `base_impact_score` and the size of the wider set as `impact_unit_count_final`, and then applies the claim penalty: `final_impact_score` is the `base_impact_score` plus 7.50 multiplied by `sustained_claim_count`, rounded half up to two decimal places and capped at 100.00. Note that the penalty is driven by the *count* of sustained claims, not by any claim's `claimed_revenue_loss_pct`, which is recorded for the file but never enters the arithmetic. The pass finally moves `impact_study_status` from `PRELIMINARY` to `FINAL` and writes the verdict into `encroachment_verdict`: a `final_impact_score` of at least 25.00 is `ENCROACHMENT_CONFIRMED`; a score of at least 12.00 but below 25.00 is `MITIGATION_REQUIRED`; anything below 12.00 is `CLEAR`. The verdict is what the approval gate reads, and the 12.00 threshold is read a second time at drafting, where it drives the marketing-fund surcharge.

### 3.5. The Approval Decision Gate

The decision is a `FranchiseDevelopmentManager` action carrying an `outcome` of either `APPROVE` or `DECLINE`, mandatory `decision_notes`, and an optional boolean `encroachment_waiver_granted` that defaults to false when omitted. The application must be `UNDER_REVIEW` in every case, or the call is refused with `ERR_APPLICATION_STAGE_INVALID`. Whatever the outcome, the operator who recorded the financial capacity review may not also record the decision: a match between the acting operator and `financial_reviewer_user_id` is refused with `ERR_SEGREGATION_OF_DUTIES`, as set out in §2.10.

Beyond the stage check and the duties check, **a decline has no preconditions whatsoever**. An application may be declined with `financial_review_status` still `NOT_STARTED`, with `impact_study_status` still `NOT_STARTED`, with claims still open, with a room count below the brand minimum, with a territory conflict outstanding and with a confirmed encroachment verdict on file. This asymmetry is deliberate: the gate exists to stop bad approvals, not to force the franchisor to complete studies on a deal it has already walked away from.

An approval, by contrast, must clear five further checks, evaluated in this fixed order so that the first applicable failure is the one reported.

1. **Territory-term conflict.** No existing unit of the same brand may hold an area-of-protection term that overlaps the term being requested. A unit is a candidate when its `brand_id` matches the application's `brand_id` and its rounded Euclidean distance from the property is less than or equal to the brand's `protected_radius_miles`. Its territory term is the **closed** interval from its `territory_start_date` to its `territory_end_date`. The requested term is the **closed** interval that begins on `requested_conversion_date` and ends on the date that is `requested_term_years` calendar years later with the same month and day. Two closed intervals conflict whenever they share at least one calendar day, so terms that merely touch at a single endpoint — a unit whose `territory_end_date` equals the `requested_conversion_date`, or one whose `territory_start_date` equals the last day of the requested term — **do** conflict. Any such candidate is refused with `ERR_TERRITORY_TERM_CONFLICT`. Note that this test uses the term the applicant asked for, not the term the license will eventually grant.
2. **Open encroachment claims.** No claim against the application may still be sitting at `FILED`. Every claim must have been resolved one way or the other; an unresolved claim is refused with `ERR_OPEN_ENCROACHMENT_CLAIMS`. Sustained and overruled claims are no obstacle.
3. **Brand room minimum.** The application's `room_count` must be at least the brand's `min_room_count`; a smaller property is refused with `ERR_ROOM_COUNT_BELOW_BRAND_MINIMUM`.
4. **Financial capacity review.** The application's `financial_review_status` must be exactly `PASSED`. `NOT_STARTED`, `FAILED` and `STALE` are all refused with `ERR_FINANCIAL_REVIEW_NOT_PASSED` — which means an approval that was viable a moment ago becomes unviable the instant the ownership entity's profile is re-verified, until the review is re-run.
5. **The impact study and its verdict.** The application's `impact_study_status` must be exactly `FINAL`; `NOT_STARTED` and `PRELIMINARY` are refused with `ERR_IMPACT_STUDY_NOT_FINAL`. Then, if `encroachment_verdict` is `ENCROACHMENT_CONFIRMED`, the approval is refused with `ERR_ENCROACHMENT_CONFIRMED` **unless** the caller supplied `encroachment_waiver_granted` as true, which is the franchisor's documented override. A verdict of `MITIGATION_REQUIRED` never blocks an approval and needs no waiver; it is priced instead, at drafting. A waiver flag supplied on an application whose verdict is `CLEAR` or `MITIGATION_REQUIRED` is stored but has no effect.

A decision that clears its checks answers 200 and writes the whole record at once: the primary axis moves `UNDER_REVIEW → APPROVED` on an approve and `UNDER_REVIEW → DECLINED` on a decline; `decision_outcome` records the chosen `outcome`; `decision_notes` and `encroachment_waiver_granted` are stored; `decision_user_id` records the acting operator and `decided_at` the logical clock's current instant. Because neither `APPROVED` nor `DECLINED` counts as an open application, both outcomes lower the brand's `open_application_count` by one. The decision is terminal on the primary axis: there is no transition out of `APPROVED` or `DECLINED`, so a declined application cannot be revived and an approved one cannot be sent back for revision.

### 3.6. License Drafting, Execution and the Onboarding Ladders

**Drafting.** A `FranchiseDevelopmentManager` drafts a license agreement from an approved application, supplying only the `effective_date` on which the license is to commence, in `YYYY-MM-DD` form. The application must be `APPROVED`, or the call is refused with `ERR_APPLICATION_STAGE_INVALID`, and its `financial_review_status` must still be `PASSED`, or the call is refused with `ERR_FINANCIAL_REVIEW_NOT_PASSED` — the second check exists because a re-verification cascade can turn a passed review stale after approval. Drafting returns 201. More than one draft may exist for the same application, which is exactly why sustaining a late claim voids drafts as a set rather than singly.

Every commercial term is derived at drafting and then **frozen for the life of the agreement**; later movement in the brand's rate card, in the ownership entity's finances or in the market picture never re-prices an existing license. The draft snapshots the brand's `code` into its own `brand_code` and snapshots the liquidated-damages cap of 36 months into `liquidated_damages_cap_months`.

The royalty rate starts from the brand's published `base_royalty_rate_pct` and is moved by two adjustments. The **conversion adjustment** prices the risk of the property's existing affiliation: 0.75 percentage points when `current_affiliation` is `COMPETITOR`, 0.25 when it is `INDEPENDENT`, and 0.00 when it is `OUR_BRAND`. The **capacity discount** rewards strong, experienced owners: 0.50 percentage points when `capacity_band_at_review` is `STRONG` **and** the ownership entity's `existing_units_count` is at least 3; 0.25 points when the band is `STRONG` but the entity operates fewer than 3 hotels; and 0.00 points for any other band. The agreement's `royalty_rate_pct` is then the base rate plus the conversion adjustment less the capacity discount, floored at 3.50 and only then capped at 7.00 — the floor is applied first and the ceiling second — with the clamped result rounded half up to two decimal places.

The marketing fund rate starts from the brand's published `marketing_fund_rate_pct` and takes an **impact surcharge** of 0.50 percentage points when the application's `final_impact_score` is at least 12.00, and 0.00 otherwise. Note that the surcharge is triggered by the score crossing 12.00, the same threshold that produces a `MITIGATION_REQUIRED` verdict, so a mitigation verdict is priced rather than blocked; a `CLEAR` application pays no surcharge, and a waived `ENCROACHMENT_CONFIRMED` application pays it. The agreement's `marketing_fund_rate_pct` is the brand rate plus the surcharge, capped at 3.00, rounded half up to two decimal places.

The granted term is the applicant's `requested_term_years` raised to a floor of 15 years and then capped at the brand's `standard_term_years`, and is stored as `term_years` — so a brand whose standard term is below 15 years caps the term below the floor, and the cap wins. The `expiry_date` is the `effective_date` advanced by `term_years` calendar years, keeping the same month and day, under the calendar-year convention of §2.4.

A fresh draft also initialises every operating axis and ledger figure: `status` is `DRAFT`, `compliance_status` is `COMPLIANT`, `training_status` is `NOT_STARTED`, `systems_status` is `NOT_STARTED`, `channel_status` is `NOT_CONNECTED`, `de_identification_status` is `NOT_REQUIRED` with a null `de_identification_deadline`, `de_identification_items_completed` is an empty array, `de_identification_breach_penalty` is 0.00, `consecutive_qa_failure_count` is 0, `revenue_periods` is an empty array, `reported_period_count` is 0, `royalty_fee_to_date`, `marketing_fund_contributed_total`, `reservation_fee_to_date` and `total_fees_assessed` are all 0.00, `transfer_consent_blocked` is false, `transfer_consent_count` is 0, `liquidated_damages_paid_amount` is 0.00, `post_termination_status` is `NOT_APPLICABLE`, and `termination_cause`, `liquidated_damages_formula`, `liquidated_damages_amount`, `remaining_term_months_at_termination`, `trailing_avg_monthly_fee`, `default_notice_issued_at`, `pip_cure_deadline`, `executed_at`, `opened_at`, `last_inspection_at`, `terminated_at` and `closed_out_at` are all null. The agreements drafted from one application can be listed from that application with an optional `status` filter, and any single agreement can be read directly.

**Execution.** A `FranchiseDevelopmentManager` executes a draft, supplying the version guard `expected_application_version` described in §2.7. The agreement must be `DRAFT`; a second execution, or an execution of a voided agreement, is refused with `ERR_AGREEMENT_NOT_DRAFT`. The application behind it must still be `APPROVED` (`ERR_APPLICATION_STAGE_INVALID`) and its `financial_review_status` must still be `PASSED` (`ERR_FINANCIAL_REVIEW_NOT_PASSED`).

Execution then applies a capacity test that is materially different from the one recorded at review. It reads the ownership entity's **live** band — `capacity_band_standalone` when the application's `capacity_basis` is `STANDALONE`, `capacity_band_portfolio_adjusted` when it is `PORTFOLIO_ADJUSTED` — and refuses with `ERR_OWNER_CAPACITY_INSUFFICIENT` when that live band is `INSUFFICIENT`. It deliberately does **not** consult the frozen `capacity_band_at_review`. An ownership entity that passed review as `ADEQUATE` and has since deteriorated to `INSUFFICIENT` cannot execute even though its snapshot still reads `ADEQUATE`; conversely, an entity that has improved since review executes on its improved standing. The version guard is checked last, after every other precondition.

A successful execution answers 200, moves the agreement `DRAFT → EXECUTED`, stamps `executed_at` with the logical clock's current instant, advances the application's `version` by one — which is what makes a stale guard detectable on a second attempt — and, when the ownership entity's `status` is still `PROSPECT`, flips it to `ACTIVE`.

**The three onboarding ladders.** An executed agreement carries three independent readiness axes, advanced one rung at a time by a `FranchiseDevelopmentManager` who names the axis in `track` — `TRAINING`, `SYSTEMS` or `CHANNEL` — and the target rung in `to_status`. The agreement must be `EXECUTED`, or the call is refused with `ERR_AGREEMENT_NOT_EXECUTED`. Exactly five rungs are climbable, each with its own prerequisite drawn from the *other* axes:

- `TRAINING` to `COMPLETED` has no prerequisite and may be climbed at any time after execution.
- `SYSTEMS` to `PROVISIONED` requires `training_status` to be `COMPLETED`.
- `SYSTEMS` to `VALIDATED` requires `systems_status` to be `PROVISIONED`.
- `CHANNEL` to `TESTING` requires `systems_status` to be `VALIDATED`.
- `CHANNEL` to `CONNECTED` requires `channel_status` to be `TESTING`.

Any request whose named rung is not one of those five, or whose prerequisite is unmet, is refused with `ERR_ONBOARDING_SEQUENCE_INVALID` — so systems cannot be provisioned before training is complete, the channel cannot be tested before systems are validated, and no rung may be skipped. `NOT_STARTED`, `NOT_CONNECTED` and `SUSPENDED` are never valid targets on this operation; a suspended channel is restored by the compliance machinery of §3.8, not by climbing a ladder.

**Opening the hotel.** A `BrandStandardsDirector` opens the hotel for business once construction and readiness are both done. The agreement must be `EXECUTED`, or the call is refused with `ERR_AGREEMENT_NOT_EXECUTED`. Five further conditions are then checked in this order:

1. Every scope line on the agreement's improvement plan whose `category` is `LIFE_SAFETY` must be `VERIFIED`; any life-safety line still `PENDING`, `SUBMITTED` or `OVERDUE` is refused with `ERR_LIFE_SAFETY_ITEM_OPEN`.
2. Every scope line whose `priority` is `CRITICAL` must be `VERIFIED`; any that is not is refused with `ERR_CRITICAL_PIP_ITEMS_OPEN`.
3. `training_status` must be `COMPLETED` and `systems_status` must be `VALIDATED`; otherwise `ERR_ONBOARDING_INCOMPLETE`.
4. `channel_status` must be `CONNECTED`; otherwise `ERR_CHANNEL_NOT_CONNECTED`.
5. The agreement must have an improvement plan whose `status` is `ACCEPTED`, `IN_PROGRESS` or `COMPLETED`; a missing plan, or a plan still `SCOPED`, `DEFAULTED` or `SUSPENDED`, is refused with `ERR_PIP_NOT_ACCEPTED`.

Note that opening does **not** require every scope line to be verified — only the life-safety and critical ones. A hotel may open with minor guestroom work still outstanding, and that work then runs against its deadlines while the hotel trades. A successful opening answers 200, moves the agreement `EXECUTED → OPEN` and stamps `opened_at`.

### 3.7. The Property Improvement Plan: Scope, Cost Allocation and Deadlines

A **property improvement plan** is the construction programme that brings a converting hotel up to brand standard. A `BrandStandardsDirector` opens one against an executed agreement — the agreement must be `EXECUTED`, or the call is refused with `ERR_AGREEMENT_NOT_EXECUTED` — supplying `scope_notes` of 1 to 2000 characters that summarise the inspection findings. Creation returns 201, records the parent agreement as `agreement_id`, stamps `status` as `SCOPED`, and initialises every counter and every money figure: `items_total_count`, `items_pending_count`, `items_submitted_count`, `items_verified_count` and `items_overdue_count` are all 0; `total_estimated_cost`, `cost_per_room`, `franchisor_key_money`, `owner_net_cost` and `owner_net_cost_per_room` are all 0.00; `key_money_pct` is 0; `escalation_required` is false; `extension_granted_days_total` is 0; and `accepted_at`, `overall_deadline` and `acknowledgement` are null. At most one plan exists per agreement. The plans of an agreement can be listed from that agreement, and a plan can also be read directly.

**Scope lines.** While the plan is still `SCOPED`, a `BrandStandardsDirector` adds scope lines to it, each naming a `category`, a `priority`, a `description` of 1 to 500 characters and an `estimated_cost` in US dollars of at least 0.00 with exactly two decimal places. A line may be added only to a plan whose `status` is `SCOPED`; once the plan has been accepted its scope is closed, and a further line is refused with `ERR_PIP_NOT_SCOPED`. Adding a line returns 201, records the parent plan as `pip_id`, stamps the line's `status` as `PENDING` and its `extension_status` as `NONE`, sets `extension_requested_days`, `extension_granted_days_total`, `extension_request_count` and `rejection_count` all to 0, leaves `base_due_date`, `due_date`, `extension_reason`, `completion_evidence`, `completed_at`, `verified_at` and `overdue_at` null, advances the plan's `items_total_count` and `items_pending_count` each by one, and recomputes the plan's `total_estimated_cost` as the sum of every line's `estimated_cost` rounded half up to two decimal places. Note that deadlines are *not* set when a line is created — a line has no due date until the plan is accepted, because the whole schedule is anchored on the acceptance instant. The lines of a plan can be listed from that plan with an optional `status` filter.

**Acceptance and cost allocation.** The applicant ownership entity accepts the plan by supplying an `acknowledgement` string, which is stored on the plan verbatim. The plan must be `SCOPED`, or the call is refused with `ERR_PIP_NOT_SCOPED`; it must carry at least one scope line, since a plan with nothing in it cannot be priced, and an empty plan is refused as a conflict with HTTP 409; the agreement behind it must still be `EXECUTED`; and the acting ownership entity must be the one behind the agreement, or the call is refused with `ERR_FORBIDDEN_RESOURCE_OWNER`. Acceptance answers 200 and does four things at once: it stamps `accepted_at` with the logical clock's current instant, allocates the cost, sets a deadline on every scope line, and moves the plan `SCOPED → ACCEPTED`.

Cost allocation runs in a **pinned order**, and the order is the whole substance of the rule. First, the gross `total_estimated_cost` is divided by the `room_count` of the application behind the plan's agreement and rounded half up to two decimal places, giving `cost_per_room`. Second, the key money band is chosen **from that gross per-room figure**: `key_money_pct` is 10 when `cost_per_room` is at least 25,000.00, 6 when it is at least 12,000.00 but below 25,000.00, and 0 otherwise. Choosing the band from the net figure instead would be circular — the net figure depends on the band — and is wrong. Third, `franchisor_key_money` is the gross `total_estimated_cost` multiplied by `key_money_pct`, divided by 100, rounded half up to two decimal places, and then capped at 250,000.00, so the franchisor's contribution never exceeds a quarter of a million dollars however large the programme. Fourth, `owner_net_cost` is the gross `total_estimated_cost` less `franchisor_key_money`, an exact subtraction of two already-rounded figures. Fifth, `owner_net_cost_per_room` is `owner_net_cost` divided by the same application `room_count`, rounded half up to two decimal places. Finally, `escalation_required` is true when `owner_net_cost_per_room` is **strictly greater** than 20,000.00 and false otherwise, flagging a programme that needs franchisor executive sign-off; a net per-room cost of exactly 20,000.00 does not escalate. Every line on the plan enters the gross total regardless of its `status`, and all six figures are frozen at acceptance — adding cost later is impossible because the scope is closed.

**Deadlines.** Each scope line's allowance is the **smaller** of two independent budgets: a priority budget of 90 days for `CRITICAL`, 180 days for `MAJOR` and 270 days for `MINOR`; and a category budget of 45 days for `LIFE_SAFETY`, 120 for `TECHNOLOGY`, 180 for `FOOD_BEVERAGE`, 210 for `GUESTROOM` and 240 for `EXTERIOR`. Taking the minimum means a `MINOR` life-safety line still gets only 45 days, and a `CRITICAL` exterior line still gets only 90. The line's `base_due_date` is the plan's `accepted_at` advanced by that allowance in whole days, preserving the time of day exactly as §2.4 requires, and its `due_date` is `base_due_date` advanced by the line's `extension_granted_days_total` — which is 0 at acceptance, so the two coincide until an extension is granted. The plan's `overall_deadline` is the latest `due_date` across all of its lines, and it is recomputed whenever any line's `due_date` moves. Despite the `_date` suffix in their names, `base_due_date`, `due_date` and `overall_deadline` are — whenever they are non-null — full ISO 8601 UTC instants rendered in the same three-fractional-digit format as `created_at` (for example `2027-04-03T00:00:00.000Z`), never bare `YYYY-MM-DD` calendar dates, and every comparison against them described in this section is an instant comparison.

**Reporting work complete.** The ownership entity reports a line finished by supplying `completion_evidence`. The line's `status` must be `PENDING`; a line already `SUBMITTED`, `VERIFIED` or `OVERDUE` is refused with `ERR_PIP_ITEM_STAGE_INVALID`. The plan the line belongs to must be `ACCEPTED` or `IN_PROGRESS`; a plan still `SCOPED`, or one that is `DEFAULTED`, `SUSPENDED` or `COMPLETED`, is refused as a plan-state conflict with HTTP 409. And the logical clock's current instant must be at or before the line's `due_date` — the boundary instant itself is inside the window — with a later submission refused as `ERR_PIP_ITEM_PAST_DUE`. A successful report answers 200, moves the line `PENDING → SUBMITTED`, stores the `completion_evidence`, stamps `completed_at`, moves one unit from the plan's `items_pending_count` to its `items_submitted_count`, and — on the first such report against a plan still sitting at `ACCEPTED` — moves the plan `ACCEPTED → IN_PROGRESS`.

**Verification.** A `BrandStandardsDirector` inspects submitted work, supplying an `outcome` of either `VERIFY` or `REJECT` together with mandatory `verification_notes`. The line's `status` must be `SUBMITTED`, or the call is refused with `ERR_PIP_ITEM_STAGE_INVALID`. A `VERIFY` moves the line `SUBMITTED → VERIFIED`, stamps `verified_at`, and moves one unit from the plan's `items_submitted_count` to its `items_verified_count`; when that leaves `items_verified_count` equal to `items_total_count`, the plan moves to `COMPLETED`. A `REJECT` moves the line `SUBMITTED → PENDING`, advances its `rejection_count` by one, and moves one unit from `items_submitted_count` back to `items_pending_count`; the line's `due_date` is untouched, so a rejection late in the allowance can leave the ownership entity with very little time and no automatic relief. There is no limit on rejections.

**Extensions.** The extension machinery is a second, independent axis on each scope line, and it is the most heavily conditioned part of the plan. The ownership entity requests relief by supplying `requested_days` and a `reason`. Four preconditions apply. The line's `status` must be `PENDING`, `SUBMITTED` or `OVERDUE`; a `VERIFIED` line is refused with `ERR_PIP_ITEM_STAGE_INVALID`. The line's `category` must not be `LIFE_SAFETY`: life-safety work is never extendable, and such a request is refused with `ERR_LIFE_SAFETY_NOT_EXTENDABLE` regardless of how much extension budget remains. The line's `extension_request_count` must be below 2 — at most two requests per line, granted or denied — with a third refused as `ERR_EXTENSION_LIMIT_EXCEEDED`. And an `OVERDUE` line may be extended **only** while the plan's `status` is `DEFAULTED`; requesting relief for an overdue line on a plan that is merely `ACCEPTED` or `IN_PROGRESS` is refused with `ERR_EXTENSION_WINDOW_CLOSED`. A valid request answers 200, sets `extension_status` to `PENDING`, stores `requested_days` in `extension_requested_days` and the `reason` in `extension_reason`, and advances `extension_request_count` by one. Because a second request is allowed, `GRANTED → PENDING` and `DENIED → PENDING` are both reachable on the extension axis, as is `NONE → PENDING`.

A `BrandStandardsDirector` then decides, supplying an `outcome` of either `GRANT` or `DENY` and optionally `decision_notes`. The line's `extension_status` must be `PENDING`, or the call is refused with `ERR_EXTENSION_NOT_PENDING`. A `DENY` moves the axis `PENDING → DENIED` and changes nothing else: the `due_date` does not move and no budget is consumed.

A `GRANT` moves the axis `PENDING → GRANTED` and awards a number of days that is clamped against **three** limits at once. The awarded days are the smallest of: the `extension_requested_days`; 60 less the line's own `extension_granted_days_total`, since no single line may accumulate more than 60 days of relief; and 120 less the plan's `extension_granted_days_total`, since the whole programme draws on a shared pool of 120 days. The result is then floored at 0, so an exhausted budget awards 0 days rather than clawing days back. The awarded days are added to the line's `extension_granted_days_total` and to the plan's `extension_granted_days_total`, the line's `due_date` is recomputed as its `base_due_date` advanced by the line's new cumulative total, and the plan's `overall_deadline` is recomputed as the latest `due_date` across its lines.

A grant can also unwind a default. If the line was `OVERDUE` and its recomputed `due_date` is at or after the logical clock's current instant, the line returns `OVERDUE → PENDING`, its `overdue_at` is cleared, and one unit moves from the plan's `items_overdue_count` back to its `items_pending_count`. If that leaves no `OVERDUE` line whose `priority` is `CRITICAL` or whose `category` is `LIFE_SAFETY`, the plan recovers `DEFAULTED → IN_PROGRESS`. Note carefully what recovery does **not** do: the agreement's `compliance_status` stays where the default put it. A `DEFAULT_NOTICE` raised by a defaulting plan is cleared only by a successful quality-assurance cure, or never — restoring the plan does not restore contractual compliance, and `transfer_consent_blocked` therefore remains true.

**The compliance sweep.** Deadlines do not fire by themselves; there are no background timers. A `BrandStandardsDirector` runs a sweep over a plan, which requires the plan's `status` to be `ACCEPTED`, `IN_PROGRESS` or `DEFAULTED` — a `SCOPED`, `COMPLETED` or `SUSPENDED` plan is refused with `ERR_PIP_NOT_SCOPED`. The sweep answers 200 and takes every line whose `status` is `PENDING` or `SUBMITTED` and whose `due_date` is **strictly before** the logical clock's current instant, moves each of them to `OVERDUE`, stamps each one's `overdue_at` with the current instant, and recomputes the plan's four per-status counters. A line whose `due_date` is exactly the current instant is not yet overdue. `VERIFIED` lines and lines already `OVERDUE` are unaffected.

If at least one of the newly overdue lines has `priority` `CRITICAL` or `category` `LIFE_SAFETY`, the sweep escalates and the cascade reaches three other resource families. The plan moves to `DEFAULTED`, whatever it was before. The agreement's `compliance_status` moves to `DEFAULT_NOTICE` — reachable from `COMPLIANT` and from `CURE_PERIOD` alike — its `default_notice_issued_at` is stamped with the current instant, its `pip_cure_deadline` is set to the current instant advanced by 30 days, and its `transfer_consent_blocked` becomes true. And every consent request against that agreement whose `status` is still `SUBMITTED` is refused: each moves `SUBMITTED → REFUSED`, takes `refusal_reason` `DEFAULT_NOTICE` and a `decided_at` of the current instant, and — because no human decided it — keeps a null `decision_user_id`, which is the observable signature of a cascade-driven refusal. If none of the newly overdue lines is critical or life-safety, none of that happens: the lines go overdue, the counters move, and the plan and agreement stay where they were.

Whatever else changes, the plan's counter invariant always holds: `items_pending_count` plus `items_submitted_count` plus `items_verified_count` plus `items_overdue_count` equals `items_total_count`.

### 3.8. Operating Years: The Fee Ledger and Quality Assurance

An open hotel does two things that the franchisor cares about: it pays fees on the revenue it earns, and it is inspected against brand standard. Both are only available while the agreement's `status` is `OPEN`; an attempt to file a revenue report or score an inspection against an agreement that is `DRAFT`, `EXECUTED`, `TERMINATION_PENDING`, `TERMINATED` or `VOIDED` is refused with `ERR_AGREEMENT_NOT_OPEN`.

**Revenue reporting.** The ownership entity files a monthly report by supplying `period_month`, the accounting month in `YYYY-MM` form — exactly 7 characters: a four-digit year, a hyphen, and a two-digit month from `01` to `12` — a `gross_room_revenue` in US dollars of at least 0.00 with exactly two decimal places, and an optional boolean `correction` that defaults to false. A report answers 200 with the updated agreement.

The ledger is **append-only**, and `correction` decides whether an append is a first filing or a restatement. When `correction` is false, no surviving entry may already exist for that `period_month`; a second ordinary filing for the same month is refused with `ERR_DUPLICATE_REVENUE_PERIOD`. When `correction` is true, a surviving entry for that `period_month` **must** already exist; a correction for a month that was never reported is refused with the same `ERR_DUPLICATE_REVENUE_PERIOD`. A correction never edits history: it appends a new entry for the same month and flips the previously surviving entry's `superseded` flag to true. Superseded entries remain visible in the ledger forever and are excluded from every sum and every count.

Each entry in the agreement's `revenue_periods` array carries the `period_month`, the reported `gross_room_revenue`, the three computed fee components `royalty_fee`, `marketing_fee` and `reservation_fee`, their sum as `period_total_fee`, and the `superseded` flag, which is false when the entry is appended. The array is ordered by entry creation time ascending, so a correction always appears after the entry it supersedes.

Fees are assessed on a **three-slice progressive schedule** applied to the reported month's revenue. The first slice is the revenue up to 200,000.00 US dollars. The second slice is the revenue between 200,000.00 and 500,000.00 — that is, the reported revenue capped at 500,000.00, less 200,000.00, floored at 0.00. The third slice is the revenue above 500,000.00 — the reported revenue less 500,000.00, floored at 0.00. The first slice is charged at the agreement's frozen `royalty_rate_pct`; the second at that rate plus 0.50 percentage points; the third at that rate plus 1.00 percentage point. The `royalty_fee` is the sum of the three slice charges, and the order of operations is pinned: each slice's charge is computed as the slice base multiplied by its rate divided by 100 and **rounded half up to two decimal places on its own**, and only then are the three rounded charges added. Computing one unrounded total and rounding once at the end is a different number and is wrong.

The other two components are flat. The `marketing_fee` is the reported revenue multiplied by the agreement's frozen `marketing_fund_rate_pct`, divided by 100, rounded half up to two decimal places. The `reservation_fee` is the reported revenue multiplied by a fixed reservation-system rate of 1.75 percent, divided by 100, rounded half up to two decimal places — this rate is a system constant and appears nowhere on the brand or the agreement. The entry's `period_total_fee` is the exact sum of the three already-rounded components and is not re-rounded.

Four running totals are then recomputed from the surviving entries only, each as the exact sum of already-rounded per-period amounts taken in ascending entry order and never re-rounded: `royalty_fee_to_date` over the entries' `royalty_fee`, `marketing_fund_contributed_total` over their `marketing_fee`, `reservation_fee_to_date` over their `reservation_fee`, and `total_fees_assessed`, which must always equal the sum of the other three. `reported_period_count` is the number of surviving entries — so a correction leaves the count unchanged, because it adds one entry and supersedes one. A fee summary can be read off the agreement at any time, returning `agreement_id`, the two frozen rates `royalty_rate_pct` and `marketing_fund_rate_pct`, the `reported_period_count`, and all four totals.

**Quality assurance inspections.** A `QaInspector` scores an inspection against an open agreement by supplying six observations: `cleanliness_score`, `condition_score`, `brand_standard_score` and `guest_experience_score`, each an integer from 0 to 100 inclusive; `critical_defect_count`, an integer from 0 to 20 inclusive counting the critical brand-standard defects found; and `life_safety_defect`, a boolean stating whether any life-safety defect was found. Creation returns 201, stamps the inspection's `inspection_at` with the logical clock's current instant and its `inspector_user_id` with the acting operator, and updates the agreement's `last_inspection_at`, which always reflects the agreement's most recent inspection ordered by `inspection_at` descending and, for ties, by creation time descending.

Inspections are rate-limited to protect franchisees from harassment: the logical clock's current instant must be at or after the agreement's `last_inspection_at` advanced by 90 days. The boundary is permitted — an inspection exactly 90 days after the previous one is allowed — while one instant earlier is refused with `ERR_INSPECTION_TOO_SOON`. An agreement's first inspection is unconstrained, because `last_inspection_at` is still null.

The score is a weighted composite followed by a defect penalty. The `weighted_score` is `cleanliness_score` at weight 0.30, plus `condition_score` at 0.25, plus `brand_standard_score` at 0.30, plus `guest_experience_score` at 0.15, with the whole sum rounded half up to two decimal places once. The `total_score` is the `weighted_score` less 5.00 points for each critical defect found, floored at 0.00 and rounded half up to two decimal places.

The `grade` is then assigned, and one rule outranks the arithmetic entirely: if `life_safety_defect` is true, the `grade` is `FAIL` no matter how high the `total_score` — a hotel scoring 100.00 with a life-safety defect fails. Otherwise a `total_score` of at least 85.00 grades `PASS`, at least 70.00 but below 85.00 grades `CONDITIONAL`, and below 70.00 grades `FAIL`.

The grade determines the cure window and the inspection's own status axis. A `PASS` sets `cure_period_days` and `cure_deadline` to null and creates the inspection directly at `CLOSED`; there is nothing to cure, and no cure may be submitted against it. A `CONDITIONAL` sets `cure_period_days` to 60, a `FAIL` sets it to 30, and in both cases the `cure_deadline` is the inspection's `inspection_at` advanced by that many days and the inspection is created at `CURE_PENDING`. A cure submitted at exactly the `cure_deadline` instant is inside the window.

A `CONDITIONAL` or `FAIL` grade also moves the agreement's `compliance_status` to `CURE_PERIOD`, whether it was `COMPLIANT` or `DEFAULT_NOTICE` beforehand. Coming from `DEFAULT_NOTICE`, `consecutive_qa_failure_count` is left exactly as it stands — the running tally of consecutive failures is not reset by the arrival of a new failing inspection, only by a successful cure. A `PASS` grade does not touch `compliance_status` at all: a passing inspection while the agreement sits in `CURE_PERIOD` or `DEFAULT_NOTICE` does not clear that state, because only the cure review can. The inspections of an agreement can be listed from it with an optional `grade` filter.

**Curing an inspection.** The ownership entity submits remediation evidence by supplying `cure_evidence`. The inspection's `status` must be `CURE_PENDING`, or the call is refused with `ERR_INSPECTION_STAGE_INVALID` — which is also what a submission against a `CLOSED` passing inspection receives. The logical clock's current instant must be at or before the `cure_deadline`, with the boundary inside; a later submission is refused with `ERR_CURE_WINDOW_EXPIRED`. A valid submission answers 200, moves the inspection `CURE_PENDING → CURE_SUBMITTED`, stores the `cure_evidence` and stamps `cure_submitted_at`.

**Reviewing the cure.** A `QaInspector` reviews the evidence, supplying an `outcome` of either `PASS` or `FAIL` together with mandatory `review_notes`. The inspection's `status` must be `CURE_SUBMITTED`, or the call is refused with `ERR_INSPECTION_STAGE_INVALID`. The reviewing operator may not be the operator who scored the inspection: a match against `inspector_user_id` is refused with `ERR_SEGREGATION_OF_DUTIES`. Either outcome stores the `review_notes`, stamps `cure_reviewed_at` and records the acting operator as `cure_reviewer_user_id`.

A `PASS` moves the inspection `CURE_SUBMITTED → CURE_PASSED` and rehabilitates the agreement: `compliance_status` returns to `COMPLIANT`, `consecutive_qa_failure_count` resets to 0, `transfer_consent_blocked` becomes false, and a `channel_status` of `SUSPENDED` is restored to `CONNECTED` provided the agreement is still `OPEN`. This is the only route back to `COMPLIANT` from either `CURE_PERIOD` or the compliance side-effects of a defaulting improvement plan.

A `FAIL` moves the inspection `CURE_SUBMITTED → CURE_FAILED` and advances the agreement's `consecutive_qa_failure_count` by one. If the new count is below 3, `compliance_status` moves to `DEFAULT_NOTICE` and `default_notice_issued_at` is stamped with the current instant; `pip_cure_deadline` is *not* set, because no improvement-plan deadline was missed. If the new count reaches 3, `compliance_status` moves instead to `TERMINATION_ELIGIBLE`, which is the only state from which a quality-assurance termination may be taken. In both cases `transfer_consent_blocked` becomes true and a `channel_status` of `CONNECTED` is suspended to `SUSPENDED`, cutting the hotel off from the franchisor's reservation channels while it remains out of standard.

### 3.9. Consent, Termination and Post-Termination Obligations

**Consent requests.** A franchisee cannot sell the hotel, restructure its ownership or refinance the property without the franchisor's consent. The ownership entity files a request by naming a `request_type` of `TRANSFER`, `CHANGE_OF_CONTROL` or `REFINANCE`, and the payload it must carry depends on the type. A `TRANSFER` or a `CHANGE_OF_CONTROL` must name the incoming ownership entity as `proposed_owner_id` and must **not** carry `lender_name`. A `REFINANCE` must carry a `lender_name` of 1 to 160 characters and must **not** name a `proposed_owner_id`. Supplying the wrong combination for the declared type is a malformed request and is refused with `ERR_INVALID_REQUEST`.

The agreement must be `EXECUTED` or `OPEN` — consent is meaningful from the moment the license is signed, before the hotel opens — and any other agreement status is refused with `ERR_AGREEMENT_NOT_OPEN`. Consent may not even be sought while the franchisee is in default: a `transfer_consent_blocked` of true, which is the case whenever `compliance_status` is `DEFAULT_NOTICE` or `TERMINATION_ELIGIBLE`, is refused with `ERR_TRANSFER_BLOCKED_BY_DEFAULT`. For a `TRANSFER` or `CHANGE_OF_CONTROL`, the incoming entity must itself be creditworthy: its live `capacity_band_standalone` must not be `INSUFFICIENT`, or the request is refused with `ERR_PROPOSED_OWNER_CAPACITY_INSUFFICIENT`. The standalone variant is always the one read here — a proposed owner is assessed on its own balance sheet, not on a portfolio adjustment.

Filing returns 201, stamps `status` as `SUBMITTED`, records the acting entity as `submitted_by_user_id`, snapshots the incoming entity's `capacity_band_standalone` into `proposed_owner_capacity_band` (null for a `REFINANCE`, which has no incoming owner), and prices the consent. The base fee is the `room_count` of the application behind the agreement multiplied by 750.00 US dollars per room, rounded half up to two decimal places, and then raised to a floor of 75,000.00 — so any hotel with fewer than 100 keys pays the floor. From that base, `transfer_fee` is the base fee itself for a `TRANSFER`; the base fee halved and rounded half up to two decimal places for a `CHANGE_OF_CONTROL`, since no new franchisee is being underwritten; and a flat 15,000.00 for a `REFINANCE`, which ignores the base fee entirely. A `non_compliance_surcharge` of 25,000.00 is added whenever the agreement's `compliance_status` is anything other than `COMPLIANT`, and 0.00 when it is `COMPLIANT`. The `total_consent_fee` is the exact sum of `transfer_fee` and `non_compliance_surcharge`. Note that the surcharge can only ever apply on a `CURE_PERIOD` agreement, since the other two non-compliant states block the filing outright. All three fee figures are frozen at filing and are never re-priced by the decision.

Requests can be read individually and listed with optional `agreement_id`, `proposed_owner_id` and `status` filters.

**Deciding a consent request.** A `FranchiseDevelopmentManager` decides, supplying an `outcome` of either `CONSENT` or `REFUSE`, the version guard `expected_agreement_version` described in §2.7, and optionally `decision_notes`. The request's `status` must be `SUBMITTED`; a second decision is refused with `ERR_TRANSFER_REQUEST_NOT_SUBMITTED`. The agreement's `transfer_consent_blocked` must still be false — a default that arrived after the request was filed blocks the decision too, with the same `ERR_TRANSFER_BLOCKED_BY_DEFAULT` — and for a `CONSENT` on a `TRANSFER` or `CHANGE_OF_CONTROL` the snapshot `proposed_owner_capacity_band` must not be `INSUFFICIENT`, or the decision is refused with `ERR_PROPOSED_OWNER_CAPACITY_INSUFFICIENT`. The version guard is checked last.

A `CONSENT` moves the request `SUBMITTED → CONSENTED` and advances the agreement's `transfer_consent_count` by one. A `REFUSE` moves it `SUBMITTED → REFUSED` with `refusal_reason` `DISCRETION` — the franchisor's reserved discretion, distinct from the `DEFAULT_NOTICE` reason that only the improvement-plan cascade writes. Both outcomes record `decision_user_id`, stamp `decided_at`, store the `decision_notes`, and advance the agreement's `version` by one so that a concurrent decision attempt with the old guard value is detected.

**Termination.** A `BrandStandardsDirector` terminates an open agreement by naming a `cause` of `FOR_CAUSE_QA`, `FOR_CAUSE_PIP` or `MUTUAL` and supplying mandatory `termination_notes`. The agreement must be `OPEN`, or the call is refused with `ERR_AGREEMENT_NOT_OPEN`. Each cause carries its own compliance precondition, and a cause whose precondition is unmet is refused with `ERR_TERMINATION_NOT_ELIGIBLE`: `FOR_CAUSE_QA` requires `compliance_status` to be exactly `TERMINATION_ELIGIBLE`, which in practice means three consecutive failed cures; `FOR_CAUSE_PIP` requires it to be either `DEFAULT_NOTICE` or `TERMINATION_ELIGIBLE`, so a single defaulting critical or life-safety scope line suffices; and `MUTUAL` has no compliance precondition at all — a fully compliant hotel may be terminated by agreement.

Termination answers 200 and does a great deal at once. The agreement moves `OPEN → TERMINATION_PENDING`, `termination_cause` records the `cause`, and `terminated_at` is stamped with the logical clock's current instant. The `liquidated_damages_formula` is selected from the cause: `CONTRACTUAL_MULTIPLE` for `FOR_CAUSE_QA` and `FOR_CAUSE_PIP`, and `DISCOUNTED_PV` for `MUTUAL`, on the reasoning that a defaulting franchisee owes the full contractual multiple while a consensual exit owes only the present value of the franchisor's lost stream. De-identification is armed: `de_identification_status` moves `NOT_REQUIRED → PENDING` and `de_identification_deadline` is set to `terminated_at` advanced by 30 days. `post_termination_status` moves `NOT_APPLICABLE → OPEN`. A `channel_status` of `CONNECTED` is suspended to `SUSPENDED`. And an improvement plan whose `status` is `ACCEPTED`, `IN_PROGRESS` or `DEFAULTED` moves to `SUSPENDED`, since there is no longer a brand to improve toward; a plan already `COMPLETED` or `SCOPED` is left alone.

Liquidated damages are computed and frozen at this moment. The basis is the sum, over the surviving entries of `revenue_periods` only, of each entry's `royalty_fee` plus its `marketing_fee`; `reservation_fee` is **excluded**, because the reservation system is a pass-through cost rather than franchisor profit. The `trailing_avg_monthly_fee` is that basis divided by `reported_period_count`, rounded half up to two decimal places — and is 0.00 when `reported_period_count` is 0, a hotel that opened and terminated without ever reporting revenue. The `remaining_term_months_at_termination` is a whole-month span computed on month indices under the convention of §2.4: the expiry year multiplied by 12 plus the expiry month, less the termination year multiplied by 12 plus the termination month, floored at 0, ignoring the day of month entirely. That span is then capped at the agreement's frozen `liquidated_damages_cap_months` of 36 to give the number of months actually charged.

Under `CONTRACTUAL_MULTIPLE`, the `liquidated_damages_amount` is the `trailing_avg_monthly_fee` multiplied by the capped month count, rounded half up to two decimal places. Under `DISCOUNTED_PV`, it is the sum of one discounted term for each month from the first through the capped count: for month *k*, the `trailing_avg_monthly_fee` divided by 1.0050 raised to the power *k*, with **each term rounded half up to two decimal places before it enters the sum**, and the terms added in ascending order of *k*. The monthly discount rate is 0.50 percent, that is a rate of 0.0050 expressed as a fraction, so the divisor for the first month is 1.0050, for the second month 1.0050 squared, and so on. Summing unrounded terms and rounding once at the end produces a different figure and is wrong. When the capped month count is 0, both formulas yield 0.00.

**De-identification.** The former franchisee certifies that the property no longer looks or trades like the brand, supplying `items_completed` as an array of de-identification codes. The agreement must be `TERMINATION_PENDING`, or the call is refused with `ERR_AGREEMENT_NOT_TERMINATION_PENDING`. The certification must be complete: the array must contain all five of `SIGNAGE`, `INTERIOR_BRANDING`, `DIGITAL_LISTINGS`, `LINENS_AND_COLLATERAL` and `RESERVATION_CODES`, and a partial certification is refused with `ERR_DEIDENTIFICATION_INCOMPLETE`. A complete certification answers 200 and stores the codes in `de_identification_items_completed`. Timeliness then decides the outcome: submitted at or before the `de_identification_deadline`, `de_identification_status` moves `PENDING → SUBMITTED` and `de_identification_breach_penalty` stays 0.00; submitted after the deadline, it moves `PENDING → BREACHED` and `de_identification_breach_penalty` is set to 50,000.00. Either way the obligation is discharged in substance, and the only difference is the money owed.

**Close-out.** A `BrandStandardsDirector` closes the post-termination file, supplying a `liquidated_damages_settlement_amount` in US dollars and a boolean `de_identification_verified`. The agreement must be `TERMINATION_PENDING`, or the call is refused with `ERR_AGREEMENT_NOT_TERMINATION_PENDING`. Three obligations must be discharged together, and failing any of them is refused with `ERR_POST_TERMINATION_OBLIGATIONS_OPEN`: `de_identification_status` must be `SUBMITTED` or `BREACHED`, so a franchisee who never certified cannot be released; `de_identification_verified` must be true, recording the franchisor's own physical verification; and the `liquidated_damages_settlement_amount` must be at least the `liquidated_damages_amount` plus the `de_identification_breach_penalty`, so a breaching franchisee must settle both the damages and the penalty. An overpayment is accepted and recorded as tendered.

A successful close-out answers 200, moves the agreement `TERMINATION_PENDING → TERMINATED` and stamps `closed_out_at`, moves `de_identification_status` from `SUBMITTED` or `BREACHED` to `VERIFIED`, moves `post_termination_status` from `OPEN` to `CLOSED`, and stores the tendered amount as `liquidated_damages_paid_amount`. `TERMINATED` is terminal: nothing leaves it, no further revenue may be reported against it, no inspection may be scored, and no consent may be sought.

## 4. Endpoint Definitions

All paths below are mounted at the root of the API. Successful responses carry HTTP 201 when the operation brings a new resource into existence — registering a brand, an ownership entity or an existing unit, filing an application or an encroachment claim, drafting a license agreement, opening an improvement plan, adding a scope line, and scoring a quality assurance inspection or filing a consent request — and HTTP 200 for every operation that reads, lists or modifies an existing resource, including every state transition, every derived recomputation and the logical clock. Operations that modify a resource return the updated resource in `data`; operations that create one return the created resource. Failures carry the HTTP status listed in §5 for the reported `error_id`.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| `POST` | `/_clock/set_current_utc` | Sets the server's logical clock, the only source of "now" for every deadline, window and timestamp. | `FranchiseDevelopmentManager`, `BrandStandardsDirector`, `QaInspector`, `Owner` |
| `POST` | `/brands` | Registers a franchisor brand with its rate card, protected radius, key-count minimum and standard term. | `BrandStandardsDirector` |
| `GET` | `/brands/{id}` | Reads one brand, including its two derived counters. | `FranchiseDevelopmentManager`, `BrandStandardsDirector`, `QaInspector`, `Owner` |
| `GET` | `/brands/{id}/existing-units` | Lists the already-operating hotels flying one brand, with an optional status filter. | `FranchiseDevelopmentManager`, `BrandStandardsDirector` |
| `POST` | `/owners` | Registers an ownership entity with its verified financial profile and computes both capacity variants. | `FranchiseDevelopmentManager` |
| `GET` | `/owners/{id}` | Reads one ownership entity with both capacity scores and both bands side by side. | `FranchiseDevelopmentManager`, `BrandStandardsDirector`, `Owner` |
| `POST` | `/owners/{id}/financial-profile` | Records a re-verified financial profile, recomputes both capacity variants and stales any passed review under way. | `FranchiseDevelopmentManager` |
| `POST` | `/existing-units` | Registers an already-operating hotel of a brand with its grid position and inclusive territory term. | `BrandStandardsDirector` |
| `POST` | `/existing-units/{id}/status` | Moves an operating hotel between OPERATING, SUSPENDED and TERMINATED. | `BrandStandardsDirector` |
| `POST` | `/applications` | Files a conversion application for one property against one brand on behalf of one ownership entity. | `FranchiseDevelopmentManager` |
| `GET` | `/applications/{id}` | Reads one application with all of its state axes, both impact figures and the capacity snapshot. | `FranchiseDevelopmentManager`, `BrandStandardsDirector`, `Owner` |
| `GET` | `/applications` | Lists applications with optional ownership-entity, brand and status filters. | `FranchiseDevelopmentManager`, `BrandStandardsDirector` |
| `POST` | `/applications/{id}/start-review` | Opens the review file on a submitted application. | `FranchiseDevelopmentManager` |
| `POST` | `/applications/{id}/financial-review` | Records the financial capacity review on the chosen basis; the outcome is derived, never supplied. | `FranchiseDevelopmentManager` |
| `POST` | `/applications/{id}/impact-analysis` | Runs the preliminary market impact study and opens the encroachment claim window. | `BrandStandardsDirector` |
| `POST` | `/applications/{id}/encroachment-claims` | Dockets an encroachment claim from a nearby operating hotel of the same brand. | `BrandStandardsDirector` |
| `GET` | `/encroachment-claims/{id}` | Reads one encroachment claim with its computed separation and penalty points. | `FranchiseDevelopmentManager`, `BrandStandardsDirector` |
| `GET` | `/encroachment-claims` | Lists encroachment claims with optional application, aggrieved-unit and status filters. | `FranchiseDevelopmentManager`, `BrandStandardsDirector` |
| `POST` | `/encroachment-claims/{id}/resolve` | Sustains or overrules a docketed claim; sustaining cascades into the impact study and voids draft licenses. | `BrandStandardsDirector` |
| `POST` | `/applications/{id}/finalize-impact` | Finalizes the impact study, applies the sustained-claim penalty and sets the encroachment verdict. | `BrandStandardsDirector` |
| `POST` | `/applications/{id}/request-revision` | Sends an application under review back to the applicant. | `FranchiseDevelopmentManager` |
| `POST` | `/applications/{id}/resubmit` | Applicant resubmits a revised application, reopening review and discarding both review axes. | `Owner` |
| `POST` | `/applications/{id}/decision` | Approves or declines the application at the gate that runs the territory, claim, key-count and duties checks. | `FranchiseDevelopmentManager` |
| `POST` | `/applications/{id}/agreements` | Drafts a license agreement from an approved application, freezing every commercial term. | `FranchiseDevelopmentManager` |
| `GET` | `/applications/{id}/agreements` | Lists the license agreements drafted from one application, with an optional status filter. | `FranchiseDevelopmentManager`, `BrandStandardsDirector`, `Owner` |
| `GET` | `/agreements/{id}` | Reads one license agreement with all four state axes, the frozen terms, the fee ledger and the exit fields. | `FranchiseDevelopmentManager`, `BrandStandardsDirector`, `QaInspector`, `Owner` |
| `POST` | `/agreements/{id}/execute` | Executes a drafted license against the application version the client last observed. | `FranchiseDevelopmentManager` |
| `POST` | `/agreements/{id}/pips` | Opens the conversion property improvement plan for an executed license. | `BrandStandardsDirector` |
| `GET` | `/agreements/{id}/pips` | Lists the property improvement plans of one agreement. | `FranchiseDevelopmentManager`, `BrandStandardsDirector`, `Owner` |
| `GET` | `/pips/{id}` | Reads one improvement plan with its four counters, its frozen cost allocation and its overall deadline. | `FranchiseDevelopmentManager`, `BrandStandardsDirector`, `Owner` |
| `POST` | `/pips/{id}/items` | Adds one scope line with its category, priority and cost estimate to a scoped plan. | `BrandStandardsDirector` |
| `GET` | `/pips/{id}/items` | Lists the scope lines of one plan, with an optional status filter. | `FranchiseDevelopmentManager`, `BrandStandardsDirector`, `Owner` |
| `POST` | `/pips/{id}/accept` | Franchisee accepts the scope, freezing the cost allocation and stamping a due date on every scope line. | `Owner` |
| `POST` | `/pips/{id}/compliance-sweep` | Re-evaluates every scope line against the logical clock and defaults the plan on an overdue critical or life-safety line. | `BrandStandardsDirector` |
| `POST` | `/pip-items/{id}/complete` | Franchisee reports a scope line finished and submits it for verification. | `Owner` |
| `POST` | `/pip-items/{id}/verify` | Verifies or rejects a submitted scope line. | `BrandStandardsDirector` |
| `POST` | `/pip-items/{id}/extension-request` | Franchisee asks for more time on a scope line. | `Owner` |
| `POST` | `/pip-items/{id}/extension-decision` | Grants or denies an extension request, clamping the award by the per-line ceiling and the plan-wide pool. | `BrandStandardsDirector` |
| `POST` | `/agreements/{id}/onboarding-milestone` | Advances one of the three onboarding tracks by exactly one rung. | `FranchiseDevelopmentManager` |
| `POST` | `/agreements/{id}/open` | Opens the hotel under the brand once critical and life-safety scope is verified and all three tracks are complete. | `BrandStandardsDirector` |
| `POST` | `/agreements/{id}/revenue-reports` | Reports one month of gross room revenue, or supersedes it, and assesses the tiered fees against it. | `Owner` |
| `GET` | `/agreements/{id}/fee-summary` | Computed read of the fee ledger: the two frozen rates, the surviving period count and the four running totals. | `FranchiseDevelopmentManager`, `BrandStandardsDirector`, `Owner` |
| `POST` | `/agreements/{id}/qa-inspections` | Records a quality assurance inspection, grades it and opens a cure window when the grade is not PASS. | `QaInspector` |
| `GET` | `/agreements/{id}/qa-inspections` | Lists the inspections of one agreement, with an optional grade filter. | `FranchiseDevelopmentManager`, `BrandStandardsDirector`, `QaInspector`, `Owner` |
| `POST` | `/qa-inspections/{id}/cure-submission` | Franchisee submits cure evidence inside the cure window. | `Owner` |
| `POST` | `/qa-inspections/{id}/cure-review` | A different inspector passes or fails the submitted cure, rehabilitating or defaulting the license. | `QaInspector` |
| `POST` | `/agreements/{id}/transfer-requests` | Franchisee seeks consent to a transfer, a change of control or a refinancing, and the consent fee is priced. | `Owner` |
| `GET` | `/transfer-requests/{id}` | Reads one consent request with its priced fee and its capacity snapshot. | `FranchiseDevelopmentManager`, `Owner` |
| `GET` | `/transfer-requests` | Lists consent requests with optional agreement, proposed-owner and status filters. | `FranchiseDevelopmentManager`, `BrandStandardsDirector` |
| `POST` | `/transfer-requests/{id}/decide` | Grants or refuses consent against the agreement version the client last observed. | `FranchiseDevelopmentManager` |
| `POST` | `/agreements/{id}/terminate` | Terminates an open license for cause or by mutual agreement, freezing liquidated damages and starting the de-identification clock. | `BrandStandardsDirector` |
| `POST` | `/agreements/{id}/de-identification` | Franchisee certifies that the brand has been removed from the property. | `Owner` |
| `POST` | `/agreements/{id}/close-out` | Closes the post-termination file once de-identification is verified and the settlement floor is met. | `BrandStandardsDirector` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_MISSING_AUTH_HEADER` | 401 |
| `ERR_INVALID_ROLE` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_FORBIDDEN_RESOURCE_OWNER` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_BRAND_NOT_FOUND` | 404 |
| `ERR_OWNER_NOT_FOUND` | 404 |
| `ERR_EXISTING_UNIT_NOT_FOUND` | 404 |
| `ERR_APPLICATION_NOT_FOUND` | 404 |
| `ERR_CLAIM_NOT_FOUND` | 404 |
| `ERR_AGREEMENT_NOT_FOUND` | 404 |
| `ERR_PIP_NOT_FOUND` | 404 |
| `ERR_PIP_ITEM_NOT_FOUND` | 404 |
| `ERR_INSPECTION_NOT_FOUND` | 404 |
| `ERR_TRANSFER_REQUEST_NOT_FOUND` | 404 |
| `ERR_APPLICATION_STAGE_INVALID` | 409 |
| `ERR_IMPACT_STUDY_STAGE_INVALID` | 409 |
| `ERR_AGREEMENT_NOT_DRAFT` | 409 |
| `ERR_AGREEMENT_NOT_EXECUTED` | 409 |
| `ERR_AGREEMENT_NOT_OPEN` | 409 |
| `ERR_AGREEMENT_NOT_TERMINATION_PENDING` | 409 |
| `ERR_PIP_NOT_SCOPED` | 409 |
| `ERR_PIP_ITEM_STAGE_INVALID` | 409 |
| `ERR_EXTENSION_NOT_PENDING` | 409 |
| `ERR_CLAIM_NOT_FILED` | 409 |
| `ERR_INSPECTION_STAGE_INVALID` | 409 |
| `ERR_TRANSFER_REQUEST_NOT_SUBMITTED` | 409 |
| `ERR_UNIT_STATUS_TRANSITION_INVALID` | 409 |
| `ERR_STALE_APPLICATION_VERSION` | 412 |
| `ERR_STALE_AGREEMENT_VERSION` | 412 |
| `ERR_LIFE_SAFETY_ITEM_OPEN` | 409 |
| `ERR_CRITICAL_PIP_ITEMS_OPEN` | 409 |
| `ERR_LIFE_SAFETY_NOT_EXTENDABLE` | 422 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_TRANSFER_BLOCKED_BY_DEFAULT` | 409 |
| `ERR_TERRITORY_TERM_CONFLICT` | 409 |
| `ERR_OPEN_ENCROACHMENT_CLAIMS` | 409 |
| `ERR_ENCROACHMENT_CONFIRMED` | 409 |
| `ERR_DUPLICATE_REVENUE_PERIOD` | 409 |
| `ERR_BRAND_CODE_TAKEN` | 409 |
| `ERR_EXTENSION_LIMIT_EXCEEDED` | 422 |
| `ERR_DEIDENTIFICATION_INCOMPLETE` | 422 |
| `ERR_ROOM_COUNT_BELOW_BRAND_MINIMUM` | 422 |
| `ERR_ONBOARDING_SEQUENCE_INVALID` | 409 |
| `ERR_ONBOARDING_INCOMPLETE` | 409 |
| `ERR_CHANNEL_NOT_CONNECTED` | 409 |
| `ERR_PIP_NOT_ACCEPTED` | 409 |
| `ERR_FINANCIAL_REVIEW_NOT_PASSED` | 409 |
| `ERR_IMPACT_STUDY_NOT_FINAL` | 409 |
| `ERR_UNIT_NOT_OPERATING` | 422 |
| `ERR_TERMINATION_NOT_ELIGIBLE` | 409 |
| `ERR_CLAIM_WINDOW_CLOSED` | 422 |
| `ERR_CURE_WINDOW_EXPIRED` | 422 |
| `ERR_INSPECTION_TOO_SOON` | 409 |
| `ERR_PIP_ITEM_PAST_DUE` | 422 |
| `ERR_EXTENSION_WINDOW_CLOSED` | 422 |
| `ERR_OWNER_CAPACITY_INSUFFICIENT` | 422 |
| `ERR_PROPOSED_OWNER_CAPACITY_INSUFFICIENT` | 422 |
| `ERR_POST_TERMINATION_OBLIGATIONS_OPEN` | 422 |
