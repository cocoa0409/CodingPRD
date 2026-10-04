# Worksite Indemnity API — Product Requirements Document

## 1. Introduction

Worksite voluntary benefits carriers run a deceptively simple business at a complicated seam: they sell fixed-amount supplemental indemnity products (accident, hospital, critical illness) through employers' payroll channels, enroll employees in short counselor-led campaigns at the worksite, and later pay pre-agreed cash benefits per covered event — amounts driven by a published benefit schedule, not by the size of any medical bill. The money in and the money out run on separate rails: payroll-deducted premiums reconcile per cycle per employee, while claims adjudicate per event against yearly occurrence caps and lifetime maxima, with a separate once-a-year wellness benefit layered on top. Employees leave, policies must port to direct billing, lapses must be reversible within a grace window, and benefit schedules are re-published over time — yet every issued policy must forever keep the schedule it was priced against.

This document specifies the Worksite Indemnity API, the system of record for that business. It governs the full lifecycle of employer groups and their enrollment campaigns, the issuance and servicing of policies, the adjudication and payment of indemnity and wellness claims, and the synthesis and reconciliation of payroll deduction cycles. The design leans on a deliberately strict separation of roles — carrier-side administrators, employer-side administrators, benefit counselors, claims adjusters, and a policyholder service desk — because the regulatory posture of supplemental benefits demands that pricing, selling, and paying are provably done by different hands.

A single logical clock underpins the entire system. Enrollment windows, reinstatement periods, appeal deadlines, and waiting periods are all evaluated against this clock rather than against wall-clock time, so that the platform's behavior is fully deterministic and replayable.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a set of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes five distinct roles: `CarrierAdmin`, `GroupAdmin`, `BenefitCounselor`, `ClaimsAdjuster`, and `PolicyholderServices`. A request missing either header, or carrying a role the system does not declare, is rejected with `ERR_UNAUTHENTICATED`. When a properly identified caller attempts an operation outside their role's authorized set, the request is rejected with `ERR_UNAUTHORIZED`.

For every role, `X-User-ID` is an opaque operator identifier not tied to any persisted entity: the server may record it for audit but never compares it to any entity's `id`. In particular, campaign operations require only the `BenefitCounselor` role; they are not restricted to the campaign's designated `counselor_id`, and no endpoint enforces a lead-counselor identity binding.

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

Requests to paths the API does not define are rejected with `ERR_NOT_FOUND` (404), and requests carrying a defined path but an unsupported HTTP method are rejected with `ERR_INVALID_REQUEST` (405).

---

### 2.3. Pagination

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0. A non-integer `limit` or `offset`, a `limit` outside the 1-to-100 range, or a negative `offset` is rejected with `ERR_INVALID_REQUEST`.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order, with ties broken by `id` ascending. Filters are exact-match equality on the named field. The `total_count` in `meta` counts the filtered result set, not the unfiltered collection.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock

The platform does not consult wall-clock time. A single logical clock determines "now" for every temporal rule in this document — enrollment-window gating, reinstatement and appeal deadlines, and waiting-period arithmetic all read this clock. Before any client sets it, the clock reads exactly 2026-09-01T00:00:00Z and must never silently fall back to wall-clock time. A test-driving capability, available to all five roles, advances the clock to a caller-supplied `to_iso8601` instant and returns the resulting `current_utc`. This is the only endpoint exempt from the authentication-header requirement; every other endpoint demands the headers of §2.1. Everywhere this document assigns a temporal meaning to an ISO 8601 instant field — the clock itself, window bounds, dates set to the current clock time, month-aligned dates, or caller-supplied timestamps echoed back on the resource — the field identifies an instant in time, and any ISO 8601 rendering of that same instant in UTC (with or without fractional digits) is an acceptable representation.

### 2.5. Common Resource Properties

Every resource in the system — employer groups, counselors, campaigns, series, schedules, employees, policies, claims, documents, wellness benefits, payroll cycles, and deduction lines — carries a standard set of system-managed fields:

- **`id` (string):** A unique, server-minted identifier formatted as a UUID, with no type prefix.
- **`created_at` (string):** An ISO 8601 timestamp in UTC with three fractional digits (for example, `2026-09-01T12:00:00.123Z`) indicating when the resource was first created. Like every temporal value in the system, it reads the logical clock of §2.4, never wall-clock time.
- **`updated_at` (string):** An ISO 8601 UTC timestamp indicating when the resource was last modified, refreshed from the same logical clock on every mutation.
- **`version` (integer):** A system-managed integer that starts at 1 on creation and increments by exactly 1 with every modification to the resource. It anchors the optimistic concurrency controls of §2.9.

### 2.6. Version Pinning of Benefit Schedules

A policy is priced and adjudicated forever against the benefit schedule that was published for its series at the instant of issuance. Each policy records a `benefit_schedule_id` — a reference to the series' schedule whose status is `PUBLISHED` at that instant — and copies `monthly_premium_cents` from that schedule. Later publications of the same series supersede the old schedule for *future* issuances only; existing policies are never repointed. At any time, the series' `current_schedule_id` names its currently published schedule, and is null when the series has none. Publishing is strictly serialized within a series: a new schedule's `schedule_version` must be greater than every existing `schedule_version` of the same series, and its `effective_date` must be strictly later than the effective date of every other schedule in the series — even a same-day collision is rejected with `ERR_SCHEDULE_VERSION_CONFLICT`. Within a schedule, `benefit_items` is an array of entries each carrying an `event_code`, a `benefit_amount_cents`, a `max_occurrences_per_year`, and a `lifetime_max_cents`; the `event_code` values must be unique within the array, and this uniqueness is enforced with `ERR_INVALID_REQUEST` both when the schedule is created and when it is published.

### 2.7. The Claims Ledger Invariants

Each policy maintains a claims ledger in two derived fields. `lifetime_paid_cents` is the sum of `payable_amount_cents` over the policy's claims whose status is `PAID` — and only those: claims that are approved but not yet paid do not consume capacity, and voided claims are compensated back out. `paid_occurrences_by_year` is a map from calendar year to event code to the number of occurrences paid, again over `PAID` claims only. Two invariants are maintained at all times: `lifetime_paid_cents` always equals the sum over the policy's non-voided paid claims, and each yearly occurrence counter always equals the occurrences credited by those same claims. Paying a claim increments both; voiding a paid claim decrements both by exactly the amount and occurrences that claim contributed. The ledger starts at zero: `lifetime_paid_cents` defaults to 0 and `paid_occurrences_by_year` to an empty map.

### 2.8. Money, Precision, and Rounding Order

All monetary amounts in the system are integer cents; claim-payable arithmetic involves no rounding at all because every operand is already an integer number of cents. Payroll deduction proration is the one place where rounding occurs, and its order of operations is pinned: each deduction line's `amount_cents` is rounded half-up to whole cents at line level first, and only then are line amounts summed into the cycle's `total_posted_cents`. The system never sums unrounded values and rounds once at the end. Month arithmetic — used for waiting periods and exclusion windows — adds whole calendar months and clamps to the last day of the target month when the day-of-month does not exist there (the thirty-first of January plus one month is the twenty-eighth of February).

### 2.9. Optimistic Concurrency Control

Two write operations guard against stale parent views via optimistic concurrency control, and both reject a mismatched version with `ERR_STALE_VERSION` (HTTP 412). In both operations the expected-version field is optional: when the field is omitted from the request body, no version check is performed and the write proceeds; when the field is supplied and does not equal the parent's current `version`, the write is rejected with `ERR_STALE_VERSION`.

Publishing a benefit schedule accepts `expected_series_version` in the request body, the `version` of the parent policy series as the client last observed it. Because a successful publish itself supersedes the previously published schedule and advances the series' `version` by 1, a publish attempted with a stale series version — for instance, after another writer has published a different schedule of the same series — is rejected with `ERR_STALE_VERSION`.

Closing an enrollment campaign accepts `expected_group_version` in the request body, the `version` of the campaign's employer group as the client last observed it. Bulk issuance at close mutates the group-visible enrolled population, so a close carrying a stale group version is rejected with `ERR_STALE_VERSION` rather than applied. The check applies only to the participation-judging close (`LOCKED` → `MET`/`FAILED`); the subsequent finalizing close (`MET`/`FAILED` → `CLOSED`) performs no version check.

Endpoints not named in this subsection do not take a version field; no other optimistic-locking mechanism exists in the system.

### 2.10. Validation Order

Every request is validated in a fixed priority order, and the first failing check determines the error returned. Authentication comes first (`ERR_UNAUTHENTICATED`, then the role check `ERR_UNAUTHORIZED`), followed by existence of every identifier referenced in the path and body, evaluated left-to-right (`ERR_NOT_FOUND`), and then referential integrity of body-supplied foreign keys (`ERR_REFERENTIAL_INTEGRITY`). Only then does the system evaluate state-transition legality (`ERR_INVALID_STATE`), regulatory and safety gates such as counselor activity, the pre-existing exclusion, and the appeal and reinstatement windows, structural constraints such as window overlaps, double-booking, duplicate coverage, duplicate wellness years, and schedule-version monotonicity, temporal gates such as window expiry and waiting periods, fiscal capacity gates such as occurrence caps, lifetime maxima, and claims-in-flight, the optimistic concurrency check of §2.9, and finally request-body schema well-formedness (`ERR_INVALID_REQUEST`). Where multiple checks of the same rank could fail, the narratives of §3 name their relative order explicitly.

## 3. Business Logic & Workflows

### 3.1. Employer Groups and Counselors: Setting the Stage

Everything begins with the employer group. A `CarrierAdmin` registers a group with its legal `name` and a globally unique `group_code`, optionally tuning the participation rules that will later decide whether campaigns at this group succeed: `participation_minimum_pct` is the fraction of eligible employees that must enroll (a number from 0 to 1 inclusive, defaulting to 0.10), `participation_minimum_count` is an absolute floor on enrolled policies (defaulting to 3), and `proration_convention` selects the group's payroll proration variant — `DAILY` or `HALF_MONTH`, defaulting to `DAILY`. Malformed input at creation is rejected with `ERR_INVALID_REQUEST`: a `proration_convention` outside the two variants, a non-numeric `participation_minimum_pct`, a non-integer `participation_minimum_count`, or a `group_code` already taken. A new group is born in `PROSPECT` status. Two counters are always derivable at read time: `eligible_employee_count` counts the group's employees whose status is `ACTIVE` at read time, and `enrolled_count` counts policies filed under campaigns of this group whose status is one of `APPLIED`, `ISSUED`, `ACTIVE`, or `LAPSED` — ported policies drop out of the count per §3.5, and declined and cancelled policies do not count.

Activating a group (`PROSPECT` → `ACTIVE`) requires its `participation_minimum_pct` to lie within the zero-to-one inclusive range and its `participation_minimum_count` to be non-negative; an out-of-range activation is refused with `ERR_INVALID_REQUEST`. Suspension (`ACTIVE` → `SUSPENDED`) immediately locks every open campaign of the group: each `OPEN` campaign is auto-transitioned to `LOCKED`. A suspended group can be reactivated (`SUSPENDED` → `ACTIVE`); activation from either `PROSPECT` or `SUSPENDED` lands on the same `ACTIVE` state. Termination is heavier. From `ACTIVE`, termination is refused with `ERR_INVALID_STATE` while any campaign of the group is `OPEN`; from `SUSPENDED` there is no such precondition. Either way, termination (`→ TERMINATED`) fires a cascade in the same transaction: every policy of the group's employees in `ISSUED` or `ACTIVE` status lapses to `LAPSED`; every campaign of the group in `DRAFT`, `LOCKED`, `MET`, or `FAILED` closes to `CLOSED`; and when the forced closure sweeps up a `LOCKED` campaign, that closure itself declines every `APPLIED` policy under it — a three-hop chain from group to campaign to policies. Each of these group transitions increments the group's `version` and refreshes `updated_at`. `TERMINATED` is final.

Benefit counselors are the licensed field force. A `CarrierAdmin` onboards a counselor with a globally unique `license_id` (a duplicate is rejected with `ERR_INVALID_REQUEST`), a `full_name`, and a two-letter `home_state`; counselors start `ACTIVE`. Counselors can be suspended (`ACTIVE` → `SUSPENDED`) and reactivated (`SUSPENDED` → `ACTIVE`), and terminated from either `ACTIVE` or `SUSPENDED` — but termination is refused with `ERR_INVALID_STATE` while the counselor leads any campaign in `OPEN` status.

### 3.2. Enrollment Campaigns: From Window to Verdict

A campaign binds a counselor to a group for a defined selling window. Creating one requires the `employer_group_id`, the `counselor_id`, a `window_start`, and a `window_end` strictly after the start (a `window_end` not strictly after `window_start` is rejected with `ERR_INVALID_REQUEST`); both instants are ISO 8601 UTC, and the window is a half-open interval — `window_start` inclusive, `window_end` exclusive. The optional `guaranteed_issue` flag (default false) determines whether applications in this campaign skip the pre-existing-condition screen. The designated counselor must be `ACTIVE` at creation, else `ERR_COUNSELOR_INACTIVE`, and a new campaign starts in `DRAFT`.

A `BenefitCounselor` opens the campaign (`DRAFT` → `OPEN`) under a battery of checks — per §2.1 any caller of that role may do so, not only the designated counselor: the counselor must still be `ACTIVE` (`ERR_COUNSELOR_INACTIVE`), the employer group must be `ACTIVE` (`ERR_GROUP_INACTIVE`), and the current clock time must be before `window_end` (`ERR_WINDOW_EXPIRED`). Two scheduling constraints protect the calendar, and they deliberately use different interval semantics. Within the group, no other `OPEN` campaign may have a window overlapping this one under half-open semantics — an existing window that ends exactly at this campaign's `window_start` does not overlap; a violation is `ERR_CAMPAIGN_WINDOW_OVERLAP`. Across the counselor's own book, the rule is stricter: the counselor must not already lead an `OPEN` campaign whose window intersects this one under closed-interval semantics, so a window whose start equals this campaign's `window_end` — or vice versa — does conflict; a violation is `ERR_COUNSELOR_DOUBLE_BOOKED`.

While open, the campaign accepts applications. When the window has run its course, the counselor locks it (`OPEN` → `LOCKED`), which requires the current clock time to be at or after `window_end` — locking early fails with `ERR_WINDOW_NOT_CLOSED`.

Closing a locked campaign is where participation is judged, and the caller does not choose the outcome: the close branches deterministically. The system freezes `required_enrollments` on the campaign as the larger of the group's `participation_minimum_count` and the group's `participation_minimum_pct` multiplied by the group's `eligible_employee_count` at the close instant and rounded up to a whole number. If the group's `enrolled_count` at that instant is at least `required_enrollments` — exactly at the threshold counts, the comparison is inclusive — the campaign transitions `LOCKED` → `MET`, records `participation_met` as true, and bulk-issues every `APPLIED` policy under it (see §3.3 for what issuance pins). Any policy whose series has no `PUBLISHED` schedule at that moment is declined instead, and this is surfaced on the campaign response as an added boolean field `series_without_schedule: true` on the returned campaign object (the close itself still succeeds with 200). Bulk issuance is not all-or-nothing for that case, but a policy whose series has gone `RETIRED` or whose issuance would violate the duplicate-coverage rule aborts the entire close with `ERR_SERIES_RETIRED` or `ERR_DUPLICATE_COVERAGE` respectively. If enrollment falls short, the campaign transitions `LOCKED` → `FAILED`, records `participation_met` as false, and every `APPLIED` policy under it is auto-declined. Because close mutates the group's enrolled population, it is one of the two OCC-guarded writes of §2.9 and its `expected_group_version`, when supplied, is enforced on this `LOCKED`-close only. Either terminal verdict can subsequently be finalized (`MET` → `CLOSED` or `FAILED` → `CLOSED`), and each close call increments the campaign's `version`.

A failed campaign gets one second chance. The counselor may reopen it (`FAILED` → `OPEN`) by supplying a `new_window_end` (omitting it fails with `ERR_INVALID_REQUEST`). The group is checked first — it must again be `ACTIVE` (`ERR_GROUP_INACTIVE`) — and only then the window: `new_window_end` must be strictly after the current clock time and strictly after the old `window_end` (`ERR_WINDOW_EXPIRED`), and the extended window must be clear of any other `OPEN` campaign of the same group under the half-open overlap rule (`ERR_CAMPAIGN_WINDOW_OVERLAP`). Reopening writes the new `window_end`, resets `participation_met` and `required_enrollments` to null, and reverses the earlier verdict on the applications: every policy under the campaign in `DECLINED` status returns to `APPLIED`. The campaign can then run the cycle again — lock, close, verdict — as many times as the business allows.

### 3.3. Product Series, Schedules, and Policy Issuance

The carrier's products are organized as policy series. A `CarrierAdmin` creates a series with a globally unique `series_code` (a duplicate is rejected with `ERR_INVALID_REQUEST`) and a `product_line` of `ACCIDENT`, `HOSPITAL`, or `CRITICAL_ILLNESS` (any other value is rejected with `ERR_INVALID_REQUEST`); it starts in `DRAFT`. Schedules carry the actual money: each schedule belongs to a series via `policy_series_id` and is created in `DRAFT` with a `schedule_version` (which must be an integer), an `effective_date`, the `benefit_items` array, a `monthly_premium_cents`, a `wellness_benefit_cents` (the annual wellness amount), a `wellness_waiting_months` (whole months after coverage start before the wellness benefit is payable), and a `preexisting_exclusion_months` (whole months after coverage start during which pre-existing diagnoses are excluded); a non-integer `schedule_version` or a non-array `benefit_items` is rejected with `ERR_INVALID_REQUEST`. The version-monotonicity and effective-date rules of §2.6 apply at creation.

Publishing a schedule (`DRAFT` → `PUBLISHED`) is gated and serialized. The owning series must be `DRAFT` or `ACTIVE` — publishing against a retired series fails with `ERR_SERIES_RETIRED`. The `benefit_items` array must be non-empty, each `event_code` unique within it, and each `benefit_amount_cents` non-negative, else `ERR_INVALID_REQUEST`. The request may carry `expected_series_version` per §2.9 (optional; enforced only when supplied). A successful publish supersedes: any other schedule of the same series currently `PUBLISHED` is auto-transitioned to `SUPERSEDED`, the series' `current_schedule_id` is repointed to the new schedule, and the series' `version` increments by 1. A series becomes sellable by activation (`DRAFT` → `ACTIVE`), which requires at least one of its schedules to be `PUBLISHED` (`ERR_SERIES_WITHOUT_SCHEDULE`). Retirement (`ACTIVE` → `RETIRED`) closes the series to new business — subsequent applications against it are rejected with `ERR_SERIES_RETIRED` — while existing policies keep their pinned schedules untouched.

Policies begin life as applications. A benefit counselor files an application with a `campaign_id`, an `employee_id`, a `policy_series_id`, and an optional `premium_mode` of `PRE_TAX` or `POST_TAX` (default `POST_TAX`; any other supplied value is rejected with `ERR_INVALID_REQUEST`). Filing checks, in order after referential integrity: an application against a `RETIRED` series is refused with `ERR_SERIES_RETIRED`; the campaign must be `OPEN`, otherwise `ERR_INVALID_STATE`; and the clock must lie within the campaign's half-open window, otherwise `ERR_WINDOW_EXPIRED`. Filing imposes no further gate — neither the pre-existing screen nor duplicate coverage is evaluated until issuance. The new policy is born in `APPLIED`.

Issuance (`APPLIED` → `ISSUED`) happens either in bulk at a `MET` campaign close or individually through direct issuance, and the preconditions are identical either way: the series must be `ACTIVE` at issuance time (`ERR_SERIES_RETIRED`), the series must have a `PUBLISHED` schedule (`ERR_SERIES_WITHOUT_SCHEDULE`), and no other policy for the same `employee_id` and `policy_series_id` may exist in any of `APPLIED`, `ISSUED`, `ACTIVE`, `LAPSED`, or `PORTED` status (`ERR_DUPLICATE_COVERAGE`). On top of that sits the pre-existing condition provision: if the campaign was not guaranteed-issue and the employee's `preexisting_diagnosis_codes` is non-empty, the policy is declined instead of issued. The pre-existing screen is applied before the duplicate-coverage check, so an application tripping both is declined (a 200 response carrying the `DECLINED` policy), not rejected with an error. A successful issuance pins the version snapshot of §2.6: `benefit_schedule_id` is set to the series' `current_schedule_id` and never changes afterwards, `monthly_premium_cents` is copied from the pinned schedule and is likewise immune to later schedule publishes, `issue_date` is set to the current clock time, `coverage_start_date` is set to the first day of the calendar month containing the issue date at 00:00:00Z, and a `certificate_number` is minted from the series code followed by a dash and an eight-character deterministic sequence unique within the series — concretely, the series code, a dash, and a per-series sequential counter zero-padded to eight digits, beginning `00000001` (for example, `ACC-2026-00000001`).

### 3.4. The Employed Life of a Policy

Once issued, a policy's day-to-day servicing belongs to the counselor. Activation (`ISSUED` → `ACTIVE`) requires the insured employee to be `ACTIVE` (`ERR_EMPLOYEE_INACTIVE`). Lapse can happen from either `ISSUED` or `ACTIVE` (`→ LAPSED`) with no further conditions. Reinstatement (`LAPSED` → `ACTIVE`) is the grace-period path: it requires the policy to have lapsed within the last 60 days measured against the current clock — the lapse instant is recorded when the policy lapses, and a reinstatement exactly 60 days after it still qualifies; only a later attempt fails with `ERR_REINSTATEMENT_WINDOW_EXPIRED` — the employee to be `ACTIVE` (`ERR_EMPLOYEE_INACTIVE`), and the employer group to be `ACTIVE` (`ERR_GROUP_INACTIVE`), evaluated in that order. Reinstated coverage is treated as continuous for exclusion purposes — the policy's `coverage_start_date` is left unchanged.

Employees themselves are managed employer-side. A `CarrierAdmin` or `GroupAdmin` creates an employee with the `employer_group_id`, an `employee_ref` unique within that employer group (a duplicate is rejected with `ERR_INVALID_REQUEST`), a `full_name`, a `hire_date`, and optionally `preexisting_diagnosis_codes` (defaulting to an empty list); employees start `ACTIVE`. A `GroupAdmin` terminates (`ACTIVE` → `TERMINATED`) or reinstates (`TERMINATED` → `ACTIVE`) them; reinstatement requires the group to be `ACTIVE` or `SUSPENDED` (`ERR_GROUP_TERMINATED`). Notably, terminating an employee does not lapse their policies — issued and active policies remain in place awaiting explicit port or lapse.

### 3.5. Portability and Cancellation

When an employee leaves the group, their coverage can follow them. Porting (`ISSUED` → `PORTED` or `ACTIVE` → `PORTED`) is performed by `PolicyholderServices` and requires the employee to be `TERMINATED` — porting while the employee is still active fails with `ERR_PORT_NOT_ELIGIBLE`. The request carries a `new_premium_mode` naming `PRE_TAX` or `POST_TAX` — a missing or other value is rejected with `ERR_INVALID_REQUEST` — but the requester's choice is nominal: ported policies are direct-billed, so the policy's `premium_mode` is forced to `POST_TAX` regardless of the requested value, and the response reports `POST_TAX`. A ported policy drops out of the group's `enrolled_count` and must never be billed by the group's future payroll cycles — its `coverage_days` in any such cycle is zero.

Cancellation is the terminal path for discontinued coverage, available from `LAPSED` or `PORTED` (`→ CANCELLED`). It is blocked while the policy has any claim in flight — that is, any claim in `SUBMITTED`, `UNDER_REVIEW`, `APPEALED`, or `APPROVED` status — with `ERR_CLAIMS_IN_FLIGHT`. `DECLINED` and `CANCELLED` are the policy's two terminal states; applications are also declined by the system itself when a campaign closes `FAILED`, when the non-guaranteed-issue pre-existing screen trips, or when issuance finds no published schedule.

### 3.6. Claims: Documentation, Adjudication, and Payment

A claim is a demand for a fixed cash benefit tied to a covered event. Filing one — a shared capability of `PolicyholderServices` and `ClaimsAdjuster` — takes the `policy_id`, the `event_code`, the `service_date`, a `diagnosis_code` linking the event to the schedule, an optional `procedure_code` (default null), and a `claimed_occurrences` that must be an integer of at least 1 (otherwise `ERR_INVALID_REQUEST`). Filing imposes no other gate: the policy's status and the event code's coverage are not examined until review. The claim starts in `SUBMITTED`.

Review (`SUBMITTED` → `UNDER_REVIEW`) is the adjuster's first look, and it applies two gates: the policy must be in `ACTIVE`, `LAPSED`, or `PORTED` status — claims are reviewable on lapsed or ported policies when the service date fell within a covered period — else `ERR_POLICY_INACTIVE`; and the `event_code` must exist among the policy's pinned schedule's benefit items, else `ERR_EVENT_NOT_COVERED`. At review the system computes `provisional_payable_cents`, an estimate that is not ledger-binding.

The estimate, and later the final amount, come from the same threshold calculation evaluated at different instants. For the claim's `event_code`, the pinned schedule's benefit item gives the per-occurrence `benefit_amount_cents`, the `max_occurrences_per_year`, and the `lifetime_max_cents`. Let the paid-this-year count be the policy's `paid_occurrences_by_year` entry for the service date's calendar year and this event code, defaulting to zero. The remaining occurrences are that yearly cap minus the paid count, floored at zero; the remaining lifetime is the lifetime maximum minus the policy's `lifetime_paid_cents`, also floored at zero. The occurrences credited are the smaller of `claimed_occurrences` and the remaining occurrences; the uncapped amount is the per-occurrence benefit times the credited occurrences; and the payable amount is the smaller of that uncapped amount and the remaining lifetime. Only `PAID` claims feed the counters — approved-but-unpaid claims are invisible to both variants. The provisional variant evaluates this at review time against the current paid counters and merely stores an estimate in `provisional_payable_cents`. The final variant re-evaluates the identical formula at the adjudication instant; if paid counters advanced since review — another claim paid in between — the final amount can be lower than the provisional one, and only the final value, stored in `payable_amount_cents`, ever posts to the ledger.

Documentation flows alongside review. Attaching a document — again shared between `PolicyholderServices` and `ClaimsAdjuster` — takes the `claim_id`, a `doc_type` of `DIAGNOSIS_PROOF`, `PROCEDURE_PROOF`, `ITEMIZED_BILL`, or `ATTENDING_PHYSICIAN_STATEMENT` (any other value is rejected with `ERR_INVALID_REQUEST`), and an opaque `content_ref`; the owning claim must be in `UNDER_REVIEW` or `APPEALED`, else `ERR_INVALID_STATE`, and the document starts in `RECEIVED`. The adjuster then accepts (`RECEIVED` → `ACCEPTED`) or rejects (`RECEIVED` → `REJECTED`) each document; both actions require the claim to be in `UNDER_REVIEW` or `APPEALED` (`ERR_INVALID_STATE`), and both are terminal for the document.

Adjudication is the decision point, driven by the adjuster's `decision`; any `decision` value other than `APPROVE` or `DENY` — or its absence — is rejected with `ERR_INVALID_REQUEST`. An explicit `DENY` moves the claim to `DENIED` with `denial_reason` set to `NOT_COVERED`. An `APPROVE` runs a gauntlet whose checks have a fixed relative order, with documentation gates evaluated before clinical and fiscal gates — and between the two documentation checks, outstanding documents are reported before missing proof types. First, every document of the claim must be resolved — accepted or rejected; any document still `RECEIVED` rejects the approval with `ERR_DOCUMENTS_PENDING`. A rejected document counts as resolved: it never blocks this gate, and once every document is resolved the missing proof surfaces through the next check. Second, at least one `ACCEPTED` document of type `DIAGNOSIS_PROOF` or `ATTENDING_PHYSICIAN_STATEMENT` must exist, else `ERR_INSUFFICIENT_DOCUMENTS`. Third, the pre-existing exclusion: if the claim's `diagnosis_code` appears in the employee's `preexisting_diagnosis_codes` and the `service_date` falls before the policy's `coverage_start_date` plus the pinned schedule's `preexisting_exclusion_months` whole months, the approval is refused with `ERR_PRE_EXISTING_EXCLUSION` and the claim moves to `DENIED` with `denial_reason` `PRE_EXISTING`. Fourth, the fiscal caps: if the prior paid occurrences of this event code in the service date's calendar year already equal or exceed the benefit item's `max_occurrences_per_year` — zero remaining occurrences — or if the policy's `lifetime_paid_cents` already equals or exceeds the item's `lifetime_max_cents`, the claim is auto-denied with `denial_reason` `CAP_EXHAUSTED` (surfaced as `ERR_CAP_EXHAUSTED`). Otherwise the approval stands as a partial-or-full credit: the final variant of the payable calculation above determines `payable_amount_cents` and `adjudicated_occurrences` — both null until this moment — and the claim moves to `APPROVED`. Partial approval, where fewer occurrences are credited than claimed or the lifetime cap trims the amount, is a normal outcome, not a denial.

Payment (`APPROVED` → `PAID`) requires the policy to be in `ACTIVE`, `LAPSED`, or `PORTED` (`ERR_POLICY_INACTIVE`) and syncs the ledger of §2.7: the claim's `payable_amount_cents` is added to the policy's `lifetime_paid_cents`, and the `adjudicated_occurrences` are added to the policy's `paid_occurrences_by_year` entry for the service date's calendar year and event code. `PAID` is terminal — except for voiding. Voiding from `APPROVED` (`→ VOIDED`) touches no ledger, since nothing was ever paid, though `payable_amount_cents` is retained for audit. Voiding from `PAID` is a compensating reversal: the claim's amount is subtracted from `lifetime_paid_cents` and its occurrences subtracted from the corresponding `paid_occurrences_by_year` entry, restoring the invariants exactly.

A denied claim is not necessarily finished. `PolicyholderServices` may appeal (`DENIED` → `APPEALED`) within 180 days of the denial measured against the current clock — the denial instant is recorded at denial, and an appeal exactly 180 days after it still qualifies; only a later appeal fails with `ERR_APPEAL_WINDOW_EXPIRED`. An appealed claim re-enters review (`APPEALED` → `UNDER_REVIEW`), which recomputes the provisional estimate and restarts adjudication — the loop from review to denial to appeal and back to review can repeat.

### 3.7. The Annual Wellness Benefit

Separate from event-based claims, each policy earns one wellness benefit per calendar year. Filing one takes the `policy_id`, the `calendar_year` the service was performed in (which must be an integer, else `ERR_INVALID_REQUEST`), and the `service_date`; filing imposes no policy-status or waiting-period gate, and the benefit starts `SUBMITTED`. Approval (`SUBMITTED` → `APPROVED`) enforces four gates: the policy must be in `ACTIVE`, `LAPSED`, or `PORTED` (`ERR_POLICY_INACTIVE`); the `service_date` must be on or after the policy's `coverage_start_date` plus the pinned schedule's `wellness_waiting_months` whole months (`ERR_WELLNESS_WAITING_PERIOD`); the calendar year of the `service_date` must equal the claimed `calendar_year` (`ERR_INVALID_REQUEST`); and no other wellness benefit of the same policy may exist for the same `calendar_year` in `SUBMITTED`, `APPROVED`, or `PAID` status — denied rows do not block a refiling — else `ERR_WELLNESS_DUPLICATE_YEAR`. Approval copies `amount_cents` from the pinned schedule's `wellness_benefit_cents`. Denial (`SUBMITTED` → `DENIED`) is unconditional, and payment (`APPROVED` → `PAID`) completes the lifecycle — payment examines no policy status and posts nothing to the claims ledger of §2.7.

### 3.8. Payroll Deduction Cycles and Reconciliation

Premiums are collected through payroll. A `GroupAdmin` opens a deduction cycle for a group with an `employer_group_id`, a `period_start`, and a `period_end` strictly after the start (a `period_end` not strictly after `period_start` is rejected with `ERR_INVALID_REQUEST`); the period is half-open and the cycle starts `OPEN` with `total_posted_cents` at zero.

Finalization (`OPEN` → `FINALIZED`) is where billing happens, and it requires the group to be `ACTIVE` or `SUSPENDED` (`ERR_GROUP_TERMINATED`). At the finalize instant, the system examines every policy of the group's employees: those in `ISSUED` or `ACTIVE` status at that instant are billable, while `LAPSED`, `PORTED`, `DECLINED`, `CANCELLED`, and `APPLIED` policies are excluded entirely. Billability is all-or-nothing per cycle — the policy's status at the finalize instant decides the whole period, with no mid-period proration of status changes: a policy billable at finalize bills the full period's `coverage_days`, which is the number of whole days in the half-open period (end excluded); a non-billable policy contributes zero days. For each billable policy the system synthesizes a deduction line carrying the `payroll_cycle_id`, the `policy_id`, the `employee_id` copied from the policy, and a `tax_treatment` copied from the policy's `premium_mode` — `PRE_TAX` lines are excluded from taxable wage reporting, `POST_TAX` lines are not. Each line starts `POSTED`.

The line's `amount_cents` is prorated from the policy's `monthly_premium_cents` using the employer group's `proration_convention`, and the two variants differ in their rounding convention. Under `DAILY`, the premium is multiplied by the coverage days, divided by the days in the period, and the single product-then-divide result is rounded half-up to whole cents. Under `HALF_MONTH`, each half-month bucket is rounded first: half the premium is rounded half-up to whole cents per bucket, then multiplied by the number of buckets — two buckets when the coverage spans the full period, one when it spans a positive partial period, and zero when there is no coverage. Because billability is all-or-nothing, both variants charge the full-period amount for a billable policy and zero otherwise; the variants diverge on the rounding itself — for a premium of 9999 cents, the daily convention yields 9999 for a full period while the half-month convention rounds 4999.5 up to 5000 per bucket and yields 10000. Following §2.8, every line is rounded before any summing, and the cycle's `total_posted_cents` is the sum of `amount_cents` over its `POSTED` lines.

Lines can be disputed after finalization: a `GroupAdmin` reverses a line (`POSTED` → `REVERSED`), which is permitted only while the cycle is `FINALIZED` — once reconciled or closed, lines are immutable and the attempt fails with `ERR_CYCLE_NOT_REVERSIBLE`. The cycle's status is consulted before the line's own state, so reversing a line of a reconciled or closed cycle fails with `ERR_CYCLE_NOT_REVERSIBLE` even when the line itself is not `POSTED`; only when the cycle is `FINALIZED` does a non-`POSTED` line fail with `ERR_INVALID_STATE`. Reversal compensates the cycle: the line's `amount_cents` is subtracted from `total_posted_cents`, keeping the invariant that the cycle total always equals the sum over its posted lines. A `CarrierAdmin` then reconciles (`FINALIZED` → `RECONCILED`) — a gate that requires every line of the cycle to be in `POSTED` or `REVERSED`, which always holds at rest, so reconciliation effectively demands that any disputes have been resolved first — and finally closes the cycle (`RECONCILED` → `CLOSED`).

## 4. Endpoint Definitions

Operations that create new resources return a `201 Created` status code. Operations that modify an existing resource — state transitions, issuance, adjudication, payment, and the clock — return a `200 OK` status code. The clock endpoint takes `to_iso8601` in the request body (its absence is `ERR_INVALID_REQUEST`) and returns a data object of the form `{"current_utc": "<ISO 8601 instant>"}`. Where the table below describes a list endpoint as "filterable", the supported exact-match query-parameter filters are: `/enrollment-campaigns` — `employer_group_id`, `counselor_id`, `status`; `/policies` — `campaign_id`, `employee_id`, `policy_series_id`, `benefit_schedule_id`, `status`; `/claims` — `policy_id`, `status`; `/wellness-benefits` — `policy_id`, `calendar_year`, `status`; `/deduction-lines` — `payroll_cycle_id`, `policy_id`, `employee_id`, `status`. Nested list endpoints additionally accept a `status` filter on top of their implied parent scoping.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock to `to_iso8601`; returns `current_utc` | CarrierAdmin, GroupAdmin, BenefitCounselor, ClaimsAdjuster, PolicyholderServices |
| POST | `/employer-groups` | Create an employer group (PROSPECT) | CarrierAdmin |
| GET | `/employer-groups/{id}` | Get an employer group with computed counters | CarrierAdmin, GroupAdmin, BenefitCounselor |
| GET | `/employer-groups` | List employer groups (paginated, `status` filter) | CarrierAdmin, GroupAdmin, BenefitCounselor |
| POST | `/employer-groups/{id}/activate` | PROSPECT or SUSPENDED to ACTIVE | CarrierAdmin |
| POST | `/employer-groups/{id}/suspend` | ACTIVE to SUSPENDED; locks open campaigns | CarrierAdmin |
| POST | `/employer-groups/{id}/terminate` | ACTIVE or SUSPENDED to TERMINATED; lapses policies, closes campaigns | CarrierAdmin |
| GET | `/employer-groups/{id}/employees` | List employees of a group | CarrierAdmin, GroupAdmin, BenefitCounselor |
| GET | `/employer-groups/{id}/enrollment-campaigns` | List campaigns of a group | CarrierAdmin, GroupAdmin, BenefitCounselor |
| GET | `/employer-groups/{id}/payroll-cycles` | List payroll cycles of a group | CarrierAdmin, GroupAdmin |
| POST | `/benefit-counselors` | Create a benefit counselor (ACTIVE) | CarrierAdmin |
| GET | `/benefit-counselors/{id}` | Get a counselor | CarrierAdmin, BenefitCounselor |
| POST | `/benefit-counselors/{id}/suspend` | ACTIVE to SUSPENDED | CarrierAdmin |
| POST | `/benefit-counselors/{id}/activate` | SUSPENDED to ACTIVE | CarrierAdmin |
| POST | `/benefit-counselors/{id}/terminate` | ACTIVE or SUSPENDED to TERMINATED (blocked while leading an OPEN campaign) | CarrierAdmin |
| GET | `/benefit-counselors/{id}/enrollment-campaigns` | List campaigns led by a counselor | CarrierAdmin, BenefitCounselor |
| POST | `/enrollment-campaigns` | Create a campaign (DRAFT) | CarrierAdmin, BenefitCounselor |
| GET | `/enrollment-campaigns/{id}` | Get a campaign | CarrierAdmin, GroupAdmin, BenefitCounselor |
| GET | `/enrollment-campaigns` | List campaigns; filterable | CarrierAdmin, GroupAdmin, BenefitCounselor |
| POST | `/enrollment-campaigns/{id}/open` | DRAFT to OPEN | BenefitCounselor |
| POST | `/enrollment-campaigns/{id}/lock` | OPEN to LOCKED (requires clock at or past window end) | BenefitCounselor |
| POST | `/enrollment-campaigns/{id}/close` | LOCKED to MET or FAILED by participation; MET or FAILED to CLOSED; OCC on employer group | BenefitCounselor |
| POST | `/enrollment-campaigns/{id}/reopen` | FAILED to OPEN with extended window | BenefitCounselor |
| GET | `/enrollment-campaigns/{id}/policies` | List policies applied under a campaign | CarrierAdmin, GroupAdmin, BenefitCounselor |
| POST | `/policy-series` | Create a policy series (DRAFT) | CarrierAdmin |
| GET | `/policy-series/{id}` | Get a series | CarrierAdmin, BenefitCounselor, ClaimsAdjuster |
| GET | `/policy-series/{id}/benefit-schedules` | List schedules of a series | CarrierAdmin, BenefitCounselor, ClaimsAdjuster |
| POST | `/policy-series/{id}/activate` | DRAFT to ACTIVE (requires a PUBLISHED schedule) | CarrierAdmin |
| POST | `/policy-series/{id}/retire` | ACTIVE to RETIRED | CarrierAdmin |
| GET | `/policy-series/{id}/policies` | List policies of a series | CarrierAdmin, ClaimsAdjuster |
| POST | `/benefit-schedules` | Create a benefit schedule (DRAFT) | CarrierAdmin |
| GET | `/benefit-schedules/{id}` | Get a schedule | CarrierAdmin, BenefitCounselor, ClaimsAdjuster |
| POST | `/benefit-schedules/{id}/publish` | DRAFT to PUBLISHED; supersedes prior published schedule; OCC on policy series | CarrierAdmin |
| POST | `/employees` | Create an employee (ACTIVE) | CarrierAdmin, GroupAdmin |
| GET | `/employees/{id}` | Get an employee | CarrierAdmin, GroupAdmin, BenefitCounselor |
| POST | `/employees/{id}/terminate` | ACTIVE to TERMINATED | GroupAdmin |
| POST | `/employees/{id}/reinstate` | TERMINATED to ACTIVE | GroupAdmin |
| GET | `/employees/{id}/policies` | List policies of an employee | CarrierAdmin, GroupAdmin, BenefitCounselor, ClaimsAdjuster, PolicyholderServices |
| POST | `/policies` | Apply for a policy under a campaign (APPLIED) | BenefitCounselor |
| GET | `/policies/{id}` | Get a policy | CarrierAdmin, GroupAdmin, BenefitCounselor, ClaimsAdjuster, PolicyholderServices |
| GET | `/policies` | List policies; filterable | CarrierAdmin, GroupAdmin, BenefitCounselor, ClaimsAdjuster, PolicyholderServices |
| POST | `/policies/{id}/issue` | APPLIED to ISSUED (direct issuance outside bulk close) | BenefitCounselor |
| POST | `/policies/{id}/activate` | ISSUED to ACTIVE | BenefitCounselor |
| POST | `/policies/{id}/lapse` | ISSUED or ACTIVE to LAPSED | BenefitCounselor |
| POST | `/policies/{id}/reinstate` | LAPSED to ACTIVE within 60 days | BenefitCounselor |
| POST | `/policies/{id}/port` | ISSUED or ACTIVE to PORTED when employee terminated; forces POST_TAX | PolicyholderServices |
| POST | `/policies/{id}/cancel` | LAPSED or PORTED to CANCELLED (no in-flight claims) | PolicyholderServices |
| POST | `/claims` | Submit a claim (SUBMITTED) | PolicyholderServices, ClaimsAdjuster |
| GET | `/claims/{id}` | Get a claim | CarrierAdmin, ClaimsAdjuster, PolicyholderServices |
| GET | `/claims` | List claims; filterable | CarrierAdmin, ClaimsAdjuster, PolicyholderServices |
| POST | `/claims/{id}/review` | SUBMITTED or APPEALED to UNDER_REVIEW; computes provisional payable | ClaimsAdjuster |
| POST | `/claims/{id}/adjudicate` | UNDER_REVIEW to APPROVED or DENIED per decision; auto-deny branches apply | ClaimsAdjuster |
| POST | `/claims/{id}/pay` | APPROVED to PAID; posts to policy ledger | ClaimsAdjuster |
| POST | `/claims/{id}/appeal` | DENIED to APPEALED within 180 days | PolicyholderServices |
| POST | `/claims/{id}/void` | APPROVED or PAID to VOIDED; reverses ledger postings for paid claims | ClaimsAdjuster |
| GET | `/claims/{id}/documents` | List documents of a claim | CarrierAdmin, ClaimsAdjuster, PolicyholderServices |
| POST | `/claim-documents` | Attach a document to a claim (RECEIVED) | PolicyholderServices, ClaimsAdjuster |
| GET | `/claim-documents/{id}` | Get a document | CarrierAdmin, ClaimsAdjuster, PolicyholderServices |
| POST | `/claim-documents/{id}/accept` | RECEIVED to ACCEPTED | ClaimsAdjuster |
| POST | `/claim-documents/{id}/reject` | RECEIVED to REJECTED | ClaimsAdjuster |
| POST | `/wellness-benefits` | Submit an annual wellness benefit (SUBMITTED) | PolicyholderServices, ClaimsAdjuster |
| GET | `/wellness-benefits/{id}` | Get a wellness benefit | CarrierAdmin, ClaimsAdjuster, PolicyholderServices |
| GET | `/wellness-benefits` | List wellness benefits; filterable | CarrierAdmin, ClaimsAdjuster, PolicyholderServices |
| POST | `/wellness-benefits/{id}/approve` | SUBMITTED to APPROVED (waiting period, duplicate-year, and year-match gates) | ClaimsAdjuster |
| POST | `/wellness-benefits/{id}/deny` | SUBMITTED to DENIED | ClaimsAdjuster |
| POST | `/wellness-benefits/{id}/pay` | APPROVED to PAID | ClaimsAdjuster |
| POST | `/payroll-cycles` | Create a payroll cycle (OPEN) | GroupAdmin |
| GET | `/payroll-cycles/{id}` | Get a payroll cycle | CarrierAdmin, GroupAdmin |
| POST | `/payroll-cycles/{id}/finalize` | OPEN to FINALIZED; synthesizes deduction lines | GroupAdmin |
| POST | `/payroll-cycles/{id}/reconcile` | FINALIZED to RECONCILED | CarrierAdmin |
| POST | `/payroll-cycles/{id}/close` | RECONCILED to CLOSED | CarrierAdmin |
| GET | `/payroll-cycles/{id}/deduction-lines` | List deduction lines of a cycle | CarrierAdmin, GroupAdmin |
| GET | `/deduction-lines` | List deduction lines; filterable by cycle, policy, employee | CarrierAdmin, GroupAdmin |
| GET | `/deduction-lines/{id}` | Get a deduction line | CarrierAdmin, GroupAdmin |
| POST | `/deduction-lines/{id}/reverse` | POSTED to REVERSED (cycle must be FINALIZED); compensates cycle total | GroupAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_REFERENTIAL_INTEGRITY` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_GROUP_INACTIVE` | 422 |
| `ERR_GROUP_TERMINATED` | 422 |
| `ERR_COUNSELOR_INACTIVE` | 422 |
| `ERR_CAMPAIGN_WINDOW_OVERLAP` | 409 |
| `ERR_COUNSELOR_DOUBLE_BOOKED` | 409 |
| `ERR_WINDOW_EXPIRED` | 422 |
| `ERR_WINDOW_NOT_CLOSED` | 422 |
| `ERR_SERIES_WITHOUT_SCHEDULE` | 422 |
| `ERR_SERIES_RETIRED` | 422 |
| `ERR_SCHEDULE_VERSION_CONFLICT` | 409 |
| `ERR_DUPLICATE_COVERAGE` | 409 |
| `ERR_EMPLOYEE_INACTIVE` | 422 |
| `ERR_PORT_NOT_ELIGIBLE` | 422 |
| `ERR_REINSTATEMENT_WINDOW_EXPIRED` | 422 |
| `ERR_CLAIMS_IN_FLIGHT` | 422 |
| `ERR_POLICY_INACTIVE` | 422 |
| `ERR_EVENT_NOT_COVERED` | 422 |
| `ERR_DOCUMENTS_PENDING` | 422 |
| `ERR_INSUFFICIENT_DOCUMENTS` | 422 |
| `ERR_PRE_EXISTING_EXCLUSION` | 422 |
| `ERR_CAP_EXHAUSTED` | 422 |
| `ERR_APPEAL_WINDOW_EXPIRED` | 422 |
| `ERR_WELLNESS_WAITING_PERIOD` | 422 |
| `ERR_WELLNESS_DUPLICATE_YEAR` | 422 |
| `ERR_CYCLE_NOT_REVERSIBLE` | 409 |
