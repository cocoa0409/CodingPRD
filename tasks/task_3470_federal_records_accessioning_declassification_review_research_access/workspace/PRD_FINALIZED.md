# Federal Records Accessioning API — Product Requirements Document

## 1. Introduction

The National Archives and Records Administration carries a statutory pipeline that few institutions share: it must decide which agency records are permanent, take legal and physical custody of them, hold their classified content under disciplined review regimes, and ultimately open them to the public — in a reading room, through reproduction services, under the Freedom of Information Act, and as digital surrogates. This document specifies the API through which agencies, archivists, reviewers, and researchers move records along that pipeline: schedule appraisal and approval, accessioning of permanent transfers with their metadata standards, systematic and mandatory declassification review with equity referrals to originating agencies, archival processing and description, researcher registration and research-room pulls, reproduction and fee handling, FOIA adjudication and appeal, presidential access restrictions, and digitization prioritization.

Three structural commitments shape every workflow below. First, **segregation of duties**: the archivist who appraises a schedule may not be the one who decides it, and the officer who adjudicates a FOIA request may not decide its appeal. Second, **entity-backed ownership**: a records officer or agency liaison acts strictly for their own agency, and a researcher acts strictly as themselves — there is no impersonation. Third, **a single logical clock** governs every age gate, transfer lag, cooling period, appeal window, and card expiry in the system; nothing in this API consults wall-clock time. Derived state — above all a collection's restriction posture — is recomputed eagerly and propagates outward, so that when records become public, every pending request that existed only because of the restriction resolves itself in the same transaction.

The API is mounted under `/records`; one administrative capability outside that mount sets the logical clock. Consistency is immediate: every mutation described in this document, including cascade effects and derived-field recomputation, is visible in the response of the call that triggered it.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contract: who may call what, how responses and errors are shaped, how lists are paged, how time works, and the fixed order in which every request is adjudicated.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. If either header is missing, or if `X-User-Role` is not one of the declared roles, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). If the role is declared but not among the roles an endpoint admits, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The system recognizes twelve roles, spelled exactly as follows: `PlatformAdmin`, `Anonymous`, `RecordsOfficer`, `AgencyLiaison`, `AppraisalArchivist`, `ProcessingArchivist`, `DeclassReviewer`, `ChiefArchivist`, `ResearchRoomStaff`, `FoiaOfficer`, `FoiaAppealsOfficer`, and `Researcher`.

Two roles are **entity-backed by an agency**. When `X-User-Role` is `RecordsOfficer`, `X-User-ID` is the `id` of the acting `Agency`, and ownership checks on any resource that references an agency compare that resource's `agency_id` field to `X-User-ID`. The same rule applies when `X-User-Role` is `AgencyLiaison`: `X-User-ID` is the `id` of the acting `Agency`, and an `AgencyLiaison` responds only for referrals addressed to that agency. A mismatch on any ownership-gated operation is rejected with `ERR_OWNERSHIP_MISMATCH` (HTTP 403).

One role is **entity-backed by a researcher registration**. When `X-User-Role` is `Researcher`, `X-User-ID` is the `id` of the acting `ResearcherRegistration`; ownership checks on a pull, reproduction, FOIA, or mandatory-review request compare the resource's `researcher_id` (or `requester_researcher_id`) field to `X-User-ID`.

The remaining nine roles are **opaque**. When `X-User-Role` is `PlatformAdmin`, `Anonymous`, `AppraisalArchivist`, `ProcessingArchivist`, `DeclassReviewer`, `ChiefArchivist`, `ResearchRoomStaff`, `FoiaOfficer`, or `FoiaAppealsOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it where a workflow stamps an actor (for example, as `appraiser_id` on a schedule, `decided_by` on a decision, `lead_reviewer_id` on a review, or `adjudicator_id` on a FOIA request) but never compares it to any entity's `id`.

`PlatformAdmin` is the system operator: it alone registers agencies and drives the logical clock. `Anonymous` is the unauthenticated public caller and may do exactly one thing — self-register as a researcher; every other endpoint rejects `Anonymous` with `ERR_FORBIDDEN_ROLE`. Read endpoints are open to every declared role except `Anonymous`. Write and action endpoints name their admitted roles individually in §4, and the workflow narratives of §3 restate them where the rule carries business meaning.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10 when omitted, accepts a minimum of 1, and is capped at a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0.

Unless a specific endpoint states otherwise, every list endpoint returns its resources sorted by `created_at` in ascending order.

The `meta` object of a paginated list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock

No rule in this system reads wall-clock time. A single server-held **logical clock** supplies the current instant, and every temporal rule — transfer-lag eligibility, the systematic-review age gate, referral overdue evaluation, the presidential notification cooling period, the FOIA appeal window, researcher card expiry, the pull visit window, and the daily reproduction quota's calendar day — evaluates against it.

An admin-only test-driving capability, available to `PlatformAdmin` alone and living outside the `/records` mount, sets the logical clock to a supplied `to_iso8601` instant (ISO 8601 UTC) and answers with the resulting `current_utc`. Before any such call, the server's startup default is exactly `2026-09-01T00:00:00Z`; the clock must never fall back to wall-clock time under any circumstance.

One clock-driven transition is lazy rather than call-driven: when a researcher registration is loaded and the clock has reached or passed its `card_expires_at`, the registration is persisted as `EXPIRED` at that moment, before any further rule that depends on the registration's status is evaluated. §3.7 states the full rule.

### 2.5. Common Resource Properties

Every resource in this API — agencies, schedules, transfers, collections, declassification reviews, equity referrals, researcher registrations, pull requests, reproduction requests, FOIA requests, and presidential restrictions — carries a standard set of system-managed fields:

- `id` (string): a server-minted UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, recorded when the resource is created.
- `updated_at` (string): an ISO 8601 UTC timestamp, refreshed on every mutation of the resource.
- `version` (integer): starts at its initial value on creation and increments by one on every mutation — including mutations the resource suffers as the target of a cascade or a derived-field recompute triggered by another resource's operation.

Because consistency is immediate, a call that cascades into another resource (for example, a pull fulfillment that increments the collection's pull counter) advances that resource's `version` and refreshes its `updated_at` within the same transaction, and the effect is visible to the very next read.

### 2.6. Request Adjudication Order

Every request is adjudicated against a fixed ladder of checks. A request that fails a rung is rejected with that rung's error, and no later rung is evaluated. The ladder, from first to last:

1. **Authentication context.** `X-User-ID` and `X-User-Role` must be present and the role must be declared (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`, 400).
2. **Role admission.** The caller's role must appear in the endpoint's role list (`ERR_FORBIDDEN_ROLE`, 403).
3. **Path existence.** Path-segment identifiers must exist, validated left to right. Each segment maps to its entity-specific 404: `ERR_AGENCY_NOT_FOUND`, `ERR_SCHEDULE_NOT_FOUND`, `ERR_TRANSFER_NOT_FOUND`, `ERR_COLLECTION_NOT_FOUND`, `ERR_REVIEW_NOT_FOUND`, `ERR_REFERRAL_NOT_FOUND`, `ERR_RESEARCHER_NOT_FOUND`, `ERR_PULL_REQUEST_NOT_FOUND`, `ERR_REPRODUCTION_NOT_FOUND`, `ERR_FOIA_NOT_FOUND`, or `ERR_RESTRICTION_NOT_FOUND`.
4. **Body reference existence.** Foreign-key identifiers in the request body must exist, validated in the endpoint's declared input order — for example, `schedule_id` before `agency_id` when initiating a transfer, and `researcher_id` before `collection_id` when requesting a pull. A missing reference yields the same entity-specific 404 family as rung 3.
5. **Entity-backed ownership.** A `RecordsOfficer` or `AgencyLiaison` caller's `X-User-ID` must equal the `agency_id` being acted on; a `Researcher` caller's `X-User-ID` must equal the `researcher_id` (or `requester_researcher_id`) of the request (`ERR_OWNERSHIP_MISMATCH`, 403).
6. **Cross-reference consistency.** Where two references must agree — a transfer's `agency_id` must equal its schedule's `agency_id` — a disagreement yields `ERR_AGENCY_MISMATCH` (409).
7. **Stale-version rejection.** The one optimistic-concurrency rung, applied only where §2.7 names it, sits here: after existence and ownership, before any business gate (`ERR_STALE_COLLECTION_VERSION`, 412).
8. **From-state validity.** The target resource must be in a valid from-state for the requested transition. The generic rejection is `ERR_INVALID_STATE` (409); several transitions carry endpoint-specific 409 codes instead (`ERR_SCHEDULE_NOT_APPRAISED`, `ERR_TRANSFER_NOT_VALIDATED`, `ERR_REVIEW_NOT_IN_PROGRESS`, `ERR_REFERRAL_ALREADY_RESPONDED`, `ERR_PULL_NOT_FULFILLABLE`, `ERR_PULL_NOT_RETURNABLE`, `ERR_REPRO_NOT_PAYABLE`, `ERR_REPRO_NOT_CANCELLABLE`, `ERR_APPEAL_NOT_ALLOWED_STATE`, `ERR_FOIA_NOT_APPEALED`, `ERR_FOIA_ALREADY_ADJUDICATED`, `ERR_RESTRICTION_NOT_NOTIFIED`, `ERR_DIGITIZATION_NOT_QUEUED`), named beside their workflows in §3.
9. **Researcher active-status.** Where a workflow requires an active researcher, the registration must be `ACTIVE`; the lazy expiry evaluation of §2.4 runs first, so a registration whose card has just lapsed is persisted `EXPIRED` and only then rejected with `ERR_RESEARCHER_NOT_ACTIVE` (409).
10. **Restriction-posture gates.** Operations that require the records to be open check `restriction_posture` here (`ERR_COLLECTION_RESTRICTED`, 403).
11. **Segregation of duties.** Where a workflow forbids the same actor from performing two successive steps, the comparison happens here (`ERR_SEGREGATION_OF_DUTIES`, 403).
12. **Uniqueness.** Duplicate-detection rung: `ERR_AGENCY_CODE_EXISTS`, `ERR_EMAIL_EXISTS`, `ERR_SCHEDULE_NUMBER_EXISTS`, `ERR_REVIEW_ALREADY_OPEN`, `ERR_DUPLICATE_REFERRAL`, and `ERR_DUPLICATE_RESTRICTION_CATEGORY` (all 409).
13. **Temporal gates.** Time-gate checks against the logical clock: `ERR_TRANSFER_LAG_NOT_ELAPSED`, `ERR_SYSTEMATIC_REVIEW_PREMATURE`, `ERR_COOLING_PERIOD_ACTIVE`, `ERR_APPEAL_WINDOW_CLOSED`, and `ERR_VISIT_DATE_OUT_OF_WINDOW` (all 409).
14. **Method/metadata compatibility.** Transfer method and metadata-standard compatibility (`ERR_METADATA_STANDARD_MISMATCH`, `ERR_METHOD_REQUIREMENT_MISSING`, both 422).
15. **Shape rules.** Business shape requirements (`ERR_NOT_PERMANENT_DISPOSITION`, `ERR_SCHEDULE_NOT_APPROVED`, `ERR_COLLECTION_NOT_DESCRIBED`, `ERR_NOT_PRESIDENTIAL_RECORDS`, `ERR_FOIA_NOT_REQUIRED`, `ERR_COLLECTION_NOT_RESTRICTED`, `ERR_DESCRIPTION_INCOMPLETE`, `ERR_EXEMPTION_REQUIRED`, and the generic `ERR_INVALID_REQUEST` for a missing required field, a wrong type, an out-of-enum value, or an empty string where non-empty is required).
16. **Reservation rules.** Pull-request range, span, overlap, capacity, and active-pull checks, in the fixed sub-order stated in §3.7.
17. **Fiscal and quota rules.** The daily reproduction-page quota and the paid-before-fulfilled requirement (`ERR_DAILY_PAGE_LIMIT_EXCEEDED`, `ERR_REPRO_NOT_PAID`).

### 2.7. Optimistic Concurrency Control

Exactly one operation in this API is optimistic-concurrency protected: **opening a declassification review**. A request to open a review must carry `expected_collection_version`, holding the `version` of the target collection as the client last observed it. If that value does not equal the collection's current `version` — because, for example, another writer has already opened a review against the same collection (which advances the collection's `version` as review demand is recorded) or a posture-relevant cascade has recomputed the collection — the request is rejected with `ERR_STALE_COLLECTION_VERSION` (HTTP 412), and no review is created. This check is evaluated at the stale-version rung of §2.6, after existence and ownership but before any business gate. No other endpoint takes a version field; requests to any other operation carry no concurrency token.

### 2.8. Restriction Posture and the Posture-Flip Cascade

Every collection carries a derived `restriction_posture` with exactly three values: `PUBLIC`, `CLASSIFIED_REVIEW_REQUIRED`, and `PRESIDENTIAL_HOLD`. The derivation is deterministic and is evaluated in this order: if the collection has any presidential restriction whose status is `IMPOSED` or `NOTIFIED`, the posture is `PRESIDENTIAL_HOLD`; otherwise, if the collection's `classification_level` is anything other than `NONE`, the posture is `CLASSIFIED_REVIEW_REQUIRED`; otherwise the posture is `PUBLIC`. A `RELEASED` restriction no longer constrains the posture. The posture is first computed when the collection comes into existence at accession, and it is recomputed whenever a presidential restriction is created or released and whenever a declassification review completes.

The recompute carries a cascade. On any recompute that changes a collection's posture into `PUBLIC`, every FOIA request against that collection still sitting in `RECEIVED` or `IN_REVIEW` is transitioned to `CLOSED` with `close_reason` set to `RECORDS_MADE_PUBLIC`, and each such request's `version` increments. The cascade exists because those requests were filed only to pry open restricted records; once the records are public, the requests are moot. A recompute that leaves the posture non-public, or that changes it between the two restricted postures, closes nothing.

### 2.9. Records Age and Anniversary Arithmetic

Several rules need the whole-year age of a body of records. Age in years is computed from the logical clock and a `records_cutoff_date` as follows: take the clock's year minus the cutoff's year, then subtract one if the clock's month-and-day has not yet reached the cutoff's month-and-day — that is, the anniversary of the cutoff must already have occurred in the clock's year for the year to count. When the cutoff falls on February 29 and the clock's year is not a leap year, the anniversary is treated as February 28. All "N years later" arithmetic in this document (the transfer lag, the two-year researcher card validity, and similar spans) uses this same anniversary rule, and every age or lag threshold in the system is inclusive of its boundary unless a rule explicitly says otherwise.

### 2.10. Numeric Precision and Rounding

Reproduction fees are integer numbers of cents, never fractional. Rounding is round half up, and it occurs at exactly two points in the fee computation and nowhere else: once per tier when the academic affiliation discount is applied, and once after the rush multiplier is applied to the discounted sum. §3.8 gives the full computation. Priority and backlog scores are integer points with no rounding at any step. Where a count is scaled by division (the reproduction-pages term of the digitization priority), the division is rounded down to a whole number before it contributes points.

## 3. Business Logic & Workflows

### 3.1. Agency Onboarding and the Schedule Lifecycle

Everything begins with an agency. A `PlatformAdmin` registers each federal agency with a short `agency_code` (such as DOJ or CIA) and a full `name`. The `agency_code` must be unique across all agencies; a duplicate registration is rejected with `ERR_AGENCY_CODE_EXISTS` (409).

With its agency registered, a `RecordsOfficer` of that agency drafts a **records schedule** — the legal instrument that declares a body of records permanent or temporary and sets the terms of their eventual transfer. Creation supplies `agency_id`, `schedule_number`, `title`, `records_domain`, `disposition`, `classification_default`, and conditionally `transfer_lag_years`. The `agency_id` must equal the caller's `X-User-ID`, because a records officer acts only for their own agency; otherwise the creation fails with `ERR_OWNERSHIP_MISMATCH`. The `schedule_number` is an agency-local identifier, unique per agency — a second schedule with the same number under the same agency is rejected with `ERR_SCHEDULE_NUMBER_EXISTS` (409). The `records_domain` is either `FEDERAL` or `PRESIDENTIAL`; presidential-domain schedules eventually produce presidential collections, which are the only collections that may carry presidential restrictions. The `disposition` is either `PERMANENT` or `TEMPORARY`, and only `PERMANENT` schedules may ever underlie a transfer. The `transfer_lag_years` field — the number of years after the records' cutoff when permanent records may be accessioned — is required if and only if the disposition is `PERMANENT`, and must lie between 0 and 50 inclusive. The `classification_default` is one of `NONE`, `CONFIDENTIAL`, `SECRET`, or `TOP_SECRET`, and it is copied onto the collection at accession as its starting classification. A new schedule is born in `DRAFT` status.

Submission moves the schedule from `DRAFT` to `SUBMITTED`. Only the owning `RecordsOfficer` may submit, again verified against `X-User-ID`. An `AppraisalArchivist` then appraises a `SUBMITTED` schedule, moving it to `APPRAISED`; appraising a schedule in any other status is rejected with `ERR_INVALID_STATE`. Appraisal records the archivist's `appraisal_recommendation` — either `APPROVE` or `RETURN` — supplied with the call, and stamps `appraiser_id` with the archivist's `X-User-ID`.

Decision belongs to a different desk. A `ChiefArchivist` decides an `APPRAISED` schedule by supplying a `decision` of `APPROVE` or `RETURN` and an optional free-text `decision_note`. Deciding a schedule that is not `APPRAISED` is rejected with `ERR_SCHEDULE_NOT_APPRAISED`. Segregation of duties applies at this step: the decider's `X-User-ID` must differ from the recorded `appraiser_id`, or the call fails with `ERR_SEGREGATION_OF_DUTIES` (403) — the archivist who appraised a schedule may never be the one who decides it. A decision of `APPROVE` moves the schedule to `APPROVED`, its terminal state, and only then can it underlie transfers. A decision of `RETURN` moves it to `RETURNED`. Either way, `decided_by` is stamped with the decider's `X-User-ID` and the note is recorded.

`RETURNED` is not the end. The owning `RecordsOfficer` may resubmit a returned schedule, moving it back to `SUBMITTED`, and may do so any number of times — this revision cycle is how schedules are repaired after an unfavorable decision. Resubmission clears the prior round's markings: `appraiser_id`, `appraisal_recommendation`, `decided_by`, and `decision_note` all reset to null, and the schedule re-enters appraisal with a clean slate. Every submit, appraise, decide, and resubmit advances the schedule's `version` by one.

### 3.2. Transfers: Initiation, Metadata Validation, Withdrawal

Once a schedule is `APPROVED`, the owning agency can move records under it. A `RecordsOfficer` initiates a **transfer** by supplying `schedule_id`, `agency_id`, `transfer_method`, `metadata_standard`, `unit_count`, `records_cutoff_date`, and the method-specific fields `linear_feet` or `checksum_manifest`. The body's references are validated in declared input order — `schedule_id` first, then `agency_id` — and each unknown id yields its entity-specific 404. The `agency_id` must equal the caller's `X-User-ID` (`ERR_OWNERSHIP_MISMATCH`), and it must also equal the schedule's own `agency_id` — a transfer filed under another agency's schedule is rejected with `ERR_AGENCY_MISMATCH` (409).

Two business-shape rules attach to the schedule at this point: it must be `APPROVED` (`ERR_SCHEDULE_NOT_APPROVED`, 409) and its disposition must be `PERMANENT` (`ERR_NOT_PERMANENT_DISPOSITION`, 409) — a temporary schedule can never underlie a transfer. Method and metadata must agree as well. The `transfer_method` is `PHYSICAL` or `ELECTRONIC`; the `metadata_standard` is one of `EAD_2002`, `MODS_3_7`, or `PREMIS_3_0`. An `ELECTRONIC` transfer requires the `PREMIS_3_0` standard, while a `PHYSICAL` transfer requires `EAD_2002` or `MODS_3_7`; an incompatible pairing is rejected with `ERR_METADATA_STANDARD_MISMATCH` (422). Each method also has a required payload: a `PHYSICAL` transfer must supply `linear_feet` greater than zero, and an `ELECTRONIC` transfer must supply a non-empty `checksum_manifest` reference; a missing or empty requirement is rejected with `ERR_METHOD_REQUIREMENT_MISSING` (422). The `unit_count` — containers for a physical transfer, files for an electronic one — must be at least 1, and it later becomes the collection's `units_total`. The `records_cutoff_date` records the end date of the records in the transfer; it drives both the transfer-lag gate at accession and the collection's age for every age-dependent rule downstream. A successfully created transfer starts in `INITIATED` status.

Metadata validation is a separate, repeatable step. The owning `RecordsOfficer` submits a list of `metadata_elements` — the element names present in the transfer's descriptive metadata. The system holds, for each metadata standard, a defined set of required element names: `EAD_2002` requires `title`, `creator`, `date`, `extent`, and `scope_content`; `MODS_3_7` requires `title`, `creator`, `date`, `identifier`, and `type_of_resource`; and `PREMIS_3_0` requires `object_identifier`, `object_category`, `preservation_level`, `original_name`, and `format_name`. When the submission contains every required element of the declared `metadata_standard`, the transfer moves to `VALIDATED`: `submitted_metadata_elements` stores the submitted names and `last_missing_elements` becomes empty. When required elements are missing, the transfer moves to `DEFICIENT` instead, and `last_missing_elements` carries the missing element names, sorted, so the agency knows exactly what to fix. A `DEFICIENT` transfer may resubmit metadata: a now-complete submission lands it in `VALIDATED`, while a still-incomplete one keeps it in `DEFICIENT` with `last_missing_elements` refreshed — a deliberate self-loop that permits incremental repair. Each metadata submission, complete or not, advances the transfer's `version`.

A transfer that will not proceed may be withdrawn. The owning `RecordsOfficer` may withdraw a transfer from `INITIATED`, `DEFICIENT`, or `VALIDATED`, moving it to the terminal `WITHDRAWN` status. An accessioned transfer can never be withdrawn.

### 3.3. Accession: The Birth of a Collection

Accession is the legal moment custody passes to the Archives, and it belongs to a `ProcessingArchivist`, who supplies a `receipt_note` with the accession call. Two gates guard it, in ladder order: the transfer must be `VALIDATED` (`ERR_TRANSFER_NOT_VALIDATED`, 409), and the schedule's transfer lag must have elapsed. The lag gate compares the logical clock against the anniversary of `records_cutoff_date` shifted forward by the schedule's `transfer_lag_years`: accession is allowed when the clock has reached that anniversary, inclusively — a transfer whose lag anniversary is exactly today may be accessioned today — and is rejected with `ERR_TRANSFER_LAG_NOT_ELAPSED` (409) while the clock still stands before it.

A successful accession does far more than flip a status. In the same transaction, the system creates the transfer's **Collection** — exactly one collection per accessioned transfer, with `transfer_id` recording the link. The new collection inherits `schedule_id`, `agency_id`, `records_domain`, and `records_cutoff_date` from the transfer and its schedule; its `classification_level` is copied from the schedule's `classification_default`; `units_total` is set from the transfer's `unit_count`. Its `processing_status` starts at `UNPROCESSED`, its `digitization_status` at `NOT_REQUESTED`, its `digitization_priority` at null, and its `declass_outcome` at `NONE`. Its `restriction_posture` is computed immediately under the §2.8 derivation — with no presidential restrictions yet, a collection accessioned with classification `NONE` is born `PUBLIC`, and any other classification yields `CLASSIFIED_REVIEW_REQUIRED`. Its three demand counters — `pull_count_total`, `repro_pages_fulfilled`, and `foia_release_count` — all start at zero.

Accession also stamps the collection's **backlog score**, computed once at this moment and stored on `backlog_score` as a snapshot of processing urgency. The score awards ten points per whole year of records age (computed under §2.9 against the logical clock), counting at most sixty years; adds a classification weight of 0 for `NONE`, 5 for `CONFIDENTIAL`, 15 for `SECRET`, or 30 for `TOP_SECRET`; and adds a further 20 points when the collection's domain is `PRESIDENTIAL`. The result is an integer number of points. A thirty-year-old `SECRET` federal collection, for example, accrues 300 age points and 15 classification points for a backlog score of 315.

On the transfer itself, accession moves the status from `VALIDATED` to `ACCESSIONED` (terminal), stamps `accessioned_at` with the logical clock, records the new collection's id on `collection_id`, and advances `version`.

### 3.4. Processing, Description, and the Digitization Queue

A collection's life after accession runs along two parallel dimensions on the same record. The **processing dimension** (`processing_status`) walks `UNPROCESSED → PROCESSING → DESCRIBED → PUBLISHED`. The **digitization dimension** (`digitization_status`) walks `NOT_REQUESTED → QUEUED → DIGITIZED`. The two evolve independently, except where a transition explicitly gates on the other dimension, and `restriction_posture` evolves alongside both as §2.8 describes.

A `ProcessingArchivist` claims an `UNPROCESSED` collection by beginning processing; the collection moves to `PROCESSING` and `assigned_archivist_id` is stamped with the archivist's `X-User-ID`. Beginning processing on a collection in any other state is rejected with `ERR_INVALID_STATE`. While `PROCESSING`, the archivist completes the description by supplying the three description elements — `scope_note`, `arrangement_note`, and `container_list_summary` — all of which must be non-empty; if any is missing or empty, the call is rejected with `ERR_DESCRIPTION_INCOMPLETE` (422). A complete description moves the collection to `DESCRIBED` and stores the three notes, making the collection searchable and eligible for researcher-facing operations.

Digitization starts only for described, open records. A `ProcessingArchivist` may enqueue a collection for digitization when three conditions all hold: `processing_status` is `DESCRIBED` (`ERR_COLLECTION_NOT_DESCRIBED`, 409, otherwise), `restriction_posture` is `PUBLIC` (`ERR_COLLECTION_RESTRICTED`, 403, otherwise), and `digitization_status` is still `NOT_REQUESTED` (`ERR_INVALID_STATE` otherwise). Enqueueing moves the digitization dimension to `QUEUED` and stamps `digitization_priority` with a snapshot of the demand-weighted priority score.

That priority score combines age and demonstrated demand. It awards 2 points per whole year of records age, counting at most 50 years; plus 3 points per fulfilled pull request against the collection, counting at most 20 pulls; plus 5 points per FOIA release the collection has had, counting at most 10 releases; plus 1 point per 50 fulfilled reproduction pages, where the page count is capped at 500 before being divided by 50 and rounded down; plus a bonus of 25 points when the collection's `declass_outcome` is `DECLASSIFIED`. All inputs come from the collection's own fields — `records_cutoff_date` for age, the demand counters `pull_count_total`, `repro_pages_fulfilled`, and `foia_release_count`, and `declass_outcome` — evaluated against the logical clock. A thirty-year-old collection with 4 fulfilled pulls, 2 FOIA releases, no fulfilled reproduction pages, and a `DECLASSIFIED` outcome scores 60 age points plus 12 pull points plus 10 FOIA points plus 0 page points plus the 25-point bonus: 107. The score is not frozen at enqueue: while a collection remains `QUEUED`, any mutation of `pull_count_total`, `repro_pages_fulfilled`, or `foia_release_count` recomputes `digitization_priority` on the spot.

The digitization queue itself is a computed read. It lists exactly the collections whose `digitization_status` is `QUEUED`, ordered by `digitization_priority` descending, then by `records_cutoff_date` ascending so that older records come first on a tie, then by `created_at` ascending as the final tie-break — a collection's `id` is never used for ordering. Standard `limit`/`offset` pagination applies over that sorted list. This read is available to `PlatformAdmin`, `ProcessingArchivist`, `DeclassReviewer`, `ChiefArchivist`, and `ResearchRoomStaff`.

A `ProcessingArchivist` marks a `QUEUED` collection's digitization complete, moving it to `DIGITIZED`; completing a collection that is not `QUEUED` is rejected with `ERR_DIGITIZATION_NOT_QUEUED` (409). Publication is the final step and belongs to the `ChiefArchivist`: publishing digital surrogates moves a `DESCRIBED` collection to `PUBLISHED`, but only when the digitization dimension has reached `DIGITIZED` (`ERR_DIGITIZATION_NOT_READY`, 409, otherwise) and the posture is `PUBLIC` (`ERR_COLLECTION_RESTRICTED` otherwise). Each transition on either dimension advances the collection's `version`.

### 3.5. Declassification Review and Equity Referrals

Classified collections leave `CLASSIFIED_REVIEW_REQUIRED` only through a **declassification review**, which comes in two flavors. Opening a review of either flavor supplies `collection_id`, a `review_type` of `SYSTEMATIC` or `MANDATORY`, and the concurrency token `expected_collection_version` described in §2.7. A `SYSTEMATIC` review is the age-triggered, archivist-initiated kind: a `ProcessingArchivist` opens it against a collection whose records have reached the systematic-review age. A `MANDATORY` review is the researcher-driven kind — the mandatory declassification review request — opened by a `Researcher` who names themselves in `requester_researcher_id` and supplies a non-empty `justification` reasonably describing the records sought. For a mandatory review, the `requester_researcher_id` must equal the caller's `X-User-ID` (`ERR_OWNERSHIP_MISMATCH`), and the referenced researcher must be `ACTIVE` (`ERR_RESEARCHER_NOT_ACTIVE`, with the lazy expiry evaluation of §2.4 applied first). For a systematic review, `requester_researcher_id` and `justification` stay null.

Three gates apply to both flavors, and their order matters. First, at the stale-version rung of §2.6, the request must carry `expected_collection_version` equal to the collection's current `version`, or it is rejected with `ERR_STALE_COLLECTION_VERSION` (412) — see §2.7. Second, a collection may host at most one review in `OPEN` or `IN_PROGRESS` at a time; opening a second concurrent review is rejected with `ERR_REVIEW_ALREADY_OPEN` (409). Third, the collection must actually require review: the posture must be `CLASSIFIED_REVIEW_REQUIRED` — for a systematic review this means the collection still carries a classification level other than `NONE` — and a request against a collection that does not is rejected with `ERR_COLLECTION_NOT_RESTRICTED` (409). The systematic flavor adds its age gate on top: the records' whole-year age under §2.9 must be at least 25 years, with the boundary inclusive, so a collection whose twenty-fifth anniversary is exactly today is eligible; a younger collection is rejected with `ERR_SYSTEMATIC_REVIEW_PREMATURE` (409). A newly opened review starts in `OPEN` status, and its creation records review demand against the collection by advancing the collection's `version` by one — which is exactly why the OCC check exists.

A `DeclassReviewer` begins an `OPEN` review, moving it to `IN_PROGRESS` and stamping `lead_reviewer_id` with their `X-User-ID`; beginning a review in any other status is rejected with `ERR_INVALID_STATE`.

While the review is `IN_PROGRESS`, the reviewer may issue **equity referrals** to other agencies whose classified equities appear in the records. Referrals are created in bulk: the call carries a list of `agency_ids`, and the operation is atomic — if any id is unknown (`ERR_AGENCY_NOT_FOUND`), if the list contains a duplicate, or if a referral already exists for the same review and agency (`ERR_DUPLICATE_REFERRAL`, 409), the whole request is aborted and no referral is created. Issuing referrals against a review that is not `IN_PROGRESS` is rejected with `ERR_REVIEW_NOT_IN_PROGRESS`. Each created referral starts in `SENT` status, with `sent_at` stamped from the logical clock, `response_due_at` computed as 21 days after `sent_at`, and its `decision` remaining null until the agency answers.

The referred agency answers through its `AgencyLiaison`, whose `X-User-ID` must equal the referral's `agency_id` (`ERR_OWNERSHIP_MISMATCH`). The parent review must still be `IN_PROGRESS` (`ERR_REVIEW_NOT_IN_PROGRESS`), and the referral must still be `SENT` — answering an already-answered referral is rejected with `ERR_REFERRAL_ALREADY_RESPONDED` (409). The response carries a `decision` of `DECLASSIFY` or `EXEMPT`; an `EXEMPT` decision must also carry a non-empty `exemption_code` (`ERR_EXEMPTION_REQUIRED`, 422). Responding moves the referral to `RESPONDED` and records `decision`, `exemption_code`, and `responded_at`.

Completion closes the loop. A `DeclassReviewer` completes an `IN_PROGRESS` review — moving it to its terminal `COMPLETED` status — by supplying their own `reviewer_assessment` of `DECLASSIFY` or `EXEMPT` — an `EXEMPT` assessment must carry an `exemption_code` (`ERR_EXEMPTION_REQUIRED`). Completing a review in any other status is rejected with `ERR_REVIEW_NOT_IN_PROGRESS`. Completion also requires that every referral of the review be either `RESPONDED` or overdue. A `SENT` referral is overdue only when the logical clock is strictly later than its `response_due_at`: at exactly the due instant the referral is not overdue and still blocks completion, and the completing call is rejected with `ERR_REFERRALS_OUTSTANDING` (409). An overdue `SENT` referral is treated as concurrence — silence is no objection — and is ignored in the outcome computation.

The completion stamps `outcome` according to a fixed rule. If the reviewer's own assessment is `EXEMPT`, the outcome is `EXEMPT_RETAINED`. Otherwise, if at least one `RESPONDED` referral decided `EXEMPT`, the outcome is `PARTIAL`. Otherwise the outcome is `DECLASSIFIED`. The review's `exemption_codes` field becomes the sorted set containing the assessment's exemption code (when the assessment is `EXEMPT`) together with the exemption code of every `EXEMPT` referral; `completed_at` is stamped from the logical clock; and the review's `version` advances.

The outcome then cascades into the collection within the same transaction. A `DECLASSIFIED` outcome clears the collection's `classification_level` to `NONE` and stamps `declass_outcome` as `DECLASSIFIED`. A `PARTIAL` or `EXEMPT_RETAINED` outcome stamps `declass_outcome` with that value and leaves `classification_level` unchanged. In every case the collection's `restriction_posture` is recomputed under §2.8 and its `version` advances — and if the recompute flips the posture to `PUBLIC`, the posture-flip cascade fires, closing the collection's still-pending FOIA requests as §2.8 describes.

### 3.6. Presidential Restrictions

Presidential records carry statutory access restrictions of their own, managed entirely by the `ChiefArchivist`. A restriction is imposed on a specific collection by supplying `collection_id` and a `category`. The target collection's `records_domain` must be `PRESIDENTIAL`; imposing a restriction on a federal-domain collection is rejected with `ERR_NOT_PRESIDENTIAL_RECORDS` (409). The category is one of six statutory grounds, spelled exactly: `P1_NATIONAL_SECURITY`, `P2_APPOINTMENTS`, `P3_STATUTORY`, `P4_TRADE_SECRETS`, `P5_CONFIDENTIAL_ADVICE`, and `P6_PERSONAL_PRIVACY`. At most one non-`RELEASED` restriction may exist per collection and category: a second live restriction of the same category on the same collection is rejected with `ERR_DUPLICATE_RESTRICTION_CATEGORY` (409). A new restriction starts in `IMPOSED` status, and its creation immediately recomputes the collection's `restriction_posture` — under §2.8, any live restriction forces `PRESIDENTIAL_HOLD` — advancing the collection's `version` in the same transaction.

Before the former president's office can be notified, a representative must be designated. Designating supplies `representative_id` and is an in-state update: the restriction remains `IMPOSED`, the designation is recorded, and the restriction's `version` advances. Designating on a restriction no longer `IMPOSED` is rejected with `ERR_INVALID_STATE`.

Notification moves the restriction from `IMPOSED` to `NOTIFIED`; notifying a restriction that is no longer `IMPOSED` is rejected with `ERR_INVALID_STATE`. It requires a designated representative — notifying without one is rejected with `ERR_REPRESENTATIVE_REQUIRED` (409) — and stamps `notified_at` from the logical clock. A statutory cooling period then runs: release is allowed only once the clock has reached `notified_at` plus 30 days, with the boundary inclusive, so a release at exactly the thirtieth day proceeds while anything earlier is rejected with `ERR_COOLING_PERIOD_ACTIVE` (409). Releasing a restriction that was never notified is rejected with `ERR_RESTRICTION_NOT_NOTIFIED` (409).

Release moves the restriction to its terminal `RELEASED` status and stamps `released_at`. It then recomputes the collection's `restriction_posture` and advances the collection's `version`: when the released restriction was the last live one and no classification remains, the posture flips to `PUBLIC`, and the §2.8 posture-flip cascade closes the collection's pending FOIA requests with `close_reason` of `RECORDS_MADE_PUBLIC`.

### 3.7. Researcher Registration and the Research Room

Anyone may walk in off the street, so to speak: an `Anonymous` caller self-registers as a researcher by supplying `full_name`, `email`, `affiliation`, and `id_document`. The email must be unique across all registrations — a duplicate is rejected with `ERR_EMAIL_EXISTS` (409) — and `id_document`, the identity-document reference, must be non-empty (`ERR_INVALID_REQUEST` otherwise). The `affiliation` is one of `ACADEMIC`, `JOURNALIST`, `GENEALOGIST`, `COMMERCIAL`, or `GOVERNMENT`; affiliation is not decorative, because `ACADEMIC` researchers receive the reproduction-fee discount of §3.8. A new registration starts `PENDING`.

A `ResearchRoomStaff` operator activates a `PENDING` registration at the desk, moving it to `ACTIVE` and stamping `card_expires_at` — null until this first activation — as the activation instant plus two years under anniversary arithmetic; the research card is valid for two years. The same activation call renews an `EXPIRED` registration back to `ACTIVE` with a fresh two-year `card_expires_at`. Expiry itself needs no call: on any load of a registration, if the clock has reached or passed `card_expires_at`, the registration is persisted as `EXPIRED` right there — at exactly the expiry instant the card is expired, while one second earlier it is still active — and its `version` advances when that lazy transition fires. Suspension, by contrast, is terminal and arrives only through the late-return cascade described below; a `SUSPENDED` registration records its `suspension_reason` and has no way back.

An `ACTIVE` researcher reserves records for a reading-room visit by filing a **pull request** naming `researcher_id`, `collection_id`, the inclusive unit range `unit_start` through `unit_end`, and a `visit_date`. The `researcher_id` must equal the caller's `X-User-ID` (`ERR_OWNERSHIP_MISMATCH`). Pull creation runs the densest gate cascade in the system, and the checks fire in a fixed order. After existence, ownership, and the active-researcher rung (`ERR_RESEARCHER_NOT_ACTIVE`), the collection must be open: its posture must be `PUBLIC` (`ERR_COLLECTION_RESTRICTED`, 403). The `visit_date` must then fall within the booking window — on or after the clock's current instant and no later than 30 days out (`ERR_VISIT_DATE_OUT_OF_WINDOW`, 409). The collection must be described: `processing_status` must be `DESCRIBED` or `PUBLISHED` (`ERR_COLLECTION_NOT_DESCRIBED`, 409). Five reservation checks then run in this exact sub-order. First, the unit range must lie inside the collection's holdings: `unit_start` at least 1, `unit_end` at most the collection's `units_total`, and `unit_start` not greater than `unit_end` (`ERR_UNIT_RANGE_INVALID`, 400). Second, the reserved span — the count of units from `unit_start` through `unit_end` inclusive — may not exceed 24 units (`ERR_UNIT_SPAN_LIMIT_EXCEEDED`, 409). Third, the reservation must not collide with another pull: a conflict exists when another pull request on the same collection, in `REQUESTED` or `PULLED` status, reserves a unit range sharing at least one integer unit with the new range and occupies a time window sharing at least one instant with the new pull's window (`ERR_UNIT_RESERVATION_CONFLICT`, 409). A pull's occupation window is the half-open interval from its `visit_date` through two days later; adjacent unit ranges such as units 10–20 versus 21–30 share no unit and never conflict, disjoint windows never conflict even for identical ranges, and pulls on different collections never conflict. Fourth, reading-room seat capacity: a pull occupies one seat on each UTC day of its occupation window — the visit day and the following day — and for each of those days the total number of seated pulls across all researchers and all collections, counting `REQUESTED` and `PULLED` pulls whose windows cover that day, must remain within the room's 8 seats; the eighth pull seated on a day succeeds and the ninth is rejected (`ERR_READING_ROOM_CAPACITY`, 409). Fifth and last, the researcher's own active-pull limit: a researcher may hold fewer than 3 pulls in `REQUESTED` or `PULLED` status, so a third active pull succeeds while a fourth is rejected (`ERR_ACTIVE_PULL_LIMIT_EXCEEDED`, 409); `RETURNED` and `CANCELLED` pulls release their slot. A pull that clears every gate starts `REQUESTED`, with `due_back_at` computed as its `visit_date` plus 24 hours.

`ResearchRoomStaff` fulfill a `REQUESTED` pull, moving it to `PULLED`; fulfilling anything else is rejected with `ERR_PULL_NOT_FULFILLABLE` (409). Fulfillment also feeds the collection's demand profile: `pull_count_total` increments by one, the collection's `version` advances, and if the collection is `QUEUED` for digitization its `digitization_priority` is recomputed on the spot.

Returning a pull is the consequential act. `ResearchRoomStaff` return a `PULLED` pull, moving it to `RETURNED`; returning anything else is rejected with `ERR_PULL_NOT_RETURNABLE` (409). The return stamps `returned_at` from the logical clock and computes `late_return`: the pull is late when `returned_at` falls strictly after `due_back_at` — a return at exactly the due instant is on time. A late return suspends the researcher: their registration moves to `SUSPENDED` with `suspension_reason` set to `LATE_RETURN`, and the suspension cascades in the same transaction — every sibling pull request of that researcher still in `REQUESTED` is cancelled, and every reproduction request of theirs still in `QUOTED` is cancelled, freeing the pages those reproductions had committed against the daily quota. Each cancelled sibling advances its own `version`.

### 3.8. Reproduction Services and the Fee Schedule

Beyond the reading room, an `ACTIVE` researcher may order copies. Creating a **reproduction request** supplies `researcher_id` (which must equal the caller's `X-User-ID`), `collection_id`, `page_count`, `format`, and optionally `rush`. The same described-and-open gates as pulls apply in ladder order: the researcher must be `ACTIVE` (`ERR_RESEARCHER_NOT_ACTIVE`), the collection's posture must be `PUBLIC` (`ERR_COLLECTION_RESTRICTED`), and its `processing_status` must be `DESCRIBED` or `PUBLISHED` (`ERR_COLLECTION_NOT_DESCRIBED`). The `page_count` must be at least 1. The `format` is one of `DIGITAL_SCAN`, `CERTIFIED_COPY`, or `PHOTOPRINT`; in this version of the rate card, format selects no rate — every format bills identically. `rush` defaults to false when omitted.

A daily quota protects the reproduction lab. Summed across the researcher's requests created on the same UTC calendar day as the logical clock and still counted — those in `QUOTED`, `PAID`, or `FULFILLED` status — the committed pages plus the new request's `page_count` must not exceed 200 pages, with the boundary inclusive: a request that brings the day to exactly 200 pages succeeds, and one page beyond is rejected with `ERR_DAILY_PAGE_LIMIT_EXCEEDED` (409). `CANCELLED` requests are excluded from the sum, so cancelling restores quota immediately.

The fee is computed once, at creation, and stored on `fee_cents` in integer cents; it never drifts afterward. Pages price in three tiers: the first 20 pages at 80 cents per page, the next 80 pages (pages 21 through 100) at 50 cents per page, and every page beyond 100 at 25 cents per page. For an `ACADEMIC` researcher, the affiliation discount applies **per tier**: each tier's subtotal is multiplied by 0.85 and rounded half up to whole cents, and the discounted tiers are then summed. For any other affiliation the tier subtotals are simply summed. Rush handling applies **last**: the summed amount is multiplied by 1.5 and rounded half up to whole cents. This order is canonical — discount per tier first, rush multiplier after — and the rush multiplier is never applied to a tier before the discount, because the two orders diverge whenever a discounted-and-rushed tier lands on a fractional cent. Worked through precisely: 25 pages for an `ACADEMIC` researcher with rush handling gives a first tier of 1600 cents discounted to 1360, a second tier of 250 cents discounted to 213 (250 times 0.85 is 212.5, rounding half up), a discounted sum of 1573, and a final fee of 2360 cents (1573 times 1.5 is 2359.5, rounding half up). A new reproduction request starts in `QUOTED` status.

Payment belongs to the researcher. The owning `Researcher` pays a `QUOTED` request (`ERR_OWNERSHIP_MISMATCH` for anyone else; `ERR_REPRO_NOT_PAYABLE`, 409, if it is not `QUOTED`), recording a `payment_reference` as the request moves to `PAID`. Fulfillment belongs to `ResearchRoomStaff`: fulfilling a `PAID` request moves it to `FULFILLED` — attempting fulfillment while the request is still `QUOTED` is rejected with `ERR_REPRO_NOT_PAID` (402), and attempting it from a terminal state is rejected with `ERR_INVALID_STATE`. Fulfillment adds the request's `page_count` to the collection's `repro_pages_fulfilled`, advances the collection's `version`, and recomputes `digitization_priority` when the collection is `QUEUED`. Finally, the owning researcher may cancel a request while it is still `QUOTED` (`ERR_REPRO_NOT_CANCELLABLE`, 409, otherwise); cancellation moves it to `CANCELLED` and frees its committed pages from the daily quota. The suspension cascade of §3.7 cancels `QUOTED` requests system-side with the same freeing effect.

### 3.9. FOIA: Intake, Adjudication, and Appeal

When records are still restricted, the Freedom of Information Act provides the compulsion. An `ACTIVE` researcher files a **FOIA request** by supplying `researcher_id` (equal to the caller's `X-User-ID`), `collection_id`, and a `description_of_records` giving a non-empty, reasonable description of what is sought. FOIA exists only for restricted records: the collection's posture must be `CLASSIFIED_REVIEW_REQUIRED` or `PRESIDENTIAL_HOLD`, and a request filed against a `PUBLIC` collection — whose records are already open — is rejected with `ERR_FOIA_NOT_REQUIRED` (409). A new request starts in `RECEIVED`.

Initial adjudication belongs to a `FoiaOfficer`, who supplies a `decision` of `GRANT`, `PARTIAL`, or `DENY` against a request in `RECEIVED` — or, after a remand, in `IN_REVIEW`. A `GRANT` moves the request to `GRANTED`; a `PARTIAL` moves it to `PARTIAL_GRANT`; a `DENY` moves it to `DENIED`. Partial grants and denials must say why: `claimed_exemptions` must be a non-empty subset of the recognized exemption codes `B1`, `B3`, and `B5` (`ERR_EXEMPTION_REQUIRED`, 422, otherwise), while a pure grant claims none. Every adjudication stamps `adjudicator_id` with the officer's `X-User-ID` and `decided_at` with the logical clock — and each re-adjudication after a remand restamps both. Adjudicating a request that already stands decided and has not been remanded — one in `GRANTED`, `PARTIAL_GRANT`, or `DENIED` — is rejected with `ERR_FOIA_ALREADY_ADJUDICATED` (409). A grant also feeds the collection's demand profile: `foia_release_count` increments by one, the collection's `version` advances, and a `QUEUED` collection's `digitization_priority` recomputes on the spot.

A researcher who receives less than everything may appeal. The owning `Researcher` appeals a request in `PARTIAL_GRANT` or `DENIED` (`ERR_OWNERSHIP_MISMATCH` for anyone else; `ERR_APPEAL_NOT_ALLOWED_STATE`, 409, from any other status), supplying an `appeal_reason`. The appeal window is thirty days: the appeal must arrive while the clock stands at or before `decided_at` plus 30 days, with the boundary inclusive — an appeal at exactly the thirtieth day is timely, and one a day later is rejected with `ERR_APPEAL_WINDOW_CLOSED` (409). A timely appeal moves the request to `APPEALED` and records the reason.

Appellate decision belongs to a different authority. A `FoiaAppealsOfficer` decides an `APPEALED` request (`ERR_FOIA_NOT_APPEALED`, 409, otherwise) by supplying an `appeal_decision` of `GRANT`, `UPHOLD`, or `REMAND`. Segregation of duties binds here: the appeals decider's `X-User-ID` must differ from the recorded `adjudicator_id`, or the call fails with `ERR_SEGREGATION_OF_DUTIES` (403). All three outcomes stamp `appeal_decider_id` and `appeal_decision`. A `GRANT` moves the request to its terminal `APPEAL_GRANTED` and, like an initial grant, increments the collection's `foia_release_count`, advances the collection's `version`, and recomputes a `QUEUED` priority. An `UPHOLD` moves it to terminal `APPEAL_UPHELD`. A `REMAND` sends the request back to `IN_REVIEW` and increments `remand_count` — opening the remand loop, in which the request is adjudicated afresh (restamping `adjudicator_id` and `decided_at`), may be appealed again, and may cycle any number of times. `GRANTED`, `APPEAL_GRANTED`, `APPEAL_UPHELD`, and `CLOSED` are the terminal states.

One closure needs no officer at all: when a declassification completion or a presidential-restriction release flips the collection's posture to `PUBLIC`, the §2.8 cascade moves every request of that collection still in `RECEIVED` or `IN_REVIEW` to `CLOSED` with `close_reason` of `RECORDS_MADE_PUBLIC`.

## 4. Endpoint Definitions

Operations that create a new resource — registering an agency, creating a schedule, initiating a transfer, opening a review, issuing referrals, registering a researcher, filing a pull, reproduction, or FOIA request, or imposing a presidential restriction — answer `201 Created`. Operations that act on an existing resource (state transitions, designations, payments, cancellations, the clock set) and all reads answer `200 OK`. Request payloads, preconditions, and side effects are specified by the §3 narratives; the table below is the routing and authorization summary only. List endpoints accept the filter parameters named in §3 (such as `agency_id`, `schedule_id`, `transfer_id`, `collection_id`, `review_id`, `researcher_id`, `requester_researcher_id`, `status`, `processing_status`, and `restriction_posture`) plus `limit` and `offset`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/records/agencies` | Register a federal agency | PlatformAdmin |
| GET | `/records/agencies/{id}` | Get one agency | All roles except Anonymous |
| POST | `/records/schedules` | Create a records schedule (DRAFT) | RecordsOfficer |
| GET | `/records/schedules` | List schedules with filters and pagination | All roles except Anonymous |
| GET | `/records/schedules/{id}` | Get one schedule | All roles except Anonymous |
| POST | `/records/schedules/{id}/submit` | Submit a DRAFT schedule; also resubmits a RETURNED schedule | RecordsOfficer |
| POST | `/records/schedules/{id}/appraise` | Appraise a SUBMITTED schedule | AppraisalArchivist |
| POST | `/records/schedules/{id}/decide` | Decide an APPRAISED schedule (APPROVE or RETURN) | ChiefArchivist |
| POST | `/records/transfers` | Initiate a transfer under an APPROVED PERMANENT schedule | RecordsOfficer |
| GET | `/records/transfers` | List transfers with filters and pagination | All roles except Anonymous |
| GET | `/records/transfers/{id}` | Get one transfer | All roles except Anonymous |
| POST | `/records/transfers/{id}/submit-metadata` | Submit metadata element names for validation | RecordsOfficer |
| POST | `/records/transfers/{id}/accession` | Accession a VALIDATED transfer; creates the Collection | ProcessingArchivist |
| POST | `/records/transfers/{id}/withdraw` | Withdraw a non-accessioned transfer | RecordsOfficer |
| GET | `/records/collections` | List collections with filters and pagination | All roles except Anonymous |
| GET | `/records/collections/{id}` | Get one collection | All roles except Anonymous |
| POST | `/records/collections/{id}/begin-processing` | Claim an UNPROCESSED collection for processing | ProcessingArchivist |
| POST | `/records/collections/{id}/complete-description` | Store description elements; mark the collection searchable | ProcessingArchivist |
| POST | `/records/collections/{id}/enqueue-digitization` | Enqueue a DESCRIBED, PUBLIC collection for digitization | ProcessingArchivist |
| POST | `/records/collections/{id}/complete-digitization` | Mark a QUEUED collection's digitization complete | ProcessingArchivist |
| POST | `/records/collections/{id}/publish-digital` | Publish digital surrogates to public access | ChiefArchivist |
| GET | `/records/digitization-queue` | QUEUED collections sorted by priority, cutoff date, creation time | PlatformAdmin, ProcessingArchivist, DeclassReviewer, ChiefArchivist, ResearchRoomStaff |
| POST | `/records/declass-reviews` | Open a declassification review (SYSTEMATIC or MANDATORY) | ProcessingArchivist, Researcher |
| GET | `/records/declass-reviews` | List declassification reviews with filters and pagination | All roles except Anonymous |
| GET | `/records/declass-reviews/{id}` | Get one declassification review | All roles except Anonymous |
| POST | `/records/declass-reviews/{id}/begin` | Begin an OPEN review | DeclassReviewer |
| POST | `/records/declass-reviews/{id}/referrals` | Create equity referrals to other agencies (bulk, atomic) | DeclassReviewer |
| POST | `/records/declass-reviews/{id}/complete` | Complete an IN_PROGRESS review and cascade the outcome | DeclassReviewer |
| GET | `/records/equity-referrals` | List equity referrals with filters and pagination | All roles except Anonymous |
| GET | `/records/equity-referrals/{id}` | Get one equity referral | All roles except Anonymous |
| POST | `/records/equity-referrals/{id}/respond` | Referred agency responds DECLASSIFY or EXEMPT | AgencyLiaison |
| POST | `/records/researchers` | Self-register a researcher (PENDING) | Anonymous |
| GET | `/records/researchers/{id}` | Get one researcher registration (lazy expiry applies) | All roles except Anonymous |
| POST | `/records/researchers/{id}/activate` | Activate a PENDING registration or renew an EXPIRED one | ResearchRoomStaff |
| POST | `/records/pull-requests` | Request a research-room pull of a unit range for a visit date | Researcher |
| GET | `/records/pull-requests` | List pull requests with filters and pagination | All roles except Anonymous |
| GET | `/records/pull-requests/{id}` | Get one pull request | All roles except Anonymous |
| POST | `/records/pull-requests/{id}/fulfill` | Pull the requested units to the research room | ResearchRoomStaff |
| POST | `/records/pull-requests/{id}/return` | Return pulled units; late return suspends the researcher | ResearchRoomStaff |
| POST | `/records/reproduction-requests` | Request reproduction of pages from a described, public collection | Researcher |
| GET | `/records/reproduction-requests` | List reproduction requests with filters and pagination | All roles except Anonymous |
| GET | `/records/reproduction-requests/{id}` | Get one reproduction request | All roles except Anonymous |
| POST | `/records/reproduction-requests/{id}/pay` | Pay a QUOTED reproduction request | Researcher |
| POST | `/records/reproduction-requests/{id}/fulfill` | Fulfill a PAID reproduction request | ResearchRoomStaff |
| POST | `/records/reproduction-requests/{id}/cancel` | Cancel a QUOTED reproduction request | Researcher |
| POST | `/records/foia-requests` | File a FOIA request against a restricted collection | Researcher |
| GET | `/records/foia-requests` | List FOIA requests with filters and pagination | All roles except Anonymous |
| GET | `/records/foia-requests/{id}` | Get one FOIA request | All roles except Anonymous |
| POST | `/records/foia-requests/{id}/adjudicate` | Adjudicate a RECEIVED or IN_REVIEW request (GRANT, PARTIAL, DENY) | FoiaOfficer |
| POST | `/records/foia-requests/{id}/appeal` | Appeal a PARTIAL_GRANT or DENIED request within the window | Researcher |
| POST | `/records/foia-requests/{id}/decide-appeal` | Decide an appeal (GRANT, UPHOLD, REMAND) | FoiaAppealsOfficer |
| POST | `/records/presidential-restrictions` | Impose a P1–P6 restriction on a PRESIDENTIAL-domain collection | ChiefArchivist |
| GET | `/records/presidential-restrictions` | List presidential restrictions with filters and pagination | All roles except Anonymous |
| GET | `/records/presidential-restrictions/{id}` | Get one presidential restriction | All roles except Anonymous |
| POST | `/records/presidential-restrictions/{id}/designate` | Designate the former president's representative | ChiefArchivist |
| POST | `/records/presidential-restrictions/{id}/notify` | Notify the designated representative; starts the cooling period | ChiefArchivist |
| POST | `/records/presidential-restrictions/{id}/release` | Release a NOTIFIED restriction once the cooling period has elapsed | ChiefArchivist |
| POST | `/_clock/set_current_utc` | Set the server's logical clock (ISO 8601 UTC) | PlatformAdmin |

## 5. Error Code Catalogue

The catalogue below fixes every error identifier and its HTTP status. Trigger conditions are specified where each rule lives, in §2 and §3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_AGENCY_NOT_FOUND` | 404 Not Found |
| `ERR_SCHEDULE_NOT_FOUND` | 404 Not Found |
| `ERR_TRANSFER_NOT_FOUND` | 404 Not Found |
| `ERR_COLLECTION_NOT_FOUND` | 404 Not Found |
| `ERR_REVIEW_NOT_FOUND` | 404 Not Found |
| `ERR_REFERRAL_NOT_FOUND` | 404 Not Found |
| `ERR_RESEARCHER_NOT_FOUND` | 404 Not Found |
| `ERR_PULL_REQUEST_NOT_FOUND` | 404 Not Found |
| `ERR_REPRODUCTION_NOT_FOUND` | 404 Not Found |
| `ERR_FOIA_NOT_FOUND` | 404 Not Found |
| `ERR_RESTRICTION_NOT_FOUND` | 404 Not Found |
| `ERR_OWNERSHIP_MISMATCH` | 403 Forbidden |
| `ERR_AGENCY_MISMATCH` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_SCHEDULE_NOT_APPRAISED` | 409 Conflict |
| `ERR_SCHEDULE_NOT_APPROVED` | 409 Conflict |
| `ERR_NOT_PERMANENT_DISPOSITION` | 409 Conflict |
| `ERR_TRANSFER_NOT_VALIDATED` | 409 Conflict |
| `ERR_TRANSFER_LAG_NOT_ELAPSED` | 409 Conflict |
| `ERR_SYSTEMATIC_REVIEW_PREMATURE` | 409 Conflict |
| `ERR_REVIEW_ALREADY_OPEN` | 409 Conflict |
| `ERR_REVIEW_NOT_IN_PROGRESS` | 409 Conflict |
| `ERR_REFERRAL_ALREADY_RESPONDED` | 409 Conflict |
| `ERR_REFERRALS_OUTSTANDING` | 409 Conflict |
| `ERR_DUPLICATE_REFERRAL` | 409 Conflict |
| `ERR_RESEARCHER_NOT_ACTIVE` | 409 Conflict |
| `ERR_PULL_NOT_FULFILLABLE` | 409 Conflict |
| `ERR_PULL_NOT_RETURNABLE` | 409 Conflict |
| `ERR_REPRO_NOT_PAYABLE` | 409 Conflict |
| `ERR_REPRO_NOT_PAID` | 402 Payment Required |
| `ERR_REPRO_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_APPEAL_NOT_ALLOWED_STATE` | 409 Conflict |
| `ERR_APPEAL_WINDOW_CLOSED` | 409 Conflict |
| `ERR_FOIA_NOT_APPEALED` | 409 Conflict |
| `ERR_FOIA_ALREADY_ADJUDICATED` | 409 Conflict |
| `ERR_RESTRICTION_NOT_NOTIFIED` | 409 Conflict |
| `ERR_COOLING_PERIOD_ACTIVE` | 409 Conflict |
| `ERR_DIGITIZATION_NOT_QUEUED` | 409 Conflict |
| `ERR_DIGITIZATION_NOT_READY` | 409 Conflict |
| `ERR_COLLECTION_RESTRICTED` | 403 Forbidden |
| `ERR_COLLECTION_NOT_RESTRICTED` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_AGENCY_CODE_EXISTS` | 409 Conflict |
| `ERR_EMAIL_EXISTS` | 409 Conflict |
| `ERR_SCHEDULE_NUMBER_EXISTS` | 409 Conflict |
| `ERR_NOT_PRESIDENTIAL_RECORDS` | 409 Conflict |
| `ERR_DUPLICATE_RESTRICTION_CATEGORY` | 409 Conflict |
| `ERR_REPRESENTATIVE_REQUIRED` | 409 Conflict |
| `ERR_METADATA_STANDARD_MISMATCH` | 422 Unprocessable Entity |
| `ERR_METHOD_REQUIREMENT_MISSING` | 422 Unprocessable Entity |
| `ERR_DESCRIPTION_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_EXEMPTION_REQUIRED` | 422 Unprocessable Entity |
| `ERR_FOIA_NOT_REQUIRED` | 409 Conflict |
| `ERR_COLLECTION_NOT_DESCRIBED` | 409 Conflict |
| `ERR_UNIT_RANGE_INVALID` | 400 Bad Request |
| `ERR_UNIT_SPAN_LIMIT_EXCEEDED` | 409 Conflict |
| `ERR_UNIT_RESERVATION_CONFLICT` | 409 Conflict |
| `ERR_READING_ROOM_CAPACITY` | 409 Conflict |
| `ERR_VISIT_DATE_OUT_OF_WINDOW` | 409 Conflict |
| `ERR_ACTIVE_PULL_LIMIT_EXCEEDED` | 409 Conflict |
| `ERR_DAILY_PAGE_LIMIT_EXCEEDED` | 409 Conflict |
| `ERR_STALE_COLLECTION_VERSION` | 412 Precondition Failed |
