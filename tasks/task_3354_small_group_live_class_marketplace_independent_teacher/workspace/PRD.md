# Outschool Marketplace API — Product Requirements Document

## 1. Introduction

This document defines the product requirements for the Outschool Marketplace API, a platform that lets independent teachers publish small-group live classes and lets parents reserve seats in those classes on behalf of their learners. The marketplace is deliberately trust-heavy: nobody teaches on it until a background screening has cleared, a recorded teaching sample has been reviewed by a human reviewer, and a platform operator has signed off on the applicant's public identity. Nothing is sold until a class listing has passed a content-policy review of its age band and subject matter, and nothing is scheduled until the listing is published and the owning teacher is in good standing.

The money flows in two directions and both are policy-bound. Parents pay a discounted seat price that is derived from their plan tier and from a small catalogue of promotional coupons; when they cancel, the size of the refund depends on how far ahead of the class start the cancellation arrives and on the format of the class they booked, with an explicit time-zone exception for a single named region. Teachers are paid on settlement periods that accrue from confirmed enrollment revenue, are reduced by a banded platform service fee, and are clawed back when a teacher-fault cancellation refunds a parent after the fact. Running alongside all of this is a risk system: parent reports carry weights that aggregate into a teacher risk score, and that score can suspend a teacher and cascade the suspension down through every listing, section and enrollment they own.

Because the marketplace is operated by a small trust-and-safety team, a large share of the platform's behaviour is automatic. An operations sweep advances the logical clock's consequences — cancelling sections that will not reach their enrollment minimum, completing sections that have started and settled, releasing seats that were never confirmed, escalating reports that have gone stale in a queue, expiring applications whose assigned reviewer never acted, and re-deriving tax-document standing from lifetime earnings. The requirements below specify both the operator-driven endpoints and these automatic behaviours with enough precision that a reader can implement them without seeing any other document.

## 2. Global Specifications & System-Wide Principles

This section states the rules that hold across the whole API: who may act, how every response is shaped, how lists are paged, how the logical clock works, how validation failures are ordered, and how money and time boundaries are computed.

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID`, which identifies the acting principal, and `X-User-Role`, which declares the capacity in which they are acting. Both are mandatory. A request that omits either header, or that declares an `X-User-Role` value outside the recognised set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose declared role is recognised but is not permitted for the targeted operation is rejected with `ERR_FORBIDDEN` (HTTP 403).

The marketplace recognises exactly five roles, spelled as follows: `TeacherApplicant`, `TeacherReviewer`, `Teacher`, `Parent`, and `PlatformAdmin`. Their identity semantics differ, and ownership checks depend on getting them right.

When `X-User-Role` is `Teacher`, `X-User-ID` is the `id` of the acting `Teacher` entity; ownership checks on any resource that references a `Teacher` compare the resource's `teacher_id` field to `X-User-ID`. This is the only entity-backed role in the system.

The other four roles act under opaque operator identifiers that are not themselves persisted entity rows. When `X-User-Role` is `TeacherApplicant`, `X-User-ID` is an opaque applicant operator identifier; it is recorded as `applicant_user_id` on the `TeacherApplication` the applicant creates, and it is compared against that recorded value by the segregation-of-duties check that stops an applicant from reviewing their own file. When `X-User-Role` is `TeacherReviewer`, `X-User-ID` is an opaque reviewer operator identifier; it is recorded as `reviewed_by_user_id` when the reviewer binds to an application, and it is compared against that recorded value to enforce reviewer continuity and to detect a reviewer deciding the same application twice. When `X-User-Role` is `Parent`, `X-User-ID` is an opaque parent operator identifier; it is compared against a learner's `parent_user_id` to establish who owns a learner account, and it is recorded as `reported_by_user_id` when that parent files a report. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is a fully opaque operator identifier that is not compared to any entity's `id` and is not persisted as an ownership key. None of these four identifiers is ever matched against a resource `id`.

Ownership is enforced separately from role membership. A request that names a resource belonging to somebody else is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403): an acting `Teacher` must own the listing, section or payout being mutated, and an acting `Parent` must own the learner whose enrollment is being mutated. `PlatformAdmin` is exempt from these ownership checks wherever the owning role is not `PlatformAdmin` itself.

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

List endpoints accept a `limit` and an `offset` query parameter. `limit` caps how many items are returned, defaults to 10, and must lie between 1 and 100 inclusive; a value outside that band is invalid. `offset` is the number of leading items to skip and defaults to 0. Unless a filter narrows the result, every list endpoint returns its resources sorted by `created_at` in ascending order, so that paging with a rising `offset` walks the collection from oldest to newest.

Every list response reports `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the standard envelope. `total_count` is the number of resources matching the request's filters before paging is applied, and `has_more` is true when further items remain beyond the returned page.

### 2.4. The Logical Clock and Period Accounting

Time in this marketplace is driven by a logical clock, not by the wall clock. When the server starts, its current instant is exactly `2026-09-01T00:00:00Z`, and it must remain at that value until it is deliberately moved; no request may consult real-world time, and no automatic sweep may fire merely because real time has passed. A `PlatformAdmin` moves the clock through an operator-only capability that accepts a target instant in the `to_iso8601` field and answers with the new `current_utc` value. Every temporal rule in this document — screening validity, reviewer deadlines, report queues, refund cutoffs, section start comparisons and the operations sweep — reads from this logical instant.

Alongside the instant, the platform tracks a `current_period_index`, defined as the number of complete 24-hour periods that have elapsed between `CURRENT_DEFAULT_UTC` and the current instant. Advancing the clock recomputes this index; it never decreases, because the clock is not permitted to move backwards across a completed period. Period indices are the unit in which three long-running deadlines are expressed: a background screening remains usable for 365 periods, an assigned reviewer has 7 periods to act before the application is automatically rejected, and a parent report may sit in its initial queue for 14 periods before it must be escalated. The index is also stamped onto resources as an audit marker — as `screening_completed_period_index` and `reviewer_bound_period_index` on applications, and as `refund_period_index` on payouts.

### 2.5. Common Resource Properties

Every top-level resource in this API — `TeacherApplication`, `Teacher`, `ClassListing`, `Section`, `Learner`, `Enrollment`, `TeacherPayout` and `ParentReport` — carries the same four system-managed properties. Each has an `id`, a server-minted UUID with no type prefix and no embedded meaning. Each has a `created_at` timestamp in ISO 8601 UTC with three fractional digits. Each has an `updated_at` timestamp in the same format, refreshed on every mutation of the resource. And each has an integer `version` that begins at its initial value and is incremented by one on every mutation, including mutations performed by an automatic cascade rather than by an explicit client request. There are no exceptions in this system: all eight entities carry `updated_at` and `version`.

A mutation is any write to a persisted field, whether it is a client-supplied input, a system-assigned value, or a computed value that has been re-derived. Recomputing a derived field such as a section's occupancy counts, a teacher's risk score, or a payout's net amount is a mutation, and it therefore refreshes `updated_at` and advances `version`. This matters beyond bookkeeping: the teacher's `version` is the concurrency token that guards payout creation (see §2.8), so a refund cascade that rewrites a payout's money fields will legitimately invalidate a client that read the teacher before the cascade ran.

### 2.6. Validation Order and Error Precedence

Requests are validated against a single ordered ladder. The rules below are numbered in evaluation order — the lowest number is evaluated first — and as soon as one rule fails, the request is rejected with that rule's error and no later rule is consulted. This ordering is part of the contract, because a request can violate several rules at once and the client is entitled to know which failure the server will report. A request that is missing a header and also names a resource that does not exist is answered with the authentication error, not the not-found error, because authentication is evaluated first.

The ladder, in order:

1. `X-User-Role` and `X-User-ID` are both present and `X-User-Role` names a declared role. Any failure here is `ERR_UNAUTHENTICATED` (HTTP 401). This applies to every endpoint.
2. `X-User-Role` is permitted for the targeted operation. Any failure here is `ERR_FORBIDDEN` (HTTP 403). This applies to every role-restricted endpoint.
3. Every resource identifier appearing in the request path resolves to an existing resource, validated from left to right along the path. Any failure here is `ERR_NOT_FOUND` (HTTP 404). This applies to every endpoint that carries a resource identifier.
4. The target resource is in a state from which the requested transition is declared. Any failure here is `ERR_INVALID_STATE` (HTTP 409). This applies to every state-transition endpoint.
5. Referenced sibling resources exist and are not archived: a `ClassListing` must exist for the `Section` being scheduled, a `Learner` must exist for the `Enrollment` being created, a `Section` must exist for the `Enrollment` being created, and the referenced `Teacher` and `ClassListing` must exist for a report being filed. Any failure here is `ERR_REFERENTIAL_INTEGRITY` (HTTP 409), and it applies to listing creation, section scheduling, seat reservation and report filing.
6. The learner's age at the section's start instant falls inside the listing's `min_age` to `max_age` band, inclusive, and the learner's `birth_date` is not in the future. Any failure here is `ERR_LEARNER_AGE_OUT_OF_RANGE` (HTTP 409), and it applies to seat reservation.
7. The owning teacher of the section being enrolled into is not `SUSPENDED` and not `TERMINATED`. Any failure here is `ERR_TEACHER_SUSPENDED` (HTTP 409), and it applies to seat reservation.
8. The section has a remaining seat: `seats_remaining` must be greater than zero, counting `CONFIRMED` and `RESERVED` enrollments against `capacity`. Any failure here is `ERR_SECTION_FULL` (HTTP 409), and it applies to seat reservation.
9. The section's `start_utc` is strictly in the future at the moment of enrollment. Any failure here is `ERR_SECTION_ALREADY_STARTED` (HTTP 409), and it applies to seat reservation.
10. The learner does not already hold an enrollment on this section in `RESERVED`, `PENDING_CONFIRMATION` or `CONFIRMED` status. Any failure here is `ERR_DUPLICATE_ENROLLMENT` (HTTP 409), and it applies to seat reservation.
11. A supplied `coupon_code` is a member of the declared coupon catalogue. Any failure here is `ERR_COUPON_NOT_FOUND` (HTTP 404), and it applies to seat reservation.
12. A supplied coupon has not already been redeemed by this learner on a `CONFIRMED` enrollment. Any failure here is `ERR_COUPON_ALREADY_REDEEMED` (HTTP 409), and it applies to seat reservation.
13. The learner's `confirmation_credit_cents` is at least the enrollment's `discounted_price_cents`. Any failure here is `ERR_CREDIT_INSUFFICIENT` (HTTP 409), and it applies to seat confirmation.
14. A section's `start_utc` is strictly before its `end_utc`, and both instants are strictly after `CURRENT_DEFAULT_UTC`. Any failure here is `ERR_INVALID_TIME_WINDOW` (HTTP 400), and it applies to section scheduling.
15. A section's `capacity` does not exceed the parent listing's `max_learners`, and `min_learners` does not exceed `capacity`. Any failure here is `ERR_CAPACITY_EXCEEDS_LISTING` (HTTP 400), and it applies to section scheduling.
16. Resource ownership holds: the acting `Teacher` owns the listing, section or payout being mutated, and the acting `Parent` owns the learner whose enrollment is being mutated. Any failure here is `ERR_NOT_RESOURCE_OWNER` (HTTP 403), and it applies to section cancellation, publishing or withdrawing a listing, enrollment confirmation, enrollment cancellation and payout request.
17. Segregation of duties holds: the acting reviewer's `X-User-ID` is not the application's `applicant_user_id`, and the acting reviewer is not already bound as the application's `reviewed_by_user_id` from an earlier round. Any failure here is `ERR_REVIEWER_CONFLICT` (HTTP 409), and it applies to application review and final approval.
18. The listing named for a new section has `content_review_state` equal to `POLICY_APPROVED`. Any failure here is `ERR_LISTING_NOT_APPROVED` (HTTP 409), and it applies to section scheduling.
19. A teaching sample's duration is at least 5 whole minutes. Any failure here is `ERR_SAMPLE_TOO_SHORT` (HTTP 400), and it applies to application creation, application submission and teaching-sample submission.
20. The applicant's most recent completed background screening is not older than 365 periods. Any failure here is `ERR_SCREENING_STALE` (HTTP 409), and it applies to teaching-sample submission and final approval.
21. The application has not exhausted its budget of 3 reviewer rejections. Any failure here is `ERR_REVISION_LIMIT_REACHED` (HTTP 409), and it applies to teaching-sample submission and final approval.
22. A payout's `period_end` is strictly after its `period_start`, and no other non-`VOIDED` payout of the same teacher overlaps the requested period. Any failure here is `ERR_PAYOUT_PERIOD_OVERLAP` (HTTP 409), and it applies to payout request.
23. A payout may not advance to `SENT` while its `tax_document_status` is anything other than `ON_FILE`. Any failure here is `ERR_TAX_DOC_MISSING` (HTTP 409), and it applies to the send action on a payout.
24. A `FAILED` payout must carry `approval_status` equal to `pending_approval`, and must have been approved, before it can be paid. Any failure here is `ERR_PAYOUT_NOT_APPROVED` (HTTP 409), and it applies to the approve and pay actions on a payout.
25. An identical `period_start` and `period_end` pair on an existing `REQUESTED` payout is an idempotent re-request, not a second payout. The duplicate is reported as `ERR_DUPLICATE_PAYOUT_PERIOD` (HTTP 409) only when the fingerprint matches but the caller supplied a different `expected_teacher_version`; the same-version path succeeds with HTTP 200 and the existing row. This applies to payout request.
26. A parent may file at most 2 reports against a given listing. Any failure here is `ERR_REPORT_WINDOW_CLOSED` (HTTP 409), and it applies to report filing.
27. A report that has sat in `OPEN` for more than 14 periods must be escalated before a disposition may be recorded against it. Any failure here is `ERR_REPORT_SLA_EXPIRED` (HTTP 409), and it applies to report disposition.
28. The listing's own age band is sane: `min_age` is at least 3, `max_age` is at most 18, and `min_age` does not exceed `max_age`. Any failure here is `ERR_INVALID_AGE_BAND` (HTTP 400), and it applies to listing creation and content-policy review.
29. A supplied `expected_teacher_version` equals the teacher's current `version`. Any failure here is `ERR_STALE_VERSION` (HTTP 412), and it applies to payout request.
30. Every required input field for the endpoint is present and non-blank. Any failure here is `ERR_MISSING_REQUIRED_FIELD` (HTTP 400), and it applies to every endpoint that declares required input.
31. Every enum-typed input field carries a member of its declared enumeration. Any failure here is `ERR_INVALID_ENUM_VALUE` (HTTP 400), and it applies to every endpoint that accepts an enum input.
32. The application's background screening outcome is not `FAIL`. Any failure here is `ERR_SCREENING_FAILED` (HTTP 409), and it applies to teaching-sample submission.
33. Final approval requires the application to be in `SAMPLE_APPROVED`. Any failure here is `ERR_APPLICATION_NOT_APPROVED` (HTTP 409), and it applies to final approval.
34. The owning teacher is `ACTIVE` for section opening, publishing and section cancellation. Any failure here is `ERR_TEACHER_NOT_ACTIVE` (HTTP 409).
35. The parent listing is in `PUBLISHED` lifecycle state for a section to be opened. Any failure here is `ERR_LISTING_NOT_PUBLISHED` (HTTP 409), and it applies to section opening.
36. The section is in `OPEN_FOR_ENROLLMENT` for its minimum to be declared met. Any failure here is `ERR_SECTION_NOT_OPEN` (HTTP 409), and it applies to declaring the minimum met.
37. The section's confirmed enrollment has reached `min_learners` before the minimum can be declared met. Any failure here is `ERR_MIN_ENROLLMENT_NOT_MET` (HTTP 409), and it applies to declaring the minimum met.
38. A payout already in `PAID` status may not be transitioned again. Any failure here is `ERR_PAYOUT_ALREADY_PAID` (HTTP 409), and it applies to every payout transition.
39. The payout would not push the teacher's approved-and-sent total past the approval cap. Any failure here is `ERR_PAYOUT_CAP_EXCEEDED` (HTTP 409), and it applies to the send action on a payout.

Two consequences of this ladder are worth stating outright, because they are easy to get backwards. First, authentication and permission failures always outrank everything else, and a missing path resource always outranks a state or business failure on that resource. Second, the payload-shape rules (missing required fields and invalid enum values) sit at positions 30 and 31, below every domain rule; a request that both omits a required field and targets a resource in the wrong state is reported with the state error.

### 2.7. Nested Resource Resolution

Several operations address a resource through its parent, for example a section that lives beneath a listing. When a path carries more than one resource identifier, the server resolves them from left to right and stops at the first one that does not exist; the client receives `ERR_NOT_FOUND` (HTTP 404) for that identifier, and the server does not attempt to resolve anything further to its right. A request naming a section under a listing that does not exist is therefore answered as a missing listing, never as a missing section. The same left-to-right rule governs the deeper nesting used by section operations, where both the listing and the section must resolve before any business rule is evaluated.

### 2.8. Optimistic Concurrency on Payout Requests

Payout creation is the one write in this API that is guarded by optimistic concurrency control. A request to create a payout for a teacher must carry `expected_teacher_version` as a non-optional field holding the teacher's `version` as the client last observed it. If the teacher's current `version` has advanced past that value — because another writer recorded a payout against the same unpaid-earnings balance, or because a teacher-fault refund cascade rewrote the teacher's fee-reversed, liability and unpaid-earnings totals — the create is rejected with `ERR_STALE_VERSION` (HTTP 412). This prevents a client from settling a period against a balance it has not actually observed. No other endpoint in this API accepts a version field, and no other entity's writes are version-guarded.

### 2.9. Monetary Precision and Rounding

Every monetary quantity in this API is an integer number of cents. List prices, discounts, refunds, gross earnings, fees, net payouts, liability amounts, caps and thresholds are all integers, and they are returned as integers. Percentage rates — plan discounts, coupon percentages, fee rates, format adjustments, the partial-refund rate and the volume discount — are IEEE-754 doubles used only as intermediate multipliers.

Rounding is always floor truncation toward the lower integer. There is no round-half-up anywhere in this system, and no step is allowed to re-round a value that an earlier step already produced. Where a calculation is defined as a sequence of steps, each step floors its own result independently; where a calculation aggregates per-section amounts, each section's amount is floored before the amounts are summed. Two such orders are load-bearing and are restated where the relevant calculation appears: the discount stack on a seat price, and the per-section flooring of the platform fee.

### 2.10. Boundary and Comparison Conventions

Settlement periods are half-open intervals. A payout's period covers instants that are at or after `period_start` and strictly before `period_end`; a section starting exactly at `period_start` falls inside the period, and a section starting exactly at `period_end` falls outside it. Refund timing is measured in whole hours remaining before a section's start, truncated down to an integer, so 47 hours and 30 minutes of remaining time counts as 47 hours. Cancellation cutoffs and section start comparisons are evaluated with the inclusive forms stated with each rule: a sweep fires when the current instant is at or after the relevant cutoff, while a teacher-driven cancellation requires the current instant to be strictly before the section's start.

Two computed booleans expose boundary behaviour directly on the section resource. `scheduled_start_confirmed` is true when the current instant is at or before the section's `start_utc`. `settled` is true when no enrollment of the section is in `RESERVED` status, meaning every seat has either been confirmed or already resolved. The tax-document thresholds are inclusive at their upper edges: earnings exactly equal to the reporting threshold leave the teacher on file, and earnings exactly equal to the ceiling leave the teacher in the update-required band rather than expiring them.

## 3. Business Logic & Workflows

### 3.1. Teacher Onboarding: Application, Screening and Sample Review

A prospective teacher begins as a `TeacherApplicant` who creates a `TeacherApplication`. The creation payload carries `applicant_user_id`, `applicant_email` and `display_name`, and may already carry `teaching_sample_url` and `teaching_sample_minutes` if the applicant has material ready. The new application is born in `DRAFT` with `screening_outcome`, `decision` and `decision_reason_code` left null, `revision_count` at zero, and both `reviewed_by_user_id` and `reviewer_bound_period_index` unbound.

Submission is the act that turns an application into a screened candidate. It is permitted only while the application is `DRAFT`, and only when `applicant_user_id`, `applicant_email` and `display_name` are all non-empty, `teaching_sample_url` is non-empty, and `teaching_sample_minutes` is at least 5 whole minutes — a shorter sample is refused with `ERR_SAMPLE_TOO_SHORT` (400). On a successful submission the platform records a completed background screening against the applicant and stamps `screening_completed_period_index` with the current period index. The screening outcome is a pure function of the applicant's email address, so it is fully reproducible and never depends on the wall clock or on any external service: `ada@example.com`, `grace@example.com` and `linus@example.com` clear the check, `alan@example.com` and `edsger@example.com` fail it, and any other address clears it by default. Only the values `PASS` and `FAIL` are ever stored in `screening_outcome`. The submission also resets `revision_count` to zero, clears the reviewer binding, and clears `decision`; then, within the same request, the application passes through `SCREENING_PENDING` and lands automatically in either `SCREENING_PASSED` or `SCREENING_FAILED`.

A screening failure is resolved by a reviewer, not by the applicant. A `TeacherReviewer` records `stage` as `SCREENING` with `verdict` as `FAIL` against an application sitting in `SCREENING_FAILED`; the application moves to `REJECTED`, `decision` becomes `REJECT`, `decision_reason_code` becomes `POLICY_VIOLATION`, and `revision_count` is incremented. An applicant whose file has been rejected can still see whether it is worth appealing: `eligible_for_appeal` is true exactly when the status is `REJECTED` and `revision_count` is still below the ceiling of 3.

Candidates who clear screening move to the sample stage. Submitting a teaching sample advances an application from `SCREENING_PASSED` to `SAMPLE_PENDING`; the request must carry a non-empty `teaching_sample_url`, a `teaching_sample_minutes` value of at least 5, and the screening must still be fresh. Freshness is tracked by `screening_is_stale`, which is true when the applicant's most recent completed screening is older than 365 periods. A stale screening blocks both sample submission and final approval with `ERR_SCREENING_STALE` (409), and an application that fails screening outright can never reach the sample queue at all — attempting it yields `ERR_SCREENING_FAILED` (409).

Sample review binds a reviewer to the file. When a `TeacherReviewer` records `stage` as `SAMPLE` with `verdict` as `PASS`, the application moves to `SAMPLE_APPROVED`, the acting reviewer's operator identifier is written to `reviewed_by_user_id`, `reviewer_bound_period_index` is stamped with the current period index, and `decision` becomes `APPROVE`. The same stage with `verdict` as `FAIL` moves the application to `SAMPLE_REJECTED` instead: the reviewer is bound the same way, `decision` becomes `REJECT`, `decision_reason_code` becomes `SAMPLE_QUALITY`, and `revision_count` is incremented. The binding is what makes reviewer inaction measurable. If a bound reviewer lets 7 periods pass without acting — that is, the current period index reaches the period at which the reviewer bound plus 7 — the operations sweep rejects the application automatically, setting `decision` to `REJECT`, `decision_reason_code` to `INCOMPLETE_MATERIALS`, and incrementing `revision_count`; the reviewer binding is deliberately left in place so the missed deadline remains auditable.

Rejection is not always the end of the road. A rejected sample may be resubmitted as a revision, which returns the application from `SAMPLE_REJECTED` to `SAMPLE_PENDING`, releases the reviewer binding and clears `decision`; this loop is available only while `revision_count` is below 3, and the resubmitted sample must again be at least 5 minutes long. Once the revision budget is exhausted, the application is forced to its terminal state: whenever a reviewer rejection would take `revision_count` to 3, or whenever a `FAIL` verdict is recorded at any non-terminal stage where `revision_count` plus one is already 3, the application advances directly to `REJECTED` rather than to a revisable state. Attempting to submit a sample or to approve an application whose `revision_count` has already reached 3 is refused with `ERR_REVISION_LIMIT_REACHED` (409).

Final approval is the step that mints a teacher account. It requires the application to be in `SAMPLE_APPROVED` (otherwise `ERR_APPLICATION_NOT_APPROVED`, 409), requires the acting reviewer to be the same operator who is bound as `reviewed_by_user_id`, requires the revision budget to be unexhausted, and requires the screening to be fresh. On success the application reaches `APPROVED` and a `Teacher` row is created with `application_id` pointing back at the application, `display_name` copied from it, status `PENDING_SETUP`, and `screening_validity_period_index` set to the application's `screening_completed_period_index` plus 365 — the period through which a re-screen is not yet due. The new teacher starts with `open_report_count`, `open_report_risk_score`, `upheld_report_risk_score`, `actionable_risk_score`, `peak_actionable_risk_score`, `lifetime_net_earnings_cents`, `lifetime_fee_reversed_cents`, `lifetime_teacher_liability_cents` and `unpaid_earnings_cents` all at zero, and `payout_tax_document_status` is derived immediately, which at zero lifetime earnings means `ON_FILE`.

Reviewers are subject to a separation-of-duties rule. A reviewer may not decide an application that they themselves filed — the acting reviewer's operator identifier may not equal the application's `applicant_user_id` — and a reviewer who is already bound as `reviewed_by_user_id` from an earlier round may not decide the same application a second time. Both situations are refused with `ERR_REVIEWER_CONFLICT` (409), and both apply to the review and final-approval operations.

### 3.2. Teacher Lifecycle and Suspension Cascades

An approved teacher does not start selling immediately. A `PlatformAdmin` activates the account, moving it from `PENDING_SETUP` to `ACTIVE`; the activation is gated on `payout_tax_document_status` being `ON_FILE`, so a teacher with an outstanding tax-document problem cannot be brought online. Activation clears `suspension_reason` and `suspension_trigger`, leaving both null on a healthy account.

Suspension is the marketplace's blunt instrument, and it cascades. A manual suspension, performed by a `PlatformAdmin` against an `ACTIVE` teacher with a supplied `reason`, moves the teacher to `SUSPENDED`, writes that reason to `suspension_reason`, and sets `suspension_trigger` to `MANUAL`. Three hops then run in order. First, every `ClassListing` owned by the teacher whose `lifecycle_state` is `PUBLISHED` is moved to `SUSPENDED`. Second, every `Section` of those listings that is in `SCHEDULED` or `OPEN_FOR_ENROLLMENT` is moved to `CANCELLED` with its `outcome` set to `CANCELLED_BY_TEACHER` and its `cancelled_by` set to `platform`. Third, every `Enrollment` of those sections that is in `RESERVED` or `CONFIRMED` is written directly to `CANCELLED_BY_TEACHER` with `refund_category` `FULL` at the enrollment's `discounted_price_cents`; because the cascade resolves these enrollments itself, they do not take the generic release path that a section cancellation would otherwise trigger.

A teacher can also be suspended by the platform's own risk machinery, with no operator in the loop. When a report disposition raises the teacher's `actionable_risk_score` to 40 or more while the teacher is `ACTIVE`, the teacher is suspended with `suspension_reason` reading `automatic policy suspension` and `suspension_trigger` set to `POLICY`. The high-water mark `peak_actionable_risk_score` is raised to the current `actionable_risk_score` before the cascade runs, and the same listing, section and enrollment cascade described above follows. The distinction between the two suspension triggers matters at reinstatement time, because the platform will not put a teacher back online while their peak risk still sits at or above the threshold.

Reinstatement returns a `SUSPENDED` teacher to `ACTIVE` and requires two conditions beyond the state itself: the tax-document status must be `ON_FILE`, and `peak_actionable_risk_score` must be strictly below 40. Reinstatement clears `suspension_reason` and `suspension_trigger`. Repeated suspensions overwrite the reason text, so `suspension_reason` is last-write-wins. Termination is the terminal state: a `PlatformAdmin` may terminate a teacher from `PENDING_SETUP`, `ACTIVE` or `SUSPENDED`, but only when no listing owned by that teacher still has live sections — that is, when no listing's `section_count` is greater than zero. Termination archives every listing the teacher owns.

One further suspension path exists and is driven entirely by money. The teacher's `payout_tax_document_status` is a pure function of `lifetime_net_earnings_cents`: a teacher at or below 20000 cents of lifetime net earnings is `ON_FILE`, a teacher above 20000 but at or below 200000 cents is `REQUIRED_UPDATE`, and a teacher above 200000 cents is `EXPIRED`. The derivation is re-run after every write to lifetime earnings, including the downward re-sum performed by a refund clawback, so a refund that drops a teacher back to or below 20000 cents returns them to `ON_FILE`. An out-of-date tax document never suspends a teacher: teacher status is changed only by the manual suspend endpoint and by the report-risk cascade. Instead, the tax-document status gates settlement — a payout may not advance to `SENT` while its `tax_document_status` is anything other than `ON_FILE`, and the attempt is refused with `ERR_TAX_DOC_MISSING` (409). The derivation is also re-evaluated by the operations sweep for every teacher whose lifetime earnings have changed.

Independently of suspension, a teacher's screening eventually expires. `re_screen_required` is true once the current period index has moved past `screening_validity_period_index`, which is the period through which the original screening remains acceptable.

### 3.3. Class Listings: Content Policy Review and Publishing

A `ClassListing` is the catalogue entry a teacher sells from. Its creation payload carries `teacher_id`, `title`, `format`, `min_age`, `max_age`, `max_learners` and `list_price_cents`. The `format` is one of `ONE_TIME`, `MULTI_DAY` or `ONGOING`, and it is immutable after creation because so much of the money logic keys off it. The age band must be sane: `min_age` is at least 3, `max_age` is at most 18, and `min_age` does not exceed `max_age`; a violation is refused with `ERR_INVALID_AGE_BAND` (400), and the same check is re-applied when the listing is policy-reviewed. `max_learners` is the listing-level ceiling, between 1 and 18, and every section scheduled under the listing must fit inside it. `list_price_cents` must be a positive integer. A new listing is born with `content_review_state` of `PENDING_REVIEW` and `lifecycle_state` of `DRAFT`, and it receives a `listing_sequence` that increases monotonically within the owning teacher; that sequence doubles as the escalation tie-break when listings are compared.

Content review is a platform-only decision on the listing's age band and subject matter, taken with a `decision` and an optional `reason_code`. Approving moves the listing from `PENDING_REVIEW` to `POLICY_APPROVED` and requires the age band to be internally consistent. Rejecting moves it to `POLICY_REJECTED`, writes the supplied `reason_code` into `policy_rejection_reason_code` — whose declared values are `AGE_MISMATCH`, `CONTENT_POLICY` and `PRICING_POLICY` — and immediately archives the listing, because a policy-rejected listing is terminally non-creatable. `content_review_state` is the sole gate on scheduling: a section cannot be created under a listing that is not `POLICY_APPROVED`, and the attempt is refused with `ERR_LISTING_NOT_APPROVED` (409).

Publishing is the teacher's act. It moves a listing from `DRAFT` to `PUBLISHED`, and it requires three things at once: the listing must already be `POLICY_APPROVED`, the owning teacher must be `ACTIVE` (otherwise `ERR_TEACHER_NOT_ACTIVE`, 409), and the acting principal must either be the owning teacher or a `PlatformAdmin`. A listing that has not been published cannot have its sections opened.

The listing mirrors its teacher's fate. When the owning teacher becomes `SUSPENDED` or `TERMINATED`, every `PUBLISHED` listing moves to `SUSPENDED`, and each of its sections that is still `SCHEDULED` or `OPEN_FOR_ENROLLMENT` is cancelled with `outcome` `CANCELLED_BY_TEACHER` while its `RESERVED` and `CONFIRMED` enrollments are cancelled with `refund_category` `FULL`. When the listing itself is policy-rejected, or when its owner is terminated, the listing moves to `ARCHIVED` from any of `DRAFT`, `PUBLISHED` or `SUSPENDED`, and any section still in `SCHEDULED` or `OPEN_FOR_ENROLLMENT` is cancelled with `outcome` `CANCELLED_BY_TEACHER`. The listing's `section_count` reflects only live work: it counts sections whose status is neither `CANCELLED` nor `COMPLETED`, and a teacher cannot be terminated while any of their listings still carries a non-zero `section_count`.

### 3.4. Section Scheduling, Enrollment Windows and Automatic Cancellation

A `Section` is one scheduled sitting of a listing. Scheduling it requires a `timezone` given as an IANA name, a `start_utc` and an `end_utc` in ISO 8601 UTC, a `min_learners` floor, a `capacity`, and an optional `expected_learners` projection. The parent listing must exist and must not be archived (otherwise `ERR_REFERENTIAL_INTEGRITY`, 409) and must be `POLICY_APPROVED` (otherwise `ERR_LISTING_NOT_APPROVED`, 409). The window must be coherent: `start_utc` strictly before `end_utc`, and both instants strictly after `CURRENT_DEFAULT_UTC`; a violation is `ERR_INVALID_TIME_WINDOW` (400). Seating must fit the parent: `capacity` is between 1 and 18 and may not exceed the listing's `max_learners`, and `min_learners` may not exceed `capacity`; a violation is `ERR_CAPACITY_EXCEEDS_LISTING` (400). A section's `status` takes exactly five values over its life — `SCHEDULED`, `OPEN_FOR_ENROLLMENT`, `MIN_ENROLLMENT_MET`, `CANCELLED` and `COMPLETED`. A new section is born `SCHEDULED` with a null `outcome`, and its `cancellation_cutoff_utc` is fixed at `start_utc` minus 24 hours, the instant at which the automatic-cancellation sweep will judge it.

Opening a section for business requires three conditions to hold together: the section is `SCHEDULED`, its owning teacher is `ACTIVE` (otherwise `ERR_TEACHER_NOT_ACTIVE`, 409), and its listing is both `PUBLISHED` (otherwise `ERR_LISTING_NOT_PUBLISHED`, 409) and `POLICY_APPROVED`. A successful opening moves the section to `OPEN_FOR_ENROLLMENT`.

Occupancy is recomputed on every status change of any enrollment carrying that section's `section_id`. `enrolled_count` counts enrollments in `CONFIRMED` status, `reserved_count` counts those in `RESERVED` status, and `seats_remaining` is `capacity` less both counts, never allowed to go negative. `enrollment_min_met` is true when `enrolled_count` has reached `min_learners`. Enrollments in `PENDING_CONFIRMATION`, `RELEASED` or `CANCELLED_BY_TEACHER` hold no seat and are excluded from both counts; `PENDING_CONFIRMATION` is a legacy status that this API never produces but must still exclude. The invariant `seats_remaining` greater than or equal to zero must hold after every write.

Declaring the enrollment minimum met is a teacher's confirmation that the class will run. It moves a section from `OPEN_FOR_ENROLLMENT` to `MIN_ENROLLMENT_MET` and requires `enrollment_min_met` to be true at that moment; a section that is not open is refused with `ERR_SECTION_NOT_OPEN` (409), and an open section whose confirmed enrollment is still below the floor is refused with `ERR_MIN_ENROLLMENT_NOT_MET` (409). Declaring the minimum met performs no credit movement of any kind — confirmation credit is drawn only when an individual enrollment is confirmed, which is covered in §3.6.

Cancellation by the teacher is available from `SCHEDULED`, `OPEN_FOR_ENROLLMENT` or `MIN_ENROLLMENT_MET`, and only while the current instant is strictly before `start_utc`; the owning teacher must be `ACTIVE` unless a `PlatformAdmin` is acting. The section's `outcome` is written as `CANCELLED_BY_TEACHER`, and every `RESERVED` or `CONFIRMED` enrollment of that section moves to `CANCELLED_BY_TEACHER` with `cancelled_by` set to `teacher`, a `refund_category` of `FULL`, `refund_cents` equal to the enrollment's `discounted_price_cents`, `credit_applied_cents` equal to the smaller of that refund and the learner's remaining `confirmation_credit_cents`, and `cash_refund_cents` equal to the difference. Because the cancellation refunds money the teacher had already accrued, it also triggers the refund clawback cascade described in §3.8.

Three automatic behaviours run against sections, and none of them needs an operator.

The automatic-cancellation sweep fires once the current instant is at or after a section's `cancellation_cutoff_utc` while the section is still `SCHEDULED` or `OPEN_FOR_ENROLLMENT`. The test is a projection against the floor: the sweep takes `expected_learners`, or falls back to `min_learners` when the scheduling request supplied no projection, and cancels the section only when that value is strictly below `min_learners`. A section that never carried a projection therefore never auto-cancels, because its fallback equals the floor. A cancelled section records `outcome` `AUTO_CANCELLED_MIN_ENROLLMENT`, and every `RESERVED` or `CONFIRMED` enrollment of it moves to `RELEASED` with `cancelled_by` set to `platform` and a `FULL` refund split between confirmation credit and cash exactly as above.

The completion sweep closes sections that have run. When a section is `MIN_ENROLLMENT_MET`, the current instant is at or after `start_utc`, and the section is `settled` — meaning no enrollment of it is still `RESERVED` — the section moves to `COMPLETED`. If its `outcome` is still null at that point, it is written as `HELD`. An `outcome`, once non-null, is sealed: no later behaviour rewrites it.

The reservation sweep releases seats that were never confirmed. A `RESERVED` enrollment whose section has reached `start_utc` while the section is still `OPEN_FOR_ENROLLMENT` moves to `RELEASED` with `refund_category` `NONE`, `refund_cents` zero, `credit_applied_cents` zero, `cash_refund_cents` zero and `cancelled_by` set to `platform`. Nothing was ever charged for an unconfirmed reservation, so nothing is returned.

### 3.5. Learners, Subscriptions and Seat Reservation

Learner accounts belong to parents. Creating one requires a `display_name`, a `birth_date` and the `parent_user_id` of the owning parent operator; a birth date that lies after `CURRENT_DEFAULT_UTC` is not accepted. A fresh learner starts with `subscription_tier` `NONE`, `subscription_discount_pct` of 0.00, `confirmation_credit_cents` of zero, `abuse_strike_count` of zero, and `enrollment_sequence` at zero.

Subscriptions are the first half of the marketplace's discount programme. Writing a learner's `subscription_tier` accepts one of `NONE`, `PLUS` or `FAMILY`, recomputes `subscription_discount_pct` to 0.00, 0.10 or 0.20 respectively, and refills `confirmation_credit_cents` to the active plan's included allowance: zero cents on `NONE`, 5000 cents on `PLUS`, and 12000 cents on `FAMILY`. The refill happens on every subscription write, so switching plans resets the allowance to the new plan's figure rather than adding to whatever remained.

Reserving a seat is the act that prices a class. The request names a `learner_id` and may carry a `coupon_code` from the declared catalogue. The learner must belong to the acting parent operator, the section's owning teacher must not be `SUSPENDED` or `TERMINATED` (otherwise `ERR_TEACHER_SUSPENDED`, 409), the learner's age at the section's start instant must fall inside the listing's `min_age` to `max_age` band inclusive and the birth date must not be in the future (otherwise `ERR_LEARNER_AGE_OUT_OF_RANGE`, 409), the section must have at least one seat left once `CONFIRMED` and `RESERVED` enrollments are counted (otherwise `ERR_SECTION_FULL`, 409), the section's `start_utc` must be strictly in the future (otherwise `ERR_SECTION_ALREADY_STARTED`, 409), and the learner must not already hold a `RESERVED`, `PENDING_CONFIRMATION` or `CONFIRMED` enrollment on that section (otherwise `ERR_DUPLICATE_ENROLLMENT`, 409). The reservation is created in `RESERVED` status and the learner's `enrollment_sequence` is incremented by one; that monotonic per-learner counter is what the marketplace uses as the coupon allocation tie-break when two enrollments compete for the same coupon allowance.

The catalogue contains exactly four coupons, each typed either `PERCENT` or `AMOUNT_CENTS`. `WELCOME5` is a `PERCENT` coupon worth 0.05. `SIBLING10` is a `PERCENT` coupon worth 0.10. `SPRING15` is a `PERCENT` coupon worth 0.15. `FLAT250` is an `AMOUNT_CENTS` coupon worth 250 cents. A code outside this catalogue is refused with `ERR_COUPON_NOT_FOUND` (404). A coupon may be used once per learner in earnest: if the learner already holds a `CONFIRMED` enrollment that redeemed the same code, the new reservation is refused with `ERR_COUPON_ALREADY_REDEEMED` (409).

Discounts stack in a pinned order, and the order changes the answer. Step one computes the subscription discount as the list price multiplied by the learner's `subscription_discount_pct`, floored to a whole cent, and records it in `subscription_discount_cents`. Step two subtracts that from the list price to obtain the price that remains. Step three computes the coupon discount on that remaining price — for a percent coupon, the remaining price multiplied by the coupon's value, floored to a whole cent; for an amount coupon, the coupon's face value in cents — and records it in `coupon_discount_cents`. Step four sets `discounted_price_cents` to the list price less the subscription discount less the coupon discount, floored at zero so a stack can never produce a negative price. Every step floors independently and no step re-rounds a value an earlier step produced. The subscription discount is always computed first, on the undiscounted list price, and the coupon always applies to what remains after it. The rejected alternative — applying the coupon to the list price first and the plan discount to the remainder — is never used by the server; it is documented only because it diverges on identical inputs. For a 3333-cent listing with a 10 percent plan and a 15 percent coupon, the applied order yields 2550 cents while the rejected order would yield 2551.

### 3.6. Confirmation, Cancellation and the Refund Tier Engine

A reservation becomes a firm booking when it is confirmed. Confirmation moves an enrollment from `RESERVED` to `CONFIRMED` and requires four things: the section has reached `MIN_ENROLLMENT_MET`, the acting parent operator owns the learner, the learner's `confirmation_credit_cents` is at least the enrollment's `discounted_price_cents` (otherwise `ERR_CREDIT_INSUFFICIENT`, 409), and the enrollment itself is still `RESERVED` (a transition attempted from any other state is `ERR_INVALID_STATE`, 409). The confirmation draws the price down from the learner's allowance, reducing `confirmation_credit_cents` by exactly the enrollment's `discounted_price_cents`.

Cancellation is where the refund tier is decided, and the tier is driven by timing first. The request is available to the owning parent operator or a `PlatformAdmin`, from `RESERVED` at any time, and from `CONFIRMED` only while the current instant is strictly before the section's `start_utc`. Two facts are established before any money is computed. The first is `learner_fault`, which is true when the current instant is strictly before the section's `cancellation_cutoff_utc` — that is, when the parent is cancelling with more than 24 hours to spare. The second is the number of whole hours remaining before the section starts, obtained by subtracting the current instant from `start_utc` and truncating down to a whole number of hours.

The time-zone exception is evaluated before the general tier, and it is the first thing that can change the outcome. If the section's `timezone` is `America/Anchorage` and the tier that the general rule would produce is `PARTIAL_HALF`, the tier is downgraded to `NONE`. The exception applies only to that one zone and only to that one tier; a full refund stays full, and a cancellation that would already have produced nothing stays at nothing.

The general rule selects the tier from the hours remaining and the listing's `format`. A full refund is granted when the whole hours remaining are at least the full-refund cutoff for that format: 168 hours for `ONE_TIME`, 336 hours for `MULTI_DAY`, and 336 hours for `ONGOING`. Failing that, a half refund is granted when the cancellation is a learner-fault cancellation and the whole hours remaining are at least the half-refund cutoff for that format: 24 hours for `ONE_TIME`, 72 hours for `MULTI_DAY`, and 168 hours for `ONGOING`. Otherwise the tier is `NONE`. The rejected alternative reading — selecting the tier from the format alone, granting `FULL` to every `ONE_TIME` cancellation, `PARTIAL_HALF` to every `MULTI_DAY` cancellation and `NONE` to every `ONGOING` cancellation regardless of how far ahead the cancellation arrives — is never applied by the server; it is recorded here only because it disagrees with the timing rule on the same request.

The tier then determines the money. `refund_category` is written as the selected tier. `refund_cents` is zero for `NONE`, the enrollment's `discounted_price_cents` multiplied by the partial-refund rate of 0.50 and floored to a whole cent for `PARTIAL_HALF`, and the full `discounted_price_cents` for `FULL`. The refund is then split between the learner's stored allowance and real money: `credit_applied_cents` is the smaller of `refund_cents` and the learner's remaining `confirmation_credit_cents`, and `cash_refund_cents` is the difference. The enrollment's `cancelled_by` is written as `parent`, and a learner-fault cancellation increments the learner's `abuse_strike_count` by one.

A cancellation that is not the learner's fault is charged back to the teacher, and it can also collapse the section. When `learner_fault` is false, the refund clawback cascade described in §3.8 runs for the affected section. Separately, and after the refund has been written, the seat-loss branch is evaluated: if the section is in `OPEN_FOR_ENROLLMENT` or `MIN_ENROLLMENT_MET`, the current instant is still strictly before `start_utc`, and the cancellation has dropped `enrolled_count` below `min_learners`, the section is cancelled with `outcome` `AUTO_CANCELLED_SEAT_LOSS`, every other `RESERVED` or `CONFIRMED` enrollment of that section moves to `CANCELLED_BY_TEACHER` with `cancelled_by` set to `platform` and a `FULL` refund, and the clawback cascade runs for the section. If the seat-loss branch does not fire and the section was `MIN_ENROLLMENT_MET` but the cancellation drops confirmed enrollment below the floor, the section simply reopens, returning to `OPEN_FOR_ENROLLMENT`.

One release path remains, and it is not parent-initiated. When an enrollment is `CONFIRMED` and its section has entered `CANCELLED`, the enrollment moves to `RELEASED` with `refund_category` `FULL`, `refund_cents` equal to its `discounted_price_cents`, `credit_applied_cents` equal to the smaller of that refund and the learner's remaining allowance, `cash_refund_cents` equal to the difference, and `cancelled_by` set to `platform`. Enrollments that a suspension cascade has already resolved directly are not touched by this path.

### 3.7. Parent Reports and Teacher Risk Scoring

Parents police the marketplace by filing reports. A report names a `teacher_id`, a `class_listing_id`, the `reported_by_user_id` of the filing parent operator, a `severity` of `LOW`, `MEDIUM` or `HIGH`, and a `category` of `CONTENT_POLICY`, `SAFETY`, `CONDUCT`, `TECHNICAL` or `OTHER`. It is born in `OPEN` with a null `disposition`, and its `severity_weight` is computed as the category's weight plus the severity's points. The category weights are 25 for `CONTENT_POLICY`, 40 for `SAFETY`, 15 for `CONDUCT`, 5 for `TECHNICAL` and 2 for `OTHER`; the severity points are 0 for `LOW`, 10 for `MEDIUM` and 25 for `HIGH`. A `SAFETY` report at `HIGH` severity therefore weighs 65, while an `OTHER` report at `LOW` severity weighs 2. Two booleans make the report's position legible: `high_severity` is true exactly when the severity is `HIGH`, and `is_terminal` is true exactly when the status is `RESOLVED` or `CLOSED`.

Filing is capped so that a single parent cannot flood a listing. A parent operator may file at most 2 reports against any one listing, and a filing beyond that cap is refused with `ERR_REPORT_WINDOW_CLOSED` (409). The same error covers an attempt to report on a section that has not yet started. On a successful filing the teacher's `open_report_risk_score` and `open_report_count` are recomputed; `open_report_count` counts the teacher's reports whose status is neither `CLOSED` nor `RESOLVED`, so reports in `OPEN` and in `UNDER_REVIEW` both count.

Disposition is a platform-only decision taken with an `action` and an optional `reason`. The action is one of `START_REVIEW`, `DISMISS`, `UPHOLD_WARNING` or `UPHOLD_MORE_SEVERE`. `START_REVIEW` moves a report from `OPEN` to `UNDER_REVIEW`, and the same action may also be used to reopen a `RESOLVED` report back into `UNDER_REVIEW`, in which case the existing `disposition` is retained until a new one is written. `DISMISS` moves a report from `UNDER_REVIEW` to `RESOLVED` and writes `DISMISSED` as the disposition, and it deliberately recalculates nothing — a dismissed report writes no risk-bearing state at all. The two uphold actions move a report out of review and write a disposition of either `WARNING` or `MORE_SEVERE`: `UPHOLD_WARNING` lands the report in `RESOLVED` with a disposition of `WARNING`, and `UPHOLD_MORE_SEVERE` lands it in `CLOSED` with a disposition of `MORE_SEVERE`. Both upheld dispositions run the same three-hop risk cascade.

The risk cascade is what turns a report into a consequence. The first hop recomputes the teacher's `upheld_report_risk_score` as the sum of `severity_weight` over every report whose disposition is `WARNING` or `MORE_SEVERE`, regardless of what status those reports now hold. The second hop recomputes `actionable_risk_score` as the larger of `open_report_risk_score` and `upheld_report_risk_score`, and raises `peak_actionable_risk_score` to that value if it is larger than the current high-water mark. The third hop suspends the teacher when `actionable_risk_score` has reached 40 and the teacher is `ACTIVE`, using the policy suspension path described in §3.2 with its listing, section and enrollment cascade.

Both scoring readings are maintained side by side, and taking their maximum is what makes the score durable. `open_report_risk_score` counts a report only while its status is `OPEN`, so resolving the report drops that contribution — this is the "is the problem still live" reading. `upheld_report_risk_score` counts a report forever once its disposition is `WARNING` or `MORE_SEVERE`, whatever its status — this is the "was the problem ever real" reading. Because `actionable_risk_score` is their maximum, resolving a report away cannot un-suspend a teacher whose complaint was upheld, and only a peak that has come back below 40 allows reinstatement.

Reports also have a queue deadline. A report left in `OPEN` for more than 14 periods must be escalated before any disposition can be recorded against it; an attempt to dispose of it while it is still sitting stale in the queue is refused with `ERR_REPORT_SLA_EXPIRED` (409). The escalation itself is performed by the operations sweep described in §3.9.

### 3.8. Teacher Payouts: Accrual, Fees and the Refund Clawback

A `Teacher` claims what the marketplace owes by requesting a payout for a settlement period. The request carries `period_start`, `period_end` and `expected_teacher_version`. The version field is mandatory and is checked against the teacher's current `version`; a client whose view of the teacher predates another writer's payout, or predates a refund cascade that rewrote the teacher's fee-reversed, liability and unpaid-earnings totals, is refused with `ERR_STALE_VERSION` (412). The period itself must be coherent — `period_end` strictly after `period_start` — and must not overlap any other non-`VOIDED` payout of the same teacher, or the request is refused with `ERR_PAYOUT_PERIOD_OVERLAP` (409). Re-requesting a period that an existing `REQUESTED` payout already covers is treated as an idempotent replay rather than a duplicate: when the `period_start` and `period_end` fingerprint matches and the supplied `expected_teacher_version` agrees, the server returns the existing row with HTTP 200 and creates nothing, though the existing row's `version` still advances by one. When the fingerprint matches but the caller supplied a different `expected_teacher_version`, the replay is refused with `ERR_DUPLICATE_PAYOUT_PERIOD` (409). A successful request creates the payout in `REQUESTED` status and increments the teacher's `version` by one.

Gross earnings are computed from accrual, not from disbursement. `gross_earnings_cents` is the sum, over every section owned by this teacher through its parent listing whose `outcome` is either null or `HELD` and whose `start_utc` is at or after `period_start` and strictly before `period_end`, of that section's confirmed discounted total — the sum of `discounted_price_cents` over the section's `CONFIRMED` enrollments. The period is half-open, so a section starting exactly at `period_end` belongs to the next period and one starting exactly at `period_start` belongs to this one. A section that has not started yet still accrues its confirmed revenue, and a section cancelled before it starts drops out of the sum entirely because its `outcome` is no longer null or `HELD`; this is precisely why a teacher-fault refund moves a payout. The rejected alternative reading — computing gross as the sum of `net_payout_cents` over payouts already in `PAID` status, that is, what has already been disbursed rather than what has been earned — is never applied by the server.

The platform fee is banded by gross and then adjusted twice. The band rate is 0.30 for gross below 2000 cents, 0.25 for gross from 2000 cents up to but not including 5000 cents, 0.20 for gross from 5000 cents up to but not including 10000 cents, and 0.15 for gross at or above 10000 cents. The rate is then adjusted by the format of the sections in the period: `ONE_TIME` sections take no adjustment, `MULTI_DAY` sections subtract 0.02, and `ONGOING` sections subtract 0.03. It is then reduced by a volume discount of 0.02 when the teacher's already-posted lifetime gross has reached 500000 cents. The adjusted rate is floored at the minimum fee rate of 0.10, and that floored value is what the payout records as `fee_rate_applied`.

The fee itself is floored per section and only then summed. `platform_fee_cents` is the sum, over the same accrual set of sections used for gross, of each section's confirmed discounted total multiplied by `fee_rate_applied` and floored to a whole cent. Summing the section totals first and flooring once at the end is the rejected alternative; it produces a larger fee whenever any per-section product is fractional, so the order is part of the contract. `net_payout_cents` is the gross less the platform fee, and `net_after_refunds_cents` is the gross less the platform fee less any `platform_fee_reversed_cents` already written against the payout.

Sending a payout is capped by a waterfall that spreads the cap across everything already approved. `already_approved_sent_cents` is the sum of `net_after_refunds_cents` over every other payout of the same teacher that is in `SENT` or `PAID` status. The remaining headroom is the approval cap of 100000 cents less that total, floored at zero, and `payout_proration_factor` is the smaller of 1 and the ratio of that headroom to the larger of 1 and the sum of this payout's `net_after_refunds_cents` plus `already_approved_sent_cents`. If the payout's `net_after_refunds_cents` plus the already-approved-and-sent total would exceed 100000 cents, the send is refused with `ERR_PAYOUT_CAP_EXCEEDED` (409); the payout stays in `REQUESTED` and its `approval_status` is moved to `pending_approval` so that the hold is visible on the resource. Otherwise `approval_status` is `not_required` and the payout may advance.

The settlement pipeline itself has four actions, submitted as the `action` field: `SEND`, `PAY`, `APPROVE` and `VOID`. A `SEND` moves a payout from `REQUESTED` to `SENT`, and it requires that the payout is not already held with `approval_status` of `pending_approval`, that its `tax_document_status` is `ON_FILE` (otherwise `ERR_TAX_DOC_MISSING`, 409), and that the cap check above passes; sending does not touch the teacher's unpaid balance, because the money is not yet disbursed. A `PAY` moves a payout from `SENT` to `PAID` and decrements `unpaid_earnings_cents` by the payout's `net_payout_cents`. An `APPROVE` moves a `FAILED` payout to `PAID`, requires `approval_status` to be `pending_approval` (otherwise `ERR_PAYOUT_NOT_APPROVED`, 409), writes `approved`, and also decrements `unpaid_earnings_cents` by `net_payout_cents`. A `VOID` is available from `REQUESTED`, `SENT` or `FAILED` and moves the payout to `VOIDED`, decrementing `unpaid_earnings_cents` by the payout's `net_payout_cents` unless it had already been paid and re-summing the teacher's lifetime net earnings while excluding voided rows. A payout already in `PAID` may not be transitioned again under any action — that is `ERR_PAYOUT_ALREADY_PAID` (409).

A teacher-fault refund reaches back into payouts that have already been requested. The clawback runs in three hops. The first hop finds every payout of the owning teacher that is still in `REQUESTED` and whose period covers the refunded section's `start_utc` — that is, `start_utc` is at or after `period_start` and strictly before `period_end` — and recomputes it: `gross_earnings_cents`, `fee_rate_applied`, `platform_fee_cents` and `net_payout_cents` are re-derived by the accrual and per-section-floor rules above, now excluding the refunded section; `platform_fee_reversed_cents` is written as the sum, over the refunded sections, of each section's original discounted total multiplied by `fee_rate_applied` and floored; `teacher_liability_cents` is written as the sum, over the refunded sections, of the section's original discounted total less the floored fee on it, multiplied by the teacher-liability rate of 0.50 and floored, so the teacher owes back half of what remains after the platform's reversed fee is deducted; `net_after_refunds_cents` is recomputed as gross less platform fee less the reversed fee; `refund_period_index` is stamped with the current period index; the payout's status becomes `FAILED`; and its `approval_status` becomes `pending_approval`. The second hop rolls those figures up onto the teacher: `lifetime_fee_reversed_cents` and `lifetime_teacher_liability_cents` each grow by the corresponding payout figure, and `unpaid_earnings_cents` is re-derived as the sum of `net_payout_cents` over payouts that are neither `PAID` nor `VOIDED`. The third hop re-sums `lifetime_net_earnings_cents` from all non-`VOIDED` payouts and re-derives `payout_tax_document_status` from that total, which means a refund large enough to drop lifetime earnings to or below 20000 cents returns the teacher from `REQUIRED_UPDATE` to `ON_FILE`, while a payout that pushes earnings past the reporting threshold moves the teacher the other way, to `REQUIRED_UPDATE`, which blocks that payout from settling.

Each payout row carries a `tax_document_status` that is a snapshot of the teacher's status taken when the row was created, so the payout records the document position it was settled under even if the teacher's position later changes.

### 3.9. Marketplace Operations Sweeps

Because the marketplace is operated by a small team, a single administrative capability performs the platform's periodic reconciliation in one batch. Only a `PlatformAdmin` may invoke it, it takes no input, and it answers with the identifiers of everything it touched: `cancelled_section_ids`, `completed_section_ids`, `released_enrollment_ids`, `escalated_report_ids`, `expired_application_ids` and `suspended_teacher_ids`. Six sweeps run in that batch, and each is idempotent in the sense that a resource already resolved by an earlier sweep is simply skipped.

The section sweeps cancel and close classes. The automatic-cancellation sweep cancels sections that have passed their cancellation cutoff without a sufficient enrollment projection, using the projection rule stated in §3.4. The completion sweep closes sections that have started and settled, writing `HELD` as the outcome of any completed section whose outcome is still null. The reservation sweep releases reserved seats whose section has started without the enrollment ever being confirmed.

The report sweep escalates stale queues: a report that has sat in `OPEN` for more than 14 periods is moved to `UNDER_REVIEW` so that it can be disposed of. The application sweep rejects abandoned files: an application that is still in `SAMPLE_PENDING` with a bound reviewer, where the current period index has reached the period at which the reviewer bound plus 7, is rejected automatically with `decision_reason_code` `INCOMPLETE_MATERIALS` and an incremented `revision_count`, and it advances straight to `REJECTED` if that increment exhausts the budget of 3. The money sweep re-derives `payout_tax_document_status` for every teacher whose lifetime earnings have changed, and suspends any teacher whose recomputed status is no longer `ON_FILE`, reporting them in `suspended_teacher_ids`.

The logical clock is advanced by a separate administrative capability that accepts `to_iso8601` and answers with the resulting `current_utc`. Moving the clock is what makes every deadline above reachable: the period index recomputes, and the next run of the batch sweep then applies the new period index to screening validity, reviewer deadlines, report queues and the tax-document re-derivation.

## 4. Endpoint Definitions

Every endpoint is mounted beneath the `/outschool` prefix, and the table below lists the complete surface. Operations that create a new stand-alone resource or add a distinct resource to a collection return `201 Created` with the created resource in the response body; operations that modify an existing resource, or that drive a resource through a transition, return `200 OK` with the updated resource. The one deliberate exception is the idempotent payout re-request described in §3.8, which returns `200 OK` with the existing row instead of `201`. Error responses use the status codes catalogued in §5, and the conditions that produce them are stated in §2 and §3 rather than in this table.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/outschool/teacher-applications` | Create a teacher application in `DRAFT` | TeacherApplicant, PlatformAdmin |
| GET | `/outschool/teacher-applications/{applicationId}` | Get a teacher application | TeacherApplicant, TeacherReviewer, PlatformAdmin |
| POST | `/outschool/teacher-applications/{applicationId}/submit` | Submit the application package: records the background screening and advances into screening | TeacherApplicant, PlatformAdmin |
| POST | `/outschool/teacher-applications/{applicationId}/submit-sample` | Submit or revise the teaching sample, entering the sample review queue | TeacherApplicant, PlatformAdmin |
| POST | `/outschool/teacher-applications/{applicationId}/review` | Reviewer records a verdict on the screening or sample stage | TeacherReviewer, PlatformAdmin |
| POST | `/outschool/teacher-applications/{applicationId}/approve` | Final approval: mints the `Teacher` account for the applicant | TeacherReviewer, PlatformAdmin |
| GET | `/outschool/teachers/{teacherId}` | Get a teacher, including all computed risk, earnings and tax fields | Teacher, TeacherReviewer, PlatformAdmin |
| GET | `/outschool/teachers` | List teachers, filterable by source application | TeacherReviewer, PlatformAdmin |
| POST | `/outschool/teachers/{teacherId}/activate` | Move a teacher from `PENDING_SETUP` to `ACTIVE` | PlatformAdmin |
| POST | `/outschool/teachers/{teacherId}/suspend` | Manually suspend a teacher and cascade the suspension to listings, sections and enrollments | PlatformAdmin |
| POST | `/outschool/teachers/{teacherId}/reinstate` | Return a suspended teacher to `ACTIVE` | PlatformAdmin |
| POST | `/outschool/teachers/{teacherId}/terminate` | Terminate a teacher whose listings carry no live sections | PlatformAdmin |
| POST | `/outschool/class-listings` | Create a class listing; enters content review | Teacher, PlatformAdmin |
| GET | `/outschool/class-listings/{listingId}` | Get a class listing | Teacher, TeacherReviewer, Parent, PlatformAdmin |
| GET | `/outschool/class-listings` | List class listings, filterable by owning teacher and by review or lifecycle state | Teacher, TeacherReviewer, Parent, PlatformAdmin |
| POST | `/outschool/class-listings/{listingId}/policy-review` | Content-policy review of a listing's age band and subject matter | PlatformAdmin |
| POST | `/outschool/class-listings/{listingId}/publish` | Publish an approved listing so sections can be opened | Teacher, PlatformAdmin |
| POST | `/outschool/class-listings/{listingId}/sections` | Schedule a section of a listing | Teacher, PlatformAdmin |
| GET | `/outschool/class-listings/{id}/sections` | List the sections of a listing | Teacher, Parent, TeacherReviewer, PlatformAdmin |
| POST | `/outschool/class-listings/{listingId}/sections/{sectionId}/open` | Open a scheduled section for enrollment | Teacher, PlatformAdmin |
| POST | `/outschool/class-listings/{listingId}/sections/{sectionId}/meet-minimum` | Declare the enrollment minimum satisfied | Teacher, PlatformAdmin |
| POST | `/outschool/class-listings/{listingId}/sections/{sectionId}/cancel` | Cancel a section before it starts and refund every enrollment in full | Teacher, PlatformAdmin |
| POST | `/outschool/learners` | Create a learner account owned by a parent operator id | Parent, PlatformAdmin |
| GET | `/outschool/learners/{learnerId}` | Get a learner | Parent, PlatformAdmin |
| POST | `/outschool/learners/{learnerId}/subscription` | Set the learner's subscription tier and refill the confirmation-credit allowance | Parent, PlatformAdmin |
| POST | `/outschool/class-listings/{listingId}/sections/{sectionId}/enrollments` | Reserve a seat for a learner on a section | Parent, PlatformAdmin |
| GET | `/outschool/enrollments/{enrollmentId}` | Get an enrollment | Parent, Teacher, PlatformAdmin |
| GET | `/outschool/enrollments` | List enrollments, filterable by learner and by section | Parent, Teacher, PlatformAdmin |
| POST | `/outschool/enrollments/{enrollmentId}/confirm` | Confirm a reserved seat, drawing down the learner's confirmation credit | Parent, PlatformAdmin |
| POST | `/outschool/enrollments/{enrollmentId}/cancel` | Cancel an enrollment, tiering the refund by timing and by section format | Parent, PlatformAdmin |
| POST | `/outschool/teachers/{teacherId}/payouts` | Request a payout for a settlement period | Teacher, PlatformAdmin |
| GET | `/outschool/teacher-payouts/{payoutId}` | Get a payout | Teacher, PlatformAdmin |
| GET | `/outschool/teacher-payouts` | List payouts, filterable by teacher | Teacher, PlatformAdmin |
| POST | `/outschool/teacher-payouts/{payoutId}/transition` | Advance a payout through its settlement pipeline | PlatformAdmin |
| POST | `/outschool/class-reports` | File a parent report against a teacher and listing | Parent, PlatformAdmin |
| GET | `/outschool/class-reports/{reportId}` | Get a report | Parent, PlatformAdmin |
| GET | `/outschool/class-reports` | List reports, filterable by teacher and by listing | Parent, PlatformAdmin |
| POST | `/outschool/class-reports/{reportId}/disposition` | Advance a report through review and record its disposition | PlatformAdmin |
| POST | `/outschool/_clock/set_current_utc` | Set the logical clock | PlatformAdmin |
| POST | `/outschool/_ops/run` | Run the batch sweep | PlatformAdmin |

## 5. Error Code Catalogue

The table below lists every error identifier this API can emit together with the HTTP status it carries. The conditions that trigger each one are stated in the narrative of §2 and §3, next to the workflow they guard.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_REFERENTIAL_INTEGRITY` | 409 |
| `ERR_MISSING_REQUIRED_FIELD` | 400 |
| `ERR_INVALID_ENUM_VALUE` | 400 |
| `ERR_INVALID_AGE_BAND` | 400 |
| `ERR_INVALID_TIME_WINDOW` | 400 |
| `ERR_CAPACITY_EXCEEDS_LISTING` | 400 |
| `ERR_SAMPLE_TOO_SHORT` | 400 |
| `ERR_LISTING_NOT_APPROVED` | 409 |
| `ERR_LISTING_NOT_PUBLISHED` | 409 |
| `ERR_TEACHER_NOT_ACTIVE` | 409 |
| `ERR_TEACHER_SUSPENDED` | 409 |
| `ERR_SECTION_FULL` | 409 |
| `ERR_SECTION_ALREADY_STARTED` | 409 |
| `ERR_SECTION_NOT_OPEN` | 409 |
| `ERR_DUPLICATE_ENROLLMENT` | 409 |
| `ERR_LEARNER_AGE_OUT_OF_RANGE` | 409 |
| `ERR_COUPON_NOT_FOUND` | 404 |
| `ERR_COUPON_ALREADY_REDEEMED` | 409 |
| `ERR_CREDIT_INSUFFICIENT` | 409 |
| `ERR_MIN_ENROLLMENT_NOT_MET` | 409 |
| `ERR_SCREENING_FAILED` | 409 |
| `ERR_SCREENING_STALE` | 409 |
| `ERR_REVISION_LIMIT_REACHED` | 409 |
| `ERR_APPLICATION_NOT_APPROVED` | 409 |
| `ERR_REVIEWER_CONFLICT` | 409 |
| `ERR_PAYOUT_PERIOD_OVERLAP` | 409 |
| `ERR_DUPLICATE_PAYOUT_PERIOD` | 409 |
| `ERR_TAX_DOC_MISSING` | 409 |
| `ERR_PAYOUT_NOT_APPROVED` | 409 |
| `ERR_PAYOUT_ALREADY_PAID` | 409 |
| `ERR_PAYOUT_CAP_EXCEEDED` | 409 |
| `ERR_REPORT_WINDOW_CLOSED` | 409 |
| `ERR_REPORT_SLA_EXPIRED` | 409 |

