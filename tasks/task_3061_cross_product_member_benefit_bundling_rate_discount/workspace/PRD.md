# Member Benefit Bundling API — Product Requirements Document

## 1. Introduction

Modern consumer financial platforms win loyalty by rewarding members for deepening their relationship across lending, banking, investing and career services. This document specifies the **Member Benefit Bundling API**, mounted under `/benefits`, which turns that strategy into an auditable, deterministic rule engine. Its central promise is that a member's standing — their tier, their deposit-rate advantage, and the discount stack applied to their loan pricing — is derived from observable product adoption and qualifying payroll activity, never from ad-hoc operator judgement. The platform must therefore be able to answer, for any member at any instant, which benefits they are entitled to, which of those entitlements are currently priceable, and what a given loan should cost after every applicable discount has been assembled and capped.

The commercial opportunity is tempered by a compliance obligation. Regulators scrutinise any arrangement in which a credit decision appears to be conditioned on the purchase of another product, and they require that underwriting already performed for one product is not silently reused where reuse is forbidden. The API therefore pairs its pricing machinery with a compliance-audit layer: consent must be recorded before certain cross-sell contacts proceed, re-underwriting is permitted only where an existing finalized lending relationship genuinely justifies it, and an entitlement override can never be approved by the same operator who requested it.

Finally, the platform must cope with the ordinary churn of member life. Direct deposit stops, tiers slide, loans move between provisional and final pricing, and benefits that were granted are stepped down, restored, or revoked. Every one of those movements is a first-class, timestamped event that must recompute the affected aggregates, emit the appropriate member notice, and leave a reconciliation trail that shows where the platform's view of a benefit and the underlying product systems have drifted apart.

## 2. Global Specifications & System-Wide Principles

This section defines the cross-cutting rules — access control, response shape, pagination, pricing discipline, concurrency, validation order and compliance boundaries — that apply to every operation in the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers. `X-User-ID` identifies the acting user, and `X-User-Role` names the capacity in which that user is acting. A request missing either header, or carrying an empty value for either, is rejected before any other processing with `ERR_MISSING_AUTH_HEADERS` (HTTP 401). The single exception is the clock-driving capability described in §3, which is reachable without an authenticated identity.

The platform recognises six roles, spelled exactly as follows: `Member`, `Underwriter`, `BenefitsAdmin`, `ComplianceOfficer`, `PlatformAdmin`, and `Anonymous`. If `X-User-Role` names a role that is not one of these six, or names a declared role that is not listed on the endpoint being called, the request is refused with `ERR_FORBIDDEN_ROLE` (HTTP 403). The same code covers the case where a caller with a valid role targets a resource that is not theirs on an ownership-guarded operation.

Identity is bound to `X-User-ID` differently depending on the role. When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting member entity; every ownership check on a resource that references a member compares that resource's member foreign-key field to `X-User-ID`, and a mismatch is an `ERR_FORBIDDEN_ROLE` rejection. `Member` is the only entity-backed role. When `X-User-Role` is `Underwriter`, `BenefitsAdmin`, `ComplianceOfficer`, `PlatformAdmin`, or `Anonymous`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server records it where a rule requires an operator identity to be stamped — for example when a compliance decision records the deciding officer, when an override records its requester and approver, or when a cross-sell check records who decided it — but it never compares that identifier to any entity's `id`.

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

List endpoints accept two query parameters. `limit` caps the number of items returned; when omitted it defaults to 10, and it may be set as low as 1 and as high as 100 — a value outside that range is a malformed request. `offset` skips a number of leading items and defaults to 0. Unless a subsection states otherwise, every list endpoint returns items ordered by creation timestamp ascending.

List responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope. A collection endpoint may also accept filter query parameters; the available filters for each collection are enumerated wherever that collection is discussed in this document.

### 2.4. Member Standing, Product Holdings and Tier Computation

The **Member** is the root identity of the platform. A member is registered with a client-facing `member_number`, a legal `full_name`, and an `email`; both `member_number` and `email` are unique across the platform. Four system-managed fields describe the member's standing. `member_status` takes one of `PROSPECT`, `MEMBER_ACTIVE`, `MEMBER_AT_RISK`, or `MEMBER_LAPSED`. `member_since_at` records the timestamp of the member's first product adoption and is null while the member remains a prospect. `member_tier` takes one of `NONE`, `BASE`, `PLUS`, or `PREMIER`. `benefit_entitlement_state` takes one of `NONE`, `FULL`, `PARTIAL`, or `SUSPENDED` and summarises the member's entitlement rollup.

Several member fields are computed aggregates rather than operator input. `product_adoption_count` is the number of the member's product holdings whose adoption status is `ADOPTED`. `product_line_set` is the sorted, de-duplicated set of product lines drawn from those adopted holdings, ordered ascending by the enum's stable ordering `LENDING` < `BANKING` < `INVESTING` < `CAREER`. `qualifying_deposit_balance_cents` is the sum of `balance_cents` across the member's banking holdings that are adopted. `rewards_points_balance` is the non-negative sum of the point deltas of the member's posted rewards ledger entries. `churn_risk_score` is an integer in the range 0 to 100 inclusive. `last_qualifying_deposit_at` is the most recent timestamp at which a qualifying deposit posted, and is null until one has ever posted.

Tier is derived from adoption breadth by a top-down threshold rule; the first clause satisfied determines the result. A member reaches `PREMIER` when their adopted product count is at least 3 and their adopted distinct product-line count is at least 3. Failing that, they reach `PLUS` when their adopted product count is at least 2 and their distinct line count is at least 2. Failing that, they reach `BASE` when their adopted product count is at least 1. Otherwise the tier is `NONE`. Only holdings in `ADOPTED` status feed this count; closed holdings are excluded. A separate forward-looking projection answers what a member would reach if every one of their pending holdings were adopted — that projection additionally counts holdings whose adoption status is `PENDING`, so a member with one adopted holding and two pending holdings spanning three distinct lines reads `BASE` under the canonical point-in-time rule but `PREMIER` under the projection. A member's `member_status` is recomputed only by the churn and lifecycle operations of §3.7; it is never set directly by a pricing change.

A **ProductHolding** represents a member's relationship to one product line. It is opened against a member through `member_id`, carries a `product_line` of `LENDING`, `BANKING`, `INVESTING`, or `CAREER`, and begins in `PENDING`. Its `adoption_status` moves through `PENDING`, `ADOPTED`, `SUSPENDED`, and `CLOSED`; `adopted_at` is stamped the first time the holding becomes adopted; `closed_at` is stamped when it closes; and `balance_cents` records the held balance for the line — a deposit balance, an invested value, or outstanding principal — defaulting to 0.

Three boolean fields on a holding are computed rather than supplied. `deposit_rate_eligible` is true only when the holding's product line is `BANKING`, its adoption status is `ADOPTED`, and the member's direct-deposit enrolment is `ACTIVE`. `cross_sell_eligible` is true only when the holding's adoption status is `ADOPTED` or `SUSPENDED` and the most recent cross-sell check for that member carries the outcome `CLEARED`; if no such check exists the value is false. `reunderwriting_permitted` is true only when the holding's product line is `LENDING`, its adoption status is `ADOPTED`, and a loan account exists for that holding whose pricing status is `FINAL` or `STEPPED_DOWN`; no holding on any other product line can ever be true.

All twelve persisted resource types in this API — Member, ProductHolding, LoanAccount, DirectDepositEnrollment, BenefitEntitlement, RateDiscountRule, DiscountApplication, RewardsLedgerEntry, RequalificationCycle, ChurnNotice, CoachingSession and CrossSellCheck — carry the same four system-managed properties. `id` is a server-minted UUID string with no type prefix. `created_at` is an ISO 8601 UTC timestamp with exactly three fractional digits, set at creation. `updated_at` is an ISO 8601 UTC timestamp with three fractional digits and is refreshed on every mutation, including mutations to derived fields. `version` is an integer that starts at 1 and increments by one on every mutation; it is the anchor for the optimistic concurrency mechanism in §2.8.

### 2.5. Rate-Discount Rule Governance and Stack Assembly

A **RateDiscountRule** is the configuration artefact that authorises a discount. It is created with a stable, human-readable `rule_code` that is unique across all rules regardless of status, a `discount_kind` of `MEMBER_TIER`, `DIRECT_DEPOSIT`, `AUTOPAY`, `PROMOTIONAL`, or `CAREER_SERVICES`, a `stacking_class` of `BASE`, `ADDITIVE`, or `CAP_CONTRIBUTING`, a discount magnitude `discount_bps` expressed in basis points, and an `effective_from` that is the inclusive start of the validity window together with an `effective_to` that is the exclusive end. A rule may optionally declare `stacks_on_rule_id`, naming the rule it stacks on top of, with a null value marking a stack root. It may declare `requires_direct_deposit`, which when true restricts the rule to members whose deposit enrolment is `ACTIVE`, and `min_member_tier`, the lowest member tier at which the rule may price, defaulting to `NONE`. A rule begins in `DRAFT`, moves to `ACTIVE` when activated, and ends in `RETIRED`.

A **DiscountApplication** is the record of a rule actually being priced against a loan. It names the loan through `loan_account_id` and the rule through `rule_id`, and snapshots the rule's magnitude into `applied_bps` and its window into `window_from` and `window_to` at the moment of application. Its `application_state` is `APPLIED`, `PREEMPTED`, or `ROLLED_BACK`, and `applied_at` records when it was written. A loan account exposes two computed pricing values that this machinery maintains: `discount_stack_bps`, the capped sum of its surviving discounts, and `effective_apr_bps`, its discounted rate after that stack is subtracted and the floor applied. Which of those two values the loan treats as frozen is governed entirely by the loan's `pricing_status`, which is `PROVISIONAL`, `FINAL`, or `STEPPED_DOWN`. When a new application displaces an older application of the same stacking class, the older row moves to `PREEMPTED` and its `preempted_by_application_id` names the application that displaced it; that field is null in every other case.

Discounts are assembled per loan by a waterfall. The candidate pool is every rule that is `ACTIVE`, whose window contains the current logical instant under the half-open convention that the start is inclusive and the end is exclusive, whose `min_member_tier` is at or below the member's current tier, and which either does not require direct deposit or requires it while the member's enrolment is `ACTIVE`. Autopay is a first-class member of that pool, not a bolted-on bonus: a rule whose kind is autopay simply does not appear in the candidate pool of a loan whose `autopay_status` is anything other than `ENROLLED`. From the pool, exactly one survivor is kept per stacking class, selected by the ordering that prefers the largest discount in basis points, then the latest window start, then the latest creation timestamp; the resource identifier is never consulted as a tie-break. The discounts of the survivors are summed and the sum is capped at 400 basis points. Each surviving rule yields one application in `APPLIED` state, and every other candidate of the same class yields a `PREEMPTED` application.

### 2.6. Benefit Entitlement Reconciliation and the Deposit Qualification Ledger

A **BenefitEntitlement** records a specific benefit a member has unlocked. It names the member through `member_id` and the holding that unlocked it through `source_holding_id`, and declares a `benefit_code` of `LOAN_RATE_DISCOUNT`, `DIRECT_DEPOSIT`, `CAREER_COACHING_CREDIT`, `INVESTING_FEE_WAIVER`, or `REWARDS_MULTIPLIER`. Its `value_bps` carries the benefit magnitude in basis points for rate benefits and in points for the rewards multiplier. Its `entitlement_status` runs through `PENDING`, `GRANTED`, `PENDING_REQUALIFICATION`, `STEPPED_DOWN`, and `REVOKED`. `granted_at` is stamped afresh on every transition into `GRANTED`, and `stepped_down_at` is stamped on every transition into `STEPPED_DOWN`. The computed `reconciliation_state` is `IN_SYNC`, `DRIFT_REPORTED`, or `RECONCILED`. Two further system-managed fields support supervision: `override_requested_by` records the identity of the operator who queued an override and is null when none is queued, while `override_approved_by` records the identity of the officer who approved it and must differ from the requester. When a rate benefit is priced, `governing_rule_id` names the discount rule the entitlement unlocks; revoking such an entitlement rolls back every discount application on that member's loans whose rule matches the governing rule. Benefits that price no rate discount — the career-coaching credit and the rewards multiplier — carry a null governing rule.

Each benefit code has its own unlocking condition. The loan rate discount, the career-coaching credit, the investing fee waiver, and the rewards multiplier are unlocked when the source holding is `ADOPTED`. The direct-deposit benefit is unlocked when the member's deposit enrolment is `ACTIVE`. The entitlement's reconciliation state is derived by comparing its stored status against that guard verdict: a row whose stored status disagrees with its guard verdict and has not yet been rewritten reads `DRIFT_REPORTED`; a row rewritten by the reconciliation operation reads `RECONCILED`; and a row that already agrees reads `IN_SYNC`. At the member level, the entitlement state is recomputed as a rollup over the member's entitlements whose source holding is not closed: a lapsed member reads `SUSPENDED`; otherwise, if every counted entitlement is granted and at least one is counted, the state is `FULL`; otherwise, if at least one counted entitlement is granted, the state is `PARTIAL`; otherwise it is `NONE`.

A **DirectDepositEnrollment** governs whether a member's payroll qualifies them for deposit-linked benefits. It is opened against a member through `member_id` with a `required_monthly_amount_cents` threshold, and begins in `PENDING_VERIFICATION`. Its `status` runs through `PENDING_VERIFICATION`, `ACTIVE`, `GRACE`, and `LAPSED`. `qualified_at` is stamped when the enrolment first becomes active, `last_deposit_at` records the most recent posted deposit of any amount, and `grace_deadline_at` is set when the enrolment enters grace. The computed `consecutive_qualifying_months` counts the maximal trailing run of consecutive calendar months, ending at the logical month containing the current logical instant, in which the enrolment's posted deposits met `required_monthly_amount_cents`. The computed `requalification_due_at` is the first instant of the third logical month after `qualified_at`. The computed `missed_cycle_count` counts completed logical months since `qualified_at` with no qualifying posting. A requalification cycle carries two rollups of its own over the logical months inside its window: `qualifying_month_count`, the number of months in the window carrying at least one qualifying posting, and `qualifying_deposit_total_cents`, the summed posted deposit amounts inside the window that met the required monthly threshold.

Months are UTC calendar months. A month qualifies for an enrolment when the sum of its posted deposit amounts, excluding reversed postings, reaches `required_monthly_amount_cents`. A non-qualifying month resets the trailing run to zero at that point, and counting restarts from the month after it. Because a reversal is applied at its own original posting timestamp, reversing an old deposit can retroactively break a month that had already been counted.

When an enrolment is active, the member earns a deposit-rate boost driven by their qualifying deposit balance. Balances of at least 1,000 dollars earn the first band of 25 basis points; balances of at least 5,000 dollars earn the second band of 50 basis points; balances of at least 25,000 dollars earn the third band of 75 basis points. The highest matching band wins, and every band's lower bound is inclusive, so a balance of exactly 1,000 dollars earns the first band while a balance one cent below earns nothing. When an enrolment is anything other than active the boost is zero. The same deposit machinery defines the 50-basis-point magnitude by which a direct-deposit entitlement is stepped down. A projection variant is also exposed for planning: instead of the balance held today, it evaluates the band against the mean qualifying balance across the trailing three logical months, so a member who funded a higher band today but held nothing for the two preceding months is still priced at the lower band.

A **RewardsLedgerEntry** is a signed movement in a member's points account. It names the member through `member_id`, and, when the entry is a principal redemption, names the loan through `loan_account_id`. Its `entry_type` is `EARN`, `REDEEM_PRINCIPAL`, `REVERSE`, or `ADJUST`; `points_delta` is the signed points change — positive for earnings and upward adjustments, negative for redemptions and reversals; `entry_status` is `POSTED` or `REVERSED`; and `source_event_code` is a free-form provenance tag. `principal_reduction_cents` is computed and is non-zero only for a principal redemption. When an entry is reversed, `reversed_by_entry_id` names the compensating entry that undid it.

### 2.7. Basis-Point Precision and Rounding Discipline

Rates and discounts throughout this API are expressed as integer basis points, where 100 basis points equal one percent, and are never rounded — they are exact integers. Monetary amounts are expressed as integer cents. The only truncating operation in the platform is the points-to-cents conversion used by principal redemption, which floors toward zero and destroys any remainder. Every timestamp in the system is an ISO 8601 UTC value carrying exactly three fractional digits.

### 2.8. Optimistic Concurrency Control on Versioned Writes

Two write operations are guarded against stale client views. When a client opens a requalification cycle for a member, the request body must carry `expected_member_version` matching the member's current `version`. If the member's version has advanced since the client last read it, the request is rejected with `ERR_STALE_VERSION` (HTTP 412), so the caller cannot restart requalification against a member view it has not observed. When a client attaches a discount application to a loan, the request body must carry `expected_loan_account_version` matching the loan account's current `version`; a mismatch is likewise rejected with `ERR_STALE_VERSION` (HTTP 412), so the caller cannot price against a loan it has not observed. No other endpoint in this API accepts a version field. This mechanism is evaluated as the fifth rung of the validation ladder in §2.9.

### 2.9. Request Validation Order and Nested Resource Retrieval

Validation is a single ordered ladder, evaluated top to bottom, and the first rule that fails determines the error returned; later rules are not consulted. The rungs, in order, are:

1. Both `X-User-Role` and `X-User-ID` are present and non-empty, else `ERR_MISSING_AUTH_HEADERS`. This rung applies to every endpoint except the clock capability.
2. `X-User-Role` is one of the six declared roles and is listed on the endpoint, and, where the operation is ownership-guarded, the acting identity is the owning member, else `ERR_FORBIDDEN_ROLE`. This rung applies to every endpoint.
3. The member named in the path exists, else `ERR_MEMBER_NOT_FOUND`; this applies to every endpoint whose path carries a member identifier.
4. Every other resource identifier in the path resolves, else `ERR_RESOURCE_NOT_FOUND`. The identifiers governed here are the holding, loan account, enrolment, entitlement, rule, application, ledger entry, cycle, notice, check, and session identifiers.
5. The optimistic-concurrency guard fires, else `ERR_STALE_VERSION`; this rung governs only the cycle-opening and application-attaching operations named in §2.8.
6. The target resource is in a state that permits the requested transition, else `ERR_INVALID_STATE`; this applies to every state-transition operation.
7. The holdings referenced by an entitlement or a discount application are adopted, else `ERR_HOLDING_NOT_ADOPTED`; this governs entitlement reconciliation, discount-application attachment, entitlement restoration, and entitlement step-down.
8. A cross-sell decision would not condition credit on a banking or investing purchase, else `ERR_CREDIT_CONDITIONING_BLOCKED`.
9. Underwriting reuse is permitted for the target line, else `ERR_REUSE_UNDERWRITING_PROHIBITED`.
10. An affirmative consent record exists where required, else `ERR_CONSENT_REQUIRED`.
11. A declared stacking link joins rules of the same stacking class, else `ERR_STACK_CLASS_CONFLICT`.
12. No applied discount application already occupies the same loan-and-rule pair, else `ERR_DUPLICATE_DISCOUNT_APPLICATION`.
13. A rule's window does not overlap a live rule's window below the minimum gap, else `ERR_RULE_WINDOW_OVERLAP`.
14. The rule code is unique across all statuses, else `ERR_DUPLICATE_RULE_CODE`.
15. The stacking chain reaches a root without revisiting a rule, else `ERR_SELF_STACK_CYCLE`.
16. A restore is not requested on an entitlement already granted, else `ERR_BENEFIT_ALREADY_GRANTED`.
17. The override approver differs from the override requester, else `ERR_SEGREGATION_OF_DUTIES`.
18. A career-coaching session does not collide with another such session on the same coach, else `ERR_SESSION_OVERLAP`.
19. A direct-deposit-dependent rule is not priced while the enrolment is inactive, else `ERR_ENROLLMENT_NOT_ACTIVE`.
20. An enrolment in grace is not lapsed before its grace deadline, else `ERR_GRACE_PERIOD_NOT_ELAPSED`.
21. A requalification cycle is not evaluated before its due instant, else `ERR_REQUALIFICATION_WINDOW_OPEN`.
22. A redemption does not exceed the member's posted points balance, else `ERR_INSUFFICIENT_POINTS`.
23. A redemption sits within the permitted per-entry bounds, else `ERR_REDEMPTION_LIMIT_EXCEEDED`.
24. A redemption does not drive principal below zero, else `ERR_PRINCIPAL_BELOW_ZERO`.
25. A discount-application request does not demand an uncapped stack above the ceiling, else `ERR_STACK_CAP_EXCEEDED`.
26. A lending holding carrying a live loan is not closed, else `ERR_HOLDING_HAS_ACTIVE_LOAN`.
27. An entitlement names a source holding that exists and belongs to the same member, else `ERR_ENTITLEMENT_NO_SOURCE_HOLDING`.
28. A rule is not activated while a rule it stacks upon is missing or still a draft, else `ERR_ACTIVE_RULE_ON_UNPRICED_LOAN`.
29. No two entitlement rows share the same member, benefit code and source holding, else `ERR_DUPLICATE_ENTITLEMENT`.
30. A compliance-driven override is requested inside its window by the benefits-administration role, else `ERR_OVERRIDE_NOT_PERMITTED`.
31. A member-event booking does not exceed the venue capacity for its overlapping interval, else `ERR_SESSION_CAPACITY_SATURATED`.
32. No two entitlement rows share the same member and benefit code while both are granted across different source holdings, else `ERR_DUPLICATE_ENTITLEMENT`.

For requests that target nested resources, path identifiers are validated left to right in the order they appear, and the first identifier that does not resolve determines the 404 that is returned — a request that names a non-existent member as the container of a holding fails on the member before the holding is ever examined. A body that is malformed, omits a required field, carries an unknown field, or supplies a value outside its declared type or enumeration is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

### 2.10. Compliance Boundaries and Segregation of Duties

The platform treats the conditioning of credit on the purchase of another product as a hard prohibition. When a member is offered a banking or investing product, no cross-sell contact may proceed unless the member has affirmatively consented; a cross-sell check that targets such a line while consent is absent is flagged as blocked, and a compliance decision that would clear it while it remains blocked is refused. Reuse of underwriting previously performed for a lending relationship is likewise bounded: it is permitted only where an adopted lending holding carries a loan that has been finally priced, and a reuse decision on a line with no such relationship is refused. Both boundaries surface on the same operation — the recording of a compliance decision on a cross-sell check — and are evaluated in the order given by the ladder in §2.9 so that a blocked target reports conditioning before consent, and a consent failure reports before any reuse failure.

Separation of duties is enforced on entitlement overrides. The operator who queues an override on a compliance-driven entitlement downgrade is recorded on the entitlement, and the operator who approves it is recorded separately; the two must differ, and an approval attempted by the requester is refused. The requesting role is validated as part of this boundary: an override may be queued only by the benefits-administration role, only while the override window remains open.

## 3. Business Logic & Workflows

### 3.1. Member Onboarding and the First Product Adoption

A prospective customer enters the platform through registration by any caller, including an unauthenticated one. Registration supplies a `member_number`, a `full_name`, and an `email`, and creates the member in `PROSPECT` standing with a null `member_since_at`, a `member_tier` of `NONE`, a `benefit_entitlement_state` of `NONE`, a `rewards_points_balance` of 0 and a `churn_risk_score` of 0. At this point the member holds no products and is invisible to every pricing rule.

Product relationships are opened by an administrator or a benefits operator against an existing member, naming the member through `member_id`, choosing a `product_line`, and optionally setting an opening `balance_cents`; the holding is created in `PENDING` status with a null `adopted_at` and a balance defaulting to 0. A holding in `PENDING` confers nothing: it contributes nothing to the member's adopted product count, and the member remains a prospect until at least one holding is adopted.

Adoption is the member's own act. A `Member` adopts the holding they own, and the platform verifies that the acting identity is the member named on the holding before anything else. Adoption stamps `adopted_at`, moves the holding to `ADOPTED`, and sets in motion a cascade: the member's `product_adoption_count` and `product_line_set` are recomputed, `member_tier` is recomputed under the canonical point-in-time rule described in §2.4, `churn_risk_score` is recomputed, and any entitlement of that holding still in `PENDING` is granted. Crucially, the very first adoption in a member's life also promotes them from `PROSPECT` to `MEMBER_ACTIVE` and stamps `member_since_at` with the current logical instant — this is the single event that converts a prospect into a member.

Entitlements are declared ahead of adoption by a benefits operator, who supplies the `source_holding_id` that will unlock the benefit, the `benefit_code`, the magnitude `value_bps`, and, for rate benefits, the `governing_rule_id` of the rule the benefit will feed. A newly declared entitlement sits in `PENDING` until its unlocking condition is met. Two duplicate guards apply: no two rows may share the same member, benefit code and source holding, and no two rows may share the same member and benefit code while both are granted against different source holdings. Both are refused with `ERR_DUPLICATE_ENTITLEMENT`. An entitlement whose `source_holding_id` does not exist or belongs to a different member is refused with `ERR_ENTITLEMENT_NO_SOURCE_HOLDING`.

The platform is driven by a logical clock that never falls back to wall-clock time. On server start it reads a fixed default, and an administrative capability advances it to a caller-supplied `current_utc` instant, returning both the new instant and the previous one. Advancing the clock recomputes every enrolment's `consecutive_qualifying_months`, `missed_cycle_count` and `requalification_due_at`, because those quantities are defined relative to the logical month. This capability is the sole endpoint that does not require authentication headers.

### 3.2. Product Holdings: Suspension, Closure and Line-Mix Effects

A holding does not have to be closed to stop contributing. An administrator may suspend an adopted holding, moving it to `SUSPENDED`; suspension immediately recomputes the holding's `deposit_rate_eligible` to false, recomputes the member's `qualifying_deposit_balance_cents` and `product_adoption_count`, and demotes every entitlement sourced from that holding that is currently `GRANTED` or `PENDING_REQUALIFICATION` to `PENDING_REQUALIFICATION`. Suspension is reversible: the owning member may re-adopt a suspended holding, which refreshes `adopted_at`, re-derives `deposit_rate_eligible`, and recomputes the member's adopted product count and tier.

Closure is permanent. A member may close a holding they own, and the platform admits the closure only when the holding's outstanding `balance_cents` is zero and no loan account referencing the holding still sits in `PROVISIONAL` or `FINAL` pricing. A lending holding that still carries a live loan is refused with `ERR_HOLDING_HAS_ACTIVE_LOAN` (HTTP 409), whatever pricing state that loan currently occupies — provisional, final or stepped down. A successful close stamps `closed_at`, moves the holding to `CLOSED`, recomputes the member's `qualifying_deposit_balance_cents`, `product_adoption_count`, `product_line_set` and `member_tier`, and revokes every entitlement sourced from that holding that was `GRANTED` or `PENDING_REQUALIFICATION`. `CLOSED` is the only terminal holding state; suspension, by contrast, always has a way back.

Revocation is not merely a status change. When a rate entitlement is revoked, every discount application on the member's loans whose rule matches that entitlement's governing rule is rolled back, and every loan affected by that rollback has its discount stack and effective rate recomputed and its pricing timestamp refreshed. A revocation notice of type benefit revocation is also queued for the member, linked to the entitlement that was revoked, with a reason code recording that the holding closed.

### 3.3. Direct Deposit Qualification, Grace and Lapse

Deposit-linked benefits depend on a separate enrolment that tracks the member's payroll. An operator opens it against a member through `member_id` with a `required_monthly_amount_cents` threshold; it starts in `PENDING_VERIFICATION` with a null `qualified_at`, a `missed_cycle_count` of 0 and a `consecutive_qualifying_months` of 0. Payroll activity is then posted against the enrolment: each posting names the `enrollment_id`, an `amount_cents`, the `posted_at` instant, and optionally the `holding_id` of a banking holding to credit. Posting appends a deposit record, refreshes `last_deposit_at` when the amount meets the threshold, resets `missed_cycle_count` when the amount qualifies, recomputes `consecutive_qualifying_months`, and — when a holding is named — credits that holding's `balance_cents` so that the member's `qualifying_deposit_balance_cents` moves with the deposits. A separate reversal operation names the `posting_id` of a previously posted deposit and marks it reversed at its original timestamp, which can retroactively break a month that had already been counted.

Activation is the transition that turns a verified enrolment into a qualifying one. An operator activates an enrolment by naming the `enrollment_id`; the platform admits the activation of a pending enrolment only when at least one posted deposit has reached `required_monthly_amount_cents`, and admits the activation of a lapsed enrolment only when a qualifying deposit posted after the retry window opened. Activation stamps `qualified_at`, resets `missed_cycle_count` to zero, recomputes `requalification_due_at` and `consecutive_qualifying_months`, grants every direct-deposit entitlement that was `PENDING`, `PENDING_REQUALIFICATION` or `STEPPED_DOWN` and restores its `value_bps` to the rule's full magnitude, recomputes each of the member's banking holdings' `deposit_rate_eligible` to true, recomputes the qualifying balance and churn score, and reprices the member's loans — a stepped-down loan returns to final pricing and is repriced with the direct-deposit discount flowing back into the stack.

Failure is a two-stage process. An active enrolment whose `missed_cycle_count` has reached at least 1 may be moved into `GRACE`; the transition stamps `grace_deadline_at` as the first instant of the month following the earliest missed month plus 30 days, demotes every direct-deposit entitlement that was `GRANTED` or `PENDING_REQUALIFICATION` to `PENDING_REQUALIFICATION`, queues a requalification-reminder notice, and recomputes the churn score. While the enrolment sits in grace, a fresh qualifying deposit posted before `grace_deadline_at` returns it to `ACTIVE`, resets `missed_cycle_count`, recomputes `consecutive_qualifying_months`, restores every `PENDING_REQUALIFICATION` direct-deposit entitlement to `GRANTED`, and swaps any queued rate-step-down notice for a rate-step-up notice. If instead the grace deadline passes and an operator attempts to lapse the enrolment from `GRACE` before that deadline, the attempt is refused with `ERR_GRACE_PERIOD_NOT_ELAPSED`; once the deadline has passed the lapse succeeds, moving the enrolment to `LAPSED`.

A lapse that lands is heavy. Every direct-deposit entitlement that was `GRANTED` or `PENDING_REQUALIFICATION` is stepped down with its `value_bps` reduced by the 50-basis-point step-down magnitude, floored at zero, and stamped with `stepped_down_at`; each of those entitlements' banking holdings loses `deposit_rate_eligible`; the member's `qualifying_deposit_balance_cents` is recomputed; every loan of the member holding `PROVISIONAL` or `FINAL` pricing is repriced, with each applied application whose rule requires direct deposit rolled back, the stack and effective rate recomputed, final pricing demoted to stepped-down, and the pricing timestamp refreshed; a rate-step-down notice linked to the stepped-down entitlement is queued; and the member's churn score is recomputed, which may in turn move the member machine into the at-risk state.

### 3.4. Rate Discount Rules: Drafting, Stacking and Activation

Discount rules begin life as drafts. A benefits operator creates a rule with a `rule_code`, a `discount_kind`, a `stacking_class`, a `discount_bps` magnitude, the inclusive `effective_from` and exclusive `effective_to` bounds, and optionally a `stacks_on_rule_id`, a `requires_direct_deposit` flag and a `min_member_tier`. Creation itself is guarded: a `rule_code` that already exists in any status is refused with `ERR_DUPLICATE_RULE_CODE`; a declared stacking link that joins rules of different stacking classes is refused with `ERR_STACK_CLASS_CONFLICT`; a stacking chain that revisits a rule is refused with `ERR_SELF_STACK_CYCLE`; and a window that collides with a live rule of the same kind is refused with `ERR_RULE_WINDOW_OVERLAP`, on exactly the same terms that govern activation below. A draft may subsequently be edited — its `stacks_on_rule_id`, its `discount_bps`, or the end of its window `effective_to` — and each edit re-validates the whole stacking graph for cycles and for class agreement.

Activation requires that the rule's window not collide with another live rule's window. Two rules of the same discount kind whose validity windows approach closer than one day are refused with `ERR_RULE_WINDOW_OVERLAP`; the comparison is made against every non-retired rule, and because the windows are half-open, two windows that merely touch have a gap of zero and are therefore refused, while a full one-day gap is accepted. Activation additionally requires that the rule's declared stacking parent exists and is not itself still a draft; a rule that stacks upon a missing or draft parent is refused with `ERR_ACTIVE_RULE_ON_UNPRICED_LOAN`. Once activated, the rule's status becomes `ACTIVE` and every loan of every member whose tier is at least `min_member_tier` is repriced, with the discount stack and effective rate recomputed.

Retirement ends a rule's pricing life. An operator retires an active rule, moving it to `RETIRED`, and every application referencing that rule that is still `APPLIED` and was applied before the current logical instant is rolled back; every affected loan is then repriced with its stack and effective rate recomputed and its pricing timestamp refreshed. Retirement requires no additional precondition: it is always available on an active rule.

### 3.5. Loan Pricing, Stack Assembly and Finalization

A loan account is originated by an underwriter or an administrator against an adopted lending holding, naming the member through `member_id`, the holding through `holding_id`, and supplying a `loan_type` of `PERSONAL`, `STUDENT`, `AUTO` or `REFINANCE`, an outstanding `principal_cents`, and an undiscounted `base_apr_bps`. The loan is created with autopay `NOT_ENROLLED`, pricing `PROVISIONAL`, a zero discount stack, an effective rate equal to the undiscounted rate, and a fresh `last_priced_at`. Origination also re-derives the linked holding's reunderwriting permission.

Two parallel dimensions then evolve independently on the same loan. Along the autopay dimension, the owning member may enrol in autopay — or resume a suspended enrolment — moving the standing to `ENROLLED`, while an administrator may suspend autopay, but only from the enrolled state and only while the loan is not already stepped down; a suspension moves the standing to `SUSPENDED`. Every autopay change recomputes the discount stack and the effective rate and refreshes the pricing timestamp. Along the pricing dimension, a loan begins `PROVISIONAL` and is promoted to `FINAL` by an underwriter; promotion requires that the member's most recent requalification cycle has passed, or that the member has no cycle at all, and that the member is `MEMBER_ACTIVE` or `MEMBER_AT_RISK`. Finalization also refuses a loan whose stack carries any rule that requires direct deposit while the member's enrolment is not `ACTIVE`, with `ERR_ENROLLMENT_NOT_ACTIVE` — the same guard that applies when such a rule is attached in the first place. Finalization freezes the discount stack at the snapshots captured when the loan was finalized and marks the linked holding as permitting underwriting reuse.

Discounts are attached to a loan one application at a time by a benefits operator, naming the `rule_id` to apply and supplying an `expected_loan_account_version` for the concurrency guard described in §2.8. Attachment is guarded further: an applied application that already occupies the same loan-and-rule pair is refused with `ERR_DUPLICATE_DISCOUNT_APPLICATION`; an application claiming a benefit against a holding that is not adopted is refused with `ERR_HOLDING_NOT_ADOPTED`; and a rule that requires direct deposit cannot be attached while the member's enrolment is not active, which is refused with `ERR_ENROLLMENT_NOT_ACTIVE`. When a new application is written, any prior applied application of the same stacking class is displaced to `PREEMPTED` with its `preempted_by_application_id` pointing at the newcomer, the loan's discount stack and effective rate are recomputed, and the loan's `version` advances.

The stack is assembled by the waterfall of §2.5. One applicant per stacking class survives, chosen by the ordering that prefers the largest magnitude, then the latest window start, then the latest creation timestamp, with the identifier never consulted. The surviving magnitudes are summed and the sum is capped at 400 basis points; the capped value is what the loan stores as its discount stack. The effective rate is then the undiscounted rate less the capped stack, and it never falls below the hard floor of 199 basis points, whatever discounts are stacked — the floor is absolute. A loan whose pricing is provisional re-derives its stack on every mutation, so a rule activated or retired after the first pricing flows straight through; a loan whose pricing is final holds its stack frozen at its application snapshots, so a rule activated afterwards changes nothing until the loan returns to provisional. A request that asks to store an uncapped stack above the ceiling instead of accepting the applied cap is refused with `ERR_STACK_CAP_EXCEEDED`; the cap itself is applied silently rather than rejected.

Diagnostics expose the machinery. A loan's pricing breakdown reports both the stored, capped stack and the raw uncapped sum beside the effective rate, the floor and the count of applied applications, so an operator can see the cap binding. A discount application may also be rolled back directly by a benefits operator, which moves it to `ROLLED_BACK` and reprices the loan.

### 3.6. Requalification Cycles and Remediation

Requalification is the periodic re-earning of deposit-linked benefits. An operator opens a cycle against a member, and the request must carry `expected_member_version`; if the member's version has advanced since the caller last read it, the request is refused with `ERR_STALE_VERSION` (HTTP 412) rather than being allowed to restart requalification against a stale view. A successfully opened cycle is `OPEN`, with an `opened_at` at the current instant, a `due_at` 90 days out, and a `cycle_index` one greater than the member's greatest existing index. Opening a superseding cycle increments the member's version.

Evaluation is driven by the count of qualifying deposit months inside the cycle window. An operator evaluates an open cycle, and the evaluation cannot occur before the cycle's `due_at`; an attempt beforehand is refused with `ERR_REQUALIFICATION_WINDOW_OPEN`. When the qualifying month count is at least 3, the cycle is marked `PASSED`: every entitlement of the member in `PENDING_REQUALIFICATION` is granted, every provisionally priced loan of the member moves to `FINAL` and is repriced, the member's churn score is recomputed, and an at-risk member is restored to `MEMBER_ACTIVE`. When the qualifying month count falls short of 3, the cycle is marked `FAILED`: every finally priced loan of the member falls back to `PROVISIONAL` and is repriced, every granted loan-rate-discount entitlement of the member is demoted to `PENDING_REQUALIFICATION`, and the churn score is recomputed. In both cases `evaluated_at` is stamped.

A failed cycle can be given a second chance. An operator opens a remediation window, moving the cycle to `REMEDIATION`, extending its `due_at` by 30 days, and queuing a requalification-reminder notice with a tier-downgrade reason. Evaluation of a remediation cycle succeeds when its qualifying month count reaches 3, granting every `PENDING_REQUALIFICATION` or `STEPPED_DOWN` entitlement and lifting every provisional or stepped-down loan back to `FINAL`; it fails when the cycle's `due_at` has been reached without that count being met, reapplying the same demotions as a first-round failure.

A resolved cycle is closed. An operator closes a cycle that is `PASSED` or `FAILED`, refreshing `evaluated_at`, moving it to `CLOSED`, and immediately opening a successor cycle with the next index, an `opened_at` at the current instant and a `due_at` 90 days out. `CLOSED` is the cycle's terminal state.

### 3.7. Churn Detection, Rate Step-Down and Member Notices

Churn risk is a weighted score bounded between 0 and 100 inclusive. An administrator can trigger a churn evaluation for a member at any time. The score sums four contributions: 40 points when the enrolment stands in `GRACE` or `LAPSED`; 20 points per missed cycle, saturating after 2 missed cycles; 25 points when the member's tier has fallen to `NONE` or `BASE`; and 15 points when the qualifying deposit balance has dropped below 5,000 dollars. The saturating contributions mean the raw score tops out at 120, and the stored score is clamped to 100. A diagnostic breakdown exposes the stored score beside the pre-clamp raw score and each factor's individual contribution.

The churn score drives the member machine. A member crosses into the at-risk state once the score reaches 60; a member at risk crosses into the lapsed state once the score reaches 85, and a member whose deposits stop and whose tier collapses can cross the lapse band directly from the active state. Each crossing has consequences. Entering `MEMBER_AT_RISK` queues a rate-step-down notice with a deposit-stopped reason. Entering `MEMBER_LAPSED` suspends the member's entitlement state and steps down every entitlement that was `GRANTED` or `PENDING_REQUALIFICATION`, stamping `stepped_down_at` on each.

Recovery is possible from every non-terminal state. A lapsed member with at least one adopted product may be reinstated, which returns them to `MEMBER_ACTIVE` and recomputes their entitlement state and churn score; a lapsed member holding no adopted products may instead be reset to `PROSPECT`, which clears `member_since_at` and forces the tier to `NONE`. Whenever an enrolment reactivates or a cycle passes and the score drops back below 60, an at-risk member is restored to `MEMBER_ACTIVE`, and any queued rate-step-down notice for that member is voided.

Notices are themselves a lifecycle. A notice is created in `QUEUED` status and stamped with its `issued_at` and the `effective_at` instant at which its rate change takes effect; its `notice_type` is `RATE_STEP_DOWN`, `RATE_STEP_UP`, `REQUALIFICATION_REMINDER` or `BENEFIT_REVOCATION`, and it may carry a `related_entitlement_id` when it concerns a specific entitlement plus a machine-readable `reason_code` such as a deposit-stopped or tier-downgrade tag. An administrator dispatches a queued notice once the current instant has reached its `issued_at`, moving it to `SENT`; the owning member then acknowledges a sent notice, moving it to `ACKNOWLEDGED`. A queued rate-step-down notice is moved to `VOIDED` automatically once the member's direct-deposit entitlement is granted again — the rate having been restored before the notice ever went out. `VOIDED` is therefore the outcome for a notice whose premise disappeared, and it is joined by `ACKNOWLEDGED` as one of the two terminal notice states; a dispatched notice that the member acknowledges ends in `ACKNOWLEDGED`.

Entitlement values can also be moved directly by operators. A benefits operator may step an entitlement down without revoking it, moving it to `STEPPED_DOWN`, stamping `stepped_down_at`, and repricing every loan of the member; when the downgrade is deposit-driven the entitlement's `value_bps` is reduced by the 50-basis-point magnitude floored at zero, and when it is compliance-driven the value is left unchanged. A benefits operator may restore a stepped-down entitlement once its unlocking condition holds again, which returns it to `GRANTED` with its value restored to the governing rule's full magnitude, refreshes `granted_at`, and lifts every stepped-down loan of the member back to `FINAL` with a repricing. A restore attempted on an entitlement that is already `GRANTED` is refused with `ERR_BENEFIT_ALREADY_GRANTED`.

Compliance-driven downgrades can be overridden, but only under supervision. A benefits operator queues an override on a stepped-down entitlement, supplying an `override_reason`; the entitlement records the requester's identity, and the override may be queued only by the benefits-administration role and only while the override window remains open — otherwise it is refused with `ERR_OVERRIDE_NOT_PERMITTED`. A compliance officer then approves the override, and the approving identity must differ from the requesting identity, or the approval is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). When both identities are recorded, the entitlement is restored to `GRANTED` and its priceable rules flow back into the member's discount stacks.

### 3.8. Rewards Points: Earning, Redemption and Reversal

Points accrue on a per-member ledger. A benefits operator may post a manual adjustment by supplying a `points_delta` and a `source_event_code`, which appends an adjustment entry. The member's posted balance is the sum of the point deltas across all posted entries and is never negative; reversed entries are excluded from the sum. A redemption that would drive the running sum below zero is rejected before it is written.

The member's own redemption act converts points into a reduction of loan principal. The member names the `loan_account_id` to credit, a `points` quantity to spend, and optionally a `source_event_code`. Three guards apply in the order set out in §2.9: a redemption whose points exceed the member's posted balance is refused with `ERR_INSUFFICIENT_POINTS`; a redemption outside the permitted per-entry bounds of at least 1,000 points and at most 500,000 points is refused with `ERR_REDEMPTION_LIMIT_EXCEEDED`; and a redemption that would drive the loan's `principal_cents` below zero is refused with `ERR_PRINCIPAL_BELOW_ZERO`. A successful redemption appends a principal-redemption entry with a negative point delta, derives its `principal_reduction_cents` by dividing the points consumed by 100 and flooring toward zero, decrements the loan's principal, and refreshes the loan's pricing timestamp.

The rounding order is pinned and is not negotiable: the floor is applied per entry, at the moment that entry is created, and the per-entry reductions are then summed. The platform never sums all consumed points first and floors once. Two redemptions of 1,150 points each therefore yield 11 cents plus 11 cents — 22 cents in total — and never the 23 cents that a single floor over the combined 2,300 points would give. Any remainder points are destroyed by the floor rather than carried forward. A separate reconciliation capability owned by the benefits-administration role re-derives the member's entire redemption history under a cumulative variant, flooring the aggregate of all posted redemption points exactly once and lifting the newest redemption entry by the difference; after the same two 1,150-point redemptions, the newest entry reads 11 cents under the per-entry rule and 12 cents under the cumulative rule.

Entries can be undone. A benefits operator reverses a posted earning or principal redemption, which is admitted only when the entry is posted and its type is an earning or a principal redemption. The reversal moves the original entry to `REVERSED` and appends a compensating reversal entry whose point delta is the negation of the original's, linked back to the original; the member's posted balance is recomputed. When the reversed entry was a principal redemption, the linked loan's principal is increased by the original's `principal_reduction_cents`, and the loan is repriced with its stack and effective rate recomputed and its timestamp refreshed.

### 3.9. Career Coaching, Member Events and Cross-Sell Compliance

The career-services side of the platform books sessions against a coach's calendar. A benefits operator books a session naming the `member_id`, the `coach_ref` whose calendar the session occupies, a `session_kind` of `CAREER_COACHING` or `MEMBER_EVENT`, an inclusive `starts_at` and an inclusive `ends_at`, and, for a member event, a `capacity_total` seat count defaulting to 1. A newly booked session is `SCHEDULED`. The first booking on a given coach and interval establishes that event's capacity, and booking recomputes the reserved-seat count for every non-cancelled session sharing the coach.

Two distinct geometry rules govern collisions, and they sit on disjoint session kinds. A career-coaching session is a one-to-one exclusive slot: it may not overlap another non-cancelled career-coaching session on the same coach, and because its interval is closed on both ends a session ending exactly when the next begins collides with it — such a booking, or the confirmation of one, is refused with `ERR_SESSION_OVERLAP`. A member event is instead a capacity pool: it is refused with `ERR_SESSION_CAPACITY_SATURATED` only when the number of non-cancelled sessions sharing its coach and overlapping it, under half-open semantics in which a session ending exactly when the next begins does not collide, has already reached the venue capacity declared by the earliest-created overlapping session on that coach. The reserved-seat figure reported as `seats_reserved` for a member event is the count of non-cancelled sessions of that kind on the same coach whose intervals overlap it under the same half-open convention.

A member confirms their attendance, moving a scheduled session to `CONFIRMED`; a member may confirm a career-coaching session only while holding a granted career-coaching entitlement, though a member event requires no entitlement. Confirmation is re-validated against the same two collision geometries as booking: a career-coaching confirmation that would place the session against another non-cancelled career-coaching session on the same coach is refused, and a member-event confirmation is refused once the overlapping bookings on that coach have reached the venue capacity. An administrator marks a confirmed session complete once the current instant has reached its start, moving it to `COMPLETED`; completing a career-coaching session appends a rewards entry earning 250 points with a career-session-completed provenance tag and recomputes the member's posted balance. A member may cancel a session from either the scheduled or the confirmed state, moving it to `CANCELLED` and recomputing the reserved-seat count.

Cross-selling is gated by compliance. A benefits operator opens a cross-sell check for a member and a target product line, supplying a `target_product_line` and optionally a `consent_recorded` flag defaulting to false; the check begins `PENDING` and computes two derived flags: `underwriting_reuse_permitted`, which is true only where an adopted lending holding carries a loan whose pricing has been finalized, and `conditioning_blocked`, which is true when the target line is banking or investing and consent has not been recorded.

A compliance officer then records the decision by supplying an `outcome`, and that single operation carries the platform's compliance boundaries. Clearing the check requires that conditioning is not blocked, that consent has been recorded or the target line is lending, and that no prior cleared check already exists for the same member and target line; a request that would clear a blocked target is refused with `ERR_CREDIT_CONDITIONING_BLOCKED`, and a request that proceeds without consent on a non-lending line is refused with `ERR_CONSENT_REQUIRED`. Blocking the check requires that conditioning is blocked, and moves the check to `BLOCKED`; a block is refused with `ERR_CREDIT_CONDITIONING_BLOCKED` when conditioning is not in fact blocked. Prohibiting reuse requires that underwriting reuse is not permitted and that the target line is lending, and moves the check to `REUSE_PROHIBITED`; a reuse prohibition on an unpermitted line is refused with `ERR_REUSE_UNDERWRITING_PROHIBITED`. A successful decision stamps `decided_at` and `decided_by`, and the three outcomes carry divergent side effects: a `CLEARED` decision sets cross-sell eligibility true for the member's holdings of the target line, a `BLOCKED` decision sets it false for those holdings, and a `REUSE_PROHIBITED` decision sets underwriting reuse false for every lending holding of the member. A check that has reached any of those three outcomes no longer occupies the pending state, and a later cleared check for the same member and target line supersedes the earlier one for eligibility purposes.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource, or add a new distinct resource to a collection, return `201 Created`. Operations that modify an existing resource, or that transition it to a new state, return `200 OK`. All paths are relative to the `/benefits` mount, with the exception of the clock capability, which is mounted at the server root.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the logical clock to a supplied instant | PlatformAdmin |
| POST | `/benefits/members` | Register a new member in prospect standing | Anonymous, PlatformAdmin |
| GET | `/benefits/members` | List members, paginated and filterable | PlatformAdmin, ComplianceOfficer, BenefitsAdmin |
| GET | `/benefits/members/{member_id}` | Get one member | Member, PlatformAdmin, ComplianceOfficer, BenefitsAdmin, Underwriter |
| GET | `/benefits/members/{member_id}/tier-projection` | Forward-looking tier projection | Member, BenefitsAdmin, PlatformAdmin |
| GET | `/benefits/members/{member_id}/churn-breakdown` | Pre-clamp churn score beside each factor | Member, ComplianceOfficer, PlatformAdmin |
| GET | `/benefits/members/{member_id}/deposit-rate-projection` | Deposit-rate boost under the trailing-average variant | Member, BenefitsAdmin, PlatformAdmin |
| GET | `/benefits/members/{member_id}/benefit-summary` | Member-level entitlement rollup counts | Member, BenefitsAdmin, ComplianceOfficer, PlatformAdmin |
| GET | `/benefits/members/{member_id}/rewards-balance` | Posted rewards points balance | Member, PlatformAdmin |
| POST | `/benefits/members/{member_id}/deposits` | Post a payroll deposit against the member's enrolment | PlatformAdmin |
| POST | `/benefits/members/{member_id}/deposits/reverse` | Reverse a previously posted payroll deposit | PlatformAdmin |
| POST | `/benefits/members/{member_id}/requalification-cycles` | Open a requalification cycle for a member | PlatformAdmin |
| POST | `/benefits/members/{member_id}/reinstate` | Reinstate a lapsed member with an adopted product | PlatformAdmin |
| POST | `/benefits/members/{member_id}/reset-to-prospect` | Return a lapsed member with no adopted products to prospect | PlatformAdmin |
| POST | `/benefits/members/{member_id}/detect-churn` | Evaluate churn risk and advance the member machine | PlatformAdmin |
| POST | `/benefits/members/{member_id}/entitlements` | Declare a benefit entitlement unlocked by a holding | BenefitsAdmin |
| POST | `/benefits/members/{member_id}/entitlements/reconcile` | Rewrite every entitlement to its guard verdict | ComplianceOfficer |
| POST | `/benefits/members/{member_id}/rewards/redeem-principal` | Spend rewards points against a loan principal | Member |
| POST | `/benefits/members/{member_id}/rewards/reconcile` | Re-derive the whole redemption history cumulatively | BenefitsAdmin |
| POST | `/benefits/members/{member_id}/rewards/adjust` | Post a manual points adjustment | BenefitsAdmin |
| POST | `/benefits/holdings` | Open a product holding in pending status | PlatformAdmin, BenefitsAdmin |
| GET | `/benefits/holdings` | List product holdings, filterable by member or line | PlatformAdmin, BenefitsAdmin, ComplianceOfficer, Underwriter |
| GET | `/benefits/holdings/{holding_id}` | Get one product holding | Member, PlatformAdmin, BenefitsAdmin, Underwriter, ComplianceOfficer |
| POST | `/benefits/holdings/{holding_id}/adopt` | Adopt a pending or suspended holding | Member |
| POST | `/benefits/holdings/{holding_id}/suspend` | Suspend an adopted holding | PlatformAdmin |
| POST | `/benefits/holdings/{holding_id}/close` | Close a holding permanently | Member |
| POST | `/benefits/loan-accounts` | Originate a loan against an adopted lending holding | Underwriter, PlatformAdmin |
| GET | `/benefits/loan-accounts` | List loan accounts, filterable by member or holding | PlatformAdmin, BenefitsAdmin, Underwriter, ComplianceOfficer |
| GET | `/benefits/loan-accounts/{loan_account_id}` | Get one loan account | Member, PlatformAdmin, Underwriter, BenefitsAdmin, ComplianceOfficer |
| POST | `/benefits/loan-accounts/{loan_account_id}/autopay-enrollment` | Enrol in autopay or resume a suspended enrolment | Member |
| POST | `/benefits/loan-accounts/{loan_account_id}/autopay-suspend` | Suspend autopay on a loan | PlatformAdmin |
| POST | `/benefits/loan-accounts/{loan_account_id}/finalize-pricing` | Promote a loan from provisional to final pricing | Underwriter |
| POST | `/benefits/loan-accounts/{loan_account_id}/applications` | Attach a rate-discount application to a loan | BenefitsAdmin |
| GET | `/benefits/loan-accounts/{loan_account_id}/applications` | List the discount applications on a loan | PlatformAdmin, BenefitsAdmin, Underwriter, Member |
| GET | `/benefits/loan-accounts/{loan_account_id}/pricing-breakdown` | Loan pricing detail under both discount variants | PlatformAdmin, BenefitsAdmin, Underwriter, Member |
| GET | `/benefits/applications` | List discount applications, filterable by loan or rule | PlatformAdmin, BenefitsAdmin, Underwriter, ComplianceOfficer |
| GET | `/benefits/applications/{application_id}` | Get one discount application | PlatformAdmin, BenefitsAdmin, Underwriter, ComplianceOfficer |
| POST | `/benefits/applications/{application_id}/rollback` | Roll back an applied discount application | BenefitsAdmin |
| GET | `/benefits/rate-discount-rules` | List discount rules, filterable by kind, status or parent | PlatformAdmin, BenefitsAdmin, ComplianceOfficer, Underwriter |
| GET | `/benefits/rate-discount-rules/{rule_id}` | Get one discount rule | PlatformAdmin, BenefitsAdmin, ComplianceOfficer, Underwriter |
| POST | `/benefits/rate-discount-rules` | Create a discount rule in draft | BenefitsAdmin |
| PUT | `/benefits/rate-discount-rules/{rule_id}` | Edit a draft rule's stacking link, magnitude or window end | BenefitsAdmin |
| POST | `/benefits/rate-discount-rules/{rule_id}/activate` | Activate a draft rule | BenefitsAdmin |
| POST | `/benefits/rate-discount-rules/{rule_id}/retire` | Retire an active rule | BenefitsAdmin |
| POST | `/benefits/deposit-enrollments` | Open a direct-deposit enrolment in pending verification | PlatformAdmin, BenefitsAdmin |
| GET | `/benefits/deposit-enrollments` | List deposit enrolments, filterable by member | PlatformAdmin, BenefitsAdmin, ComplianceOfficer |
| GET | `/benefits/deposit-enrollments/{enrollment_id}` | Get one deposit enrolment | Member, PlatformAdmin, BenefitsAdmin, ComplianceOfficer |
| POST | `/benefits/deposit-enrollments/{enrollment_id}/activate` | Activate a pending or lapsed enrolment | PlatformAdmin |
| POST | `/benefits/deposit-enrollments/{enrollment_id}/lapse` | Lapse a failing enrolment or move it into grace | PlatformAdmin |
| GET | `/benefits/benefit-entitlements` | List entitlements, filterable by member, benefit or holding | PlatformAdmin, BenefitsAdmin, ComplianceOfficer |
| GET | `/benefits/benefit-entitlements/{entitlement_id}` | Get one entitlement | Member, PlatformAdmin, BenefitsAdmin, ComplianceOfficer |
| POST | `/benefits/benefit-entitlements/{entitlement_id}/step-down` | Step an entitlement's value down without revoking it | BenefitsAdmin |
| POST | `/benefits/benefit-entitlements/{entitlement_id}/restore` | Restore a stepped-down entitlement to full value | BenefitsAdmin |
| POST | `/benefits/benefit-entitlements/{entitlement_id}/request-override` | Queue a compliance override on a stepped-down entitlement | BenefitsAdmin |
| POST | `/benefits/benefit-entitlements/{entitlement_id}/approve-override` | Approve a queued override | ComplianceOfficer |
| GET | `/benefits/rewards-ledger-entries` | List rewards ledger entries, filterable by member or loan | PlatformAdmin, BenefitsAdmin, Member |
| GET | `/benefits/rewards-ledger-entries/{entry_id}` | Get one rewards ledger entry | PlatformAdmin, BenefitsAdmin, Member |
| POST | `/benefits/rewards-ledger-entries/{entry_id}/reverse` | Reverse a posted earning or principal redemption | BenefitsAdmin |
| GET | `/benefits/requalification-cycles` | List requalification cycles, filterable by member | PlatformAdmin, BenefitsAdmin, ComplianceOfficer |
| GET | `/benefits/requalification-cycles/{cycle_id}` | Get one requalification cycle | PlatformAdmin, BenefitsAdmin, ComplianceOfficer, Member |
| POST | `/benefits/requalification-cycles/{cycle_id}/evaluate` | Evaluate an open cycle as passed or failed | PlatformAdmin |
| POST | `/benefits/requalification-cycles/{cycle_id}/open-remediation` | Open a remediation window on a failed cycle | PlatformAdmin |
| POST | `/benefits/requalification-cycles/{cycle_id}/close` | Close a resolved cycle and open its successor | PlatformAdmin |
| GET | `/benefits/churn-notices` | List churn notices, filterable by member | PlatformAdmin, BenefitsAdmin, ComplianceOfficer |
| GET | `/benefits/churn-notices/{notice_id}` | Get one churn notice | Member, PlatformAdmin, BenefitsAdmin, ComplianceOfficer |
| POST | `/benefits/churn-notices/{notice_id}/send` | Dispatch a queued notice | PlatformAdmin |
| POST | `/benefits/churn-notices/{notice_id}/acknowledge` | Member acknowledges a sent notice | Member |
| GET | `/benefits/coaching-sessions` | List coaching sessions, filterable by member or coach | PlatformAdmin, BenefitsAdmin, Member |
| GET | `/benefits/coaching-sessions/{session_id}` | Get one coaching session | Member, PlatformAdmin, BenefitsAdmin |
| POST | `/benefits/coaching-sessions` | Book a career-coaching session or a member-event seat | BenefitsAdmin |
| POST | `/benefits/coaching-sessions/{session_id}/confirm` | Member confirms attendance | Member |
| POST | `/benefits/coaching-sessions/{session_id}/complete` | Mark a confirmed session complete | PlatformAdmin |
| POST | `/benefits/coaching-sessions/{session_id}/cancel` | Cancel a session | Member |
| GET | `/benefits/cross-sell-checks` | List cross-sell checks, filterable by member | PlatformAdmin, ComplianceOfficer, BenefitsAdmin |
| GET | `/benefits/cross-sell-checks/{check_id}` | Get one cross-sell check | PlatformAdmin, ComplianceOfficer, BenefitsAdmin |
| POST | `/benefits/cross-sell-checks` | Open a cross-sell eligibility check | BenefitsAdmin |
| POST | `/benefits/cross-sell-checks/{check_id}/decide` | Record the compliance decision on a check | ComplianceOfficer |

## 5. Error Code Catalogue

The trigger conditions for each code are stated in the narrative of §2 and §3; this catalogue lists only the identifier and the HTTP status it carries.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_AUTH_HEADERS` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_MEMBER_NOT_FOUND` | 404 |
| `ERR_RESOURCE_NOT_FOUND` | 404 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_HOLDING_NOT_ADOPTED` | 409 |
| `ERR_CREDIT_CONDITIONING_BLOCKED` | 422 |
| `ERR_REUSE_UNDERWRITING_PROHIBITED` | 422 |
| `ERR_CONSENT_REQUIRED` | 422 |
| `ERR_OVERRIDE_NOT_PERMITTED` | 422 |
| `ERR_STACK_CLASS_CONFLICT` | 409 |
| `ERR_DUPLICATE_DISCOUNT_APPLICATION` | 409 |
| `ERR_RULE_WINDOW_OVERLAP` | 409 |
| `ERR_DUPLICATE_RULE_CODE` | 409 |
| `ERR_SELF_STACK_CYCLE` | 422 |
| `ERR_BENEFIT_ALREADY_GRANTED` | 409 |
| `ERR_DUPLICATE_ENTITLEMENT` | 409 |
| `ERR_SESSION_OVERLAP` | 409 |
| `ERR_ENROLLMENT_NOT_ACTIVE` | 409 |
| `ERR_GRACE_PERIOD_NOT_ELAPSED` | 409 |
| `ERR_REQUALIFICATION_WINDOW_OPEN` | 409 |
| `ERR_INSUFFICIENT_POINTS` | 422 |
| `ERR_REDEMPTION_LIMIT_EXCEEDED` | 422 |
| `ERR_PRINCIPAL_BELOW_ZERO` | 422 |
| `ERR_STACK_CAP_EXCEEDED` | 422 |
| `ERR_HOLDING_HAS_ACTIVE_LOAN` | 409 |
| `ERR_ENTITLEMENT_NO_SOURCE_HOLDING` | 422 |
| `ERR_ACTIVE_RULE_ON_UNPRICED_LOAN` | 422 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_SESSION_CAPACITY_SATURATED` | 409 |