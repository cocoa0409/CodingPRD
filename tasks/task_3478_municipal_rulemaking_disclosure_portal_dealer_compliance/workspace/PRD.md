# Municipal Rulemaking, Disclosure Portal & Dealer Compliance API — Product Requirements Document

## 1. Introduction

This document specifies the Municipal Rulemaking, Disclosure Portal & Dealer Compliance API, the system of record for a municipal securities rulemaking board. The platform serves three intertwined mandates. First, it governs the rule-development process itself: staff draft proposed rule changes for dealers and municipal advisors, open them for public comment, and shepherd them through regulatory decision, with approved rules taking effect only after a defined effectiveness delay. Second, it operates the public disclosure portal: issuers and obligated persons file official statements, annual financial continuing disclosures, event notices, and voluntary documents, all of which are reviewed by portal staff and then disseminated to the public free of charge alongside municipal trade data. Third, it underwrites dealer and advisor compliance: trade reporting with strict time limits and price-transparency banding, professional qualification examinations and continuing education for municipal professionals, market data products under subscriber licensing, enforcement referrals routed to the correct examining authority with published rule-interpretation guidance, and a fiduciary standard applied to advisor solicitation activity.

The system is built around a logical clock rather than the wall clock, so that comment windows, effectiveness delays, reporting deadlines, retake exclusions, and continuing-education cycles are all deterministic and testable. Readers implementing this API should treat Section 2 as the structural contract — response envelopes, pagination, validation ordering, concurrency control — and Section 3 as the business narrative from which the behavior of each workflow is reconstructed. Endpoint paths are collected in Section 4; the error catalogue, without conditions, appears in Section 5. Trigger conditions for every error are stated in the narrative where they naturally arise.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring their operational capacity. A request in which either header is missing or blank is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The system recognizes eleven roles, spelled exactly as follows: `SystemAdmin`, `RulemakingOfficer`, `Regulator`, `PortalOperator`, `ComplianceOfficer`, `ExamAdmin`, `LicensingOfficer`, `IssuerRep`, `DealerRep`, `MarketDataSubscriber`, and `PublicReader`. Access to every operation is restricted by role; an attempt to perform an action outside the caller's designated role is rejected with `ERR_UNAUTHORIZED` (HTTP 403). `PublicReader` is the free public-access role: it is an ordinary role value carried in the same two headers, not an exemption from supplying them.

The roles and their charters are:

- `SystemAdmin` — platform operator for the logical clock; its only operation is the test-driving clock surface.
- `RulemakingOfficer` — rule-development staff; drafts rule proposals and shepherds them through comment and submission.
- `Regulator` — the approving authority; decides submitted rule proposals, and is segregated from the submitting officer.
- `PortalOperator` — disclosure-portal operations staff; registers organizations, moderates comment letters, and reviews disclosure submissions.
- `ComplianceOfficer` — enforcement staff; suspends organizations, manages professional standing, and opens and advances enforcement referrals.
- `ExamAdmin` — qualification administrator; registers municipal professionals and records exam attempts and continuing-education credits.
- `LicensingOfficer` — market-data licensing staff; creates and advances data subscriptions.
- `IssuerRep` — filing representative of an issuer or obligated-person organization.
- `DealerRep` — operations representative of a broker-dealer or municipal-advisor organization.
- `MarketDataSubscriber` — a licensed data subscriber principal.
- `PublicReader` — public access; submits comment letters and reads published disclosures and disseminated trades.

Two of these roles are entity-backed. When `X-User-Role` is `IssuerRep`, `X-User-ID` is the `id` of the acting `Organization`; ownership checks on any resource that references an `Organization` compare the resource's foreign-key field to `X-User-ID` — for a filing, the payload's `issuer_org_id` must equal it. When `X-User-Role` is `DealerRep`, `X-User-ID` is likewise the `id` of the acting `Organization`; ownership checks compare `dealer_org_id` on a trade report, `advisor_org_id` on a solicitation record, and the owning organization of a scoped listing to `X-User-ID`. Every other role is opaque: when `X-User-Role` is `SystemAdmin`, `RulemakingOfficer`, `Regulator`, `PortalOperator`, `ComplianceOfficer`, `ExamAdmin`, `LicensingOfficer`, `MarketDataSubscriber`, or `PublicReader`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `submitted_by_user_id` or `decided_by_user_id` on a rule proposal, or as `created_by_user_id` and `closed_by_user_id` on an enforcement referral) but does not compare it to any entity's `id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items from the front of the result set and defaults to 0. Unless otherwise specified, every list endpoint returns its resources sorted by creation timestamp in ascending order. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and Epoch Processing

All temporal rules in this system — comment windows, effectiveness delays, reporting deadlines, examination retake exclusions, continuing-education cycles, and the trailing late-report window — are evaluated against a single server-held **logical clock**, never against the wall clock. Before any clock-setting call has been made, the logical clock starts at exactly `2026-09-01T00:00:00Z`. All business resources are mounted under the `/msrb` prefix; the clock-setting capability is deliberately mounted outside that prefix, is restricted to `SystemAdmin`, and advances the logical clock to a caller-supplied `to_iso8601` instant. The clock is monotonic: `to_iso8601` must be at least the current logical time, and a request to move it strictly backwards is rejected with `ERR_CLOCK_REGRESSION` (HTTP 422). A successful clock set returns the new `current_utc` together with an integer `epoch_effects` count describing how many state changes the pass applied.

Every clock set triggers a single **epoch pass** whose steps run in a pinned order. First, the system effectuates rule proposals: every `APPROVED` proposal whose `effective_at` is at or before the new current time transitions to `EFFECTIVE`, processed in order of `effective_at` ascending with ties broken by `created_at` ascending, and each effectuation runs the supersession cascade described in §3.2. Second, continuing-education transitions are applied to municipal professionals — `QUALIFIED` to `CE_DUE` when the current time has reached `ce_cycle_end`, and `CE_DUE` to `LAPSED` when it has reached `ce_grace_end` — processed in order of `ce_cycle_end` ascending with ties broken by `created_at` ascending. Third, every organization's late-report tally and compliance posture are recomputed as described in §3.5, with organizations processed in order of `created_at` ascending, applying the pending-subscription rejection cascade wherever a posture degrades. Ties within any epoch step are broken by `created_at` ascending, never by identifier.

### 2.5. Validation Order and First-Failure Semantics

Every request is validated against an ordered battery of checks, and the first failing check determines the error returned — later checks are not consulted. The fixed order is:

1. **Authentication.** `X-User-ID` and `X-User-Role` must both be present and non-blank, on every endpoint (HTTP 401).
2. **Authorization and ownership.** The named role must be listed for the endpoint, and for entity-backed roles the ownership comparison of §2.1 must hold: an `IssuerRep` may act only on its own `issuer_org_id`, a `DealerRep` only on its own `dealer_org_id` or `advisor_org_id` (and, for a cancellation, only on a trade whose `dealer_org_id` matches) (HTTP 403).
3. **Request schema.** Required fields present, types correct, enum values within their declared sets, unknown fields ignored, and domain ranges enforced: `cusip` exactly nine characters, `par_amount` greater than zero, `price` greater than zero, `seats` at least one, `score` between 0 and 100 inclusive, `compensation_cents` at least zero, `action`, `decision`, `outcome`, `to_state`, and `standing` inside their input enums, an `ANNUAL_FINANCIAL` filing carrying `period_start` strictly before `period_end`, an event notice's `event_occurred_at` not in the future, and `to_state` equal to `REJECTED` refused on the subscription-advance operation (HTTP 400). One dedicated successor check follows immediately: an `EVENT_NOTICE` filing submitted without its `event_category` is rejected with `ERR_EVENT_CATEGORY_REQUIRED` (HTTP 422).
4. **Path existence.** Path identifiers must resolve to existing resources, validated left to right, each with its own not-found error (HTTP 404); a resource outside the caller's visibility scope is reported as not-found rather than forbidden.
5. **Body-referenced existence.** Organizations, professionals, and proposals referenced from request bodies (`employer_org_id`, `issuer_org_id`, `dealer_org_id`, `advisor_org_id`, `licensee_org_id`, `professional_id`, `subject_org_id`, `subject_professional_id`, `supersedes_proposal_id`) must exist (HTTP 404), and a referral's `rule_code` must match an existing rule proposal's `rule_code` (`ERR_RULE_NOT_FOUND`, HTTP 404).
6. **Segregation of duties.** A `Regulator` must not decide a proposal they submitted, and a `ComplianceOfficer` must not close a referral they created (`ERR_SEGREGATION_OF_DUTIES`, HTTP 403).
7. **Generic state preconditions.** The target resource's state machine must permit the attempted transition — deciding a proposal that is not `PENDING_APPROVAL`, moderating a letter that is already terminal, cancelling a `CANCELLED` trade, advancing a `TERMINATED` or `REJECTED` subscription, editing a proposal outside `DRAFT` and `DISAPPROVED`, recording credits while `UNQUALIFIED` or `LAPSED`, advancing a closed referral (`ERR_INVALID_STATE`, HTTP 409).
8. **Specific state gates, in their pinned relative order.** A comment letter requires its proposal to be `OPEN_FOR_COMMENT` (`ERR_PROPOSAL_NOT_OPEN_FOR_COMMENT`, HTTP 409); a submission for approval requires zero unresolved comment letters (`ERR_UNRESOLVED_COMMENTS`, HTTP 409); organization-dependent operations require the referenced organization to be `ACTIVE` (`ERR_ORG_SUSPENDED`, HTTP 409); an exam attempt requires the professional's `standing` to be `ACTIVE` (`ERR_INVALID_STATE`, HTTP 409).
9. **Safety and temporal gates, in order.** The fiduciary compensation disclosure (`ERR_DISCLOSURE_REQUIRED`); the comment-window-closed check (`ERR_COMMENT_WINDOW_CLOSED`); the comment-period length bound (`ERR_COMMENT_PERIOD_TOO_SHORT`); the comment-period-still-open check (`ERR_COMMENT_PERIOD_STILL_OPEN`); the examination retake window (`ERR_RETAKE_WINDOW_ACTIVE`); the trade-time check (`ERR_TRADE_TIME_INVALID`); and clock monotonicity (`ERR_CLOCK_REGRESSION`) (all HTTP 422).
10. **Referential and fiscal gates, in order.** Organization type gates (`ERR_ORG_TYPE_NOT_PERMITTED`); the single-subject requirement (`ERR_AMBIGUOUS_SUBJECT`); the cited rule must be `EFFECTIVE` (`ERR_RULE_NOT_EFFECTIVE`); the annual coverage-overlap check (`ERR_COVERAGE_PERIOD_OVERLAP`, HTTP 409); the fiduciary fee cap (`ERR_FEE_CAP_EXCEEDED`); and, last of all, market-data product licensing (`ERR_PRODUCT_NOT_LICENSED`, HTTP 403).

Because of this ordering, for example, a comment letter filed on a proposal that was never opened reports `ERR_PROPOSAL_NOT_OPEN_FOR_COMMENT` even if its window would also have ended, and a solicitation failing both fiduciary gates reports the missing disclosure before the fee cap.

### 2.6. Optimistic Concurrency Control

Exactly one operation is guarded by optimistic concurrency control: revising a rule proposal — `PATCH /msrb/rule-proposals/{id}` — requires the client to present a non-optional `expected_rule_proposal_version` field carrying the `version` of the proposal it last observed. If the presented value does not match the proposal's current `version` — for example because another edit, an open-comment-period, or a decision has advanced the proposal since the client last read it — the write is rejected as stale with `ERR_STALE_VERSION` (HTTP 412), preventing the client from overwriting state it has not observed. Editing a draft twice is legitimate product behavior, so this is resolved purely by the version check rather than by any state precondition. No other endpoint accepts a version field.

### 2.7. Nested Path Resolution and Scoped Visibility

Requests that target nested resources resolve path identifiers sequentially, left to right, and the first identifier that fails to resolve determines the not-found error. A comment-letter operation under an unknown proposal reports `ERR_PROPOSAL_NOT_FOUND` before the letter itself is ever consulted; an unknown letter under a known proposal reports `ERR_COMMENT_NOT_FOUND`. Each resource family carries its own not-found error identifier: `ERR_ORG_NOT_FOUND` for organizations, `ERR_PROPOSAL_NOT_FOUND` for rule proposals, `ERR_COMMENT_NOT_FOUND` for comment letters, `ERR_SUBMISSION_NOT_FOUND` for disclosure submissions, `ERR_PROFESSIONAL_NOT_FOUND` for municipal professionals, `ERR_TRADE_NOT_FOUND` for trade reports, `ERR_SUBSCRIPTION_NOT_FOUND` for data subscriptions, and `ERR_REFERRAL_NOT_FOUND` for enforcement referrals.

Visibility scoping is applied as part of this resolution. An `IssuerRep` sees only its own organization's disclosure submissions; a `DealerRep` sees only its own organization's trade reports and solicitation records; a `PublicReader` sees only `PUBLISHED` disclosure submissions and `DISSEMINATED` trade reports, reflecting the portal's free public access mandate. `PortalOperator` and `ComplianceOfficer` see all submissions and trades. A single-resource read that exists but falls outside the caller's scope is reported as not-found — `ERR_SUBMISSION_NOT_FOUND` or `ERR_TRADE_NOT_FOUND` — never as a permission error, so that scoped callers cannot probe for the existence of other organizations' filings. The same scoping narrows list results silently.

### 2.8. Common Resource Properties

Every primary resource carries a standard set of system-managed properties:

- `id` — a server-minted UUID with no type prefix, unique across the system.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created.
- `updated_at` — an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` — a system-managed integer that increments by exactly one on every mutation of the resource, including mutations caused by system cascades and epoch processing.

Two record families are deliberately append-only and deviate from this convention: an `ExamAttempt` and a `SolicitationRecord` each carry only `id` and `created_at`; both `updated_at` and `version` are absent on them, because neither record is ever modified after creation. Derived-field recomputation on a resource — for example an organization's recalculated counters — counts as a mutation of that resource for `updated_at` and `version` purposes only where the narrative in §3 says the resource is mutated; the derived counters themselves are always current when read.

### 2.9. Units, Precision, and Rounding

Monetary amounts in the licensing domain are integer cents; par amounts on trades are whole dollars with no rounding applied. License fees are rounded by the round-half-up method, applied exactly once at the end of the monthly fee formula; the annual invoice sums twelve individually rounded monthly lines — round per line, then sum — and never rounds a single unrounded annual total. Trade timeliness is measured in whole seconds against a fifteen-minute (900-second) reporting limit. Event-notice timeliness is measured in whole calendar days between UTC calendar dates. Continuing-education credits are decimal numbers, and their thresholds are inclusive. Datetime comparisons throughout the system are exact, and day arithmetic on timestamps is exact ISO 8601 UTC arithmetic. Enum fields accept exactly the strings named in §3 and §4 narratives — no other spellings are valid.

## 3. Business Logic & Workflows

### 3.1. Drafting Rules, Opening Comment Windows, and the Decision Gate

A rule change begins when a `RulemakingOfficer` registers a **rule proposal** with a public `rule_code` (such as "G-42", unique across all proposals and later cited verbatim by enforcement referrals), a `title`, the full rule text as `body`, and a `category` of exactly one of `DEALER_CONDUCT`, `ADVISOR_CONDUCT`, `DISCLOSURE`, `TRADE_REPORTING`, `MARKET_DATA`, or `QUALIFICATION`. A proposal is born in `DRAFT` with its `comment_round` at 0 and its `expedited` flag false. At creation the officer may also declare an optional `supersedes_proposal_id` naming another proposal this one will eventually replace; when the new proposal later reaches `EFFECTIVE`, the referenced proposal is superseded as described in §3.2. The proposal roster can be listed with optional `status`, `category`, and `supersedes_proposal_id` filters.

While a proposal is in `DRAFT`, a `RulemakingOfficer` may revise its `title`, `body`, or `category`, and it stays in `DRAFT`. Revising a proposal carries the optimistic-concurrency obligation of §2.6: the request must present `expected_rule_proposal_version` matching the proposal's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). Editing is legal only in `DRAFT` and `DISAPPROVED`; an edit attempted in any other state is rejected with `ERR_INVALID_STATE` (HTTP 409). A successful revision of a `DISAPPROVED` proposal reopens it as a draft — the revision cycle — and in doing so clears `submitted_by_user_id`, `decided_by_user_id`, and `decision_reason`, so the reworked proposal re-enters the pipeline with a clean decision history. Every successful edit increments the proposal's `version` by one.

When the draft is ready for public input, a `RulemakingOfficer` opens a comment period by supplying `comment_period_days` — the length of the comment window in days, which must be at least 21 and at most 90, with anything outside that range rejected as `ERR_COMMENT_PERIOD_TOO_SHORT` (HTTP 422) — and may optionally set the `expedited` flag (defaulting to false) that selects the faster effectiveness variant described in §3.2. Opening records `comment_window_start` as the current logical time and derives `comment_window_end` as the start plus the stated number of days; the window is half-open, accepting comments strictly before the end instant. The `comment_round` counter, 0 at creation, is set to 1 by the first opening and increments by one on every subsequent `DRAFT` → `OPEN_FOR_COMMENT` transition after a revision cycle, so readers can tell a first-time comment round from a re-opened one. The opening increments the proposal's `version`.

While a proposal is `OPEN_FOR_COMMENT`, any member of the public — acting as `PublicReader` — may file a **comment letter** carrying an `author_name`, a non-empty `body`, and a declared `sentiment` of `SUPPORT`, `OPPOSE`, or `NEUTRAL`. Each letter is born in `RECEIVED` status attached to its proposal via `proposal_id`. Two gates guard filing, in the order fixed by §2.5: the proposal must currently be `OPEN_FOR_COMMENT` — a filing against a proposal in any other status is rejected with `ERR_PROPOSAL_NOT_OPEN_FOR_COMMENT` (HTTP 409) regardless of whether its window has also ended — and the current logical time must be strictly before `comment_window_end`; at exactly the end instant the window is already closed and the filing is rejected with `ERR_COMMENT_WINDOW_CLOSED` (HTTP 422).

Once the window has run, a `RulemakingOfficer` submits the proposal for regulatory approval. Submission requires the comment window to have ended — the current logical time must be at or after `comment_window_end`, otherwise the request is rejected with `ERR_COMMENT_PERIOD_STILL_OPEN` (HTTP 422) — and, evaluated before that window check per §2.5, it requires that zero comment letters on the proposal remain in `RECEIVED`: every letter must first be moderated per §3.3, and any unmoderated remainder is rejected with `ERR_UNRESOLVED_COMMENTS` (HTTP 409). A successful submission moves the proposal from `OPEN_FOR_COMMENT` to `PENDING_APPROVAL`, records the acting officer's header value in `submitted_by_user_id`, and increments the `version`.

The decision belongs to a `Regulator`, who supplies a `decision` of `APPROVE` or `DISAPPROVE`. Segregation of duties is enforced: the deciding regulator's `X-User-ID` must differ from the recorded `submitted_by_user_id`, and a violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). On `APPROVE` the proposal moves to `APPROVED`, the system records `decided_by_user_id` and stamps `approval_at` with the current logical time, and computes `effective_at` per §3.2. On `DISAPPROVE` the proposal moves to `DISAPPROVED` and the optional `reason` supplied with the decision is recorded as `decision_reason`; a disapproval does not end the rule's life — the revision cycle above carries it back to `DRAFT`. Either decision increments the proposal's `version`. A decision attempted on a proposal that is not `PENDING_APPROVAL` is rejected with `ERR_INVALID_STATE`.

### 3.2. Effectiveness Delays, Supersession, and the Rule-Review Flag

Approval does not make a rule immediately effective. The system computes `effective_at` as `approval_at` plus thirty days for a standard rulemaking, or `approval_at` plus ten days when the proposal's `expedited` flag is true — for two proposals approved at the same instant, the expedited one becomes effective twenty days earlier. The choice between the two variants is fixed at comment-opening time by the `expedited` input of §3.1, not at decision time.

Effectiveness itself is conferred by the epoch pass of §2.4: when the logical clock reaches or passes a proposal's `effective_at`, the proposal transitions from `APPROVED` to `EFFECTIVE`, with due proposals processed oldest-effective-first. If the newly effective proposal declared a `supersedes_proposal_id` and the referenced proposal is currently `EFFECTIVE`, that referenced proposal transitions from `EFFECTIVE` to `SUPERSEDED` in the same pass — the only way a proposal reaches the terminal `SUPERSEDED` state is through this cascade. Both the newly effective proposal's and the superseded proposal's `version` increment by one.

Supersession has a downstream compliance consequence. Every enforcement referral that cites the superseded proposal's `rule_code` and is still in `OPEN` or `REFERRED` status has its `needs_rule_review` flag set to true, signalling that the interpretation basis of the referral has changed. The flag stays true until the referral closes; referrals already closed are untouched. A proposal that is superseded never returns, and a proposal's own effectiveness is never revoked by the clock.

### 3.3. Comment Moderation and the Public Record

Comment letters accumulate in `RECEIVED` until a `PortalOperator` moderates them — the moderation work queue is the proposal's letter listing, filterable by `status`. Moderation supplies an `action` of `PUBLISH` or `DISMISS`. Publishing moves the letter from `RECEIVED` to `PUBLISHED`, making it part of the public record of the rulemaking. Dismissal moves it from `RECEIVED` to `DISMISSED` and requires a `reason` input; the reason is recorded as the letter's `moderation_reason`, and a dismissal without one is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Both `PUBLISHED` and `DISMISSED` are terminal, and moderating a letter that has already reached either state is rejected with `ERR_INVALID_STATE` (HTTP 409). Each moderation increments the letter's `version`. Because §3.1's submission gate counts only letters still in `RECEIVED`, both outcomes clear the proposal's path to approval — what matters is that no letter remains unexamined.

### 3.4. Disclosure Intake, Event Timeliness, and Portal Review

Issuers and obligated persons file disclosure documents through an `IssuerRep`, whose `X-User-ID` must equal the filing organization's `id`: the payload's `issuer_org_id` must match it exactly, and a mismatch is rejected with `ERR_UNAUTHORIZED` (HTTP 403). The referenced organization must be of a filing type — its `org_type` must be `ISSUER` or `OBLIGATED_PERSON`, otherwise `ERR_ORG_TYPE_NOT_PERMITTED` (HTTP 422) — and it must currently be `ACTIVE`, otherwise `ERR_ORG_SUSPENDED` (HTTP 409). Every filing carries a `submission_type` of exactly one of `OFFICIAL_STATEMENT`, `ANNUAL_FINANCIAL`, `EVENT_NOTICE`, or `VOLUNTARY`, a `document_uri` locating the filed document, and a `cusip` issue identifier of exactly nine characters. A submission is born in `RECEIVED` status.

Event notices carry extra structure. When `submission_type` is `EVENT_NOTICE`, the filing must include an `event_category` — one of `PAYMENT_DEFAULT`, `RATING_CHANGE`, `BOND_CALL`, `MERGER_ANNOUNCEMENT`, `MATERIAL_LITIGATION`, or `OTHER` — and a missing category is rejected with `ERR_EVENT_CATEGORY_REQUIRED` (HTTP 422); the category is forbidden on the other three submission types. The filing must also include `event_occurred_at`, the instant the reportable event occurred, which must not lie in the future (a future occurrence is `ERR_INVALID_REQUEST`). On intake the system computes the notice's `timeliness`: it counts the whole calendar days between the UTC calendar date of `event_occurred_at` and the UTC calendar date the filing was received, and classifies the notice `TIMELY` when that count is at most ten — filing on exactly the tenth day is timely — and `LATE` otherwise. Submissions of the other three types always carry a `timeliness` of `NOT_APPLICABLE`.

Annual financial filings carry a different pair of fields: `period_start` and `period_end`, both required, with `period_start` strictly before `period_end`. The portal enforces non-overlapping annual coverage per issuer: a new `ANNUAL_FINANCIAL` submission whose closed coverage interval intersects any sibling `ANNUAL_FINANCIAL` submission of the same issuer in `RECEIVED` or `PUBLISHED` status is rejected with `ERR_COVERAGE_PERIOD_OVERLAP` (HTTP 409). The comparison is closed-interval: two periods that share even a single calendar day overlap, while perfect adjacency — the new period starting the day after the existing period ends — is permitted.

Portal review is performed by a `PortalOperator` supplying an `outcome` of `PUBLISH` or `DEFICIENT`. Publishing moves the submission from `RECEIVED` to `PUBLISHED`, at which point it joins the free public record. Marking a submission deficient requires a `deficiency_reason` input — recorded verbatim on the resource — and an outcome of `DEFICIENT` without one is rejected with `ERR_INVALID_REQUEST`. `PUBLISHED` and `DEFICIENT` are both terminal; reviewing an already-terminal submission is `ERR_INVALID_STATE`. Each review increments the submission's `version`. Submissions can be listed with optional `issuer_org_id`, `status`, and `submission_type` filters, subject to the visibility scoping of §2.7: an `IssuerRep` listing or reading sees only its own organization's filings, a `PublicReader` sees only `PUBLISHED` submissions, and a scoped read of an out-of-scope submission reports `ERR_SUBMISSION_NOT_FOUND`.

### 3.5. Organizations, Trade Reporting, and Dealer Compliance Posture

Every regulated participant is an **organization**, registered by a `PortalOperator` with a unique registrar `org_code`, a legal `name`, and an `org_type` of exactly one of `ISSUER`, `OBLIGATED_PERSON`, `BROKER_DEALER`, or `MUNICIPAL_ADVISOR` — the classification that gates which child workflows may reference it. An organization is born `ACTIVE` with a `compliance_posture` of `CLEAR` and all derived counters — `late_report_count`, `published_par_total`, and `active_professional_count` — at zero. A `ComplianceOfficer` may suspend an organization, supplying a `reason` that is recorded as `suspended_reason`; suspension moves the organization from `ACTIVE` to the terminal `SUSPENDED` state and increments its `version`. Suspension does not cascade to the organization's professionals or subscriptions, but it gates the future: filing disclosures, reporting trades, logging solicitations, sitting examinations (via the employer), and creating or activating data subscriptions all require the referenced organization to be `ACTIVE` and are otherwise rejected with `ERR_ORG_SUSPENDED` (HTTP 409).

Trade reporting is the highest-frequency obligation. A `DealerRep` reports a municipal securities trade for its own firm — the payload's `dealer_org_id` must equal the caller's `X-User-ID`, else `ERR_UNAUTHORIZED` — and the firm must be a `BROKER_DEALER` (any other type is `ERR_ORG_TYPE_NOT_PERMITTED`) and `ACTIVE`. The report carries the traded issue's nine-character `cusip`, a `trade_type` of `INTER_DEALER`, `CUSTOMER_BUY`, or `CUSTOMER_SELL`, a whole-dollar `par_amount` greater than zero, an execution `price` expressed as a percentage of par (for example 101.25) and greater than zero, and the `executed_at` execution timestamp. A report whose `executed_at` lies after the current logical time is rejected with `ERR_TRADE_TIME_INVALID` (HTTP 422).

On receipt the system stamps `reported_at` with the current logical time — identical to the record's `created_at` — and computes the report's timeliness and publication banding. Timeliness: the gap between `reported_at` and `executed_at` is measured in whole seconds, and the report is late only when that gap strictly exceeds the fifteen-minute reporting limit — a gap of exactly 900 seconds is timely. The boolean `late_flag` records the outcome, and `seconds_late` records the gap minus 900 seconds, never below zero. Banding for price transparency: the disseminated size `published_par` is the smaller of `par_amount` and 5,000,000 dollars, and `capped_flag` is true exactly when `par_amount` exceeds 5,000,000 — the public feed suppresses the true size of very large trades while reporting their existence. Every trade report is born `DISSEMINATED`: publication is immediate, not a separate step.

Each new report rolls into its dealer's compliance picture in the same transaction. The organization's `published_par_total` increases by the report's `published_par`. Its `late_report_count` is recomputed as the number of the organization's trade reports that are late, still `DISSEMINATED`, and whose `reported_at` falls inside the trailing thirty-day window — a half-open window in which a report received exactly thirty days ago is excluded, while anything younger counts. The organization's `compliance_posture` becomes `WATCH` when that count reaches five — the fifth late trade inside the window trips the threshold, boundary inclusive — and returns to `CLEAR` when a recomputation finds fewer than five. The tally is recomputed on every trade creation, every trade cancellation, and every epoch pass of §2.4.

A posture degradation has teeth. Whenever a recomputation moves an organization from `CLEAR` to `WATCH`, every data subscription licensed to that organization and still in `PENDING` status transitions to `REJECTED`. `REJECTED` is terminal and is never resurrected: if the tally later improves and the posture returns to `CLEAR`, rejected subscriptions stay rejected, and the licensee must re-apply. A recovery from `WATCH` to `CLEAR` carries no side effects at all.

A trade can be withdrawn only by the reporting dealer itself: cancellation requires the acting `DealerRep`'s `X-User-ID` to equal the trade's `dealer_org_id`, otherwise `ERR_UNAUTHORIZED`. Cancellation moves the trade from `DISSEMINATED` to the terminal `CANCELLED` state and runs the compensating adjustments — the organization's `published_par_total` decreases by the cancelled trade's `published_par`, and the late tally and posture are recomputed, since a cancelled late trade leaves the thirty-day window tally. That recomputation may relax the posture from `WATCH` back to `CLEAR`, but it never resurrects `REJECTED` subscriptions. Cancelling a trade that is already `CANCELLED` is rejected with `ERR_INVALID_STATE`, and each cancellation increments the trade's `version`. Trade reports can be listed with optional `dealer_org_id`, `status`, and `cusip` filters; a `DealerRep` sees only its own organization's reports, a `PublicReader` sees only `DISSEMINATED` reports, and out-of-scope single reads report `ERR_TRADE_NOT_FOUND` per §2.7.

### 3.6. Professional Qualification, Examinations, and Continuing Education

An `ExamAdmin` registers a **municipal professional** with a `full_name`, an `employer_org_id`, and a `professional_class` of `MUNICIPAL_DEALER_REP`, `MUNICIPAL_ADVISOR_REP`, or `MUNICIPAL_PRINCIPAL`. The employing organization must be a `BROKER_DEALER` or `MUNICIPAL_ADVISOR` — any other type is rejected with `ERR_ORG_TYPE_NOT_PERMITTED` — and must be `ACTIVE` at registration time, otherwise `ERR_ORG_SUSPENDED`. A professional's state has two parallel dimensions that evolve independently: `qualification_status`, born `UNQUALIFIED`, and `standing`, born `ACTIVE`. Registration increments the employer organization's `active_professional_count` by one. Professionals can be listed with optional `employer_org_id` and `qualification_status` filters.

Qualification is earned by examination. An `ExamAdmin` records an **exam attempt** naming the sitting `professional_id`, a `series_code` of `MSRB_50`, `MSRB_52`, `MSRB_53`, or `MSRB_54`, and an integer `score` from 0 to 100 inclusive. Three gates precede scoring, in §2.5 order: the professional's employer organization must be `ACTIVE` (`ERR_ORG_SUSPENDED`); the professional's `standing` must be `ACTIVE` — an attempt by a suspended professional is `ERR_INVALID_STATE` (HTTP 409); and the retake exclusion forbids a new attempt on the same professional-and-series pair while an earlier attempt on that pair is strictly younger than thirty days — a prior attempt exactly thirty days old does not block — with a violation rejected as `ERR_RETAKE_WINDOW_ACTIVE` (HTTP 422).

The attempt's `result` is computed against a per-series pass mark with an inclusive boundary: `MSRB_50` passes at a score of at least 70, `MSRB_52` at least 72, `MSRB_53` at least 75, and `MSRB_54` at least 80; anything below is a `FAIL`. Qualification completes when every series required for the professional's class has at least one passing attempt: a `MUNICIPAL_ADVISOR_REP` needs `MSRB_50`; a `MUNICIPAL_DEALER_REP` needs `MSRB_52`; a `MUNICIPAL_PRINCIPAL` needs both `MSRB_53` and `MSRB_54`. The attempt that completes the set automatically moves the professional from `UNQUALIFIED` to `QUALIFIED`: `qualified_at` is stamped with the current logical time, `ce_cycle_end` is derived as exactly 365 days after qualification, `ce_grace_end` as 60 days beyond the cycle end, both continuing-education buckets `ce_credits_total` and `ce_ethics_credits` are reset to zero, and `may_transact` is recomputed. Attempts are an append-only event log — per §2.8 they carry only `id` and `created_at` — listable per professional with an optional `series_code` filter.

Qualification is not permanent. When the epoch pass of §2.4 finds the current time at or beyond a `QUALIFIED` professional's `ce_cycle_end`, the professional moves to `CE_DUE`; when it finds a `CE_DUE` professional at or beyond `ce_grace_end`, the professional moves to `LAPSED`. While `CE_DUE`, the cure is continuing education: an `ExamAdmin` records `credits_total` and `ethics_credits`, which are added into the open cycle's `ce_credits_total` and `ce_ethics_credits` respectively. Credit recording is legal only while the professional is `QUALIFIED` or `CE_DUE` — recording while `UNQUALIFIED` or `LAPSED` is rejected with `ERR_INVALID_STATE`. When, after applying a recording, the open cycle holds at least 12 credits in total **and** at least 2 ethics credits, the professional returns from `CE_DUE` to `QUALIFIED`; the ethics minimum binds independently, so a large general total without the ethics sub-bucket does not cure. Curing satisfies the current cycle only — `qualified_at`, `ce_cycle_end`, and `ce_grace_end` are left unchanged. A professional who reaches `LAPSED` can no longer cure by credits at all: the only way back is to re-pass the full required series set, and only attempts recorded after the lapse timestamp count toward re-qualification, which on completion moves the professional from `LAPSED` to `QUALIFIED` with freshly derived cycle anchors and zeroed credit buckets.

The `standing` dimension is managed separately by a `ComplianceOfficer`, who sets it to `SUSPENDED` or `ACTIVE` (the request also accepts an optional `reason` note). Moving a professional to `SUSPENDED` decrements the employer organization's `active_professional_count` by one; reinstatement to `ACTIVE` increments it back. The two dimensions meet in exactly one derived boolean: `may_transact` is true precisely when `qualification_status` is `QUALIFIED` and `standing` is `ACTIVE`, and it is recomputed on every qualification or standing change. Every mutation of the professional — qualification transition, credit recording, or standing change — increments the professional's `version` by one.

### 3.7. Market Data Licensing, Fee Computation, and Feed Access

Market data is licensed, not given away. A `LicensingOfficer` creates a **data subscription** naming a `product_code` of `TRADE_REALTIME`, `TRADE_HISTORICAL`, or `DISCLOSURE_ARCHIVE`, a `licensee_org_id` whose organization must be `ACTIVE` both at creation and again at activation — otherwise `ERR_ORG_SUSPENDED` — a `subscriber_principal` operator identifier for the subscribing principal, a `license_scope` of `INTERNAL`, `DISPLAY`, or `REDISTRIBUTION`, and a `seats` count of at least one. A subscription is born in `PENDING` with both of its fees computed at creation.

The monthly fee, stored as integer `monthly_fee_cents`, is computed per product and per licensee. The number of billable seats is the requested `seats` minus the product's included allowance, never fewer than zero. The unrounded fee is then the product's base charge plus the per-seat rate multiplied by the billable seats, the whole of that multiplied first by the license-scope multiplier and then by the licensee organization's type discount, and the final result is rounded half-up to a whole cent exactly once — no intermediate rounding occurs. The schedule is: base charges of 250,000 cents for `TRADE_REALTIME`, 99,999 cents for `TRADE_HISTORICAL`, and 150,000 cents for `DISCLOSURE_ARCHIVE`; per-seat rates of 5,000, 2,500, and 1,000 cents respectively; included allowances of 5, 10, and 20 seats respectively; scope multipliers of 1.0 for `INTERNAL`, 1.5 for `DISPLAY`, and 2.25 for `REDISTRIBUTION`; and an org-type discount of 0.9 for a `MUNICIPAL_ADVISOR` licensee with 1.0 (no discount) for `ISSUER`, `OBLIGATED_PERSON`, and `BROKER_DEALER` licensees. The annual invoice, `annual_invoice_cents`, is twelve times the stored monthly fee: each of the twelve identical monthly lines is rounded to whole cents first and the lines are then summed — computing the annual figure by rounding a single unrounded yearly total is forbidden, because the two orders diverge whenever the unrounded monthly fee carries a fractional cent.

The subscription lifecycle is driven by the `LicensingOfficer` supplying a `to_state`. From `PENDING`, a subscription may advance to `ACTIVE` — permitted only while the licensee organization is `ACTIVE`, otherwise `ERR_ORG_SUSPENDED` — or directly to `TERMINATED`; from `ACTIVE` it may advance to `TERMINATED`. Both `TERMINATED` and `REJECTED` are terminal, and requesting `to_state` equal to `REJECTED` through this operation is refused with `ERR_INVALID_REQUEST`: rejection is reserved for the compliance cascade of §3.5, which is the sole path into `REJECTED`. Any advance attempted on a terminal subscription is `ERR_INVALID_STATE`, and each successful advance increments the subscription's `version`. Subscriptions can be listed with optional `licensee_org_id`, `product_code`, and `status` filters.

Licensed access is exercised through the per-product data feeds. A `MarketDataSubscriber` may pull the feed for a product only when an `ACTIVE` data subscription exists for the path's `product_code` whose `subscriber_principal` equals the caller's `X-User-ID`; without one the request is rejected with `ERR_PRODUCT_NOT_LICENSED` (HTTP 403), the last check in the §2.5 order. An unrecognized product code in the path is an invalid enum member and fails schema validation with `ERR_INVALID_REQUEST`. A successful feed read returns the `product_code`, the `subscription_id` that authorized the pull, and a `record_count` giving the number of records currently in the product dataset: `DISSEMINATED` trade reports for `TRADE_REALTIME` and `TRADE_HISTORICAL`, and `PUBLISHED` disclosure submissions for `DISCLOSURE_ARCHIVE`.

### 3.8. Enforcement Referrals, Interpretation Guidance, and Solicitation Oversight

When staff suspect a rule violation, a `ComplianceOfficer` opens an **enforcement referral** citing the rule by its `rule_code` and summarizing the suspicion in `violation_summary`. The cited `rule_code` must match the `rule_code` of an existing rule proposal — otherwise `ERR_RULE_NOT_FOUND` (HTTP 404) — and that proposal must currently be `EFFECTIVE`, otherwise `ERR_RULE_NOT_EFFECTIVE` (HTTP 422): referrals cannot cite rules still in development. The referral names exactly one subject: setting both `subject_org_id` and `subject_professional_id`, or neither, is rejected with `ERR_AMBIGUOUS_SUBJECT` (HTTP 422). A subject organization must be a `BROKER_DEALER` or `MUNICIPAL_ADVISOR` — issuers and obligated persons are not referable subjects and yield `ERR_ORG_TYPE_NOT_PERMITTED`. At creation the system records the acting officer's header value in `created_by_user_id` and derives the `examining_authority` deterministically from the subject's type: a broker-dealer subject — or a professional subject whose employer organization is a broker-dealer — routes to `DEALER_EXAM_AUTHORITY`, while a municipal-advisor subject — or a professional employed by one — routes to `ADVISOR_EXAM_AUTHORITY`. The mapping is total and admits no ties. A referral is born in `OPEN` status with `needs_rule_review` false, and referrals can be listed with optional `subject_org_id`, `subject_professional_id`, and `status` filters.

A referral advances under `ComplianceOfficer` hands through a `to_state`. From `OPEN` it moves to `REFERRED`, stamping `referred_at` with the current logical time — the moment the matter is handed to the examining authority. From `REFERRED` it closes in one of two ways. Closing as `CLOSED_ACTION_TAKEN` requires a non-empty `guidance_text` input — the board's published rule-interpretation guidance, the system's interpretation channel — and a close attempted without it is rejected with `ERR_INVALID_REQUEST`. Closing as `CLOSED_NO_ACTION` needs no guidance. Either close records the acting officer in `closed_by_user_id` and preserves any `closure_notes` supplied. Segregation of duties applies at the close: the closing officer's `X-User-ID` must differ from `created_by_user_id`, and a violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Both closed states are terminal, and advancing a closed referral is `ERR_INVALID_STATE`. Each advance increments the referral's `version`. Separately, the supersession cascade of §3.2 may set a referral's `needs_rule_review` flag true while it is `OPEN` or `REFERRED`; the flag remains true until the referral closes, warning the authority that the cited rule has been replaced.

The fiduciary standard for municipal advisors is enforced through an append-only ledger of **solicitation records**. A `DealerRep` logs a solicitation performed by its own firm — the payload's `advisor_org_id` must equal the caller's `X-User-ID`, else `ERR_UNAUTHORIZED` — and the firm must be a `MUNICIPAL_ADVISOR` (any other type is `ERR_ORG_TYPE_NOT_PERMITTED`) and `ACTIVE` (otherwise `ERR_ORG_SUSPENDED`). Each record names the solicited `municipal_entity_name`, a `compensation_type` of `FIXED`, `HOURLY`, or `CONTINGENT`, a `compensation_cents` amount of at least zero, and a `disclosure_provided` flag attesting that the fiduciary compensation disclosure was delivered to the municipal entity. Two fiduciary gates guard creation, checked in this order per §2.5: the disclosure must have been delivered — a record with `disclosure_provided` false is rejected with `ERR_DISCLOSURE_REQUIRED` (HTTP 422) — and `CONTINGENT` compensation may not exceed the fiduciary fee cap of 25,000 dollars (2,500,000 cents), with an amount above the cap rejected as `ERR_FEE_CAP_EXCEEDED` (HTTP 422). Solicitation records undergo no state transitions and, per §2.8, carry only `id` and `created_at`. An organization's solicitation records can be listed under the organization, with a `DealerRep` permitted to list only its own organization's records.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource, drive a state transition, or merely read return a `200 OK` status code. All business endpoints are mounted under the `/msrb` prefix; the logical-clock endpoint is mounted outside that prefix, exactly as listed below.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/msrb/organizations` | Register a regulated organization (issuer, obligated person, broker-dealer, or municipal advisor) | PortalOperator |
| GET | `/msrb/organizations/{id}` | Read one organization including derived fields (late-report tally, posture, published par total, active professional count) | PortalOperator, ComplianceOfficer, ExamAdmin, LicensingOfficer |
| POST | `/msrb/organizations/{id}/suspend` | Suspend an organization; gates future disclosures, trades, solicitations, exam attempts, and subscription creation/activation without cascading | ComplianceOfficer |
| POST | `/msrb/rule-proposals` | Create a rule proposal in DRAFT, optionally declaring a supersession target | RulemakingOfficer |
| GET | `/msrb/rule-proposals` | List rule proposals with optional filters | RulemakingOfficer, Regulator, PortalOperator, ComplianceOfficer |
| GET | `/msrb/rule-proposals/{id}` | Read one rule proposal | RulemakingOfficer, Regulator, PortalOperator, ComplianceOfficer |
| PATCH | `/msrb/rule-proposals/{id}` | Edit a proposal (legal only in DRAFT or DISAPPROVED; OCC-guarded) | RulemakingOfficer |
| POST | `/msrb/rule-proposals/{id}/open-comment-period` | Open a public comment window of 21–90 days; sets the half-open window and the expedited flag | RulemakingOfficer |
| POST | `/msrb/rule-proposals/{id}/submit-for-approval` | Submit a proposal for regulatory approval once the window has ended and no unmoderated letters remain | RulemakingOfficer |
| POST | `/msrb/rule-proposals/{id}/decide` | Regulatory decision (APPROVE computes the effectiveness date; DISAPPROVE records the reason); segregated from the submitter | Regulator |
| POST | `/msrb/rule-proposals/{id}/comment-letters` | Submit a public comment letter while the proposal is open and the window is live | PublicReader |
| GET | `/msrb/rule-proposals/{id}/comment-letters` | List a proposal's comment letters (moderation work queue) | RulemakingOfficer, Regulator, PortalOperator, ComplianceOfficer |
| POST | `/msrb/comment-letters/{id}/moderate` | Moderate a comment letter — PUBLISH or DISMISS (DISMISS requires a reason) | PortalOperator |
| POST | `/msrb/disclosure-submissions` | File a disclosure (official statement, annual financial, event notice, or voluntary) for the caller's own organization | IssuerRep |
| GET | `/msrb/disclosure-submissions` | List disclosure submissions, scoped by caller visibility | PortalOperator, IssuerRep, PublicReader, ComplianceOfficer |
| GET | `/msrb/disclosure-submissions/{id}` | Read one disclosure submission; out-of-scope reads report not-found | PortalOperator, IssuerRep, PublicReader, ComplianceOfficer |
| POST | `/msrb/disclosure-submissions/{id}/review-outcome` | Portal review decision — PUBLISH or mark DEFICIENT (requires a deficiency reason) | PortalOperator |
| POST | `/msrb/professionals` | Register a municipal professional under an ACTIVE broker-dealer or municipal-advisor organization | ExamAdmin |
| GET | `/msrb/professionals` | List municipal professionals with optional filters | ExamAdmin, ComplianceOfficer |
| GET | `/msrb/professionals/{id}` | Read one professional including qualification, standing, CE anchors, credit buckets, and transaction eligibility | ExamAdmin, ComplianceOfficer |
| POST | `/msrb/professionals/{id}/standing` | Set the standing dimension (ACTIVE or SUSPENDED), independent of qualification | ComplianceOfficer |
| POST | `/msrb/professionals/{id}/ce-credits` | Record continuing-education credits into the open CE cycle | ExamAdmin |
| POST | `/msrb/exam-attempts` | Record a qualification exam attempt; a set-completing PASS qualifies the professional | ExamAdmin |
| GET | `/msrb/professionals/{id}/exam-attempts` | List a professional's exam attempts (append-only event log) | ExamAdmin, ComplianceOfficer |
| POST | `/msrb/trade-reports` | Report a municipal securities trade for the caller's own ACTIVE broker-dealer; computes timeliness and dissemination banding and rolls into the dealer's posture | DealerRep |
| GET | `/msrb/trade-reports` | List trade reports, scoped by caller visibility | DealerRep, PortalOperator, PublicReader, ComplianceOfficer |
| GET | `/msrb/trade-reports/{id}` | Read one trade report; out-of-scope reads report not-found | DealerRep, PortalOperator, PublicReader, ComplianceOfficer |
| POST | `/msrb/trade-reports/{id}/cancel` | Cancel a disseminated trade (ownership-gated); compensates the published par total and late tally | DealerRep |
| POST | `/msrb/data-subscriptions` | Create a market-data license in PENDING with computed monthly and annual fees | LicensingOfficer |
| GET | `/msrb/data-subscriptions` | List data subscriptions with optional filters | LicensingOfficer, ComplianceOfficer |
| GET | `/msrb/data-subscriptions/{id}` | Read one data subscription | LicensingOfficer, ComplianceOfficer |
| POST | `/msrb/data-subscriptions/{id}/transition` | Advance a subscription to ACTIVE or TERMINATED; REJECTED is system-only | LicensingOfficer |
| POST | `/msrb/enforcement-referrals` | Open an enforcement referral citing an EFFECTIVE rule against exactly one subject; derives the examining authority | ComplianceOfficer |
| GET | `/msrb/enforcement-referrals` | List enforcement referrals with optional filters | ComplianceOfficer, Regulator |
| GET | `/msrb/enforcement-referrals/{id}` | Read one enforcement referral including the rule-review flag and published guidance | ComplianceOfficer, Regulator |
| POST | `/msrb/enforcement-referrals/{id}/advance` | Advance a referral to REFERRED or to a closed state; closes require a different officer than the creator | ComplianceOfficer |
| POST | `/msrb/solicitation-records` | Log an advisor solicitation of a municipal entity under the fiduciary standard | DealerRep |
| GET | `/msrb/organizations/{id}/solicitation-records` | List an advisor organization's solicitation records; DealerRep sees only its own | ComplianceOfficer, PortalOperator, DealerRep |
| POST | `/_clock/set_current_utc` | Set the logical clock (monotonic; outside the `/msrb` prefix) and run the ordered epoch pass | SystemAdmin |
| GET | `/msrb/data-feeds/{product_code}` | Licensed market-data pull; requires an ACTIVE subscription for the product whose subscriber principal is the caller | MarketDataSubscriber |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_PRODUCT_NOT_LICENSED` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_ORG_NOT_FOUND` | 404 Not Found |
| `ERR_PROPOSAL_NOT_FOUND` | 404 Not Found |
| `ERR_COMMENT_NOT_FOUND` | 404 Not Found |
| `ERR_SUBMISSION_NOT_FOUND` | 404 Not Found |
| `ERR_PROFESSIONAL_NOT_FOUND` | 404 Not Found |
| `ERR_TRADE_NOT_FOUND` | 404 Not Found |
| `ERR_SUBSCRIPTION_NOT_FOUND` | 404 Not Found |
| `ERR_REFERRAL_NOT_FOUND` | 404 Not Found |
| `ERR_RULE_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_PROPOSAL_NOT_OPEN_FOR_COMMENT` | 409 Conflict |
| `ERR_UNRESOLVED_COMMENTS` | 409 Conflict |
| `ERR_ORG_SUSPENDED` | 409 Conflict |
| `ERR_COVERAGE_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_EVENT_CATEGORY_REQUIRED` | 422 Unprocessable Entity |
| `ERR_DISCLOSURE_REQUIRED` | 422 Unprocessable Entity |
| `ERR_COMMENT_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_COMMENT_PERIOD_TOO_SHORT` | 422 Unprocessable Entity |
| `ERR_COMMENT_PERIOD_STILL_OPEN` | 422 Unprocessable Entity |
| `ERR_RETAKE_WINDOW_ACTIVE` | 422 Unprocessable Entity |
| `ERR_TRADE_TIME_INVALID` | 422 Unprocessable Entity |
| `ERR_CLOCK_REGRESSION` | 422 Unprocessable Entity |
| `ERR_ORG_TYPE_NOT_PERMITTED` | 422 Unprocessable Entity |
| `ERR_AMBIGUOUS_SUBJECT` | 422 Unprocessable Entity |
| `ERR_RULE_NOT_EFFECTIVE` | 422 Unprocessable Entity |
| `ERR_FEE_CAP_EXCEEDED` | 422 Unprocessable Entity |
