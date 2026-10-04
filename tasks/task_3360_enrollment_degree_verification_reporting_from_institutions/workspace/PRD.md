# Enrollment Verification Clearinghouse API — Product Requirements Document

## 1. Introduction

Colleges and universities report the enrollment status and conferred credentials of their students to a central clearinghouse, and that clearinghouse answers the outside world's questions about those records. Loan servicers depend on the clearinghouse's enrollment determinations to drive deferment and repayment programs; employers and background screeners purchase degree and enrollment verifications against prepaid balances; learners order their own transcripts for electronic delivery; and institutions and states consume aggregate outcome research drawn from the same reporting base. This document specifies the API for that clearinghouse: institutional participation agreements, the required reporting calendar with its on-time and grace windows, the enrollment status determination rules for full-time, half-time, and withdrawn students, the verification product catalog with its fee structure, and the privacy compliance regime that governs every disclosure.

Two commitments shape every workflow below. First, accuracy is repairable but never silent: when an institution's file misstates a student's status, a formal correction cycle — filed by one registrar officer and decided by another — supersedes the erroneous row and re-feeds the downstream loan-servicing notifications. Second, privacy is a gate rather than an afterthought: directory-information blocks and research opt-outs placed by the learner are evaluated when a verification is requested and again when it is fulfilled, and a blocked or unfulfillable release always returns the requester's money. All time-driven behavior — agreement expiry, period close, quote expiry, notification dispatch — is evaluated against a logical clock maintained by the server (§2.4), never against wall-clock time.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contract: authentication, response envelopes, pagination, the logical clock, common resource properties, concurrency control, numeric precision, reference resolution, and the state-transition discipline on which the business workflows of §3 rely.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting party, and `X-User-Role`, naming the capacity in which they act. The system recognizes exactly seven roles: `ClearinghouseOps`, `RegistrarSubmitter`, `RegistrarCertifier`, `Requester`, `Learner`, `Servicer`, and `ResearchAnalyst`.

A request missing either header, or whose `X-User-ID` fails to resolve to an existing entity for an entity-backed role, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not listed among the roles authorized for the target endpoint, or that fails an ownership check, is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The meaning of `X-User-ID` depends on the role:

- When `X-User-Role` is `RegistrarSubmitter`, `X-User-ID` is the `id` of the acting `InstitutionUser` whose registrar-office `role` is `SUBMITTER`. Ownership and tenancy checks on any resource that references an institution compare the acting user's `institution_id` to the institution being read or written.
- When `X-User-Role` is `RegistrarCertifier`, `X-User-ID` is likewise the `id` of an acting `InstitutionUser`, this time one whose `role` is `CERTIFIER`, with the same tenancy comparison.
- When `X-User-Role` is `Requester`, `X-User-ID` is the `id` of the acting `Requester`. A requester reads its own account only and acts only on its own verification requests: any request whose `requester_id` does not equal `X-User-ID` is out of scope and is rejected with `ERR_UNAUTHORIZED`.
- When `X-User-Role` is `Learner`, `X-User-ID` is the `id` of the acting `StudentRecord`. The learner acts only on their own student record, whether that record is identified in the path or in the request body's `student_id`.
- When `X-User-Role` is `ClearinghouseOps`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server never compares it against an entity `id`.
- When `X-User-Role` is `Servicer`, `X-User-ID` is an opaque identifier not tied to any persisted entity, but it is compared against the `servicer_ref` code carried on enrollment rows and copied onto ServicerNotifications — a servicer sees and acknowledges exactly the notifications addressed to its code, and no others.
- When `X-User-Role` is `ResearchAnalyst`, `X-User-ID` is an opaque identifier not tied to any persisted entity; the server records it as `created_by_analyst_id` on each ResearchDataset and scopes dataset listings to the records the caller created.

Registrar users are provisioned as InstitutionUser records carrying an `email`, a `role` of `SUBMITTER` or `CERTIFIER`, and a `status` of `ACTIVE` or `DEACTIVATED`; only `ACTIVE` users may act. The two registrar roles are deliberately segregated: submission and certification of the same institution's data are distinct capacities, and nowhere may one role perform the other's exclusive action.

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

Endpoints that return lists of resources are paginated through two query parameters. `limit` caps the number of items returned: it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` skips a number of items and defaults to 0. Unless a specific endpoint documents a different ordering in §3, list responses sort by `created_at` ascending. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. The Logical Clock and Time-Driven Processing

All time-dependent behavior is evaluated against a logical clock maintained by the server, never against wall-clock time. Before any clock operation has been called, the logical clock reads exactly 2026-09-01T00:00:00Z. A `ClearinghouseOps`-only capability advances the clock to a supplied `to_iso8601` instant; the target must be strictly later than the current logical time, and a non-forward move is rejected with `ERR_VALIDATION` (HTTP 400). The capability's response carries the new logical time as `current_utc`.

Each advance processes every due transition in a fixed, six-step order:

1. Participation agreements flip: `SCHEDULED` agreements whose window has been reached move to `ACTIVE`, and agreements whose `effective_to` has been reached move to `EXPIRED`, applying the institution cascades described in §3.1 as they go.
2. Verification-request cancellations caused by institution suspension run in `created_at` ascending order.
3. Reporting periods advance through their lifecycle, processed in `submission_due_at` ascending order with `created_at` ascending as the tie-break, computing outcomes and recomputing institutional standing at each close.
4. `QUOTED` verification requests whose `quote_expires_at` has been reached move to `EXPIRED`, in `created_at` ascending order.
5. `QUEUED` servicer notifications are dispatched to `SENT`, in `created_at` ascending order.
6. Privacy directives whose `effective_to` has been reached move to `EXPIRED`, in `created_at` ascending order.

Wherever this document describes a date-valued field, the value is interpreted as midnight UTC of that date (T00:00:00Z).

### 2.5. Common Resource Properties

Every resource in this system — Institution, ParticipationAgreement, InstitutionUser, ReportingPeriod, StudentRecord, PrivacyDirective, EnrollmentFile, EnrollmentEntry, CorrectionCase, DegreeRecord, Requester, VerificationRequest, ServicerNotification, and ResearchDataset — carries a standard set of system-managed fields:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation.
- `version` (integer): starts at 1 at creation and increments by one on every mutation of the resource, including mutations driven by cascades from operations on other resources.

### 2.6. Optimistic Concurrency Control

Exactly two write operations participate in optimistic concurrency control; endpoints not named here accept no version field.

- Placing a privacy directive on a student record requires a non-optional `expected_student_version` field carrying the student record's `version` as last observed by the client. A same-type directive create legitimately supersedes the prior `ACTIVE` directive under the privacy rules of §3.8, so the client must present the student version it based the decision on; if the record's current `version` no longer matches — because another directive create or a standing update landed in between — the request is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Uploading an enrollment file requires a non-optional `expected_reporting_period_version` field carrying the reporting period's `version` as last observed by the client. An upload legitimately supersedes any prior uncertified file for the period and increments the period's `upload_count` — hence its `version` — so a stale token means the client's view of the period is out of date; the upload is rejected with `ERR_STALE_VERSION` (HTTP 412).

### 2.7. Numeric Precision: Money, Rates, and Dates

All monetary amounts in the system — `fee_cents`, `refund_cents`, `credit_balance_cents`, and `initial_credit_cents` — are integer cents; fractional cents do not exist. Fee arithmetic rounds half-up to integer cents at each pinned step of the quote computation (§3.7): rounding is per component, and the quoted fee is the sum of already-rounded components. `credit_hours` values are compared exactly as given, as numbers that may carry up to two decimal places. Date arithmetic for grace periods and lag windows is performed at whole-day granularity, and the comparisons that branch on a grace end are strict. Research completion rates are reported to exactly four decimal places, rounded half-up.

### 2.8. Reference Resolution and Request Evaluation Order

Every request is evaluated against an ordered cascade of checks, and the first failure wins: its error is the response. Broadly, authentication and role membership come first (§2.1), then payload well-formedness, then existence of referenced resources, then state-machine applicability, then institutional and agreement state, and finally the business, temporal, and fiscal rules of the specific workflow narrated in §3.

Payload well-formedness — required fields present, types correct, enum members valid, dates parseable — is enforced on every creation and action endpoint; a malformed payload is rejected with `ERR_VALIDATION` (HTTP 400).

Reference resolution proceeds left to right: path identifiers first, then body identifiers. Each kind of unresolved reference reports its own error — `ERR_INSTITUTION_NOT_FOUND`, `ERR_PERIOD_NOT_FOUND`, `ERR_STUDENT_NOT_FOUND`, `ERR_FILE_NOT_FOUND`, `ERR_ENTRY_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_DEGREE_NOT_FOUND`, `ERR_REQUESTER_NOT_FOUND`, `ERR_REQUEST_NOT_FOUND`, `ERR_NOTIFICATION_NOT_FOUND`, or `ERR_DATASET_NOT_FOUND`, each HTTP 404 — and the earliest unresolvable reference in that left-to-right sweep is the one reported.

Registrar writes carry an additional tenancy rule beyond role membership: the acting InstitutionUser's `institution_id` must equal the institution being written. A cross-institution write — file upload, certification, correction filing or decision, degree reporting, sealing, or revocation — is rejected with `ERR_CROSS_INSTITUTION_ACCESS` (HTTP 403).

### 2.9. State Transitions and Cascading Consistency

Every entity lifecycle in §3 is a closed state machine: transitions occur only through the triggers named there, terminal states accept no further transitions, and an action fired against a resource in the wrong state — including re-firing an action whose effect has already been applied, or acting on a resource in a terminal state — is rejected with `ERR_INVALID_STATE` (HTTP 409).

Many operations mutate more than one resource. Suspending an institution cancels its in-flight verification requests; certifying a file can supersede a previously certified file along with its entries and its undelivered notifications; applying a correction supersedes the old entry and installs a replacement. These cascades are part of each operation's contract and are enumerated where the workflow is described. Every mutation — including every cascade step — refreshes the affected resource's `updated_at` and increments its `version`.

## 3. Business Logic & Workflows

The workflows below follow the clearinghouse's operating rhythm: institutions are onboarded and bound by participation agreements, the reporting calendar opens and closes on them, enrollment files are submitted, screened, and certified, corrections repair certified data, degrees are reported and sealed, and vetted requesters buy verification against prepaid credit while learners guard their own records. State names appear as exact UPPERCASE strings, and state pairs (for example, `UPLOADED` → `CERTIFIED`) bridge each narrative to the endpoint table in §4.

### 3.1. Institutional Onboarding, Registrar Users, and Participation Agreements

A `ClearinghouseOps` operator onboards an institution by supplying its legal `name`, its federal `ope_id` — unique across institutions — and an inline `users` array whose members each carry an `email` and a registrar `role` of `SUBMITTER` or `CERTIFIER`. Creation provisions one InstitutionUser per array member, each starting `ACTIVE`, each email unique within the institution; the create response embeds the provisioned `users` array in the same order the members were supplied, and that embedded array appears on the create response only. The institution itself begins `ACTIVE`, with `suspension_reason` of `NONE` and `compliance_standing` of `COMPLIANT`.

Participation in the reporting program is contractual. An operator creates a ParticipationAgreement for an institution with an `effective_from` and an `effective_to`, interpreted together as a half-open coverage window: coverage includes `effective_from` and runs up to but not including `effective_to`. The window must not overlap any `SCHEDULED` or `ACTIVE` agreement of the same institution — adjacency, where one agreement's `effective_from` equals another's `effective_to`, is permitted — and an overlapping submission is rejected with `ERR_AGREEMENT_OVERLAP` (HTTP 409). Field-level date ordering is enforced as well: `effective_to` strictly after `effective_from`, otherwise `ERR_VALIDATION`. An agreement's initial status is computed from the current logical time: `ACTIVE` when now falls inside the window (on or after `effective_from` and before `effective_to`), and `SCHEDULED` when now is earlier than `effective_from`; `EXPIRED` is reached only through clock processing. An institution's agreements can be listed in `created_at` ascending order.

As the clock advances, a `SCHEDULED` agreement whose `effective_from` has been reached — with `effective_to` still in the future — flips to `ACTIVE`; an `ACTIVE` agreement whose `effective_to` has been reached flips to `EXPIRED`; and a `SCHEDULED` agreement whose entire window was skipped likewise becomes `EXPIRED`, with no further effect.

Suspension severs an institution's ability to certify files, seal degrees, upload new files, or sell verifications. An operator may suspend an `ACTIVE` institution directly — the request is rejected with `ERR_INVALID_STATE` against anything else: the institution becomes `SUSPENDED` with `suspension_reason` of `OPS`, its `version` increments, and the cancellation cascade runs. Every VerificationRequest targeting that institution in `QUOTED` or `PAID` status moves to `CANCELLED`, processed in `created_at` ascending order, and each `PAID` request refunds its full `fee_cents` to the requester's `credit_balance_cents`, recording the amount in the request's `refund_cents`. The same cascade fires automatically when clock processing expires an institution's last `ACTIVE` agreement and no other `ACTIVE` agreement covers the current instant: the institution flips from `ACTIVE` to `SUSPENDED` with `suspension_reason` of `AGREEMENT_LAPSE`, followed by the identical request-cancellation cascade.

Recovery mirrors the cause. An operator may reinstate a `SUSPENDED` institution only when an `ACTIVE` agreement covers the current instant — otherwise the reinstatement is rejected with `ERR_AGREEMENT_LAPSED` (HTTP 409) — and reinstatement returns the institution to `ACTIVE` with `suspension_reason` cleared to `NONE`. Separately, an institution suspended with reason `AGREEMENT_LAPSE` is reinstated automatically, again with `suspension_reason` cleared to `NONE`, the moment a `SCHEDULED` agreement flips to `ACTIVE` on clock advance or a newly created agreement is already `ACTIVE`. An institution suspended with reason `OPS` enjoys no such automatic recovery and waits for the operator.

### 3.2. The Reporting Calendar and Institutional Compliance Standing

Within a participating institution, an operator defines each reporting period with a human-readable `term_label` (for example, "Fall 2026"), a `term_start`, a `term_end`, a `submission_opens_at`, and a `submission_due_at`. From these the system derives `grace_ends_at` as fourteen days after `submission_due_at` — a two-week grace window in which late certification is still accepted — and computes the period's initial status from the current logical time.

Periods of one institution may not crowd each other. Each period occupies the closed interval from its `term_start` through its `submission_due_at`, inclusive, and a new period's `term_start` must fall strictly after every existing period's `submission_due_at` for that institution; even a same-day start collides. A colliding period is rejected with `ERR_PERIOD_OVERLAP` (HTTP 409). The field-level date rules are then applied: `term_end` strictly after `term_start`, and `submission_opens_at` no earlier than `term_start` and strictly before `submission_due_at`; violations are rejected with `ERR_VALIDATION` (HTTP 400).

A period's lifecycle is clock-driven: `SCHEDULED` before submissions open, `OPEN` once now reaches `submission_opens_at`, `GRACE` once now passes `submission_due_at`, and `CLOSED` once now passes `grace_ends_at`. Because the clock can jump, the lifecycle tolerates skipped waypoints: a period can move directly from `SCHEDULED` to `GRACE` or straight to `CLOSED`, and from `OPEN` straight to `CLOSED`, whenever the landing condition holds. Each such advance increments the period's `version`. Two computed fields round out the period: `outcome`, which begins as `NONE`, and `upload_count`, which begins at zero and increments by one on every successful enrollment-file upload for the period — the increment that drives the period `version` bumps on which upload concurrency control (§2.6) relies.

Closing a period settles its outcome. At close, the period's `outcome` becomes `ON_TIME` when a `CERTIFIED` file exists whose `certified_at` is on or before `submission_due_at`, `LATE` when the only certified files were certified after `submission_due_at`, and `DELINQUENT` when nothing was ever certified. Closing also recomputes the institution's `compliance_standing`.

Standing is a three-period memory. The recompute considers the institution's `CLOSED` periods, at most the three most recent ordered by `submission_due_at` descending with `created_at` ascending breaking ties. If any of those periods is `DELINQUENT`, the institution becomes `NON_COMPLIANT`; otherwise, if any is `LATE`, it moves to `WATCH`; otherwise — including when no period has ever closed — it stands `COMPLIANT`. Standing is recomputed at every period close and again at every file certification. A delinquency is not necessarily permanent: uploading into a `CLOSED` period is the sanctioned remedy path (§3.3), and when a file for a `DELINQUENT` period is certified late, the period's outcome flips from `DELINQUENT` to `LATE` (§3.4).

An institution's periods are listed ordered by `submission_due_at` ascending, then `created_at` ascending; its registrar users are listed in `created_at` ascending order.

### 3.3. Enrollment File Submission and Row Screening

Reporting begins when a `RegistrarSubmitter` uploads an enrollment file. The payload names the `institution_id` and the `reporting_period_id`, carries the concurrency token `expected_reporting_period_version` (§2.6), and embeds the `rows` themselves. Each row reports one student's term: `full_name` and `date_of_birth` as the identity key, the institution-scoped `student_ref`, attempted `credit_hours`, the `career_level` — `UNDERGRAD` or `GRADUATE` — that selects the threshold set, the row's `term_start` and `term_end`, an optional `withdrawal_date`, and an optional `servicer_ref`, an opaque loan-servicer code whose presence puts the row on the servicer notification feed.

Before any row is examined, the upload passes an ordered gauntlet, and the first failure wins. The submitter's institution must match the file's institution (`ERR_CROSS_INSTITUTION_ACCESS`); the payload must be well-formed (`ERR_VALIDATION`); the referenced institution and then the referenced period must exist (`ERR_INSTITUTION_NOT_FOUND`, then `ERR_PERIOD_NOT_FOUND`); the concurrency token must match the period's current `version` (`ERR_STALE_VERSION`); the institution must be `ACTIVE` (`ERR_INSTITUTION_SUSPENDED`); an `ACTIVE` agreement must cover now (`ERR_AGREEMENT_LAPSED`); and the period must not still be `SCHEDULED` — uploads are accepted while the period is `OPEN`, in `GRACE`, or `CLOSED`, with the closed period serving as the delinquency remedy path, while a `SCHEDULED` period rejects the upload with `ERR_PERIOD_NOT_OPEN` (HTTP 409).

Screening is deterministic and row-ordered. Rows are examined in payload order — the first row carries `row_index` zero — and the first occurrence of a `student_ref` wins: a later row repeating an already-seen `student_ref` is rejected with `reject_reason` `DUPLICATE_STUDENT_IN_FILE`. A row missing a required field is rejected as `MISSING_FIELD`; an unrecognized `career_level` value as `INVALID_ENUM_VALUE`; `credit_hours` below zero or above the 30-credit ceiling as `INVALID_CREDITS`; a `term_end` not strictly after its `term_start` as `INVALID_TERM_DATES`; and a `withdrawal_date` that falls before the row's `term_start` or after its `term_end` as `INVALID_WITHDRAWAL_DATE`. Clean rows become EnrollmentEntries with `entry_status` `ACCEPTED` and `reject_reason` `NONE`; failed rows are kept on the file as `REJECTED` entries carrying their reason — they are produced at screening time only and never transition afterward. The file records `row_count` (every row ever attached, including correction-created entries later), `accepted_rows`, and `rejected_rows`, and the submitting user is captured from `X-User-ID` as `submitted_by_user_id`.

Every accepted row resolves its student: the system matches on the lowercased, whitespace-trimmed `full_name` together with `date_of_birth`, reusing the existing StudentRecord on a match and creating one otherwise. A student record carries `full_name`, `date_of_birth`, and a `deferment_standing` that begins at `NONE` and thereafter reflects the most recently acknowledged servicer notification (§3.4). Each accepted entry's status fields — `status_code`, `census_status_code`, and `deferment_status` — are computed as-of the upload date per §3.4; rejected rows keep `NONE` in all of them. Each entry is stamped with its `file_id` and a denormalized `institution_id` copied from the file.

Upload supersedes the period's prior uncertified file: any previous file still `UPLOADED` for the same period moves to `SUPERSEDED`, and its entries — both `REJECTED` ones, which keep their `reject_reason`, and `ACCEPTED` ones — move to `SUPERSEDED` with it. The new file itself begins `UPLOADED`, and the period's `upload_count` increments by one.

Enrollment files are listed in `created_at` ascending order, filtered by `institution_id`, `reporting_period_id`, `submitted_by_user_id`, or `status`; entries are listed in file order — `row_index` ascending within a file, then `created_at` ascending — filtered by `file_id`, `student_id`, `institution_id`, or `entry_status`.

### 3.4. Certification, Status Determination, and the Servicer Notification Feed

Certification is the certifier's act, never the submitter's: a `RegistrarCertifier` certifies a file still in `UPLOADED` status, moving it `UPLOADED` → `CERTIFIED`. The checks run in order — the certifier's institution must match the file's (`ERR_CROSS_INSTITUTION_ACCESS`), the file must exist (`ERR_FILE_NOT_FOUND`) and be `UPLOADED` (`ERR_INVALID_STATE`), the institution must be `ACTIVE` (`ERR_INSTITUTION_SUSPENDED`), an `ACTIVE` agreement must cover now (`ERR_AGREEMENT_LAPSED`), and the file must be clean: a `rejected_rows` count above zero blocks certification with `ERR_UNRESOLVED_ROWS` (HTTP 409). A file carrying rejected rows can never be certified; the remedy is a fresh, corrected upload, which supersedes it.

Certification stamps `certified_at` with the current logical time and derives `late_submission`: true exactly when `certified_at` falls strictly after the period's `submission_due_at`, so certification on the due date itself is on time.

Every `ACCEPTED` entry is then re-evaluated, and this is where the two status variants matter. The system maintains, per entry, a `status_code` — the as-of-report variant — and a `census_status_code` — the as-of-census variant — each drawn from `NONE`, `FULL_TIME`, `HALF_TIME`, `LESS_THAN_HALF_TIME`, and `WITHDRAWN`, plus a `deferment_status` drawn from `NONE`, `DEFERMENT_ELIGIBLE`, `DEFERMENT_INELIGIBLE`, `WITHDRAWN_GRACE`, and `REPAYMENT_DUE`. An entry's census date is its `term_start` plus fourteen days. For the as-of-report variant evaluated at a date D — the upload date at upload, `certified_at` at certification, the decision date at correction, the fulfill date at enrollment fulfillment — the entry is `WITHDRAWN` when a `withdrawal_date` is present and falls on or before D; otherwise the credit band applies. For the as-of-census variant, withdrawal counts only when the `withdrawal_date` falls on or before the census date; a student who withdrew after census keeps the credit-based band. The credit band depends on `career_level`: an `UNDERGRAD` is `FULL_TIME` at 12.0 credits or more, `HALF_TIME` at 6.0 or more, and `LESS_THAN_HALF_TIME` below that; a `GRADUATE` is `FULL_TIME` at 9.0 credits or more, `HALF_TIME` at 4.5 or more, and `LESS_THAN_HALF_TIME` below that. Both variants are recomputed together at upload, at certification, and at correction-apply time; rejected rows keep `NONE` throughout.

The deferment determination follows the status code at the same as-of date. A `FULL_TIME` or `HALF_TIME` student is `DEFERMENT_ELIGIBLE`; a `LESS_THAN_HALF_TIME` student is `DEFERMENT_INELIGIBLE`. A `WITHDRAWN` student is measured against a grace end computed as the `withdrawal_date` plus 180 days: strictly before that grace end the entry is `WITHDRAWN_GRACE`; on or after it, the entry is `REPAYMENT_DUE`.

Certification also feeds the loan servicers. For every `ACCEPTED` entry carrying a `servicer_ref`, the system generates a ServicerNotification in `QUEUED` status, recording the entry as `enrollment_entry_id`, copying the `student_id` and the `servicer_ref`, setting `notification_type` to the entry's `deferment_status` at generation, and setting `grace_end_date` to the withdrawal date plus 180 days only when the type is `WITHDRAWN_GRACE` — otherwise null.

If another file for the same reporting period was already `CERTIFIED`, certification supersedes it: that file moves to `SUPERSEDED`, its `ACCEPTED` entries move to `SUPERSEDED`, and its still-undelivered notifications — `QUEUED` or `SENT` — move to `SUPERSEDED`, while `ACKNOWLEDGED` notifications remain as history.

Finally, certification settles the calendar. When the period's `outcome` is still `NONE`, it becomes `ON_TIME` or `LATE` according to `late_submission`; when the period had already closed `DELINQUENT`, a late certification flips the outcome from `DELINQUENT` to `LATE`. The institution's `compliance_standing` is then recomputed per §3.2.

Notifications travel on the clock: any clock advance dispatches every `QUEUED` notification to `SENT` in `created_at` ascending order. A `Servicer` acknowledges a `SENT` notification — the caller's `X-User-ID` must equal the notification's `servicer_ref`, otherwise `ERR_UNAUTHORIZED` — moving it `SENT` → `ACKNOWLEDGED` and writing the notification's `notification_type` onto the student's `deferment_standing`. A student's `deferment_standing` therefore always reflects the most recently acknowledged notification for that student, latest by `created_at`. When a newer determination exists for the same entry — because a correction was applied or the owning file was superseded — the entry's `QUEUED` and `SENT` notifications move to `SUPERSEDED`; acknowledged ones are historical and remain. Notifications are listed in `created_at` ascending order, filtered by `servicer_ref`, `student_id`, `enrollment_entry_id`, or `status`; a Servicer caller sees only its own `servicer_ref`.

### 3.5. The Correction and Amendment Cycle

When an institution discovers that a certified row misstated reality, either registrar officer of that institution — submitter or certifier — files a CorrectionCase against the erroneous entry. The target must be an `ACCEPTED` entry of a `CERTIFIED` or `AMENDMENT_PENDING` file: filing against a `SUPERSEDED` entry is rejected distinctly with `ERR_ENTRY_SUPERSEDED` (HTTP 409), and an entry that already has a `FILED` case open against it rejects the new filing with `ERR_OPEN_CORRECTION_EXISTS` (HTTP 409); as always, the filer's institution must match (`ERR_CROSS_INSTITUTION_ACCESS`), the entry must exist (`ERR_ENTRY_NOT_FOUND`), and a filing against a file in any other status fails the state check (`ERR_INVALID_STATE`). The payload names the `enrollment_entry_id` and a `reason_code` — `REPORTING_ERROR`, `STATUS_MISSTATEMENT`, or `LATE_WITHDRAWAL_NOTICE` — and may carry a `corrected_credit_hours`, a `corrected_withdrawal_date`, or the flag `clear_withdrawal_date`, which defaults to false and, when true, produces a replacement entry with no withdrawal date at all. `clear_withdrawal_date` and `corrected_withdrawal_date` are mutually exclusive; supplying both is rejected with `ERR_VALIDATION`. The filer is recorded as `filed_by_user_id` from `X-User-ID`, the case begins `FILED`, and filing has immediate structural effects: the owning file, if `CERTIFIED`, moves to `AMENDMENT_PENDING`, and its `open_correction_count` increments by one.

Decision belongs to a certifier of the same institution — and never to the filer. The deciding certifier's institution must match the entry's institution (`ERR_CROSS_INSTITUTION_ACCESS`), the case must exist (`ERR_CASE_NOT_FOUND`) and still be `FILED` (`ERR_INVALID_STATE`), and the deciding user, recorded as `decided_by_user_id`, must differ from `filed_by_user_id`: a same-user decision is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). The decision payload carries a single `outcome`: `APPROVED` or `DENIED`.

An approved case moves `FILED` → `APPLIED`, stamps `decided_at`, and rewrites the row. The old entry moves `ACCEPTED` → `SUPERSEDED`, and a replacement `ACCEPTED` entry is created on the same file carrying the corrected fields — or the cleared withdrawal date — with `row_index` set to the file's current `row_count`; the file's `row_count` and `accepted_rows` then each increment by one, and the replacement's `source_case_id` points back to the case that created it. The replacement's `status_code`, `census_status_code`, and `deferment_status` are computed as-of the decision date per §3.4. When the replacement's `deferment_status` differs from the old entry's and a `servicer_ref` is present, a new `QUEUED` ServicerNotification is generated for the replacement while the old entry's `QUEUED` and `SENT` notifications move to `SUPERSEDED`. The file's `open_correction_count` decrements by one, and when the count drains to zero on a file in `AMENDMENT_PENDING`, the file returns to `CERTIFIED`.

A denied case moves `FILED` → `DENIED` with `decided_at` stamped; the entry stands unchanged, and only the file's `open_correction_count` decrements — again returning an `AMENDMENT_PENDING` file to `CERTIFIED` once the count reaches zero.

Supersession does not adjudicate open cases: if a different file for the same period is certified while cases are `FILED`, the `AMENDMENT_PENDING` file moves to `SUPERSEDED` through the same entry-and-notification cascade as a certified file, but those `FILED` cases remain `FILED` until decided on their own merits.

Correction cases are listed in `created_at` ascending order, filtered by `enrollment_entry_id`, `filed_by_user_id`, or `status`.

### 3.6. Degree Reporting, Sealing, and Revocation

Degrees enter the system through the registrar's submitter. A `RegistrarSubmitter` reports a conferred credential with the conferring `institution_id`, the `student_id`, the `degree_level` — `CERTIFICATE`, `ASSOCIATE`, `BACHELOR`, `MASTER`, or `DOCTORATE` — a free-text `degree_title` such as "BS Computer Science", and the `conferred_on` date. The submitter's institution must match the conferring institution (`ERR_CROSS_INSTITUTION_ACCESS`), and both the institution (`ERR_INSTITUTION_NOT_FOUND`) and the student (`ERR_STUDENT_NOT_FOUND`) must exist. The record begins `REPORTED`, and the reporting user is captured from `X-User-ID` as `created_by_user_id`.

Only sealing makes a degree verifiable, and sealing is deliberately harder than reporting. A `RegistrarCertifier` seals a `REPORTED` record — anything else fails with `ERR_INVALID_STATE` — and only when the certifier's institution matches the degree's (`ERR_CROSS_INSTITUTION_ACCESS`), the institution is `ACTIVE` (`ERR_INSTITUTION_SUSPENDED`), an `ACTIVE` participation agreement covers the current instant (`ERR_AGREEMENT_LAPSED`), and the institution's `compliance_standing` is anything other than `NON_COMPLIANT`: a non-compliant institution's sealing attempt is rejected with `ERR_INSTITUTION_NON_COMPLIANT` (HTTP 422). Sealing stamps `sealed_at` and moves the record `REPORTED` → `SEALED`.

Revocation is terminal and one-way: a certifier of the same institution revokes a `SEALED` record, moving it `SEALED` → `REVOKED`. From that moment, fulfillments treat the degree as absent — a degree verification that would have matched it takes the `NO_RECORD` path instead (§3.7).

Degree records are listed ordered by `conferred_on` ascending, then `created_at` ascending, filtered by `student_id`, `institution_id`, or `status`.

### 3.7. Requester Vetting, Prepaid Credit, and Verification Commerce

Employers and background screeners buy verification against prepaid credit. An operator creates a Requester account with an `org_name`, a `requester_kind` of `EMPLOYER` or `BACKGROUND_SCREENER`, and an optional `initial_credit_cents` that defaults to zero; the account begins `PENDING_VETTING` with `credit_balance_cents` equal to the seed credit. Vetting is an ops decision carrying an `outcome`: `VET` moves a `PENDING_VETTING` account to `VETTED` — and later re-vets a `SUSPENDED` account back to `VETTED` — stamping `vetted_at` with the most recent vetting time, while `DENY` moves a `PENDING_VETTING` account to terminal `DENIED`; a decision fired from any other from-state is rejected with `ERR_INVALID_STATE`. An operator may also suspend a `VETTED` account: in-flight `QUOTED` requests are unaffected, but new request creation is rejected with `ERR_REQUESTER_NOT_VETTED` (HTTP 403). A requester reads its own account only.

The balance is a simple ledger: `credit_balance_cents` begins at `initial_credit_cents`, is debited by payments, and is credited by refunds; there is no top-up channel. Every debit and credit is enumerated below.

Creating a verification request is the most heavily guarded operation in the system, and the guards run in a fixed order — the first failure wins. Authentication, role membership, and ownership come first (§2.1): a `Requester` caller buys `DEGREE` or `ENROLLMENT` products and must present a `requester_id` equal to its own `X-User-ID`; a `Learner` caller self-orders a `TRANSCRIPT` with `purpose` `SELF`, presents a `student_id` equal to its own `X-User-ID`, and presents no `requester_id` at all. Next, a requester caller's account must be `VETTED` (`ERR_REQUESTER_NOT_VETTED`). Then the purpose matrix: an `EMPLOYER` may purchase for purposes `EMPLOYMENT` and `INSURANCE`; a `BACKGROUND_SCREENER` may purchase for `EMPLOYMENT` and `BACKGROUND_SCREEN`; `LOAN_DEFERMENT` is purchasable by neither kind; `TRANSCRIPT` with `SELF` is Learner-only, while `DEGREE` and `ENROLLMENT` are Requester-only — any other combination of role, product, and purpose is rejected with `ERR_PURPOSE_NOT_PERMITTED` (HTTP 422). Payload well-formedness (`ERR_VALIDATION`) follows, then existence of the referenced institution (`ERR_INSTITUTION_NOT_FOUND`) and student (`ERR_STUDENT_NOT_FOUND`), then the target institution must be `ACTIVE` (`ERR_INSTITUTION_SUSPENDED`).

Privacy is checked at creation, before money moves. The creation-time privacy gate rejects with `ERR_PRIVACY_BLOCKED` (HTTP 422) when an active `FULL_BLOCK` directive covers the student — for any product other than the learner's own `TRANSCRIPT` self-order, which is exempt — or when an active `DIRECTORY_BLOCK` covers a `DEGREE` request. The consent gate follows, rejecting with `ERR_CONSENT_REQUIRED` (HTTP 422) when an `ENROLLMENT` request for purpose `EMPLOYMENT` or `BACKGROUND_SCREEN` lacks `consent_artifact` set to true — even with no directive on the student — or when a `DIRECTORY_BLOCK` covers the student and an `ENROLLMENT` request lacks it. `ENROLLMENT` checks for `LOAN_DEFERMENT` or `INSURANCE` purposes are consent-exempt, and a `DEGREE` request without a block on file is likewise consent-exempt. The `consent_artifact` flag itself defaults to false, as does `rush`.

Duplicate suppression comes next: an in-flight request — `QUOTED` or `PAID` — with the same (`requester_id`, `student_id`, `institution_id`, `product_type`, `purpose`) is rejected with `ERR_DUPLICATE_REQUEST` (HTTP 409). The rule applies to `DEGREE` and `ENROLLMENT` only, because `TRANSCRIPT` self-orders are repeat-orderable and are governed instead by the active-transcript cap: a learner who already holds two `TRANSCRIPT` requests in `QUOTED` or `PAID` status is rejected with `ERR_MAX_ACTIVE_TRANSCRIPTS` (HTTP 409).

A created request is `QUOTED`, and its price is pinned for life — the fee is never re-quoted, and an expired quote forces a brand-new request. The quote computation is deliberately ordered. The base fee is 2599 cents for `DEGREE`, 1599 cents for `ENROLLMENT`, and 0 cents for `TRANSCRIPT`. The requester's volume tier at quote time, recorded as `volume_tier_at_quote`, is `PREFERRED` when the requester already has at least three requests in `RELEASED` status whose `released_at` falls inside the current calendar quarter — January through March, April through June, July through September, or October through December — and strictly before the current instant, with the request being quoted never counting itself; otherwise the tier is `STANDARD`. A `PREFERRED` tier earns a discount of 2000 basis points off the base; `STANDARD` earns none. Step one rounds first: the discounted base is the base multiplied by the ten-thousandths remaining after the discount and divided by ten thousand, rounded half-up to integer cents. Step two computes the rush component on that rounded discounted base: when `rush` is true, a surcharge of 3333 basis points of the rounded discounted base, itself rounded half-up to integer cents; when `rush` is false, zero. Step three sums: `fee_cents` is the discounted base plus the rush component, a sum of two already-rounded components. Alternative orderings — summing before rounding, or computing the surcharge on the unrounded base — yield different cents and are wrong. The quote also stamps `quote_expires_at` at 48 hours after creation; the tier, the fee, and the expiry never move afterward, and `refund_cents` begins at zero.

Payment draws on the prepaid balance. Paying requires the request still be `QUOTED` — a request that has already expired reports the specific cause, `ERR_QUOTE_EXPIRED` (HTTP 409) — and requires the current instant to be strictly before `quote_expires_at`. The requester's `credit_balance_cents` must be at least `fee_cents`, otherwise `ERR_INSUFFICIENT_CREDIT` (HTTP 402); the Learner transcript fee is zero and always passes this check. Payment debits `fee_cents` from the balance, stamps `paid_at`, and moves the request `QUOTED` → `PAID`. Should the clock reach `quote_expires_at` first, a still-`QUOTED` request moves to `EXPIRED` instead.

Fulfillment is an operations act with two gates, evaluated in order: privacy first, then records. The privacy gate fails — moving the request `PAID` → `BLOCKED_PRIVACY` — when an active `FULL_BLOCK` covers the student (the learner's own `TRANSCRIPT` self-order is exempt), when an active `DIRECTORY_BLOCK` covers a `DEGREE` request, or when an active `DIRECTORY_BLOCK` covers an `ENROLLMENT` request whose `consent_artifact` is not true. The record gate fails — moving the request `PAID` → `NO_RECORD` — when a `DEGREE` request finds no `SEALED` DegreeRecord for the student at the institution (a `REVOKED` degree counts as absent), when an `ENROLLMENT` request finds not a single `ACCEPTED`, non-`SUPERSEDED` entry for the student at the institution, or when a `TRANSCRIPT` request finds neither. Both failure branches refund in full: `refund_cents` is set to `fee_cents` and credited back to the requester's `credit_balance_cents` — a no-op for the zero-fee Learner transcript. When both gates pass, the request moves `PAID` → `RELEASED`: `released_at` is stamped; `result_status` becomes `VERIFIED` (the field enumerates `NONE`, `VERIFIED`, and `NOT_VERIFIED`, and begins at `NONE`); an `ENROLLMENT` release recomputes `enrollment_status_at_release` as-of the fulfill date using the as-of-report variant of §3.4 (it otherwise remains `NONE`); and a `TRANSCRIPT` release stamps `artifact_expires_at` at 72 hours after release — the informational expiry of the electronic delivery artifact.

Institution suspension reaches into this pipeline from §3.1: requests targeting the institution in `QUOTED` move to `CANCELLED` untouched, while `PAID` ones move to `CANCELLED` with the same full-refund mechanics.

Verification requests are listed in `created_at` ascending order, filtered by `requester_id`, `student_id`, `institution_id`, or `status`; a `Requester` caller sees only its own requests, and a `Learner` caller only their own.

### 3.8. Learner Self-Service and Privacy Directives

Learners control the disclosure of their own records through privacy directives, and operations staff may place directives on a learner's behalf. A learner reads their own student record and places directives only on it — a path or body `student_id` other than the caller's own is rejected with `ERR_UNAUTHORIZED`, and an unknown student with `ERR_STUDENT_NOT_FOUND`.

Placing a directive names the `directive_type` — `FULL_BLOCK`, `DIRECTORY_BLOCK`, or `RESEARCH_OPT_OUT` — an `effective_from` marking the inclusive window start, an optional `effective_to` marking the exclusive window end (absent means indefinite), and the concurrency token `expected_student_version`. The token is checked before any window arithmetic: a token that does not match the student record's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412), per §2.6. The window itself must be non-empty — `effective_to`, when present, strictly after `effective_from` — otherwise `ERR_DIRECTIVE_WINDOW_INVALID` (HTTP 422).

The three types do different work. A `FULL_BLOCK` blocks all non-self verification of the student. A `DIRECTORY_BLOCK` blocks the `DEGREE` product outright and blocks `ENROLLMENT` unless the requester attests signed consent via `consent_artifact`. A `RESEARCH_OPT_OUT` excludes the student from research cohorts (§3.9) without affecting verification.

A directive is `ACTIVE` from creation — creation with an `effective_from` in the future is permitted and produces an `ACTIVE` directive whose window simply has not started yet. Creating a new directive of the same type for the same student supersedes the prior `ACTIVE` one, moving it `ACTIVE` → `SUPERSEDED`, and the student record's `version` increments as part of that create mutation. When the clock reaches a directive's `effective_to`, the directive moves `ACTIVE` → `EXPIRED`. A directive gates only while it is `ACTIVE` and its window actually covers the current instant: `effective_from` on or before now, and `effective_to` either absent or strictly after now. A student's directives are listed in `created_at` ascending order.

### 3.9. Aggregate Research Data Services

Research data services deliver aggregate outcomes, never student-level rows. A `ResearchAnalyst` requests a dataset with the `scope_institution_id` whose entries form the cohort and a cohort window running from `cohort_term_start` through `cohort_term_end`, both boundaries inclusive; the end must not precede the start, otherwise `ERR_VALIDATION`. The dataset begins `REQUESTED`, and the analyst is recorded from `X-User-ID` as `created_by_analyst_id`.

Generation is an operations act on a dataset still `REQUESTED` — anything else fails with `ERR_INVALID_STATE`, and an unknown dataset reports `ERR_DATASET_NOT_FOUND` — and its computation order is pinned. First, the cohort: distinct students who hold an `ACCEPTED`, non-`SUPERSEDED` EnrollmentEntry at the scope institution whose entry `term_start` falls within the cohort window, minus any student with a `RESEARCH_OPT_OUT` directive in effect at generation time under §3.8's gating rule; the count is `cohort_size`. Second, the k-anonymity gate: a `cohort_size` below ten rejects the generation with `ERR_COHORT_TOO_SMALL` (HTTP 422). Third, completers: `completer_count` counts the cohort members holding a `SEALED` DegreeRecord at the scope institution whose `conferred_on` falls within the window from `cohort_term_start` through 730 days after `cohort_term_end`, inclusive. Fourth, the adjusted denominator: `adjusted_cohort_size` is `cohort_size` minus the members whose latest entry's `census_status_code` is `WITHDRAWN`. Fifth, the two rates, each computed to exactly four decimal places rounded half-up: `completion_rate_census` divides `completer_count` by `cohort_size`, and `completion_rate_adjusted` divides the same `completer_count` — the numerator is identical in both variants — by `adjusted_cohort_size`, so the two rates diverge exactly when census-withdrawn members exist. Generation stamps `generated_at` and moves the dataset `REQUESTED` → `GENERATED`, a stable end state with no further transitions.

The institution-scoped dataset list shows `ClearinghouseOps` and registrar callers the institution's datasets; a `ResearchAnalyst` caller sees only the datasets they created.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that read, modify, or act on an existing resource return `200 OK`. The table below is a summary only — request fields, response content, side effects, and the guards each operation enforces are specified in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST   | `/institutions` | Create an institution with its registrar users inline | ClearinghouseOps |
| GET    | `/institutions/{id}` | Read one institution | ClearinghouseOps, RegistrarSubmitter, RegistrarCertifier |
| POST   | `/institutions/{id}/suspend` | Ops-suspend an `ACTIVE` institution; cancels in-flight `QUOTED`/`PAID` verification requests (`PAID` refunded) | ClearinghouseOps |
| POST   | `/institutions/{id}/reinstate` | Reinstate a `SUSPENDED` institution; requires an `ACTIVE` agreement covering now | ClearinghouseOps |
| POST   | `/institutions/{id}/agreements` | Create a participation agreement (half-open window, overlap-checked); created `ACTIVE` or `SCHEDULED` per current time | ClearinghouseOps |
| GET    | `/institutions/{id}/agreements` | List an institution's agreements | ClearinghouseOps, RegistrarSubmitter, RegistrarCertifier |
| POST   | `/institutions/{id}/reporting-periods` | Create a reporting period (closed-occupancy overlap rule against the institution's other periods) | ClearinghouseOps |
| GET    | `/institutions/{id}/reporting-periods` | List an institution's reporting periods | ClearinghouseOps, RegistrarSubmitter, RegistrarCertifier |
| GET    | `/institutions/{id}/users` | List an institution's registrar users | ClearinghouseOps, RegistrarSubmitter, RegistrarCertifier |
| GET    | `/institutions/{id}/research-datasets` | List datasets scoped to an institution; ResearchAnalyst callers see only their own | ClearinghouseOps, RegistrarSubmitter, RegistrarCertifier, ResearchAnalyst |
| POST   | `/enrollment-files` | Upload an enrollment file with rows inline; supersedes any prior `UPLOADED` file for the period | RegistrarSubmitter |
| GET    | `/enrollment-files/{id}` | Read one enrollment file | ClearinghouseOps, RegistrarSubmitter, RegistrarCertifier |
| GET    | `/enrollment-files` | List enrollment files with filters | ClearinghouseOps, RegistrarSubmitter, RegistrarCertifier |
| POST   | `/enrollment-files/{id}/certify` | Certify an `UPLOADED` file; generates servicer notifications and may supersede a previously `CERTIFIED` file | RegistrarCertifier |
| GET    | `/enrollment-entries/{id}` | Read one enrollment entry | ClearinghouseOps, RegistrarSubmitter, RegistrarCertifier |
| GET    | `/enrollment-entries` | List enrollment entries with filters | ClearinghouseOps, RegistrarSubmitter, RegistrarCertifier |
| POST   | `/correction-cases` | File a correction against an `ACCEPTED` entry of a `CERTIFIED` or `AMENDMENT_PENDING` file | RegistrarSubmitter, RegistrarCertifier |
| GET    | `/correction-cases/{id}` | Read one correction case | ClearinghouseOps, RegistrarSubmitter, RegistrarCertifier |
| GET    | `/correction-cases` | List correction cases with filters | ClearinghouseOps, RegistrarSubmitter, RegistrarCertifier |
| POST   | `/correction-cases/{id}/decision` | Decide a `FILED` case; `APPROVED` applies the correction with the full supersede/notification cascade | RegistrarCertifier |
| POST   | `/degree-records` | Report a conferred degree or certificate | RegistrarSubmitter |
| GET    | `/degree-records/{id}` | Read one degree record | ClearinghouseOps, RegistrarSubmitter, RegistrarCertifier |
| GET    | `/degree-records` | List degree records with filters | ClearinghouseOps, RegistrarSubmitter, RegistrarCertifier |
| POST   | `/degree-records/{id}/seal` | Seal a `REPORTED` degree (requires `ACTIVE` institution, `ACTIVE` agreement, standing not `NON_COMPLIANT`) | RegistrarCertifier |
| POST   | `/degree-records/{id}/revoke` | Revoke a `SEALED` degree (terminal) | RegistrarCertifier |
| POST   | `/requesters` | Create a requester account (`PENDING_VETTING`) with optional prepaid credit | ClearinghouseOps |
| GET    | `/requesters/{id}` | Read one requester (a Requester reads its own account only) | ClearinghouseOps, Requester |
| POST   | `/requesters/{id}/vet` | Vet decision: `VET` from `PENDING_VETTING` or `SUSPENDED` to `VETTED`; `DENY` from `PENDING_VETTING` to `DENIED` | ClearinghouseOps |
| POST   | `/requesters/{id}/suspend` | Suspend a `VETTED` requester | ClearinghouseOps |
| POST   | `/verification-requests` | Create a verification request; computes the pinned fee quote, tier, and quote expiry | Requester, Learner |
| GET    | `/verification-requests/{id}` | Read one verification request (Requester and Learner see only their own) | ClearinghouseOps, Requester, Learner |
| GET    | `/verification-requests` | List verification requests with filters (Requester and Learner scoped to their own) | ClearinghouseOps, Requester, Learner |
| POST   | `/verification-requests/{id}/pay` | Pay a `QUOTED` request from the requester's prepaid balance (Learner transcript fee is 0) | Requester, Learner |
| POST   | `/verification-requests/{id}/fulfill` | Fulfill a `PAID` request: privacy gate, then record gate; `RELEASED` / `BLOCKED_PRIVACY` / `NO_RECORD` | ClearinghouseOps |
| POST   | `/students/{id}/privacy-directives` | Place a privacy directive on a student record; supersedes a same-type `ACTIVE` directive | Learner, ClearinghouseOps |
| GET    | `/students/{id}` | Read one student record | ClearinghouseOps, Learner |
| GET    | `/students/{id}/privacy-directives` | List a student's privacy directives | ClearinghouseOps, Learner |
| GET    | `/servicer-notifications/{id}` | Read one servicer notification (Servicer only when `servicer_ref` matches) | ClearinghouseOps, Servicer |
| GET    | `/servicer-notifications` | List servicer notifications with filters (Servicer scoped to its own `servicer_ref`) | ClearinghouseOps, Servicer |
| POST   | `/servicer-notifications/{id}/acknowledge` | Acknowledge a `SENT` notification; updates the student's `deferment_standing` | Servicer |
| POST   | `/research-datasets` | Request an aggregate outcome dataset for an institution's cohort window | ResearchAnalyst |
| POST   | `/research-datasets/{id}/generate` | Generate the dataset: opt-out exclusion, k-anonymity gate, completer count, both rate variants | ClearinghouseOps |
| POST   | `/_clock/set_current_utc` | Advance the logical clock (strictly forward); processes all time-driven transitions in the pinned order | ClearinghouseOps |

## 5. Error Code Catalogue

Trigger conditions for each error live in the narratives of §2 and §3; this catalogue enumerates only the codes and their HTTP statuses.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_CROSS_INSTITUTION_ACCESS` | 403 Forbidden |
| `ERR_REQUESTER_NOT_VETTED` | 403 Forbidden |
| `ERR_PURPOSE_NOT_PERMITTED` | 422 Unprocessable Entity |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_INSTITUTION_NOT_FOUND` | 404 Not Found |
| `ERR_PERIOD_NOT_FOUND` | 404 Not Found |
| `ERR_STUDENT_NOT_FOUND` | 404 Not Found |
| `ERR_FILE_NOT_FOUND` | 404 Not Found |
| `ERR_ENTRY_NOT_FOUND` | 404 Not Found |
| `ERR_CASE_NOT_FOUND` | 404 Not Found |
| `ERR_DEGREE_NOT_FOUND` | 404 Not Found |
| `ERR_REQUESTER_NOT_FOUND` | 404 Not Found |
| `ERR_REQUEST_NOT_FOUND` | 404 Not Found |
| `ERR_NOTIFICATION_NOT_FOUND` | 404 Not Found |
| `ERR_DATASET_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INSTITUTION_SUSPENDED` | 409 Conflict |
| `ERR_ENTRY_SUPERSEDED` | 409 Conflict |
| `ERR_QUOTE_EXPIRED` | 409 Conflict |
| `ERR_AGREEMENT_LAPSED` | 409 Conflict |
| `ERR_PERIOD_NOT_OPEN` | 409 Conflict |
| `ERR_PRIVACY_BLOCKED` | 422 Unprocessable Entity |
| `ERR_CONSENT_REQUIRED` | 422 Unprocessable Entity |
| `ERR_INSTITUTION_NON_COMPLIANT` | 422 Unprocessable Entity |
| `ERR_COHORT_TOO_SMALL` | 422 Unprocessable Entity |
| `ERR_AGREEMENT_OVERLAP` | 409 Conflict |
| `ERR_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_OPEN_CORRECTION_EXISTS` | 409 Conflict |
| `ERR_DUPLICATE_REQUEST` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_UNRESOLVED_ROWS` | 409 Conflict |
| `ERR_MAX_ACTIVE_TRANSCRIPTS` | 409 Conflict |
| `ERR_DIRECTIVE_WINDOW_INVALID` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_CREDIT` | 402 Payment Required |
