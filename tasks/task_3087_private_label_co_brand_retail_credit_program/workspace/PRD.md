# Private Label Retail Credit Program API — Product Requirements Document

## 1. Introduction

Retail credit programs sit at an intersection of two businesses that rarely share a vocabulary: a retailer that wants its customers financed at the point of sale, and an issuer that carries the receivable, the promotional subsidy, and the regulatory disclosure burden. This API is the servicing backbone of such a partnership. It holds the economic agreement between the two parties, the credit program issued under that agreement, the accounts and purchases that flow through the program, and the promotional financing machinery that makes the whole arrangement profitable for the retailer without becoming a one-sided subsidy for the issuer.

The commercial heart of the product is the deferred-interest promotion: a purchase above a minimum threshold is financed at no interest for a fixed term, and the interest that would have accrued is carried as an exposure the two parties have agreed to share. Modeling that exposure correctly — at the moment the promotion is written, and again when it is settled — is the single most important behavior in the system, because every partner-facing invoice, every reconciliation variance, and every wind-down purchase price is read off those two numbers. Alongside it sits a second, subtler requirement: the cardholder experience is branded as the retailer, so dispute handling, servicing correspondence, and loyalty accrual must all look and behave as though the retailer were the creditor.

What follows specifies the partner onboarding and agreement lifecycle, the program and account servicing flows, the application and instant-decisioning path, the promotional settlement and partner chargeback reconciliation, the dispute and loyalty benefit subsystem, and the wind-down and portfolio transfer process. It defines behavior only; no implementation structure is prescribed beyond the API contract itself.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two headers. `X-User-ID` identifies the acting user, and `X-User-Role` declares the operational capacity in which they are acting. A request that omits or malforms either header is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request that carries a valid role which is not permitted for the requested operation is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes seven roles, spelled exactly as follows: `ProgramAdmin`, `RetailPartnerAnalyst`, `Underwriter`, `CardholderService`, `Cardholder`, `Applicant`, and `CoBrandIssuer`.

`ProgramAdmin` is the issuer-side operations administrator. `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server may record it on resources where a transition names the acting operator, but it is never compared against any entity's `id`. The same is true of `Underwriter`, `CardholderService`, and `Applicant` — for each of these role values, `X-User-ID` is an opaque identifier with no corresponding entity row, and no ownership comparison is performed against it.

`RetailPartnerAnalyst` is a retail-partner-side analyst, and for this role `X-User-ID` is the `id` of the acting `RetailPartner`. Ownership checks on any resource that references a `RetailPartner` therefore compare the resource's partner foreign-key field to `X-User-ID`; the analyst sees only their own partner's agreement, program, and settlement data.

`Cardholder` is the consumer acting on their own account, and for this role `X-User-ID` is the `id` of the acting `Account`. Any operation a `Cardholder` performs against an account, a purchase, a benefit posting, or a dispute is ownership-checked against that account identifier — a `Cardholder` may act only on the account named by `X-User-ID`, and a mismatch is rejected with `ERR_UNAUTHORIZED`.

`CoBrandIssuer` is a co-brand issuer partner holding a delegated portfolio purchase right; `X-User-ID` for this role is an opaque identifier not tied to a persisted entity, and it is not compared against any entity's `id`.

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

List endpoints accept two query parameters. `limit` sets the maximum number of items returned in one page; it defaults to 10 and must be an integer between 1 and 100 inclusive. `offset` sets the number of leading items to skip and defaults to 0.

Unless a business rule states otherwise, list endpoints return resources sorted by `created_at` in ascending order.

List responses carry four pagination fields in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`. `total_count` reports the total number of matching resources before pagination is applied, and `has_more` reports whether further pages remain.

### 2.4. Retailer-Branded Servicing and Ownership Boundaries

Servicing correspondence in this program is issued in the retailer's name, never the issuer's. Every dispute case carries a `servicing_brand_name` field whose value is the owning retailer's `retailer_name`; it is a read-only projection computed at case creation and never accepted from a client. Nothing in the dispute workflow may cause an issuer name to surface in a cardholder-facing field.

Ownership enforcement applies to the roles described in §2.1. A `Cardholder` may only act against the `Account` named by their `X-User-ID`, a `RetailPartnerAnalyst` may only read the resources tied to their `RetailPartner`, and the opaque operator roles carry no per-resource ownership restriction beyond the role permission itself.

### 2.5. Logical Clock and Scheduled Effects

The system runs on a logical clock rather than wall-clock time. Before any clock operation is performed the clock reads exactly `2026-09-01T00:00:00Z`, and the server must never fall back to real system time. Two test-driving capabilities administer it. The first sets the logical clock to a supplied ISO-8601 instant via the `to_iso8601` field. The second advances the clock by a whole number of days supplied in `days`; the accepted range is 1 to 3650 inclusive, and a request outside that range is rejected with `ERR_INVALID_ADVANCE_DAYS` (HTTP 422). A successful advance responds with the resulting `current_utc` and the `advanced_days` actually applied.

An advance is not merely a counter increment. It must run every scheduled effect that falls due inside the advanced window, in chronological order: accounts whose scheduled minimum payment was missed past its due date move from `ACTIVE` to `DELINQUENT`; promotional plans whose expiry instant has been reached move from `ACTIVE` to `EXPIRED`; and statement close and payment-due dating fire on the account's `cycle_day`.

The `cycle_day` field on a program is an integer from 1 to 31. When it is set to 29, 30, or 31 and the current month is shorter, the statement close clamps to the last real day of that month.

### 2.6. Common Resource Properties

Every top-level resource in this API — `RetailPartner`, `ProgramAgreement`, `CreditProgram`, `Account`, `Application`, `Transaction`, `PromoPlan`, `SettlementBatch`, `DisputeCase`, `BenefitPosting`, `ScheduledBalance`, and `WindDownTransfer` — shares a common set of system-managed properties, because every one of these entities declares `common_fields: true`:

- `id` (string) — a server-minted UUID with no type prefix or namespace segment.
- `created_at` (string) — an ISO 8601 UTC timestamp with three fractional digits, set once at creation.
- `updated_at` (string) — an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer) — a system-managed counter that increments by one on every mutation of the resource, used for optimistic concurrency control.

No entity in this program omits `updated_at` or `version`; all twelve carry the full common set.

### 2.7. Monetary Precision, Rates, and Rounding

All monetary amounts in this API are integer cents. Fields carrying the `_cents` suffix — `partner_portfolio_exposure_cents`, `minimum_charge_cents`, `outstanding_receivable_cents`, `free_look_exposure_cents`, `program_profitability_cents`, `credit_limit_cents`, `outstanding_balance_cents`, `requested_credit_limit_cents`, `approved_credit_limit_cents`, `amount_cents`, `subsidy_at_application_cents`, `subsidy_at_risk_cents`, `net_subsidy_cents`, `gross_subsidy_cents`, `retailer_liability_cents`, `issuer_subsidy_cents`, `variance_cents`, `chargeback_amount_cents`, `program_exposure_delta_cents`, `principal_balance_cents`, `portfolio_book_value_cents`, `purchase_price_cents`, and `payment_amount_cents` — hold whole cents and are never fractional.

Rate and multiple fields are decimal numbers rather than cents: `revenue_share_rate` and `promo_subsidy_rate` each lie between 0.0 and 1.0 inclusive, `purchase_right_rate` is a price multiple over book value, and the promotional term rates in the internal rate table are four-decimal decimal fractions. These configuration values preserve their input precision and are not cents.

Every computed monetary result is expressed to exactly 2 decimal places using round-half-up. Where a calculation rounds a per-item figure and then sums, the per-item rounding happens first and the sum of the already-rounded figures is the result; the system never sums unrounded values and rounds once at the end.

### 2.8. Optimistic Concurrency Control

Two write operations in this API are guarded by optimistic concurrency control, and both use the same rejection contract. The first is the execution of a negotiated program agreement, which must carry `expected_agreement_version`; if that value does not match the agreement's current `version`, the execution is rejected with `ERR_STALE_VERSION` (HTTP 412). The second is the opening of a renewal round against a credit program, which must carry `expected_program_version`; if that value does not match the program's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). In both cases the expected-version field is a non-optional input — the request is not processed without it — and the check exists precisely so that a client which has not observed the entity's latest state cannot overwrite it.

No other write endpoint in this API accepts an expected-version field. A version mismatch on any other endpoint is not a defined rejection path.

### 2.9. Referential Integrity and Left-to-Right Path Validation

Every path-segment identifier and every body-referenced foreign key must resolve to an existing resource before an operation proceeds, and a failure to resolve is reported with `ERR_RESOURCE_NOT_FOUND` (HTTP 404). When a request path contains more than one identifier, the identifiers are validated strictly left to right and the request is abandoned at the first failure, so a request against a child of a nonexistent parent never evaluates the child at all. This same left-to-right discipline applies to body references: a payload that carries a `program_id` and an `agreement_id`, for instance, resolves the program before the agreement.

Cross-entity references declared in payloads are `partner_id` (agreement to retailer, program to retailer), `agreement_id` (program to agreement, settlement batch to agreement), `program_id` (account, application, promo plan, and wind-down transfer to program), `account_id` (transaction and benefit posting to account, promo plan to account, dispute to account), `transaction_id` (promo plan to transaction, dispute to transaction, benefit posting to transaction), and `supersedes_program_id` (a program to its own predecessor program, a self-referential chain).

### 2.10. State Enumeration Reference

State fields throughout the API take values from closed enumerations. `partner_status` on a retail partner is one of `ACTIVE`, `SUSPENDED`, or `OFFBOARDING`. `agreement_status` on a program agreement is one of `DRAFT`, `NEGOTIATION`, `ACTIVE`, `SUSPENDED`, or `TERMINATED`. `program_status` on a credit program is one of `ACTIVE`, `RENEWAL_NEGOTIATION`, `WINDING_DOWN`, or `CLOSED`. `account_status` on an account is one of `ACTIVE`, `DELINQUENT`, `CHARGED_OFF`, `PAID_OFF`, or `TRANSFERRED`. `application_status` on an application is one of `PENDING`, `APPROVED`, or `DECLINED`, and its `source_channel` is one of `IN_STORE`, `DIGITAL`, or `PRESCREENED`. `transaction_status` on a transaction is one of `POSTED` or `DISPUTED`, and its `transaction_channel` is one of `IN_STORE` or `DIGITAL`. `plan_status` on a promotional plan is one of `ACTIVE`, `SETTLED`, or `EXPIRED`. On a settlement batch, `settlement_method` is one of `FORWARD_LOOKING` or `AS_CHARGED`, `reconciliation_method` is one of `PROJECTED` or `AS_CHARGED`, and `batch_status` is one of `OPEN` or `SETTLED`. On a dispute case, `case_status` is one of `OPEN`, `UNDER_REVIEW`, `RESOLVED_FAVOR_CARDHOLDER`, `RESOLVED_FAVOR_MERCHANT`, or `CLOSED`, `dispute_reason` is one of `FRAUD`, `GOODS_NOT_RECEIVED`, `UNAUTHORIZED`, `DUPLICATE_CHARGE`, or `SERVICE_NOT_RENDERED`, and `resolution_outcome` is one of `CARDHOLDER` or `MERCHANT`. On a benefit posting, `posting_reason` is one of `PURCHASE_EARN`, `PROMO_BONUS`, or `DISPUTE_CLAWBACK`, and `posted_status` is one of `POSTED` or `REVERSED`. `balance_bucket` on a scheduled balance is one of `PRINCIPAL` or `PROMO_PRINCIPAL`. On a wind-down transfer, `buyer_role` and `accepted_by_role` are each one of `RETAILER` or `ISSUER`, and `transfer_status` is one of `PROPOSED`, `AGREEMENT_REACHED`, `COMPLETED`, or `WITHDRAWN`.

### 2.11. Validation Ordering

Every request passes through a fixed validation sequence, and the order determines which error a given malformed request reports. Authentication is evaluated first, so a request that both lacks headers and names a missing resource reports `ERR_UNAUTHENTICATED` (HTTP 401) rather than a not-found error. Authorization is evaluated second, so a request from a permitted-but-insufficient role reports `ERR_UNAUTHORIZED` (HTTP 403) before any resource is loaded. Existence resolution is third, reporting `ERR_RESOURCE_NOT_FOUND` (HTTP 404).

Only after those three system-wide gates do business rules run, and they run in the following order. For opening a dispute, the duplicate-dispute check (no other `DisputeCase` on the same transaction may be in `OPEN` or `UNDER_REVIEW`) is evaluated before the filing-window check. For posting a purchase, the promotional term membership check precedes the minimum-charge check, which precedes the credit-limit check. For finalizing a settlement batch, the in-scope dispute hold is evaluated before the batch's own state. State-admission checks — whether the target resource is in the from-state named in §3 — sit between existence resolution and the business rules. Within any single operation these business rules are evaluated in priority order, so the first rule that fails determines the reported `error_id`; a request that violates two business rules reports the higher-priority one.

## 3. Business Logic & Workflows

### 3.1. Onboarding a Retail Partner and Drafting Its Economic Agreement

A `ProgramAdmin` begins a partnership by creating a `RetailPartner` with a `retailer_name`, a `loyalty_program_code` naming the retailer's own rewards scheme, and an optional `loyalty_link_enabled` flag that defaults to true. The `loyalty_link_enabled` flag governs whether cardholder reward points earned on this program may post into the retailer's own loyalty balances at all; while it is true, accruals flow across, and while it is false, every attempt to post a loyalty benefit against an account on this retailer's program is rejected with `ERR_LOYALTY_LINK_DISABLED` (HTTP 422). A new partner starts in `ACTIVE`. The partner also carries a computed `partner_portfolio_exposure_cents` field, which is the sum of `free_look_exposure_cents` across every program whose `partner_id` points at this retailer; it is never supplied by a client and is recomputed whenever any of the retailer's programs changes its exposure.

The partner's `partner_status` moves along four paths. An explicit administrative suspension or reinstatement by a `ProgramAdmin` toggles between `ACTIVE` and `SUSPENDED`, and an administrative suspension is rejected unless the partner is currently `ACTIVE`, while a reinstatement is rejected unless it is currently `SUSPENDED`; a violation of either is reported as `ERR_INVALID_STATE` (HTTP 409). Separately, once every program governed by the partner's agreements has reached `WINDING_DOWN` or `CLOSED` — that is, once no program with this `partner_id` remains in either `ACTIVE` or `RENEWAL_NEGOTIATION` — the system suspends the partner on its own, without any client request. That bubble-up suspension is distinct from the administrative one and is reachable only after the portfolio has fully wound down. Finally, a `ProgramAdmin` may move a partner from `ACTIVE` to the terminal `OFFBOARDING` state, but only when every program with this `partner_id` is already `CLOSED`; the partner carries no cascade of its own into program status, because program cascading is driven by the agreement, not by the partner.

The economic terms of the partnership live in a `ProgramAgreement`, drafted against the partner via `partner_id`. The agreement captures `revenue_share_rate` — the share of credit-card net revenue the retailer retains — and `promo_subsidy_rate` — the share of deferred-interest promotional interest subsidy the retailer funds. Their sum may never exceed 1.0, and a draft or an execution that would breach that ceiling is rejected with `ERR_REVENUE_SHARE_INVALID` (HTTP 422). Beyond the two rates, the agreement sets a default `promo_term_months`, a `minimum_charge_cents` purchase floor that defaults to 29900, a `settlement_terms_days` invoice window that defaults to 30, a `dispute_grace_days` allowance that defaults to 0, a `renewal_notice_days` advance-notice requirement that defaults to 90, and a `purchase_right_rate` price multiple that defaults to 1.04.

A drafted agreement sits in `DRAFT` until a `ProgramAdmin` opens negotiation on it, which requires that the agreement currently be `DRAFT` and that `revenue_share_rate` plus `promo_subsidy_rate` be at most 1.0; the agreement then becomes `NEGOTIATION`. Executing a negotiated agreement into force requires the agreement to be in `NEGOTIATION` and requires the caller to supply the agreement's expected version; on success the agreement becomes `ACTIVE` and its `version` increments by one. Any credit program whose `supersedes_program_id` names this agreement's active program is thereby attached to the executed agreement as a renewal of that predecessor. A second route back to `ACTIVE` exists for a suspended agreement: reinstatement by a `ProgramAdmin`, again requiring the expected agreement version, with the same version increment.

An agreement does not remain `ACTIVE` indefinitely on its own. When the aggregate `free_look_exposure_cents` summed across this agreement's programs reaches 5,000,000,000 cents or more, the system suspends the agreement, transitioning it `ACTIVE` to `SUSPENDED` and incrementing its version by one; this is an automatic safeguard driven by the exposure rollup, not a client action. The safeguard is asymmetric on the way back: once the same aggregate has fallen strictly below 4,000,000,000 cents, the system restores the agreement from `SUSPENDED` to `ACTIVE`, again incrementing the version. Two further paths leave `ACTIVE`: a `ProgramAdmin` may terminate a `NEGOTIATION`-state agreement, which requires the expected agreement version and moves it to the terminal `TERMINATED` state with a version increment; and the system may return the agreement to `NEGOTIATION` by itself when no credit program under it remains in `ACTIVE` or `RENEWAL_NEGOTIATION`, or when the agreement is within `renewal_notice_days` of expiry. That bubble-up marks the end of the agreement's current term of operation and reopens the commercial conversation.

### 3.2. Issuing a Credit Program Under an Agreement

A credit program is the operational issuance vehicle for a partnership. A `ProgramAdmin` creates a `CreditProgram` with a `partner_id`, an `agreement_id`, and a `cycle_day`, and may optionally name a `supersedes_program_id` to record the predecessor program this one replaces in a renewal chain. A first-generation program carries no predecessor at all and leaves the field null. When a predecessor is named it must resolve to a program that exists and whose `program_status` is not `CLOSED`; a named predecessor that is missing or already closed is rejected with `ERR_SUPERSEDES_INVALID` (HTTP 422). New programs start in `ACTIVE`.

Three computed figures hang off the program and are maintained by the system rather than by clients. `outstanding_receivable_cents` is the sum of `outstanding_balance_cents` across every account on the program whose `account_status` is not `CHARGED_OFF`. `free_look_exposure_cents` is the sum of `subsidy_at_risk_cents` across every promotional plan on the program whose `plan_status` is `ACTIVE`. `program_profitability_cents` is the net program profit produced by the profitability calculation of §3.6 and is recomputed on every settlement, payment, and write-off. All three are denormalized rollups: they move as a consequence of operations on other resources, never through a direct client write.

A program's lifecycle has a distinctive shape because a renewal round is a negotiation that may succeed or fail. Opening a renewal round against an `ACTIVE` program moves it to `RENEWAL_NEGOTIATION`, requires the caller to supply the expected program version, and increments the version. From `RENEWAL_NEGOTIATION` there are two exits. If the round succeeds, a `ProgramAdmin` completes the renewal, which requires the program to still be in `RENEWAL_NEGOTIATION` and an expected version match; the renewal round closes, the newly executed successor program whose `supersedes_program_id` names this program becomes the governing program, and the original program returns to `ACTIVE` with its version incremented. If the round fails, the same renewal-opening capability is invoked again against the `RENEWAL_NEGOTIATION` program, this time supplying a `to_status` of `WINDING_DOWN`; this is the second arm of the same operation, distinguished by the requested target status. The cycle is therefore `ACTIVE` → `RENEWAL_NEGOTIATION` → either `ACTIVE` (renewed) or `WINDING_DOWN` (failed). Rolling into `WINDING_DOWN` triggers a cascade at its first hop: every account whose `program_id` names this program, whose `outstanding_balance_cents` is zero, and whose `account_status` is either `ACTIVE` or `DELINQUENT` is moved to `PAID_OFF`. Accounts still carrying principal are deliberately left untouched, because they must be either paid off or transferred before the program can close. The program's version increments.

Closure is the terminal step and it is deliberately hard to reach. Moving from `WINDING_DOWN` to the terminal `CLOSED` state requires that every wind-down transfer with this `program_id` has reached `COMPLETED`, and requires an expected-version match. It additionally requires that every account on the program have reached `TRANSFERRED` or `PAID_OFF`; a program closure attempted while any account is still neither transferred nor paid off is rejected with `ERR_ACCOUNT_NOT_SETTLED` (HTTP 422). On success the program's `free_look_exposure_cents` is forced to zero, the version increments, and the program becomes `CLOSED`.

### 3.3. Cardholder Acquisition: Applications, Prescreened Offers, and Instant Decisioning

Applications arrive through one of three `source_channel` values: `IN_STORE`, `DIGITAL`, or `PRESCREENED`. A submission names the target `program_id` and a `requested_credit_limit_cents`, and an application captured through the prescreened channel must additionally carry a `prescreen_reference` that resolves to a live offer; a `PRESCREENED` application that omits the reference or supplies one that does not resolve is rejected with `ERR_PRESCREEN_REQUIRED` (HTTP 422). Independently of channel, the requested line may not exceed the program's per-applicant ceiling of 5,000,000 cents; a request above that ceiling is rejected with `ERR_CREDIT_LIMIT_OUT_OF_BAND` (HTTP 422). A new application starts in `PENDING` with no decision yet stamped; once decisioned, the machine-readable reason is recorded on the application as its `decision_code`.

Instant decisioning is performed by an `Underwriter` and is the point at which the application splits into one of two terminal outcomes. Approval requires the application to still be `PENDING` and the `requested_credit_limit_cents` to be at most 1,500,000 cents. On approval the application becomes `APPROVED`, its `approved_credit_limit_cents` is set equal to the requested limit, and a brand-new `Account` is synthesized with `account_status` `ACTIVE`, the same `program_id` as the application, `credit_limit_cents` equal to the approved limit, and `outstanding_balance_cents` of zero. That synthesized account is discoverable only by listing accounts filtered to the application's program — it is not returned by the decision response and has no independent creation path. A request above the 1,500,000-cent threshold takes the other branch: the application becomes `DECLINED` and its `approved_credit_limit_cents` is set to null. Both branches are terminal, and the decision time is stamped on the application as `instant_decision_at`.

Accounts created through this path carry an opaque masked `cardholder_ref` printed on correspondence, and their `linked_loyalty_balance` begins at zero and grows only through benefit accruals.

### 3.4. Purchases, Promotional Qualification, and the Exposure Mesh

One last behavioral rule precedes the purchase posting itself: an account may be serviced only while its program's `program_status` is not `CLOSED`. Posting a purchase, submitting an application, and applying an account payment are all refused with `ERR_PROGRAM_CLOSED` (HTTP 422) once the account's or application's program has reached the terminal closed state.

Posting a purchase names an `account_id`, a `merchant_name`, an `amount_cents`, and a `transaction_channel` of `IN_STORE` or `DIGITAL`. Every request is also expected to carry the standard input fields of its endpoint, and a request whose body omits a required input or sends a value that does not match its declared type is refused with `ERR_INVALID_REQUEST` (HTTP 400). A new transaction starts in `POSTED`. Two business rules police the posting of a promotional purchase, in a fixed order. First, if the cardholder elected promotional financing, the requested term must be a member of the supported term set — the only permissible values are 6, 12, 18, and 24 months — and a term outside that set is rejected with `ERR_INVALID_PROMO_TERM` (HTTP 422). Second, the purchase amount must meet the governing agreement's `minimum_charge_cents`; a deferred-interest purchase below that floor is rejected with `ERR_PROMO_MINIMUM_CHARGE` (HTTP 422). The term check is evaluated before the minimum-charge check, so a purchase that is both below the floor and on an unsupported term reports the term error.

The credit check is applied to every purchase regardless of promotional election. The new `amount_cents` added to the account's current `outstanding_balance_cents` may not exceed the account's `credit_limit_cents`, and a purchase that would breach the line is rejected with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 422).

The `promo_requested` flag on the purchase is what elects deferred-interest financing; it defaults to false, and it is only when it is true that the purchase synthesizes a `PromoPlan`. A new plan starts in `ACTIVE`. The plan records the `program_id`, the `account_id`, and the `transaction_id` it is tied to, along with the agreed `promo_term_months`, the `promo_principal_cents` placed under the promotional balance, and a `qualifying_flag` capturing whether the purchase met the agreement minimum at qualification time. The term requested on the purchase is carried onto the plan as its `promo_term_months`, and the term must be a member of the same four-value rate table.

The plan's timing is derived, not supplied. `promo_start_at` is the logical-clock instant the plan qualified, and `promo_expires_at` is that instant advanced by the term length multiplied by 30 days. Two monetary figures are attached at creation and behave very differently afterwards. `subsidy_at_application_cents` is the projected subsidy struck once from the transaction-specific term rate; it is the quote the cardholder is shown and is never revised — not by a later rate change, not by a dispute, not by anything. `subsidy_at_risk_cents` is the live, partner-funded figure the retailer carries, and it moves. It is zero when `promo_start_at` has reached or passed `promo_expires_at`, zero when `promo_principal_cents` is below the agreement's `minimum_charge_cents`, and zero when `qualifying_flag` is false; otherwise it is the plan's principal multiplied by its term rate, multiplied by its term in months, divided by twelve, multiplied by the agreement's `promo_subsidy_rate`, rounded half-up to two decimal places. The rate table maps 6 months to 0.1299, 12 months to 0.1599, 18 months to 0.1899, and 24 months to 0.2199. A third figure, `net_subsidy_cents`, is the as-charged subsidy asset and is written only at settlement; it stays null for as long as `plan_status` is anything other than `SETTLED`.

Because `free_look_exposure_cents` is the sum of `subsidy_at_risk_cents` over `ACTIVE` plans, every event that changes a plan's risk figure ripples up to the program. Four such events are wired through the plan itself. When the logical clock reaches `promo_expires_at`, the plan moves from `ACTIVE` to `EXPIRED` and its `subsidy_at_risk_cents` is set to zero, which recomputes the program's exposure. A cardholder-service operator can also expire a plan explicitly, but only once the clock is at or after `promo_expires_at`; an attempt to expire a plan early is rejected with `ERR_PROMO_NOT_EXPIRED` (HTTP 422), and the explicit expiry likewise sets the risk figure to zero and recomputes exposure. An in-term payoff that is later reversed reopens an `EXPIRED` plan back to `ACTIVE` and recomputes its `subsidy_at_risk_cents` from its principal and the agreement subsidy rate, then recomputes the program exposure. And when a plan settles, it leaves the `ACTIVE` exposure set and the program's exposure is recomputed.

Two further events reach the plan's risk figure from outside it. Charging off an account transitions every promotional plan on that account, including its risk figure. And a dispute against a purchase transitions any plan on that purchase to a zero risk figure; the exposure recompute that follows is driven by the risk figure change, not by the case object. Both are described with their own workflows below. The account's own `outstanding_balance_cents` is a rollup of its principal balance slices rather than a directly writable field.

### 3.5. Statement Balances, Minimum Payments, Delinquency, and Charge-Off

Account principal is recorded as statement slices rather than as a single mutable number. A `ProgramAdmin` records a `ScheduledBalance` against an `account_id` with a `principal_balance_cents` amount and a `balance_bucket` of either `PRINCIPAL` or `PROMO_PRINCIPAL`, and the system stamps `recorded_at` with the logical-clock instant. Recording a slice recomputes the account's `outstanding_balance_cents` as the sum of its `principal_balance_cents` rows. The account's `outstanding_balance_cents` is therefore always the sum of its principal balance slices while the account is not charged off, and it is never accepted as a client-supplied value.

The minimum payment due on an account is computed, not stored, and it has a zero-balance boundary that is easy to get wrong. If the account's `outstanding_balance_cents` is exactly zero, the minimum due is exactly zero — never the floor. If the account is `DELINQUENT`, the minimum due is the entire `outstanding_balance_cents`. Otherwise the minimum is the greater of the absolute floor of 3,500 cents and two percent of `outstanding_balance_cents` rounded half-up to two decimal places. The two-percent figure is taken on the balance before any same-day payment is applied, and the floor applies only when the computed percentage figure is strictly less than it. A `CHARGED_OFF` account is a special case of the same computation: it carries no serviced minimum at all and returns zero even when a residual balance remains.

An account becomes delinquent on its own when its scheduled minimum payment stays unpaid past its statement due date; the transition from `ACTIVE` to `DELINQUENT` requires only that `outstanding_balance_cents` be greater than zero and is driven by the clock rather than by a client. A scheduled payment due date is set explicitly against an `account_id` with a `due_date`, but only a due date at or after the current logical clock is accepted; a due date in the past is rejected with `ERR_PAYMENT_DUE_IN_PAST` (HTTP 422).

Payments are applied by a `Cardholder` or a `ProgramAdmin` and carry a `payment_amount_cents`. The payment reduces the account's `principal_balance_cents` rows by the payment amount, floored at zero so that no slice goes negative, and then recomputes both the account's `outstanding_balance_cents` and the program's `program_profitability_cents`. A payment produces one of three outcomes depending on the account's state and size. A `DELINQUENT` account whose payment at least covers the overdue minimum due returns to `ACTIVE`. An `ACTIVE` account whose payment covers the whole outstanding balance moves to `PAID_OFF` and its `outstanding_balance_cents` is set to zero. A `DELINQUENT` account whose payment covers the whole outstanding balance likewise moves to `PAID_OFF` with a zero balance.

Charge-off is the terminal write-off path and it cascades in three hops. A `ProgramAdmin` may charge off an account only when it is `DELINQUENT` and its payment due date is 180 or more logical days in the past; a charge-off attempted before that window is met is rejected with `ERR_CHARGEOFF_WINDOW_NOT_MET` (HTTP 422). The first hop sets the account's `account_status` to `CHARGED_OFF`, which is the origin of the chain. The second hop is caused by the first: every promotional plan whose `account_id` names this account has its `plan_status` set to `EXPIRED` and its `subsidy_at_risk_cents` set to zero. The third hop is caused by the second: because those plans have left the `ACTIVE` exposure set, the owning program's `free_look_exposure_cents` is recomputed, and because the account is now `CHARGED_OFF` its `ScheduledBalance` rows stop summing into the program's `outstanding_receivable_cents`, so the program's `program_profitability_cents` is recomputed as well.

### 3.6. Program Economics: Delinquency Risk Scoring and Profitability

Every account carries a computed delinquency risk score, recomputed whenever its status or balance changes and surfaced through the program economics rollup. The score is the minimum of 1,000 and the sum of four contributions. A `DELINQUENT` account contributes 400 points; any other status contributes nothing. An account whose `outstanding_balance_cents` exceeds its `credit_limit_cents` contributes 300 points; the comparison is strictly greater, so an account sitting exactly at its limit contributes nothing extra, and the score at that exact boundary is a full 300 points lower than one cent above it. Utilization contributes the smaller of 200 points and the number of whole 500,000-cent units in the outstanding balance multiplied by 25, where the unit count is rounded down to a whole number before multiplication. Finally, days since the account's last payment contributes the smaller of 100 points and twice the number of days elapsed. The ceiling of 1,000 applies to each individual account's score.

The per-account scores are also rolled up to the program level for program economics reporting. The program rollup averages the per-account scores over accounts whose `account_status` is not `CHARGED_OFF` and rounds the average half-up; charged-off accounts are excluded from the denominator entirely, not merely treated as zero.

Program profitability is the top of the economic pyramid and is recomputed whenever a settlement finalizes, an account is charged off or paid off, or a program is wound down. It is the sum, over every settled settlement batch of the program, of the batch's net contribution, with the total acquisition cost of the program's accounts subtracted at the end. A batch's net contribution is the difference between its `gross_subsidy_cents` and its `retailer_liability_cents`, multiplied by a revenue-share multiplier, where the multiplier is one plus the product of `revenue_share_rate` and the smaller of two figures: the batch's average balance measured in whole millions of cents, and the cap multiple of 2.5. The batch contribution is rounded half-up to two decimal places before it is summed. The final subtraction is the account count of the program multiplied by a per-account acquisition cost of 4,200 cents, and the whole result is rounded half-up to two decimal places.

The profitability figure has a deliberate evaluation-order dependency. A batch's average balance is defined after that batch's own profitability pass — the pinned order is to settle the batch, then recompute balances, then score — and because the revenue-share multiplier is keyed on a balance figure that itself moves as batches settle, the order is fixed rather than incidental. The figure may be maintained either by recomputing every settled batch from scratch, which is the authoritative full recomputation, or by adding a single new batch's contribution to the prior total when only that batch has settled. The incremental path must land on exactly the same cents as the full recomputation; the reason each batch contribution is rounded before the outer sum is precisely so that no rounding drift accumulates between the two paths.

### 3.7. Promotional Settlement and the Partner Chargeback Reconciliation

Settlement is a two-stage process with a genuinely different number struck at each stage, and the difference between the two is the product's central economic fact. A `ProgramAdmin` opens a `SettlementBatch` against an `agreement_id` with a `period_start` instant that is inclusive and a `period_end` instant that is exclusive. At creation the batch is `OPEN` and the system computes `transaction_count`, the forward-looking `gross_subsidy_cents`, and the `variance_cents`. Later, a `ProgramAdmin` finalizes the batch, which strikes the as-charged figures and posts the partner-funded chargeback invoice; the batch becomes `SETTLED`, every in-scope promotional plan moves to `SETTLED` with its `net_subsidy_cents` stamped, the retailer and issuer shares are computed, and the program's `program_profitability_cents` is recomputed.

The batch carries two method selectors. `settlement_method` chooses which algorithm governs `subsidy_at_risk_cents` and defaults to `AS_CHARGED`. `reconciliation_method` chooses which algorithm governs `gross_subsidy_cents`, `net_subsidy_cents`, `variance_cents`, and `retailer_liability_cents`, and defaults to `PROJECTED`, which is the method most partner agreements write.

The input set for both variants is the same. It is every promotional plan whose `promo_start_at` falls within the half-open window running from `period_start` inclusive to `period_end` exclusive, and whose `transaction_id` resolves to a purchase that is `POSTED`. Plans whose purchase is `DISPUTED` at settle time are excluded from both variants entirely. The forward-looking variant additionally requires the plan to be `ACTIVE` at evaluation time; the as-charged variant does not, because it deliberately replays plans that may since have reached `EXPIRED`.

Both variants evaluate plans in a fixed order — ascending by `promo_start_at`, then by `transaction_id` as a tiebreaker — and both round each plan's figure to two decimal places half-up before summing, never after. The forward-looking pass, struck when the batch is opened, projects each plan's full-term interest as the principal multiplied by the plan's term rate, multiplied by its term in months, divided by twelve, rounded half-up; `gross_subsidy_cents` is the sum of those per-plan figures. This projection assumes the balance runs the full term and therefore over-states the exposure whenever a balance is paid in full inside the promotional window. The as-charged pass, struck only at finalize, replays each plan's actual accrued interest: the number of days accrued is the smaller of the days elapsed from `promo_start_at` to `period_end` and the plan's term in months multiplied by 30; the accrued interest is the principal multiplied by the plan's term rate, multiplied by that day count, divided by 365, rounded half-up; and `net_subsidy_cents` is the sum of those per-plan figures. This is the legally payable subsidy, and a balance paid in full early drives it toward zero while `gross_subsidy_cents` is untouched. `variance_cents` is `gross_subsidy_cents` minus `net_subsidy_cents`, signed, and it is the figure the program variance series is read from.

The chargeback reconciliation then splits the subsidy between the two parties under the reconciliation method. Under the projected view, the retailer's liability is the sum over selected plans of the plan's principal multiplied by its term rate, multiplied by its term in months, divided by twelve, multiplied by the agreement's `promo_subsidy_rate`; the issuer's subsidy is the same expression with the complement of the subsidy rate — one minus `promo_subsidy_rate` — in place of the rate itself; and each of the two totals is rounded half-up to two decimal places. Under the as-charged view, the retailer's liability is the sum over selected plans of each plan's accrued interest multiplied by `promo_subsidy_rate`, rounded half-up per plan, and the issuer's subsidy is the sum over selected plans of each plan's accrued interest multiplied by one minus `promo_subsidy_rate`, likewise rounded per plan. In the as-charged view the accrued interest is the per-plan figure from the as-charged subsidy pass, not the batch-cumulative `net_subsidy_cents` total. The projected view bills the retailer its share of the full projected subsidy and gives no credit for early payoffs inside the window, so the two variants differ by the rounded difference between gross and net subsidy multiplied by `promo_subsidy_rate`.

One invariant holds across both views and violating it is a defect: `retailer_liability_cents` plus `issuer_subsidy_cents` must equal that variant's total promotional subsidy to the cent.

Finalizing is blocked whenever any purchase in the batch's input set carries a dispute that is still `OPEN` or `UNDER_REVIEW`; the attempt is rejected with `ERR_SETTLEMENT_DISPUTE_HOLD` (HTTP 422), and this hold is evaluated before the batch's own state. The same rule governs an individual plan's move to `SETTLED`: no plan may settle while a dispute on its transaction remains `OPEN` or `UNDER_REVIEW`. A batch may only finalize from the `OPEN` state. On a successful finalize the agreement's `version` is incremented once for the settlement day, and the batch's `retailer_liability_cents` is posted as a partner-funded chargeback invoice payable by the retailer within the agreement's `settlement_terms_days`.

### 3.8. Disputes, Chargeback Discharge, and Loyalty Benefit Clawback

A dispute is opened by a `CardholderService` operator or by the cardholder acting on their own account, naming a `transaction_id`, an `account_id`, and a `dispute_reason` from `FRAUD`, `GOODS_NOT_RECEIVED`, `UNAUTHORIZED`, `DUPLICATE_CHARGE`, or `SERVICE_NOT_RENDERED`. The dispute may be raised against an account whose `account_status` is `CHARGED_OFF`. Two checks gate the opening, in order. No other `DisputeCase` on the same transaction may already be in `OPEN` or `UNDER_REVIEW`; a duplicate attempt is rejected with `ERR_DISPUTE_ALREADY_OPEN` (HTTP 409). Then the filing window applies: the disputed purchase must have posted no more than 60 logical days plus the agreement's `dispute_grace_days` before the current clock, and an out-of-window filing is rejected with `ERR_DISPUTE_PERIOD_EXPIRED` (HTTP 422). A new case starts in `OPEN` and is branded with the retailer's `retailer_name` in `servicing_brand_name`.

Opening the case is itself the trigger that moves the disputed purchase from `POSTED` to `DISPUTED`, and that move is the origin of a three-hop chain. The first hop is the transaction status change; the case object itself does not touch downstream rows. The second hop is caused by the first: because the purchase is now `DISPUTED`, every promotional plan with this `transaction_id` has its `subsidy_at_risk_cents` set to zero. The third hop is caused by the second: because a plan's risk figure changed, the owning program's `free_look_exposure_cents` is recomputed.

Resolution runs through review. A `CardholderService` operator moves an `OPEN` case to `UNDER_REVIEW`, and the instant the case leaves `UNDER_REVIEW` is stamped on it as `resolved_at`. From `UNDER_REVIEW` the operator resolves the case with a `resolution_outcome` of `CARDHOLDER` or `MERCHANT`, and the case lands in the matching terminal state. Resolution for the cardholder additionally requires that the disputed transaction posted no more than 60 logical days plus the agreement's `dispute_grace_days` before the current clock. On that branch the case records `chargeback_amount_cents` equal to the disputed purchase's `amount_cents`, and the case becomes `RESOLVED_FAVOR_CARDHOLDER`. Two consequences follow in sequence. First, a clawback benefit posting is raised against the purchase's original earn posting; second, applying that clawback decrements the account's `linked_loyalty_balance` by the original points amount and marks the original posting `REVERSED`. The disputed purchase's `transaction_status` is set back to `POSTED` — permanently chargeback-discharged — and its promotional plan keeps a `subsidy_at_risk_cents` of zero rather than being recomputed.

Resolution for the merchant takes a different path with a different downstream effect. There is no chargeback amount and no loyalty clawback. The disputed promotional plan's `subsidy_at_risk_cents` is recomputed from its principal and the agreement's `promo_subsidy_rate`, which is the first hop; the purchase's `transaction_status` returns to `POSTED`; and the owning program's `free_look_exposure_cents` is recomputed as the second hop. So the two resolution branches differ precisely in whether the exposure is restored or permanently discharged. A third exit exists for a case that never reaches review: an `OPEN` case may be withdrawn, which closes it in the terminal `CLOSED` state and returns the disputed purchase to `POSTED`. Each case records a `program_exposure_delta_cents` capturing the signed change it contributed to the program's exposure at resolution.

Loyalty benefits are posted independently of disputes through a `BenefitPosting` against an `account_id` and a `transaction_id`, with a `posting_reason` of `PURCHASE_EARN`, `PROMO_BONUS`, or `DISPUTE_CLAWBACK` and a signed `points_amount`; a clawback posting carries a negative value. A posting carries a `posts_to_retailer_loyalty` flag that defaults to true, and a computed `loyalty_program_code` field that copies the retailer's own `loyalty_program_code` at posting time and is null when `posts_to_retailer_loyalty` is false. A new posting is `POSTED` and stamps `posted_at` with the logical-clock instant. An accepted posting increments the account's `linked_loyalty_balance` by `points_amount` — which is exactly how a negative clawback decrements it.

A clawback arises from the cardholder-favored dispute branch just described. It requires that a benefit posting with reason `PURCHASE_EARN` exists on the disputed transaction. When it fires, it creates a new `BenefitPosting` with reason `DISPUTE_CLAWBACK` whose `points_amount` is negative one times the original posting's points, decrements the account's `linked_loyalty_balance` by the original points amount, and marks the original posting's `posted_status` as `REVERSED`. A posting so reversed is terminal.

### 3.9. Wind-Down, the Portfolio Purchase Right, and Partnership Termination

When a partnership ends, the portfolio does not simply evaporate — it is negotiated, priced, and transferred. The process begins when a `ProgramAdmin` proposes a `WindDownTransfer` against a `program_id`, naming the `buyer_role` as `RETAILER` or `ISSUER` and optionally supplying a `proposed_price_cents`. At proposal time the system copies two figures: `portfolio_book_value_cents`, which is the program's `outstanding_receivable_cents` at the instant of the proposal, and `purchase_right_rate`, which is the governing agreement's rate. The accepted `purchase_price_cents` is the supplied `proposed_price_cents` when one was given, and otherwise the book value multiplied by the rate, rounded half-up to the nearest cent. A transfer starts in `PROPOSED` with `accepted_by_role` null and no execution timestamp.

A proposed price is not free to be arbitrary. Any proposed price must be at least the program's book value multiplied by the agreement's `purchase_right_rate`; a lower proposal is rejected with `ERR_PURCHASE_PRICE_BELOW_FLOOR` (HTTP 422). The delegated purchase right held by a `CoBrandIssuer` is exercised through the acceptance step rather than through proposal, and a `CoBrandIssuer` may accept only as the `ISSUER` buyer.

Acceptance moves a `PROPOSED` transfer to `AGREEMENT_REACHED`, recording the accepting party's role in `accepted_by_role`. Execution then follows from `AGREEMENT_REACHED` and requires that every account whose `program_id` names this program is already in `PAID_OFF` or `TRANSFERRED` — a program still carrying live accounts cannot complete its transfer. On execution the first hop cascades every account on the program to `TRANSFERRED`, the program's `program_status` is set to `WINDING_DOWN`, and the program's version increments; the transfer becomes `COMPLETED` and stamps `transfer_executed_at`. Note the direction of that dependency: the transfer is the precondition for wind-down, and the program is then closed once the transfer has completed.

The negotiation is reversible up to a point. An accepted transfer may be withdrawn, which returns it from `AGREEMENT_REACHED` to `PROPOSED` and reopens the negotiation against the same program. A transfer that is still merely `PROPOSED` may also be withdrawn, which takes it to the terminal `WITHDRAWN` state instead. `COMPLETED` and `WITHDRAWN` are the two terminal outcomes.

Partner offboarding closes the loop, but only at the very end. A partner may be moved to the terminal `OFFBOARDING` state only once every program with this `partner_id` is `CLOSED`. And a program may reach `CLOSED` only from `WINDING_DOWN`, with every wind-down transfer on it `COMPLETED`, and with an expected-version match on the program itself. The sequence from partnership termination to final closure is therefore: negotiate and accept transfer terms, execute the transfer so the accounts cascade to `TRANSFERRED`, let the program sit in `WINDING_DOWN`, close the program, and only then offboard the partner.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource or add a distinct new resource to a collection return `201 Created`. Operations that modify an existing resource return `200 OK`. All paths below are mounted under the `/servicing` prefix. Roles are the exact strings defined in §2.1.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/servicing/_clock/set_current_utc` | Set the logical clock to a supplied instant | ProgramAdmin |
| POST | `/servicing/_clock/advance` | Advance the logical clock by whole days and run due scheduled effects | ProgramAdmin |
| POST | `/servicing/partners` | Onboard a retail partner | ProgramAdmin |
| GET | `/servicing/partners` | List retail partners | ProgramAdmin, CardholderService, Underwriter |
| GET | `/servicing/partners/{id}` | Read one retail partner | ProgramAdmin, CardholderService, Underwriter, RetailPartnerAnalyst |
| POST | `/servicing/partners/{id}/suspend` | Suspend a partner's participation | ProgramAdmin |
| POST | `/servicing/partners/{id}/reinstate` | Reinstate a suspended partner | ProgramAdmin |
| POST | `/servicing/partners/{id}/offboard` | Offboard a partner whose programs have all closed | ProgramAdmin |
| GET | `/servicing/partners/{id}/credit-programs` | List every program issued for a partner | ProgramAdmin, Underwriter |
| POST | `/servicing/agreements` | Draft a partner program agreement | ProgramAdmin |
| GET | `/servicing/agreements` | List agreements, optionally filtered by partner | ProgramAdmin, CardholderService, Underwriter |
| GET | `/servicing/agreements/{id}` | Read one agreement | ProgramAdmin, CardholderService, Underwriter, RetailPartnerAnalyst |
| POST | `/servicing/agreements/{id}/open-negotiation` | Open negotiation on a drafted agreement | ProgramAdmin |
| POST | `/servicing/agreements/{id}/execute` | Execute a negotiated agreement into force | ProgramAdmin |
| POST | `/servicing/agreements/{id}/reinstate` | Reinstate a suspended agreement | ProgramAdmin |
| POST | `/servicing/agreements/{id}/terminate` | Terminate a negotiated agreement | ProgramAdmin |
| POST | `/servicing/credit-programs` | Issue a credit program under a partner and agreement | ProgramAdmin |
| GET | `/servicing/credit-programs` | List credit programs with optional FK filters | ProgramAdmin, Underwriter, CardholderService |
| GET | `/servicing/credit-programs/{id}` | Read one credit program | ProgramAdmin, Underwriter, CardholderService, RetailPartnerAnalyst, CoBrandIssuer |
| POST | `/servicing/credit-programs/{id}/open-renewal` | Open a renewal round, or roll a failed renewal into wind-down | ProgramAdmin |
| POST | `/servicing/credit-programs/{id}/complete-renewal` | Close a successful renewal round | ProgramAdmin |
| POST | `/servicing/credit-programs/{id}/close` | Close a wound-down program once its transfer has completed | ProgramAdmin |
| GET | `/servicing/credit-programs/{id}/summary` | Read the computed program economics rollup | ProgramAdmin, Underwriter, RetailPartnerAnalyst |
| POST | `/servicing/applications` | Submit a credit application for instant decisioning | Applicant, ProgramAdmin |
| GET | `/servicing/applications` | List applications with an optional program filter | ProgramAdmin, Underwriter |
| GET | `/servicing/applications/{id}` | Read one application | ProgramAdmin, Underwriter, Applicant |
| POST | `/servicing/applications/{id}/decide` | Instant decisioning; synthesizes an account on approval | Underwriter |
| POST | `/servicing/transactions` | Post a purchase; promotional election synthesizes a plan | Cardholder, ProgramAdmin |
| GET | `/servicing/transactions` | List transactions with an optional account filter | ProgramAdmin, CardholderService, Cardholder |
| GET | `/servicing/transactions/{id}` | Read one transaction | ProgramAdmin, CardholderService, Cardholder |
| GET | `/servicing/accounts` | List accounts with an optional program filter | ProgramAdmin, CardholderService, Underwriter |
| GET | `/servicing/accounts/{id}` | Read one account | ProgramAdmin, CardholderService, Cardholder, Underwriter |
| POST | `/servicing/accounts/{id}/post-payment` | Apply a cardholder payment; clears delinquency or pays the account off | Cardholder, ProgramAdmin |
| POST | `/servicing/accounts/{id}/schedule-payment` | Schedule a statement payment due date | Cardholder, ProgramAdmin |
| POST | `/servicing/accounts/{id}/charge-off` | Charge off a delinquent account past the window | ProgramAdmin |
| POST | `/servicing/accounts/{id}/balances` | Record a statement-close principal-balance slice | ProgramAdmin |
| GET | `/servicing/accounts/{id}/balances` | List the principal-balance rows on an account | ProgramAdmin, CardholderService, Cardholder, Underwriter |
| GET | `/servicing/balances` | List principal-balance rows with an optional account filter | ProgramAdmin, CardholderService, Underwriter |
| GET | `/servicing/accounts/{id}/loyalty` | Read the cardholder-facing loyalty view for one account | Cardholder, CardholderService, ProgramAdmin |
| GET | `/servicing/promo-plans` | List promotional plans with optional FK filters | ProgramAdmin, CardholderService, Underwriter |
| GET | `/servicing/promo-plans/{id}` | Read one promotional plan | ProgramAdmin, CardholderService, Cardholder, Underwriter |
| POST | `/servicing/promo-plans/{id}/expire` | Expire a plan at or past its expiry instant | ProgramAdmin |
| POST | `/servicing/promo-plans/{id}/reopen` | Reopen an expired plan after a reversed payoff | CardholderService |
| POST | `/servicing/settlement-batches` | Open a settlement batch; projects the forward-looking subsidy | ProgramAdmin |
| GET | `/servicing/settlement-batches` | List settlement batches with an optional agreement filter | ProgramAdmin, Underwriter, RetailPartnerAnalyst |
| GET | `/servicing/settlement-batches/{id}` | Read one settlement batch | ProgramAdmin, Underwriter, RetailPartnerAnalyst |
| POST | `/servicing/settlement-batches/{id}/finalize` | Finalize a batch; strikes the as-charged subsidy and reconciles the chargeback | ProgramAdmin |
| POST | `/servicing/disputes` | Open a dispute against a transaction | CardholderService, Cardholder |
| GET | `/servicing/disputes` | List dispute cases with optional FK filters | ProgramAdmin, CardholderService |
| GET | `/servicing/disputes/{id}` | Read one dispute case | ProgramAdmin, CardholderService, Cardholder |
| POST | `/servicing/disputes/{id}/review` | Move an open dispute into review | CardholderService |
| POST | `/servicing/disputes/{id}/resolve` | Resolve a dispute for the cardholder or the merchant | CardholderService |
| POST | `/servicing/disputes/{id}/withdraw` | Withdraw an unresolved dispute | CardholderService |
| POST | `/servicing/benefit-postings` | Post a cardholder benefit accrual into the retailer's loyalty scheme | CardholderService, ProgramAdmin |
| GET | `/servicing/benefit-postings` | List benefit postings with optional FK filters | ProgramAdmin, CardholderService, Cardholder |
| GET | `/servicing/benefit-postings/{id}` | Read one benefit posting | ProgramAdmin, CardholderService, Cardholder |
| POST | `/servicing/transfer-agreements` | Propose a portfolio transfer on partnership wind-down | ProgramAdmin |
| GET | `/servicing/transfer-agreements` | List transfer agreements with an optional program filter | ProgramAdmin, Underwriter, CoBrandIssuer |
| GET | `/servicing/transfer-agreements/{id}` | Read one transfer agreement | ProgramAdmin, Underwriter, CoBrandIssuer |
| POST | `/servicing/transfer-agreements/{id}/accept` | Accept proposed transfer terms | ProgramAdmin, CoBrandIssuer |
| POST | `/servicing/transfer-agreements/{id}/execute` | Execute the accepted transfer | ProgramAdmin |
| POST | `/servicing/transfer-agreements/{id}/withdraw` | Withdraw a proposed or accepted transfer | ProgramAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_RESOURCE_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_PROMO_TERM` | 422 |
| `ERR_PROMO_MINIMUM_CHARGE` | 422 |
| `ERR_PRESCREEN_REQUIRED` | 422 |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 422 |
| `ERR_DISPUTE_ALREADY_OPEN` | 409 |
| `ERR_REVENUE_SHARE_INVALID` | 422 |
| `ERR_SUPERSEDES_INVALID` | 422 |
| `ERR_CREDIT_LIMIT_OUT_OF_BAND` | 422 |
| `ERR_DISPUTE_PERIOD_EXPIRED` | 422 |
| `ERR_SETTLEMENT_DISPUTE_HOLD` | 422 |
| `ERR_PROGRAM_CLOSED` | 422 |
| `ERR_PURCHASE_PRICE_BELOW_FLOOR` | 422 |
| `ERR_LOYALTY_LINK_DISABLED` | 422 |
| `ERR_ACCOUNT_NOT_SETTLED` | 422 |
| `ERR_PAYMENT_DUE_IN_PAST` | 422 |
| `ERR_PROMO_NOT_EXPIRED` | 422 |
| `ERR_CHARGEOFF_WINDOW_NOT_MET` | 422 |
| `ERR_INVALID_ADVANCE_DAYS` | 422 |