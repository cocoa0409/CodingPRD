# Ambient Clinical Documentation API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Ambient Clinical Documentation API, the service that backs an ambient clinical documentation capture and physician attestation platform. Clinical documentation is among the largest contributors to physician burnout: hours of structured note-writing spill into after-hours "pajama time," and every minute spent at the keyboard is a minute taken from the patient. The platform this API powers lets a physician hold a normal conversation in the exam room while an ambient recorder, with the patient's explicit consent, captures the encounter audio, separates the speakers, and drafts a structured note mapped into the specialty's template and discrete fields. The physician then reviews, edits, and attests — only after attestation does the note become part of the legal medical record.

Consent is the spine of the system. Every recording decision flows through an explicit, encounter-scoped ambient consent that requires posted room signage, honors a patient's standing preference only as a default, and supports opt-out and compliance revocation with strict downstream consequences: in-flight audio is purged, retained audio has its retention window shortened, and any note content derived from the audio is invalidated so the physician re-touches it. Attested notes are never silently rewritten — the legal record is preserved and flagged for review instead.

Because the platform operates on protected health information and feeds billing, the API also enforces segregation of duties between clinicians, quality assurance auditors, and compliance operators; a dual-variant billing model that distinguishes provisional (confidence-weighted) totals from final (clinician-confirmed) totals; quality sampling with appeals; and adoption measurement of documentation time and after-hours charting. All time-dependent behavior is driven by a server-side logical clock so that tests and demonstrations can advance time deterministically.

## 2. Global Specifications & System-Wide Principles

This section defines the rules that apply uniformly across the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, which identifies the acting party, and `X-User-Role`, which declares the capacity in which they act. The system recognizes five roles, spelled exactly as follows: `Patient`, `Physician`, `QAAuditor`, `ComplianceOfficer`, and `PlatformAdmin`. A request with either header missing, or whose role is not one of the five declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is authenticated but is not permitted for the target endpoint — or which fails an entity-backed ownership check — is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The identity semantics of `X-User-ID` differ by role and are contractual:

- When `X-User-Role` is `Patient`, `X-User-ID` is the `id` of the acting `Patient`; ownership checks on any resource that references a `Patient` (for example, an `AmbientConsent`'s `patient_id`) compare the resource's foreign-key field to `X-User-ID`.
- When `X-User-Role` is `Physician`, `X-User-ID` is the `id` of the acting `Physician`; ownership checks on any resource that references a `Physician` (for example, an `Encounter`'s `physician_id` or a `NoteDraft`'s `author_physician_id`) compare the resource's foreign-key field to `X-User-ID`.
- When `X-User-Role` is `QAAuditor`, `X-User-ID` is the `id` of the acting `QAAuditor`; ownership checks on any resource that references a `QAAuditor` (for example, a `QASample`'s `auditor_id`) compare the resource's foreign-key field to `X-User-ID`.
- When `X-User-Role` is `ComplianceOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `created_by_user_id` on a manually queued `QASample`) but does not compare it to any entity's `id`.
- When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity and is never compared against a resource's foreign key.

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

List endpoints are paginated via two query parameters. `limit` sets the maximum number of items returned per page; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` sets the number of items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns its resources sorted by `created_at` in ascending order. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Resource Identity, Timestamps, and Versioning

Every primary resource carries a standard set of system-managed properties. `id` is a server-minted UUID with no type prefix. `created_at` and `updated_at` are ISO 8601 UTC timestamps rendered with three fractional digits; `updated_at` refreshes on every mutation. `version` is an integer that starts at its initial value at creation and increments by exactly 1 on every mutation of the resource, including mutations performed as a side effect of an operation on another resource (for example, the `Encounter.version` bump when a note draft is generated against the encounter).

One resource is deliberately exempt from the full set: an `Attestation` is an append-only legal-record entry and carries only `id` and `created_at`. It has no `updated_at` and no `version`, because attestations are never modified after creation.

### 2.5. The Logical Clock

All time-aware behavior — timestamps such as `started_at`, `ended_at`, `granted_at`, `attested_at`, `finalized_at`, retention eligibility, gap buffers, and after-hours windows — is evaluated against a server-side logical clock, never against wall-clock time. At server startup the logical clock reads 2026-09-01T00:00:00Z, and it never falls back to wall-clock time on its own. A `PlatformAdmin`-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant; the current logical time is returned as `current_utc`.

### 2.6. Precision, Rounding, and Monetary Values

Numeric rules are uniform. Completeness and QA scores are integers between 0 and 100 inclusive, produced with round-half-up. Diarization confidence values (`base_confidence`, `effective_confidence`, and code-suggestion `confidence`) are numbers between 0 and 1 inclusive, carried to at most 4 decimal places and rounded half-up. Monetary amounts are integer cents; line totals and billing totals are always integers. Rounding order is pinned wherever it matters and is stated alongside each calculation in §3.

### 2.7. Optimistic Concurrency Control

Two write operations participate in optimistic concurrency control, and no others do.

Editing a note draft requires the request to carry `expected_note_draft_version`, a non-optional input holding the `version` of the `NoteDraft` the client last observed. If that value does not match the draft's current `version` — because another write (a physician edit, a regenerate cycle, or a consent-driven cascade that recomputed completeness) has advanced it since the client last read the draft — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). This prevents a client from silently overwriting content it has not observed.

Generating a note draft against an encounter requires the request to carry `expected_encounter_version`, a non-optional input holding the `version` of the parent `Encounter` the client last observed. If the encounter's `version` has advanced since then, the create is rejected with `ERR_STALE_VERSION` (HTTP 412). The check exists because draft generation supersedes (voids) any existing non-terminal draft, so a stale view of the encounter means the client cannot know which draft it would supersede.

Endpoints not named above do not take a version field.

### 2.8. Nested Resource Retrieval

When an endpoint path contains multiple resource identifiers, the server validates the identifiers in left-to-right order. The request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first path identifier that does not resolve to an existing resource; deeper identifiers are not examined once an earlier one fails.

### 2.9. Validation Ordering

Where several validation rules could reject the same request, the server evaluates them in a fixed priority order so that the surfaced error is deterministic. Authentication (`ERR_UNAUTHENTICATED`) is checked first, then authorization and ownership (`ERR_UNAUTHORIZED`), then left-to-right path resolution (`ERR_NOT_FOUND`), then request shape and referential validity (`ERR_INVALID_REQUEST`, `ERR_SPEAKER_ROLE_INVALID`, `ERR_TEMPLATE_FIELD_MISMATCH`, `ERR_CODE_VALUE_MALFORMED`), then safety gates (`ERR_CONSENT_REQUIRED`, `ERR_CONSENT_NOT_ACTIVE`, `ERR_LEGAL_HOLD_ACTIVE`, `ERR_PHYSICIAN_NOT_ACTIVE`), then state-machine legality (`ERR_INVALID_STATE` and its more specific siblings), then business constraints (`ERR_SIGNAGE_NOT_POSTED`, `ERR_DUPLICATE_CONSENT`, `ERR_CAPTURE_ACTIVE_EXISTS`, `ERR_TEMPLATE_INACTIVE`, `ERR_NO_TRANSCRIBED_AUDIO`, `ERR_NOTE_INCOMPLETE`, `ERR_CODE_LIMIT_EXCEEDED`, `ERR_QA_MAX_APPEALS`, `ERR_QA_SELF_REVIEW_FORBIDDEN`, `ERR_AUDITOR_SPECIALTY_MISMATCH`), then temporal rules (`ERR_CAPTURE_GAP_VIOLATION`, `ERR_SEGMENT_OVERLAP`), and finally the fiscal cap (`ERR_BILLING_CAP_EXCEEDED`). An attestation request, for example, surfaces `ERR_QA_HOLD_ACTIVE` (a state rule) before `ERR_NOTE_INCOMPLETE` (a business constraint) when both would apply, and a capture start surfaces `ERR_CONSENT_REQUIRED` before `ERR_CAPTURE_ACTIVE_EXISTS` or `ERR_CAPTURE_GAP_VIOLATION`.

## 3. Business Logic & Workflows

### 3.1. Registries: Patients, Physicians, Auditors, and Note Templates

Four registries anchor the platform, all administered by a `PlatformAdmin`. A patient registration supplies the medical record number `mrn` (unique across all patients), the `full_name`, and an optional `default_ambient_opt_in` boolean (default true) that records the patient's standing preference about ambient recording. The standing preference is informational only: every encounter still requires its own explicit consent, as described in §3.2.

A physician registration supplies the National Provider Identifier `npi` (unique), the `full_name`, and a `specialty_code` such as CARD, FM, or ORTHO, which drives template selection and QA routing. A physician's `status` begins as `ACTIVE` and may be moved to `SUSPENDED` by a `PlatformAdmin` status update; suspension blocks attestation as described in §3.5, and each such update increments the physician's `version`.

A QA auditor registration supplies a unique `employee_code`, the `full_name`, and `specialty_codes`, an array of non-empty specialty codes the auditor is certified to score. An auditor's `status` begins as `ACTIVE`; an auditor whose `status` is `INACTIVE` cannot be assigned to samples.

A note template registration supplies the `specialty_code` it serves, a human-readable `template_version` label (unique together with the specialty code), and `field_specs` — an ordered array of objects, each with a `key`, an `importance` of `CRITICAL`, `MAJOR`, or `MINOR`, and a `required` flag. A template must declare at least one field spec, and each `key` must be unique within the template. Two optional tunables refine scoring: `completeness_multiplier` (default 1.0, must be greater than 0 and at most 3.0) scales missing-field penalties for specialty-specific model tuning, and `low_confidence_threshold` (default 90, between 0 and 100) sets the completeness bar below which attested notes auto-queue a low-confidence QA sample. A template's `active` flag (default true) governs whether new drafts may be created from it; a `PlatformAdmin` may flip `active` on an existing template, and each activation change increments the template's `version`.

### 3.2. Encounters and Ambient Consent

A `Physician` opens an encounter by supplying the `patient_id` of the patient to be seen and the `physician_id` of the attending physician; the attending must be the caller, so `physician_id` must equal the caller's `X-User-ID`. An optional `scheduled_start` records the booked time and is informational. The encounter's lifecycle runs across three parallel dimensions on one row. The first, `encounter_status`, begins at `SCHEDULED`; starting the encounter (attending physician only) moves `SCHEDULED` to `IN_PROGRESS` and stamps `started_at` from the logical clock; completing it moves `IN_PROGRESS` to `COMPLETED` and stamps `ended_at`; cancellation from either `SCHEDULED` or `IN_PROGRESS` — available to a `Physician` or a `ComplianceOfficer` — moves the encounter to `CANCELLED`, stamps `ended_at`, and records the optional `cancel_reason` from the request. Start and complete are restricted to the attending physician, and completion is refused while any capture of the encounter is still `RECORDING` or `PAUSED`. The second dimension, `audio_status`, begins at `NOT_RECORDING`, becomes `RECORDING_ACTIVE` while any capture is `RECORDING` or `PAUSED`, and settles at `AUDIO_STOPPED` when recording ceases. The third, `documentation_status`, begins at `NOT_STARTED` and mirrors the active note draft's status (`DRAFTING`, `IN_REVIEW`, `ATTESTED`, `AMENDED`). The three dimensions advance independently: audio and documentation are moved purely by side effects of capture and draft transitions, and attestation remains allowed after the encounter is `COMPLETED` to support after-hours charting. Starting, completing, and cancelling each increment the encounter's `version`.

Before any audio may roll, the encounter needs an `AmbientConsent` scoped to it: the consent's `encounter_id` ties it to that encounter, and its `patient_id` must equal the encounter's own patient. A `Patient` (for their own `patient_id` only) or a `ComplianceOfficer` grants consent by supplying the `patient_id`, confirming that room signage disclosing ambient recording was posted (`signage_posted`), and declaring how consent was captured via `captured_via` — one of `ROOM_SIGNAGE`, `VERBAL`, or `PORTAL`. Granting stamps `granted_at`. Signage is non-negotiable: a grant with `signage_posted` other than true is rejected with `ERR_SIGNAGE_NOT_POSTED`. At most one consent may be `GRANTED` per encounter; a second grant while one is active is rejected with `ERR_DUPLICATE_CONSENT`. A consent's `status` begins at `GRANTED` and ends in one of three terminal states, each stamping `ended_at` and recording an `end_reason`: `OPTED_OUT` (end_reason `OPT_OUT`), `REVOKED` (end_reason `REVOKE`), or `EXPIRED` (end_reason `EXPIRE`). The optional free-text `revocation_reason` may accompany an opt-out or revocation; `end_reason` is null while the consent is `GRANTED`.

A patient opts out of their own consent at any time — `X-User-ID` must match the consent's `patient_id` — and a `ComplianceOfficer` may revoke one; both carry an optional `reason`. Opt-out and revocation trigger the same three-link cascade, with only the purge reason differing (`OPT_OUT` versus `REVOKE`). Link one: every capture of the encounter in `RECORDING` or `PAUSED` is purged, and every capture already in `CAPTURED` or `TRANSCRIBED` has its `retention_days_effective` shortened to the lesser of its planned retention and 30 days. Link two: every note field of the encounter's drafts whose `source` is `AUDIO` has its `field_value` nulled and its `validated` flag reset to false; the field's `source` remains `AUDIO`. Link three: drafts of the encounter in `IN_REVIEW` or `EDITED` are demoted back to `DRAFT` with their `completeness_score` recomputed, while drafts already `ATTESTED` are left untouched in status — the attested legal record is immutable — and are instead flagged with `phi_review_required` set to true. Once all captures of the encounter are terminal, the encounter's `audio_status` returns to `NOT_RECORDING`.

Cancelling an encounter triggers a related but narrower cascade: a still-`GRANTED` consent on the cancelled encounter expires (`GRANTED` → `EXPIRED`, end_reason `EXPIRE`), and any captures in `RECORDING` or `PAUSED` are purged with purge reason `CANCEL`. The retention sweep described in §3.8 likewise expires consents that remain `GRANTED` on `CANCELLED` encounters.

### 3.3. Audio Capture and Speaker Segmentation

Once an encounter is `IN_PROGRESS` and holds a `GRANTED` consent, the attending physician may start an audio capture, supplying `planned_retention_days` — the requested retention window, between 1 and 3650 days. Starting a capture without a `GRANTED` consent is rejected with `ERR_CONSENT_REQUIRED`; starting one while the encounter is not `IN_PROGRESS` is rejected with `ERR_ENCOUNTER_NOT_IN_PROGRESS`; starting one while another capture of the same encounter is `RECORDING` or `PAUSED` is rejected with `ERR_CAPTURE_ACTIVE_EXISTS`. A gap buffer also applies: a new capture may start only at least 60 seconds after the most recently stopped capture's `ended_at` on the same encounter — a start exactly 60 seconds later is allowed, one second earlier is rejected with `ERR_CAPTURE_GAP_VIOLATION`. A fresh capture begins in `RECORDING` with `started_at` stamped from the logical clock, and the encounter's `audio_status` becomes `RECORDING_ACTIVE`.

The attending physician may pause a `RECORDING` capture and later resume it. Pausing opens a pause interval during which `recorded_seconds` accrual suspends; resuming closes it. The pause/resume pair is a compensating invariant: it leaves `recorded_seconds` unchanged. Stopping — permitted from either `RECORDING` or `PAUSED` — moves the capture to `CAPTURED`, stamps `ended_at`, finalizes `recorded_seconds` as the sum of the `RECORDING` intervals between `started_at` and `ended_at` with paused time excluded, and sets the encounter's `audio_status` to `AUDIO_STOPPED`.

Transcription is a deterministic, test-driving step: a `PlatformAdmin` may advance a `CAPTURED` capture to `TRANSCRIBED` by supplying its `audio_capture_id`, provided the encounter still holds a `GRANTED` consent (otherwise `ERR_CONSENT_NOT_ACTIVE`). Only after transcription does the audio become available for note regeneration. A capture's `retention_days_effective` normally equals its `planned_retention_days`; it is clamped downward only by the consent cascade described in §3.2. A `legal_hold` flag (default false) marks a capture under compliance hold and blocks both manual purge and retention expiry.

Compliance purging is available to a `ComplianceOfficer` on captures in `CAPTURED` or `TRANSCRIBED`. A purge on a capture whose `legal_hold` is true is rejected with `ERR_LEGAL_HOLD_ACTIVE`; otherwise the capture moves to `PURGED` with `purge_reason` `MANUAL`, and its speaker segments cease to be returned by list endpoints. Captures in `RECORDING` or `PAUSED` reach `PURGED` only through the consent and cancellation cascades (purge reasons `OPT_OUT`, `REVOKE`, or `CANCEL`). `purge_reason` is null until a purge occurs. A `ComplianceOfficer` may also set or clear a capture's legal hold by supplying `hold`.

While a capture is in flight, the attending physician appends speaker segments describing who spoke when. Each segment supplies a half-open interval within the capture — `start_offset_ms` (zero or greater) and `end_offset_ms` (strictly greater than the start), both in milliseconds — a `speaker_role` of `PHYSICIAN`, `PATIENT`, `CAREGIVER`, or `OTHER`, and a `base_confidence` between 0 and 1 with at most 4 decimals. A `speaker_role` outside the four declared values is rejected with `ERR_SPEAKER_ROLE_INVALID`. Intervals within one capture must be pairwise disjoint under half-open semantics: adjacency (one segment's start equal to another's end) is allowed, while even a 1-millisecond overlap is rejected with `ERR_SEGMENT_OVERLAP`. Appending a segment also requires the encounter to be `IN_PROGRESS` (`ERR_ENCOUNTER_NOT_IN_PROGRESS` otherwise).

Diarization is imperfect, so segments may be corrected. Reassigning a segment's speaker — by supplying `new_speaker_role` (subject to the same `ERR_SPEAKER_ROLE_INVALID` domain check) — increments its `reassignment_count` and bumps the segment's `version`. Each segment carries a computed `effective_confidence`, the diarization confidence after decay: the `base_confidence` is multiplied by 0.9 once for every reassignment that has been applied (that is, by 0.9 raised to the power of `reassignment_count`), and the result is rounded half-up to 4 decimal places. A freshly appended segment, with `reassignment_count` zero, therefore has `effective_confidence` equal to its `base_confidence`. Segment listings may be filtered by `speaker_role`.

### 3.4. Note Drafts, Discrete Fields, and Completeness

A note draft is generated against an encounter by the attending physician, who supplies the `template_id` of an active note template and the `expected_encounter_version` required by §2.7. Generation requires a `GRANTED` consent on the encounter (`ERR_CONSENT_NOT_ACTIVE` otherwise), an active template (`ERR_TEMPLATE_INACTIVE` otherwise), and at least one `TRANSCRIBED` capture on the encounter (`ERR_NO_TRANSCRIBED_AUDIO` otherwise). Generation supersedes any existing draft of the encounter in `DRAFT`, `EDITED`, `IN_REVIEW`, or `AMENDED` — the superseded draft moves to `VOID` — then seeds one `NoteField` row per entry in the template's `field_specs`: each field's `field_key` and `importance` and `required` flag are copied from the spec, its `field_value` starts null, its `source` starts `SYSTEM`, and `validated` starts false. The new draft's `author_physician_id` is set from the encounter's attending physician, its `status` begins at `DRAFT`, its `completeness_score` is computed immediately, and its `regeneration_count` and `amendment_count` start at zero. The encounter's `documentation_status` becomes `DRAFTING` and the encounter's `version` increments.

The `completeness_score` is an integer from 0 to 100 measuring how much of the required structure is filled. A field counts as missing when its `required` flag is true and its `field_value` is null or the empty string. Each missing field carries a penalty by importance: 25 points for `CRITICAL`, 10 for `MAJOR`, 5 for `MINOR`. Each penalty is multiplied by the template's `completeness_multiplier`; the products are summed and the sum is rounded half-up; that rounded total is subtracted from 100. If any missing field is `CRITICAL`, the result is capped at 49 no matter how small the arithmetic penalty. The score is finally clamped into the 0 to 100 range. Because the multiplier scales the penalties, the same set of missing fields yields different scores under different specialty templates — this is the specialty-weighted variant used for model tuning. The score is recomputed on draft creation, on every edit, on regenerate, and whenever the consent-invalidation cascade nulls audio-derived content.

Only the author may work a draft. Editing accepts `expected_note_draft_version` (per §2.7) plus `field_updates`, a map from `field_key` to new text. Every key in `field_updates` must be declared in the template's `field_specs`; an unknown key is rejected with `ERR_TEMPLATE_FIELD_MISMATCH`. Each edited field has its `field_value` set, its `source` flipped to `MANUAL`, and its `validated` flag set true, and the `completeness_score` is recomputed. Edits are permitted while the draft is `DRAFT`, `EDITED`, `IN_REVIEW`, or `AMENDED`; an edit on an `ATTESTED` or `VOID` draft is rejected with `ERR_NOTE_LOCKED`. Editing a draft in `IN_REVIEW` returns it to `EDITED`; editing in `DRAFT`, `EDITED`, or `AMENDED` leaves the status unchanged. Every edit increments the draft's `version`.

Submitting a draft for review — from `DRAFT`, `EDITED`, or `AMENDED` — moves it to `IN_REVIEW` and sets the encounter's `documentation_status` to `IN_REVIEW`. If the review reveals that the audio-derived content needs a fresh pull, the author may regenerate: every field whose `source` is not `MANUAL` is refilled from the transcript (its `field_value` becomes the literal prefix `drafted:` followed by its `field_key`, its `source` becomes `AUDIO`, and `validated` resets to false), while `MANUAL` fields are preserved untouched. Regeneration moves the draft from `IN_REVIEW` back to `DRAFT`, increments `regeneration_count`, recomputes the `completeness_score`, returns the encounter's `documentation_status` to `DRAFTING`, and increments the draft's `version`. Regenerate requires a `GRANTED` consent (`ERR_CONSENT_NOT_ACTIVE`) and at least one `TRANSCRIBED` capture (`ERR_NO_TRANSCRIBED_AUDIO`).

A draft that will never be used can be voided by its author or by a `ComplianceOfficer` from any of `DRAFT`, `EDITED`, `IN_REVIEW`, or `AMENDED`; `VOID` is terminal. When a draft is voided and no other non-terminal draft remains on the encounter, the encounter's `documentation_status` falls back to `NOT_STARTED`. Field listings for a draft may be filtered by `source` and by `validated`.

### 3.5. Attestation, Amendment, and the Legal Record

Attestation is the moment the note enters the legal record, and it is gated by five preconditions, evaluated under the ordering of §2.9: the caller must be the draft's author; the author's physician `status` must be `ACTIVE` — a `SUSPENDED` physician attesting is rejected with `ERR_PHYSICIAN_NOT_ACTIVE`; the encounter must hold a `GRANTED` consent (`ERR_CONSENT_NOT_ACTIVE`); no QA sample of the draft may be `ASSIGNED` — attesting under a QA hold is rejected with `ERR_QA_HOLD_ACTIVE`; and the draft's `completeness_score` must be at least 80 — otherwise `ERR_NOTE_INCOMPLETE`. The draft must be in `IN_REVIEW` to attest.

A successful attestation writes an `Attestation` row: its `note_draft_id` and `physician_id` identify the draft and its author, its `attestation_type` is `INITIAL` when the draft's `amendment_count` is zero and `AMENDMENT` for every re-attestation after an amend cycle, `attested_at` is stamped from the logical clock (and mirrored onto the draft's own `attested_at`), and `completeness_at_attestation` snapshots the draft's `completeness_score` at that instant. The draft moves from `IN_REVIEW` to `ATTESTED`, the encounter's `documentation_status` becomes `ATTESTED`, and the attestations list of a draft is append-only — an immutable legal trail.

Attestation has three further consequences. Every code suggestion of the draft still in `SUGGESTED` or `MODIFIED` expires (`SUGGESTED` → `EXPIRED`, `MODIFIED` → `EXPIRED`) and drops out of both billing variants, so `billing_provisional_cents` and `billing_final_cents` are recomputed. The physician's documentation metric for the calendar month containing `attested_at` is auto-created as a `PROVISIONAL` row if absent, and its `notes_attested` counter increments by 1. And if the snapshot `completeness_at_attestation` is strictly below the template's `low_confidence_threshold`, a QA sample is auto-queued in `QUEUED` status with `sampling_reason` `LOW_CONFIDENCE` and `created_by_user_id` recorded as the literal string `system`.

An attested note can still be corrected, but only through a formal amendment cycle. The author opens an amendment on an `ATTESTED` draft, which moves it to `AMENDED`, increments `amendment_count`, sets the encounter's `documentation_status` to `AMENDED`, and decrements `notes_attested` on the metric row of the attestation period — compensating the earlier increment, so the live counter always equals the number of the physician's currently `ATTESTED` drafts attested in that period. The amended draft re-enters the normal flow: it may be edited, submitted back to `IN_REVIEW`, and re-attested (producing an `Attestation` of type `AMENDMENT`). Separately, the consent cascade of §3.2 may set `phi_review_required` on an `ATTESTED` draft (default false) when consent is opted out or revoked after attestation; the legal record is preserved but flagged for compliance review.

### 3.6. Code Suggestions and Billing Totals

The platform suggests diagnoses, orders, and billing codes, but no suggestion enters the record without clinician confirmation. The author generates a batch of suggestions for a draft by supplying `suggestions`, each with a `code_type` of `DIAGNOSIS`, `ORDER`, or `BILLING`, a `code_value`, and a model `confidence` between 0 and 1 with at most 4 decimals. Every `code_value` must match the code format — an uppercase letter followed by 2 to 15 characters drawn from uppercase letters, digits, and dots — or the batch is rejected with `ERR_CODE_VALUE_MALFORMED`. Billing lines additionally carry `quantity` (default 1, at least 1), `unit_fee_cents` (required for `BILLING`, zero or greater), and `adjustment_pct` (default 1.0, greater than 0 and at most 5.0) — a fee multiplier such as 1.10. After the batch lands, the number of active suggestions on the draft — those in `SUGGESTED` or `MODIFIED` — must not exceed 8; a batch that would push past that ceiling is rejected with `ERR_CODE_LIMIT_EXCEEDED`.

Each suggestion's `line_total_cents` is computed per line, before any summation: the `unit_fee_cents` is multiplied by the `quantity` and by the `adjustment_pct`, and the product is rounded half-up to integer cents. For non-`BILLING` suggestions the line total is 0. Each suggestion also receives a 1-based `rank` within the draft, assigned across all non-terminal suggestions (`SUGGESTED`, `MODIFIED`, `CONFIRMED`) ordered by `confidence` descending, with ties broken by `created_at` ascending; ranks are dense from 1.

The draft carries two billing totals that answer different questions. `billing_final_cents` is the legal-record figure: the sum of the per-line totals over the draft's `BILLING` suggestions in `CONFIRMED` status only, unweighted; `EXPIRED` and `REJECTED` lines are excluded. `billing_provisional_cents` is the forward-looking figure: it covers `BILLING` suggestions in `SUGGESTED`, `MODIFIED`, and `CONFIRMED` status, with each line's already-rounded total multiplied by that suggestion's `confidence` and the result rounded half-up to cents before summing. Rounding order is pinned — each line is rounded first, then the confidence weighting is applied and rounded again, then the lines are summed; summing first and rounding once is the rejected alternative. Both totals recompute whenever a suggestion is created, confirmed, rejected, or modified, and at attestation.

The author confirms a suggestion to admit it into the record; confirmation records the caller in the audit field `confirmed_by`. Confirming or rejecting or modifying is allowed only while the owning draft is not `ATTESTED` (and not `VOID`); once the draft is `ATTESTED` or `VOID`, all three actions are rejected with `ERR_CODE_SUGGESTION_LOCKED`. Confirmation moves `SUGGESTED` → `CONFIRMED` or `MODIFIED` → `CONFIRMED`; rejection moves `SUGGESTED` → `REJECTED` or `MODIFIED` → `REJECTED`. Modification moves `SUGGESTED` → `MODIFIED`, replacing `code_value` with `new_code_value` (itself subject to the `ERR_CODE_VALUE_MALFORMED` format check) and optionally `quantity` with `new_quantity`, then recomputing `line_total_cents`. A fiscal cap guards confirmation of billing lines: the sum of `line_total_cents` over the draft's already-`CONFIRMED` billing suggestions plus the line being confirmed must not exceed 10000000 cents; a confirmation that would breach the cap is rejected with `ERR_BILLING_CAP_EXCEEDED`. Suggestion listings may be filtered by `status` and by `code_type`.

### 3.7. Quality Assurance: Sampling, Scoring, and Appeals

Quality assurance runs on samples of drafts. A sample enters the queue in `QUEUED` status by one of two routes, recorded in `sampling_reason`: automatically at attestation with reason `LOW_CONFIDENCE` (§3.5), or manually when a `ComplianceOfficer` or `QAAuditor` queues one with reason `MANUAL` — optionally naming an `auditor_id` up front. For manual samples the caller's `X-User-ID` is recorded in `created_by_user_id`; for auto-sampled ones it is the literal string `system`. The creator may never score the sample — segregation of duties — enforced as `ERR_QA_SELF_REVIEW_FORBIDDEN`.

Assignment moves `QUEUED` → `ASSIGNED` and is performed by a `QAAuditor` or `ComplianceOfficer` supplying the target `auditor_id`. The target auditor must be `ACTIVE`, and their `specialty_codes` must contain the `specialty_code` of the draft's template; a mismatch is rejected with `ERR_AUDITOR_SPECIALTY_MISMATCH`. Assignment stores the auditor on the sample's `auditor_id` (null until assigned). While any sample of a draft is `ASSIGNED`, attestation of that draft is held (§3.5).

The assigned auditor — and only that auditor — scores the sample (`ASSIGNED` → `SCORED`) by supplying three sub-scores: `accuracy_score`, `completeness_score`, and `timeliness_score`, each an integer from 0 to 100. The `composite_score` is the round-half-up integer of the weighted blend: accuracy contributes one half, completeness three tenths, and timeliness one fifth. The scorer's identity is recorded in `last_scorer_id`. Either a `QAAuditor` or a `ComplianceOfficer` may then close a `SCORED` sample, moving it to terminal `CLOSED`.

The author physician may appeal a `SCORED` (or `RESCORED`) sample, moving it to `APPEALED` and incrementing `appeal_count`, optionally with a `reason`. At most two appeals are permitted per sample: an appeal when `appeal_count` has reached 2 is rejected with `ERR_QA_MAX_APPEALS`. An appealed sample is rescored (`APPEALED` → `RESCORED`) by a different auditor: the rescorer must differ from `last_scorer_id` and must also differ from the sample's `created_by_user_id`, with violations rejected as `ERR_QA_SELF_REVIEW_FORBIDDEN`. The rescore uses appeal weights — accuracy now contributes seven tenths, completeness two tenths, timeliness one tenth — so identical sub-scores yield a different composite after appeal, again rounded half-up to an integer. The rescorer replaces `last_scorer_id`, and a `RESCORED` sample may be closed like a `SCORED` one, or appealed again subject to the two-appeal cap. Sample listings may be filtered by `status`.

### 3.8. Documentation Metrics and Retention Maintenance

Adoption is measured per physician per calendar month on `DocumentationMetric` rows. Each row's `period_start` is the first day of the calendar month (at 00:00:00Z) containing the measured activity, and `period_end` is the first day of the following month, an exclusive bound. A row's `status` begins `PROVISIONAL`; a row can be recomputed and, optionally, locked.

Recomputation — available to a `Physician`, a `ComplianceOfficer`, or a `PlatformAdmin`, supplying a `period_start` — creates the row for the month containing that date if absent, then recomputes three quantities from the physician's attestations in the period. The input spans are built from every `Attestation` of type `INITIAL` or `AMENDMENT` by the physician whose `attested_at` falls in the period: each span runs from its encounter's `started_at` to the attestation's `attested_at`. `provisional_minutes` is the wall-clock measure: each span's duration is converted to whole minutes (sub-minute remainders truncated per span, with partial minutes rounded up to the next whole minute before truncation of further precision) — that is, each span contributes its duration rounded up to the next minute — and the per-span minutes are summed. `final_minutes` is the effort-adjusted measure over the identical spans: from each span's minutes, the minutes of that encounter's `PAUSED` recording intervals are subtracted before summing. `after_hours_minutes` sums, over the same spans, the minutes of each span that fall between 18:00:00Z and midnight or between midnight and 07:00:00Z UTC, minus any paused minutes inside those windows. Until a recompute runs, all three counters read 0.

Passing `finalize` as true on the recompute locks the row: it moves from `PROVISIONAL` to terminal `FINAL`, and `finalized_at` is stamped. A `FINAL` row is immutable to recompute — recomputing it is rejected with `ERR_METRIC_PERIOD_CLOSED`. The `notes_attested` counter is maintained live by attestation and amendment (§3.5) rather than by recompute. Metric listings may be filtered by `period_start` and `status`; drafts may also be listed per physician (filterable by `status`) and per template, encounters per patient or physician (filterable by `encounter_status`), consents per patient or encounter (filterable by `status`), attestations per physician or per draft, captures per encounter (filterable by `status`), and samples per auditor (filterable by `status`).

Two `PlatformAdmin` maintenance capabilities complete the picture. The retention sweep walks `TRANSCRIBED` captures and expires any whose retention has elapsed: a capture is eligible when the current logical time is at or past its `ended_at` plus `retention_days_effective` whole days (the boundary instant exactly on the deadline is eligible) and its `legal_hold` is false; eligible captures move to `RETENTION_EXPIRED` with `purge_reason` `RETENTION`. The same sweep expires any consent still `GRANTED` on a `CANCELLED` encounter (`GRANTED` → `EXPIRED`, end_reason `EXPIRE`, with the usual capture-purge cascade for `RECORDING` or `PAUSED` captures under purge reason `CANCEL`). The sweep returns `expired_capture_ids` and `expired_consent_ids`. The logical-clock setter described in §2.5 is what lets operators and tests bring those deadlines forward.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource return `200 OK`. All endpoints are mounted under the `/ambient-clinical-documentation` prefix.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/ambient-clinical-documentation/patients` | Register a patient | PlatformAdmin |
| GET | `/ambient-clinical-documentation/patients/{id}` | Read one patient | PlatformAdmin, Physician, ComplianceOfficer, QAAuditor |
| GET | `/ambient-clinical-documentation/patients/{id}/encounters` | List encounters of a patient | PlatformAdmin, Physician, ComplianceOfficer |
| GET | `/ambient-clinical-documentation/patients/{id}/consents` | List consents of a patient | Patient, Physician, ComplianceOfficer, PlatformAdmin |
| POST | `/ambient-clinical-documentation/physicians` | Register a physician | PlatformAdmin |
| GET | `/ambient-clinical-documentation/physicians/{id}` | Read one physician | PlatformAdmin, Physician, ComplianceOfficer, QAAuditor |
| PATCH | `/ambient-clinical-documentation/physicians/{id}` | Update physician status (suspend/reactivate) | PlatformAdmin |
| GET | `/ambient-clinical-documentation/physicians/{id}/encounters` | List encounters of a physician | Physician, ComplianceOfficer, PlatformAdmin |
| GET | `/ambient-clinical-documentation/physicians/{id}/note-drafts` | List note drafts authored by a physician | Physician, QAAuditor, ComplianceOfficer, PlatformAdmin |
| GET | `/ambient-clinical-documentation/physicians/{id}/attestations` | List attestations by a physician | Physician, ComplianceOfficer, PlatformAdmin |
| GET | `/ambient-clinical-documentation/physicians/{id}/documentation-metrics` | List documentation metrics of a physician | Physician, ComplianceOfficer, PlatformAdmin |
| POST | `/ambient-clinical-documentation/physicians/{id}/documentation-metrics/recompute` | Create-if-absent and recompute the metric row for the calendar month containing period_start; finalize=true locks it | Physician, ComplianceOfficer, PlatformAdmin |
| POST | `/ambient-clinical-documentation/qa-auditors` | Register a QA auditor | PlatformAdmin |
| GET | `/ambient-clinical-documentation/qa-auditors/{id}` | Read one QA auditor | QAAuditor, ComplianceOfficer, PlatformAdmin |
| GET | `/ambient-clinical-documentation/qa-auditors/{id}/qa-samples` | List QA samples assigned to an auditor | QAAuditor, ComplianceOfficer, PlatformAdmin |
| POST | `/ambient-clinical-documentation/note-templates` | Create a note template | PlatformAdmin |
| GET | `/ambient-clinical-documentation/note-templates/{id}` | Read one note template | PlatformAdmin, Physician, ComplianceOfficer, QAAuditor, Patient |
| PATCH | `/ambient-clinical-documentation/note-templates/{id}` | Activate/deactivate a template | PlatformAdmin |
| GET | `/ambient-clinical-documentation/note-templates/{id}/note-drafts` | List drafts created from a template | Physician, QAAuditor, ComplianceOfficer, PlatformAdmin |
| POST | `/ambient-clinical-documentation/encounters` | Create an encounter (creating physician must be the attending physician) | Physician |
| GET | `/ambient-clinical-documentation/encounters/{id}` | Read one encounter | Physician, Patient, QAAuditor, ComplianceOfficer, PlatformAdmin |
| POST | `/ambient-clinical-documentation/encounters/{id}/start` | Start the encounter (SCHEDULED to IN_PROGRESS) | Physician |
| POST | `/ambient-clinical-documentation/encounters/{id}/complete` | Complete the encounter; allowed even before documentation is attested | Physician |
| POST | `/ambient-clinical-documentation/encounters/{id}/cancel` | Cancel the encounter; cascades consent EXPIRED and purges in-flight captures | Physician, ComplianceOfficer |
| GET | `/ambient-clinical-documentation/encounters/{id}/consents` | List consents of an encounter | Patient, Physician, ComplianceOfficer, PlatformAdmin |
| POST | `/ambient-clinical-documentation/encounters/{id}/consents` | Grant ambient consent for the encounter | Patient, ComplianceOfficer |
| POST | `/ambient-clinical-documentation/consents/{id}/opt-out` | Patient opt-out; triggers the purge/invalidate/demote cascade | Patient |
| POST | `/ambient-clinical-documentation/consents/{id}/revoke` | Compliance revocation; same cascade as opt-out | ComplianceOfficer |
| GET | `/ambient-clinical-documentation/encounters/{id}/audio-captures` | List audio captures of an encounter | Physician, Patient, ComplianceOfficer, QAAuditor, PlatformAdmin |
| POST | `/ambient-clinical-documentation/encounters/{id}/audio-captures` | Start an ambient audio capture | Physician |
| GET | `/ambient-clinical-documentation/audio-captures/{id}` | Read one audio capture | Physician, ComplianceOfficer, QAAuditor, PlatformAdmin |
| POST | `/ambient-clinical-documentation/audio-captures/{id}/pause` | Pause recording | Physician |
| POST | `/ambient-clinical-documentation/audio-captures/{id}/resume` | Resume recording | Physician |
| POST | `/ambient-clinical-documentation/audio-captures/{id}/stop` | Stop recording; finalizes recorded_seconds excluding paused time | Physician |
| POST | `/ambient-clinical-documentation/audio-captures/{id}/purge` | Compliance purge of a CAPTURED or TRANSCRIBED capture | ComplianceOfficer |
| POST | `/ambient-clinical-documentation/audio-captures/{id}/legal-hold` | Set or clear a legal hold | ComplianceOfficer |
| POST | `/ambient-clinical-documentation/audio-captures/{id}/segments` | Append a speaker segment | Physician |
| GET | `/ambient-clinical-documentation/audio-captures/{id}/segments` | List speaker segments of a capture | Physician, QAAuditor, ComplianceOfficer, PlatformAdmin |
| POST | `/ambient-clinical-documentation/segments/{id}/reassign-speaker` | Reassign a segment's speaker role | Physician |
| GET | `/ambient-clinical-documentation/encounters/{id}/note-drafts` | List note drafts of an encounter | Physician, Patient, QAAuditor, ComplianceOfficer, PlatformAdmin |
| POST | `/ambient-clinical-documentation/encounters/{id}/note-drafts` | Generate a note draft from a template; supersedes any existing non-terminal draft | Physician |
| GET | `/ambient-clinical-documentation/note-drafts/{id}` | Read one note draft (includes computed completeness and billing totals) | Physician, QAAuditor, ComplianceOfficer, PlatformAdmin |
| PATCH | `/ambient-clinical-documentation/note-drafts/{id}` | Edit draft fields (OCC on the draft) | Physician |
| POST | `/ambient-clinical-documentation/note-drafts/{id}/submit-review` | Submit draft for review | Physician |
| POST | `/ambient-clinical-documentation/note-drafts/{id}/regenerate` | Pull fresh content from the transcript | Physician |
| POST | `/ambient-clinical-documentation/note-drafts/{id}/attest` | Physician attestation; the note enters the legal record | Physician |
| POST | `/ambient-clinical-documentation/note-drafts/{id}/amend` | Open an amendment cycle on an attested note | Physician |
| POST | `/ambient-clinical-documentation/note-drafts/{id}/void` | Void a non-terminal draft | Physician, ComplianceOfficer |
| GET | `/ambient-clinical-documentation/note-drafts/{id}/fields` | List the discrete fields of a draft | Physician, QAAuditor, ComplianceOfficer, PlatformAdmin |
| GET | `/ambient-clinical-documentation/note-drafts/{id}/attestations` | List attestations of a draft (append-only legal record) | Physician, QAAuditor, ComplianceOfficer, PlatformAdmin |
| POST | `/ambient-clinical-documentation/note-drafts/{id}/code-suggestions` | Generate a batch of code suggestions | Physician |
| GET | `/ambient-clinical-documentation/note-drafts/{id}/code-suggestions` | List code suggestions of a draft | Physician, QAAuditor, ComplianceOfficer, PlatformAdmin |
| POST | `/ambient-clinical-documentation/code-suggestions/{id}/confirm` | Clinician confirmation of a suggestion | Physician |
| POST | `/ambient-clinical-documentation/code-suggestions/{id}/reject` | Reject a suggestion | Physician |
| POST | `/ambient-clinical-documentation/code-suggestions/{id}/modify` | Modify a suggested code before confirming | Physician |
| POST | `/ambient-clinical-documentation/note-drafts/{id}/qa-samples` | Manually queue a QA sample | ComplianceOfficer, QAAuditor |
| GET | `/ambient-clinical-documentation/note-drafts/{id}/qa-samples` | List QA samples of a draft | Physician, QAAuditor, ComplianceOfficer, PlatformAdmin |
| POST | `/ambient-clinical-documentation/qa-samples/{id}/assign` | Assign a queued sample to a specialty-matched active auditor | QAAuditor, ComplianceOfficer |
| POST | `/ambient-clinical-documentation/qa-samples/{id}/score` | Assigned auditor scores the sample | QAAuditor |
| POST | `/ambient-clinical-documentation/qa-samples/{id}/appeal` | Author physician appeals a score | Physician |
| POST | `/ambient-clinical-documentation/qa-samples/{id}/rescore` | A different auditor rescores after appeal | QAAuditor |
| POST | `/ambient-clinical-documentation/qa-samples/{id}/close` | Close a scored or rescored sample | QAAuditor, ComplianceOfficer |
| POST | `/ambient-clinical-documentation/_clock/set_current_utc` | Test-driving: set the logical clock | PlatformAdmin |
| POST | `/ambient-clinical-documentation/_audio/simulate-transcription` | Test-driving: advance a CAPTURED capture to TRANSCRIBED | PlatformAdmin |
| POST | `/ambient-clinical-documentation/_maintenance/run-retention-sweep` | Test-driving: expire past-retention captures and stale consents | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_SPEAKER_ROLE_INVALID` | 400 |
| `ERR_TEMPLATE_FIELD_MISMATCH` | 422 |
| `ERR_CODE_VALUE_MALFORMED` | 422 |
| `ERR_CONSENT_REQUIRED` | 422 |
| `ERR_CONSENT_NOT_ACTIVE` | 422 |
| `ERR_LEGAL_HOLD_ACTIVE` | 422 |
| `ERR_PHYSICIAN_NOT_ACTIVE` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ENCOUNTER_NOT_IN_PROGRESS` | 409 |
| `ERR_NOTE_LOCKED` | 409 |
| `ERR_CODE_SUGGESTION_LOCKED` | 409 |
| `ERR_QA_HOLD_ACTIVE` | 409 |
| `ERR_METRIC_PERIOD_CLOSED` | 409 |
| `ERR_SIGNAGE_NOT_POSTED` | 422 |
| `ERR_DUPLICATE_CONSENT` | 409 |
| `ERR_CAPTURE_ACTIVE_EXISTS` | 409 |
| `ERR_TEMPLATE_INACTIVE` | 422 |
| `ERR_NO_TRANSCRIBED_AUDIO` | 422 |
| `ERR_NOTE_INCOMPLETE` | 422 |
| `ERR_CODE_LIMIT_EXCEEDED` | 422 |
| `ERR_QA_MAX_APPEALS` | 422 |
| `ERR_QA_SELF_REVIEW_FORBIDDEN` | 403 |
| `ERR_AUDITOR_SPECIALTY_MISMATCH` | 422 |
| `ERR_CAPTURE_GAP_VIOLATION` | 409 |
| `ERR_SEGMENT_OVERLAP` | 409 |
| `ERR_BILLING_CAP_EXCEEDED` | 422 |
| `ERR_STALE_VERSION` | 412 |
