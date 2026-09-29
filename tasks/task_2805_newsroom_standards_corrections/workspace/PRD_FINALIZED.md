# Newsroom Standards & Corrections API — Product Requirements Document

## 1. Introduction

A newsroom's credibility is an operational asset, and the standards desk is the department that maintains it. Today that work is scattered across e-mail threads, shared spreadsheets and the institutional memory of two or three senior editors: who authorised the anonymous source on last Tuesday's investigation, whether the lawyer actually signed off before the piece went live, how many days a reader complaint has been sitting unanswered, and whether the reporter now under a plagiarism inquiry still has an approved paid speaking engagement on the books. When any one of those threads breaks, the failure is public and expensive.

This document specifies the Newsroom Standards & Corrections API, a single system of record for the standards desk of a news organisation. It governs eight interlocking practices: anonymous-source authorisation with documented justification, pre-publication legal and standards review for high-risk stories, correction and clarification policy with severity classification and mandated notice placement, correction intake from readers and story subjects with enforceable response deadlines, conflict-of-interest disclosure and outside-activity approval for journalists, plagiarism and fabrication investigation with disciplinary consequence and transparency obligations, editor's notes and story unpublishing, and newsroom-wide standards training with case-study review.

The design premise is that standards work is a compliance discipline, not an editorial preference. Every consequential decision is attributable to a named actor, is refused when the actor is a party to the matter being judged, and leaves an immutable trace in a transparency log. The desk's own risk exposure is measured continuously: as severe corrections accumulate and serious misconduct inquiries open, the newsroom's operating posture tightens automatically, and at the extreme the system stops clearing and publishing stories until the backlog is worked down. The whole API is mounted under the `/standards-desk` prefix.

## 2. Global Specifications & System-Wide Principles

This section defines the contract-level rules that hold for every endpoint: how a caller identifies itself, what a response looks like, how lists are paged, how numbers are rounded, how time is told, and in what order the system refuses a bad request.

### 2.1. Acting Identities and Role-Based Access Control

Every request must carry two headers. `X-User-ID` identifies the acting user; `X-User-Role` declares the capacity in which they are acting. The system recognises exactly five roles, spelled `Reporter`, `StandardsEditor`, `LegalCounsel`, `ExecutiveEditor` and `PublicEditor`. If either header is absent, or if `X-User-Role` is not one of those five strings, the request is refused with `ERR_UNAUTHENTICATED`. If the headers are well formed but the declared role is not among the roles the target endpoint admits, the refusal is `ERR_UNAUTHORIZED`.

Four of the five roles are **entity-backed**, meaning `X-User-ID` must resolve to a real persisted record whose own attributes agree with the declared role:

- When `X-User-Role` is `Reporter`, `X-User-ID` is the `id` of the acting `Journalist`, and that journalist's `role_title` must be `REPORTER`.
- When `X-User-Role` is `StandardsEditor`, `X-User-ID` is the `id` of the acting `Journalist`, and that journalist's `role_title` must be `STANDARDS_EDITOR`.
- When `X-User-Role` is `ExecutiveEditor`, `X-User-ID` is the `id` of the acting `Journalist`, and that journalist's `role_title` must be `EXECUTIVE_EDITOR`.
- When `X-User-Role` is `LegalCounsel`, `X-User-ID` is the `id` of the acting `Reviewer`, and that reviewer's `discipline` must be `LEGAL`.

For all four, ownership checks on any resource that references a journalist or a reviewer compare that resource's foreign-key field to `X-User-ID` — a story's `lead_journalist_id`, a disclosure's or activity request's `journalist_id`, an investigation's `journalist_id`. A mismatch between `X-User-ID` and the backing record's type or title, and any case where `X-User-ID` does not resolve at all, is `ERR_UNAUTHORIZED`.

`PublicEditor` is the exception. When `X-User-Role` is `PublicEditor`, `X-User-ID` is an opaque operator identifier for the reader-advocate desk and is not tied to any persisted entity. The server records it in the transparency log's `actor_user_id` and may retain it on the records the public editor touches, but it never compares it to any entity's `id`.

There is one deliberate hole in the identity binding, and it exists because the system must be able to start empty. The two bootstrap endpoints — newsroom registration (`POST /standards-desk/newsrooms`) and journalist creation (`POST /standards-desk/journalists`) — skip the entity-backed identity check entirely, because the first `EXECUTIVE_EDITOR` journalist cannot exist before someone creates it. Both still require the headers to be present and the role to be `ExecutiveEditor`; they simply do not insist that `X-User-ID` already resolves to a journalist. Every other endpoint in the API enforces the binding.

Separately from role membership, a `Reporter` may only write resources that belong to them. Story creation must name the acting reporter in `lead_journalist_id`; a review submission or resubmission must come from the story's own lead journalist; an anonymous-source request must be filed by the lead journalist of the story it concerns; and a conflict disclosure, outside-activity request or training record must name the acting journalist in `journalist_id`. A reporter reaching for another journalist's resource receives `ERR_UNAUTHORIZED`.

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

List endpoints are paged through two query parameters. The `limit` parameter caps the number of records returned; it defaults to 10 when omitted, accepts a minimum of 1 and a maximum of 100. The `offset` parameter is the number of records to skip and defaults to 0.

Unless a specific endpoint states otherwise, every list is ordered by the record's creation timestamp, ascending — oldest first. List responses populate `limit`, `offset`, `total_count` and `has_more` in the `meta` object of the envelope, where `total_count` is the size of the full filtered set before paging and `has_more` indicates whether records remain beyond the current window.

### 2.4. Resource Identity, Timestamps and Version Counters

Every resource the API mints carries an `id` that is a server-generated UUID. Identifiers are bare UUIDs with no type prefix, no embedded entity name and no client-supplied component; a client may never propose one. Alongside it, every resource carries a `created_at` timestamp, formatted as an ISO 8601 UTC instant with exactly three fractional-second digits, for example `2026-08-01T00:00:00.000Z`.

Most resources also carry two mutation-tracking fields. `updated_at` is an ISO 8601 UTC timestamp, in the same three-fractional-digit form, refreshed on every change to the resource — including changes the server makes to itself as a downstream consequence of an operation on some other resource. `version` is an integer that starts at 1 on creation and increments by exactly 1 on every mutation. Newsrooms, journalists, reviewers, stories, anonymous-source approvals, pre-publication reviews, review assignments, correction requests, misconduct investigations, conflict disclosures and outside-activity requests all carry the full set: `id`, `created_at`, `updated_at` and `version`.

Two record types are append-only and therefore deliberately narrower. A `TrainingRecord` and a `StandardsAuditEvent` carry only `id` and `created_at`: both `updated_at` and `version` are absent from their representations, because neither record is ever modified after it is written. A filed training module is a historical fact; an audit event is a historical fact; the system rewrites neither.

Recomputation counts as mutation. When a correction adjudication drives a story's `severe_correction_count` and `risk_index_actual` to new values, the story's `updated_at` moves and its `version` advances, even though the request was addressed to the correction request rather than to the story. The same holds for a reviewer whose `reserved_minutes` are re-aggregated by a cascade, and for a journalist whose `penalty_points` are re-summed by a misconduct decision.

### 2.5. The Logical Newsroom Clock

Every instant this system records — a publication time, a decision time, a correction's response deadline, a training filing — is read from a server-side **logical clock**, never from real wall-clock time. Before any caller sets it, the logical clock reads exactly `2026-08-01T00:00:00Z`, and it never falls back to the host's actual time.

An `ExecutiveEditor` may move the clock forward or backward through an administrative test-driving capability that accepts a single field, `to_iso8601`, carrying the target instant. The response body is the object `{ current_utc: string }` reporting the clock's new reading. If `to_iso8601` cannot be parsed as an ISO 8601 UTC instant, the request is refused with `ERR_INVALID_INTERVAL`. Setting the clock has one substantive consequence: `breach_flag` is re-evaluated against `response_due_at` for every correction request that has not yet reached `RESOLVED` or `DISMISSED`.

### 2.6. Identifier Resolution and Cross-Newsroom Referential Integrity

Identifiers in a URL path are resolved strictly left to right, and the first one that fails to resolve determines the error. A request for a sub-collection beneath a newsroom that does not exist yields `ERR_NEWSROOM_NOT_FOUND` before the system considers anything nested under it; the same discipline applies beneath a journalist (`ERR_JOURNALIST_NOT_FOUND`) and beneath a story (`ERR_STORY_NOT_FOUND`). Addressing a single record by its own identifier produces the error for that record type: `ERR_SOURCE_APPROVAL_NOT_FOUND` for an anonymous-source approval, `ERR_REVIEW_NOT_FOUND` for a pre-publication review, `ERR_ASSIGNMENT_NOT_FOUND` for a review assignment, `ERR_CORRECTION_REQUEST_NOT_FOUND` for a correction request, `ERR_INVESTIGATION_NOT_FOUND` for a misconduct investigation, `ERR_DISCLOSURE_NOT_FOUND` for a conflict disclosure and `ERR_ACTIVITY_REQUEST_NOT_FOUND` for an outside-activity request. Reviewer lookups that fail yield `ERR_REVIEWER_NOT_FOUND`.

Identifiers supplied inside a request body are held to the same standard. Every `newsroom_id`, `lead_journalist_id`, `journalist_id`, `story_id`, `review_id` and `reviewer_id` in a write payload must resolve to an existing record, and a dangling reference produces the 404 belonging to the referenced type rather than a generic validation failure.

Beyond mere existence, references must stay inside the newsroom that owns them. A story's lead journalist must belong to the same newsroom named in the story's `newsroom_id`, and a reviewer booked against a review round must belong to the newsroom of that review's story. Either violation is refused with `ERR_CROSS_NEWSROOM_REFERENCE`.

### 2.7. Numeric Precision Across Risk, Severity and Compliance Figures

The system mixes decimal and integer quantities, and the distinction is normative.

- **Story risk indices.** `risk_index_estimate` and `risk_index_actual` are decimal numbers carried to exactly 2 decimal places, rounded half up. The rounding is the *last* step: the risk subtotal is an integer, the journalist multiplier is applied to that integer, the product is capped, and only the capped product is rounded to 2 decimal places.
- **Desk training compliance.** `training_compliance_index` is a decimal number to exactly 2 decimal places, rounded half up, and it is produced by a two-stage rounding whose order is normative — see the training discussion in §3.8.
- **Correction severity.** `provisional_severity_score` and `adjudicated_severity_score` are integers computed with integer arithmetic throughout. Nothing is rounded because nothing is fractional.
- **Response deadlines.** A correction's response window is computed in whole hours, with the rounding-up step applied at a specific point in the arithmetic described in §3.6.
- **Reviewer minutes.** `duration_minutes`, `reserved_minutes`, `available_minutes` and `weekly_capacity_minutes` are whole integer minutes; a slot's duration is truncated downward to a whole minute.
- **Penalty points.** `penalty_points` on both an investigation and a journalist are integers; there is no rounding anywhere in the disciplinary ledger.

Decimal values are returned in JSON as numbers, not strings.

### 2.8. Stale-View Protection on Story and Reviewer Writes

Two write operations in this API accept a version token from the client, because for both of them a repeated request is legitimate product behaviour and therefore cannot be refused by a state precondition alone.

The first is submitting a story for pre-publication review (`POST /standards-desk/pre-publication-reviews`). That request must carry `expected_story_version`, a required field whose value is the `version` the client last observed on the target `Story`. If it does not equal the story's current `version`, the submission is refused with `ERR_STALE_STORY_VERSION` and HTTP status 412. A second submission for the same story is perfectly legal once the previous round has been sent back for revision — the new round supersedes the old — so the guard cannot be "a review already exists". It is instead a guard on the story's version, which every sourcing decision, correction intake and risk recomputation advances. A reporter who read the story, then had an editor revoke an anonymous source underneath them, is submitting against a story whose risk profile they have not seen, and the system makes them re-read it first.

The second is booking a reviewer slot (`POST /standards-desk/review-assignments`). That request must carry `expected_reviewer_version`, a required field whose value is the `version` the client last observed on the target `Reviewer`. If it does not equal the reviewer's current `version`, the booking is refused with `ERR_STALE_REVIEWER_VERSION` and HTTP status 412. Two bookings for genuinely disjoint slots are both legitimate, so again no state precondition covers the case; what invalidates the caller's view is that their reading of `reserved_minutes` and `available_minutes` is out of date, and every booking, cancellation and cascade completion bumps the reviewer's `version`.

No other endpoint in this API accepts a version field, and no other endpoint performs a stale-view check. Endpoints not named in this subsection take no version token at all.

### 2.9. The Desk-Wide Standards Posture

Each newsroom carries a derived gate called `standards_posture`, which takes one of exactly three values — `OPEN`, `HEIGHTENED` or `LOCKDOWN` — and starts at `OPEN` when the newsroom is registered. It is not set by hand; it is recomputed by the server from a single integer, `open_high_severity_count`, which itself starts at 0 and is the sum of two live counts:

- the number of correction requests belonging to stories of this newsroom whose `status` is `ADJUDICATED` and whose `adjudicated_severity_band` is either `MAJOR` or `SEVERE`; and
- the number of misconduct investigations whose subject journalist belongs to this newsroom, whose `status` is `OPENED`, `EVIDENCE_REVIEW` or `RESPONSE_PENDING`, and whose `severity` is either `SERIOUS` or `EGREGIOUS`.

Corrections leave that pool the moment their notice is published and the request reaches `RESOLVED`, which is precisely what allows the posture to relax again. Investigations leave it as soon as they are decided, whichever way. Allegations assessed as `MINOR` never move the posture at all, and corrections still in `INTAKE`, `INVESTIGATING`, `AWAITING_SUBJECT`, `RESOLVED` or `DISMISSED` do not count.

The newsroom's own `high_severity_open_threshold` — an integer between 1 and 20 inclusive, defaulting to 2 — sets where the gate trips. When `open_high_severity_count` reaches twice the threshold or more, the posture is `LOCKDOWN`. Otherwise, when it reaches the threshold or more, the posture is `HEIGHTENED`. Below the threshold it is `OPEN`. Both comparisons are inclusive: a count exactly equal to the threshold is already `HEIGHTENED`, and a count exactly equal to double the threshold is already `LOCKDOWN`.

Posture has teeth. Under `LOCKDOWN`, neither clearing a review round nor publishing a story is permitted, and both are refused with `ERR_POSTURE_LOCKDOWN`. Under `HEIGHTENED`, clearing a review round is reserved to an `ExecutiveEditor`; when a `StandardsEditor` attempts it, the refusal is `ERR_HEIGHTENED_REQUIRES_EXEC`. Publication is unaffected by `HEIGHTENED` posture. Whenever the posture value actually changes, the desk's transparency log gains an event of type `POSTURE_CHANGED`.

The posture is recomputed on newsroom creation, on every correction adjudication and resolution, and on every misconduct investigation opening, decision and appeal.

### 2.10. Segregation of Duties

Four decisions in this API are structurally barred to anyone with a stake in the outcome, and the refusal in every case is `ERR_SEGREGATION_OF_DUTIES` with HTTP status 403.

Deciding an anonymous-source request and adjudicating a correction are both barred to the lead journalist of the story concerned: the acting `X-User-ID` must not equal that story's `lead_journalist_id`. Deciding a misconduct investigation is barred both to its subject and to the editor who opened it: the acting `X-User-ID` must not equal the investigation's `journalist_id` and must not equal its `opened_by_user_id`. Hearing an appeal against a sustained finding is barred to its subject and to the editor who decided it: the acting `X-User-ID` must not equal the investigation's `journalist_id` and must not equal its `decided_by_user_id`.

To make those checks possible, the system retains the acting identity on the record at each decision point — `decided_by_user_id` on an anonymous-source approval, `opened_by_user_id` and `decided_by_user_id` on a misconduct investigation, `reviewed_by_user_id` on a conflict disclosure, `decided_by_user_id` on an outside-activity request. Each of these is an opaque audit value copied from `X-User-ID`; none of them is a queryable relationship and none may be filtered on.

### 2.11. Cascade Discipline and the Transparency Log

A story carries two independent state dimensions that advance on disjoint triggers. `publication_status` tracks the story through `DRAFT`, `IN_REVIEW`, `CLEARED`, `PUBLISHED` and terminally `UNPUBLISHED`. `standards_status` tracks its editorial integrity through `CLEAN`, `UNDER_INQUIRY`, `CORRECTED` and terminally `RETRACTED`, and unlike the publication dimension it is cyclic: a corrected story returns to `UNDER_INQUIRY` when a fresh complaint arrives. The two dimensions never interact except at one point — unpublishing writes both, driving `publication_status` to `UNPUBLISHED` and `standards_status` to `RETRACTED` in the same operation.

Where an operation has downstream consequences, those consequences are applied immediately and completely within the same request; nothing is deferred to a background sweep. Aggregate figures are always recomputed by full re-aggregation over the current rows, never by applying an incremental delta to a stored total — so a cascade that moves three reviewer bookings at once still lands on the exact sum rather than drifting. Each entity a cascade touches has its own `updated_at` refreshed and its own `version` incremented.

Consequential transitions also append to an immutable transparency log, the `StandardsAuditEvent` stream. Each event records the newsroom it belongs to in `newsroom_id`, which the server populates from the subject's own newsroom and never accepts from a request body; an `event_type` drawn from `SOURCE_APPROVED`, `SOURCE_DENIED`, `SOURCE_REVOKED`, `REVIEW_CLEARED`, `STORY_PUBLISHED`, `STORY_UNPUBLISHED`, `CORRECTION_ADJUDICATED`, `CORRECTION_RESOLVED`, `INVESTIGATION_SUSTAINED`, `INVESTIGATION_OVERTURNED`, `POSTURE_CHANGED` and `ACTIVITY_REVOKED`; a polymorphic subject reference made of `subject_type` — one of `Story`, `CorrectionRequest`, `MisconductInvestigation`, `AnonymousSourceApproval`, `Newsroom` or `OutsideActivityRequest` — together with the `subject_id` of the record in question; the `actor_role` that caused it, which is the acting `X-User-Role` for a directly requested transition and the literal string `system` for a cascaded one; the `actor_user_id`, which is the acting `X-User-ID` for a directly requested transition and null for a cascaded one; a one-line human-readable `summary`; and `occurred_at`, the logical-clock instant at which the event was emitted. The log is append-only in `occurred_at` order and is never rewritten.

### 2.12. Order of Precedence Among Validations

When a single request violates more than one rule, the response reports the violation that comes first in the following ladder. The ordering is normative, because it decides which of several plausible error identifiers the caller actually sees.

1. Header presence and role recognition — `ERR_UNAUTHENTICATED`.
2. Entity-backed identity binding, exempted only on `POST /standards-desk/newsrooms` and `POST /standards-desk/journalists` — `ERR_UNAUTHORIZED`.
3. Role membership in the endpoint's authorised list — `ERR_UNAUTHORIZED`.
4. Reporter ownership on `POST /standards-desk/stories`, `POST /standards-desk/anonymous-source-approvals`, `POST /standards-desk/pre-publication-reviews`, `POST /standards-desk/pre-publication-reviews/{id}/resubmit`, `POST /standards-desk/conflict-disclosures`, `POST /standards-desk/outside-activity-requests` and `POST /standards-desk/training-records` — `ERR_UNAUTHORIZED`.
5. Segregation of duties on `POST /standards-desk/anonymous-source-approvals/{id}/decide`, `POST /standards-desk/correction-requests/{id}/adjudicate`, `POST /standards-desk/misconduct-investigations/{id}/decide` and `POST /standards-desk/misconduct-investigations/{id}/appeal` — `ERR_SEGREGATION_OF_DUTIES`.
6. Path identifier resolution, left to right — the 404 for the first unresolved segment.
7. Request-body identifier resolution — the 404 for the referenced type.
8. Body shape: required fields present, enum members recognised, integers inside their declared ranges, strings inside their declared lengths, arrays non-empty where required, and unknown fields rejected outright — `ERR_INVALID_REQUEST`.
9. Interval sanity on `POST /standards-desk/review-assignments`, `POST /standards-desk/outside-activity-requests` and `POST /standards-desk/_clock/set_current_utc` — `ERR_INVALID_INTERVAL`.
10. Stale-view checks on `POST /standards-desk/pre-publication-reviews` and `POST /standards-desk/review-assignments` — `ERR_STALE_STORY_VERSION` or `ERR_STALE_REVIEWER_VERSION`.
11. Generic state admissibility, for every action endpoint that has no more specific state error — `ERR_INVALID_STATE`.
12. Publish requires `publication_status` `CLEARED` — `ERR_STORY_NOT_CLEARED`.
13. Unpublish requires `publication_status` `PUBLISHED` — `ERR_STORY_NOT_PUBLISHED`.
14. The review round must still be open for the verdict being recorded — `ERR_REVIEW_ROUND_NOT_OPEN`.
15. A standards verdict on a legal-review round requires the legal pass first — `ERR_LEGAL_VERDICT_REQUIRED`.
16. An anonymous-source decision requires `status` `REQUESTED` — `ERR_SOURCE_ALREADY_DECIDED`.
17. Adjudication requires the correction to be `INVESTIGATING` or `AWAITING_SUBJECT` — `ERR_CORRECTION_NOT_INVESTIGATED`.
18. An appeal requires the investigation to be `SUSTAINED` — `ERR_APPEAL_NOT_ALLOWED`.
19. Posture must not be `LOCKDOWN` when clearing a review or publishing a story — `ERR_POSTURE_LOCKDOWN`.
20. Under `HEIGHTENED` posture only an `ExecutiveEditor` may clear — `ERR_HEIGHTENED_REQUIRES_EXEC`.
21. Source approval requires complete documentation — `ERR_INSUFFICIENT_SOURCE_DOCUMENTATION`.
22. Source approval at `SEVERE` harm risk requires corroboration — `ERR_INSUFFICIENT_CORROBORATION`.
23. Publishing a `HIGH` risk-tier story requires current training — `ERR_TRAINING_NOT_CURRENT`.
24. No anonymous source of the story may be unresolved or revoked at publication — `ERR_SOURCE_NOT_APPROVED`.
25. The lead journalist must be `ACTIVE` on `POST /standards-desk/stories`, `POST /standards-desk/pre-publication-reviews`, `POST /standards-desk/pre-publication-reviews/{id}/resubmit` and `POST /standards-desk/stories/{id}/publish` — `ERR_JOURNALIST_SUSPENDED`.
26. Cross-newsroom references on `POST /standards-desk/stories` and `POST /standards-desk/review-assignments` — `ERR_CROSS_NEWSROOM_REFERENCE`.
27. Reviewer discipline must match the stage awaited — `ERR_REVIEWER_DISCIPLINE_MISMATCH`.
28. Outside-activity approval requires no pending disclosure — `ERR_COI_DISCLOSURE_PENDING`.
29. The activity's beat must not be restricted — `ERR_ACTIVITY_BEAT_RESTRICTED`.
30. Unpublishing requires a documented basis — `ERR_UNPUBLISH_NOT_JUSTIFIED`.
31. Notice copy must be present or absent as the outcome demands — `ERR_NOTICE_TEXT_REQUIRED`.
32. Outside-activity interval overlap — `ERR_OUTSIDE_ACTIVITY_OVERLAP`.
33. Reviewer slot collision with buffer — `ERR_REVIEWER_SLOT_CONFLICT`.
34. Scoped uniqueness on `POST /standards-desk/training-records` and `POST /standards-desk/anonymous-source-approvals` — `ERR_DUPLICATE_TRAINING_MODULE` or `ERR_DUPLICATE_SOURCE_ALIAS`.
35. Reviewer weekly capacity — `ERR_REVIEWER_CAPACITY_EXCEEDED`.

Steps 1, 3, 6 and 8 apply to every request; step 7 applies to every write carrying body identifiers; the remainder apply only to the endpoints named in their own description. The practical consequences worth internalising: an unauthorised role never learns whether the resource exists, a segregation-of-duties breach is reported ahead of any state complaint, a stale version token is reported ahead of any business rule, and among business rules the newsroom's posture outranks every story-level condition.

## 3. Business Logic & Workflows

### 3.1. Standing Up the Desk: Newsrooms, People and Reviewers

Everything begins with a newsroom. An `ExecutiveEditor` registers one by supplying a `name` between 1 and 120 characters, and may tune three policy dials at the same time. `correction_response_sla_hours` is the base window, in hours, that the desk gives itself to answer a complaint; it defaults to 72 and must fall between 1 and 336 inclusive — that is, from one hour to a full fortnight. `high_severity_open_threshold` is the number of concurrently open high-severity matters at which the desk tightens up, defaulting to 2 and constrained to between 1 and 20 inclusive. `required_module_codes` is the array of standards training modules every journalist of the newsroom owes; it defaults to a single-element array containing `SOURCING`, must be non-empty with no repeated members, and every member must be one of `SOURCING`, `CORRECTIONS`, `LEGAL_RISK`, `ANONYMOUS_SOURCING` or `PLAGIARISM`. A newly registered newsroom opens with `standards_posture` `OPEN`, `open_high_severity_count` 0 and `training_compliance_index` 0.00.

Adding people is the same editor's job. Creating a journalist takes the employing `newsroom_id`, a `full_name` of 1 to 120 characters, an `email` that must contain an `@` character and must be unique among the journalists of that same newsroom, and a `role_title` of `REPORTER`, `STANDARDS_EDITOR` or `EXECUTIVE_EDITOR` — the masthead title that the `X-User-Role` header must agree with, as §2.1 describes. A new journalist starts with `employment_status` `ACTIVE`, `penalty_points` 0, `completed_required_module_count` 0, `training_current` false and `restricted_beats` as an empty array, and their arrival immediately re-runs the newsroom's `training_compliance_index` because the cohort has grown.

Reviewers are a separate population from journalists, because the people who scrutinise copy are not the people who write it. Registering one takes the `newsroom_id` they serve, a `full_name` of 1 to 120 characters, a `discipline` of either `LEGAL` or `STANDARDS`, and a `weekly_capacity_minutes` figure that defaults to 600 and must be at least 60 and at most 4800. A `LegalCounsel` identity, per §2.1, is always backed by a `LEGAL` reviewer. On registration the reviewer's `reserved_minutes` is 0 and `available_minutes` equals `weekly_capacity_minutes`.

The desk's standing can be read back at any time. A journalist listing for a newsroom may be narrowed by `role_title` or by `employment_status`; a reviewer listing may be narrowed by `discipline`; the transparency log may be narrowed by `event_type` or by `subject_type`. There is also a computed summary read of the newsroom's position at the current logical instant, returning `standards_posture`, `open_high_severity_count`, `training_compliance_index`, a `published_story_count` of the newsroom's stories that have reached publication, an `open_correction_request_count` aggregating the newsroom's unresolved complaints, and a `breached_correction_count` giving the number of those complaints whose response deadline has already passed as measured against the logical clock.

### 3.2. Opening a Story File and Authorising Anonymous Sources

A `Reporter` opens a story file by naming the owning `newsroom_id`, themselves as `lead_journalist_id`, and a working `headline` of 1 to 200 characters. Three optional integers inventory the story's legal exposure as the desk currently understands it: `defamation_claim_count`, the number of potentially defamatory assertions in the copy; `privacy_subject_count`, the number of private individuals identifiable in it; and `unverified_document_count`, the number of documents relied on that nobody has independently verified. Each defaults to 0 and each must fall between 0 and 50 inclusive. The story opens with `publication_status` `DRAFT` and `standards_status` `CLEAN`, with all four of its derived counters — `approved_anonymous_source_count`, `revoked_anonymous_source_count`, `severe_correction_count` and `open_correction_request_count` — at 0, with `risk_index_estimate` at 0.00, `risk_tier` at `STANDARD`, and with `risk_index_actual`, `published_at`, `unpublished_at` and `editors_note_text` all null. Its risk figures are then computed straight away. The named lead journalist must belong to the story's own newsroom (§2.6) and must be `ACTIVE`; a story cannot be opened in the name of a suspended reporter, and the attempt is refused with `ERR_JOURNALIST_SUSPENDED`.

**The risk index.** A story's exposure is expressed as a **risk index**, and the desk keeps two of them. `risk_index_estimate` is the desk's forward-looking figure, present from creation onward. `risk_index_actual` is the retrospective figure, which stays null until the story is published and is maintained from that point on. Both are produced by the same skeleton, and both share an opening term drawn entirely from the story's approved anonymous sources.

That shared term works as follows. Count the story's anonymous-source approvals whose `status` is `APPROVED` and whose `harm_risk` is `SEVERE`, then take the smaller of that count and 3. Multiply the result by 4. Separately, count the story's approved approvals whose `harm_risk` is `ELEVATED`, take the smaller of that count and 5, and multiply by 2. The two products added together form the sourcing base. Approvals in `REQUESTED`, `DENIED` or `REVOKED` contribute nothing to this base; a source at `LOW` harm risk contributes nothing either, however many of them there are.

The estimate variant adds two declared-exposure terms to that base. The first is three points for every potentially defamatory assertion counted in `defamation_claim_count` plus two points for every identifiable private individual counted in `privacy_subject_count`. The second is a flat five-point documentation penalty applied when `unverified_document_count` is greater than zero, and nothing at all when it is zero — a single unverified document costs the same as a dozen.

The three terms add to an integer subtotal, and then the lead journalist's disciplinary record scales it. Read `penalty_points` from the journalist named in `lead_journalist_id`. If that figure is 6 or more, the subtotal is multiplied by 1.25; otherwise, if it is 3 or more, the subtotal is multiplied by 1.10; otherwise the multiplier is 1.00 and the subtotal passes through unchanged. The product is then capped at 100.00 — the index can never exceed that ceiling however lurid the story — and only after the capping is the result rounded half up to 2 decimal places. The order matters and is fixed: subtotal first, then the multiplier, then the cap, then the rounding.

From the estimate alone the desk derives a coarse band, `risk_tier`, which is `HIGH` when `risk_index_estimate` is 40.00 or greater, `ELEVATED` when it is 20.00 or greater but below 40.00, and `STANDARD` otherwise. The tier is always banded from the estimate and never from the actual figure, which is why publishing a story can never change its tier. `risk_index_estimate` and `risk_tier` are recomputed on story creation, on every anonymous-source approval and revocation, on every review submission and resubmission, and at publication.

**Requesting anonymity.** A `Reporter` files an anonymous-source request against their own story by naming the `story_id` and supplying a `source_alias` — the non-identifying name that will appear in copy, 1 to 80 characters, and unique among that story's approvals, with a repeat refused as `ERR_DUPLICATE_SOURCE_ALIAS`. The request also carries a `source_category` of `GOVERNMENT`, `CORPORATE`, `VICTIM`, `WHISTLEBLOWER` or `LAW_ENFORCEMENT`; a `harm_risk` assessment of `LOW`, `ELEVATED` or `SEVERE` describing what would happen to the source if identified; a required boolean `identity_known_to_editor` recording whether a standards editor holds the true identity on the record; a `corroboration_count` of independent sources supporting the source's central claim, defaulting to 0 and bounded to between 0 and 20 inclusive; and a `justification_text` of up to 2000 characters arguing why anonymity is warranted. The record is created in `status` `REQUESTED`, and at that moment the server computes `documentation_complete`, which is true exactly when `identity_known_to_editor` is true **and** `justification_text` is at least 20 characters long, and false otherwise.

Decisions belong to the standards desk, never to the author. A `StandardsEditor` or `ExecutiveEditor` decides a `REQUESTED` approval by supplying a `decision` — `APPROVE` or `DENY` — and optionally a `decision_note`. The deciding user must not be the story's lead journalist (§2.10). Deciding a record that is no longer `REQUESTED` is refused with `ERR_SOURCE_ALREADY_DECIDED`.

The two branches are not symmetric. Approval, moving the record `REQUESTED → APPROVED`, is gated twice: `documentation_complete` must be true, and a failure here is `ERR_INSUFFICIENT_SOURCE_DOCUMENTATION`; and if `harm_risk` is `SEVERE`, `corroboration_count` must be at least 2, with a shortfall refused as `ERR_INSUFFICIENT_CORROBORATION`. On success the server stores `decided_by_user_id` and `decided_at`, increments the story's `approved_anonymous_source_count`, recomputes the story's `risk_index_estimate` and `risk_tier` — and `risk_index_actual` too, when the story has already been published — advances the story's `version` by one, and appends an audit event of type `SOURCE_APPROVED`. Denial, moving the record `REQUESTED → DENIED`, is gated by neither documentation nor corroboration: it stores `decided_by_user_id` and `decided_at`, advances the story's `version` by one, and appends an audit event of type `SOURCE_DENIED`, but performs no risk recomputation at all, because a denied source never entered the approved pool.

**Revoking after the fact.** Sometimes a source falls apart after clearance. A `StandardsEditor` or `ExecutiveEditor` may revoke an `APPROVED` approval by supplying a `revocation_reason`, taking it `APPROVED → REVOKED`. Revocation is only available from `APPROVED`; attempting it against a `REQUESTED`, `DENIED` or already `REVOKED` record is refused with `ERR_INVALID_STATE`. The consequences reach further than approval's did: the reason is stored, the story's `approved_anonymous_source_count` is decremented and its `revoked_anonymous_source_count` incremented, `risk_index_estimate` and `risk_tier` are recomputed because the approved pool shrank, `risk_index_actual` is recomputed as well when the story is `PUBLISHED`, the story's `version` advances by one, and an audit event of type `SOURCE_REVOKED` is appended. Crucially, a published story that now carries a revoked source is no longer clean: if its `standards_status` was `CLEAN` or `CORRECTED`, it becomes `UNDER_INQUIRY`.

A story's approval records can be listed with filters on `status` and on `harm_risk`, and any single approval can be read on its own.

### 3.3. The Pre-Publication Review Cycle

Before a story can be cleared, it goes through a bounded revision cycle in front of the desk's lawyers and standards editors. The story's own lead journalist starts a round, which advances `publication_status` from `DRAFT` to `IN_REVIEW` and creates a review record in `status` `SUBMITTED` at `review_round` 1. The submission names the `story_id`, carries the `expected_story_version` token described in §2.8, and may carry two further fields: `high_risk_declared`, a boolean defaulting to false by which the desk forces the legal track regardless of what the arithmetic says, and a free-text `submission_note` explaining the state of the copy, which defaults to null. Submission is only available from `DRAFT`; the lead journalist must be `ACTIVE`, or the round is refused with `ERR_JOURNALIST_SUSPENDED`. Opening the round recomputes the story's `risk_index_estimate` and advances the story's `version` by one.

At submission the server pins `requires_legal_review` on the new round. It is true when `high_risk_declared` is true **or** when the story's `risk_tier` is `HIGH` at that moment, and false otherwise. That single boolean decides which of two tracks the round follows, and it is not revisited later in the round.

**The legal track.** When `requires_legal_review` is true, a `LegalCounsel` — and only a `LegalCounsel` — must speak first. The verdict carries a `legal_verdict` of `PASS`, `CHANGES_REQUIRED` or `BLOCK`, together with the defamation and privacy analysis itself: `defamation_findings`, the count of defamation exposures the lawyer actually found, and `privacy_findings`, the count of privacy exposures, each an integer between 0 and 50 inclusive. An optional `findings_note` carries the narrative. All three values are stored on the round whichever way the verdict goes.

A `PASS` moves the round `SUBMITTED → LEGAL_CLEARED` and advances the round's own `version` by one; the story stays `IN_REVIEW`. A `CHANGES_REQUIRED` moves the round `SUBMITTED → CHANGES_REQUESTED` and sends the story back, returning `publication_status` from `IN_REVIEW` to `DRAFT`; because the round has left its open stage, every review assignment of that round still in `SCHEDULED` becomes `CANCELLED`, and because those bookings left `SCHEDULED`, each affected reviewer's `reserved_minutes` is re-aggregated and `available_minutes` follows. The story's `version` advances by one. A `BLOCK` moves the round `SUBMITTED → BLOCKED`, which is terminal, and carries exactly the same downstream consequences: the story returns to `DRAFT`, the round's `SCHEDULED` bookings become `CANCELLED`, and the affected reviewer ledgers are re-aggregated. Recording a legal verdict on a round whose `requires_legal_review` is false has no declared transition and is refused with `ERR_INVALID_STATE`.

**The standards track.** A `StandardsEditor` or `ExecutiveEditor` records the standards verdict, supplying a `standards_verdict` of `PASS`, `CHANGES_REQUIRED` or `BLOCK` and optionally a `findings_note`. Where it may be recorded from depends on the track. On a round that requires legal review, the standards verdict may only be recorded once the round is `LEGAL_CLEARED` — the legal `PASS` must already be on the record — and an attempt made while the round is still `SUBMITTED` is refused with `ERR_LEGAL_VERDICT_REQUIRED`. On a round that does not require legal review, the standards verdict is recorded directly from `SUBMITTED`, closing the round without any legal involvement at all.

Both entry points behave identically thereafter. A `PASS` moves the round to `STANDARDS_CLEARED`, stores `standards_verdict` and advances the round's `version` by one. A `CHANGES_REQUIRED` moves the round to `CHANGES_REQUESTED`, returns the story from `IN_REVIEW` to `DRAFT`, cancels the round's `SCHEDULED` bookings and re-aggregates the affected reviewer ledgers — the same three consequences the legal `CHANGES_REQUIRED` produced.

**Which rounds are open.** A verdict may only be recorded while the round is at the stage that verdict belongs to: `SUBMITTED` for a legal verdict, and `SUBMITTED` or `LEGAL_CLEARED` for a standards verdict. A round that has reached `CLEARED`, `BLOCKED`, `CHANGES_REQUESTED` or `STANDARDS_CLEARED` is closed to further verdicts, and the refusal is `ERR_REVIEW_ROUND_NOT_OPEN`.

**Resubmission, and why the loop terminates.** A round in `CHANGES_REQUESTED` can be revived by the story's lead journalist — and by nobody else — with an optional `revision_note`. Resubmission moves the round `CHANGES_REQUESTED → SUBMITTED`, increments `review_round` by one, clears both `legal_verdict` and `standards_verdict` back to null so the next round starts from a blank record, drives the story from `DRAFT` back to `IN_REVIEW`, recomputes `risk_index_estimate` and advances the story's `version` by one. The lead journalist must still be `ACTIVE`, or the attempt is refused with `ERR_JOURNALIST_SUSPENDED`. This `DRAFT → IN_REVIEW → DRAFT → IN_REVIEW` loop is the revision cycle, and it terminates because `review_round` is capped at 3: resubmission requires `review_round` to be less than 3, so a round that has already reached its third submission cannot be sent round a fourth time, and the attempt is refused with `ERR_INVALID_STATE`.

**Clearing the round.** Once a round reaches `STANDARDS_CLEARED` it can be closed out by a `StandardsEditor` or an `ExecutiveEditor`, with no request body at all. Clearing is refused outright when the newsroom's `standards_posture` is `LOCKDOWN` (`ERR_POSTURE_LOCKDOWN`), and under `HEIGHTENED` posture it is reserved to an `ExecutiveEditor` (`ERR_HEIGHTENED_REQUIRES_EXEC`); both gates are described in §2.9. Attempting to clear a round that has not reached `STANDARDS_CLEARED` is refused with `ERR_INVALID_STATE`. On success the round moves `STANDARDS_CLEARED → CLEARED`, `cleared_at` is stamped from the logical clock, and the story advances `IN_REVIEW → CLEARED` with its `version` incremented by one. Because the round has reached its successful terminus rather than being sent back, its `SCHEDULED` bookings become `COMPLETED` rather than `CANCELLED` — but the ledger effect is the same, since each affected reviewer's `reserved_minutes` and `available_minutes` are re-aggregated either way. An audit event of type `REVIEW_CLEARED` is appended.

A story's review rounds can be listed and narrowed by `status`, and any single round can be read on its own together with its legal and standards findings.

### 3.4. Reviewer Time as a Conserved Resource

Reviewer attention is the scarcest thing the standards desk buys, so the system treats it as a ledger rather than a calendar. Each reviewer's `weekly_capacity_minutes` is the conserved total; `reserved_minutes` is the portion currently committed; `available_minutes` is what remains. The system guarantees that `reserved_minutes` and `available_minutes` always sum to exactly `weekly_capacity_minutes`, before and after every operation, cascades included.

A `LegalCounsel` or `StandardsEditor` books a slot against an open round by naming the `review_id`, the `reviewer_id` whose minutes it will occupy, an inclusive `starts_at` and an inclusive `ends_at` — both ISO 8601 UTC instants — and the `expected_reviewer_version` token from §2.8. The booking is created in `status` `SCHEDULED`, and the server derives `duration_minutes` as the number of whole minutes between the two instants: take the elapsed seconds, divide by 60 and truncate downward, so a slot of 89 seconds is one minute and a slot of 59 seconds is zero. `ends_at` must be strictly after `starts_at`, and a non-positive interval is refused with `ERR_INVALID_INTERVAL`.

Three further checks stand between a booking request and a reserved slot, and they are evaluated in the order given here. First, the reviewer must belong to the same newsroom as the review's story, or the request is refused with `ERR_CROSS_NEWSROOM_REFERENCE`. Second, the reviewer's `discipline` must match the stage the round is actually waiting on: `LEGAL` when the round's `status` is `SUBMITTED` and its `requires_legal_review` is true, and `STANDARDS` in every other case. A mismatch is refused with `ERR_REVIEWER_DISCIPLINE_MISMATCH`. Third, the slot must not collide with any other `SCHEDULED` booking of the same reviewer once a **thirty-minute turnaround buffer** is applied to both sides of the comparison: a collision exists when the new slot's `starts_at` falls earlier than the other slot's `ends_at` extended by thirty minutes and the other slot's `starts_at` falls earlier than the new slot's `ends_at` extended by thirty minutes. In practice, a slot that begins exactly thirty minutes after another one ends is admissible, while one that begins twenty-nine minutes after is refused with `ERR_REVIEWER_SLOT_CONFLICT`.

Last comes the capacity test. The reviewer's `reserved_minutes` as they stand before the booking, plus the new slot's `duration_minutes`, must be no greater than `weekly_capacity_minutes`. Equality is admissible — a booking that consumes the reviewer's last remaining minute exactly is accepted — while exceeding the capacity by even one minute is refused with `ERR_REVIEWER_CAPACITY_EXCEEDED`. Because the admission test runs first, `available_minutes` can never go negative. On acceptance, `reserved_minutes` rises and `available_minutes` falls by the slot's duration, and the reviewer's `version` is incremented by one.

`reserved_minutes` is never adjusted by a delta. It is always recomputed as the sum of `duration_minutes` over every booking of that reviewer whose `status` is `SCHEDULED`; `COMPLETED` and `CANCELLED` bookings contribute zero. `available_minutes` is then the reviewer's `weekly_capacity_minutes` less that sum. This full re-aggregation is what makes a multi-row cascade safe: when a suspension blocks a review that held three bookings at once, the reviewer's ledger still lands on the exact remaining sum instead of drifting.

Releasing a slot deliberately is the compensating action for booking it. A `LegalCounsel`, `StandardsEditor` or `ExecutiveEditor` cancels a `SCHEDULED` booking by supplying a `cancellation_reason`, which is stored on the record; the booking moves `SCHEDULED → CANCELLED`, the reviewer's ledger is re-aggregated so the minutes return to `available_minutes` and leave `reserved_minutes`, and the reviewer's `version` is incremented by one. Cancelling a booking that is already `COMPLETED` or `CANCELLED` is refused with `ERR_INVALID_STATE`.

Bookings also leave `SCHEDULED` without anyone asking. When a round is cleared, its `SCHEDULED` bookings move `SCHEDULED → COMPLETED`. When a round is sent back with changes requested, blocked by legal, or blocked by a suspension cascade, its `SCHEDULED` bookings move `SCHEDULED → CANCELLED`. In every one of those cases the affected reviewer's `reserved_minutes` and `available_minutes` are re-aggregated and the reviewer's `version` is incremented, exactly as a hand-cancellation would have done. Bookings can be read individually or listed with filters on `review_id`, `reviewer_id` and `status`, and a reviewer can be read on their own to inspect `reserved_minutes` and `available_minutes` directly.

### 3.5. Clearing, Publication and Removal from the Site

Publication is the accountable editor's act alone. An `ExecutiveEditor` publishes a story with no request body, and the operation advances `publication_status` from `CLEARED` to `PUBLISHED`. Five conditions guard it. The story must actually be `CLEARED`, and an attempt from `DRAFT`, `IN_REVIEW`, `PUBLISHED` or `UNPUBLISHED` is refused with `ERR_STORY_NOT_CLEARED`. The newsroom's `standards_posture` must not be `LOCKDOWN`, or the refusal is `ERR_POSTURE_LOCKDOWN`. No anonymous-source approval of the story may still be sitting in `REQUESTED`, and none may have been `REVOKED` — an unresolved source or a withdrawn one both refuse publication with `ERR_SOURCE_NOT_APPROVED`, while `APPROVED` and `DENIED` records are both fine, the first because it was cleared and the second because it will not appear in the copy. When the story's `risk_tier` is `HIGH`, its lead journalist must have `training_current` true, and a shortfall is refused with `ERR_TRAINING_NOT_CURRENT`; stories at `STANDARD` and `ELEVATED` tier are exempt from the training gate entirely. Finally the lead journalist must be `ACTIVE`, or the refusal is `ERR_JOURNALIST_SUSPENDED`.

On success `published_at` is stamped from the logical clock, an audit event of type `STORY_PUBLISHED` is appended, and the story's `version` advances by one. Publication is also the moment `risk_index_actual` comes into existence, computed for the first time.

**The retrospective risk index.** `risk_index_actual` follows the same skeleton as the estimate from §3.2 — the same sourcing base, the same journalist multiplier, the same 100.00 ceiling, the same half-up rounding to 2 decimal places in the same pinned order — but it adds what actually went wrong to the two declared-exposure terms. To the claim term (three points per assertion in `defamation_claim_count` plus two points per individual in `privacy_subject_count`) it adds six points for every one of the story's correction requests whose `status` is `ADJUDICATED` or `RESOLVED` and whose `adjudicated_severity_band` is `MAJOR` or `SEVERE`; requests in `INTAKE`, `INVESTIGATING`, `AWAITING_SUBJECT` or `DISMISSED` add nothing, and neither do adjudicated requests banded `TRIVIAL` or `MINOR`. To the documentation term (five points when `unverified_document_count` is above zero, nothing when it is zero) it adds seven points for every revoked anonymous source, counted from `revoked_anonymous_source_count`. Identical declared inputs therefore yield a strictly larger actual index than estimate once a story has been corrected or has lost a source. `risk_index_actual` is recomputed at publication, on every subsequent correction adjudication of that story, on every source revocation, and at removal from the site. It never influences `risk_tier`.

**Unpublishing.** Taking a story off the site is the gravest editorial act in this system and it requires a documented basis. An `ExecutiveEditor` performs it by supplying a `removal_reason` explaining the decision internally and an `editors_note_text` — the transparency note that will stand in the story's place publicly. The story must be `PUBLISHED`, or the request is refused with `ERR_STORY_NOT_PUBLISHED`. Beyond that, at least one of two things must be true: either some misconduct investigation with `status` `SUSTAINED` names this story, or the story's `severe_correction_count` is 1 or more. If neither holds, the removal is refused with `ERR_UNPUBLISH_NOT_JUSTIFIED` — editors may not quietly disappear a story that nothing on the record faults.

Removal is the single point where the two story dimensions move together. `publication_status` goes `PUBLISHED → UNPUBLISHED`, which is terminal, and `standards_status` goes to `RETRACTED` from whichever of `CLEAN`, `UNDER_INQUIRY` or `CORRECTED` it held, which is likewise terminal. `unpublished_at` is stamped from the logical clock, `editors_note_text` is stored on the story, `risk_index_actual` is recomputed, an audit event of type `STORY_UNPUBLISHED` is appended, and the story's `version` advances by one.

Stories can be read individually — the read exposes both state dimensions, both risk indices and the correction counters — or listed with filters on `newsroom_id`, `lead_journalist_id`, `publication_status`, `standards_status` and `risk_tier`.

### 3.6. Correction Intake, Investigation and Adjudication

Complaints arrive from three directions, and the desk logs all of them the same way. A `PublicEditor` or `StandardsEditor` opens a correction request against a story by naming the `story_id`, a `submitter_type` of `READER`, `SUBJECT` or `INTERNAL`, a `submitter_email` containing an `@` character as the reply-to address for the response obligation, the complaint itself as `claim_text` of 1 to 4000 characters, a `claimed_error_category` of `FACTUAL`, `QUOTE`, `NUMERIC`, `IDENTIFICATION` or `CONTEXT` as the complainant characterises it, a `reader_reported_reach` giving the audience reach the submitter believes the error had, which defaults to 0 and must not be negative, and a boolean `subject_named` recording whether a named individual is implicated, defaulting to false.

Intake is admissible while the story's `standards_status` is `CLEAN` or `CORRECTED`, and in both cases it drives that dimension to `UNDER_INQUIRY`. An intake attempt against a story whose `standards_status` is `UNDER_INQUIRY` or `RETRACTED` is refused with `ERR_INVALID_STATE`. The `CORRECTED → UNDER_INQUIRY` edge is the re-entry that makes the standards dimension cyclic where the publication dimension is not: a story that has already been corrected once returns to inquiry the moment a fresh complaint lands. Intake also increments the story's `open_correction_request_count` and advances the story's `version` by one. The request itself is created in `status` `INTAKE`.

**Grading the complaint.** Severity is graded by one arithmetic, run twice on the same row from two different sets of inputs. The arithmetic is this. Start from the error category's weight: `IDENTIFICATION` is worth 8 points, `FACTUAL` 6, `QUOTE` 5, `NUMERIC` 4 and `CONTEXT` 3. Add 4 points when the subject flag is set and nothing when it is not. Add a reach component: 6 points when the reach is 100,000 or more, otherwise 4 points when it is 10,000 or more, otherwise 2 points when it is 1,000 or more, otherwise nothing. Those three numbers added together form the **raw** figure.

The band is then read off the raw figure and off nothing else: `SEVERE` when raw is 16 or more, `MAJOR` when raw is 11 or more but below 16, `MINOR` when raw is 6 or more but below 11, and `TRIVIAL` below 6. Only then is the stored score produced, by adding a placement surcharge determined by that band — nothing for `TRIVIAL`, 1 point for `MINOR`, 2 points for `MAJOR`, 3 points for `SEVERE`. The order is what breaks the apparent circularity, and it is normative: the band comes from the raw figure, the surcharge comes from the band, and the band is **never** re-derived from the final score. A raw figure of 15 bands as `MAJOR` and stores a score of 17; the fact that 17 exceeds the `SEVERE` edge of 16 does not promote it. All of this is integer arithmetic and nothing is rounded.

The first run happens once, at intake, from the complainant's own account: the category is `claimed_error_category`, the reach is `reader_reported_reach`, and the subject flag is set exactly when `submitter_type` is `SUBJECT`. It writes `provisional_severity_score` and `provisional_severity_band`. The second run happens at adjudication, from the desk's verified account: the category is `adjudicated_error_category`, the reach is `verified_reach`, and the subject flag is the request's own `subject_named` field. It writes `adjudicated_severity_score` and `adjudicated_severity_band`, both of which are null until then. The same row therefore ends up carrying two bands that routinely disagree, and only the adjudicated one drives notice placement, the severe-correction counter and the newsroom's posture.

**The response deadline.** At intake, and only at intake, the desk pins the deadline it must answer by. Take the owning newsroom's `correction_response_sla_hours` as it stands at that moment and scale it by a factor read from the *provisional* band: 1.0 for `TRIVIAL`, 1.0 for `MINOR`, 0.5 for `MAJOR` and 0.25 for `SEVERE` — the graver the apparent error, the shorter the fuse. Round that product up to the next whole hour. Then apply the submitter bump: subtract 12 hours when `submitter_type` is `SUBJECT`, add nothing for `READER`, and add 24 hours for `INTERNAL`, on the reasoning that a wronged subject waits least and an internal note waits most. Finally take whichever is larger, the resulting figure or a floor of 4 hours. The rounding-up step is applied to the product *before* the submitter bump and *before* the 4-hour floor. The result, a whole number of hours, is added to the logical clock's current reading to give `response_due_at`. The deadline is pinned once and never recomputed, so a band that changes at adjudication never moves it.

`breach_flag` is evaluated on read against the current logical clock: it is true when the clock now reads strictly later than `response_due_at` **and** the request's `status` is `INTAKE`, `INVESTIGATING` or `AWAITING_SUBJECT`. It is false for every request in `ADJUDICATED`, `RESOLVED` or `DISMISSED`, however late that request ran — once the desk has answered, the clock stops mattering. Moving the logical clock, as §2.5 notes, re-evaluates the flag for every request not yet `RESOLVED` or `DISMISSED`.

**Working the request.** A `PublicEditor` or `StandardsEditor` opens the investigation, taking the request `INTAKE → INVESTIGATING` and optionally recording an `assigned_note`; the request's `version` advances by one. Attempting this from any state other than `INTAKE` is refused with `ERR_INVALID_STATE`. Where the complaint concerns a named person, a `PublicEditor` — and only a `PublicEditor` — records the outreach to that person, naming the `outreach_channel` used and optionally an `outreach_note`, which takes the request `INVESTIGATING → AWAITING_SUBJECT` and advances its `version` by one. Outreach is only available from `INVESTIGATING`, and an attempt elsewhere is refused with `ERR_INVALID_STATE`. This stage is optional: a request may be adjudicated directly from `INVESTIGATING` without ever waiting on a subject.

**Adjudication.** A `StandardsEditor` or `ExecutiveEditor` decides the request, supplying the `outcome_type` — one of `CORRECTION`, `CLARIFICATION`, `UPDATE`, `EDITORS_NOTE` or `NO_ACTION` — together with the `adjudicated_error_category` the desk actually found, the `verified_reach` the desk actually measured, and, where a notice is to be published, the `notice_text` that will carry it. The request must be `INVESTIGATING` or `AWAITING_SUBJECT`, and an attempt from `INTAKE`, `ADJUDICATED`, `RESOLVED` or `DISMISSED` is refused with `ERR_CORRECTION_NOT_INVESTIGATED`. The adjudicator must not be the story's lead journalist (§2.10). `notice_text` is required whenever `outcome_type` is `CORRECTION`, `CLARIFICATION`, `UPDATE` or `EDITORS_NOTE`, and must be absent when it is `NO_ACTION`; either mistake is refused with `ERR_NOTICE_TEXT_REQUIRED`.

Where a notice is published, `placement` is derived from the outcome and the adjudicated band together. An `UPDATE` is placed `INLINE`. A `CLARIFICATION` is placed at the `END_OF_STORY`. An `EDITORS_NOTE` is placed at the `TOP_OF_STORY`. A `CORRECTION` is placed at the `TOP_OF_STORY` when its adjudicated band is `MAJOR` or `SEVERE`, and at the `END_OF_STORY` when that band is `TRIVIAL` or `MINOR`. For `NO_ACTION`, `placement` is null. It is also null for the whole time the request sits in `INTAKE`, `INVESTIGATING` or `AWAITING_SUBJECT`, because there is no adjudicated band to read it from yet.

The two adjudication branches carry deliberately different weight. When `outcome_type` is anything other than `NO_ACTION`, the request moves to `ADJUDICATED`; `adjudicated_severity_score`, `adjudicated_severity_band` and `placement` are computed; the story's `standards_status` becomes `CORRECTED`; when the adjudicated band is `MAJOR` or `SEVERE` the story's `severe_correction_count` is incremented and its `risk_index_actual` recomputed; because that counter moved, the newsroom's `open_high_severity_count` is re-derived and `standards_posture` follows, escalating to `HEIGHTENED` at the threshold or `LOCKDOWN` at twice the threshold and emitting a `POSTURE_CHANGED` audit event whenever the value actually changes; an audit event of type `CORRECTION_ADJUDICATED` is appended; and the story's `version` advances by one.

When `outcome_type` is `NO_ACTION`, the branch is strictly smaller. The request moves to `DISMISSED` instead of `ADJUDICATED`, `placement` is null and `notice_text` stays null, the story's `open_correction_request_count` is decremented, and the story's `version` advances by one. There is no notice, no increment to `severe_correction_count`, and no posture cascade. The story returns to `standards_status` `CLEAN` precisely when this dismissal was the last open complaint against it — that is, when `open_correction_request_count` was 1 before the decrement and so reaches 0 — and when its `severe_correction_count` is 0. If either condition fails, the story stays `UNDER_INQUIRY`.

**Publishing the notice.** A `PublicEditor`, `StandardsEditor` or `ExecutiveEditor` closes out an `ADJUDICATED` request, optionally recording a `resolution_note`, which takes it `ADJUDICATED → RESOLVED`. Resolving from any other state is refused with `ERR_INVALID_STATE`. Both `notice_published_at` and `resolved_at` are stamped from the logical clock, the story's `open_correction_request_count` is decremented and its `version` advances by one, an audit event of type `CORRECTION_RESOLVED` is appended, and — because the request has left `ADJUDICATED` and therefore left the high-severity pool described in §2.9 — the newsroom's `open_high_severity_count` is re-derived and `standards_posture` may fall back to `OPEN`. Publishing the notice is what lets the desk breathe again.

A story's correction requests can be listed with filters on `status` and `submitter_type`, and any single request can be read on its own with its deadline and breach flag.

### 3.7. Plagiarism, Fabrication and the Disciplinary Ledger

Allegations against a journalist are handled through a staged investigation that a `StandardsEditor` or `ExecutiveEditor` opens by naming the subject in `journalist_id`, the `allegation_type` — `PLAGIARISM`, `FABRICATION` or `UNDISCLOSED_COI` — a `severity` of `MINOR`, `SERIOUS` or `EGREGIOUS` assessed by the desk and fixed at opening, and an `allegation_summary` of 1 to 4000 characters. Where the allegation arose from a specific piece, the optional `story_id` names it; it defaults to null, because not every conflict allegation attaches to a story. The investigation opens in `status` `OPENED` with `penalty_points` 0 and `disclosure_obligation` `NONE`, snapshots `prior_sustained_count`, and stamps `opened_by_user_id` from the acting `X-User-ID` together with `opened_at` from the logical clock. Because a newly opened serious or egregious inquiry is itself a high-severity matter, opening one re-derives the newsroom's `open_high_severity_count` and `standards_posture`.

The case then walks forward one stage at a time. A `StandardsEditor` or `ExecutiveEditor` advances it, optionally recording an `advance_note`, taking `OPENED → EVIDENCE_REVIEW` and then `EVIDENCE_REVIEW → RESPONSE_PENDING`, each advance incrementing the investigation's `version` by one. Advancing a case that has already been decided has no declared transition and is refused with `ERR_INVALID_STATE`.

**Deciding.** From `RESPONSE_PENDING`, a `StandardsEditor` or `ExecutiveEditor` records the finding by supplying a `disposition` of `SUSTAINED` or `UNFOUNDED` and optionally a `decision_note`. The decider may be neither the subject nor the editor who opened the case (§2.10). Both dispositions stamp `decided_by_user_id` and `decided_at` and re-derive the newsroom's `open_high_severity_count` and `standards_posture`, since the case has left the open pool either way. Beyond that the branches diverge sharply.

An `UNFOUNDED` finding takes the case to its terminal `UNFOUNDED` state and does almost nothing else: `penalty_points` stays at 0, `disclosure_obligation` stays at `NONE`, the journalist's ledger is not written, no suspension cascade runs, and no `INVESTIGATION_SUSTAINED` audit event is emitted.

A `SUSTAINED` finding takes the case to `SUSTAINED` and assesses points. First the desk counts how many of this journalist's other investigations were already `SUSTAINED` with a `decided_at` strictly earlier than the logical clock's current reading, ordering by `decided_at` ascending with `created_at` ascending as the tie-break; that count is stored on the case as `prior_sustained_count`. The case's own `penalty_points` are then the severity's base — 2 points for `MINOR`, 5 for `SERIOUS`, 9 for `EGREGIOUS` — plus a 3-point surcharge when `allegation_type` is `FABRICATION`, plus a 2-point repeat surcharge when `prior_sustained_count` is 1 or more. Because the prior count is evaluated against the clock at decision time, processing two allegations in the opposite order yields different per-case points for the same two facts; the ordering is therefore part of the specification, not an implementation detail.

The journalist's own `penalty_points` figure is then always recomputed as the full sum of `penalty_points` over every investigation of that journalist whose `status` is `SUSTAINED` — never as a delta applied to a stored total. Cases in `OPENED`, `EVIDENCE_REVIEW`, `RESPONSE_PENDING`, `UNFOUNDED` or `OVERTURNED` contribute zero. The system guarantees that a journalist's `penalty_points` equals that sum at all times.

The sustained finding also fixes the transparency duty it implies, recorded in `disclosure_obligation`. A sustained `FABRICATION` at `EGREGIOUS` severity carries `RETRACTION_REVIEW`. A sustained `FABRICATION` at `MINOR` or `SERIOUS` severity carries `CORRECTION`. A sustained `PLAGIARISM` or `UNDISCLOSED_COI`, at any severity, carries `EDITORS_NOTE`. In every other situation — including a case that has been overturned — the obligation is `NONE`.

**Suspension, and what it drags with it.** When the recomputation leaves a journalist's `penalty_points` at 12 or more, their `employment_status` moves `ACTIVE → SUSPENDED` and their `version` advances by one. Suspension is not a flag; it is a cascade with four arms. Every outside-activity request of that journalist whose `status` is `APPROVED` moves `APPROVED → REVOKED` with `revocation_reason` set to the string `JOURNALIST_SUSPENDED`. Every story led by that journalist whose `publication_status` is `IN_REVIEW` returns to `DRAFT`, each with its `version` advanced by one. Every non-terminal review round of those stories — any round in `SUBMITTED`, `LEGAL_CLEARED`, `STANDARDS_CLEARED` or `CHANGES_REQUESTED` — moves to `BLOCKED`. And because those rounds became `BLOCKED`, each of their `SCHEDULED` reviewer bookings becomes `CANCELLED`, with each affected reviewer's `reserved_minutes` re-aggregated, `available_minutes` following and `version` incremented, exactly as §3.4 describes. The audit trail records an `INVESTIGATION_SUSTAINED` event plus one `ACTIVITY_REVOKED` event for each revoked outside activity.

**Appeals.** A sustained finding may be appealed, and only an `ExecutiveEditor` hears it. The appeal supplies an `appeal_outcome` of `UPHELD` or `OVERTURNED` and optionally an `appeal_note`. The investigation must be `SUSTAINED`, or the appeal is refused with `ERR_APPEAL_NOT_ALLOWED`; and the hearer may be neither the subject nor the editor who decided the case (§2.10). Either outcome re-derives the newsroom's `open_high_severity_count` and `standards_posture`.

An `UPHELD` outcome records `appeal_outcome` as `UPHELD` and leaves everything else exactly as it stood: the case remains `SUSTAINED`, its `penalty_points` and `disclosure_obligation` are untouched, and the journalist's `employment_status` does not move. An `OVERTURNED` outcome is the compensating action for the sustained decision. It takes the case `SUSTAINED → OVERTURNED`, which is terminal, records `appeal_outcome` as `OVERTURNED`, resets the case's own `penalty_points` to 0 and its `disclosure_obligation` to `NONE`, and re-runs the journalist's ledger as the sum over their remaining `SUSTAINED` investigations. If that sum falls below 12, the journalist's `employment_status` returns `SUSPENDED → ACTIVE` with their `version` advanced by one. An `INVESTIGATION_OVERTURNED` audit event is appended. What the overturn does **not** do is undo the cascade: revoked outside activities stay `REVOKED` and blocked review rounds stay `BLOCKED`. Only the points ledger and `employment_status` are restored.

Investigations can be read individually, with their points and disclosure obligation, or listed with filters on `journalist_id`, `story_id`, `status` and `allegation_type`.

### 3.8. Conflicts, Outside Work and Standards Training

**Disclosing a conflict.** A `Reporter` files their own conflict-of-interest disclosure, naming themselves in `journalist_id`, a `disclosure_type` of `FINANCIAL`, `FAMILIAL`, `POLITICAL` or `EMPLOYMENT`, the `subject_entity_name` of the organisation or person the conflict concerns in 1 to 160 characters, and a `description` of the conflict in 1 to 4000 characters. It is created in `status` `SUBMITTED` with `restricted_beats` as an empty array.

A `StandardsEditor` or `ExecutiveEditor` then reviews it, supplying a `review_outcome` of `ACKNOWLEDGE`, `IMPOSE_RESTRICTION` or `REJECT`, and optionally a `restricted_beats` array. Review is only available from `SUBMITTED`; a second review of the same disclosure is refused with `ERR_INVALID_STATE`. All three outcomes stamp `reviewed_by_user_id` from the acting `X-User-ID` and `reviewed_at` from the logical clock, and all three are terminal. `ACKNOWLEDGE` moves the disclosure `SUBMITTED → ACKNOWLEDGED` and leaves `restricted_beats` empty. `REJECT` moves it `SUBMITTED → REJECTED`, likewise with no restriction recorded. `IMPOSE_RESTRICTION` moves it `SUBMITTED → RESTRICTION_IMPOSED` and requires the `restricted_beats` array to be present and non-empty; the supplied beat labels are stored on the disclosure, and the journalist's own `restricted_beats` field is then recomputed as the union of `restricted_beats` over all of that journalist's disclosures in `RESTRICTION_IMPOSED`.

**Asking for outside work.** A `Reporter` requests approval for outside activity in their own name, supplying an `activity_type` of `SPEAKING`, `BOOK`, `CONSULTING` or `BOARD_SERVICE`, a required boolean `compensated` recording whether the work is paid, an inclusive `starts_on` and an exclusive `ends_on` — both ISO 8601 UTC instants, with `ends_on` required to be strictly after `starts_on` on pain of `ERR_INVALID_INTERVAL` — a `related_beat` label of 1 to 80 characters naming the coverage area the activity touches, and the `host_organization` of 1 to 160 characters. The request is created in `status` `REQUESTED`.

A `StandardsEditor` or `ExecutiveEditor` decides it with a `decision` of `APPROVE` or `DENY` and an optional `decision_note`, taking the request `REQUESTED → APPROVED` or `REQUESTED → DENIED`; a decision against a request that is no longer `REQUESTED` is refused with `ERR_INVALID_STATE`. Both branches store `decided_by_user_id` and `decided_at`, but only approval is gated. Approval requires, in order, that the journalist has no conflict disclosure still sitting in `SUBMITTED` — an unreviewed disclosure blocks all outside work with `ERR_COI_DISCLOSURE_PENDING`; that the request's `related_beat` is not a member of the journalist's `restricted_beats`, or the approval is refused with `ERR_ACTIVITY_BEAT_RESTRICTED`; and that the requested window does not overlap any already-`APPROVED` activity of the same journalist. That window is half-open, running from `starts_on` inclusive up to but excluding `ends_on`: an overlap exists when the new `starts_on` falls strictly before the other request's `ends_on` and the other request's `starts_on` falls strictly before the new `ends_on`. Touching endpoints are therefore admissible — a new engagement beginning at the exact instant an approved one ends is accepted — while any true intersection is refused with `ERR_OUTSIDE_ACTIVITY_OVERLAP`. A denial performs none of these three checks. An approved activity may later be swept away by the suspension cascade of §3.7, which moves it `APPROVED → REVOKED` and writes `revocation_reason`.

**Filing training.** Standards training is filed as a record per module. A `Reporter`, `StandardsEditor` or `ExecutiveEditor` files one by naming the `journalist_id` who completed it and the `module_code` completed — one of `SOURCING`, `CORRECTIONS`, `LEGAL_RISK`, `ANONYMOUS_SOURCING` or `PLAGIARISM` — with an optional `case_study_reference` naming the case study reviewed during the module. The server stamps `completed_at` from the logical clock; the record is append-only and is never updated afterwards. A journalist may file at most one record per `module_code`, and a duplicate is refused with `ERR_DUPLICATE_TRAINING_MODULE`.

Filing a record moves two derived figures. The journalist's `completed_required_module_count` is recomputed as the number of **distinct** `module_code` values across their training records that also appear in their newsroom's `required_module_codes`; a module the journalist completed that the newsroom does not require counts for nothing. `training_current` is then true exactly when `completed_required_module_count` equals the number of codes in `required_module_codes`, and false otherwise. This is the flag that gates publication of a `HIGH` risk-tier story, per §3.5.

**The desk-wide compliance index.** The newsroom's `training_compliance_index` is recomputed on newsroom creation, on journalist creation and on every training filing, and it is also read back through the newsroom's standards summary. The cohort is every journalist of the newsroom, taken in `created_at` ascending order, and it includes journalists whose `employment_status` is `SUSPENDED` — a suspended journalist still owes their training. When the cohort is empty the index is 0.00 and no division is performed.

Otherwise the index is produced in two rounding stages, and **the order is normative**. First, for each journalist in the cohort, divide their `completed_required_module_count` by the number of codes in `required_module_codes` and round that individual ratio half up to 2 decimal places. Second, add those already-rounded ratios together, divide by the number of journalists in the cohort, multiply by 100, and round half up to 2 decimal places again. The alternative order — summing the unrounded ratios and rounding only once at the end — produces a different answer for the same data, so it is not permitted: with three required modules and a three-journalist cohort whose completed counts are 1, 1 and 2, the pinned order yields 44.33 while the single-rounding order would yield 44.44. Implementations must produce 44.33.

A journalist can be read on their own to inspect `penalty_points`, `training_current` and `restricted_beats`. Their disclosures can be listed with a filter on `status`, their outside-activity requests with filters on `status` and `activity_type`, and their training records with a filter on `module_code`; any single disclosure or activity request can also be read directly.

## 4. Endpoint Definitions

Every endpoint is mounted beneath the `/standards-desk` prefix. Endpoints that bring a new resource into existence answer with HTTP 201 and the created resource in `data`; endpoints that transition, decide or otherwise modify an existing resource answer with HTTP 200 and the updated resource in `data`; read endpoints answer with HTTP 200. Refusals carry the status codes catalogued in §5. The table below is a routing index only — the request payloads, the conditions each operation enforces and the downstream effects it produces are specified in §2 and §3, and must be reconstructed from there.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/standards-desk/newsrooms` | Register a newsroom standards desk. Bootstrap endpoint, exempt from entity-backed identity binding. | ExecutiveEditor |
| POST | `/standards-desk/journalists` | Add a journalist to a newsroom. Bootstrap endpoint, exempt from entity-backed identity binding. | ExecutiveEditor |
| POST | `/standards-desk/reviewers` | Register a legal or standards reviewer with a weekly review-minute capacity. | ExecutiveEditor |
| POST | `/standards-desk/stories` | Open a story file owned by the acting reporter. | Reporter |
| POST | `/standards-desk/stories/{id}/publish` | Publish a cleared story. | ExecutiveEditor |
| POST | `/standards-desk/stories/{id}/unpublish` | Remove a published story from the site and attach the mandatory editor's note. | ExecutiveEditor |
| POST | `/standards-desk/anonymous-source-approvals` | Request approval to use an anonymous source on a story. | Reporter |
| POST | `/standards-desk/anonymous-source-approvals/{id}/decide` | Approve or deny an anonymous-source request. | StandardsEditor, ExecutiveEditor |
| POST | `/standards-desk/anonymous-source-approvals/{id}/revoke` | Revoke an approved anonymous source after the fact. | StandardsEditor, ExecutiveEditor |
| POST | `/standards-desk/pre-publication-reviews` | Submit a story for pre-publication legal and standards review. | Reporter |
| POST | `/standards-desk/pre-publication-reviews/{id}/legal-verdict` | Record the legal verdict with the defamation and privacy analysis for the open round. | LegalCounsel |
| POST | `/standards-desk/pre-publication-reviews/{id}/standards-verdict` | Record the standards verdict for the open round. | StandardsEditor, ExecutiveEditor |
| POST | `/standards-desk/pre-publication-reviews/{id}/clear` | Close the review round and clear the story for publication. | StandardsEditor, ExecutiveEditor |
| POST | `/standards-desk/pre-publication-reviews/{id}/resubmit` | Resubmit a revised story for a further review round. | Reporter |
| POST | `/standards-desk/review-assignments` | Book a reviewer slot against an open review round. | LegalCounsel, StandardsEditor |
| POST | `/standards-desk/review-assignments/{id}/cancel` | Release a scheduled reviewer slot. | LegalCounsel, StandardsEditor, ExecutiveEditor |
| POST | `/standards-desk/correction-requests` | Log a correction request from a reader, a story subject or an internal desk review. | PublicEditor, StandardsEditor |
| POST | `/standards-desk/correction-requests/{id}/start-investigation` | Open the investigation into a logged correction request. | PublicEditor, StandardsEditor |
| POST | `/standards-desk/correction-requests/{id}/subject-outreach` | Record the outreach to the story subject and pause for their response. | PublicEditor |
| POST | `/standards-desk/correction-requests/{id}/adjudicate` | Decide the correction: adjudicated category, verified reach, outcome type and notice placement. | StandardsEditor, ExecutiveEditor |
| POST | `/standards-desk/correction-requests/{id}/resolve` | Publish the notice and close out the adjudicated correction. | PublicEditor, StandardsEditor, ExecutiveEditor |
| POST | `/standards-desk/misconduct-investigations` | Open a plagiarism, fabrication or undisclosed-conflict investigation into a journalist. | StandardsEditor, ExecutiveEditor |
| POST | `/standards-desk/misconduct-investigations/{id}/advance` | Move the investigation to the next pre-decision stage. | StandardsEditor, ExecutiveEditor |
| POST | `/standards-desk/misconduct-investigations/{id}/decide` | Sustain or dismiss the allegation. | StandardsEditor, ExecutiveEditor |
| POST | `/standards-desk/misconduct-investigations/{id}/appeal` | Hear the journalist's appeal against a sustained finding. | ExecutiveEditor |
| POST | `/standards-desk/conflict-disclosures` | File a conflict-of-interest disclosure. | Reporter |
| POST | `/standards-desk/conflict-disclosures/{id}/review` | Acknowledge, restrict or reject a filed disclosure. | StandardsEditor, ExecutiveEditor |
| POST | `/standards-desk/outside-activity-requests` | Request approval for a speaking engagement, book, consulting arrangement or board seat. | Reporter |
| POST | `/standards-desk/outside-activity-requests/{id}/decide` | Approve or deny an outside-activity request. | StandardsEditor, ExecutiveEditor |
| POST | `/standards-desk/training-records` | File a completed standards training module with its case-study review reference. | Reporter, StandardsEditor, ExecutiveEditor |
| POST | `/standards-desk/_clock/set_current_utc` | Set the server's logical UTC clock. | ExecutiveEditor |
| GET | `/standards-desk/newsrooms/{id}` | Read a newsroom with its derived posture, open high-severity count and training compliance index. | Reporter, StandardsEditor, LegalCounsel, ExecutiveEditor, PublicEditor |
| GET | `/standards-desk/newsrooms/{id}/standards-summary` | Computed read of the desk's standing at the current logical instant. | StandardsEditor, ExecutiveEditor, PublicEditor |
| GET | `/standards-desk/newsrooms/{id}/journalists` | List the newsroom's journalists. | Reporter, StandardsEditor, LegalCounsel, ExecutiveEditor, PublicEditor |
| GET | `/standards-desk/newsrooms/{id}/reviewers` | List the newsroom's legal and standards reviewers with their minute ledgers. | StandardsEditor, LegalCounsel, ExecutiveEditor |
| GET | `/standards-desk/newsrooms/{id}/audit-events` | Transparency log: the newsroom's immutable standards audit trail in occurrence order. | StandardsEditor, ExecutiveEditor, PublicEditor |
| GET | `/standards-desk/journalists/{id}` | Read a journalist with penalty points, training currency and restricted beats. | Reporter, StandardsEditor, LegalCounsel, ExecutiveEditor, PublicEditor |
| GET | `/standards-desk/journalists/{id}/conflict-disclosures` | List the journalist's conflict-of-interest disclosures. | Reporter, StandardsEditor, ExecutiveEditor, PublicEditor |
| GET | `/standards-desk/journalists/{id}/outside-activity-requests` | List the journalist's outside-activity requests. | Reporter, StandardsEditor, ExecutiveEditor, PublicEditor |
| GET | `/standards-desk/journalists/{id}/training-records` | List the journalist's completed standards training modules. | Reporter, StandardsEditor, ExecutiveEditor |
| GET | `/standards-desk/reviewers/{id}` | Read a reviewer with their reserved and available minutes. | StandardsEditor, LegalCounsel, ExecutiveEditor |
| GET | `/standards-desk/stories/{id}` | Read a story with both state dimensions, both risk indices and the correction counters. | Reporter, StandardsEditor, LegalCounsel, ExecutiveEditor, PublicEditor |
| GET | `/standards-desk/stories` | List stories, filterable by newsroom, lead journalist, either state dimension or risk tier. | Reporter, StandardsEditor, LegalCounsel, ExecutiveEditor, PublicEditor |
| GET | `/standards-desk/stories/{id}/anonymous-source-approvals` | List the story's anonymous-source approval records. | Reporter, StandardsEditor, ExecutiveEditor |
| GET | `/standards-desk/stories/{id}/pre-publication-reviews` | List the story's pre-publication review rounds. | Reporter, StandardsEditor, LegalCounsel, ExecutiveEditor |
| GET | `/standards-desk/stories/{id}/correction-requests` | List the story's correction requests with their provisional and adjudicated severity. | Reporter, StandardsEditor, ExecutiveEditor, PublicEditor |
| GET | `/standards-desk/anonymous-source-approvals/{id}` | Read an anonymous-source approval record. | Reporter, StandardsEditor, ExecutiveEditor |
| GET | `/standards-desk/pre-publication-reviews/{id}` | Read a pre-publication review round with its legal and standards findings. | Reporter, StandardsEditor, LegalCounsel, ExecutiveEditor |
| GET | `/standards-desk/review-assignments/{id}` | Read a reviewer slot booking. | StandardsEditor, LegalCounsel, ExecutiveEditor |
| GET | `/standards-desk/review-assignments` | List reviewer slot bookings, filterable by review round, reviewer or status. | StandardsEditor, LegalCounsel, ExecutiveEditor |
| GET | `/standards-desk/correction-requests/{id}` | Read a correction request with its response deadline and breach flag. | Reporter, StandardsEditor, ExecutiveEditor, PublicEditor |
| GET | `/standards-desk/misconduct-investigations/{id}` | Read a misconduct investigation with its penalty points and disclosure obligation. | StandardsEditor, ExecutiveEditor |
| GET | `/standards-desk/misconduct-investigations` | List misconduct investigations, filterable by journalist, story or status. | StandardsEditor, ExecutiveEditor |
| GET | `/standards-desk/conflict-disclosures/{id}` | Read a conflict-of-interest disclosure. | Reporter, StandardsEditor, ExecutiveEditor, PublicEditor |
| GET | `/standards-desk/outside-activity-requests/{id}` | Read an outside-activity request. | Reporter, StandardsEditor, ExecutiveEditor, PublicEditor |

## 5. Error Code Catalogue

The table lists every error identifier the API emits together with its HTTP status code. The conditions that trigger each one are stated in the §2 principles and §3 workflows above; they are deliberately not repeated here.

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_HEIGHTENED_REQUIRES_EXEC` | 403 |
| `ERR_NEWSROOM_NOT_FOUND` | 404 |
| `ERR_JOURNALIST_NOT_FOUND` | 404 |
| `ERR_REVIEWER_NOT_FOUND` | 404 |
| `ERR_STORY_NOT_FOUND` | 404 |
| `ERR_SOURCE_APPROVAL_NOT_FOUND` | 404 |
| `ERR_REVIEW_NOT_FOUND` | 404 |
| `ERR_ASSIGNMENT_NOT_FOUND` | 404 |
| `ERR_CORRECTION_REQUEST_NOT_FOUND` | 404 |
| `ERR_INVESTIGATION_NOT_FOUND` | 404 |
| `ERR_DISCLOSURE_NOT_FOUND` | 404 |
| `ERR_ACTIVITY_REQUEST_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_INTERVAL` | 400 |
| `ERR_STALE_STORY_VERSION` | 412 |
| `ERR_STALE_REVIEWER_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STORY_NOT_CLEARED` | 409 |
| `ERR_STORY_NOT_PUBLISHED` | 409 |
| `ERR_REVIEW_ROUND_NOT_OPEN` | 409 |
| `ERR_LEGAL_VERDICT_REQUIRED` | 409 |
| `ERR_SOURCE_ALREADY_DECIDED` | 409 |
| `ERR_CORRECTION_NOT_INVESTIGATED` | 409 |
| `ERR_APPEAL_NOT_ALLOWED` | 409 |
| `ERR_POSTURE_LOCKDOWN` | 409 |
| `ERR_JOURNALIST_SUSPENDED` | 409 |
| `ERR_OUTSIDE_ACTIVITY_OVERLAP` | 409 |
| `ERR_REVIEWER_SLOT_CONFLICT` | 409 |
| `ERR_DUPLICATE_TRAINING_MODULE` | 409 |
| `ERR_DUPLICATE_SOURCE_ALIAS` | 409 |
| `ERR_INSUFFICIENT_SOURCE_DOCUMENTATION` | 422 |
| `ERR_INSUFFICIENT_CORROBORATION` | 422 |
| `ERR_TRAINING_NOT_CURRENT` | 422 |
| `ERR_SOURCE_NOT_APPROVED` | 422 |
| `ERR_CROSS_NEWSROOM_REFERENCE` | 422 |
| `ERR_REVIEWER_DISCIPLINE_MISMATCH` | 422 |
| `ERR_COI_DISCLOSURE_PENDING` | 422 |
| `ERR_ACTIVITY_BEAT_RESTRICTED` | 422 |
| `ERR_UNPUBLISH_NOT_JUSTIFIED` | 422 |
| `ERR_NOTICE_TEXT_REQUIRED` | 422 |
| `ERR_REVIEWER_CAPACITY_EXCEEDED` | 422 |
