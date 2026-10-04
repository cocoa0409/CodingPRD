# Affordable Housing Equity Syndication API — Product Requirements Document

## 1. Introduction

Enterprise Community Partners administers a national affordable housing platform in which tax credit allocation awards, won by sponsoring developers, are monetised through syndicated investment funds. The equity that funds a project's construction and permanent gap is not raised by the developer directly; it is raised by an investment fund, subscribed to by institutional investors, and released in tranches that follow the physical progress of the buildings themselves. This document specifies the API that governs that entire chain — from the moment a sponsor is onboarded, through the underwriting of a project and its credit award, through fund formation and investor subscription, through construction and lease-up capital calls, through a fifteen-year compliance period with its watch list and enforcement machinery, and finally through the year-fifteen exit in which the investor's option is either exercised or permitted to lapse.

The commercial difficulty the system must encode is that credit and capital move at different speeds. A developer is promised a face value of tax credits; an investor pays a price per credit dollar against that promise; the physical delivery of credits lags the capital calls that were sized against them. The platform therefore maintains two parallel valuations of every fund — a priced valuation built from awarded credits and subscribed equity, and a realized valuation built from credits actually delivered and equity actually funded — and it adjusts the capital call schedule, the subscription funding status, and the developer's guarantee exposure as the gap between those two valuations opens and closes. Sponsors are additionally required to backstop the fund through operating deficit, recapture, and completion guarantees, so the platform continuously tests each sponsor's net worth and liquid assets against the guarantees it has written.

Because the money involved is public subsidy, the compliance surface is as load-bearing as the financial one. Every project is reviewed annually through its compliance period; each review is scored into a risk band that determines whether it is simply closed as compliant, placed on the watch list, escalated into distress, or recorded as a noncompliance finding. Distress on a project propagates upward: it changes the posture of the owning fund, which in turn gates further project commitments and capital calls, and it changes the standing of the sponsoring developer, which in turn gates whether that developer may commit a new project or exercise an exit option. The system therefore must be understood as a set of interlocking state machines — ten core entities and twelve state machines, with a deliberately cyclic shape so that cured distress can return a portfolio to health.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules that apply to every resource and every operation in the API.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory headers. `X-User-ID` identifies the acting principal and `X-User-Role` states the operational capacity in which that principal is acting. Exactly seven role names are recognised, and no others: `Developer`, `Investor`, `Underwriter`, `AssetManager`, `ComplianceOfficer`, `Anonymous`, and `PlatformAdmin`.

Two of these roles are entity-backed, meaning that the value supplied in `X-User-ID` is not merely a label but the identity of a persisted record. When `X-User-Role` is `Developer`, `X-User-ID` is the `id` of the acting `Developer`; ownership checks on any resource that references a `Developer` compare the resource's foreign-key field to `X-User-ID`. When `X-User-Role` is `Investor`, `X-User-ID` is the `id` of the acting `Investor`; ownership checks on any resource that references an `Investor` compare the resource's foreign-key field to `X-User-ID`. The remaining five roles — `Underwriter`, `AssetManager`, `ComplianceOfficer`, `Anonymous`, and `PlatformAdmin` — are opaque: the value in `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The server may record such an identifier, for example on a field written by a transition, but it never compares it to the `id` of any entity.

`Anonymous` is a sentinel, not a usable capacity. It exists solely to model a caller that presents no meaningful role. It is never permitted on any endpoint, and a request carrying it fails the authentication check as described below; this is the reachable path by which a client can observe the shape of an authentication failure. `PlatformAdmin` is the operational role: it onboards developers and investors, forms funds on a sponsor's behalf, records equity pay-ins on a client's behalf, and drives the logical clock. It is not a substitute for the business roles, and in particular the platform administration role cannot commit a project to its fund.

Role authority is enforced in two layers. The first layer is the endpoint's declared role list, given in §4: a request whose acting role does not appear in that list is rejected before any business logic runs. The second layer is referential scope, which is enforced for the two entity-backed roles and described in §2.5. A small number of operations are further restricted within a role by the action being requested. An `Investor` may settle a capital call only if it holds a subscription in the fund that finances the call's project. An `Investor` may reinstate or pay into a subscription only when it owns that subscription. A `ComplianceOfficer` alone may record an escalation or a noncompliance outcome, and an `AssetManager` alone may draw against a guarantee. A `Developer` may never underwrite, never commit, and never draw against its own guarantees; it may read only its own developer record and its own projects, together with the capital calls, allocations, guarantees, reviews, and exit events belonging to those projects.

The authentication failure is reported as `ERR_UNAUTHENTICATED` with HTTP status 401. It is raised when `X-User-Role` is absent, when it names something that is not one of the seven declared roles, or when it names an entity-backed role while `X-User-ID` is absent. A request that is authenticated but whose acting role is not listed on the target endpoint is rejected with `ERR_FORBIDDEN` and HTTP status 403. A request that is authenticated and correctly roled but that reaches outside the actor's own entity scope is rejected with `ERR_FORBIDDEN_SCOPE`, also HTTP status 403.

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

### 2.3. Pagination and Listing

List endpoints accept `limit` and `offset` as query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, and it may not be smaller than 1 nor larger than 100. The `offset` parameter states how many items to skip; it defaults to 0. List responses carry four pagination fields inside the `meta` object: `limit`, `offset`, `total_count`, and `has_more`.

Unless a caller requests otherwise, list endpoints return resources in ascending order of their creation timestamp. This ordering is a system-wide default and applies to every collection in the API.

### 2.4. The Logical Clock

The system does not observe wall-clock time. Every temporal decision — fund close and termination, capital call issue eligibility, compliance period closure, right-of-first-refusal expiry, and the placed-in-service deadline — is evaluated against a single server-held logical clock. At server startup the logical clock reads exactly `2026-09-01T00:00:00Z`, and it continues to read that value until an operator advances it. It never tracks real time.

Advancing the clock is an administrative capability restricted to the `PlatformAdmin` role. The caller supplies the new instant as `current_utc`, and the response echoes that value back. No other operation moves the logical clock, and no resource stores a wall-clock timestamp: every timestamp the API returns is either client-supplied or derived from the logical clock.

### 2.5. Nested Resources and Referential Scope

Several resources are addressed within the scope of a parent: allocations, capital calls, guarantees, portfolio reviews, and exit events all belong to a project. When a path carries more than one identifier, the identifiers are resolved strictly left to right, and the request fails at the first identifier that does not resolve. The identifier names are `developer_id`, `investor_id`, `fund_id`, `project_id`, `allocation_id`, `call_id`, `guarantee_id`, `subscription_id`, `review_id`, and `exit_event_id`. A path is validated segment by segment, and identifiers that appear only in the request body are resolved after every path identifier has resolved.

The error raised by a failed resolution depends on the segment that failed. A missing developer is reported as `ERR_DEVELOPER_NOT_FOUND`, a missing fund as `ERR_FUND_NOT_FOUND`, a missing project as `ERR_PROJECT_NOT_FOUND`, a missing allocation as `ERR_ALLOCATION_NOT_FOUND`, a missing capital call as `ERR_CAPITAL_CALL_NOT_FOUND`, a missing guarantee as `ERR_GUARANTEE_NOT_FOUND`, a missing subscription as `ERR_SUBSCRIPTION_NOT_FOUND`, a missing review as `ERR_REVIEW_NOT_FOUND`, and a missing exit event as `ERR_EXIT_EVENT_NOT_FOUND`. All of these carry HTTP status 404. An allocation that exists but belongs to a different project is likewise reported as `ERR_ALLOCATION_NOT_FOUND`, because an allocation is only addressable within its own project.

Referential scope is a separate check from role authority. An entity-backed actor may act only on resources that its own entity owns: a `Developer` may act only on its own projects, and an `Investor` may act only on its own subscriptions. Every nested child must carry the project identifier of the parent named in the path, and the settling capital call's project must be financed by the subscription's fund. A violation of any of these scope rules is rejected with `ERR_FORBIDDEN_SCOPE` and HTTP status 403. The two collection endpoints that would otherwise fail every scoped request — the project listing and the subscription listing — do not reject; they filter their results down to the rows the acting entity owns.

### 2.6. Common Resource Properties

All ten primary resources in this API — `Developer`, `Investor`, `SyndicationFund`, `FundSubscription`, `Project`, `Allocation`, `CapitalCall`, `Guarantee`, `PortfolioReview`, and `ExitEvent` — carry the same four system-managed properties:

- `id` (string): a unique, server-minted identifier for the resource, formatted as a UUID. The identifier carries no type prefix and no semantic content.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, recording when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, recording when the resource was last modified.
- `version` (integer): a system-managed counter that increments by one on every modification to the resource.

The `version` property is not merely an audit convenience; it is the substrate of the optimistic concurrency mechanism described in §2.8. Every derived-field recomputation that changes a resource counts as a modification: writing a derived field refreshes `updated_at` and increments `version` on the resource whose field changed, and when a single operation cascades to several resources, each affected resource is independently refreshed and incremented. No resource in this API omits `updated_at` or `version`.

### 2.7. Monetary, Ratio, and Rounding Conventions

Money in this system is integer cents. Every field whose name ends in `_cents` holds a whole number of cents, and no monetary field is ever returned as a floating-point dollar value or as a string. Monetary arithmetic is exact integer arithmetic between rounding points; there is no accumulated floating-point drift.

Where a calculation produces a fractional cent, the result is rounded using the round-half-up rule: a value exactly at the midpoint rounds away from zero, so a half-cent becomes the next whole cent upward. The precision and rounding of each computed quantity are as follows.

- Equity figures, capital call amounts, guarantee amounts, allocations of credit dollars, and other monetary outputs are whole cents, each intermediate rounded half-up before the next step consumes it.
- The debt service coverage ratio `dscr` is stored with 4 decimal places.
- The credit delivery ratio `delivery_ratio` is stored with 6 decimal places.
- Yield figures — `priced_yield_pct` and `realized_yield_pct` — are decimal fractions with 6 decimal places, rounded half-up.
- The watch-list `risk_score` is an integer, rounded half-up at each weighted term before the terms are summed.
- Enum outputs such as `status` and `posture` involve no rounding at all.

Where a calculation is specified as a sequence of steps, the rounding points are pinned: a step rounds its own output before the next step reads it, and steps are never collapsed so that a single rounding is applied to a combined expression. Different rounding orders produce different cent totals, and only the pinned order is correct.

### 2.8. Optimistic Concurrency and Revision Bands

Three write operations accept a client-supplied expectation of the version they are writing against, and all three enforce it.

Creating a subscription against a fund is a write that must carry `expected_fund_version`, holding the client's last observed `version` of the target `SyndicationFund`. If the fund's version has advanced since the client last read it, the create is rejected with `ERR_STALE_VERSION` and HTTP status 412. The rule is framed entirely in stale-revision terms: a client may not create a subscription, and thereby pin an `executed_price_per_credit_dollar`, against a fund whose state it has not observed.

Editing a project's underwriting inputs must carry `expected_project_version`, holding the client's last observed `version` of the target `Project`. A mismatch is rejected with `ERR_STALE_VERSION` and HTTP status 412. Repricing a fund likewise carries `expected_fund_version` and applies the same rejection.

Scheduling a new capital call against a project must also carry `expected_project_version`. A mismatch is rejected with `ERR_STALE_VERSION` and HTTP status 412.

These three endpoints are the complete set of writes that consume a version expectation. The rejection code is identical across them — `ERR_STALE_VERSION`, HTTP 412 — and there are no endpoint-specific variants. Endpoints that are not named here do not accept a version field, and an unexpected version field on such an endpoint is not part of the contract.

### 2.9. Validation Ordering and Rejection Precedence

When more than one rule could reject a request, the rejection the caller observes is determined by a fixed priority order. The order is strict, and the first failing rule wins; a later rule is never permitted to mask an earlier one. The ten priority tiers, from first to last, are as follows.

1. Authentication. `X-User-Role` must be present and must name one of the seven declared roles, the sentinel `Anonymous` is never accepted, and an entity-backed role requires `X-User-ID`. Failure is `ERR_UNAUTHENTICATED`, HTTP 401. This tier applies to every endpoint.
2. Role authority. The acting role must appear in the endpoint's declared role list. Failure is `ERR_FORBIDDEN`, HTTP 403. This tier applies to every endpoint. Entity ownership is deliberately not tested at this tier.
3. Request shape. Every required input must be present, every enum input must be a declared member, every numeric input must be non-negative, `coverage_start_date` must be strictly before `coverage_end_date`, `exercise_deadline` must not be before `rofr_notice_date`, and `scheduled_date` must not be after `due_date`. Failure is `ERR_INVALID_REQUEST`, HTTP 400. This tier applies to every mutating endpoint.
4. Existence. Every identifier, whether in the path or the body, must resolve, with the segment-specific 404 code described in §2.5. This tier applies to every endpoint.
5. Referential scope. An entity-backed actor must own the target, a nested child must carry the path parent's project identifier, and the settling capital call's project must be financed by the subscription's fund. Failure is `ERR_FORBIDDEN_SCOPE`, HTTP 403.
6. Target state. The target resource must be in a state that permits the requested operation; the state codes are `ERR_PROJECT_NOT_COMMITTABLE`, `ERR_INVALID_ALLOCATION_STATE`, `ERR_CALL_NOT_ISSUED`, `ERR_REVIEW_NOT_ESCALATED`, `ERR_EXIT_EVENT_NOT_PENDING`, and `ERR_SUBSCRIPTION_TERMINAL`, all HTTP 409.
7. Sponsor and guarantee safeguards. The acting `Developer` must be `ELIGIBLE` for a project commitment (`ERR_DEVELOPER_WATCH_BLOCKED`), must be `ELIGIBLE` with no `DISTRESSED` project for an exit exercise (`ERR_DEVELOPER_NOT_ELIGIBLE_FOR_EXIT`), and a new guarantee must not push `guarantee_exposure_cents` above `net_worth_cents` (`ERR_GUARANTEE_EXPOSURE_EXCEEDED`). All three are HTTP 422.
8. Revision bands and conflicts. A stale version expectation is `ERR_STALE_VERSION`, HTTP 412. Conflict failures are `ERR_DUPLICATE_CALL_MILESTONE`, `ERR_CALL_BUFFER_TOO_SHORT`, `ERR_DUPLICATE_SUBSCRIPTION`, `ERR_DUPLICATE_ALLOCATION_PERIOD`, `ERR_ROFR_WINDOW_OVERLAP`, `ERR_COVERAGE_WINDOW_OVERLAP`, and `ERR_FUND_POSTURE_FROZEN`, all HTTP 409; `ERR_INVESTOR_SUSPENDED` is HTTP 403; `ERR_FUND_NOT_FORMING` is HTTP 409.
9. Equity buckets. A subscription may not exceed the fund's remaining raise nor the investor's remaining capacity against its tier cap (`ERR_SUBSCRIPTION_EXCEEDS_CAPACITY`); a pay-in may not push `paid_in_cents` above `committed_cents` (`ERR_OVERPAYMENT`); a distribution may not exceed the allocation's `delivered_credit_dollars_cents` (`ERR_DISTRIBUTION_EXCEEDS_DELIVERED`); a guarantee draw is clamped rather than rejected. The three rejection codes here are HTTP 422.
10. Temporal windows. Subscription creation requires the logical clock to fall within the fund's subscription window (`ERR_SUBSCRIPTION_WINDOW_CLOSED`); a call may issue only at or after its `scheduled_date` (`ERR_CALL_NOT_DUE`); a noncompliance finding requires the review period to have closed (`ERR_REVIEW_PERIOD_OPEN`); an exit exercise requires the right-of-first-refusal window to be open (`ERR_ROFR_WINDOW_EXPIRED`); and the placed-in-service milestone requires the deadline not to have passed (`ERR_PLACED_IN_SERVICE_DEADLINE_PASSED`). All five are HTTP 422.

The practical consequence of this order is that a request which is both unauthorised and malformed reports the authentication failure, a request which names a nonexistent identifier and also violates a business rule reports the not-found failure, and a request which is stale and also violates a bucket rule reports the stale-version failure.

### 2.10. Derived Status and Portfolio Propagation

The platform's two most consequential values are never set directly by a client: a fund's `posture` and a developer's `status` are both derived, and both are recomputed whenever any input to their derivation changes. Derivation is always whole: a recomputation discards the previous value and re-derives from current rows, so the derived value can move in either direction as conditions appear and clear.

Distress is the medium through which project-level problems travel upward. A project entering `DISTRESSED` changes the posture of its owning fund and the status of its owning developer. Distress also travels downward in one specific and deliberate direction: when a developer is suspended, every one of its projects is pushed into `DISTRESSED`. Distress does not, however, release guarantees — a suspension leaves every `ACTIVE` or `DRAWN` guarantee exactly where it was, and guarantee capacity is only released when the underlying project reaches `EXITED`.

Every derived recomputation is a mutation. When a fund's posture changes, the fund's `updated_at` is refreshed and its `version` is incremented. When a developer's status changes, the developer's `updated_at` is refreshed and its `version` is incremented. The same is true of every cascade described in §3: a single client action that touches a project, its fund, and its developer produces three independent version increments, one per affected row.

## 3. Business Logic & Workflows

### 3.1. Sponsor Onboarding and Eligibility

A `PlatformAdmin` onboards a sponsor by supplying `name`, `developer_type`, `sponsor_experience_months`, `projects_completed`, `net_worth_cents`, and `liquid_assets_cents`. The `developer_type` must be `NONPROFIT`, `FOR_PROFIT`, or `JOINT_VENTURE`. On onboarding, `guarantee_exposure_cents` and `active_project_count` both start at zero, and `status` is derived rather than accepted.

That derivation is the sponsor-eligibility test, and it combines a balance-sheet test with an experience test. The developer's exposure is the sum of `guaranteed_amount_cents` across all of its guarantees that are not `RELEASED`. The coverage ratio is the developer's `net_worth_cents` divided by that exposure, except that the exposure used in the division is never allowed below one cent. A developer is deeply experienced when its `sponsor_experience_months` is at least 120 and its `projects_completed` is at least 5. A developer passes on coverage when the coverage ratio is at least 2.0, or when it is deeply experienced. The remaining inputs are two counts: the number of `PortfolioReview` rows in status `ESCALATED` across the developer's non-`EXITED` projects, and the number of the developer's projects in status `DISTRESSED`.

The derived `status` is then read off in strict order. A developer is `SUSPENDED` when the escalated count is at least 2 and the distressed count is at least 1 — both conditions, not either. A developer is `WATCH` when it fails the coverage test, or has at least one distressed project, or has at least one escalated review. Otherwise it is `ELIGIBLE`. Two boundaries are easy to get wrong and both are deliberate. Because the coverage test uses "at least 2.0", a developer whose exposure sits exactly at twice its net worth is still `ELIGIBLE` unless some other condition fails. And because suspension requires both conditions, a developer with two escalated reviews but no distressed project is only `WATCH`, never `SUSPENDED`.

The developer `status` field moves through four transitions, all of which are triggered by the system rather than by a client request, and all of which re-derive the value from current rows.

A developer moves from `ELIGIBLE` to `WATCH` when its coverage ratio falls below 2.0, or when at least one of its projects is `DISTRESSED`, or when at least one review of one of its non-`EXITED` projects is `ESCALATED`. This transition fires as a consequence of opening or resolving compliance reviews. Its side effects are two: committing a project is now blocked for every project belonging to that developer, and the `posture` of every `SyndicationFund` that holds one of the developer's projects is recomputed.

A developer moves from `WATCH` back to `ELIGIBLE` when the coverage ratio has recovered to at least 2.0, no project of the developer is `DISTRESSED`, and no review of a non-`EXITED` project is `ESCALATED`. All three conditions must hold. The only side effect is a recomputation of `posture` for each fund holding one of the developer's projects.

A developer moves from either `ELIGIBLE` or `WATCH` to `SUSPENDED` when at least two reviews across its non-`EXITED` projects are `ESCALATED` and at least one of its projects is `DISTRESSED`. Suspension is the most severe cascade in the system. Every project belonging to the developer is moved into `DISTRESSED`. Every affected fund's `posture` becomes `FROZEN`. Guarantees are deliberately left alone: a suspension does not release any `ACTIVE` or `DRAWN` guarantee, and guarantee exposure therefore remains on the developer's books through the suspension.

A developer moves from `SUSPENDED` back to `WATCH` when no review of any of its non-`EXITED` projects remains `ESCALATED`. Guarantee exposure is unchanged by this transition; the developer lands in `WATCH` and must satisfy the coverage re-derivation separately before it can return to `ELIGIBLE`.

### 3.2. Investor Onboarding and Subscription Capacity

Institutional investors are onboarded by a `PlatformAdmin` with `name`, `investor_type`, `committed_capacity_cents`, and `risk_tier`. The `investor_type` must be `BANK`, `INSURANCE`, `CORPORATE`, `FOUNDATION`, or `PENSION`, and the `risk_tier` must be `TIER_1`, `TIER_2`, or `TIER_3`. An investor starts at `ACTIVE` with `outstanding_commitment_cents` and `funded_cents` both at zero.

Two derived totals govern an investor's remaining room. The `outstanding_commitment_cents` is the sum of `committed_cents` across the investor's subscriptions that are not `DEFAULTED`, so a defaulted subscription freezes its commitment out of the total. The `funded_cents` is the sum of `paid_in_cents` across all of the investor's subscriptions, with no exclusions.

An investor's `status` is a function of its subscriptions. It moves from `ACTIVE` to `SUSPENDED` as soon as at least one of its subscriptions has reached `DEFAULTED`. The consequences are threefold: the investor is removed from the ordering used when credit distribution payables are allocated across a fund, its already-defaulted subscription keeps whatever `shortfall_cents` it accumulated, and no further subscription may be created for it. The reverse edge exists too — an investor returns from `SUSPENDED` to `ACTIVE` once none of its subscriptions remains `DEFAULTED`, which happens when a defaulted subscription is reinstated.

Subscription creation is bounded by a waterfall that splits a fund's remaining raise across risk tiers. The remaining raise is the fund's `target_equity_cents` minus its `subscribed_equity_cents` as of the moment before the request. The tiers are filled in strict priority order, each spilling its overflow into the next. The first bucket is reserved for `TIER_1` investors and is capped at 800000000 cents of the remaining raise, with each individual `TIER_1` investor additionally capped at 300000000 cents for any single fund. The second bucket is reserved for `TIER_2` investors and is capped at 600000000 cents of the remaining raise, with each individual `TIER_2` investor additionally capped at 400000000 cents. The third bucket absorbs everything that remains and is uncapped, so a `TIER_3` investor can take the whole remainder while a `TIER_1` investor is held to 300000000 cents even with unlimited personal headroom.

The amount an individual investor may actually commit is the lesser of two ceilings. One is the investor's own headroom, computed as the investor's `committed_capacity_cents` minus its `outstanding_commitment_cents`, further limited by the tier cap that applies to its `risk_tier`. The other is the fund's remaining raise. The maximum subscription is the smaller of the two. If the requested `committed_cents` exceeds that maximum the request is rejected outright with `ERR_SUBSCRIPTION_EXCEEDS_CAPACITY`; the endpoint never partially accepts a smaller amount.

A subscription is created with `investor_id`, `committed_cents`, `payin_schedule`, and `expected_fund_version`. The `payin_schedule` is an ordered array whose elements each pair a `milestone` with a `share_pct`, and the `share_pct` values across the array must sum to 1.0. At creation the subscription's `executed_price_per_credit_dollar` is pinned to the fund's current `price_per_credit_dollar`, and its `status` begins at `PLEDGED`. The fund's `version` is incremented by the write, and the fund's `subscribed_equity_cents`, `priced_yield_pct`, and `subscription_count` are recomputed.

Subscriptions may be opened only while the fund is `FORMING` or `CLOSING`; a subscription attempted against a fund in any other status is rejected with `ERR_FUND_NOT_FORMING`, as is one attempted against a fund that has been terminated before closing or has wound down. The subscription must also fall inside the fund's raise window: the logical clock must be at or after `subscription_open_date` and at or before `subscription_close_date`, and a request outside that window is rejected with `ERR_SUBSCRIPTION_WINDOW_CLOSED`. Only one non-`DEFAULTED` subscription may exist for any given fund-and-investor pair; a second attempt is rejected with `ERR_DUPLICATE_SUBSCRIPTION`. A subscription attempted on behalf of an investor whose `status` is `SUSPENDED` is rejected with `ERR_INVESTOR_SUSPENDED`.

Equity pay-ins are recorded against a subscription by its owning `Investor`, in an amount of `amount_cents`. A pay-in advances the subscription's `status` along `PLEDGED → SUBSCRIBED → PARTIALLY_FUNDED → FULLY_FUNDED`. The first pay-in against a pledge moves it to `SUBSCRIBED`; a pay-in that leaves `paid_in_cents` above zero but below `committed_cents` lands the subscription in `PARTIALLY_FUNDED`; a pay-in that brings `paid_in_cents` to exactly `committed_cents` lands it in `FULLY_FUNDED`. A pay-in that would push `paid_in_cents` above `committed_cents` is rejected with `ERR_OVERPAYMENT`. Every accepted pay-in increases the fund's `funded_equity_cents` and the investor's `funded_cents` by the payment amount, recomputes the subscription's `unfunded_commitment_cents` as the commitment less the amount paid in but never below zero, and recomputes the fund's `realized_yield_pct`. Pay-ins are accepted only once the fund has reached `CLOSING` or `CLOSED`; against a fund that has not closed its raise the request fails with `ERR_FUND_NOT_FORMING`, as does a pay-in against a fund that has wound down. A pay-in against a subscription that has already reached `DEFAULTED` is rejected with `ERR_SUBSCRIPTION_TERMINAL`, because default is terminal.

### 3.3. Fund Formation, Pricing, and the Two Valuations

A fund is formed by an `Underwriter` or a `PlatformAdmin`, who supplies `fund_name`, `target_equity_cents`, `price_per_credit_dollar`, `target_yield_pct`, an optional `close_threshold_pct`, and the two dates `subscription_open_date` and `subscription_close_date`. The `close_threshold_pct` expresses the fraction of the target equity that must be subscribed before the fund may close, and when it is omitted it defaults to 0.85. A newly formed fund begins at `FORMING`, with `posture` `OPEN` and with `funded_equity_cents`, `subscribed_equity_cents`, and `subscription_count` all at zero.

The fund's `status` machine has six values and a strict threshold. A fund moves from `FORMING` to `CLOSING` as soon as its `subscribed_equity_cents` reaches the close threshold, which is the fund's `target_equity_cents` multiplied by its `close_threshold_pct` and rounded half-up to a whole cent. The move is reversible: if a subscription leaves the not-defaulted set and `subscribed_equity_cents` drops below that same rounded threshold, the fund returns from `CLOSING` to `FORMING`, and any capital call rows already issued are left untouched by the reversal.

The fund closes or dies when the logical clock crosses `subscription_close_date`. If the threshold has been met at that point, the fund moves from `CLOSING` to `CLOSED`, and from that moment no further subscription may be created against it — the attempt is rejected with `ERR_FUND_NOT_FORMING`. If the threshold has not been met, the fund moves from either `FORMING` or `CLOSING` to `TERMINATED`, and termination is severe: every subscription of that fund becomes `DEFAULTED`, every investor holding one of those subscriptions becomes `SUSPENDED`, every project of the fund is left in `UNDERWRITING`, and no new capital call may be created for the fund's projects.

Once a fund has closed, it moves to `DEPLOYING` the moment its first allocation is placed into `COMMITTED` by a project commitment. It moves from `DEPLOYING` to `WOUND_DOWN` once every one of its projects has reached `EXITED`; from that point the fund stops accepting pay-ins, and a pay-in attempt against it is rejected with `ERR_FUND_NOT_FORMING`. `TERMINATED` is the only terminal value of this machine.

Pricing is a read-side concern in one sense and a write-side trigger in another. Reading a fund recomputes and exposes `awarded_credits_total_cents`, `delivered_credits_total_cents`, `priced_value_cents`, `realized_value_cents`, `priced_yield_pct`, `realized_yield_pct`, and the portfolio summary counters. Repricing a fund is done by an `Underwriter`, who may change `price_per_credit_dollar`, `target_yield_pct`, and `close_threshold_pct`, and who must also supply `expected_fund_version`. Repricing recomputes both yields. Subscriptions already created keep the `executed_price_per_credit_dollar` they pinned at creation; a reprice never reaches backwards into them.

The fund carries two parallel valuations of the same portfolio, and the difference between them is the system's central economic signal. The priced valuation starts from awarded credits. The `awarded_credits_total_cents` is the sum of `awarded_credit_dollars_cents` across the `COMMITTED` and `CLOSED` allocations of the fund's non-`EXITED` projects. The `priced_value_cents` is not computed by summing credit dollars and then multiplying by the price; instead, each allocation's `awarded_credit_dollars_cents` is multiplied by the fund's `price_per_credit_dollar` and rounded half-up to a whole cent individually, and only those per-allocation rounded values are summed. Rounding the aggregate once produces a different cent total and that variant is explicitly not used. The `priced_yield_pct` is the `awarded_credits_total_cents` minus the `subscribed_equity_cents`, divided by the `subscribed_equity_cents`, expressed to 6 decimal places; when `subscribed_equity_cents` is zero the yield is zero.

The realized valuation mirrors that construction against what was actually delivered and actually funded. The `delivered_credits_total_cents` is the sum of `delivered_credit_dollars_cents` across the same `COMMITTED` and `CLOSED` allocations of non-`EXITED` projects. The `realized_value_cents` is the sum of each allocation's `delivered_credit_dollars_cents` multiplied by the fund price and rounded half-up per allocation, again rounded before summing. The `realized_yield_pct` is the `delivered_credits_total_cents` minus the `funded_equity_cents`, divided by the `funded_equity_cents`, to 6 decimal places, and zero when the funded equity is zero. A fund that under-delivers credits therefore reports a realized yield far below its priced yield even when the price per credit dollar has not moved at all.

The portfolio summary exposes the fund's exposure in one view: `project_count` counts the fund's projects that are not `EXITED`; `distressed_count` counts those in `DISTRESSED`; `total_awarded_credit_dollars_cents` and `total_delivered_credit_dollars_cents` sum the corresponding fields across the fund's `COMMITTED` and `CLOSED` allocations; `total_committed_equity_cents` sums `underwritten_equity_cents` across the fund's non-`EXITED` projects; and `weighted_average_risk_score` is the sum of the `risk_score` of the latest review of every non-`EXITED` project, divided by the project count or by one if there are no projects, rounded half-up to an integer.

Distributing a payable across a fund's investors is a pinned-order waterfall rather than a proportional split. When a delivery payable is distributed, the amount distributable is the lesser of the allocation's `delivered_credit_dollars_cents` and its `awarded_credit_dollars_cents`. The subscriptions that participate are the fund's subscriptions whose status is not `DEFAULTED`, and they are ordered by three keys applied in sequence: first by the owning investor's `risk_tier` ascending, treating `TIER_1` as lowest and `TIER_3` as highest; then by the investor's `created_at` ascending; and finally by the subscription's own `created_at` ascending. Random identifiers are never consulted as a tie-break. Each subscription's provisional share is the payable multiplied by its `committed_cents` and divided by the total `committed_cents` of the participating subscriptions, rounded half-up to a whole cent. Because rounding can leave the shares summing to less than the payable, the shortfall is then distributed in that same pinned order, one cent to each subscription, until it is exhausted. If the payable is smaller than the number of participating subscriptions, the earliest subscriptions in the pinned order receive the single cents. A distribution larger than the allocation's delivered credit dollars is rejected with `ERR_DISTRIBUTION_EXCEEDS_DELIVERED`.

Investors and underwriters observe the portfolio through a small set of read surfaces rather than through direct state inspection. A fund's read view exposes its derived posture, its `priced_yield_pct` and `realized_yield_pct`, its `priced_value_cents` and `realized_value_cents`, its `awarded_credits_total_cents` and `delivered_credits_total_cents`, its `subscribed_equity_cents` and `funded_equity_cents`, and its `subscription_count`, all recomputed on read so the numbers are never stale. An investor following the funds it subscribes to reads each project within them together with that project's capital calls, allocations, guarantees, reviews, and exit events, and reads its own commitments through its `outstanding_commitment_cents` and `funded_cents`. A developer reads its own derived `status` and `guarantee_exposure_cents` alongside its projects and their `active_project_count`.

The portfolio summary view is the aggregated reporting surface for a fund, and it presents `project_count`, `distressed_count`, `total_awarded_credit_dollars_cents`, `total_delivered_credit_dollars_cents`, `total_committed_equity_cents`, and `weighted_average_risk_score` as described above. Because the summary is built from the `COMMITTED` and `CLOSED` allocations of non-`EXITED` projects, an allocation that is rescinded leaves the summary totals the moment it leaves the committed set, and a project that exits leaves the summary the moment its status changes to `EXITED`.

### 3.4. Developer Underwriting and the Commitment Gate

A project is created by an `Underwriter`, who supplies `developer_id`, `fund_id`, `project_name`, `state_code`, `total_credit_dollars_cents`, `construction_budget_cents`, `construction_loan_cents`, `operating_pro_forma_noi_cents`, `debt_service_cents`, `market_study_absorption_score`, `sponsor_experience_months`, `placed_in_service_deadline`, and an optional `compliance_period_months`. The `state_code` must be exactly two uppercase letters, and the `market_study_absorption_score` is a decimal fraction between 0 and 1 inclusive. The `compliance_period_months` defaults to 180. A new project starts at `UNDERWRITING` with `underwriting_stage` `PRELIMINARY`, and creation immediately computes `preliminary_equity_cents` and `underwritten_equity_cents`, and derives `dscr`, `operating_deficit_cents`, and `underwritten_gap_cents`.

Three derived figures anchor the underwriting story. The `dscr` is the `operating_pro_forma_noi_cents` divided by the `debt_service_cents`, held to 4 decimal places. The `operating_deficit_cents` is the `debt_service_cents` minus the `operating_pro_forma_noi_cents`, floored at zero. The `underwritten_gap_cents` is the `construction_budget_cents` minus the `construction_loan_cents` minus the `underwritten_equity_cents`, and it is never allowed to go negative.

Equity underwriting runs in two variants that are deliberately built from different bases, and the active result is whichever variant the project's `underwriting_stage` selects. The preliminary variant is the estimate a developer circulates before the credit award has been priced, and it ignores the credit award entirely. Its base is the `construction_budget_cents` minus the `construction_loan_cents`. A quality uplift is then computed as that base multiplied by the `market_study_absorption_score` and by 0.10, rounded half-up to a whole cent. The `preliminary_equity_cents` is the base minus the quality uplift.

The final variant is computed only when underwriting is finalized, and it is built from the award rather than from the budget gap. The credit value is the `total_credit_dollars_cents` multiplied by the fund's current `price_per_credit_dollar`, rounded half-up to a whole cent. The final base is again the `construction_budget_cents` minus the `construction_loan_cents`. The sponsor uplift is the final base multiplied by the lesser of `sponsor_experience_months` and 120, divided by 10000.0, rounded half-up to a whole cent. The `final_equity_cents` is the lesser of the final base and the credit value, minus the sponsor uplift. The `underwritten_equity_cents` is always `final_equity_cents` when the stage is `FINAL` and `preliminary_equity_cents` otherwise. The two variants are rounded independently; there is no shared intermediate between them, and the preliminary figure is generally the larger of the two whenever the credit award times the fund price falls below the budget gap.

The `underwriting_stage` is a second dimension on the same project row, independent of the project's status pipeline. It begins at `PRELIMINARY` and is moved to `FINAL` by an `Underwriter` submitting `underwriting_action` set to finalize. Finalization is permitted only when the `market_study_absorption_score` is at least 0.60, the `construction_budget_cents` is greater than zero, the `operating_pro_forma_noi_cents` and the `debt_service_cents` are both greater than zero, and the `sponsor_experience_months` is at least 24. Finalizing computes `final_equity_cents` and causes `underwritten_equity_cents` to switch from the preliminary to the final figure. The reverse edge is automatic: while the project is still `UNDERWRITING`, a change to any underwriting input through the project edit operation reverts the stage from `FINAL` to `PRELIMINARY`, sets `final_equity_cents` back to null, and returns `underwritten_equity_cents` to the preliminary figure. Any such edit also recomputes `preliminary_equity_cents`, and every project edit requires `expected_project_version` and increments the project's `version`.

The project edit operation accepts `underwriting_action`, `allocation_action`, `allocation_id`, `construction_budget_cents`, `construction_loan_cents`, `operating_pro_forma_noi_cents`, `debt_service_cents`, `market_study_absorption_score`, `sponsor_experience_months`, `placed_in_service_deadline`, and `expected_project_version`. The allocation actions move a single allocation between `AWARDED` and `RESERVED`, with `allocation_action` set to reserve or release and the target named by `allocation_id`. Reserving may also be achieved by recording a superseding award for the same project and `state_agency`.

An allocation is the record of a credit award from a housing finance agency, and it is created under a project with an `action` that distinguishes the operations the endpoint carries. Creation supplies `state_agency`, `awarded_credit_dollars_cents`, `commitment_fee_pct`, `awarded_date`, and `placed_in_service_deadline`, and the allocation begins at `AWARDED`. An allocation moves from `AWARDED` to `RESERVED` when a superseding award is recorded for the same project and `state_agency`, or when the project edit carries the reserve action. That move is refused when the new allocation's award interval, from `awarded_date` up to but not including `placed_in_service_deadline`, overlaps another `AWARDED` or `RESERVED` allocation of the same project and `state_agency`; touching intervals are permitted, so a new `awarded_date` that exactly equals an existing `placed_in_service_deadline` is allowed. An overlap is rejected with `ERR_DUPLICATE_ALLOCATION_PERIOD`. An allocation moves back from `RESERVED` to `AWARDED` when the project edit carries the release action.

Commitment is the pivot of the whole system. An `Underwriter` commits a fully underwritten project, and the operation requires all of the following at once: the `underwriting_stage` must be `FINAL`; the project's fund must be in `CLOSING`, `CLOSED`, or `DEPLOYING` and its `posture` must be `OPEN`; the sponsoring developer's `status` must be `ELIGIBLE`; the project must have at least one allocation in `RESERVED` or `AWARDED`; the `dscr` must be at least 1.15; the `market_study_absorption_score` must be at least 0.60; and the logical clock must be at or before the `placed_in_service_deadline`. A commit attempted with `underwriting_stage` still at `PRELIMINARY`, or from a project status other than `UNDERWRITING`, or with no allocation in `RESERVED` or `AWARDED`, or with a `dscr` below 1.15, or with an absorption score below 0.60, or with `sponsor_experience_months` below 24, is rejected with `ERR_PROJECT_NOT_COMMITTABLE`. A commit whose developer is on `WATCH` or `SUSPENDED` is rejected with `ERR_DEVELOPER_WATCH_BLOCKED`. A commit against a fund whose posture is `FROZEN` is rejected with `ERR_FUND_POSTURE_FROZEN`. A successful commit moves the project from `UNDERWRITING` to `COMMITTED`, moves every `RESERVED` and every `AWARDED` allocation of that project into `COMMITTED`, moves the fund from `CLOSED` to `DEPLOYING` if it was `CLOSED`, and recomputes the project's `committed_credit_dollars_cents` together with the fund's `subscribed_equity_cents`, `priced_yield_pct`, and `realized_yield_pct`. It also increments the project's `version`.

The two terminal ends of an allocation's life are reached from the asset-management side. An `AssetManager` closes an allocation by recording a delivery action to close, which moves it from `COMMITTED` to `CLOSED`; closure requires that the allocation's `delivered_credit_dollars_cents` not exceed its `awarded_credit_dollars_cents`, and it recomputes the project's `delivered_credit_dollars_cents`, the allocation's `delivery_ratio`, and the fund's `realized_yield_pct`. An `AssetManager` rescinds an allocation by recording a delivery action to rescind, which moves it from `AWARDED`, `RESERVED`, or `COMMITTED` to `RESCINDED`; rescission requires that the delivered credit dollars be strictly below the awarded credit dollars, and it removes the allocation from the project's committed total, recomputing the project's `committed_credit_dollars_cents` and the fund's `subscribed_equity_cents` and `priced_yield_pct`. A close attempted on an allocation that is not `COMMITTED`, or a rescind attempted on one already `CLOSED`, is rejected with `ERR_INVALID_ALLOCATION_STATE`. Delivery against an allocation is recorded with the delivery action and a per-allocation `delivered_credit_dollars_cents`, which recomputes the allocation's `delivery_ratio` and the project's `delivered_credit_dollars_cents`; a distribution runs the pinned-order payable split described in §3.3 across the fund's non-`DEFAULTED` subscriptions.

Two conservation invariants are asserted across these paired operations, and both must hold to the cent. The credit-dollar invariant pairs a commitment with a rescission: a commitment moves every `RESERVED` or `AWARDED` allocation into `COMMITTED`, and a subsequent rescission of one of those allocations moves it out again, so the project's `committed_credit_dollars_cents` after the pair equals its value immediately before the commitment. With a single allocation awarded a given number of cents, the sequence through the total must read zero, then that amount, then zero exactly. The equity invariant pairs a subscription creation with a default: creating a subscription with a commitment of a given number of cents adds that amount to the fund's `subscribed_equity_cents`, and that subscription later reaching `DEFAULTED` removes it again, so after the pair the fund's `subscribed_equity_cents` plus the sum of `committed_cents` across the fund's defaulted subscriptions equals the sum of `committed_cents` across all of the fund's subscriptions, exactly, and the fund's `subscribed_equity_cents` has returned to its pre-creation value to the cent. A drift of even one cent in either invariant is a failure.

### 3.5. Construction Milestones and Capital Calls

Once a project is committed, its physical progress is recorded as milestones by an `AssetManager` or an `Underwriter`, one step at a time, by naming the `milestone` reached. The project status advances `COMMITTED → CONSTRUCTION → LEASE_UP → STABILIZED → COMPLIANCE_PERIOD`, and each step is gated on the capital call for the preceding stage having actually been paid.

The `CONSTRUCTION_START` milestone moves the project from `COMMITTED` to `CONSTRUCTION`, but only once a capital call for that same milestone exists and is in status `PAID`; the move recomputes the paid-in progress of every subscription of the project's fund. The `LEASE_UP_50PCT` milestone moves the project from `CONSTRUCTION` to `LEASE_UP`, gated on a `CONSTRUCTION_50PCT` capital call existing in status `PAID`. The `LEASE_UP_STABILIZED` milestone moves the project from `LEASE_UP` to `STABILIZED`, gated on a `LEASE_UP_50PCT` capital call existing in status `PAID`, and recomputes the debt-service coverage fields that later feed the watch-list risk score. A milestone recorded out of order, or without its predecessor call having been paid, is rejected with `ERR_PROJECT_NOT_COMMITTABLE`.

The `PLACED_IN_SERVICE` milestone is the pivot into the fifteen-year compliance regime. It moves the project from `STABILIZED` to `COMPLIANCE_PERIOD`, and it requires both that a `LEASE_UP_STABILIZED` capital call exists in status `PAID` and that the logical clock be at or before the project's `placed_in_service_deadline`; a milestone recorded after that deadline is rejected with `ERR_PLACED_IN_SERVICE_DEADLINE_PASSED`. On success the `placed_in_service_at` field is stamped with the logical clock and the compliance end is derived as the placed-in-service month plus `compliance_period_months`.

A capital call is an equity call against a milestone. It is scheduled with `milestone`, `scheduled_date`, `due_date`, `milestone_share`, and `expected_project_version`. The `milestone` must be one of `CONSTRUCTION_START`, `CONSTRUCTION_50PCT`, `LEASE_UP_50PCT`, `LEASE_UP_STABILIZED`, or `PLACED_IN_SERVICE`. A newly scheduled call begins at `SCHEDULED`, with `credit_delivery_adjuster_pct` at 0.0, `settled_amount_cents` at 0, and `shortfall_cents` at 0, and it increments the project's `version`. Creating a call against a fund whose posture is `FROZEN` is rejected with `ERR_FUND_POSTURE_FROZEN`, and creating one for a fund that has been terminated before closing, or wound down, is rejected with `ERR_FUND_NOT_FORMING`.

A call is issued by an `AssetManager`, moving it from `SCHEDULED` to `ISSUED`, and three conditions must hold. The logical clock must be at or after the call's `scheduled_date`, else the request is rejected with `ERR_CALL_NOT_DUE`. No other capital call of the same project may carry the same `milestone` in any status at all, else the request is rejected with `ERR_DUPLICATE_CALL_MILESTONE`. And the call's `scheduled_date` must be at least 30 days after the `due_date` of the most recently `PAID` or `DEFICIENT` capital call of the same project; when there is no such prior call the buffer check passes vacuously. A call whose `scheduled_date` falls fewer than 30 days after that prior `due_date` is rejected with `ERR_CALL_BUFFER_TOO_SHORT`. Issuing a call computes its `called_amount_cents`.

The called amount is derived from the project's active equity and from a credit-delivery band, in a pinned two-stage evaluation. The band is selected from every allocation of the project that is in status `COMMITTED`: the awarded credit dollars of those allocations are summed, the delivered credit dollars of those allocations are summed, and the delivery ratio is the delivered sum divided by the awarded sum, or 1.0 when the awarded sum is zero. The band is then chosen by the delivery ratio, and the boundaries are half-open on the low side, so a ratio that sits exactly on a boundary takes the lower adjuster. A delivery ratio of at least 0.99 selects an adjuster of 0.00. A ratio of at least 0.95 and below 0.99 selects 0.05. A ratio of at least 0.90 and below 0.95 selects 0.12. A ratio below 0.90 selects 0.20. The adjuster actually pinned on the call is the greater of that band value and the adjuster the call already carries, so the adjuster ratchets upward and never falls.

With the adjuster settled, the amount is computed in an explicitly pinned order. The `base_call_cents` is the project's `underwritten_equity_cents` multiplied by the call's `milestone_share`, rounded half-up to a whole cent. The `called_amount_cents` is then the `base_call_cents` multiplied by one plus the `credit_delivery_adjuster_pct`, rounded half-up again. The milestone share is rounded before the adjuster is applied, and the adjuster is applied to the rounded share; summing first and rounding once produces different cents and is not the specified behaviour.

Settlement is driven by the call's investors. An `Investor` settles an issued call by supplying `funded_amount_cents`, and the settlement branches on that amount. When the funded amount equals the `called_amount_cents`, the call moves from `ISSUED` to `PAID`, `settled_amount_cents` is recorded, `shortfall_cents` remains zero, the `paid_in_cents` of every subscription of the project's fund is recomputed, and the project's and fund's delivered credit fields are recomputed. When the funded amount is less than the `called_amount_cents`, the call moves from `ISSUED` to `DEFICIENT` and `shortfall_cents` is set to the called amount minus the funded amount; that shortfall is added to every subscription of the project's fund. A settlement requested against a call that is not `ISSUED` is rejected with `ERR_CALL_NOT_ISSUED`, and a settlement by an `Investor` whose subscription is not in the call's project's fund is rejected with `ERR_FORBIDDEN_SCOPE`.

Whenever a shortfall lands on a subscription, the subscription's own crisis is tested. A defaulted subscription is a terminal one, so once a subscription reaches `DEFAULTED` no further pay-in is accepted against it and the attempt is rejected with `ERR_SUBSCRIPTION_TERMINAL`. The threshold is a band: when a subscription's accumulated `shortfall_cents` exceeds 20 percent of its `committed_cents`, rounded half-up, the subscription becomes `DEFAULTED` rather than merely underfunded, and its investor becomes `SUSPENDED`. A settlement that pushes a fully funded subscription below its commitment, without breaching the band, instead moves it from `FULLY_FUNDED` back to `PARTIALLY_FUNDED` and raises its `unfunded_commitment_cents`.

Adjustment is the mechanism by which a call is re-priced after the credit picture changes, and it carries the system's most intricate cascade. An `AssetManager` adjusts a call with the adjust action when the project's allocation delivery ratio now selects a strictly larger adjuster than the one currently pinned on the call; the call must be `ISSUED` or `PAID`, and a `DEFICIENT` call is never adjusted. Adjustment recomputes `credit_delivery_adjuster_pct` and `called_amount_cents` under the ratchet rule. When the call had already been `PAID`, the delta between the new `called_amount_cents` and the recorded `settled_amount_cents` is reclaimed from the project's fund: the fund's `funded_equity_cents` decreases by that delta, and every subscription of the fund has its `paid_in_cents` reduced by that delta. Reducing those paid-in amounts moves every `FULLY_FUNDED` subscription back to `PARTIALLY_FUNDED` — the cyclic edge that this domain is built around — and raises each subscription's `unfunded_commitment_cents`. The fund's `realized_value_cents` and `realized_yield_pct` are recomputed. If the reclaimed shortfall pushes a subscription's `shortfall_cents` past the 20 percent band, that subscription becomes `DEFAULTED` and its investor `SUSPENDED`. The call itself moves to `ADJUSTED`. An adjusted call is returned to the outstanding state by a re-issue, which moves it from `ADJUSTED` back to `ISSUED` once the project's delivery-ratio band matches the adjuster now pinned on the call; once re-issued, the call's interval participates again in the 30-day buffer test. An adjustment or settlement requested against a call that is not in the required state is rejected with `ERR_CALL_NOT_ISSUED`.

### 3.6. Guarantees and Sponsor Backstop

Every committed project is backstopped by guarantees written by its sponsoring developer, and the developer's exposure to those guarantees is tracked continuously. A guarantee is recorded against a project by an `AssetManager` or an `Underwriter`, with `guarantee_type`, `guaranteed_amount_cents`, `recapture_pct`, `coverage_start_date`, and `coverage_end_date`. The `guarantee_type` must be `OPERATING_DEFICIT`, `RECAPTURE`, or `COMPLETION`. The `coverage_end_date` must be strictly after the `coverage_start_date`, and a guarantee of the same project and same `guarantee_type` may not cover an interval that overlaps a non-`RELEASED` guarantee already on the books; an overlap is rejected with `ERR_COVERAGE_WINDOW_OVERLAP`. A new guarantee whose amount would push the developer's `guarantee_exposure_cents` above its `net_worth_cents` without the developer qualifying under the sponsor-eligibility coverage test is rejected with `ERR_GUARANTEE_EXPOSURE_EXCEEDED`. A newly recorded guarantee starts at `ACTIVE`, with `drawn_amount_cents` at zero and `remaining_capacity_cents` equal to the `guaranteed_amount_cents`, and it recomputes the developer's `guarantee_exposure_cents` and `status` and increments the project's `version`.

Guarantee draws are exclusive to the `AssetManager`. A draw supplies `requested_amount_cents`, and moves the guarantee from `ACTIVE` to `DRAWN` when the draw is positive. The amount drawn increases by the lesser of the requested amount and the guarantee's remaining capacity, so a draw larger than the capacity simply consumes the capacity rather than being rejected. The `remaining_capacity_cents` is then recomputed as the guarantee amount less the drawn amount and is never allowed below zero. The draw recomputes the developer's `guarantee_exposure_cents` and re-derives the developer's `status`.

The preconditions a draw must satisfy depend on the guarantee type, and each type is gated on the matching distress condition. An `OPERATING_DEFICIT` guarantee may be drawn only when the project's `operating_deficit_cents` is strictly greater than zero and the acting developer's `liquid_assets_cents` are insufficient to cover the deficit in full. That insufficiency is itself defined by a coverage test: the monthly deficit is the `operating_deficit_cents` divided by 12 and rounded half-up to a whole cent, the annual deficit is the `operating_deficit_cents` taken as it stands but never below zero, and the coverage months are the developer's `liquid_assets_cents` divided by the monthly deficit using integer floor division, with the divisor never below one. The developer is considered covered when those months reach at least 12, and an operating deficit draw is permitted only when the developer is not covered. A `RECAPTURE` guarantee may be drawn only when the project has at least one review in status `NONCOMPLIANT` or `ESCALATED`, and a `COMPLETION` guarantee may be drawn only when the project has at least one review in status `ESCALATED`. Every draw additionally requires that the drawn amount be below the guaranteed amount.

A zero draw is a reinstatement rather than a draw, and it moves a `DRAWN` guarantee back to `ACTIVE` in order to restore its absorbency for a later call; it requires that the remaining capacity be positive after the zero draw and leaves `drawn_amount_cents` unchanged.

A recapture draw is one of the two events that push a project into `DISTRESSED`; the other is leaving a review escalated. When a recapture guarantee moves to `DRAWN`, the owning project becomes `DISTRESSED`, and the owning fund's posture and the owning developer's status are recomputed.

A guarantee is discharged when the crisis that justified its draw has fully healed: it moves from `ACTIVE` to `DISCHARGED` once the last relevant review of the project has been moved to `CURED` while the guarantee's drawn amount is zero and the project retains no review in `ESCALATED` or `NONCOMPLIANT`. A discharged guarantee keeps its full remaining capacity. Every guarantee of a project — `ACTIVE`, `DRAWN`, or `DISCHARGED` alike — becomes `RELEASED` when the owning project reaches `EXITED`, and at that point the developer's `guarantee_exposure_cents` drops by that guarantee's guaranteed amount. `RELEASED` is the only terminal value of this machine.

### 3.7. Compliance Reviews, Watch List, and Distress

The compliance period is a revolving annual review. An `AssetManager` or a `ComplianceOfficer` opens a review for a project with `review_period_index`, `review_period_end`, `occupancy_pct`, `dscr_observed`, and `reserve_balance_cents`. A review opens at `PENDING`, and the `review_period_end` is the instant the reviewed compliance year closes; the `review_period_index` is a zero-based year index, and a second review for a period index already reviewed for that project is rejected with `ERR_DUPLICATE_REVIEW_PERIOD`.

Opening the review scores it into a weighted risk score, which is floored at zero and capped at 100 and whose terms are each rounded half-up to an integer before being summed. The occupancy term is 35 multiplied by the `occupancy_pct`. The debt-service term is 30 multiplied by the lesser of the `dscr_observed` and 1.5, divided by 1.5. The reserve term is 20 when the `reserve_balance_cents` is below 50000000, and zero otherwise. The term-violation points are 15 for each of two conditions that holds: the logical clock is after the project's `placed_in_service_deadline`, and the review's `review_period_end` is after the logical clock. The raw score is the sum of the four terms, and the `risk_score` is that sum clamped into the range from zero to 100.

The `outcome` is always optional: when it is absent the resolve action derives the classification from the score, and when it is present it names the finding the officer is recording. Resolving a review reads the score into a band and, for the two most serious outcomes, into an additional requirement. When no `outcome` is supplied, the resolve action derives the outcome from the score: a score below 70 resolves the review from `PENDING` to `COMPLIANT`; a score of at least 70 and below 85 resolves it from `PENDING` to `WATCH`, making it visible on the project's watch list; a score of 85 or above resolves it from `PENDING` to `ESCALATED`. Escalation, and the recording of the two most serious outcomes, are reserved to the `ComplianceOfficer`; the `AssetManager` may resolve only the implied and cured outcomes. A review on `WATCH` may later be corrected and re-resolved to `COMPLIANT` if the corrected inputs bring the score below 70, or escalated to `ESCALATED` if the corrected inputs raise the score to 85 or above.

`ESCALATED` is the state that carries consequences beyond the review row. Resolving a review into `ESCALATED` stamps `escalated_at` with the logical clock, moves the owning project to `DISTRESSED` because an escalated review is sufficient on its own, recomputes the owning developer's status, and recomputes the owning fund's posture. Escalation is also the precondition for the two terminal outcomes: a review may be moved from `ESCALATED` to `NONCOMPLIANT` only once the logical clock has reached the review's `review_period_end`, because a noncompliance finding may not be recorded before the reviewed period has closed, and a finding recorded earlier is rejected with `ERR_REVIEW_PERIOD_OPEN`. A `NONCOMPLIANT` or `CURED` outcome requested on a review that never reached `ESCALATED` or `NONCOMPLIANT` is rejected with `ERR_REVIEW_NOT_ESCALATED`.

Recording a `NONCOMPLIANT` finding increments the project's `compliance_failure_count` by one and recomputes the developer's status. It also feeds the fund-level posture rule directly: if the project's `compliance_failure_count` reaches 2, the owning fund's posture becomes `FROZEN`.

A `NONCOMPLIANT` review is cured by a `ComplianceOfficer` supplying the `corrected_reserve_balance_cents` recorded with the cure. The cure requires that the recorded corrected reserve balance be at least the reserve target of 50000000 cents; `corrected_reserve_balance_cents` is null until a cure is recorded. Curing moves the review to `CURED`, removes it from the count that drives the `FROZEN` condition, recomputes the owning fund's posture, and recomputes the developer's status. When the cure clears the developer's last escalated review, the developer returns from `SUSPENDED` to `WATCH`.

A project that has been `DISTRESSED` can be healed, and the healing is explicit. A `DISTRESSED` project returns to `COMPLIANCE_PERIOD` once none of its reviews remains `ESCALATED`, provided the project had reached `COMPLIANCE_PERIOD` before it became distressed. The return recomputes the owning fund's posture back toward `OPEN` when no other project of the fund is distressed. The project's return is the mechanism that makes this domain's state machine cyclic rather than terminal.

### 3.8. Fund Posture and Portfolio Constraints

A fund's `posture` is a second, independent state machine on the fund row, and it is derived rather than set. It is recomputed whenever a compliance review is opened or resolved, whenever a project is committed, whenever a milestone is recorded, and whenever a guarantee is drawn. The derivation has a strict precedence and is evaluated top-down: the first matching rule wins, and a higher rule always dominates a lower one. A fund's posture is `FROZEN` when at least two of its projects are `DISTRESSED`, or when any single one of its projects has a `compliance_failure_count` of at least 2. Only if neither of those holds is the posture `WATCH`, which applies when exactly one of the fund's projects is `DISTRESSED`. Otherwise the posture is `OPEN`. Because the precedence is strict, a fund with two distressed projects and one compliance failure is `FROZEN` and never `WATCH`.

Posture is a gate rather than a penalty. A fund whose posture is `FROZEN` refuses both project commitments and capital call creations for every one of its projects, and both are rejected with `ERR_FUND_POSTURE_FROZEN`. A fund on `WATCH`, by contrast, still permits commitments — the posture is a warning, not a freeze — and only the `FROZEN` posture blocks the write path. The value also moves in both directions: once the underlying conditions clear, a fund on `WATCH` or `FROZEN` returns to `OPEN`.

### 3.9. The Fifteen-Year Exit

A project reaches the end of its compliance period and becomes exit-eligible when the logical clock reaches `compliance_period_months` months after its placed-in-service stamp and its `compliance_failure_count` is zero. Satisfying both conditions moves the project from `COMPLIANCE_PERIOD` to `EXIT_ELIGIBLE`. An exit event may then be created for the project, and an exit event requested for a project that is neither `COMPLIANCE_PERIOD` nor `EXIT_ELIGIBLE`, or whose compliance period has not yet run, is rejected with `ERR_EXIT_NOT_ELIGIBLE`.

An exit event is planned by an `Underwriter` or an `AssetManager` with `exit_year`, `rofr_notice_date`, an optional `rofr_window_days`, and `exercise_deadline`. The `rofr_window_days` is the length of the right-of-first-refusal window in days and defaults to 90. The exit event begins at `PENDING`, and its `rofr_expires_at` is computed as the `rofr_notice_date` plus the `rofr_window_days`.

The exit event moves through `PENDING → OPTION_NOTICE_ISSUED → ROFR_WINDOW → EXERCISED`, with a decline branch to `DECLINED` and a final `CLOSED`. Issuing the option notice, available to an `Underwriter` or an `AssetManager`, moves the event from `PENDING` to `OPTION_NOTICE_ISSUED` and requires that the owning project be in `COMPLIANCE_PERIOD` or `EXIT_ELIGIBLE`, that the `exercise_deadline` be at or after the `rofr_notice_date` — otherwise the request is rejected with `ERR_EXIT_WINDOW_INVERTED` — and that the computed `rofr_expires_at` fall at or before the `exercise_deadline`, otherwise the request is rejected with `ERR_EXIT_WINDOW_INVERTED` as well. Issuing the notice computes `rofr_expires_at` from the notice date and the window length, and computes `option_price_cents`.

The option price is built in a pinned three-step evaluation in which each step reads the already-rounded result of the step above it, and the final price is floored at zero. First, the project's `underwritten_equity_cents` is multiplied by 1.05 and rounded half-up to a whole cent, producing a five percent equity step-up. Second, the `cumulative_distributions_cents`, which is the sum of `settled_amount_cents` across the project's `PAID` capital calls, is subtracted from that stepped-up figure, and the difference is rounded half-up. Third, the result is multiplied by one plus 0.01 for each capital call of the project that is `DEFICIENT` or `ADJUSTED`, and that product is rounded half-up. The three roundings are sequential and the order is pinned; a different order yields a different cent total.

Opening the right-of-first-refusal window moves the event from `OPTION_NOTICE_ISSUED` to `ROFR_WINDOW` by the `AssetManager`. The window from the `rofr_notice_date` through the `rofr_expires_at` is pinned at this point, and a second exit notice for the same project whose window would overlap an already-open window is rejected with `ERR_ROFR_WINDOW_OVERLAP`.

Exercising the option is the `Underwriter`'s act, moving the event from `ROFR_WINDOW` to `EXERCISED`. It requires that the logical clock be at or before the `rofr_expires_at`, else the request is rejected with `ERR_ROFR_WINDOW_EXPIRED`; that the acting developer's `status` be `ELIGIBLE` and that the developer have no project in status `DISTRESSED`, either failure being reported as `ERR_DEVELOPER_NOT_ELIGIBLE_FOR_EXIT`. Exercise recomputes `cumulative_distributions_cents` from the project's `PAID` capital calls and recomputes `option_price_cents` under the same pinned order. An exit action requested from a state that does not permit it is rejected with `ERR_EXIT_EVENT_NOT_PENDING`: issuing a notice from anything other than `PENDING`, exercising from anything other than `ROFR_WINDOW`, or closing from anything other than `EXERCISED` or `DECLINED`.

Declining moves the event from `OPTION_NOTICE_ISSUED` or `ROFR_WINDOW` to `DECLINED`, and it can be done deliberately by an `Underwriter` or automatically by the system once the logical clock passes the `rofr_expires_at`. In either case the owning project returns to `COMPLIANCE_PERIOD`, where a fresh exit event may be planned for the following compliance year.

Closing is the `AssetManager`'s final act, moving the event from `EXERCISED` or `DECLINED` to `CLOSED` once the exit distribution has been recorded. When the event closes from `EXERCISED`, the owning project becomes `EXITED`; every guarantee of the project whose status is `ACTIVE`, `DRAWN`, or `DISCHARGED` becomes `RELEASED`; and the owning developer's `active_project_count` and `guarantee_exposure_cents` are recomputed. When the event closes from `DECLINED`, the project has already returned to `COMPLIANCE_PERIOD` and no exit occurs.

## 4. Endpoint Definitions

Two status-code conventions govern the whole surface. An operation that creates a new stand-alone resource, or that adds a new distinct resource to a collection, returns `201 Created` with the created resource in the `data` field. An operation that modifies an existing resource, including one that advances it through a state machine or records a delivery against it, returns `200 OK` with the updated resource in the `data` field. The one exception to the "return the resource" convention is the logical clock, which returns the clock's current value rather than a resource object.

The table below lists every endpoint with the roles permitted to call it. Request bodies, response bodies, and side effects are deliberately omitted here; they are specified in the workflows of §3. Where an endpoint's behaviour depends on an action value supplied in the request, the action names appear in §3, not in this table.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/developers` | Onboard a sponsor/developer | PlatformAdmin |
| GET | `/developers/{developer_id}` | Read a developer with derived status and guarantee exposure | Developer, Underwriter, AssetManager, ComplianceOfficer, PlatformAdmin |
| POST | `/investors` | Onboard an institutional investor | PlatformAdmin |
| GET | `/investors/{investor_id}` | Read an investor with outstanding commitment and funded equity | Investor, Underwriter, AssetManager, PlatformAdmin |
| POST | `/funds` | Form a syndication fund | Underwriter, PlatformAdmin |
| GET | `/funds/{fund_id}` | Read a fund with derived posture, pricing, yields and portfolio counters | Underwriter, AssetManager, Investor, PlatformAdmin |
| PUT | `/funds/{fund_id}` | Reprice a fund or move its close threshold | Underwriter |
| POST | `/funds/{fund_id}/subscriptions` | Create an investor subscription against a fund | Investor, PlatformAdmin |
| GET | `/subscriptions` | List subscriptions, filterable by fund and investor | Investor, Underwriter, AssetManager, PlatformAdmin |
| GET | `/subscriptions/{subscription_id}` | Read one subscription with paid-in progress and shortfall | Investor, Underwriter, AssetManager, PlatformAdmin |
| POST | `/subscriptions/{subscription_id}/payins` | Record an equity pay-in against a subscription | Investor, PlatformAdmin |
| POST | `/projects` | Create a project under a developer and a fund | Underwriter |
| GET | `/projects` | List projects, filterable by developer, fund and status | Underwriter, AssetManager, ComplianceOfficer, Developer, PlatformAdmin |
| GET | `/projects/{project_id}` | Read a project with derived underwriting, credit-delivery and compliance fields | Underwriter, AssetManager, ComplianceOfficer, Developer, Investor, PlatformAdmin |
| PUT | `/projects/{project_id}` | Edit underwriting inputs, finalize or reopen underwriting, or reserve/release an allocation | Underwriter |
| POST | `/projects/{project_id}/commit` | Commit a fully underwritten project and its allocations to its fund | Underwriter |
| POST | `/projects/{project_id}/milestones` | Record a construction, lease-up or placed-in-service milestone | AssetManager, Underwriter |
| GET | `/projects/{project_id}/capital-calls` | List a project's capital calls, filterable by milestone and status | Investor, AssetManager, Underwriter, PlatformAdmin |
| POST | `/projects/{project_id}/capital-calls` | Schedule an equity capital call against a milestone | AssetManager, Underwriter |
| POST | `/capital-calls/{call_id}/transitions` | Issue, settle, adjust or re-issue a capital call | Investor, AssetManager |
| GET | `/projects/{project_id}/allocations` | List a project's credit allocations, filterable by status | Underwriter, AssetManager, Investor, ComplianceOfficer, PlatformAdmin |
| POST | `/projects/{project_id}/allocations` | Create an allocation award, or close, rescind, record a delivery against, or distribute one | Underwriter, AssetManager |
| GET | `/projects/{project_id}/guarantees` | List a project's guarantees, filterable by type and status | AssetManager, ComplianceOfficer, Underwriter, Investor, PlatformAdmin |
| POST | `/projects/{project_id}/guarantees` | Record a developer guarantee covering a project | AssetManager, Underwriter |
| POST | `/guarantees/{guarantee_id}/draw` | Draw against a guarantee, or reinstate a partially drawn one with a zero draw | AssetManager |
| GET | `/projects/{project_id}/reviews` | List a project's compliance reviews, filterable by status and period | AssetManager, ComplianceOfficer, Investor, PlatformAdmin |
| POST | `/projects/{project_id}/reviews` | Open a compliance review for a period and score it | AssetManager, ComplianceOfficer |
| POST | `/reviews/{review_id}/resolve` | Resolve a compliance review into compliant, watch, escalated, noncompliant or cured | AssetManager, ComplianceOfficer |
| GET | `/projects/{project_id}/exit-events` | List a project's year-fifteen exit events | Underwriter, AssetManager, Investor, PlatformAdmin |
| POST | `/projects/{project_id}/exit-events` | Plan a year-fifteen exit for a project | Underwriter, AssetManager |
| POST | `/exit-events/{exit_event_id}/exercise` | Issue the option notice, open the ROFR window, exercise, decline or close an exit | Underwriter, AssetManager |
| POST | `/_clock/set_current_utc` | Set the logical clock | PlatformAdmin |

## 5. Error Code Catalogue

The table below lists every error identifier the API can return against its HTTP status code. The conditions that trigger each error are stated in the narratives of §2 and §3 rather than repeated here.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_FORBIDDEN_SCOPE` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_EXIT_WINDOW_INVERTED` | 400 Bad Request |
| `ERR_DEVELOPER_NOT_FOUND` | 404 Not Found |
| `ERR_FUND_NOT_FOUND` | 404 Not Found |
| `ERR_PROJECT_NOT_FOUND` | 404 Not Found |
| `ERR_ALLOCATION_NOT_FOUND` | 404 Not Found |
| `ERR_CAPITAL_CALL_NOT_FOUND` | 404 Not Found |
| `ERR_GUARANTEE_NOT_FOUND` | 404 Not Found |
| `ERR_SUBSCRIPTION_NOT_FOUND` | 404 Not Found |
| `ERR_REVIEW_NOT_FOUND` | 404 Not Found |
| `ERR_EXIT_EVENT_NOT_FOUND` | 404 Not Found |
| `ERR_PROJECT_NOT_COMMITTABLE` | 409 Conflict |
| `ERR_INVALID_ALLOCATION_STATE` | 409 Conflict |
| `ERR_CALL_NOT_ISSUED` | 409 Conflict |
| `ERR_REVIEW_NOT_ESCALATED` | 409 Conflict |
| `ERR_EXIT_EVENT_NOT_PENDING` | 409 Conflict |
| `ERR_SUBSCRIPTION_TERMINAL` | 409 Conflict |
| `ERR_DEVELOPER_WATCH_BLOCKED` | 422 Unprocessable Entity |
| `ERR_GUARANTEE_EXPOSURE_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_DEVELOPER_NOT_ELIGIBLE_FOR_EXIT` | 422 Unprocessable Entity |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_DUPLICATE_CALL_MILESTONE` | 409 Conflict |
| `ERR_CALL_BUFFER_TOO_SHORT` | 409 Conflict |
| `ERR_DUPLICATE_SUBSCRIPTION` | 409 Conflict |
| `ERR_DUPLICATE_ALLOCATION_PERIOD` | 409 Conflict |
| `ERR_ROFR_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_COVERAGE_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_INVESTOR_SUSPENDED` | 403 Forbidden |
| `ERR_FUND_POSTURE_FROZEN` | 409 Conflict |
| `ERR_FUND_NOT_FORMING` | 409 Conflict |
| `ERR_DUPLICATE_REVIEW_PERIOD` | 409 Conflict |
| `ERR_EXIT_NOT_ELIGIBLE` | 409 Conflict |
| `ERR_SUBSCRIPTION_EXCEEDS_CAPACITY` | 422 Unprocessable Entity |
| `ERR_OVERPAYMENT` | 422 Unprocessable Entity |
| `ERR_DISTRIBUTION_EXCEEDS_DELIVERED` | 422 Unprocessable Entity |
| `ERR_SUBSCRIPTION_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_CALL_NOT_DUE` | 422 Unprocessable Entity |
| `ERR_REVIEW_PERIOD_OPEN` | 422 Unprocessable Entity |
| `ERR_ROFR_WINDOW_EXPIRED` | 422 Unprocessable Entity |
| `ERR_PLACED_IN_SERVICE_DEADLINE_PASSED` | 422 Unprocessable Entity |