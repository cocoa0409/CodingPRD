# Loss History Exchange API — Product Requirements Document

## 1. Introduction

Insurance carriers price risk on the strength of what they know about an applicant's loss history, and today that knowledge is fragmented across every carrier's private claim files. This document specifies the Loss History Exchange API: a shared, contributory loss-history reporting exchange in which carriers contribute standardized claim records and, in return, receive quote-time loss history reports matched on individual, address, and vehicle identifiers. The exchange operates under fair-credit-reporting-style obligations — permissible purpose validation, consumer file disclosure, dispute and reinvestigation timelines, and adverse action support when a report influences pricing or declination.

The system is compliance-first. Every material event — batch receipt, claim acceptance, report issuance, dispute activity, freezes, suspensions — is recorded in an immutable audit trail, and every time-dependent rule (retention windows, reinvestigation deadlines, freeze expiries, reciprocity lapses) is evaluated against a single logical clock that operators control explicitly. Contributory reciprocity is enforced mechanically: a carrier that stops supplying data loses access to reports until its contributions resume. Matching is deliberately conservative, with graded identity signals and a disposition ladder designed to avoid attributing another household's losses to an applicant.

## 2. Global Specifications & System-Wide Principles

This section defines the rules that apply uniformly across the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming one of the five declared roles. The recognized roles are `PlatformAdmin`, `ExchangeComplianceOfficer`, `CarrierDataSteward`, `CarrierUnderwriter`, and `Consumer`. A request with a missing header, or an `X-User-Role` value outside this set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401); for the entity-backed roles named below, `X-User-ID` must additionally be present. A request whose role is not permitted on the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

Role identity is bound to `X-User-ID` as follows:

- When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The same holds when `X-User-Role` is `ExchangeComplianceOfficer`: an opaque identifier, never compared to any entity's `id`.
- When `X-User-Role` is `CarrierDataSteward`, `X-User-ID` is the `id` of the acting `Carrier`; ownership checks on carrier-scoped operations (contributing batches, amending claims) compare the target carrier's `id` — or the claim's contributing carrier — to `X-User-ID`.
- When `X-User-Role` is `CarrierUnderwriter`, `X-User-ID` is likewise the `id` of the acting `Carrier`; filing inquiries and filing, sending, or cancelling adverse action notices are only permitted for the carrier whose `id` equals `X-User-ID`.
- When `X-User-Role` is `Consumer`, `X-User-ID` is the `id` of the acting `Consumer`; file access, dispute filing, and notice acknowledgment compare the resource's consumer reference to `X-User-ID`.

The duties are deliberately segregated: the compliance authority that withdraws carriers, freezes files, voids batches, and adjudicates disputes (`ExchangeComplianceOfficer`) is a different role from the one that contributes data (`CarrierDataSteward`) and from the one that consumes reports for underwriting (`CarrierUnderwriter`).

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

List endpoints are paginated through the `limit` and `offset` query parameters. `limit` defaults to 10, accepts a minimum of 1 and a maximum of 100, and caps the number of items returned. `offset` defaults to 0 and skips that many items from the front of the result set. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

Unless an endpoint states otherwise, all list endpoints return resources sorted by `created_at` in ascending order. The single exception is the exchange-wide audit event listing, which returns events most recent first.

### 2.4. The Logical Clock

All time-dependent behavior in the exchange — retention windows, deadlines, freeze expiries, contribution lag — is evaluated against a single server-side logical clock, never against wall-clock time. At server startup the logical clock reads exactly `2026-09-01T00:00:00Z`. A `PlatformAdmin` may advance it to a supplied `to_iso8601` instant. Advancing the clock re-evaluates, in one sweep: carrier suspension and reactivation from contribution lag, automatic lifting of consumer data freezes whose `frozen_until` has been reached, dispute-overdue audit events for disputes past their reinvestigation deadline, and retention redaction of losses that have aged out of reportability. The clock-advance response reports the new `current_utc` plus the sets `suspended_carrier_ids`, `reactivated_carrier_ids`, `expired_freeze_consumer_ids`, `overdue_dispute_ids`, and `retention_redacted_claim_ids` describing what the sweep changed.

### 2.5. Common Resource Properties

Every primary resource — carriers, consumers, batches, claims, inquiries, reports, disputes, notices, and the exchange rulebook — carries four system-managed fields: `id`, a server-minted UUID with no type prefix; `created_at`, an ISO 8601 UTC timestamp with three fractional digits recording creation; `updated_at`, the same timestamp format refreshed on every mutation; and `version`, an integer starting low and incrementing by one on every mutation of the resource. Two resource kinds are immutable snapshots and therefore carry only `id` and `created_at` — `updated_at` and `version` are absent on both: the `ReportClaimEntry` rows frozen into a report at issuance, and the `ContributionAuditEvent` records of the audit trail. Any mutation described in this document — including automatic, system-driven state changes — refreshes the owning resource's `updated_at` and increments its `version` unless the resource is one of those two snapshot kinds.

### 2.6. The Exchange Rulebook

A singleton `ExchangeRule` resource holds every tunable threshold of the exchange. A `PlatformAdmin` initializes it once; attempting initialization when the singleton already exists is rejected with `ERR_EXCHANGE_RULE_EXISTS` (HTTP 409). On initialization every field takes its declared default: `retention_years` 7 (how far back losses are reportable), `reinvestigation_days` 30 (the dispute reinvestigation deadline), `correction_hold_days` 45 (the per-claim grace window after a dispute is filed during which a stale batch may be voided without freezing the carrier), `data_freeze_days` 60 (the duration of a compliance data freeze), `reciprocity_lag_threshold_days` 45 (the contribution lag at which reciprocity gating engages), `max_outstanding_inquiries` 50 (the cap on outstanding adverse action notices per carrier), `min_batch_claims` 1 and `max_batch_claims` 500 (the batch size bounds), `disclosure_window_days` 5 (the adverse action disclosure deadline), and `premium_weight_cap_cents` 500000 (the per-claim cap applied before premium weighting). A `PlatformAdmin` may later update any subset of these tunables; all five roles may read the rulebook.

### 2.7. Amounts, Precision, and Rounding

Monetary amounts are integers denominated in cents — claim paid amounts, the premium weighting cap, and the premium-weighted risk score are all integer cents. The identity certainty score is a number with exactly 2 decimal places, produced by rounding half up. Integer scores and counts are produced by rounding half up where a division is involved. Contribution lag is measured in whole days, floored toward zero, and never negative. Date and timestamp comparisons in this document state their boundary semantics explicitly at the point of use; where a boundary is described as inclusive, a value exactly equal to the threshold triggers the rule.

### 2.8. The Contribution Audit Trail

Every material event in the exchange appends a `ContributionAuditEvent` record carrying the affected `carrier_id`, an optional `consumer_id` (null for purely carrier-scoped events), an `event_type`, the logical-clock `event_at` instant, and a `details` payload holding event-specific ids, counts, and codes. The recognized event types are `BATCH_RECEIVED`, `BATCH_COMPLETED`, `BATCH_FAILED`, `BATCH_VOIDED`, `BATCH_FROZEN_BY_CORRECTION`, `CLAIM_ACCEPTED`, `CLAIM_REJECTED`, `CLAIM_AMENDED`, `CLAIM_WITHDRAWN`, `REPORT_ISSUED`, `REPORT_FROZEN`, `DISPUTE_FILED`, `DISPUTE_REINVESTIGATED`, `DISPUTE_OVERDUE`, `DISPUTE_RESOLVED`, `ADVERSE_ACTION_FILED`, `ADVERSE_ACTION_SENT`, `ADVERSE_ACTION_ACKNOWLEDGED`, `DATA_FREEZE_APPLIED`, `DATA_FREEZE_LIFTED`, `CARRIER_SUSPENDED`, `CARRIER_REACTIVATED`, and `RETENTION_REDACTED`. Audit records are immutable once written. Listings of the trail — exchange-wide, per carrier, or per consumer — may be filtered by `carrier_id`, `consumer_id`, and `event_type`.

### 2.9. Validation Pipeline and Error Ordering

When several checks could reject the same request, they are evaluated in a fixed priority order, and the first failing check determines the error returned. The order is: (1) authentication — the headers of §2.1, failing as `ERR_UNAUTHENTICATED`; (2) authorization — the role is permitted on this endpoint, failing as `ERR_UNAUTHORIZED`; (3) path existence — every identifier in the URL resolves, failing as `ERR_NOT_FOUND`; (4) body references — foreign keys declared in the request body resolve, failing as `ERR_REFERENCED_NOT_FOUND`; (5) state — the target resource is in a state that permits the operation, failing as `ERR_INVALID_STATE`; (6) consumer file freeze — file access and report issuance are blocked while a consumer file is frozen, failing as `ERR_CONSUMER_FILE_FROZEN`; (7) permissible purpose — the inquiry's declared purpose is valid, failing as `ERR_PERMISSIBLE_PURPOSE`; (8) contributory reciprocity — the inquiring carrier's standing, failing as `ERR_RECIPROCITY_REQUIRED` or `ERR_CARRIER_NOT_ACTIVE` as §3.3 describes; (9) standardized claim coding, failing as `ERR_INVALID_REQUEST`; (10) batch size and claim-number uniqueness, failing as `ERR_BATCH_CONSTRAINT`; (11) dispute timing and openness, failing as `ERR_DISPUTE_OVERDUE` or `ERR_DISPUTE_ALREADY_OPEN`; and (12) the outstanding adverse action notice cap, failing as `ERR_INQUIRY_CAP_EXCEEDED`. A stale optimistic-concurrency token surfaces as `ERR_STALE_VERSION` under the rules of §2.11. Because existence outranks state, and state outranks the business-safety checks, a request aimed at a nonexistent carrier always reports the missing resource rather than any downstream business violation.

### 2.10. Nested and Referenced Resource Resolution

Requests that carry multiple resource identifiers — in the path or in the body — are validated in a fixed sequence. Path identifiers resolve left to right (a carrier before a consumer before a dispute before a notice), and the first identifier that does not resolve yields `ERR_NOT_FOUND` (HTTP 404) without examining the rest. Foreign keys declared in a request body — the consumer attached to each claim row in a contribution batch, the claim cited by a new dispute, the report cited by a new adverse action notice, the claim being amended — resolve in the endpoint's input declaration order, and the first unresolvable reference yields `ERR_REFERENCED_NOT_FOUND` (HTTP 404).

### 2.11. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency on a parent entity's `version`, and they are the only endpoints that accept a version field at all — every other endpoint takes no version input:

- Filing a dispute for a consumer requires the request to carry `expected_consumer_version` holding the consumer `version` the client last observed. Because every consumer mutation — a prior dispute filing, a freeze, a freeze lift — advances that version, a filing whose `expected_consumer_version` no longer matches the consumer's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412) and no dispute is persisted.
- Creating a replacement claim that supersedes an existing claim requires `expected_claim_version` holding the claim `version` the client last observed. If the claim's version has advanced since — for example because a dispute filing or an earlier amendment already bumped it — the create is rejected with `ERR_STALE_VERSION` (HTTP 412) and no replacement is persisted.

## 3. Business Logic & Workflows

### 3.1. Carrier Registration and Standing

A `PlatformAdmin` registers a carrier with its `legal_name` and its `naic_code`; the `naic_code` must be unique across all carriers. A new carrier begins in `PROVISIONAL` standing, with `accepted_batch_count` and `accepted_claim_count` at zero and its `contribution_lag_days` not yet defined. A carrier's standing cycles through `PROVISIONAL`, `ACTIVE`, and `SUSPENDED`, and ends at `WITHDRAWN`, which is terminal.

Standing advances automatically. When a `PROVISIONAL` carrier's first contribution batch completes with at least one accepted claim, the carrier transitions to `ACTIVE` and a `CARRIER_REACTIVATED` audit event is appended — the same event type the exchange uses for both first activation and reactivation. When a carrier's `contribution_lag_days` reaches the rulebook's reciprocity threshold at a clock evaluation, an `ACTIVE` carrier is suspended, with a `CARRIER_SUSPENDED` event whose `details` record the lag; when a newly completed batch brings the lag back below the threshold, the carrier returns to `ACTIVE` with a `CARRIER_REACTIVATED` event. Each such standing change is a mutation of the carrier and bumps its `version`.

An `ExchangeComplianceOfficer` may withdraw a carrier that is `ACTIVE` or `SUSPENDED`, provided the carrier has no contribution batch still in `RECEIVED` or `VALIDATED`; a withdrawal attempted while such an in-flight batch exists is rejected with `ERR_INVALID_STATE`. Withdrawal moves the carrier to `WITHDRAWN`: its claims remain stored but are excluded from every future report, outstanding inquiry reads are unaffected, and any new quote inquiry for the carrier is rejected. Carriers may be listed with a `status` filter, and individually read, by the administrative, compliance, and carrier-side roles.

### 3.2. Contributing Loss History Batches

The contribution pipeline begins when a `CarrierDataSteward` submits a batch — a `claims` array of loss claim rows — on behalf of their own carrier. A `WITHDRAWN` carrier cannot contribute; the attempt is rejected with `ERR_CARRIER_NOT_ACTIVE`. Each claim row names the consumer the loss is attributed to via `consumer_id`, the carrier's `policy_number`, a carrier-side `claim_number` (unique within the contributing carrier), the `loss_date` as an ISO 8601 date, a `loss_type` of `COLLISION`, `COMPREHENSIVE`, `LIABILITY`, `PROPERTY`, or `OTHER`, a standardized `cause_of_loss_code` of one to eight uppercase alphanumeric characters, the `paid_amount_cents` as a non-negative integer (zero is allowed, representing a claim closed without payment), a `claim_status_code` of `OPEN`, `CLOSED_WITH_PAYMENT`, `CLOSED_WITHOUT_PAYMENT`, or `SUBROGATED`, and an optional `vehicle_identifier` that defaults to the empty string when no vehicle is associated.

Standardized coding is enforced per row. A row whose `cause_of_loss_code` violates the format, or whose `loss_type` or `claim_status_code` is not a declared member of its enum, is rejected individually and counted toward the batch's `rejected_count`; a request that is malformed at the envelope level — a missing required field or a bad enum member — fails outright with `ERR_INVALID_REQUEST` (HTTP 400). The batch as a whole must contain between `min_batch_claims` and `max_batch_claims` rows inclusive, and no row may reuse a `claim_number` the carrier has already contributed; either violation is rejected with `ERR_BATCH_CONSTRAINT` (HTTP 422). Accepted rows are recorded as `CLAIM_ACCEPTED` audit events and rejected rows as `CLAIM_REJECTED` events.

The batch lifecycle is automatic once the submission is accepted. A batch is born in `RECEIVED` with its `submitted_at` stamped from the logical clock; per-claim validation runs immediately, `claim_count` is set to the number of rows in the payload, `accepted_count` and `rejected_count` are recorded, the batch moves to `VALIDATED`, and a `BATCH_RECEIVED` event is appended. From `VALIDATED`, a batch with at least one accepted claim completes: every accepted claim becomes an `ACTIVE` loss claim whose `retention_expires_on` is its `loss_date` plus `retention_years` years, the carrier's `accepted_batch_count` grows by one and its `accepted_claim_count` grows by the batch's `accepted_count`, the carrier's `contribution_lag_days` is recomputed from this batch's `submitted_at`, the standing cascades of §3.1 fire as applicable, and a `BATCH_COMPLETED` event is appended. A `VALIDATED` batch with zero accepted claims instead transitions to `FAILED` with a `BATCH_FAILED` event. `COMPLETED`, `FAILED`, and `VOIDED` are all terminal.

An `ExchangeComplianceOfficer` may void a batch that is still in `RECEIVED` or `VALIDATED`, moving it to `VOIDED` and appending `BATCH_VOIDED`; voiding a terminal batch is rejected with `ERR_INVALID_STATE`. Voiding interacts with the correction hold of §3.7: while every open dispute against the batch's claims sits inside its correction hold window, the void is a clean correction; once any such dispute's hold window has lapsed, voiding the batch additionally suspends the contributing carrier. Batches are retrievable individually, per carrier, or across the exchange with `carrier_id` and `status` filters; the claims that arrived in a batch, the claims a carrier has contributed, and the report entries snapshotting a carrier's claims are all listed through carrier- and batch-scoped listings.

### 3.3. Contributory Reciprocity

Report access is earned by contribution. A carrier's `contribution_lag_days` is the number of whole days — floored, never negative — between its most recent `COMPLETED` batch's `submitted_at` and the logical clock. A carrier that has never completed a batch has no defined lag: it is simply `PROVISIONAL`, and its quote inquiries are rejected with `ERR_CARRIER_NOT_ACTIVE` (HTTP 409), as are the inquiries of a `WITHDRAWN` carrier. Once a carrier has completed a batch, reciprocity gating engages when `contribution_lag_days` reaches `reciprocity_lag_threshold_days`; the boundary is inclusive, so a lag exactly equal to the threshold suspends the carrier. A `SUSPENDED` carrier's inquiries are rejected with `ERR_RECIPROCITY_REQUIRED` (HTTP 409) — reports are withheld until contribution resumes — and the corresponding blocked outcome is recorded on the inquiry as described in §3.5. Suspension and reactivation are driven both by completing batches and by advancing the logical clock, which re-evaluates every carrier's lag in one sweep.

### 3.4. Quote Inquiries and Identity Matching

A `CarrierUnderwriter` submits a quote inquiry for their own carrier by supplying the applicant's `subject_name`, `subject_dob`, `subject_address`, `subject_driver_license`, an optional `subject_vehicle_identifier` (defaulting to the empty string), and a declared `permissible_purpose`. The permissible purpose must be one of `UNDERWRITING`, `CLAIMS`, or `CONSUMER_REQUEST`; a missing or out-of-enum value is rejected with `ERR_PERMISSIBLE_PURPOSE` (HTTP 403), and a `CONSUMER_REQUEST` inquiry is only lawful when the supplied subject identifiers resolve to the acting consumer — otherwise it fails with the same error. Every inquiry lands in `RESOLVED` status once matching completes, since matching runs synchronously at submission.

Matching builds a candidate bundle: the set of consumers sharing at least one identifier signal with the inquiry — driver license, name-plus-date-of-birth, address, or vehicle identifier. Each signal is graded `EXACT`, `FUZZY`, `MISMATCH`, or `ABSENT`, worth 50, 25, 0, and 0 points respectively. The individual match grade is taken from the strongest individual signal: the driver license comparison dominates, so a license match yields an `EXACT` individual grade; when the inquiry supplies no driver license, or no candidate matches it, the individual grade falls back to the name-plus-date-of-birth comparison, which grades at most `FUZZY`. The inquiry's `match_score` is then computed for each candidate bundle as the individual points multiplied by 100, plus the vehicle points multiplied by 30, plus the address points multiplied by 20, plus 50 for each `ACTIVE` loss claim in that candidate's bundle that passes the retention filter. The bundle with the highest `match_score` wins; ties break by the earliest consumer `created_at`, never by `id`. The score ranges from 0 to 10050, and the inquiry persists the winning bundle's `individual_match_grade`, `address_match_grade`, and `vehicle_match_grade` — each the highest grade achieved across the candidate bundles — together with the `match_score` itself.

The score maps to a four-rung disposition ladder with inclusive lower bounds: at least 7000 yields `DEFINITE`, at least 5500 yields `PROBABLE`, at least 4000 yields `POSSIBLE`, and anything below 4000 yields `UNMATCHED`. Two structural properties follow from the weights. An `EXACT` individual grade from a driver license match contributes 5000 points on its own, driving the score into the `DEFINITE` band as soon as a handful of reportable losses exist, even with `ABSENT` vehicle and address signals. Conversely, a `FUZZY` individual grade from a name-and-birthdate-only match caps the achievable band at `POSSIBLE` unless the vehicle and address signals both grade `EXACT` — this asymmetry is the exchange's guard against attributing another household's losses to an applicant. An `UNMATCHED` inquiry resolves with `matched_consumer_id` null, no report, and `report_blocked_reason` of `NONE`. Inquiries may be listed per carrier or across the exchange, filtered by `carrier_id`, `matched_consumer_id`, `report_id`, or `match_disposition`, and read individually.

### 3.5. Report Issuance and Risk Scoring

When an inquiry's disposition is not `UNMATCHED`, the exchange attempts to issue a `LossHistoryReport` to the inquiring carrier. Issuance has two gates, checked in the validation order of §2.9: the matched consumer's file must not be frozen (otherwise report issuance is blocked under `ERR_CONSUMER_FILE_FROZEN`), and the carrier must pass reciprocity (otherwise blocked under `ERR_RECIPROCITY_REQUIRED` or `ERR_CARRIER_NOT_ACTIVE` per §3.3). When the report leg is blocked, the inquiry is still recorded with `report_blocked_reason` set to `FROZEN` or `RECIPROCITY` accordingly and `report_id` left null. When issuance proceeds, the inquiry's `report_id` points at the new report, `report_blocked_reason` stays `NONE`, a `REPORT_ISSUED` audit event is appended, and the report's `delivered_at` is stamped from the logical clock.

A report captures the generating `inquiry_id`, the receiving `carrier_id`, the matched `consumer_id`, and the inquiry's `match_disposition` (`DEFINITE`, `PROBABLE`, or `POSSIBLE` — `UNMATCHED` inquiries never receive a report). Its inclusion set is then determined: all of the matched consumer's loss claims whose status is `ACTIVE`, whose contributing carrier is not `WITHDRAWN`, and whose `loss_date` is strictly newer than the logical clock date minus `retention_years` years. The date comparison is strict — a loss exactly `retention_years` old on the report date is excluded. Claims under dispute are outside the inclusion set because they are not `ACTIVE`. The number of included claims becomes `claim_count_reported`, and each included claim is snapshotted into a `ReportClaimEntry` preserving its `loss_date`, `loss_type`, `cause_of_loss_code`, `paid_amount_cents`, `claim_status_code`, and `contributing_carrier_id`, along with the owning `report_id`, the snapshotted `loss_claim_id`, and a denormalized `consumer_id` for reverse lookup. Entries are ordered by `loss_date` descending with `created_at` ascending as the tie-break — never by `id` — and numbered with a 1-based `entry_sequence` in that order.

Three risk scores are computed and persisted on every report. The identity certainty, `risk_score_certainty`, is the inquiry's `match_score` divided by 100 and expressed with exactly two decimals, rounded half up — a `match_score` of 7550 yields 75.50 — and ranges from 0.00 to 100.50. The frequency variant, `risk_score_count`, is `claim_count_reported` multiplied by `risk_score_certainty`, rounded half up to an integer; it drives claim-frequency-based pricing, so a consumer with three zero-payment claims scores higher than one with a single large paid loss. The severity variant, `risk_score_premium_weighted_cents`, first caps each included claim's `paid_amount_cents` at `premium_weight_cap_cents`, sums the capped amounts, multiplies by `risk_score_certainty`, divides by 100, and rounds half up to integer cents; it drives severity-based pricing, so a single large loss outweighs several small ones. The two variants are always computed together and diverge whenever the average capped paid amount per claim differs from 100 cents — which is to say, almost always. Reports and their entries are retrievable individually and through listings filterable by `inquiry_id`, `consumer_id`, `carrier_id`, `status`, `report_id`, `loss_claim_id`, or `contributing_carrier_id`, with a report's entries always returned in `entry_sequence` order.

### 3.6. Consumer Files, Freezes, and File Disclosure

A `PlatformAdmin` registers a consumer file with the consumer's `full_name`, `date_of_birth` (an ISO 8601 date), current `address_line`, and `driver_license_number`. New files are born unfrozen: `file_frozen` false and `frozen_until` null. A consumer may read their own file — the file-disclosure view returns the `consumer` record together with their `claims`, `disputes`, and `adverse_action_notices` — and may browse their own claims, disputes, inquiries resolved to them, reports about them, report entries snapshotting their claims, and notices addressed to them. Consumers are listed by the administrative and compliance roles.

An `ExchangeComplianceOfficer` may apply a data freeze to a consumer file. Freezing sets `file_frozen` true, sets `frozen_until` to the logical clock plus `data_freeze_days` days, increments the consumer's `version`, and appends `DATA_FREEZE_APPLIED`. The freeze cascades immediately: every `ISSUED` report whose subject is the frozen consumer transitions to `FROZEN` — the terminal state of a report — with a `REPORT_FROZEN` event appended for each. While the freeze is in force, two things are blocked: the consumer's own file-disclosure read is rejected with `ERR_CONSUMER_FILE_FROZEN` (HTTP 409), and report issuance on any inquiry resolving to that consumer is blocked as §3.5 describes. A carrier holding a `FROZEN` report that is referenced by an outstanding `DRAFT` or `SENT` adverse action notice must resolve that notice — by sending or cancelling it — before filing new inquiries that would consume the report. When the logical clock reaches `frozen_until`, the freeze lifts automatically: `file_frozen` returns to false, `frozen_until` clears, and `DATA_FREEZE_LIFTED` is appended. Frozen reports do not thaw; `FROZEN` is terminal.

### 3.7. Disputes, Reinvestigation, and Correction

A consumer who believes a loss record is inaccurate files a dispute against it, naming the `loss_claim_id`, a `dispute_reason` of `NOT_MY_CLAIM`, `WRONG_AMOUNT`, `WRONG_DATE`, `ALREADY_REMOVED`, or `OTHER`, and a free-text `dispute_statement` of at most 2000 characters; the filing must also carry `expected_consumer_version` per §2.11. Only a consumer's own disputes may be filed under their identity, and the disputed claim must be `ACTIVE` — a filing against a claim in any other status is rejected with `ERR_INVALID_STATE` — with no other dispute against the same claim already `FILED` or `UNDER_REINVESTIGATION`, which would be rejected with `ERR_DISPUTE_ALREADY_OPEN` (HTTP 409). A successful filing moves the claim to `UNDER_DISPUTE` — removing it from the inclusion set of any report issued thereafter — records `filed_at` from the logical clock, sets `reinvestigation_due_at` to `filed_at` plus `reinvestigation_days` days, increments the consumer's `version`, and appends `DISPUTE_FILED`. The dispute begins in `FILED` status.

The reinvestigation clock is strict. An `ExchangeComplianceOfficer` moves a `FILED` dispute to `UNDER_REINVESTIGATION` by beginning reinvestigation, which appends `DISPUTE_REINVESTIGATED`; resolution may follow from either `FILED` or `UNDER_REINVESTIGATION`. Both actions require the logical clock to be strictly before `reinvestigation_due_at` — at or past the deadline the boundary is inclusive and the action is rejected with `ERR_DISPUTE_OVERDUE` (HTTP 409). When a still-open dispute passes its deadline at a clock evaluation, a `DISPUTE_OVERDUE` audit event is appended and the dispute remains open but unresolvable, terminal for action purposes; it can only be closed by a fresh filing cycle after the underlying data is corrected.

Resolution takes one of three `resolution_code` values, recorded with `resolution_notes`, the `resolved_at` timestamp, and a terminal dispute status. `VERIFIED_ACCURATE` returns the claim to `ACTIVE` — restoring it to the reportable population — and closes the dispute as `RESOLVED_VERIFIED` with a `DISPUTE_RESOLVED` event. `DELETED` moves the claim to `WITHDRAWN`, permanently excluding it from all future reports, and closes the dispute as `RESOLVED_DELETED` with `CLAIM_WITHDRAWN` and `DISPUTE_RESOLVED` events. `AMENDED` creates the correcting claim in the same request from the supplied `corrected_loss_date`, `corrected_loss_type`, `corrected_cause_of_loss_code`, `corrected_paid_amount_cents`, `corrected_claim_status_code`, and optional `corrected_vehicle_identifier`: the replacement becomes an `ACTIVE` claim whose `amendment_of_id` points at the disputed claim and whose `retention_expires_on` is freshly computed, the disputed claim becomes `AMENDED`, and the dispute closes as `RESOLVED_AMENDED` with `CLAIM_AMENDED` and `DISPUTE_RESOLVED` events.

Corrections also flow carrier-side. A `CarrierDataSteward` may file a replacement claim superseding an `ACTIVE` claim their carrier contributed, supplying fresh `loss_date`, `loss_type`, `cause_of_loss_code`, `paid_amount_cents`, `claim_status_code`, and optionally `vehicle_identifier`, together with `expected_claim_version` per §2.11. The replacement is born `ACTIVE` with `amendment_of_id` set to the superseded claim and a fresh `retention_expires_on`; the superseded claim transitions automatically to `AMENDED` and leaves the reportable population, and its `version` increments by one. A claim's amendment lineage — zero or one replacement rows — and the disputes filed against it are both browsable, and claims across the exchange may be listed with `contributing_carrier_id`, `batch_id`, `consumer_id`, `amendment_of_id`, and `status` filters.

The correction hold couples disputes back to batch governance. When a dispute is filed, its `filed_at` is compared against the contributing carrier's latest `COMPLETED` batch: the hold window is open while the gap between the batch's `submitted_at` and the filing is strictly less than `correction_hold_days` days — a dispute filed exactly `correction_hold_days` after the batch falls outside the window. While the window is open, voiding the disputed claim's batch is a clean correction recorded as `BATCH_VOIDED`; once the window has lapsed for any open dispute on that batch's claims, voiding the batch additionally suspends the carrier, the `BATCH_FROZEN_BY_CORRECTION` event type marking this correction-driven escalation in the audit trail.

### 3.8. Adverse Action Notices

When a report influences a carrier's pricing or declination decision, a `CarrierUnderwriter` of that carrier files an adverse action notice citing the `report_id`, an `action_type` of `DECLINE`, `RATE_INCREASE`, `NON_RENEWAL`, or `CANCELLATION`, an ordered `notice_reason_codes` list of one to five codes (each two to sixteen characters of uppercase alphanumerics and dashes), and a `report_influence_rank` of 1, 2, or 3 — the report as primary factor, contributing factor, or marginal factor respectively. The notice's `consumer_id` is derived from the cited report, its `disclosure_deadline` is established as the logical-clock instant of creation plus `disclosure_window_days` days, and the filing is recorded as `ADVERSE_ACTION_FILED`. Notices begin in `DRAFT` status.

The exchange caps concurrent consumer-impact activity: a carrier's outstanding notices — those in `DRAFT` or `SENT` — may not reach `max_outstanding_inquiries`. The boundary is inclusive, so when a carrier's outstanding count already equals the cap, the next filing and the next send are both rejected with `ERR_INQUIRY_CAP_EXCEEDED` (HTTP 409).

Sending a notice is the underwriter's act, valid only while the notice is `DRAFT` — sending a notice in any other state fails with `ERR_INVALID_STATE` — and additionally requires that the acting underwriter belongs to the notice's carrier, that the cited report is still in `ISSUED` status, and that the carrier's outstanding count is strictly below the cap at send time. Sending stamps `disclosure_deadline` as the logical clock at send time plus `disclosure_window_days` days and appends `ADVERSE_ACTION_SENT`. The addressed consumer — and only that consumer — may then acknowledge receipt, moving the notice from `SENT` to `ACKNOWLEDGED` with an `ADVERSE_ACTION_ACKNOWLEDGED` event; acknowledgment by anyone else fails authorization. Alternatively, the owning carrier's underwriter may cancel a `DRAFT` notice, moving it to `CANCELLED`. Both `ACKNOWLEDGED` and `CANCELLED` are terminal. Notices are browsable per carrier, per consumer, per report, and across the exchange with `carrier_id`, `report_id`, `consumer_id`, and `status` filters.

## 4. Endpoint Definitions

Operations that create a new resource — registering a carrier or consumer, initializing the rulebook, contributing a batch, filing an inquiry, dispute, amendment, or notice — return `201 Created`. Operations that modify an existing resource, drive a state transition, advance the clock, or acknowledge a notice return `200 OK`. All reads return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the logical clock and re-evaluate time-driven rules | PlatformAdmin |
| POST | `/exchange-rules` | Initialize the singleton exchange rulebook | PlatformAdmin |
| GET | `/exchange-rules` | Read the exchange rulebook | PlatformAdmin, ExchangeComplianceOfficer, CarrierDataSteward, CarrierUnderwriter, Consumer |
| PATCH | `/exchange-rules` | Update one or more rulebook tunables | PlatformAdmin |
| POST | `/carriers` | Register a carrier (starts PROVISIONAL) | PlatformAdmin |
| GET | `/carriers` | List carriers | PlatformAdmin, ExchangeComplianceOfficer |
| GET | `/carriers/{carrierId}` | Get a carrier | PlatformAdmin, ExchangeComplianceOfficer, CarrierDataSteward, CarrierUnderwriter |
| POST | `/carriers/{carrierId}/withdraw` | Withdraw a carrier from the exchange | ExchangeComplianceOfficer |
| POST | `/carriers/{carrierId}/batches` | Contribute a batch of loss claims | CarrierDataSteward |
| GET | `/carriers/{carrierId}/batches` | List a carrier's contribution batches | PlatformAdmin, ExchangeComplianceOfficer, CarrierDataSteward |
| GET | `/carriers/{carrierId}/claims` | List loss claims contributed by a carrier | PlatformAdmin, ExchangeComplianceOfficer, CarrierDataSteward |
| GET | `/carriers/{carrierId}/report-entries` | List report entries snapshotting this carrier's claims | PlatformAdmin, ExchangeComplianceOfficer, CarrierDataSteward |
| GET | `/carriers/{carrierId}/audit-events` | List audit events affecting a carrier | PlatformAdmin, ExchangeComplianceOfficer |
| GET | `/carriers/{carrierId}/inquiries` | List a carrier's quote inquiries | PlatformAdmin, ExchangeComplianceOfficer, CarrierUnderwriter |
| POST | `/carriers/{carrierId}/inquiries` | Submit a quote inquiry and resolve identity matching | CarrierUnderwriter |
| GET | `/carriers/{carrierId}/reports` | List reports delivered to a carrier | PlatformAdmin, ExchangeComplianceOfficer, CarrierUnderwriter |
| GET | `/carriers/{carrierId}/adverse-action-notices` | List a carrier's adverse action notices | PlatformAdmin, ExchangeComplianceOfficer, CarrierUnderwriter |
| POST | `/carriers/{carrierId}/adverse-action-notices` | File an adverse action notice citing a report | CarrierUnderwriter |
| GET | `/batches` | List contribution batches across carriers | PlatformAdmin, ExchangeComplianceOfficer |
| GET | `/batches/{batchId}` | Get a contribution batch | PlatformAdmin, ExchangeComplianceOfficer, CarrierDataSteward |
| POST | `/batches/{batchId}/void` | Void a non-terminal batch (may suspend the carrier) | ExchangeComplianceOfficer |
| GET | `/batches/{batchId}/claims` | List loss claims that arrived in a batch | PlatformAdmin, ExchangeComplianceOfficer, CarrierDataSteward |
| GET | `/claims` | List loss claims across the exchange | PlatformAdmin, ExchangeComplianceOfficer |
| GET | `/claims/{claimId}` | Get a loss claim | PlatformAdmin, ExchangeComplianceOfficer, CarrierDataSteward, Consumer |
| POST | `/claims/{claimId}/amendments` | Create a replacement claim superseding an ACTIVE claim | CarrierDataSteward |
| GET | `/claims/{claimId}/amendments` | List replacement claims amending this claim | PlatformAdmin, ExchangeComplianceOfficer, CarrierDataSteward, Consumer |
| GET | `/claims/{claimId}/disputes` | List disputes filed against this claim | PlatformAdmin, ExchangeComplianceOfficer, Consumer |
| GET | `/claims/{claimId}/report-entries` | List report entries snapshotting this claim | PlatformAdmin, ExchangeComplianceOfficer, CarrierDataSteward, Consumer |
| POST | `/consumers` | Register a consumer file | PlatformAdmin |
| GET | `/consumers` | List consumers | PlatformAdmin, ExchangeComplianceOfficer |
| GET | `/consumers/{consumerId}` | Get a consumer | PlatformAdmin, ExchangeComplianceOfficer, Consumer |
| GET | `/consumers/{consumerId}/file` | Consumer file access (file disclosure) | Consumer |
| POST | `/consumers/{consumerId}/freeze` | Apply a data freeze to a consumer file | ExchangeComplianceOfficer |
| GET | `/consumers/{consumerId}/claims` | List loss claims attributed to a consumer | PlatformAdmin, ExchangeComplianceOfficer, Consumer |
| GET | `/consumers/{consumerId}/reports` | List reports whose subject is this consumer | PlatformAdmin, ExchangeComplianceOfficer, Consumer |
| GET | `/consumers/{consumerId}/report-entries` | List report entries snapshotting this consumer's claims | PlatformAdmin, ExchangeComplianceOfficer, Consumer |
| GET | `/consumers/{consumerId}/inquiries` | List inquiries resolved to this consumer | PlatformAdmin, ExchangeComplianceOfficer, Consumer |
| GET | `/consumers/{consumerId}/disputes` | List a consumer's disputes | PlatformAdmin, ExchangeComplianceOfficer, Consumer |
| POST | `/consumers/{consumerId}/disputes` | File a dispute against a loss claim | Consumer |
| GET | `/consumers/{consumerId}/adverse-action-notices` | List notices addressed to this consumer | PlatformAdmin, ExchangeComplianceOfficer, Consumer |
| GET | `/consumers/{consumerId}/audit-events` | List audit events affecting this consumer | PlatformAdmin, ExchangeComplianceOfficer |
| GET | `/inquiries` | List inquiries across carriers | PlatformAdmin, ExchangeComplianceOfficer |
| GET | `/inquiries/{inquiryId}` | Get an inquiry | PlatformAdmin, ExchangeComplianceOfficer, CarrierUnderwriter |
| GET | `/reports` | List reports across carriers | PlatformAdmin, ExchangeComplianceOfficer |
| GET | `/reports/{reportId}` | Get a loss history report | PlatformAdmin, ExchangeComplianceOfficer, CarrierUnderwriter, Consumer |
| GET | `/reports/{reportId}/entries` | List a report's claim entries in entry order | PlatformAdmin, ExchangeComplianceOfficer, CarrierUnderwriter, Consumer |
| GET | `/reports/{reportId}/adverse-action-notices` | List notices citing this report | PlatformAdmin, ExchangeComplianceOfficer, CarrierUnderwriter |
| GET | `/report-entries` | List report claim entries across reports | PlatformAdmin, ExchangeComplianceOfficer |
| GET | `/report-entries/{entryId}` | Get a single report claim entry | PlatformAdmin, ExchangeComplianceOfficer, CarrierUnderwriter, Consumer |
| GET | `/disputes` | List disputes across consumers | PlatformAdmin, ExchangeComplianceOfficer |
| GET | `/disputes/{disputeId}` | Get a dispute | PlatformAdmin, ExchangeComplianceOfficer, Consumer |
| POST | `/disputes/{disputeId}/begin-reinvestigation` | Move a FILED dispute into reinvestigation | ExchangeComplianceOfficer |
| POST | `/disputes/{disputeId}/resolve` | Resolve a dispute (verify, amend, or delete) | ExchangeComplianceOfficer |
| GET | `/adverse-action-notices` | List notices across carriers | PlatformAdmin, ExchangeComplianceOfficer |
| GET | `/adverse-action-notices/{noticeId}` | Get an adverse action notice | PlatformAdmin, ExchangeComplianceOfficer, CarrierUnderwriter, Consumer |
| POST | `/adverse-action-notices/{noticeId}/send` | Send a DRAFT notice (sets the disclosure deadline) | CarrierUnderwriter |
| POST | `/adverse-action-notices/{noticeId}/acknowledge` | Consumer acknowledges receipt of a SENT notice | Consumer |
| POST | `/adverse-action-notices/{noticeId}/cancel` | Cancel a DRAFT notice | CarrierUnderwriter |
| GET | `/audit-events` | List contribution audit events, most recent first | PlatformAdmin, ExchangeComplianceOfficer |
| GET | `/audit-events/{eventId}` | Get a single audit event | PlatformAdmin, ExchangeComplianceOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENCED_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_CARRIER_NOT_ACTIVE` | 409 Conflict |
| `ERR_RECIPROCITY_REQUIRED` | 409 Conflict |
| `ERR_PERMISSIBLE_PURPOSE` | 403 Forbidden |
| `ERR_CONSUMER_FILE_FROZEN` | 409 Conflict |
| `ERR_DISPUTE_ALREADY_OPEN` | 409 Conflict |
| `ERR_DISPUTE_OVERDUE` | 409 Conflict |
| `ERR_BATCH_CONSTRAINT` | 422 Unprocessable Entity |
| `ERR_INQUIRY_CAP_EXCEEDED` | 409 Conflict |
| `ERR_EXCHANGE_RULE_EXISTS` | 409 Conflict |
