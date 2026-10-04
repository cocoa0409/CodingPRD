# Federal Building Lease Billing API — Product Requirements Document

## 1. Introduction

The General Services Administration houses federal tenant agencies in a mixed portfolio of federally owned buildings and competitively procured leased stock. Getting an agency into space is a long, money-dense pipeline: a tenant agency develops a space requirement from headcount projections and security scoring, GSA validates the requirement and runs a market survey, lessors submit competitive offers with build-out allowances and rent abatements, an award creates a lease, and only then can occupancy agreements, rent billing, alterations, and service delivery begin. At the far end of the term, expiration planning weighs a succeeding lease against relocation and replacement construction, while utilization measurement continually pressures the portfolio to shed unused square footage.

This document specifies the API that automates that pipeline end to end. The system is at heart a pricing engine: every occupancy agreement is billed monthly from a pinned sequence of rent components — shell, operating, tax escalation, tenant-improvement amortization, alteration amortization, lump-sum charges, abatements, a percentage fee, and service credits — with two escalation methods and two amortization methods producing deliberately different cent-level outcomes from similar inputs. All money is carried in integer cents, all temporal behavior is driven by a controllable logical clock rather than the wall clock, and space inventory is conserved at all times: square footage committed to agreements and leases is never created or destroyed silently, only moved between the available pool and the committed pool.

## 2. Global Specifications & System-Wide Principles

This section defines the rules that hold across every resource and endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying an empty value in either, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). The system recognizes exactly five roles, spelled as follows: `GSAAdmin`, `GSALeasingOfficer`, `GSAPropertyManager`, `AgencyManager`, and `LessorRep`. Each endpoint admits a fixed list of roles (see §4); a caller whose role is not on that list is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403).

The five roles divide the work along organizational lines. A `GSAAdmin` is the central administrator: it registers agencies and buildings, drives the logical clock, and approves proposed space reductions. A `GSALeasingOfficer` is the leasing specialist: it returns, validates, and surveys requirements, evaluates and selects offers, commences leases, records tax statements, opens and executes expiration plans, and establishes, amends, and terminates occupancy agreements. A `GSAPropertyManager` is the property and facilities manager: it prices and completes alterations, resolves service tickets, generates rent bills, records and finalizes utilization surveys, and executes approved space reductions. An `AgencyManager` is the tenant agency's space manager: it develops and submits requirements, signs occupancy agreements, requests, approves, revises, and cancels alterations, pays rent bills, and reports and verifies service tickets. A `LessorRep` is a private lessor representative: it submits competitive lease offers and withdraws them.

Role identity is resolved in two different ways. When `X-User-Role` is `AgencyManager`, `X-User-ID` is the `id` of the acting `Agency`; ownership checks on any resource that references an `Agency` compare the resource's `agency_id` field to `X-User-ID`, and a mismatch is rejected with `ERR_AGENCY_SCOPE_VIOLATION` (HTTP 403). When `X-User-Role` is `GSAAdmin`, `GSALeasingOfficer`, `GSAPropertyManager`, or `LessorRep`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.

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

List endpoints paginate through two query parameters. `limit` sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` sets the number of items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock

All time-dependent behavior in the system — award and execution timestamps, alteration and measurement freshness, SLA measurement, and every automatic state sweep — reads a single server-held logical clock. The clock never falls back to wall-clock time: before any clock-setting call has been made, the logical clock reads exactly `2026-09-01T00:00:00Z`. A `GSAAdmin`-only capability advances the clock to a supplied `to_iso8601` instant. The clock is monotonic: an attempt to set it to an instant earlier than its current reading is rejected with `ERR_INVALID_REQUEST`. The clock-setting response reports `current_utc` plus the ids of everything the sweep moved: `transitioned_lease_ids`, `transitioned_oa_ids`, and `transitioned_plan_ids`.

Advancing the clock sweeps the portfolio for time-based transitions. A lease in `COMMENCED` moves to `EXPIRING` once the current date reaches the date eighteen months before its `end_date` (month arithmetic, with the day clamped to the month end when the target month is shorter). A lease in `EXPIRING` moves to `EXPIRED` or `SUCCEEDED` once the current date passes its `end_date`, depending on its `executed_option` (§3.9). An occupancy agreement in `ACTIVE` moves to `EXPIRED` once the current date passes the agreement's `end_date` (§3.5).

### 2.5. Monetary Representation and Rounding

All monetary values are integers denominated in cents — rent rates, tax rates, allowances, costs, credits, and bill totals alike. Per-square-foot rates are annual figures in cents per rentable square foot. Every rounding in the system is round half up, and bill components are each rounded to whole cents before they are summed into a subtotal; the component-first order is pinned and must not be rearranged (§3.5). Utilization rates are the one non-monetary computed quantity with their own precision: four decimal places, round half up (§3.8).

### 2.6. Common Resource Properties

Every resource type in the system — agencies, buildings, space requirements, offers, leases, expiration plans, occupancy agreements, rent bills, alteration requests, service tickets, utilization surveys, and space reduction actions — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set when the resource is created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that increments by one on every mutation of the resource, including system-driven transitions, cascade effects, and computed-field recomputation.

### 2.7. Optimistic Concurrency Control

Exactly two write operations are guarded by optimistic concurrency control, and each names its own expected-version field:

- Amending an occupancy agreement requires the request to carry `expected_oa_version` holding the `version` of the agreement as the client last observed it. If the agreement's current `version` has advanced since that observation — amendments may be issued in sequence, and each one rewrites `assigned_sf`, the term end, or the owned-space rates — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), forcing the stale writer to re-read and rebase before retrying.
- Revising an alteration request requires the request to carry `expected_alteration_version` holding the alteration's last observed `version`. A revision legitimately supersedes the pending estimate — it clears the estimate fields and reopens the request — so a stale revision is rejected with `ERR_STALE_VERSION` (HTTP 412).

No endpoint other than these two accepts a version field.

### 2.8. Nested Paths and Identifier Resolution

Requests that carry resource identifiers are validated left to right: path identifiers first, in path order, then identifiers referenced in the request body (for example `lease_id`, `building_id`, and `agency_id` when an occupancy agreement is created, `building_id` when an offer is created, or `reported_oa_id` when a service ticket is created). The first identifier that does not resolve to an existing resource rejects the request with `ERR_NOT_FOUND` (HTTP 404); later identifiers are not examined.

### 2.9. Space Inventory Conservation

A building's `available_sf` is a computed quantity, never accepted as client input, and the system conserves square footage at all times. On a `FEDERALLY_OWNED` building, `available_sf` equals `total_sf` minus the sum of `assigned_sf` over that building's occupancy agreements in `DRAFT` or `ACTIVE` status — a draft agreement already reserves its space. On a `LEASED_STOCK` building, `available_sf` equals `total_sf` minus the sum of `leased_sf` over that building's leases in `AWARDED`, `COMMENCED`, or `EXPIRING` status. Equivalently, committed square footage plus available square footage always equals `total_sf`, on both ownership variants. The quantity is reconciled at every event that changes the committed pool: occupancy agreement creation, amendment, termination, and expiry, space-reduction execution, and lease award (which decrements the leased-stock building's `available_sf` by the newly leased square footage at selection time). Releases happen symmetrically at termination, expiry, and reduction execution (§3.5, §3.8, §3.9).

### 2.10. Validation Order and Error Precedence

When a single request violates several rules, the violation with the lowest priority number produces the response; the checks are evaluated in this order:

1. Presence of the user-context headers — `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (400).
2. Role authorization for the endpoint — `ERR_FORBIDDEN_FOR_ROLE` (403).
3. Agency scope for an `AgencyManager` caller: the caller's `X-User-ID` must equal the `agency_id` of the target resource (the requirement, the occupancy agreement, the bill's agreement, the alteration's agreement, or the ticket's reported agreement) — `ERR_AGENCY_SCOPE_VIOLATION` (403).
4. Existence of path and body identifiers, left to right — `ERR_NOT_FOUND` (404).
5. Request shape and field domains: required fields present, enums within their declared sets, numeric ranges respected, `special_needs` item shape, `measured_at` not in the future — `ERR_INVALID_REQUEST` (400).
6. State-transition validity: the requested transition must exist from the resource's current state, which covers terminal-state lockdown and repeated transitions — `ERR_INVALID_STATE_TRANSITION` (409).
7. Cross-entity state gates — `ERR_REQUIREMENT_NOT_SOLICITING`, `ERR_LEASE_NOT_COMMENCED`, `ERR_OA_NOT_ACTIVE`, or `ERR_LEASE_NOT_EXPIRING` (all 409).
8. Award safety: the offered building's security capability against the requirement's level — `ERR_SECURITY_LEVEL_INSUFFICIENT` (422).
9. Temporal windows — `ERR_OFFER_EXPIRED`, `ERR_COMMENCEMENT_OUT_OF_WINDOW`, `ERR_BILL_MONTH_OUT_OF_TERM`, `ERR_OPTION_DEADLINE_PASSED` (all 422), and `ERR_ALTERATION_WINDOW_CONFLICT` (409).
10. Referential structure of occupancy tenancy and ticket references — `ERR_OA_TENANCY_AMBIGUOUS`, `ERR_BUILDING_NOT_OWNED`, `ERR_INVALID_REQUEST`, `ERR_OA_TERM_EXCEEDS_LEASE`, `ERR_OA_NOT_ACTIVE` (422 family).
11. Capacity and uniqueness — `ERR_BUILDING_CAPACITY_EXCEEDED`, `ERR_LEASE_SPACE_EXCEEDED` (both 422), and `ERR_BILL_ALREADY_EXISTS`, `ERR_PLAN_ALREADY_OPEN`, `ERR_DUPLICATE_TAX_YEAR` (all 409).
12. Fiscal gates — `ERR_AMORTIZATION_WINDOW_TOO_SHORT` and `ERR_PAYMENT_EXCEEDS_BALANCE` (both 422).

### 2.11. Lifecycle Cascades and Ledger-Style Consistency

Three resource fields are append-only histories that the system never rewrites, only extends: a lease's `tax_statements`, a bill's `payments`, and an occupancy agreement's `amendment_history`. Each occupancy agreement also behaves as a small receivable ledger: its `receivable_outstanding_cents` always equals the sum of its bills' `total_cents` minus the sum of their `amount_paid_cents`, recomputed at every bill generation and every payment. A lump-sum alteration that is cancelled before completion never enters any bill, so an approve-then-cancel pair leaves the agreement's billable pipeline exactly as it found it — net zero. Finally, when a lease or an occupancy agreement reaches the end of its life, the system resolves its dependents automatically rather than leaving them dangling: in-flight alterations are cancelled with their pending charges reversed, unamortized balances accelerate into a terminal write-off, reserved space is released, and unexecuted plans are cancelled. The full cascades are described where they occur (§3.5, §3.9).

## 3. Business Logic & Workflows

### 3.1. Establishing the Portfolio: Agencies and Buildings

Before any requirement can be developed, a `GSAAdmin` registers the actors and the inventory. An agency is registered with a `bureau_code` — unique across all agencies — and a display `name`; its `status` is `ACTIVE` from creation, the only value that field takes.

A building is registered with its `building_name`, street `address`, GSA `region_code`, `ownership_type` (exactly one of `FEDERALLY_OWNED` or `LEASED_STOCK`), `security_capability` (an integer from 1 to 5 expressing the highest facility security level the building can support), and `total_sf`, its total rentable square feet, which must be greater than zero. On registration a building's `status` is `ACTIVE` and its `available_sf` initializes to `total_sf`. The only other building status, `UNDER_CONSTRUCTION`, is never written directly — it appears only when expiration-plan execution spawns a replacement construction project (§3.9). The ownership type chosen here drives everything downstream: leased stock is committed lease-by-lease at award, owned buildings are committed agreement-by-agreement (§2.9), and occupancy agreements over owned space price from market-rate inputs supplied at agreement creation rather than from a lease (§3.5).

### 3.2. Developing and Validating a Space Requirement

An `AgencyManager` opens the pipeline by creating a space requirement for their own agency: the `agency_id` in the payload must equal the caller's `X-User-ID`, or the create is rejected with `ERR_AGENCY_SCOPE_VIOLATION`. The requirement carries a `title`; the `base_headcount` currently to be housed, which must be greater than zero; the projected `annual_growth_pct` as a decimal, which may run from zero up to a ten-percent annual ceiling; the `target_occupancy_year` in which the space must be ready; the agency's `sf_per_person` space standard, between 100 and 250 usable square feet per person; an array of `special_needs`, which may be empty, each item pairing a `need_type` of `SCIF`, `LAB`, `WAREHOUSE`, or `SECURE_STORAGE` with a positive integer `sf`; the `region_code` delineating the market to search; and the four ISC scoring inputs `mission_points`, `population_points`, `size_points`, and `criticality_points`, each between 0 and 25. A new requirement starts in `DRAFT`, with `delivery_method` set to `STANDARD` and `source_plan_id` null — both are only ever different when an expiration plan spawns the requirement (§3.9).

Submission moves the requirement from `DRAFT` to `SUBMITTED`; only the owning agency's manager may submit, under the same scope check. A `GSALeasingOfficer` who finds the requirement deficient returns it, moving `SUBMITTED` to `NEEDS_REVISION`, and the agency resubmits from `NEEDS_REVISION` back to `SUBMITTED` — again scope-checked. This return-and-resubmit cycle may repeat without bound.

Validation is the computational heart of requirement development and moves `SUBMITTED` to `VALIDATED`. Two calculations run at this moment. First, headcount projection: the projection horizon is the number of whole years from the year of the current logical clock to `target_occupancy_year`, never less than zero. The `projected_headcount` is the `base_headcount` grown at the `annual_growth_pct` rate, compounded once per year across that horizon, and rounded half up to whole persons. From it, `required_usable_sf` is the `projected_headcount` multiplied by `sf_per_person`, plus the sum of the `sf` of every item in `special_needs`. Second, security level determination: the four ISC point inputs are summed, and the base level is 1 when the total is below 15, 2 when it is at least 15 but below 30, 3 when at least 30 but below 45, 4 when at least 45 but below 60, and 5 when it reaches 60. When any special need is of type `SCIF`, the level is raised to at least 4. The outcome is stored as `required_security_level`, an integer from 1 to 5.

Once the market survey is complete, the officer records it: the requirement moves from `VALIDATED` to `SOLICITING`, and the `survey_summary` narrative from the request payload is stored on the requirement. Solicitation is the only state in which offers may be submitted or selected (§3.3). When an offer is finally selected, the system itself moves the requirement from `SOLICITING` to `AWARDED` — a terminal state that hands the lifecycle off to the newly created lease.

### 3.3. Competitive Offering and Lease Award

While a requirement is `SOLICITING`, a `LessorRep` submits a competitive offer against it, carrying the offered `building_id`, the lessor's legal `lessor_name`, the annual `shell_rate_per_sf_yr_cents` (greater than zero), the annual `operating_rate_per_sf_yr_cents` (zero or more), the `base_year_tax_per_sf_yr_cents` that anchors tax escalation (zero or more), the `escalation_method` of `BASE_YEAR_STOP` or `CPI_INDEXED`, the `ti_allowance_per_sf_cents` build-out allowance (zero or more), the `free_rent_months` shell abatement (from 0 to 24), the `term_years` of the lease (from 5 to 20), and a `valid_until` deadline after which the offer lapses. Submitting against a requirement that is not `SOLICITING` is rejected with `ERR_REQUIREMENT_NOT_SOLICITING`. A new offer starts in `SUBMITTED`; a `GSALeasingOfficer` moves it to `UNDER_EVALUATION` when evaluation begins.

Awarding the lease — selecting an offer, moving it from `UNDER_EVALUATION` to `SELECTED` — is the most heavily gated operation in the system. Four preconditions hold, surfacing in validation-priority order (§2.10): the requirement must still be `SOLICITING` (`ERR_REQUIREMENT_NOT_SOLICITING`); the offered building's `security_capability` must be at least the requirement's `required_security_level` (`ERR_SECURITY_LEVEL_INSUFFICIENT`); the offer's `valid_until` must not be earlier than the current logical clock (`ERR_OFFER_EXPIRED`); and the offered building's `available_sf` must be at least the requirement's `required_usable_sf` (`ERR_BUILDING_CAPACITY_EXCEEDED`).

Selection's side effects fan out across four resources. A lease springs into existence in `AWARDED` status: the shell, operating, and base-year tax rates, the `escalation_method`, and the `free_rent_months` are copied from the offer; `term_months` is twelve times the offer's `term_years`; `leased_sf` equals the requirement's `required_usable_sf`; `ti_allowance_total_cents` is the offer's `ti_allowance_per_sf_cents` multiplied by `leased_sf`; and `awarded_date` is stamped from the logical clock. The lease records its provenance in `requirement_id`, `building_id`, `offer_id`, and `agency_id`, and its `succeeds_lease_id` is null unless the lease was itself created by succession (§3.9). Simultaneously, the requirement transitions from `SOLICITING` to `AWARDED`; every sibling offer on the same requirement still in `SUBMITTED` or `UNDER_EVALUATION` is moved to `REJECTED` with `rejection_reason` set to `AUTO_NOT_SELECTED` (sibling offers already in a terminal state are untouched); and the building's `available_sf` decreases by `leased_sf`, committing the space per §2.9.

A `LessorRep` may withdraw an offer that is still in `SUBMITTED` or still in `UNDER_EVALUATION`; either way the offer lands in `WITHDRAWN` with `rejection_reason` set to `WITHDRAWN_BY_LESSOR`. The `rejection_reason` field is null on every offer that is neither `REJECTED` nor `WITHDRAWN`.

### 3.4. Commencement, Rent Structure, and Tax Escalation

An awarded lease does not bill until a `GSALeasingOfficer` commences it, moving `AWARDED` to `COMMENCED` with a payload of `commencement_date`, the actual `ti_buildout_cost_cents` (zero or more), the `ti_amort_method` of `ANNUITY` or `STRAIGHT_LINE`, and — only when the escalation method is `CPI_INDEXED` — the `cpi_base_index` observed at commencement. The commencement date must fall on or after the award date and no later than twenty-four months after it; outside that window the request fails with `ERR_COMMENCEMENT_OUT_OF_WINDOW`. Supplying `cpi_base_index` when the escalation method is not `CPI_INDEXED`, or omitting it when it is, fails with `ERR_INVALID_REQUEST`. Commencement pins the lease's `end_date`: the date `term_months` months after the commencement date, minus one day, using month arithmetic with the day preserved and clamped to the target month's end.

Commencement also builds the tenant-improvement amortization schedule. The amortizable principal `ti_amortized_principal_cents` is the `ti_buildout_cost_cents` minus the `ti_allowance_total_cents`, floored at zero; when it is zero, `ti_schedule_monthly_cents` is empty and no TI component ever bills. Otherwise the schedule has one entry per month for `term_months` months, at a monthly rate of one-twelfth of the six-percent annual rate — one half of one percent per month. Under `ANNUITY`, a single level payment is computed: the principal multiplied by the monthly rate, divided by one minus the quantity one-plus-the-monthly-rate raised to the negative power of the term in months, rounded half up to whole cents; every month's entry equals that level payment. Under `STRAIGHT_LINE`, an equal principal portion is computed as the principal divided by the term in months, rounded half up; each month then charges that equal principal plus interest of the current remaining balance times the monthly rate, rounded half up, and the balance is reduced by the equal principal before the next month is computed — so the method is front-loaded and its early entries differ from the annuity's. In both variants each monthly entry is rounded half up to whole cents before the next month is computed.

Throughout the term, the lessor's annual actual-tax statements are recorded against the lease by a `GSALeasingOfficer` — but only while the lease is `COMMENCED` or `EXPIRING`; attempts earlier or later fail with `ERR_LEASE_NOT_COMMENCED`. Each statement supplies a `tax_year`, the `actual_tax_per_sf_yr_cents` for that year, and a `cpi_index` — the index is required exactly when the escalation method is `CPI_INDEXED`, and its presence or absence otherwise is an `ERR_INVALID_REQUEST`. One statement per `tax_year` per lease: a duplicate year is rejected with `ERR_DUPLICATE_TAX_YEAR`. Statements accumulate in the append-only `tax_statements` array, and each append recomputes the lease's `current_tax_per_sf_yr_cents` and `current_cpi_index` and increments the lease's `version`. Those current values come from the statement with the greatest `tax_year` not later than the context year; when no statement qualifies, the base-year tax rate and the `cpi_base_index` stand in.

Tax escalation is billed monthly to leased occupancy agreements — agreements over owned space always bill a zero escalation component (§3.5). The relevant statement is the one with the greatest `tax_year` not later than the billing year, with base values standing in when none qualifies. Under `BASE_YEAR_STOP`, the annual escalation is the excess of the statement's actual per-square-foot tax over the lease's `base_year_tax_per_sf_yr_cents`, floored at zero, multiplied by the agreement's assigned square feet — so when no statement qualifies, actual equals base and the escalation is zero. Under `CPI_INDEXED`, the escalation indexes the base-year tax by CPI growth: the statement's index divided by the `cpi_base_index`, minus one, floored at zero and capped at twenty percent, multiplied by the base-year tax rate and the assigned square feet. Either way, the annual figure is rounded half up first, then divided by twelve and rounded half up again to whole cents for the month.

### 3.5. Occupancy Agreements and the Monthly Rent Bill

An occupancy agreement, established by a `GSALeasingOfficer`, is the instrument that actually bills a tenant agency for space. Creation demands exactly one of `lease_id` or `building_id`: presenting both, or neither, is rejected with `ERR_OA_TENANCY_AMBIGUOUS`. A `building_id` agreement is only valid on a `FEDERALLY_OWNED` building — pointing one at leased stock fails with `ERR_BUILDING_NOT_OWNED` — and requires the market-rate inputs `shell_equivalent_rate_per_sf_yr_cents` and `operating_rate_per_sf_yr_cents`; an owned agreement missing either rate fails with `ERR_INVALID_REQUEST`, while on a leased agreement both are simply ignored. Every agreement also carries the tenant `agency_id`, the `assigned_sf` (greater than zero), and an inclusive `start_date` and `end_date` with the end after the start. A leased agreement's window must lie within the lease's own term — no earlier than the lease's `commencement_date` and no later than its `end_date` — on pain of `ERR_OA_TERM_EXCEEDS_LEASE`; because an awarded-but-not-yet-commenced lease has no pinned dates, that window check is skipped at creation while the lease is still `AWARDED` and applies at creation only once the lease has commenced, as well as at every later amendment. The agreement's `pricing_source` is computed, not supplied: `LEASE_PASS_THROUGH` when a `lease_id` is present, `OWNED_MARKET` otherwise. New agreements start in `DRAFT` with `pending_service_credit_cents` and `terminal_writeoff_cents` both at zero, and an owned agreement reserves its space immediately — the building's `available_sf` drops by `assigned_sf` from the moment of creation (§2.9). Capacity is enforced at creation and at any amendment that grows the footprint: on owned buildings the committed square feet across `DRAFT` and `ACTIVE` agreements must not exceed `total_sf` (`ERR_BUILDING_CAPACITY_EXCEEDED`), and on a lease the committed square feet across the lease's `DRAFT` and `ACTIVE` agreements must not exceed `leased_sf` (`ERR_LEASE_SPACE_EXCEEDED`).

Activation — the tenant agency signing — moves `DRAFT` to `ACTIVE` and is performed by the `AgencyManager` whose `X-User-ID` equals the agreement's `agency_id` (`ERR_AGENCY_SCOPE_VIOLATION`). A leased agreement may activate only while its lease is `COMMENCED` or `EXPIRING` (`ERR_LEASE_NOT_COMMENCED`); an owned agreement has no lease gate.

Amendment keeps an `ACTIVE` agreement in `ACTIVE` while rewriting its commercial terms; attempting it against an agreement that is not `ACTIVE` is rejected with `ERR_OA_NOT_ACTIVE`. It is one of the system's two OCC-guarded writes (§2.7): the request must carry `expected_oa_version`. Beyond it, the officer may supply `delta_sf` (which may be negative), a `new_end_date`, new owned-space rates `new_shell_equivalent_rate_per_sf_yr_cents` and `new_operating_rate_per_sf_yr_cents`, and a free-text `note`. The amendment increments the agreement's `version`, appends to `amendment_history` an entry recording `amended_at`, `delta_sf`, `old_sf`, `new_sf`, and the `note`, and applies `delta_sf` to `assigned_sf` — moving the owned building's `available_sf` in the opposite direction by the same amount. A positive `delta_sf` re-runs the capacity checks above, and a `new_end_date` that would push a leased agreement past the lease's `end_date` is rejected with `ERR_OA_TERM_EXCEEDS_LEASE`.

Termination is performed by a `GSALeasingOfficer` and ends the agreement in `TERMINATED`. From `DRAFT`, termination simply releases the reservation, restoring the owned building's `available_sf` by the `assigned_sf`. From `ACTIVE`, the full terminal cascade runs: the owned building's `available_sf` is restored; every non-terminal alteration request on the agreement — those in `REQUESTED`, `ESTIMATED`, or `APPROVED` — is cancelled, and any such cancellation reverses a pending lump-sum charge from `PENDING` to `REVERSED`; and each completed amortized alteration's exact remaining `amortization_balance_cents` is accelerated, rounded half up, into the agreement's `terminal_writeoff_cents`. Expiry lands in `EXPIRED` instead and fires the identical cascade — the system moves an `ACTIVE` agreement to `EXPIRED` when the logical clock passes its `end_date`, and a lease ending can push its agreements into `EXPIRED` by cascade (§3.9).

Billing is the agreement's monthly ritual, performed by a `GSAPropertyManager`. The agreement must be `ACTIVE` (`ERR_OA_NOT_ACTIVE`); the requested `billing_month`, in `YYYY-MM` form, must be unique for the agreement (`ERR_BILL_ALREADY_EXISTS`); and it must not fall before the lease's commencement month on a leased agreement nor after the agreement's own end month on any agreement (`ERR_BILL_MONTH_OUT_OF_TERM`). Each generated bill carries the agreement's `oa_id` and is computed in a pinned, component-first order, every component rounded half up to whole cents before the subtotal is summed:

1. The month index is the one-based count of months from the lease's commencement month to the billing month — defined for leased agreements.
2. `shell_cents` is the annual shell rate times `assigned_sf`, divided by twelve: the lease's `shell_rate_per_sf_yr_cents` on a leased agreement, the agreement's `shell_equivalent_rate_per_sf_yr_cents` on an owned one.
3. `operating_cents` is the same shape from the applicable operating rate.
4. `abatement_credit_cents` equals `shell_cents` when the agreement is leased and the month index falls within the lease's `free_rent_months`; otherwise it is zero.
5. `tax_escalation_cents` follows §3.4 — leased agreements only; owned agreements bill zero.
6. `ti_amortization_cents` is the lease's `ti_schedule_monthly_cents` entry at the month index when the agreement is leased, the index lies within the lease term, and the schedule is non-empty; otherwise zero.
7. `alteration_amortization_cents` sums, over the agreement's `COMPLETED` amortized alterations whose billed span — from `amortization_start_month` through the agreement's end month — covers the billing month, that month's scheduled charge: the level `monthly_amort_cents` for every month of a schedule except its final month, which bills its residual amount instead (§3.6).
8. `lump_sum_charges_cents` sums the `estimated_cost_cents` of the agreement's `COMPLETED` lump-sum alterations whose completion month is the month immediately preceding the billing month; charging a lump sum on a bill moves that alteration's `lump_charge_status` to `BILLED`.
9. The subtotal is `shell_cents` minus `abatement_credit_cents`, plus `operating_cents`, `tax_escalation_cents`, `ti_amortization_cents`, `alteration_amortization_cents`, and `lump_sum_charges_cents`.
10. `fee_cents` is the GSA fee: five percent of the subtotal, rounded half up.
11. `service_credit_applied_cents` consumes the agreement's `pending_service_credit_cents`, up to the subtotal plus the fee.
12. `total_cents` is the subtotal plus the fee minus the applied service credit, never below zero.
13. The agreement's `pending_service_credit_cents` is then reduced by the applied amount, and its `receivable_outstanding_cents` is recomputed per §2.11.

A bill starts in `ISSUED` with `amount_paid_cents` at zero and an empty `payments` array. Payment is made by the `AgencyManager` of the bill's agency (scope-checked), supplying an `amount_cents` that must be greater than zero and no more than the bill's remaining balance — `total_cents` minus what has already been paid — or the payment fails with `ERR_PAYMENT_EXCEEDS_BALANCE`. Three transitions are defined: a payment smaller than the remaining balance moves an `ISSUED` bill to `PARTIALLY_PAID` with `amount_paid_cents` increased by the amount; a payment exactly equal to the remaining balance moves an `ISSUED` bill straight to `PAID` with `amount_paid_cents` set to `total_cents`; and a payment exactly equal to the remaining balance on a `PARTIALLY_PAID` bill moves it to `PAID` the same way. Every payment appends a record of `paid_at`, `amount_cents`, and `payer_user_id` to `payments`, and the agreement's receivable ledger is recomputed.

### 3.6. Alterations During the Term

Mid-term space alterations begin with the tenant: an `AgencyManager` of the agreement's agency requests one against an `ACTIVE` agreement (`ERR_OA_NOT_ACTIVE`), supplying a `title`, a scope `description`, and the `scope_sf` affected (greater than zero). The request starts in `REQUESTED`.

A `GSAPropertyManager` then prices it, moving `REQUESTED` to `ESTIMATED` with an `estimated_cost_cents` (greater than zero) and a proposed inclusive work window from `work_start_date` to `work_end_date`; an end before the start is an `ERR_INVALID_REQUEST`. The agreement must still be `ACTIVE`. The proposed window must also leave at least fourteen clear days to every other non-`CANCELLED` alteration window on the same agreement — the clear-day gap being the days between the later window's start and the earlier window's end — and a gap shorter than that is rejected with `ERR_ALTERATION_WINDOW_CONFLICT`.

If the tenant dislikes the estimate, revision sends the alteration from `ESTIMATED` back to `REQUESTED`; only the `AgencyManager` of the agreement's agency may revise, under the usual scope check (`ERR_AGENCY_SCOPE_VIOLATION`). This is the system's second OCC-guarded write (§2.7): the request must carry `expected_alteration_version`. A revision increments the alteration's `version`, replaces `description` and `scope_sf` when supplied, and clears the pending estimate — `estimated_cost_cents` and both work dates return to null. The estimate-and-revise cycle may repeat.

Approval is the tenant's: an `AgencyManager` of the agreement's agency moves `ESTIMATED` to `APPROVED`, choosing a `funding_method` of `LUMP_SUM` or `AMORTIZED`, again requiring the agreement `ACTIVE`. Choosing `AMORTIZED` commits to at least twelve whole amortization months between the month after the work-end month and the agreement's end month; a shorter runway is rejected with `ERR_AMORTIZATION_WINDOW_TOO_SHORT`. Choosing `LUMP_SUM` arms the one-time charge: the alteration's `lump_charge_status` — `NONE` until now — becomes `PENDING`.

Completion is recorded by a `GSAPropertyManager` with the `completion_date`, moving `APPROVED` to `COMPLETED` against a still-`ACTIVE` agreement. For `AMORTIZED` funding, completion builds the alteration's amortization schedule. The principal is the `estimated_cost_cents`; the monthly rate is one-twelfth of the seven-percent annual rate; the term `amortization_months` is the count of months from the month after the completion month through the agreement's end month, inclusive; and `amortization_start_month` is that first billed month, the month after completion. The level `monthly_amort_cents` is computed first — the principal times the monthly rate, divided by one minus the quantity one-plus-the-monthly-rate raised to the negative power of the term — and rounded half up to whole cents before anything else. The `amortization_balance_cents` then tracks the exact, unrounded remaining balance: each month before the last, the balance grows by one month of interest and the level payment is subtracted; the final month — the agreement's end month — bills the remaining balance grown by one more month of interest, rounded half up, so the residual is absorbed by the last month. Computing the total first and dividing is expressly forbidden: it produces different cents. For `LUMP_SUM` funding, completion instead makes the charge billable in the month immediately following the completion month, where the next bill picks it up and flips `lump_charge_status` to `BILLED` (§3.5, step 8).

Cancellation is the tenant's escape hatch from any non-terminal state, performed by the `AgencyManager` of the agreement's agency under the same scope check. From `REQUESTED` or from `ESTIMATED`, cancellation lands in `CANCELLED` with no further effect. From `APPROVED`, it also reverses a pending lump-sum charge — `PENDING` to `REVERSED` — so the charge never reaches a bill.

### 3.7. Building Services and SLA Credits

Operations, maintenance, and security issues in both leased and owned space are tracked as service tickets on a building. Either the tenant's `AgencyManager` or a `GSAPropertyManager` may report one, supplying the `reported_oa_id`, a `category` of `MAINTENANCE`, `SECURITY`, or `CLEANING`, a `severity` of `CRITICAL` or `ROUTINE`, and a `description`. The `reported_oa_id` must resolve to an `ACTIVE` occupancy agreement on that very building (`ERR_OA_NOT_ACTIVE`), and when the caller is an `AgencyManager`, that agreement must belong to the caller's agency (`ERR_AGENCY_SCOPE_VIOLATION`). A new ticket is `OPEN`, and its `sla_hours` is set from severity: 24 hours for `CRITICAL`, 72 for `ROUTINE`.

A `GSAPropertyManager` resolves the ticket, moving `OPEN` to `RESOLVED` and stamping `resolved_at` from the logical clock. Verification belongs to the tenant: the `AgencyManager` of the reported agreement's agency moves `RESOLVED` to `VERIFIED`, stamping `verified_at`. At that moment the SLA is adjudicated. The ticket's open hours are measured exactly from `created_at` to `resolved_at`; `sla_breached` is true only when that span strictly exceeds `sla_hours` — resolution at exactly the SLA limit is not a breach. An unbreached ticket earns a `credit_cents` of zero. A breached ticket earns ten thousand cents per started twenty-four-hour block of overrun — partial blocks round up — capped at one hundred thousand cents. Any positive credit is added to the agreement's `pending_service_credit_cents`, where it sits until the next generated bill consumes it (§3.5, step 11).

### 3.8. Utilization Measurement and Space Reduction

Utilization surveys measure whether an agency still needs its space. A `GSAPropertyManager` records one against an `ACTIVE` agreement (`ERR_OA_NOT_ACTIVE`), choosing a `method` of `SPACE_BASED` or `HEADCOUNT_BASED` and reporting the `measured_headcount` and `utilized_sf` observed (both zero or more) and a `measured_at` timestamp, which must not lie in the future of the logical clock (`ERR_INVALID_REQUEST`). The survey starts in `RECORDED`.

Finalization moves `RECORDED` to `FINALIZED` and computes the utilization picture. Under `SPACE_BASED`, the `utilization_rate` is the `utilized_sf` divided by the agreement's current `assigned_sf`. Under `HEADCOUNT_BASED`, it is the `measured_headcount` times the 150-square-feet-per-person standard, divided by `assigned_sf` — so identical payloads under the two methods generally yield different rates. Either way the rate is rounded half up to four decimal places. Finalization also sets `recommended_release_sf`: the `assigned_sf` minus the `measured_headcount` times the same 150-square-feet-per-person standard, floored at zero. When the finalized rate falls strictly below 0.60 — a rate of exactly 0.6000 does not qualify — the system auto-creates a space reduction action in `PROPOSED` on the same agreement, copies the recommendation into it, and links it back through the survey's `reduction_action_id`; otherwise that field stays null.

A proposed reduction carries the agreement's `oa_id`, the proposing `survey_id`, and the `recommended_release_sf`. It is deliberately segregated across three hands: only a `GSAAdmin` may approve it, moving `PROPOSED` to `APPROVED`, and only a `GSAPropertyManager` may execute an approved action, moving `APPROVED` to `EXECUTED` — and only while the agreement is still `ACTIVE` (`ERR_OA_NOT_ACTIVE`). Execution behaves like a downward amendment: the agreement's `assigned_sf` decreases by the recommended release, `amendment_history` gains an entry whose `delta_sf` is the negative of the released footage, and the agreement's `version` increments; an owned building's `available_sf` rises by the released footage, while on leased space the footage is released against the lease. The action records `executed_release_sf` — equal to the recommendation — and stamps `executed_at` from the logical clock.

### 3.9. Expiration Planning and Lease Succession

Eighteen months before a commenced lease's `end_date`, the clock sweep moves it from `COMMENCED` to `EXPIRING` (§2.4) — but planning starts earlier. A `GSALeasingOfficer` may open an expiration plan on any lease that is `COMMENCED` or `EXPIRING`; on a lease in any other state the attempt fails with `ERR_INVALID_STATE_TRANSITION`, and a lease that already has a plan in `OPEN` or `OPTION_SELECTED` refuses a second with `ERR_PLAN_ALREADY_OPEN`. The plan starts in `OPEN`.

Selecting an option moves `OPEN` to `OPTION_SELECTED`. The officer supplies the chosen `option` — `SUCCEEDING_LEASE`, `RELOCATION`, or `REPLACEMENT_CONSTRUCTION` — together with the full cost parameter set the scoring needs now and execution will need later: `succeeding_shell_rate`, `succeeding_operating_rate`, and `succeeding_term_years` for a successor lease; `relocation_move_cost_cents`, `relocation_downtime_cost_cents`, `market_shell_rate`, and `market_operating_rate` for relocation; and `construction_cost_cents` and `construction_operating_rate` for replacement construction. The decision deadline is enforced first: the whole calendar months from the current date to the lease's `end_date` — twelve times the difference in years, plus the difference in months, minus one when the end date's day of month precedes the current day — must be at least twelve, or the selection fails with `ERR_OPTION_DEADLINE_PASSED`. All three options are then scored over a ten-year, 120-month horizon against the lease's `leased_sf`. The succeeding-lease cost is the sum of the succeeding shell and operating rates, times the square feet, times ten years. The relocation cost is the move cost plus the downtime cost, plus the sum of the market shell and operating rates times the square feet times ten years. The replacement-construction cost amortizes the construction cost over a 300-month — twenty-five-year — schedule and charges the 120-month horizon's share of it, rounded half up, then adds the construction operating rate times the square feet times ten years. The three results are stored in `option_costs`, each option paired with its `projected_cost_cents`; `recommended_option` is the cheapest, with ties broken by the fixed priority `SUCCEEDING_LEASE` over `RELOCATION` over `REPLACEMENT_CONSTRUCTION`. The supplied inputs are retained in `cost_params` for reuse at execution, and `selected_option` records the officer's choice.

Execution moves `OPTION_SELECTED` to `EXECUTED` and is gated on the lease actually being `EXPIRING` (`ERR_LEASE_NOT_EXPIRING`). It stamps `executed_at` and copies the selection onto the lease's `executed_option`, then branches by option. A `SUCCEEDING_LEASE` execution creates a new lease in `AWARDED` on the same building for the same agency, its `succeeds_lease_id` pointing back to the expiring lease, its rates and term taken from the stored `cost_params`, and its `leased_sf` carried over; the plan's `outcome_lease_id` records it. A `RELOCATION` execution creates a fresh space requirement in `DRAFT` for the same agency, its headcount and square-footage fields copied from the requirement that originated the expiring lease, its `delivery_method` left at `STANDARD` and its `source_plan_id` pointing back to the plan; `outcome_requirement_id` records it. A `REPLACEMENT_CONSTRUCTION` execution creates both a new building in `UNDER_CONSTRUCTION` status and a fresh `DRAFT` requirement whose `delivery_method` is `NEW_CONSTRUCTION`; `outcome_building_id` and `outcome_requirement_id` record the pair.

The end of the lease itself is clock-driven. When the current date passes an `EXPIRING` lease's `end_date`, the sweep moves it to `SUCCEEDED` if its `executed_option` is `SUCCEEDING_LEASE`, and to `EXPIRED` otherwise — including when no option was ever executed. Either landing fires the same cascade across the lease's dependents: every occupancy agreement on the lease still in `DRAFT` or `ACTIVE` moves to `EXPIRED`, and each of those expirations in turn runs the agreement's terminal cascade — its non-terminal alterations are cancelled with pending lump charges reversed, its completed amortized alterations' remaining balances accelerate into `terminal_writeoff_cents`, and owned-space agreements release their square footage (§3.5). Finally, every expiration plan of the lease still sitting in `OPEN` or `OPTION_SELECTED` is moved to `CANCELLED` — a plan that was not executed in time simply lapses.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created` — this includes awarding a lease by selecting an offer, since that operation creates the lease it returns. Operations that modify an existing resource, including all state transitions, return `200 OK`. All business endpoints are mounted under the `/leasing` prefix; the logical-clock endpoint is mounted outside it, at the root. List endpoints accept the pagination parameters of §2.3 plus the optional filters named in their description below.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/leasing/agencies` | Register a tenant agency | GSAAdmin |
| GET | `/leasing/agencies/{id}` | Get one agency | GSAAdmin, GSALeasingOfficer, GSAPropertyManager, AgencyManager, LessorRep |
| POST | `/leasing/buildings` | Register a federally owned or leased-stock building | GSAAdmin |
| GET | `/leasing/buildings/{id}` | Get one building, including computed `available_sf` | GSAAdmin, GSALeasingOfficer, GSAPropertyManager, AgencyManager, LessorRep |
| POST | `/leasing/space-requirements` | Create a space requirement in `DRAFT` | AgencyManager |
| GET | `/leasing/space-requirements/{id}` | Get one space requirement | GSAAdmin, GSALeasingOfficer, GSAPropertyManager, AgencyManager, LessorRep |
| GET | `/leasing/space-requirements` | List space requirements, optionally filtered by `agency_id` and `status` | GSAAdmin, GSALeasingOfficer, GSAPropertyManager, AgencyManager, LessorRep |
| POST | `/leasing/space-requirements/{id}/submit` | Submit a `DRAFT` requirement for GSA review | AgencyManager |
| POST | `/leasing/space-requirements/{id}/return` | Return a `SUBMITTED` requirement for revision | GSALeasingOfficer |
| POST | `/leasing/space-requirements/{id}/resubmit` | Resubmit a returned requirement | AgencyManager |
| POST | `/leasing/space-requirements/{id}/validate` | Validate a `SUBMITTED` requirement; computes projection, security level, and required square footage | GSALeasingOfficer |
| POST | `/leasing/space-requirements/{id}/complete-market-survey` | Record the market survey and open competitive solicitation | GSALeasingOfficer |
| POST | `/leasing/space-requirements/{id}/offers` | Submit a competitive offer against a `SOLICITING` requirement | LessorRep |
| GET | `/leasing/offers/{id}` | Get one offer | GSAAdmin, GSALeasingOfficer, GSAPropertyManager, AgencyManager, LessorRep |
| GET | `/leasing/offers` | List offers, optionally filtered by `requirement_id`, `building_id`, and `status` | GSAAdmin, GSALeasingOfficer, GSAPropertyManager, AgencyManager, LessorRep |
| POST | `/leasing/offers/{id}/evaluate` | Move an offer into evaluation | GSALeasingOfficer |
| POST | `/leasing/offers/{id}/select` | Award the lease to this offer; creates the lease and rejects sibling offers | GSALeasingOfficer |
| POST | `/leasing/offers/{id}/withdraw` | Withdraw a non-terminal offer | LessorRep |
| GET | `/leasing/leases/{id}` | Get one lease, including its TI schedule and tax statements | GSAAdmin, GSALeasingOfficer, GSAPropertyManager, AgencyManager, LessorRep |
| GET | `/leasing/leases` | List leases, optionally filtered by `requirement_id`, `building_id`, `agency_id`, `offer_id`, `succeeds_lease_id`, and `status` | GSAAdmin, GSALeasingOfficer, GSAPropertyManager, AgencyManager, LessorRep |
| POST | `/leasing/leases/{id}/commence` | Commence an awarded lease; fixes the term window and TI amortization schedule | GSALeasingOfficer |
| POST | `/leasing/leases/{id}/tax-statements` | Record an annual actual-tax statement from the lessor | GSALeasingOfficer |
| POST | `/leasing/leases/{id}/expiration-plans` | Open an expiration plan for a lease | GSALeasingOfficer |
| GET | `/leasing/leases/{id}/expiration-plans` | List expiration plans of a lease | GSAAdmin, GSALeasingOfficer, GSAPropertyManager, AgencyManager, LessorRep |
| POST | `/leasing/expiration-plans/{id}/select-option` | Score all three expiration options and record the selected option | GSALeasingOfficer |
| POST | `/leasing/expiration-plans/{id}/execute` | Execute the selected option, creating its successor artifacts | GSALeasingOfficer |
| POST | `/leasing/occupancy-agreements` | Establish an occupancy agreement over leased or owned space | GSALeasingOfficer |
| GET | `/leasing/occupancy-agreements/{id}` | Get one occupancy agreement | GSAAdmin, GSALeasingOfficer, GSAPropertyManager, AgencyManager, LessorRep |
| GET | `/leasing/occupancy-agreements` | List occupancy agreements, optionally filtered by `lease_id`, `building_id`, `agency_id`, and `status` | GSAAdmin, GSALeasingOfficer, GSAPropertyManager, AgencyManager, LessorRep |
| POST | `/leasing/occupancy-agreements/{id}/activate` | Tenant agency signs the agreement | AgencyManager |
| POST | `/leasing/occupancy-agreements/{id}/terminate` | Terminate an agreement early; releases space and runs the terminal cascade | GSALeasingOfficer |
| POST | `/leasing/occupancy-agreements/{id}/amend` | Amend an `ACTIVE` agreement (OCC-guarded): square footage, term, or owned-space rates | GSALeasingOfficer |
| POST | `/leasing/occupancy-agreements/{id}/bills` | Generate the rent bill for a billing month | GSAPropertyManager |
| GET | `/leasing/occupancy-agreements/{id}/bills` | List rent bills of an agreement, optionally filtered by `status` | GSAAdmin, GSALeasingOfficer, GSAPropertyManager, AgencyManager, LessorRep |
| POST | `/leasing/rent-bills/{id}/pay` | Pay all or part of a bill | AgencyManager |
| POST | `/leasing/occupancy-agreements/{id}/alteration-requests` | Request a space alteration during the term | AgencyManager |
| GET | `/leasing/occupancy-agreements/{id}/alteration-requests` | List alteration requests of an agreement, optionally filtered by `status` | GSAAdmin, GSALeasingOfficer, GSAPropertyManager, AgencyManager, LessorRep |
| POST | `/leasing/alteration-requests/{id}/estimate` | Price an alteration and propose the work window | GSAPropertyManager |
| POST | `/leasing/alteration-requests/{id}/approve` | Approve the estimate and choose the funding method | AgencyManager |
| POST | `/leasing/alteration-requests/{id}/revise` | Send an estimate back for revised scope (OCC-guarded); clears the pending estimate | AgencyManager |
| POST | `/leasing/alteration-requests/{id}/complete` | Record completion; amortized alterations get their schedule | GSAPropertyManager |
| POST | `/leasing/alteration-requests/{id}/cancel` | Cancel a non-terminal alteration; a pending lump-sum charge is reversed | AgencyManager |
| POST | `/leasing/buildings/{id}/service-tickets` | Report a maintenance, security, or cleaning issue in leased or owned space | AgencyManager, GSAPropertyManager |
| GET | `/leasing/buildings/{id}/service-tickets` | List service tickets of a building, optionally filtered by `status` | GSAAdmin, GSALeasingOfficer, GSAPropertyManager, AgencyManager, LessorRep |
| POST | `/leasing/service-tickets/{id}/resolve` | Mark a ticket resolved; stamps `resolved_at` from the logical clock | GSAPropertyManager |
| POST | `/leasing/service-tickets/{id}/verify` | Tenant agency verifies the resolution; an SLA breach posts a service credit | AgencyManager |
| POST | `/leasing/occupancy-agreements/{id}/utilization-surveys` | Record a utilization measurement against an `ACTIVE` agreement | GSAPropertyManager |
| GET | `/leasing/occupancy-agreements/{id}/utilization-surveys` | List utilization surveys of an agreement | GSAAdmin, GSALeasingOfficer, GSAPropertyManager, AgencyManager, LessorRep |
| POST | `/leasing/utilization-surveys/{id}/finalize` | Finalize a survey; computes the utilization rate and auto-proposes a reduction below threshold | GSAPropertyManager |
| GET | `/leasing/occupancy-agreements/{id}/space-reduction-actions` | List space reduction actions of an agreement, optionally filtered by `status` | GSAAdmin, GSALeasingOfficer, GSAPropertyManager, AgencyManager, LessorRep |
| POST | `/leasing/space-reduction-actions/{id}/approve` | Approve a proposed space reduction (segregated from proposal and execution) | GSAAdmin |
| POST | `/leasing/space-reduction-actions/{id}/execute` | Execute an approved reduction; amends the agreement down and releases the space | GSAPropertyManager |
| POST | `/_clock/set_current_utc` | Set the logical clock and sweep time-based transitions | GSAAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error live in the narratives of §2 and §3; this table is the canonical id-to-status mapping only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_AGENCY_SCOPE_VIOLATION` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE_TRANSITION` | 409 Conflict |
| `ERR_REQUIREMENT_NOT_SOLICITING` | 409 Conflict |
| `ERR_LEASE_NOT_COMMENCED` | 409 Conflict |
| `ERR_LEASE_NOT_EXPIRING` | 409 Conflict |
| `ERR_OA_NOT_ACTIVE` | 409 Conflict |
| `ERR_SECURITY_LEVEL_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_OFFER_EXPIRED` | 422 Unprocessable Entity |
| `ERR_COMMENCEMENT_OUT_OF_WINDOW` | 422 Unprocessable Entity |
| `ERR_BILL_MONTH_OUT_OF_TERM` | 422 Unprocessable Entity |
| `ERR_OPTION_DEADLINE_PASSED` | 422 Unprocessable Entity |
| `ERR_ALTERATION_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_OA_TENANCY_AMBIGUOUS` | 422 Unprocessable Entity |
| `ERR_BUILDING_NOT_OWNED` | 422 Unprocessable Entity |
| `ERR_OA_TERM_EXCEEDS_LEASE` | 422 Unprocessable Entity |
| `ERR_BUILDING_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_LEASE_SPACE_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_BILL_ALREADY_EXISTS` | 409 Conflict |
| `ERR_PLAN_ALREADY_OPEN` | 409 Conflict |
| `ERR_DUPLICATE_TAX_YEAR` | 409 Conflict |
| `ERR_AMORTIZATION_WINDOW_TOO_SHORT` | 422 Unprocessable Entity |
| `ERR_PAYMENT_EXCEEDS_BALANCE` | 422 Unprocessable Entity |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
