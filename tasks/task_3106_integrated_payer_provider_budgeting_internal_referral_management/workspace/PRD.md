# Integrated Payer-Provider Budgeting API — Product Requirements Document

## 1. Introduction

A vertically integrated payer and care-delivery organization earns revenue by accepting a fixed monthly capitation payment for each member it covers, not by billing for procedures performed. That single inverted fact reshapes every downstream requirement in this document. When the organization is paid per member rather than per service, procedure volume stops being a source of income and becomes a source of cost, so the compensation arrangements offered to employed clinicians must be structurally severed from how much work those clinicians perform. This API is the system of record for that arrangement: it tracks the members whose capitation funds each operating region, the employed providers whose compensation is drawn against that same revenue, and the deliberate internal-referral machinery that keeps delivered care inside the owned network.

A region is identified by a `name` for display, a non-empty list of two-letter `state_codes` describing the states it serves, a `margin_target_pct` expressing the target operating margin as a fraction of premium revenue, such as three hundredths, and a `capitation_index` — the regional cost-structure multiplier relative to the system average that is applied to every base rate in the region and that defaults to 1.0 when omitted. Creating a region starts its `posture` at `OPEN` and both `premium_revenue_cents` and `operating_margin_cents` at zero.

Every nested relationship in the system descends from a region, and each level records the region it ultimately draws funding from. A member's `region_id` names the region of record that receives that member's capitation; a care site's `region_id` names the region whose operating budget funds the facility; a provider's `region_id` names the region whose premium funds that provider's compensation; a network service's `region_id` names the region whose network it describes; and a quality metric's `region_id` names the region it scores. Because departments and providers both sit under a care site while also belonging to a region, a department carries a `care_site_id` naming the facility it operates in alongside a denormalized `region_id`, and a provider carries a `care_site_id` for its base facility alongside its own `region_id`. This redundancy is deliberate: region-scoped reads and region-scoped fiscal rollups never have to walk the site relationship to find their scope.

The second organizing pressure is scarcity. Because premium revenue arrives on a fixed per-member schedule while staffing, facilities, contracted outside care and emergency claims all draw against it, every region runs a live operating margin that can turn negative and must visibly change how the region behaves when it does. Regions therefore move through operating postures that tighten capacity, hold pending referrals and eventually freeze mutation entirely. Appointment supply is treated as a budgeting decision rather than a market outcome: a department holds an authorized weekly slot supply, and the system refuses bookings beyond it rather than allowing demand to expand the schedule.

A third concern is accountability for the care that leaks outside the network. When an internal referral cannot be satisfied — a service is unavailable, a department has closed, a member is out of area — the organization may authorize an exception, and the resulting outside-services spending is booked against the region's budget with a deductible-and-coinsurance structure. Layered on top are quality and access metrics whose finalization is gated on complete internal-referral logging, and a set of affiliated-entity integrations whose settlement credits feed back into the region's forward margin. This document specifies the entities, transitions, calculations, validations and endpoints that carry all of it.

## 2. Global Specifications & System-Wide Principles

The rules in this section apply uniformly across the API. Contract-level details — header names, envelope shape, pagination mechanics, precision and rounding, and the concurrency protocol — are fixed and must be implemented exactly as written, because the automated conformance suite asserts them literally.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the operational capacity in which that principal acts. A request missing either header, or carrying a value the system does not recognise, is refused with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A well-formed request whose role does not hold the invoked operation — either exclusively or in its shared read set — is refused with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

The API recognises eight roles, spelled exactly: `RegionalFinanceOfficer`, `UtilizationReviewer`, `AccessScheduler`, `QualityReviewBoard`, `BudgetAppropriationsCommittee`, `CareTeamMember`, `Provider`, and `PlatformAdmin`.

Identity binding differs between roles. For `Provider`, the `X-User-Role` header value `Provider` means `X-User-ID` is the `id` of the acting `Provider`; ownership checks on any resource that references a `Provider` compare that resource's provider-reference field to `X-User-ID`, so a `Provider` principal reads only its own row and the region-scoped reads around it. The remaining seven roles — `RegionalFinanceOfficer`, `UtilizationReviewer`, `AccessScheduler`, `QualityReviewBoard`, `BudgetAppropriationsCommittee`, `CareTeamMember` and `PlatformAdmin` — are opaque operators: when `X-User-Role` carries any of those names, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it but never compares it to any entity's `id`.

`RegionalFinanceOfficer` owns enrollment, compensation, facility cost, outside-services spend, capacity-plan activation and adjustment, member transfers and the regional operating budget lifecycle, and is the sole writer of member termination, provider compensation-model changes, claim adjudication and payment, budget submission and close, and the bulk referral-claim adjudication capability. `UtilizationReviewer` exclusively decides referral authorizations, referral denials, referral appeals, and claim denials and claim appeals. `AccessScheduler` exclusively owns department creation and capacity-flag adjustment, network-service declaration, referral intake, appointment booking and cancellation, capacity-plan review and return, and the referral-scoped capacity-plan creation capability. `QualityReviewBoard` exclusively opens, finalizes and reopens quality metrics. `BudgetAppropriationsCommittee` exclusively approves, returns and reopens regional budgets, and exclusively proposes, binds, enrolls, contracts and terminates referential integrations. `CareTeamMember` exclusively performs visit completion and referral completion through the appointment-completion capability. `PlatformAdmin` exclusively creates regions and exclusively operates the logical clock. All listing and single-resource read operations are shared broadly across the eight roles with the region scoping described above.

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

### 2.3. Pagination and Collection Ordering

List-returning endpoints accept a `limit` parameter bounding the maximum number of items in the page, and an `offset` parameter counting how many items to skip from the front of the ordered result. `limit` defaults to 10; its minimum is 1 and its maximum is 100. `offset` defaults to 0. Values outside those bounds are not silently clamped into an unbounded page.

Unless a specification in §3 says otherwise, every list endpoint returns its resources sorted by creation timestamp in ascending order. The `meta` object of a list response carries the four pagination fields `limit`, `offset`, `total_count` and `has_more`; `total_count` reflects the size of the full filtered set rather than the page, and `has_more` is true when further items remain beyond the current page. List endpoints also accept the per-resource filter parameters named in §3; the region listing, for instance, accepts a `posture` filter and a `state_code` filter restricting the result to regions serving that state.

### 2.4. Regional Operating Posture and the Mutation Gate

Every `Region` carries a `posture` drawn from `OPEN`, `RESTRICTED` and `FROZEN`. Posture is not client-writable: it is derived from the region's settled fiscal and capacity position and is re-evaluated whenever the numbers feeding it change. The `FROZEN` posture is the system's hardest gate. While a region sits in `FROZEN`, mutations of its `Member`, `CareSite`, `Department`, `Provider`, `CapacityPlan`, `Referral` and `OutsideServiceClaim` rows are refused with `ERR_REGION_POSTURE_FROZEN` (HTTP 409), as are staffing changes, compensation-model changes, capacity-plan activation and adjustment, referrals, appointments and outside-service-claim submission. Read operations remain available in every posture.

The posture ladder itself has five declared steps. A region moves from `OPEN` to `RESTRICTED` when its `operating_margin_cents` is below zero, or — independently — when `capacity_committed_appointments` exceeds `capacity_budget_appointments`. A region moves from `RESTRICTED` to `FROZEN` when `operating_margin_cents` falls below negative five hundred million cents. Recovery runs in the other direction: `FROZEN` returns to `RESTRICTED` when `operating_margin_cents` is at or above zero, and `RESTRICTED` returns to `OPEN` when `operating_margin_cents` is at or above zero.

### 2.5. Nested Resource Retrieval and Reference Resolution

For any request whose path nests one resource under another, the identifiers in the path are resolved left to right and the first identifier that fails to resolve determines the response. A request naming a department under a care site under a region that does not exist fails on the region and reports `ERR_REGION_NOT_FOUND` (HTTP 404) without ever attempting the deeper lookups. Each resource has its own not-found identifier, and the full set is enumerated in §5. Identifiers that arrive in a request body rather than in the path are validated separately: an unresolvable body reference is rejected with `ERR_REFERENCED_RESOURCE_NOT_FOUND` (HTTP 422) rather than a 404.

Cross-region referential integrity is enforced on the writes that assemble care across entities. The member, department, provider, referral and claim rows named in a single request must all resolve to the same region of record; a request that mixes regions is rejected with `ERR_CROSS_REGION_REFERENCE` (HTTP 422). The two declared exceptions are an explicitly typed `OUTSIDE_NETWORK` referral and a claim typed `OUT_OF_AREA`, both of which exist precisely to reach outside the region.

### 2.6. The Regional Ledger of Operating Accountability

Seven figures on a `Region` are computed continuously rather than stored from an event. `premium_revenue_cents` is the sum of `capitation_rate_cents` over the region's members whose status is `ACTIVE` or `TRANSFER_PENDING`; `member_count` counts that same set. `employed_delivery_cost_cents` is the sum of `comp_total_cents` over the region's providers. `outside_services_spend_cents` is the sum of `final_liability_cents` over the region's claims whose status is `PAID` or `ADJUDICATED`. `staffing_and_facility_cents` is the sum, over the region's care sites, of filled full-time-equivalents multiplied by one million two hundred fifty thousand cents plus the site's `facility_investment_spent_cents`. `operating_margin_cents` is the settled margin defined in §3.7. `computed_margin_cents` is the forward variant defined in §3.7, recomputed from each member's current `risk_score` and each provider's current panel.

Four further rollups serve capacity and network reporting. `capacity_budget_appointments` sums `budgeted_slots` and `capacity_committed_appointments` sums `committed_slots` over the region's capacity plans whose status is `ACTIVE`, `ADJUSTED` or `UNDER_REVIEW` — plans still in `PLANNING` or already `FROZEN` are excluded from both. `access_breach_pct` is the rounded share of the region's non-cancelled appointments whose `access_status` is `BREACHED_ACCESS_TARGET`. `quality_composite_score` is a weighted composite over the region's `FINALIZED` quality metrics. `referential_integration_credit_cents` sums `settlement_account_cents` over the region's non-terminated integrations, weighted by the integration's risk-sharing credit rate, and is described further in §3.11. `open_alert_count` counts the region's alerts still in `RAISED` status. Every one of these rollups is recomputed whenever an input to it changes, and a recomputation that changes a stored value refreshes the region's `updated_at` and advances its `version`.

### 2.7. Common Resource Properties

Every persistable resource in this API — `Region`, `Member`, `CareSite`, `Department`, `Provider`, `NetworkService`, `Appointment`, `Referral`, `OutsideServiceClaim`, `RegionalBudget`, `CapacityPlan`, `MemberTransfer`, `QualityMetric`, `ReferentialIntegration` and `AlertNotification` — carries `id`, `created_at`, `updated_at` and `version`. All fifteen entities are declared with common fields present; none of them omits `updated_at` or `version`.

- `id` (string): a server-minted opaque identifier formatted as a UUID. Identifiers carry no type prefix and no domain-specific prefix — a region id and a claim id are indistinguishable in shape.
- `created_at` (string): an ISO 8601 UTC instant with three fractional digits, assigned at creation and never changed thereafter.
- `updated_at` (string): an ISO 8601 UTC instant with three fractional digits, refreshed on every mutation of the resource, including mutations the server performs on the client's behalf as part of a cascade.
- `version` (integer): a system-managed counter that starts at its creation value and increments by one on every mutation of the resource. A cascade that rewrites a parent therefore advances that parent's `version` even though no client request named the parent directly.

### 2.8. Monetary Precision and Rounding

All monetary values in this system are integer cents. No monetary field is fractional, and no monetary field is returned as a string. Every rounding operation named anywhere in this document — in §2 and §3 alike — uses the round-half-up rule: a value exactly at the midpoint between two integers is rounded toward the larger integer. Fields described as carrying two decimal places, such as `access_breach_pct`, `utilization_pct` and `wait_days`, are the only fractional-number fields in the API; `wait_days` carries one decimal place, and the percentage fields carry two. Fields that preserve an input ratio rather than a rounded count, such as `margin_target_pct`, `capitation_index`, `ort_contract_rate`, `shared_savings_rate` and `risk_score`, are stored and returned at the precision supplied.

### 2.9. Optimistic Concurrency Control and Stale Writes

Four write operations in this API are guarded by an optimistic concurrency check on the `Member` they act upon. Each of them requires a non-optional body field named `expected_member_version`, carrying the client's last-observed `version` of that member.

The four guarded writes are:

- `POST /member-transfers` — requesting a transfer of a member between regions. The client's view of the member may already be stale because a completed transfer, a termination, or a capitation recomputation has rewritten the member's region of record.
- `POST /regions/{id}/outside-service-claims` — submitting an outside-service claim against a member. A stale view means the claim would be priced against a member snapshot whose capitation and panel attribution have already been rewritten.
- `POST /appointments` — booking an appointment for a member. A stale view means the member's region of record and network profile may already have moved.
- `POST /referrals` — raising a referral for a member. A stale view is consequential because a completed transfer changes which departments count as in-network for that member.

In all four cases a supplied `expected_member_version` that does not equal the member's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412), and the write does not occur. Two further member-scoped writes require the same field for the same reason — terminating a member's coverage and correcting a member's risk score both take `expected_member_version` as a non-optional input. No other endpoint in this API accepts a version field of any kind; an endpoint not named here does not take one.

### 2.10. Fiscal Discipline: The Staffing Line and the Freeze Floor

Two fiscal constraints bound what a region may spend. The first is the region's `staffing_and_facility_cents`, which may not exceed the `staffing_budget_cents` of that region's latest `RegionalBudget`; a staffing change that would cross the line, or an outside-service-claim submission, a member enrollment or an appointment booking that pushes the figure to or above the line while the region's latest budget is not in `APPROVED` status, is rejected with `ERR_BUDGET_FISCAL_LINE_EXCEEDED` (HTTP 402). The second is the freeze floor: a settled operating margin below negative five hundred million cents drives the region to `FROZEN` through the posture ladder of §2.4, which in turn closes the mutation gate for every child entity. The staffing line applies to the staffing and facility change capability, to appointment booking, to outside-service-claim submission and to member enrollment.

### 2.11. The Logical Clock

The system does not read wall-clock time for any business decision. A single logical clock governs every expiry, triage window, waiting-period measurement, effective-date comparison and effective-instant evaluation in the API. The clock's startup value is exactly `2026-09-01T00:00:00Z`, and it holds that instant until changed. An administrative capability sets the logical clock to a supplied `to_iso8601` instant, after which every subsequent temporal evaluation reads that value. No business rule may fall back to the host's wall-clock time when the logical clock has not been advanced.

### 2.12. Alerts and Operating Visibility

Operational thresholds are made visible through `AlertNotification` records rather than through silent state changes. An alert carries an `alert_type` drawn from `POSTURE_CHANGE`, `BUDGET_BREACH`, `QUALITY_GAP` and `CAPACITY_SHORTFALL`, a `severity` drawn from `INFO`, `WARNING` and `CRITICAL` defaulting to `INFO`, a `payload_ref_type` naming the kind of entity the alert concerns, and a `payload_ref_id` naming the specific row. Alerts are raised with `status` `RAISED` and carry the logical-clock instant in `raised_at`. Acknowledging an alert moves it to `ACKNOWLEDGED` and refreshes the owning region's `open_alert_count`, which counts only the alerts still in `RAISED` status.

## 3. Business Logic & Workflows

### 3.1. Enrolling Members and the Capitation That Funds a Region

A member relationship begins when a `RegionalFinanceOfficer` enrolls a person into a region of record. The enrollment payload carries a `member_ref` that is unique across all members of the system, an optional `attributed_provider_id` naming the provider whose panel the member counts toward, a `plan_product` drawn from `COMMERCIAL_HMO`, `MEDICARE_ADVANTAGE`, `MEDICAID_MANAGED` and `DUAL_ELIGIBLE`, a `benefit_tier` drawn from `TIER_1`, `TIER_2` and `TIER_3`, a `risk_score` between 0.5 and 5.0, and a `coverage_effective_date`. The new member receives `region_id` from the region of record, and `status` begins at `ACTIVE`. Enrollment is one of the writes refused outright while the target region is `FROZEN`, and it is also one of the writes subject to the staffing fiscal line of §2.10.

The monthly capitation the region receives for that member — `capitation_rate_cents` — is computed by the capitation rule the moment the member is created. The rule begins from a base rate selected by the member's `plan_product`: forty-two thousand cents for `COMMERCIAL_HMO`, ninety-five thousand for `MEDICARE_ADVANTAGE`, twenty-eight thousand for `MEDICAID_MANAGED`, and one hundred eighteen thousand for `DUAL_ELIGIBLE`. That base is multiplied by the region's `capitation_index`, a regional cost-structure multiplier captured at region creation and defaulting to 1.0, and the product is rounded half-up to a whole cent to produce the adjusted base. A risk component is then computed as the adjusted base multiplied by the member's own `risk_score`, rounded half-up. The raw rate is the adjusted base plus the risk component.

Because extreme risk scores should not let a single member's rate run away, the rule clamps. The lower bound is the adjusted base multiplied by one half, rounded half-up; the upper bound is the adjusted base multiplied by two and a half, rounded half-up. The member's `capitation_rate_cents` is the raw rate constrained to that closed interval — a raw rate below the lower bound becomes the lower bound, a raw rate above the upper bound becomes the upper bound, and a raw rate inside the interval stands as computed. The rule has a second, explicitly non-operational variant used when a region-level revenue estimate must be produced before member-level risk scores are loaded: that variant uses the unweighted base rate for every member, ignoring both the member's risk score and the region's `capitation_index`. It is the risk-adjusted, clamped variant that governs real enrollment and real transfer completion.

Enrollment is never a single-row write. Creating a member recomputes the parent region's `premium_revenue_cents`, which sums `capitation_rate_cents` across exactly those members whose `region_id` matches and whose `status` is `ACTIVE` or `TRANSFER_PENDING`; it recomputes the region's `member_count`, which counts the same status set; and it recomputes the region's `operating_margin_cents`. Every `ACTIVE` provider in that region then has its `panel_size_assigned` — the count of `ACTIVE` members whose `attributed_provider_id` names it — recomputed, along with `quality_bonus_cents` and `comp_total_cents`. The region's `version` advances by one and each recomputed provider's `version` advances by one. A region whose revenue falls short of its costs will, through the posture ladder, move to `RESTRICTED` as a consequence.

A member's risk score can be corrected later by a `RegionalFinanceOfficer` through a correction payload carrying the new `risk_score` alongside the required `expected_member_version`; the correction recomputes `capitation_rate_cents`, the region's `premium_revenue_cents`, its `computed_margin_cents` and its `operating_margin_cents`, and advances both the member's and the region's `version`. Termination is a separate transition: a member in `ACTIVE` status may be terminated, moving `status` to `TERMINATED` and recomputing the region's `premium_revenue_cents`, `member_count` and `operating_margin_cents` so that the terminating member's capitation is no longer counted.

### 3.2. Compensating Clinicians Without Rewarding Volume

Providers are registered by a `RegionalFinanceOfficer` at a care site, with a `provider_name`, a `specialty`, a `compensation_model`, a `base_component_cents` and a `panel_size_target`. The `specialty` taken at registration is drawn from `PRIMARY_CARE`, `CARDIOLOGY`, `ORTHOPEDICS`, `ONCOLOGY`, `RADIOLOGY` and `BEHAVIORAL_HEALTH`. The same six values are the domain of a department's `specialty`, and a provider's `region_id` is the region whose premium funds their compensation. A provider begins in `ACTIVE` status and may later be moved to `PANEL_CLOSED`, at which point the provider is no longer accepting attributed members.

Compensation is assembled from a fixed base plus a per-member panel component plus a conditional quality bonus. The panel capitation component is the provider's `panel_size_assigned` multiplied by a per-specialty panel rate, rounded half-up to a whole cent. The panel rate is nine hundred cents per attributed member per month for `PRIMARY_CARE`, fourteen hundred for `CARDIOLOGY`, fifteen hundred for `ORTHOPEDICS`, eighteen hundred for `ONCOLOGY`, eleven hundred for `RADIOLOGY`, and one thousand for `BEHAVIORAL_HEALTH`. The quality bonus is evaluated only when the provider's `quality_score` is at least eighty-five; when it is, the bonus is ten percent of the sum of the fixed `base_component_cents` and the panel capitation component just computed, rounded half-up. The evaluation order here matters and is deliberate: the panel component is computed first, then the bonus is keyed on the base plus that panel component, and only then is `comp_total_cents` summed from all four components. A bonus computed on the base alone produces a different total, and that reading is incorrect.

The fourth component, `volume_component_cents`, is structural rather than computed. It is pinned to zero under every compensation arrangement. The invariant is that provider compensation must stay decoupled from procedure volume: neither registering a provider nor changing a provider's `compensation_model` may introduce a non-zero volume component, and any arrangement that would do so is rejected with `ERR_VOLUME_COMPONENT_NOT_PERMITTED` (HTTP 422). A compensation-model change carries a `compensation_model` drawn from `SALARY`, `PANEL_CAPITATION` and `QUALITY_BONUS`, together with a `base_component_cents` and a `panel_size_target`; whichever model is chosen, `volume_component_cents` is pinned to zero, the panel capitation component is recomputed from the current `panel_size_assigned`, the quality bonus is recomputed, and the total is reassembled. A separate capability for drafting a compensation plan ties a quality bonus to a `bonus_quality_target` with no procedure-volume component; a supplied `volume_linked` flag set to true causes the plan to be recorded and refused with `ERR_VOLUME_COMPONENT_NOT_PERMITTED`, while a false value records the plan in draft.

A provider's `quality_score` is its own persisted field, initialised to zero and staying at zero until a `QUALITY_COMPOSITE` metric finalizes against it. That finalization writes the metric's measured value onto the provider's `quality_score` and recomputes the provider's `comp_total_cents`, which is how quality performance feeds back into compensation cost and therefore into the region's `employed_delivery_cost_cents` and `operating_margin_cents`.

Panel attribution is the pivot on which compensation and region cost both turn. Whenever membership shifts — a member enrolling, terminating, transferring in or transferring out — every `ACTIVE` provider in the affected region has `panel_size_assigned`, `quality_bonus_cents` and `comp_total_cents` recomputed, and the region's `employed_delivery_cost_cents` and `operating_margin_cents` follow.

### 3.3. Facilities, Staffing and the Supply of Appointment Slots

A `RegionalFinanceOfficer` opens a `CareSite` under a region with a `site_name`, a `site_type` drawn from `MEDICAL_CENTER`, `HOSPITAL` and `MEDICAL_OFFICE`, a `licensed_beds` count that is zero for office sites, a `staffing_fte_budget` expressing budgeted full-time-equivalent headcount for the period, and a `facility_investment_budget_cents`. The site's `staffing_fte_filled` and `facility_investment_spent_cents` both begin at zero; filled staffing is set later through a staffing capability that accepts `staffing_fte_filled` and recomputes the region's `staffing_and_facility_cents` and `operating_margin_cents`. Filled staffing may never exceed the site's own `staffing_fte_budget`: a staffing change that would cross it is rejected with `ERR_FTE_BUDGET_EXCEEDED` (HTTP 409). Site cost enters the region's `staffing_and_facility_cents` as the filled full-time-equivalents multiplied by one million two hundred fifty thousand cents per FTE, plus the site's `facility_investment_spent_cents`.

Clinical supply is organised into `Department` rows inside a site. An `AccessScheduler` opens a department with a `specialty`, an `appointment_slots_budgeted` figure representing the weekly appointment supply the budget authorizes, and a `wait_threshold_days` access target defaulting to fourteen days. The department's `appointment_slots_committed` starts at zero, `accepting_internal_referrals` starts true, and `status` starts at `OPEN`. Departments move among `OPEN`, `CONSTRAINED` and `CLOSED`; a department may be written to any of the three through a capacity-flag adjustment that also accepts `accepting_internal_referrals` and `wait_threshold_days`. `CLOSED` stops the department accepting new bookings entirely.

Appointment supply is a budget decision, not a market outcome. A `RegionalFinanceOfficer` budgets supply by opening a `CapacityPlan` for a department and a `period` given in `YYYY-MM` form, supplying a `budgeted_slots` figure and a `panel_target`. Only one plan may exist for a given department and period; a second is rejected with `ERR_DUPLICATE_CAPACITY_PLAN` (HTTP 409). A plan starts in `PLANNING` with `recalculation_epoch` at one, and its `committed_slots` and `supply_shortfall_slots` are computed at creation. The plan then advances through review and activation: an `AccessScheduler` sends a plan in `PLANNING` or `ADJUSTED` to `UNDER_REVIEW`, but only when `budgeted_slots` is at least the `panel_target` divided by one and a half — an unstated commissioning ratio that expresses how many members one slot is expected to serve. A `RegionalFinanceOfficer` then activates a plan in `UNDER_REVIEW`, permitted only while the parent region's posture is `OPEN` or `RESTRICTED`, moving it to `ACTIVE` and recomputing `committed_slots` as the count of the department's non-cancelled appointments for the period. Activation is refused for a plan not in `UNDER_REVIEW` with `ERR_CAPACITY_PLAN_NOT_ACTIVATABLE` (HTTP 409).

An `ACTIVE` plan may be adjusted by a `RegionalFinanceOfficer` supplying a new `budgeted_slots`, but only when the new value is at least the current `committed_slots`; the plan moves to `ADJUSTED` and `recalculation_epoch` advances. An `AccessScheduler` may return a plan in `UNDER_REVIEW` to `PLANNING`. A plan in `ACTIVE` status whose `committed_slots` grows past its `budgeted_slots` is moved back to `UNDER_REVIEW` automatically, and a plan whose parent region reaches `FROZEN` posture is moved to `FROZEN` automatically. `FROZEN` is the plan's terminal state.

The supply arithmetic itself is a running reconciliation. `committed_slots` counts the department's appointments for the plan period whose `fulfillment_status` is `REQUESTED`, `SCHEDULED` or `COMPLETED`. `supply_shortfall_slots` is the amount by which `committed_slots` exceeds `budgeted_slots`, floored at zero — it is never negative. `utilization_pct` is one hundred times `committed_slots` divided by `budgeted_slots`, rounded half-up to two decimal places. Every recomputation of `committed_slots` advances `recalculation_epoch` by one. This same rule has an explicitly different reading after a period closes, when actual filled and delivered slot counts are used in place of the budgeted denominator; during planning and approval the budgeted figure is the one that governs. A department whose clinicians could physically deliver more slots than budgeted still reports the budgeted figure, which is the whole point of treating supply as a budgeting decision.

### 3.4. Booking, Cancelling and Completing Appointments

An `AccessScheduler` books an appointment with a payload naming `department_id`, `provider_id`, `member_id`, an optional `referral_id`, an `appointment_type` drawn from `ROUTINE`, `SPECIALTY`, `URGENT` and `FOLLOW_UP`, a `start_utc` instant, a `duration_minutes` defaulting to twenty, and the concurrency field `expected_member_version` described in §2.9. A booking is refused when the department's `status` is `CLOSED`, and refused when the department's `appointment_slots_committed` plus one would exceed its `appointment_slots_budgeted` — both cases returning `ERR_DEPARTMENT_CAPACITY_EXHAUSTED` (HTTP 409). A booking is likewise refused with `ERR_PROVIDER_SCHEDULE_OVERLAP` (HTTP 409) when the named provider already holds a non-cancelled appointment on the same calendar day whose half-open instant range intersects the requested one; that range runs from `start_utc` inclusive to `start_utc` plus `duration_minutes` exclusive.

Specialty bookings carry an additional authorization chain. When `appointment_type` is `SPECIALTY`, the referral named by `referral_id` must exist, must belong to the supplied `member_id`, must name the supplied `department_id` as its `target_department_id`, and must itself be in `AUTHORIZED` status. A referral in `PENDING_TRIAGE`, `DENIED`, `HELD`, `EXPIRED`, `SCHEDULED` or `COMPLETED` status never authorizes a booking, and the mismatch is reported as `ERR_REFERRAL_NOT_AUTHORIZED` (HTTP 409). A specialty booking against a referral whose logical-clock position has reached the referral's `expires_at` is refused with `ERR_REFERRAL_EXPIRED` (HTTP 409), because an authorized referral at or past its expiry is `EXPIRED` and cannot be booked. Separately, the booking's member-and-department combination must satisfy the network-availability rule of §3.5, which reports `ERR_SERVICE_NOT_AVAILABLE_IN_NETWORK` (HTTP 409) when it does not, and the booking is refused outright while the department's region is `FROZEN`.

A successful booking moves the appointment's `fulfillment_status` from `REQUESTED` to `SCHEDULED` and computes three read-only fields. `wait_days` is the number of calendar days from the booking instant to `start_utc`, expressed to one decimal place. `access_status` is `BREACHED_ACCESS_TARGET` when `wait_days` is at least the department's `wait_threshold_days`, and `WITHIN_ACCESS_TARGET` otherwise; the comparison is inclusive at the boundary, so a wait exactly equal to the threshold is a breach while a wait one tenth of a day shorter is not. `hold_status` begins at `NONE` and can be set to `REFERRAL_HOLD` by the referral machinery described below.

Booking cascades across four entities at once. The department's `appointment_slots_committed` increments by one, and if that reaches `appointment_slots_budgeted` the department moves from `OPEN` to `CONSTRAINED`. A referenced referral in `AUTHORIZED` status moves to `SCHEDULED`. The `CapacityPlan` covering the department has its `committed_slots` and `supply_shortfall_slots` recomputed and its `recalculation_epoch` advanced. The parent region's `operating_margin_cents` is recomputed, and the posture ladder may run onward from there into new alert records. The `version` of the member, the referral and the department each advance by one.

Cancellation is available to an `AccessScheduler` from either `REQUESTED` or `SCHEDULED`. From `REQUESTED` the appointment simply moves to `CANCELLED`. From `SCHEDULED` the cancellation additionally decrements the department's `appointment_slots_committed`, returns a referral in `SCHEDULED` status to `AUTHORIZED`, and recomputes the covering capacity plan's `committed_slots`, `supply_shortfall_slots` and `recalculation_epoch`. Completion is the exclusive province of a `CareTeamMember` and applies to a `SCHEDULED` appointment, moving `fulfillment_status` to `COMPLETED`, moving a linked referral in `SCHEDULED` status to `COMPLETED`, and recomputing the parent region's `access_breach_pct`. `COMPLETED` and `CANCELLED` are the appointment's terminal states.

### 3.5. Internal Referrals, Network Availability and the Authorization Decision

The network a member's care must stay inside is described by `NetworkService` declarations raised by an `AccessScheduler`. Each declaration names a `service_code` that is unique within its region, a human-readable `service_name`, an `availability_status` drawn from `AVAILABLE`, `CONSTRAINED` and `UNAVAILABLE` and defaulting to `AVAILABLE`, and a free-text `capacity_note` recording the current capacity situation. Each declaration also carries a computed `available_provider_count`, the count of `ACTIVE` providers in the region whose specialty matches the mapping of that `service_code`. These declarations are the profiles that later determine whether two regions differ for a given plan product when a member is moved between them.

Referrals exist to keep care inside the owned network, and the rules that decide whether a referral may proceed are the system's most heavily layered. An `AccessScheduler` raises a referral with a `member_id`, a `requesting_department_id`, a `target_department_id`, a `service_code`, a `referral_type` drawn from `INTERNAL` and `OUTSIDE_NETWORK`, an `authorization_exception` flag, an `exception_reason` drawn from `SERVICE_UNAVAILABLE_IN_NETWORK`, `EMERGENCY`, `OUT_OF_AREA` and `REGULATORY_MANDATE`, an `external_contract_count` defaulting to zero, and the `expected_member_version` from §2.9. A new referral begins in `PENDING_TRIAGE` with `appeal_rounds` at zero.

Two independent safety checks gate the raise. First, `external_contract_count` may not exceed the external-contract maximum; a value above it is an unauthorized external network expansion and is refused with `ERR_UNAUTHORIZED_NETWORK_EXPANSION` (HTTP 409). Second, the referral must satisfy network availability, or it is refused with `ERR_SERVICE_NOT_AVAILABLE_IN_NETWORK` (HTTP 409). That availability question is answered strictly within the member's own region of record: a department in another region never satisfies it. A department qualifies only when its `specialty` equals the referral's `service_code` verbatim, its `accepting_internal_referrals` is true, and its `status` is `OPEN` or `CONSTRAINED`.

The decision itself turns on `referral_type`. An `INTERNAL` referral is authorized exactly when a qualifying in-network department exists; an `authorization_exception` flag alone never authorizes an internal referral. An `OUTSIDE_NETWORK` referral is authorized when an authorization exception is claimed, the `exception_reason` is either `SERVICE_UNAVAILABLE_IN_NETWORK` or `EMERGENCY`, and either no in-network department qualifies or the reason is `EMERGENCY`. The asymmetry between the two permitted reasons is deliberate and must be preserved: when the network is in fact available, an `EMERGENCY` reason still authorizes, while a `SERVICE_UNAVAILABLE_IN_NETWORK` reason does not.

When more than one department qualifies, the system ranks candidates by remaining supply — `appointment_slots_budgeted` minus `appointment_slots_committed`, descending — and breaks ties in favor of the earliest `created_at`. If the filtered candidate set is empty, the referral is denied with `ERR_NO_IN_NETWORK_CAPACITY` (HTTP 409).

A `UtilizationReviewer` decides referrals, and a decision is only available while the referral sits in `PENDING_TRIAGE` or `APPEALED`; any other status yields `ERR_REFERRAL_NOT_DECIDABLE` (HTTP 409). Decisions are also bounded in time: the logical clock must be at or before the referral's `created_at` plus the triage window, or the decision is refused with `ERR_REFERRAL_TRIAGE_WINDOW_EXPIRED` (HTTP 409); that window applies to raising a referral as well as to deciding one.

Authorizing a referral in `PENDING_TRIAGE` moves it to `AUTHORIZED`, records `effective_decision_at` from the logical clock, and sets `expires_at` to ninety days after the referral's `created_at`. The same decision reached from `APPEALED` moves the referral to `AUTHORIZED` and refreshes `effective_decision_at` while retaining the accumulated `appeal_rounds`. Denying a referral from `PENDING_TRIAGE` moves it to `DENIED`, records `effective_decision_at`, and releases any appointment that was holding a `REFERRAL_HOLD` against it, returning that appointment's `hold_status` to `NONE`. Denying from `APPEALED` moves the referral to `DENIED` and requires that `appeal_rounds` is still below the appeal-round maximum.

The appeal loop is bounded. A referral in `DENIED` may be appealed by a `UtilizationReviewer`, moving it to `APPEALED` and incrementing `appeal_rounds` by one, and opening an appeal requires that `appeal_rounds` is below the appeal-round maximum — the maximum is two rounds. An appeal opened at the maximum is refused with `ERR_APPEAL_ROUNDS_EXHAUSTED` (HTTP 409).

Once authorized, a referral has ninety days to become a booked visit. A referral in `AUTHORIZED` whose logical-clock position reaches its `expires_at` becomes `EXPIRED` automatically, and neither the authorization nor any new appointment may be created against it thereafter. A referral in `AUTHORIZED` for which an appointment is booked moves to `SCHEDULED`; a referral in `SCHEDULED` whose appointment completes moves to `COMPLETED`. `COMPLETED` and `EXPIRED` are the referral's terminal states.

Referrals also respond to the region's posture. When a referral's target department belongs to a region whose posture moves to `RESTRICTED`, a referral in `PENDING_TRIAGE` is moved to `HELD`, and every appointment referencing it that is still in `REQUESTED` status has its `hold_status` set to `REFERRAL_HOLD`. When that region's posture returns to `OPEN`, a `HELD` referral returns to `PENDING_TRIAGE`.

### 3.6. Outside Services and the Chronological Liability Calculation

Care that leaves the network is booked as an `OutsideServiceClaim` against the region that pays it. A `RegionalFinanceOfficer` submits a claim with a `member_id`, a `vendor_name`, a `service_code`, a `claim_type` drawn from `EMERGENCY`, `CONTRACTED`, `OUT_OF_AREA` and `DIRECT`, an `emergency_flag`, a `billed_amount_cents`, and the concurrency field `expected_member_version`. The submission also carries a `provider_type`, a `claim_line_number`, a `derived_claim_type` and an `emergency_inject_once` marker, which together determine which claim line supplies the annual-deductible consumption described below. A claim begins in `SUBMITTED` status, or in `PENDED` status when the region's committed outside-services figure already exceeds its budget line. A claim records the logical-clock instant of its submission as `submitted_at`, and the instant at which it is adjudicated as `adjudicated_at`. Adjudication may also be driven by the bulk capability described below, whose payload names the `referral_id` in which the claims to adjudicate are batched.

Submission books a forward-looking `provisional_liability_cents` rather than a final figure. The provisional amount is the `billed_amount_cents` multiplied by a vendor allowable percentage keyed on `vendor_name` — eighty percent for the vendor `KP Affiliate` and seventy percent for any other vendor name — rounded half-up to a whole cent. When `emergency_flag` is true, the provisional amount is instead the billed amount multiplied by seventy-five percent, rounded half-up. This provisional figure deliberately ignores the deductible, so it will differ from the final liability for the same claim.

The final figure is pinned at adjudication and is chronological. The claim's line items are sorted by `line_number` ascending and, where line numbers tie, by `created_at` ascending. A running total and a running liability both begin at zero, and the lines are walked in that sorted order. Each line's `line_amount_cents` is added to the running total first. If the running total is at or below the annual deductible of one hundred fifty thousand cents, that line contributes nothing to liability. Otherwise the excess of the running total over the annual deductible is computed: when that excess is at least the line's own amount, the line's liability is the line amount multiplied by the coinsurance rate of twenty percent, rounded half-up; when the excess is smaller than the line amount, the line's liability is that excess multiplied by twenty percent, rounded half-up. The line's liability is added to the running liability, and the process repeats. When every line has been walked, `final_liability_cents` is the running liability capped at the out-of-pocket maximum of six hundred thousand cents. Because the annual deductible is consumed line by line in that sorted order, the same set of lines in a different order produces a different final liability.

Adjudication by a `RegionalFinanceOfficer` is available from `SUBMITTED`, `PENDED` or `APPEALED` status — but only when the region's committed outside-services figure is at or below the budget line, and only when the region holds an `APPROVED` `RegionalBudget` for the period. The budget requirement is reported as `ERR_BUDGET_NOT_APPROVED` (HTTP 409), and adjudication requested from any other claim status is reported as `ERR_CLAIM_NOT_ADJUDICABLE` (HTTP 409). Adjudication pins the final liability, records `adjudicated_at` from the logical clock, moves the claim to `ADJUDICATED`, adds the final liability to the region's `outside_services_spend_cents` and to the budget's `outside_services_committed_cents`, and recomputes the region's `operating_margin_cents`. When that recomputed margin falls below zero, the posture ladder runs and can move the region from `OPEN` to `RESTRICTED`. The same adjudication capability exists in a bulk form that takes a `referral_id` and adjudicates every linked claim in `SUBMITTED` or `APPEALED` status in one request, pinning each final liability, moving each to `ADJUDICATED`, recomputing each affected region's spend and margin, and advancing the version of every adjudicated claim and affected region.

Payment requires the claim in `ADJUDICATED` status and the region's budget in `APPROVED` status; payment moves the claim to `PAID` without altering the booked liability. Denial is a `UtilizationReviewer` capability available from `ADJUDICATED` or `APPEALED`; it moves the claim to `DENIED` and reverses the booked `final_liability_cents` out of the region's `outside_services_spend_cents` and out of the budget's `outside_services_committed_cents`, so a denied claim returns the region's margin to where it stood before adjudication. Appeals of a denied claim mirror the referral loop: a claim in `DENIED` may be appealed by a `UtilizationReviewer`, moving it to `APPEALED` and incrementing `appeal_rounds` by one, but only while `appeal_rounds` is below the appeal-round maximum of two; an appeal opened at the maximum is refused with `ERR_APPEAL_ROUNDS_EXHAUSTED` (HTTP 409). A claim in `APPEALED` may be denied again, subject to the same round bound. `PAID` and `DENIED` are the claim's terminal states.

### 3.7. The Regional Operating Budget, Validation Ordering and the Two Margins

Every request in this API is evaluated against an ordered sequence of checks, and the order is observable because the first failing check determines the error the caller sees. Header presence and validity is checked first, so a request with a missing or malformed `X-User-ID` or `X-User-Role` reports `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` even if the request would also fail on permissions or on business grounds. Role authorization is checked second, mapping to `ERR_INSUFFICIENT_PERMISSIONS`. Path-segment existence follows, resolved left to right with the first miss winning, and reported through the per-resource not-found identifiers of §5. Body reference existence comes next, reported as `ERR_REFERENCED_RESOURCE_NOT_FOUND`, followed by cross-region referential integrity, reported as `ERR_CROSS_REGION_REFERENCE`. State admissibility is then checked — the target row must occupy a status from which the requested trigger is declared, which is where the state-specific identifiers `ERR_REFERRAL_NOT_DECIDABLE`, `ERR_CLAIM_NOT_ADJUDICABLE`, `ERR_BUDGET_NOT_APPROVED`, `ERR_BUDGET_NOT_SUBMITTABLE`, `ERR_CAPACITY_PLAN_NOT_ACTIVATABLE`, `ERR_TRANSFER_NOT_COMPLETABLE` and `ERR_METRIC_NOT_FINALIZABLE` apply.

Beyond that point the ordering is business-defined and must be preserved, because a caller who violates two rules must receive the error belonging to the earlier one. The triage window is evaluated before network availability, so a late referral decision reports `ERR_REFERRAL_TRIAGE_WINDOW_EXPIRED` rather than an availability failure. Network availability is evaluated before the specialty-referral match, before the external-contract ceiling and before the appeal-round bound. The specialty-referral match is evaluated before the referral-expiry check, so a booking naming a referral that is not `AUTHORIZED` reports `ERR_REFERRAL_NOT_AUTHORIZED` even when that referral has also passed its expiry. The external-contract ceiling and the appeal-round bound are evaluated before the transfer effective-date check. The volume-decoupling check is evaluated before the region posture gate, and the duplicate-quality-metric, duplicate-capacity-plan and provider-schedule-overlap checks follow the posture gate. The posture gate is evaluated before the department capacity check, the department capacity check before the FTE budget check, and the FTE budget check before the fiscal line check — so a booking against a department that is simultaneously full and in an over-budget region reports `ERR_DEPARTMENT_CAPACITY_EXHAUSTED`, not the fiscal error. The fiscal line check is the last of the business checks. Claim adjudication carries its own placement: the `APPROVED`-budget requirement is evaluated together with state admissibility, before the committed-outside-services comparison.

A region's operating budget is opened by a `RegionalFinanceOfficer` for a `period` in `YYYY-MM` form, unique within the region, with a `staffing_budget_cents` line, an `outside_services_budget_cents` line, a `facility_investment_cents` line and a `system_deductible_cents`. The budget snapshots its region's `premium_revenue_cents` and `employed_delivery_cost_cents` at creation, computes `outside_services_committed_cents` from the region's booked claims, computes its own `operating_margin_cents`, initializes `division_deductible_cents` and `division_deductible_original_cents` both from the supplied `system_deductible_cents`, and starts in `DRAFT` status.

The system carries two distinct margins and must not conflate them. The settled variant, `operating_margin_cents`, is built from persisted rows only. Premium revenue is the sum of `capitation_rate_cents` over members in the region whose status is `ACTIVE` or `TRANSFER_PENDING`. Employed delivery cost is the sum of `comp_total_cents` over the region's providers. Outside-services spend is the sum of `final_liability_cents` over the region's claims whose status is `PAID` or `ADJUDICATED` — un-adjudicated claims are excluded. Staffing and facility cost is the sum, over the region's sites, of filled full-time-equivalents multiplied by the one-million-two-hundred-fifty-thousand-cent FTE cost plus the site's `facility_investment_spent_cents`. The settled margin is premium revenue minus employed delivery cost minus outside-services spend minus staffing and facility cost. A separate `margin_gap_cents` expresses the settled margin against the region's `margin_target_pct` goal: the gap is the settled margin minus the region's premium revenue multiplied by `margin_target_pct`, rounded half-up.

The forward variant, `computed_margin_cents`, is what planning reads. It recomputes each in-force member's capitation at that member's current `risk_score` rather than at the persisted rate, adds to the expected premium revenue a credit for every `ReferentialIntegration` in the region whose status is `BOUND`, `ENROLLED` or `CONTRACTED` — that credit being the integration's `cost_reporting_basis_cents` multiplied by its risk-sharing credit rate — and then subtracts the same employed delivery, outside-services and staffing-and-facility figures. Because the forward variant reads live risk scores and live panel sizes, a member whose `risk_score` changed after enrollment moves the forward revenue even though no cash line changed, and a test-driving capability that writes a member's `risk_score` directly recomputes only the forward margin, leaving the persisted `capitation_rate_cents` and the region's `premium_revenue_cents` untouched so that the settled margin does not move.

The ordering of the two variants is fixed. The forward components are aggregated first: expected premium revenue from live capitation recomputation, employed delivery cost from live provider compensation, escalated deductible from the region's referrals whose `effective_decision_at` falls inside the period, and projected claim liability from the region's seeded claim-line data for the period. Forward revenue and forward expense are then combined to produce the forward margin. The settled margin is evaluated last, from persisted rows, and never feeds back into the forward margin. The two figures coincide only when the period has no un-adjudicated claims and no pending transfers; on identical data they otherwise differ, which is intended.

The budget's own fiscal line decomposes into a division share and a system-level retained amount. `outside_services_committed_cents` on the budget sums the region's claims for the period plus any non-terminated referential-integration settlement accounts reported as outside services. The division liability is `outside_services_committed_cents` multiplied by the budget's `ort_contract_rate`, which defaults to 1.0, rounded half-up, minus `division_deductible_cents`; that figure is exposed on the budget as `division_liability_cents`. The budget's `net_liability_cents` is the division liability minus `system_deductible_cents`, and `system_deductible_cents` is never reimbursed to the division. The division deductible pool `division_deductible_cents` is consumed by each adjudication and restored by each denial, and its restoration is capped at the `division_deductible_original_cents` snapshot so the pool can never be refilled beyond its original size. The budget's `operating_margin_cents` is premium revenue minus the staffing line, minus `outside_services_committed_cents`, minus the facility investment line, minus employed delivery cost.

Budget status moves through a committee cycle. A `RegionalFinanceOfficer` submits a budget from `DRAFT` or `REOPENED`; submission recomputes the budget's `operating_margin_cents` and the parent region's `operating_margin_cents`, and when the budget's recomputed margin falls below zero it raises a `BUDGET_BREACH` alert at `WARNING` severity referencing the budget. Submission requires that the budget's operating margin is at least zero or that the region's posture is not `FROZEN`, and submission from any status other than `DRAFT` or `REOPENED` is refused with `ERR_BUDGET_NOT_SUBMITTABLE` (HTTP 409). A `BudgetAppropriationsCommittee` approves a `SUBMITTED` budget, at which point the revenue and employed-delivery snapshots are frozen at their current values; the committee may also return a `SUBMITTED` budget to `DRAFT`. A `RegionalFinanceOfficer` closes an `APPROVED` budget to `CLOSED`. The committee may reopen either an `APPROVED` or a `CLOSED` budget to `REOPENED`. `CLOSED` is the terminal state, though `REOPENED` budgets can be resubmitted.

A claim in `ADJUDICATED` status cannot be paid while its region's budget is not `APPROVED`, which is the mechanism that ties outside-services cash movement to committee approval.

### 3.8. Regional Posture Reactions and Their Cascade Tiers

The posture ladder of §2.4 is evaluated automatically rather than invoked, and its two fiscal tiers carry deliberately different cascades. When a region's settled margin drops below zero while the region is `OPEN`, the region moves to `RESTRICTED`, its settled `operating_margin_cents` and its `access_breach_pct` are both recomputed, and a wide reconciliation spreads outward. Every capacity plan in the region whose status is `PLANNING`, `UNDER_REVIEW`, `ACTIVE` or `ADJUSTED` has its `committed_slots` and `supply_shortfall_slots` recomputed and its `recalculation_epoch` advanced. Every department in the region whose `appointment_slots_committed` has reached its `appointment_slots_budgeted`, or whose status is already `CONSTRAINED`, is moved from `OPEN` to `CONSTRAINED`. Every referral targeting a department in that region that is still in `PENDING_TRIAGE` is moved to `HELD`, and every appointment referencing such a referral that is still in `REQUESTED` status has its `hold_status` set to `REFERRAL_HOLD`. Finally a `POSTURE_CHANGE` alert at `INFO` severity referencing the region is raised, and the region's `open_alert_count` is recomputed.

The capacity-driven route into `RESTRICTED` is a separate and narrower branch, reached when `capacity_committed_appointments` grows past `capacity_budget_appointments` while the region is still `OPEN`. It also sets the posture to `RESTRICTED` and also holds every `PENDING_TRIAGE` referral in the region, but in place of the department reconciliation it closes every `ACTIVE` provider in the region by setting their status to `PANEL_CLOSED`, and it raises a `CAPACITY_SHORTFALL` alert at `WARNING` severity rather than a posture-change notice.

Descent to `FROZEN` is reserved for the deeper fiscal failure: a region already in `RESTRICTED` whose settled margin falls below negative five hundred million cents. That step sets the posture to `FROZEN`, closes every `ACTIVE` provider in the region by moving it to `PANEL_CLOSED`, freezes every `ACTIVE` capacity plan by moving it to `FROZEN`, raises a `POSTURE_CHANGE` alert at `CRITICAL` severity referencing the region, and recomputes `open_alert_count`. Recovery is deliberately narrower than descent. A region in `FROZEN` whose settled margin returns to zero or above moves back exactly one step, to `RESTRICTED`; it does not return directly to `OPEN`, and nothing that was closed or frozen on the way down is reopened by that step. A region in `RESTRICTED` whose settled margin returns to zero or above moves to `OPEN`, and a referral in `HELD` status targeting that region returns to `PENDING_TRIAGE`.

### 3.9. Moving Members Between Regions

Because benefit design and network composition differ by region, a member's move from one region of record to another is an explicit, staged process rather than a field update. A `RegionalFinanceOfficer` requests a transfer with a `member_id`, a `from_region_id`, a `to_region_id`, an `effective_utc` instant, and the `expected_member_version` from §2.9. The new `MemberTransfer` computes `benefit_difference_cents` — the destination region's capitation for that member minus the origin region's — and sets `network_difference_flag` to true when the two regions' network service availability profiles differ for the member's `plan_product`. The transfer starts in `REQUESTED` status, and the member's `version` advances by one.

The destination region's `RegionalFinanceOfficer` accepts a `REQUESTED` transfer, which is permitted only while the destination region's posture is not `FROZEN`. Acceptance moves the transfer to `PENDING_EFFECTIVE` and moves the member to `TRANSFER_PENDING`, which is the status that keeps the member's capitation counted in the origin region's `premium_revenue_cents` while the move is in flight. Rejection from `REQUESTED` moves the transfer to `REJECTED` and leaves the member's region of record untouched.

Completion belongs to a `RegionalFinanceOfficer` and requires the transfer to be in `PENDING_EFFECTIVE` and the logical clock to be at or after the transfer's `effective_utc`; a completion attempted before that instant is refused with `ERR_TRANSFER_EFFECTIVE_DATE_NOT_REACHED` (HTTP 409), and a completion requested from any other status is refused with `ERR_TRANSFER_NOT_COMPLETABLE` (HTTP 409). A successful completion is the system's widest single cascade. The transfer moves to `COMPLETED`; the member's `region_id` becomes the destination region and `capitation_rate_cents` is recomputed at the destination region's own `capitation_index`; the member returns to `ACTIVE`; the destination region's `premium_revenue_cents` and `member_count` are recomputed; every `ACTIVE` provider in the destination region has `panel_size_assigned`, `quality_score`, `volume_component_cents`, `panel_capitation_component_cents`, `quality_bonus_cents` and `comp_total_cents` recomputed; the destination region's `employed_delivery_cost_cents`, `referential_integration_credit_cents` and `computed_margin_cents` are recomputed; and the `version` of the transfer, the member and both regions advance.

Cancellation may be performed by a `RegionalFinanceOfficer` from `REQUESTED`, or from `PENDING_EFFECTIVE` while the logical clock is still before `effective_utc`. Either way the transfer moves to `CANCELLED`; from `PENDING_EFFECTIVE` the member additionally returns to `ACTIVE` with its region of record unchanged at the origin region. Separately, a member sitting in `TRANSFER_PENDING` whose transfer is rejected by the destination region moves to `SUSPENDED` with no capitation booked into the destination region, and a suspended member returns to `ACTIVE` if that transfer is subsequently cancelled, again with `region_id` unchanged at the origin. `COMPLETED`, `REJECTED` and `CANCELLED` are the transfer's terminal states.

### 3.10. Quality, Access and Internal-Referral Accountability

Quality and access accountability is expressed through `QualityMetric` rows opened by a `QualityReviewBoard` against a region and a `period`, with a `metric_code` drawn from `ACCESS_WAIT_DAYS`, `QUALITY_COMPOSITE`, `MEMBER_SATISFACTION` and `PANEL_AVAILABILITY`, a `target_value`, and an `accountable_provider_id` naming the provider answerable for remediation. A region may hold only one metric for a given `metric_code` and `period` pair; a second is rejected with `ERR_DUPLICATE_QUALITY_METRIC` (HTTP 409). A metric starts in `MEASURING` with `measured_value` at zero.

Finalization is gated on internal-referral accounting being complete. The gate is the logged internal-referral percentage for the region and period reaching exactly 1.0 — that is, every referral decision for the period must be logged before a metric can be scored. Finalization is available from `MEASURING` or `REOPENED`; a finalization requested from any other status is refused with `ERR_METRIC_NOT_FINALIZABLE` (HTTP 409). The logged percentage is computed as the count of referrals referred inside divided by the total authorized count, rounded half-up, and it is built only from referrals whose status is `AUTHORIZED`, `SCHEDULED` or `COMPLETED`; denied referrals are excluded from the denominator entirely. Finalization computes `measured_value`, computes `weighted_component_score`, and moves the metric to `FINALIZED`. For an `ACCESS_WAIT_DAYS` metric the measured value is the mean of `wait_days` over the region's non-cancelled appointments for the period, expressed to one decimal place.

Composite scoring is weighted and rounds per component before summing. Each component `c` is scored as one hundred times the ratio of its `measured_value` to its `target_value`, constrained to the closed interval from zero to one, then rounded half-up to a whole number. That component score is then multiplied by the component's weight and rounded half-up to produce the component's `weighted_component_score`. The composite is the sum of the per-component weighted scores. The weights are forty percent for the access component, thirty percent for the quality component, twenty percent for the satisfaction component, and ten percent for the panel component, and the resulting composite is an integer between zero and one hundred. The nested rounding is deliberate: rounding the weighted sum once at the end rather than rounding each component first produces a different integer, and that single-round reading is incorrect.

Finalization propagates. When the metric's `metric_code` is `QUALITY_COMPOSITE`, the measured value is written onto the accountable provider's `quality_score`, and that provider's `comp_total_cents`, the parent region's `employed_delivery_cost_cents` and the region's `operating_margin_cents` are recomputed; when that recomputed margin falls below zero the posture ladder runs. The parent region's `quality_composite_score` — a weighted composite over the region's `FINALIZED` metrics — is also recomputed, and a `QUALITY_GAP` alert at `WARNING` severity referencing the metric is raised. A metric whose finalized `measured_value` falls below its `target_value` moves automatically from `FINALIZED` to `REMEDIATION`, and in doing so sets the accountable provider's status to `PANEL_CLOSED`. The board may reopen a metric in `REMEDIATION` to `REOPENED` for re-measurement; a `REOPENED` metric can be finalized again, which recomputes `measured_value` and `weighted_component_score` and can once more trigger the posture ladder. A metric has no terminal state.

Region-level access reporting follows the same measurement. The region's `access_breach_pct` is one hundred times the count of its breached appointments divided by its count of non-cancelled appointments, rounded half-up to two decimal places; appointments in `CANCELLED` status are excluded from both the numerator and the denominator. The `ACCESS_WAIT_DAYS` measured value is the sum of `wait_days` over the region's non-cancelled appointments in the period divided by their count, expressed to one decimal place.

### 3.11. Referential Integrations and Settlement Credits

An affiliation with an external payer, medical group, hospital entity or third-party administrator platform is captured as a `ReferentialIntegration` proposed by a `BudgetAppropriationsCommittee` with an `integration_type` drawn from `PAYER_ENTITY`, `MEDICAL_GROUP`, `HOSPITAL_ENTITY` and `TPA_PLATFORM`, a `risk_sharing_model` drawn from `CAPITATED`, `SHARED_SAVINGS`, `BUNDLED` and `NOT_AT_RISK` defaulting to `CAPITATED`, a `bound_effective_date`, a `cost_reporting_basis_cents`, a `shared_savings_rate` defaulting to zero, a `per_diem_days`, a `per_diem_rate_cents`, a `per_diem_cap_cents`, and an `interim_claim_count`. A proposal begins in `PROPOSED` status with `settlement_posted_cents` at zero and a computed `settlement_account_cents`.

The settlement account is assembled from two components. The per-diem component is the smaller of `per_diem_days` multiplied by `per_diem_rate_cents`, rounded half-up, and `per_diem_cap_cents` — a non-linear cap that binds whenever the day count would otherwise push the component past the cap. The basis component is `cost_reporting_basis_cents` multiplied by the integration's effective credit rate, rounded half-up. The effective credit rate is normally the credit rate keyed to the integration's `risk_sharing_model`, but when `interim_claim_count` exceeds forty the rate is multiplied by one and a half before the basis component is computed. The credit rates themselves are twelve percent for `CAPITATED`, twenty percent for `SHARED_SAVINGS`, eight percent for `BUNDLED`, and zero for `NOT_AT_RISK`. The `settlement_account_cents` is the sum of the per-diem component and the basis component. Note that `shared_savings_rate` is captured as an input but never scales the settlement on its own; it is read only through the `SHARED_SAVINGS` credit rate.

The region's rollup of these credits, `referential_integration_credit_cents`, sums `settlement_account_cents` over the region's non-terminated integrations, weighted by the integration's risk-sharing credit rate. Binding a proposal is available while the region's posture is not `FROZEN`; it moves the integration from `PROPOSED` to `BOUND`, increases the region's `referential_integration_credit_cents` by the basis component, recomputes the region's `computed_margin_cents`, and advances the region's `version`. Enrollment from `BOUND` moves the integration to `ENROLLED`, adds the posted portion of the settlement account to the region's `premium_revenue_cents`, recomputes the region's `referential_integration_credit_cents`, and adds the unposted remainder to the region's `outside_services_committed_cents` — which is the path by which an affiliation's unfunded portion is reported as outside-services spending. Contracting from `ENROLLED` moves the integration to `CONTRACTED`, sets `settlement_posted_cents` equal to the full `settlement_account_cents`, and recomputes the region's `computed_margin_cents`.

Termination is available from `BOUND` or `ENROLLED` and is not available once the integration has contracted. Terminating a `BOUND` integration moves it to `TERMINATED`, reduces the region's `referential_integration_credit_cents` by that integration's contribution, recomputes the region's `computed_margin_cents`, and advances the region's `version`. Terminating an `ENROLLED` integration moves it to `TERMINATED`, reduces the region's `premium_revenue_cents` by `settlement_posted_cents`, reduces the region's `outside_services_committed_cents` by the unposted remainder, and recomputes the region's `computed_margin_cents`. `TERMINATED` is the terminal state.

## 4. Endpoint Definitions

Operations that create a new resource, whether standalone or as a new member of a collection, respond with `201 Created`; operations that modify an existing resource respond with `200 OK`. Read operations respond with `200 OK`. The table below lists each endpoint with its authorized role set; the request payloads, response bodies and side effects are specified in §2 and §3 and are deliberately omitted here.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/regions` | Create an operating Region | `PlatformAdmin` |
| GET | `/regions` | List operating Regions | All roles |
| GET | `/regions/{id}` | Get one Region with its computed operating aggregates | All roles |
| POST | `/regions/{id}/members` | Enroll a Member into a Region | `RegionalFinanceOfficer` |
| GET | `/regions/{id}/members` | List the Members of a Region | All roles |
| POST | `/members/{id}/terminate` | Terminate a Member's coverage | `RegionalFinanceOfficer` |
| PATCH | `/members/{id}` | Correct a member's risk score | `RegionalFinanceOfficer` |
| GET | `/members` | List Members across regions | All roles |
| GET | `/members/{id}` | Get one Member | All roles |
| POST | `/regions/{id}/care-sites` | Open a CareSite funded by a Region | `RegionalFinanceOfficer` |
| GET | `/regions/{id}/care-sites` | List the CareSites of a Region | All roles |
| GET | `/care-sites` | List CareSites across regions | All roles |
| GET | `/care-sites/{id}` | Get one CareSite | All roles |
| POST | `/care-sites/{id}/staffing` | Set filled staffing full-time-equivalents | `RegionalFinanceOfficer` |
| POST | `/care-sites/{id}/departments` | Open a clinical Department inside a CareSite | `AccessScheduler` |
| GET | `/care-sites/{id}/departments` | List the Departments of a CareSite | All roles |
| GET | `/departments` | List Departments across sites | All roles |
| GET | `/departments/{id}` | Get one Department | All roles |
| PATCH | `/departments/{id}` | Adjust a Department's capacity flags | `AccessScheduler` |
| POST | `/care-sites/{id}/providers` | Register a Provider under a compensation arrangement | `RegionalFinanceOfficer` |
| GET | `/care-sites/{id}/providers` | List the Providers of a CareSite | All roles |
| GET | `/providers` | List Providers across sites and regions | All roles |
| GET | `/providers/{id}` | Get one Provider with its compensation breakdown | All roles |
| PATCH | `/providers/{id}/compensation-model` | Change a Provider's compensation model | `RegionalFinanceOfficer` |
| POST | `/provider-compensation-plans` | Draft a compensation plan with no volume component | `RegionalFinanceOfficer` |
| POST | `/regions/{id}/network-services` | Declare a network service and its availability | `AccessScheduler` |
| GET | `/regions/{id}/network-services` | List the NetworkServices of a Region | All roles |
| GET | `/network-services/{id}` | Get one NetworkService | All roles |
| POST | `/appointments` | Book an Appointment slot for a Member | `AccessScheduler` |
| GET | `/appointments` | List Appointments with filters | All roles |
| GET | `/appointments/{id}` | Get one Appointment | All roles |
| POST | `/appointments/{id}/cancel` | Cancel an Appointment and release its slot | `AccessScheduler` |
| POST | `/appointments/{id}/complete` | Mark an Appointment delivered | `CareTeamMember` |
| POST | `/referrals` | Raise a referral and resolve its in-network target | `AccessScheduler` |
| GET | `/referrals` | List Referrals with filters | All roles |
| GET | `/referrals/{id}` | Get one Referral | All roles |
| POST | `/referrals/{id}/authorize` | Authorize a referral, including from the appeal loop | `UtilizationReviewer` |
| POST | `/referrals/{id}/deny` | Deny a referral, including from the appeal loop | `UtilizationReviewer` |
| POST | `/referrals/{id}/appeal` | Open an appeal round on a denied referral | `UtilizationReviewer` |
| POST | `/referrals/{id}/capacity-plans` | Budget appointment supply for the referral's target department | `AccessScheduler` |
| POST | `/regions/{id}/outside-service-claims` | Submit an outside-service claim | `RegionalFinanceOfficer` |
| GET | `/regions/{id}/outside-service-claims` | List the outside-service claims of a Region | `PlatformAdmin`, `RegionalFinanceOfficer`, `UtilizationReviewer`, `BudgetAppropriationsCommittee` |
| GET | `/outside-service-claims` | List outside-service claims with filters | `PlatformAdmin`, `RegionalFinanceOfficer`, `UtilizationReviewer`, `BudgetAppropriationsCommittee` |
| GET | `/outside-service-claims/{id}` | Get one OutsideServiceClaim | `PlatformAdmin`, `RegionalFinanceOfficer`, `UtilizationReviewer`, `BudgetAppropriationsCommittee` |
| POST | `/outside-service-claims/{id}/adjudicate` | Adjudicate a claim and pin its final liability | `RegionalFinanceOfficer` |
| POST | `/outside-service-claims/{id}/pay` | Pay an adjudicated claim | `RegionalFinanceOfficer` |
| POST | `/outside-service-claims/{id}/deny` | Deny an adjudicated claim or an appeal | `UtilizationReviewer` |
| POST | `/outside-service-claims/{id}/appeal` | Open an appeal round on a denied claim | `UtilizationReviewer` |
| POST | `/referral-claims/bulk-adjudicate` | Adjudicate every submitted claim for one referral | `RegionalFinanceOfficer` |
| GET | `/referral-claims/{id}` | Get one referral-linked claim batch | `PlatformAdmin`, `RegionalFinanceOfficer`, `UtilizationReviewer` |
| POST | `/regions/{id}/regional-budgets` | Open an operating budget for a region and period | `RegionalFinanceOfficer` |
| GET | `/regions/{id}/regional-budgets` | List the operating budgets of a Region | `PlatformAdmin`, `RegionalFinanceOfficer`, `BudgetAppropriationsCommittee` |
| GET | `/regional-budgets` | List regional operating budgets across all regions | `PlatformAdmin`, `BudgetAppropriationsCommittee` |
| GET | `/regional-budgets/{id}` | Get one RegionalBudget | `PlatformAdmin`, `RegionalFinanceOfficer`, `BudgetAppropriationsCommittee` |
| POST | `/regional-budgets/{id}/submit` | Submit a budget for committee approval | `RegionalFinanceOfficer` |
| POST | `/regional-budgets/{id}/approve` | Approve a submitted budget | `BudgetAppropriationsCommittee` |
| POST | `/regional-budgets/{id}/return` | Return a submitted budget to draft | `BudgetAppropriationsCommittee` |
| POST | `/regional-budgets/{id}/close` | Close an approved budget period | `RegionalFinanceOfficer` |
| POST | `/regional-budgets/{id}/reopen` | Reopen an approved or closed budget period | `BudgetAppropriationsCommittee` |
| POST | `/regions/{id}/capacity-plans` | Budget appointment supply for a department and period | `RegionalFinanceOfficer` |
| GET | `/regions/{id}/capacity-plans` | List the capacity plans of a Region | `PlatformAdmin`, `RegionalFinanceOfficer`, `AccessScheduler`, `BudgetAppropriationsCommittee` |
| GET | `/capacity-plans` | List capacity plans with filters | `PlatformAdmin`, `RegionalFinanceOfficer`, `AccessScheduler`, `BudgetAppropriationsCommittee` |
| GET | `/capacity-plans/{id}` | Get one CapacityPlan | `PlatformAdmin`, `RegionalFinanceOfficer`, `AccessScheduler`, `BudgetAppropriationsCommittee` |
| POST | `/capacity-plans/{id}/review` | Send a capacity plan to review | `AccessScheduler` |
| POST | `/capacity-plans/{id}/activate` | Activate a reviewed capacity plan | `RegionalFinanceOfficer` |
| POST | `/capacity-plans/{id}/adjust` | Adjust the budgeted supply of an active plan | `RegionalFinanceOfficer` |
| POST | `/capacity-plans/{id}/return` | Return a reviewed capacity plan to planning | `AccessScheduler` |
| POST | `/member-transfers` | Request a transfer of a member between regions | `RegionalFinanceOfficer` |
| GET | `/member-transfers` | List member transfers with filters | `PlatformAdmin`, `RegionalFinanceOfficer`, `BudgetAppropriationsCommittee` |
| GET | `/member-transfers/{id}` | Get one MemberTransfer | `PlatformAdmin`, `RegionalFinanceOfficer`, `BudgetAppropriationsCommittee` |
| POST | `/member-transfers/{id}/accept` | Accept a transfer request at the destination region | `RegionalFinanceOfficer` |
| POST | `/member-transfers/{id}/reject` | Reject a transfer request | `RegionalFinanceOfficer` |
| POST | `/member-transfers/{id}/complete` | Complete a transfer once its effective instant has passed | `RegionalFinanceOfficer` |
| POST | `/member-transfers/{id}/cancel` | Cancel a transfer request | `RegionalFinanceOfficer` |
| POST | `/regions/{id}/quality-metrics` | Open a quality or access metric for a region and period | `QualityReviewBoard` |
| GET | `/regions/{id}/quality-metrics` | List the quality metrics of a Region | `PlatformAdmin`, `RegionalFinanceOfficer`, `QualityReviewBoard`, `BudgetAppropriationsCommittee` |
| GET | `/quality-metrics` | List quality metrics with filters | `PlatformAdmin`, `RegionalFinanceOfficer`, `QualityReviewBoard`, `BudgetAppropriationsCommittee` |
| GET | `/quality-metrics/{id}` | Get one QualityMetric | `PlatformAdmin`, `RegionalFinanceOfficer`, `QualityReviewBoard`, `BudgetAppropriationsCommittee` |
| POST | `/quality-metrics/{id}/finalize` | Finalize a metric | `QualityReviewBoard` |
| POST | `/quality-metrics/{id}/reopen` | Reopen a metric in remediation for re-measurement | `QualityReviewBoard` |
| POST | `/regions/{id}/referential-integrations` | Propose a binding with an affiliated entity | `BudgetAppropriationsCommittee` |
| GET | `/regions/{id}/referential-integrations` | List the referential integrations of a Region | `PlatformAdmin`, `RegionalFinanceOfficer`, `BudgetAppropriationsCommittee` |
| GET | `/referential-integrations/{id}` | Get one ReferentialIntegration | `PlatformAdmin`, `RegionalFinanceOfficer`, `BudgetAppropriationsCommittee` |
| POST | `/referential-integrations/{id}/bind` | Bind an integration and book its credit | `BudgetAppropriationsCommittee` |
| POST | `/referential-integrations/{id}/enroll` | Enroll a bound integration | `BudgetAppropriationsCommittee` |
| POST | `/referential-integrations/{id}/contract` | Contract an enrolled integration at full settlement | `BudgetAppropriationsCommittee` |
| POST | `/referential-integrations/{id}/terminate` | Terminate an integration and reverse its booking | `BudgetAppropriationsCommittee` |
| GET | `/regions/{id}/alerts` | List the alerts raised against a Region | All roles |
| POST | `/alerts/{id}/acknowledge` | Acknowledge a raised alert | `RegionalFinanceOfficer` |
| POST | `/_clock/set_current_utc` | Set the logical clock | `PlatformAdmin` |
| PATCH | `/_outcome-targets/{id}` | Set a QualityMetric's measured value and scored outcome directly | `PlatformAdmin` |
| POST | `/_inject/member-risk-score` | Set a member's risk score and recompute the forward margin | `PlatformAdmin` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 |
| `ERR_REGION_NOT_FOUND` | 404 |
| `ERR_MEMBER_NOT_FOUND` | 404 |
| `ERR_CARE_SITE_NOT_FOUND` | 404 |
| `ERR_DEPARTMENT_NOT_FOUND` | 404 |
| `ERR_PROVIDER_NOT_FOUND` | 404 |
| `ERR_NETWORK_SERVICE_NOT_FOUND` | 404 |
| `ERR_APPOINTMENT_NOT_FOUND` | 404 |
| `ERR_REFERRAL_NOT_FOUND` | 404 |
| `ERR_OUTSIDE_CLAIM_NOT_FOUND` | 404 |
| `ERR_REGIONAL_BUDGET_NOT_FOUND` | 404 |
| `ERR_CAPACITY_PLAN_NOT_FOUND` | 404 |
| `ERR_MEMBER_TRANSFER_NOT_FOUND` | 404 |
| `ERR_QUALITY_METRIC_NOT_FOUND` | 404 |
| `ERR_REFERENCED_RESOURCE_NOT_FOUND` | 422 |
| `ERR_CROSS_REGION_REFERENCE` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_REFERRAL_NOT_DECIDABLE` | 409 |
| `ERR_CLAIM_NOT_ADJUDICABLE` | 409 |
| `ERR_BUDGET_NOT_SUBMITTABLE` | 409 |
| `ERR_CAPACITY_PLAN_NOT_ACTIVATABLE` | 409 |
| `ERR_TRANSFER_NOT_COMPLETABLE` | 409 |
| `ERR_METRIC_NOT_FINALIZABLE` | 409 |
| `ERR_REFERRAL_TRIAGE_WINDOW_EXPIRED` | 409 |
| `ERR_REFERRAL_EXPIRED` | 409 |
| `ERR_TRANSFER_EFFECTIVE_DATE_NOT_REACHED` | 409 |
| `ERR_SERVICE_NOT_AVAILABLE_IN_NETWORK` | 409 |
| `ERR_NO_IN_NETWORK_CAPACITY` | 409 |
| `ERR_VOLUME_COMPONENT_NOT_PERMITTED` | 422 |
| `ERR_APPEAL_ROUNDS_EXHAUSTED` | 409 |
| `ERR_REFERRAL_NOT_AUTHORIZED` | 409 |
| `ERR_UNAUTHORIZED_NETWORK_EXPANSION` | 409 |
| `ERR_BUDGET_NOT_APPROVED` | 409 |
| `ERR_DUPLICATE_QUALITY_METRIC` | 409 |
| `ERR_DUPLICATE_CAPACITY_PLAN` | 409 |
| `ERR_PROVIDER_SCHEDULE_OVERLAP` | 409 |
| `ERR_REGION_POSTURE_FROZEN` | 409 |
| `ERR_DEPARTMENT_CAPACITY_EXHAUSTED` | 409 |
| `ERR_FTE_BUDGET_EXCEEDED` | 409 |
| `ERR_BUDGET_FISCAL_LINE_EXCEEDED` | 402 |
| `ERR_STALE_VERSION` | 412 |