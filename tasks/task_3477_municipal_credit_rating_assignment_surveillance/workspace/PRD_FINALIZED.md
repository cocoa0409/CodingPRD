# Municipal Credit Ratings API — Product Requirements Document

## 1. Introduction

Municipal borrowers live and die by the credit notch attached to their name: a single step on the rating scale moves the interest they must offer investors when bonds come to market. This document specifies the **Municipal Credit Ratings API**, the operating system for a rating agency's municipal practice. The lifecycle it governs begins when a municipal issuer — or an underwriter acting on the issuer's behalf — requests a rating and accepts engagement terms, continues through structured information gathering and a six-factor analytical scorecard, and culminates in a rating committee that assigns a notch under jurisdiction-specific criteria for general obligation, revenue, and enterprise credits. Publication releases the notch together with a rationale and an outlook; because that notch directly prices debt, the API also computes the borrowing cost of prospective bond sales against both the pre-committee indicative rating and the published current rating.

Once published, a rating enters surveillance. Issuers owe periodic financial disclosure on a fixed annual schedule, and the consequences of silence are mechanical rather than discretionary: deadlines slip an obligation from overdue to delinquent, delinquency hardens into default, and default withdraws the rating for non-disclosure. Changes to the agency's published criteria fan out into portfolio-wide reviews of every affected rating, with issuer communication at each step; issuers may appeal a freshly assigned rating before publication strictly on the basis of new information; and a rating withdrawn for non-disclosure can be reinstated once the issuer cures its obligations. The agency may also initiate **unsolicited** ratings on its own analytical motion, and an issuer may carry several concurrent engagements at once — across credit families, or as the same credit shopped to multiple agencies.

All business endpoints are mounted under the `/muni` URL prefix; one platform endpoint, the logical-clock control, lives outside that prefix. Time inside the system is logical rather than wall-clock: the server clock starts at exactly 2026-09-01T00:00:00Z and advances only when an operator moves it forward, and every advance triggers a deterministic sweep of disclosure deadlines, delinquency escalations, non-disclosure withdrawals, and review escalations. Every window, deadline, and cascade described below is evaluated against that clock.

## 2. Global Specifications & System-Wide Principles

This section fixes the system-wide contract: authentication, the response envelope, pagination, the logical clock, resource boilerplate, concurrency control, the rating scale, monetary precision, and the order in which the server evaluates competing validation failures.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. A request missing either header, or carrying a role the system does not declare, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). Seven roles exist: `PlatformAdmin`, `Issuer`, `Underwriter`, `LeadAnalyst`, `CommitteeChair`, `CommitteeMember`, and `SurveillanceOfficer`. Each endpoint admits a fixed set of roles; a caller whose role is not admitted is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403). The role check also polices who may originate which kind of engagement: only a `LeadAnalyst` may open an unsolicited engagement, and only an `Issuer` or an `Underwriter` may open a solicited one — any other pairing draws the same `ERR_UNAUTHORIZED_ROLE`.

Two roles are entity-backed. When `X-User-Role` is `Issuer`, `X-User-ID` is the `id` of the acting `Issuer`; ownership checks on any resource that references an issuer — an engagement's `issuer_id`, the issuer standing behind a rating or a disclosure obligation, the issuer named on a bond sale — compare that foreign key to `X-User-ID`. When `X-User-Role` is `Underwriter`, `X-User-ID` is the `id` of the acting `Underwriter`, and an engagement opened by an underwriter must carry an `underwriter_id` equal to `X-User-ID`.

The remaining five roles carry opaque operator identifiers not tied to any persisted entity. The server records some of these identifiers as work proceeds — the `LeadAnalyst` who submits an engagement's scorecard is stored as the engagement's `assigned_analyst_id`, the `CommitteeChair` who schedules a session is stored as the session's `chair_id`, and each `CommitteeMember`'s ballot is recorded under a `voter_id` that must equal the caller's `X-User-ID` — but it never compares them to any entity's `id` for ownership. `PlatformAdmin` and `SurveillanceOfficer` identifiers are likewise opaque: they are recorded nowhere as ownership keys.

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

List endpoints paginate through two query parameters. `limit` sets the page size: it defaults to 10, must be at least 1, and may not exceed 100. `offset` sets how many records to skip, defaults to 0, and may not be negative. A `limit` outside the 1-to-100 range or a negative `offset` is rejected with `ERR_INVALID_PAGINATION_PARAMETERS` (HTTP 400). Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the envelope's `meta` object.

Unless an endpoint pins a different order, lists are sorted by `created_at` in ascending order. Several lists pin their order explicitly: an issuer's notification log is returned in emission order (`created_at` ascending), the ratings list is returned in insertion order (`created_at` ascending), portfolio review items are returned in fan-out order (the reviewed rating's `published_at` ascending, ties broken by the rating's `created_at` ascending), and a rating's disclosure obligations are listed in period order.

Beyond pagination, list endpoints accept optional equality filters on the resource's own fields — `state_code` on issuers; `issuer_id`, `underwriter_id`, `status`, and `credit_type` on engagements; `jurisdiction_code`, `credit_type`, and `status` on criteria versions; `engagement_id`, `criteria_version_id`, and `status` on committee sessions; `issuer_id`, `engagement_id`, `criteria_version_id`, and `status` on ratings; `issuer_id` and `rating_id` on bond sales; and `criteria_version_id`, `rating_id`, and `status` on review items.

### 2.4. The Logical Clock and the Time-Driven Sweep

The server maintains a single logical clock. Before any operator input, the clock stands at exactly 2026-09-01T00:00:00Z, and it never falls back to wall-clock time on its own. A `PlatformAdmin` advances the clock through a test-driving capability that accepts a target instant in the request field `to_iso8601`; this platform endpoint is deliberately mounted outside the `/muni` prefix at `/_clock/set_current_utc` and answers 200 on success. Advancing the clock is never a mere timestamp change: each advance runs the full time-driven sweep described in §3.5 and §3.6 — disclosure obligations flip state, delinquency notifications are logged, ratings are withdrawn for non-disclosure, pending review items escalate, and surveillance postures are recomputed, all in the pinned evaluation order given there. Every timestamp the system records — `assigned_at`, `published_at`, `withdrawn_at`, `submitted_at`, `decided_at`, `completed_at`, `activated_at`, `due_at`, and the common `created_at` and `updated_at` fields — reads this logical clock.

### 2.5. Common Resource Properties

Every primary resource carries four system-managed fields. `id` is a server-minted UUID with no type prefix. `created_at` is an ISO 8601 UTC timestamp with three fractional digits, fixed at creation. `updated_at` is refreshed on every change to the resource. `version` is an integer that increments by one on every mutation of the resource, whether the mutation is client-driven or system-driven. Two resources are deliberately lighter: a `CommitteeVote` and an `IssuerNotification` each carry only `id` and `created_at` — both `updated_at` and `version` are absent from them, because neither is ever modified after it is recorded.

### 2.6. Optimistic Concurrency Control

Exactly two write operations are guarded by optimistic concurrency control, each anchored on the version of the aggregate the write supersedes.

Submitting or superseding an engagement's analytical scorecard (the scorecard endpoint, `POST /muni/engagements/{id}/scorecard`) requires the request to carry `expected_engagement_version` holding the engagement's `version` as the client last observed it. If the engagement's current `version` has moved past that value — because another scorecard landed, a document was accepted, or terms were accepted in between — the submission is rejected with `ERR_STALE_ENGAGEMENT_VERSION` (HTTP 412). The scorecard write is a create-with-supersede, so the client's observed engagement version is the consistency anchor that keeps it from silently overwriting a state it has not seen.

Posting a surveillance rating action (the rating-actions endpoint, `POST /muni/ratings/{id}/actions`) requires `expected_rating_version` holding the rating's `version` as the client last observed it, because each action supersedes the rating's previously published state as the basis for the next. A mismatch with the rating's current `version` is rejected with `ERR_STALE_RATING_VERSION` (HTTP 412). No other endpoint takes a version field; endpoints not named here accept no expected-version input at all.

### 2.7. The Rating Notch Scale

All rating notches live on a single seven-step scale, ordered from strongest to weakest: `AAA`, `AA`, `A`, `BBB`, `BB`, `B`, `CCC`. Every construct that compares notches — the anchor table that maps a weighted score to a notch, committee ballots, the median tally with its even-count tie-break, the one-notch deviation band around the scorecard's indicative rating, and the adjacent-step rule on upgrades and downgrades — orders positions along this scale, with `AAA` at the best end and `CCC` at the worst. A rating's outlook is a separate axis with four values: `POSITIVE`, `STABLE`, `NEGATIVE`, and `DEVELOPING`.

### 2.8. Monetary Units, Weights, and Rounding

All monetary amounts — engagement fees, refunds, issuer credit balances, bond par amounts, and computed interest — are integers denominated in cents. Fee, refund, and interest computations round half-up to whole cents, and the interest computation pins a specific per-year rounding order described in §3.7. Analytical weighted scores are decimal numbers rounded half-up to exactly four decimal places, and the anchor table is applied to that rounded value rather than to any raw sum. Criteria weights are decimal fractions, and the six weights of a criteria version must sum to exactly 1.000. Yields and spreads are expressed in basis points, one basis point being one hundredth of a percent.

### 2.9. Nested Resource Retrieval

Endpoints that address a resource nested under another validate path identifiers strictly left to right. The request is rejected with a 404 the moment an identifier fails to resolve, before any later segment is examined: an unknown issuer yields `ERR_ISSUER_NOT_FOUND`, an unknown underwriter `ERR_UNDERWRITER_NOT_FOUND`, an unknown engagement `ERR_ENGAGEMENT_NOT_FOUND`, an unknown criteria version `ERR_CRITERIA_VERSION_NOT_FOUND`, an unknown committee session `ERR_SESSION_NOT_FOUND`, an unknown rating `ERR_RATING_NOT_FOUND`, an unknown appeal `ERR_APPEAL_NOT_FOUND`, an unknown disclosure obligation `ERR_OBLIGATION_NOT_FOUND`, an unknown bond sale `ERR_BOND_SALE_NOT_FOUND`, and an unknown review item `ERR_REVIEW_ITEM_NOT_FOUND`. Foreign keys supplied inside a request body — `issuer_id`, `underwriter_id`, and `rating_id` — are validated for existence under the same rule.

### 2.10. The Validation Priority Order

A single request can fail several checks at once, so the server evaluates its checks in a fixed priority order and reports the earliest failure: the lower-numbered check always wins over a higher-numbered one.

First, header presence and role validity, failing as `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. Second, role authorization for the endpoint, including the solicitation-role rule on engagement creation, failing as `ERR_UNAUTHORIZED_ROLE`. Third, existence of every path identifier, validated left to right, and of every body-supplied foreign key — the ten not-found errors of §2.9. Fourth, request well-formedness: required fields present, enum values in range, `end_at` after `start_at`, `par_amount_cents` positive, `maturity_years` within 1 to 30, and `withdraw_reason` present exactly when the rating action is `WITHDRAW`, failing as `ERR_INVALID_REQUEST`. Fifth, ownership: the caller's `X-User-ID` must match the owning identity — the engagement's issuer for term acceptance, document submission, withdrawal, appeals, and disclosure submission; the session's `chair_id` for open, close, and alternate appointment; the underwriter on underwriter-originated engagements; and the issuer on bond sales — failing as `ERR_NOT_RESOURCE_OWNER`. Sixth, state permission: the target resource's state must allow the operation, failing as `ERR_ENGAGEMENT_STATE_INVALID`, `ERR_SESSION_STATE_INVALID`, `ERR_RATING_STATE_INVALID`, `ERR_APPEAL_STATE_INVALID`, `ERR_OBLIGATION_STATE_INVALID`, `ERR_REVIEW_ITEM_STATE_INVALID`, `ERR_CRITERIA_VERSION_STATE_INVALID`, `ERR_WITHDRAWAL_NOT_PERMITTED`, or `ERR_REINSTATE_NOT_PERMITTED`. Seventh, optimistic concurrency: `expected_engagement_version` and `expected_rating_version` must match the resources' current versions, failing as `ERR_STALE_ENGAGEMENT_VERSION` or `ERR_STALE_RATING_VERSION`. Eighth, vote integrity and segregation of duties — the barred analyst, recused voters, and pool membership — failing as `ERR_ANALYST_VOTE_FORBIDDEN`, `ERR_RECUSED_VOTER_VOTE_FORBIDDEN`, or `ERR_VOTER_NOT_ELIGIBLE`. Ninth, the temporal windows on appeal filing, session opening, publication, and reinstatement, failing as `ERR_APPEAL_WINDOW_CLOSED`, `ERR_SESSION_NOT_OPENABLE`, `ERR_PUBLISH_WINDOW_NOT_ELAPSED`, or `ERR_REINSTATE_WINDOW_EXPIRED`.

Tenth, the structural business rules, evaluated among themselves in this sub-order: (a) the voter pool must hold exactly 5 distinct identifiers, failing as `ERR_VOTER_POOL_INVALID`; (b) a ballot must supply exactly one of `notch_vote` or `recusal_reason`, failing as `ERR_VOTE_KIND_AMBIGUOUS`; (c) the six criteria weights must sum to exactly 1.000, failing as `ERR_WEIGHT_SUM_INVALID`; (d) every factor score must be an integer from 1 to 5, failing as `ERR_FACTOR_SCORE_OUT_OF_RANGE`; (e) a submitted `document_code` must be registered and not already received, failing as `ERR_DOCUMENT_CODE_UNKNOWN` or `ERR_DUPLICATE_DOCUMENT`; (f) a rating carries at most one appeal, citing only new information, failing as `ERR_APPEAL_ALREADY_EXISTS` or `ERR_NO_NEW_INFORMATION`; (g) one ballot per voter per session, failing as `ERR_DUPLICATE_COMMITTEE_VOTE`; (h) an alternate may fill only a genuinely recused seat and must not already sit in the pool, failing as `ERR_ALTERNATE_NOT_PERMITTED`; (i) an `ACTIVE` criteria version must exist for the engagement's jurisdiction and credit type at scorecard submission, failing as `ERR_NO_ACTIVE_CRITERIA`; (j) no `ESCALATED` review item may hang over any rating of the engagement's issuer when a committee session is scheduled, failing as `ERR_ESCALATED_REVIEW_BLOCKS_SCHEDULING`; (k) the scheduling chair's calendar must be free of overlapping half-open windows, and a 24-hour cooling-off must separate sessions on the same engagement, failing as `ERR_SESSION_WINDOW_OVERLAP` or `ERR_SESSION_COOLING_OFF`; (l) the posture and review gates on rating actions, failing as `ERR_AFFIRM_BLOCKED_BY_POSTURE`, `ERR_UPGRADE_BLOCKED_BY_POSTURE`, or `ERR_REVIEW_PENDING`; (m) a delinquent issuer may not open new solicited engagements, failing as `ERR_ISSUER_DELINQUENT`; (n) reinstatement requires every disclosure obligation resolved, failing as `ERR_UNRESOLVED_OBLIGATIONS`; (o) the adjacent-notch rule on upgrades and downgrades, and the notch required by a rating-action review outcome, failing as `ERR_NOTCH_STEP_INVALID` or `ERR_REVIEW_OUTCOME_NOTCH_REQUIRED`.

Eleventh, fee settlement at term acceptance: payment plus applied credit must equal the fee, and the applied credit may not exceed the issuer's balance, failing as `ERR_FEE_PAYMENT_MISMATCH` or `ERR_INSUFFICIENT_ISSUER_CREDIT`. Twelfth, pagination parameters on list endpoints, failing as `ERR_INVALID_PAGINATION_PARAMETERS`.

### 2.11. The Issuer Communication Log

Every event that concerns a rated issuer is recorded in an append-only log of `IssuerNotification` entries. Each entry carries the `issuer_id` it concerns, an `event_type`, the `reference_id` of the related entity — a rating, an obligation, a review item, or an engagement — and a human-readable `message`. Eleven event types exist: `ENGAGEMENT_WITHDRAWN`, `RATING_ASSIGNED`, `RATING_PUBLISHED`, `RATING_ACTION`, `RATING_WITHDRAWN`, `RATING_REINSTATED`, `APPEAL_UPHELD`, `APPEAL_DENIED`, `OBLIGATION_DELINQUENT`, `REVIEW_OPENED`, and `REVIEW_COMPLETED`. The workflows in §3 name the exact moment at which each is logged. An issuer's log is listed in emission order, `created_at` ascending, and entries are never updated after they are written.

## 3. Business Logic & Workflows

This section narrates the rating lifecycle from engagement origination to bond pricing. State values appear as exact strings, and each workflow names the error codes that guard it; §4 supplies the HTTP contract for every capability described here.

### 3.1. Opening an Engagement: Registration, Fees, and Withdrawal

Before any rating work begins, a `PlatformAdmin` registers the parties. Registering a municipal issuer records its `legal_name`, its two-letter `state_code`, an `issuer_type` of `GENERAL_GOVERNMENT`, `SPECIAL_DISTRICT`, or `ENTERPRISE_PROVIDER`, the issuer's `fiscal_year_end` as a month-day in MM-DD form (for example 06-30), and the `population` served. A new issuer starts with a `credit_balance_cents` of 0 and a `delinquent_flag` of false. Registering an underwriter records the `firm_name` and the municipal `license_number`.

A rating engagement is opened by an `Issuer` for itself, by an `Underwriter` on the issuer's behalf, or by a `LeadAnalyst` when the agency initiates coverage on its own motion. The payload names the `issuer_id`, the `solicitation` (`SOLICITED` or `UNSOLICITED`), the `credit_type` (`GENERAL_OBLIGATION`, `REVENUE`, or `ENTERPRISE`), and the `jurisdiction_code` that keys criteria selection (for example US-CA); an underwriter-originated engagement also carries the `underwriter_id`. The solicitation dimension is policed by role: a `LeadAnalyst` may create only `UNSOLICITED` engagements, and only an `Issuer` or `Underwriter` may create a `SOLICITED` one, with any other pairing rejected as `ERR_UNAUTHORIZED_ROLE`. An `Issuer` caller must be opening its own engagement — `issuer_id` equal to `X-User-ID` — and an `Underwriter` caller must name itself in `underwriter_id`, on pain of `ERR_NOT_RESOURCE_OWNER`. Multiple concurrent engagements per issuer, whether of the same or of different credit types, are permitted, modeling issuers that rate with multiple agencies.

The engagement fee is fixed by credit family: 4500000 cents for `GENERAL_OBLIGATION`, 5200000 cents for `REVENUE`, and 5800000 cents for `ENTERPRISE`. An unsolicited engagement carries a `fee_cents` of 0 and is created with `fee_paid` already true, its fee waived. A solicited engagement starts in `REQUESTED` with `fee_paid` false; an unsolicited one skips negotiation entirely and starts in `INFORMATION_GATHERING`. Creation also fixes the engagement's information requirements: `required_document_codes` is derived from the engagement's `solicitation` and `credit_type`. A solicited engagement's set is a strict subset of the twelve-code document registry (§3.2), keyed by `credit_type`: a `GENERAL_OBLIGATION` engagement requires exactly `AUDIT_FY`, `ADOPTED_BUDGET`, `TAX_BASE_REPORT`, and `DEBT_STATEMENT`; a `REVENUE` engagement requires exactly `AUDIT_FY`, `RATE_COVENANT`, `FLOW_OF_FUNDS`, and `ENGINEERING_REPORT`; and an `ENTERPRISE` engagement requires exactly `AUDIT_FY`, `MANAGEMENT_DISCUSSION`, and `CAPITAL_PLAN`. An unsolicited engagement's set is exactly the single code `PUBLIC_FILING_FY`. One structural guard applies at creation: a `SOLICITED` engagement may not be opened while the issuer's `delinquent_flag` is set — the attempt is rejected with `ERR_ISSUER_DELINQUENT`.

Accepting terms is the issuer's act that turns a request into a paid engagement, moving it `REQUESTED` → `ENGAGED`. The issuer settles the fee with a cash `fee_payment_cents` plus an optional `apply_credit_cents` drawn from its credit balance, which defaults to 0 when omitted. The cash and the applied credit together must equal `fee_cents` exactly, or the attempt fails with `ERR_FEE_PAYMENT_MISMATCH`; the applied credit may not exceed the issuer's `credit_balance_cents`, or it fails with `ERR_INSUFFICIENT_ISSUER_CREDIT`. Because unsolicited engagements are created directly into `INFORMATION_GATHERING`, only `SOLICITED` engagements ever occupy `REQUESTED`, so acceptance always concerns a paid engagement. On success `fee_paid` flips to true, the applied credit is deducted from the issuer's `credit_balance_cents`, and the engagement's `version` increments.

Withdrawal lets an issuer exit a solicited engagement before a rating is assigned. From `REQUESTED`, where no fee has yet been paid, withdrawal records a `refund_cents` of 0 and moves no money. From `ENGAGED`, `INFORMATION_GATHERING`, `ANALYSIS`, or `COMMITTEE_READY`, withdrawal refunds half the paid fee: `refund_cents` is `fee_cents` multiplied by the withdrawal refund ratio of 0.5, rounded half-up to whole cents, and the refund is credited to the issuer's `credit_balance_cents` for use against future engagement fees. Every withdrawal moves the engagement to the terminal `WITHDRAWN` state, logs an `ENGAGEMENT_WITHDRAWN` notification to the issuer, and increments the engagement's `version`. Withdrawal is never available on an unsolicited engagement, nor on any engagement once it reaches `RATING_ASSIGNED`; both attempts are rejected with `ERR_WITHDRAWAL_NOT_PERMITTED`, because from assignment onward the appeal process is the only pre-publication remedy.

### 3.2. Information Gathering and the Analytical Scorecard

Information flows into an engagement one document at a time, identified by a `document_code` drawn from a fixed registry of twelve: `AUDIT_FY`, `ADOPTED_BUDGET`, `TAX_BASE_REPORT`, `DEBT_STATEMENT`, `RATE_COVENANT`, `FLOW_OF_FUNDS`, `ENGINEERING_REPORT`, `MANAGEMENT_DISCUSSION`, `CAPITAL_PLAN`, `PUBLIC_FILING_FY`, `PENSION_VALUATION`, and `EPA_LITIGATION_REPORT`. A code outside this registry is rejected with `ERR_DOCUMENT_CODE_UNKNOWN`, and resubmitting a code already present in the engagement's `received_document_codes` is rejected with `ERR_DUPLICATE_DOCUMENT`. For a solicited engagement the submitting actor is the owning `Issuer`; for an unsolicited one it is the `LeadAnalyst`. Documents are accepted only while the engagement is `ENGAGED` or `INFORMATION_GATHERING`; in any other state the submission fails with `ERR_ENGAGEMENT_STATE_INVALID`.

Each accepted document appends its code to `received_document_codes` and increments the engagement's `version`. The first accepted document moves the engagement `ENGAGED` → `INFORMATION_GATHERING` automatically, and the moment the received set covers every code in `required_document_codes`, the engagement advances `INFORMATION_GATHERING` → `ANALYSIS` on its own — no separate request exists for either move.

Once in `ANALYSIS`, a `LeadAnalyst` authors the engagement's **analytical scorecard**: six integer factor scores — `score_economy`, `score_management`, `score_budgetary_performance`, `score_flexibility`, `score_liquidity`, and `score_debt_profile` — each an integer from 1 to 5 inclusive, with anything outside that range rejected as `ERR_FACTOR_SCORE_OUT_OF_RANGE`. The submission is OCC-guarded (§2.6): it must carry `expected_engagement_version` matching the engagement's current `version`, failing with `ERR_STALE_ENGAGEMENT_VERSION` otherwise. Scoring also requires an `ACTIVE` criteria version for the engagement's `jurisdiction_code` and `credit_type`; when none exists the submission fails with `ERR_NO_ACTIVE_CRITERIA`. A first submission moves the engagement `ANALYSIS` → `COMMITTEE_READY`; a later submission from `COMMITTEE_READY` supersedes the prior scorecard wholesale — the engagement stays `COMMITTEE_READY`, and the committee, when it eventually convenes, always sees the latest scorecard. Either way the engagement's `version` increments, and the caller's `X-User-ID` is recorded as `assigned_analyst_id` — the segregation-of-duties anchor that bars the authoring analyst from voting on this engagement's committee (§3.3). A scorecard submitted while the engagement is in any state other than `ANALYSIS` or `COMMITTEE_READY` is rejected with `ERR_ENGAGEMENT_STATE_INVALID`.

The scorecard's computed fields are derived the moment it is submitted. The server first finds the `ACTIVE` criteria version for the engagement's segment and pins its identity into the scorecard's `criteria_version_id` — the version whose weights produced this scorecard, whatever happens to criteria afterwards. The **weighted score** is the sum of each criterion's weight times its factor score across all six factors: `w_economy` times `score_economy`, plus `w_management` times `score_management`, plus `w_budgetary_performance` times `score_budgetary_performance`, plus `w_flexibility` times `score_flexibility`, plus `w_liquidity` times `score_liquidity`, plus `w_debt_profile` times `score_debt_profile` — the total rounded half-up to exactly four decimal places and stored as `weighted_score`.

From the rounded `weighted_score`, the anchor table fixes `anchor_notch` using inclusive lower bounds: a rounded score of at least 4.50 anchors at `AAA`; at least 4.00 anchors at `AA`; at least 3.50 anchors at `A`; at least 3.00 anchors at `BBB`; at least 2.50 anchors at `BB`; at least 2.00 anchors at `B`; and anything below 2.00 anchors at `CCC`. The comparison always runs against the four-decimal rounded value, never against the raw sum.

For `GENERAL_OBLIGATION` and `REVENUE` engagements, the indicative rating the committee will see is simply the anchor: `indicative_notch` equals `anchor_notch` and `capped` is false. Enterprise credits carry a **weak-link cap**: when the engagement's `credit_type` is `ENTERPRISE` and the lowest of the six factor scores is exactly 1, the indicative rating becomes the worse of `anchor_notch` and `BB`, and `capped` is set true; when no factor scores a 1, an enterprise scorecard behaves like the standard variant, `capped` false and the anchor flowing through unchanged. An engagement's current scorecard can be read back as an array holding zero or one element, and every scorecard computed under a given criteria version can be listed for governance review.

### 3.3. The Rating Committee

With an engagement `COMMITTEE_READY`, a `CommitteeChair` convenes the rating committee. Scheduling a session takes a `start_at` and an `end_at` — the session window, inclusive at the start and exclusive at the end, with `end_at` required to fall after `start_at` on pain of `ERR_INVALID_REQUEST` — and a `voter_ids` pool of exactly 5 distinct voter identifiers, with any other pool rejected as `ERR_VOTER_POOL_INVALID`. Scheduling pins the `ACTIVE` criteria version for the engagement's segment into the session's `criteria_version_id`, and that pin is never re-pointed by later criteria activations. The scheduling chair's `X-User-ID` is stored as `chair_id`, and only that chair may subsequently open, close, or appoint alternates to the session — anyone else meets `ERR_NOT_RESOURCE_OWNER`. A freshly scheduled session is `SCHEDULED`, records the engagement through its `engagement_id`, and starts with an `eligible_voter_count` of 5. Scheduling is permitted only while the engagement is `COMMITTEE_READY`; otherwise it fails with `ERR_ENGAGEMENT_STATE_INVALID`.

Two calendar rules protect both the chair and the engagement. The chair may not hold another `SCHEDULED` or `IN_SESSION` session whose half-open window intersects the requested one — windows that merely touch, one ending exactly as the other begins, are permitted, while a true overlap is rejected with `ERR_SESSION_WINDOW_OVERLAP`. And a new session on the same engagement must respect a 24-hour cooling-off: its `start_at` may not fall earlier than 24 hours after the latest prior session's `end_at` on that engagement, though a gap of exactly 24 hours is allowed; violations yield `ERR_SESSION_COOLING_OFF`. Scheduling is additionally blocked while any rating belonging to the engagement's issuer carries a criteria review item in `ESCALATED` — an unresolved escalation anywhere in the issuer's portfolio freezes new committee work with `ERR_ESCALATED_REVIEW_BLOCKS_SCHEDULING`.

Opening moves a session `SCHEDULED` → `IN_SESSION` and may happen only inside its window: the clock must have reached `start_at` and must not yet have reached `end_at`, otherwise the open fails with `ERR_SESSION_NOT_OPENABLE`. A successful open increments the session's `version`.

While a session is `IN_SESSION`, each `CommitteeMember` casts exactly one ballot; any ballot offered while the session is in another state is rejected with `ERR_SESSION_STATE_INVALID`. The ballot's `voter_id` must equal the caller's `X-User-ID` and must belong to the session pool — the original `voter_ids` plus any `appointed_alternate_ids` — or the vote is rejected with `ERR_VOTER_NOT_ELIGIBLE`. Each ballot takes exactly one of two forms: a `notch_vote` carrying one of the seven notches, or a `recusal_reason` text; supplying both or neither is `ERR_VOTE_KIND_AMBIGUOUS`, and the recorded `kind` becomes `VOTE` or `RECUSAL` accordingly. Two integrity bars apply before any ballot is accepted: a `voter_id` equal to the engagement's `assigned_analyst_id` may not vote at all — `ERR_ANALYST_VOTE_FORBIDDEN`, the segregation-of-duties bar — and a voter who has recorded a recusal in the session may not later cast a vote in it, failing as `ERR_RECUSED_VOTER_VOTE_FORBIDDEN`. Any second ballot, whether vote or recusal, from the same voter in the same session is `ERR_DUPLICATE_COMMITTEE_VOTE`. Every recorded ballot carries the session's `session_id`, its `voter_id`, its `kind`, and whichever of `notch_vote` or `recusal_reason` was cast. A recorded recusal extends the session's `recused_voter_ids`, and each accepted ballot or recusal increments the session's `version`.

Recusals shrink the eligible pool, so the chair may appoint alternates to restore it toward five. Appointing an alternate names the `recused_voter_id` being replaced and the `alternate_voter_id` stepping in; the appointment is rejected with `ERR_ALTERNATE_NOT_PERMITTED` unless the named voter has a recorded recusal in this session, the alternate is not already in the pool and not among the recused, and the session is not yet terminal. A successful appointment appends to `appointed_alternate_ids`, recomputes `eligible_voter_count` as 5 minus the number of recused voters plus the number of appointed alternates, and increments the session's `version`.

Closing the session — again, only the scheduling chair — tallies the committee. If the chair closes a session that was never opened, the session is adjourned outright with `adjourn_reason` `QUORUM_NOT_MET` and zero votes recorded. From `IN_SESSION`, the tally counts only ballots of `kind` `VOTE`; recusals do not count toward the tally. Fewer than 3 cast votes is a failed quorum: the session adjourns `IN_SESSION` → `ADJOURNED` with `adjourn_reason` `QUORUM_NOT_MET`. With at least 3 votes, the tally sorts the cast notches by their positions on the seven-step scale and takes the median — and when the vote count is even, the worse of the two middle notches, the one nearer `CCC`, is chosen. The committee's median may sit at most one notch away from the scorecard's `indicative_notch` in either direction; a wider gap adjourns the session with `adjourn_reason` `NOTCH_DEVIATION_EXCEEDED`. A median inside the band completes the session `IN_SESSION` → `COMPLETED` and records the median as the session's `outcome_notch`; a session that adjourns leaves `outcome_notch` null, just as a completed one leaves `adjourn_reason` null. Any close, completed or adjourned, increments the session's `version`.

Completion assigns the rating. A new `Rating` is created in `ASSIGNED` with its `notch` set to the session's `outcome_notch`, `surveillance_posture` initialized to `CURRENT`, `assigned_at` stamped from the clock, and `notch_history` opened with a single entry whose cause is `COMMITTEE_ASSIGNMENT`. The rating inherits the session's pinned `criteria_version_id`, copies `credit_type` and `jurisdiction_code` from the engagement, and denormalizes the `issuer_id` for filtering. The engagement advances `COMMITTEE_READY` → `RATING_ASSIGNED`, and a `RATING_ASSIGNED` notification is logged to the issuer. An adjourned session, by contrast, leaves the engagement `COMMITTEE_READY`, and the chair may schedule a fresh session for another attempt, subject to the same cooling-off rule.

### 3.4. Publication, Appeals, and the Pre-Publication Window

Between assignment and publication runs a 120-hour appeal window. An issuer that believes the committee missed evidence may file an appeal while the rating is `ASSIGNED` and the clock stands no later than 120 hours after `assigned_at` — a filing at exactly the 120-hour mark is still admitted, while anything later is rejected with `ERR_APPEAL_WINDOW_CLOSED`; a filing against a rating in any other state fails with `ERR_RATING_STATE_INVALID`. The appeal rests entirely on new information: `new_information_codes` must be a non-empty list of registered document codes, and every code must be disjoint from the engagement's `received_document_codes` — an empty list, an unknown code, or any code the committee already saw is rejected with `ERR_NO_NEW_INFORMATION`. Each rating carries at most one appeal; a second filing is rejected with `ERR_APPEAL_ALREADY_EXISTS`. A successfully filed appeal is `FILED`, is tied to its rating through `rating_id`, and blocks publication until decided.

The decision belongs to a `CommitteeChair`, who supplies a `decision` of `UPHELD` or `DENIED` together with a `rationale`; the rationale is recorded as `decision_rationale` and the moment of decision as `decided_at`. An upheld appeal is decisive: the rating moves `ASSIGNED` → `REMANDED`, a terminal state, the engagement returns `RATING_ASSIGNED` → `COMMITTEE_READY` to re-deliberate in light of the new information — the analyst may supersede the scorecard and the chair may convene a fresh committee — and an `APPEAL_UPHELD` notification is logged. A denied appeal leaves the rating `ASSIGNED`, logs `APPEAL_DENIED`, and clears the way to publication once the window has elapsed. Deciding an appeal that is no longer `FILED` is rejected with `ERR_APPEAL_STATE_INVALID`.

Publication is performed by a `LeadAnalyst` and is gated twice: the clock must stand strictly later than 120 hours after `assigned_at` — a publish attempted at or before the mark fails with `ERR_PUBLISH_WINDOW_NOT_ELAPSED` — and no `FILED` appeal may exist for the rating, on pain of `ERR_APPEAL_PENDING`. The payload supplies the published `outlook` — one of `POSITIVE`, `STABLE`, `NEGATIVE`, or `DEVELOPING` — and the published `rationale`. On success the rating moves `ASSIGNED` → `PUBLISHED` with `published_at` stamped from the clock, the engagement moves to its own terminal `PUBLISHED` state — its lifecycle ends while surveillance continues on the rating — the first annual disclosure obligation is created per the schedule in §3.5, a `RATING_PUBLISHED` notification is logged, and the rating's `version` increments. Any attempt to publish a rating that is not `ASSIGNED` is rejected with `ERR_RATING_STATE_INVALID`.

### 3.5. Surveillance: Disclosure, Posture, and Rating Actions

Publication starts the disclosure clock. The first obligation, `period_index` 1, takes as its `fiscal_year_end` the first occurrence of the issuer's `fiscal_year_end` month-day — anchored at 00:00:00Z — that falls strictly after `published_at`; if the issuer's month-day in the publication year falls on or before the publication date, the schedule rolls forward one calendar year. Its `due_at` is 210 days after that `fiscal_year_end`. Each submission while the rating is `PUBLISHED` then creates the next annual period: `period_index` increments by one, `fiscal_year_end` advances by exactly one calendar year, and `due_at` is again set 210 days out. Every obligation is tied to its rating through `rating_id`.

Submitting a disclosure is the issuer's own act, checked against the issuer that owns the obligation's rating — anyone else is refused with `ERR_NOT_RESOURCE_OWNER`. The clock classifies each submission. An obligation still `PENDING`, submitted at or before its `due_at`, becomes `SUBMITTED_ON_TIME`. One already `OVERDUE` or `DELINQUENT` becomes `SUBMITTED_LATE`. Even a `DEFAULTED` obligation can be cured late, and that late cure is what makes reinstatement possible. Every submission stamps `submitted_at` from the clock. While the rating is `PUBLISHED`, a submission also schedules the next annual period as described above; while the rating is `WITHDRAWN`, no new period is created. An obligation already resting in `SUBMITTED_ON_TIME` or `SUBMITTED_LATE` accepts no further submission, refusing with `ERR_OBLIGATION_STATE_INVALID`. Each submission recomputes the rating's posture while the rating remains `PUBLISHED`, and a cure out of `DEFAULTED` recomputes the issuer's `delinquent_flag`.

Each published rating carries a **surveillance posture**, a parallel state axis that evolves independently of the publication axis. The posture derives from the rating's obligations in open states: it is `DELINQUENT` when any obligation is `DELINQUENT`; otherwise `GRACE` when any obligation is `OVERDUE`; otherwise `CURRENT`. The posture freezes the moment the rating leaves `PUBLISHED` — a withdrawn rating keeps whatever posture it last held, typically `DELINQUENT`.

Every advance of the logical clock runs the non-disclosure sweep in a pinned evaluation order, which resolves the circular-looking dependency between posture and withdrawal deterministically. First, the sweep walks every obligation of every `PUBLISHED` rating in `created_at` ascending order and applies the thresholds in sequence: a `PENDING` obligation whose `due_at` is strictly behind the clock flips to `OVERDUE`; an `OVERDUE` obligation more than 30 days past its `due_at` flips to `DELINQUENT` and logs an `OBLIGATION_DELINQUENT` notification; a `DELINQUENT` obligation more than 60 days past its `due_at` flips to `DEFAULTED` and sets the issuer's `delinquent_flag` true — a flag the intermediate `DELINQUENT` hop does not touch. A single clock jump walks one obligation through as many flips as its thresholds allow, in that order, within the same sweep. Second, for every obligation that flipped to `DEFAULTED`, the sweep withdraws its rating: the rating moves `PUBLISHED` → `WITHDRAWN` with `withdraw_reason` `NON_DISCLOSURE`, `withdrawn_at` stamped from the clock, the current notch frozen into `notch_at_withdrawal`, and a `RATING_WITHDRAWN` notification logged after the delinquency notification. Third, postures are recomputed for ratings still `PUBLISHED`; ratings withdrawn in the same sweep are excluded, keeping their frozen `DELINQUENT` posture. Every sweep comparison is strict: when the clock stands exactly at `due_at`, the obligation remains `PENDING`.

The issuer's `delinquent_flag` stays true while any obligation of any of the issuer's ratings sits in `DEFAULTED`, and it clears once all such obligations have been cured to `SUBMITTED_LATE`. While the flag flies, the issuer may not open new solicited engagements — see `ERR_ISSUER_DELINQUENT` in §3.1.

Between committee cycles, analysts act on published ratings through **rating actions**, available to both `LeadAnalyst` and `SurveillanceOfficer`. The call is OCC-guarded with `expected_rating_version` (§2.6) and carries an `action` of `AFFIRM`, `UPGRADE`, `DOWNGRADE`, or `WITHDRAW`, a required `rationale`, an optional `new_outlook` that updates the rating's outlook when present, and — depending on the action — a `new_notch` or a `withdraw_reason`. An action is permitted only while the rating is `PUBLISHED`, failing otherwise with `ERR_RATING_STATE_INVALID`, and only while `review_pending` is false: a rating with any criteria review item in `PENDING`, `IN_REVIEW`, or `ESCALATED` refuses actions with `ERR_REVIEW_PENDING`.

Each action has its own gate. `AFFIRM` keeps the current notch and is permitted while the posture is `CURRENT` or `GRACE`; against a `DELINQUENT` posture it fails with `ERR_AFFIRM_BLOCKED_BY_POSTURE`. `UPGRADE` is stricter, requiring a `CURRENT` posture and failing otherwise with `ERR_UPGRADE_BLOCKED_BY_POSTURE`. `UPGRADE` and `DOWNGRADE` each move the notch exactly one step on the seven-step scale — one step better or one step worse — and any other `new_notch` is rejected with `ERR_NOTCH_STEP_INVALID`. A successful affirmation, upgrade, or downgrade leaves the rating `PUBLISHED`, appends a `notch_history` entry whose cause is `SURVEILLANCE_ACTION`, logs a `RATING_ACTION` notification, and increments the rating's `version`.

A manual withdrawal is the fourth action. `WITHDRAW` requires a `withdraw_reason` of `ISSUER_REQUEST` or `CRITERIA`; the payload must carry `withdraw_reason` exactly when the action is `WITHDRAW`, on pain of `ERR_INVALID_REQUEST`, and `NON_DISCLOSURE` is reserved to the sweep and never accepted here. Manual withdrawal moves the rating to `WITHDRAWN`, stamps `withdrawn_at`, freezes the current notch into `notch_at_withdrawal` and the posture in place, logs a `RATING_WITHDRAWN` notification, and increments the rating's `version`. The sweep-driven non-disclosure withdrawal described above performs the same state move and logs the same notification after the default flip and the delinquency notification, but carries no version increment.

Reinstatement, performed by a `SurveillanceOfficer`, returns a rating from `WITHDRAWN` to `PUBLISHED` — but only for non-disclosure withdrawals: any other `withdraw_reason` is rejected with `ERR_REINSTATE_NOT_PERMITTED`, and a rating not in `WITHDRAWN` is rejected with `ERR_RATING_STATE_INVALID`. Two further gates apply. The clock must stand no later than 180 days after `withdrawn_at`; later attempts fail with `ERR_REINSTATE_WINDOW_EXPIRED`. And every disclosure obligation of the rating must be resolved — each in `SUBMITTED_ON_TIME` or `SUBMITTED_LATE` — or the reinstatement fails with `ERR_UNRESOLVED_OBLIGATIONS`. A successful reinstatement restores `notch` from `notch_at_withdrawal`, recomputes the posture to `CURRENT`, schedules the next annual disclosure period when no obligation of the rating remains in an open state (`PENDING`, `OVERDUE`, `DELINQUENT`, or `DEFAULTED`) — the new period's `period_index` continuing from the last — appends a `notch_history` entry whose cause is `REINSTATEMENT`, logs a `RATING_REINSTATED` notification, and increments the rating's `version`.

### 3.6. Criteria Governance and Portfolio-Wide Reviews

Criteria versions are the agency's published methodology, scoped to a jurisdiction and a credit family. A `SurveillanceOfficer` drafts one with a `jurisdiction_code`, a `credit_type`, a human-readable `version_label` such as GO-2026.2, and the six factor weights `w_economy`, `w_management`, `w_budgetary_performance`, `w_flexibility`, `w_liquidity`, and `w_debt_profile`, which must sum to exactly 1.000 — any other total is rejected with `ERR_WEIGHT_SUM_INVALID`. A new version is `DRAFT` with `activated_at` null.

Activation, again a `SurveillanceOfficer` act, moves a version `DRAFT` → `ACTIVE`, stamps `activated_at` from the clock, and increments the version's own `version`; activating anything not `DRAFT` fails with `ERR_CRITERIA_VERSION_STATE_INVALID`. At most one version is `ACTIVE` per jurisdiction-and-credit segment: the activation supersedes the segment's prior `ACTIVE` version, moving it to the terminal `SUPERSEDED` state. Sessions and scorecards keep their pinned versions regardless — activation never re-points work already scheduled or scored.

The activation's far reach is the portfolio review. When a prior `ACTIVE` version existed for the segment, activation walks every `PUBLISHED` rating whose `jurisdiction_code` and `credit_type` match — regardless of which criteria version the rating was originally pinned to, because the review is portfolio-wide — in order of the rating's `published_at` ascending, ties broken by `created_at` ascending, and for each one creates a `CriteriaReviewItem` in `PENDING` whose `criteria_version_id` names the newly activated version, whose `due_at` is 90 days after that version's `activated_at`, sets the rating's `review_pending` true, and logs a `REVIEW_OPENED` notification to the rating's issuer. The very first activation of a segment — one with no prior `ACTIVE` version — creates no review items at all.

Review work is driven by a `SurveillanceOfficer`. Beginning a review moves an item `PENDING` → `IN_REVIEW`, or `ESCALATED` → `IN_REVIEW`; beginning from any other state fails with `ERR_REVIEW_ITEM_STATE_INVALID`. Meanwhile the clock sweep escalates any `PENDING` item whose `due_at` is strictly behind the clock to `ESCALATED` — items already `IN_REVIEW` are exempt from escalation — and while any item on any rating of an issuer sits in `ESCALATED`, committee scheduling for that issuer's engagements is blocked, as §3.3 describes.

Completing a review requires the item to be `IN_REVIEW` and takes an `outcome` of `NO_ACTION` or `RATING_ACTION` together with a `rationale`. `NO_ACTION` closes the item `IN_REVIEW` → `COMPLETED_NO_ACTION`. `RATING_ACTION` additionally requires a `new_notch` — without one the completion fails with `ERR_REVIEW_OUTCOME_NOTCH_REQUIRED` — and closes the item `IN_REVIEW` → `COMPLETED_RATING_ACTION`, records the notch as the item's `outcome_notch` (null on a no-action completion), applies it to the rating's `notch`, appends a `notch_history` entry whose cause is `CRITERIA_REVIEW`, and increments the rating's `version`. Either completion stamps `completed_at` from the clock, recomputes the rating's `review_pending` — true while any of its items remains `PENDING`, `IN_REVIEW`, or `ESCALATED` — logs a `REVIEW_COMPLETED` notification, and increments the item's `version`.

### 3.7. Borrowing Cost at Sale

Because a rating prices debt, the API computes the carrying cost of a prospective bond sale. An `Issuer` or an `Underwriter` prices a sale by naming the `issuer_id`, the `rating_id` of a rating belonging to that same issuer — a rating of a different issuer is rejected with `ERR_NOT_RESOURCE_OWNER` — a `par_amount_cents` that must be greater than zero, a `maturity_years` from 1 to 30, the expected `sale_date`, and a `pricing_mode`. Violations of these numeric and structural bounds fail with `ERR_INVALID_REQUEST`.

The pricing mode selects which notch prices the sale. `PROVISIONAL` prices off the indicative notch on the scorecard of the rating's engagement — the pre-committee estimate — and is available whether the rating is `ASSIGNED` or `PUBLISHED`. `FINAL` prices off the rating's current published notch, reflecting every post-publication action, and requires the rating to be `PUBLISHED`; otherwise it fails with `ERR_RATING_STATE_INVALID`.

The effective yield is a benchmark of 300 basis points plus a spread keyed by the pricing notch: 25 basis points for `AAA`, 45 for `AA`, 90 for `A`, 150 for `BBB`, 325 for `BB`, 600 for `B`, and 900 for `CCC`; the resulting yield is stored as `effective_yield_bps`. Annual interest is the par amount multiplied by the effective yield in basis points and divided by 10000, rounded half-up to whole cents and stored as `annual_interest_cents`. The rounding order is pinned: each year's interest is rounded to whole cents first, and only then is that rounded annual figure multiplied by `maturity_years` to give `total_interest_cents`. The alternative order — multiplying the exact annual figure by the years and rounding once at the end — is forbidden: a par of 1000000008 cents at a yield of 625 basis points over 3 years produces a `total_interest_cents` of 187500003, not 187500002.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource — registering an issuer or an underwriter, opening an engagement, drafting a criteria version, scheduling a committee session, casting a ballot, filing an appeal, pricing a bond sale — answer `201 Created`. Operations that modify an existing resource answer `200 OK`, as do all reads and the logical-clock advance. Every business endpoint lives under the `/muni` prefix; the logical-clock endpoint is a platform endpoint mounted outside it. Read endpoints are available to every declared role and are marked "Any authenticated role" below; mutating endpoints name their admitted roles exactly. Request payloads, side effects, and preconditions for each operation are specified by the narratives in §2 and §3 rather than restated here.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the server logical clock and run the full time-driven sweep | PlatformAdmin |
| POST | `/muni/issuers` | Register a municipal issuer | PlatformAdmin |
| GET | `/muni/issuers` | List issuers | Any authenticated role |
| GET | `/muni/issuers/{id}` | Get one issuer | Any authenticated role |
| GET | `/muni/issuers/{id}/notifications` | List an issuer's notification log in emission order | Any authenticated role |
| POST | `/muni/underwriters` | Register an underwriter | PlatformAdmin |
| GET | `/muni/underwriters/{id}` | Get one underwriter | Any authenticated role |
| POST | `/muni/engagements` | Open a rating engagement, solicited or unsolicited | Issuer, Underwriter, LeadAnalyst |
| GET | `/muni/engagements` | List engagements with filters | Any authenticated role |
| GET | `/muni/engagements/{id}` | Get one engagement | Any authenticated role |
| POST | `/muni/engagements/{id}/accept-terms` | Accept engagement terms and settle the fee | Issuer |
| POST | `/muni/engagements/{id}/documents` | Submit one information document by code | Issuer, LeadAnalyst |
| POST | `/muni/engagements/{id}/withdraw` | Withdraw a solicited engagement before rating assignment | Issuer |
| POST | `/muni/engagements/{id}/scorecard` | Submit or supersede the analytical scorecard (OCC-guarded) | LeadAnalyst |
| GET | `/muni/engagements/{id}/scorecard` | Get the engagement's current scorecard (array of 0 or 1) | Any authenticated role |
| GET | `/muni/criteria-versions/{id}/scorecards` | List scorecards computed under a criteria version | Any authenticated role |
| POST | `/muni/criteria-versions` | Create a jurisdiction-specific criteria version | SurveillanceOfficer |
| GET | `/muni/criteria-versions` | List criteria versions with filters | Any authenticated role |
| GET | `/muni/criteria-versions/{id}` | Get one criteria version | Any authenticated role |
| POST | `/muni/criteria-versions/{id}/activate` | Activate a criteria version, superseding the prior active one and fanning out portfolio reviews | SurveillanceOfficer |
| POST | `/muni/engagements/{id}/committee-sessions` | Schedule a rating committee session | CommitteeChair |
| GET | `/muni/committee-sessions` | List committee sessions with filters | Any authenticated role |
| GET | `/muni/committee-sessions/{id}` | Get one committee session | Any authenticated role |
| POST | `/muni/committee-sessions/{id}/open` | Open a scheduled session inside its window | CommitteeChair |
| POST | `/muni/committee-sessions/{id}/votes` | Cast a vote or a recusal | CommitteeMember |
| GET | `/muni/committee-sessions/{id}/votes` | List the votes of a session | Any authenticated role |
| POST | `/muni/committee-sessions/{id}/alternates` | Appoint an alternate voter for a recused seat | CommitteeChair |
| POST | `/muni/committee-sessions/{id}/close` | Close and tally the session | CommitteeChair |
| GET | `/muni/ratings` | List ratings with filters, in insertion order | Any authenticated role |
| GET | `/muni/ratings/{id}` | Get one rating | Any authenticated role |
| POST | `/muni/ratings/{id}/publish` | Publish an assigned rating after the appeal window has elapsed | LeadAnalyst |
| POST | `/muni/ratings/{id}/actions` | Post a surveillance rating action (OCC-guarded) | LeadAnalyst, SurveillanceOfficer |
| POST | `/muni/ratings/{id}/reinstate` | Reinstate a non-disclosure-withdrawn rating | SurveillanceOfficer |
| POST | `/muni/ratings/{id}/appeals` | File a pre-publication appeal citing new information | Issuer |
| GET | `/muni/ratings/{id}/appeals` | List the appeals for a rating (0 or 1) | Any authenticated role |
| GET | `/muni/appeals/{id}` | Get one appeal | Any authenticated role |
| POST | `/muni/appeals/{id}/decide` | Decide an appeal | CommitteeChair |
| GET | `/muni/ratings/{id}/disclosure-obligations` | List a rating's disclosure obligations in period order | Any authenticated role |
| GET | `/muni/disclosure-obligations/{id}` | Get one disclosure obligation | Any authenticated role |
| POST | `/muni/disclosure-obligations/{id}/submit` | Submit the periodic financial disclosure | Issuer |
| POST | `/muni/bond-sales` | Price a bond sale against a rating of the same issuer | Issuer, Underwriter |
| GET | `/muni/bond-sales` | List bond sales with filters | Any authenticated role |
| GET | `/muni/bond-sales/{id}` | Get one bond sale | Any authenticated role |
| GET | `/muni/review-items` | List portfolio review items in fan-out order | Any authenticated role |
| GET | `/muni/review-items/{id}` | Get one review item | Any authenticated role |
| POST | `/muni/review-items/{id}/begin` | Begin a review | SurveillanceOfficer |
| POST | `/muni/review-items/{id}/complete` | Complete a review with an outcome | SurveillanceOfficer |

## 5. Error Code Catalogue

The catalogue fixes each error's identifier and HTTP status; the conditions that trigger each error are specified in the narratives of §2 and §3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_ISSUER_NOT_FOUND` | 404 Not Found |
| `ERR_UNDERWRITER_NOT_FOUND` | 404 Not Found |
| `ERR_ENGAGEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_CRITERIA_VERSION_NOT_FOUND` | 404 Not Found |
| `ERR_SESSION_NOT_FOUND` | 404 Not Found |
| `ERR_RATING_NOT_FOUND` | 404 Not Found |
| `ERR_APPEAL_NOT_FOUND` | 404 Not Found |
| `ERR_OBLIGATION_NOT_FOUND` | 404 Not Found |
| `ERR_BOND_SALE_NOT_FOUND` | 404 Not Found |
| `ERR_REVIEW_ITEM_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_PAGINATION_PARAMETERS` | 400 Bad Request |
| `ERR_ENGAGEMENT_STATE_INVALID` | 409 Conflict |
| `ERR_SESSION_STATE_INVALID` | 409 Conflict |
| `ERR_RATING_STATE_INVALID` | 409 Conflict |
| `ERR_APPEAL_STATE_INVALID` | 409 Conflict |
| `ERR_OBLIGATION_STATE_INVALID` | 409 Conflict |
| `ERR_REVIEW_ITEM_STATE_INVALID` | 409 Conflict |
| `ERR_CRITERIA_VERSION_STATE_INVALID` | 409 Conflict |
| `ERR_WITHDRAWAL_NOT_PERMITTED` | 409 Conflict |
| `ERR_REINSTATE_NOT_PERMITTED` | 409 Conflict |
| `ERR_STALE_ENGAGEMENT_VERSION` | 412 Precondition Failed |
| `ERR_STALE_RATING_VERSION` | 412 Precondition Failed |
| `ERR_ANALYST_VOTE_FORBIDDEN` | 403 Forbidden |
| `ERR_RECUSED_VOTER_VOTE_FORBIDDEN` | 403 Forbidden |
| `ERR_VOTER_NOT_ELIGIBLE` | 403 Forbidden |
| `ERR_APPEAL_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_SESSION_NOT_OPENABLE` | 409 Conflict |
| `ERR_PUBLISH_WINDOW_NOT_ELAPSED` | 409 Conflict |
| `ERR_REINSTATE_WINDOW_EXPIRED` | 422 Unprocessable Entity |
| `ERR_VOTER_POOL_INVALID` | 422 Unprocessable Entity |
| `ERR_VOTE_KIND_AMBIGUOUS` | 422 Unprocessable Entity |
| `ERR_WEIGHT_SUM_INVALID` | 422 Unprocessable Entity |
| `ERR_FACTOR_SCORE_OUT_OF_RANGE` | 422 Unprocessable Entity |
| `ERR_DOCUMENT_CODE_UNKNOWN` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_DOCUMENT` | 409 Conflict |
| `ERR_DUPLICATE_COMMITTEE_VOTE` | 409 Conflict |
| `ERR_APPEAL_ALREADY_EXISTS` | 409 Conflict |
| `ERR_NO_NEW_INFORMATION` | 422 Unprocessable Entity |
| `ERR_NO_ACTIVE_CRITERIA` | 422 Unprocessable Entity |
| `ERR_SESSION_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_SESSION_COOLING_OFF` | 409 Conflict |
| `ERR_ALTERNATE_NOT_PERMITTED` | 409 Conflict |
| `ERR_AFFIRM_BLOCKED_BY_POSTURE` | 409 Conflict |
| `ERR_UPGRADE_BLOCKED_BY_POSTURE` | 409 Conflict |
| `ERR_REVIEW_PENDING` | 409 Conflict |
| `ERR_ESCALATED_REVIEW_BLOCKS_SCHEDULING` | 409 Conflict |
| `ERR_ISSUER_DELINQUENT` | 409 Conflict |
| `ERR_UNRESOLVED_OBLIGATIONS` | 409 Conflict |
| `ERR_NOTCH_STEP_INVALID` | 422 Unprocessable Entity |
| `ERR_REVIEW_OUTCOME_NOTCH_REQUIRED` | 422 Unprocessable Entity |
| `ERR_APPEAL_PENDING` | 409 Conflict |
| `ERR_FEE_PAYMENT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_ISSUER_CREDIT` | 422 Unprocessable Entity |
