# Advertiser Policy Auction API — Product Requirements Document

## 1. Introduction

Online advertising earns trust only when three forces stay in balance: advertisers know who they are paying to reach users, users are protected from misleading or unsafe ads, and the platform prices attention fairly. This document specifies an ad-serving and policy-enforcement platform that operationalizes that balance across the full advertiser lifecycle — from the moment an unregistered business first announces itself, through identity verification and policy review, into the per-query auction that decides which ad wins a placement and at what price, and finally through billing, invalid-traffic remediation, and suspension appeals.

The platform treats money and trust as first-class state. Advertiser accounts carry a public identity disclosure once their legal business identity is verified; campaigns pace spend against daily budgets and monthly caps with deterministic overdelivery credits; auctions resolve a winner from bid and live quality signals while the advertiser-visible quality diagnostic stays frozen as a stable point-in-time reference. Billing follows a threshold ladder that escalates with proven payment behavior, and clicks later found to be invalid unwind every accumulator they ever touched — day, campaign, account, and invoice.

Operators act in five distinct roles: an anonymous caller may only register; the `Advertiser` manages its own account, campaigns, ads, and keywords; a `PolicyReviewer` renders human verdicts on restricted-category ads; a `BillingAdmin` closes months, applies payments, and flags invalid clicks; and a `PlatformAdmin` drives the logical clock, suspends accounts, decides verifications and appeals, and simulates auctions. All time-dependent behavior — appeal windows, campaign flights, invoice due dates, month closes — is driven by a logical clock rather than the wall clock, so every temporal rule in this document is reproducible and testable.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request except account registration carries two headers: `X-User-ID` and `X-User-Role`. A request missing either header, or presenting a role not among the declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) — this authentication check runs before every other validation on every authenticated endpoint. A request whose role is not permitted for the addressed endpoint, or whose identity fails the ownership rule below, is rejected with `ERR_FORBIDDEN` (HTTP 403); the authorization check runs immediately after authentication and before any path resolution.

Five roles exist, spelled exactly: `Anonymous`, `Advertiser`, `PolicyReviewer`, `BillingAdmin`, `PlatformAdmin`.

When `X-User-Role` is `Advertiser`, `X-User-ID` is the `id` of the acting `AdvertiserAccount`; ownership checks on any resource that references an `AdvertiserAccount` compare the resource's account foreign-key field (its `account_id`, resolved through the parent chain when the resource is nested) to `X-User-ID`, and a mismatch is `ERR_FORBIDDEN`. When `X-User-Role` is `Anonymous`, `X-User-ID` is an opaque caller identifier not tied to any persisted entity — the anonymous role exists only to open the registration door. When `X-User-Role` is `PolicyReviewer`, `X-User-ID` is an opaque operator identifier not compared to any entity's `id`. When `X-User-Role` is `BillingAdmin`, `X-User-ID` is likewise an opaque operator identifier with no entity backing. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier as well; the platform may record it but never matches it against a resource owner.

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

List endpoints accept two optional query parameters, `limit` and `offset`. `limit` defaults to 10, must be at least 1, and may be at most 100; `offset` defaults to 0. List responses order by `created_at` ascending. The `meta` object of every list response carries `limit`, `offset`, `total_count` (the full count of matching resources, not just the page), and `has_more` (true when more resources exist beyond the returned page).

### 2.4. Resource Identity and Common Properties

Every persisted resource carries an `id`, minted by the server as a UUID with no type prefix. Every resource in this system also carries `created_at` and `updated_at`, both ISO 8601 UTC timestamps with three fractional digits, and a `version` integer that starts at 1 and increments by 1 on every mutation of that resource. There are no exceptions: all twelve resource kinds — accounts, identity verifications, appeals, billing profiles, campaigns, ad groups, ads, keywords, policy reviews, auction events, daily spend records, and invoices — follow this common shape.

### 2.5. The Logical Clock

Time in this platform never comes from the wall clock. A single logical clock governs every date- or timestamp-sensitive rule in this document: appeal windows and cooling-off buffers, campaign flight windows, invoice due dates, month closes, and lazy state finalization. Before the clock is ever set, it reads exactly `2026-09-01T00:00:00Z`, and it never falls back to wall-clock time. A `PlatformAdmin` may advance it by calling the clock capability with a target instant `to_iso8601`; the response echoes the new reading as `current_utc`. Advancing the clock does not eagerly rewrite any resource; instead, the next access of a campaign, invoice, or suspended account re-evaluates the lazy transitions described in §2.6.

Dates and datetimes are distinct: campaign flights, spend days, and invoice due dates are calendar dates in `YYYY-MM-DD` form, while suspension timestamps, appeal decisions, and invoice periods are full ISO 8601 instants.

### 2.6. Lazy State Finalization

Three state transitions are triggered by the passage of logical time rather than by an explicit call, and all three are evaluated lazily — on any access of the affected entity, and additionally on the specific operations named below.

A campaign whose logical date has moved strictly past its `end_date` transitions from `DRAFT`, `ACTIVE`, or `PAUSED` to `ENDED`; this is evaluated on any access of the campaign and whenever auction eligibility is checked. An invoice in `ISSUED` or `PARTIALLY_PAID` whose logical date has moved strictly past its `due_date` transitions to `OVERDUE`; this is evaluated on any access of the invoice and on every payment attempt, and an `OVERDUE` invoice still accepts payments. An account in `SUSPENDED` whose logical clock has reached or passed thirty days after its `suspended_at` with no open appeal transitions to `SUSPENDED_FINAL`; this is evaluated on any access of the account and on every appeal creation attempt.

### 2.7. Nested Resource Resolution

Resources form a containment hierarchy: an account owns its verifications, appeals, billing profile, and campaigns; a campaign owns ad groups and daily spend records; an ad group owns ads and keywords; an ad owns policy reviews and auction events; a billing profile owns invoices. Whenever a URL addresses a nested resource, every path identifier is validated left to right — the outermost id first, then each nested id in order. The first id that fails to resolve yields `ERR_NOT_FOUND` (HTTP 404), and resolution stops there; a deeper identifier is never consulted once an ancestor is missing.

### 2.8. Optimistic Concurrency Control

Two write operations guard against stale views of their parent entity by requiring the client's last-observed version as a non-optional input. No other endpoint accepts a version field.

Updating a campaign requires `expected_campaign_version` carrying the client's last observed `version` of that campaign. Because budget and end-date writes are absolute sets that would each legitimately succeed under product semantics, a stale view of the campaign must be refused rather than applied: if the campaign's current `version` has advanced since the client last read it, the update is rejected with `ERR_STALE_VERSION` (HTTP 412).

Submitting an identity verification — which supersedes the account's previous `REJECTED` verification — requires `expected_account_version` matching the account's current `version`. If another writer has advanced the account's version since the client last observed it, the submission is rejected with `ERR_STALE_VERSION` (HTTP 412).

### 2.9. Monetary Quantities, Precision, and Score Integers

All money is integer cents: budgets, bids, charges, thresholds, credits, invoices, and payments are whole-cent values with no fractional part. Quality signals are integer scores: each ad carries three component scores on the 1-to-10 scale, and the derived quality score is an integer centi-score between 100 and 1000 with no rounding at any step. Wherever a formula requires a floor — the actual cost per click, the final monthly cap — the floor is applied exactly once at the position the rule states, never repeatedly and never rounded half-up instead.

### 2.10. Validation Ordering

When a request fails several checks, the error returned is the one whose check ranks highest in this fixed priority order — readers should treat the list as an ordered cascade, not a menu of independent rules:

1. Authentication — the headers-and-role check that yields `ERR_UNAUTHENTICATED` (401).
2. Authorization and ownership — role permission and `Advertiser` ownership, yielding `ERR_FORBIDDEN` (403).
3. Path existence — left-to-right id resolution, yielding `ERR_NOT_FOUND` (404).
4. Request-body shape — required fields present, types valid, enum values legal, integer ranges respected (the quality component scores between 1 and 10, `max_cpc_cents` strictly positive on a non-negative keyword), and a negative keyword forbidden from carrying `max_cpc_cents`, all yielding `ERR_VALIDATION` (400).
5. Optimistic concurrency — the `expected_campaign_version` / `expected_account_version` comparison, yielding `ERR_STALE_VERSION` (412). A stale version surfaces before any state-transition check, so a client learns it must re-read before it learns whether the transition would have been legal.
6. Transition legality — the target entity must be in a valid from-state, else `ERR_INVALID_STATE` (409).
7. Restricted-category certification — `ERR_RESTRICTED_CATEGORY_UNCERTIFIED` (422).
8. Uniqueness and conflict rules — the six conflict errors of §2.11, all (409).
9. Time-window rules — appeal window, appeal cooling-off, campaign flight window, and month closability, all (422).
10. Cross-entity state references — account state requirements on campaign activation, yielding `ERR_VERIFICATION_REQUIRED` or `ERR_ACCOUNT_SUSPENDED` (422).
11. Fiscal rules — budget minimum, date range, daily overdelivery, and overpayment, all (422).

### 2.11. Uniqueness and Conflict Rules

Six creation-time conflicts are each reported with their own error code. A second billing profile for an account that already has one is rejected with `ERR_BILLING_PROFILE_EXISTS` (409). A new identity verification while the account already has a verification in `SUBMITTED` — the pending window is occupied — is rejected with `ERR_DUPLICATE_VERIFICATION_PENDING` (409). A new appeal while an appeal of the same account sits in `SUBMITTED` or `UNDER_REVIEW` is rejected with `ERR_APPEAL_ALREADY_OPEN` (409). An ad whose headline matches another ad in the same ad group, compared case-insensitively, is rejected with `ERR_DUPLICATE_AD_HEADLINE` (409). A keyword whose combination of `normalized_text`, `match_type`, and `is_negative` already exists in the same ad group is rejected with `ERR_DUPLICATE_KEYWORD` (409). Finally, a negative keyword that would block the canonical query of another keyword — whether existing or newly created — in the same ad group is rejected with `ERR_NEGATIVE_KEYWORD_CONFLICT` (409).

### 2.12. Cascading State Propagation

Several operations mutate more than one entity, and every cascade is part of the contract. Suspending an account not only moves the account but pauses every one of its `ACTIVE` campaigns, stamping each with a suspension origin so the platform remembers why it stopped. Overturning the suspension through an appeal walks the cascade in reverse, resuming exactly the campaigns the suspension paused and no others. An ad's human disapproval decrements the eligible-ad count of its campaign, and when that count reaches zero on an `ACTIVE` campaign the campaign pauses itself with a no-eligible-ads origin; symmetrically, an ad becoming eligible on a campaign paused for lack of eligible ads lifts the campaign back to `ACTIVE` when the account itself is active. A voluntary content edit never triggers this auto-pause — only the disapproval path does. Every such transition refreshes the affected entity's `updated_at` and increments its `version` as a mutation.

## 3. Business Logic & Workflows

### 3.1. Account Onboarding and Identity Verification

An `Anonymous` caller opens the platform by registering an advertiser account, supplying a `business_name` and a `country_code` — the latter exactly two uppercase letters, the ISO 3166-1 alpha-2 country of business. The new account begins in `PENDING_VERIFICATION` with all lifetime counters at zero: `lifetime_valid_served_cents`, `lifetime_billed_cents`, `lifetime_overdelivery_credit_cents`, and `lifetime_invalid_click_credit_cents` each start at 0, and both `suspension_reason_code` and `suspended_at` are null.

Before the account can serve, the `Advertiser` submits an identity verification carrying the `legal_business_name` from the registration document, the government `registration_number`, a `document_type` of `BUSINESS_LICENSE`, `TAX_CERTIFICATE`, or `GOVERNMENT_ID`, and the advertiser's `disclosure_consent` to public identity disclosure. The verification record is born in `SUBMITTED`, and only one pending verification may occupy an account at a time. Each submission also records which rejected record it replaces: `supersedes_id` points at the previous `REJECTED` verification for the account, or stays null on the very first submission. Submitting a verification advances the account's `version` by 1 — the submission is a mutation of the account's dossier — which is why the submission call carries `expected_account_version` per §2.8. Verifications of an account can be listed back at any time.

A `PlatformAdmin` then decides the verification. Approval moves the verification from `SUBMITTED` to `APPROVED` and the account from `PENDING_VERIFICATION` to `ACTIVE` in the same act, stamping `verified_business_name` with the approved legal name and composing `disclosure_text` as the string "Ads by " followed by the verified business name — the public identity disclosure shown alongside the advertiser's ads. Both fields stay null until that approval lands. Rejection moves the verification from `SUBMITTED` to `REJECTED`, recording the reviewer's `rejection_reason` — the reason is required whenever the outcome is a rejection — while the account remains `PENDING_VERIFICATION`. The advertiser may then submit a fresh verification, which supersedes the rejected one under the OCC guard described above. Both `APPROVED` and `REJECTED` are terminal for a verification; deciding an already-decided record is `ERR_INVALID_STATE`.

An account read returns the full dossier, including the disclosure text and the four lifetime counters, and silently applies the lazy `SUSPENDED_FINAL` evaluation of §2.6.

### 3.2. Suspension and the Appeal Lifecycle

A `PlatformAdmin` may suspend an `ACTIVE` account for a policy violation, circumvention, or billing delinquency, supplying a `reason_code` of `POLICY_VIOLATION`, `CIRCUMVENTION`, or `BILLING_DELINQUENCY`. The account moves from `ACTIVE` to `SUSPENDED`; its `suspension_reason_code` is set to the supplied code, `suspended_at` is stamped from the logical clock, `upheld_appeal_count` resets to 0, and the account's `version` increments. The cascade of §2.12 then fires: every `ACTIVE` campaign of the account moves to `PAUSED` with `pause_origin` set to `SUSPENSION`, and each paused campaign recomputes its `eligible_ad_count` — the count itself is unchanged, because the ads keep their `ELIGIBLE` status, but they are auction-ineligible for as long as the campaign is paused.

The suspended advertiser may file one appeal at a time, supplying an `argument_text`. Filing is permitted only within a half-open window: the logical clock must be strictly before thirty days after `suspended_at`; an appeal filed at or after that boundary is rejected with `ERR_APPEAL_WINDOW_CLOSED` (422), and the lazy evaluation of §2.6 — which runs on the filing attempt itself — may already have moved the account to `SUSPENDED_FINAL`. If a previous appeal on the current suspension episode was decided `UPHELD`, the logical clock must also be at or after fourteen days past that decision's `decided_at`; filing earlier is rejected with `ERR_APPEAL_COOLDOWN` (422). Filing while another appeal is still open trips `ERR_APPEAL_ALREADY_OPEN` (409). A successful filing moves the account from `SUSPENDED` to `APPEAL_PENDING`, increments the account's `version`, creates the appeal in `SUBMITTED`, and immediately — as an automatic intake step — advances the appeal to `UNDER_REVIEW`. The appeal records `challenges_suspended_at`, a copy of the account's `suspended_at` it contests, and appeals of an account can be listed back.

A `PlatformAdmin` decides an appeal in `UNDER_REVIEW`, supplying an `outcome` of `UPHELD` or `OVERTURNED` and an optional `reviewer_note`. Either decision stamps `decided_at` from the logical clock and records the note; deciding an already-decided appeal is `ERR_INVALID_STATE`. An `UPHELD` decision moves the appeal to `UPHELD` and the account back from `APPEAL_PENDING` to `SUSPENDED`, incrementing `upheld_appeal_count` by 1 — and when that count reaches 2, the account lands in `SUSPENDED_FINAL` instead of `SUSPENDED`, closing the episode permanently (`SUSPENDED_FINAL` is terminal). An `OVERTURNED` decision moves the appeal to `OVERTURNED` and the account back to `ACTIVE`, clearing `suspension_reason_code` to null while retaining `suspended_at` for audit, and firing the resume cascade: every campaign paused with `pause_origin` `SUSPENSION` returns to `ACTIVE` with `pause_origin` reset to `NONE`, and each resumed campaign recomputes its `eligible_ad_count`.

### 3.3. Campaigns, Budgets, and Flight Windows

The `Advertiser` creates campaigns in `DRAFT` by supplying the owning `account_id`, a `name`, a `daily_budget_cents` of at least 100 cents, and an inclusive flight window from `start_date` to `end_date` in `YYYY-MM-DD` form. An end date earlier than the start date — whether at creation or on a later update — is rejected with `ERR_CAMPAIGN_DATE_RANGE_INVALID` (422); a daily budget below the 100-cent floor is `ERR_BUDGET_BELOW_MINIMUM` (422). Campaigns may be listed with optional `account_id` and `status` filters plus pagination, and any campaign access applies the lazy `ENDED` evaluation of §2.6.

Activation moves a campaign from `DRAFT` — or resumes it from `PAUSED` — to `ACTIVE` and resets `pause_origin` to `NONE`. Two gates guard activation, evaluated in the priority order of §2.10: the logical date must fall within the flight window from `start_date` through `end_date` inclusive, else `ERR_CAMPAIGN_OUTSIDE_FLIGHT_WINDOW` (422); and the owning account must be `ACTIVE` — activation against a `PENDING_VERIFICATION` account is rejected with `ERR_VERIFICATION_REQUIRED` (422), while a `SUSPENDED`, `APPEAL_PENDING`, or `SUSPENDED_FINAL` account yields `ERR_ACCOUNT_SUSPENDED` (422). The account-state check belongs to the cross-entity reference tier, which ranks after the flight-window check, so a campaign that is both out of window and on a suspended account reports the window error first.

Pausing moves an `ACTIVE` campaign to `PAUSED` with `pause_origin` set to `ADVERTISER`. Attempting to pause a campaign that is not `ACTIVE` — a `DRAFT` campaign, for instance — is `ERR_INVALID_STATE` (409), as is activating or pausing an `ENDED` one. A resume is symmetric to activation: the same two gates apply to a manual resume from `PAUSED`, and the appeal-overturned cascade of §3.2 performs a system resume restricted to campaigns whose `pause_origin` is `SUSPENSION`.

Budget and end-date changes go through the OCC-guarded update of §2.8: the request may carry a new `daily_budget_cents`, a new `end_date`, or both, alongside the mandatory `expected_campaign_version`. A successful update increments the campaign's `version` by 1, and a budget change takes effect for the current logical day — the day the write executes is already accounted at the new budget when the month is later closed (§3.5). Campaigns may also be created or updated only within the fiscal rules: the 100-cent floor and the date-range check apply at both create and update time.

Each campaign accumulates its own telemetry. `served_lifetime_cents` and `click_count_lifetime` are the running sums across all of the campaign's daily records; `current_month_served_cents` tracks served cents within the calendar month containing the current logical date; `overdelivery_credit_cents` accumulates every credit the campaign has ever been issued at month close; `eligible_ad_count` counts the campaign's ads currently in `ELIGIBLE`; and `monthly_cap_provisional_cents`, `last_closed_month_cap_cents`, and `last_closed_month_credit_cents` expose the budget diagnostics of §3.5. A campaign read returns all of these, including the provisional cap. The campaign's daily spend records — one per served day, each carrying its `campaign_id`, `spend_date`, `served_cents`, and `click_count` — can be listed back for reconciliation.

### 3.4. Ad Groups, Ads, and Policy Review

Within a campaign, the `Advertiser` creates ad groups by `name`, and each ad group holds the ads and keywords that share its targeting. Ad groups can be listed per campaign or fetched individually.

Creating an ad inside an ad group requires a `headline` (unique within the ad group, compared case-insensitively), a `final_url` landing page, a `category` of `GENERAL`, `ALCOHOL`, `GAMBLING`, `HEALTHCARE`, or `FINANCIAL`, and the three quality component scores `quality_ectr_score`, `quality_relevance_score`, and `quality_lp_score`, each an integer from 1 to 10. The advertiser may also assert `restricted_category_certified`, defaulting to false, claiming certification for restricted categories. An ad in one of the four restricted categories — `ALCOHOL`, `GAMBLING`, `HEALTHCARE`, or `FINANCIAL` — may only be created with `restricted_category_certified` true; otherwise creation fails with `ERR_RESTRICTED_CATEGORY_UNCERTIFIED` (422). A body-shape failure — a score outside the 1-to-10 range, a missing required field, an illegal enum value — surfaces first as `ERR_VALIDATION` (400) per the priority order of §2.10. A new ad is born in `DRAFT` with `review_round` at 0 and `quality_score_snapshot_centi` null.

Submitting an ad for review moves it from `DRAFT` to `UNDER_REVIEW`, increments `review_round` by 1, and creates a policy review whose `ad_id` binds it to the ad, whose `round` equals the new `review_round`, and whose `automated_verdict` is derived from the category: `CLEAN` for a `GENERAL` ad, `FLAGGED_RESTRICTED` for any restricted category. The automated pipeline completes immediately at creation: a `CLEAN` verdict finalizes the review as `AUTO_APPROVED` and moves the ad straight from `UNDER_REVIEW` to `ELIGIBLE`; a `FLAGGED_RESTRICTED` verdict moves the review from `PENDING_AUTO` to `NEEDS_HUMAN` and leaves the ad in `UNDER_REVIEW` until a human decides.

The first approval of an ad freezes `quality_score_snapshot_centi` at the live quality score computed at that moment (§3.6), and every transition into `ELIGIBLE` recomputes the campaign's `eligible_ad_count`. When that count rises above zero on a campaign paused with `pause_origin` `NO_ELIGIBLE_ADS` whose owning account is `ACTIVE`, the campaign bubbles back up to `ACTIVE` — the bubble-up resume of §2.12.

A `PolicyReviewer` decides a review in `NEEDS_HUMAN`, supplying an `outcome` of `HUMAN_APPROVED` or `HUMAN_VIOLATION` with an optional `reviewer_note` recorded on the review. Approval of a restricted-category ad requires `restricted_category_certified` to be true on the ad; an uncertified restricted ad is rejected with `ERR_RESTRICTED_CATEGORY_UNCERTIFIED` (422) — the certification gate is enforced at both creation and human approval, and only those two points. Approval finalizes the review as `HUMAN_APPROVED` and moves the ad to `ELIGIBLE` with the same snapshot-freeze, count recompute, and bubble-up effects. A violation finalizes the review as `HUMAN_VIOLATION` and moves the ad to `DISAPPROVED`, firing the two-link cascade: the campaign's `eligible_ad_count` is recomputed, and if the count has fallen to zero while the campaign is `ACTIVE`, the campaign pauses itself with `pause_origin` `NO_ELIGIBLE_ADS`. Deciding a review already in a terminal outcome is `ERR_INVALID_STATE`. Both the reviews of an ad and the ads of an ad group can be listed, and a single ad read exposes the frozen `quality_score_snapshot_centi` diagnostic.

Editing an ad accepts new values for `headline`, `final_url`, and the three quality scores. A change to `headline` or `final_url` on an ad in `ELIGIBLE` or `DISAPPROVED` returns it to `DRAFT`, requiring a fresh review cycle: the campaign's `eligible_ad_count` is recomputed immediately, but the no-eligible-ads auto-pause deliberately does not fire on this voluntary-edit path — it fires only on the disapproval path. Editing quality scores alone does not reset eligibility; the live score simply moves (§3.6) while the frozen snapshot stays put. Every ad edit increments the ad's `version`.

Keywords shape which queries an ad group may serve; each keyword is bound to its group through `ad_group_id`, just as every ad of the group is. Creating a keyword takes the raw `text`, a `match_type` of `EXACT`, `PHRASE`, or `BROAD`, an optional `is_negative` flag defaulting to false, and — for non-negative keywords only — a `max_cpc_cents` bid ceiling that must be strictly greater than zero. A negative keyword must not carry `max_cpc_cents`; supplying one is a body-shape failure. The server derives `normalized_text` from the raw text by lowercasing, trimming, and collapsing internal whitespace to single spaces; keywords are listed per ad group with an optional `is_negative` filter.

### 3.5. Billing Profiles, Invoices, and the Monthly Close

Each account has exactly one billing profile. The `Advertiser` creates it by supplying a `payment_method_type` of `CARD` or `INVOICING` and an optional `currency_code` defaulting to `USD` — all monetary semantics in this system are fixed in USD cents regardless of the code. The profile opens with `billing_threshold_cents` at 50000 and all accumulators — `unbilled_cost_cents`, `pending_credit_cents`, `outstanding_balance_cents` — at zero; `last_closed_month` is null until the first month close. A duplicate profile is `ERR_BILLING_PROFILE_EXISTS` (409). Fetching the profile through the account returns an array of zero or one profiles — empty before creation, one element after — while the direct profile read returns the profile itself, threshold ladder rung and accumulators included.

Invoices come in two kinds, recorded on the invoice's `kind` field. A `THRESHOLD` invoice is issued mid-flight whenever the billing threshold trips (§3.7). A `MONTHLY` invoice is issued at month close. Every invoice records its `billing_profile_id`, an exclusive lower bound `period_start` — the issue time of the previous invoice, or the profile's creation — and an inclusive upper bound `period_end` at its own issue time, a `due_date` exactly fourteen days after its issue date, an `amount_cents` of served cost in the period minus any credits applied at issuance, and the `overdelivery_credit_cents` and `invalid_click_credit_cents` applied to it, each defaulting to zero. `paid_cents` tracks the sum of payments applied, and the profile's `outstanding_balance_cents` is the sum of each invoice's amount minus its paid cents across all invoices, while the account-level `lifetime_billed_cents` is the sum of the current `amount_cents` over all of the profile's invoices. Invoices are listed per profile — a list access applies the lazy `OVERDUE` evaluation — and a `BillingAdmin` applies payments.

A payment supplies an `amount_cents` that must be strictly positive and no greater than the invoice's remaining balance; a payment that exceeds the remainder or is not positive is `ERR_OVERPAYMENT` (422). Payments against an invoice already in `PAID` are `ERR_INVOICE_NOT_PAYABLE` (409). A partial payment moves an `ISSUED` invoice to `PARTIALLY_PAID` and adds the amount to `paid_cents`; a payment equal to the remaining balance moves `ISSUED` directly to `PAID`, or `PARTIALLY_PAID` to `PAID`. An `OVERDUE` invoice accepts payments the same way, moving to `PARTIALLY_PAID` or `PAID` as the balance dictates. Full payment of a `THRESHOLD` invoice escalates the profile's `billing_threshold_cents` one rung up the ladder — from 50000 to 150000, then to 300000, then to 500000, where the terminal rung repeats and further full payments leave the threshold at 500000.

Month close is a `BillingAdmin` capability on the billing profile, naming a target `month` in `YYYY-MM` form. The month must be fully past — every day of it strictly before the current logical date — and strictly after the profile's `last_closed_month`; anything else is `ERR_MONTH_NOT_CLOSABLE` (422). Closing a month settles each of the account's campaigns and then bills the remainder. For every campaign, the final monthly cap is computed chronologically: take each day of the month, note the `daily_budget_cents` in effect at the end of that day — a budget update takes effect for the day it executes on — sum those per-day budgets across the month, multiply the sum by 304, divide by ten times the number of days in the month, and floor once at the very end to whole cents. The campaign's served total for the month is the sum of `served_cents` across its daily records dated within the month, and the overdelivery credit is the amount by which that served total exceeds the final cap, or zero when it does not. The credit accrues into the campaign's `overdelivery_credit_cents`; `last_closed_month_cap_cents` and `last_closed_month_credit_cents` are stamped with the final cap and the credit; and the account's `lifetime_overdelivery_credit_cents` grows by the same amount. The credit then enters the month's invoice: a `MONTHLY` invoice is issued for the month whenever the billed amount is greater than zero, with pending credits applied first — the amount applied is the smaller of `pending_credit_cents` and the amount being billed, and any unapplied remainder of `pending_credit_cents` persists for future issuances. The close stamps `last_closed_month` with the target month and reports the closed month, the new invoice's id, and the total overdelivery credit issued across campaigns.

By contrast, `monthly_cap_provisional_cents` — the forward-looking diagnostic exposed on every campaign read — uses only the campaign's current `daily_budget_cents`: the current budget multiplied by 304 and then integer-divided by 10. Because it ignores mid-month budget history, the provisional figure diverges from the final chronological cap whenever the budget changed during the month; the divergence is intentional, giving the advertiser a simple projection while settlement remains exact.

### 3.6. Quality Scoring and the Auction

The quality score combines an ad's three component scores into a single centi-score: fifty times `quality_ectr_score`, plus thirty times `quality_relevance_score`, plus twenty times `quality_lp_score`. With each component between 1 and 10, the score ranges exactly from 100 to 1000 as an integer — no rounding anywhere — and the familiar 1-to-10 display form is derived by dividing by 100. The score exists in two variants. The provisional variant is the advertiser-visible diagnostic: `quality_score_snapshot_centi` freezes the score at the ad's most recent transition into `ELIGIBLE` and does not move when component scores are edited afterward. The final variant is live: at auction time the score is recomputed from the ad's current component scores, so an ad whose scores changed since approval bids and prices on the new values even though its snapshot stays frozen.

An auction is simulated by a `PlatformAdmin` supplying a `query_text` and optional `clicked` and `is_invalid_click` flags, both defaulting to false. The query is normalized the same way keyword text is — lowercased, trimmed, internal whitespace collapsed to single spaces — and each ad group's keywords decide membership. A non-negative keyword matches the normalized query under its match type: an `EXACT` keyword matches when its `normalized_text` equals the normalized query; a `PHRASE` keyword matches when its `normalized_text` appears as a substring of the normalized query; a `BROAD` keyword matches when every whitespace-separated token of its `normalized_text` appears among the query's tokens. A negative keyword in the same ad group whose own match rule holds against the normalized query blocks every ad of that ad group from the auction.

An ad is a candidate only when every eligibility gate holds: its account is `ACTIVE`, its campaign is `ACTIVE` — which includes the lazy `ENDED` evaluation, so a campaign whose flight has ended is out — the logical date lies within the campaign's flight window, the ad itself is `ELIGIBLE`, and at least one non-negative keyword of its ad group matches the query. The ad's bid is the highest `max_cpc_cents` among its matching keywords; ties between matching keywords break in favor of the keyword created earliest. The ad's rank is its bid in cents multiplied by its live quality centi-score, and any ad whose rank falls below the reserve of 20000 is excluded. The winner is the highest-ranked surviving ad, with ties broken by earliest ad creation; the runner-up is the next-highest surviving rank, or null when no second ad survives. When no ad survives at all, the auction is rejected with `ERR_NO_ELIGIBLE_AD` (422).

The recorded auction event captures `occurred_date` from the logical clock, the `winner_ad_id`, the `winner_campaign_id` — an informational snapshot resolved through the winning ad's ad group — the `winner_ad_rank`, the `runner_up_ad_rank` (null when there was no runner-up), and `quality_score_final_centi`, the winner's live score at auction time. The event's `charged_cents` is the actual cost per click when the click is real and currently valid, and zero otherwise; the winner's own campaign and account accumulators update only on a valid click. Single auction events can be fetched back, and an ad's won auctions can be listed.

### 3.7. Click Pricing, Pacing, and Invalid-Traffic Remediation

When a winning auction carries a click, the price follows a pinned three-step order whenever a runner-up exists. First, divide the runner-up's rank by the winner's live quality score — an exact rational division — and floor the result to integer cents. Second, add exactly one cent to that floored base. Third, cap the price at the winner's bid: the actual cost per click is the smaller of the winner's bid and the incremented base. When no runner-up exists, the actual cost per click is simply the smaller of the winner's bid and the reserve price of 5 cents. The floor happens before the increment, and the cap applies last — reordering any of the three steps changes the price and is non-conformant.

Pacing guards the click before it bills. The platform keeps one daily spend record per campaign per logical day, created lazily on first use. A click is allowed only when the campaign-day's `served_cents` plus the new `charged_cents` stays at or below twice the campaign's `daily_budget_cents` — the boundary is inclusive, so landing exactly at double the budget is permitted. A click that would push the day past that limit is rejected with `ERR_DAILY_OVERDELIVERY_LIMIT` (422): the auction event is still recorded, but with no-charge semantics, and neither the day, the campaign, nor the billing profile accumulates anything for it. The inclusive daily boundary is what the monthly overdelivery credit of §3.5 exists to correct: a campaign may serve up to double its budget on individual days, but never pays for more than the chronological monthly cap at settlement.

Each valid, charged click moves money through a fixed pipeline. The campaign-day's `served_cents` grows by the charge and its `click_count` by one; the campaign's `served_lifetime_cents` and `click_count_lifetime` grow likewise; the account's `lifetime_valid_served_cents` grows by the charge. The profile's `unbilled_cost_cents` then grows by the charge, and when the unbilled total reaches or exceeds the current `billing_threshold_cents` — the boundary is inclusive — a `THRESHOLD` invoice is issued immediately for the unbilled amount minus any pending credits applied, with `due_date` fourteen days out, and `unbilled_cost_cents` resets to zero. At every invoice issuance, threshold or monthly, pending credits apply first: the applied amount is the smaller of `pending_credit_cents` and the unbilled amount, and any remainder of `pending_credit_cents` persists.

Remediation runs in reverse. A `BillingAdmin` may flag an auction event's click as invalid traffic, but only when the event was actually clicked — flagging an unclicked event is `ERR_AUCTION_NOT_CLICKED` (409) — and only when the click is not already flagged — a second flag is `ERR_CLICK_ALREADY_INVALID` (409). Flagging sets `is_invalid_click` true, recomputes the event's `charged_cents` to zero, and unwinds every accumulator the click ever touched by exactly the original charge: the chronological campaign-day record loses the charge from `served_cents` and one from `click_count`; the campaign's `served_lifetime_cents` and `click_count_lifetime` unwind identically; the account's `lifetime_valid_served_cents` decreases while `lifetime_invalid_click_credit_cents` grows by the charge. Where the credit lands depends on whether the click was already invoiced. If it was not, `unbilled_cost_cents` simply decreases by the charge. If it was, the credit applies to the profile's oldest unpaid invoice by creation order: that invoice's `amount_cents` decreases and its `invalid_click_credit_cents` grows by the applied amount, never pushing the amount below what has already been paid; any remainder beyond what could be applied flows into `pending_credit_cents`, where it awaits the next invoice issuance.

## 4. Endpoint Definitions

All endpoints share the envelope and error formats of §2.2. Operations that create a new resource respond with 201 Created; operations that modify an existing resource, transition state, or run a capability respond with 200 OK; reads respond with 200 OK. Request and response bodies for each endpoint are defined by the workflows in §3 — the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
|--------|------|-------------|--------------------|
| POST | `/_clock/set_current_utc` | Set the logical clock (test-driving) | `PlatformAdmin` |
| POST | `/advertiser-accounts` | Register an advertiser account | `Anonymous` |
| GET | `/advertiser-accounts/{account_id}` | Get an account incl. disclosure and lifetime counters | `Advertiser`, `PlatformAdmin`, `BillingAdmin`, `PolicyReviewer` |
| POST | `/advertiser-accounts/{account_id}/suspend` | Suspend an account | `PlatformAdmin` |
| POST | `/advertiser-accounts/{id}/identity-verifications` | Submit an identity verification (supersedes a rejected one) | `Advertiser` |
| GET | `/advertiser-accounts/{id}/identity-verifications` | List verifications of an account | `Advertiser`, `PlatformAdmin` |
| POST | `/identity-verifications/{verification_id}/decide` | Approve or reject a verification | `PlatformAdmin` |
| POST | `/advertiser-accounts/{id}/appeals` | File an appeal against the current suspension | `Advertiser` |
| GET | `/advertiser-accounts/{id}/appeals` | List appeals of an account | `Advertiser`, `PlatformAdmin` |
| POST | `/appeals/{appeal_id}/decide` | Decide an appeal (`UPHELD` or `OVERTURNED`) | `PlatformAdmin` |
| POST | `/advertiser-accounts/{id}/billing-profile` | Create the account's single billing profile | `Advertiser` |
| GET | `/advertiser-accounts/{id}/billing-profile` | Get the account's billing profile (array of 0..1) | `Advertiser`, `BillingAdmin` |
| GET | `/billing-profiles/{billing_profile_id}` | Get a billing profile with threshold and accumulators | `Advertiser`, `BillingAdmin` |
| POST | `/billing-profiles/{billing_profile_id}/close-month` | Close a fully past month: final caps, credits, monthly invoice | `BillingAdmin` |
| GET | `/billing-profiles/{id}/invoices` | List invoices of a profile | `Advertiser`, `BillingAdmin` |
| POST | `/invoices/{invoice_id}/payments` | Apply a payment to an invoice | `BillingAdmin` |
| POST | `/campaigns` | Create a campaign | `Advertiser` |
| GET | `/campaigns` | List campaigns with optional filters | `Advertiser`, `PlatformAdmin` |
| GET | `/campaigns/{campaign_id}` | Get a campaign with served/credit diagnostics | `Advertiser`, `PlatformAdmin` |
| PUT | `/campaigns/{campaign_id}` | Update budget and/or end date (OCC-guarded) | `Advertiser` |
| POST | `/campaigns/{campaign_id}/activate` | Activate or resume a campaign | `Advertiser` |
| POST | `/campaigns/{campaign_id}/pause` | Pause an active campaign | `Advertiser` |
| GET | `/campaigns/{id}/daily-spend-records` | List daily spend records of a campaign | `Advertiser`, `PlatformAdmin` |
| POST | `/campaigns/{id}/ad-groups` | Create an ad group | `Advertiser` |
| GET | `/campaigns/{id}/ad-groups` | List ad groups of a campaign | `Advertiser`, `PlatformAdmin` |
| GET | `/ad-groups/{ad_group_id}` | Get an ad group | `Advertiser`, `PlatformAdmin` |
| POST | `/ad-groups/{id}/ads` | Create an ad | `Advertiser` |
| GET | `/ad-groups/{id}/ads` | List ads of an ad group | `Advertiser`, `PolicyReviewer`, `PlatformAdmin` |
| GET | `/ads/{ad_id}` | Get an ad with its quality snapshot | `Advertiser`, `PolicyReviewer`, `PlatformAdmin` |
| PUT | `/ads/{ad_id}` | Edit ad fields; content changes require re-review | `Advertiser` |
| POST | `/ads/{ad_id}/submit-review` | Submit an ad for policy review | `Advertiser` |
| GET | `/ads/{id}/policy-reviews` | List policy reviews of an ad | `Advertiser`, `PolicyReviewer`, `PlatformAdmin` |
| GET | `/ads/{id}/auction-events` | List auction events won by an ad | `Advertiser`, `PlatformAdmin` |
| POST | `/policy-reviews/{review_id}/decide` | Human decision on a review awaiting one | `PolicyReviewer` |
| POST | `/ad-groups/{id}/keywords` | Create a keyword or negative keyword | `Advertiser` |
| GET | `/ad-groups/{id}/keywords` | List keywords of an ad group | `Advertiser`, `PlatformAdmin` |
| POST | `/auctions` | Simulate an auction for a query | `PlatformAdmin` |
| GET | `/auction-events/{auction_event_id}` | Get an auction event with ranks and charge | `PlatformAdmin`, `Advertiser` |
| POST | `/auction-events/{auction_event_id}/flag-invalid` | Retroactively flag the click as invalid traffic | `BillingAdmin` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|----------|------------------|
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_VERIFICATION_REQUIRED` | 422 Unprocessable Entity |
| `ERR_ACCOUNT_SUSPENDED` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_VERIFICATION_PENDING` | 409 Conflict |
| `ERR_BILLING_PROFILE_EXISTS` | 409 Conflict |
| `ERR_APPEAL_ALREADY_OPEN` | 409 Conflict |
| `ERR_APPEAL_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_APPEAL_COOLDOWN` | 422 Unprocessable Entity |
| `ERR_RESTRICTED_CATEGORY_UNCERTIFIED` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_AD_HEADLINE` | 409 Conflict |
| `ERR_DUPLICATE_KEYWORD` | 409 Conflict |
| `ERR_NEGATIVE_KEYWORD_CONFLICT` | 409 Conflict |
| `ERR_BUDGET_BELOW_MINIMUM` | 422 Unprocessable Entity |
| `ERR_CAMPAIGN_DATE_RANGE_INVALID` | 422 Unprocessable Entity |
| `ERR_CAMPAIGN_OUTSIDE_FLIGHT_WINDOW` | 422 Unprocessable Entity |
| `ERR_DAILY_OVERDELIVERY_LIMIT` | 422 Unprocessable Entity |
| `ERR_NO_ELIGIBLE_AD` | 422 Unprocessable Entity |
| `ERR_OVERPAYMENT` | 422 Unprocessable Entity |
| `ERR_INVOICE_NOT_PAYABLE` | 409 Conflict |
| `ERR_MONTH_NOT_CLOSABLE` | 422 Unprocessable Entity |
| `ERR_AUCTION_NOT_CLICKED` | 409 Conflict |
| `ERR_CLICK_ALREADY_INVALID` | 409 Conflict |
