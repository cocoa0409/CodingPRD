# Card Fraud Ops API — Product Requirements Document

## 1. Introduction

Card issuers run fraud operations as a continuous tension between two failure modes that cannot both be minimized: decline too aggressively and legitimate cardholders are embarrassed at the point of sale, eroding portfolio trust and driving attrition; decline too leniently and organized rings siphon funds through compromised credentials before the first chargeback lands. The Card Fraud Ops API is the operational backbone for the issuer's fraud team — it sits between the card networks' real-time authorization stream and the back-office workflows that turn raw transactions into scored decisions, triaged alerts, customer verification calls, compromised-card reissues, booked losses, and network recovery filings.

The system serves four distinct operator populations with deliberately segregated duties: front-line fraud analysts who work the alert queue and tune scoring rules, fraud operations managers who activate rule changes and confirm compromise events, loss accountants who book confirmed fraud losses, and recovery specialists who pursue chargebacks and network recoveries — plus the cardholders themselves through a narrow self-service surface and the network gateway service account that injects live authorization traffic. Every workflow is driven by a logical clock under test control, so that SLA expiry, reissue auto-approval deadlines, rolling loss windows, and travel-notice validity are all deterministic functions of clock state rather than wall time. Throughout, the design favors auditable state machines, explicit error codes, and invariants that survive replays and compensations — the ledger never drifts, a reversed recovery restores the loss it reduced, and a dismissed ring undoes the watch flags it raised.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two mandatory HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming one of the six declared roles. The roles are spelled exactly `FraudAnalyst`, `FraudOpsManager`, `LossAccountant`, `RecoverySpecialist`, `Cardholder`, and `NetworkGateway`. A request missing either header, or whose `X-User-Role` does not match one of these six spellings, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before any other check runs. A request whose role is authenticated but not permitted on the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403); this same code also fires when an analyst touches an alert or verification contact that is assigned to a different analyst, since assignment-based custody is enforced as a role-permission failure rather than an ownership failure.

Role identity resolves in two distinct ways, and the distinction matters for every ownership check:

- When `X-User-Role` is `Cardholder`, `X-User-ID` is the `id` of the acting `Account`; ownership checks on any resource that references an `Account` — the account itself, an alert's `account_id`, a card's `account_id`, a travel notice reached through its card — compare that foreign-key field to `X-User-ID`, and a mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).
- When `X-User-Role` is `FraudAnalyst`, `FraudOpsManager`, `LossAccountant`, `RecoverySpecialist`, or `NetworkGateway`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example as `created_by_user_id` on a `RuleSet`, `assigned_to_user_id` on a `FraudAlert`, `booked_by_user_id` on a `LossEntry`, or `filed_by_user_id` on a `RecoveryFiling` where transitions stamp it — but it is never compared to any entity's `id`.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items and defaults to 0. Unless a more specific ordering rule applies (the open-alert queue, described in §3.4, is the one exception), every list endpoint returns resources sorted by `created_at` ascending. The `meta` object of any list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every top-level resource — `Account`, `Card`, `RuleSet`, `AuthTransaction`, `FraudAlert`, `VerificationContact`, `CompromisedCardEvent`, `ReissueDecision`, `TravelNotice`, `ChargebackCase`, `LossEntry`, `RecoveryFiling`, `FraudRing`, and `RingMembership` — carries a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` and `updated_at` fields are ISO 8601 UTC timestamps with three fractional digits; `updated_at` refreshes on any mutation of the resource. The same three-fractional-digit ISO 8601 UTC format applies to every server-generated timestamp field on a resource: the intake and transition stamps listed in §2.5 (`scored_at`, `contacted_at`, `booked_at`, `finalized_at`, `confirmed_at`, `resolved_at`, `decided_at`) and the server-computed deadlines derived from them (`sla_expires_at`, `due_at`). The `version` field is an integer that starts at its initial value on creation and increments by one on every mutation; derived-field recomputations that write back to a resource (for example a recomputed `risk_tier` on an `Account`, or a recomputed `outstanding_cents` on a `LossEntry`) count as mutations and therefore advance `updated_at` and `version` like any other change, while a recomputation that produces no new value writes nothing back and leaves `updated_at` and `version` untouched. All fourteen resources in this system carry the full common-field set — none omit `updated_at` or `version`.

### 2.5. The Logical Clock and Lazy Time-Based Transitions

All timestamps, deadlines, windows, and SLA computations in the system are evaluated against a **logical clock**, never wall-clock time. Before any test-driving call has been made, the logical clock is pinned at exactly `2026-08-01T00:00:00Z`; the server must not silently fall back to real time. A `FraudOpsManager` may advance the logical clock by supplying a target instant via the clock-setting capability — the request carries the target as `to_iso8601` — which is the single entry point for time control. Every intake timestamp (`scored_at` on a transaction, `contacted_at` on a contact, `booked_at` on a loss, `finalized_at` on a finalized loss, `confirmed_at` on a compromise event, `resolved_at` on a resolution, `decided_at` on a reissue decision) is stamped from this logical clock at the moment the corresponding write occurs.

Three time-based transitions are applied **lazily**: the system does not run a background scheduler. Instead, whenever an alert, a reissue decision, or a travel notice is read or written — and additionally whenever the logical clock itself is advanced — the server first applies any time-based transition whose trigger instant has been reached, and only then evaluates the rest of the request. An unresolved alert whose logical-clock time has reached `sla_expires_at` (creation plus 72 hours) flips from `OPEN`, `IN_REVIEW`, or `CONTACT_PENDING` to `EXPIRED`; `EXPIRED` is terminal. A reissue decision still in `PENDING` whose `due_at` (the parent event's `confirmed_at` plus 5 days) has been reached flips to `AUTO_APPROVED` and fires the same replacement-card cascade as a manual approval. A travel notice whose `end_date` is at or before the current logical date flips from `ACTIVE` to `EXPIRED`. Because expiry is lazy, a reader may observe an alert as `OPEN` up until the first read or write that occurs at or after the deadline, at which point the flip is applied before the response is produced. The clock-advance pass additionally recomputes every account's derived fields (§2.11, §3.1): because the rolling 90-day loss window ends at the current logical time, advancing the clock can by itself change an account's `rolling_90d_loss_cents` — and therefore the `risk_tier` derived from it — with no other write involved.

### 2.6. Validation Priority Order

When a single request would fail several checks, the failure that is reported is the one with the lowest priority number; later checks are masked by earlier ones. The full order is: authentication (priority 1, `ERR_UNAUTHENTICATED`); role permission including cross-analyst custody (priority 2, `ERR_FORBIDDEN_ROLE`); left-to-right path-id existence (priority 3, `ERR_NOT_FOUND`); cardholder ownership (priority 4, `ERR_NOT_RESOURCE_OWNER`); body foreign-reference resolution (priority 5, `ERR_NOT_FOUND`); request shape — required fields, enum membership, `amount_cents` at least 1 where required, well-formed dates, `review_threshold` strictly below `decline_threshold`, window start strictly before window end, `rationale` present on a decline, and the optimistic-concurrency version field present and current (priority 6); state-machine preconditions (priority 7, including the domain variants `ERR_CHARGEBACK_INVALID_STATE`, `ERR_NO_ACTIVE_RULESET`, and `ERR_ACCOUNT_NOT_ACTIVE`); safety and segregation-of-duties rules (priority 8, including `ERR_CARD_COMPROMISED`, `ERR_SEGREGATION_OF_DUTIES`, `ERR_DECISION_EXPOSURE_REQUIRES_MANAGER`, and `ERR_REOPEN_LIMIT_EXCEEDED`); temporal rules (priority 9, `ERR_TRAVEL_NOTICE_OVERLAP`, `ERR_CONTACT_TOO_SOON`, `ERR_FINALIZE_WINDOW_EXPIRED`); referential and duplicate guards (priority 10, including `ERR_DUPLICATE_EVENT`, `ERR_CHARGEBACK_EXISTS`, `ERR_TXN_ALREADY_IN_LOSS`, `ERR_CONTACT_REQUIRED`, `ERR_CHARGEBACK_PENDING`, `ERR_TXN_NOT_DISPUTABLE`, and `ERR_LOSS_TXN_NOT_CONFIRMED`); and fiscal caps (priority 11, `ERR_DUPLICATE_CREDIT`, `ERR_RECOVERY_EXCEEDS_OUTSTANDING`, `ERR_FINAL_AMOUNT_TOLERANCE`). The practical consequence is that a state error beats a fiscal cap, a missing-resource error beats a state error, and an authentication failure beats everything.

### 2.7. Nested Resource Retrieval and Reverse Reachability

Path parameters are validated strictly left to right: the first identifier in the path that does not resolve to an existing resource produces `ERR_NOT_FOUND` (HTTP 404), and no later identifier or business rule is consulted. Body-carried foreign references — `card_id`, `account_id`, `alert_id`, `auth_transaction_id`, `loss_entry_id`, and every element of `transaction_ids` — are validated after path identifiers, and any that fails to resolve likewise produces `ERR_NOT_FOUND`. Several collections additionally support reverse reachability: cards may be filtered by `account_id` or `replaces_card_id`; transactions by `card_id`, `account_id`, `ruleset_id`, `shadow_ruleset_id`, `decision`, `final_disposition`, or `merchant_id`; alerts by `account_id`, `card_id`, `auth_transaction_id`, `alert_status`, or `assigned_to_user_id`; contacts by `alert_id`, `account_id`, or `contact_status`; chargebacks by `auth_transaction_id`, `account_id`, or `cb_status`; losses by `account_id` or `loss_status`; filings by `loss_entry_id` or `filing_status`; reissue decisions by `event_id`, `card_id`, `decision`, or `replacement_card_id`; rings by `ring_status`; memberships by `ring_id` or `account_id`; rulesets by `scope` or `ruleset_status`; accounts by `status` or `risk_tier`; and travel notices of a card by `notice_status`.

### 2.8. Monetary Precision, Integer Arithmetic, and Pinned Rounding Order

All monetary values in the system are integer cents; there is no floating-point money anywhere. Scores and priorities are integer points. The one genuinely dangerous calculation — the loss provision estimate — pins its rounding order explicitly: each transaction line is individually rounded **half up** to whole cents after applying the network recovery haircut, and only then are the per-line results summed. The alternative order (sum first, round once) is forbidden, because the two orders diverge by a cent on realistic inputs: a VISA line of 10001 cents contributes round-half-up of 5500.55, i.e. 5501, and a MASTERCARD line of 10001 cents contributes round-half-up of 6000.60, i.e. 6001, totalling 11502 — whereas summing first and rounding once would yield 11501. Where a percentage must produce a cent value (the finalize tolerance, and the false-positive rates in basis points), rounding is again half up to the nearest integer.

### 2.9. Optimistic Concurrency Control

Exactly one write endpoint in the system is guarded by optimistic concurrency control: the ruleset-tuning update. A `PUT` against a draft ruleset must carry `expected_ruleset_version`, a non-optional input holding the caller's last-observed `version` of that `RuleSet`. If the value does not equal the ruleset's current `version` — because another update has already advanced it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the caller from silently overwriting tuning it has not observed. No other endpoint accepts a version field; all other state coordination is expressed through the state machines, the segregation-of-duties rules, and the lazy time-based transitions.

### 2.10. Segregation of Duties

Two segregation-of-duties rules are enforced as first-class safety checks. The `FraudOpsManager` who activates a ruleset must not be the operator who created it — the activator's `X-User-ID` is compared to the ruleset's `created_by_user_id`, and a match is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403); the activator's identity is then stamped as `activated_by_user_id`. Symmetrically, the `RecoverySpecialist` who files a network recovery against a loss must not be the `LossAccountant` who booked that loss — the filer's `X-User-ID` (stamped as `filed_by_user_id`) must differ from the loss's `booked_by_user_id`, and a match is again rejected with `ERR_SEGREGATION_OF_DUTIES`. The drafter-checker split on scoring rules and the booker-filer split on loss recovery are the two structural anti-fraud controls on the fraud team itself.

### 2.11. Customer Credit and Loss Ledgers

Two cross-entity ledgers are maintained as computed fields on `Account`, and both are governed by explicit compensating-pair invariants. The customer credit ledger, `credit_balance_cents`, is the sum of `provisional_credit_cents` across the account's chargeback cases in `PROVISIONAL_CREDIT_POSTED`, `REPRESENTMENT_FILED`, or `RESOLVED_WON`, plus the sum of `fraud_credit_cents` across the account's alerts currently in `RESOLVED_FRAUD`. Invariant INV-CREDIT: posting a provisional credit and later resolving that same chargeback `RESOLVED_LOST` leaves the balance unchanged, because the credit exits the qualifying status set exactly as the reversal occurs; reopening a `RESOLVED_FRAUD` alert withdraws its `fraud_credit_cents` from the balance for as long as the alert is no longer `RESOLVED_FRAUD`. The confirmed-loss ledger, `rolling_90d_loss_cents`, is the sum of `final_amount_cents` across the account's losses in `FINALIZED`, `PARTIALLY_RECOVERED`, or `WRITTEN_OFF` whose `finalized_at` falls within the inclusive 90-day window ending at the current logical time; `FULLY_RECOVERED` losses are excluded from the set. On each `LossEntry`, `outstanding_cents` is the `final_amount_cents` minus the sum of `paid_cents` over its recovery filings in `PAID` minus `written_off_cents`; invariant INV-LOSS states that a filing marked `PAID` and later `REVERSED` (a network clawback) leaves `outstanding_cents` unchanged, because reversed filings drop out of the paid sum and thereby restore the outstanding amount. Both ledgers feed the account risk tier described in §3.1. Because the rolling window is defined relative to the current logical time, the account read endpoints refresh the account's derived fields before responding: the single-account GET recomputes the account's `credit_balance_cents`, `open_alert_count`, `rolling_90d_loss_cents`, and `risk_tier`, and the list endpoint recomputes every account before applying its `status` and `risk_tier` filters, so the values returned by these endpoints are never stale with respect to the logical clock.

## 3. Business Logic & Workflows

### 3.1. Accounts, Risk Tiers, and the Card Lifecycle

A `FraudOpsManager` opens an account by supplying `account_number` (unique across all accounts — a duplicate create is rejected with `ERR_INVALID_REQUEST`), `cardholder_name`, and `home_country` (an ISO 3166-1 alpha-2 code used by cross-border scoring). New accounts begin with `account_status` equal to `ACTIVE`, zero balances, zero `open_alert_count`, and `risk_tier` equal to `LOW`. Suspension moves an account from `ACTIVE` to `SUSPENDED` and reinstatement returns it; while an account is `SUSPENDED`, attempts to create new travel notices or new cards for it are rejected with `ERR_ACCOUNT_NOT_ACTIVE` (HTTP 409).

The account's `risk_tier` is recomputed whenever its alert set, loss ledger, or card fraud flags change: the tier is `HIGH` when at least two alerts are open (statuses `OPEN`, `IN_REVIEW`, or `CONTACT_PENDING`), or when the rolling 90-day confirmed loss is at least 100000 cents, or when any card of the account has `fraud_flag` equal to `COMPROMISED`; failing that, the tier is `MEDIUM` when exactly one alert is open, or the rolling loss is at least 25000 cents, or any card carries `fraud_flag` equal to `WATCH`; otherwise the tier is `LOW`. All boundaries are inclusive exactly as written. Triggers for recomputation include alert creation, resolution, reopen, and expiry; card flag changes driven by compromise confirmation, ring confirmation and dismissal, and reissue decline; and loss finalization, recovery payment or reversal, and write-off. The `open_alert_count` field mirrors the count used by the tier rule.

Cards are issued by a `FraudOpsManager` against an `ACTIVE` account, with `pan_token` (unique across all cards, duplicates rejected with `ERR_INVALID_REQUEST`), `product_type` (`DEBIT` or `CREDIT`), and `network` (`VISA` or `MASTERCARD`). A card carries two independent state dimensions on the same row. The `card_status` dimension starts at `ACTIVE` and may move to `SOFT_BLOCKED` (a soft block — the block request carries a `block_type` of `SOFT` — recording a `block_reason` of `ANALYST_REVIEW` or `CUSTOMER_REQUEST` when an operator sets it, or `CONFIRMED_FRAUD` when the system applies it during a fraud resolution), from `SOFT_BLOCKED` back to `ACTIVE` via an unblock, and from either `ACTIVE` or `SOFT_BLOCKED` to the terminal states `HARD_CLOSED` (a hard block by an analyst or manager with `block_type` of `HARD`, which also records a `block_reason`) or `REPLACED` (system-only, on reissue). The `fraud_flag` dimension starts at `CLEAN` and moves to `WATCH` or `COMPROMISED` and back under system control only: confirming a compromised-card event flags matched cards `COMPROMISED`; confirming a fraud ring raises every member account's `CLEAN` cards to `WATCH`; dismissing a previously confirmed ring returns the cards that ring raised back to `CLEAN` (cards that are `COMPROMISED` stay `COMPROMISED`); and declining a reissue decision downgrades the exposed card from `COMPROMISED` to `WATCH`, which is the risk-acceptance path that makes the card eligible for unblocking again. `block_reason` is one of `ANALYST_REVIEW`, `CONFIRMED_FRAUD`, `CUSTOMER_REQUEST`, or `COMPROMISE_EVENT`, and is null whenever `card_status` is `ACTIVE` — an unblock clears it to null.

Unblocking a card is gated by the compromise rule: if the card's `fraud_flag` is `COMPROMISED` and no `ReissueDecision` for that card has been `DECLINED`, the unblock is rejected with `ERR_CARD_COMPROMISED` (HTTP 409). A card carries a self-referential `replaces_card_id`, which is null on original cards and points to the replaced card on a replacement minted by a reissue decision; the replacement inherits the account, `product_type`, and `network`, receives a fresh server-minted `pan_token`, starts `ACTIVE` with `fraud_flag` equal to `WATCH`, and its creation cancels every `ACTIVE` travel notice of the replaced card.

### 3.2. Scoring Rules: Drafting, Activation, and Tuning

Scoring is configured through `RuleSet` resources. Either a `FraudAnalyst` or a `FraudOpsManager` may draft a ruleset, supplying its `scope` (`GLOBAL`, `DEBIT_CARD`, or `CREDIT_CARD`), a `base_score` floor added to every scored authorization, the `review_threshold` and `decline_threshold` integer cutoffs, the `amount_tiers` array (each element a `min_amount_cents` with its associated `points`; no two tiers may repeat the same `min_amount_cents`), the `channel_weights` map (all four keys — `CHIP`, `CONTACTLESS`, `CNP`, `ATM` — required, each mapping to integer points), the `cross_border_weight` applied when the transaction's origin differs from the account's home country, the `high_risk_multiplier` applied to that weight when the origin is a listed high-risk country, the `watch_weight` and `compromised_weight` added for flagged cards, and optionally `high_risk_countries` (defaulting to an empty list). The threshold ordering is strict: `review_threshold` must be strictly less than `decline_threshold`, and equality is rejected along with inversion as `ERR_THRESHOLD_ORDER_INVALID` (HTTP 422). A new ruleset starts in `DRAFT` with its creator recorded as `created_by_user_id`.

Tuning a draft ruleset is the OCC-guarded write described in §2.9: the request must present `expected_ruleset_version` equal to the ruleset's current `version`, and any subset of the tunable fields (`base_score`, `review_threshold`, `decline_threshold`, `amount_tiers`, `channel_weights`, `cross_border_weight`, `high_risk_multiplier`, `watch_weight`, `compromised_weight`, `high_risk_countries`) may be adjusted in one call; a successful update increments `version` by exactly 1, so a second update still carrying the pre-update version fails with `ERR_STALE_VERSION` (HTTP 412).

Activation is a `FraudOpsManager`-only action and enforces segregation of duties: the activator's `X-User-ID` must differ from `created_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`. Activating a `DRAFT` ruleset moves it to `ACTIVE`, stamps `activated_by_user_id`, and supersedes any currently `ACTIVE` ruleset of the same `scope`, which becomes `RETIRED` — so at most one `ACTIVE` ruleset exists per scope at any moment. Either a `DRAFT` or an `ACTIVE` ruleset may be retired manually; retiring the only `ACTIVE` ruleset for a scope leaves that scope without coverage, and subsequent authorization intake for affected cards then fails with `ERR_NO_ACTIVE_RULESET` (HTTP 409). `RETIRED` is terminal.

### 3.3. Real-Time Authorization Scoring and the Shadow Rescore

The `NetworkGateway` service account submits each authorization with `card_id`, `amount_cents` (must be at least 1), `merchant_id`, `merchant_category_code` (the ISO 18245 MCC), `channel` (`CHIP`, `CONTACTLESS`, `CNP`, or `ATM`), `origin_country`, and optionally `currency` (defaulting to `USD`). At intake the server copies `account_id` and `home_country` from the card's account, stamps `scored_at` from the logical clock, and resolves the scoring ruleset by scope: the `ACTIVE` ruleset whose `scope` matches the card's product type (`DEBIT_CARD` for a debit card, `CREDIT_CARD` for a credit card), falling back to the `ACTIVE` `GLOBAL` ruleset when no product-specific one exists; if neither exists, intake is rejected with `ERR_NO_ACTIVE_RULESET`.

When the presented card is not in `card_status` `ACTIVE`, scoring is bypassed entirely: the decision is `DECLINE` with `decision_reason` equal to `CARD_BLOCKED`, `auth_score` and `ruleset_id` are null, no alert is created — but the transaction is still recorded and the intake still returns success (HTTP 201). Otherwise the score is the sum of five integer components: the `base_score`; the `points` of the amount tier with the greatest `min_amount_cents` that is less than or equal to `amount_cents`; the channel's points from `channel_weights`; the cross-border component, which is zero when `origin_country` equals the account's `home_country`, otherwise `cross_border_weight`, and that weight multiplied by `high_risk_multiplier` when the origin appears in `high_risk_countries` (the product must be an integer); and the flag component — `watch_weight` when the card's `fraud_flag` is `WATCH`, `compromised_weight` when `COMPROMISED`, zero when `CLEAN`. Travel suppression overrides the cross-border component to zero when an `ACTIVE` travel notice exists for the card whose `region_country` equals `origin_country` and whose half-open date range contains the date of `scored_at` (start inclusive, end exclusive). The decision is `DECLINE` when the score is at least `decline_threshold` (an inclusive boundary), `REVIEW` when it is at least `review_threshold` but below the decline threshold, and `APPROVE` otherwise; `decision_reason` is `RULE_SCORE`, and the ruleset is pinned on the transaction as `ruleset_id` with the score persisted as `auth_score`. A `REVIEW` decision creates exactly one `FraudAlert` with `source` equal to `SCORING_REVIEW`.

Every read of a transaction additionally computes a **shadow rescore**: the identical formula evaluated under whichever ruleset is `ACTIVE` at read time for the transaction's scope. The result surfaces as `shadow_score`, `shadow_decision` (the decision implied by the shadow score under the current ruleset's thresholds), and `shadow_ruleset_id`; all three are null when no `ACTIVE` ruleset covers the scope at read time. When the pinned ruleset has since been superseded by one with different weights or thresholds, realtime and shadow diverge for identical transaction data — this is deliberate, and it powers the missed-decline monitoring described in §3.9.

### 3.4. The Alert Queue: Priority, Triage, and Claiming

Fraud alerts arrive from two sources. A `SCORING_REVIEW` alert is created automatically on a `REVIEW` decision and copies `account_id`, `card_id`, and `auth_transaction_id` from the source transaction. A `MANUAL` alert is created by a `FraudAnalyst` — for example when a cardholder calls in — supplying `account_id` and `card_id` plus an optional `auth_transaction_id` (the referenced transaction may carry any decision, and it must belong to the given account; the card must also belong to that account, else `ERR_INVALID_REQUEST`). Both sources start in `OPEN` with `assigned_to_user_id` null, `reopen_count` 0, and `sla_expires_at` set to creation plus 72 hours.

Alert priority is computed in a pinned three-step order that avoids a circular dependency: first, the account's `risk_tier` is computed **excluding the alert being created**; second, `band_points` is frozen — 25 for a `MANUAL` alert, or for a `SCORING_REVIEW` alert the transaction's `auth_score` minus the ruleset's `review_threshold`, clamped below at 0 and capped above at 49; third, `priority` is the tier points (0 for `LOW`, 100 for `MEDIUM`, 200 for `HIGH`) plus the frozen `band_points`, and it never changes thereafter except through escalation. Escalation is one-way: when a compromise confirmation or ring confirmation raises an account's tier to `HIGH`, each of that account's open alerts has its `priority` raised to the maximum of its current value and 200 plus its own `band_points`. Creating a new alert never recomputes older alerts' priorities. The triage queue — the list of `OPEN` alerts — is ordered by `priority` descending with ties broken by `created_at` ascending, never by id.

A `FraudAnalyst` claims an `OPEN` alert, moving it to `IN_REVIEW` and stamping `assigned_to_user_id` with their own `X-User-ID`; claiming an alert that is already `IN_REVIEW` fails with `ERR_INVALID_STATE` (HTTP 409). From this point forward, the alert is in that analyst's custody: any other analyst attempting to work it — recording a contact, resolving it — is rejected with `ERR_FORBIDDEN_ROLE`.

### 3.5. Customer Verification Contact and Alert Resolution

While working an alert, the assigned analyst records outbound contact attempts as `VerificationContact` resources, supplying `alert_id` and `channel` (`VOICE`, `SMS`, or `EMAIL`; the fourth value `IN_APP` is reserved for cardholder-initiated responses). Creating a contact requires the alert to be `IN_REVIEW` or `CONTACT_PENDING` and assigned to the caller, and it enforces a per-account contact gap: at least 60 minutes must separate this attempt from the account's most recent contact, and an attempt landing strictly inside that gap is rejected with `ERR_CONTACT_TOO_SOON` (HTTP 409). Each contact is stamped with `contacted_at` from the logical clock, with `created_by_user_id` set to the analyst (or `SYSTEM` for cardholder-initiated `IN_APP` contacts), with `account_id` copied from the alert, and starts `PENDING`; creating it transitions the alert from `IN_REVIEW` to `CONTACT_PENDING`. The creating analyst later completes the contact by supplying an `outcome` of `CONFIRMED_FRAUD`, `CONFIRMED_LEGIT`, or `UNREACHABLE`, moving it to `COMPLETED`; only the creating analyst may complete their own contact.

Resolution moves an alert from `IN_REVIEW` or `CONTACT_PENDING` to `RESOLVED_FRAUD` or `RESOLVED_LEGIT` and requires a fresh, matching customer contact: a `COMPLETED` verification contact for this alert whose `outcome` matches the resolution and whose `contacted_at` is strictly after the alert's most recent resolution — an alert with no matching fresh contact is rejected with `ERR_CONTACT_REQUIRED`, and an `UNREACHABLE` outcome never satisfies any resolution. An analyst resolves through the resolve action with a `resolution` of `FRAUD` or `LEGIT`; an `OPEN` alert must be claimed before resolution through this path. A `Cardholder` may instead respond directly through the self-service respond action with an `outcome`, which creates an already-`COMPLETED` `IN_APP` contact and resolves the alert in one step — this path works even while the alert is still `OPEN`.

Resolving `FRAUD` carries four side effects: if the alert references a transaction, that transaction's `final_disposition` becomes `CONFIRMED_FRAUD`; if the card is still `ACTIVE`, it is soft-blocked with `block_reason` `CONFIRMED_FRAUD`; the optional `fraud_credit_cents` granted to the customer (subject to the duplicate-credit cap of §3.7 — exceeding it yields `ERR_DUPLICATE_CREDIT`) feeds the account's `credit_balance_cents` for as long as the alert remains `RESOLVED_FRAUD`; and the account's `risk_tier` is recomputed. Resolving `LEGIT` requires `fraud_credit_cents` to be absent or zero (`ERR_INVALID_REQUEST` otherwise) and sets the transaction's `final_disposition` to `CONFIRMED_LEGIT`. Latest resolution wins on the transaction: a later `LEGIT` resolution may overwrite an earlier `CONFIRMED_FRAUD` disposition and vice versa.

A resolved alert may be reopened — moving from `RESOLVED_FRAUD` or `RESOLVED_LEGIT` back to `IN_REVIEW` — by an analyst or manager supplying a `reason`, subject to two guards evaluated in order: `reopen_count` must be below 2, else `ERR_REOPEN_LIMIT_EXCEEDED` (HTTP 409), and the logical clock must not have passed `resolved_at` plus 30 days, else `ERR_INVALID_STATE`. A successful reopen increments `reopen_count` by 1; reopening a `RESOLVED_FRAUD` alert immediately withdraws its `fraud_credit_cents` from the account's credit balance; and the risk tier is recomputed as the alert rejoins the open set. Any alert left unresolved reaches `EXPIRED` when the logical clock passes `sla_expires_at`, applied lazily per §2.5.

### 3.6. Compromised-Card Events and the Reissue Cascade

Network compromised-card feeds (CAMS and ADC) arrive as `CompromisedCardEvent` intake by a `FraudOpsManager`, carrying `network_source` (`CAMS` or `ADC`), a network-supplied `event_reference` (globally unique — a duplicate intake is rejected with `ERR_DUPLICATE_EVENT`), the common-point-of-purchase `merchant_id`, and the half-open exposure window `window_start` (inclusive) to `window_end` (exclusive); a window whose start is not strictly before its end is rejected with `ERR_INVALID_WINDOW` (HTTP 422). Events begin with `event_status` equal to `RECEIVED`.

Confirmation is the system's largest cascade, executed as four linked effects when a `FraudOpsManager` confirms a `RECEIVED` event. First, every card with at least one transaction at the event's `merchant_id` whose `scored_at` falls inside the half-open window — transactions with any decision, `APPROVE`, `REVIEW`, or `DECLINE`, all count as exposure — has its `fraud_flag` set from `CLEAN` or `WATCH` to `COMPROMISED`, and `affected_card_count` records how many distinct cards matched. Second, each newly compromised card spawns a `ReissueDecision` in `PENDING` with `due_at` set to `confirmed_at` plus 5 days and `exposure_cents` computed as the sum of `amount_cents` over that card's matching transactions at the event merchant inside the window; creation order is deterministic — by each card's earliest matching transaction `scored_at` ascending, ties broken by the card's `created_at` ascending, never by id. Third, every owning account's `risk_tier` is recomputed (any `COMPROMISED` card forces `HIGH`). Fourth, every account whose tier rose to `HIGH` escalates its open alerts' priorities per §3.4. The event's `confirmed_at` is stamped at confirmation. Once no `ReissueDecision` of the event remains `PENDING` — every one is `APPROVED`, `DECLINED`, or `AUTO_APPROVED` — the event itself transitions from `CONFIRMED` to `CLOSED`, checked after each decision and on clock advances.

Each `PENDING` reissue decision is acted on by an analyst or manager through the decide action. Approving (or the system's `AUTO_APPROVED` at `due_at`, which stamps `decided_by_user_id` as `SYSTEM`) mints the replacement card per §3.1, records it as `replacement_card_id`, moves the exposed card to `REPLACED` if it is `ACTIVE` or `SOFT_BLOCKED`, cancels that card's `ACTIVE` travel notices, and re-evaluates the parent event's auto-close. Declining requires a `rationale` (`ERR_INVALID_REQUEST` when missing), and when `exposure_cents` exceeds 50000 cents the decline is restricted to a `FraudOpsManager` — an analyst attempting it is rejected with `ERR_DECISION_EXPOSURE_REQUIRES_MANAGER` (HTTP 403); a decline downgrades the card's `fraud_flag` from `COMPROMISED` to `WATCH` (risk accepted, making the card unblockable again) and likewise re-evaluates the parent event. Both manual paths stamp `decided_by_user_id` and `decided_at`. `PENDING` decisions that reach `due_at` auto-approve lazily on any read or write of the decision and on clock advances.

### 3.7. Chargebacks and the Duplicate-Credit Cap

A `RecoverySpecialist` files a chargeback against a transaction by supplying `auth_transaction_id`, the network `reason_code`, and a `provisional_credit_cents` amount — zero is permitted, in which case the case opens in `FILED` with no credit attached. Filing requires the transaction's `decision` to be `APPROVE`, else `ERR_TXN_NOT_DISPUTABLE` (HTTP 409), and at most one non-terminal chargeback may exist per transaction, else `ERR_CHARGEBACK_EXISTS` (HTTP 409); the case's `account_id` is denormalized from the transaction at creation. Note that the duplicate-credit cap is deliberately **not** checked at filing time — it is enforced at posting time.

Posting the provisional credit moves a case from `FILED` to `PROVISIONAL_CREDIT_POSTED`. The state check fires first: posting on a case in any other status is rejected with `ERR_CHARGEBACK_INVALID_STATE`. Then `provisional_credit_cents` must be at least 1 (`ERR_INVALID_REQUEST`). Finally the fiscal cap is enforced: the posted amount plus the sum of the transaction's existing active chargeback credits plus the `fraud_credit_cents` of any `RESOLVED_FRAUD` alerts on that transaction must not exceed the transaction's `amount_cents` — equality is allowed — else `ERR_DUPLICATE_CREDIT` (HTTP 422). The same cap applies to `fraud_credit_cents` granted at a `FRAUD` alert resolution. Posting adds the amount to the account's `credit_balance_cents`.

From `PROVISIONAL_CREDIT_POSTED` the case may advance to `REPRESENTMENT_FILED` via the representment action. Resolution then splits by outcome: `WON` is only valid from `REPRESENTMENT_FILED` and keeps the credit counting toward the account balance (the case settles in `RESOLVED_WON`); `LOST` is valid from either `PROVISIONAL_CREDIT_POSTED` or `REPRESENTMENT_FILED` and reverses the credit — it stops counting toward the balance, per invariant INV-CREDIT. A case may be withdrawn only from `FILED`, before any credit was posted. `RESOLVED_WON`, `RESOLVED_LOST`, and `WITHDRAWN` are terminal. Invalid transitions on this machine — posting on a withdrawn case, winning without representment — surface as `ERR_CHARGEBACK_INVALID_STATE` rather than the generic state error.

### 3.8. Loss Booking, Finalization, and Network Recovery

A `LossAccountant` books a fraud loss candidate by supplying `account_id` and a non-empty `transaction_ids` array. Every listed transaction must belong to the given account and carry `final_disposition` equal to `CONFIRMED_FRAUD`, else `ERR_LOSS_TXN_NOT_CONFIRMED` (HTTP 422); and each transaction may appear in at most one non-terminal loss entry, else `ERR_TXN_ALREADY_IN_LOSS`. At creation the system computes the provisional estimate per the pinned rounding order of §2.8: for each transaction, take its `amount_cents`, multiply by one minus the network recovery rate for that transaction's card network (45 percent for `VISA`, 40 percent for `MASTERCARD`), round the result half up to whole cents, and sum the per-line results into `provisional_amount_cents`. The `tolerance_cents` is the provisional amount multiplied by ten percent, rounded half up. The entry begins in `ESTIMATED` with `outstanding_cents` and `written_off_cents` at zero and `final_amount_cents` null.

The book action moves an entry from `ESTIMATED` to `BOOKED`, stamping `booked_by_user_id` and `booked_at`. Finalization moves it from `BOOKED` to `FINALIZED` and checks four preconditions in their validation-priority order: the state must be `BOOKED`; the logical clock must not have passed `booked_at` plus 30 days — the temporal check, evaluated before the fiscal one, failing with `ERR_FINALIZE_WINDOW_EXPIRED`; no covered transaction may have a chargeback in `FILED`, `PROVISIONAL_CREDIT_POSTED`, or `REPRESENTMENT_FILED`, else `ERR_CHARGEBACK_PENDING`; and the accountant-supplied `final_amount_cents` must lie within the inclusive tolerance band centered on `provisional_amount_cents` — the absolute difference must not exceed `tolerance_cents`, and a difference of exactly `tolerance_cents` passes — else `ERR_FINAL_AMOUNT_TOLERANCE` (HTTP 422). Finalization stamps `final_amount_cents` and `finalized_at`, sets `outstanding_cents` to the final amount, and recomputes the account's rolling 90-day loss and risk tier. A `FINALIZED` or `PARTIALLY_RECOVERED` entry with positive outstanding may be written off, moving to `WRITTEN_OFF` with `written_off_cents` set to the full remaining `outstanding_cents` (driving it to zero); writing off when nothing remains is rejected with `ERR_INVALID_STATE`. `FULLY_RECOVERED` and `WRITTEN_OFF` are terminal.

A `RecoverySpecialist` files a network recovery against a `FINALIZED` or `PARTIALLY_RECOVERED` loss, supplying `loss_entry_id`, a unique `network_reference` (duplicates rejected with `ERR_INVALID_REQUEST`), and `claimed_cents`, which must be at least 1 and no more than the loss's `outstanding_cents` at filing time, else `ERR_RECOVERY_EXCEEDS_OUTSTANDING` (HTTP 422). The filer's `X-User-ID` is stamped as `filed_by_user_id` and must differ from the loss's `booked_by_user_id` per §2.10. Filings begin in `FILED` and are progressed through the mark-outcome action: from `FILED` to `ACCEPTED` or `REJECTED`; from `ACCEPTED` to `PAID`, which requires `paid_cents` present and at least 1, no more than `claimed_cents`, and no more than the loss's current `outstanding_cents` (violations of either bound are `ERR_RECOVERY_EXCEEDS_OUTSTANDING`; marking `PAID` directly from `FILED` is `ERR_INVALID_STATE`); and from `PAID` to `REVERSED`, modelling a network clawback. A payment recomputes the loss's `outstanding_cents` per INV-LOSS and cascades into status: a payment that leaves outstanding at zero moves the loss to `FULLY_RECOVERED` (which also drops it from the account's rolling-loss set and recomputes the tier), while a partial payment moves a `FINALIZED` loss to `PARTIALLY_RECOVERED`. A reversal restores `outstanding_cents` by the reversed `paid_cents` and recomputes status — outstanding back to the full `final_amount_cents` returns the loss to `FINALIZED`, while a positive remainder below the full amount leaves it `PARTIALLY_RECOVERED` — then recomputes the account's rolling loss and risk tier.

### 3.9. Ring Detection and Cross-Account Pattern Confirmation

Ring detection is a `FraudOpsManager` capability that scans for the one signal supported in v1, `COMMON_MERCHANT`: given `signal_type`, `merchant_id`, and a half-open detection window `window_start` to `window_end` (start strictly before end, else `ERR_INVALID_WINDOW`), the system identifies every account with at least 2 `APPROVE` transactions at that merchant whose `scored_at` falls in the window. When at least 3 accounts qualify, a `FraudRing` is created in `SUSPECTED` together with a `RingMembership` per member account recording the account's `evidence_txn_count`; `member_count` mirrors the membership count. Fewer than 3 qualifying accounts — exactly 3 succeeds — is rejected with `ERR_RING_THRESHOLD_NOT_MET` (HTTP 409).

Confirming a `SUSPECTED` ring moves it to `CONFIRMED` and cascades: every card of every member account whose `fraud_flag` is `CLEAN` becomes `WATCH`; every member account's `risk_tier` is recomputed; and every member account whose tier rose to `HIGH` escalates its open alerts per §3.4. Dismissal from `SUSPECTED` simply moves the ring to `DISMISSED`. Dismissal from `CONFIRMED` compensates: the cards that this ring's confirmation raised to `WATCH` return to `CLEAN` (cards that are `COMPROMISED` remain so), and member accounts' tiers are recomputed. `DISMISSED` is terminal.

### 3.10. Travel Notices and Cross-Border Suppression

Travel notices let the scoring engine distinguish a cardholder's announced travel from hostile cross-border use. A `FraudAnalyst`, or a `Cardholder` acting on their own cards, creates a notice with `card_id`, `region_country`, `start_date`, and `end_date` (both ISO 8601 dates in `YYYY-MM-DD` form). The date range is half-open — `start_date` inclusive, `end_date` exclusive — and `end_date` must fall after `start_date`, else `ERR_INVALID_WINDOW`. Overlap is policed per card and region: a new `ACTIVE` notice that overlaps an existing `ACTIVE` notice for the same card and `region_country` under half-open interval semantics (touching boundaries do not overlap) is rejected with `ERR_TRAVEL_NOTICE_OVERLAP` (HTTP 409). Creation requires the owning account to be `ACTIVE`. A notice begins `ACTIVE`, may be cancelled by an analyst or by the owning cardholder (moving to `CANCELLED`), and flips to `EXPIRED` lazily once the logical clock's current date reaches `end_date`. While `ACTIVE`, a notice whose region matches a transaction's `origin_country` suppresses the cross-border scoring component per §3.3.

### 3.11. Ruleset Monitoring: False-Positive Rate versus Confirmed Loss

Tuning decisions rest on a per-ruleset metrics view, readable by analysts and managers, computed over the population of transactions pinned to that ruleset via `ruleset_id`. The view reports `scored_count`, `approved_count`, `review_count`, and `declined_count` as the population split by `decision`; `confirmed_fraud_count` and `confirmed_legit_count` as the split by `final_disposition`; and `gross_confirmed_loss_cents` as the sum of `final_amount_cents` over losses in `FINALIZED`, `PARTIALLY_RECOVERED`, `FULLY_RECOVERED`, or `WRITTEN_OFF` that cover transactions of this population.

The false-positive rate is deliberately reported on two bases, because "what is the false-positive rate" has two legitimate answers that diverge whenever declined traffic is confirmed legitimate at a different rate than reviewed traffic. The review-basis rate, `fp_rate_review_basis_bp`, divides the count of legitimately-disposed `REVIEW` transactions by the count of `REVIEW` transactions with any disposition other than `UNDISPOSED`, scales to basis points by ten thousand, and rounds half up to an integer; when no `REVIEW` transaction has been disposed, the rate is 0. The decline-basis rate, `fp_rate_decline_basis_bp`, applies the identical formula over `DECLINE` transactions. Finally, `missed_declines_under_current` counts transactions of the population whose realtime `decision` was not `DECLINE` but whose `shadow_decision` under the currently active ruleset is `DECLINE` — the shadow rescore of §3.3 surfacing traffic the current tuning would have stopped.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource return `200 OK`. The system is mounted under `/fraudops`, with the logical-clock test-driving capability mounted separately. Readers should refer to §3 for the full request/response semantics of each operation.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the logical clock; lazily applies due time-based transitions | FraudOpsManager |
| POST | `/fraudops/rule-sets` | Create a DRAFT ruleset | FraudAnalyst, FraudOpsManager |
| GET | `/fraudops/rule-sets` | List rulesets with optional filters | FraudAnalyst, FraudOpsManager |
| GET | `/fraudops/rule-sets/{id}` | Get one ruleset | FraudAnalyst, FraudOpsManager |
| PUT | `/fraudops/rule-sets/{id}` | Tune a DRAFT ruleset (OCC-guarded) | FraudAnalyst, FraudOpsManager |
| POST | `/fraudops/rule-sets/{id}/activate` | Activate a DRAFT ruleset; supersedes the ACTIVE ruleset of the same scope | FraudOpsManager |
| POST | `/fraudops/rule-sets/{id}/retire` | Retire a DRAFT or ACTIVE ruleset | FraudOpsManager |
| GET | `/fraudops/rule-sets/{id}/metrics` | False-positive vs loss trade-off monitor for this ruleset | FraudAnalyst, FraudOpsManager |
| POST | `/fraudops/accounts` | Open an account | FraudOpsManager |
| GET | `/fraudops/accounts` | List accounts with optional filters | FraudAnalyst, FraudOpsManager, LossAccountant, RecoverySpecialist |
| GET | `/fraudops/accounts/{id}` | Get one account; Cardholder reads only their own | FraudAnalyst, FraudOpsManager, LossAccountant, RecoverySpecialist, Cardholder |
| POST | `/fraudops/accounts/{id}/suspend` | Suspend an ACTIVE account | FraudOpsManager |
| POST | `/fraudops/accounts/{id}/reinstate` | Reinstate a SUSPENDED account | FraudOpsManager |
| POST | `/fraudops/cards` | Issue a card on an ACTIVE account | FraudOpsManager |
| GET | `/fraudops/cards` | List cards with optional filters | FraudAnalyst, FraudOpsManager |
| GET | `/fraudops/cards/{id}` | Get one card | FraudAnalyst, FraudOpsManager |
| POST | `/fraudops/cards/{id}/block` | Soft-block or hard-block a card | FraudAnalyst, FraudOpsManager |
| POST | `/fraudops/cards/{id}/unblock` | Unblock a SOFT_BLOCKED card | FraudAnalyst, FraudOpsManager |
| GET | `/fraudops/cards/{id}/travel-notices` | List travel notices of a card | FraudAnalyst, FraudOpsManager, Cardholder |
| POST | `/fraudops/auth-transactions` | Real-time authorization intake with scoring | NetworkGateway |
| GET | `/fraudops/auth-transactions` | List transactions with optional filters | FraudAnalyst, FraudOpsManager, RecoverySpecialist |
| GET | `/fraudops/auth-transactions/{id}` | Get one transaction with shadow rescore | FraudAnalyst, FraudOpsManager, RecoverySpecialist |
| POST | `/fraudops/fraud-alerts` | Create a MANUAL alert | FraudAnalyst |
| GET | `/fraudops/fraud-alerts` | List alerts; OPEN queue ordered by priority DESC, created_at ASC | FraudAnalyst, FraudOpsManager |
| GET | `/fraudops/fraud-alerts/{id}` | Get one alert; Cardholder reads only own-account alerts | FraudAnalyst, FraudOpsManager, Cardholder |
| POST | `/fraudops/fraud-alerts/{id}/claim` | Claim an OPEN alert | FraudAnalyst |
| POST | `/fraudops/fraud-alerts/{id}/resolve` | Resolve an alert as FRAUD or LEGIT | FraudAnalyst |
| POST | `/fraudops/fraud-alerts/{id}/respond` | Cardholder self-service response resolving the alert | Cardholder |
| POST | `/fraudops/fraud-alerts/{id}/reopen` | Reopen a resolved alert | FraudAnalyst, FraudOpsManager |
| POST | `/fraudops/verification-contacts` | Record an outbound contact attempt for an alert | FraudAnalyst |
| GET | `/fraudops/verification-contacts` | List contacts with optional filters | FraudAnalyst, FraudOpsManager |
| GET | `/fraudops/verification-contacts/{id}` | Get one contact | FraudAnalyst, FraudOpsManager |
| POST | `/fraudops/verification-contacts/{id}/complete` | Complete a PENDING contact with an outcome | FraudAnalyst |
| POST | `/fraudops/compromised-card-events` | CAMS/ADC event intake | FraudOpsManager |
| GET | `/fraudops/compromised-card-events` | List events | FraudAnalyst, FraudOpsManager |
| GET | `/fraudops/compromised-card-events/{id}` | Get one event | FraudAnalyst, FraudOpsManager |
| POST | `/fraudops/compromised-card-events/{id}/confirm` | Confirm an event; full compromise cascade | FraudOpsManager |
| GET | `/fraudops/reissue-decisions` | List reissue decisions with optional filters | FraudAnalyst, FraudOpsManager |
| GET | `/fraudops/reissue-decisions/{id}` | Get one reissue decision | FraudAnalyst, FraudOpsManager |
| POST | `/fraudops/reissue-decisions/{id}/decide` | Approve or decline a PENDING reissue decision | FraudAnalyst, FraudOpsManager |
| POST | `/fraudops/travel-notices` | Create a travel notice | FraudAnalyst, Cardholder |
| GET | `/fraudops/travel-notices/{id}` | Get one travel notice | FraudAnalyst, FraudOpsManager, Cardholder |
| POST | `/fraudops/travel-notices/{id}/cancel` | Cancel an ACTIVE travel notice | FraudAnalyst, Cardholder |
| POST | `/fraudops/chargeback-cases` | File a chargeback | RecoverySpecialist |
| GET | `/fraudops/chargeback-cases` | List chargebacks with optional filters | RecoverySpecialist, FraudOpsManager |
| GET | `/fraudops/chargeback-cases/{id}` | Get one chargeback | RecoverySpecialist, FraudOpsManager |
| POST | `/fraudops/chargeback-cases/{id}/post-provisional-credit` | Post the provisional credit | RecoverySpecialist |
| POST | `/fraudops/chargeback-cases/{id}/representment` | File representment | RecoverySpecialist |
| POST | `/fraudops/chargeback-cases/{id}/resolve` | Resolve a chargeback WON or LOST | RecoverySpecialist |
| POST | `/fraudops/chargeback-cases/{id}/withdraw` | Withdraw a FILED chargeback | RecoverySpecialist |
| POST | `/fraudops/loss-entries` | Book a loss candidate over CONFIRMED_FRAUD transactions | LossAccountant |
| GET | `/fraudops/loss-entries` | List losses with optional filters | LossAccountant, RecoverySpecialist, FraudOpsManager |
| GET | `/fraudops/loss-entries/{id}` | Get one loss | LossAccountant, RecoverySpecialist, FraudOpsManager |
| POST | `/fraudops/loss-entries/{id}/book` | Book an ESTIMATED loss | LossAccountant |
| POST | `/fraudops/loss-entries/{id}/finalize` | Finalize a BOOKED loss within tolerance | LossAccountant |
| POST | `/fraudops/loss-entries/{id}/write-off` | Write off the remaining outstanding amount | LossAccountant |
| POST | `/fraudops/recovery-filings` | File a network recovery against a loss | RecoverySpecialist |
| GET | `/fraudops/recovery-filings` | List filings with optional filters | RecoverySpecialist, LossAccountant, FraudOpsManager |
| GET | `/fraudops/recovery-filings/{id}` | Get one filing | RecoverySpecialist, LossAccountant, FraudOpsManager |
| POST | `/fraudops/recovery-filings/{id}/mark-outcome` | Mark a filing ACCEPTED, REJECTED, PAID, or REVERSED | RecoverySpecialist |
| POST | `/fraudops/fraud-rings/detect` | Detect a COMMON_MERCHANT ring | FraudOpsManager |
| GET | `/fraudops/fraud-rings` | List rings | FraudAnalyst, FraudOpsManager |
| GET | `/fraudops/fraud-rings/{id}` | Get one ring | FraudAnalyst, FraudOpsManager |
| POST | `/fraudops/fraud-rings/{id}/confirm` | Confirm a SUSPECTED ring | FraudOpsManager |
| POST | `/fraudops/fraud-rings/{id}/dismiss` | Dismiss a SUSPECTED or CONFIRMED ring | FraudOpsManager |
| GET | `/fraudops/ring-memberships` | List memberships with optional filters | FraudAnalyst, FraudOpsManager |
| GET | `/fraudops/ring-memberships/{id}` | Get one membership | FraudAnalyst, FraudOpsManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_WINDOW` | 422 |
| `ERR_THRESHOLD_ORDER_INVALID` | 422 |
| `ERR_ACCOUNT_NOT_ACTIVE` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_CHARGEBACK_INVALID_STATE` | 409 |
| `ERR_NO_ACTIVE_RULESET` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_CARD_COMPROMISED` | 409 |
| `ERR_DECISION_EXPOSURE_REQUIRES_MANAGER` | 403 |
| `ERR_REOPEN_LIMIT_EXCEEDED` | 409 |
| `ERR_TRAVEL_NOTICE_OVERLAP` | 409 |
| `ERR_CONTACT_TOO_SOON` | 409 |
| `ERR_FINALIZE_WINDOW_EXPIRED` | 409 |
| `ERR_DUPLICATE_EVENT` | 409 |
| `ERR_CHARGEBACK_EXISTS` | 409 |
| `ERR_TXN_NOT_DISPUTABLE` | 409 |
| `ERR_TXN_ALREADY_IN_LOSS` | 409 |
| `ERR_LOSS_TXN_NOT_CONFIRMED` | 422 |
| `ERR_CONTACT_REQUIRED` | 409 |
| `ERR_CHARGEBACK_PENDING` | 409 |
| `ERR_DUPLICATE_CREDIT` | 422 |
| `ERR_FINAL_AMOUNT_TOLERANCE` | 422 |
| `ERR_RECOVERY_EXCEEDS_OUTSTANDING` | 422 |
| `ERR_RING_THRESHOLD_NOT_MET` | 409 |
