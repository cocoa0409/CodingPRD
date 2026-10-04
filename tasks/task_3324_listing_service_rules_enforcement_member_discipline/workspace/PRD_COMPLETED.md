# Listing Service Rules Enforcement API — Product Requirements Document

## 1. Introduction

A national-association-style multiple listing service (MLS) lives or dies by the credibility of its rulebook. Member brokers cooperate on inventory only because every participant trusts that dues are collected on schedule, that listings enter the service within the promised window after public marketing begins, that status changes are recorded promptly and accurately, that offers of cooperative compensation are displayed (or suppressed) exactly as the governing policy revision demands, and that violations are cited, fined, heard, and — when necessary — escalated to professional standards through a process whose panelists are demonstrably disinterested. This document specifies the API that operationalizes that rulebook: membership and dues administration, listing input rules and their automated audits, the citation and fine machinery with its hearing track, code-of-ethics complaints screened by a grievance committee, arbitration of commission disputes between members with a weighted procuring-cause analysis, data licensing to portals and brokers with feed-compliance monitoring, and association consolidation with full governance transition of the absorbed membership.

The system is built around a logical clock rather than the wall clock: dues suspensions, policy-revision activations, listing expiries, screening deadlines, appeal windows, cure windows, and consolidation executions all derive from a server-maintained logical instant that staff operators advance explicitly. Money is carried in integer cents everywhere; strike counts, fine tiers, sanction amounts, and arbitration awards are all deterministic functions of recorded state, so that every disciplinary outcome an operator sees is reproducible from the audit trail. The remainder of this document fixes the global contracts (§2), walks the business workflows in narrative form (§3), and then gives the compact endpoint table (§4) and error catalogue (§5).

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID` and `X-User-Role`. If either header is missing, or `X-User-Role` is not one of the declared roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the role is recognized but not permitted for the endpoint, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

The declared roles, spelled exactly as the server expects them, are `AssociationStaff`, `Member`, `GrievanceMember`, and `HearingPanelist`.

- When `X-User-Role` is `AssociationStaff`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it but never compares it to any entity's `id`.
- When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member`; ownership checks on any resource that references a `Member` — a listing's `listing_member_id`, an invoice's `member_id`, a citation's `member_id`, an ethics case's `respondent_member_id` — compare the resource's foreign-key field to `X-User-ID`. A `Member` acting on a resource owned by a different member id is rejected with `ERR_MEMBER_MISMATCH` (HTTP 403), distinct from the wrong-role rejection `ERR_FORBIDDEN`.
- When `X-User-Role` is `GrievanceMember`, `X-User-ID` is likewise the `id` of the acting `Member` (a member serving on the grievance committee); segregation-of-duties checks compare it against the case's `complainant_member_id`, `respondent_member_id`, and the original panel's `selected_member_ids`.
- When `X-User-Role` is `HearingPanelist`, `X-User-ID` is the `id` of the acting `Member` seated on a hearing panel; the server checks membership in the panel's `selected_member_ids`.

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

List endpoints accept `limit` and `offset` query parameters. `limit` defaults to 10, with a minimum of 1 and a maximum of 100; `offset` defaults to 0. Results are sorted by `created_at` ascending. The `meta` block of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and the Logical Clock

Every persisted entity carries an `id` that is a server-minted UUID with no type prefix. All entities except `ConsolidationEvent` also carry `created_at` and `updated_at` (ISO 8601 UTC timestamps with three fractional digits) and a `version` integer that starts at 1 and increments by exactly 1 on every mutation of that entity. `ConsolidationEvent` is the exception: it carries only `id` and `created_at`; both `updated_at` and `version` are absent from it.

All temporal rules in this document are evaluated against a server-maintained logical clock, never the wall clock. At server startup the logical clock reads exactly 2026-09-01T00:00:00.000Z, and before any clock-setting call it continues to read that default. An `AssociationStaff` operator may set the logical clock to a supplied `to_iso8601` instant (the response echoes the new reading as `now_iso8601`), or advance it by whole days via a capability that accepts an optional `days` parameter defaulting to 1. Advancing the clock re-evaluates scheduled policy-revision activations, dues-suspension checks, and listing expiries against the new instant — in that pinned order: policy-revision activations are applied first (so the display-ruleset version count settles before anything reads it), then dues-suspension checks. Listing expiry, however, is driven exclusively by the compliance checkpoint of §3.10; clock advancement alone never expires a listing.

### 2.5. Money, Precision, and Rounding

All monetary quantities are integer cents. Dues computations use integer cents with no rounding. Where a proration is required (mid-year joins), the prorated base is computed with floor toward zero. Arbitration procuring-cause scores are rounded half-up to two decimal places before tier selection, and the resulting award in cents is rounded half-up to an integer; rounding the claim times the percentage per factor and then summing is forbidden. Sanction amounts, fine amounts, late fees, and credit balances are always integer cents.

### 2.6. Optimistic Concurrency Control

Two write endpoints are guarded by optimistic concurrency control on a parent entity's `version`:

- Scheduling a policy revision requires `expected_association_version` in the request body, carrying the client's last observed `version` of the parent association. If the association's `version` has advanced since that observation, the create is rejected with `ERR_STALE_VERSION` (HTTP 412) — the revision selector on listing activation depends on the full set of `ACTIVE` revisions, and a writer holding a stale association view could publish a revision that silently reorders governance.
- Billing a dues period requires `expected_dues_period_version` matching the period's current `version`. A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412); billing mints one invoice per `ACTIVE` member and a stale view risks double-billing after a corrective period edit.

Endpoints not named here do not take a version field.

### 2.7. Nested Resource Resolution and Validation Priority

Path parameters are validated left-to-right: the association is resolved first, then the office, then the listing; the dues period before the invoice; the case before the panel. A resource that exists but is nested under the wrong parent scope is rejected with `ERR_NOT_FOUND` (HTTP 404), not `ERR_FORBIDDEN`.

When a request violates more than one rule, the rejection is determined by a fixed priority order, evaluated from first to last: (1) authentication — missing or unknown headers, `ERR_UNAUTHENTICATED`; (2) authorization — role not permitted, `ERR_FORBIDDEN`, or right role but wrong member id, `ERR_MEMBER_MISMATCH`; (3) existence — path resources and left-to-right nesting, `ERR_NOT_FOUND`; (4) the association consolidation gate — mutations under a `MERGED` association rejected with `ERR_ASSOCIATION_MERGED`; (5) optimistic concurrency — `ERR_STALE_VERSION` on the two guarded endpoints; (6) source-state legality — `ERR_INVALID_STATE`; (7) the member disciplinary and segregation-of-duties gate — `ERR_MEMBER_SUSPENDED`, `ERR_SCREENING_CONFLICT`, `ERR_APPEAL_CONFLICT`, `ERR_PANEL_SOLE_ACTOR`; (8) the policy and compensation gate — `ERR_COMP_DISPLAY_PROHIBITED`, `ERR_RULESET_MISMATCH`, `ERR_LISTING_FLAGGED`; (9) time-window rules — `ERR_HEARING_WINDOW_CLOSED`, `ERR_SCREENING_OVERDUE`, `ERR_APPEAL_WINDOW_CLOSED`, `ERR_CURE_WINDOW_CLOSED`, `ERR_ARBITRATION_WINDOW_CLOSED`, `ERR_CONSOLIDATION_NOT_DUE`; (10) money rules — `ERR_CREDIT_CAP_EXCEEDED` (the credit-cap check runs before any state change) and `ERR_TENDER_MISMATCH`; (11) cross-association referential integrity — `ERR_CROSS_ASSOCIATION_REFERENCE` (HTTP 422); (12) structural and uniqueness rules — `ERR_DUPLICATE_RESOURCE`, `ERR_SCHEDULE_OVERLAP`, `ERR_LAST_FINE_SCHEDULE`, `ERR_PANEL_POOL_EXHAUSTED`, `ERR_OFFICE_HAS_OPEN_LISTINGS`, `ERR_FACTOR_SCORE_INVALID`, `ERR_NO_FINE_SCHEDULE`, `ERR_POLICY_REVISION_MISSING`. A malformed payload, missing required field, invalid enum value, or out-of-range value is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Input fields beyond the ones an endpoint specifies are silently ignored — including server-computed fields supplied by the client on a create call: the created resource always carries the server-minted defaults regardless of such input (for example, a member create carries `sanction_credit_balance_cents` 0 and `strikes_12m` 0 even when the payload names them).

### 2.8. The Consolidation Gate

An association's `consolidation_state` is one of `ACTIVE`, `MERGING`, or `MERGED`. Mutating endpoints scoped under a `MERGED` association are rejected with `ERR_ASSOCIATION_MERGED` (reads remain allowed). While an association is `MERGING`, creating a new consolidation event naming it as the absorbed party is likewise rejected with `ERR_ASSOCIATION_MERGED`. Listing activation under an association whose `consolidation_state` is `MERGED` fails with the same error.

## 3. Business Logic & Workflows

### 3.1. Chartering Associations, Registering Members, and Opening Offices

An `AssociationStaff` operator charters an association by supplying its globally unique `association_code` (for example `NOR`), its legal `name`, the annual `membership_dues_cents`, the two flat late-fee tiers `late_fee_tier1_cents` and `late_fee_tier2_cents`, and optionally `sanction_credit_cap_cents` — the ceiling on any member's sanction-credit balance, which defaults to 200000 cents when omitted. A new association begins with `consolidation_state` `ACTIVE` and `consolidated_into_id` null. The dues and late-fee amounts must be non-negative. The association collection may be filtered by `consolidation_state` or by `consolidated_into_id`, the self-referential pointer that names the surviving association once a merger executes.

Members are registered into an association by staff with an association-scoped `member_nr` (unique within the association; a collision is rejected with `ERR_DUPLICATE_RESOURCE`) and the member's `full_name`. A new member starts in `membership_state` `ACTIVE` with `mls_access_state` `ENABLED`, a `sanction_credit_balance_cents` of 0, and a `strikes_12m` count of 0. Staff may also seed an initial credit — a goodwill settlement, for example — by posting a credit adjustment carrying `amount_cents` and a required `note`; the credit lands on the member's `sanction_credit_balance_cents` provided the result does not exceed the association's `sanction_credit_cap_cents`, otherwise the adjustment is rejected with `ERR_CREDIT_CAP_EXCEEDED`. The member collection can be filtered by `membership_state`. Like every list endpoint, it is paginated per §2.3: the response envelope carries `limit`, `offset`, `total_count`, and `has_more`, sorted by `created_at` ascending.

An office is opened under an association with a globally unique `office_code` and a designated `broker_member_id` who must be an `ACTIVE` member of the chartering association; a broker from another association — and likewise a broker of the chartering association whose `membership_state` is not `ACTIVE` — trips the cross-association reference rule and is rejected with `ERR_CROSS_ASSOCIATION_REFERENCE` (HTTP 422). Offices open in status `ACTIVE`. An office may be closed by staff only when none of its listings remain in `DRAFT`, `ACTIVE`, or `PENDING`; attempting closure with open listings is rejected with `ERR_OFFICE_HAS_OPEN_LISTINGS`; a successful closure transitions the office to `CLOSED`, which is terminal.

Offices and their brokers are coupled through suspension: when the member named by an office's `broker_member_id` transitions from `ACTIVE` to `SUSPENDED`, the office transitions to `SUSPENDED` as well, and while the office is suspended all of its listings are blocked from activation. When that broker is reinstated from `SUSPENDED` to `ACTIVE`, the office returns to `ACTIVE`. The office collections — both the association-scoped list and the flat list — can be filtered by `status`, and the flat list additionally by `broker_member_id`.

### 3.2. The Dues Cycle: Periods, Billing, Invoices, and Delinquency

Each billing year is represented by a dues period created by staff with a calendar `year`, a `period_start_date` marking the first day of the billing year, a `due_date` (dues are due at the end of that day, 23:59:59.999Z), a `grace_end_date` (the last day of grace; suspension fires at 00:00:00.000Z on the day after), and the `amount_cents` assessed for the year. A period opens in status `OPEN` and the collection can be filtered by `status` or `year`.

Billing is a staff action against an `OPEN` period. Because billing mints one invoice per `ACTIVE` member of the association, the request must carry `expected_dues_period_version` as described in §2.6; a stale view is rejected with `ERR_STALE_VERSION`. On a successful bill the period transitions `OPEN` → `BILLED` and, for every member whose `membership_state` is `ACTIVE`, a dues invoice is created in status `PENDING` with its amounts computed as follows, in this fixed evaluation order — late-fee tier first, then the credit application, then the amount due:

- `base_amount_cents` is a snapshot of the period's `amount_cents` at issuance.
- `days_overdue_at_issue` is the whole number of days between the issuance instant and the period's `due_date`, floored to a day boundary and never below zero.
- `late_fee_cents` is 0 when `days_overdue_at_issue` is 0; the association's `late_fee_tier1_cents` when it is at least 1 and at most 30 (day 30 belongs to tier 1); and the association's `late_fee_tier2_cents` when it is 31 or more — tier 2 replaces tier 1, it is not added to it. Tier selection uses the days at issue, never the days at payment.
- `credit_applied_cents` is the smaller of the member's current `sanction_credit_balance_cents` and the sum of base plus late fee; that amount is debited from the member's balance at issuance.
- `amount_due_cents` is the base plus the late fee minus the applied credit.

Two variants modify the base. When the member's `created_at` falls inside the period's window from `period_start_date` through `due_date`, the member is a mid-year joiner and the base is prorated: the period's `amount_cents` is multiplied by the number of remaining days in the period — computed as the whole days from the member's `created_at` to the `due_date`, plus one — divided by 365, and the result is floored toward zero before any late-fee or credit step. Separately, when a member's `association_id` was re-pointed by an executed consolidation, the member is billed by the surviving association's period at the survivor's `amount_cents` — but if the member already holds any invoice, in any status, for the same calendar year from the absorbed association, the survivor's billing skips that member entirely, so no member is double-billed for a year. In fact the anti-double-billing skip is keyed purely on the calendar year: any member billed under a period who already holds an invoice, in any status, for that calendar year — whatever association the earlier period belongs to — is skipped.

A member settles their own invoice by paying it; the request carries `tender_cents`, which must equal the invoice's `amount_due_cents` exactly — any other amount is rejected with `ERR_TENDER_MISMATCH` (HTTP 409). Only the invoice's own member may pay it; a different member id is `ERR_MEMBER_MISMATCH`. Payment transitions the invoice `PENDING` → `PAID`, stamps `paid_at` with the current logical instant, and then runs the reinstatement chain: if the member now holds zero `PENDING` invoices and their `membership_state` is `SUSPENDED`, the member returns to `ACTIVE`, their `mls_access_state` becomes `ENABLED`, their `strikes_12m` is recomputed (see §3.5), and future hearing-panel eligibility is restored. Reinstatement is unconditional on reaching zero pending invoices — the 30-day window mentioned in the strike computation affects only whether the citation counts toward `strikes_12m`, never whether the member is reinstated.

Staff may instead waive an invoice, transitioning it `PENDING` → `WAIVED`. Waiver is strictly per-invoice: it does not require that the member would then hold zero pending invoices, and it does not refund the `credit_applied_cents` — credits are spent at issuance and are not returned. If the waiver does leave the member with zero `PENDING` invoices while suspended, the same reinstatement chain as payment runs. The invoice collections can be filtered by `member_id`, `dues_period_id`, and `status`.

Suspension arrives by two doors. When the logical clock crosses a period's `grace_end_date` while a member's invoice for that period is still `PENDING`, the member transitions `ACTIVE` → `SUSPENDED` automatically. Alternatively, staff reconcile a `BILLED` period — permitted only once the current logical date is later than the period's `grace_end_date` — which transitions the period `BILLED` → `RECONCILED` and suspends every member of the association whose invoice for that period remains `PENDING`. Either way, suspension disables the member's `mls_access_state` (it becomes `DISABLED`), blocks every listing of that member in `DRAFT`, `ACTIVE`, or `PENDING` from activation and status-change transitions, and excludes the member from all future hearing-panel candidate pools (the member's `hearing_panel_exclusions` list itself is unchanged; the eligibility predicate does the excluding).

A member who has been `SUSPENDED` for at least 90 consecutive days — measured from the `grace_end_date` of the dues period whose lapse triggered the suspension — may be terminated by staff. Termination transitions the member to `TERMINATED`, keeps `mls_access_state` at `DISABLED`, and cascades to the member's listings: every listing in `ACTIVE` where the member is the `listing_member_id` transitions to `WITHDRAWN` with its `accuracy_flag` preserved. Office broker reassignment is out of scope — the listings withdraw; the office remains.

### 3.3. Entering Listings: Drafts, Activation, and the Policy-Revisions Selector

A member enters a listing under their office by supplying the `listing_member_id` (the responsible listing agent — the office's broker or any `ACTIVE` member of that office; a `listing_member_id` who is neither the office's broker nor an `ACTIVE` member is rejected with `ERR_MEMBER_SUSPENDED`; the member must belong to the office's association, else `ERR_CROSS_ASSOCIATION_REFERENCE`), a globally unique `mls_number`, the `property_address`, the `list_price_cents` (strictly greater than zero), optionally the `public_marketing_at` instant at which public marketing first began, and optionally an `offer_comp_cents` amount declaring the offer of cooperative compensation, which defaults to 0. The listing is created in status `DRAFT` with `accuracy_flag` `CLEAN`.

Activation — by the listing's own member — transitions the listing from `DRAFT` (or from `WITHDRAWN`, on reactivation) to `ACTIVE`. The gate is layered: the acting `X-User-ID` must be the listing's `listing_member_id`; the listing member must be `ACTIVE` with `mls_access_state` `ENABLED`, otherwise the activation is rejected with `ERR_MEMBER_SUSPENDED`; the office must be `ACTIVE`; and the office's association must not be `MERGED`, otherwise `ERR_ASSOCIATION_MERGED`. On activation the listing's `activated_at` is stamped with the current logical instant, `status_changed_at` is set to the same instant, and a `StatusChange` record is appended.

Activation also binds the listing to its governing policy revision. The server selects, among the association's `ACTIVE` policy revisions, the one with the greatest `effective_at` that is still at or before the activation instant, and superseded revisions are never selected for new activations. If no such revision exists, activation is rejected with `ERR_POLICY_REVISION_MISSING`. The selected revision's id is recorded as the listing's `policy_revision_id`. On reactivation from `WITHDRAWN`, the selector runs again and a fresh `policy_revision_id` is chosen — but the clear-cooperation audit does not run again, because the original `public_marketing_at` was already consumed by the first activation.

Two compensation rules hang off the governing revision. Whenever the governing revision's `comp_display_mode` is `COMP_DISPLAY_OFF`, `offer_comp_cents` is forced to 0 on the listing and any attempt to supply a positive amount is rejected; in particular, a listing create that supplies a positive `offer_comp_cents` while the currently governing revision is `COMP_DISPLAY_OFF` is rejected with `ERR_COMP_DISPLAY_PROHIBITED` — an omitted or zero amount is accepted and stored as 0 — and likewise, if the request to activate carries a listing whose `offer_comp_cents` is greater than zero while the governing revision's `comp_display_mode` is `COMP_DISPLAY_OFF`, activation is rejected outright with `ERR_COMP_DISPLAY_PROHIBITED` — this is a validation, not a clamp; the value is never silently forced to zero at activation time. The clear-cooperation audit is the other: when `public_marketing_at` is set and the activation instant is later than exactly 24 hours after `public_marketing_at`, the listing is in violation of the clear-cooperation obligation and the server automatically creates a citation with `rule_code` `CLEAR_COOP` and `source` `AUTO_LATE_LISTING` against the `listing_member_id`, referencing the listing. The deadline boundary is inclusive: activation at exactly the deadline instant is timely, and activation one second after it is late. The audit does not alter the listing's `accuracy_flag`.

### 3.4. Moving a Listing Through Its Life: Status Changes, Lateness Audits, and the Accuracy Flag

Once `ACTIVE`, a listing moves through `PENDING` and on to `SOLD`, or out of the market to `WITHDRAWN` or `CANCELLED`. The member responsible requests a status change by naming the target `to_status` and supplying `business_effective_at` — the instant the off-MLS event actually occurred, such as the contract signing. The same member-identity and member-standing gates as activation apply: the actor must be the `listing_member_id`, and the listing member must be `ACTIVE` and `ENABLED` (`ERR_MEMBER_SUSPENDED` otherwise).

Every status change appends a `StatusChange` audit record capturing the `listing_id`, the `from_status`, the `to_status`, the supplied `business_effective_at`, and the `recorded_at` logical instant at which the change was entered; the listing's `status_changed_at` is refreshed to the same instant. A `StatusChange` is append-only: it is created in the single state `RECORDED`, which is both its initial and its terminal state, and it is created only by listing transitions. Status changes may be listed per listing as an audit trail, or queried flat filtered by `listing_id` or by the `auto_citation_id` of the citation a late entry spawned.

For transitions into `PENDING` and `SOLD`, a lateness audit runs against a 48-hour grace window. The elapsed whole hours between `business_effective_at` and `recorded_at` are computed with floor toward zero; the recorded `late_by_hours` is that elapsed count minus 48, never below zero. The boundary is exact: recording precisely 48 hours after the business event is timely; 48 hours and one second floors to 48 whole hours and is still timely; 49 whole hours yields `late_by_hours` of 1 and is late. When `late_by_hours` is greater than zero, the server automatically creates a citation with `rule_code` `LATE_STATUS` and `source` `AUTO_LATE_STATUS` against the listing member — its id is stored on the status change as `auto_citation_id` — and sets the listing's `accuracy_flag` to `FLAGGED`. The cascade matters: a flagged listing cannot be withdrawn or cancelled until the flag clears. For status changes other than those into `PENDING` or `SOLD`, `late_by_hours` is 0 and no audit fires.

Withdrawal and cancellation by the member are gated on the flag: a request to move an `ACTIVE` listing to `WITHDRAWN` or `CANCELLED` while `accuracy_flag` is `FLAGGED` is rejected with `ERR_LISTING_FLAGGED`. Withdrawal is reversible — the listing may later be reactivated under the activation rules — while `CANCELLED` and `SOLD` are terminal.

Two system-driven transitions complete the machine. A compliance checkpoint run (§3.10) expires any listing that has been `ACTIVE` for more than 365 days, moving it to `EXPIRED` and recording a status change whose `business_effective_at` is the checkpoint instant. And when a member is terminated, each of their `ACTIVE` listings moves to `WITHDRAWN` by cascade — this edge carries no `accuracy_flag` precondition, unlike the member-action withdrawal edge, and the flag is preserved across it.

The listing collections — association-scoped and flat — can be filtered by `status`, `office_id`, and `listing_member_id`; the flat list additionally accepts `policy_revision_id` to find every listing governed by a particular revision.

### 3.5. Citations, Fine Schedules, and the Sanction-Credit Ledger

Rules violations are punished through citations. Staff issue a citation by naming the cited `member_id`, the `rule_code` — one of `LATE_LISTING`, `LATE_STATUS`, `INACCURACY`, `CLEAR_COOP`, `COMP_OFFER`, or `FEED_ABUSE` — and, when the violated rule is listing-scoped, the `listing_id` (null for membership-rule citations). The cited member must belong to the citing association, else `ERR_CROSS_ASSOCIATION_REFERENCE`. Citations also arise automatically from the clear-cooperation audit (`source` `AUTO_LATE_LISTING`), the status-change lateness audit (`source` `AUTO_LATE_STATUS`), and feed-compliance failures (`source` `STAFF` written by the audit machinery); a staff-issued citation carries `source` `STAFF` by default.

Every citation's fine is pinned at issuance by the association's fine schedule. A fine-schedule row is created by staff with a `rule_code`, a flat `fine_amount_cents` strictly greater than zero, an `effective_from` instant, and an optional `effective_to` instant (null means open-ended). Rows for the same association and `rule_code` must never overlap under half-open semantics — a row applies to citations assessed at or after `effective_from` and strictly before `effective_to`, so a citation assessed exactly at one row's `effective_to` belongs to the next row, and adjacent rows (the second row's `effective_from` equal to the first row's `effective_to`) neither overlap nor gap. An overlapping submission is rejected with `ERR_SCHEDULE_OVERLAP`. At citation creation the server finds the single `ACTIVE` row covering the citation's `assessed_at`; if none exists, creation is rejected with `ERR_NO_FINE_SCHEDULE`. The matched row's amount becomes the citation's `fine_amount_cents` — citation fines are flat per schedule and repeat-offense multipliers never apply — and the citation records a `fine_schedule_key` of the form rule-code, an at-sign, and the calendar date of `assessed_at`, pinning the schedule row used. A schedule row may be retired by staff, transitioning it `ACTIVE` → `RETIRED`, but retiring the last remaining `ACTIVE` row for an association and rule code is forbidden and rejected with `ERR_LAST_FINE_SCHEDULE`. The schedule list can be filtered by `rule_code` and `status`.

A citation opens in status `OPEN`. The cited member has two doors out. The first is payment: the member tenders `tender_cents`, which must equal the `fine_amount_cents` minus the portion covered by their sanction-credit balance — credits auto-apply up to the smaller of the fine and the balance, and the member tenders only the remainder; any other tender is rejected with `ERR_TENDER_MISMATCH`. Before any state change, the server checks that crediting the fine amount to the member's `sanction_credit_balance_cents` would not exceed the association's `sanction_credit_cap_cents`; on overflow the payment is rejected with `ERR_CREDIT_CAP_EXCEEDED` and nothing changes. A successful payment transitions the citation `OPEN` → `PAID`, credits the full `fine_amount_cents` to the member's balance, recomputes the member's `strikes_12m`, and runs the unflag chain: if the citation references a listing whose `accuracy_flag` is `FLAGGED` and no other `OPEN` or `HEARING_PENDING` citation references that listing, the flag returns to `CLEAN`, unblocking withdrawal and cancellation.

A member holding a `PAID` citation may additionally top up their own credit balance through that citation by donating `amount_cents` — an external settlement credit with no fine linkage. The donation is allowed only when the citation is `PAID` (only settled fines yield stable credits) and only when the resulting balance stays at or below the association cap; landing exactly at the cap is permitted, exceeding it is `ERR_CREDIT_CAP_EXCEEDED`.

The second door is a hearing. The cited member may request a hearing within 20 days of the citation's `assessed_at`; a request at exactly the instant 20 days after `assessed_at` is still permitted, and only a request after that instant is rejected with `ERR_HEARING_WINDOW_CLOSED`, and a second request once `hearing_requested` is already true — like any action attempted on an entity that is not in a legal source state for it, such as paying an already-`PAID` citation or invoice, or ruling on an already-`DECIDED` panel — is rejected with `ERR_INVALID_STATE`. Requesting a hearing transitions the citation `OPEN` → `HEARING_PENDING` and sets `hearing_requested` to true. What happens next is decided by a hearing panel (§3.8): if the panel overturns, the citation transitions to `WAIVED` and no credit accrues, since nothing was paid; if the panel upholds, the branch depends on the member's live `strikes_12m` at the ruling instant — below 3 strikes the citation transitions to `PAID` with the same credit accrual (cap check included; on overflow the ruling itself is rejected with `ERR_CREDIT_CAP_EXCEEDED` and the citation stays `HEARING_PENDING`), strikes recompute, and unflag chain as a direct payment, while at 3 or more strikes the citation transitions to `ESCALATED` instead, no credit accrues, and the case is marked as handed off to the association's professional-standards process — no ethics case is auto-created. All three branches run the listing unflag chain.

The `strikes_12m` count itself is recomputed whenever a citation is paid, whenever a member is reinstated from suspension, and whenever an ethics sanction is applied. The count includes a citation when all of the following hold: the citation belongs to the member; its status is `PAID`; its `assessed_at` falls within the trailing 365 days — the window is half-open, excluding the instant exactly 365 days ago and including now; and the member's next reinstatement after that citation's `assessed_at` occurred at or after the citation and within 30 days of it. When several reinstatements exist, the first reinstatement at or after the citation's assessment is the one measured. If no reinstatement exists after the citation — the never-suspended member — the citation still counts. When the recomputation was triggered by an ethics ruling, the ethics sanction itself never adds a strike; sanctions are fine-only, and only paid citations count. Citation lists, association-scoped or flat, can be filtered by `member_id`, `listing_id`, `status`, and `rule_code`.

### 3.6. Ethics Complaints: Filing, Grievance Screening, Hearings, and Appeals

A member files a code-of-ethics complaint against another member by naming the `respondent_member_id` — which must differ from the complainant, since the complainant is taken from the acting member's identity — and the `article_code` of the code-of-ethics article cited, such as `A16`. Filing stamps `filed_at`, computes `grievance_review_due_at` as exactly 45 days after filing, and immediately opens screening: the case transitions `FILED` → `GRIEVANCE_SCREENING` automatically.

A `GrievanceMember` screens the case by submitting an `outcome` of `DISMISSED` or `FORWARDED`. Two guards apply, evaluated in this order: first the screener must be neither the complainant nor the respondent, else `ERR_SCREENING_CONFLICT` (the segregation-of-duties gate of §2.7 tier 7); then the screening must conclude no later than `grievance_review_due_at`, else `ERR_SCREENING_OVERDUE` (the time-window gate of §2.7 tier 9) — when both would trip, the conflict is reported. A dismissal records `screening_outcome` `DISMISSED` and transitions the case to the terminal state `DISMISSED`; a forwarding records `screening_outcome` `FORWARDED` and transitions the case to `HEARING_SCHEDULED`, awaiting a panel.

Once a convened panel for the case holds its hearing, the case transitions `HEARING_SCHEDULED` → `HEARD`; when the panel rules, the case transitions `HEARD` → `DECIDED`. An upholding decision sets the case's `sanction_cents` from the respondent's live `strikes_12m` read at the ruling instant — after the panel's decision is recorded but before the case transitions, and independently of any citation branch that a different panel might be ruling on: 50000 cents when the respondent has no strikes, 100000 cents at one strike, 250000 cents at two, and 500000 cents at three or more. The sanction is applied as a fine-only ledger entry and never feeds the respondent's credit balance. If the respondent's `strikes_12m` is at least 3 after the sanction, the respondent is suspended — `membership_state` transitions to `SUSPENDED` with the full suspension cascade of §3.2. An overturning decision sets no sanction.

The respondent — and only the respondent — may appeal within 20 days of the linked panel's ruling instant (the ruling instant is the `updated_at` of the `DECIDED` panel); an appeal at exactly the ruling instant plus 20 days is still permitted, and only a later appeal is rejected with `ERR_APPEAL_WINDOW_CLOSED`. Appeal transitions the case `DECIDED` → `APPEALED`. A `GrievanceMember` then rules on the appeal, transitioning the case `APPEALED` → `FINAL`, but the ruling member must be neither complainant, nor respondent, nor a member of the original panel's `selected_member_ids`; a conflict is rejected with `ERR_APPEAL_CONFLICT`. Ethics-case lists can be filtered by `status`, `complainant_member_id`, and `respondent_member_id`.

### 3.7. Arbitrating Commission Disputes and the Procuring-Cause Analysis

When two members dispute a commission, the complainant files an arbitration case naming the `respondent_member_id` (again distinct from the complainant), the `listing_id` of the transaction whose commission is disputed, and the `claim_amount_cents` in dispute, which must be strictly positive. The listing must be `SOLD`, and the filing window is 180 days from the listing's closing date — the closing date being the `business_effective_at` of the status change into `SOLD` (or, failing that, the status change's `recorded_at`); a filing after the window is rejected with `ERR_ARBITRATION_WINDOW_CLOSED`. Filing stamps `filed_at` and transitions the case `FILED` → `MEDIATION_OFFERED` automatically. No filing fee applies.

Staff then record the mediation outcome with an `outcome` of `SETTLED` or `DECLINED`. A settlement transitions the case to the terminal state `MEDIATED`; a decline transitions it to `ARBITRATION_SCHEDULED`, awaiting a panel.

When the panel holds its hearing, the holding panelist must supply `factor_scores`: a map from each of the five procuring-cause factor keys — `F1_FIRST_CONTACT`, `F2_CONTINUOUS_EFFORT`, `F3_AGENCY_DISCLOSURE`, `F4_CONTRACT_ROLE`, and `F5_ABANDONMENT` — to an integer from 0 to 10. A missing key or an out-of-range value is rejected with `ERR_FACTOR_SCORE_INVALID`. The scores are stored on the case as `procuring_cause_factor_scores`, and the case transitions `ARBITRATION_SCHEDULED` → `HEARD`.

When the panel rules, an overturning decision sets `award_amount_cents` to 0. An upholding decision computes the award as follows. The weighted score is the sum of each factor's score times its weight — 0.30 for first contact, 0.25 for continuous effort, 0.15 for agency disclosure, 0.20 for contract role, and 0.10 for abandonment — yielding a value between 0.00 and 10.00. The score is rounded half-up to two decimal places first, and only then is the award percentage selected: a score of at least 7.00 awards the full claim (the 7.00 boundary is inclusive); at least 5.00 awards 60 percent; at least 3.00 awards 30 percent; below 3.00 awards nothing. One override runs after the score rounding and before tier selection: when `F5_ABANDONMENT` is 8 or higher — the respondent abandoned the transaction — the percentage is forced to zero regardless of the weighted score. Finally the award in cents is the claim amount times the selected percentage, rounded half-up to an integer; the claim is always between 0 and the claim amount inclusive. The case transitions `HEARD` → `AWARDED`. Arbitration-case lists can be filtered by `status`, `complainant_member_id`, `respondent_member_id`, and `listing_id`.

### 3.8. Hearing Panels: Selection, Hearings, and Rulings

A single panel type serves all three case kinds. Staff convene a panel by naming the `case_type` — `CITATION`, `ETHICS`, or `ARBITRATION` — and the `case_id` of a case of that kind: a citation in `HEARING_PENDING`, an ethics case in `HEARING_SCHEDULED`, or an arbitration case in `ARBITRATION_SCHEDULED`. The `case_id` must resolve under the named `case_type` within the convening association, else `ERR_CROSS_ASSOCIATION_REFERENCE`.

Convening runs the selector policy over the association's membership. The case's subject set is the cited member for a citation, or the complainant and respondent for an ethics or arbitration case. A member is eligible when they are `ACTIVE` with `mls_access_state` `ENABLED`, belong to the panel's association, are not in the subject set, are not in the union of the subjects' `hearing_panel_exclusions` lists — each member's exclusion list contains the member themself, every member of their own association, and the respondents of any open or decided arbitration case in which they are complainant or respondent, so arbitration counterparties exclude each other's whole dispute set — and have not served on any `DECIDED` panel for the same `case_id`. Eligible members are ranked by fewest `strikes_12m` first, with ties broken by earliest `created_at` — seniority, never the member id. Fewer than three eligible members rejects the convene with `ERR_PANEL_POOL_EXHAUSTED`; otherwise the first three, in ranked order, become the panel's `selected_member_ids`, and `convene_at` stamps the selection snapshot. Later member suspensions do not retroactively invalidate a seated panel.

A seated panelist holds the hearing — for arbitration panels this is where `factor_scores` are supplied and validated as described in §3.7. Holding the hearing transitions the panel `CONVENED` → `HEARING_HELD` and advances the linked case: an ethics case moves `HEARING_SCHEDULED` → `HEARD`, an arbitration case moves `ARBITRATION_SCHEDULED` → `HEARD`, while a citation has no intermediate state and stays `HEARING_PENDING`.

A panelist then rules by submitting a `decision` of `UPHOLD` or `OVERTURN`, transitioning the panel `HEARING_HELD` → `DECIDED`. Segregation of duties applies within the panel: the panelist who triggered the hearing must not be the panelist who rules, and a violation is rejected with `ERR_PANEL_SOLE_ACTOR`. The ruling cascades by case type: for a citation, the branch logic of §3.5 runs — `PAID` on an uphold below 3 strikes, `ESCALATED` on an uphold at 3 or more, `WAIVED` on an overturn, each with its credit, strikes, and unflag chains; for an ethics case, the sanction chain of §3.6 runs; for an arbitration case, the award computation of §3.7 runs. Panel lists can be filtered by `case_type`, `case_id`, and `status`.

### 3.9. Data Licensing, Display Rules, and Feed Compliance

Associations license listing data to portals and brokers. Staff create a license with a `licensee_name` unique within the association, a `scope` of `IDX` (public display), `VOW` (gated brokerage), or `BACKOFFICE` (internal analytics), the `display_ruleset_version` the licensee agreed to, and the `listing_field_allowlist` of listing field names the licensee may display. A license opens in status `PENDING` with `feed_sync_state` `STALE`.

An association's current display-ruleset version is defined as the count of its policy revisions in status `ACTIVE` or `SUPERSEDED`. This definition sits atop a circular-looking dependency — the ruleset version feeds license compliance, a license audit can create a citation, citation payment changes strikes — so the evaluation order is pinned: first count revisions, then evaluate the license check, then issue any citation; strikes never feed back into the ruleset version. Activating a license requires its `display_ruleset_version` to equal the association's current ruleset version; a mismatch is rejected with `ERR_RULESET_MISMATCH`. Activation transitions the license `PENDING` → `ACTIVE` and leaves `feed_sync_state` `STALE` until the first feed sync.

A feed sync projects the association's listings into the licensee's payload, with the projection varying by scope. For `IDX` and `VOW` scopes, only listings in `ACTIVE` or `PENDING` are included and only allowlisted fields are projected; `VOW` additionally always appends `office_id`. For `BACKOFFICE` scope, listings in every status except `DRAFT` — that is, `ACTIVE`, `PENDING`, `SOLD`, `WITHDRAWN`, `EXPIRED`, and `CANCELLED` — are included with all fields. When the governing `ACTIVE` policy revision's `comp_display_mode` is `COMP_DISPLAY_OFF`, `offer_comp_cents` is stripped from both variants at sync time even when the licensee's allowlist names it; the same strip applies on every sync after such a revision activates. A successful sync sets `feed_sync_state` to `CURRENT`, records the projected count on the license as `last_synced_listing_count`, and reports the `projected_listing_count`, whether `comp_fields_stripped` occurred, and the resulting `feed_sync_state`.

Staff audit a license's feed compliance at any time. The audit stamps `last_audit_at`; when it finds a violation — the allowlist contains `offer_comp_cents` while the governing revision suppresses compensation display, or the license's `display_ruleset_version` has drifted from the association's current ruleset version — the license transitions `ACTIVE` → `SUSPENDED` and the server automatically creates a citation with `rule_code` `FEED_ABUSE` and `source` `STAFF` against a deterministically chosen member: the `broker_member_id` of the office owning the association's most recently activated `ACTIVE` listing, with ties on `activated_at` broken by earliest `created_at`; when the association has no `ACTIVE` listing at all, the member is instead the broker of the association's earliest-created office, and when the association has no offices either, no citation is created and `auto_citation_id` is null. The audit response reports `violation_found` and the `auto_citation_id`.

A suspended license may be cured: the cure must be submitted within 30 days of `last_audit_at` — a cure at exactly `last_audit_at` plus 30 days is still permitted, and only a later cure is rejected with `ERR_CURE_WINDOW_CLOSED` — and the same request logically re-runs the compliance check, which must now pass, otherwise the cure is rejected with `ERR_RULESET_MISMATCH`. A successful cure returns the license to `ACTIVE` with `feed_sync_state` reset to `STALE`. A license may also be terminated outright, transitioning `ACTIVE` → `TERMINATED`, which is terminal. License lists can be filtered by `status` and `scope`.

### 3.10. Policy Revisions, Consolidation, and the Compliance Checkpoint

Policy change is versioned through policy revisions. Staff schedule a revision against an association by supplying a `revision_code` unique within the association (a human code such as `LIT-2024-COMP`; duplicates are `ERR_DUPLICATE_RESOURCE`), the `effective_at` instant from which the revision governs new events, the `comp_display_mode` — `COMP_DISPLAY_ON` to show the offer of cooperative compensation on listings, or `COMP_DISPLAY_OFF` to suppress compensation fields everywhere — and the OCC guard `expected_association_version` of §2.6. A new revision is `SCHEDULED`, and scheduling it increments the parent association's `version` by 1. When the logical clock reaches or passes `effective_at`, the revision activates — including the case where `effective_at` is already at or before the current logical instant at scheduling time, in which case the revision activates immediately as part of the same scheduling call: it transitions `SCHEDULED` → `ACTIVE`, and every other `ACTIVE` revision of the same association with an earlier `effective_at` transitions to `SUPERSEDED` — the newest-effective revision wins. From that activation onward, active licenses of the association keep their recorded `display_ruleset_version` but must strip `offer_comp_cents` from their projected allowlist on the next feed sync when the new revision's mode is `COMP_DISPLAY_OFF`. Revision lists can be filtered by `status`.

Consolidation merges one association into another. Staff schedule the event against the surviving association by naming the `absorbed_association_id` — which must differ from the survivor — and a future `effective_at`. Scheduling transitions the event to `SCHEDULED` and moves the absorbed association's `consolidation_state` from `ACTIVE` to `MERGING`; an association may cycle between `MERGING` and `ACTIVE` repeatedly as events are scheduled and cancelled. Cancelling the event — permitted only before `effective_at` — transitions it to `CANCELLED` and returns the absorbed association to `ACTIVE`. Executing the event requires the current logical instant to be at or after `effective_at`, else `ERR_CONSOLIDATION_NOT_DUE`, and requires the absorbed association to be in `MERGING`. Execution transitions the event to `EXECUTED`, moves the absorbed association to `MERGED` with `consolidated_into_id` pointing at the survivor, re-points every member of the absorbed association to the survivor while preserving each member's `membership_state` (bumping each re-pointed member's `version`), terminates every `ACTIVE` data license of the absorbed association, and leaves dues posture as follows: invoices stay with their member — who now belongs to the survivor — and each `OPEN` or `BILLED` dues period of the absorbed association becomes `RECONCILED` only if it was `BILLED`, otherwise it stays `OPEN` under the now-frozen absorbed association. The survivor's next billing then applies the consolidated-member variant of §3.2. Consolidation-event lists can be filtered by `status`, `survivor_association_id`, and `absorbed_association_id`.

Finally, staff may run a compliance checkpoint against an association. The checkpoint expires every listing that has been `ACTIVE` for more than 365 days — each such listing transitions to `EXPIRED` with a status-change record whose `business_effective_at` is the checkpoint instant — and re-derives the license-compliance posture of the association. The response reports the `expired_listing_count`.

## 4. Endpoint Definitions

All endpoints are mounted under `/mls`. Creating a new resource returns 201; modifications and action endpoints return 200. Reads return 200. Error responses carry the codes catalogued in §5. Request bodies, response payloads, and side effects are as narrated in §3; this table is a routing index only.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /mls/_clock/set_current_utc | Set the logical clock to `to_iso8601` | AssociationStaff |
| POST | /mls/_clock/advance_day | Advance the logical clock by whole days (default 1) | AssociationStaff |
| POST | /mls/associations | Create association | AssociationStaff |
| GET | /mls/associations | List associations (filter `consolidation_state`, `consolidated_into_id`) | AssociationStaff |
| GET | /mls/associations/{id} | Get association | AssociationStaff, Member, GrievanceMember, HearingPanelist |
| GET | /mls/associations/{id}/members | List members of association (filter `membership_state`) | AssociationStaff, GrievanceMember, HearingPanelist, Member |
| GET | /mls/associations/{id}/members/{memberId} | Get member | AssociationStaff, Member, GrievanceMember, HearingPanelist |
| POST | /mls/associations/{id}/members | Register member (starts ACTIVE with MLS access ENABLED) | AssociationStaff |
| POST | /mls/associations/{id}/members/{memberId}/terminate | Terminate a member suspended at least 90 days | AssociationStaff |
| POST | /mls/associations/{id}/members/{memberId}/credit-adjustments | Seed a sanction-credit adjustment with a reason note | AssociationStaff |
| GET | /mls/associations/{id}/offices | List offices of association (filter `status`) | AssociationStaff, Member |
| GET | /mls/associations/{id}/offices/{officeId} | Get office | AssociationStaff, Member |
| POST | /mls/associations/{id}/offices | Create office | AssociationStaff |
| POST | /mls/associations/{id}/offices/{officeId}/close | Close office (no open listings) | AssociationStaff |
| GET | /mls/associations/{id}/listings | List listings of association across offices | AssociationStaff, Member, HearingPanelist |
| GET | /mls/associations/{id}/offices/{officeId}/listings/{listingId} | Get listing | AssociationStaff, Member, HearingPanelist |
| GET | /mls/associations/{id}/offices/{officeId}/listings/{listingId}/status-changes | List status changes of a listing (audit trail) | AssociationStaff, Member, HearingPanelist |
| POST | /mls/associations/{id}/offices/{officeId}/listings | Create listing in DRAFT | Member |
| POST | /mls/associations/{id}/offices/{officeId}/listings/{listingId}/activate | Activate listing (DRAFT or WITHDRAWN to ACTIVE); runs revision selector and clear-coop audit | Member |
| POST | /mls/associations/{id}/offices/{officeId}/listings/{listingId}/status | Change listing status; `business_effective_at` drives the lateness audit | Member |
| GET | /mls/associations/{id}/dues-periods | List dues periods (filter `status`, `year`) | AssociationStaff, Member |
| GET | /mls/associations/{id}/dues-periods/{periodId} | Get dues period | AssociationStaff, Member |
| POST | /mls/associations/{id}/dues-periods | Create dues period | AssociationStaff |
| POST | /mls/associations/{id}/dues-periods/{periodId}/bill | Bill all ACTIVE members (OCC-guarded on period version) | AssociationStaff |
| POST | /mls/associations/{id}/dues-periods/{periodId}/reconcile | Reconcile period: suspend members with PENDING invoices | AssociationStaff |
| GET | /mls/associations/{id}/dues-invoices | List dues invoices (filter `member_id`, `dues_period_id`, `status`) | AssociationStaff, Member |
| GET | /mls/associations/{id}/dues-invoices/{invoiceId} | Get dues invoice | AssociationStaff, Member |
| POST | /mls/associations/{id}/dues-invoices/{invoiceId}/pay | Pay own invoice; `tender_cents` must equal `amount_due_cents` | Member |
| POST | /mls/associations/{id}/dues-invoices/{invoiceId}/waive | Waive an invoice (no credit refund) | AssociationStaff |
| GET | /mls/associations/{id}/citations | List citations of association (filter `member_id`, `listing_id`, `status`, `rule_code`) | AssociationStaff, Member |
| GET | /mls/associations/{id}/citations/{citationId} | Get citation | AssociationStaff, Member |
| POST | /mls/associations/{id}/citations | Issue citation (staff) | AssociationStaff |
| POST | /mls/associations/{id}/citations/{citationId}/pay | Pay citation fine (credits auto-apply; tender covers remainder) | Member |
| POST | /mls/associations/{id}/citations/{citationId}/request-hearing | Request hearing within 20 days of assessment | Member |
| POST | /mls/associations/{id}/citations/{citationId}/donate-credit | Top up own sanction-credit balance; cap-checked | Member |
| GET | /mls/associations/{id}/fine-schedules | List fine schedule rows (filter `rule_code`, `status`) | AssociationStaff |
| POST | /mls/associations/{id}/fine-schedules | Create fine schedule row (half-open non-overlap enforced) | AssociationStaff |
| POST | /mls/associations/{id}/fine-schedules/{scheduleId}/retire | Retire a schedule row (last-row retirement forbidden) | AssociationStaff |
| GET | /mls/associations/{id}/ethics-cases | List ethics cases (filter `status`, `respondent_member_id`, `complainant_member_id`) | AssociationStaff, GrievanceMember, HearingPanelist, Member |
| GET | /mls/associations/{id}/ethics-cases/{caseId} | Get ethics case | AssociationStaff, GrievanceMember, HearingPanelist, Member |
| POST | /mls/associations/{id}/ethics-cases | File ethics complaint (auto-enters GRIEVANCE_SCREENING) | Member |
| POST | /mls/associations/{id}/ethics-cases/{caseId}/screen | Grievance screening (outcome DISMISSED or FORWARDED) | GrievanceMember |
| POST | /mls/associations/{id}/ethics-cases/{caseId}/appeal | Respondent appeals within 20 days of ruling | Member |
| POST | /mls/associations/{id}/ethics-cases/{caseId}/appeal-ruling | Appeal ruling (ruling member must not be party nor original panelist) | GrievanceMember |
| GET | /mls/associations/{id}/arbitration-cases | List arbitration cases (filter `status`, parties, `listing_id`) | AssociationStaff, Member, HearingPanelist |
| GET | /mls/associations/{id}/arbitration-cases/{caseId} | Get arbitration case | AssociationStaff, Member, HearingPanelist |
| POST | /mls/associations/{id}/arbitration-cases | File commission dispute (listing must be SOLD; window = closing + 180 days) | Member |
| POST | /mls/associations/{id}/arbitration-cases/{caseId}/mediation-outcome | Record mediation outcome (SETTLED or DECLINED) | AssociationStaff |
| GET | /mls/associations/{id}/hearing-panels | List hearing panels (filter `case_type`, `case_id`, `status`) | AssociationStaff, HearingPanelist, GrievanceMember |
| GET | /mls/associations/{id}/hearing-panels/{panelId} | Get hearing panel | AssociationStaff, HearingPanelist, GrievanceMember |
| POST | /mls/associations/{id}/hearing-panels | Convene panel for a CITATION, ETHICS, or ARBITRATION case; runs panel selector | AssociationStaff |
| POST | /mls/associations/{id}/hearing-panels/{panelId}/hold-hearing | Hold hearing (panelist only); arbitration requires `factor_scores` | HearingPanelist |
| POST | /mls/associations/{id}/hearing-panels/{panelId}/rule | Rule on the case (different panelist than hold-hearing); decision UPHOLD or OVERTURN | HearingPanelist |
| GET | /mls/associations/{id}/data-licenses | List data licenses (filter `status`, `scope`) | AssociationStaff |
| GET | /mls/associations/{id}/data-licenses/{licenseId} | Get data license | AssociationStaff |
| POST | /mls/associations/{id}/data-licenses | Create data license (PENDING) | AssociationStaff |
| POST | /mls/associations/{id}/data-licenses/{licenseId}/activate | Activate license (ruleset must match) | AssociationStaff |
| POST | /mls/associations/{id}/data-licenses/{licenseId}/sync-feed | Sync feed; returns projected listing payload per scope variant | AssociationStaff |
| POST | /mls/associations/{id}/data-licenses/{licenseId}/audit-feed | Feed-compliance audit; on violation suspends license and auto-cites the deterministic broker | AssociationStaff |
| POST | /mls/associations/{id}/data-licenses/{licenseId}/cure | Cure a suspended license within 30 days of audit | AssociationStaff |
| POST | /mls/associations/{id}/data-licenses/{licenseId}/terminate | Terminate license | AssociationStaff |
| GET | /mls/associations/{id}/policy-revisions | List policy revisions (filter `status`) | AssociationStaff, Member |
| GET | /mls/associations/{id}/policy-revisions/{revisionId} | Get policy revision | AssociationStaff, Member |
| POST | /mls/associations/{id}/policy-revisions | Schedule policy revision (OCC-guarded on association version) | AssociationStaff |
| GET | /mls/associations/{id}/consolidations | List consolidation events where association is survivor or absorbed | AssociationStaff |
| POST | /mls/associations/{id}/consolidations | Schedule consolidation (path association is the survivor) | AssociationStaff |
| POST | /mls/associations/{id}/consolidations/{eventId}/execute | Execute consolidation at or after `effective_at` | AssociationStaff |
| POST | /mls/associations/{id}/consolidations/{eventId}/cancel | Cancel scheduled consolidation before `effective_at` | AssociationStaff |
| POST | /mls/associations/{id}/run-compliance-checkpoint | Ops-run checkpoint: expires listings ACTIVE over 365 days; re-derives license compliance | AssociationStaff |
| GET | /mls/offices | Flat office list (filter `broker_member_id`, `status`) | AssociationStaff, Member |
| GET | /mls/offices/{officeId} | Flat office read | AssociationStaff, Member |
| GET | /mls/listings | Flat listing list (filter `office_id`, `listing_member_id`, `status`); reverse-lookup form for listings by office or member | AssociationStaff, Member, HearingPanelist |
| GET | /mls/listings | Flat listing list (filter `office_id`, `listing_member_id`, `status`, `policy_revision_id`); reverse-lookup by governing policy revision | AssociationStaff, Member, HearingPanelist |
| GET | /mls/listings/{listingId} | Flat listing read | AssociationStaff, Member, HearingPanelist |
| GET | /mls/status-changes | Flat status-change list (filter `listing_id`); reverse-lookup form for status changes by listing | AssociationStaff, Member, HearingPanelist |
| GET | /mls/status-changes | Flat status-change list (filter `listing_id`, `auto_citation_id`); reverse-lookup by triggering auto-citation | AssociationStaff, Member, HearingPanelist |
| GET | /mls/status-changes/{statusChangeId} | Flat status-change read | AssociationStaff, Member, HearingPanelist |
| GET | /mls/citations | Flat citation list (filter `member_id`, `listing_id`, `status`, `rule_code`) | AssociationStaff, Member |
| GET | /mls/citations/{citationId} | Flat citation read | AssociationStaff, Member |
| GET | /mls/dues-periods/{periodId} | Flat dues-period read | AssociationStaff, Member |
| GET | /mls/dues-invoices | Flat dues-invoice list (filter `dues_period_id`, `member_id`, `status`) | AssociationStaff, Member |
| GET | /mls/dues-invoices/{invoiceId} | Flat dues-invoice read | AssociationStaff, Member |
| GET | /mls/ethics-cases | Flat ethics-case list (filter `complainant_member_id`, `respondent_member_id`, `status`) | AssociationStaff, GrievanceMember, HearingPanelist, Member |
| GET | /mls/ethics-cases/{caseId} | Flat ethics-case read | AssociationStaff, GrievanceMember, HearingPanelist, Member |
| GET | /mls/arbitration-cases | Flat arbitration-case list (filter `complainant_member_id`, `respondent_member_id`, `listing_id`, `status`) | AssociationStaff, Member, HearingPanelist |
| GET | /mls/arbitration-cases/{caseId} | Flat arbitration-case read | AssociationStaff, Member, HearingPanelist |
| GET | /mls/hearing-panels/{panelId} | Flat hearing-panel read | AssociationStaff, HearingPanelist, GrievanceMember |
| GET | /mls/data-licenses/{licenseId} | Flat data-license read | AssociationStaff |
| GET | /mls/policy-revisions | Flat policy-revision list (filter `association_id`, `status`) | AssociationStaff, Member |
| GET | /mls/policy-revisions/{revisionId} | Flat policy-revision read | AssociationStaff, Member |
| GET | /mls/consolidations | Flat consolidation-event list (filter `survivor_association_id`, `absorbed_association_id`, `status`) | AssociationStaff |
| GET | /mls/consolidations/{eventId} | Flat consolidation-event read | AssociationStaff |

## 5. Error Code Catalogue

Trigger conditions for each error are narrated in §2 and §3 alongside the workflows they guard; this table is the identifier-to-status index.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_MEMBER_MISMATCH | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_STALE_VERSION | 412 |
| ERR_INVALID_STATE | 409 |
| ERR_ASSOCIATION_MERGED | 409 |
| ERR_MEMBER_SUSPENDED | 409 |
| ERR_SCREENING_CONFLICT | 409 |
| ERR_APPEAL_CONFLICT | 409 |
| ERR_PANEL_SOLE_ACTOR | 409 |
| ERR_COMP_DISPLAY_PROHIBITED | 409 |
| ERR_RULESET_MISMATCH | 409 |
| ERR_LISTING_FLAGGED | 409 |
| ERR_HEARING_WINDOW_CLOSED | 409 |
| ERR_SCREENING_OVERDUE | 409 |
| ERR_APPEAL_WINDOW_CLOSED | 409 |
| ERR_CURE_WINDOW_CLOSED | 409 |
| ERR_ARBITRATION_WINDOW_CLOSED | 409 |
| ERR_CONSOLIDATION_NOT_DUE | 409 |
| ERR_CREDIT_CAP_EXCEEDED | 409 |
| ERR_TENDER_MISMATCH | 409 |
| ERR_CROSS_ASSOCIATION_REFERENCE | 422 |
| ERR_DUPLICATE_RESOURCE | 409 |
| ERR_SCHEDULE_OVERLAP | 409 |
| ERR_LAST_FINE_SCHEDULE | 409 |
| ERR_PANEL_POOL_EXHAUSTED | 409 |
| ERR_FACTOR_SCORE_INVALID | 409 |
| ERR_NO_FINE_SCHEDULE | 409 |
| ERR_POLICY_REVISION_MISSING | 409 |
| ERR_OFFICE_HAS_OPEN_LISTINGS | 409 |
| ERR_INVALID_REQUEST | 400 |
