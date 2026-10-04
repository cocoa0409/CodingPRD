# Certified Contractor Warranty API — Product Requirements Document

## 1. Introduction

A building-materials manufacturer operates a certified contractor program whose value proposition rests on a simple trade: contractors who complete training, maintain valid licensing and insurance, and demonstrate clean workmanship history gain access to enhanced warranty products they can sell to homeowners, while the manufacturer gains a vetted installation network and a defensible claim adjudication process. When a warranty claim arrives — a leaking roof, a premature shingle failure — the program must decide three things with rigor: was the failure a manufacturer defect or an installation error, how much money moves and from whose pocket, and whether the contractor's standing in the program should change as a result. Every one of those decisions is auditable, proration-driven, and sensitive to the exact dates, component mix, and tier held at installation time.

This document specifies the REST API that backs the program. It governs contractor onboarding and training credit accounting, certification issuance at the `BRONZE`, `SILVER`, and `GOLD` tiers, warranty registration with qualifying-system component matching, claim intake with photo evidence and optional independent inspection, determination-based remedy allocation between manufacturer, homeowner, and contractor, complaint-driven suspension and revocation of contractors, and distributor-to-contractor lead sharing under territory rules. All behavior is evaluated against a server-side logical clock so that time-dependent rules — proration schedules, complaint aging, training credit validity windows, certification expiry — are deterministic and testable.

## 2. Global Specifications & System-Wide Principles

This section defines the cross-cutting contracts and principles that apply uniformly across the API. Endpoint-specific behavior lives in §3 and §4.

### 2.1. User and Role-Based Access Control

Every request carries two mandatory headers: `X-User-ID` identifies the acting caller and `X-User-Role` names their operational role. The system recognizes five roles, spelled exactly as follows: `ProgramAdmin`, `Contractor`, `Distributor`, `Claimant`, and `Inspector`. A request missing either header, or presenting a role string outside this set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403); the permitted roles for every endpoint appear in §4.

The five roles differ in how `X-User-ID` binds to persisted resources. When `X-User-Role` is `Contractor`, `X-User-ID` is the `id` of the acting `Contractor` record; ownership checks on any resource that references a contractor — a certification application, a renewal, a warranty registration, a registration component line — compare the resource's `contractor_id` to `X-User-ID`, and a mismatch is rejected with `ERR_OWNERSHIP_MISMATCH` (HTTP 403). When `X-User-Role` is `Distributor`, `X-User-ID` is the `id` of the acting `Distributor` record; lead-assignment creation and return compare the resource's `distributor_id` to `X-User-ID` under the same `ERR_OWNERSHIP_MISMATCH` rule. When `X-User-Role` is `Inspector`, `X-User-ID` is an opaque inspector identifier not tied to any persisted entity of its own; it is compared against the `inspector_id` stored on an inspection order at schedule time, and only the assigned inspector may complete that order. When `X-User-Role` is `ProgramAdmin` or `Claimant`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity and not compared to any entity's `id`.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and any supplied value must fall between 1 and 100 inclusive. The `offset` parameter specifies how many items to skip and defaults to 0. Unless otherwise specified, list endpoints return resources sorted by `created_at` ascending. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every top-level resource in this API — `Contractor`, `TrainingCourse`, `TrainingEnrollment`, `Certification`, `ComponentCatalogItem`, `WarrantyRegistration`, `RegistrationComponent`, `WarrantyClaim`, `InspectionOrder`, `RemedyAllocation`, `Complaint`, `Distributor`, and `LeadAssignment` — carries a standard set of system-managed fields:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): starts at 1 on creation and increments on every mutation, including cascaded state changes triggered by the system rather than by a direct client write.

Cascaded transitions count as mutations: when a complaint cascade suspends a certification, that certification's `version` increments and its `updated_at` refreshes even though no client wrote to it directly.

### 2.5. The Logical Clock

All date-sensitive evaluation — certification validity windows, training credit aging, proration year counting, complaint aging, insurance and license expiry checks — runs against a server-side logical clock, never against wall-clock time. At server startup, before any client interaction, the logical clock reads exactly `2026-09-01T00:00:00Z`. A `ProgramAdmin` advances it through an admin-only clock-setting capability that accepts a `to_iso8601` instant; the response reports the new `current_utc`. Two automatic side effects ride on every clock advance, described in §3.2 and §3.7: certifications whose validity has lapsed are expired lazily, and suspended contractors whose recomputed complaint pattern has cooled are reinstated.

### 2.6. Monetary Values, Precision, and Rounding

All money in the system is carried as integer cents — never fractional units, never strings. Cost inputs such as `material_cost_cents` and `claim_labor_cost_cents` are integers of cents and must be zero or greater. Every computed monetary value — the prorated material pool, the manufacturer-paid material and labor amounts, the homeowner share, the contractor liability — is likewise an integer number of cents. Wherever a calculation produces a fraction of a cent, the value is rounded half up to a whole cent at that step, before the next step consumes it. Training credits, workmanship scores, complaint pattern scores, and completed-year counts are all integers with no rounding step.

### 2.7. Optimistic Concurrency Control

Two write operations in the system are guarded by optimistic concurrency control, and only those two. Adjudicating a claim requires the request to carry `expected_claim_version`, equal to the claim's current `version` as last observed by the caller; if the claim's version has advanced since that observation — for example because an evidence submission or the automatic transition into evidence review incremented it — the adjudication is rejected with `ERR_STALE_CLAIM_VERSION` (HTTP 412), so a remedy allocation is never computed from a claim the adjudicator has not seen. Renewing a certification requires `expected_certification_version` matching the certification's current `version`; a mismatch is rejected with `ERR_STALE_CERTIFICATION_VERSION` (HTTP 412). Endpoints not named here do not accept a version field at all.

### 2.8. Validation Ordering

When a single request could fail for several reasons, checks are applied in a fixed priority order so the returned error is deterministic. Authentication and role permission checks come first (`ERR_UNAUTHENTICATED`, then `ERR_FORBIDDEN`), with entity-ownership checks (`ERR_OWNERSHIP_MISMATCH`) sharing that auth tier. Request-shape validation follows (`ERR_INVALID_REQUEST`), then existence of every referenced resource, validated left to right along path and body references (`ERR_RESOURCE_NOT_FOUND`). State-eligibility checks come next — that the requested transition exists from the entity's current state (`ERR_INVALID_STATE`), and the standing checks `ERR_CONTRACTOR_SUSPENDED`, `ERR_CERTIFICATION_NOT_ACTIVE`, and `ERR_REGISTRATION_NOT_ACTIVE` — followed by the two optimistic-concurrency rejections (`ERR_STALE_CLAIM_VERSION`, `ERR_STALE_CERTIFICATION_VERSION`). Temporal compliance checks (`ERR_INSURANCE_EXPIRED`, `ERR_LICENSE_EXPIRED`) are evaluated after state checks, and finally the business-constraint tier: training credit sufficiency, photo evidence sufficiency, inspection completeness, required-component presence, duplicate component types, catalog existence, tier and territory eligibility, territory window overlap, inspector capacity, and lead pool availability.

### 2.9. Account Standing and Compliance Cascades

A contractor's standing is a computed property, not a stored opinion. Substantiated complaints decay in weight as they age; certifications hang off the contractor and are suspended or revoked in cascade when the contractor's standing collapses; warranty registrations in turn hang off certifications and are voided when a revocation cascade reaches them. The full cascade rules and their thresholds live in §3.7; the principle here is that the server, not the client, performs these transitions, and each cascaded transition increments the affected resource's `version` and refreshes `updated_at`. Cascades never run backward automatically: a reinstated contractor does not resurrect suspended certifications — each certification must be individually reinstated.

### 2.10. Nested Resource Retrieval

Requests that reference several resources — whether nested in the path or chained through body references — are validated left to right. The first reference that does not resolve to an existing resource terminates the request with `ERR_RESOURCE_NOT_FOUND` (HTTP 404), and the error message names the type of the missing resource. Existence is established before any state or business rule of a deeper resource is evaluated, so a request against a nonexistent certification never surfaces a rule about the registration beneath it.

## 3. Business Logic & Workflows

### 3.1. Contractor Onboarding, Compliance Records, and Training

A `ProgramAdmin` registers a new contractor by supplying the firm's `legal_name`, its `license_number`, the `license_expiry` date, the `insurance_expiry` date for its liability coverage, and the `territory_codes` list naming every territory the contractor serves. Dates are supplied in `YYYY-MM-DD` form. A fresh contractor record begins with `status` of `ACTIVE`, a `workmanship_score` of 100, a `complaint_score_24mo` of 0, a `lifetime_substantiated_count` of 0, and an `outstanding_liability_cents` of 0. A contractor's `status` takes one of `ACTIVE`, `SUSPENDED`, or `REVOKED`; `REVOKED` is terminal. Compliance fields drift over time as licenses and insurance renew, so a `ProgramAdmin` may later update `license_number`, `license_expiry`, or `insurance_expiry` — any subset of the three — through the contractor compliance update; each such update increments the contractor's `version`. Fetching a contractor exposes all of the computed standing fields alongside the input fields.

Training is tracked as courses and enrollments. A `ProgramAdmin` creates a training course with a `title`, the `credits` it grants on completion, and a `validity_months` window stating how long a completion remains creditable. Enrolling a contractor in a course creates an enrollment row referencing the `contractor_id` and `course_id`, starting in `ENROLLED` status. Marking the enrollment finished requires a `completed_at` date and moves it to `COMPLETED`; the completion call increments the enrollment's `version`. Enrollments can be listed with optional filters on `contractor_id`, `course_id`, and `status`, plus `limit` and `offset` pagination.

Creditable training at any evaluation date is the sum of `credits` over the contractor's `COMPLETED` enrollments whose completion has not aged out: an enrollment counts when its `completed_at` date, advanced by the course's `validity_months`, is on or after the evaluation date — the boundary month still counts, because the comparison is inclusive. This creditable total is what the certification verify and renew checks consume in §3.2.

### 3.2. Certification Tiers, Verification, Renewal, and Expiry

A contractor joins the program by applying for a certification at one of three tiers — `BRONZE`, `SILVER`, or `GOLD`, which rank in that order with `BRONZE` the lowest and `GOLD` the highest. The applying call carries the `contractor_id` and the requested `tier`; a `Contractor` caller may apply only for itself, meaning the supplied `contractor_id` must equal the caller's `X-User-ID`, while a `ProgramAdmin` may apply on a contractor's behalf. The contractor must be `ACTIVE` at application time — a `SUSPENDED` or `REVOKED` contractor is refused with `ERR_CONTRACTOR_SUSPENDED` (HTTP 409). A new certification begins in `PENDING_VERIFICATION`.

Verification is a `ProgramAdmin` decision. Approving moves the certification from `PENDING_VERIFICATION` to `ACTIVE` and is gated by four checks evaluated at the current clock date, in the order stated: the contractor's `status` must be `ACTIVE` (else `ERR_CONTRACTOR_SUSPENDED`), the contractor's `insurance_expiry` must be strictly later than the current clock date (else `ERR_INSURANCE_EXPIRED`, HTTP 422), the contractor's `license_expiry` must be strictly later than the current clock date (else `ERR_LICENSE_EXPIRED`, HTTP 422), and the contractor's creditable training total at the current clock date must meet the tier minimum — 4 credits for `BRONZE`, 8 for `SILVER`, 12 for `GOLD` (else `ERR_INSUFFICIENT_TRAINING_CREDITS`, HTTP 422). On approval the certification records `valid_from` as the current clock date and `valid_until` as `valid_from` advanced by 24 months, and the certification's `version` increments. Denying instead moves the certification to `DENIED`, a terminal state; a denial carries no compliance checks and simply increments the certification's `version`. Either decision is supplied in the `decision` field as `APPROVE` or `DENY`.

Renewal extends an `ACTIVE` certification. The contractor itself performs the renewal — and only for its own certification — and the renewal is only possible while the certification is still `ACTIVE`; once validity has lapsed the certification is `EXPIRED` and renewal no longer exists as a transition, so attempting it is rejected with `ERR_INVALID_STATE` (HTTP 409). Renewal re-runs the same standing checks as approval at the current clock date: contractor `ACTIVE`, `insurance_expiry` strictly later than the clock date, `license_expiry` strictly later than the clock date, and creditable training at or above the tier minimum, surfacing `ERR_CONTRACTOR_SUSPENDED`, `ERR_INSURANCE_EXPIRED`, `ERR_LICENSE_EXPIRED`, or `ERR_INSUFFICIENT_TRAINING_CREDITS` as applicable. Renewal is one of the two optimistic-concurrency-guarded writes described in §2.7: the request must carry `expected_certification_version` matching the certification's current `version`, or it is rejected with `ERR_STALE_CERTIFICATION_VERSION` (HTTP 412). A successful renewal extends `valid_until` by a further 24 months — measured from the prior `valid_until`, not from the renewal date — and increments the certification's `version`.

Expiry is lazy. Whenever a certification is read, and whenever the logical clock advances, any certification in `ACTIVE` whose `valid_until` is strictly earlier than the current clock date transitions to `EXPIRED` — a terminal state — with its `version` incremented. A certification can also leave `ACTIVE` by cascade: the complaint-driven suspension cascade of §3.7 moves it to `SUSPENDED`, and the revocation cascade moves it to `REVOKED`. A `SUSPENDED` certification returns to `ACTIVE` only through an individual reinstatement by a `ProgramAdmin`, which requires the contractor to be `ACTIVE` (else `ERR_CONTRACTOR_SUSPENDED`) and the contractor's `insurance_expiry` to be strictly later than the current clock date (else `ERR_INSURANCE_EXPIRED`); reinstatement increments the certification's `version`. Notably, reinstatement does not re-check the license or the training credits — those gates belong to verification and renewal only. The terminal states of a certification are `DENIED`, `REVOKED`, and `EXPIRED`.

### 3.3. Warranty Registration, Component Matching, and Activation

The product catalog is administered by a `ProgramAdmin` as component catalog items, each carrying a manufacturer `sku` that is unique across the catalog, a `component_type` of `SHINGLE`, `UNDERLAYMENT`, `STARTER`, `RIDGE_CAP`, `VENTILATION`, or `OTHER`, and a `manufacturer` of `GAF` or `OTHER`.

An installation contractor registers a completed roof system by creating a warranty registration against one of its own certifications, supplying the `certification_id`, the `homeowner_name`, the `property_postal_code`, and the `install_date`. Registration creation is a `Contractor` self-service operation: the referenced certification must belong to the caller. The referenced certification must be `ACTIVE` and the `install_date` must fall within its validity — that is, on or before the certification's `valid_until` — or the creation is refused with `ERR_CERTIFICATION_NOT_ACTIVE` (HTTP 409). The `install_date` must also not lie in the future relative to the logical clock; a future date is a malformed request and is refused with `ERR_INVALID_REQUEST` (HTTP 400). A new registration starts in `DRAFT` with `coverage_class` of `DRAFT` until activation.

While the registration is in `DRAFT`, the contractor builds out its component bill of materials, one line at a time. Each line names the `registration_id`, a `catalog_sku`, and the installed `material_cost_cents` for that line (zero or more). The `catalog_sku` must match an existing catalog item or the line is refused with `ERR_CATALOG_ITEM_NOT_FOUND` (HTTP 404). At creation the line copies `component_type` and `manufacturer` from the referenced catalog item — these are snapshots, not live references. A registration may hold at most one line of any given `component_type`; a second line duplicating a type already present is refused with `ERR_DUPLICATE_COMPONENT_TYPE` (HTTP 409). Because activation locks the bill of materials, component lines can only be added to a `DRAFT` registration; attempting to add one to a registration in any other state is rejected with `ERR_INVALID_STATE`.

Activation is a `ProgramAdmin` action that converts the draft into an enforceable warranty. The activation re-confirms that the backing certification is still `ACTIVE` and that the `install_date` remains on or before the certification's `valid_until` (else `ERR_CERTIFICATION_NOT_ACTIVE`) and that the `install_date` is not after the current clock date (else `ERR_INVALID_REQUEST`). The bill of materials must then contain each of the four required component types — `SHINGLE`, `UNDERLAYMENT`, `STARTER`, and `RIDGE_CAP` — present exactly once each; a missing or duplicated required type is refused with `ERR_MISSING_REQUIRED_COMPONENT` (HTTP 422). On successful activation the registration records `activated_at` as the current clock timestamp — this timestamp is the base date from which proration years are later counted — snapshots `coverage_tier` from the certification's tier at that moment, and computes `coverage_class`: `QUALIFYING_SYSTEM` when every required-type component has `manufacturer` `GAF`, and `MIXED_MANUFACTURER` when any required-type component is `OTHER`-manufactured. Activation moves the registration from `DRAFT` to `ACTIVE` and increments its `version`. A registration's only other transition is to `VOID`, terminal, which happens exclusively through the contractor revocation cascade of §3.7.

### 3.4. Claim Intake and Photo Evidence

A `Claimant` — typically the homeowner — files a warranty claim against an `ACTIVE` registration, supplying the `registration_id`, a free-text `description` of the failure, and the `claim_labor_cost_cents` being claimed for repair labor (zero or more). Filing against a registration in any other state is refused with `ERR_REGISTRATION_NOT_ACTIVE` (HTTP 409). At intake the server stamps `filed_at` from the logical clock and snapshots the contractor's current `workmanship_score` into `filing_workmanship_score` — this snapshot exists so that the liability factor at adjudication time reflects the score the contractor held when the claim was filed, not a score that the adjudication itself may be about to mutate. A new claim begins in `SUBMITTED` with a `photo_count` of 0.

Evidence accrues item by item. Each evidence submission — by the `Claimant` or a `ProgramAdmin` — appends one entry carrying an `evidence_type` of `PHOTO`, `CORE_SAMPLE`, or `DOCUMENT` plus a free-text `note` to the claim's `evidence` list; the server stamps each entry with its `submitted_at` instant. The `evidence` list is append-only: entries are never edited or removed. Each submission recomputes `photo_count` as the number of entries whose `evidence_type` is `PHOTO` and increments the claim's `version`. When a submission raises `photo_count` to at least 2 while the claim is `SUBMITTED`, the claim automatically advances from `SUBMITTED` to `EVIDENCE_REVIEW`; claims already past `SUBMITTED` simply continue to accumulate evidence. Evidence may be appended while the claim is in any non-terminal state.

### 3.5. Independent Inspection

When photographic evidence alone cannot settle defect-versus-installation-error, a `ProgramAdmin` requests a core-sample or independent inspection. The first such request moves the claim from `EVIDENCE_REVIEW` to `INSPECTION_REQUESTED` and creates an inspection order in `REQUESTED` status, linked to the claim through the order's `claim_id`. Requesting again while the claim is in `INSPECTION_REQUESTED` creates an additional order — several inspectors may need to visit — without moving the claim's state. Each new order increments the claim's `version` as a side effect of the request.

Scheduling assigns an order to an inspector: a `ProgramAdmin` supplies the `inspector_id` — an opaque identifier for the inspector — and the `service_date`. An inspector may carry at most three `SCHEDULED` orders on a single `service_date`; scheduling a fourth order for the same `inspector_id` and `service_date` pair is refused with `ERR_INSPECTOR_CAPACITY_EXCEEDED` (HTTP 422). Scheduling moves the order from `REQUESTED` to `SCHEDULED` and increments the order's `version`.

Completion belongs to the assigned inspector and no one else: the completing call must present an `X-User-ID` equal to the order's `inspector_id`, or it is refused with `ERR_OWNERSHIP_MISMATCH`. The inspector supplies a narrative `findings` and a boolean `confirms_defect` stating whether the inspection confirms a manufacturer defect. Completion moves the order from `SCHEDULED` to `COMPLETED` — its terminal state — and increments the order's `version`. When the last outstanding order of a claim completes — that is, when no linked order remains in `REQUESTED` or `SCHEDULED` — the claim automatically advances from `INSPECTION_REQUESTED` to `INSPECTION_COMPLETED`, incrementing the claim's `version`.

### 3.6. Adjudication and the Remedy Split

Adjudication is the financial heart of the program. A `ProgramAdmin` adjudicates a claim that has reached `EVIDENCE_REVIEW` or `INSPECTION_COMPLETED` by supplying a `determination` of `MANUFACTURER_DEFECT`, `INSTALLATION_ERROR`, `MIXED`, or `NO_DEFECT`. Three gates guard the call, evaluated in the order stated. First, the claim's `photo_count` must be at least 2 — adjudicating on thinner photographic evidence is refused with `ERR_PHOTO_EVIDENCE_INSUFFICIENT` (HTTP 422). Second, no linked inspection order may remain in `REQUESTED` or `SCHEDULED` — adjudicating with inspection work outstanding is refused with `ERR_INSPECTION_INCOMPLETE` (HTTP 422). Third, the call must carry `expected_claim_version` matching the claim's current `version` under the optimistic-concurrency rule of §2.7, or it is refused with `ERR_STALE_CLAIM_VERSION` (HTTP 412).

A `NO_DEFECT` determination denies the claim: it moves to `DENIED`, terminal, no remedy allocation is created, and the claim's `version` increments. Any other determination resolves the claim: it moves to `RESOLVED`, and the system computes and persists a remedy allocation in `ACTIVE` status, splits the money, and updates the contractor's standing — in a pinned evaluation order, because the allocation must be fully computed and persisted before the score mutation it triggers is allowed to exist. The steps, in order:

1. **Age and schedule.** The completed years of coverage is the whole number of years between the registration's `activated_at` and the claim's `filed_at` — the day difference divided by 365, rounded down to a whole number, stored on the allocation as `completed_years`. The schedule applied is recorded as `schedule_used`: it is the tier's own schedule — `STANDARD` for `BRONZE`, `ENHANCED` for `SILVER`, `ENHANCED_PLUS` for `GOLD` — unless the registration's `coverage_class` is `MIXED_MANUFACTURER`, in which case the `STANDARD` schedule is forced regardless of tier.
2. **Material percentage.** Each schedule maps completed years to an integer percentage, recorded as `material_pct`. Under `STANDARD`, coverage is 100 percent in the first year and decays by 10 points for each year beyond the first, never falling below 20 percent. Under `ENHANCED`, coverage holds at 100 percent through the fifth year and decays by 5 points for each year beyond the fifth, never falling below 50 percent. Under `ENHANCED_PLUS`, coverage holds at 100 percent through the tenth year and decays by 2 points for each year beyond the tenth, never falling below 80 percent.
3. **Prorated material pool.** Each registration component line's `material_cost_cents` is multiplied by the schedule percentage and rounded half up to a whole cent per line; the pool `prorated_material_pool_cents` is the sum of those per-line rounded amounts. The per-line rounding before summation is pinned — rounding the sum instead is a different, incorrect algorithm.
4. **Determination share.** The determination maps to a share: 1.0 for `MANUFACTURER_DEFECT`, 0.5 for `MIXED`, 0.0 for `INSTALLATION_ERROR`.
5. **Manufacturer material coverage.** `material_covered_cents` is the determination share applied to the prorated material pool, rounded half up to a whole cent. `homeowner_material_share_cents` is the determination share applied to the remainder — the total installed material cost across all component lines minus the prorated pool — rounded half up to a whole cent.
6. **Labor coverage.** `labor_covered_cents` is zero whenever the registration is `MIXED_MANUFACTURER` — mixed systems carry no labor coverage at all. For `QUALIFYING_SYSTEM` registrations, labor coverage also expires with age: each tier covers labor for a fixed number of years — 2 years for `BRONZE`, 5 for `SILVER`, 10 for `GOLD` — and the gate is strict, so at the boundary year the coverage is already gone; a claim filed in or after the tier's labor year count receives zero labor coverage. Inside the window, `labor_covered_cents` is the determination share applied to the lesser of the claim's `claim_labor_cost_cents` and the tier's labor cap — 200000 cents for `BRONZE`, 500000 cents for `SILVER`, 1000000 cents for `GOLD` — rounded half up to a whole cent.
7. **Contractor liability.** The liability factor is read from a band of the claim's `filing_workmanship_score` — the intake snapshot, never the live score: 1.00 when the snapshot is 80 or higher, 1.10 when the snapshot is between 61 and 79 inclusive, and 1.25 when the snapshot is 60 or below. `contractor_liability_cents` is the complement of the determination share (one minus the share) applied to the sum of the total installed material cost and the `claim_labor_cost_cents`, then multiplied by that factor, rounded half up to a whole cent. Note the consequence: a `MANUFACTURER_DEFECT` claim carries zero contractor liability because the complement share is zero, while an `INSTALLATION_ERROR` claim places the fullest weight on the contractor.
8. **Standing mutation.** Only after the allocation is persisted does the system apply the workmanship delta to the contractor: minus 10 for `INSTALLATION_ERROR`, minus 4 for `MIXED`, and zero for `MANUFACTURER_DEFECT`, with the score never falling below its floor of 0. The delta actually applied is recorded on the allocation as `workmanship_delta_applied` so a later reopen knows exactly what to refund. The contractor's `outstanding_liability_cents` increases by the allocation's `contractor_liability_cents`. Finally, if the determination was `INSTALLATION_ERROR` or `MIXED` and the contractor's resulting `workmanship_score` is 60 or below, every `ACTIVE` certification of the contractor transitions to `SUSPENDED` — each with its `version` incremented. The claim's `version` increments.

Reopening unwinds a resolution. A `ProgramAdmin` may reopen a `RESOLVED` claim — the call carries a free-text `reason` — provided the claim still has a remedy allocation in `ACTIVE` status. Reopening moves that allocation to `REVERSED`, subtracts the allocation's `contractor_liability_cents` from the contractor's `outstanding_liability_cents`, refunds the workmanship penalty by subtracting the recorded `workmanship_delta_applied` from the score (a negative delta thus raises the score, which is capped at its ceiling of 100), returns the claim to `EVIDENCE_REVIEW`, and increments the claim's `version`. Reopening does not un-suspend certifications that the original adjudication suspended; those remain `SUSPENDED` until individually reinstated under §3.2.

The remedy allocation of a claim is retrievable as a list of zero or one element, exposing every computed figure: `determination`, `completed_years`, `schedule_used`, `material_pct`, `prorated_material_pool_cents`, `material_covered_cents`, `homeowner_material_share_cents`, `labor_covered_cents`, `contractor_liability_cents`, `workmanship_delta_applied`, and its own `status` of `ACTIVE` or `REVERSED`.

### 3.7. Complaints, Standing Scores, Suspension, and Revocation

Complaints against a contractor are filed by a `Claimant` or a `ProgramAdmin`, carrying the `contractor_id` and a `category` of `WORKMANSHIP`, `COMMUNICATION`, `PROPERTY_DAMAGE`, or `CONTRACT_DISPUTE`. The server stamps `filed_at` from the logical clock, and the complaint begins in `FILED` with `substantiated_at` unset. A `ProgramAdmin` then resolves each complaint one way or the other. Dismissal moves it to `DISMISSED` — terminal — with no effect on any score. Substantiation moves it to `SUBSTANTIATED` — also terminal — stamps `substantiated_at` from the clock, and triggers the standing recompute described next.

Two contractor-risk metrics answer two different questions from the same set of substantiated complaints. The weighted trailing score asks "is this contractor currently a problem?": each substantiated complaint's age in months is the day difference between its `filed_at` and the current clock, divided by 30 and rounded down to a whole number; a complaint aged 6 months or less weighs 3 points, one aged 7 through 12 months weighs 2, one aged 13 through 24 months weighs 1, and one older than 24 months weighs nothing at all. The sum of these weights over all substantiated complaints is the contractor's `complaint_score_24mo`. The lifetime count asks "has this contractor ever been a persistent problem?": `lifetime_substantiated_count` is the plain count of all substantiated complaints with no time window, so a contractor whose complaints are all ancient has a weighted score of 0 yet still accrues toward the lifetime threshold.

Substantiating a complaint applies three immediate mutations, in this order: the contractor's `workmanship_score` drops by 5 (never below its floor of 0), the `lifetime_substantiated_count` rises by 1, and the `complaint_score_24mo` is recomputed against the current clock. Two thresholds then act, lifetime first: if the `lifetime_substantiated_count` has reached 8, the contractor is `REVOKED` — terminal — and the revocation cascade fires. Otherwise, if the recomputed weighted score has reached 5 and the contractor is currently `ACTIVE`, the contractor is `SUSPENDED` and the suspension cascade fires. The suspension cascade moves every `ACTIVE` certification of the contractor to `SUSPENDED` — each with its `version` incremented — and returns every `ASSIGNED` lead assignment of the contractor to `RETURNED`, recomputing each owning distributor's `lead_pool_available`. The revocation cascade is wider: every certification of the contractor in `ACTIVE` or `SUSPENDED` moves to `REVOKED`, every warranty registration reached through those certifications that is currently `ACTIVE` moves to `VOID`, and every `ASSIGNED` lead assignment returns to `RETURNED` with the distributor pool recomputed — each affected resource with its `version` incremented and `updated_at` refreshed.

Suspension is not necessarily permanent, but reinstatement is a clock event, not a complaint event. Whenever the logical clock advances, the server re-evaluates every `SUSPENDED` contractor whose `lifetime_substantiated_count` is still below 8: the weighted score is recomputed at the new clock, and if it has decayed below 5 the contractor returns to `ACTIVE`. This is the only route out of suspension. Reinstatement of the contractor does not reinstate its certifications — certifications suspended by the complaint cascade stay `SUSPENDED` until individually reinstated under §3.2 — and it does not restore returned lead assignments.

### 3.8. Distributor Lead Sharing and Territory Rules

Distributors feed work into the certified network. A `ProgramAdmin` creates a distributor with a `name`, the `territory_codes` it covers, and a `lead_pool_total` granting that many lead slots (zero or more). The pool's remaining capacity, `lead_pool_available`, is computed as `lead_pool_total` minus the number of the distributor's lead assignments currently in `ASSIGNED` status; it is recomputed every time an assignment is created or returned.

A `Distributor` assigns a lead to a contractor from its own pool, supplying the `distributor_id` — which must be the caller's own id — the `contractor_id`, the `territory_code` the lead covers, the `required_tier` of `BRONZE`, `SILVER`, or `GOLD` that the lead demands, and a half-open service window from `start_date` (inclusive) to `end_date` (exclusive, and strictly later than `start_date`, or the request is malformed with `ERR_INVALID_REQUEST`). The assignment is refused with `ERR_TIER_REQUIREMENT_NOT_MET` (HTTP 422) unless all of the following hold: the contractor is `ACTIVE` (a non-active contractor surfaces `ERR_CONTRACTOR_SUSPENDED` instead), the `territory_code` appears in both the distributor's and the contractor's `territory_codes`, and the contractor holds an `ACTIVE` certification whose tier ranks at or above the `required_tier`. The window must not overlap any existing `ASSIGNED` assignment of the same distributor and `territory_code`; overlap is judged on the half-open interval, so two windows that merely touch — one's `end_date` equal to the other's `start_date` — do not conflict, while any positive overlap is refused with `ERR_TERRITORY_OVERLAP` (HTTP 409). Finally, the pool itself must not be empty: assigning when `lead_pool_available` is 0 is refused with `ERR_LEAD_POOL_EMPTY` (HTTP 422). A created assignment begins in `ASSIGNED` and decrements the pool.

Returning a lead is the distributor's call: the owning `Distributor` returns an assignment, moving it from `ASSIGNED` to `RETURNED` — terminal — and the pool's `lead_pool_available` is recomputed, rising by 1. Returns also arrive by cascade from §3.7 when a contractor is suspended or revoked; the pool math is identical regardless of who initiated the return. Lead assignments are listable with optional filters on `distributor_id`, `contractor_id`, and `status`, plus `limit` and `offset` pagination, and each assignment is individually retrievable.

## 4. Endpoint Definitions

Operations that create a new resource — registering a contractor, filing a claim, adding a component line, and the like — return `201 Created`. Operations that act on an existing resource without creating a new one — state transitions, evidence appends that return the parent claim, compliance updates, clock advancement — return `200 OK`. All endpoints are mounted under the `/program` prefix. Request and response bodies for every endpoint are reconstructed from the narratives of §3; this table is only an index of method, path, summary, and authorization.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/program/_clock/set_current_utc` | Advance the logical clock; lazily expires certifications and re-evaluates suspended contractors | ProgramAdmin |
| POST | `/program/contractors` | Register a contractor | ProgramAdmin |
| GET | `/program/contractors/{id}` | Fetch a contractor including computed scores and liability | ProgramAdmin, Contractor, Distributor |
| PATCH | `/program/contractors/{id}/compliance` | Update license and insurance compliance fields | ProgramAdmin |
| GET | `/program/contractors/{id}/certifications` | List a contractor's certifications | ProgramAdmin, Contractor |
| GET | `/program/contractors/{id}/complaints` | List complaints filed against a contractor | ProgramAdmin |
| POST | `/program/training-courses` | Create a training course | ProgramAdmin |
| POST | `/program/training-enrollments` | Enroll a contractor in a course | ProgramAdmin |
| GET | `/program/training-enrollments/{id}` | Fetch one enrollment | ProgramAdmin, Contractor |
| GET | `/program/training-enrollments` | List enrollments with pagination and filters | ProgramAdmin, Contractor |
| POST | `/program/training-enrollments/{id}/complete` | Mark an enrollment completed | ProgramAdmin |
| POST | `/program/certifications` | Apply for a certification tier | Contractor, ProgramAdmin |
| GET | `/program/certifications/{id}` | Fetch a certification | ProgramAdmin, Contractor |
| POST | `/program/certifications/{id}/verify` | Approve or deny a pending certification | ProgramAdmin |
| POST | `/program/certifications/{id}/reinstate` | Reinstate a suspended certification | ProgramAdmin |
| POST | `/program/certifications/{id}/renew` | Renew an active certification for 24 more months; OCC-guarded | Contractor |
| GET | `/program/certifications/{id}/warranty-registrations` | List registrations under a certification | ProgramAdmin, Contractor |
| POST | `/program/component-catalog-items` | Add a component catalog item | ProgramAdmin |
| POST | `/program/warranty-registrations` | Register an installed system under an active certification | Contractor |
| GET | `/program/warranty-registrations/{id}` | Fetch a registration | ProgramAdmin, Contractor, Claimant |
| POST | `/program/warranty-registrations/{id}/activate` | Activate a draft registration | ProgramAdmin |
| GET | `/program/warranty-registrations/{id}/components` | List component lines of a registration | ProgramAdmin, Contractor |
| GET | `/program/warranty-registrations/{id}/claims` | List claims on a registration | ProgramAdmin, Contractor, Claimant |
| POST | `/program/registration-components` | Add a component line to a draft registration | Contractor |
| POST | `/program/warranty-claims` | File a warranty claim | Claimant |
| GET | `/program/warranty-claims/{id}` | Fetch a claim | ProgramAdmin, Contractor, Claimant |
| POST | `/program/warranty-claims/{id}/evidence` | Append one evidence item | Claimant, ProgramAdmin |
| POST | `/program/warranty-claims/{id}/request-inspection` | Request an independent inspection | ProgramAdmin |
| GET | `/program/warranty-claims/{id}/inspection-orders` | List inspection orders of a claim | ProgramAdmin, Contractor |
| POST | `/program/warranty-claims/{id}/adjudicate` | Adjudicate a claim; OCC-guarded | ProgramAdmin |
| POST | `/program/warranty-claims/{id}/reopen` | Reopen a resolved claim and reverse its remedy | ProgramAdmin |
| GET | `/program/warranty-claims/{id}/remedy-allocation` | List the claim's remedy allocations | ProgramAdmin, Contractor, Claimant |
| POST | `/program/inspection-orders/{id}/schedule` | Schedule an inspection order to an inspector | ProgramAdmin |
| POST | `/program/inspection-orders/{id}/complete` | Assigned inspector completes the order | Inspector |
| POST | `/program/complaints` | File a complaint against a contractor | Claimant, ProgramAdmin |
| POST | `/program/complaints/{id}/substantiate` | Substantiate a complaint and trigger standing recompute | ProgramAdmin |
| POST | `/program/complaints/{id}/dismiss` | Dismiss a complaint | ProgramAdmin |
| POST | `/program/distributors` | Create a distributor with a lead pool | ProgramAdmin |
| GET | `/program/distributors/{id}` | Fetch a distributor including available pool | ProgramAdmin, Distributor |
| POST | `/program/lead-assignments` | Assign a territory lead to a certified contractor | Distributor |
| POST | `/program/lead-assignments/{id}/return` | Return a lead to the pool | Distributor |
| GET | `/program/lead-assignments` | List lead assignments with pagination and filters | ProgramAdmin, Distributor |
| GET | `/program/lead-assignments/{id}` | Fetch one lead assignment | ProgramAdmin, Distributor |

## 5. Error Code Catalogue

The conditions that raise each error are described in §2 and §3 alongside the workflows they guard; this table is only an index of identifiers and status codes.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_OWNERSHIP_MISMATCH` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_RESOURCE_NOT_FOUND` | 404 |
| `ERR_CATALOG_ITEM_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_CONTRACTOR_SUSPENDED` | 409 |
| `ERR_CERTIFICATION_NOT_ACTIVE` | 409 |
| `ERR_REGISTRATION_NOT_ACTIVE` | 409 |
| `ERR_STALE_CLAIM_VERSION` | 412 |
| `ERR_STALE_CERTIFICATION_VERSION` | 412 |
| `ERR_INSURANCE_EXPIRED` | 422 |
| `ERR_LICENSE_EXPIRED` | 422 |
| `ERR_INSUFFICIENT_TRAINING_CREDITS` | 422 |
| `ERR_PHOTO_EVIDENCE_INSUFFICIENT` | 422 |
| `ERR_INSPECTION_INCOMPLETE` | 422 |
| `ERR_MISSING_REQUIRED_COMPONENT` | 422 |
| `ERR_DUPLICATE_COMPONENT_TYPE` | 409 |
| `ERR_TIER_REQUIREMENT_NOT_MET` | 422 |
| `ERR_TERRITORY_OVERLAP` | 409 |
| `ERR_INSPECTOR_CAPACITY_EXCEEDED` | 422 |
| `ERR_LEAD_POOL_EMPTY` | 422 |
