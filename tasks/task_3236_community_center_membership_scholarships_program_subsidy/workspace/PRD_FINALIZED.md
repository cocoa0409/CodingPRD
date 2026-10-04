# Community Center Membership API — Product Requirements Document

## 1. Introduction

Community associations like the YMCA operate on a distinctive financial bargain: households pay monthly dues for access to pools, gyms, studios, and programs, but the association's charitable mission guarantees that inability to pay the full price never excludes a family from membership. Delivering on that bargain at scale demands machinery that ordinary retail systems do not have — a sliding-scale subsidy engine keyed to documented household income against area median income, a per-branch scholarship pool that is funded by fundraising campaigns and must never be over-obligated, and a billing model where monthly drafts, holds, delinquency, and lapse interact with the subsidy itself.

This document specifies the REST API for one such community-center platform. A single **Association** governs many **Branch** facilities. Each branch offers **MembershipCategory** price plans keyed to household composition, enrolls households into **Membership** agreements billed by monthly **BillingDraft** collection, runs **Program** offerings (swim lessons, childcare, camps, sports) delivered as dated **ProgramSession** instances with **Registration** rosters and waitlists, and schedules **FacilitySpace** inventory through **FacilityReservation** bookings that must coexist with member drop-in use. An annual association-wide **Campaign** raises **Donation** gifts whose scholarship-designated receipts fund each branch's pool, and **ScholarshipApplication** adjudication converts verified income documentation into an award fraction that discounts dues and program fees for a year at a time.

The platform must also honor the movement's social-contract details that distinguish it from a generic gym: nationwide reciprocity lets visiting members from other associations use branches at a defined surcharge; licensed childcare sessions enforce statutory staff-to-child ratios that cap effective capacity and even reorder waitlist promotion; membership holds give households a generous but bounded escape valve (no more than 120 hold days in any trailing 365); and every dollar of scholarship money is conserved — pool receipts, obligations, releases, and refunds reconcile exactly at all times. Where multiple writers could race on a shared record, the API uses explicit optimistic concurrency rather than silent last-write-wins.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID` identifying the acting principal and `X-User-Role` naming one of the declared roles. A request missing `X-User-Role`, carrying a role string the API does not declare, or omitting `X-User-ID` when the role is entity-backed is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is valid but not permitted for the endpoint — or where a `Member` attempts to act on a resource they do not own — is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The declared roles, spelled exactly as the API expects them, are:

- **`AssociationAdmin`** — association-level administrator; owns associations, branches, campaigns, donation refunds, BLACKOUT facility reservations, and the test-driving logical clock.
- **`BranchDirector`** — branch executive; adjudicates scholarship applications, approves or denies facility reservations, and reinstates lapsed memberships.
- **`ProgramCoordinator`** — runs programs and sessions at a branch; creates programs, assigns session staff, and closes registration early.
- **`FrontDesk`** — front-desk staff; registers members, takes payments, and books on behalf of members. Holds no exclusive operations.
- **`Member`** — an entity-backed member acting on their own resources. When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member` record; ownership checks on any resource that references a `Member` compare the resource's foreign-key field (such as `primary_member_id`, `applicant_member_id`, or `member_id`) to `X-User-ID`. Only the applicant member may resubmit documentation on their own application.
- **`BoardMember`** — association or branch board volunteer with read-only governance visibility; holds no exclusive or mutating operations.

When `X-User-Role` is `AssociationAdmin`, `BranchDirector`, `ProgramCoordinator`, `FrontDesk`, or `BoardMember`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record such identifiers for audit purposes but never compares them to any entity's `id`.
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

List endpoints accept two optional query parameters, `limit` and `offset`. `limit` defaults to 10, with a minimum of 1 and a maximum of 100; `offset` defaults to 0. Every list response includes the pagination fields `limit`, `offset`, `total_count`, and `has_more` in its `meta` object, where `total_count` is the full count of matching records and `has_more` reports whether further records exist beyond the current window. Unless an endpoint states otherwise, list results are sorted by `created_at` in ascending order.

### 2.4. Common Resource Properties and Money Semantics

Every persisted resource carries a server-minted `id` that is a UUID with no type prefix, plus `created_at` and `updated_at` timestamps in ISO 8601 UTC with three fractional digits, and an integer `version` that starts at 1 on creation and increments by exactly 1 on every mutation of the record. All fourteen entity types — `Association`, `Branch`, `MembershipCategory`, `Member`, `Membership`, `BillingDraft`, `ScholarshipApplication`, `Program`, `ProgramSession`, `Registration`, `FacilitySpace`, `FacilityReservation`, `Campaign`, and `Donation` — follow this common-field contract.

All monetary quantities are integer cents; no fractional-cent values ever persist. Whenever a calculation produces a non-integer cent result, the final amount is rounded half-up to the nearest whole cent. Ratios and multipliers used mid-calculation follow their own precision rules as stated where each calculation is defined; multipliers themselves are never rounded.

### 2.5. Optimistic Concurrency Control

Three write operations require the caller to present the version of a parent entity as last observed, and reject a stale presentation with `ERR_STALE_VERSION` (HTTP 412):

- Approving a scholarship application requires the request to carry `expected_membership_version` equal to the membership's current `version`. Because the award writes `assistance_pct` onto the membership and re-prices its pending drafts, a stale view — for example a category change or hold applied after the director's review screen loaded — fails closed rather than overwriting newer state.
- Updating a membership's mutable fields (a `category_id` change or a `member_ids` household edit) requires `expected_membership_version` matching the membership's current `version`, so an operator editing household composition cannot silently overwrite a category change or assistance award that landed on the same row in the meantime.
- Closing a campaign requires `expected_campaign_version` matching the campaign's current `version`; donations received in between advance the version, and a stale close is rejected so the frozen match tier reflects the true final attainment rather than a snapshot.

Endpoints not named above do not take any version field. A version mismatch is always `ERR_STALE_VERSION` with HTTP 412.

### 2.6. The Logical Clock and Scheduled Transitions

The server maintains a logical clock whose startup value is exactly 2026-09-01T00:00:00Z; the server must never consult wall-clock time. An admin-only test-driving capability advances the logical clock to a supplied `current_utc` instant, and every clock-driven transition evaluates against this logical clock: a held membership resumes automatically when the clock reaches `hold_until`; a session flips from `SCHEDULED` to `REG_OPEN` when the clock reaches `member_opens_on`, from `REG_OPEN` to `REG_CLOSED` at the end of its `start_on` day, and from `REG_CLOSED` to `COMPLETED` once the clock passes `end_on`; an approved facility reservation completes when the clock passes its `end_at`; an approved scholarship award expires when the clock reaches `award_end_on`; and a membership lapses after its draft status has remained `DELINQUENT` for 45 consecutive days.

### 2.7. Validation Priority Order

When several checks could reject the same request, they are evaluated in a fixed priority order so the surfaced error is deterministic. Authentication (missing or malformed identity headers, `ERR_UNAUTHENTICATED`) comes first, then authorization and member-ownership checks (`ERR_UNAUTHORIZED`). Existence of every path identifier follows (`ERR_NOT_FOUND`), then resolution of body foreign keys (`ERR_BRANCH_NOT_FOUND`, `ERR_CATEGORY_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_SPACE_NOT_FOUND`, `ERR_SESSION_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`). Next come state-legality checks (`ERR_INVALID_STATE`, `ERR_CAMPAIGN_NOT_ACTIVE`, `ERR_ALREADY_TERMINAL`), then request-schema and composition checks (`ERR_INVALID_REQUEST`, `ERR_DOCUMENTATION_MISSING`, `ERR_HOUSEHOLD_CAP_EXCEEDED`, `ERR_TIME_RANGE_INVALID`). Childcare licensing-ratio safety is checked after that (`ERR_RATIO_CAPACITY_EXCEEDED`), followed by temporal-window rules (`ERR_REGISTRATION_WINDOW_CLOSED`, `ERR_MEMBER_PRIORITY_ONLY`, `ERR_HOLD_WINDOW_INVALID`, `ERR_PARTICIPANT_AGE_INVALID`, `ERR_MEMBER_ONLY_PROGRAM`), then capacity-and-uniqueness constraints (`ERR_SESSION_FULL`, `ERR_SPACE_CONFLICT`, `ERR_DUPLICATE_ACTIVE_AWARD`, `ERR_CAMPAIGN_ALREADY_ACTIVE`, `ERR_DUPLICATE_DRAFT`, `ERR_DUPLICATE_EMAIL`, `ERR_DUPLICATE_BRANCH_CODE`). Fiscal limits are evaluated second to last (`ERR_POOL_EXHAUSTED`, `ERR_POOL_WOULD_GO_NEGATIVE`, `ERR_AWARD_INELIGIBLE`, `ERR_HOLD_ALLOWANCE_EXCEEDED`, `ERR_REINSTATE_WINDOW_PASSED`), and the optimistic-concurrency stale-version check (`ERR_STALE_VERSION`) runs last of all.

### 2.8. The Scholarship Pool Conservation Law

Each branch maintains three counters on its record: `scholarship_pool_received_cents` (the sum of `amount_cents` over donations credited to that branch whose status is `RECEIVED` and whose `designation` is `SCHOLARSHIP`), `scholarship_pool_obligated_cents` (the sum of `award_obligation_cents` over the branch's applications in `APPROVED` status), and `scholarship_pool_available_cents`, which always equals receipts minus obligations and is never allowed to go negative. The stored counters are recomputed eagerly on every triggering mutation — donation receipt or refund, award approval, award expiry, or the cancellation or lapse of an awarded membership — and an audit read that replays donation and application state events in `created_at` ascending order must arrive at exactly the same value; the compensating refund transition is what keeps both consistent. A branch also tracks `active_membership_count`, the count of its memberships whose status is `ACTIVE` or `ON_HOLD`.

## 3. Business Logic & Workflows

### 3.1. Standing Up the Association and Its Branches

Before anything else exists, an `AssociationAdmin` creates the `Association`, supplying its legal `name`, whether `reciprocity_enabled` is on (it defaults to true), the `ami_base_cents` area median income for a one-person household in cents, and the active `campaign_year`. The AMI figure is the anchor for every sliding-scale decision the association will ever make, so it lives at the association level and is resolved downward through each branch.

Branches come next, also created by an `AssociationAdmin` with their owning `association_id`, a `code` that must be unique within the association (a reused code is rejected with `ERR_DUPLICATE_BRANCH_CODE`), a display `name`, and the branch's `branch_goal_cents` share of the association campaign goal. A freshly created branch starts with all three scholarship pool counters and its `active_membership_count` at zero. A body `branch_id` that does not resolve to an existing branch is rejected with `ERR_BRANCH_NOT_FOUND`; likewise a body `association_id` that does not resolve is a foreign-key failure.

Each branch then publishes its `MembershipCategory` price plans. A category record carries the offering `branch_id`, a display `name`, a `household_type` of exactly one of `ADULT`, `TWO_ADULT`, `FAMILY`, `SENIOR`, `YOUNG_ADULT`, or `TEEN`, the one-time `joining_fee_cents`, the standard `monthly_dues_cents` before assistance, the household caps `max_adults` and `max_dependents`, and an optional `hold_fee_cents` that defaults to 1000 cents — the flat monthly draft charged while a membership of this category is on hold. Categories may be listed and filtered by `branch_id` or `household_type`.

People enter the system as `Member` records registered by `FrontDesk`, `BranchDirector`, or `AssociationAdmin` staff, with `full_name`, an `email` that must be unique across the association (a duplicate is `ERR_DUPLICATE_EMAIL`, HTTP 409), a `birth_date` in ISO date form that determines adult-versus-dependent standing and age-gated program eligibility, a `home_branch_id`, and optionally a `visiting_association_name`. The visiting field is set only for reciprocity visitors from another association and stays null for home members; it is the signal that later drives the reciprocity surcharge on program fees. Any unresolved member reference — whether it arrives as `primary_member_id`, `member_id`, `applicant_member_id`, `donor_member_id`, or `renter_member_id` — is `ERR_MEMBER_NOT_FOUND`.

### 3.2. Joining: Memberships and the First Bill

Joining creates a `Membership` at a branch, performed by `FrontDesk`, the joining `Member` themselves, a `BranchDirector`, or an `AssociationAdmin`. The request names the `branch_id`, the `category_id`, the `primary_member_id` (the adult responsible for billing), and the full `member_ids` roster including the primary. The category must belong to the same branch as the membership; a `category_id` that does not resolve or that belongs to a different branch is `ERR_CATEGORY_NOT_FOUND`.

Household composition is validated against the category caps at join time. Adults are members aged at least 18, dependents are younger than 18, both derived from each member's `birth_date`; a roster whose adult count exceeds `max_adults` or whose dependent count exceeds `max_dependents` is rejected with `ERR_HOUSEHOLD_CAP_EXCEEDED`.

A new membership is born with `status` `ACTIVE`, `draft_status` `CURRENT`, `version` 1, and an `anniversary_day` equal to the day-of-month of the activation date capped at 28, which is the day each month on which the recurring draft runs. The joining fee actually charged is recorded in `joining_fee_charged_cents`: normally the category's `joining_fee_cents`, but the fee is waived to zero when the primary member previously held a `CANCELLED` or `LAPSED` membership at the same branch whose terminal date falls within 30 days of this activation. Activation immediately creates the first billing artifacts: a `BillingDraft` of kind `JOINING_FEE` when the charged fee is greater than zero, plus a `BillingDraft` of kind `REGULAR` covering the activation month. That first regular draft is prorated — its `amount_cents` is the full assisted monthly amount multiplied by the number of remaining days in the activation month counted inclusively from the activation day, divided by the total days in the activation month, rounded half-up to integer cents. The branch's `active_membership_count` increases by one.

Staff may later update a membership's `category_id` or `member_ids` roster through a modification request that must carry `expected_membership_version`; the stale-version rule of §2.5 applies, and a successful update increments the membership's `version` by one. A category change re-prices any future `PENDING` drafts under the new category's dues and hold fee. Household-cap validation applies to the edited roster exactly as at join.

### 3.3. Holds, Billing Failures, Delinquency, Lapse, and Reinstatement

A membership carries two parallel state dimensions on the same row. The `status` dimension runs `ACTIVE`, `ON_HOLD`, `LAPSED`, and the terminal `CANCELLED`. The `draft_status` dimension runs `CURRENT`, `RETRY_PENDING`, and `DELINQUENT`. Billing failures move only the draft dimension; 45 consecutive days of delinquency is what moves the status dimension to `LAPSED`.

**Placing a hold.** A `Member` or `BranchDirector` may place an `ACTIVE` membership on hold by supplying a `hold_until` date; attempting it from any other status is `ERR_INVALID_STATE`. The hold duration — `hold_until` measured from the current date — must be at least 30 days and at most 180 days, and `hold_until` must be in the future, else the request is rejected with `ERR_HOLD_WINDOW_INVALID`. The trailing allowance is then checked: the system gathers every hold window of the membership, each window running from its `hold_started_on` to the earlier of its `hold_until` and its actual resume date when it was resumed early, clips every window to the trailing 365 days ending today, merges overlapping or adjacent clipped intervals (a gap of zero days merges), and sums the merged lengths into `hold_days_used_trailing_12mo`. The new request is allowed only when that total plus the requested hold days is at most 120 days — a total of exactly 120 days is allowed, and 121 is rejected with `ERR_HOLD_ALLOWANCE_EXCEEDED`. On success `hold_started_on` records the current date, `hold_until` records the requested end (exclusive), and every future draft during the hold is created with `kind` `HOLD_FEE` at the category's `hold_fee_cents` rather than regular dues.

**Resuming.** A hold ends when the logical clock reaches `hold_until`, or earlier when a `Member` or `BranchDirector` resumes the membership. Either way the status returns `ON_HOLD` → `ACTIVE`, `hold_days_used_trailing_12mo` is recomputed by the interval merge, and the next regular draft resumes at the full assisted dues amount.

**Monthly drafts.** A `BranchDirector` or `AssociationAdmin` creates each month's draft; the period is inferred from the logical clock and the membership's `anniversary_day`, and recorded on the draft as `period_month` in YYYY-MM form. Only one draft may exist per membership per `period_month` — a second is `ERR_DUPLICATE_DRAFT`. The draft's `amount_cents` is computed by first selecting the base: when the membership is `ON_HOLD` the base is the category's `hold_fee_cents` and the draft `kind` is `HOLD_FEE`; otherwise the base is the category's `monthly_dues_cents` and the `kind` is `REGULAR`. The amount is then that base multiplied by one minus the membership's `assistance_pct`, rounded half-up to integer cents. This base-first, assistance-second ordering is deliberate: assistance discounts dues, but hold status changes what the dues are. Creating a draft increments the membership's `version` by one.

**Failure and retry.** Recording a failed collection attempt — a `BranchDirector` or `AssociationAdmin` action — is legal while the draft is `PENDING` or `FAILED` and its `attempt_count` is below 3. Each failure increments `attempt_count` and sets the draft's `status` to `FAILED`. When the count reaches 3, the membership's `draft_status` flips to `DELINQUENT` and `delinquent_since` records the current date; before that threshold the draft dimension sits in `RETRY_PENDING`.

**Settlement.** A `Member`, `BranchDirector`, or `FrontDesk` operator may settle a `PENDING` or `FAILED` draft, marking it `PAID` and adding its `amount_cents` to the membership's `lifetime_billed_cents` — the conserved billing quantity that accumulates successfully drafted cents minus reversals. When no `FAILED` drafts remain for the membership, `draft_status` returns to `CURRENT`; settling the last failed draft of a delinquent membership also clears `delinquent_since` and cancels the 45-day lapse countdown.

**Lapse and reinstatement.** Once `draft_status` has remained `DELINQUENT` for 45 consecutive days, the system moves the membership `ACTIVE` → `LAPSED`, stamps `lapsed_on` with the current date, expires any approved scholarship award on the membership with the pool-release cascade described in §3.4, and decrements the branch's `active_membership_count`. A `BranchDirector` may reinstate a `LAPSED` membership within 90 days of `lapsed_on` — attempting it later, or while any draft of the membership remains `FAILED` and unsettled, is rejected with `ERR_REINSTATE_WINDOW_PASSED`. Reinstatement returns the status to `ACTIVE`, the draft dimension to `CURRENT`, clears `delinquent_since`, and increments `active_membership_count`.

**Cancellation.** A `Member` or `BranchDirector` may cancel from either `ACTIVE` or `ON_HOLD`. Cancellation is terminal, releases any approved award exactly as lapse does, resets the membership's `assistance_pct` to 0, and decrements the branch's `active_membership_count`. Once `CANCELLED`, any further transition attempt on the membership is `ERR_ALREADY_TERMINAL`.

### 3.4. Financial Assistance: The Sliding Scale and the Branch Pool

A household applies for assistance by submitting a `ScholarshipApplication` at its branch — the applying `Member`, a `FrontDesk` operator on their behalf, or a `BranchDirector` may file it. The application names the `branch_id`, the `membership_id` it would subsidize, the `applicant_member_id` (which must be the membership's primary member), the `household_size` (an integer from 1 to 12), the documented `annual_income_cents` gross annual household income, and a `documentation` array naming the kinds of evidence supplied: `TAX_RETURN`, `PAY_STUB`, or `BENEFITS_LETTER`. At least one such document kind is required; an empty or unrecognized documentation array is rejected with `ERR_DOCUMENTATION_MISSING` (HTTP 400). When the application renews a prior expired award, it also carries `renews_application_id` linking to that prior `EXPIRED` application; an unresolvable link is `ERR_APPLICATION_NOT_FOUND`.

**The income ratio and the tiers.** At submission the system computes two informational fields. The household multiplier is 0.80 plus 0.20 times the household size capped at 12 — so a household of one yields 1.00, two yields 1.20, four yields 1.60, and twelve yields 3.20 — expressed with two decimal places rounded half-up. The `income_ratio` is then the `annual_income_cents` divided by the product of the association's `ami_base_cents` and that household multiplier, rounded to four decimal places half-up before any tier comparison is made. The provisional tier is written to `preview_award_pct`: a ratio strictly below 0.30 previews 0.75; a ratio of exactly 0.30 or above but strictly below 0.50 previews 0.50; a ratio of exactly 0.50 or above but strictly below 0.80 previews 0.25; and a ratio of exactly 0.80 or above is ineligible. The preview is informational only — it obligates nothing from the pool and never touches the membership's `assistance_pct`. A new application is born in `SUBMITTED` status with `award_pct` still null.

**Adjudication.** A `BranchDirector` moves the application `SUBMITTED` → `UNDER_REVIEW` (a review attempt from any other status is `ERR_INVALID_STATE`). From `UNDER_REVIEW` the director may either push the application to `MORE_INFO_REQUIRED` or decide it. When more information is requested, only the applicant member — the acting `X-User-ID` must equal the application's `applicant_member_id`, else `ERR_UNAUTHORIZED` — may supply further `documentation` (again requiring at least one recognized kind, else `ERR_DOCUMENTATION_MISSING`) and optionally corrected `annual_income_cents` or `household_size`, cycling the application back to `UNDER_REVIEW`. Resubmission recomputes `income_ratio` and `preview_award_pct` from the updated inputs. The `UNDER_REVIEW` → `MORE_INFO_REQUIRED` → `UNDER_REVIEW` cycle may repeat as often as the director and applicant need.

**Approval** is the fiscal commit point, and the director's approval request must carry `expected_membership_version` under the §2.5 stale-version rule. Approval enforces its checks in the global priority order of §2.7 — state legality first, then the capacity-and-uniqueness rule, then the fiscal limits, with the version check last. Concretely: the final `income_ratio` is recomputed from the verified inputs and must yield an `award_pct` among 0.25, 0.50, or 0.75 — a ratio at or above the 0.80 ceiling is ineligible and the application must be denied instead; approving it anyway is `ERR_AWARD_INELIGIBLE`. No other application for the same membership may currently be `APPROVED`, else `ERR_DUPLICATE_ACTIVE_AWARD`. And the branch's `scholarship_pool_available_cents` must be at least the annualized obligation — twelve times the category's `monthly_dues_cents` times the `award_pct` — else the approval fails with `ERR_POOL_EXHAUSTED`. Because verified income may differ from the declared figures, the final `award_pct` can legitimately differ from `preview_award_pct`.

A successful approval writes `award_pct`, computes `award_obligation_cents` as that annualized amount, sets `award_start_on` to the current date and `award_end_on` to `award_start_on` plus 365 days (the annual renewal boundary), and cascades: the membership's `assistance_pct` becomes the awarded fraction and the membership's `version` increments by one; the branch's `scholarship_pool_obligated_cents` increases by `award_obligation_cents`, which lowers `scholarship_pool_available_cents` by the same amount; and every `PENDING` draft of the membership has its `amount_cents` recomputed under the new assistance fraction. Denial is the sibling decision: `UNDER_REVIEW` → `DENIED`, with no side effects, and like approval it is terminal.

**Expiry.** When the clock reaches `award_end_on`, or when the underlying membership is cancelled or lapses, an approved application moves to `EXPIRED`. Expiry releases the obligation: the branch's `scholarship_pool_obligated_cents` decreases by `award_obligation_cents`, raising the available pool accordingly. The membership's `assistance_pct` returns to 0 — unless a renewal application whose `renews_application_id` points at this application is already `APPROVED`, in which case the renewal's `award_pct` applies instead, keeping the household's discount continuous across the annual boundary.

### 3.5. Programs, Sessions, and the Registration Marketplace

A `ProgramCoordinator`, `BranchDirector`, or `AssociationAdmin` creates a `Program` at a branch, with a `name`, a `kind` of `SWIM_LESSON`, `CHILDCARE`, `CAMP`, or `SPORTS`, the full `base_fee_cents` member fee before discounts, and several behavioral switches. `member_only` (default false) restricts registration to members of the association. `member_priority_days` (default 0) sets how many days before the public window only home-branch members may register. `min_age` (default 0) and `max_age` (default 99) bound participant ages, both inclusive. `non_member_multiplier` (default 1.5) scales the fee for non-members. When `is_licensed_childcare` is true, `licensed_children_per_staff` must be supplied — omitting it is `ERR_INVALID_REQUEST` — and the session enforces the statutory ratio described below.

A `ProgramSession` is created by a `ProgramCoordinator` or `BranchDirector` with the parent `program_id`, the `space_id` it occupies (the space must belong to the session's branch, else `ERR_SPACE_NOT_FOUND`), the `start_on` and `end_on` ISO dates, daily `time_start` and `time_end` in 24-hour HH:MM form, the `capacity` maximum enrollment, and an optional `staff_member_ids` roster defaulting to empty. Time ranges must be sane — `end_on` on or after `start_on` and `time_end` after `time_start` — else `ERR_TIME_RANGE_INVALID`. The session's `branch_id` is denormalized from its program. Two system-computed dates govern enrollment: `public_opens_on` is the `start_on` date minus 14 days, and `member_opens_on` is `member_priority_days` earlier still, so the member-priority window runs from `member_opens_on` up to but not including `public_opens_on`. A session is born `SCHEDULED`.

The clock drives the session lifecycle: `SCHEDULED` → `REG_OPEN` when the clock reaches `member_opens_on`; `REG_OPEN` → `REG_CLOSED` at the end of the `start_on` day, or earlier when a `ProgramCoordinator` or `BranchDirector` closes registration by hand; `REG_CLOSED` → `COMPLETED` once the clock passes `end_on`. Closing registration — by clock or by hand — expires every `WAITLISTED` registration (each becomes `EXPIRED`) and zeroes `waitlist_count`; no new registrations are accepted afterward. Cancelling a session, whether `SCHEDULED` or `REG_OPEN`, cascades broadly: every `REGISTERED` registration becomes `REFUNDED` and `enrolled_count` drops to zero, every `WAITLISTED` registration becomes `EXPIRED` and `waitlist_count` drops to zero, and any linked program reservation for the session in `REQUESTED` or `APPROVED` status is `CANCELLED`, releasing the space. `COMPLETED` and `CANCELLED` are terminal; acting further on one is `ERR_ALREADY_TERMINAL`.

**Registering a participant.** A `Member`, `FrontDesk`, or `ProgramCoordinator` registers by supplying the `session_id`, the `member_id` of the account doing the registering (which may be a non-member walk-in record), the `participant_name`, and the `participant_birth_date` — the participant may differ from the account holder, as when a parent enrolls a child. The participant's age at the session's `start_on` must fall within the program's `min_age` to `max_age` inclusive, else `ERR_PARTICIPANT_AGE_INVALID`. Registration is only accepted while the session is `REG_OPEN`; a session still `SCHEDULED` (before the window opens) or already `REG_CLOSED` (after it closes, whether by clock or by hand) rejects the attempt with `ERR_REGISTRATION_WINDOW_CLOSED`. `ERR_SESSION_FULL` is not surfaced for program sessions: landing on the waitlist when the roster is at effective capacity is a normal outcome, not an error, and by the time a session is closed its waitlist has already been expired.

The system derives `registrant_class` by comparing the member record against the session's branch: a member holding an `ACTIVE` or `ON_HOLD` membership at that branch is a `HOME_MEMBER`; a membership at another branch of the same association makes an `ASSOCIATION_MEMBER`; a record with `visiting_association_name` set is a `RECIPROCITY_VISITOR`; anything else is a `NON_MEMBER`. During the member-priority window only `HOME_MEMBER` registrants are accepted — everyone else is turned away with `ERR_MEMBER_PRIORITY_ONLY`. A `member_only` program rejects `NON_MEMBER` and `RECIPROCITY_VISITOR` registrants with `ERR_MEMBER_ONLY_PROGRAM` regardless of window.

The fee is computed in two pinned rounding steps, never rounding multipliers. First the gross: `HOME_MEMBER` and `ASSOCIATION_MEMBER` registrants pay the program's `base_fee_cents` unchanged; a `RECIPROCITY_VISITOR` pays the base fee multiplied by 1.25, rounded half-up to integer cents; a `NON_MEMBER` pays the base fee multiplied by the program's `non_member_multiplier`, rounded half-up. Then, when the registrant holds an `ACTIVE` or `ON_HOLD` membership at the session's branch, the `fee_charged_cents` is the gross multiplied by one minus that membership's `assistance_pct`, rounded half-up again; without such a membership the fee is simply the gross.

**Capacity and the licensed ratio.** Whether a registration lands as `REGISTERED` or `WAITLISTED` depends on effective capacity. For an ordinary program the effective capacity is simply the session's `capacity`. For a licensed-childcare program the statutory cap is the program's `licensed_children_per_staff` multiplied by the number of assigned staff, and the effective capacity is the smaller of the session capacity and that statutory cap; an unstaffed licensed session therefore accepts zero children and every registration waitlists. When the enrolled count plus one fits within effective capacity the registration is `REGISTERED` and `enrolled_count` rises; otherwise it becomes `WAITLISTED` with `waitlist_position` one past the current `waitlist_count` — waitlisting is a normal outcome, not an error. The roster counters `enrolled_count` and `waitlist_count` track registrations in `REGISTERED` and `WAITLISTED` status respectively.

**Staff assignment.** A `ProgramCoordinator` or `BranchDirector` may assign staff to a session by supplying `staff_member_ids`. Assignment recomputes the effective capacity and, when a licensed session's ratio cap rises, promotes waitlisted registrations head-of-line while capacity allows. Removing staff below the level the current enrollment requires would break the ratio and is rejected with `ERR_RATIO_CAPACITY_EXCEEDED`.

**Cancellation and promotion.** A `Member`, `ProgramCoordinator`, or `FrontDesk` operator may cancel a `REGISTERED` registration while the session is `SCHEDULED` or `REG_OPEN`; cancelling against any later session state is `ERR_INVALID_STATE`. Cancellation decrements `enrolled_count`, then promotes the head-of-line waitlisted registration — the lowest `waitlist_position`, with ties broken by earliest `created_at`, never by id — to `REGISTERED`, computing its `fee_charged_cents` at promotion time, incrementing `enrolled_count`, decrementing `waitlist_count`, nulling its `waitlist_position`, and shifting every remaining waitlisted position down by one. Waitlist order is stable once assigned: a registration keeps the `waitlist_position` it received until it is promoted or leaves the waitlist, and any recomputation of the roster counters preserves the existing positions, appending only never-positioned entries at the tail in arrival order and closing gaps left by promotions or removals; the queue is never re-sorted by `created_at` alone and never ordered by id. The promotion chain is repeatable: cancel, promote the head, cancel, promote the next. One refinement applies on licensed sessions: if promoting the head candidate would push the post-promotion enrolled count past `licensed_children_per_staff` times the staff count, that candidate is skipped — the `ERR_RATIO_CAPACITY_EXCEEDED` condition skips rather than errors at promotion — the seat stays notionally open for them, and the next eligible candidate is promoted instead. On the money side, a cancellation within 48 hours before the session's `start_on` forfeits the `fee_charged_cents`; an earlier cancellation refunds it.

### 3.6. Facility Scheduling: Spaces, Reservations, and Buffers

Each branch's physical inventory is modeled as `FacilitySpace` records created by a `BranchDirector` or `AssociationAdmin` with a `branch_id`, a `name` such as Pool A or Studio 2, a `kind` of `POOL`, `GYM`, `STUDIO`, or `CHILDCARE_ROOM`, the total `capacity`, and a `dropin_capacity` — the number of spots guaranteed for member drop-in use even while the space is reserved. The drop-in guarantee can never exceed the total capacity; a request with `dropin_capacity` greater than `capacity` is `ERR_INVALID_REQUEST`.

A `FacilityReservation` is requested against a space by a `ProgramCoordinator`, `BranchDirector`, `AssociationAdmin`, or `Member`, naming the `space_id`, a `reservation_type` of `PROGRAM`, `RENTAL`, `MAINTENANCE`, or `BLACKOUT`, and the `start_at` and `end_at` ISO datetimes; `end_at` is exclusive and must be later than `start_at`, else `ERR_TIME_RANGE_INVALID`. Program reservations link their `session_id`; rental reservations name the `renter_member_id`. Creating a `BLACKOUT` reservation is reserved to the `AssociationAdmin` role — anyone else attempting it is `ERR_UNAUTHORIZED`. Each type carries a fixed setup-and-teardown `buffer_minutes` applied to both ends of the interval: 15 minutes for `PROGRAM`, 30 minutes for `RENTAL`, and zero for `MAINTENANCE` and `BLACKOUT`. A reservation is born `REQUESTED`.

Approval is a `BranchDirector` decision and is where conflict enforcement lives. The director's approval moves the reservation `REQUESTED` → `APPROVED` only when no already-`APPROVED` reservation on the same space has a buffered interval — its `start_at` minus its buffer through its `end_at` plus its buffer — that intersects this request's buffered interval; an overlap is `ERR_SPACE_CONFLICT`. Buffered intervals that merely touch, one ending exactly when the other begins, are allowed. An `APPROVED` `BLACKOUT` covering any part of the requested interval also blocks approval with `ERR_SPACE_CONFLICT`. The sibling decision moves the reservation `REQUESTED` → `DENIED`, which is terminal. An approved reservation may be cancelled by a `BranchDirector` or `ProgramCoordinator` — or automatically when its linked program session is cancelled — restoring the space's availability, and it completes automatically when the clock passes `end_at`. `DENIED`, `CANCELLED`, and `COMPLETED` are all terminal.

### 3.7. Campaigns, Donations, and the Funding Loop

An `AssociationAdmin` creates a `Campaign` with its `association_id`, a `name`, and the association-wide `goal_cents`; the campaign is born in `DRAFT` status. Activation — also an `AssociationAdmin` action — moves it to `ACTIVE`, but only one campaign per association may be active at a time; activating a second is `ERR_CAMPAIGN_ALREADY_ACTIVE`.

Giving begins as a pledge: a `BranchDirector`, `AssociationAdmin`, or `FrontDesk` operator records a `Donation` with the `campaign_id`, the `branch_id` to be credited, the `amount_cents` (which must be greater than zero), a `designation` of `SCHOLARSHIP` or `GENERAL`, and optionally a `donor_member_id`, which stays null for anonymous gifts. A pledge sits in `PLEDGED` status and affects nothing — no campaign totals move and no branch pool is credited.

Receipt is the money-arrives moment, performed by a `BranchDirector` or `AssociationAdmin` and legal only while the campaign is `ACTIVE`; receiving against a draft or closed campaign is `ERR_CAMPAIGN_NOT_ACTIVE`. Receipt adds the `amount_cents` to the campaign's `base_raised_cents`, increments the campaign's `version` by one, and recomputes the board match: the attainment is `base_raised_cents` divided by `goal_cents`, rounded to four decimal places half-up before tier comparison, and the `match_pct` tier is 0 when attainment is below 0.50, 0.10 when attainment is exactly 0.50 or above but below 1.00, and 0.25 when attainment is exactly 1.00 or above. The `matched_raised_cents` is then `base_raised_cents` multiplied by one plus the `match_pct`, rounded half-up to integer cents. While the campaign is live the match tier moves both up and down with attainment. When the gift's `designation` is `SCHOLARSHIP`, receipt additionally credits the branch: `scholarship_pool_received_cents` increases by the amount, raising `scholarship_pool_available_cents` — and that fresh credit may unblock a scholarship approval that was previously failing with `ERR_POOL_EXHAUSTED`.

Refund is the compensating action, restricted to `AssociationAdmin`. It subtracts the amount from `base_raised_cents` and increments the campaign `version`; while the campaign is still `ACTIVE` the match tier is recomputed from the reduced attainment. A `SCHOLARSHIP`-designated refund debits the branch pool's received counter as well — but only if solvency survives: a refund that would push `scholarship_pool_available_cents` below zero is rejected with `ERR_POOL_WOULD_GO_NEGATIVE`. A refunded donation lands in the terminal `REFUNDED` status.

Closing a campaign requires `expected_campaign_version` per §2.5 and increments the campaign's `version` by one. At close, `match_pct` and `matched_raised_cents` are frozen at their closing values; donations refunded after the close still reduce `base_raised_cents`, but the frozen fields are never recomputed. Donations still `PLEDGED` at close remain `PLEDGED` but can no longer be received. `CLOSED` is terminal.

### 3.8. Reciprocity and Cross-Association Visits

When an association has `reciprocity_enabled`, visiting members of other associations may register at its branches. The visitor's member record carries `visiting_association_name`, which the fee engine reads to classify them as `RECIPROCITY_VISITOR` and to apply the 1.25 surcharge described in §3.5. Visitors are excluded from `member_only` programs and from member-priority windows, and because they hold no membership at the session's branch they receive no assistance discount on program fees. Home members of the association visiting a sibling branch are treated more warmly: an `ACTIVE` or `ON_HOLD` membership at any branch of the same association classifies the registrant as `ASSOCIATION_MEMBER`, paying the flat member `base_fee_cents` without surcharge, though the assistance discount applies only when the membership sits at the session's own branch.

## 4. Endpoint Definitions

Endpoints that create a new resource return HTTP 201; all other successful operations, including reads, state transitions, and updates, return HTTP 200. Request and response payloads follow the envelope of §2.2, and the full behavior of each endpoint — its inputs, side effects, and failure modes — is specified by the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /_clock/set_current_utc | Advance the logical clock | AssociationAdmin |
| POST | /associations | Create an association | AssociationAdmin |
| GET | /associations/{associationId} | Get an association | AssociationAdmin, BranchDirector, ProgramCoordinator, FrontDesk, BoardMember |
| GET | /associations/{associationId}/branches | List branches of an association | AssociationAdmin, BranchDirector, ProgramCoordinator, FrontDesk, BoardMember |
| GET | /associations/{associationId}/campaigns | List campaigns of an association | AssociationAdmin, BranchDirector, BoardMember, FrontDesk |
| POST | /branches | Create a branch | AssociationAdmin |
| GET | /branches/{branchId} | Get a branch with computed pool and membership counts | AssociationAdmin, BranchDirector, ProgramCoordinator, FrontDesk, BoardMember |
| GET | /branches | List branches, filterable by association_id | AssociationAdmin, BranchDirector, ProgramCoordinator, FrontDesk, BoardMember |
| GET | /branches/{branchId}/memberships | List memberships of a branch | AssociationAdmin, BranchDirector, FrontDesk |
| GET | /branches/{branchId}/categories | List categories of a branch | AssociationAdmin, BranchDirector, ProgramCoordinator, FrontDesk, Member, BoardMember |
| GET | /branches/{branchId}/programs | List programs of a branch | AssociationAdmin, BranchDirector, ProgramCoordinator, FrontDesk, Member, BoardMember |
| GET | /branches/{branchId}/spaces | List facility spaces of a branch | AssociationAdmin, BranchDirector, ProgramCoordinator, FrontDesk, Member |
| GET | /branches/{branchId}/scholarship-applications | List scholarship applications of a branch | BranchDirector, AssociationAdmin, Member |
| GET | /branches/{branchId}/donations | List donations credited to a branch | AssociationAdmin, BranchDirector, BoardMember |
| POST | /categories | Create a membership category | AssociationAdmin, BranchDirector |
| GET | /categories/{categoryId} | Get a category | AssociationAdmin, BranchDirector, ProgramCoordinator, FrontDesk, Member, BoardMember |
| GET | /categories | List categories, filterable by branch_id | AssociationAdmin, BranchDirector, ProgramCoordinator, FrontDesk, Member, BoardMember |
| POST | /members | Register a member account | FrontDesk, AssociationAdmin, BranchDirector |
| GET | /members/{memberId} | Get a member | AssociationAdmin, BranchDirector, ProgramCoordinator, FrontDesk, Member |
| GET | /members | List members, filterable by home_branch_id | AssociationAdmin, BranchDirector, ProgramCoordinator, FrontDesk |
| GET | /members/{memberId}/registrations | List registrations made by this member | AssociationAdmin, BranchDirector, ProgramCoordinator, FrontDesk, Member |
| GET | /members/{memberId}/memberships | List memberships whose primary is this member | AssociationAdmin, BranchDirector, FrontDesk, Member |
| GET | /members/{memberId}/scholarship-applications | List applications filed by this applicant | AssociationAdmin, BranchDirector, Member |
| GET | /members/{memberId}/donations | List donations made by this donor | AssociationAdmin, BranchDirector, BoardMember, Member |
| GET | /members/{memberId}/reservations | List rental reservations for this renter | AssociationAdmin, BranchDirector, FrontDesk, Member |
| POST | /memberships | Join: create a membership | FrontDesk, Member, BranchDirector, AssociationAdmin |
| GET | /memberships/{membershipId} | Get a membership | AssociationAdmin, BranchDirector, FrontDesk, Member |
| GET | /memberships | List memberships, filterable by branch_id / category_id / primary_member_id | AssociationAdmin, BranchDirector, FrontDesk |
| PATCH | /memberships/{membershipId} | Update category or household composition (OCC) | BranchDirector, AssociationAdmin, FrontDesk |
| POST | /memberships/{membershipId}/hold | Place a membership on hold | Member, BranchDirector |
| POST | /memberships/{membershipId}/resume | Resume a held membership early | Member, BranchDirector |
| POST | /memberships/{membershipId}/cancel | Cancel a membership | Member, BranchDirector |
| POST | /memberships/{membershipId}/reinstate | Reinstate a LAPSED membership | BranchDirector |
| POST | /memberships/{membershipId}/drafts | Create the monthly draft for a membership | BranchDirector, AssociationAdmin |
| GET | /memberships/{membershipId}/drafts | List drafts of a membership | BranchDirector, AssociationAdmin, FrontDesk, Member |
| GET | /drafts/{draftId} | Get a draft | BranchDirector, AssociationAdmin, FrontDesk, Member |
| GET | /drafts | List drafts, filterable by membership_id | BranchDirector, AssociationAdmin, FrontDesk |
| POST | /drafts/{draftId}/settle | Mark a PENDING/FAILED draft as PAID | Member, BranchDirector, FrontDesk |
| POST | /drafts/{draftId}/fail | Record a failed collection attempt | BranchDirector, AssociationAdmin |
| POST | /scholarship-applications | Submit a financial assistance application | Member, FrontDesk, BranchDirector |
| GET | /scholarship-applications/{applicationId} | Get an application | BranchDirector, AssociationAdmin, Member |
| GET | /scholarship-applications | List applications, filterable by branch_id / membership_id | BranchDirector, AssociationAdmin, Member |
| POST | /scholarship-applications/{applicationId}/review | Move application to UNDER_REVIEW | BranchDirector |
| POST | /scholarship-applications/{applicationId}/request-info | Request more documentation | BranchDirector |
| POST | /scholarship-applications/{applicationId}/submit-info | Applicant supplies more documentation | Member |
| POST | /scholarship-applications/{applicationId}/approve | Approve with sliding-scale award (OCC on membership) | BranchDirector |
| POST | /scholarship-applications/{applicationId}/deny | Deny an application | BranchDirector |
| POST | /programs | Create a program | ProgramCoordinator, BranchDirector, AssociationAdmin |
| GET | /programs/{programId} | Get a program | AssociationAdmin, BranchDirector, ProgramCoordinator, FrontDesk, Member, BoardMember |
| GET | /programs | List programs, filterable by branch_id | AssociationAdmin, BranchDirector, ProgramCoordinator, FrontDesk, Member, BoardMember |
| GET | /programs/{programId}/sessions | List sessions of a program | AssociationAdmin, BranchDirector, ProgramCoordinator, FrontDesk, Member, BoardMember |
| POST | /sessions | Create a session | ProgramCoordinator, BranchDirector |
| GET | /sessions/{sessionId} | Get a session | AssociationAdmin, BranchDirector, ProgramCoordinator, FrontDesk, Member, BoardMember |
| GET | /sessions | List sessions, filterable by program_id / branch_id / space_id | AssociationAdmin, BranchDirector, ProgramCoordinator, FrontDesk, Member, BoardMember |
| POST | /sessions/{sessionId}/close-registration | Close registration early | ProgramCoordinator, BranchDirector |
| POST | /sessions/{sessionId}/cancel | Cancel a session (cascade refunds) | ProgramCoordinator, BranchDirector |
| POST | /sessions/{sessionId}/staff | Assign staff to a session | ProgramCoordinator, BranchDirector |
| GET | /sessions/{sessionId}/registrations | List registrations of a session | AssociationAdmin, BranchDirector, ProgramCoordinator, FrontDesk, Member |
| POST | /registrations | Register a participant | Member, FrontDesk, ProgramCoordinator |
| GET | /registrations/{registrationId} | Get a registration | AssociationAdmin, BranchDirector, ProgramCoordinator, FrontDesk, Member |
| GET | /registrations | List registrations, filterable by session_id / member_id | AssociationAdmin, BranchDirector, ProgramCoordinator, FrontDesk, Member |
| POST | /registrations/{registrationId}/cancel | Cancel a registration; promotes waitlist head | Member, ProgramCoordinator, FrontDesk |
| POST | /spaces | Create a facility space | BranchDirector, AssociationAdmin |
| GET | /spaces/{spaceId} | Get a space | AssociationAdmin, BranchDirector, ProgramCoordinator, FrontDesk, Member |
| GET | /spaces | List spaces, filterable by branch_id | AssociationAdmin, BranchDirector, ProgramCoordinator, FrontDesk, Member |
| GET | /spaces/{spaceId}/reservations | List reservations of a space | AssociationAdmin, BranchDirector, ProgramCoordinator, FrontDesk, Member |
| POST | /reservations | Request a reservation | ProgramCoordinator, BranchDirector, AssociationAdmin, Member |
| GET | /reservations/{reservationId} | Get a reservation | AssociationAdmin, BranchDirector, ProgramCoordinator, FrontDesk, Member |
| GET | /reservations | List reservations, filterable by space_id / branch_id / session_id / renter_member_id | AssociationAdmin, BranchDirector, ProgramCoordinator, FrontDesk, Member |
| POST | /reservations/{reservationId}/approve | Approve a reservation (overlap enforced here) | BranchDirector |
| POST | /reservations/{reservationId}/deny | Deny a reservation | BranchDirector |
| POST | /reservations/{reservationId}/cancel | Cancel an approved reservation | BranchDirector, ProgramCoordinator |
| POST | /campaigns | Create a campaign | AssociationAdmin |
| GET | /campaigns/{campaignId} | Get a campaign | AssociationAdmin, BranchDirector, BoardMember, FrontDesk |
| GET | /campaigns | List campaigns, filterable by association_id | AssociationAdmin, BranchDirector, BoardMember, FrontDesk |
| POST | /campaigns/{campaignId}/activate | Activate a campaign (one ACTIVE per association) | AssociationAdmin |
| POST | /campaigns/{campaignId}/close | Close a campaign (OCC); freezes the match | AssociationAdmin |
| GET | /campaigns/{campaignId}/donations | List donations of a campaign | AssociationAdmin, BranchDirector, BoardMember |
| POST | /donations | Record a pledge | BranchDirector, AssociationAdmin, FrontDesk |
| GET | /donations/{donationId} | Get a donation | AssociationAdmin, BranchDirector, BoardMember, FrontDesk, Member |
| GET | /donations | List donations, filterable by campaign_id / branch_id / donor_member_id | AssociationAdmin, BranchDirector, BoardMember, FrontDesk |
| POST | /donations/{donationId}/receive | Mark a pledge received | BranchDirector, AssociationAdmin |
| POST | /donations/{donationId}/refund | Refund a received donation | AssociationAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3; this catalogue fixes only the identifier and the HTTP status.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_INVALID_REQUEST | 400 |
| ERR_NOT_FOUND | 404 |
| ERR_BRANCH_NOT_FOUND | 404 |
| ERR_MEMBER_NOT_FOUND | 404 |
| ERR_CATEGORY_NOT_FOUND | 404 |
| ERR_SPACE_NOT_FOUND | 404 |
| ERR_SESSION_NOT_FOUND | 404 |
| ERR_APPLICATION_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_ALREADY_TERMINAL | 409 |
| ERR_DUPLICATE_EMAIL | 409 |
| ERR_DUPLICATE_BRANCH_CODE | 409 |
| ERR_DUPLICATE_DRAFT | 409 |
| ERR_DUPLICATE_ACTIVE_AWARD | 409 |
| ERR_CAMPAIGN_ALREADY_ACTIVE | 409 |
| ERR_CAMPAIGN_NOT_ACTIVE | 409 |
| ERR_HOUSEHOLD_CAP_EXCEEDED | 409 |
| ERR_DOCUMENTATION_MISSING | 400 |
| ERR_AWARD_INELIGIBLE | 409 |
| ERR_POOL_EXHAUSTED | 409 |
| ERR_POOL_WOULD_GO_NEGATIVE | 409 |
| ERR_HOLD_WINDOW_INVALID | 409 |
| ERR_HOLD_ALLOWANCE_EXCEEDED | 409 |
| ERR_REINSTATE_WINDOW_PASSED | 409 |
| ERR_REGISTRATION_WINDOW_CLOSED | 409 |
| ERR_MEMBER_PRIORITY_ONLY | 409 |
| ERR_MEMBER_ONLY_PROGRAM | 409 |
| ERR_SESSION_FULL | 409 |
| ERR_RATIO_CAPACITY_EXCEEDED | 409 |
| ERR_TIME_RANGE_INVALID | 400 |
| ERR_SPACE_CONFLICT | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_PARTICIPANT_AGE_INVALID | 409 |
