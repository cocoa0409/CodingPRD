# Interagency Toll Reciprocity API — Product Requirements Document

## 1. Introduction

Across the E-ZPass Group's member agencies, a driver with a transponder issued by one agency routinely crosses the plazas of several others, and every such trip creates two obligations at once: the motorist must be billed accurately at the away agency's rate, and the away agency must later be made whole by the home agency that collected the money. This document specifies an API that manages that full reciprocity loop — transponder account issuance at a home agency, trip posting against agency-specific rate schedules with discount plans and vehicle classification, image-based billing when a tag cannot be read, violation notice issuance and escalation to registration-hold referrals, dispute handling for classification errors, misread plates, and rental vehicles, and the nightly settlement files through which agencies reconcile what they owe one another.

The system is built around a logical clock rather than wall-clock time, because escalation timelines, dispute windows, discount caps, and plate-data agreement validity are all defined in terms of calendar days. An operator-driven day-advancement capability sweeps the system for work that only becomes due with the passage of time — escalation of long-unpaid violations, automatic rejection of stale disputes, and the reset of per-day and per-month usage counters. Optimistic concurrency control protects account balances against stale writers, since a toll posting, an automatic replenishment, a dispute credit, and a manual adjustment can all legitimately move the same balance.

## 2. Global Specifications & System-Wide Principles

This section defines the cross-cutting rules that apply uniformly to the entire API, mounted under `/toll`.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the operational capacity in which they act. A request with either header missing or malformed is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). If the named role is not permitted to call the endpoint, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403). These two checks are evaluated before any resource lookup on every endpoint.

The system recognizes five roles, spelled exactly as follows:

- `SettlementOfficer` — the interagency settlement operator. Registers and suspends agencies, runs settlement files, administers plate data agreements, and drives the logical clock.
- `AgencyOperations` — a single agency's back office. Owns rate schedules, discount plans, account issuance, transponder issuance, toll posting, voids, reinstatements, and balance adjustments.
- `AccountHolder` — the account owner. Closes their own account, reports their own transponders lost or found, retires transponders, files and withdraws their own disputes, and pays violations.
- `ViolationsOfficer` — violation and dispute processing. Issues notices, dismisses violations, reviews and adjudicates disputes, and can accept violation payments.
- `PlateLookupAgent` — runs license plate lookups against partner agencies and resolves image bills.

When `X-User-Role` is `AccountHolder`, `X-User-ID` is the `id` of the acting `Account`; ownership checks on any resource that references an `Account` compare the resource's foreign-key field to `X-User-ID`, and the holder may act only on their own account, their own transponders, their own disputes, and violations belonging to their account. When `X-User-Role` is `SettlementOfficer`, `AgencyOperations`, `ViolationsOfficer`, or `PlateLookupAgent`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it but does not compare it to any entity's `id`.

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

List endpoints paginate through two query parameters. The `limit` parameter caps the number of items returned per page; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter says how many items to skip and defaults to 0. A non-integer `limit` or `offset`, a `limit` outside the 1–100 range, or a negative `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order, with ties broken by insertion order. List endpoints additionally honor equality-filter query parameters naming resource fields (for example `status`, `agency_id`, `account_id`, `plaza_code`, `vehicle_class`, and the foreign keys of the listed resource); filters narrow the result set before sorting and pagination. The `meta` object of every list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every primary resource carries a system-minted `id` formatted as a UUID with no type prefix, a `created_at` timestamp, an `updated_at` timestamp, and an integer `version` starting at 1. Both timestamps are ISO 8601 UTC with three fractional digits of precision, stamped from the server's wall clock rather than the logical clock — the logical clock of §2.6 governs only business-day logic (epoch days, windows, sweeps), never `created_at`/`updated_at`. Any mutation of a resource refreshes its `updated_at` and increments its `version` by exactly one, including mutations performed as side effects of operations on other resources (for example, the `Account` whose `balance_cents` moves when one of its tolls posts). The single exception is the day-advancement sweep's counter resets (`discount_used_today_cents` and `trips_this_month`), which rewrite those counters in place without refreshing `updated_at` or bumping `version`; likewise, an automatic replenishment that fires as part of a debit shares the debit's single version bump rather than adding a second one.

One entity deviates from this convention: `TollTransaction` carries only `id` and `created_at`. It has no `updated_at` and no `version`; its lifecycle is append-and-transition, and settlement sweeps reference it without an optimistic-concurrency token.

### 2.5. Monetary Values and Precision

All money in the system is integer cents — never fractional units, never floating point. Wherever a multiplication step produces a fraction of a cent (multiplying a base rate by an axle multiplier, applying a peak multiplier, computing a discount percentage, or computing a reciprocity fee), that step is rounded half-up to whole cents immediately, before the value feeds the next step. Rounding is per multiplication step, never deferred to the end of a formula.

### 2.6. The Logical Clock and Epoch Days

The server maintains a logical clock, initialized to `2026-09-01T00:00:00Z` before any clock call, and it never falls back to wall-clock time. A `SettlementOfficer` may set the clock to an arbitrary instant by supplying `to_iso8601`, and may advance the calendar by supplying a `days` count, which must be a non-negative integer — a negative `days` is rejected with `ERR_INVALID_REQUEST`. Setting the clock also immediately re-evaluates plate data agreement expiry against the new instant, exactly as the day-advancement sweep does. The clock-setting operation returns the current instant as `current_utc`, and the day-advance operation returns the new counter as `epoch_day`. Advancing the day counter is the system's ops-run checkpoint: each advancement increments the epoch day index and triggers a sweep that re-evaluates plate data agreement expiry, runs the violation escalation pipeline, auto-rejects stale disputes, resets every account's `discount_used_today_cents` as the UTC day rolls over, and resets every account's `trips_this_month` when the advancement crosses a UTC month boundary. All day-indexed fields (`first_notice_day`, `current_notice_day`, `filed_day`, `settlement_day`) are expressed in this epoch-day numbering, and time-window checks in the business logic are comparisons against the current logical time. Epoch-day numbering begins at 0 on the initial clock instant (`2026-09-01T00:00:00Z`); whenever a rule needs the epoch day of an arbitrary timestamp (for example, the trip timestamp in the dispute-window check of §3.8), it is the whole number of calendar days elapsed since that initial instant — the initial instant itself is day 0 — so partial days never count and the comparison is day-granular rather than an exact 90×24-hour span.

### 2.7. Optimistic Concurrency Control

Two write endpoints on accounts are guarded by optimistic concurrency control, and both use the same field name and rejection.

Recording a replenishment against an account — whether the operator is recording a manual top-up or simulating an automatic one — may carry `expected_account_version`, the account's `version` as last observed by the caller. If the field is supplied and does not match the account's current `version`, the write is rejected with `ERR_STALE_VERSION` (HTTP 412); if the field is omitted, the write proceeds without a concurrency check. This is the serialization point that prevents a double top-up when an automatic replenishment triggered by a toll posting has already landed and advanced the account's version since the caller read it.

Posting a manual balance adjustment accepts the same optional `expected_account_version`; a supplied value that does not match the account's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412), because any intervening toll debit, dispute credit, or replenishment legitimately moved the balance and invalidated the stale writer's basis.

Endpoints other than these two do not take a version field.

### 2.8. Nested Resource Retrieval and Validation Order

Endpoints whose paths nest resources (for example, a rate schedule created beneath an agency, or a transponder beneath an account) validate path identifiers strictly left to right: each identifier must name an existing resource before the next is examined, and the first non-existent identifier yields `ERR_NOT_FOUND` (HTTP 404). Across all endpoints, validation runs in a fixed order. Header presence and well-formedness are checked first (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`), then role authorization (`ERR_FORBIDDEN_FOR_ROLE`), then path resource existence (`ERR_NOT_FOUND`), then whether the target resource's current state permits the requested transition (`ERR_INVALID_STATE_TRANSITION`). Only after those generic checks do business rules run, in the following order: account, transponder, and agency operational safety before a toll debit; rate-schedule existence and discount-plan applicability; plate-lookup agreement availability; notice-spacing timelines; idempotency and uniqueness constraints; settlement and suspension bookkeeping constraints; fiscal floor checks such as the reinstatement balance threshold and positive amounts; and finally general request-body well-formedness (`ERR_INVALID_REQUEST`).

### 2.9. Hierarchical Consistency and Cascading Side Effects

State changes propagate along the ownership hierarchy. Closing an account retires every transponder on it and pays out the remaining balance. A violation reaching `HOLD_REFERRED` with money still owed suspends the owning account. Suspending an account makes every active transponder on it ineligible for new toll postings. Suspending an agency blocks new toll postings at that agency's plazas. A dispute upheld on a billed image bill simultaneously credits the original account, re-marks the image bill, spawns a fresh image bill for the corrected party, and dismisses any linked violation. Each of these cascades refreshes `updated_at` and bumps `version` on every resource it touches, so a client holding a stale account version after any cascade will fail the OCC checks of §2.7.

### 2.10. Idempotency and Uniqueness

Three uniqueness constraints are enforced globally. A toll trip submission carries a client-supplied `idempotency_key`; a duplicate tuple of away agency, plaza, trip timestamp, tag or plate, and key is rejected with `ERR_DUPLICATE_TRANSACTION`. A `tag_number` is unique across all agencies and all accounts; re-issuing a tag serial already in the system is rejected with `ERR_DUPLICATE_TAG`. A `plan_code` is unique within its issuing agency; reusing one yields `ERR_DUPLICATE_PLAN_CODE`.

## 3. Business Logic & Workflows

### 3.1. Registering Agencies and Their Rate Schedules

A `SettlementOfficer` onboards a member agency by providing its `agency_code` (a short identifier such as NYTA, NJTA, or ISTHA), its display `name`, its two-letter `home_state`, and its `reciprocity_fee_bps` — the fee, expressed in basis points, that this agency charges a home agency when it settles tolls collected on this agency's facilities (a value of 150 means one and a half percent). The `settlement_currency` may be supplied and defaults to USD; `reciprocity_fee_bps` must be an integer. A newly registered agency starts in `ACTIVE` status.

An `AgencyOperations` operator then publishes the agency's rate schedules. Each schedule belongs to its owning agency via `agency_id` and names a `plaza_code`, a `vehicle_class` drawn from `CLASS_2` (passenger two-axle), `CLASS_5` (five-axle truck), or `CLASS_7` (seven-or-more-axle oversized), an off-peak `base_rate_cents`, an `axle_multiplier`, an optional `peak_multiplier` defaulting to 1.0, an optional `image_fee_cents` defaulting to 100 cents, and a validity window from `effective_from` to `effective_to`. The window is half-open: a schedule is usable at `effective_from` and stops being usable at `effective_to`, and `effective_to` must be strictly after `effective_from` — a non-conforming window is rejected with `ERR_INVALID_REQUEST`. Schedules are created in `ACTIVE` status; if the requested window overlaps the window of any existing `ACTIVE` schedule for the same agency, plaza, and class, creation is rejected with `ERR_SCHEDULE_OVERLAP`. The `image_fee_cents` is an administrative surcharge added to image-based tolls and is never discounted.

A `SettlementOfficer` may suspend an agency, moving it from `ACTIVE` to `SUSPENDED`; suspending an agency in any other status is rejected with `ERR_INVALID_STATE_TRANSITION`. Suspension is refused with `ERR_AGENCY_HAS_PENDING_SETTLEMENT` whenever any settlement file naming this agency on either side — as collector or as facility provider — is sitting in `GENERATED` or `TRANSMITTED` status. While suspended, no new toll transaction may be posted at the agency's plazas: such attempts fail with `ERR_AGENCY_SUSPENDED`. A suspended agency may be reactivated, returning it to `ACTIVE`; reactivation has no further preconditions, and reactivating an agency that is not `SUSPENDED` is rejected with `ERR_INVALID_STATE_TRANSITION`.

### 3.2. Discount Plans and Account Issuance

Before accounts are opened, `AgencyOperations` defines the agency's discount plans. A plan is identified within its agency by `plan_code` and carries a `discount_pct` — a fractional discount (0.20 means twenty percent) that applies to the toll portion of a fare only, never to any fee — plus a `daily_discount_cap_cents` ceiling on the total discount one account may receive per UTC calendar day across all trips on the plan, where zero means uncapped. The `applies_to_agency_codes` list names the away agencies whose tolls the plan discounts; an empty list means the plan discounts only the home agency's own tolls. An optional `min_trips_per_month`, defaulting to zero, gates the discount on loyalty: when it is greater than zero, the discount applies only once the account has accumulated at least that many posted transponder trips in the current UTC month. Plans are created `ACTIVE`, and a reused `plan_code` within the same agency is rejected with `ERR_DUPLICATE_PLAN_CODE` — the uniqueness check considers every plan ever created for the agency, regardless of its status, so even a `RETIRED` plan's code cannot be reused.

Opening an account requires the `home_agency_id` of the issuing agency, the holder's `holder_name` and `holder_email`, and the `discount_plan_id` of the plan the holder enrolls in. A `home_agency_id` naming no existing agency is rejected with `ERR_NOT_FOUND`. The plan must belong to the account's home agency and must not be `RETIRED`, and it must name an existing plan; otherwise account creation fails with `ERR_PLAN_NOT_APPLICABLE`. At fare time, by contrast, an inapplicable or non-`ACTIVE` plan does not fail the posting — it simply grants no discount. Optional `low_balance_threshold_cents` (default 1000) and `replenishment_amount_cents` (default 2500) tune the account's auto-replenishment behavior, and an optional `opening_balance_cents` seeds `balance_cents` (default zero). New accounts start `ACTIVE` with `replenishment_fail_count`, `discount_used_today_cents`, and `trips_this_month` all at zero, and `suspended_reason` null.

### 3.3. Issuing and Managing Transponders

`AgencyOperations` issues a transponder on an account by supplying the physical `tag_number`, the declared `vehicle_class` of the vehicle the tag is mounted on (one of `CLASS_2`, `CLASS_5`, `CLASS_7`), and the primary vehicle's `plate_number` and `plate_state`. The tag serial must be unique across the entire network — reusing one is rejected with `ERR_DUPLICATE_TAG` — and the new transponder starts `ACTIVE`. Issuance performs no check on the owning account's status; a transponder may be issued on a suspended account.

The account holder manages the tag lifecycle. Reporting a tag lost moves it from `ACTIVE` to `REPORTED_LOST`; from that point on, trips whose `trip_timestamp` falls after the report and present this tag are routed to the image-billing path instead of debiting the account directly, protecting the holder from a stolen tag. Reporting the tag found moves it back to `ACTIVE`. Retiring a tag moves it from `ACTIVE` to `RETIRED`, a terminal state; the same transition happens automatically to every transponder on an account when that account is closed. Any attempt to bill against a transponder that is `REPORTED_LOST` or `RETIRED` (outside the lost-tag rerouting rule) fails with `ERR_TRANSPONDER_NOT_ACTIVE`.

### 3.4. Posting Toll Trips: Transponder Reads and Image Fallback

Trip posting is the operational heart of the system, performed by `AgencyOperations` with a payload naming the `away_agency_id` whose facility recorded the trip, the `plaza_code`, the UTC `trip_timestamp`, an `is_peak` flag saying whether the trip falls inside the plaza's peak window, and the client's `idempotency_key`. The vehicle is identified either by `tag_number` or by `plate_number` and `plate_state`. If the tag resolves to an `ACTIVE` transponder, the trip is priced as a transponder toll with `detection_method` `TRANSPONDER`; otherwise it is priced as an image toll with `detection_method` `IMAGE`, and an `ImageBill` is created in `PENDING_LOOKUP` alongside the transaction. A tag that names no transponder at all falls to the image path only when `plate_number` and `plate_state` are also supplied; a submission whose tag is unknown and that omits the plate identity is rejected with `ERR_INVALID_REQUEST`. A lost-tag reroute images the tag's registered plate (taken from the transponder record, not the request) and — because the transponder is resolved, merely not billable — prices the image leg at the tag's declared vehicle class rather than the default. Either way, the transaction itself starts in `POSTED`, with `transponder_id` set for tag reads and null for image trips, `account_id` set for transponder reads and null for image trips, `away_agency_id` recording the facility agency, and `settlement_file_id` null until a settlement sweep claims it.

Several safety checks gate every posting, evaluated after the generic validation order of §2.8: on the transponder path the billed account must not be `SUSPENDED` (`ERR_ACCOUNT_SUSPENDED`) or `CLOSED` (`ERR_ACCOUNT_CLOSED`) — the image path debits no account at posting time and so performs no account-status check; a transponder-resolved tag must be `ACTIVE` (`ERR_TRANSPONDER_NOT_ACTIVE`); and the away agency must not be `SUSPENDED` (`ERR_AGENCY_SUSPENDED`). A duplicate submission with the same away agency, plaza, trip timestamp, tag or plate, and `idempotency_key` is rejected with `ERR_DUPLICATE_TRANSACTION`.

Fare calculation proceeds as follows. The system locates the `ACTIVE` rate schedule of the away agency whose `plaza_code` matches, whose `vehicle_class` matches the class being billed, and whose half-open window from `effective_from` to `effective_to` contains the `trip_timestamp`; if no such schedule exists, the posting fails with `ERR_RATE_NOT_FOUND`. The selected schedule is recorded on the transaction as its `rate_schedule_id`. The billed class, recorded as `billed_vehicle_class`, equals the transponder's declared class for tag reads — unless a later classification dispute reclasses it. An image trip priced without a resolved transponder has no declared class to consult; such trips are billed at the default `CLASS_2`, and the rate-schedule lookup for the image leg uses that class. The base computation multiplies `base_rate_cents` by `axle_multiplier` and rounds the product half-up to whole cents; if `is_peak` is true, that axle component is then multiplied by `peak_multiplier` and again rounded half-up to whole cents. Call this pre-fee amount the gross before surcharges.

For a transponder trip, `gross_amount_cents` is exactly that gross. The enrolled discount plan is consulted: the plan must be `ACTIVE`, and the away agency must appear in the plan's `applies_to_agency_codes` (or the plan is home-only and the trip is at the home agency). The plan is eligible only when its `min_trips_per_month` is zero or the account's `trips_this_month` has already reached that floor. When eligible, the raw discount is the gross multiplied by `discount_pct`, rounded half-up to whole cents. If the plan's `daily_discount_cap_cents` is greater than zero, the granted discount is the smaller of the raw discount and the remaining cap, where the remaining cap is the cap minus the account's `discount_used_today_cents`, floored at zero; otherwise the raw discount stands. The granted amount is recorded as `discount_amount_cents`, added to `discount_used_today_cents`, and the account's `trips_this_month` increments by one. Each trip draws down the remaining cap as it posts, in the order postings arrive at the API; the cap is never redistributed retroactively, so an earlier trip keeps its full discount even if a later trip is voided — voiding does not restore `discount_used_today_cents`.

For an image trip, no discount ever applies: `discount_amount_cents` is zero, and `gross_amount_cents` is the pre-fee gross plus the schedule's `image_fee_cents`. In both variants, `charged_amount_cents` is the gross minus the discount, and that is the amount the account is actually debited.

Posting a transponder trip debits `charged_amount_cents` from the account's `balance_cents` and bumps the account's `version` by one. Immediately after any such debit, the replenishment decision of §3.5 runs; if it fires, it shares that single version bump.

`AgencyOperations` may void a transaction. Voiding a transaction that is already `SETTLED` — or already claimed by a settlement file — is rejected with `ERR_TRANSACTION_ALREADY_SETTLED`; voiding from any other non-`POSTED` status (for example, voiding twice) is rejected with `ERR_INVALID_STATE_TRANSITION`. A successful void moves the transaction to `VOIDED` and credits the account back `charged_amount_cents`; being a credit rather than a debit, the void does not trigger the replenishment decision.

### 3.5. Replenishment, Low-Balance Handling, and the Account Lifecycle

After every debit to an account's `balance_cents` — from a toll posting or from an image bill resolving against the account — the replenishment decision is evaluated. If the account is `ACTIVE` and its balance has fallen strictly below its `low_balance_threshold_cents`, an automatic replenishment of `replenishment_amount_cents` is attempted. The boundary is strict: a balance exactly equal to the threshold does not trigger a top-up. The automatic attempt always succeeds — payment failure is only ever exercised through the explicitly recorded replenishments below — so on the automatic path the balance is always credited the replenishment amount and `replenishment_fail_count` resets to zero; on payment failure (the recorded path) the count increments by one. When `replenishment_fail_count` reaches three consecutive failures, the account transitions from `ACTIVE` to `SUSPENDED` with `suspended_reason` set to `REPLENISHMENT_FAILED`, and every `ACTIVE` transponder on the account becomes ineligible for new toll postings — subsequent postings fail with `ERR_ACCOUNT_SUSPENDED`.

A replenishment may also be recorded explicitly by `AgencyOperations` or by the `AccountHolder` on their own account. The request carries the `amount_cents`, an `outcome` spelled exactly `SUCCEEDED` or `FAILED` (any other value is rejected with `ERR_INVALID_REQUEST`), and optionally the OCC token `expected_account_version` per §2.7. A recorded success adds `amount_cents` to `balance_cents` and resets `replenishment_fail_count` to zero; a recorded failure increments `replenishment_fail_count`, and at three the account suspends exactly as in the automatic path — the fail-count suspension fires only while the account is `ACTIVE`. Either way the account's `version` increments by one, and the response — `201 Created`, per §4 — reports the resulting `balance_cents`, `replenishment_fail_count`, and `status` as a small summary object rather than the full account.

`AgencyOperations` may also post a manual balance adjustment — a goodwill credit or a fee correction — carrying a signed `delta_cents`, a free-text `reason`, and the OCC token `expected_account_version`. The delta may be negative, but if applying it would drive `balance_cents` below zero the adjustment is rejected with `ERR_INVALID_AMOUNT`; non-positive payment amounts elsewhere are likewise rejected with `ERR_INVALID_AMOUNT`. A successful adjustment applies the delta, bumps `version`, and returns `201 Created` with a summary object carrying the resulting `balance_cents`.

Reinstating a suspended account is an `AgencyOperations` action with two preconditions: the account's `balance_cents` must be at least its `low_balance_threshold_cents` (otherwise `ERR_BALANCE_BELOW_THRESHOLD`), and no violation on the account may sit in `ESCALATED` or `HOLD_REFERRED` with `total_outstanding_cents` greater than zero (otherwise `ERR_ACCOUNT_HAS_UNRESOLVED_VIOLATIONS`). Reinstatement moves the account from `SUSPENDED` back to `ACTIVE`, resets `replenishment_fail_count` to zero, and clears `suspended_reason` to null.

Closing an account is holder-initiated and irreversible. Closure requires that no violation on the account remain in `OPEN`, `NOTICED`, `ESCALATED`, or `HOLD_REFERRED` (`ERR_ACCOUNT_HAS_UNRESOLVED_VIOLATIONS`) and that no toll transaction on the account remain in `POSTED` status awaiting settlement (`ERR_ACCOUNT_HAS_UNSETTLED_TRANSACTIONS`). On closure the account moves from `ACTIVE` to `CLOSED`, the remaining `balance_cents` is paid out to the holder and set to zero, and every transponder on the account transitions from `ACTIVE` to `RETIRED`.

### 3.6. Image Billing and Plate Lookups

When a trip's tag cannot be resolved to an active transponder, the system falls back to the image path: an `ImageBill` is created in `PENDING_LOOKUP` capturing the `plate_number` and `plate_state` read from the image and linked to its `toll_transaction_id`, with `account_id` and `lookup_agency_id` both null. The bill's `billed_amount_cents` equals the transaction's `charged_amount_cents` at creation, and its `misread_flag` starts false. Because an image trip is always priced at the video rate, the image fee has already been folded into that amount per §3.4.

Resolution is performed by a `PlateLookupAgent`. The lookup is only lawful when a plate data agreement in `ACTIVE` status exists whose requesting agency is the away agency of the trip, whose providing agency covers the plate's state in its `covers_states` list, and whose half-open validity window from `effective_from` to `effective_to` contains the current logical time. Absent such an agreement the resolution is rejected with `ERR_PLATE_LOOKUP_NOT_AVAILABLE`. When the lookup returns an account — supplied as `resolved_account_id` (a value naming no existing account is rejected with `ERR_NOT_FOUND`) — and that account is `ACTIVE`, the bill moves from `PENDING_LOOKUP` to `BILLED`: `lookup_agency_id` records the providing agency, and the target account's `balance_cents` is debited `billed_amount_cents` (which in turn triggers the replenishment decision of §3.5). When the lookup resolves to no account, or the located account is anything other than `ACTIVE` at resolve time (suspended or closed), the bill instead moves from `PENDING_LOOKUP` to `ESCALATED` — `lookup_agency_id` still records the providing agency — and a `Violation` is created with `toll_amount_cents` equal to the bill's `billed_amount_cents`, with `image_bill_id` pointing back to the bill, with the plate identity carried over, and with `account_id` set to the located account's id when one was located and null otherwise.

`AgencyOperations` may void an image bill. Voiding a `BILLED` bill credits its account back `billed_amount_cents`, but only when no dispute in `FILED` or `UNDER_REVIEW` references the bill — such a dispute blocks the void with `ERR_IMAGE_BILL_HAS_ACTIVE_DISPUTE`. Voiding a `PENDING_LOOKUP` bill simply retires it with no financial effect. Both paths end in `VOIDED`, a terminal state.

### 3.7. Violations: Notices, Escalation, and Registration Holds

A violation is born either from an escalated image bill or directly for an unregistered plate, and it opens in `OPEN` status. It carries the offending `plate_number` and `plate_state`, the underlying `toll_transaction_id`, optionally the `image_bill_id` it stems from (null otherwise), the unpaid `toll_amount_cents`, and zeroed `notice_count` and `admin_fees_cents`; `first_notice_day` and `current_notice_day` start null and stay null until the first notice; its `total_outstanding_cents` starts as the toll amount, `registration_hold_referred` starts false, and for unregistered plates `account_id` is null.

Notice issuance is the `ViolationsOfficer`'s lever, and the administrative fee schedule is fixed. The first notice requires `notice_count` to be zero; issuing it moves the violation from `OPEN` to `NOTICED`, sets `notice_count` to one, adds 500 cents to `admin_fees_cents`, recomputes `total_outstanding_cents`, and stamps both `first_notice_day` and `current_notice_day` with the current epoch day. The second and third notices keep the violation in `NOTICED` and each require two things: `notice_count` must currently be one or two (a fourth notice is rejected with `ERR_NOTICE_LIMIT_REACHED`), and at least 30 days must have elapsed since the previous notice — issuing too early is rejected with `ERR_NOTICE_TOO_SOON`. The second notice adds 2500 cents and the third adds 5000 cents to `admin_fees_cents`; in each case `notice_count` increments, `current_notice_day` moves to the current epoch day, and `total_outstanding_cents` recomputes. The fee is always computed from the notice count before the increment, so there is no circularity between the fee and the total it feeds. The outstanding total is always the toll amount plus accumulated admin fees, reduced by any payments.

Escalation happens in the day-advancement sweep, not by manual action. When a violation in `NOTICED` has reached its third notice (`notice_count` is three) and at least 60 days have elapsed since `first_notice_day`, the sweep transitions it to `ESCALATED` — unless its `total_outstanding_cents` has reached 10000 cents (one hundred dollars), in which case it goes directly to `HOLD_REFERRED` instead. For violations already sitting in `ESCALATED`, every subsequent day advancement re-evaluates the same threshold: once `total_outstanding_cents` is at least 10000 cents — and the boundary is inclusive, exactly 10000 is referred while 9999 is not — the violation moves to `HOLD_REFERRED`, `registration_hold_referred` is set true, and a referral is sent to the plate state's DMV. The moment a violation reaches `HOLD_REFERRED` while money remains outstanding, the owning account (if any) is suspended with `suspended_reason` set to `VIOLATION_ESCALATION`.

Payment closes the loop. An `AccountHolder` or a `ViolationsOfficer` may pay a violation in full from `OPEN`, `NOTICED`, `ESCALATED`, or `HOLD_REFERRED`; payment moves it to `PAID` and zeroes `total_outstanding_cents`. Notably, paying a violation that was already `HOLD_REFERRED` leaves `registration_hold_referred` untouched — releasing the DMV hold is a separate out-of-band flow. A `ViolationsOfficer` may instead dismiss a violation from `OPEN` or `NOTICED`, moving it to `DISMISSED`. When the dismissal stems from an upheld dispute rather than an officer's direct action, the dismissal also zeroes `total_outstanding_cents` and credits back any amount that had been debited. Both `PAID` and `DISMISSED` are terminal.

### 3.8. Disputes and Their Corrections

Disputes are filed by the `AccountHolder` against their own account, supplying `account_id` and a `dispute_type` of `VEHICLE_CLASSIFICATION`, `MISREAD_PLATE`, or `RENTAL_VEHICLE`. The type dictates which targets the filing must name. A classification dispute names the `toll_transaction_id` under dispute and the `claimed_vehicle_class` the holder asserts, which must differ from the class actually billed and must be one of the three vehicle classes — a claimed class equal to the billed class, or not a valid class, is rejected with `ERR_INVALID_REQUEST`. The named transaction must currently be `POSTED`; filing a classification dispute against a transaction in any other status is rejected with `ERR_INVALID_STATE_TRANSITION`. A misread-plate dispute names the `image_bill_id` and the `claimed_plate_number` the holder says was actually present. A rental-vehicle dispute names the `image_bill_id` and a `rental_agreement_ref` that reassigns liability to the renter. Any dispute may additionally carry a `violation_id` when it targets an escalated violation. Every filing is stamped with the current epoch day in `filed_day`, starts in `FILED`, and must arrive within 90 days of the trip: a filing whose current epoch day is more than 90 days past the trip is rejected with `ERR_DISPUTE_WINDOW_CLOSED`. "Days past the trip" is measured in epoch-day units per §2.6 — the current epoch day minus the epoch day of the trip's timestamp — not as a wall-clock 24-hour span. For unregistered-plate violations, a plate-owner dispute is permitted with a null `account_id`.

Filing a classification dispute has an immediate bookkeeping effect: the named toll transaction moves from `POSTED` to `DISPUTED`, and while `DISPUTED` it is excluded from settlement sweeps.

A `ViolationsOfficer` then works the queue. Beginning review moves a dispute from `FILED` to `UNDER_REVIEW`. From `UNDER_REVIEW` the officer either upholds the dispute, moving it to `UPHOLD`, or rejects it, moving it to `REJECTED`. Upholding a classification dispute re-prices the transaction at the `claimed_vehicle_class`: the system looks up the `ACTIVE` rate schedule for the claimed class at the transaction's plaza and trip timestamp — falling back to the transaction's existing schedule if none covers it — and `billed_vehicle_class`, `gross_amount_cents`, `discount_amount_cents`, and `charged_amount_cents` are recomputed against the account's current plan state, without altering `discount_used_today_cents` or `trips_this_month`; `rate_schedule_id` is updated to the new schedule when one was found. The account's `balance_cents` is then credited the difference between the old and new charged amounts — old minus new, so a corrected class that costs more results in a net debit — and the transaction returns to `POSTED` with the corrected class. Upholding a misread-plate or rental dispute drives the linked image bill from `BILLED` to `REBILLED`: the original account is credited exactly `billed_amount_cents` once — a single net-credit entry, deliberately not a reversal-plus-separate-credit-memo pair — and for a misread the bill's `misread_flag` is set true. A brand-new image bill for the corrected plate or the rental liable party is then created in `PENDING_LOOKUP`, carrying the same `toll_transaction_id` and copying the original bill's `billed_amount_cents`, with `lookup_agency_id` null and with `account_id` preset to the corrected party's account when a transponder registered to the corrected plate exists (null otherwise); no violation is spawned for the new bill at creation — if the corrected plate matches no account, the bill simply awaits a fresh resolve cycle like any other pending image bill. Any linked violation is dismissed per §3.7, from whichever non-terminal status it currently sits in (`OPEN`, `NOTICED`, `ESCALATED`, or `HOLD_REFERRED`). Rejecting a classification dispute moves the dispute to `REJECTED` and returns the transaction from `DISPUTED` to `POSTED` unchanged — a rejection never re-prices the transaction. The holder may withdraw a dispute from either `FILED` or `UNDER_REVIEW`, moving it to `WITHDRAWN`; for a classification dispute the transaction likewise returns from `DISPUTED` to `POSTED` unchanged.

Disputes that sit idle are not allowed to linger. The day-advancement sweep auto-rejects any dispute still in `FILED` once 30 days have passed since `filed_day` without a review having begun, moving it to `REJECTED`, and the classification bookkeeping unwinds exactly as for a manual rejection.

### 3.9. Interagency Settlement and Plate Data Agreements

Settlement is how the away agency gets paid. A `SettlementOfficer` generates a settlement file for an ordered agency pair by naming `from_agency_id` (the home agency that collected the money and now owes) and `to_agency_id` (the away agency that provided the facility and is owed). The sweep claims every toll transaction that is in `POSTED` status with `settlement_file_id` still null, whose `away_agency_id` is the to-agency, and whose account's home agency is the from-agency, ordered by `trip_timestamp` ascending with `created_at` ascending as the tie-breaker. Because the claim requires a matching account, image-path transactions — whose `account_id` is null — are never swept into a settlement file. Each claimed line moves from `POSTED` to `SETTLED` and has its `settlement_file_id` set.

The file's totals are computed with a deliberately pinned rounding convention. `line_count` is the number of swept lines and `gross_amount_cents` is the sum of their `charged_amount_cents`. The reciprocity fee is computed per line: each line contributes its `charged_amount_cents` multiplied by the to-agency's `reciprocity_fee_bps`, divided by ten thousand, rounded half-up to whole cents — and `fee_amount_cents` is the sum of those per-line fees. Computing the fee on the aggregate gross instead is an explicitly rejected alternative: the two conventions diverge by one or more cents on many multi-line files, and the per-line convention is the normative one. `net_amount_cents`, the amount the from-agency owes the to-agency, is the gross minus the fee. The file is stamped with the current epoch day as its `settlement_day`, starts in `GENERATED`, and carries `exception_count` zero. Any mutation of the file's line set recomputes all four totals.

From `GENERATED` the officer transmits the file, moving it to `TRANSMITTED`. The receiving side acknowledges receipt, moving it to `ACKNOWLEDGED`; because operator identities are not bound to agencies in this API (§2.1), acknowledgement requires only the `SettlementOfficer` role — no receiving-agency identity check is enforced. If the receiver finds problems, they flag an exception with a free-text `reason`, moving the file from `TRANSMITTED` to `DISPUTED_SETTLEMENT` and incrementing `exception_count` once per flag. Resolving exceptions moves the file from `DISPUTED_SETTLEMENT` to `ACKNOWLEDGED` and resets `exception_count` to zero. Reconciliation is the terminal step: an `ACKNOWLEDGED` file with zero exceptions moves to `RECONCILED`, marking `net_amount_cents` as transferred from the from-agency to the to-agency; attempting to reconcile while `exception_count` is greater than zero is rejected with `ERR_SETTLEMENT_HAS_EXCEPTIONS`.

Plate data agreements govern the cross-jurisdiction lookups that image billing depends on. A `SettlementOfficer` creates one between a `requesting_agency_id` and a `providing_agency_id`, with a half-open validity window from `effective_from` to `effective_to`, a `covers_states` list naming which states' plates the providing agency (acting as the DMV proxy) will resolve, and an optional `per_lookup_fee_cents` defaulting to 25 cents that the requester pays per resolved lookup. Agreements are created `ACTIVE`; the validity timestamps must parse as ISO 8601 but the window's direction is not validated at creation. If an existing `ACTIVE` agreement for the same requesting-providing pair already covers any shared state with an overlapping validity window, creation is rejected with `ERR_AGREEMENT_OVERLAP`. When the logical clock passes an agreement's `effective_to`, the agreement moves automatically from `ACTIVE` to `EXPIRED`. An officer may revoke an agreement outright, moving it from `ACTIVE` to `REVOKED` (terminal); from that moment, plate lookups relying on it are rejected with `ERR_PLATE_LOOKUP_NOT_AVAILABLE`.

## 4. Endpoint Definitions

Operations that create a new resource — an agency, a rate schedule, a discount plan, an account, a transponder, a toll transaction, a dispute, a settlement file, a plate data agreement, or a replenishment or adjustment record — return `201 Created`. Operations that act on an existing resource without creating a new one — state transitions, voids, resolutions, notices, payments, clock operations — return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/toll/_clock/set_current_utc` | Set the logical clock | SettlementOfficer |
| POST | `/toll/_clock/advance_day` | Advance the epoch day counter and run scheduled sweeps | SettlementOfficer |
| POST | `/toll/agencies` | Register a member agency | SettlementOfficer |
| GET | `/toll/agencies` | List agencies | SettlementOfficer, AgencyOperations, ViolationsOfficer, PlateLookupAgent, AccountHolder |
| GET | `/toll/agencies/{agencyId}` | Get an agency | SettlementOfficer, AgencyOperations, ViolationsOfficer, PlateLookupAgent, AccountHolder |
| POST | `/toll/agencies/{agencyId}/suspend` | Suspend an agency | SettlementOfficer |
| POST | `/toll/agencies/{agencyId}/reactivate` | Reactivate a suspended agency | SettlementOfficer |
| POST | `/toll/agencies/{agencyId}/rate-schedules` | Create a rate schedule for a plaza and class window | AgencyOperations |
| GET | `/toll/agencies/{agencyId}/rate-schedules` | List an agency's rate schedules | SettlementOfficer, AgencyOperations, ViolationsOfficer, PlateLookupAgent, AccountHolder |
| GET | `/toll/rate-schedules` | List rate schedules across agencies | SettlementOfficer, AgencyOperations, ViolationsOfficer, PlateLookupAgent, AccountHolder |
| GET | `/toll/rate-schedules/{scheduleId}` | Get a rate schedule | SettlementOfficer, AgencyOperations, ViolationsOfficer, PlateLookupAgent, AccountHolder |
| POST | `/toll/agencies/{agencyId}/discount-plans` | Create a discount plan issued by the agency | AgencyOperations |
| GET | `/toll/agencies/{agencyId}/discount-plans` | List an agency's discount plans | SettlementOfficer, AgencyOperations, ViolationsOfficer, PlateLookupAgent, AccountHolder |
| GET | `/toll/discount-plans` | List discount plans across agencies | SettlementOfficer, AgencyOperations, ViolationsOfficer, PlateLookupAgent, AccountHolder |
| GET | `/toll/discount-plans/{planId}` | Get a discount plan | SettlementOfficer, AgencyOperations, ViolationsOfficer, PlateLookupAgent, AccountHolder |
| POST | `/toll/accounts` | Open a transponder account at a home agency | AgencyOperations |
| GET | `/toll/accounts` | List accounts | SettlementOfficer, AgencyOperations, ViolationsOfficer |
| GET | `/toll/accounts/{accountId}` | Get an account | SettlementOfficer, AgencyOperations, ViolationsOfficer, AccountHolder |
| POST | `/toll/accounts/{accountId}/replenishments` | Record a replenishment with OCC on account version | AgencyOperations, AccountHolder |
| POST | `/toll/accounts/{accountId}/adjustments` | Post a manual balance adjustment with OCC on account version | AgencyOperations |
| POST | `/toll/accounts/{accountId}/reinstate` | Reinstate a suspended account | AgencyOperations |
| POST | `/toll/accounts/{accountId}/close` | Close an account | AccountHolder |
| POST | `/toll/accounts/{accountId}/transponders` | Issue a transponder on an account | AgencyOperations |
| GET | `/toll/accounts/{accountId}/transponders` | List an account's transponders | SettlementOfficer, AgencyOperations, ViolationsOfficer, AccountHolder |
| GET | `/toll/transponders` | List transponders across accounts | SettlementOfficer, AgencyOperations, ViolationsOfficer, AccountHolder |
| GET | `/toll/transponders/{transponderId}` | Get a transponder | SettlementOfficer, AgencyOperations, ViolationsOfficer, AccountHolder |
| POST | `/toll/transponders/{transponderId}/report_lost` | Report a transponder lost | AccountHolder |
| POST | `/toll/transponders/{transponderId}/report_found` | Report a transponder found | AccountHolder |
| POST | `/toll/transponders/{transponderId}/retire` | Retire a transponder | AccountHolder |
| POST | `/toll/toll-transactions` | Post a toll trip (transponder read or image fallback) | AgencyOperations |
| GET | `/toll/toll-transactions` | List toll transactions | SettlementOfficer, AgencyOperations, ViolationsOfficer, AccountHolder |
| GET | `/toll/toll-transactions/{transactionId}` | Get a toll transaction | SettlementOfficer, AgencyOperations, ViolationsOfficer, AccountHolder |
| POST | `/toll/toll-transactions/{transactionId}/void` | Void a posted transaction and credit the account | AgencyOperations |
| GET | `/toll/image-bills` | List image bills | SettlementOfficer, AgencyOperations, ViolationsOfficer, PlateLookupAgent, AccountHolder |
| GET | `/toll/image-bills/{imageBillId}` | Get an image bill | SettlementOfficer, AgencyOperations, ViolationsOfficer, PlateLookupAgent, AccountHolder |
| POST | `/toll/image-bills/{imageBillId}/resolve` | Resolve a pending image bill to an account and bill it | PlateLookupAgent |
| POST | `/toll/image-bills/{imageBillId}/void` | Void an image bill | AgencyOperations |
| GET | `/toll/violations` | List violations | SettlementOfficer, AgencyOperations, ViolationsOfficer, AccountHolder |
| GET | `/toll/violations/{violationId}` | Get a violation | SettlementOfficer, AgencyOperations, ViolationsOfficer, AccountHolder |
| POST | `/toll/violations/{violationId}/issue_notice` | Issue the next violation notice with its admin fee | ViolationsOfficer |
| POST | `/toll/violations/{violationId}/pay` | Pay a violation in full | AccountHolder, ViolationsOfficer |
| POST | `/toll/violations/{violationId}/dismiss` | Dismiss a violation | ViolationsOfficer |
| POST | `/toll/disputes` | File a dispute | AccountHolder |
| GET | `/toll/disputes` | List disputes | SettlementOfficer, AgencyOperations, ViolationsOfficer, AccountHolder |
| GET | `/toll/disputes/{disputeId}` | Get a dispute | SettlementOfficer, AgencyOperations, ViolationsOfficer, AccountHolder |
| POST | `/toll/disputes/{disputeId}/begin_review` | Move a dispute to under review | ViolationsOfficer |
| POST | `/toll/disputes/{disputeId}/uphold` | Uphold a dispute and apply its correction | ViolationsOfficer |
| POST | `/toll/disputes/{disputeId}/reject` | Reject a dispute | ViolationsOfficer |
| POST | `/toll/disputes/{disputeId}/withdraw` | Withdraw a dispute | AccountHolder |
| POST | `/toll/settlement-files/generate` | Generate the settlement file for an agency pair | SettlementOfficer |
| GET | `/toll/settlement-files` | List settlement files | SettlementOfficer, AgencyOperations |
| GET | `/toll/settlement-files/{settlementFileId}` | Get a settlement file | SettlementOfficer, AgencyOperations |
| POST | `/toll/settlement-files/{settlementFileId}/transmit` | Transmit a generated file to the counterparty | SettlementOfficer |
| POST | `/toll/settlement-files/{settlementFileId}/acknowledge` | Counterparty acknowledges receipt | SettlementOfficer |
| POST | `/toll/settlement-files/{settlementFileId}/flag_exception` | Flag a reconciliation exception | SettlementOfficer |
| POST | `/toll/settlement-files/{settlementFileId}/resolve_exceptions` | Resolve all exceptions | SettlementOfficer |
| POST | `/toll/settlement-files/{settlementFileId}/reconcile` | Reconcile an acknowledged exception-free file | SettlementOfficer |
| POST | `/toll/plate-data-agreements` | Create a plate data agreement between two agencies | SettlementOfficer |
| GET | `/toll/plate-data-agreements` | List plate data agreements | SettlementOfficer, AgencyOperations, PlateLookupAgent |
| GET | `/toll/plate-data-agreements/{agreementId}` | Get a plate data agreement | SettlementOfficer, AgencyOperations, PlateLookupAgent |
| POST | `/toll/plate-data-agreements/{agreementId}/revoke` | Revoke an agreement | SettlementOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE_TRANSITION` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_ACCOUNT_SUSPENDED` | 409 Conflict |
| `ERR_ACCOUNT_CLOSED` | 409 Conflict |
| `ERR_TRANSPONDER_NOT_ACTIVE` | 409 Conflict |
| `ERR_AGENCY_SUSPENDED` | 409 Conflict |
| `ERR_RATE_NOT_FOUND` | 422 Unprocessable Entity |
| `ERR_PLAN_NOT_APPLICABLE` | 422 Unprocessable Entity |
| `ERR_PLATE_LOOKUP_NOT_AVAILABLE` | 409 Conflict |
| `ERR_NOTICE_TOO_SOON` | 409 Conflict |
| `ERR_NOTICE_LIMIT_REACHED` | 409 Conflict |
| `ERR_DUPLICATE_TRANSACTION` | 409 Conflict |
| `ERR_DUPLICATE_TAG` | 409 Conflict |
| `ERR_DUPLICATE_PLAN_CODE` | 409 Conflict |
| `ERR_SCHEDULE_OVERLAP` | 409 Conflict |
| `ERR_AGREEMENT_OVERLAP` | 409 Conflict |
| `ERR_TRANSACTION_ALREADY_SETTLED` | 409 Conflict |
| `ERR_IMAGE_BILL_HAS_ACTIVE_DISPUTE` | 409 Conflict |
| `ERR_DISPUTE_WINDOW_CLOSED` | 409 Conflict |
| `ERR_BALANCE_BELOW_THRESHOLD` | 409 Conflict |
| `ERR_ACCOUNT_HAS_UNRESOLVED_VIOLATIONS` | 409 Conflict |
| `ERR_ACCOUNT_HAS_UNSETTLED_TRANSACTIONS` | 409 Conflict |
| `ERR_INVALID_AMOUNT` | 409 Conflict |
| `ERR_SETTLEMENT_HAS_EXCEPTIONS` | 409 Conflict |
| `ERR_AGENCY_HAS_PENDING_SETTLEMENT` | 409 Conflict |
