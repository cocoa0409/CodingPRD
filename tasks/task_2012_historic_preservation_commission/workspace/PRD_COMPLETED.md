# Historic Preservation API — Product Requirements Document

## 1. Introduction

A municipal historic preservation commission exists to protect the character of its designated districts, and its instrument for doing so is the Certificate of Appropriateness: no exterior alteration, addition, new construction, relocation, or demolition may lawfully proceed within a designated district without one. The commission's day-to-day reality is a long chain of judgment calls — is an application complete, does it rise to a public hearing, which design guideline set applies, was the public properly notified, has a demoliable building earned a reprieve through economic hardship — and every one of those calls must be defensible under audit, consistent with precedent, and enforceable against property owners who act without permission.

This document specifies the Historic Preservation API, the system of record for that entire chain. It governs the property inventory and district boundaries, the design guideline sets that decisions cite, application intake with costed work items, the threshold logic that routes an application to a staff decision or a commission hearing, hearing notice and public comment, approval conditions, appeals to the city council, demolition delay and hardship review, violation enforcement with after-the-fact legalization, and the certificates that finally authorize work. Because every deadline in preservation law is litigable, the API evaluates all windows and deadlines against an explicit logical clock rather than wall-clock time; because every fee and penalty is auditable to the cent, all money is integer cents with pinned rounding; and because the district's contributing census is a legal statistic, it is protected by optimistic concurrency where a stale write could corrupt it.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a set of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes five distinct roles: `Applicant`, `PreservationStaff`, `Commissioner`, `CouncilMember`, and `EnforcementOfficer`. A request missing either header, or carrying a role value outside this declared set, is rejected with `ERR_UNAUTHENTICATED`. Access to specific operations is further restricted by role, per the endpoint authorization lists in §4; an attempt to perform an action outside the caller's designated role, or an `Applicant` attempt to act on another owner's application or appeal, is rejected with `ERR_FORBIDDEN_ROLE`.

Role identity is resolved in one of two ways. When `X-User-Role` is `Applicant`, `X-User-ID` is the `id` of the acting `PropertyOwner`; ownership checks on any resource that references a `PropertyOwner` compare the resource's foreign-key field to `X-User-ID`. When `X-User-Role` is `PreservationStaff`, `Commissioner`, `CouncilMember`, or `EnforcementOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `completeness_accepted_by` on an application whose completeness was accepted by that staff user) but does not compare it to any entity's `id`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0. A `limit` that is not an integer, is below 1, or exceeds 100, and an `offset` that is not an integer or is negative, are rejected with `ERR_VALIDATION`.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order, with ties broken by creation order.

Paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

All primary resources — districts, guideline sets, owners, properties, applications, meetings, hearings, appeals, violations, demolition delays, hardship reviews, and certificates — carry a standard set of system-managed fields:

- `id` (string): a unique, server-generated identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 timestamp in UTC with three fractional digits (e.g., `2025-05-24T10:30:00.123Z`), set when the resource is first created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed upon any change to the resource's properties.
- `version` (integer): a system-managed integer that starts at 1 when the resource is created and increments with every modification to the resource, including mutations performed as cascading side effects of operations on other resources.

A public comment is the single exception: it is an immutable record of testimony and carries only `id` and `created_at`. Both `updated_at` and `version` are absent from a comment, since a comment is never modified after submission.

### 2.5. The Logical Clock

The server maintains a logical clock, and every deadline, window, accrual, and timestamped side effect in this document is evaluated against that logical clock — never against wall-clock time. Before any client call, the logical clock starts at exactly `2026-08-01T00:00:00Z`; an administrative test-driving capability, available to every role, advances it by accepting a `to_iso8601` instant and reporting the resulting `current_utc`. Once set, the logical clock must not fall back to wall-clock time. Two state transitions in the system are lazy: they are not fired by a timer but are evaluated whenever the logical clock is consulted on the resource — see the demolition-delay expiry rule in §3.7. The logical clock governs the business timestamps named in §3 — `returned_at`, `decided_at`, `adopted_at`, `submitted_at`, `filed_at`, `notice_issued_at`, `compliance_verified_at`, `referred_at`, `issued_at`, `completed_at`, and the demolition-delay boundaries — while each resource's `created_at` and `updated_at` and the envelope's `api_request_timestamp` are rendered from wall-clock time. Timestamps derived from the logical clock render in UTC at the precision the clock was set with: a second-precision instant renders without fractional digits, a millisecond-precision instant with three fractional digits, and a finer setting with six.

### 2.6. Monetary Values: Integer Cents and Pinned Rounding

All monetary values in the system — fees, penalties, assessed values, payments, refunds — are represented as integer numbers of cents; there are no fractional cents anywhere in the API. Wherever a computation produces a non-integer cent amount, the result is rounded half-up to a whole cent. Where a computation is built from per-component amounts (as the application fee is), the rounding order stated with that computation is normative: components are rounded first and then summed, and reordering the rounding is a specification violation even when the difference is a single cent. Derived monetary fields are recomputed from their declared inputs at the moments §3 names, never edited directly.

### 2.7. Optimistic Concurrency on Property Reclassification

Exactly one write in the system is guarded by optimistic concurrency control: reclassifying a property's contributing status. The reclassification request must carry `expected_property_version`, holding the `version` of the property as the client last observed it; the field is non-optional on that operation. If the value does not match the property's current `version`, the request is rejected with `ERR_STALE_PROPERTY_VERSION` (HTTP 412), and the version check runs before any state or business evaluation of the write. The reason this one write is guarded is the district contributing census: a reclassification legitimately mutates the property's `version` and the district's counters, so a writer carrying a stale property version would otherwise apply a duplicate census delta (§2.9). No other endpoint accepts or requires a version field.

### 2.8. The Request Gatekeeping Pipeline

Every request passes through a fixed sequence of validation layers. The layers are evaluated in the order below, and a failure at an earlier layer masks every later layer: the response carries the first failing layer's error, and no later layer is evaluated.

1. **Request shape and authentication.** The `X-User-ID` and `X-User-Role` headers must be present and the role must be one of the five declared roles, or the request fails with `ERR_UNAUTHENTICATED`. Malformed bodies, missing required fields, wrong-typed values, and enum values outside the declared sets are rejected at this same outermost layer with `ERR_VALIDATION`. Within this layer, header authentication is evaluated before body-shape validation.
2. **Authorization.** The caller's role must appear in the endpoint's allowed-role list, and for `Applicant` actions on an existing application or appeal the caller's `X-User-ID` must equal the application's `owner_id`; failures are rejected with `ERR_FORBIDDEN_ROLE`. The ownership comparison is evaluated as soon as the owner identity is available: at application intake it is compared against the payload `owner_id` before any existence check, while operations on an existing application, appeal, or hardship review compare it against the loaded resource's `owner_id` immediately after the resource's reference resolves.
3. **Existence.** Path identifiers are validated left-to-right, and the request is rejected with `ERR_NOT_FOUND` at the first path identifier that does not correspond to an existing resource. Body-supplied references — `property_id`, `owner_id`, `meeting_id`, `application_id`, `violation_id`, `district_id` — must likewise exist. For paths with more than one identifier, such as the district-scoped property and guideline-set collections or the hearing-scoped comment collection, the parent identifier is therefore validated before anything inside it is touched.
4. **Optimistic concurrency.** On property reclassification only, `expected_property_version` must equal the property's current `version`, checked before any state or business evaluation of the write; a mismatch is rejected with `ERR_STALE_PROPERTY_VERSION`.
5. **State.** The target resource must be in a state from which the requested transition is declared in §3; otherwise the request is rejected with `ERR_INVALID_STATE`.
6. **Safety.** The demolition-prohibition rule of §3.2 is enforced at application creation and rejected with `ERR_DEMOLITION_PROHIBITED`.
7. **Referential integrity.** Cross-entity gates: certificate issuance requires the property's open-violation tally to be zero (`ERR_UNRESOLVED_VIOLATION_EXISTS`); officer compliance verification on a violation awaiting an after-the-fact decision requires the linked application to be approved (`ERR_LINKED_APPLICATION_NOT_APPROVED`); an after-the-fact application requires its violation to be under notice (`ERR_VIOLATION_NOT_UNDER_NOTICE`) and on the same property (`ERR_VIOLATION_PROPERTY_MISMATCH`); and application submission into a district requires the district to be active (`ERR_DISTRICT_UNDER_REVIEW`). These guard certificate creation, compliance verification, and application creation respectively.
8. **Temporal windows.** The hearing notice window (`ERR_NOTICE_WINDOW_TOO_SHORT` on hearing creation and rescheduling), the appeal filing window (`ERR_APPEAL_WINDOW_LAPSED` on appeal creation), the resubmission window (`ERR_RESUBMISSION_WINDOW_LAPSED` on resubmission), the hardship filing window (`ERR_HARDSHIP_WINDOW_LAPSED` on hardship filing), the public comment period (`ERR_COMMENT_PERIOD_CLOSED` on comment submission), the certificate commencement deadline (`ERR_CERTIFICATE_EXPIRED` on completion, `ERR_CERTIFICATE_NOT_YET_EXPIRED` on expiry), and the court-escalation threshold (`ERR_ESCALATION_THRESHOLD_NOT_MET` on court referral).
9. **Structural constraints.** Review-track decision authority (`ERR_COMMISSION_HEARING_REQUIRED`, `ERR_STAFF_DECISION_NOT_PERMITTED`), segregation of duties (`ERR_SEGREGATION_OF_DUTIES`), meeting agenda capacity (`ERR_MEETING_AGENDA_FULL` on hearing creation and rescheduling), demolition-delay overlap (`ERR_DEMOLITION_DELAY_OVERLAP` at decision time), the superseded-guideline acknowledgement (`ERR_GUIDELINE_SET_SUPERSEDED`), non-empty required arrays (`ERR_EMPTY_WORK_ITEMS` on submission and resubmission, `ERR_DENIAL_RATIONALE_REQUIRED` and `ERR_CONDITIONS_REQUIRED` at decision time, `ERR_CONDITIONS_UNMET` at condition verification), the postponement limit (`ERR_POSTPONEMENT_LIMIT_REACHED`), one pending appeal per application (`ERR_APPEAL_ALREADY_PENDING`), and one certificate per application (`ERR_CERTIFICATE_EXISTS`).
10. **Fiscal gates.** Certificate issuance requires the application's fee balance to be fully paid (`ERR_FEE_BALANCE_OUTSTANDING`), and a fee payment must not exceed the outstanding balance (`ERR_OVERPAYMENT`).

Because of this ordering, a stale property version surfaces even when the payload would also fail a business rule, an unresolved-violation rejection at certificate issuance surfaces before any outstanding-balance check, and an applicant-ownership failure on a resubmission surfaces before the resubmission window is ever evaluated.

### 2.9. District Census and Preservation Posture

Each district maintains two census counters and a derived posture, all computed and never directly editable. `total_inventory_count` is the count of properties assigned to the district whose `listing_status` is not `DEMOLISHED`; `contributing_count` is the count of those same properties whose `contributing_status` is `CONTRIBUTING`. The `preservation_posture` is `AT_RISK` exactly when the inventory is non-empty and strictly fewer than half of its properties are contributing — that is, when `total_inventory_count` is greater than zero and twice `contributing_count` is strictly less than `total_inventory_count`; otherwise it is `STABLE`, including for an empty district. The counters are maintained incrementally on each triggering mutation — property creation into the district, property reclassification, and demolition completion — and are always equal to a full recount of the district's properties, so reads of a district reflect current values. Every change to these census fields is a mutation of the district itself: it refreshes the district's `updated_at` and increments its `version`.

### 2.10. Atomic Cross-Aggregate Cascades

Although the resources in this system are peers linked by references rather than nested under one another, single operations routinely mutate several of them, and every such cascade commits atomically within the triggering request: there is no eventual-consistency window in which a client could observe a decision without its hearing mirror, a demolition approval without its delay window, or a violation resolution without its property counter adjustment. The cascade families, each detailed where its workflow lives in §3, are: the decision cascade (an open hearing moving to `DECIDED`, a demolition approval spawning a delay window and advancing the property's `listing_status`, an after-the-fact approval resolving its violation); the withdrawal cascade (refund computation plus hearing withdrawal and agenda-slot release); the appeal-sustained cascade (application, violation, and property counters); the demolition-completion census (property, district counters, and posture); guideline adoption superseding the district's prior adopted set; and postponement or hardship decisions rewriting a delay window's end.

## 3. Business Logic & Workflows

### 3.1. Building the Inventory: Districts, Guideline Sets, Owners, and Properties

Everything begins with the inventory. A `PreservationStaff` user establishes a historic district by providing its `name`, a narrative legal `boundary_description`, and a `significance_tier` of `LOCAL`, `LANDMARK`, or `ICONIC`. The tier is not decorative: it feeds both the review-track branch in §3.3 and the demolition-delay base period in §3.7. A new district starts `ACTIVE` with both census counters at zero and posture `STABLE`. Staff may later update the `boundary_description` or `significance_tier`, or move the district's `status` between `ACTIVE` and `BOUNDARY_REVIEW`; each such update increments the district's `version` by one. An update call that supplies at least one of these fields increments the version once, even when the supplied values equal the current ones; a call supplying none of them changes nothing and leaves the version untouched. While a district sits in `BOUNDARY_REVIEW`, new application intake for properties inside it is frozen — submission attempts are rejected with `ERR_DISTRICT_UNDER_REVIEW` — though everything already in flight continues.

Design guidance is versioned per district through guideline sets. Staff authors a set as a `DRAFT` with a `title` and a `sections` array, each section carrying a `section_code` and its `text`, and the system assigns a `version_no` of one plus the count of prior guideline sets for that district, so numbering is per-district monotonic. Adoption is the pivotal act: adopting a `DRAFT` set stamps its `adopted_at` with the logical clock (it remains null while `DRAFT`), moves the set to `ADOPTED`, and flips the district's previously `ADOPTED` set, if one exists, to `SUPERSEDED` — at most one set per district is `ADOPTED` at any time. Section codes from the adopted set are what denial rationales cite later, so supersession mid-flight has decision-time consequences handled in §3.4.

Before any property can change hands in the system, staff registers its owner or authorized agent with a `full_name`, `email`, and `mailing_address` used for official notices. Staff then adds each property with its `address`, assessor `parcel_number` (which must be unique across the entire inventory; a duplicate is rejected with `ERR_VALIDATION`), an optional `district_id` (a null value marks an inventory-only property outside any district), the current `owner_id`, a `contributing_status` of `CONTRIBUTING`, `NON_CONTRIBUTING`, or `VACANT_LOT`, the `construction_year`, and the `assessed_value_cents` that later serves as the basis of the violation penalty cap. `construction_year` must be an integer and `assessed_value_cents` a non-negative integer, failing which the request is rejected with `ERR_VALIDATION`. A property's `listing_status` begins at `INVENTORY`; creation into a district immediately updates the district census of §2.9. Note that a `VACANT_LOT` property counts toward the district's inventory total but never toward its contributing count.

Reclassification — a staff action changing a property's `contributing_status` — is the OCC-guarded write of §2.7: the request must carry `expected_property_version` matching the property's current `version` or it is rejected with `ERR_STALE_PROPERTY_VERSION`. A successful reclassification adjusts the district's contributing census by the delta of the change (moving to `CONTRIBUTING` raises `contributing_count` by one; moving away lowers it by one; the district's counters stay consistent through the change), recomputes the district's `preservation_posture`, and increments the property's `version`. For orientation and audit, the properties of a district are listable as a collection (every property assigned to the district, `DEMOLISHED` ones included), and the global property list is filterable by `district_id`, `owner_id`, `contributing_status`, and `listing_status`.

### 3.2. Application Intake: Work Items, Declared Costs, and Provisional Fees

An `Applicant` initiates a Certificate of Appropriateness by submitting an application carrying the `property_id` of the subject property, an `owner_id` that must equal the caller's `X-User-ID`, an `application_type` of `ALTERATION`, `ADDITION`, `NEW_CONSTRUCTION`, `DEMOLITION`, or `RELOCATION`, an `is_visible_from_public_way` flag recording whether the proposed work is visible from a public right-of-way, an `after_the_fact` flag, and a `work_items` array describing the drawings and material specifications as costed line items. Each work item carries a `category` — one of `EXTERIOR_ALTERATION`, `ADDITION`, `NEW_CONSTRUCTION`, `DEMOLITION`, `RELOCATION`, or `SITE_WORK` — a free-text `description`, and an `estimated_cost_cents` (a non-negative integer, failing which the request is rejected with `ERR_VALIDATION`). The array must not be empty; an empty submission is rejected with `ERR_EMPTY_WORK_ITEMS`.

Two safety and referential gates guard intake. A `DEMOLITION` application for a `CONTRIBUTING` property in an `ICONIC`-tier district is prohibited outright and rejected with `ERR_DEMOLITION_PROHIBITED`. And per §3.1, submission for a property whose district is in `BOUNDARY_REVIEW` is rejected with `ERR_DISTRICT_UNDER_REVIEW`. The `after_the_fact` flag and its companion `violation_id` belong to the enforcement workflow and are specified in §3.8. The `violation_id` field is required when `after_the_fact` is true and must be absent or null when it is false, with either violation rejected as `ERR_VALIDATION`. Where the district-review gate and the after-the-fact linkage gates of §3.8 would both fail, the district-review rejection surfaces first.

At submission the system computes two money fields from the declared work items. `declared_cost_cents` is the plain sum of every item's `estimated_cost_cents`. `provisional_fee_cents` is the provisional variant of the application fee: it uses the applicant-declared costs and never includes a hearing surcharge.

The application fee schedule is a per-category base fee plus a percentage of the item's cost, and its rounding order is pinned. Each work item's fee is its category's base amount plus the category's rate multiplied by the item's cost in cents, with that variable component rounded half-up to a whole cent; the application fee is then the sum of the per-item fees. Rounding each item before summing is normative — summing unrounded products and rounding once at the end yields a different total and is not compliant. The schedule itself: an `EXTERIOR_ALTERATION` item carries a base of 15,000 cents and a rate of 0.4 percent of the item's cost; an `ADDITION` item a base of 30,000 cents at 0.5 percent; a `NEW_CONSTRUCTION` item a base of 50,000 cents at 0.6 percent; a `DEMOLITION` item a base of 25,000 cents at 0.3 percent; a `RELOCATION` item a base of 40,000 cents at 0.5 percent; and a `SITE_WORK` item a base of 10,000 cents at 0.2 percent.

A freshly submitted application enters `SUBMITTED` status. From here it can only move forward into staff review, or out of the system by withdrawal (§3.5).

### 3.3. Completeness Review: Verification, Resubmission, and the Review Track

A `PreservationStaff` user takes up an application by beginning review, moving it from `SUBMITTED` to `UNDER_STAFF_REVIEW`. If the package is deficient, staff returns it incomplete, recording `deficiency_notes`; the application lands in `INCOMPLETE` and the system stamps `returned_at` with the logical clock, anchoring the resubmission window.

The applicant then has ninety days: resubmission is permitted only while the logical clock is no later than `returned_at` plus ninety days, and a later attempt is rejected with `ERR_RESUBMISSION_WINDOW_LAPSED`. Only the owning applicant may resubmit — a caller whose `X-User-ID` differs from the application's `owner_id` is rejected with `ERR_FORBIDDEN_ROLE`, and per the pipeline of §2.8 that ownership check surfaces before the window is evaluated. Resubmission replaces the `work_items` array wholesale with the payload's revised items (which must again be non-empty, or `ERR_EMPTY_WORK_ITEMS`), optionally updates `is_visible_from_public_way`, recomputes `declared_cost_cents` and `provisional_fee_cents` from the new declared items, increments `resubmission_count` by one, and returns the application to `UNDER_STAFF_REVIEW`.

When the package is complete, staff accepts completeness. This is the load-bearing moment of the lifecycle, and its payload is the staff-verified `verified_work_items` array, each entry carrying a `category` and a `verified_cost_cents` (a non-negative integer, failing which the request is rejected with `ERR_VALIDATION`); the array may legitimately be empty, in which case the verified total is zero. Acceptance records the verified array, computes `verified_cost_cents` as the sum of the entries' verified costs (the field is null until acceptance), computes the `review_track` (also null until acceptance), assesses the final fee, pins the applicable guideline set, and records the accepting staff user. Each of the intake and review actions above — beginning review, returning incomplete, resubmitting, and accepting completeness — increments the application's `version` and refreshes its `updated_at`.

The review track is computed by three branches evaluated in order. First, an application of type `DEMOLITION`, `NEW_CONSTRUCTION`, or `RELOCATION` is always `COMMISSION` track. Otherwise, if `verified_cost_cents` is at least 1,000,000 cents — ten thousand dollars — the application is `COMMISSION` track; the comparison is inclusive, so a verified total of exactly 1,000,000 cents routes to the commission. Otherwise, if the property is `CONTRIBUTING`, the work `is_visible_from_public_way`, and the district's `significance_tier` is `LANDMARK` or `ICONIC`, the application is `COMMISSION` track; for a property outside any district this third branch is false by construction. Every remaining application is `STAFF` track.

The final fee, stored as `assessed_fee_cents`, is the final variant of the §3.2 schedule applied to the verified work items — the same per-item base-plus-rate computation with the same pinned per-item rounding — plus, when the computed track is `COMMISSION`, a flat hearing surcharge of 20,000 cents added after the per-item sum. At acceptance the `fee_balance_cents` is set equal to `assessed_fee_cents`; `paid_fee_cents` accumulates against it later (§3.5). The acceptance also pins `guideline_set_id` to the district's currently `ADOPTED` guideline set, or to null when the district has no adopted set or the property sits outside any district, and records the caller in `completeness_accepted_by` — a field that exists solely to enforce segregation of duties at decision time in §3.4.

### 3.4. Hearings, Public Comment, and the Decision

Commission work centers on meetings. Staff schedules a `CommissionMeeting` with a `meeting_date`, a `location`, and an `agenda_capacity` — a non-negative integer (anything else is `ERR_VALIDATION`) giving the maximum number of hearings that may occupy the meeting, where occupancy counts hearings in `SCHEDULED` or `OPENED` status. The meeting's `scheduled_hearing_count` is the live tally of those occupying hearings.

Once an application is `ACCEPTED` on the `COMMISSION` track, staff schedules a hearing for it by naming the `application_id`, the target `meeting_id`, and the `notice_posted_at` instant. Public notice law requires fifteen clear days: `notice_posted_at` must be no later than the meeting's `meeting_date` minus fifteen days, the boundary is inclusive — a notice posted exactly fifteen days before the meeting instant passes, and one second later fails with `ERR_NOTICE_WINDOW_TOO_SHORT`. The meeting must also have a free agenda slot; when its `scheduled_hearing_count` already equals `agenda_capacity`, the scheduling is rejected with `ERR_MEETING_AGENDA_FULL`. A successful scheduling creates the hearing in `SCHEDULED`, moves the application from `ACCEPTED` to `HEARING_SCHEDULED` (incrementing the application's `version`), and raises the meeting's `scheduled_hearing_count` by one. Scheduling a hearing for an application in any other situation — including a `STAFF`-track `ACCEPTED` application — is rejected with `ERR_INVALID_STATE`.

While a hearing is `SCHEDULED` (or later `CONTINUED`), the public comment period is open: any authenticated participant may submit a comment to the hearing it addresses — the comment records that hearing's identifier as its `hearing_id` — with a `commenter_name`, a `stance` of `SUPPORT`, `OPPOSE`, or `NEUTRAL`, and the `comment_text` body, and the system stamps `submitted_at` with the logical clock. A comment submitted when the hearing is in any other status is rejected with `ERR_COMMENT_PERIOD_CLOSED`. Comments are retrievable as a per-hearing collection for the record.

At the meeting, a `Commissioner` opens the hearing — permitted only while its application is `HEARING_SCHEDULED`, otherwise `ERR_INVALID_STATE` — which moves the hearing from `SCHEDULED` to `OPENED`, advances the application from `HEARING_SCHEDULED` to `HEARING_OPEN`, and closes the comment period. When testimony cannot conclude, the commissioner continues the hearing: from `SCHEDULED` or `OPENED` the hearing moves to `CONTINUED`, the application falls back to `HEARING_DEFERRED`, and the meeting's `scheduled_hearing_count` drops by one, freeing the agenda slot. Staff later reschedules a `CONTINUED` hearing by supplying a fresh `meeting_id` (possibly a different meeting) and a fresh `notice_posted_at`; both the fifteen-day notice window and the agenda-capacity check run again against the new meeting, with the same `ERR_NOTICE_WINDOW_TOO_SHORT` and `ERR_MEETING_AGENDA_FULL` rejections. A successful reschedule replaces the hearing's `meeting_id` and `notice_posted_at`, raises the new meeting's count by one, and returns the application from `HEARING_DEFERRED` to `HEARING_SCHEDULED`.

The decision itself branches on track, with authority split deliberately. For a `STAFF`-track application in `ACCEPTED`, a `PreservationStaff` user records the decision by naming an `outcome`. For a `COMMISSION`-track application in `HEARING_OPEN`, a `Commissioner` records it. The cross cases are hard errors: a staff decision on a `COMMISSION`-track application still sitting in `ACCEPTED` is rejected with `ERR_COMMISSION_HEARING_REQUIRED` — it must be heard first — and a `PreservationStaff` attempt to decide a `COMMISSION`-track application in `HEARING_OPEN` is rejected with `ERR_STAFF_DECISION_NOT_PERMITTED`, because only a commissioner may decide there. Symmetrically, a `Commissioner` attempt to decide a `STAFF`-track application in `ACCEPTED` is rejected with `ERR_FORBIDDEN_ROLE`, because only `PreservationStaff` may decide there. Segregation of duties adds one more guard on the staff track: the staff user whose identifier sits in `completeness_accepted_by` may not decide that same application, and their attempt is rejected with `ERR_SEGREGATION_OF_DUTIES`.

Three outcomes exist on both tracks, with symmetric documentary requirements. An `outcome` of `APPROVE` approves outright and leaves `decision_conditions` empty. An `outcome` of `APPROVE_WITH_CONDITIONS` requires a non-empty `conditions` array — missing or empty is rejected with `ERR_CONDITIONS_REQUIRED` — and records it onto `decision_conditions`. An `outcome` of `DENY` requires a non-empty `denial_rationale_sections` array citing the `section_code`s of the pinned guideline set that the proposal violates — missing or empty is rejected with `ERR_DENIAL_RATIONALE_REQUIRED`. Any decision stamps `decided_at` with the logical clock (the instant that anchors the appeal window of §3.6) and increments the application's `version`; on the commission track the `OPENED` hearing simultaneously moves to `DECIDED`. Within a decision's structural checks the evaluation order is fixed: review-track authority and segregation of duties first, then the documentary requirements (`ERR_CONDITIONS_REQUIRED`, `ERR_DENIAL_RATIONALE_REQUIRED`), then the superseded-guideline acknowledgement below, and finally the demolition-delay overlap gate of §3.7, which runs last, immediately before an approval commits. Approvals of demolition and after-the-fact applications carry further cascades specified in §3.7 and §3.8.

One acknowledgement can stand between a decision and its guideline basis. If, at decision time, the pinned guideline set is no longer the district's `ADOPTED` set — a newer set was adopted after acceptance — the decision is rejected with `ERR_GUIDELINE_SET_SUPERSEDED` unless the payload carries `guideline_override_ack` set to true, an explicit acknowledgement that the commission proceeds under superseded guidance. When the acknowledgement is present, the application's `guideline_set_id` is re-pinned to the district's currently `ADOPTED` set as part of the decision. When no guideline set was pinned at acceptance (`guideline_set_id` is null), this check never applies. For precedent research, the application listing supports filtering by `property_id`, `owner_id`, `district_id`, `violation_id`, `guideline_set_id`, `status`, and `work_category` — `district_id` matching applications whose subject property is assigned to that district, and `work_category` matching applications carrying at least one work item of that category — so staff and commissioners can survey how prior applications in a category or under a guideline set were treated.

### 3.5. Fees, Payments, and Withdrawal Refunds

The assessed fee is payable in installments. The owning applicant records a payment by supplying `amount_cents`, a positive integer (anything else is `ERR_VALIDATION`); the system adds it to `paid_fee_cents` and subtracts it from `fee_balance_cents`. Payments are accepted in every application status except `WITHDRAWN` and `DENIED_FINAL`, where the attempt is rejected with `ERR_INVALID_STATE`. A payment that exceeds the outstanding `fee_balance_cents` is rejected with `ERR_OVERPAYMENT` — partial payment of the exact remaining balance is the intended final installment.

An applicant may withdraw an application from exactly the seven live states `SUBMITTED`, `UNDER_STAFF_REVIEW`, `INCOMPLETE`, `ACCEPTED`, `HEARING_SCHEDULED`, `HEARING_DEFERRED`, and `HEARING_OPEN` — a withdrawal attempt from any other status, including `DENIED` and the approval terminal states, is rejected with `ERR_INVALID_STATE` — provided the caller's `X-User-ID` equals the application's `owner_id` (otherwise `ERR_FORBIDDEN_ROLE`). Withdrawal moves the application to `WITHDRAWN` and settles the fee account by a stage-based refund schedule: withdrawal from `SUBMITTED`, `UNDER_STAFF_REVIEW`, or `INCOMPLETE` refunds one hundred percent of `paid_fee_cents`; withdrawal from `ACCEPTED`, `HEARING_SCHEDULED`, or `HEARING_DEFERRED` refunds fifty percent; withdrawal from `HEARING_OPEN` refunds nothing. The `refunded_fee_cents` is the paid amount multiplied by the stage's percentage, rounded half-up to a whole cent, and after the refund the `fee_balance_cents` is forced to zero — any unpaid assessed balance is forgiven, and the retained revenue is exactly `paid_fee_cents` minus `refunded_fee_cents`.

Withdrawal also releases the public process. Withdrawing from `HEARING_SCHEDULED` or `HEARING_OPEN` moves the application's `SCHEDULED` or `OPENED` hearing to `WITHDRAWN` and decrements the meeting's `scheduled_hearing_count` by one, freeing the agenda slot. Withdrawing from `HEARING_DEFERRED` moves the `CONTINUED` hearing to `WITHDRAWN` without touching the meeting tally, since the slot was already freed when the hearing was continued. Withdrawal, like every application mutation, increments the application's `version`.

### 3.6. Appeals to the City Council

A denial is not final until the council has had its chance. The owning applicant appeals a `DENIED` application by submitting the `application_id` and the `grounds` for appeal; the system stamps `filed_at` with the logical clock. The appeal must land within thirty days of the application's `decided_at` — a filing that would be later than `decided_at` plus thirty days is rejected with `ERR_APPEAL_WINDOW_LAPSED` — and only one appeal per application may be pending at a time: a second filing while an appeal for the same application is `FILED` is rejected with `ERR_APPEAL_ALREADY_PENDING`. Appealing an application that is not `DENIED` fails the state gate with `ERR_INVALID_STATE`, and a non-owner's filing fails with `ERR_FORBIDDEN_ROLE`.

A `CouncilMember` decides a `FILED` appeal with an `outcome` and the council's `council_findings`, and the system stamps the appeal's `decided_at`. The two outcomes diverge sharply. `SUSTAIN` overturns the denial: the appeal moves to `DECIDED_SUSTAINED`, the application moves from `DENIED` to `APPROVED_ON_APPEAL`, and if the application was an after-the-fact legalization, the linked violation — whether still `NOTICE_ISSUED` or already `AFTER_THE_FACT_PENDING` — moves to `COMPLIANCE_VERIFIED` with its `compliance_verified_at` set to the appeal's `decided_at`, its `final_penalty_cents` computed with that same instant as the accrual stop, and the property's `open_violation_count` decremented by one with `compliance_posture` recomputed. `UPHOLD` affirms the denial: the appeal moves to `DECIDED_UPHELD` and the application moves from `DENIED` to `DENIED_FINAL`. The appellant may also withdraw a pending appeal; the withdrawal requires the same ownership check (the caller's `X-User-ID` must equal the application's `owner_id`, else `ERR_FORBIDDEN_ROLE`) and moves the appeal to `WITHDRAWN` without touching the application, which remains `DENIED`.

For denials that nobody appeals, staff closes the loop by finalizing the denial, moving the application from `DENIED` to `DENIED_FINAL`. Finalization is permitted only when no appeal for the application is in `FILED` status and the logical clock has passed `decided_at` plus thirty days; attempting it while an appeal is pending, or while the appeal window is still open, is rejected with `ERR_INVALID_STATE`.

### 3.7. Demolition Delay, Postponement, and Economic Hardship

Demolition is the one irreversible outcome, so the system slows it down by law. On any approval of a `DEMOLITION` application — staff-track or commission-track — three things happen together. The property's `listing_status` advances from `INVENTORY` to `DEMOLITION_PENDING`. A demolition delay is created in `ACTIVE` status, linked to the approving `application_id` and carrying the `property_id` denormalized from the application so that overlap checks run directly against the property; its `delay_start_at` is set to the application's `decided_at`, its `base_delay_days` is drawn from the district's significance tier — ninety days for `LOCAL`, one hundred eighty days for `LANDMARK`, three hundred sixty-five days for `ICONIC`, and ninety days (the `LOCAL` base) for a property outside any district — and its `postponement_count` starts at zero. And before any of this commits, the overlap check runs: the new delay window, the half-open interval from `delay_start_at` up to but not including its provisional end, must not overlap any other `ACTIVE` delay on the same property; because the interval is half-open, adjacency — one window ending exactly where another begins — is permitted. A failing overlap check rejects the entire decision with `ERR_DEMOLITION_DELAY_OVERLAP` and no approval is recorded.

The delay's `provisional_delay_end` is its `delay_start_at` plus the base days plus thirty days for each granted postponement. Staff may postpone an `ACTIVE` delay at most twice — a third attempt, when `postponement_count` has already reached two, is rejected with `ERR_POSTPONEMENT_LIMIT_REACHED` — and each postponement raises `postponement_count` by one and recomputes the provisional end thirty days further out. The `final_delay_end` stays null unless a hardship grant sets it (below); while null, the provisional end governs.

Expiry of a delay is lazy. The effective end of a delay is its `final_delay_end` when set, otherwise its `provisional_delay_end`. Whenever the logical clock is consulted on the delay — any read of it, or any action upon it — and that clock has reached or passed the effective end, the delay's status moves from `ACTIVE` to `EXPIRED` as part of answering. One consequence: a postponement attempted after the effective end finds the delay already `EXPIRED` and fails the state gate with `ERR_INVALID_STATE`.

An owner who believes the delay imposes an economic hardship may seek relief. The applicant files a hardship review naming the `application_id` of their approved `DEMOLITION` application, a `claimed_rate_of_return_pct` (any JSON number) stating the rate of return they would earn under the denial of demolition, and an `appraisal_basis_cents` (a non-negative integer) for the property; the system stamps `filed_at` with the logical clock. The filing window is bounded on both sides: `filed_at` must be strictly after the application's `decided_at` and no later than thirty days before the delay's `provisional_delay_end` — the cutoff instant itself is included. A filing at or before the approval instant, or after the cutoff, is rejected with `ERR_HARDSHIP_WINDOW_LAPSED`.

The commission's consideration has two steps. A `Commissioner` first hears the review, moving it from `FILED` to `HEARD`. Later, a commissioner decides it with an `outcome` and written `findings`, stamping its `decided_at`. A `GRANT` outcome moves the review to `GRANTED` and lifts the delay: the linked demolition delay moves from `ACTIVE` to `LIFTED_BY_HARDSHIP`, and its `final_delay_end` is set to the hardship's `decided_at` plus ten days, replacing the provisional end from that moment forward. A `DENY` outcome moves the review to `DENIED` and leaves the delay entirely unchanged, its provisional end still governing.

### 3.8. Violations, Civil Penalties, and After-the-Fact Legalization

When unpermitted work is observed, an `EnforcementOfficer` opens a violation case with the `property_id`, the `observed_violation_date`, and a `work_description` of what was done. The case starts `OPEN`, and the property's `open_violation_count` rises by one with its `compliance_posture` recomputed — the posture is `UNDER_ENFORCEMENT` whenever the count is greater than zero and `CLEAR` otherwise.

Issuing the formal notice moves the case from `OPEN` to `NOTICE_ISSUED`, stamps `notice_issued_at` with the logical clock, and computes the `demand_letter_amount_cents`: the demand variant of the civil penalty, projecting the accrual if the owner cures within the thirty-day cure window by taking the stop date as `notice_issued_at` plus thirty days.

The civil penalty itself accrues daily on whole days, measured from the notice instant to the applicable stop date; partial days do not count. The schedule is marginal, like tax brackets. The first thirty days accrue at 10,000 cents per day; days thirty-one through sixty accrue at 20,000 cents per day; and every day from the sixty-first onward accrues at 50,000 cents per day. The raw accrual is therefore 10,000 cents times the elapsed days counted up to a maximum of thirty, plus 20,000 cents times the days beyond the thirtieth counted up to a maximum of thirty more, plus 50,000 cents times the days beyond the sixtieth. The cap is ten percent of the property's `assessed_value_cents`, rounded half-up to a whole cent. The assessed penalty is the lesser of the raw accrual and the cap, and `penalty_capped` is true exactly when the raw accrual strictly exceeds the cap — when the two are equal, the cap did not limit anything and the flag is false.

Resolution comes in three shapes. An officer verifies compliance directly, moving the case to `COMPLIANCE_VERIFIED`: from `NOTICE_ISSUED` this is always structurally permitted, since by construction such a case has no linked after-the-fact application (submission of one would have flipped it, as below); from `AFTER_THE_FACT_PENDING` it is permitted only when the linked application has reached an approval terminal state — `APPROVED`, `APPROVED_WITH_CONDITIONS`, or `APPROVED_ON_APPEAL` — and is otherwise rejected with `ERR_LINKED_APPLICATION_NOT_APPROVED`. Verification stamps `compliance_verified_at` with the logical clock, computes `final_penalty_cents` as the final variant of the penalty with the accrual stop at that verification instant, sets `penalty_capped`, decrements the property's `open_violation_count` by one, and recomputes `compliance_posture`.

Escalation is the second shape: an officer refers a `NOTICE_ISSUED` case to court, but only once more than sixty whole days have elapsed since `notice_issued_at`; at sixty days or fewer the referral is rejected with `ERR_ESCALATION_THRESHOLD_NOT_MET`. A successful referral moves the case to `COURT_REFERRAL` and stamps `referred_at`.

Closure is the last shape. An officer closes a `COMPLIANCE_VERIFIED` or `COURT_REFERRAL` case to `CLOSED`. Closing from `COURT_REFERRAL` computes `final_penalty_cents` if it is not already set — the final variant with the accrual stop at `referred_at` — and sets `penalty_capped`. Closure adjusts no property counters: `open_violation_count` and `compliance_posture` are recomputed only when a case is opened, verified, or resolved through an approval cascade, so a case closed from `COURT_REFERRAL` continues to count against the property's open-violation tally at certificate issuance.

The system also offers a legalization path. An applicant may submit an application with `after_the_fact` set to true, naming the `violation_id` of the case that caught the work; the submission requires the violation to be in `NOTICE_ISSUED` status — anything else is rejected with `ERR_VIOLATION_NOT_UNDER_NOTICE` — and the violation's property must be the application's `property_id`, or the submission is rejected with `ERR_VIOLATION_PROPERTY_MISMATCH`. A successful after-the-fact submission immediately flips the violation from `NOTICE_ISSUED` to `AFTER_THE_FACT_PENDING`. From that point the violation's fate is tied to the application's: any approval of the application — staff-track, commission-track, or sustained on appeal — moves the violation to `COMPLIANCE_VERIFIED` with `compliance_verified_at` set to the application's `decided_at` (or, for `APPROVED_ON_APPEAL`, the appeal's `decided_at` as in §3.6), computes `final_penalty_cents` with that instant as the accrual stop, sets `penalty_capped`, decrements the property's `open_violation_count` by one, and recomputes `compliance_posture`.

### 3.9. Certificates: Issuance, Conditions, and Completion

The Certificate of Appropriateness is the deliverable the whole process exists to produce. Staff issues a certificate by naming the `application_id` of an application that has reached an approval terminal state — `APPROVED`, `APPROVED_WITH_CONDITIONS`, or `APPROVED_ON_APPEAL`; an application in any other status fails the state gate with `ERR_INVALID_STATE`. Three further gates stand in line, evaluated per the pipeline of §2.8 — so the open-violation check runs first, then the one-certificate check, then the fee-balance check. There must be no existing certificate for the same application — the relationship is one-to-one, and a second issuance is rejected with `ERR_CERTIFICATE_EXISTS`. The property must be clean of enforcement: an `open_violation_count` greater than zero is rejected with `ERR_UNRESOLVED_VIOLATION_EXISTS`, and this referential check runs before the fiscal one. Finally the fee account must be settled: a `fee_balance_cents` greater than zero is rejected with `ERR_FEE_BALANCE_OUTSTANDING`.

Issuance stamps `issued_at` with the logical clock, sets the `work_commence_deadline` to exactly three hundred sixty-five days after issuance, copies the application's `decision_conditions` onto the certificate's `conditions`, and starts the certificate in `ISSUED`. From there, staff verifies conditions by reporting the `conditions_met_count`; the reported count must equal the number of recorded `conditions` — every condition satisfied — or the verification is rejected with `ERR_CONDITIONS_UNMET`, and a successful verification moves the certificate from `ISSUED` to `CONDITIONS_VERIFIED`.

Completion requires that work both commenced and finished inside the deadline. Staff completes a `CONDITIONS_VERIFIED` certificate by supplying the `commenced_at` instant; both the current logical clock and the payload's `commenced_at` must be at or before the `work_commence_deadline`, and either being late is rejected with `ERR_CERTIFICATE_EXPIRED`. A successful completion stamps `completed_at` and moves the certificate to `COMPLETED`. When the underlying application was a demolition, completion is also the moment the building leaves the inventory: the property's `listing_status` advances from `DEMOLITION_PENDING` to `DEMOLISHED`, the district's `contributing_count` drops by one if and only if the property was `CONTRIBUTING`, its `total_inventory_count` drops by one, and the `preservation_posture` is recomputed per §2.9.

Should the deadline lapse first, staff expires the certificate: from `ISSUED` or `CONDITIONS_VERIFIED`, expiry is permitted only once the logical clock has passed the `work_commence_deadline` — at or before the deadline the request is rejected with `ERR_CERTIFICATE_NOT_YET_EXPIRED` — and moves the certificate to `EXPIRED`.

## 4. Endpoint Definitions

All endpoints are mounted under the `/preservation` prefix. Operations that create new resources return a `201 Created` status code; operations that modify an existing resource return a `200 OK`. Recording a fee payment returns `201 Created`, since each payment is a new record even though the response carries the updated application. Retrieval endpoints, whether single-resource or list, return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/preservation/districts` | Create a historic district (status `ACTIVE`, census counters zero, posture `STABLE`) | PreservationStaff |
| GET | `/preservation/districts` | List districts, filterable by `status` | Any |
| GET | `/preservation/districts/{districtId}` | Get one district with current census counters and posture | Any |
| PATCH | `/preservation/districts/{districtId}` | Update boundary/tier or move status between `ACTIVE` and `BOUNDARY_REVIEW` | PreservationStaff |
| GET | `/preservation/districts/{id}/properties` | List properties in a district | Any |
| POST | `/preservation/districts/{id}/guideline-sets` | Create a `DRAFT` guideline set for the district | PreservationStaff |
| GET | `/preservation/districts/{id}/guideline-sets` | List the district's guideline sets, filterable by `status` | Any |
| POST | `/preservation/guideline-sets/{guidelineSetId}/adopt` | Adopt a `DRAFT` guideline set; the prior `ADOPTED` set becomes `SUPERSEDED` | PreservationStaff |
| POST | `/preservation/owners` | Register a property owner or authorized agent | PreservationStaff |
| POST | `/preservation/properties` | Add a property to the inventory | PreservationStaff |
| GET | `/preservation/properties` | List properties, filterable | Any |
| GET | `/preservation/properties/{propertyId}` | Get one property | Any |
| POST | `/preservation/properties/{propertyId}/reclassify` | Change `contributing_status`; OCC-guarded; adjusts the district census | PreservationStaff |
| POST | `/preservation/meetings` | Schedule a commission meeting with agenda capacity | PreservationStaff |
| GET | `/preservation/meetings` | List meetings | Any |
| GET | `/preservation/meetings/{meetingId}` | Get one meeting with its live scheduled-hearing tally | Any |
| POST | `/preservation/applications` | Submit a Certificate of Appropriateness application | Applicant |
| GET | `/preservation/applications` | List applications, filterable for precedent lookup | Any |
| GET | `/preservation/applications/{applicationId}` | Get one application | Any |
| POST | `/preservation/applications/{applicationId}/begin-review` | Begin completeness review (`SUBMITTED` to `UNDER_STAFF_REVIEW`) | PreservationStaff |
| POST | `/preservation/applications/{applicationId}/return-incomplete` | Return the application for deficiency (`UNDER_STAFF_REVIEW` to `INCOMPLETE`) | PreservationStaff |
| POST | `/preservation/applications/{applicationId}/resubmit` | Resubmit with revised work items within the ninety-day window | Applicant |
| POST | `/preservation/applications/{applicationId}/accept-completeness` | Accept completeness: verify costs, compute track, assess fee, pin guideline set | PreservationStaff |
| POST | `/preservation/applications/{applicationId}/decide` | Record the decision: staff for `STAFF`-track `ACCEPTED`, commission for `COMMISSION`-track `HEARING_OPEN` | PreservationStaff, Commissioner |
| POST | `/preservation/applications/{applicationId}/withdraw` | Withdraw the application; stage-based refund; hearing cascade | Applicant |
| POST | `/preservation/applications/{applicationId}/finalize-denial` | Finalize a denial after the appeal window lapses (`DENIED` to `DENIED_FINAL`) | PreservationStaff |
| POST | `/preservation/applications/{applicationId}/fee-payments` | Record a fee payment against the assessed balance | Applicant |
| POST | `/preservation/hearings` | Schedule a hearing for a `COMMISSION`-track `ACCEPTED` application into a meeting | PreservationStaff |
| GET | `/preservation/hearings` | List hearings, filterable by application, meeting, and status | Any |
| GET | `/preservation/hearings/{hearingId}` | Get one hearing | Any |
| POST | `/preservation/hearings/{hearingId}/open` | Open the hearing at the meeting; closes the comment period | Commissioner |
| POST | `/preservation/hearings/{hearingId}/continue` | Continue (defer) the hearing, freeing the agenda slot | Commissioner |
| POST | `/preservation/hearings/{hearingId}/reschedule` | Reschedule a `CONTINUED` hearing with fresh notice and capacity checks | PreservationStaff |
| POST | `/preservation/hearings/{id}/comments` | Submit a public comment while the comment period is open | Any |
| GET | `/preservation/hearings/{id}/comments` | List comments on a hearing | Any |
| POST | `/preservation/appeals` | Appeal a `DENIED` application to the council within thirty days | Applicant |
| GET | `/preservation/appeals` | List appeals, filterable by application and status | Any |
| GET | `/preservation/appeals/{appealId}` | Get one appeal | Any |
| POST | `/preservation/appeals/{appealId}/decide` | Council decides the appeal: `SUSTAIN` overturns, `UPHOLD` finalizes | CouncilMember |
| POST | `/preservation/appeals/{appealId}/withdraw` | Withdraw a pending appeal | Applicant |
| POST | `/preservation/violations` | Open a violation case for unpermitted work | EnforcementOfficer |
| GET | `/preservation/violations` | List violations, filterable by property and status | Any |
| GET | `/preservation/violations/{violationId}` | Get one violation | Any |
| POST | `/preservation/violations/{violationId}/issue-notice` | Issue the violation notice; starts penalty accrual and computes the demand amount | EnforcementOfficer |
| POST | `/preservation/violations/{violationId}/verify-compliance` | Verify correction of the unpermitted work | EnforcementOfficer |
| POST | `/preservation/violations/{violationId}/refer-court` | Refer to court once more than sixty days have elapsed since notice | EnforcementOfficer |
| POST | `/preservation/violations/{violationId}/close` | Close a `COMPLIANCE_VERIFIED` or `COURT_REFERRAL` violation | EnforcementOfficer |
| GET | `/preservation/demolition-delays` | List demolition delays, filterable by `property_id`, `application_id`, and `status`; lazy expiry is evaluated | Any |
| GET | `/preservation/demolition-delays/{delayId}` | Get one demolition delay (lazy expiry evaluated) | Any |
| POST | `/preservation/demolition-delays/{delayId}/postpone` | Postpone an `ACTIVE` delay by thirty days, at most twice | PreservationStaff |
| POST | `/preservation/hardship-reviews` | File an economic-hardship review for an approved demolition | Applicant |
| GET | `/preservation/hardship-reviews` | List hardship reviews, filterable by application and status | Any |
| GET | `/preservation/hardship-reviews/{hardshipReviewId}` | Get one hardship review | Any |
| POST | `/preservation/hardship-reviews/{hardshipReviewId}/hear` | Commission hears the hardship review (`FILED` to `HEARD`) | Commissioner |
| POST | `/preservation/hardship-reviews/{hardshipReviewId}/decide` | Decide hardship: `GRANT` lifts the delay, `DENY` keeps it | Commissioner |
| POST | `/preservation/certificates` | Issue the Certificate of Appropriateness for an approved application | PreservationStaff |
| GET | `/preservation/certificates` | List certificates, filterable by application and status | Any |
| GET | `/preservation/certificates/{certificateId}` | Get one certificate | Any |
| POST | `/preservation/certificates/{certificateId}/verify-conditions` | Verify all approval conditions are met | PreservationStaff |
| POST | `/preservation/certificates/{certificateId}/complete` | Complete the certificate; for demolition this demolishes the property | PreservationStaff |
| POST | `/preservation/certificates/{certificateId}/expire` | Expire a certificate whose commence deadline has passed | PreservationStaff |
| POST | `/preservation/_clock/set_current_utc` | Set the server logical clock (ISO 8601 UTC) | Any |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_DEMOLITION_PROHIBITED` | 422 |
| `ERR_DISTRICT_UNDER_REVIEW` | 409 |
| `ERR_UNRESOLVED_VIOLATION_EXISTS` | 409 |
| `ERR_LINKED_APPLICATION_NOT_APPROVED` | 409 |
| `ERR_VIOLATION_NOT_UNDER_NOTICE` | 409 |
| `ERR_VIOLATION_PROPERTY_MISMATCH` | 422 |
| `ERR_NOTICE_WINDOW_TOO_SHORT` | 422 |
| `ERR_APPEAL_WINDOW_LAPSED` | 422 |
| `ERR_RESUBMISSION_WINDOW_LAPSED` | 422 |
| `ERR_HARDSHIP_WINDOW_LAPSED` | 422 |
| `ERR_COMMENT_PERIOD_CLOSED` | 409 |
| `ERR_CERTIFICATE_EXPIRED` | 409 |
| `ERR_CERTIFICATE_NOT_YET_EXPIRED` | 409 |
| `ERR_ESCALATION_THRESHOLD_NOT_MET` | 409 |
| `ERR_COMMISSION_HEARING_REQUIRED` | 409 |
| `ERR_STAFF_DECISION_NOT_PERMITTED` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_MEETING_AGENDA_FULL` | 409 |
| `ERR_DEMOLITION_DELAY_OVERLAP` | 409 |
| `ERR_GUIDELINE_SET_SUPERSEDED` | 409 |
| `ERR_EMPTY_WORK_ITEMS` | 422 |
| `ERR_DENIAL_RATIONALE_REQUIRED` | 422 |
| `ERR_CONDITIONS_REQUIRED` | 422 |
| `ERR_CONDITIONS_UNMET` | 422 |
| `ERR_POSTPONEMENT_LIMIT_REACHED` | 422 |
| `ERR_APPEAL_ALREADY_PENDING` | 409 |
| `ERR_CERTIFICATE_EXISTS` | 409 |
| `ERR_FEE_BALANCE_OUTSTANDING` | 402 |
| `ERR_OVERPAYMENT` | 422 |
| `ERR_STALE_PROPERTY_VERSION` | 412 |
| `ERR_VALIDATION` | 400 |
