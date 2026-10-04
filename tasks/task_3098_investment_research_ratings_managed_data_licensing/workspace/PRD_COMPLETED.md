# Research Ratings Licensing API — Product Requirements Document

## 1. Introduction

Investment research firms occupy an uncomfortable commercial position: they publish ratings on the very fund companies that may also be their data-licensing clients. This document specifies the Research Ratings & Managed Data Licensing API, a platform that manages the full lifecycle of fund and equity research data — from holdings ingestion and category assignment, through quantitative and analyst-driven rating methodologies governed by a rating committee, to commercial licensing of the resulting data under tiered agreements with audit rights and seat-based adviser entitlements.

The platform serves three constituencies whose interests must be kept structurally separate. Research operations ingests fund-company data, computes ratings, and manages methodology versions and their historical restatements. The licensing organization sells display, redistribution, and derived-works access to licensees, enforces seat quotas, and runs compliance audits that can suspend delinquent clients. A compliance function arbitrates the conflicts of interest that arise when a rated fund's issuer is also a paying licensee. Because date-dependent rules — methodology effectiveness windows, methodology-change effectuation, trailing dispute windows — must be reproducible in testing, the platform evaluates all such rules against a logical clock rather than wall-clock time.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelope formats, and cross-cutting principles that apply to every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the operational capacity in which they act. The platform recognizes five roles, spelled exactly as follows: `ResearchOps`, `Analyst`, `LicenseAdmin`, `ComplianceOfficer`, and `FundCompanyRep`. A request missing either header, or presenting a role that is not one of these five, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose authenticated role is not permitted to invoke the endpoint per the authorization matrix is rejected with `ERR_FORBIDDEN` (HTTP 403).

The identity carried by `X-User-ID` differs by role:

- When `X-User-Role` is `ResearchOps`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it but never compares it to any entity's `id`.
- When `X-User-Role` is `Analyst`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it (for example, as the `proposed_by` of a rating proposal at creation, or as the `voter_id` of a committee vote) and compares those recorded values against it for segregation-of-duties and withdrawal-ownership checks, but it is not the `id` of any entity row.
- When `X-User-Role` is `LicenseAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- When `X-User-Role` is `ComplianceOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- When `X-User-Role` is `FundCompanyRep`, `X-User-ID` is the `id` of the acting `FundCompany`; ownership checks on any resource that references a `FundCompany` compare the resource's foreign-key field to `X-User-ID`. In particular, a data-quality dispute may only be raised by the fund's issuer, so the rep's `X-User-ID` must equal the fund's issuing company's `id`.

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

List endpoints paginate via two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10 when omitted, accepts a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0.

Unless otherwise specified, every list endpoint returns resources sorted by their creation timestamp in ascending order.

The `meta` object of every list response carries exactly the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Validation Ordering

When a request violates more than one rule, the platform evaluates checks in a fixed priority order so that the first failure surfaces deterministically rather than being masked by a later one. The order is:

1. Authentication of the `X-User-ID` and `X-User-Role` headers, failing with `ERR_UNAUTHENTICATED`.
2. Role authorization for the endpoint, failing with `ERR_FORBIDDEN`.
3. Existence of path identifiers, validated left-to-right with the parent before the child, failing with `ERR_NOT_FOUND`.
4. Existence of foreign-key references carried in the request body (such as `fund_company_id`, `methodology_id`, or `licensed_agreement_id`), failing with `ERR_REFERENCE_NOT_FOUND`.
5. Legality of the target resource's current state for the requested transition, failing with `ERR_INVALID_STATE_TRANSITION`.
6. The conflict-of-interest gate described in §2.7, failing with `ERR_CONFLICT_OF_INTEREST`.
7. Segregation-of-duties rules on committee voting, failing with `ERR_SOD_VIOLATION`.
8. Uniqueness constraints, failing with `ERR_UNIQUENESS_VIOLATION`.
9. Temporal overlap and window-ordering rules, failing with `ERR_TEMPORAL_OVERLAP`.
10. Holdings snapshot integrity, failing with `ERR_SNAPSHOT_INVALID`.
11. Seat quota checks, failing with `ERR_SEAT_LIMIT_REACHED`.
12. Licensing tier prerequisites for index operations, failing with `ERR_LICENSE_TIER_INSUFFICIENT`.
13. Dispute-issuer and corrected-value rules, failing with `ERR_DISPUTE_NOT_ISSUER`.

A malformed request body — a missing required field, an invalid enum value, or a value of the wrong type — is rejected with `ERR_VALIDATION` (HTTP 400).

### 2.5. Common Resource Properties and Mutation Semantics

Every primary resource — fund companies, funds, categories, methodologies, methodology changes, ratings, rating proposals, licensees, license agreements, seat entitlements, license audits, data disputes, index definitions, and conflict flags — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation.
- `version` (integer): starting at its initial value on creation and incremented by exactly 1 on every mutation of the resource, including mutations caused by cascading side effects from operations on other resources.

Three subordinate resource kinds — holdings rows, committee votes, and client notices — are immutable ledger-style records. They carry only `id` and `created_at`; both `updated_at` and `version` are absent from them.

### 2.6. Nested Resource Retrieval

For endpoints whose path contains multiple resource identifiers, the platform validates existence strictly left-to-right, parent before child. The request is rejected immediately with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve, and deeper identifiers are never consulted. A request to list the funds of a nonexistent fund company fails on the company identifier before any fund-level rule is evaluated.

### 2.7. Conflict-of-Interest Governance

Whenever a rating is computed or initiated for a fund whose issuing company has any commercial relationship with the platform, the system raises a conflict flag on the fund — its `flag_kind` set to `COMMERCIAL_RATING_CONFLICT` and its `flag_status` beginning as `OPEN`. While such a flag's `flag_status` remains `OPEN`, the flag's `blocking` property is true and rating publication for that fund is prevented. Three operations enforce this gate, and all three reject with `ERR_CONFLICT_OF_INTEREST` (HTTP 422): publishing a quantitative rating, opening a committee proposal on an analyst rating when the proposer covers a fund whose issuer holds an unwaived commercial relationship, and casting a committee vote that would approve such a rating. Only a `ComplianceOfficer` may waive a flag; waiver moves `flag_status` from `OPEN` to `WAIVED`, flips `blocking` to false, and unblocks publication unless another open commercial-conflict flag remains on the same fund. A second flag kind, `INDEX_LICENSOR_CONFLICT`, records conflicts arising from index-licensing relationships; it does not block rating publication. Separately, a fund company's `commercial_relationship` returning to `NONE` resolves its open flags automatically, moving `flag_status` from `OPEN` to `RESOLVED`. Both `WAIVED` and `RESOLVED` are terminal.

### 2.8. Optimistic Concurrency Control

Three write operations require the client to declare the version of the parent entity it last observed, protecting against acting on a stale view of capacity or baseline state. In each case the version field is a non-optional input; if the supplied value does not match the parent entity's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412):

- Granting a seat entitlement requires `expected_agreement_version` matching the target license agreement's current `version`. Because every grant or revocation advances the agreement's version (its `seats_in_use` changes), a client whose view of remaining capacity predates another writer's grant or revocation is refused rather than allowed to oversubscribe the agreement.
- Proposing a methodology change requires `expected_methodology_version` matching the target methodology's current `version`, refusing a proposal whose baseline predates a competing change or a re-activation.
- Resolving a data dispute requires `expected_dispute_version` matching the dispute's current `version`, refusing a resolution whose read-modify-write chain predates another operator's transition of the same dispute.

No other endpoint takes a version field; all other mutations proceed without an optimistic-concurrency check.

### 2.9. Monetary and Basis-Point Precision

All monetary quantities are integer cents. All ratings, weights, and quality scores are integer basis points, where 10000 basis points represent the whole. Calculations that divide use integer floor division with no rounding to decimal places; where a fee calculation has numbered steps, each step floors to the cent before the next step consumes it. No floating-point arithmetic is used anywhere in fee, penalty, score, or weight computation.

### 2.10. Logical Clock

Date-dependent rules — methodology effectiveness windows, methodology-change approval and effectuation dates, trailing dispute windows for quality scoring, and holdings snapshot future-dating — are all evaluated against a platform logical clock, never against wall-clock time. The logical clock defaults to `2026-09-01T00:00:00Z` before it has ever been set and must not fall back to wall-clock time under any circumstances. A `ResearchOps`-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant; date-dependent rules evaluate against the new value on the next operation. The endpoint returns an object with a single field `current_utc` carrying the new logical-clock timestamp normalized to UTC `Z` form with three fractional digits.

### 2.11. Uniqueness Constraints

The platform enforces the following uniqueness rules, each violation rejected with `ERR_UNIQUENESS_VIOLATION` (HTTP 409): a fund's `ticker` is globally unique; the combination of a methodology's `methodology_code` and `version_number` is unique; a category's `category_code` is unique; an index definition's `index_code` is unique; and within a license agreement, an `ACTIVE` seat entitlement's `workstation_user_id` is unique (a revoked seat frees the identity for re-grant).

## 3. Business Logic & Workflows

### 3.1. Registering the Research Universe: Fund Companies and Funds

A `ResearchOps` operator registers a fund company with its `legal_name` and an optional `commercial_relationship` — one of `NONE`, `LICENSED_CLIENT`, or `INDEX_LICENSEE` — that defaults to `NONE` when omitted. The new company's `company_status` begins as `ACTIVE` and its `open_dispute_count` begins at 0. Every fund company read returns a computed `quality_score_bp` reflecting its dispute history, described in §3.7.

Funds are registered against their issuer by supplying `fund_company_id`, a globally unique `ticker`, an `inception_date`, the trailing three-year total return in basis points as `trailing_return_3y_bp`, optionally the trailing five-year return as `trailing_return_5y_bp` (null when the fund is younger than five years), and a downside-deviation `risk_score_bp`, both return and risk figures sourced from the most recent ingestion. A new fund's `fund_status` is `ACTIVE`; its `category_id` remains null until the first category assignment, and its `category_assignment_revision` begins at 0.

Suspending a fund company — a `ResearchOps` operation legal only while the company's `company_status` is `ACTIVE` — cascades: every `ACTIVE` fund of the company moves to `SUSPENDED`, and each such fund's non-terminal ratings (those in `PROVISIONAL` or `COMMITTEE_REVIEW`) have their `suppression_reason` set to `DISPUTE_HOLD`, blocking their publication until the hold clears. These suppression holds persist through reinstatement; they clear only through the dispute-resolution rule of §3.7. Reinstatement is legal only from `SUSPENDED` and only while the company's `open_dispute_count` is 0; an attempt with open disputes outstanding is rejected with `ERR_OPEN_DISPUTES_REMAIN` (HTTP 409). Reinstatement returns all of the company's `SUSPENDED` funds to `ACTIVE`. Offboarding is terminal and legal only from `ACTIVE`, only when every fund of the company has reached `LIQUIDATED`, and only with zero open disputes; the dispute precondition failure likewise surfaces `ERR_OPEN_DISPUTES_REMAIN`. It moves `company_status` to `OFFBOARDED` and has no cascading side effects because nothing operational remains.

Liquidating a fund — legal only while the fund is `ACTIVE` and while no dispute against it is `OPEN` or `UNDER_INVESTIGATION` (violations rejected with `ERR_OPEN_DISPUTES_REMAIN`) — moves the fund to `LIQUIDATED`, withdraws every non-terminal rating of the fund (`PROVISIONAL`, `COMMITTEE_REVIEW`, and `PUBLISHED` ratings all move to `WITHDRAWN`), and deletes the fund's row from every constituent list of any index in `LIVE` or `DRAFT` status.

### 3.2. Holdings Ingestion and Category Assignment

Holdings arrive as snapshots: a `ResearchOps` ingestion call carries one `as_of_date` and a `holdings` array whose every row names a `security_ticker`, an `asset_class` of `EQUITY`, `BOND`, `CASH`, or `OTHER`, a `sector` of `TECH`, `HEALTH`, `FINANCE`, `ENERGY`, `CONSUMER`, `INDUSTRIAL`, or `MIXED`, and a `weight_bp`. Snapshot integrity is enforced at ingestion: the weights across the snapshot must sum to exactly 10000 basis points, the `as_of_date` must not lie in the future relative to the logical clock, and a given snapshot date may be ingested only once per fund. Any violation is rejected with `ERR_SNAPSHOT_INVALID` (HTTP 422). The ingestion response is an array envelope containing the created holdings rows.

Ingestion completing triggers category assignment on a best-effort basis: if no category qualifies, the snapshot is still persisted and the fund's `category_id` simply stays as it was (null if never assigned); the failure is only surfaced as an error by the explicit re-run. Assignment considers only the snapshot with the latest `as_of_date` — because a given snapshot date may be ingested only once per fund, the latest-date snapshot is a single set of rows and the ingestion-time tie-break on `security_ticker` never comes into play. For each category whose `active` flag is true, the platform aggregates the total weight of holdings whose `asset_class` matches the category's `dominant_asset_class` — a category whose dominant asset class is `MIXED` counts both `EQUITY` and `BOND` holdings toward that leg — and separately the total weight whose `sector` matches the category's `dominant_sector`, where a `MIXED` dominant sector matches every holding. A category is eligible only when its asset-class aggregate is at least its `min_weight_bp`. Each eligible category is then scored: its asset-class aggregate, in basis points, contributes seven-tenths of the score, and its sector aggregate contributes three-tenths — that is, the asset aggregate is multiplied by 7000 and the sector aggregate by 3000 and the two products summed. The eligible category with the highest score wins; a tie in score is broken by ascending `category_code`, never by identifier. A category is defined by its unique `category_code`, its `dominant_asset_class` of `EQUITY`, `BOND`, or `MIXED`, its `dominant_sector`, its `min_weight_bp` threshold, and its `active` flag, which defaults to true; an inactive category accepts no new assignments.

An explicit `ResearchOps` re-run of assignment from the latest snapshot fails with `ERR_NO_ELIGIBLE_CATEGORY` (HTTP 422) when no active category clears its threshold. Whenever assignment — from ingestion, from the explicit re-run, or from an accepted category dispute — changes the fund's category, the fund's `category_id` is updated, its `category_assignment_revision` increments by 1, and the fund's `version` increments with `updated_at` refreshed.

### 3.3. Methodologies and Their Versions

A methodology version is created by `ResearchOps` with a `methodology_code`, a `methodology_kind` of `QUANTITATIVE` or `ANALYST`, an integer `version_number` unique within the code, an inclusive `effective_from` date, an optional exclusive `effective_to` date (null meaning open-ended), the two quantitative weights `weight_return_bp` and `weight_risk_bp` which must sum to exactly 10000, and `rating_ceilings`, an array of four non-increasing integer basis-point cutoffs. A new methodology's `methodology_status` is `DRAFT`; activation moves `methodology_status` to `EFFECTIVE`, supersession to `SUPERSEDED`, and retirement to `RETIRED`. When `effective_to` is provided it must be strictly later than `effective_from`; a window that violates this ordering is rejected with `ERR_TEMPORAL_OVERLAP` (HTTP 422).

Activating a methodology moves it from `DRAFT` to `EFFECTIVE`. Activation is refused with `ERR_TEMPORAL_OVERLAP` when another same-code methodology is already `EFFECTIVE` with an overlapping window — where the window runs from `effective_from` inclusive to `effective_to` exclusive, so two windows that merely abut, one ending exactly where the other begins, are legal. When the new version's window abuts or overlaps a currently `EFFECTIVE` same-code version, that prior version moves to `SUPERSEDED` and its `effective_to` is clipped to the successor's `effective_from`; the same clipping applies whenever a newer same-code version activates with an `effective_from` on or before the incumbent's `effective_to`.

Retirement is legal from either `DRAFT` or `EFFECTIVE`, except that an `EFFECTIVE` methodology cannot be retired while any `LIVE` index references it; retirement moves the methodology to `RETIRED`, its terminal state.

### 3.4. Methodology Change Management and Historical Restatement

Changes to an `EFFECTIVE` methodology follow a governed pipeline. A `ResearchOps` operator proposes a change by supplying `restatement_required` (whether historical ratings must be restated), an `effective_date`, and `expected_methodology_version` per the optimistic-concurrency rule of §2.8; the change is created with `change_status` set to `PROPOSED`, and its `client_notice_sent` flag begins false while `restated_rating_count` remains null until effectuation. Proposing a change advances the methodology's `version` as a side effect, so a subsequent proposal must declare the advanced version. Approval moves `change_status` from `PROPOSED` to `APPROVED`, effectuation from `APPROVED` to `EFFECTIVE`, and withdrawal — legal from either `PROPOSED` or `APPROVED` — to the terminal `WITHDRAWN`.

Approving the change — legal only from `PROPOSED`, only while the underlying methodology is `EFFECTIVE`, and only when the change's `effective_date` is on or after the current logical-clock date (an earlier date is rejected with `ERR_FUTURE_EFFECTIVE_DATE`, HTTP 422) — moves it to `APPROVED`. Client communication is then mandatory: recording a client notice creates a `ClientNotice` naming the `methodology_change_id`, the notified `licensee_id`, and a `notice_channel` of `EMAIL`, `PORTAL`, or `API`, stamps `notice_sent_at` with the logical-clock timestamp, and flips the change's `client_notice_sent` to true.

Effectuating an approved change is legal only from `APPROVED`, only once `client_notice_sent` is true, and only once the logical-clock date has reached the `effective_date` (a premature attempt is rejected with `ERR_FUTURE_EFFECTIVE_DATE`). Effectuation moves the change to `EFFECTIVE`. When the change's `restatement_required` is true, every `PUBLISHED` rating computed under the changed methodology moves to `RESTATED`, a successor rating is created for each — in `PROVISIONAL` for quantitative ratings or `COMMITTEE_REVIEW` for analyst ratings, each successor's `restatement_of_id` pointing at the rating it replaces — and the change's `restated_rating_count` is set to the number of ratings restated. A change may instead be withdrawn from either `PROPOSED` or `APPROVED`, moving it to the terminal `WITHDRAWN` state with no further effects.

### 3.5. Computing and Publishing Ratings

The quantitative star rating blends trailing performance against risk. The return leg combines the fund's `trailing_return_3y_bp` weighted at 6000 basis points with its `trailing_return_5y_bp` weighted at 4000 basis points — the three-year figure multiplied by 6000 plus the five-year figure multiplied by 4000, the sum floor-divided by 10000; when the five-year figure is null, the return leg is simply the three-year figure. The score in basis points is then the return leg multiplied by the methodology's `weight_return_bp` plus the quantity 10000 minus the fund's `risk_score_bp`, that quantity multiplied by the methodology's `weight_risk_bp`, the two products summed and floor-divided by 10000. Stars map from the score through the methodology's `rating_ceilings`: five stars when the score is at least the first cutoff, otherwise four when at least the second, otherwise three when at least the third, otherwise two when at least the fourth, otherwise one. The calculation is defined over funds that are `ACTIVE` and have at least one holdings snapshot ingested.

Two variants of the star value coexist on a computed rating. The provisional variant, computed at ingestion time before the as-of window is locked, uses the three-year return alone for the return leg — ignoring the five-year leg even when present — and its result is kept in `provisional_stars`. The final variant, computed through the rating-computation operation and through restatement cascades, uses the blended return leg and is stored in `stars`. Because the variants weight history differently, `provisional_stars` may differ from `stars` for an identical fund row.

A `ResearchOps` rating computation takes a `fund_id` and a `methodology_id` and creates the rating with `rating_status` set to `PROVISIONAL`, with `rating_kind` set to `QUANTITATIVE`, both `stars` (final variant) and `provisional_stars` populated, and `as_of_date` stamped from the logical clock. The referenced methodology must be `EFFECTIVE`; otherwise the request is rejected with `ERR_METHODOLOGY_NOT_EFFECTIVE` (HTTP 409). If the fund's issuer has a `commercial_relationship` other than `NONE`, a `COMMERCIAL_RATING_CONFLICT` conflict flag is created on the fund in `OPEN` status at the same time.

An analyst-driven rating is initiated instead by an `Analyst`, likewise with `fund_id` and `methodology_id`, but the referenced methodology must have `methodology_kind` equal to `ANALYST` and be `EFFECTIVE`; the rating is created `PROVISIONAL` with `rating_kind` set to `ANALYST` and both `stars` and `analyst_grade` null. The same conflict-flag creation applies when the issuer has a commercial relationship.

Publishing is the quantitative path's gate: a `ResearchOps` publish moves a rating from `PROVISIONAL` to `PUBLISHED` only when the rating is quantitative (publishing an analyst rating is rejected with `ERR_RATING_KIND_MISMATCH`, HTTP 409), the methodology is `EFFECTIVE`, the fund is `ACTIVE`, the rating's `suppression_reason` is `NONE` (a rating suppressed by `DISPUTE_HOLD` or `CONFLICT_HOLD` is rejected with `ERR_SUPPRESSED_RATING`, HTTP 409), and no `OPEN` `COMMERCIAL_RATING_CONFLICT` flag exists on the fund (per §2.7, rejected with `ERR_CONFLICT_OF_INTEREST`). On publication, any prior `PUBLISHED` rating of the same fund with the same `rating_kind` moves to `SUPERSEDED`. A non-terminal rating may also be withdrawn directly by `ResearchOps` — legal from `PROVISIONAL`, `COMMITTEE_REVIEW`, or `PUBLISHED`, never from `WITHDRAWN` or `SUPERSEDED` — moving it to `WITHDRAWN`.

### 3.6. The Analyst Rating Committee

An analyst rating advances through committee governance rather than direct publication. An `Analyst` opens a committee proposal — a `RatingProposal` whose `rating_id` links it to the analyst rating it mutates — on a `PROVISIONAL` analyst rating — opening one on a quantitative rating is rejected with `ERR_RATING_KIND_MISMATCH`, and opening one on a fund that is not `ACTIVE` or via a proposer with an unwaived commercial conflict is rejected per §2.7 — by supplying a `proposed_grade` of `GOLD`, `SILVER`, `BRONZE`, `NEUTRAL`, or `NEGATIVE`. The rating moves from `PROVISIONAL` to `COMMITTEE_REVIEW`, and the proposal is created with `proposal_status` set to `OPEN`, with its `proposed_by` recorded as the acting analyst's `X-User-ID` and its `approvals` and `rejections` counters both at 0.

Committee members then cast votes; each vote names the `proposal_id`, the `voter_id` taken from the acting analyst's `X-User-ID`, and a `vote` of `APPROVE`, `REJECT`, or `ABSTAIN`. Segregation of duties is strictly enforced: the analyst recorded as `proposed_by` may not vote on their own proposal, and no voter may vote twice on the same proposal; either violation is rejected with `ERR_SOD_VIOLATION` (HTTP 422). Each vote recomputes the proposal's `approvals` and `rejections` counts and increments the proposal's `version`.

The proposal auto-transitions as votes accumulate. Once the total votes cast reach three, the proposal moves from `OPEN` to `QUORUM_MET`. From either `OPEN` or `QUORUM_MET`, the proposal moves to `APPROVED` as soon as the approvals number at least 2, the combined count of approvals, rejections, and abstentions is at least 3, and approvals strictly outnumber rejections. Symmetrically, it moves to `REJECTED` from either state as soon as rejections number at least 2 and rejections are at least the approvals. On approval, the underlying rating moves from `COMMITTEE_REVIEW` to `PUBLISHED` — provided its `suppression_reason` is `NONE` and no open commercial-conflict flag exists on the fund, the same gate as §2.7 — with its `analyst_grade` set from the approved proposal's `proposed_grade`, and any prior `PUBLISHED` analyst rating for the same fund moves to `SUPERSEDED`. On rejection, the rating falls back from `COMMITTEE_REVIEW` to `PROVISIONAL`. The error `ERR_QUORUM_NOT_MET` (HTTP 422) is reserved for explicit close attempts before quorum; because proposals auto-transition, it normally never surfaces, but it remains the defined rejection for any direct finalize attempt. The proposing analyst may also withdraw their own `OPEN` proposal — only the analyst whose identity matches `proposed_by` may do so — which moves the proposal to `WITHDRAWN` and returns the rating from `COMMITTEE_REVIEW` to `PROVISIONAL`.

### 3.7. Data-Quality Disputes with Fund Companies

A fund company representative disputes the data the platform holds on one of their own funds by raising a dispute naming the `fund_id`, the `raised_by_company_id`, the `disputed_field` — one of `HOLDINGS`, `TRAILING_RETURN_3Y`, `TRAILING_RETURN_5Y`, `RISK_SCORE`, or `CATEGORY` — and, when the disputed field is numeric, a `corrected_value` in basis points (the corrected value is ignored for `HOLDINGS` and `CATEGORY` disputes). The raiser must be the fund's issuer: `raised_by_company_id` must equal the fund's `fund_company_id`, which for a `FundCompanyRep` is also their `X-User-ID`; and a numeric `disputed_field` without a `corrected_value` is invalid. Either violation is rejected with `ERR_DISPUTE_NOT_ISSUER` (HTTP 422). The dispute is created with `dispute_status` set to `OPEN`.

A `ResearchOps` operator then moves the dispute's `dispute_status` from `OPEN` to `UNDER_INVESTIGATION`. Investigation increments the issuer's `open_dispute_count` by 1 and sets `suppression_reason` to `DISPUTE_HOLD` on the disputed fund's `PROVISIONAL` and `COMMITTEE_REVIEW` ratings, freezing their publication while the facts are checked.

Resolution — which carries an `outcome` of `ACCEPTED` or `REJECTED`, a `resolution_note` recording the rationale, and `expected_dispute_version` per §2.8 — is legal only from `UNDER_INVESTIGATION`. Either outcome decrements the issuer's `open_dispute_count` by 1 and clears `DISPUTE_HOLD` from the fund's ratings whose `suppression_reason` is `DISPUTE_HOLD`, unless another `OPEN` or `UNDER_INVESTIGATION` dispute on the same fund remains, in which case the hold persists. An `ACCEPTED` resolution on a numeric disputed field additionally updates the corresponding fund field to the `corrected_value` and restates history: every `PUBLISHED` rating on the fund moves to `RESTATED` with a successor created exactly as in §3.4. An `ACCEPTED` resolution with `disputed_field` of `CATEGORY` instead recomputes the fund's category via the assignment calculation of §3.2, incrementing `category_assignment_revision` on change. Resolution moves the dispute to `RESOLVED_ACCEPTED` or `RESOLVED_REJECTED`, both terminal.

The dispute history feeds back into the issuer's standing. A fund company's `quality_score_bp`, computed on every read of the company, starts from 10000 and subtracts 1500 basis points for each dispute against the company's funds that was resolved `RESOLVED_ACCEPTED` within the trailing 365 logical days, then subtracts a further 500 basis points times the company's current `open_dispute_count`, floored at 0.

### 3.8. Licensees, Agreements, and Seat Entitlements

A `LicenseAdmin` registers a licensee with its `licensee_name`; the licensee's `licensee_status` begins as `ACTIVE` with `arrears_cents` at 0. License agreements are created with `agreement_status` set to `DRAFT`, carrying a `licensee_id`, a `tier` of `DISPLAY`, `REDISTRIBUTION`, or `DERIVED_WORKS`, a positive `seat_limit`, an inclusive `effective_from`, an optional exclusive `effective_to` (null meaning open, and when provided strictly later than `effective_from`), and an annual `base_fee_cents`; a new agreement's `seats_in_use` and `audit_count` both start at 0.

Activating an agreement — legal from `DRAFT`, and separately from `SUSPENDED` as a re-activation — requires the licensee to be `ACTIVE` and, on the `DRAFT` path, that no other agreement for the same licensee and same tier is already `ACTIVE` with an overlapping window; abutting windows are legal, and violations are rejected with `ERR_TEMPORAL_OVERLAP`. Suspending an `ACTIVE` agreement blocks new seat grants while suspended. Terminating an agreement — legal from `DRAFT`, `ACTIVE`, or `SUSPENDED` — requires `seats_in_use` to be 0 when done manually; seats still outstanding produce `ERR_SEATS_STILL_ACTIVE` (HTTP 409). Termination also suspends any `LIVE` index whose `licensed_agreement_id` references the agreement.

The annual fee for an agreement follows a fixed quoted structure, also exposed as a fee preview that takes a `tier`, `seat_limit`, and `base_fee_cents` and returns `total_fee_cents`. The per-seat rate is 120000 cents for `DISPLAY`, 250000 cents for `REDISTRIBUTION`, and 500000 cents for `DERIVED_WORKS`. A volume discount applies to the seat component only, by `seat_limit`: no discount for 1 to 10 seats, 1000 basis points for 11 to 50, 2000 basis points for 51 to 200, and 3000 basis points above 200. A derived-works surcharge of 2500 basis points applies when the tier is `DERIVED_WORKS`, and 0 otherwise. The fee preview returns an object with a single field `total_fee_cents`. The evaluation order is pinned and each step floors to the cent before the next consumes it: first, the raw seat component is the per-seat rate multiplied by `seat_limit`; second, the discounted seat component is the raw component minus the raw component multiplied by the volume-discount basis points floor-divided by 10000; third, the pre-surcharge subtotal is the `base_fee_cents` plus the discounted seat component; fourth, the total fee is the pre-surcharge subtotal plus that subtotal multiplied by the surcharge basis points floor-divided by 10000.

Granting a seat names a `workstation_user_id` and requires `expected_agreement_version` per §2.8. Within an agreement, an `ACTIVE` seat entitlement's `workstation_user_id` must be unique per §2.11 (a violation is `ERR_UNIQUENESS_VIOLATION`). The grant is refused with `ERR_SEAT_LIMIT_REACHED` (HTTP 422) when the agreement's `seats_in_use` has reached its `seat_limit`, or when either the agreement or the licensee is not `ACTIVE` — a suspended agreement blocks grants even with capacity free. A granted seat — a seat entitlement whose `agreement_id` links it to its parent agreement — begins with `seat_status` set to `ACTIVE` and with its `entitled_data_scope` set to the agreement's tier name at grant time; a later tier upgrade re-derives the scope. Each grant increments the agreement's `seats_in_use` by 1 and advances the agreement's `version`. Revoking a seat moves `seat_status` to `REVOKED`, decrements `seats_in_use` by 1, and advances both the seat's and the agreement's versions; revocation also happens automatically when the licensee is suspended.

A licensee's own lifecycle is driven by audit outcomes. Reinstating a `SUSPENDED` licensee requires `arrears_cents` to be 0; outstanding arrears produce `ERR_ARREARS_OUTSTANDING` (HTTP 409). Terminating a licensee — legal from `ACTIVE` or `SUSPENDED` — requires that no agreement under the licensee is `ACTIVE`; termination moves all `DRAFT` or `SUSPENDED` agreements to `TERMINATED`.

### 3.9. License Audits and Penalties

A `LicenseAdmin` opens an audit against an agreement by supplying its `agreement_id`; the audit is created with `audit_status` set to `OPEN`, with `unlicensed_uses_found` at 0, and the agreement's `audit_count` increments by 1. Filing findings — legal only while `audit_status` is `OPEN`, with a non-negative `unlicensed_uses_found` — moves `audit_status` to `FINDINGS_FILED`.

Closing an audit takes an `outcome`. Closing with `NO_ACTION` is legal from `FINDINGS_FILED` and moves the audit to `CLOSED_NO_ACTION` with `penalty_cents` at 0. Closing with `PENALTY` — moving `audit_status` to `CLOSED_WITH_PENALTY` — requires `unlicensed_uses_found` greater than 0 — a penalty close with zero unlicensed uses is rejected with `ERR_AUDIT_OUTCOME_INVALID` (HTTP 422) — and computes the penalty as follows. The per-use rate is 50000 cents for `DISPLAY`, 150000 cents for `REDISTRIBUTION`, and 400000 cents for `DERIVED_WORKS`; the raw penalty is that rate multiplied by `unlicensed_uses_found`. When the licensee has any prior audit on any of its agreements that closed `CLOSED_WITH_PENALTY`, a repeat-offender uplift of 5000 basis points applies to the raw penalty before the floor; otherwise no uplift applies. The computed `penalty_cents` is the raw penalty plus the raw penalty multiplied by the uplift floor-divided by 10000, and the result is then floored at a minimum of 100000 cents applied after the uplift — so a repeat offender always pays strictly more than a first offender for the same finding count whenever the raw penalty is already at least the minimum.

A penalty close adds the computed `penalty_cents` to the licensee's `arrears_cents`. When that leaves arrears above 0, the licensee moves automatically from `ACTIVE` to `SUSPENDED`, every `ACTIVE` seat entitlement under the licensee's agreements moves to `REVOKED`, and each affected agreement's `seats_in_use` is recomputed to 0.

### 3.10. Index Construction and Licensing

An index definition is created by a `LicenseAdmin` with a unique `index_code`, the `methodology_id` it tracks, a positive `max_constituents` cap, and a `single_constituent_cap_bp` per-constituent weight cap. It begins with `index_status` set to `DRAFT` and `licensed_agreement_id` null. Constituents are added by naming a `fund_id` and a requested `target_weight_bp`; each constituent row's `index_id` ties it to its parent index, the fund must be `ACTIVE` and hold a `PUBLISHED` rating under the index's methodology, and the constituent count must not exceed `max_constituents`. A new constituent's `final_weight_bp` stays null until a rebalance runs.

Before an index can go live it must be licensed: linking a license sets `licensed_agreement_id` to an agreement that is `ACTIVE` with tier `DERIVED_WORKS`, and launching — whether the first launch from `DRAFT` or a relaunch from `SUSPENDED` — requires that linked agreement to be `ACTIVE` and `DERIVED_WORKS` with the licensee `ACTIVE` (tier or status failures are rejected with `ERR_LICENSE_TIER_INSUFFICIENT`, HTTP 422), requires the tracked methodology to be `EFFECTIVE` (otherwise `ERR_METHODOLOGY_NOT_EFFECTIVE`), and requires at least one constituent and no more than `max_constituents` (unmet launch preconditions are rejected with `ERR_INDEX_NOT_LICENSABLE`, HTTP 409; an index with no linked agreement at all is likewise rejected with `ERR_INDEX_NOT_LICENSABLE`). Each launch runs the rebalance.

Rebalancing is a cap-and-redistribute waterfall over all constituent rows. The constituents are considered in descending order of `target_weight_bp`, with ties broken by ascending fund `ticker` — never by identifier. In the first pass, each constituent's final weight is set to the smaller of its `target_weight_bp` and the `single_constituent_cap_bp`, and whatever was capped away accumulates as excess. In the second pass, while excess remains, the walk repeats in the same order, adding to each constituent the smaller of the remaining excess and the headroom between the cap and that constituent's current final weight; when a full pass adds nothing to any constituent, redistribution stops and any leftover excess is discarded — so the total final weight may legitimately fall below 10000 basis points, which is by design and not an error. Rebalance writes `final_weight_bp` on every constituent and can also be re-run on demand against a `LIVE` index; the on-demand re-run returns the index's constituent rows in an array envelope.

Suspending moves a `LIVE` index to `SUSPENDED` — this also happens automatically when the licensing agreement is terminated — and relaunch follows the same preconditions as the original launch. Retirement is legal from `DRAFT`, `LIVE`, or `SUSPENDED` only when the index is not currently `LIVE`; a live index must be suspended first, and retirement is terminal.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource or drive a state transition return `200 OK`. All endpoints are mounted under the paths below.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock | ResearchOps |
| POST | `/research/fund-companies` | Register a fund company | ResearchOps |
| GET | `/research/fund-companies/{id}` | Get a fund company including computed quality score | ResearchOps, Analyst, LicenseAdmin, ComplianceOfficer, FundCompanyRep |
| GET | `/research/fund-companies` | List fund companies | ResearchOps, Analyst, LicenseAdmin, ComplianceOfficer |
| GET | `/research/fund-companies/{id}/funds` | List funds issued by the company | ResearchOps, Analyst, LicenseAdmin, ComplianceOfficer, FundCompanyRep |
| GET | `/research/fund-companies/{id}/disputes` | List disputes raised against the company's funds | ResearchOps, Analyst, ComplianceOfficer, FundCompanyRep |
| POST | `/research/fund-companies/{id}/suspend` | Suspend a fund company; cascades to funds and ratings | ResearchOps |
| POST | `/research/fund-companies/{id}/reinstate` | Reinstate a suspended fund company | ResearchOps |
| POST | `/research/fund-companies/{id}/offboard` | Offboard a fund company (terminal) | ResearchOps |
| POST | `/research/funds` | Register a fund | ResearchOps |
| GET | `/research/funds/{id}` | Get a fund | ResearchOps, Analyst, LicenseAdmin, ComplianceOfficer, FundCompanyRep |
| GET | `/research/funds` | List funds with filters | ResearchOps, Analyst, LicenseAdmin, ComplianceOfficer, FundCompanyRep |
| POST | `/research/funds/{id}/holdings` | Ingest a holdings snapshot | ResearchOps |
| GET | `/research/funds/{id}/holdings` | List holdings snapshots for a fund | ResearchOps, Analyst, ComplianceOfficer, FundCompanyRep |
| POST | `/research/funds/{id}/assign-category` | Re-run category assignment from the latest snapshot | ResearchOps |
| POST | `/research/funds/{id}/liquidate` | Liquidate a fund (terminal) | ResearchOps |
| GET | `/research/funds/{id}/ratings` | List ratings for a fund | ResearchOps, Analyst, LicenseAdmin, ComplianceOfficer, FundCompanyRep |
| GET | `/research/funds/{id}/disputes` | List disputes for a fund | ResearchOps, Analyst, ComplianceOfficer, FundCompanyRep |
| GET | `/research/funds/{id}/conflict-flags` | List conflict flags for a fund | ResearchOps, ComplianceOfficer |
| POST | `/research/funds/{id}/disputes` | Raise a data-quality dispute (issuer only) | FundCompanyRep |
| POST | `/research/categories` | Create a category | ResearchOps |
| GET | `/research/categories` | List categories | ResearchOps, Analyst, LicenseAdmin, ComplianceOfficer, FundCompanyRep |
| GET | `/research/categories/{id}` | Get a category | ResearchOps, Analyst, LicenseAdmin, ComplianceOfficer, FundCompanyRep |
| POST | `/research/methodologies` | Create a methodology version | ResearchOps |
| GET | `/research/methodologies/{id}` | Get a methodology | ResearchOps, Analyst, LicenseAdmin, ComplianceOfficer |
| GET | `/research/methodologies` | List methodologies | ResearchOps, Analyst, LicenseAdmin, ComplianceOfficer |
| GET | `/research/methodologies/{id}/changes` | List methodology changes for a methodology | ResearchOps, Analyst, ComplianceOfficer |
| POST | `/research/methodologies/{id}/activate` | Activate a methodology version | ResearchOps |
| POST | `/research/methodologies/{id}/retire` | Retire a methodology | ResearchOps |
| POST | `/research/methodologies/{id}/changes` | Propose a methodology change | ResearchOps |
| GET | `/research/methodology-changes/{id}` | Get a methodology change | ResearchOps, Analyst, ComplianceOfficer |
| GET | `/research/methodology-changes/{id}/notices` | List client notices for a change | ResearchOps, ComplianceOfficer |
| POST | `/research/methodology-changes/{id}/approve` | Approve a methodology change | ResearchOps |
| POST | `/research/methodology-changes/{id}/notices` | Record a client notice for the change | ResearchOps |
| POST | `/research/methodology-changes/{id}/effectuate` | Effectuate an approved change | ResearchOps |
| POST | `/research/methodology-changes/{id}/withdraw` | Withdraw a proposed or approved change | ResearchOps |
| POST | `/research/ratings/compute` | Compute a quantitative rating (final variant) | ResearchOps |
| POST | `/research/ratings` | Initiate an analyst-driven rating | Analyst |
| GET | `/research/ratings/{id}` | Get a rating | ResearchOps, Analyst, LicenseAdmin, ComplianceOfficer, FundCompanyRep |
| GET | `/research/ratings` | List ratings | ResearchOps, Analyst, LicenseAdmin, ComplianceOfficer, FundCompanyRep |
| GET | `/research/proposals` | List rating proposals | ResearchOps, Analyst, ComplianceOfficer |
| GET | `/research/indices` | List index definitions | LicenseAdmin, ResearchOps, Analyst, ComplianceOfficer |
| GET | `/research/funds/{id}/constituents` | List index constituent rows referencing a fund | LicenseAdmin, ResearchOps, Analyst, ComplianceOfficer |
| GET | `/research/licensees/{id}/notices` | List client notices sent to a licensee | LicenseAdmin, ResearchOps, ComplianceOfficer |
| POST | `/research/ratings/{id}/publish` | Publish a quantitative provisional rating | ResearchOps |
| POST | `/research/ratings/{id}/withdraw` | Withdraw a non-terminal rating | ResearchOps |
| POST | `/research/ratings/{id}/proposals` | Open a committee proposal on an analyst rating | Analyst |
| GET | `/research/proposals/{id}` | Get a proposal | ResearchOps, Analyst, ComplianceOfficer |
| GET | `/research/proposals/{id}/votes` | List committee votes on a proposal | ResearchOps, Analyst, ComplianceOfficer |
| POST | `/research/proposals/{id}/votes` | Cast a committee vote | Analyst |
| POST | `/research/proposals/{id}/withdraw` | Withdraw your own open proposal | Analyst |
| POST | `/research/conflict-flags/{id}/waive` | Waive an open conflict flag | ComplianceOfficer |
| GET | `/research/conflict-flags/{id}` | Get a conflict flag | ResearchOps, ComplianceOfficer |
| POST | `/research/licensees` | Register a licensee | LicenseAdmin |
| GET | `/research/licensees/{id}` | Get a licensee | LicenseAdmin, ResearchOps, ComplianceOfficer |
| GET | `/research/licensees/{id}/agreements` | List agreements for a licensee | LicenseAdmin, ResearchOps, ComplianceOfficer |
| POST | `/research/licensees/{id}/reinstate` | Reinstate a suspended licensee | LicenseAdmin |
| POST | `/research/licensees/{id}/terminate` | Terminate a licensee | LicenseAdmin |
| POST | `/research/license-agreements` | Create a license agreement | LicenseAdmin |
| POST | `/research/license-agreements/fee-quote` | Preview the license fee for a hypothetical agreement | LicenseAdmin, ResearchOps |
| GET | `/research/license-agreements/{id}` | Get an agreement | LicenseAdmin, ResearchOps, ComplianceOfficer |
| GET | `/research/license-agreements/{id}/seats` | List seat entitlements for an agreement | LicenseAdmin, ResearchOps, ComplianceOfficer |
| GET | `/research/license-agreements/{id}/audits` | List audits for an agreement | LicenseAdmin, ComplianceOfficer |
| POST | `/research/license-agreements/{id}/activate` | Activate an agreement | LicenseAdmin |
| POST | `/research/license-agreements/{id}/suspend` | Suspend an agreement | LicenseAdmin |
| POST | `/research/license-agreements/{id}/terminate` | Terminate an agreement | LicenseAdmin |
| POST | `/research/license-agreements/{id}/seats` | Grant a seat | LicenseAdmin |
| POST | `/research/seat-entitlements/{id}/revoke` | Revoke a seat | LicenseAdmin |
| POST | `/research/license-audits` | Open a license audit on an agreement | LicenseAdmin |
| POST | `/research/license-audits/{id}/file-findings` | File audit findings | LicenseAdmin |
| POST | `/research/license-audits/{id}/close` | Close an audit | LicenseAdmin |
| POST | `/research/indices` | Create an index definition | LicenseAdmin |
| GET | `/research/indices/{id}` | Get an index | LicenseAdmin, ResearchOps, Analyst, ComplianceOfficer |
| GET | `/research/indices/{id}/constituents` | List constituents of an index | LicenseAdmin, ResearchOps, Analyst, ComplianceOfficer |
| POST | `/research/indices/{id}/link-license` | Attach the derived-works agreement licensing this index | LicenseAdmin |
| POST | `/research/indices/{id}/constituents` | Add a constituent | LicenseAdmin |
| POST | `/research/indices/{id}/launch` | Launch or relaunch an index; runs rebalance | LicenseAdmin |
| POST | `/research/indices/{id}/suspend` | Suspend a live index | LicenseAdmin |
| POST | `/research/indices/{id}/retire` | Retire an index | LicenseAdmin |
| POST | `/research/indices/{id}/rebalance` | Re-run the cap-and-redistribute rebalance | LicenseAdmin |
| GET | `/research/data-disputes/{id}` | Get a dispute | ResearchOps, Analyst, ComplianceOfficer, FundCompanyRep |
| POST | `/research/data-disputes/{id}/investigate` | Move a dispute to under-investigation | ResearchOps |
| POST | `/research/data-disputes/{id}/resolve` | Resolve a dispute | ResearchOps |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_REFERENCE_NOT_FOUND` | 422 |
| `ERR_INVALID_STATE_TRANSITION` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_UNIQUENESS_VIOLATION` | 409 |
| `ERR_TEMPORAL_OVERLAP` | 422 |
| `ERR_SNAPSHOT_INVALID` | 422 |
| `ERR_NO_ELIGIBLE_CATEGORY` | 422 |
| `ERR_CONFLICT_OF_INTEREST` | 422 |
| `ERR_SOD_VIOLATION` | 422 |
| `ERR_QUORUM_NOT_MET` | 422 |
| `ERR_SEAT_LIMIT_REACHED` | 422 |
| `ERR_LICENSE_TIER_INSUFFICIENT` | 422 |
| `ERR_DISPUTE_NOT_ISSUER` | 422 |
| `ERR_RATING_KIND_MISMATCH` | 409 |
| `ERR_METHODOLOGY_NOT_EFFECTIVE` | 409 |
| `ERR_SUPPRESSED_RATING` | 409 |
| `ERR_OPEN_DISPUTES_REMAIN` | 409 |
| `ERR_ARREARS_OUTSTANDING` | 409 |
| `ERR_SEATS_STILL_ACTIVE` | 409 |
| `ERR_INDEX_NOT_LICENSABLE` | 409 |
| `ERR_AUDIT_OUTCOME_INVALID` | 422 |
| `ERR_VALIDATION` | 400 |
| `ERR_FUTURE_EFFECTIVE_DATE` | 422 |
