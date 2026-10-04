# Generic Medicine Application Review and Patent Certification API — Product Requirements Document

## 1. Introduction

When a patent-protected brand drug approaches the end of its exclusivity, generic manufacturers may seek approval through an abbreviated pathway: rather than repeating clinical trials, an applicant demonstrates that its product is bioequivalent to the agency's reference listed drug and certifies its position on every patent the innovator has listed against that product. This document specifies the Generic Medicine Application Review & Patent Certification API, mounted under `/generic-drug-review`, as the system of record for that program. It governs the registration of applicant companies and reference products, the listing of patents and protected indications, the assembly and filing of abbreviated applications, and the scientific review that follows — all of it driven by a deterministic logical clock so that every statutory deadline can be exercised reproducibly.

The regulatory stakes are asymmetric by design. A paragraph-IV certification invites litigation: notice to the patent owner opens a 45-day window in which an infringement suit imposes a 30-month stay on approval, while the first applicant to file such a challenge earns 180 days of marketing exclusivity that can be forfeited in half a dozen distinct ways. Beyond that core, the system enforces review-cycle discipline (goal dates of ten or eight months depending on priority, deficiency letters answered within twelve months), pre-approval facility inspections with special rules for foreign sites, labeling carve-outs for protected indications, and post-approval change supplements whose effectivity depends on the chosen pathway. Responsibility is deliberately separated across five roles — applicants sponsor their own applications, innovators own the patent side, agency reviewers decide, field inspectors record outcomes, and a program administrator maintains the registry and the clock.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through two mandatory HTTP headers: `X-User-ID` identifies the acting user and `X-User-Role` declares their operational capacity. The system recognizes exactly five roles: `ProgramAdmin`, `ApplicantSponsor`, `InnovatorSponsor`, `RegulatoryReviewer`, and `FacilityInspector`. A request missing either header, or carrying a role value outside this list, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). Every endpoint declares the roles permitted to invoke it; a call from any other role is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `ApplicantSponsor`, `X-User-ID` is the `id` of the acting `ApplicantCompany`; ownership checks on any resource that references an applicant company compare the resource's `applicant_id` field to `X-User-ID`, and a mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). When `X-User-Role` is `InnovatorSponsor`, `X-User-ID` is an opaque operator identifier not tied to any persisted sponsor entity; the server records it as `patent_owner_user_id` on each `ReferenceProduct` and compares it against that field when the sponsor lists patents or reports an infringement suit, again rejecting mismatches with `ERR_NOT_RESOURCE_OWNER`. When `X-User-Role` is `ProgramAdmin`, `RegulatoryReviewer`, or `FacilityInspector`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit purposes but never compares it to any entity's `id`.

Read access is deliberately broad: every retrieval endpoint accepts all five roles, and ownership scoping never hides reads.

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

List endpoints paginate through two query parameters. `limit` caps the number of returned items: it defaults to 10, accepts a minimum of 1 and a maximum of 100; a `limit` below 1 is clamped to 1 and a `limit` above 100 is clamped to 100, while a non-integer `limit` is rejected with `ERR_INVALID_REQUEST`. `offset` skips that many items from the start of the collection and defaults to 0; a negative `offset` is clamped to 0, and a non-integer `offset` is rejected with `ERR_INVALID_REQUEST`. Unless an endpoint states otherwise, list responses are sorted by `created_at` in ascending order, with ties broken by commit order — the sequence in which the resources were persisted — never by resource `id`. The `meta` object of a list response carries the fields `limit`, `offset`, `total_count`, and `has_more`, where `total_count` is the size of the filtered collection before pagination and `has_more` is true exactly when items remain beyond the returned page. Several list endpoints additionally accept an optional `status` filter or reverse foreign-key filters such as `applicant_id`, `reference_product_id`, `application_id`, `patent_id`, or `facility_id`; these narrow the collection without changing the sort order.

### 2.4. The Logical Clock and Calendar Conventions

Every regulatory deadline in the system is measured against a logical clock, never wall-clock time. Before any administrative action is taken, the logical clock reads exactly 2026-09-01T00:00:00Z. A `ProgramAdmin`-only test-driving capability, mounted at `/_clock/set_current_utc` outside the business prefix, advances the clock to a supplied `to_iso8601` instant and answers with the resulting `current_utc`; the target instant must be at or after the current logical time, and a backward move is rejected with `ERR_INVALID_REQUEST`. The clock never advances on its own. Every server-stamped instant — `created_at`, `updated_at`, and the envelope's `api_request_timestamp` — reads this logical clock rather than wall-clock time, and a `to_iso8601` value supplied without a timezone designator is interpreted as UTC.

Advancing the clock is the single trigger that re-evaluates every time-driven rule in the system: listed patents and protected-indication windows expire, unanswered deficiency letters lapse their review cycle and with it the application, unexercised suit windows close, litigation stays expire, exclusivity awards forfeit or expire, thirty-day change supplements take effect, and every tentatively approved application is re-examined for full approval.

Two kinds of temporal values flow through the API. Calendar-date fields — receipt dates, expiry dates, deadlines — are ISO 8601 `YYYY-MM-DD` strings. Instants such as `created_at` are full ISO 8601 UTC datetimes with three fractional digits. All date arithmetic follows one convention: adding calendar months preserves the day-of-month, and when that day does not exist in the target month the result clamps to the month's last day — adding ten calendar months to 2027-01-31 yields 2027-11-30. Day arithmetic is plain calendar-day addition with no clamping. The phrase "within N days of X" means the distance between the two dates is at most N days, inclusive of day N.

### 2.5. Common Resource Properties

Every resource in the system — applicant companies, reference products, listed patents, protected indications, applications, bioequivalence studies, patent certifications, challenge notices, review cycles, amendments, manufacturing facilities, facility inspections, supplements, and exclusivity awards — carries the same four system-managed properties. `id` is a server-minted UUID with no type prefix. `created_at` records the instant of creation and `updated_at` the instant of the last mutation, both ISO 8601 UTC with three fractional digits. `version` is an integer that starts at 1 on creation and that the server increments by one on every mutation of the resource. Clients never supply these fields; a payload that contains them has them silently ignored.

### 2.6. Optimistic Concurrency Control

Exactly two write operations are guarded by optimistic concurrency control on the parent application: filing an amendment against an application, and filing a patent certification against an application. Each such request must carry `expected_application_version`, set to the `version` of the parent `GenericApplication` the client last observed; the field is non-optional on these two operations. If the application's current `version` no longer matches — that is, the client is acting on a stale view of the application — the write is rejected with `ERR_STALE_VERSION` (HTTP 412) and nothing is persisted. No endpoint other than these two accepts a version field.

### 2.7. Validation Pipeline and Error Precedence

When more than one rule could reject the same request, the server evaluates its checks in a fixed order and reports the first failure encountered; checks are never reported as an unordered set. The order is:

1. First, the two context headers are validated (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. Second, the caller's role is checked against the endpoint's declared roles (`ERR_INSUFFICIENT_PERMISSIONS`).
3. Third, ownership is enforced for entity-backed callers — an applicant's `X-User-ID` must equal the target resource's `applicant_id`, and an innovator's must equal the reference product's `patent_owner_user_id` for patent listing and suit reporting (`ERR_NOT_RESOURCE_OWNER`). Ownership is evaluated only when the target resource exists; a missing target surfaces the existence error of the next step instead.
4. Fourth, identifiers must resolve: path identifiers are validated left to right, then body-referenced identifiers (`reference_product_id`, `patent_id`, `facility_id`, `application_id`) in the endpoint's input declaration order, each unresolvable identifier producing its own 404 — `ERR_APPLICANT_NOT_FOUND`, `ERR_REFERENCE_PRODUCT_NOT_FOUND`, `ERR_LISTED_PATENT_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, `ERR_CERTIFICATION_NOT_FOUND`, `ERR_NOTICE_NOT_FOUND`, `ERR_REVIEW_CYCLE_NOT_FOUND`, `ERR_FACILITY_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND`, `ERR_SUPPLEMENT_NOT_FOUND`, or `ERR_EXCLUSIVITY_AWARD_NOT_FOUND`.
5. Fifth, the request body shape: required fields present, enum members valid, dates well-formed, `scheduled_end_date` on or after `scheduled_start_date`, and `protected_until` on or after `effective_from` (`ERR_INVALID_REQUEST`). Unknown payload fields, and client-supplied system or computed fields such as `id`, `created_at`, `version`, `is_adequate`, or `status`, are ignored — never echoed and never rejected.
6. Sixth, the optimistic-concurrency token on the two guarded writes (`ERR_STALE_VERSION`).
7. Seventh, the state-machine preconditions of the target transition — filing only from a draft, a decision only on a filed application, an outcome only on a scheduled inspection, and so on (`ERR_INVALID_STATE`).
8. Eighth, bioequivalence adequacy at filing and at the approval decision (`ERR_NO_ADEQUATE_BE_STUDY`).
9. Ninth, facility clearance at the approval decision (`ERR_FACILITY_CLEARANCE_FAILED`).
10. Tenth, waiver legitimacy when an inspection outcome of `WAIVED` is recorded (`ERR_FOREIGN_FACILITY_WAIVER`).
11. Eleventh, the new-chemical-entity submission bar at filing (`ERR_NCE_SUBMISSION_BARRED`).
12. Twelfth, inspection-window overlap when an inspection is scheduled (`ERR_INSPECTION_OVERLAP`).
13. Thirteenth, protected-indication window overlap when a protection is registered (`ERR_INDICATION_WINDOW_OVERLAP`).
14. Fourteenth, carve-out completeness in both directions, checked at application creation, at filing, and at the approval decision (`ERR_LABEL_CARVE_OUT_INCOMPLETE`, `ERR_CARVE_OUT_OF_UNPROTECTED`).
15. Fifteenth, certification completeness at filing (`ERR_CERTIFICATION_INCOMPLETE`).
16. Sixteenth, uniqueness — one certification per application-and-patent pair and one notice per paragraph-IV certification (`ERR_DUPLICATE_CERTIFICATION`, `ERR_NOTICE_ALREADY_EXISTS`).
17. Seventeenth, an outstanding paragraph-IV notice blocks the approval decision (`ERR_P4_NOTICE_REQUIRED`).
18. Eighteenth, a supplement's pathway must be permitted for its change type (`ERR_INVALID_PATHWAY_FOR_CHANGE`).
19. Nineteenth, a certification's patent must be listed on the application's reference product (`ERR_PATENT_NOT_LISTED_FOR_REFERENCE_PRODUCT`).
20. Twentieth, an inspection's facility must belong to the same applicant as the application (`ERR_FACILITY_APPLICATION_MISMATCH`).
21. Twenty-first, a protected indication's code must be a member of the reference product's approved indication codes (`ERR_INDICATION_NOT_ON_REFERENCE_PRODUCT`).
22. Twenty-second, a method-of-use patent must carry its use code (`ERR_INVALID_REQUEST`).

### 2.8. Nested Resource Retrieval

Endpoints whose paths contain several identifiers validate them strictly left to right, and the response carries the 404 of the first identifier that does not resolve. A request aimed at the review cycles of a non-existent application fails with `ERR_APPLICATION_NOT_FOUND` before cycle state is ever consulted; a litigation event against a non-existent notice fails with `ERR_NOTICE_NOT_FOUND` regardless of what the payload contains. Existence of the parent container is always settled before any rule that depends on the child.

### 2.9. Numeric Precision and Rounding

Confidence-interval bounds on bioequivalence studies are compared only after each bound has been independently rounded to exactly two decimal places using round-half-up decimal arithmetic; the rounded values, not the raw submissions, decide adequacy. The two regulatory bounds themselves are expressed to two decimals — 80.00 and 125.00 — and comparisons against them are inclusive. Calendar arithmetic everywhere else in the system is exact to whole days under the conventions of §2.4.

## 3. Business Logic & Workflows

### 3.1. Registering the Regulatory Cast: Applicants, Reference Products, and Facilities

Before any application can be filed, a `ProgramAdmin` builds the registry. An `ApplicantCompany` is registered with its `legal_name`, a regulatory `contact_email`, and the `headquarters_country` expressed as an ISO 3166-1 alpha-2 code. A `ReferenceProduct` captures the innovator's approved drug: its `brand_name`, `active_ingredient`, a `strength` declaration such as "20 mg", and a free-form `dosage_form` string (values such as TABLET, CAPSULE, or INJECTION are conventional but not constrained). Two fields on the reference product drive later statutory clocks: `rld_approval_date`, the calendar date the product was approved, which anchors the new-chemical-entity submission bars; and `is_new_chemical_entity`, a boolean defaulting to false, which switches those bars on. The product's full set of approved indication codes is recorded in `indication_codes`, and `patent_owner_user_id` stores the opaque `X-User-ID` of the `InnovatorSponsor` authorized to list patents and report litigation for this product.

Each `ApplicantSponsor` then registers its own manufacturing estate. Creating a `ManufacturingFacility` requires an `applicant_id` equal to the caller's `X-User-ID`, a `facility_name`, the establishment identifier `fei_number`, and the site's `country_code`. The server derives `is_foreign` itself: it is true whenever `country_code` is anything other than "US". An applicant's facilities are retrievable as a collection under the company record, and every inspection rule in §3.6 keys off this derived foreign flag.

### 3.2. Listing Patents and Protecting Indications

The innovator side of the registry belongs to the `InnovatorSponsor` whose `X-User-ID` matches the product's `patent_owner_user_id`. Listing a `ListedPatent` requires the `patent_number`, a `patent_type` of `DRUG_SUBSTANCE`, `DRUG_PRODUCT`, or `METHOD_OF_USE`, and the `expiry_date` on which the patent lapses. A `use_code` such as "U-123" must be supplied exactly when the type is `METHOD_OF_USE` and must be null for the other two types; either violation is an `ERR_INVALID_REQUEST`. A patent stands `LISTED` while the logical clock has not moved beyond its `expiry_date` and becomes `EXPIRED` once it has — including at registration, where a patent listed with an already-past `expiry_date` starts directly in `EXPIRED`. Expiry is consequential: every paragraph-III deferral on that patent stops contributing to each referencing application's `patent_blocked_until`, any litigation block decided in the patent's favor lifts with it, and each tentatively approved application referencing the patent is re-evaluated and auto-approves if no block remains.

A `ProgramAdmin` may also register a `ProtectedIndication` when an indication enjoys its own exclusivity or method-of-use coverage. The `indication_code` must be a member of the reference product's `indication_codes` — anything else is rejected with `ERR_INDICATION_NOT_ON_REFERENCE_PRODUCT`. The protection window runs from `effective_from` through `protected_until`, both dates inclusive, and `protected_until` must be on or after `effective_from`. The window stands `ACTIVE` until the logical clock moves beyond `protected_until`, then turns `EXPIRED`; a window registered entirely in the past starts `EXPIRED`. When a window expires, the carve-out obligations of applications against that product change the next time a filing or an approval is validated.

Protection windows for the same product and the same `indication_code` may not overlap, and the rule uses closed-interval semantics on both ends: a new `ACTIVE` window conflicts with an existing `ACTIVE` window whenever the new window starts on or before the existing window's end and the existing window starts on or before the new window's end. Adjacency therefore counts as conflict — a new window whose `effective_from` is exactly the existing window's `protected_until` is rejected with `ERR_INDICATION_WINDOW_OVERLAP` (HTTP 409). `EXPIRED` windows never block new registrations. This is deliberately stricter than the inspection-scheduling rule of §3.6, where abutting windows are allowed.

### 3.3. Assembling the Application: Bioequivalence, Certifications, and the Filing Gate

An `ApplicantSponsor` begins an abbreviated application as a `DRAFT` `GenericApplication`, naming the `reference_product_id` it claims equivalence to and an `applicant_id` equal to the caller's `X-User-ID`. The `review_priority` is `STANDARD` by default and may be declared `PRIORITY`; the choice drives the review goal described in §3.5. The `labeling_mode` is either `FULL`, asserting all reference indications, or `CARVE_OUT`, omitting protected ones; in the latter case `carved_indication_codes` lists the omitted codes, and it defaults to an empty list. While the application is a draft, its `current_cycle_number` reads 0.

Labeling honesty is checked against the live protection registry at three moments — application creation, filing, and the approval decision. The rule is exact set equality between `carved_indication_codes` and the reference product's currently `ACTIVE` protected-indication codes: a protected code missing from the carve-out, or a `FULL` label submitted while any protection is active, fails with `ERR_LABEL_CARVE_OUT_INCOMPLETE`; a carved code that names an indication under no active protection fails with `ERR_CARVE_OUT_OF_UNPROTECTED`. When a submission fails in both directions at once, `ERR_LABEL_CARVE_OUT_INCOMPLETE` is the one reported.

Bioequivalence is demonstrated study by study. While the application is `DRAFT` or `RECEIVED`, the sponsor submits a `BioequivalenceStudy` carrying a `study_type` of `FASTING` or `FED`, the measured `analyte`, and six percentage figures: the test-to-reference ratios `auc_ratio_pct` and `cmax_ratio_pct`, and the bounds of the two ninety-percent confidence intervals, `auc_ci_low_pct` and `auc_ci_high_pct` for overall exposure and `cmax_ci_low_pct` and `cmax_ci_high_pct` for peak exposure. The server alone computes `is_adequate` — any client-supplied verdict is ignored. Each of the four interval bounds is first rounded to two decimal places, round half up, per bound and before any comparison; the study is adequate when the rounded AUC lower bound is at least 80.00, the rounded AUC upper bound is at most 125.00, the rounded Cmax lower bound is at least 80.00, and the rounded Cmax upper bound is at most 125.00. The bounds are inclusive, so a rounded bound of exactly 80.00 or exactly 125.00 passes. The study's `status` is set once at creation — `ACCEPTED` when adequate, `DEFICIENT` otherwise — and never changes afterward; a superseding study is simply a new study record. Each study is judged on its own numbers; bounds are never averaged or pooled across studies.

Every listed patent of the reference product must be addressed by exactly one `PatentCertification`, filed while the application is a draft. The sponsor names the `patent_id` and a `certification_type`: `PARAGRAPH_II_EXPIRED` when the patent has already expired, `PARAGRAPH_III_DEFER` when the applicant commits to wait for expiry before marketing, or `PARAGRAPH_IV_CHALLENGE` when the applicant asserts the patent is invalid or not infringed. A reference product with no listed patents is the implicit paragraph-I case and requires no certifications at all. Filing a certification requires the OCC token `expected_application_version` (§2.6), stamps the `filed_date`, and advances the application's `version` by one. The patent must be one listed on the application's own reference product (`ERR_PATENT_NOT_LISTED_FOR_REFERENCE_PRODUCT`), and a second certification for the same application-and-patent pair is refused as `ERR_DUPLICATE_CERTIFICATION`.

Filing the application — moving it from `DRAFT` to `RECEIVED` — runs the full statutory gate in the priority order of §2.7: the application must be a draft (`ERR_INVALID_STATE`); at least one study must stand `ACCEPTED` (`ERR_NO_ADEQUATE_BE_STUDY`); the new-chemical-entity bar must permit filing (`ERR_NCE_SUBMISSION_BARRED`); the carve-out must match the active protections exactly (the two labeling errors above); and there must be exactly one certification per currently `LISTED` patent of the reference product (`ERR_CERTIFICATION_INCOMPLETE`). The NCE bar applies only when the reference product's `is_new_chemical_entity` is true: before the date 48 calendar months after `rld_approval_date` no filing is permitted at all; beginning exactly on that 48-month date and running until the date 60 calendar months after `rld_approval_date`, filing is permitted only when the application carries at least one `PARAGRAPH_IV_CHALLENGE` certification; on or after the 60-month date, filing is unrestricted. The boundaries are inclusive — a filing made exactly on the 48-month date with a paragraph-IV certification succeeds, while one day earlier is barred.

A successful filing stamps `received_date` with the current logical date, sets `current_cycle_number` to 1, and opens the first `ReviewCycle` in `OPEN` status with `opened_date` equal to the receipt date and `base_review_months` snapshotted at 8 for a `PRIORITY` application or 10 for a `STANDARD` one. If the application carries at least one paragraph-IV certification and no `ExclusivityAward` yet exists for the reference product, the system creates one in `ELIGIBLE` status for this application — the first-filer determination. The first application to reach `RECEIVED` wins; should two receipts land at the same logical instant, the one whose submission was committed first prevails, and random identifiers never participate in the tie-break. The application's `version` increments by one.

### 3.4. Paragraph IV Notice, Suit Windows, and the Litigation Stay

A paragraph-IV challenge obliges the applicant to notify the patent owner. Once the application stands `RECEIVED` or `TENTATIVE_APPROVAL`, the sponsor records a `PatentChallengeNotice` bound by its `certification_id` to a certification that still stands `CERTIFIED` with type `PARAGRAPH_IV_CHALLENGE`; any other application state or certification posture is refused with `ERR_INVALID_STATE`, and a second notice against the same certification is refused with `ERR_NOTICE_ALREADY_EXISTS` — exactly one notice may exist per certification. The `notice_date` is the logical date of recording. Timeliness is computed immediately: `is_timely` is true when the notice date falls within 20 calendar days of the application's `received_date`, the twentieth day itself counting as timely. A late notice is still recorded, but recording it forfeits the applicant's `ELIGIBLE` exclusivity award with reason `NOTICE_LATE`. The notice also computes its `suit_deadline`, the calendar date 45 days after the notice date.

The `InnovatorSponsor` who owns the patent side of the reference product then decides whether to sue. Recording a litigation event with `event_type` `SUIT_FILED` requires the notice to still stand in `NOTICE_SENT` and an `event_date` that is on or after the `notice_date`, on or before the `suit_deadline` — the forty-fifth day is inclusive — and not later than the current logical date; a bad date or payload shape is `ERR_INVALID_REQUEST`, and a wrong notice posture is `ERR_INVALID_STATE`. A timely suit records the `suit_filed_date` and erects the statutory stay: `stay_until` is set to the date 30 calendar months after the notice date under the month-clamping convention, and the stay immediately contributes to the parent application's `patent_blocked_until`. The notice stands at `SUIT_FILED` with `court_outcome` still `NONE`. Although the litigation-event endpoint declares both `InnovatorSponsor` and `ProgramAdmin`, the event itself selects the actor — a `SUIT_FILED` event is accepted only from the `InnovatorSponsor`, a `COURT_DECIDED` event only from the `ProgramAdmin`, and any other pairing is rejected with `ERR_INSUFFICIENT_PERMISSIONS` — and its checks run in this order: the notice must exist (`ERR_NOTICE_NOT_FOUND`); `event_type` must be a declared member (`ERR_INVALID_REQUEST`); the event-type role check fires; for `SUIT_FILED` the innovator-ownership check on the reference product follows (`ERR_NOT_RESOURCE_OWNER`); the remaining body shape is validated; the notice's posture is checked (`ERR_INVALID_STATE`); and the `event_date` window is evaluated last (`ERR_INVALID_REQUEST`).

Should the logical clock pass the suit deadline with no suit recorded, the notice settles into `NO_SUIT_FILED` and no stay ever attaches — under the system's pinned optimistic posture, an open suit window contributes nothing to any block. A late suit can never be recorded after that: the event date may not lie in the future relative to the logical clock, and by the time the clock has moved past the deadline the notice has already left `NOTICE_SENT`, so the attempt fails as `ERR_INVALID_STATE`.

Court outcomes are recorded by a `ProgramAdmin` as a litigation event with `event_type` `COURT_DECIDED` while the notice stands `SUIT_FILED`, carrying an `outcome` of `PATENT_VALID` or `PATENT_INVALID_OR_NOT_INFRINGED` and an `event_date` on or after the `suit_filed_date` and not later than the current logical date. A decision of invalid-or-not-infringed moves the notice to `DECIDED_INVALID`, stamps `court_decision_date`, and lifts the application's patent block entirely, prompting re-evaluation of any tentatively approved application. A decision upholding the patent moves the notice to `DECIDED_VALID` and converts the block to run until the patent's own `expiry_date` in place of the stay. Should the clock pass `stay_until` with the `court_outcome` still `NONE`, the notice becomes `STAY_EXPIRED`, the stay lifts, and the same re-evaluation fires.

Either litigation story can be cut short when the applicant retreats from its challenge. While the parent application is neither `APPROVED` nor in a terminal state, the sponsor may amend a certification that still stands `CERTIFIED` with type `PARAGRAPH_IV_CHALLENGE`; any other certification is `ERR_CERTIFICATION_NOT_AMENDABLE`, and an approved or terminal application is `ERR_INVALID_STATE`. The amendment is one-way to paragraph III: the certification moves to `AMENDED_TO_P3` — its stored `certification_type` is not rewritten and continues to read `PARAGRAPH_IV_CHALLENGE` — is treated thereafter as `PARAGRAPH_III_DEFER` (deferring to the patent's expiry) for blocking and notice purposes, stamps `amended_date`, recomputes the application's `patent_blocked_until`, forfeits an `ELIGIBLE` or `AWARDED` exclusivity award with reason `CERTIFICATION_AMENDED` (with the sibling unblocking and re-evaluation of §3.8), and advances the application's `version` by one.

### 3.5. Review Cycles, Deficiency Letters, and Amendments

Review proceeds in numbered cycles. A `ReviewCycle` snapshots its `base_review_months` at opening — 8 when the application's `review_priority` is `PRIORITY`, 10 when `STANDARD` — and tracks `major_amendment_extensions_count`, initially zero. Its `goal_date` is derived by adding to `opened_date` a number of calendar months equal to the base plus three additional months for each major amendment applied to the cycle, clamped per the month convention and recomputed on every such amendment; there is no cap on extensions. An application's cycles are listed in ascending `cycle_number` order, and the application's `open_deficiency_count` reports how many of its cycles currently stand in `CRL_ISSUED`.

When the review cannot complete on the current record, a `RegulatoryReviewer` issues a deficiency letter against a cycle that stands `OPEN` on an application in `RECEIVED` — any other posture is `ERR_INVALID_STATE`. The cycle moves to `CRL_ISSUED`, `deficiency_issued_date` is stamped with the current logical date, an optional free-text `deficiency_summary` may be recorded, and `deficiency_response_due_date` is computed as twelve calendar months after the issue date under the clamping convention. The parent's `open_deficiency_count` rises by one.

The sponsor answers with an `Amendment`. Every amendment carries a `classification` of `MAJOR` or `MINOR`, a `contains_new_be_data` flag, optional free-text `notes`, and the OCC token `expected_application_version`; the server stamps `submitted_date` and advances the application's `version` by one. While the application's current cycle stands in `CRL_ISSUED`, the amendment is treated as the deficiency response: it must arrive on or before `deficiency_response_due_date` — the due date itself is timely — whereupon `deficiency_response_received_date` is stamped, the cycle moves to `AMENDMENT_RECEIVED`, and the open-deficiency count falls by one. A response later than the due date cannot be accepted at all, because the lapse described below has already closed the matter, and the attempt fails with `ERR_INVALID_STATE`. Amendments submitted while the current cycle stands `OPEN` or `AMENDMENT_RECEIVED` are unsolicited and equally permitted — amendments are legitimately creatable in sequence. Every `MAJOR` amendment applied to the current cycle, whether a deficiency response or unsolicited, adds exactly one extension and recomputes the cycle's `goal_date`. An amendment may be filed only while the application stands `RECEIVED` or `TENTATIVE_APPROVAL`; anything else is `ERR_INVALID_STATE`.

Should the logical clock pass the response due date with `deficiency_response_received_date` still unset, the cycle lapses: it moves to `LAPSED` with `closed_reason` `LAPSED`, the parent application collapses to `LAPSED` as well, and an `ELIGIBLE` exclusivity award held by that application is forfeited with reason `APPLICATION_LAPSED`, with the sibling unblocking and re-evaluation of §3.8. Lapse is terminal for the application.

A deficiency letter issued against a cycle that already stands in `AMENDMENT_RECEIVED` starts the next round: the current cycle closes — status `CLOSED` with `closed_reason` `SUPERSEDED` — and a fresh cycle opens already in `CRL_ISSUED`, with a new `opened_date`, a new issue date, a new twelve-month response clock, and a fresh base snapshot per the application's priority; the parent's `current_cycle_number` advances by one and the open-deficiency count reflects the new cycle's contribution of one.

Amending a `TENTATIVE_APPROVAL` application reopens review entirely: the application falls back to `RECEIVED`, its `tentative_approval_date` is cleared to null, the next cycle opens in `OPEN` with a fresh base snapshot, and `current_cycle_number` advances by one; if the reopening amendment is `MAJOR`, the new cycle begins with `major_amendment_extensions_count` already at one. Approval decisions and withdrawals close whatever cycle is current, stamping `closed_reason` `APPROVAL`, `TENTATIVE_APPROVAL`, or `REFUSAL` for the corresponding decisions, or `SUPERSEDED` on withdrawal. One asymmetry is enforced at the decision gate itself: while any cycle of the application stands in `CRL_ISSUED` without a recorded response, a review decision is refused outright with `ERR_DEFICIENCY_RESPONSE_OPEN`.

### 3.6. Facility Inspections and Clearance

Approval is impossible until the manufacturing estate clears inspection. A `RegulatoryReviewer` schedules a `FacilityInspection` by naming the `facility_id`, the `application_id` it supports, and the window's `scheduled_start_date` and `scheduled_end_date`; the end date must be on or after the start date. The `inspection_type` is `PRE_APPROVAL`, the only supported kind — the field may be omitted from the payload and defaults to `PRE_APPROVAL`, and any other supplied value is rejected with `ERR_INVALID_REQUEST` — and the new inspection stands `SCHEDULED`. The facility must belong to the same applicant that owns the application — a cross-applicant pairing is rejected with `ERR_FACILITY_APPLICATION_MISMATCH`.

One facility cannot host two overlapping scheduled inspections. The occupied window is the half-open interval from `scheduled_start_date` up to but not including `scheduled_end_date`, and a new inspection conflicts with an existing `SCHEDULED` inspection of the same facility exactly when the new start falls before the existing end and the existing start falls before the new end. Adjacency is allowed: a new window starting on the very day another window ends does not conflict. Inspections that have reached any terminal outcome never block. A genuine collision is rejected with `ERR_INSPECTION_OVERLAP` (HTTP 409). Recall from §3.2 that protected-indication windows use the opposite, closed-interval rule, under which adjacency is itself a conflict.

A `FacilityInspector` records the `outcome` of a `SCHEDULED` inspection as `PASSED`, `FAILED`, `WAIVED`, or `CANCELLED`; an inspection in any other posture refuses the recording with `ERR_INVALID_STATE`, and the `outcome_date` is stamped at recording. `WAIVED` is reserved for a domestic facility — its `is_foreign` must be false — that has another inspection recorded `PASSED` with an `outcome_date` within the 24 calendar months preceding the waiver; a waiver for a foreign site, or one without that prior pass, fails with `ERR_FOREIGN_FACILITY_WAIVER`. A `CANCELLED` inspection is inert: it participates neither in clearance evaluation nor in overlap blocking.

Clearance is evaluated at the approval gate. Consider the distinct facilities appearing on the application's non-`CANCELLED` inspections; if there are none at all, clearance fails outright. For each such facility, only its latest-recorded non-`CANCELLED` inspection counts, whatever posture it stands in — a facility whose latest such inspection is still `SCHEDULED` has no passing outcome and fails clearance until that inspection's outcome is recorded; inspections are committed sequentially so ties cannot arise, and `created_at` is the fallback ordering key, never the resource `id`. Clearance demands that every facility's latest non-`CANCELLED` inspection stand `PASSED` or `WAIVED`, and additionally that every foreign facility have at least one `PASSED` inspection for this application — a waiver never clears a foreign site. Any shortfall rejects the decision with `ERR_FACILITY_CLEARANCE_FAILED`.

### 3.7. The Approval Decision: Blocks, Posture, and Tentative Approval

A `RegulatoryReviewer` closes the scientific review with a `decision` of `APPROVE` or `REFUSE` on an application standing `RECEIVED`. Refusal is always available once the request clears the opening gates — the `RECEIVED` posture and the deficiency-response gate of §3.5 bind `APPROVE` and `REFUSE` alike: the application falls to `REFUSED_APPROVAL`, terminal, the current cycle closes with `closed_reason` `REFUSAL`, and — critically — an `ELIGIBLE` award survives the refusal; only the running thirty-month tentative-approval clock described in §3.8 can still forfeit it later as `TA_NOT_OBTAINED_30MO`.

Approval is gated twice. The scientific gates, evaluated in the pipeline order of §2.7, demand: the application standing `RECEIVED` (`ERR_INVALID_STATE`); no cycle in `CRL_ISSUED` awaiting a response (`ERR_DEFICIENCY_RESPONSE_OPEN`); at least one `ACCEPTED` study (`ERR_NO_ADEQUATE_BE_STUDY`); facility clearance per §3.6 (`ERR_FACILITY_CLEARANCE_FAILED`); the carve-out still matching the currently `ACTIVE` protections (the two labeling errors of §3.3); and every paragraph-IV certification still standing `CERTIFIED` carrying its notice (`ERR_P4_NOTICE_REQUIRED`). A certification already amended to paragraph III no longer needs a notice — the requirement binds only while the certification remains `CERTIFIED` as a challenge.

The second gate is patent-side posture. Each certification still standing — `CERTIFIED`, or `AMENDED_TO_P3` — against a patent still `LISTED` contributes a block date as follows. A `PARAGRAPH_II_EXPIRED` certification never blocks. A `PARAGRAPH_III_DEFER` certification blocks until the patent's `expiry_date`: the block holds while the current logical date is earlier than the expiry date and releases on the date itself. A `PARAGRAPH_IV_CHALLENGE` certification blocks according to its notice posture: a notice sent but unanswered (`NOTICE_SENT`) or a window closed without suit (`NO_SUIT_FILED`) contributes nothing, because an open suit window never blocks; a suit pending decision blocks until `stay_until`; a decision of invalid-or-not-infringed (`DECIDED_INVALID`) contributes nothing; a decision upholding the patent (`DECIDED_VALID`) blocks until the patent's `expiry_date`. A challenge with no notice recorded at all is not a date block — it is the hard `ERR_P4_NOTICE_REQUIRED` gate described above. The application's `patent_blocked_until` surfaces the latest contributing block date that lies strictly after the current logical date, or null when no block is active. Separately, the application's `exclusivity_blocked` flag is true whenever another application's award for the same reference product stands `AWARDED`, or stands `ACTIVE` with the current logical date still earlier than its `exclusivity_end_date`.

When both gates are clear, `APPROVE` yields `APPROVED`: `approval_date` is stamped, the current cycle closes with `closed_reason` `APPROVAL`, an `ELIGIBLE` award held by this application converts to `AWARDED`, and `version` increments by one. When the science passes but a block is active — `patent_blocked_until` set, or `exclusivity_blocked` true — the same `APPROVE` yields `TENTATIVE_APPROVAL` instead: `tentative_approval_date` is stamped and the cycle closes with `closed_reason` `TENTATIVE_APPROVAL`.

Tentative approval is a waiting room with a vigilant attendant. After every clock advance, litigation event, certification amendment, patent expiry, or exclusivity transition, the system re-evaluates each `TENTATIVE_APPROVAL` application: when no patent block remains, exclusivity no longer blocks, and the carve-out still matches the active protections, the application converts to `APPROVED` automatically — `approval_date` is stamped with the current logical date, `tentative_approval_date` is retained as history, an `ELIGIBLE` award on the application converts to `AWARDED`, and `version` increments. If the protection set has drifted so the carve-out no longer matches, the application holds in `TENTATIVE_APPROVAL` until its labeling is amended.

### 3.8. First-Filer Exclusivity: Award, Marketing, and Forfeiture

The `ExclusivityAward` is the program's prize for challenging a patent. Created `ELIGIBLE` at filing per §3.3, it is tied to one application and one `reference_product_id`. When the award-holding application reaches `APPROVED` — directly or through the re-evaluation of §3.7 — the award converts to `AWARDED`: `awarded_date` and the copied `approval_date` are set, and `marketing_deadline` is computed as the calendar date 75 days after the approval date. From that moment every sibling application against the same product computes `exclusivity_blocked` true and can no longer reach full approval.

To bank the exclusivity, the sponsor records first commercial marketing on the approved, award-holding application; any other posture — an application not `APPROVED`, or an award not standing `AWARDED` — is `ERR_INVALID_STATE`. This stamps `first_marketing_date` on both the award and the application, computes `exclusivity_end_date` as the date 180 calendar days after that marketing date, and moves the award to `ACTIVE`; the application's `version` increments by one. The response carries the updated `ExclusivityAward` object. The block on siblings persists while the award stands `ACTIVE` and the current logical date is earlier than `exclusivity_end_date`; when the clock reaches that date the block lifts at the date itself, the award settles to `EXPIRED`, siblings recompute `exclusivity_blocked` false, and their tentative approvals re-evaluate.

Six events forfeit the award, moving it to `FORFEITED` and recording a `forfeiture_reason`. From `ELIGIBLE`: a late paragraph-IV notice (`NOTICE_LATE`); a paragraph-IV certification amended to paragraph III (`CERTIFICATION_AMENDED`); withdrawal of the application (`APPLICATION_WITHDRAWN`); lapse of the application (`APPLICATION_LAPSED`); and the logical clock passing the date 30 calendar months after the application's `received_date` — clamped month arithmetic — while the application has reached neither `TENTATIVE_APPROVAL` nor `APPROVED` (`TA_NOT_OBTAINED_30MO`). From `AWARDED`: the certification-amendment and withdrawal events again, plus the clock passing `marketing_deadline` with no first marketing recorded (`MARKETING_NOT_COMMENCED_75D`) — marketing recorded exactly on the deadline day is timely. Forfeiture of an `ELIGIBLE` award creates no successor award for the reference product and changes nothing for siblings, since mere eligibility never blocked them. Forfeiture of an `AWARDED` award lifts the block: siblings recompute `exclusivity_blocked` false and their tentative approvals re-evaluate.

Withdrawal deserves its own word. The sponsor may withdraw the application — moving it to `WITHDRAWN` — from `DRAFT` (a clean exit with no cascade), from `RECEIVED` (the open cycle closes with `closed_reason` `SUPERSEDED`, and an `ELIGIBLE` or `AWARDED` award is forfeited as `APPLICATION_WITHDRAWN`), from `TENTATIVE_APPROVAL` (the cycle already stands closed from the tentative approval; the same forfeiture fires), or from `APPROVED` (an `AWARDED` or `ACTIVE` award is forfeited on the same reason). Each withdrawal advances the application's `version` by one, and wherever a blocking award is released, the sibling unblocking and re-evaluation described above follows.

### 3.9. Post-Approval Change Supplements

Once an application stands `APPROVED`, its sponsor reports changes through `Supplement` records; filing one against an application in any other state fails with `ERR_APPLICATION_NOT_APPROVED`. Each supplement declares a `change_type` — `MANUFACTURING_SITE`, `FORMULATION`, `LABELING`, `PACKAGING`, or `EDITORIAL` — and a `pathway` of `PRIOR_APPROVAL`, `CBE_30`, `CBE_0`, or `ANNUAL_REPORT`, plus an optional free-text `description`. The pathway must be one the change type permits: a `MANUFACTURING_SITE` or `FORMULATION` change travels only as `PRIOR_APPROVAL`; a `LABELING` change may travel `PRIOR_APPROVAL` or `CBE_30`; a `PACKAGING` change may travel `PRIOR_APPROVAL`, `CBE_30`, or `CBE_0`; and an `EDITORIAL` change travels only `CBE_0` or `ANNUAL_REPORT`. Any other pairing is rejected with `ERR_INVALID_PATHWAY_FOR_CHANGE`.

A supplement lives on two independent axes. Its `review_status` runs from `SUBMITTED` to `APPROVED`, `REJECTED`, or `WITHDRAWN` — except annual reports, which are born `LOGGED`, terminal and never reviewable. Its `effectivity` runs from `NOT_EFFECTIVE` to `EFFECTIVE` and possibly on to `REVOKED`. The pathway fixes the creation posture: `PRIOR_APPROVAL` and `CBE_30` supplements arrive `SUBMITTED` and `NOT_EFFECTIVE`; a `CBE_0` supplement arrives `SUBMITTED` and already `EFFECTIVE`, with `effective_date` equal to its `submitted_date`; an `ANNUAL_REPORT` supplement arrives `LOGGED` and `EFFECTIVE`, likewise effective on its submission date. The parent's `open_supplement_count` — its running tally of supplements standing `SUBMITTED` — rises by one for the three reviewable pathways and is left untouched by an annual report.

A `CBE_30` supplement takes effect on its own clock: when the logical clock reaches the date 30 calendar days after `submitted_date` — the thirtieth day itself counts — while the supplement still stands `SUBMITTED`, its effectivity flips to `EFFECTIVE` with `effective_date` set to that thirtieth day. A later approval does not alter this timing. A `PRIOR_APPROVAL` supplement, by contrast, becomes effective only upon approval, with `effective_date` equal to the decision date.

A `RegulatoryReviewer` decides a `SUBMITTED` supplement with a `decision` of `APPROVE` or `REJECT`; a supplement no longer `SUBMITTED` refuses with `ERR_INVALID_STATE`, and an annual report is never decidable at all — an annual report, born `LOGGED` and never `SUBMITTED`, draws `ERR_SUPPLEMENT_NOT_REVIEWABLE`, a check applied before the `SUBMITTED` posture is consulted. Approval stamps `decision_date`, activates a still-ineffective `PRIOR_APPROVAL` supplement as described above, and leaves `CBE_30` timing untouched. Rejection stamps `decision_date` and revokes a change that had already taken effect — the effectivity of a `CBE_0` supplement, or of a `CBE_30` supplement past its thirtieth day, moves to `REVOKED`, and distribution under the change must cease. The sponsor may likewise withdraw a `SUBMITTED` supplement, moving it to `WITHDRAWN` and revoking any effectivity already in force. Decisions and withdrawals each decrement the parent's `open_supplement_count` by one.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that act on an existing resource in place return `200 OK`. The deficiency-letter action returns `201 Created` because it advances the application's cycle structure — materializing the next review cycle when issued against an answered cycle — and the clock-setting capability returns `200 OK`. Retrieval endpoints accept all five roles; the table abbreviates this as "All five roles".

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the logical clock to a supplied instant | ProgramAdmin |
| POST | `/generic-drug-review/applicant-companies` | Register a generic applicant company | ProgramAdmin |
| GET | `/generic-drug-review/applicant-companies/{id}` | Get one applicant company | All five roles |
| GET | `/generic-drug-review/applicant-companies/{id}/manufacturing-facilities` | List facilities owned by an applicant | All five roles |
| POST | `/generic-drug-review/manufacturing-facilities` | Register a manufacturing facility owned by the acting applicant | ApplicantSponsor |
| POST | `/generic-drug-review/reference-products` | Register a reference listed drug | ProgramAdmin |
| GET | `/generic-drug-review/reference-products/{id}` | Get one reference product | All five roles |
| POST | `/generic-drug-review/reference-products/{id}/listed-patents` | List a patent against the reference product | InnovatorSponsor |
| GET | `/generic-drug-review/reference-products/{id}/listed-patents` | List patents of a reference product | All five roles |
| POST | `/generic-drug-review/reference-products/{id}/protected-indications` | Register a protected indication window | ProgramAdmin |
| GET | `/generic-drug-review/reference-products/{id}/protected-indications` | List protected indications of a reference product | All five roles |
| POST | `/generic-drug-review/applications` | Create a DRAFT abbreviated application | ApplicantSponsor |
| GET | `/generic-drug-review/applications` | List applications with optional filters | All five roles |
| GET | `/generic-drug-review/applications/{id}` | Get one application including computed posture fields | All five roles |
| POST | `/generic-drug-review/applications/{id}/submit` | File the application (runs the full filing gate) | ApplicantSponsor |
| POST | `/generic-drug-review/applications/{id}/approval-decision` | Approve or refuse the current review cycle | RegulatoryReviewer |
| POST | `/generic-drug-review/applications/{id}/withdraw` | Withdraw the application from its current state | ApplicantSponsor |
| POST | `/generic-drug-review/applications/{id}/record-first-marketing` | Record first commercial marketing of an approved first-filer | ApplicantSponsor |
| POST | `/generic-drug-review/applications/{id}/bioequivalence-studies` | Submit a bioequivalence study | ApplicantSponsor |
| GET | `/generic-drug-review/applications/{id}/bioequivalence-studies` | List BE studies of an application | All five roles |
| POST | `/generic-drug-review/applications/{id}/patent-certifications` | File a patent certification on a DRAFT application (OCC-guarded) | ApplicantSponsor |
| GET | `/generic-drug-review/patent-certifications/{id}` | Get one patent certification | All five roles |
| GET | `/generic-drug-review/patent-certifications` | List patent certifications with optional filters | All five roles |
| POST | `/generic-drug-review/patent-certifications/{id}/amend` | Amend a paragraph-IV certification to paragraph III (one-way) | ApplicantSponsor |
| POST | `/generic-drug-review/patent-certifications/{id}/notices` | Record the paragraph-IV notice to the patent holder | ApplicantSponsor |
| GET | `/generic-drug-review/patent-certifications/{id}/notices` | List notices for a certification (0 or 1 element) | All five roles |
| POST | `/generic-drug-review/patent-notices/{id}/litigation-events` | Record a litigation event (suit filed or court decision) | InnovatorSponsor, ProgramAdmin |
| GET | `/generic-drug-review/applications/{id}/review-cycles` | List review cycles of an application, ordered by cycle number ascending | All five roles |
| POST | `/generic-drug-review/review-cycles/{id}/issue-deficiency` | Issue a deficiency letter (complete response) | RegulatoryReviewer |
| POST | `/generic-drug-review/applications/{id}/amendments` | Submit an amendment (OCC-guarded) | ApplicantSponsor |
| GET | `/generic-drug-review/applications/{id}/amendments` | List amendments of an application | All five roles |
| POST | `/generic-drug-review/facility-inspections` | Schedule a pre-approval inspection of a facility for an application | RegulatoryReviewer |
| GET | `/generic-drug-review/facility-inspections/{id}` | Get one facility inspection | All five roles |
| GET | `/generic-drug-review/facility-inspections` | List facility inspections with optional filters | All five roles |
| POST | `/generic-drug-review/facility-inspections/{id}/record-outcome` | Record the inspection outcome | FacilityInspector |
| POST | `/generic-drug-review/applications/{id}/supplements` | Submit a post-approval change supplement | ApplicantSponsor |
| GET | `/generic-drug-review/applications/{id}/supplements` | List supplements of an application | All five roles |
| POST | `/generic-drug-review/supplements/{id}/review-decision` | Approve or reject a SUBMITTED supplement | RegulatoryReviewer |
| POST | `/generic-drug-review/supplements/{id}/withdraw` | Withdraw a SUBMITTED supplement | ApplicantSponsor |
| GET | `/generic-drug-review/exclusivity-awards/{id}` | Get one exclusivity award | All five roles |
| GET | `/generic-drug-review/exclusivity-awards` | List exclusivity awards with optional filters | All five roles |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_APPLICANT_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENCE_PRODUCT_NOT_FOUND` | 404 Not Found |
| `ERR_LISTED_PATENT_NOT_FOUND` | 404 Not Found |
| `ERR_APPLICATION_NOT_FOUND` | 404 Not Found |
| `ERR_CERTIFICATION_NOT_FOUND` | 404 Not Found |
| `ERR_NOTICE_NOT_FOUND` | 404 Not Found |
| `ERR_REVIEW_CYCLE_NOT_FOUND` | 404 Not Found |
| `ERR_FACILITY_NOT_FOUND` | 404 Not Found |
| `ERR_INSPECTION_NOT_FOUND` | 404 Not Found |
| `ERR_SUPPLEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_EXCLUSIVITY_AWARD_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_DEFICIENCY_RESPONSE_OPEN` | 409 Conflict |
| `ERR_CERTIFICATION_NOT_AMENDABLE` | 409 Conflict |
| `ERR_APPLICATION_NOT_APPROVED` | 409 Conflict |
| `ERR_SUPPLEMENT_NOT_REVIEWABLE` | 409 Conflict |
| `ERR_NO_ADEQUATE_BE_STUDY` | 422 Unprocessable Entity |
| `ERR_FACILITY_CLEARANCE_FAILED` | 422 Unprocessable Entity |
| `ERR_FOREIGN_FACILITY_WAIVER` | 422 Unprocessable Entity |
| `ERR_NCE_SUBMISSION_BARRED` | 422 Unprocessable Entity |
| `ERR_INSPECTION_OVERLAP` | 409 Conflict |
| `ERR_INDICATION_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_LABEL_CARVE_OUT_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_CARVE_OUT_OF_UNPROTECTED` | 422 Unprocessable Entity |
| `ERR_CERTIFICATION_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_CERTIFICATION` | 409 Conflict |
| `ERR_NOTICE_ALREADY_EXISTS` | 409 Conflict |
| `ERR_P4_NOTICE_REQUIRED` | 422 Unprocessable Entity |
| `ERR_INVALID_PATHWAY_FOR_CHANGE` | 422 Unprocessable Entity |
| `ERR_PATENT_NOT_LISTED_FOR_REFERENCE_PRODUCT` | 409 Conflict |
| `ERR_FACILITY_APPLICATION_MISMATCH` | 409 Conflict |
| `ERR_INDICATION_NOT_ON_REFERENCE_PRODUCT` | 422 Unprocessable Entity |



