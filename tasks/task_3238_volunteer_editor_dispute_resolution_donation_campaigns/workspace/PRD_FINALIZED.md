# Wiki Governance API — Product Requirements Document

## 1. Introduction

The Wikimedia Foundation operates one of the largest open editing platforms in the world. Volunteer editors contribute content, but governance — dispute resolution, vandalism control, conflict-of-interest enforcement, legal compliance, and fundraising — requires a structured system that balances openness with accountability. This document specifies the REST API that powers volunteer editor governance, donation campaigns, grant distribution, and legal request handling.

The system serves multiple constituencies: anonymous visitors who read pages and donate, volunteer editors who create and patrol content, administrators who moderate and resolve disputes, fundraising staff who run banner campaigns, grant reviewers who distribute funds, and legal counsel who handle takedowns and transparency reporting. Each constituency has distinct capabilities, and the API enforces strict role-based segregation of duties.

Because the platform is open by default, every write operation is guarded by validation rules that escalate in severity: authentication and authorization checks run first, then referential integrity, then state-machine legality, and finally domain-specific business constraints such as conflict-of-interest disclosure, page protection levels, and budget ceilings. The API uses optimistic concurrency control on contested resources so that simultaneous edits, escalations, or approvals are serialized deterministically rather than silently overwriting each other.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every API request must include two headers: `X-User-ID` and `X-User-Role`. If either header is missing or the role is not recognized, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the role is recognized but not permitted for the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes these roles, spelled exactly as follows:

- `Anonymous` — an unauthenticated visitor. `X-User-ID` is an opaque operator identifier not tied to any persisted entity. Anonymous users can register as editors, view public pages, view active campaigns, and record donation pledges.
- `VolunteerEditor` — a registered community member. When `X-User-Role` is `VolunteerEditor`, `X-User-ID` is the `id` of the acting `VolunteerEditor`; ownership checks on any resource that references a `VolunteerEditor` compare the resource's foreign-key field to `X-User-ID`.
- `Administrator` — a senior volunteer with elevated moderation privileges. `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it on resources but does not compare it to any entity's `id`.
- `FundraisingManager` — staff managing donation campaigns. `X-User-ID` is an opaque operator identifier.
- `PaymentProcessor` — automated system or staff handling payments. `X-User-ID` is an opaque operator identifier.
- `GrantAdministrator` — staff managing grant programs. `X-User-ID` is an opaque operator identifier.
- `GrantReviewer` — community or staff reviewing grant applications. `X-User-ID` is an opaque operator identifier.
- `LegalCounsel` — legal team handling requests and transparency. `X-User-ID` is an opaque operator identifier.
- `PlatformAdmin` — system administrator for test infrastructure and clock control. `X-User-ID` is an opaque operator identifier.

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

List endpoints accept `limit` and `offset` query parameters. The default `limit` is 10, the minimum is 1, and the maximum is 100. The default `offset` is 0. Results are sorted by `created_at` ascending. The `meta` object in list responses includes `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every persisted entity carries an `id` that is a server-minted UUID with no type prefix. Every entity also carries `created_at` and `updated_at`, both ISO 8601 UTC timestamps with three fractional digits. Most entities also carry a `version` field, an integer that increments on every mutation; entities that do not carry `version` are explicitly noted in the relevant workflow sections. The `version` field is absent from `Revision`, `ProtectionRequest`, `VandalismReport`, `ImpressionEvent`, and `LegalRequest` — these entities do not participate in optimistic concurrency control.

### 2.5. Precision and Rounding

All monetary amounts are stored as integer cents. All calculated scores that are integers (content score, vandalism score, grant review score) are rounded half-up to zero decimal places. Banner conversion rates in basis points are either truncated toward zero or rounded half-up, depending on the reporting context; the exact rule is stated in the campaign analytics section.

### 2.6. Resource Identifiers, Hierarchical Consistency, and Cascading Side Effects

Path parameters are named `editorId`, `pageId`, `revisionId`, `disputeId`, `requestId`, `reportId`, `campaignId`, `bannerId`, `donationId`, `programId`, `applicationId`, `impressionId`, and `reportId` (transparency reports reuse `reportId`); each binds the `id` of the corresponding resource in the URL hierarchy.

Foreign-key fields link child entities to their parents. A revision carries `page_id` and `editor_id`. A dispute carries `page_id`, `initiator_id`, `respondent_id`, and `subject_revision_id`. A protection request carries `page_id`, `requested_by_id`, and `reviewed_by_id`. A vandalism report carries `revision_id` and `reporter_id`. A banner carries `campaign_id`. A donation carries `campaign_id` and `banner_id`. An impression carries `banner_id`. A grant application carries `program_id` and `applicant_id`. A legal request carries `target_page_id`, `target_user_id`, and `transparency_report_id`.

When a state transition on one entity affects related entities, the API performs those cascades atomically as part of the same request. For example, suspending an editor also flags all of that editor's pending revisions; blocking an editor also closes all disputes that editor initiated; activating or pausing a campaign also flips the status of every banner under that campaign; approving a protection request updates the page's protection level; and processing a donation increments both the campaign's raised total and the banner's conversion count. Every mutation refreshes `updated_at` and increments `version` on the mutated entity.

### 2.7. Nested Resource Retrieval and Validation Order

URL path parameters are validated left to right. If a request references `/wiki/pages/{pageId}/revisions`, the server first verifies that `pageId` exists before checking anything about the revision payload. If any referenced ID does not exist, the request is rejected with `ERR_NOT_FOUND` (HTTP 404). Validation proceeds in strict priority order across all endpoints: authentication first (`ERR_UNAUTHENTICATED`), then authorization (`ERR_UNAUTHORIZED`), then existence (`ERR_NOT_FOUND`), then state legality (`ERR_INVALID_STATE`), and finally the domain-specific business rules described in §3.

### 2.8. Optimistic Concurrency Control

Five write operations require a client-supplied expected-version field. If the value does not match the parent entity's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). The five guarded operations are:

- Accepting a revision requires `expected_page_version` matching the target `WikiPage`'s current `version`.
- Escalating a dispute requires `expected_dispute_version` matching the target `DisputeCase`'s current `version`.
- Activating, pausing, completing, or cancelling a campaign requires `expected_campaign_version` matching the target `DonationCampaign`'s current `version`.
- Approving a grant application requires `expected_application_version` matching the target `GrantApplication`'s current `version`.
- Publishing a transparency report requires `expected_report_version` matching the target `TransparencyReport`'s current `version`.

Endpoints not listed above do not take a version field.

### 2.9. Logical Clock for Deterministic Testing

The server maintains a logical clock. A `PlatformAdmin` may advance the clock to a supplied `to_iso8601` instant. The default startup time is 2026-09-01T00:00:00Z. All timestamps generated by the server (`served_at`, `processed_at`, `opened_at`, `escalated_at`, `received_at`, `expires_at` checks) derive from this logical clock.

## 3. Business Logic & Workflows

### 3.1. Editor Registration and Account Lifecycle

Anyone may register as a volunteer editor by providing a `username` and `email`. Upon registration, the new editor's `account_status` is set to `ACTIVE`, `coi_disclosed` defaults to false, and `edit_count` starts at zero. The editor immediately gains the ability to create pages and submit revisions.

An editor's standing can change. An `Administrator` may suspend an editor when the editor has at least one confirmed vandalism report in the last thirty days or when an undisclosed conflict of interest is detected. Suspension transitions `account_status` to `SUSPENDED`, transitions every pending revision that editor has submitted to `FLAGGED` (without creating a vandalism report), and sets `rollback_eligible` to false. A suspended editor may be reinstated after at least seven days have elapsed and provided no open Arbitration-level disputes exist against that editor; reinstatement recalculates `rollback_eligible` from the editor's warning history.

An `Administrator` may permanently block an editor who has three or more confirmed vandalism reports in the last ninety days, or who is subject to a court order, or who has repeatedly evaded conflict-of-interest disclosure. Blocking transitions `account_status` to `BLOCKED` — a terminal state — and flags all pending revisions and closes all open disputes the editor initiated. Flagging here has the meaning given in §3.2: each flagged revision transitions to `FLAGGED` and a `VandalismReport` is created for it; because the trigger is automated rather than a volunteer, each such report's `auto_flagged` field is set to true. Closing the disputes applies the same `dispute_level` recalculation described in §3.4, so the `dispute_level` of each affected page is recalculated from its remaining open disputes. An editor who has an open Arbitration-level dispute as the initiator cannot be blocked; attempting to do so is rejected with `ERR_EDITOR_HAS_OPEN_ARBITRATION` (HTTP 409).

### 3.2. Page Creation and Revision Workflow

A `VolunteerEditor` may create a new wiki page by supplying a `title` and selecting a `topic_area` from the set `GENERAL`, `POLITICS`, `HEALTH`, `BIOGRAPHY`, or `HISTORY`. A new page starts with `protection_level` set to `NONE`, `dispute_level` set to `NONE`, and `content_score` set to zero.

Once a page exists, editors submit revisions containing `content_text` and a `summary`. Each revision is created in `PENDING` status. The system computes three scores at creation time: `vandalism_score`, `source_quality_score`, and `neutrality_score`. The vandalism score is an integer from 0 to 100, calculated as the sum of a base score (10 for new pages, 5 for existing pages), a keyword score (30 if spam keywords are detected, otherwise 0), a pattern score (40 if mass deletion or blanking is detected, otherwise 0), and an editor history score (20 if the editor has prior confirmed vandalism, otherwise 0); the total is capped at 100.

A pending revision may be accepted by a `VolunteerEditor` with `rollback_eligible` set to true, or by an `Administrator`. Acceptance is not automatic. The vandalism score must be below 50. The page's protection level must permit the editor: `NONE` allows any editor; `SEMI` requires an account age of at least four days; `FULL` permits only an `Administrator`. There must be no open Arbitration-level dispute on the page. In addition, the request must carry `expected_page_version` matching the page's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). When a revision is accepted, the page's `current_revision_id` is updated, `content_score` is recalculated, the editor's `edit_count` is incremented, and the page's `version` is incremented.

The composite quality threshold for acceptance depends on whether the page is contested. For a pending revision on a page with no open dispute, the composite score — the average of `source_quality_score` and `neutrality_score` — must be at least 40. For a revision on a page with an open `NOTICE` or `ARBITRATION` dispute, the composite must be at least 70. Identical scores therefore produce different accept/reject outcomes depending on the dispute context.

A revision may also be flagged. Any editor with `rollback_eligible`, or an `Administrator`, or the system itself may flag a revision when the vandalism score is at least 50 or when a report is filed with a `report_type` of `VANDALISM`, `SPAM`, `BLP_VIOLATION`, or `COPYVIO`. Flagging transitions the revision to `FLAGGED` and creates a `VandalismReport`; the report's `auto_flagged` field is set to true when the trigger was automated rather than a volunteer.

A flagged revision may be reverted once its vandalism report has been confirmed. Reversion transitions the revision to `REVERTED`, rolls the page's `current_revision_id` back to the prior accepted revision, recalculates `content_score`, sets the report's `rollback_applied` to true, and increments the page's `version`. The revert request must carry `expected_page_version`. Alternatively, an `Administrator` may accept a flagged revision if the vandalism report was dismissed; this transitions the revision to `ACCEPTED` and applies the same side effects as a normal acceptance.

If an editor's `coi_disclosure_required` flag is true and `coi_disclosed` is false, submitting a revision is rejected with `ERR_COI_UNDISCLOSED` (HTTP 403). If the page's protection level does not permit the editor, the submission or acceptance is rejected with `ERR_PROTECTION_BLOCKED` (HTTP 403). If a revision's vandalism score is 50 or higher and no admin override is applied, acceptance is rejected with `ERR_VANDALISM_SCORE_HIGH` (HTTP 409). If an editor lacks `rollback_eligible` or admin status for a privileged action, the rejection is `ERR_INSUFFICIENT_PRIVILEGE` (HTTP 403).

### 3.3. Conflict-of-Interest Disclosure

An editor who has any paid contribution or employer overlap detected by the system has `coi_disclosure_required` set to true. Such an editor must file a disclosure by providing `disclosure_text` before editing pages in declared conflict areas. Filing the disclosure sets `coi_disclosed` to true and removes the editing block. Editing without disclosure when required is rejected with `ERR_COI_UNDISCLOSED`.

### 3.4. Dispute Resolution Ladder

Any editor may open a dispute on a page by naming a `respondent_id`, a `subject_revision_id`, and a `dispute_type` from `CONTENT`, `CONDUCT`, `SOURCING`, or `NOTABILITY`. The dispute opens at `level` `TALK` with `status` `OPEN`, and the page's `dispute_level` is updated. A page may not have two open disputes at the same level; a duplicate attempt is rejected with `ERR_DISPUTE_ALREADY_OPEN` (HTTP 409).

A dispute may be escalated by the initiator, the respondent, or an `Administrator`. Escalation requires that the current level be `TALK` or `NOTICE`, that at least 72 hours have elapsed since the dispute was opened or since the last escalation, and that no resolution has been reached at the current level. Attempting escalation sooner is rejected with `ERR_ESCALATION_TOO_SOON` (HTTP 409). Escalation advances the level from `TALK` to `NOTICE` or from `NOTICE` to `ARBITRATION`, updates `escalated_at`, and increments the dispute's `version`. The request must carry `expected_dispute_version`. If the level becomes `ARBITRATION`, the page's `dispute_level` is set to `ARB` and the page is automatically protected at level `FULL`.

An `Administrator` may resolve an open dispute by providing `resolution_notes`. Resolution transitions the dispute to `RESOLVED`. If the dispute had reached `ARBITRATION`, the page's `dispute_level` is recalculated from any remaining open disputes. An `Administrator` may also close a dispute when the initiator's account is `BLOCKED` or withdrawn; closure transitions the dispute to `CLOSED` and applies the same `dispute_level` recalculation.

### 3.5. Page Protection

Any editor may request protection for a page by specifying a `requested_level` of `SEMI` or `FULL` and a `reason`. An optional `expires_at` may be provided. The request is created in `PENDING` status.

An `Administrator` may approve a protection request when the page has at least three flagged revisions in the last seven days or an open Arbitration dispute, and when the requested level is `SEMI` or `FULL`. Approval sets the page's `protection_level` to the requested level. If an `expires_at` was provided, the system transitions the request to `EXPIRED` at that time and reverts the page's `protection_level` to its prior level, or to `NONE` if there was no prior level. An `Administrator` may deny a protection request without preconditions; denial transitions the request to `DENIED`.

### 3.6. Vandalism Reporting and Moderation

Vandalism reports track whether a revision constitutes vandalism, spam, a biographies-of-living-persons violation, or a copyright violation. An `Administrator` may confirm a report, which transitions it to `CONFIRMED` and triggers a recalculation of the subject editor's `rollback_eligible`. An `Administrator` may dismiss a report, transitioning it to `DISMISSED` and likewise recalculating `rollback_eligible`. Rollback eligibility is true exactly when the editor has zero confirmed vandalism reports in the last ninety days. Because the ninety-day window is anchored to the current time, eligibility can change as time passes even without any moderation event; the `rollback_eligible` value returned when fetching an individual editor's profile reflects the editor's standing as of the current time.

### 3.7. Donation Campaign Lifecycle

A `FundraisingManager` creates a donation campaign by supplying a `name`, `start_at`, `end_at`, and `target_amount_cents`. The campaign starts in `DRAFT` with `raised_cents` at zero. Activation requires that the current time fall within the campaign window and that at least one banner be configured and active; activation transitions the campaign to `ACTIVE`. A campaign may be paused, which sets all its banners to `PAUSED`. A paused campaign may be reactivated provided the current time has not passed `end_at`; reactivation sets all banners back to `ACTIVE`. A campaign may be completed when the current time has passed `end_at` or when `raised_cents` has reached `target_amount_cents`; completion sets all banners to `RETIRED`. A campaign may be cancelled at any time; cancellation sets all banners to `RETIRED` and transitions all `PLEDGED` donations to `FAILED`. All four lifecycle transitions require `expected_campaign_version`.

### 3.8. Banner Management and Impression Tracking

A `FundraisingManager` creates a banner under a campaign by providing `message_variant`, `geo_target` (an ISO country code or `GLOBAL`), `frequency_cap` (maximum impressions per user per day), and an optional `priority_weight` defaulting to 1. The banner starts `ACTIVE` with all counters at zero.

When a page view carries a donation banner slot, the system selects which banner to show. Eligible banners are those whose campaign is `ACTIVE` and whose own status is `ACTIVE`, whose `geo_target` is either `GLOBAL` or matches the viewer's country, and for which the number of impressions already served to that viewer on the current UTC day is below the banner's `frequency_cap`. If no banner is eligible, none is shown. Eligible banners are ranked by `priority_weight` descending; ties are broken by `created_at` ascending, never by `id`.

Recording a served impression requires `viewer_key` and `country_code`, and optionally `clicked` defaulting to false. The impression is rejected with `ERR_BANNER_GEO_MISMATCH` (HTTP 409) if the banner's `geo_target` is neither `GLOBAL` nor the viewer's country. It is rejected with `ERR_BANNER_FREQUENCY_CAP` (HTTP 409) if the viewer has already reached the daily cap. A recorded impression increments the banner's `impression_count`; if `clicked` is true, `click_count` is also incremented. The impression's `day_bucket` is derived from `served_at` as the UTC date in `YYYY-MM-DD` form and is used for frequency-cap counting.

A banner's conversion rate in basis points is computed on read. The denominator is the banner's `impression_count`, with a floor of 1 to avoid division by zero. On operational dashboards (banner detail reads), the rate is truncated toward zero to integer basis points. In campaign completion summaries, the rate is rounded half-up to integer basis points.

### 3.9. Donation Processing and Refunds

An `Anonymous` visitor may record a donation pledge under a campaign by supplying a `banner_id`, `donor_email_hash`, `amount_cents`, and `currency`. The donation starts in `PLEDGED` status.

A `PaymentProcessor` may process a pledged donation only when both the campaign and the banner are `ACTIVE`; otherwise the attempt is rejected with `ERR_CAMPAIGN_INACTIVE` (HTTP 409). Processing transitions the donation to `COMPLETED`, sets `processed_at`, increments the campaign's `raised_cents` by the donation amount, and increments the banner's `conversion_count`. The banner's `impression_count` is not incremented by processing; impressions are tracked separately. A pledged donation may alternatively be marked `FAILED` without preconditions.

A `FundraisingManager` may refund a completed donation within ninety days of `processed_at`; a later attempt is rejected with `ERR_REFUND_WINDOW_EXPIRED` (HTTP 409). Refunding transitions the donation to `REFUNDED`, decrements the campaign's `raised_cents` by the donation amount, and decrements the banner's `conversion_count`.

When a campaign completes, net revenue is allocated across banners. For each banner, attributed cents are the sum of `amount_cents` for all `COMPLETED` donations tied to that banner; refunded donations are excluded. A processing fee of three percent is calculated per banner and rounded half-up to integer cents. The per-banner net is the attributed cents minus the rounded fee. The total net revenue is the sum of the per-banner nets. The per-banner-round-then-sum order is mandatory; summing first and rounding once is forbidden because it yields a different total.

### 3.10. Grant Programs and Applications

A `GrantAdministrator` creates a grant program by supplying a `name`, `fiscal_year`, and `budget_cents`. The program starts `OPEN` with `allocated_cents` at zero. The administrator may close the program to new applications; closure requires `expected_program_version` and transitions the program to `CLOSED`.

A `VolunteerEditor` may submit a grant application under an open program by supplying `project_title` and `requested_cents`. The application starts in `SUBMITTED`. A `GrantReviewer` may start review, transitioning the application to `UNDER_REVIEW`. The reviewer submits scores for `impact_score`, `feasibility_score`, `budget_reasonableness_score`, and `community_support_score`, each from 0 to 100. The `review_score` is the weighted sum — thirty percent impact, thirty percent feasibility, twenty percent budget reasonableness, twenty percent community support — rounded half-up to an integer from 0 to 100.

Approval requires a `review_score` of at least 70; a lower score is rejected with `ERR_GRANT_SCORE_TOO_LOW` (HTTP 409). Approval also requires that the program's `allocated_cents` plus the application's `awarded_cents` not exceed `budget_cents`; exceeding the budget is rejected with `ERR_GRANT_BUDGET_EXCEEDED` (HTTP 409). The `awarded_cents` must be greater than zero. The approval request must carry `expected_application_version`. Approval transitions the application to `APPROVED` and increments the program's `allocated_cents` by `awarded_cents`. An application may be rejected without preconditions, or withdrawn by the applicant while it is `SUBMITTED` or `UNDER_REVIEW`.

### 3.11. Legal Requests and Transparency Reporting

`LegalCounsel` files a legal request by selecting a `request_type` from `TAKEDOWN`, `USER_INFO`, `SUBPOENA`, or `COURT_ORDER`, naming a `requesting_party`, and optionally supplying a `target_page_id` or `target_user_id`. The request is received in `RECEIVED` status with `received_at` set. Counsel may start review, transitioning the request to `UNDER_REVIEW`.

Compliance with a request requires that the request type be one of the four enumerated types. For a `TAKEDOWN`, the target page must exist and must not have an open Arbitration dispute; attempting compliance while an Arbitration dispute is open is rejected with `ERR_TAKEDOWN_ARBITRATION_BLOCK` (HTTP 409). For a `USER_INFO` request, a court order or subpoena must be present. Compliance transitions the request to `COMPLIED`; if the request is a takedown, the page's `protection_level` is set to `FULL`, and if a `target_page_id` was set, the page's revisions are locked. Partial compliance applies the same checks but with a narrowed scope, transitioning the request to `PARTIALLY_COMPLIED`. Rejection transitions the request to `REJECTED`.

Counsel creates a transparency report by supplying `period_start` and `period_end`. The report starts in `DRAFT` with all counts at zero. Publishing requires that every legal request whose `received_at` falls within the half-open interval from `period_start` to `period_end` have reached a terminal status (`COMPLIED`, `REJECTED`, or `PARTIALLY_COMPLIED`); if any request is still pending, publication is rejected with `ERR_LEGAL_REQUESTS_PENDING` (HTTP 409). The publish request must carry `expected_report_version`. At publish time, `total_requests` is the count of requests in the period, `complied_count` is the count of those with status `COMPLIED` or `PARTIALLY_COMPLIED`, and `rejected_count` is the count with status `REJECTED`. Publishing transitions the report to `PUBLISHED` and sets `transparency_report_id` on every included request.

### 3.12. Content Score Derivation

A page's `content_score` is recalculated whenever a revision is accepted or reverted. The calculation considers all accepted revisions for the page from the last thirty days. The score is forty percent of the average `source_quality_score`, forty percent of the average `neutrality_score`, and twenty percent of a stability bonus. The stability bonus is 100 if the page has had no disputes in the last thirty days, 50 if the only disputes were at `TALK` level, and 0 otherwise. The final score is rounded half-up to an integer from 0 to 100.

## 4. Endpoint Definitions

New resources are returned with HTTP 201. Modifications to existing resources are returned with HTTP 200. All list endpoints return HTTP 200.

| Method | Path | Description | Authorized Role(s) |
|--------|------|-------------|-------------------|
| POST | `/_clock/set_current_utc` | Set logical clock for deterministic testing | PlatformAdmin |
| GET | `/wiki/editors` | List editors (paginated) | VolunteerEditor, Administrator, LegalCounsel, PlatformAdmin |
| GET | `/wiki/pages` | List pages (paginated) | VolunteerEditor, Administrator, LegalCounsel, Anonymous, PlatformAdmin |
| GET | `/wiki/revisions` | List revisions, filterable by page_id or editor_id | VolunteerEditor, Administrator, LegalCounsel, PlatformAdmin |
| GET | `/wiki/disputes` | List disputes, filterable by page_id, initiator_id, respondent_id, subject_revision_id | VolunteerEditor, Administrator, LegalCounsel, PlatformAdmin |
| GET | `/wiki/protection-requests` | List protection requests, filterable by page_id, requested_by_id, reviewed_by_id | VolunteerEditor, Administrator, PlatformAdmin |
| GET | `/wiki/vandalism-reports` | List vandalism reports, filterable by revision_id or reporter_id | VolunteerEditor, Administrator, PlatformAdmin |
| GET | `/wiki/campaigns` | List donation campaigns (paginated) | FundraisingManager, Anonymous, PlatformAdmin |
| GET | `/wiki/banners` | List campaign banners, filterable by campaign_id | FundraisingManager, PlatformAdmin |
| GET | `/wiki/donations` | List donations, filterable by campaign_id or banner_id | FundraisingManager, PaymentProcessor, PlatformAdmin |
| GET | `/wiki/grant-programs` | List grant programs (paginated) | GrantAdministrator, GrantReviewer, VolunteerEditor, PlatformAdmin |
| GET | `/wiki/grant-applications` | List grant applications, filterable by program_id or applicant_id | GrantAdministrator, GrantReviewer, VolunteerEditor, PlatformAdmin |
| GET | `/wiki/legal-requests` | List legal requests, filterable by target_page_id, target_user_id, transparency_report_id | LegalCounsel, PlatformAdmin |
| GET | `/wiki/transparency-reports` | List transparency reports (paginated) | LegalCounsel, Anonymous, PlatformAdmin |
| POST | `/wiki/editors` | Register a new volunteer editor | Anonymous |
| GET | `/wiki/editors/{editorId}` | Get editor profile | VolunteerEditor, Administrator, LegalCounsel |
| POST | `/wiki/editors/{editorId}/suspend` | Suspend an editor | Administrator |
| POST | `/wiki/editors/{editorId}/reinstate` | Reinstate a suspended editor | Administrator |
| POST | `/wiki/editors/{editorId}/block` | Permanently block an editor | Administrator |
| POST | `/wiki/editors/{editorId}/disclose-coi` | Editor files conflict-of-interest disclosure | VolunteerEditor |
| POST | `/wiki/pages` | Create a new wiki page | VolunteerEditor |
| GET | `/wiki/pages/{pageId}` | Get page details | VolunteerEditor, Administrator, LegalCounsel, Anonymous |
| POST | `/wiki/pages/{pageId}/revisions` | Submit a new revision to a page | VolunteerEditor |
| GET | `/wiki/revisions/{revisionId}` | Get revision details | VolunteerEditor, Administrator, LegalCounsel |
| POST | `/wiki/revisions/{revisionId}/accept` | Accept a pending revision | VolunteerEditor, Administrator |
| POST | `/wiki/revisions/{revisionId}/flag` | Flag a revision for vandalism | VolunteerEditor, Administrator |
| POST | `/wiki/revisions/{revisionId}/revert` | Revert a flagged revision after confirmed vandalism | VolunteerEditor, Administrator |
| POST | `/wiki/pages/{pageId}/disputes` | Open a dispute on a page | VolunteerEditor |
| GET | `/wiki/disputes/{disputeId}` | Get dispute details | VolunteerEditor, Administrator, LegalCounsel |
| POST | `/wiki/disputes/{disputeId}/escalate` | Escalate dispute to next level | VolunteerEditor, Administrator |
| POST | `/wiki/disputes/{disputeId}/resolve` | Resolve a dispute | Administrator |
| POST | `/wiki/disputes/{disputeId}/close` | Close a dispute | Administrator |
| POST | `/wiki/pages/{pageId}/protection-requests` | Request page protection | VolunteerEditor, Administrator |
| GET | `/wiki/protection-requests/{requestId}` | Get a protection request | VolunteerEditor, Administrator, PlatformAdmin |
| POST | `/wiki/protection-requests/{requestId}/approve` | Approve a protection request | Administrator |
| POST | `/wiki/protection-requests/{requestId}/deny` | Deny a protection request | Administrator |
| GET | `/wiki/vandalism-reports/{reportId}` | Get vandalism report | VolunteerEditor, Administrator |
| POST | `/wiki/vandalism-reports/{reportId}/confirm` | Confirm a vandalism report | Administrator |
| POST | `/wiki/vandalism-reports/{reportId}/dismiss` | Dismiss a vandalism report | Administrator |
| POST | `/wiki/campaigns` | Create a donation campaign | FundraisingManager |
| GET | `/wiki/campaigns/{campaignId}` | Get campaign details | FundraisingManager, Anonymous |
| POST | `/wiki/campaigns/{campaignId}/activate` | Activate a campaign | FundraisingManager |
| POST | `/wiki/campaigns/{campaignId}/pause` | Pause a campaign | FundraisingManager |
| POST | `/wiki/campaigns/{campaignId}/complete` | Complete a campaign | FundraisingManager |
| POST | `/wiki/campaigns/{campaignId}/cancel` | Cancel a campaign | FundraisingManager |
| POST | `/wiki/campaigns/{campaignId}/banners` | Create a campaign banner | FundraisingManager |
| GET | `/wiki/banners/{bannerId}` | Get banner details | FundraisingManager |
| POST | `/wiki/banners/{bannerId}/impressions` | Record a served banner impression | Anonymous, PlatformAdmin |
| GET | `/wiki/impressions` | List impression events, filterable by banner_id | FundraisingManager, PlatformAdmin |
| GET | `/wiki/impressions/{impressionId}` | Get an impression event | FundraisingManager, PlatformAdmin |
| POST | `/wiki/campaigns/{campaignId}/donations` | Record a donation pledge | Anonymous |
| GET | `/wiki/donations/{donationId}` | Get donation details | FundraisingManager, PaymentProcessor |
| POST | `/wiki/donations/{donationId}/process` | Process a pledged donation | PaymentProcessor |
| POST | `/wiki/donations/{donationId}/fail` | Mark donation as failed | PaymentProcessor |
| POST | `/wiki/donations/{donationId}/refund` | Refund a completed donation | FundraisingManager |
| POST | `/wiki/grant-programs` | Create a grant program | GrantAdministrator |
| GET | `/wiki/grant-programs/{programId}` | Get grant program details | GrantAdministrator, GrantReviewer, VolunteerEditor |
| POST | `/wiki/grant-programs/{programId}/close` | Close a grant program to new applications | GrantAdministrator |
| POST | `/wiki/grant-programs/{programId}/applications` | Submit a grant application | VolunteerEditor |
| GET | `/wiki/grant-applications/{applicationId}` | Get grant application | GrantAdministrator, GrantReviewer, VolunteerEditor |
| POST | `/wiki/grant-applications/{applicationId}/start-review` | Start reviewing a grant application | GrantReviewer |
| POST | `/wiki/grant-applications/{applicationId}/score` | Submit review scores | GrantReviewer |
| POST | `/wiki/grant-applications/{applicationId}/approve` | Approve a grant application | GrantReviewer |
| POST | `/wiki/grant-applications/{applicationId}/reject` | Reject a grant application | GrantReviewer |
| POST | `/wiki/grant-applications/{applicationId}/withdraw` | Withdraw a grant application | VolunteerEditor |
| POST | `/wiki/legal-requests` | File a legal request | LegalCounsel |
| GET | `/wiki/legal-requests/{requestId}` | Get legal request | LegalCounsel |
| POST | `/wiki/legal-requests/{requestId}/start-review` | Start reviewing a legal request | LegalCounsel |
| POST | `/wiki/legal-requests/{requestId}/comply` | Comply with a legal request | LegalCounsel |
| POST | `/wiki/legal-requests/{requestId}/partially-comply` | Partially comply with a legal request | LegalCounsel |
| POST | `/wiki/legal-requests/{requestId}/reject` | Reject a legal request | LegalCounsel |
| POST | `/wiki/transparency-reports` | Create a transparency report draft | LegalCounsel |
| GET | `/wiki/transparency-reports/{reportId}` | Get transparency report | LegalCounsel, Anonymous |
| POST | `/wiki/transparency-reports/{reportId}/publish` | Publish a transparency report | LegalCounsel |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|----------|-----------------|
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_COI_UNDISCLOSED` | 403 |
| `ERR_PROTECTION_BLOCKED` | 403 |
| `ERR_ESCALATION_TOO_SOON` | 409 |
| `ERR_GRANT_BUDGET_EXCEEDED` | 409 |
| `ERR_CAMPAIGN_INACTIVE` | 409 |
| `ERR_REFUND_WINDOW_EXPIRED` | 409 |
| `ERR_EDITOR_HAS_OPEN_ARBITRATION` | 409 |
| `ERR_LEGAL_REQUESTS_PENDING` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_VANDALISM_SCORE_HIGH` | 409 |
| `ERR_DISPUTE_ALREADY_OPEN` | 409 |
| `ERR_INSUFFICIENT_PRIVILEGE` | 403 |
| `ERR_BANNER_FREQUENCY_CAP` | 409 |
| `ERR_BANNER_GEO_MISMATCH` | 409 |
| `ERR_GRANT_SCORE_TOO_LOW` | 409 |
| `ERR_TAKEDOWN_ARBITRATION_BLOCK` | 409 |
