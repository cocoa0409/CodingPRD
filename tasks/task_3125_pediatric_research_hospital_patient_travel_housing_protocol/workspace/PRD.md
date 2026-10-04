# Pediatric Research Hospital API — Product Requirements Document

## 1. Introduction

A family whose child has just been diagnosed with a catastrophic pediatric disease does not
need another invoice. That conviction is the reason this platform exists: treatment itself is
never billed to the household, and every dollar the family would otherwise spend getting to
the hospital, sleeping near the hospital, and eating while they are there is covered from a
donor-funded pool. The API described here is the operational spine of that promise. It takes a
referral from an outside institution, screens it against a research protocol's eligibility
rules, places the family in housing matched to the expected length of treatment and the
child's immune status, walks the household through consent and, where the child is old enough,
assent, and then keeps the family supported — travel legs, meal allowances, sibling services,
mileposts in the treatment course — until the child graduates into long-term survivorship
follow-up.

The design tension throughout is between generosity and accountability. Funds arrive from
private campaigns and federal grants in uneven amounts, they are split between research and
patient support at commitment time, and each protocol may only draw a fixed budget against
them. Housing is a finite pool of beds with a buffer that must never be oversubscribed, and
immunosuppressed children may only be placed at residences capable of caring for them. Because
research budgets, bed inventories, and enrollment capacity are all shared resources that
several coordinators touch at once, the platform treats the referral funnel as a
concurrency-sensitive workflow: the two steps that admit a patient to the program are guarded
by explicit version checks so that a screen or an arrival computed against a stale protocol or
referral is refused rather than silently applied.

The document below is written for the engineers who will build the service. Section 2 fixes
the cross-cutting contracts — roles and headers, the response envelope, pagination, the ledger
principles, the tier selector, precision, concurrency. Section 3 narrates the business
workflows in the order a family would encounter them. Section 4 lists the endpoint surface and
Section 5 the error catalogue. Nothing is billed to a family except the single excess line
defined in §2.7.

## 2. Global Specifications & System-Wide Principles

### 2.1. Roles, Identity Headers and the Care-Team Authority Model

Every request must carry two headers. `X-User-ID` identifies the acting user and `X-User-Role`
declares their operational capacity. A request that omits either header, or presents an
unresolvable value, is refused with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400).
An authenticated caller whose role is not permitted for the requested operation is refused with
`ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403). These two checks run before every other rule in the
system, in that order, so a malformed header is never reported as a permission problem.

The platform recognizes nine role names, spelled exactly as follows: `PlatformAdmin`,
`ProtocolCoordinator`, `IRBReviewer`, `IntakeCoordinator`, `HousingCoordinator`,
`PatientSupportOfficer`, `AffiliateClinicCoordinator`, `SurvivorshipCoordinator`, and `Any`.
`Any` is not a grantable persona but the read-visibility marker shared by every authenticated
role: operations declared for `Any` are reachable by any of the eight named roles, while
operations declared for a specific role are exclusive to it unless that role's own description
lists them as shared reads.

None of these roles is backed by a persisted entity. For every role in the matrix, `X-User-ID`
is an opaque operator identifier that is not tied to any row in the database; the server may
record it where a workflow stores an operator reference, but it never compares it to an
entity's `id`. Ownership therefore is never inferred from identity — a coordinator acting for a
family is authorized by role, and the family's own records are addressed by the resource
identifiers in the request.

`PlatformAdmin` is the donor-funding and platform operator: it exclusively owns fund creation,
additional donations, the logical-clock setter and the operations checkpoint, and it shares
read access to the fund list and to an individual fund. `ProtocolCoordinator` owns the protocol
itself — drafting, opening, closing, releasing a hold, releasing a hold record, and registering
milestones on an enrollment — and shares reads of protocols and holds.
`IRBReviewer` is the institutional review officer: it alone raises a hold on a protocol,
escalates an IRB-review hold into a clinical review lock, and records a child's own assent.
`IntakeCoordinator` owns the referral funnel and the treatment lifecycle end to end: referral
submission, screening, arrival, withdrawal, consent signing, treatment start, hiatus, resume,
treatment completion and follow-up closure. `HousingCoordinator` owns facilities, bookings and
the on-campus-to-partner step-down path. `PatientSupportOfficer` owns pledges, travel legs,
family-service allowances, service-line creation and ledger freezing, and sibling services.
`AffiliateClinicCoordinator` registers clinics, pins affiliation agreements, and both defers
and executes milestones closer to home. `SurvivorshipCoordinator` owns follow-up studies,
survivor enrollment and the long-run visit schedule.

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

### 2.3. Pagination and List Ordering

List operations accept `limit` and `offset` as query parameters. `limit` caps how many items are
returned and defaults to 10; its minimum accepted value is 1 and its maximum is 100. `offset`
is the number of items to skip and defaults to 0. No list endpoint in this program is
unpaginated — every collection response carries `limit`, `offset`, `total_count`, and
`has_more` in the `meta` object, including the sub-collection reads such as a protocol's
referrals, an enrollment's pledges, or an affiliate's deferred milestones.

Unless a workflow states otherwise, list responses are ordered by creation timestamp ascending.
Two collections carry an explicit visibility rule rather than a default filter. The enrollment
list omits every row in `WITHDRAWN` status when no `enrollment_status` filter is supplied; an
explicit `enrollment_status` of `WITHDRAWN` is the only way to surface withdrawn rows. The
protocol, referral, housing-assignment, travel, pledge, milestone, study, survivorship and
sibling collections expose `status` as an optional filter and return everything when it is
absent.

### 2.4. The Donor-Fund Ledger and the Commitment Split

Everything the program spends traces back to a `ResearchFund` — a donor-funded campaign
identified by a `fund_code` and bound to a `fiscal_year`. The campaign records what was raised
in `fundraising_raised_cents` and what arrived as a federal grant in `federal_grant_cents`, both
in integer cents. When the fund is created, and again on every later read of the fund, the
server derives two pools from those figures using the `research_allocation_pct` chosen at
commitment time.

The research pool `research_balance_cents` holds the share of the money raised that belongs to
research: it is the fundraising total multiplied by the research allocation percentage, rounded
up to the next whole cent. The patient-support pool `patient_support_balance_cents` holds what
remains: net fundraising — the money raised minus the federal grant funds — less that same
rounded-up research share. Because both pools are re-derived on every read rather than frozen,
recording a later donation through the fund's donation capability changes the totals a
subsequent read reports, while any protocol budget already committed against the fund is
unchanged. A donation carries an `amount_cents` and an optional `is_federal_grant` flag; a
successful donation increases `fundraising_raised_cents`, or increases `federal_grant_cents`
instead when `is_federal_grant` is true, re-derives both pools, and advances the fund's
`version` by one.

Protocol budgets are capped against the fund at creation. A protocol's `protocol_budget_cents`
may not exceed three quarters of the fund's net fundraising — the money raised minus the
federal grant funds — divided by the number of protocols that fund supports, with the result
rounded down to a whole cent. A protocol created with a budget above that ceiling is refused
with `ERR_PROTOCOL_BUDGET_EXCEEDS_COMMITMENT_SHARE` (HTTP 402). The three-quarters share and
the division are evaluated as described here; the budget itself, once accepted, stays fixed
even if later donations enlarge the fund. The divisor is the number of protocols created
against that `fund_id`, so a fund carrying several protocols divides its commitment share
across them.

Several counters on these entities are mirrors of live funnel state rather than stored inputs.
An enrollment's `protocol_enrolled_count` mirrors the host protocol's `enrolled_count` and is
refreshed whenever that enrollment is written, and an enrollment's `active_family_count` counts
the families from that enrollment currently holding an `ACTIVE` housing assignment or an
`ACTIVE` family pledge.

### 2.5. Reservation, Saturation and the Research Budget Envelope

Each protocol carries a research budget and three counters that move as families are admitted.
`protocol_budget_cents` is the total earmarked for the protocol. `reserved_cents` holds the
money pledged by accepted families that have not yet been enrolled. `committed_cents` holds the
money already booked against the budget by active families. `available_cents` is what remains:
the budget less the reserved amount less the committed amount. Nothing may be reserved or
committed if it would leave `available_cents` at or below zero; a screen that would do so is
refused with `ERR_PROTOCOL_BUDGET_EXHAUSTED` (HTTP 402), and a budget failure records no
accrual on the protocol at all.

A protocol is flagged `is_budget_saturated` once `available_cents` is above zero but no larger
than three point seven five percent of the protocol budget, rounded up to the next whole cent.
The flag is recomputed after every event that touches the counters. `enrolled_count` tracks the
patients currently in `ENROLLED` status and `capacity` caps them; a screen or a consent signing
that would push `enrolled_count` to `capacity` or beyond is refused with
`ERR_PROTOCOL_CAPACITY_EXCEEDED` (HTTP 409), and completion of treatment decrements the count
while survivorship and withdrawal adjust it as described in §3.

Two derived attributes describe who a protocol can accept. `age_tier` is `PAEDIATRIC` when the
protocol's `age_max_years` is below 12, `ADOLESCENT` when `age_min_years` is 12 or above, and
`MIXED` when the band spans that boundary. `mental_capacity_floor` is the larger of the
protocol's `age_min_years` and 7 — the age from which a child's own assent becomes the deciding
signature. A protocol's `required_stage` is one of `NEWLY_DIAGNOSED`, `RELAPSED`, `REFRACTORY`,
or `REMISSION`, and its `status` moves through `DRAFT`, `OPEN`, `HELD`, and `CLOSED`; only an
`OPEN` protocol accepts referrals or enrollments.

### 2.6. Housing Tier Selection and Bed Inventory

Residences are registered as `HousingFacility` rows with a `facility_code`, a display `name`, a
`tier`, a `total_beds` count and an optional `buffer_beds` count. The tier is one of
`ON_CAMPUS`, `PARTNER_CLASS_A`, `PARTNER_CLASS_B`, or `PARTNER_CLASS_C`. Three capability flags
are derived rather than supplied. `is_on_campus` is true exactly when the tier is `ON_CAMPUS`,
and `is_partner_site` is true exactly when the tier is not `ON_CAMPUS`.
`immunosuppression_capable` is true exactly when the tier is `ON_CAMPUS` or `PARTNER_CLASS_A` —
there, and only there, may an immunosuppressed child be housed, though immune-competent
families may also be placed in such a residence. `is_step_down_capable` is true exactly when
the tier is `PARTNER_CLASS_A` or `PARTNER_CLASS_B`, marking the residences a family may move
down to once immunosuppression has cleared. A facility's `status` is `OPEN`, `SUSPENDED`, or
`CLOSED`, and only an `OPEN` residence is offered to the selector. `active_beds_committed` is
the highest number of occupancies that coincide at any single instant across the facility's
assignments in `SCHEDULED` or `ACTIVE` status, recomputed on activation, on vacation, and on
every read of the facility.

Choosing a residence is a deterministic ranking, not a preference. First the selector computes
the referral's `selector_window_days` as the smaller of the referral's `expected_treatment_days`
and 540 days, then divides by 180 days and rounds up to obtain a whole number of duration
steps. One step requires `PARTNER_CLASS_C`; two steps require `PARTNER_CLASS_A`; three or more
steps require `PARTNER_CLASS_B`. Both immunosuppression conditions override the step count: if
the referral's `is_immunosuppressed` is true, or its `has_febrile_neutropenia_risk` is true,
the required tier is `ON_CAMPUS`. Because the 540-day clamp is applied before the band count,
a referral declaring 900 treatment days and one declaring 540 resolve to the same window and
the same band. Candidate facilities are those whose `status` is `OPEN` and whose tier is at
least as capable as the required tier, ordered by the tier's position in the sequence
`ON_CAMPUS`, `PARTNER_CLASS_A`, `PARTNER_CLASS_B`, `PARTNER_CLASS_C` — lowest position first —
then by `immunosuppression_capable` descending, then by the residue of `total_beds` minus
`buffer_beds` descending. An exact tie is broken by the earliest `created_at`, and a remaining
tie by the lexicographically smallest `facility_code`. If the candidate set is empty the
screen cannot place the family: the referral is declined with `applied_tier` of `DECLINED` and
the refusal code `ERR_NO_HOUSING_AVAILABLE` (HTTP 409).

Capacity is enforced at both endpoints of a proposed window. At the start instant and again at
the end instant, the number of assignments at that facility in `SCHEDULED` or `ACTIVE` status
whose half-open occupancy window covers the instant, plus the facility's `buffer_beds`, must not
exceed its `total_beds`; otherwise the booking is refused with `ERR_HOUSING_CAPACITY_EXCEEDED`
(HTTP 409). The same test is re-run whenever a scheduled assignment is re-booked to a new
window. This rule is exercised by referral screening, by housing booking and by re-booking, and
it is the reason a facility's buffer beds are never bookable by anyone.

### 2.7. No-Billing Guarantee for Treatment, Housing, Meals and Required Travel

Treatment, housing, meals, and required travel are covered services and are never billable to
the family. The single amount that may ever be charged is held in a pledge's
`billing_permitted_cents`, and it may only ever contain the excess of the family's final
settlement over both the family-support budget and the insurance coverage committed to that
household. Any operation that would raise a billable amount from any other source is refused
with `ERR_BILLING_NOT_PERMITTED` (HTTP 409). This invariant is guarded on pledge settlement,
on pledge accrual, and on housing activation.

The family-support maths that produce that excess are pinned. At settlement, the final family
charge is covered first from the family-support budget, then from the third-party insurance
coverage, and only the residue — floored at zero — becomes billable. When the final charge
exceeds the budget plus the insurance coverage, the settlement is refused outright with
`ERR_SUPPORT_BUDGET_EXCEEDED` (HTTP 402); the budget-then-insurance ordering is a contract
even though reversing it would not change the arithmetic. `ERR_HOUSING_IMMUNOSUPPRESSION_INCOMPATIBLE`
(HTTP 422) and `ERR_STEP_DOWN_NOT_PERMITTED` (HTTP 422) enforce the safety counterpart of this
principle — an immunosuppressed child may not be placed at a facility that is not
`immunosuppression_capable`, a febrile-neutropenia risk flag forces the `ON_CAMPUS` tier, and a
family may not step down out of `ON_CAMPUS` housing until immunosuppression has been cleared.

### 2.8. Monetary Precision and Rounding

All monetary values are integer cents, and no monetary field in this program is ever a
fractional or string-encoded amount. Where a rate must be applied, the scaffold's arithmetic is
as follows: rounding is applied to each individual product rather than to a running sum, so a
charge built from several legs is the sum of individually rounded products and never a rounded
sum. The aggregate ceiling, the commitment-share floor, the research and patient-support split,
the reservation, and the screening fee are all rounded up to the next whole cent; the fund's
commitment share is the one place where the result is rounded down. The stimulation markup
multiplies the base allowance by the stimulation rate and rounds the product half up before
capping it. Charges that resolve to a whole number of cents exactly — the provisional family-day
charge, the occupancy charge, the accumulated travel charge, and the family-support settlement —
are computed without rounding at all.

### 2.9. Nested Resource Retrieval and Referential Ordering

When a request addresses a nested resource, the identifiers in the path are validated strictly
left to right, and the request fails on the first identifier that does not resolve. The path
variables a client will encounter are `fundId`, `protocolId`, `referralId`, `enrollmentId`,
`assignmentId`, `facilityId`, `pledgeId`, `travelId`, `holdId`, `milestoneId`, `clinicId`,
`agreementId`, `studyId`, `survivorshipEnrollmentId`, `serviceId`, and `ledgerId`; a read that
names a protocol and then a hold beneath it must fail on the protocol first. Where the scaffold
declares an entity-specific not-found code the server returns it in place of the generic one —
`ERR_REFERRAL_NOT_FOUND`, `ERR_PROTOCOL_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`,
`ERR_HOUSING_ASSIGNMENT_NOT_FOUND`, `ERR_HOUSING_FACILITY_NOT_FOUND`, `ERR_PLEDGE_NOT_FOUND`,
`ERR_TRAVEL_NOT_FOUND`, `ERR_MILESTONE_NOT_FOUND`, `ERR_STUDY_NOT_FOUND`,
`ERR_SURVIVORSHIP_ENROLLMENT_NOT_FOUND`, `ERR_CLINIC_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`,
`ERR_SERVICE_NOT_FOUND`, `ERR_LEDGER_NOT_FOUND`, `ERR_FUND_NOT_FOUND`,
`ERR_SIBLING_SERVICE_NOT_FOUND`, and `ERR_HOLD_NOT_FOUND`. All of these carry HTTP 404, as does
the generic `ERR_NOT_FOUND`, which is returned for any identifier with no entity-specific code.
Foreign keys supplied in a request body are validated next, in the order the endpoint's input
list declares them, and a missing body foreign key yields the generic `ERR_NOT_FOUND` rather
than an entity-specific code.

### 2.10. Common Resource Properties

Every entity in this program carries two server-managed fields. `id` is the unique identifier,
formatted as a UUID with no type prefix, and `created_at` is the ISO 8601 UTC creation instant
with three fractional digits. Every entity in this program also carries `updated_at`, the ISO
8601 UTC instant of the last modification, and `version`, an integer that starts at zero and
increments by exactly one on every mutation of the row. Every entity here declares common fields
enabled, so no row in the program omits `updated_at` or `version`; derived fields are mutations
like any other and therefore refresh `updated_at` and advance `version`.

`version` is also the currency that the concurrency rules in §2.11 read. A protocol's version
advances on opening, closing, on every hold raised against it, on every screen that reserves or
commits against it, on consent signing, on pledge voiding, on withdrawal that releases a
reservation, on travel disbursement reversal, and on every donation-driven fund re-derivation
of an affiliated row; a referral's version advances on arrival.

### 2.11. Optimistic Concurrency on the Referral Funnel

Two operations that admit a patient to the program are guarded by optimistic concurrency. The
guard is a version the client observed and now re-asserts; it is not a lock, and no rule here
depends on the relative timing of two requests.

Screening a referral is written against the `ClinicalProtocol` that will carry the family. The
screen must carry `expected_protocol_version` holding the protocol version the client last read.
If the protocol's version has moved on since that read — because another writer changed its
capacity, its reservation posture, or its hold posture — the screen is refused with
`ERR_STALE_VERSION` (HTTP 412) rather than being applied against a stale view.

Arriving a referral is written against the `Referral` itself. The arrival must carry
`expected_referral_version` holding the referral version the client last read. If the referral's
version has moved on since then — because another writer screened, withdrew, or re-screened that
same referral — the arrival is refused with `ERR_STALE_VERSION` (HTTP 412).
`expected_protocol_version` and `expected_referral_version` are both mandatory inputs to their
respective operations; no other endpoint in the program accepts a version field of this kind.
The general rule behind both is uniform: whenever an `expected_*_version` field is supplied, its
value must equal the parent entity's current `version`.

### 2.12. Protocol Freeze Propagation

A `ProtocolHold` is the mechanism by which the institution stops admitting families to a
protocol. It is created against a protocol with a `hold_reason` of `IRB_REVIEW`, `SAFETY_SIGNAL`,
`FUNDING_REVIEW`, or `SPONSOR_AUDIT`, and an `initiated_at` instant; it is created in `ACTIVE`
status and records the host protocol's `protocol_version` as observed at creation. While a hold
is active the protocol's `is_protocol_held` flag is true. Releasing a hold stamps `released_at`
from the logical clock and refreshes the hold's `protocol_version` to the protocol's current
version; escalating a hold in `ESCALATED` status likewise refreshes the recorded version, keeps
`is_protocol_held` true, and makes the hold a review lock. A hold's `is_review_lock` attribute is
true exactly when its `hold_reason` is `IRB_REVIEW` and its `status` is `ESCALATED`.

The freeze propagates. While a protocol is frozen — by an active hold or by a review lock — the
screen, arrival, consent signing, arm-assent recording, milestone deferral, and milestone
execution operations are all refused with `ERR_PROTOCOL_HELD` (HTTP 409); assent confirmation
and enrollment completion specifically report `ERR_ARM_ASSENT_BLOCKED_BY_HOLD` (HTTP 409). The
cascade into already-accepted work, and the rules that a protocol may only return to `OPEN`
when no active hold remains, are detailed in §3.9.

### 2.13. Validation Ordering and Request Hygiene

Rules are evaluated in a fixed order and the first failure is the one reported. Header presence
and role permission come first. Then path identifiers are resolved left to right, then body
foreign keys in declaration order, then uniform request hygiene — every required body field
present, integer ranges honoured, an occupancy window whose `start_at` is strictly before its
`end_at`, and the rule that a declined referral is reopened only by submitting a new referral
that names it in `reopen_source_referral_id`; hygiene failures report `ERR_INVALID_REQUEST`
(HTTP 400). Declared uniqueness follows: `protocol_code` is unique across the program, as are
`facility_code` and `clinic_code`; `service_code` is unique within its fund and `sibling_alias`
is unique within its enrollment. A collision reports `ERR_DUPLICATE_ENTITY` (HTTP 409). The OCC
guard of §2.11 follows, then the sibling session-limit guard, then the ledger-epoch guard, then
the generic state requirement that a target resource be in the state the operation demands
(`ERR_INVALID_STATE`, HTTP 409). Only after those does the server apply the protocol-freeze
check, the immunosuppression and step-down gates, the one-to-one care gate, the occupancy and
travel-overlap windows, the duplicate-patient check, capacity, age band, disease group and
stage, the budget rules, the billing invariant, the family-support budget ceiling, and finally
the survivorship follow-up window rule. Where several of these rules can fire on the same call,
the earlier one wins and later ones are not reported.
## 3. Business Logic & Workflows

### 3.1. Opening a Protocol for Referrals

A `ProtocolCoordinator` creates a clinical protocol by naming the fund that will carry it, a
`protocol_code` unique across the whole program, the `disease_group` it treats, the inclusive
age band through `age_min_years` and `age_max_years`, the `required_stage` a referral must carry
to be screen-eligible, a `protocol_budget_cents`, and a `capacity`. The protocol is born in
`DRAFT` status with `reserved_cents`, `committed_cents`, and `enrolled_count` at zero,
`is_protocol_held` and `is_budget_saturated` false, and `age_tier` and `mental_capacity_floor`
derived as §2.5 describes. Creating it with a budget above the fund's commitment share fails
with `ERR_PROTOCOL_BUDGET_EXCEEDS_COMMITMENT_SHARE`, and creating it with a `protocol_code`
already in use fails with `ERR_DUPLICATE_ENTITY`.

A draft protocol admits nobody. It becomes operable only when the `ProtocolCoordinator` opens
it, and that transition requires the protocol to still be in `DRAFT` — anything else is refused
with `ERR_PROTOCOL_NOT_IN_DRAFT` (HTTP 409) — with a `capacity` greater than zero and a
`protocol_budget_cents` greater than zero, both of which report `ERR_INVALID_REQUEST` when they
fail. Opening moves the protocol to `OPEN` and advances its version by one. Closing is the
mirror operation: it requires `OPEN` status (`ERR_PROTOCOL_NOT_OPEN` when not) and an
`enrolled_count` of exactly zero, since a protocol still carrying patients reports
`ERR_PROTOCOL_HAS_ENROLLED_PATIENTS` (HTTP 409), and it accepts a `close_reason` string. Closing
is not a pure status flip — every `SurvivorshipStudy` on that protocol transitions to `CLOSED`
with it, and every `FamilySupportPledge` sitting on a withdrawn enrollment of that protocol is
voided in the same operation.

A coordinator can read a protocol's live funding posture without walking the referral list. The
posture read returns the protocol's `protocol_id`, its current `protocol_version` for use as an
OCC token, its `protocol_status`, and the full budget picture: `capacity`, `enrolled_count`,
`protocol_budget_cents`, `reserved_cents`, `committed_cents`, `available_cents`,
`is_budget_saturated`, and `is_protocol_held`. This is the read a client should perform
immediately before screening, because `protocol_version` from this response is exactly the value
the screen must re-assert.

Milestones belong to the enrolled patient's course rather than to the protocol sheet. A
`ProtocolCoordinator` registers them against an enrollment, supplying a `milestone_sequence`
that is at least 1 and unique within that enrollment, a `description`, a `requires_main_campus`
flag, and a `target_at` instant. A registered milestone is `PENDING` with `executed_at`,
`deferred_from_milestone_id` and `affiliate_clinic_id` all null.

### 3.2. The Referral Funnel: Submission, Screening and the Tier Selector

Referrals arrive from outside institutions. An `IntakeCoordinator` submits one by supplying the
`protocol_id` it should be screened against, the `child_name`, the `child_date_of_birth`, the
`disease_group` and `disease_stage` reported by the referring institution, the family's
`household_state_code`, the `traveling_family_member_count` who must be housed (between 1 and 6),
the `expected_treatment_days` the clinician estimates (between 1 and 3650), and optionally
`is_immunosuppressed`, `insurance_coverage_cents`, `has_febrile_neutropenia_risk`,
`one_to_one_care_capability_codes`, and `reopen_source_referral_id`. The submission computes the
`eligibility_alias` — the child's name lowercased with runs of whitespace collapsed to a single
hyphen — which becomes the stable screening identity that guards against the same child being
admitted twice. A fresh submission starts in `SUBMITTED` with `applied_tier` at `PENDING`.
`traveling_one_to_one_codes` is derived on the referral as the set of `coverage_type` codes of
the `GUARDIAN`-type coverages the referral actually places, and a read of the referral's
one-to-one record reports `referral_id`, `traveling_one_to_one_code_count` and a
`one_to_one_shortfall` flag.

Screening is the funnel's narrowest gate, and it applies its checks in a fixed order. A referral
that is not in `SUBMITTED` is refused with `ERR_REFERRAL_NOT_SUBMITTED` (HTTP 409). The target
protocol must be `OPEN` and not held, or the attempt fails with `ERR_PROTOCOL_NOT_OPEN`
(HTTP 409). No other referral sharing the same `eligibility_alias` may already be `ACCEPTED` or
`ARRIVED`, otherwise the screen fails with `ERR_DUPLICATE_PATIENT_ELIGIBILITY` (HTTP 409). The
child's `computed_age_years`, measured in whole completed years against the logical clock, must
lie within the protocol's inclusive `age_min_years` to `age_max_years` band or the screen fails
with `ERR_AGE_OUTSIDE_PROTOCOL_RANGE` (HTTP 422). The referral's `disease_group` must equal the
protocol's `disease_group`, else `ERR_DISEASE_GROUP_MISMATCH` (HTTP 422), and — a distinct check
that is easy to miss — the referral's `disease_stage` must equal the protocol's `required_stage`
exactly, else `ERR_DISEASE_STAGE_MISMATCH` (HTTP 422). Capacity comes next: the protocol's
`enrolled_count` must be strictly below its `capacity`, else `ERR_PROTOCOL_CAPACITY_EXCEEDED`
(HTTP 409). Budget comes last: the protocol's `available_cents` must be strictly above zero,
else `ERR_PROTOCOL_BUDGET_EXHAUSTED` (HTTP 402). Before any of this the request must carry
`expected_protocol_version` matching the protocol's current `version`, or it is refused with
`ERR_STALE_VERSION` (HTTP 412).

An accepted screen does five things at once. It moves the referral to `ACCEPTED`. It recomputes
`screening_fee_cents` as one fortieth of the `insurance_coverage_cents` — the ceiling of two and
a half percent of that coverage — and this fee is charged on every screen attempt, accepted or
declined alike; it never moves the protocol's `available_cents` and it is never refunded. It
recomputes `is_self_pay` as true when the referral places no `FAMILY_PLEDGE` coverage. It runs
the housing selector of §2.6 to set `applied_tier`, and if the selector finds nothing it sets
`applied_tier` to `DECLINED` and refuses the whole screen with `ERR_NO_HOUSING_AVAILABLE`. And
it books a reservation on the protocol: `reservation_basis_cents` is set to one eighth of the
protocol budget rounded up to the whole cent when the accepted tier is `ON_CAMPUS`, and to one
sixteenth of the protocol budget rounded up when the accepted tier is one of the partner
classes; that amount is added to `reserved_cents`, and `is_budget_saturated` is recomputed. The
accepted screen also advances the protocol's version.

A declined screen is the same call with a different outcome. When at least one eligibility,
capacity, or budget check fails, the referral moves to `DECLINED`, `decline_occurred_at` is
stamped from the logical clock, and `decline_reason` records the first failed check in the
screen's priority order above — `ELIGIBILITY_AGE`, `ELIGIBILITY_DISEASE`, `ELIGIBILITY_STAGE`,
`CAPACITY_FULL`, or `BUDGET_INSUFFICIENT`. A budget failure records no accrual on the protocol at
all, and a declined referral books no reservation; `reservation_basis_cents` is left at zero and
`reserved_cents` untouched. `reopened_referral_id` stays null on a first-generation row.

A family that is declined is not turned away permanently. Re-opening is a submission rather than
a mutation: the `IntakeCoordinator` posts a new referral whose `reopen_source_referral_id` names
a referral currently in `DECLINED` status — naming anything else, or naming nothing in a
re-open attempt, is refused with `ERR_REFERRAL_NOT_DECLINED` (HTTP 409). Every screen
precondition that governs the `SUBMITTED`-to-`ACCEPTED` transition is then evaluated against the
successor directly, and if all of them hold the successor is created already `ACCEPTED` with its
own `applied_tier` and its own reservation; the source row is left exactly as it was, still
`DECLINED`, and the new row carries `reopened_referral_id` pointing back at it. A read of the
source referral's reopens collection lists the successors.

Withdrawal is available to the coordinator while the referral is `SUBMITTED`, `ACCEPTED`, or
`ARRIVED`, and the operation is fussy about which state it is in for reasons that matter to the
ledger. A withdrawal from `SUBMITTED` simply moves the row to `WITHDRAWN` with a
`withdrawal_reason` recorded and nothing else to unwind. A withdrawal from `ACCEPTED` moves the
row to `WITHDRAWN` and releases the reservation: `reserved_cents` is reduced by the referral's
`reservation_basis_cents` and `reservation_basis_cents` is reset to zero, with
`is_budget_saturated` recomputed and the protocol's version advanced; `decline_occurred_at` is
left null because the family withdrew rather than being refused. A withdrawal from `ARRIVED` is
the heaviest: it is refused with `ERR_ENROLLMENT_ACTIVE` (HTTP 409) while any enrollment on the
referral is in `ACTIVE_TREATMENT` or `SURVIVORSHIP`, and when it does proceed it cascades —
the enrollment on that referral moves to `WITHDRAWN`, every `HousingAssignment` on the
enrollment is `CANCELLED`, every `FamilySupportPledge` on it is `VOIDED`, and the protocol's
`enrolled_count` is decremented if the enrollment had reached `ENROLLED`. The reservation is
released exactly as in the accepted case. Any withdrawal from a state that is not one of the
three reports `ERR_REFERRAL_NOT_SUBMITTED`.

### 3.3. Arrival, Consent and Assent

Arriving a referral is the act that creates the patient's clinical record. It requires the
referral to be `ACCEPTED` — otherwise `ERR_REFERRAL_NOT_ACCEPTED` (HTTP 409) — and the target
protocol to be `OPEN` and not held, otherwise `ERR_PROTOCOL_NOT_OPEN` (HTTP 409). The request
must carry `expected_referral_version` equal to the referral's current `version`, or it is
refused with `ERR_STALE_VERSION` (HTTP 412). On success the referral moves to `ARRIVED`, its
version advances, and an `Enrollment` row is created for it in `PENDING_CONSENT` status. The
new enrollment's `assent_state` is set to `PENDING` when the child's assent is required and to
`NOT_REQUIRED` when it is not, where `is_assent_required` is true exactly when the child's
`computed_age_years` is at least the protocol's `mental_capacity_floor` and below 18. `ARRIVED`
is the state that opens clinical protocol enrollment, and the referral's `enrollment_id` is set
to the row just created.

The enrollment drives the consent paperwork. A `consent_signer` of `GUARDIAN` or
`GUARDIAN_AND_CHILD` states who must sign the packet, and the required signer depends on the
child's age: a signing operation whose `consent_signer` does not match the signer the child's
age demands is refused with `ERR_INVALID_CONSENT_SIGNER` (HTTP 422). The signing operation
accepts a `guardian_consent_signature_code` and an optional `child_assent_signature_code`. It
stamps `guardian_consent_signed_at`, and when the child's signature code is supplied it moves
`assent_state` to `OBTAINED` and stamps `child_assent_signed_at`; when the code is omitted the
assent state is left as it was. The operation requires the enrollment to still be in
`PENDING_CONSENT`, reporting `ERR_ENROLLMENT_NOT_PENDING_CONSENT` (HTTP 409) otherwise.

Enrollment completion has more gates than the signing itself. Assent must not still be `PENDING`
— a completion attempted while the child's assent is outstanding is refused with
`ERR_ASSENT_NOT_OBTAINED` (HTTP 409). The host protocol must be `OPEN` and not held, and while a
review lock is up the completion is refused specifically with `ERR_ARM_ASSENT_BLOCKED_BY_HOLD`
(HTTP 409). Every traveler holding a `GUARDIAN`-type coverage placed by this referral must appear
in the referral's `one_to_one_care_capability_codes`, and a coverage holder who was not cleared
for one-to-one care is refused with `ERR_ONE_TO_ONE_CARE_NOT_ELIGIBLE` (HTTP 422). Finally the
protocol's `enrolled_count` must still be strictly below its `capacity`, or completion fails
with `ERR_PROTOCOL_CAPACITY_EXCEEDED` (HTTP 409). When all gates pass, the enrollment moves to
`ENROLLED`, the protocol's `enrolled_count` is incremented, the referral's reservation is
released by subtracting `reservation_basis_cents` from `reserved_cents` and resetting the basis
to zero, `is_budget_saturated` is recomputed, and the protocol's version advances.

There is a second door into `ENROLLED` for children whose own assent is the deciding signature.
An `IRBReviewer` — not an intake coordinator — may record the child's own assent directly with a
`child_assent_signature_code`, which moves `assent_state` to `OBTAINED`, stamps
`child_assent_signed_at`, and advances the enrollment's version. This operation requires the
enrollment to be in `PENDING_CONSENT` (`ERR_ENROLLMENT_NOT_PENDING_CONSENT` otherwise) and the
host protocol to be `OPEN` and unheld (`ERR_ARM_ASSENT_BLOCKED_BY_HOLD` otherwise). It exists
precisely for the case where the enrollment is otherwise blocked, and it does not itself move
the enrollment to `ENROLLED`.

### 3.4. Housing: Assigning, Activating, Re-booking and Vacating

The tier a family is entitled to comes from the accepted screen, and the booking records it.
A `HousingCoordinator` books an assignment by supplying the `enrollment_id`, a `start_at`, an
`end_at`, and an optional `buffer_window_days`; the window must have `start_at` strictly before
`end_at` or the request is rejected as malformed with `ERR_INVALID_REQUEST` (HTTP 400). The
booking runs the selector to choose the facility, sets `housing_facility_id` and `assigned_tier`
from that choice — `assigned_tier` must equal the referral's `applied_tier` — looks up
`nightly_rate_cents` from the tier rate card, and computes `housing_cost_cents`. It starts in
`SCHEDULED` status. The overnight charge is the number of whole days between `start_at` and
`end_at`, clamped to at most 180 nights per booking, multiplied by the tier's nightly rate of
19000 cents for `ON_CAMPUS`, 15000 for `PARTNER_CLASS_A`, 13000 for `PARTNER_CLASS_B`, or 11000
for `PARTNER_CLASS_C`. Because the clamp is per booking, a 900-night window and a 180-night
window at the same tier cost exactly the same, and a family whose course runs longer than 180
nights is re-booked for the remainder. `billed_nights` reports the inclusive night count of the
window and `is_active_occupancy` is true while `start_at` is at or before the logical clock and
the logical clock is before `end_at`.

The occupancy and immunosuppression gates apply at booking, at re-booking, and again at
activation. Capacity is the two-endpoint test of §2.6, refused with
`ERR_HOUSING_CAPACITY_EXCEEDED`. Immunosuppression is a two-part gate: a booking whose referral
has `is_immunosuppressed` true may only target a facility with `immunosuppression_capable` true,
and a referral carrying `has_febrile_neutropenia_risk` true may only be housed at `ON_CAMPUS`;
both failures report `ERR_HOUSING_IMMUNOSUPPRESSION_INCOMPATIBLE` (HTTP 422). The step-down gate
is the mirror image and is checked on re-booking: a family may not be moved out of `ON_CAMPUS`
until its immunosuppression status has been cleared, or the re-booking reports
`ERR_STEP_DOWN_NOT_PERMITTED` (HTTP 422). A re-booking replaces the window, recomputes
`housing_cost_cents`, re-runs both gates, and advances the enrollment's version by one.

Activation is where scheduling becomes occupancy. The assignment must still be `SCHEDULED`, or
the attempt reports `ERR_HOUSING_ASSIGNMENT_NOT_SCHEDULED` (HTTP 409); `start_at` must not be
later than the logical clock, or it reports `ERR_OCCUPANCY_NOT_STARTED` (HTTP 409); the chosen
`HousingFacility` must be `OPEN`, or it reports `ERR_HOUSING_FACILITY_UNAVAILABLE` (HTTP 409);
and the two-endpoint capacity test must hold, reporting `ERR_HOUSING_CAPACITY_EXCEEDED`. On
success the assignment becomes `ACTIVE` with `is_active_occupancy` true, and the facility's
`active_beds_committed` is recomputed as the highest number of occupancies that coincide at any
instant across the window. A scheduled assignment that never happens is `CANCELLED`, which
requires `SCHEDULED` status and moves the row to `CANCELLED` without touching the ledger.

Vacating ends an occupancy and is the point at which the family's accruals are booked. It
requires the assignment to be `ACTIVE` (`ERR_HOUSING_ASSIGNMENT_NOT_ACTIVE`, HTTP 409) and a
`vacated_reason` that is one of `TREATMENT_COMPLETE`, `TRANSFERRED_AFFILIATE`, or `RELOCATED` —
anything else reports `ERR_INVALID_VACATE_REASON` (HTTP 422), though the three permitted reasons
are exactly the ones that book an accrual. On vacation the assignment becomes `VACATED` with
`is_active_occupancy` false, `HousingFacility.active_beds_committed` is recomputed from the
assignments still `SCHEDULED` or `ACTIVE`, and the enrollment's sibling session counter resets.
The reason then decides what else happens: a `TREATMENT_COMPLETE` vacation recomputes the
enrollment's pledge `final_settled_cents`, and a `TRANSFERRED_AFFILIATE` vacation bookmarks the
family for the affiliate coordination workflow of §3.7 so that care can continue closer to home.

Facilities themselves move through `OPEN`, `SUSPENDED`, and `CLOSED`. A `HousingCoordinator`
registers one with a `facility_code` unique across the program, a `name`, a `tier`, a `total_beds`
count greater than zero and an optional `buffer_beds` count, and it is born `OPEN` with the four
capability flags derived per §2.6. Unique collisions report `ERR_DUPLICATE_ENTITY`. A facility
is taken out of the selector pool temporarily by suspending it with a `suspension_reason`, taken
out permanently by closing it with a `closure_reason`, and returned to service by reopening
it — the reopen path exists so a suspension is reversible while a closure is not.

### 3.5. Family-Support Pledges and the Settlement Mathematics

A pledge is the family's support agreement, and it opens against an enrollment. A
`PatientSupportOfficer` creates one by naming the `enrollment_id` and a
`patient_support_budget_cents`. The pledge is born `ACTIVE` with `covered_days` initialized from
the housing nights the enrollment has already accrued, `provisional_settled_cents` and
`final_settled_cents` at zero, and `billing_permitted_cents` at zero. Crucially, creating a
pledge leaves the protocol's `reserved_cents` untouched — pledges ride on the family-support
ledger, not on the protocol reservation — and `ClinicalProtocol.committed_cents` is recomputed
from the pledge's enrollment window as days accrue.

Days accrue in whole units. The accrual operation takes a `days` count that must be at least 1,
reporting `ERR_INVALID_REQUEST` (HTTP 400) when it is not, and requires the pledge to still be
`ACTIVE`, reporting `ERR_PLEDGE_SETTLE_NOT_ACTIVE` (HTTP 409) otherwise. Each accrual adds the
days to `covered_days` and recomputes `provisional_settled_cents` as the accrued days multiplied
by 450 cents — the starter per-family-day rate that applies before the family's home state is
resolved. The accrual is also where the family-support budget ceiling is enforced: a charge that
exceeds the household's `patient_support_budget_cents` plus its insurance coverage is refused
with `ERR_SUPPORT_BUDGET_EXCEEDED` (HTTP 402), and an accrual that would raise a billable amount
from anywhere other than the permitted excess line is refused with `ERR_BILLING_NOT_PERMITTED`
(HTTP 409).

Settlement is the day the numbers become final, and it is only available once the family's
treatment phase has wound down. The pledge must be `ACTIVE`, or the attempt reports
`ERR_PLEDGE_SETTLE_NOT_ACTIVE`, and the pledge's enrollment must be in `WITHDRAWN`,
`COMPLETED`, `ON_HIATUS`, or `SURVIVORSHIP` — a pledge whose enrollment is still in live
treatment cannot settle and reports `ERR_PLEDGE_SETTLE_ENROLLMENT_ACTIVE` (HTTP 409). Settlement
resolves the per-traveler-day rate from the family's `household_state_code`: a family from
`TX`, `OK`, `AR`, `MS`, `AL`, `LA`, `TN`, `MO`, or `KY` resolves to 15000 cents per day; a
family from `CA`, `NY`, `IL`, `WA`, `MA`, `NJ`, `CT`, `OR`, or `MD` resolves to 22000 cents per
day; every other state resolves to 18000 cents per day. `final_settled_cents` is then the
accrued `covered_days` multiplied by that resolved rate, with the product rounded half up to the
cent. `billing_permitted_cents` is computed by the pinned waterfall of §2.7: cover the final
charge from the budget first, then from the insurance coverage on the remainder, and the
residue, floored at zero, is what may be billed. The settlement then debits the family-support
pool by subtracting `final_settled_cents` from `ResearchFund.patient_support_balance_cents`, and
the pledge moves to `SETTLED_FINAL`.

Voiding is the other terminal path, and it is guarded by the family's actual housing. A pledge
may only be voided while no `HousingAssignment` for its enrollment is in `ACTIVE` status —
a family still occupying a residence reports `ERR_HOUSING_OCCUPANCY_ACTIVE` (HTTP 409). A void
requires the pledge to be `ACTIVE` (`ERR_PLEDGE_SETTLE_NOT_ACTIVE`), moves it to `VOIDED`, and
adjusts the protocol's `reserved_cents` by reversing this pledge's reservation, advancing the
protocol's version by one.

Pledges are also settled automatically, without a settlement request. The enrollment's own
lifecycle settles them: a hiatus settles the current pledge, treatment completion settles the
current pledge, and a vacation with the reason `TREATMENT_COMPLETE` recomputes
`final_settled_cents`. A resume after a hiatus creates a fresh `ACTIVE` pledge for the
continuing course rather than reviving the settled one.

### 3.6. Travel Legs, Coverage Windows and the No-Double-Charge Rule

Travel is arranged leg by leg, each leg recorded as a `TravelArrangement`. A `PatientSupportOfficer` requests one against an enrollment by
supplying the `mode`, the `traveler_count`, a `departure_at`, an optional `return_at`, a
`trip_reason`, an optional `is_required_travel` flag, and an optional `placed_coverages` array.
The mode is one of `AIR_ECONOMY`, `AIR_MEDICAL`, `GROUND`, or `RAIL`. A leg whose family is
already housed by an `ACTIVE` housing assignment must use `GROUND`, so that a family sleeping in
program housing is never double-charged for air travel on top of the occupancy charge. The
`traveler_count` must be between 2 and 6 inclusive, because a leg always carries the patient
plus at least one caregiver; a count outside that band is refused with `ERR_TRAVELER_COUNT_RANGE`
(HTTP 422). The `trip_reason` is `PROTOCOL_REVIEW`, `THERAPY_ADMINISTRATION`,
`SURVIVORSHIP_VISIT`, or `FAMILY_REQUEST`, and a trip is required travel when its
`trip_reason` is a protocol review, a therapy administration, or a survivorship visit. Each
element of `placed_coverages` carries a `plan_code`, a `coverage_id` that may be null, a
`travel_window_start_at`, a `travel_window_end_at`, an integer `coverage_cents`, and a
`covers_required_travel` boolean. A requested leg starts in `REQUESTED` with `family_day_units`
and `transport_cost_cents` already computed.

Confirmation is where eligibility is stamped, and the leg's clock starts ticking there. The leg
must be `REQUESTED`, or the attempt reports `ERR_TRAVEL_NOT_REQUESTED` (HTTP 409); the
`traveler_count` is re-checked against the 2-to-6 band, reporting `ERR_TRAVELER_COUNT_RANGE`;
the target enrollment's protocol must be `OPEN` and unheld, and if it is not the confirmation
fails with `ERR_TRAVEL_ELIGIBILITY_NOT_CONFIRMED` (HTTP 409); and no already-confirmed leg for
the same enrollment and the same mode may have a travel window that collides on the arrival
boundary, which reports `ERR_TRAVEL_LEG_OVERLAP` (HTTP 409). On success the leg becomes
`CONFIRMED` and `eligibility_confirmed_at` is stamped from the logical clock. That stamp is a
perishable token: a confirmation is only good for 30 days, and a disbursement attempted once the
logical clock has moved to or past `eligibility_confirmed_at` plus 30 days is refused with
`ERR_TRAVEL_COVERAGE_EXPIRED` (HTTP 409).

Disbursement converts the leg into money owed to the family and money spent from the fund. The
leg must be `CONFIRMED` (`ERR_TRAVEL_NOT_CONFIRMED`, HTTP 409); the eligibility stamp must still
be live per the 30-day rule; `family_day_units` must be at least 1 or the request is malformed
with `ERR_INVALID_REQUEST`; and no confirmed or disbursed leg for the same enrollment and mode
may overlap this leg's window by a day or more, which reports `ERR_TRAVEL_LEG_OVERLAP`. The
`family_day_units` figure is the traveler count multiplied by the billed days between
`departure_at` and `return_at` with both boundaries exclusive and a floor of one day; when the
referral declares `one_to_one_care_capability_codes`, the multiplier counts only the travelers
cleared for one-to-one care rather than the whole party. `transport_cost_cents` is then
`family_day_units` multiplied by the same resolved per-traveler-day rate the family's home state
produced in §3.5 — 15000 cents for a household in the near set, 22000 for a household in the far
set, 18000 otherwise. Disbursement subtracts that cost from
`ResearchFund.patient_support_balance_cents`, increases the enrollment's pledge `covered_days` by
the leg's billed days, and advances the protocol's `committed_cents` by the family-research-day
charge for the leg, which is the same resolved per-traveler-day rate. When the disbursed leg is a
`TRAVEL`-mode leg on a protocol that currently carries a non-operational review lock, the
protocol also credits research: `ResearchFund.research_balance_cents` is increased by seven and a
half percent of the leg's `transport_cost_cents`, rounded up to the whole cent. The leg ends
`DISBURSED`.

A disbursement can be undone, and the reversal is complete rather than partial. The reversal
takes a `reversal_reason`, refunds `ResearchFund.patient_support_balance_cents` by the leg's
`transport_cost_cents`, reduces the protocol's `committed_cents` by the leg's research-day
accrual, reduces the enrollment's pledge `covered_days` by the leg's billed days, resets
`transport_cost_cents` to zero, advances the protocol's version, and ends the leg at
`CANCELLED`. A plain cancellation is lighter: it is available while the leg is `REQUESTED` or
`CONFIRMED` — anything else reports `ERR_TRAVEL_NOT_CANCELLABLE` (HTTP 409) — moves the leg to
`CANCELLED`, and, for a leg that had already stamped `eligibility_confirmed_at`, reverses no fee.

Two reads frame the travel picture. A leg exposes `fund_patient_support_balance_cents` and
`fund_research_balance_cents` reflecting the fund after the leg was last disbursed or reversed.
The enrollment-level travel summary reports the accumulated historical charge rather than any
single leg: it gathers every leg for the enrollment whose status is `CONFIRMED` or `DISBURSED`,
orders them chronologically by `departure_at` with ties broken by `created_at` ascending, and
attaches to each leg the most recent placed coverage whose travel window contains that leg's
`departure_at` — where several qualify, the one with the highest `coverage_cents` wins, ties
again broken by earliest `created_at`. A leg is chargeable when the attached coverage's
`covers_required_travel` is true, or otherwise when the leg's `trip_reason` is itself a required
travel reason. The summary's `accumulated_family_day_charge_cents` is the sum, over just the
chargeable legs, of each leg's `family_day_units` multiplied by its resolved per-traveler-day
rate, and `chargeable_leg_count` reports how many legs qualified. Legs in `REQUESTED` or
`CANCELLED` status are excluded from the summary entirely, and because the accumulation is
order-sensitive, re-costing the same set of legs in a different order can legitimately produce a
different total.

### 3.7. Milestones and Care Delivered Closer to Home

A protocol course is a sequence of checkpoints, each recorded as a `ProtocolMilestone`. Each milestone carries a `milestone_sequence`
ordinal, a `description`, a `requires_main_campus` flag, a `target_at` instant, and a `status`
of `PENDING`, `DUE`, `EXECUTED`, or `MISSED`. Promotion is automatic and strictly ordered: a
`PENDING` milestone becomes `DUE` only when it holds the lowest `milestone_sequence` among the
enrollment's milestones that have not been executed and the immediately preceding milestone of
the same enrollment, when one exists, is already `EXECUTED` — a promotion attempted out of turn
is refused with `ERR_PRIOR_MILESTONE_NOT_EXECUTED` (HTTP 409). A promotion is not a deferral, so
`deferred_from_milestone_id` is left null. Starting treatment promotes the enrollment's earliest
scheduled milestone to `DUE` as a side effect of beginning the course, and executing a milestone
promotes the next `PENDING` one.

Missed milestones are enforced by the clock rather than by a caller. A milestone still `PENDING`
whose `target_at` has passed the logical clock becomes `MISSED`, and a milestone in `DUE` whose
`target_at` has passed does the same — and a `DUE` milestone missed this way blocks treatment
completion until a replacement milestone is registered.

Deferral is the mechanism that moves a visit out of the main campus and closer to the family's
home. An `AffiliateClinicCoordinator` defers a milestone by naming an `affiliate_clinic_id`, and
the operation is heavily gated. The milestone must be `DUE` (`ERR_MILESTONE_NOT_DUE`, HTTP 409);
an `ACTIVE` affiliation agreement must cover that protocol at the requested affiliate
(`ERR_NO_ACTIVE_AFFILIATION_AGREEMENT`, HTTP 409); the requested clinic must have `is_active`
true and its `state_code` must be within one state of the family's `household_state_code`
(`ERR_AFFILIATE_NOT_ADJACENT`, HTTP 422); `requires_main_campus` must be false, since a
main-campus-only milestone cannot be deferred at all (`ERR_MILESTONE_REQUIRES_MAIN_CAMPUS`,
HTTP 422); and the visit must be near enough to schedule, because a `target_at` more than 14 days
after the logical clock reports `ERR_VISIT_WINDOW_TOO_DISTANT` (HTTP 409). A successful deferral
leaves the milestone `DUE` but records `deferred_from_milestone_id` as the enrollment's
immediately preceding milestone, sets `affiliate_clinic_id` to the coordinating site, and raises
a referral intent for that affiliate on the family's behalf. A read of an affiliate's milestones
lists the visits deferred to it, and the milestone collection can be filtered by enrollment, by
affiliate, or by the milestone a deferral latched onto.

Execution closes the checkpoint. The milestone must be `DUE` or the attempt reports
`ERR_MILESTONE_NOT_DUE`, and the host protocol must be `OPEN` and unheld or it reports
`ERR_PROTOCOL_NOT_OPEN` (HTTP 409). Executing stamps `executed_at`, moves the milestone to
`EXECUTED`, and promotes the enrollment's next `PENDING` milestone to `DUE`. For a `TRAVEL`-mode
leg covering the visit, the fund research accrual booked for that visit still holds after
execution.

`AffiliationAgreement` records are what give an affiliate the standing to do any of this. An
`AffiliateClinicCoordinator` registers an `AffiliateClinic` with a `clinic_code` unique across the program, a
`name`, a `state_code`, and an optional `is_active` flag defaulting to true; a collision reports
`ERR_DUPLICATE_ENTITY`. The coordinator then pins a protocol to the site by supplying a
`protocol_id`, a `protocol_version` string that records exactly which revision of the protocol
the site is permitted to execute, and an `effective_start_at`. A pin carries the affiliate as
its `clinic_id` and is created `PENDING` and
records `is_cross_state`, which is true exactly when the affiliate's `state_code` differs from
the referring family's `household_state_code`. Activation requires the agreement to be `PENDING`
(`ERR_INVALID_STATE`, HTTP 409), the referenced clinic to have `is_active` true
(`ERR_INVALID_REQUEST`, HTTP 400), and the referenced protocol to exist (`ERR_PROTOCOL_NOT_FOUND`,
HTTP 404); once active, the site may receive deferred milestones for that protocol. Suspension
requires `ACTIVE` status and stops the site receiving new deferrals without ending the
relationship. Termination requires the agreement to be `ACTIVE` or `SUSPENDED` — an agreement
already `TERMINATED` reports `ERR_INVALID_STATE` — and ends it for good; it takes a
`termination_reason` recording why the site lost its standing. A read of an affiliate's protocols
lists the agreements that pin protocols at it, and the program-wide agreement collection can be
filtered by `protocol_id`, by `clinic_id`, or by `status`.

### 3.8. Treatment Transitions, Hiatus and Survivorship Enrollment

Active treatment begins once the patient is actually housed: starting treatment requires the
enrollment to be `ENROLLED` (`ERR_ENROLLMENT_NOT_ENROLLED`, HTTP 409) and at least one
`HousingAssignment` for that enrollment to be `ACTIVE`, since a patient with nowhere to stay
reports `ERR_NO_ACTIVE_HOUSING` (HTTP 409). Success moves the enrollment to `ACTIVE_TREATMENT`
and promotes its earliest `SCHEDULED` milestone to `DUE`.

A family that returns home between protocol milestones does so through a hiatus. Pausing
requires the enrollment to be `ACTIVE_TREATMENT`, reporting
`ERR_ENROLLMENT_NOT_ACTIVE_TREATMENT` otherwise, and requires that no milestone on the
enrollment is still `PENDING` or `DUE`, since outstanding work reports
`ERR_MILESTONES_OUTSTANDING` (HTTP 409). The hiatus operation takes a `hiatus_reason` and does
three things: it moves the enrollment to `ON_HIATUS`, it vacates the active housing assignment
with `vacated_reason` of `TRANSFERRED_AFFILIATE`, and it settles the current family-support
pledge so the family's support is closed out for the period. A second, narrower hiatus path
exists for a family that never reached active treatment: an enrollment still in `PENDING_CONSENT`
may be moved to `ON_HIATUS`, retaining its hospital housing and settling its pledge on transfer.
Resuming requires the enrollment to be `ON_HIATUS` (`ERR_ENROLLMENT_NOT_ON_HIATUS`, HTTP 409)
and the host protocol to be `OPEN` and unheld (`ERR_ARM_ASSENT_BLOCKED_BY_HOLD` when a review
lock is up); it returns the enrollment to `ACTIVE_TREATMENT` and creates a fresh `ACTIVE` pledge
for the resumed course.

Completing treatment graduates the patient into follow-up, and the gates reflect that. The
enrollment must be `ACTIVE_TREATMENT`, or the attempt reports
`ERR_ENROLLMENT_NOT_ACTIVE_TREATMENT`; no milestone may be `DUE` or `MISSED`, since either
reports `ERR_MILESTONES_OUTSTANDING`; and an `ACTIVE` `SurvivorshipStudy` must already exist on
the enrollment's protocol, or the attempt reports `ERR_NO_ACTIVE_SURVIVORSHIP_STUDY` (HTTP 409).
Success moves the enrollment to `SURVIVORSHIP`, decrements the protocol's `enrolled_count`,
creates a `SurvivorshipEnrollment` in `ON_STUDY` status with `completed_treatment_at` stamped
from the logical clock, completes every sibling support service on that enrollment, and settles
the current pledge.

Follow-up study enrollment can also happen directly. A `SurvivorshipCoordinator` creates a study
on a protocol by supplying a `study_code` unique within that protocol, a
`follow_up_interval_months` greater than zero, and a `min_years_after_completion` greater than
zero; the study is born `ACTIVE`, and only an `ACTIVE` study accepts enrollments. A study that is
not `ACTIVE` refuses both follow-up graduation and new enrollments with
`ERR_STUDY_NOT_ACTIVE` (HTTP 409). A survivor is
enrolled into a study by naming the `enrollment_id` and a `completed_treatment_at`, which is
the instant follow-up windows are counted from; the row is created `ON_STUDY`, bound to its study
through `study_id` and to the survivor through `enrollment_id`, with
`adult_transition_age_years` of 18 and `next_due_at` computed as `completed_treatment_at` plus
the number of visits already done times `follow_up_interval_months`. `is_adult_follow_up` is
true when `completed_treatment_at` plus 18 years is at or before the logical clock, marking the
point where the survivor's care transfers to the adult clinic.

Visits are logged one at a time. Logging a follow-up takes a `completed_at` and appends a
`SurvivorshipFollowUp` in `LOGGED` status — every appended visit is `LOGGED` — belonging to its
follow-up course through `survivorship_enrollment_id`, advances
`next_due_at` by exactly one interval, and moves the survivorship enrollment to `GRADUATED` when
the terminal visit is reached. The interval discipline is enforced: windows must advance by
exactly one interval per logged visit and no visit may be logged before the previous one, and a
violation reports `ERR_FOLLOW_UP_WINDOW_VIOLATION` (HTTP 409). Graduation is otherwise automatic
once the study has been `ACTIVE` and `completed_treatment_at` plus the number of visits times
`follow_up_interval_months` has reached the logical clock. A survivor may instead be withdrawn
from follow-up, which requires `ON_STUDY` status or reports
`ERR_SURVIVORSHIP_NOT_ON_STUDY` (HTTP 409) and moves the row to `WITHDRAWN`. When the patient's
enrollment has moved into `SURVIVORSHIP`, closing it entirely requires every survivorship
enrollment on that patient to be `GRADUATED`, or the attempt reports
`ERR_SURVIVORSHIP_NOT_GRADUATED` (HTTP 409); an enrollment that is not in `SURVIVORSHIP` at all
reports `ERR_ENROLLMENT_NOT_IN_SURVIVORSHIP` (HTTP 409) instead. The closure moves the enrollment
to `COMPLETED`.

### 3.9. Protocol Holds, Review Locks and the Freeze Cascade

When the institution must stop admitting families to a protocol, an `IRBReviewer` raises a hold.
The hold is recorded with a `hold_reason` of `IRB_REVIEW`, `SAFETY_SIGNAL`, `FUNDING_REVIEW`, or
`SPONSOR_AUDIT`, and an `initiated_at` instant, and it is born `ACTIVE` with `released_at` null
and `protocol_version` recording the host protocol's version at the moment of creation. Raising
a hold is not a passive flag: the protocol moves to `HELD` with its `is_protocol_held` flag set
true, the protocol's version advances by one, and — the part that surprises people — every
referral on that protocol currently in `ACCEPTED` status reverts to `SUBMITTED` with its
`applied_tier` reset to `PENDING`. That revert is unconditional on acceptance and costs nothing:
those reverts charge no screening fee and advance no budget. It does release money, though:
each reverted referral has its `reservation_basis_cents` subtracted from the protocol's
`reserved_cents` and then reset to zero, and `is_budget_saturated` is recomputed. An accepted
screen is therefore not a durable claim on a bed or a budget while a hold is in the air.

Releasing a hold is the `ProtocolCoordinator`'s counter-move, and it is available only while the
host protocol is actually `HELD` — releasing against a protocol that is not held reports
`ERR_PROTOCOL_NOT_HELD` (HTTP 409) — and only for a hold in `ACTIVE` status, since anything else
reports `ERR_HOLD_NOT_ACTIVE` (HTTP 409). A successful release stamps `released_at` from the
logical clock and refreshes the hold's recorded `protocol_version` to the host protocol's current
version. The protocol's `is_protocol_held` flag is set false, and the protocol returns to `OPEN`
only if no other `ACTIVE` hold remains on it; while one does, the protocol stays frozen and a
second release attempt reports `ERR_PROTOCOL_HOLD_ACTIVE` (HTTP 409).

Escalation is the `IRBReviewer`'s heavier instrument. Escalating requires the hold to be
`ACTIVE` (`ERR_HOLD_NOT_ACTIVE`) and its `hold_reason` to be `IRB_REVIEW` — any other reason
reports `ERR_HOLD_NOT_IRB_REVIEW` (HTTP 409). The hold moves to `ESCALATED`, its recorded
`protocol_version` is refreshed, and `is_review_lock` becomes true for it, since that attribute
is true exactly when the reason is `IRB_REVIEW` and the status is `ESCALATED`. The host
protocol's `is_protocol_held` stays true, and the protocol now blocks arm-assent confirmation and
enrollment completion until the hold is released.

What the freeze blocks is uniform and worth stating in one place. While a protocol is frozen —
by any `ACTIVE` hold or by a `ESCALATED` review lock — the screening of referrals, the arrival of
accepted referrals, consent signing, arm-assent recording, milestone deferral and milestone
execution all fail, reporting `ERR_PROTOCOL_HELD` (HTTP 409), while the two consent-adjacent
operations report the more specific `ERR_ARM_ASSENT_BLOCKED_BY_HOLD` (HTTP 409). Resume from
hiatus is caught by the same gate. Holds are readable at three levels: a protocol's own holds
collection, a program-wide holds collection filterable by `protocol_id` and by `status`, and a
single hold by its identifier. A hold's `status` moves through `ACTIVE`, `RELEASED`, and
`ESCALATED`, with `RELEASED` and `ESCALATED` both terminal for the hold record itself, whether or
not the protocol behind it has been released.

### 3.10. Family Support Services, Sibling Programming and Operational Tooling

Meals, sibling care, comfort items and the other wraparound lines are catalogued as
`FamilySupportService` rows under a fund. A `PatientSupportOfficer` creates one with the
`fund_id` that will carry it, a `service_code` that must be unique within that fund and must be
one of `TRAVEL`, `HOUSING`, `MEALS`, `SIBLING_CARE`, or `COMFORT_ITEM`, a `display_name`, a
`base_allowance_cents` per-family baseline, and optionally `is_stimulation_eligible`,
`stimulation_rate`, and `stimulation_cap_cents`. The stimulation rate is a number between 0 and
1 inclusive. A duplicate `service_code` within the fund reports `ERR_DUPLICATE_ENTITY`. Creating
a service line also creates its `FamilyServiceLedger` with status `ACTIVE`, a `ledger_epoch` of
zero and zero `accumulated_cents`; the ledger knows its service line through
`family_support_service_id`.

Accruing an allowance into a service ledger is where the charitable-stimulation markup is
applied. The operation takes a `family_count` and an optional `ledger_epoch`. The allowance
itself is the service line's `base_allowance_cents` multiplied by the family count, and the
stimulation markup is the base allowance multiplied by the service's `stimulation_rate`,
rounded half up to the cent, capped at the service's `stimulation_cap_cents`. The markup is
contributed only when two conditions hold together: the service is `is_stimulation_eligible` and
the ledger's status is `ACTIVE`. When it does apply, `ResearchFund.research_balance_cents` is
increased by the markup, and in every case `ResearchFund.patient_support_balance_cents` is
reduced by the allowance. The ledger's `accumulated_cents` is updated, and the response reports
`allowance_cents`, `markup_cents`, `family_service_ledger_id`, `service_ledger_status`,
`ledger_accumulated_cents`, and the resulting `fund_research_balance_cents`.

The ledger epoch is a cheap staleness guard on this flow. When the request supplies a
`ledger_epoch`, it must equal the ledger's current `ledger_epoch`, or the accrual is refused
with `ERR_STALE_LEDGER_EPOCH` (HTTP 409). A `PatientSupportOfficer` can freeze a ledger, which
moves it to `FROZEN` and pauses markup accrual on it, and a program-wide operations checkpoint
exists for test-driving: it advances every ledger's `ledger_epoch` to a supplied
`advance_to_epoch` and freezes every ledger whose `accumulated_cents` exceeds its service's
`stimulation_cap_cents`, reporting back the resulting `ledger_epoch` and a
`frozen_ledger_count`. The logical clock itself is set through a test-driving capability that
takes `current_utc`; the clock starts at 2026-09-01T00:00:00Z on server startup and the service
never falls back to real wall-clock time, so every age, occupancy and window computation in this
document is measured against the logical clock rather than the host's calendar.

Sibling support is programming rather than money, and it is counted rather than charged. A
`SiblingSupportService` is opened by a `PatientSupportOfficer` for a household, by naming the enrollment, a
`sibling_alias` that is unique within that enrollment, a `service_type` of `TUITION_STIPEND`,
`COUNSELING_SESSION`, `RECREATION_PROGRAM`, or `SIBLING_CAMP`, and an inclusive
`delivery_window_start_at` and exclusive `delivery_window_end_at`. The service is born `ACTIVE`
with `sessions_delivered` at zero, and opening it moves no ResearchFund balance — sibling
services are delivery counters, not allowances.

Sessions are delivered in batches. The delivery operation takes a `session_count`, adds it to
`sessions_delivered`, and recomputes `has_reached_monthly_limit`, which is true once
`sessions_delivered` has reached the window's session allowance. That allowance is 4 sessions
when the household's `household_state_code` is one of the near states `TX`, `OK`, `AR`, `MS`,
`AL`, `LA`, `TN`, `MO`, or `KY`, and 6 sessions otherwise; the boundary is inclusive at the
limit, so the fourth delivery for a near-state household and the sixth for any other household
reaches the cap exactly. The counter is cumulative within the window and resets to zero when the
enrollment's housing occupancy ends — that reset is driven by the housing vacation path in §3.4,
not by the sibling service itself. A service whose `has_reached_monthly_limit` is already true
may not accept further sessions until the counter resets, and such a delivery is refused with
`ERR_SIBLING_SESSION_LIMIT_REACHED` (HTTP 409). Any session, limit, completion or cancellation
operation on a service that is not `ACTIVE` reports `ERR_SIBLING_SERVICE_NOT_ACTIVE` (HTTP 409).

Sibling services end in one of two ways. Completion is automatic and is driven by the patient's
course: when the host enrollment reaches `SURVIVORSHIP`, every sibling service on it moves to
`COMPLETED`. Cancellation is explicit and available to the `PatientSupportOfficer` while the
service is `ACTIVE`, moving it to `CANCELLED`.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource, or that add a new, distinct resource to a
collection, return `201 Created`. Operations that modify an existing resource — status
transitions, settlements, donations, re-bookings, and the creation of a ledger or agreement that
is internal to an existing parent — return `200 OK`. The two test-driving capabilities that set
the logical clock and run the operations checkpoint also return `200 OK`. The table below lists
the endpoint surface only; every request body, side effect and precondition is specified in the
section 3 narratives, and a client should reconstruct the payload from those narratives rather
than from this table.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Test-driving endpoint: set the logical clock. The server's startup default is 2026-09-01T00:00:00Z and it never falls back to real wall-clock time. | PlatformAdmin |
| POST | `/programs/research-funds` | Create a donor-funded campaign | PlatformAdmin |
| GET | `/programs/research-funds` | List research funds | Any |
| GET | `/programs/research-funds/{id}` | Get a research fund | Any |
| POST | `/programs/research-funds/{id}/donations` | Record an additional donation and re-derive the fund split | PlatformAdmin |
| POST | `/programs/clinical-protocols` | Create a clinical protocol | ProtocolCoordinator |
| GET | `/programs/clinical-protocols` | List clinical protocols | Any |
| GET | `/programs/clinical-protocols/{id}` | Get a clinical protocol | Any |
| POST | `/programs/clinical-protocols/{id}/open` | Open a draft protocol for referrals | ProtocolCoordinator |
| POST | `/programs/clinical-protocols/{id}/close` | Close an open protocol | ProtocolCoordinator |
| POST | `/programs/clinical-protocols/{id}/release-hold` | Release the freeze on a held protocol | ProtocolCoordinator |
| GET | `/programs/clinical-protocols/{id}/funding-posture` | Read a protocol's live funding posture: its OCC version alongside the reservation, saturation and enrollment counters derived from the referral funnel | Any |
| GET | `/programs/clinical-protocols/{id}/referrals` | List referrals screened against this protocol | Any |
| GET | `/programs/clinical-protocols/{id}/studies` | List survivorship studies on this protocol | Any |
| GET | `/programs/research-funds/{id}/services` | List family-support service lines funded by this fund | Any |
| GET | `/programs/affiliate-clinics/{id}/protocols` | List protocols this affiliate is affiliated with, via its affiliation agreements | Any |
| GET | `/programs/clinical-protocols/{id}/holds` | List protocol holds | Any |
| POST | `/programs/clinical-protocols/{id}/holds` | Raise a hold, freezing the protocol and reverting accepted referrals | IRBReviewer |
| POST | `/programs/protocol-holds/{id}/release` | Release a hold | ProtocolCoordinator |
| POST | `/programs/protocol-holds/{id}/escalate` | Escalate an IRB-review hold into a review lock | IRBReviewer |
| GET | `/programs/protocol-holds` | List all protocol holds | Any |
| POST | `/programs/referrals` | Submit a referral, or re-open a declined referral by naming it as reopen_source_referral_id | IntakeCoordinator |
| GET | `/programs/referrals` | List referrals | Any |
| GET | `/programs/referrals/{id}` | Get a referral | Any |
| POST | `/programs/referrals/{id}/screen` | Screen a referral against its protocol, returning the acceptance or decline outcome | IntakeCoordinator |
| POST | `/programs/referrals/{id}/arrive` | Mark an accepted referral as arrived, creating the enrollment | IntakeCoordinator |
| POST | `/programs/referrals/{id}/withdraw` | Withdraw a referral | IntakeCoordinator |
| GET | `/programs/referrals/{id}/enrollments` | List enrollments created from this referral | Any |
| GET | `/programs/referrals/{id}/one-to-one-summary` | Return the one-to-one care eligibility record for this referral | Any |
| GET | `/programs/referrals/{id}/reopens` | List successor referrals that re-opened this declined referral | Any |
| POST | `/programs/housing-facilities` | Register a housing facility | HousingCoordinator |
| GET | `/programs/housing-facilities` | List housing facilities | Any |
| GET | `/programs/housing-facilities/{id}` | Get a housing facility, including its current committed beds | Any |
| GET | `/programs/housing-facilities/{id}/assignments` | List assignments placed at this facility | Any |
| POST | `/programs/housing-facilities/{id}/suspend` | Suspend a housing facility, removing it from the selector pool | HousingCoordinator |
| POST | `/programs/housing-facilities/{id}/close` | Close a housing facility permanently, removing it from the selector pool for good | HousingCoordinator |
| POST | `/programs/housing-facilities/{id}/reopen` | Return a suspended housing facility to service | HousingCoordinator |
| POST | `/programs/housing-assignments` | Book a housing assignment at the selector-chosen facility | HousingCoordinator |
| GET | `/programs/housing-assignments` | List housing assignments | Any |
| GET | `/programs/housing-assignments/{id}` | Get a housing assignment | Any |
| PUT | `/programs/housing-assignments/{id}` | Re-book a scheduled assignment to a different window, re-running capacity and step-down checks | HousingCoordinator |
| POST | `/programs/housing-assignments/{id}/activate` | Activate a scheduled occupancy | HousingCoordinator |
| POST | `/programs/housing-assignments/{id}/vacate` | Vacate an active occupancy | HousingCoordinator |
| POST | `/programs/housing-assignments/{id}/cancel` | Cancel a scheduled occupancy | HousingCoordinator |
| GET | `/programs/enrollments` | List enrollments. With no enrollment_status filter every enrollment is returned except those in WITHDRAWN status; an explicit enrollment_status=WITHDRAWN filter is the only way to surface withdrawn rows. | Any |
| GET | `/programs/enrollments/{id}` | Get an enrollment | Any |
| POST | `/programs/enrollments/{id}/sign-consent` | Record guardian consent and, where required, the child's own assent | IntakeCoordinator |
| POST | `/programs/enrollments/{id}/record-arm-assent` | Record the child's own assent as the deciding signature, used when the enrollment is otherwise blocked | IRBReviewer |
| POST | `/programs/enrollments/{id}/start-treatment` | Begin active treatment for an enrolled patient | IntakeCoordinator |
| POST | `/programs/enrollments/{id}/hiatus` | Pause treatment for an affiliate-based care period | IntakeCoordinator |
| POST | `/programs/enrollments/{id}/resume` | Resume treatment after a hiatus | IntakeCoordinator |
| POST | `/programs/enrollments/{id}/complete-treatment` | Complete treatment and open survivorship follow-up | IntakeCoordinator |
| POST | `/programs/enrollments/{id}/complete-follow-up` | Close the survivor's enrollment once every study is graduated | IntakeCoordinator |
| GET | `/programs/enrollments/{id}/pledges` | List family-support pledges for this enrollment | Any |
| GET | `/programs/enrollments/{id}/housing-assignments` | List housing assignments for this enrollment | Any |
| GET | `/programs/enrollments/{id}/travel-arrangements` | List travel legs for this enrollment | Any |
| GET | `/programs/enrollments/{id}/travel-summary` | Return the accumulated family-day charge computed by travel_accumulation_charge | Any |
| GET | `/programs/enrollments/{id}/milestones` | List the protocol milestones for this enrollment | Any |
| GET | `/programs/enrollments/{id}/survivorship-enrollments` | List survivorship study enrollments for this patient | Any |
| GET | `/programs/enrollments/{id}/sibling-services` | List sibling support services for this household | Any |
| POST | `/programs/enrollments/{id}/sibling-services` | Open a sibling support service line | PatientSupportOfficer |
| POST | `/programs/enrollments/{id}/milestones` | Register a protocol milestone for this enrollment | ProtocolCoordinator |
| POST | `/programs/enrollments/{id}/travel-arrangements` | Request a travel leg for this enrollment | PatientSupportOfficer |
| POST | `/programs/family-support-pledges` | Open a family-support pledge for an enrollment | PatientSupportOfficer |
| GET | `/programs/family-support-pledges` | List family-support pledges | Any |
| GET | `/programs/family-support-pledges/{id}` | Get a family-support pledge | Any |
| POST | `/programs/family-support-pledges/{id}/accrue` | Accrue family-support days on an active pledge | PatientSupportOfficer |
| POST | `/programs/family-support-pledges/{id}/settle` | Settle a pledge at its final per-traveler-day rate | PatientSupportOfficer |
| POST | `/programs/family-support-pledges/{id}/void` | Void an active pledge and release its protocol reservation | PatientSupportOfficer |
| GET | `/programs/travel-arrangements` | List travel legs | Any |
| GET | `/programs/travel-arrangements/{id}` | Get a travel leg | Any |
| POST | `/programs/travel-arrangements/{id}/confirm` | Confirm a requested travel leg and stamp its eligibility instant | PatientSupportOfficer |
| POST | `/programs/travel-arrangements/{id}/disburse` | Disburse a confirmed travel leg, booking the family-day and research-day charges | PatientSupportOfficer |
| POST | `/programs/travel-arrangements/{id}/reverse-disbursement` | Reverse a disbursed travel leg, refunding the family-support pool and releasing the research accrual | PatientSupportOfficer |
| POST | `/programs/travel-arrangements/{id}/cancel` | Cancel a requested or confirmed travel leg | PatientSupportOfficer |
| POST | `/programs/affiliate-clinics` | Register an affiliate clinic | AffiliateClinicCoordinator |
| GET | `/programs/affiliate-clinics` | List affiliate clinics | Any |
| GET | `/programs/affiliate-clinics/{id}` | Get an affiliate clinic | Any |
| POST | `/programs/affiliate-clinics/{id}/affiliations` | Pin a protocol version to an affiliate site | AffiliateClinicCoordinator |
| GET | `/programs/affiliate-clinics/{id}/affiliations` | List affiliations for this affiliate | Any |
| GET | `/programs/affiliations` | List affiliation agreements, optionally filtered by protocol | Any |
| POST | `/programs/affiliations/{id}/activate` | Activate an affiliation agreement | AffiliateClinicCoordinator |
| POST | `/programs/affiliations/{id}/terminate` | Terminate an affiliation agreement so the affiliate can no longer execute the protocol | AffiliateClinicCoordinator |
| POST | `/programs/affiliations/{id}/suspend` | Suspend an affiliation agreement | AffiliateClinicCoordinator |
| GET | `/programs/affiliate-clinics/{id}/milestones` | List milestones that were deferred to this affiliate clinic | Any |
| GET | `/programs/milestones/{id}` | Get a protocol milestone | Any |
| POST | `/programs/protocol-milestones/{id}/defer-visit` | Defer a pending milestone to an affiliate clinic closer to the family's home | AffiliateClinicCoordinator |
| POST | `/programs/protocol-milestones/{id}/execute` | Mark a due milestone executed | AffiliateClinicCoordinator |
| GET | `/programs/protocol-milestones` | List protocol milestones | Any |
| GET | `/programs/clinical-protocols/{id}/affiliations` | List affiliation agreements pinning this protocol at affiliate sites | Any |
| POST | `/programs/clinical-protocols/{id}/studies` | Create a survivorship follow-up study on a protocol | SurvivorshipCoordinator |
| GET | `/programs/survivorship-studies` | List survivorship studies | Any |
| POST | `/programs/survivorship-studies/{id}/enrollments` | Enroll a survivor into a follow-up study | SurvivorshipCoordinator |
| GET | `/programs/survivorship-studies/{id}/enrollments` | List enrollment courses on this study | Any |
| GET | `/programs/survivorship-enrollments/{id}` | Get a survivorship enrollment | Any |
| POST | `/programs/survivorship-enrollments/{id}/follow-ups` | Log a follow-up visit, advancing the next-due date by one interval | SurvivorshipCoordinator |
| POST | `/programs/survivorship-enrollments/{id}/withdraw` | Withdraw a survivor from follow-up | SurvivorshipCoordinator |
| GET | `/programs/survivorship-enrollments/{id}/follow-ups` | List follow-up visits for a survivorship enrollment | Any |
| POST | `/programs/family-support-services` | Create a family-support service line | PatientSupportOfficer |
| GET | `/programs/family-support-services` | List family-support service lines | Any |
| GET | `/programs/family-support-services/{id}` | Get a family-support service line | Any |
| POST | `/programs/family-support-services/{id}/allowances` | Accrue a family allowance into the service ledger, applying the stimulation markup | PatientSupportOfficer |
| GET | `/programs/family-service-ledgers/{id}` | Get a family service ledger | Any |
| POST | `/programs/family-service-ledgers/{id}/freeze` | Freeze a family service ledger, pausing markup accrual | PatientSupportOfficer |
| GET | `/programs/family-support-services/{id}/ledgers` | List service ledgers for a service line | Any |
| GET | `/programs/sibling-support-services` | List sibling support services | Any |
| GET | `/programs/sibling-support-services/{id}` | Get a sibling support service | Any |
| POST | `/programs/sibling-support-services/{id}/sessions` | Deliver sibling support sessions, honouring the monthly window limit | PatientSupportOfficer |
| POST | `/programs/sibling-support-services/{id}/cancel` | Cancel a sibling support service | PatientSupportOfficer |
| GET | `/programs/milestones` | List protocol milestones across enrollments, optionally filtered by affiliate | Any |
| GET | `/programs/survivorship-enrollments` | List survivorship enrollments across studies | Any |
| POST | `/_ops/run-checkpoint` | Test-driving endpoint: advance the service-ledger epoch, freezing ledgers whose accumulated_cents exceeds their service cap | PlatformAdmin |

## 5. Error Code Catalogue

The table below lists every error identifier the service may return and the HTTP status that
accompanies it. Trigger conditions are not repeated here; each identifier's condition is stated
in the section 2 principle or section 3 workflow that guards it.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_REFERRAL_NOT_FOUND` | 404 |
| `ERR_PROTOCOL_NOT_FOUND` | 404 |
| `ERR_ENROLLMENT_NOT_FOUND` | 404 |
| `ERR_HOUSING_ASSIGNMENT_NOT_FOUND` | 404 |
| `ERR_HOUSING_FACILITY_NOT_FOUND` | 404 |
| `ERR_PLEDGE_NOT_FOUND` | 404 |
| `ERR_TRAVEL_NOT_FOUND` | 404 |
| `ERR_MILESTONE_NOT_FOUND` | 404 |
| `ERR_STUDY_NOT_FOUND` | 404 |
| `ERR_SURVIVORSHIP_ENROLLMENT_NOT_FOUND` | 404 |
| `ERR_CLINIC_NOT_FOUND` | 404 |
| `ERR_AGREEMENT_NOT_FOUND` | 404 |
| `ERR_SERVICE_NOT_FOUND` | 404 |
| `ERR_LEDGER_NOT_FOUND` | 404 |
| `ERR_FUND_NOT_FOUND` | 404 |
| `ERR_SIBLING_SERVICE_NOT_FOUND` | 404 |
| `ERR_HOLD_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_DUPLICATE_ENTITY` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_PROTOCOL_NOT_OPEN` | 409 |
| `ERR_PROTOCOL_NOT_IN_DRAFT` | 409 |
| `ERR_PROTOCOL_NOT_HELD` | 409 |
| `ERR_PROTOCOL_HELD` | 409 |
| `ERR_PROTOCOL_HOLD_ACTIVE` | 409 |
| `ERR_PROTOCOL_HAS_ENROLLED_PATIENTS` | 409 |
| `ERR_ARM_ASSENT_BLOCKED_BY_HOLD` | 409 |
| `ERR_HOLD_NOT_ACTIVE` | 409 |
| `ERR_HOLD_NOT_IRB_REVIEW` | 409 |
| `ERR_REFERRAL_NOT_SUBMITTED` | 409 |
| `ERR_REFERRAL_NOT_ACCEPTED` | 409 |
| `ERR_REFERRAL_NOT_DECLINED` | 409 |
| `ERR_DUPLICATE_PATIENT_ELIGIBILITY` | 409 |
| `ERR_AGE_OUTSIDE_PROTOCOL_RANGE` | 422 |
| `ERR_DISEASE_GROUP_MISMATCH` | 422 |
| `ERR_DISEASE_STAGE_MISMATCH` | 422 |
| `ERR_PROTOCOL_CAPACITY_EXCEEDED` | 409 |
| `ERR_PROTOCOL_BUDGET_EXCEEDS_COMMITMENT_SHARE` | 402 |
| `ERR_PROTOCOL_BUDGET_EXHAUSTED` | 402 |
| `ERR_NO_HOUSING_AVAILABLE` | 409 |
| `ERR_HOUSING_CAPACITY_EXCEEDED` | 409 |
| `ERR_HOUSING_IMMUNOSUPPRESSION_INCOMPATIBLE` | 422 |
| `ERR_HOUSING_FACILITY_UNAVAILABLE` | 409 |
| `ERR_STEP_DOWN_NOT_PERMITTED` | 422 |
| `ERR_INVALID_VACATE_REASON` | 422 |
| `ERR_HOUSING_OCCUPANCY_ACTIVE` | 409 |
| `ERR_NO_ACTIVE_HOUSING` | 409 |
| `ERR_OCCUPANCY_NOT_STARTED` | 409 |
| `ERR_HOUSING_ASSIGNMENT_NOT_SCHEDULED` | 409 |
| `ERR_HOUSING_ASSIGNMENT_NOT_ACTIVE` | 409 |
| `ERR_ENROLLMENT_NOT_PENDING_CONSENT` | 409 |
| `ERR_ENROLLMENT_NOT_ENROLLED` | 409 |
| `ERR_ENROLLMENT_NOT_ACTIVE_TREATMENT` | 409 |
| `ERR_ENROLLMENT_NOT_ON_HIATUS` | 409 |
| `ERR_ENROLLMENT_NOT_IN_SURVIVORSHIP` | 409 |
| `ERR_ENROLLMENT_ACTIVE` | 409 |
| `ERR_INVALID_CONSENT_SIGNER` | 422 |
| `ERR_BILLING_NOT_PERMITTED` | 409 |
| `ERR_ONE_TO_ONE_CARE_NOT_ELIGIBLE` | 422 |
| `ERR_ASSENT_NOT_OBTAINED` | 409 |
| `ERR_SUPPORT_BUDGET_EXCEEDED` | 402 |
| `ERR_PLEDGE_SETTLE_NOT_ACTIVE` | 409 |
| `ERR_PLEDGE_SETTLE_ENROLLMENT_ACTIVE` | 409 |
| `ERR_TRAVEL_NOT_REQUESTED` | 409 |
| `ERR_TRAVEL_NOT_CONFIRMED` | 409 |
| `ERR_TRAVEL_NOT_CANCELLABLE` | 409 |
| `ERR_TRAVELER_COUNT_RANGE` | 422 |
| `ERR_TRAVEL_ELIGIBILITY_NOT_CONFIRMED` | 409 |
| `ERR_TRAVEL_COVERAGE_EXPIRED` | 409 |
| `ERR_TRAVEL_LEG_OVERLAP` | 409 |
| `ERR_MILESTONE_NOT_DUE` | 409 |
| `ERR_PRIOR_MILESTONE_NOT_EXECUTED` | 409 |
| `ERR_MILESTONE_REQUIRES_MAIN_CAMPUS` | 422 |
| `ERR_NO_ACTIVE_AFFILIATION_AGREEMENT` | 409 |
| `ERR_AFFILIATE_NOT_ADJACENT` | 422 |
| `ERR_VISIT_WINDOW_TOO_DISTANT` | 409 |
| `ERR_MILESTONES_OUTSTANDING` | 409 |
| `ERR_NO_ACTIVE_SURVIVORSHIP_STUDY` | 409 |
| `ERR_SURVIVORSHIP_NOT_GRADUATED` | 409 |
| `ERR_SURVIVORSHIP_NOT_ON_STUDY` | 409 |
| `ERR_STUDY_NOT_ACTIVE` | 409 |
| `ERR_FOLLOW_UP_WINDOW_VIOLATION` | 409 |
| `ERR_SIBLING_SERVICE_NOT_ACTIVE` | 409 |
| `ERR_SIBLING_SESSION_LIMIT_REACHED` | 409 |
| `ERR_STALE_LEDGER_EPOCH` | 409 |
