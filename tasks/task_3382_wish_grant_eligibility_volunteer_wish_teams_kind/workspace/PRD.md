# Wish Grant & In-Kind Sourcing API — Product Requirements Document

## 1. Introduction

A wish-granting organization serves children living with critical illnesses through a federation of local chapters, each covering a defined territory and answering for a fiscal-year budget. This document specifies the API, mounted under `/wish-grant`, that coordinates the full lifecycle of a wish: intake of a referral arriving from a family member, a medical professional, or the child themself; certification of a qualifying medical condition by an external provider; an eligibility determination rendered by chapter staff; a determination visit conducted by a trained two-person volunteer team that captures the child's true wish and classifies it as travel, meeting a person, receiving an item, or being something; sourcing of donated goods and services from airline, resort, retailer, and sponsor partners; assembly of a fulfillment plan that blends cash spending with in-kind value; approval of that plan under segregation-of-duties and fiscal controls; medical clearance for travel wishes; scheduling around the child's treatment cycles; and completion of the grant itself.

Three commitments shape every rule that follows. First, the right child: eligibility is gated by provider certification and by precise age criteria measured against a controllable logical clock, with duplicate-referral detection so that one child is never carried through intake twice in parallel. Second, the true wish: determination belongs to trained volunteer teams using age-appropriate elicitation methods, and urgent cases — children with a short prognosis — are fast-tracked onto the calendar. Third, the responsible dollar: chapters answer for both their committed spend and their average cost per granted wish, in-kind donations are valued against published retail prices under a conservative cap, and plans that would push a chapter past its cost-per-wish target escalate to national leadership. Roles are deliberately segregated — the provider certifies, the reviewer determines, the coordinator builds, the director approves — so that no single actor can move a wish from intake to funding alone.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming the operator's role. A request missing either header, or presenting a role outside the declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the role is declared but is not on the target endpoint's authorized list, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The declared roles, spelled exactly as the API expects them, are: `NationalAdmin`, `ReferralSource`, `MedicalProvider`, `EligibilityReviewer`, `Volunteer`, `WishCoordinator`, `InKindOfficer`, `ChapterDirector`, and `NationalDirector`.

`NationalAdmin` is the national office platform operator; it provisions chapters and drives the logical clock. `ReferralSource` is the intake channel actor for family, medical-professional, and self referrals; the channel itself is recorded on each referral. `MedicalProvider` is the external certifying professional who certifies conditions, records treatment windows, and decides medical clearances. `EligibilityReviewer` is chapter eligibility staff who render the determination after certification; certification and determination are deliberately segregated so the provider certifies and the reviewer determines. `Volunteer` is the trained wish-team member who acts only on visits of teams they belong to. `WishCoordinator` is chapter wish-granting staff managing volunteers, teams, plans, clearances, and scheduling. `InKindOfficer` manages donation offers from partner organizations. `ChapterDirector` approves and aborts plans and may also create them, subject to segregation of duties. `NationalDirector` is the national office director and the only role that may approve a plan whose projected cost per wish exceeds the chapter target.

Identity semantics differ across roles. When `X-User-Role` is `Volunteer`, `X-User-ID` is the `id` of the acting `Volunteer` entity; membership checks on any resource that references a volunteer — notably a `WishTeam`'s `lead_volunteer_id` and `second_volunteer_id` — compare those foreign-key fields to `X-User-ID`. When `X-User-Role` is `NationalAdmin`, `ReferralSource`, `MedicalProvider`, `EligibilityReviewer`, `WishCoordinator`, `InKindOfficer`, `ChapterDirector`, or `NationalDirector`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — for example, as `created_by_user_id` or `approved_by_user_id` on a `FulfillmentPlan` — but does not compare it to any entity's `id`.

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

List endpoints accept two query parameters. `limit` defaults to 10, with a minimum of 1 and a maximum of 100. `offset` defaults to 0. List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object. Unless stated otherwise, every list endpoint sorts by `created_at` ascending — the oldest record first.

### 2.4. Resource Identity, Timestamps, and Change Tracking

Every resource in this API shares the same bookkeeping spine. Each carries an `id` minted by the server as a UUID with no type prefix, a `created_at` timestamp recording when the resource was created, an `updated_at` timestamp refreshed on every mutation, and an integer `version` that starts at 1 on creation and increments by exactly one each time the resource changes. All timestamps are ISO 8601 UTC with three fractional digits. When a single operation cascades across several entities — an approval that touches the plan, its line items, the chapter, and the wish, for example — every affected resource increments its own `version` by one and refreshes its own `updated_at`, and the narratives of §3 name those increments at each cascade step.

### 2.5. The Logical Clock and the Offer Expiry Sweep

The server does not consult wall-clock time. A logical clock governs every "now" in the system: certification timestamps, determination timestamps, grant timestamps, clearance decisions, event completions, age computations, the calendar-year filtering of granted wishes, and donation-offer expiry all read it. Before any operator sets it, the logical clock reads exactly 2026-09-01T00:00:00Z, and it never falls back to wall-clock time. A `NationalAdmin` advances the clock through a test-driving capability that accepts a target instant as `to_iso8601` and reports the new value as `current_utc`.

Advancing the clock triggers an expiry sweep across donation offers: any offer still `AVAILABLE`, holding no reserved units, whose `valid_until` date falls before the new logical date transitions to `EXPIRED` with a version increment. Offers carrying reservations are partner commitments and are never auto-expired, even when their validity date passes. Independently of the sweep, an attempt to reserve from an offer whose `valid_until` is already in the past at reservation time fails with `ERR_DONATION_EXPIRED` (HTTP 409) — the sweep cleans the catalogue, but the reservation-time check is the authoritative guard.

### 2.6. Monetary Precision and Rounding Discipline

All money in this system is integer cents; no fractional cents exist anywhere. There is exactly one rounding point in the entire cost pipeline: the per-unit fair market value of a donation offer is rounded half-up to integer cents when the offer is created. Every later step is exact integer arithmetic — a reserved line multiplies the already-rounded unit value by its quantity, a plan sums its line values, and the plan total adds the cash portion. The pinned evaluation order is therefore: round the per-unit value first, multiply by the line quantity, sum across the plan's lines, and add cash last. An implementation that sums raw unrounded values and rounds once at the end will produce different cents and is incorrect.

Chapter averages divide integer-cent totals by whole wish counts and round half-up to integer cents, reporting 0 while no wishes have been granted in the period. The chapter budget-freeze threshold rounds down to whole cents before comparison.

### 2.7. Optimistic Concurrency Control on Wish-Scoped Writes

Two write operations are guarded by optimistic concurrency control on the wish they target: creating a determination team, and creating a fulfillment plan. Both require the request to carry `expected_wish_version`, a non-optional field holding the wish's `version` as the client last observed it. If the wish's current `version` differs from the submitted value — because another write has advanced the wish since the client read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). Replacing a determination team and superseding a draft plan are legitimate product operations, so a client that re-reads the wish and resubmits with the fresh version succeeds; the version check is the mechanism that detects a writer acting on a stale view. Endpoints other than these two do not accept a version field.

### 2.8. Validation Order and Failure Semantics

When several checks would fail on the same request, the API does not choose arbitrarily: validations run in a fixed priority order and the earliest failure is the one reported. Authentication comes first — missing or invalid headers yield `ERR_UNAUTHENTICATED` — then role authorization (`ERR_FORBIDDEN_ROLE`), then existence of every resource named by a path parameter, validated left-to-right (`ERR_NOT_FOUND`), then body well-formedness (`ERR_INVALID_REQUEST`): required fields present, types correct, enum values within their declared sets, dates parseable, quantities at least 1, end dates not before start dates, and decision-conditional fields such as a denial reason or a clearance's validity date supplied when their decision requires them. Only after the envelope is sound do state-machine from-state checks run, in this entity order where several apply: volunteer, referral, wish, team, visit, plan, offer, clearance, then event — each surfacing its own `ERR_INVALID_*_STATE` code. The stale-version check (`ERR_STALE_VERSION`) follows the state checks, then segregation of duties, then medical-clearance validity for scheduling, then the temporal rules — team visit overlap, treatment blackout, and the urgent-case scheduling deadline — then donation expiry, and finally the remaining business constraints and fiscal rules described throughout §3. The per-endpoint chains in §3 state this order concretely wherever more than one check guards an operation, so a request failing two guards always surfaces the same code.

### 2.9. Chapter Fiscal Stewardship: Commitments, the Freeze Threshold, and Cost-Per-Wish Accountability

Each chapter tracks `committed_cost_cents`, the sum of `total_cost_cents` over its approved fulfillment plans — only plans in `APPROVED` status count toward the commitment; cancelled, superseded, and completed plans are excluded. A chapter's `posture` is derived, never set directly: it is `FROZEN` whenever `committed_cost_cents` reaches or exceeds the freeze threshold — the chapter's `fiscal_year_budget_cents` multiplied by 95 percent and rounded down to whole cents — and `OPEN` below it. Equality freezes: a commitment landing exactly on the threshold closes the chapter. While a chapter is `FROZEN`, every plan approval is rejected with `ERR_CHAPTER_BUDGET_FROZEN` (HTTP 409). Independently of posture, an approval that would push `committed_cost_cents` — including the pending plan's full total — above the chapter's `fiscal_year_budget_cents` is rejected with `ERR_CHAPTER_BUDGET_EXCEEDED` (HTTP 422).

Cost-per-wish accountability runs on two variants, both recomputed at grant completion and both defined over the set of the chapter's wishes granted within the calendar year of the current logical-clock date. The blended variant, `avg_cost_blended_cents`, divides the granted plans' total value — cash plus in-kind fair market value — by the granted wish count, rounding half-up to integer cents. The cash-only variant, `avg_cost_cash_cents`, divides only the cash portions of those same plans by the same count; for identical grant data involving any in-kind lines, the cash-only figure is strictly lower than the blended figure. Both report 0 while the count is 0.

The blended variant also drives escalation. When an approval is attempted, the system projects the chapter average as if the plan were granted: it takes the chapter's pre-approval granted totals, adds the pending plan's `total_cost_cents` to the numerator exactly once, adds exactly one to the granted count in the denominator, divides, rounds half-up to integer cents, and compares against the chapter's `target_avg_cost_per_wish_cents` with a strict greater-than — a projection landing exactly on the target does not escalate. When the projection exceeds the target, the plan's `escalation_required` flag is set and only a `NationalDirector` may approve it; a `ChapterDirector` attempting the same approval is rejected with `ERR_COST_ESCALATION_REQUIRED` (HTTP 422).

### 2.10. Nested Resource Retrieval and Path Validation

Several resources are addressed through their parents in the URL hierarchy — the visits of a team, the plans, clearances, and events of a wish, the line items of a plan or of an offer. Path parameters are validated left-to-right: the server first confirms the leftmost identifier references an existing resource, then proceeds rightward along the path. The first identifier that does not resolve yields `ERR_NOT_FOUND` (HTTP 404), regardless of whether later identifiers would also fail.

## 3. Business Logic & Workflows

### 3.1. Chapters, Territory Coverage, and the Volunteer Pipeline

Everything begins with a chapter. A `NationalAdmin` provisions one with a display `name`, a set of `territory_zip_prefixes` — at least one prefix is required, and each prefix is a string of one to five digits — a `fiscal_year_budget_cents` strictly greater than zero, and a `target_avg_cost_per_wish_cents`, also strictly greater than zero, that sets the chapter's cost-per-wish accountability ceiling. From then on the chapter's posture, commitment totals, and grant averages are computed by the system (§2.9 and §3.8), and reading the chapter returns all of them together.

Volunteers join a chapter through the `WishCoordinator`, who registers each one with the chapter's `chapter_id`, the volunteer's `full_name`, and a contact `email`. A new volunteer starts in `APPLIED` status and advances along a strict one-step ladder: `APPLIED` → `TRAINED` → `ACTIVE` → `INACTIVE`. Each advancement is driven by the coordinator naming a `target_state`, and the target must be exactly the next rung — asking for `ACTIVE` from `APPLIED`, or any other skip or sideways move, is rejected with `ERR_INVALID_VOLUNTEER_STATE` (HTTP 409). Every successful step increments the volunteer's `version`. Deactivation is not retroactive: moving a volunteer to `INACTIVE` leaves the teams and visits they already belong to untouched, because team composition is frozen at team creation.

### 3.2. Referral Intake: Age Bounds, Duplicate Detection, and Territory Assignment

A `ReferralSource` opens a case by submitting the intake payload: `child_full_name`, `child_date_of_birth`, `child_zip_code`, `parent_email`, a free-text `diagnosis_summary`, the `source_type` — one of `FAMILY`, `MEDICAL_PROFESSIONAL`, or `SELF` — and, optionally, `prognosis_months`, the expected prognosis horizon in whole months, which is either a non-negative integer or absent entirely. The payload atomically creates — or, on re-referral after a terminal referral, reuses — the child record, and produces a referral in `PENDING_CERTIFICATION` status with `age_months_at_intake` computed from the logical clock and `child_id` linking the two records.

Age is measured in complete calendar months. From the date of birth to the reference date, count the difference in years multiplied by twelve, add the difference in months, and subtract one when the reference day-of-month falls before the birth day-of-month. A child is eligible for intake when this measure is at least 30 months — two and a half years — and strictly below 216 months, the eighteenth birthday. Anything outside that range is rejected with `ERR_CHILD_AGE_OUT_OF_RANGE` (HTTP 422). A `SELF` referral carries an additional floor: the child must be at least 156 months old — thirteen years — at intake, or the request fails with `ERR_SELF_REFERRAL_TOO_YOUNG` (HTTP 422). These two checks run in that order, the general age bounds before the self-referral minimum.

Duplicate detection runs after the age checks and before territory selection. The submitted name is normalized — lowercased, trimmed, with internal whitespace collapsed — and stored on the child record as `normalized_full_name`. A duplicate exists when some earlier referral names a child with the same normalized name and the same `date_of_birth` and that earlier referral is still alive, meaning `PENDING_CERTIFICATION` or `CERTIFIED`; the intake is then rejected with `ERR_DUPLICATE_REFERRAL` (HTTP 409). A prior referral that already reached `DENIED` or `APPROVED` does not block a new one: the existing child record, matched by the same normalized name and birth date, is reused and linked to the new referral.

With duplicates cleared, territory assignment chooses the child's chapter. Every chapter whose `territory_zip_prefixes` contains a prefix that the submitted `child_zip_code` begins with is a candidate; the candidate offering the longest matching prefix wins, and remaining ties break on the candidate chapters' `created_at`, earliest first — never on chapter id. The winning chapter's id is recorded as the child's `chapter_id`. When no chapter matches at all, the entire intake fails with `ERR_NO_TERRITORY_CHAPTER` (HTTP 422) and nothing is persisted.

The resulting `Child` record carries the `full_name` exactly as given at intake alongside the computed `normalized_full_name`, the `date_of_birth`, the residential `zip_code`, the `parent_email`, the `diagnosis_summary`, the assigned `chapter_id`, and a `treatment_windows` array that starts empty and is maintained later by the provider (§3.8).

### 3.3. Medical Certification and the Eligibility Determination

Certification belongs to the `MedicalProvider`. Acting on a referral in `PENDING_CERTIFICATION` — any other state yields `ERR_INVALID_REFERRAL_STATE` (HTTP 409) — the provider submits a `qualifying_condition` drawn from `ONCOLOGY`, `CARDIAC`, `NEUROLOGIC`, `GENETIC`, `OTHER_PROGRESSIVE`, or `NON_QUALIFYING`, optionally accompanied by a `certification_note`. A qualifying condition moves the referral to `CERTIFIED`, stamps `certified_at` with the current logical clock, and increments the referral's `version`. Declaring `NON_QUALIFYING` auto-denies the referral in the same breath: the referral moves straight to `DENIED`, both `certified_at` and `determined_at` are stamped, and `denial_reason` is set by the system to `CONDITION_NOT_QUALIFYING`.

Determination belongs to the `EligibilityReviewer`, acting on a `CERTIFIED` referral — again `ERR_INVALID_REFERRAL_STATE` guards the from-state — with a `decision` of `APPROVED` or `DENIED`. Denial requires a `denial_reason`; its absence is a malformed request rejected with `ERR_INVALID_REQUEST`. Denial is never age-blocked: a reviewer may always deny, whatever the child's age. Approval, by contrast, re-checks the child's age at the determination date using the same complete-calendar-months measure as intake, and if the child has reached 216 months — the eighteenth birthday — approval is rejected with `ERR_CHILD_AGE_OUT_OF_RANGE`, even though intake accepted the case months earlier.

An approved determination creates the wish. The new wish opens in `CREATED` status at `version` 1, with `child_id` and `chapter_id` copied from the child record, `referral_id` pointing back to the referral that produced it, and `urgency` frozen at creation: `RAPID` when the referral's `prognosis_months` was provided and is at most 6 — the boundary month itself classifies as rapid — and `STANDARD` otherwise, including when no prognosis was recorded at all. Later edits to the referral never revisit this classification. The referral records the outcome as well: its `wish_id` links to the new wish, `determined_at` is stamped with the logical clock, and its `version` increments.

### 3.4. Determination Teams and the True-Wish Visit

A wish in `CREATED` waits for its determination team. The `WishCoordinator` forms one by naming the `wish_id`, a `lead_volunteer_id`, and a `second_volunteer_id`, and by presenting `expected_wish_version` under the optimistic-concurrency rule of §2.7. The guards run in a fixed order: first the wish must be in `CREATED` or `DETERMINATION_PENDING` — anything else yields `ERR_INVALID_WISH_STATE` (HTTP 409); then the stale-version check rejects with `ERR_STALE_VERSION`; then team composition is examined — the two volunteers must be different people, or `ERR_TEAM_DUPLICATE_MEMBER` (HTTP 422) fires; both must hold `ACTIVE` status, or `ERR_VOLUNTEER_NOT_ACTIVE` (HTTP 409) fires; and both must belong to the wish's chapter, meaning each volunteer's `chapter_id` equals the wish's `chapter_id`, or `ERR_TEAM_CHAPTER_MISMATCH` (HTTP 422) fires.

Creating the first team moves the wish `CREATED` → `DETERMINATION_PENDING`, opens a team in `ACTIVE` status, and advances the wish's `version`. Creating another team while the wish is `DETERMINATION_PENDING` is a legitimate replacement rather than an error: the wish self-loops within `DETERMINATION_PENDING` — the state label is unchanged but the wish's `version` advances — the previously `ACTIVE` team is disbanded to `DISBANDED` with its own version increment, every `SCHEDULED` visit of that disbanded team is cancelled to `CANCELLED` with a version increment each, and the new team opens `ACTIVE`.

Visits are the team's instrument. Either member schedules one by naming the `wish_team_id`, a `scheduled_start`, a `scheduled_end` strictly later than the start, and a `visit_method`. Four guards apply, in this order: the team must still be `ACTIVE`, or the request fails with `ERR_INVALID_TEAM_STATE` (HTTP 409); the new window must not overlap the team's other scheduled visits; the acting volunteer must be the team's lead or second — the server compares `X-User-ID` to the team's `lead_volunteer_id` and `second_volunteer_id`, and anyone else is rejected with `ERR_NOT_TEAM_MEMBER` (HTTP 403); and the chosen method must suit the child's age. Visit windows are half-open intervals, start inclusive and end exclusive: a new visit conflicts with an existing `SCHEDULED` visit of the same team only when the new start falls before the existing end and the existing start falls before the new end. Touching boundaries — one visit ending exactly when the other begins — count as adjacency, not conflict. A true overlap is rejected with `ERR_TEAM_SCHEDULE_OVERLAP` (HTTP 409).

The method rule measures the child's age, in the same complete calendar months as intake, at the visit's `scheduled_start`. A child under 72 months — under six years — may only be visited `PLAY_BASED`; from 72 months up to but not including 156 months, either `PLAY_BASED` or `DRAWING` is acceptable; at 156 months and above, only `INTERVIEW` remains. Any other pairing of method and age fails with `ERR_AGE_INAPPROPRIATE_METHOD` (HTTP 422). A successfully scheduled visit opens in `SCHEDULED` status.

Concluding a visit takes an `outcome` of `COMPLETED` or `NO_SHOW`, examined in this order: the team must be `ACTIVE` (`ERR_INVALID_TEAM_STATE`), the visit must be `SCHEDULED` (`ERR_INVALID_VISIT_STATE`, HTTP 409), and the actor must be a member of the team (`ERR_NOT_TEAM_MEMBER`). A completion requires the member to record `captured_true_wish` — the child's true-wish narrative — and `captured_wish_type`, one of `TRAVEL`, `MEET_PERSON`, `RECEIVE_ITEM`, or `BE_SOMETHING`; a completion missing either field is malformed (`ERR_INVALID_REQUEST`). The completion cascade then runs within the same request: the visit becomes `COMPLETED`; the wish moves `DETERMINATION_PENDING` → `DETERMINED` with `wish_type` set to the captured type, `true_wish_description` set to the captured narrative, and `determined_at` stamped with the logical clock — the timestamp that later anchors the urgent-case scheduling deadline; the team becomes `COMPLETED` with a version increment; and the team's other `SCHEDULED` visits are cancelled to `CANCELLED`, each with a version increment, while the wish's `version` advances as well. A `NO_SHOW` outcome changes only the visit, which moves to `NO_SHOW` with a version increment; the team stays `ACTIVE` and the wish stays `DETERMINATION_PENDING`, ready for another attempt.

### 3.5. In-Kind Donation Sourcing and Valuation

The `InKindOfficer` cultivates donated inventory by registering each offer with the `partner_name` — an airline, resort, retailer, or sponsor — a `category` of exactly `AIRLINE`, `RESORT`, `RETAILER`, or `SPONSOR`, a free-text `description` of what is being donated, the `quantity_total` of units donated, at least 1, the published `unit_retail_cents`, at least 1, and the reservable window running from `valid_from` through `valid_until`, where the end date must not precede the start date.

Every offer declares a `valuation_method`, and the method selects how the system computes `fmv_unit_cents`, the fair market value of one unit. Under `RETAIL_BASIS`, the unit value is simply the full `unit_retail_cents`, and a `partner_declared_unit_cents` supplied anyway is ignored. Under `PARTNER_DECLARED`, the partner's `partner_declared_unit_cents` is required — omitting it is a malformed request (`ERR_INVALID_REQUEST`) — and the unit value is the lesser of that declared figure and a cap computed as 80 percent of `unit_retail_cents`, with the cap itself rounded half-up to integer cents before the comparison. For identical retail prices and declared values, the partner-declared variant never exceeds the retail basis and falls strictly below it whenever the declared value or the cap binds underneath retail. The unit value is rounded here, once, at the unit level (§2.6); nothing downstream rounds again.

Reservation bookkeeping conserves units. `quantity_reserved` starts at 0, and `quantity_available` is always `quantity_total` minus `quantity_reserved`. An offer opens in `AVAILABLE` status; when a reservation takes the last available unit the offer becomes `FULLY_RESERVED`, and when a later release makes availability positive again it returns to `AVAILABLE`. The clock sweep of §2.5 moves an unreserved `AVAILABLE` offer whose `valid_until` has passed to `EXPIRED`. Consumption at grant completion (§3.8) decrements `quantity_reserved` and `quantity_total` together, leaving `quantity_available` untouched, and an offer whose total reaches zero becomes `DEPLETED`. Both `EXPIRED` and `DEPLETED` are terminal.

### 3.6. Fulfillment Planning, Line-Item Reservation, and Approval Governance

Once a wish is `DETERMINED`, a `WishCoordinator` or `ChapterDirector` drafts its fulfillment plan with the `wish_id`, a `cash_cost_cents` of zero or more, optional `notes`, and the OCC field `expected_wish_version`. Three guards run in order: the wish must be `DETERMINED` or `PLANNING`, otherwise `ERR_INVALID_WISH_STATE`; the stale-version check rejects a lagging client with `ERR_STALE_VERSION`; and if the wish already has a plan in `APPROVED` status, creation is rejected outright with `ERR_PLAN_ALREADY_APPROVED` (HTTP 409). Creating a plan while a `DRAFT` or `PENDING_APPROVAL` plan exists for the wish is a supersede, not a conflict: the old plan moves to `SUPERSEDED` with a version increment, each of its `RESERVED` line items is released to `RELEASED`, and each affected offer's `quantity_reserved` drops by the released quantity — an offer that was `FULLY_RESERVED` reopens to `AVAILABLE` once availability is positive again. The new plan opens in `DRAFT`, records `created_by_user_id` from the caller's `X-User-ID`, and the wish moves `DETERMINED` → `PLANNING` — or self-loops within `PLANNING` on a replacement — with a wish version increment either way.

Line items stock the draft. On a plan in `DRAFT` — any other state yields `ERR_INVALID_PLAN_STATE` (HTTP 409) — the planner reserves units of an offer by naming `donation_offer_id` and a `quantity` of at least 1; each line item also records its owning `plan_id`. The checks fire in order: the offer must be `AVAILABLE` (`ERR_INVALID_OFFER_STATE`, HTTP 409); the current logical date must not be past the offer's `valid_until` (`ERR_DONATION_EXPIRED`); the offer's category must fit the wish type's fulfillment path — `TRAVEL` wishes draw from `AIRLINE` and `RESORT`, `RECEIVE_ITEM` from `RETAILER`, `MEET_PERSON` from `SPONSOR`, and `BE_SOMETHING` from `SPONSOR` or `RETAILER`, with any other pairing rejected as `ERR_CATEGORY_WISH_TYPE_MISMATCH` (HTTP 422); and the requested `quantity` must not exceed the offer's `quantity_available`, where exactly the remaining quantity is allowed (`ERR_INSUFFICIENT_DONATION_QTY`, HTTP 409). A successful reservation pins `line_fmv_cents` at the line's `quantity` multiplied by the offer's `fmv_unit_cents` as of that moment, raises the offer's `quantity_reserved` by the same quantity — tipping the offer to `FULLY_RESERVED` when availability reaches zero — recomputes the plan's derived totals, and increments both the offer's and the plan's `version`.

The plan's money is derived, never entered. `in_kind_value_cents` sums `line_fmv_cents` across the plan's lines in `RESERVED`, `COMMITTED`, or `CONSUMED` status — `RELEASED` lines are excluded — and `total_cost_cents` is `cash_cost_cents` plus that sum, computed in the pinned order of §2.6: round the unit value first, multiply by quantity, sum the lines, add cash last.

Submitting moves a `DRAFT` plan to `PENDING_APPROVAL` with a version increment; a plan holding no `RESERVED` line items and zero `cash_cost_cents` cannot be submitted and is rejected with `ERR_EMPTY_PLAN` (HTTP 422).

Approval is where governance concentrates. The approver must be a `ChapterDirector` or `NationalDirector`, and the checks fire in this order: the plan must be `PENDING_APPROVAL` (`ERR_INVALID_PLAN_STATE`); segregation of duties forbids the plan's creator from approving it, comparing the plan's `created_by_user_id` to the approver's `X-User-ID` (`ERR_SEGREGATION_OF_DUTIES`, HTTP 403); the chapter's `posture` must be `OPEN` (`ERR_CHAPTER_BUDGET_FROZEN`); the chapter's `committed_cost_cents` plus the plan's `total_cost_cents` must not exceed `fiscal_year_budget_cents` (`ERR_CHAPTER_BUDGET_EXCEEDED`); and the escalation test of §2.9 restricts an over-target approval to `NationalDirector` (`ERR_COST_ESCALATION_REQUIRED`). Because the fiscal rules sit after the state and duty checks, a frozen chapter surfaces the freeze error even when the budget cap would also be breached, and the segregation-of-duties rejection precedes both.

An approved plan becomes `APPROVED` in place: `approved_by_user_id` records the approver, the `escalation_required` flag records whether the escalation test fired, every `RESERVED` line commits to `COMMITTED` with a version increment each, the chapter's `committed_cost_cents` rises by the plan's total with `posture` recomputed and the chapter's `version` incremented, and the wish moves `PLANNING` → `PLAN_APPROVED` with its own version increment. The ready gate is evaluated within the same request. For `MEET_PERSON` and `BE_SOMETHING` the gate is the approval itself; for `RECEIVE_ITEM` it additionally requires every line of the approved plan to be `COMMITTED`, a condition a cash-only plan satisfies vacuously. Wishes of those three types therefore continue straight to `READY_TO_SCHEDULE` inside the approval response. A `TRAVEL` wish waits in `PLAN_APPROVED` until a medical clearance satisfies its gate (§3.7).

Abortion unwinds a plan, and the `ChapterDirector` performing it may supply an optional `reason`. From `PENDING_APPROVAL`, aborting moves the plan to `CANCELLED`, releases its `RESERVED` lines to `RELEASED` and returns their quantities to the offers, recomputes `in_kind_value_cents` without the released lines, and leaves the wish in `PLANNING`. From `APPROVED`, aborting runs the deeper cascade: the plan moves to `CANCELLED`; its `COMMITTED` lines release to `RELEASED`, each returning its reserved quantity to the offer and reopening a `FULLY_RESERVED` offer to `AVAILABLE` when availability is restored; the chapter's `committed_cost_cents` falls by the plan's total with `posture` recomputed and the chapter's `version` incremented; and the wish reverts from `PLAN_APPROVED` or `READY_TO_SCHEDULE` back to `PLANNING` with a version increment. Either abort increments the plan's `version`. An approved plan can never be aborted while its wish is `SCHEDULED` — the attempt fails the state check with `ERR_INVALID_PLAN_STATE` — because at that point the commitment is on the calendar and must either run to completion or fall to a medical hold.

### 3.7. Medical Clearance and the Travel Hold

Travel wishes carry medical risk, so a `TRAVEL` wish cannot leave `PLAN_APPROVED` until a provider clears it. The `WishCoordinator` requests a clearance by naming only the `wish_id`. The wish must be of type `TRAVEL` — requesting a clearance for any other wish type is rejected with `ERR_WISH_TYPE_NO_CLEARANCE` (HTTP 422) — and it must be in `DETERMINED`, `PLANNING`, `PLAN_APPROVED`, `READY_TO_SCHEDULE`, `SCHEDULED`, or `MEDICAL_HOLD`, with any other state rejected as `ERR_INVALID_WISH_STATE`. At most one clearance per wish may be live at a time: when a clearance already exists in `PENDING`, `CLEARED`, or `CONDITIONAL`, a new request fails with `ERR_CLEARANCE_ALREADY_ACTIVE` (HTTP 409). A successfully requested clearance opens in `PENDING`.

The `MedicalProvider` decides with a `decision` and, depending on the outcome, `accommodations`, `valid_until`, and an optional `decision_note`. From `PENDING`, three rulings exist. `CLEARED` requires a `valid_until` date — the last day the clearance covers travel — and stamps `decided_at` with the logical clock. `CONDITIONAL` requires both `valid_until` and a non-empty `accommodations` array describing needs such as wheelchair, oxygen, or ground-transport-only; missing decision-conditional fields make the request malformed (`ERR_INVALID_REQUEST`). Either ruling increments the clearance's `version` and re-evaluates the travel gate immediately, in the same request: a wish sitting in `PLAN_APPROVED` advances to `READY_TO_SCHEDULE`, and a wish sitting in `MEDICAL_HOLD` returns to whichever state its `hold_return_state` recorded, with that field then cleared to null. `DENIED` needs nothing beyond the decision itself; it stamps `decided_at` and leaves the wish untouched — an uncleared travel wish simply remains in `PLAN_APPROVED`. Asking for any of these three rulings on a clearance that has left `PENDING`, or asking for `REVOKED` on a clearance that is not in `CLEARED` or `CONDITIONAL`, fails with `ERR_INVALID_CLEARANCE_STATE` (HTTP 409).

Revocation is the emergency brake. A provider may revoke a `CLEARED` or a `CONDITIONAL` clearance — both from-states behave identically — and the hold cascade fires: the wish, whether in `PLAN_APPROVED`, `READY_TO_SCHEDULE`, or `SCHEDULED`, drops to `MEDICAL_HOLD` with a version increment and records a `hold_return_state` — `PLAN_APPROVED` when the wish had advanced no further than its approval, and `READY_TO_SCHEDULE` otherwise. For a `SCHEDULED` wish the return state is also `READY_TO_SCHEDULE`, because the event itself is lost: every `SCHEDULED` wish event of the held wish is cancelled to `CANCELLED`, each with a version increment. When a later `CLEARED` or `CONDITIONAL` ruling arrives — necessarily on a new clearance, since a revoked one is terminal — the wish lifts out of `MEDICAL_HOLD` back to the recorded return state, and `hold_return_state` is cleared to null.

### 3.8. Scheduling Around Treatment and the Grant Completion Cascade

A wish in `READY_TO_SCHEDULE` is ready for its date with the calendar. The `WishCoordinator` schedules it by naming the `wish_id`, an `event_start_date`, and an `event_end_date` that must not precede the start date; the wish must be `READY_TO_SCHEDULE`, otherwise `ERR_INVALID_WISH_STATE`. Three guards then run in order. First, a `TRAVEL` wish must hold a medical clearance in `CLEARED` or `CONDITIONAL` status whose `valid_until` falls on or after `event_end_date` — a clearance expiring mid-event is not good enough — or scheduling fails with `ERR_MEDICAL_CLEARANCE_INVALID` (HTTP 422); non-travel wishes skip this guard entirely. Second, the event window must avoid every entry of the child's `treatment_windows`: both the event window and each treatment window are closed intervals, inclusive of both ends, so a conflict exists whenever the event starts on or before a window's last day and that window starts on or before the event's last day — an event beginning exactly on the final day of a treatment window conflicts, because closed intervals share that day. A clash is rejected with `ERR_TREATMENT_BLACKOUT_CONFLICT` (HTTP 409). Third, a `RAPID` wish must start promptly: its `event_start_date` may be no later than the calendar date of the wish's `determined_at` plus 14 days, with the boundary day itself allowed; a later start fails with `ERR_URGENT_SLA_VIOLATION` (HTTP 422). Success creates a wish event in `SCHEDULED` status and moves the wish `READY_TO_SCHEDULE` → `SCHEDULED` with a version increment.

Treatment windows belong to the provider. A `MedicalProvider` replaces the child's `treatment_windows` array wholesale; each entry pairs a `start_date` with an `end_date`, both valid dates with the start no later than the end, and any malformed entry fails the whole replacement with `ERR_TREATMENT_WINDOW_INVALID` (HTTP 422). A successful replacement refreshes the child's `updated_at`.

Completing the event is the culmination, performed by the `WishCoordinator` while the event is `SCHEDULED` — otherwise `ERR_INVALID_EVENT_STATE` (HTTP 409) — and the wish itself is `SCHEDULED`. The grant cascade then runs as one atomic sequence. The event becomes `COMPLETED` and `completed_at` is stamped with the logical clock. The wish becomes `GRANTED` with `granted_at` stamped. The approved plan becomes `COMPLETED`. Each committed line item is consumed to `CONSUMED`, and per line the offer's `quantity_reserved` and `quantity_total` both fall by the line's quantity — consumption shrinks the donation itself, so `quantity_available` does not move — and an offer whose total reaches zero becomes `DEPLETED`. The chapter's books close the loop: `committed_cost_cents` falls by the plan's total, `granted_wish_count` rises by one, `granted_cost_total_cents` rises by the plan's `total_cost_cents`, `granted_cash_total_cents` rises by the plan's `cash_cost_cents`, both `avg_cost_blended_cents` and `avg_cost_cash_cents` are recomputed as described in §2.9 over the chapter's wishes granted within the calendar year of the current logical-clock date, and `posture` is recomputed. Every resource the cascade touches — event, wish, plan, line items, offers, chapter — increments its own `version`.

## 4. Endpoint Definitions

The table below is the complete HTTP surface of the API. Endpoints that create a new resource respond with 201 and the created resource; reads, modifications, transitions, and decisions respond with 200 with the affected resource (or, for the clock, the new clock value). Request payloads, preconditions, validation order, and side effects are specified in §2 and §3 rather than repeated here; list endpoints additionally accept the pagination parameters of §2.3. Authorized roles are spelled exactly as in §2.1.

| Method | Path | Description | Authorized Role(s) |
|--------|------|-------------|--------------------|
| POST | `/wish-grant/_clock/set_current_utc` | Advance the logical clock to `to_iso8601`; sweeps unreserved offers past `valid_until` to `EXPIRED`. | NationalAdmin |
| POST | `/wish-grant/chapters` | Create a chapter with territory prefixes, budget, and cost-per-wish target. | NationalAdmin |
| GET | `/wish-grant/chapters/{id}` | Read a chapter including computed aggregates and `posture`. | NationalAdmin, WishCoordinator, ChapterDirector, NationalDirector, InKindOfficer, EligibilityReviewer |
| POST | `/wish-grant/volunteers` | Register a volunteer in `APPLIED` status for a chapter. | WishCoordinator |
| GET | `/wish-grant/volunteers` | List volunteers; optional filters `chapter_id` and `status`. | WishCoordinator, ChapterDirector, NationalDirector |
| GET | `/wish-grant/volunteers/{id}` | Read one volunteer. | WishCoordinator, ChapterDirector, NationalDirector, Volunteer |
| POST | `/wish-grant/volunteers/{id}/transition` | Advance a volunteer exactly one step via `target_state`. | WishCoordinator |
| POST | `/wish-grant/referrals` | Intake a referral; atomically creates or reuses the child with territory-based chapter assignment. | ReferralSource |
| GET | `/wish-grant/referrals` | List referrals; optional filters `child_id`, `wish_id`, and `status`. | ReferralSource, EligibilityReviewer, MedicalProvider, WishCoordinator |
| GET | `/wish-grant/referrals/{id}` | Read one referral. | ReferralSource, EligibilityReviewer, MedicalProvider, WishCoordinator |
| POST | `/wish-grant/referrals/{id}/certify` | Certify a qualifying condition; `NON_QUALIFYING` auto-denies. | MedicalProvider |
| POST | `/wish-grant/referrals/{id}/determine` | Render the eligibility `decision`; approval creates the wish. | EligibilityReviewer |
| GET | `/wish-grant/children` | List children; optional filter `chapter_id`. | WishCoordinator, EligibilityReviewer, MedicalProvider, ChapterDirector |
| GET | `/wish-grant/children/{id}` | Read one child including `treatment_windows`. | WishCoordinator, EligibilityReviewer, MedicalProvider, ChapterDirector, Volunteer |
| PATCH | `/wish-grant/children/{id}` | Replace the child's `treatment_windows` array wholesale. | MedicalProvider |
| POST | `/wish-grant/wish-teams` | Create or replace a wish's determination team; OCC-guarded on the wish version. | WishCoordinator |
| GET | `/wish-grant/wish-teams` | List wish teams; optional filters `wish_id`, `lead_volunteer_id`, `second_volunteer_id`, and `status`. | WishCoordinator, ChapterDirector, Volunteer |
| GET | `/wish-grant/wish-teams/{id}` | Read one wish team. | WishCoordinator, ChapterDirector, Volunteer |
| POST | `/wish-grant/wish-visits` | Schedule a determination visit for a team. | Volunteer |
| GET | `/wish-grant/wish-teams/{id}/visits` | List a team's visits; optional filter `status`. | WishCoordinator, Volunteer, ChapterDirector |
| POST | `/wish-grant/wish-visits/{id}/conclude` | Conclude a visit with an `outcome`; completion drives the wish to `DETERMINED`. | Volunteer |
| GET | `/wish-grant/wishes` | List wishes; optional filters `child_id`, `chapter_id`, `referral_id`, `status`, `wish_type`, and `urgency`. | WishCoordinator, ChapterDirector, NationalDirector, EligibilityReviewer, Volunteer |
| GET | `/wish-grant/wishes/{id}` | Read one wish. | WishCoordinator, ChapterDirector, NationalDirector, EligibilityReviewer, Volunteer |
| POST | `/wish-grant/donation-offers` | Register an in-kind donation offer; computes its per-unit fair market value. | InKindOfficer |
| GET | `/wish-grant/donation-offers/{id}` | Read one offer including computed quantities and value. | InKindOfficer, WishCoordinator, ChapterDirector |
| POST | `/wish-grant/fulfillment-plans` | Create (or supersede) a fulfillment plan for a wish; OCC-guarded on the wish version. | WishCoordinator, ChapterDirector |
| GET | `/wish-grant/wishes/{id}/fulfillment-plans` | List a wish's fulfillment plans; optional filter `status`. | WishCoordinator, ChapterDirector, NationalDirector |
| GET | `/wish-grant/fulfillment-plans/{id}` | Read one plan including computed totals. | WishCoordinator, ChapterDirector, NationalDirector |
| POST | `/wish-grant/fulfillment-plans/{id}/line-items` | Reserve offer units into a `DRAFT` plan. | WishCoordinator, ChapterDirector |
| GET | `/wish-grant/fulfillment-plans/{id}/line-items` | List a plan's line items. | WishCoordinator, ChapterDirector, NationalDirector, InKindOfficer |
| POST | `/wish-grant/fulfillment-plans/{id}/submit` | Submit a `DRAFT` plan for approval. | WishCoordinator, ChapterDirector |
| POST | `/wish-grant/fulfillment-plans/{id}/approve` | Approve a `PENDING_APPROVAL` plan under segregation-of-duties and fiscal checks. | ChapterDirector, NationalDirector |
| POST | `/wish-grant/fulfillment-plans/{id}/abort` | Cancel a `PENDING_APPROVAL` or `APPROVED` plan; optional `reason`. | ChapterDirector |
| GET | `/wish-grant/donation-offers/{id}/line-items` | List line items reserving a given offer. | InKindOfficer, WishCoordinator, ChapterDirector |
| POST | `/wish-grant/medical-clearances` | Request a medical clearance for a `TRAVEL` wish. | WishCoordinator |
| GET | `/wish-grant/wishes/{id}/medical-clearances` | List a wish's medical clearances; optional filter `status`. | WishCoordinator, MedicalProvider, ChapterDirector |
| POST | `/wish-grant/medical-clearances/{id}/decide` | Provider decision on a clearance; revocation holds the wish, clearance lifts it. | MedicalProvider |
| POST | `/wish-grant/wish-events` | Schedule the wish event around clearance, treatment, and urgency constraints. | WishCoordinator |
| GET | `/wish-grant/wishes/{id}/wish-events` | List a wish's events; optional filter `status`. | WishCoordinator, ChapterDirector, MedicalProvider |
| POST | `/wish-grant/wish-events/{id}/complete` | Complete the event, granting the wish and running the grant cascade. | WishCoordinator |

## 5. Error Code Catalogue

Every error response carries one of the identifiers below in the `error_id` field of the error envelope (§2.2). The conditions that trigger each code are specified in the narratives of §2 and §3 alongside the workflows they guard.

| Error ID | HTTP Status Code |
|----------|------------------|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN_ROLE | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_VOLUNTEER_STATE | 409 |
| ERR_INVALID_REFERRAL_STATE | 409 |
| ERR_INVALID_WISH_STATE | 409 |
| ERR_INVALID_TEAM_STATE | 409 |
| ERR_INVALID_VISIT_STATE | 409 |
| ERR_INVALID_PLAN_STATE | 409 |
| ERR_INVALID_OFFER_STATE | 409 |
| ERR_INVALID_CLEARANCE_STATE | 409 |
| ERR_INVALID_EVENT_STATE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_MEDICAL_CLEARANCE_INVALID | 422 |
| ERR_TEAM_SCHEDULE_OVERLAP | 409 |
| ERR_TREATMENT_BLACKOUT_CONFLICT | 409 |
| ERR_URGENT_SLA_VIOLATION | 422 |
| ERR_DONATION_EXPIRED | 409 |
| ERR_CHILD_AGE_OUT_OF_RANGE | 422 |
| ERR_SELF_REFERRAL_TOO_YOUNG | 422 |
| ERR_DUPLICATE_REFERRAL | 409 |
| ERR_NO_TERRITORY_CHAPTER | 422 |
| ERR_TEAM_DUPLICATE_MEMBER | 422 |
| ERR_VOLUNTEER_NOT_ACTIVE | 409 |
| ERR_TEAM_CHAPTER_MISMATCH | 422 |
| ERR_NOT_TEAM_MEMBER | 403 |
| ERR_AGE_INAPPROPRIATE_METHOD | 422 |
| ERR_CATEGORY_WISH_TYPE_MISMATCH | 422 |
| ERR_WISH_TYPE_NO_CLEARANCE | 422 |
| ERR_CLEARANCE_ALREADY_ACTIVE | 409 |
| ERR_EMPTY_PLAN | 422 |
| ERR_PLAN_ALREADY_APPROVED | 409 |
| ERR_TREATMENT_WINDOW_INVALID | 422 |
| ERR_INSUFFICIENT_DONATION_QTY | 409 |
| ERR_CHAPTER_BUDGET_FROZEN | 409 |
| ERR_CHAPTER_BUDGET_EXCEEDED | 422 |
| ERR_COST_ESCALATION_REQUIRED | 422 |
