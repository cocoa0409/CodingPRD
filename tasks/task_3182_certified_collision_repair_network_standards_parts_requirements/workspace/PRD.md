# Certified Collision Repair Network API — Product Requirements Document

## 1. Introduction

This document specifies the Certified Collision Repair Network API, the system of record for an OEM-administered certified collision repair program modeled on American Honda's network standards. The network exists to answer a deceptively simple consumer question — "which shops near me are actually qualified to repair my vehicle correctly?" — and to keep that answer honest over time. A shop earns certification by satisfying a published catalogue of equipment, training, tooling, and structural-repair requirements; it keeps certification by surviving an annual on-site audit, remediating findings through corrective actions under auditor verification, maintaining technician training currency as courses expire, and repairing vehicles to procedure with documented parts provenance.

Three pressures shaped the design. First, certification posture is not a static badge: it is derived from live evidence, and a single lapsed attestation or overdue corrective action must cascade through the shop's locator visibility, its insurer steering eligibility, and even in-flight consumer referrals. Second, the repair floor is safety-critical: pre- and post-repair diagnostic scanning, ADAS sensor calibration, and original-equipment parts usage are enforced as chronology and classification rules rather than as policy prose. Third, several parties with conflicting interests — the OEM's network administrators, independent field auditors, shop managers, dealers, and insurers — share the system, so verification duties are segregated (an auditor cannot verify corrective evidence for a finding they themselves issued, and a shop manager who files a warranty claim may never review it).

The API is mounted under the `/network` path prefix. It covers shop onboarding and certification cycles, requirement publishing and revision with attestation version-pinning, audit scheduling and corrective-action loops, technician roster and training currency, repair order execution from estimate through warranty, insurer DRP relationships, consumer referrals with a ranked locator, and a logical-clock test-driving surface that drives every time-gated sweep (course expiry, referral TTL, corrective-action deadlines, cycle window expiry, and warranty transitions).

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational role. A request missing either header, or presenting a role the system does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The single exception is the public consumer locator search, which is anonymous and requires no headers. A request whose role is authenticated but not permitted for the endpoint per the authorization column in §4 is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes six roles, spelled exactly as follows:

- `Anonymous` — the unauthenticated consumer hitting the public locator search. `X-User-ID` is an opaque identifier not tied to any persisted entity; the locator endpoint does not require headers at all.
- `NetworkAdmin` — the OEM network administrator: registers shops, opens certification cycles, manages requirement and training-course catalogues, administers insurer relations, reviews and resolves warranty claims, runs the logical clock and sweep endpoints, and may originate referrals. `X-User-ID` is an opaque operator identifier not tied to any persisted entity; it is recorded for audit-trail purposes only.
- `NetworkAuditor` — the field auditor: schedules, begins, cancels, and issues findings on audits; verifies corrective actions; closes certification cycles. `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it as `auditor_user_id` on a scheduled Audit and as `issued_by_user_id` / `verified_by_user_id` on corrective actions, where it is compared for segregation-of-duties purposes, but it is never compared to any entity's `id` for ownership.
- `ShopManager` — manager of a certified shop: attests to requirements, hires technicians, records course completions, runs the repair-order lifecycle, files warranty claims, submits corrective evidence, and accepts or declines referrals. When `X-User-Role` is `ShopManager`, `X-User-ID` is the `id` of the acting `Shop`; ownership checks on any resource that references a `Shop` compare the resource's shop foreign-key field to `X-User-ID` (for example, accepting a referral requires the acting shop's id to equal the referral's routed shop).
- `DealerRep` — dealer representative originating referrals. `X-User-ID` is an opaque identifier not tied to any persisted entity.
- `InsurerRep` — insurer representative originating referrals and reading DRP repair data. `X-User-ID` is an opaque identifier not tied to any persisted entity.

Two identity-derived segregation rules follow from the above and are enforced wherever they arise in §3: a corrective action may only be verified by an auditor whose `X-User-ID` differs from the `issued_by_user_id` recorded on that action, and a warranty claim may only be reviewed or resolved by a user whose `X-User-ID` differs from the filer's; in both cases a violation is rejected with `ERR_SELF_VERIFICATION` (HTTP 422).

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

List endpoints accept two query parameters. `limit` controls the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` controls how many items are skipped; it defaults to 0. Unless otherwise specified, list endpoints return resources sorted by `created_at` ascending. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties

Every primary resource in the network carries a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. `created_at` is an ISO 8601 UTC timestamp with three fractional digits recording first creation. `updated_at` is an ISO 8601 UTC timestamp refreshed on any mutation of the resource. `version` is an integer starting at creation and incremented on every mutation — including mutations driven by cascades, computed-field recomputation, and clock-sweep transitions. All entities in this domain (Shop, Requirement, CertificationCycle, ShopAttestation, Audit, CorrectiveAction, Technician, TrainingCourse, CourseCompletion, RepairOrder, ProcedureStep, PartLineItem, WarrantyClaim, InsurerRelation, Referral) carry the full common set. Wherever §3 describes a side effect that recomputes a derived field on an entity (for example `live_compliance_score` on a Shop after an attestation lapses), that recomputation is a mutation of the owning entity: it refreshes `updated_at` and increments `version`.

### 2.5. Logical Clock and Time-Gated Sweeps

All temporal rules in this system — expiry deadlines, warranty windows, referral TTLs, audit windows, corrective-action due dates, certification cycle windows — are evaluated against a server-maintained **logical clock**, never against wall-clock time. At startup the logical clock reads 2026-09-01T00:00:00Z. A `NetworkAdmin` may advance it by supplying a `to_iso8601` instant; advancing the clock triggers a full sweep pass that applies every time-gated transition described in §3 (course-completion expiries, referral TTL expiry, corrective-action overdue handling, certification-cycle window expiry, and repair-order warranty transitions). A separate admin-only capability re-runs the same sweep set at the current logical clock without advancing it. The logical clock must never fall back to wall-clock time.

### 2.6. Certification Posture as Derived State

A Shop's `certification_status` is posture-driven: it is derived from the shop's certification-cycle and audit state, and the only legal writers are the transitions enumerated in §3 — no endpoint accepts a free-form posture value. The status space is exactly `APPLICANT`, `CERTIFIED`, `PROBATION`, `SUSPENDED`, `EXPIRED`, and `DECERTIFIED`, with `APPLICANT` as the initial state at registration and `DECERTIFIED` as the sole terminal state. Posture changes cascade: entering `SUSPENDED` or `DECERTIFIED` flips `locator_hidden` to true, disables steering on insurer relations, and (for suspension and decertification) force-declines every `ROUTED` referral pointing at the shop, decrementing `pending_referral_count` for each — a cascade three levels deep from Shop through Referral back to the Shop's counter.

### 2.7. The Compliance Score: Live and Snapshot Variants

Every Shop carries `live_compliance_score`, a weighted score over current attestation state that is recomputed on every attestation status change, every technician status change, and every requirement publish-revision or retirement cascade. The same formula, evaluated exactly once at cycle close and never recomputed afterwards, is frozen onto the cycle as `audit_snapshot_score`. The two variants deliberately diverge after any post-close mutation: the snapshot is the historical record of what the auditor saw, while the live score tracks the shop's present posture. The full weighted formula — category weights, the training currency factor, and rounding — is specified in §3.2 alongside the attestation mechanics that drive it.

### 2.8. Money, Ratios, and Rounding

Monetary amounts are integer cents (for example `estimate_total_cents`, `unit_cost_cents`, `claim_amount_cents`, `warranty_reserve_cents`) so that no floating-point error can enter the ledger. Two precision regimes apply elsewhere. Scores expressed as percentages — the compliance score and technician `curriculum_progress_pct` — are rounded to 2 decimal places using round-half-up. Original-equipment parts ratios (`oe_parts_ratio_by_cost` and `oe_parts_ratio_by_count`) are rounded to 4 decimal places, round-half-up. The warranty reserve accrual is computed in whole cents with a single round-half-up step at a pinned point in its evaluation order, specified in §3.7. The referral ranking score carries 6 decimal places of intermediate precision, round-half-up, before comparison.

### 2.9. Optimistic Concurrency Control

Three write endpoints are guarded by optimistic concurrency against the parent entity's `version`, and only these three; no other endpoint takes a version field:

- Creating a repair order under a shop requires a non-optional `expected_shop_version` input carrying the shop's `version` as the client last observed it. If the shop's current `version` has advanced since — because another writer mutated the shop through a posture cascade, a referral counter change, or a reserve accrual — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from acting on a stale view of `certification_status`.
- Closing a certification cycle requires a non-optional `expected_cycle_version`. If the cycle's current `version` has advanced since the client last read it — for example because finding issuance or corrective-action verification cascades bumped the cycle — the close is rejected with `ERR_STALE_VERSION` (HTTP 412) rather than applied over unknown state.
- Creating an attestation under a shop requires a non-optional `expected_shop_version`. A superseding attestation for the same requirement row may legitimately have been written by another client since the client last read the shop; if the versions diverge, the create is rejected with `ERR_STALE_VERSION` (HTTP 412).

### 2.10. Nested Resource Resolution and Validation Order

Endpoints whose paths contain multiple resource identifiers validate existence sequentially, left to right: the parent segment is resolved first, and a nested child must actually belong to the parent named in the path. A miss anywhere in the chain, or an unresolvable foreign key in the request body (`shop_id`, `cycle_id`, `requirement_id`, `technician_id`, `course_id`, `repair_order_id`, `referral_id`, `insurer_relation_id`, `audit_id`, `attestation_id`), is rejected with `ERR_NOT_FOUND` (HTTP 404). Validation across the board runs in a fixed priority order: authentication and authorization first (`ERR_UNAUTHENTICATED`, then `ERR_UNAUTHORIZED`), then existence (`ERR_NOT_FOUND`), then legal source state (`ERR_INVALID_STATE`, HTTP 409), then optimistic concurrency (`ERR_STALE_VERSION`), and only then the domain-specific business rules of §3 — safety classification, scanning and calibration chronology, structural capability, segregation of duties, documentation, temporal windows, fiscal floors — with plain malformed-payload and enum/format violations (`ERR_INVALID_REQUEST`, HTTP 400) checked last among business rules. Where multiple business checks could reject the same request, the check whose category is safety-related surfaces before referential checks, which surface before constraint and temporal checks, so that (for example) a missing mandatory pre-scan is reported rather than masked by a later window check.

### 2.11. Warranty Reserve Ledger

Each Shop carries `warranty_reserve_cents`, an aggregated accrual ledger. Accrual is added when a repair order enters its warranty-active period, decremented (capped at the order's remaining accrual and never below zero overall) when a warranty claim is accepted against that order, and the unreleased remainder for an order is subtracted back out when the order closes — a compensating invariant meaning a repair with no accepted claims nets zero drift on the reserve. The per-order accrual formula is tiered and specified in §3.7.

## 3. Business Logic & Workflows

### 3.1. Shop Onboarding and Certification Cycles

A `NetworkAdmin` registers a shop by supplying its `legal_name`, the two-letter uppercase US `state_code` where it operates, the 5-digit `zip_code` used by locator radius queries, geocoded `latitude` and `longitude`, and optionally `structural_capability` (defaulting to false) declaring whether the shop performs frame and unibody work. The shop enters the network in `APPLICANT` posture, with `lifetime_repair_count`, `pending_referral_count`, and `warranty_reserve_cents` all zero, `locator_hidden` false at rest (an applicant is simply not yet eligible for certification-gated surfaces), and `live_compliance_score` at 0.0.

Certification is organized into annual cycles. A `NetworkAdmin` opens the next cycle for a shop by supplying `window_start` and `window_end`. The window is a closed interval that must span exactly one year: `window_end` must equal `window_start` plus 365 days minus 1 second, and a new cycle's `window_start` must equal the previous cycle's `window_end` plus 1 second — zero-gap adjacency with no overlap and no gap. A window that violates either rule is rejected with `ERR_CYCLE_WINDOW` (HTTP 422). Each cycle receives a server-assigned 1-based `cycle_index` reflecting its creation order for the shop, begins in `OPEN` status, and progresses through `AUDIT_SCHEDULED`, `UNDER_AUDIT`, and `CORRECTIVE_ACTION` toward one of two terminals, `CLOSED_PASS` or `CLOSED_FAIL`. The `audit_snapshot_score` stays null until the cycle's audit closes.

Posture transitions out of the cycle machinery are the shop's only path into and out of certification. When a `NetworkAuditor` closes the shop's first cycle with result PASS — requiring the cycle to be in `UNDER_AUDIT` or `CORRECTIVE_ACTION`, the cycle's `cycle_index` to be 1, and the audit's grade to be `A` or `B` — the shop moves `APPLICANT → CERTIFIED`, `locator_hidden` is recomputed to false, and every insurer relation of the shop has `steering_enabled` set to true where the relation is `ACTIVE`. A cycle close with grade `C` instead moves `CERTIFIED → PROBATION`; probation keeps the shop listed (`locator_hidden` stays false), keeps steering enabled on `ACTIVE` relations, and leaves every `ROUTED` referral to the shop valid. From `PROBATION`, closing the current cycle with result PASS and grade `A` or `B` restores `CERTIFIED` — but only when no `OPEN` or `SUBMITTED` corrective action with a past-due `due_at` exists for any audit of the shop — and recomputes `locator_hidden` to false.

A grade of `F` at cycle close, or a clock sweep that finds any `CRITICAL` corrective action of the shop's audits past its `due_at` still `OPEN`, drives `CERTIFIED → SUSPENDED`. The suspension cascade flips `locator_hidden` to true, sets `steering_enabled` false on every insurer relation of the shop, and force-transitions every `ROUTED` referral pointing at the shop to `DECLINED`, decrementing `pending_referral_count` for each. A second consecutive cycle close at grade `C`, or an overdue `CRITICAL` corrective action beyond its `due_at` found by the sweep, drives `PROBATION → SUSPENDED` with the identical cascade. From `SUSPENDED`, closing the current cycle with result PASS and grade `A` or `B` — permitted only when every corrective action for audits of the shop's current cycle has reached `VERIFIED` — restores `CERTIFIED`, clears `locator_hidden`, and re-enables steering on every `ACTIVE` insurer relation, compensating the earlier cascade.

Certification can also lapse passively. When the sweep finds the logical clock past the current cycle's `window_end` with no audit of that cycle in `SCHEDULED`, `IN_PROGRESS`, `FINDINGS_ISSUED`, or `VERIFICATION`, the shop moves `CERTIFIED → EXPIRED`: `locator_hidden` becomes true and steering is disabled on all relations. Expiry is recoverable — opening a new cycle after expiry and closing it with result PASS moves `EXPIRED → CERTIFIED`, recomputing `locator_hidden` to false and recomputing steering for `ACTIVE` relations.

Decertification is the terminal act. A `NetworkAdmin` may decertify a shop only while it has remained `SUSPENDED` for at least 90 days by the logical clock and no repair order of the shop sits in `ESTIMATE`, `APPROVED`, `IN_REPAIR`, `QC`, `REWORK`, or `CALIBRATION`; otherwise the request is rejected with `ERR_DECERTIFY_BLOCKED` (HTTP 422). A successful decertification moves the shop to `DECERTIFIED`, terminates every `ACTIVE` insurer relation, force-declines every `ROUTED` referral, and pins `locator_hidden` to true permanently. Note that `locator_hidden` is also forced true, independently of posture, whenever an active audit of the shop is in `VERIFICATION` with a `CRITICAL` finding outstanding — the shop drops out of the consumer locator until the critical finding is resolved.

### 3.2. Requirements, Revisions, and Attestations

The certification standards catalogue is a set of versioned Requirement rows. A `NetworkAdmin` authors a requirement in `DRAFT` with a stable `requirement_code` (for example EQ-WELD-01), a `category` of `EQUIPMENT`, `TRAINING`, `TOOLING`, or `STRUCTURAL`, a human-readable `description`, the `severity_if_failed` (`MINOR`, `MAJOR`, or `CRITICAL`) an audit finding against it would carry, and the `effective_from` instant from which the published revision applies to audits. Publishing a draft requires `effective_from` to be present and no earlier than the logical clock; a past effective date is rejected with `ERR_EFFECTIVE_IN_PAST` (HTTP 422). The `requirement_code` together with `requirement_version` is unique; the first revision of a code carries `requirement_version` 1 and a null `supersedes_requirement_id`.

Standards evolve by revision, never by mutation. Publishing a new revision of a `PUBLISHED` requirement creates an entirely new Requirement row with the same `requirement_code`, `requirement_version` incremented by one, and `supersedes_requirement_id` pointing at the row being replaced; the old row moves to `SUPERSEDED`. The new revision carries its own `description`, `severity_if_failed`, and `effective_from`, and — exactly as at initial publish — an `effective_from` earlier than the logical clock is rejected with `ERR_EFFECTIVE_IN_PAST` (HTTP 422). The revision has teeth: every ShopAttestation pinned to the superseded row flips from `ACTIVE` to `LAPSED` with `lapse_reason` `REQUIREMENT_REVISED`, each affected shop's `live_compliance_score` is recomputed, and any technician whose currency depended on a `TRAINING`-category attestation to the superseded row may flip to `LAPSED` through the currency recompute of §3.4. Retiring a requirement is allowed from `DRAFT` unconditionally, or from `PUBLISHED` provided no `IN_PROGRESS` audit references it; retiring a published row likewise lapses its pinned attestations with `lapse_reason` `REQUIREMENT_RETIRED`. A retired row is terminal. The requirements list endpoint supports a `supersedes_requirement_id` filter so clients can walk a code's revision chain.

Shops prove compliance through attestations. A `ShopManager` attests satisfaction of a specific published revision — attestations are version-pinned to the exact Requirement row, not to the code — by submitting the `requirement_id` and an `evidence_uri` (photo, invoice, or certificate). The server stamps `attested_at`. Attesting is permitted while the shop's `certification_status` is `CERTIFIED`, `PROBATION`, or `APPLICANT`; the create is OCC-guarded by `expected_shop_version` per §2.9. When an attestation is created for a requirement row that already has an `ACTIVE` attestation at that shop, the older attestation transitions to `SUPERSEDED` (the attestation's terminal state) and the shop's `live_compliance_score` is recomputed. An attestation in `ACTIVE` status can also lapse — moving to `LAPSED` — when its owning requirement is superseded or retired, or when an audit finding is opened against it; each lapse recomputes the owning shop's `live_compliance_score` and recomputes `locator_hidden`, since a lapsed `CRITICAL`-severity requirement while an audit sits in `VERIFICATION` forces the shop out of the locator.

The `live_compliance_score` itself is a weighted average over the four categories, with weights 30 for `EQUIPMENT`, 30 for `STRUCTURAL`, 15 for `TOOLING`, and 25 for `TRAINING`. For each category, the denominator is the count of Requirement rows in `PUBLISHED` status in that category whose `effective_from` is at or before the logical clock, and the numerator is the count of distinct such requirement rows for which the shop holds an `ACTIVE` attestation (attestations in `LAPSED`, `UNDER_CORRECTION`, or `SUPERSEDED` never count). A category with zero published effective rows scores 100.0; otherwise the category score is 100.0 times the satisfied count divided by the total count. The `TRAINING` category carries an additional currency factor: for every technician role represented among the shop's technicians, the shop must have at least one technician in `CURRENT` status for that role, and if any represented role has zero current technicians, the training category score is halved. The overall score is the sum of each category's weight times its category score, divided by 100.0, rounded to 2 decimal places round-half-up. The snapshot variant frozen as `audit_snapshot_score` at cycle close uses the identical formula evaluated as of the close instant and is never recomputed, even if attestations later lapse.

### 3.3. Audits, Findings, and the Corrective-Action Loop

Audits are scheduled against a cycle, not against a shop directly. A `NetworkAuditor` schedules an audit by supplying `scheduled_start` and `scheduled_end`, which define a half-open on-site window — inclusive at the start, exclusive at the end. Scheduling is refused in two cases. First, the cycle must not already have another audit for the same shop in `SCHEDULED`, `IN_PROGRESS`, `FINDINGS_ISSUED`, or `VERIFICATION` — the cycle moves from `OPEN` to `AUDIT_SCHEDULED` on success. Second, the new window must not intersect any other audit of the same shop that is in `SCHEDULED` or `IN_PROGRESS`: an intersection exists whenever the new start falls before the existing window's end and the existing window's start falls before the new end. Touching windows, where the new start equals an existing window's end, do not conflict, and audits in `CANCELLED`, `PASSED`, or `FAILED` never conflict. An overlap is rejected with `ERR_AUDIT_OVERLAP` (HTTP 409). The scheduling auditor's `X-User-ID` is recorded as `auditor_user_id` for audit-trail purposes.

When the on-site day arrives, the auditor begins the audit; beginning is legal only while the logical clock sits within the scheduled half-open window, and only when the acting auditor's `X-User-ID` equals the recorded `auditor_user_id`. A begin outside the window is rejected with `ERR_AUDIT_WINDOW_MISSED` (HTTP 422). Beginning moves the audit `SCHEDULED → IN_PROGRESS` and the cycle `AUDIT_SCHEDULED → UNDER_AUDIT`. A scheduled audit that will not happen can be cancelled, moving the audit to `CANCELLED` and returning the cycle from `AUDIT_SCHEDULED` to `OPEN`.

The pivotal act is issuing findings. The auditor submits a `findings` list against an `IN_PROGRESS` audit. With zero findings, the audit passes outright: the audit's `grade` is set to `A` (the grade produced by zero effective points), the audit moves `IN_PROGRESS → PASSED`, and the cycle moves `UNDER_AUDIT → CLOSED_PASS` with `audit_snapshot_score` frozen. With one or more findings, each finding references the ShopAttestation found deficient; every referenced attestation flips to `LAPSED` with `lapse_reason` `AUDIT_FINDING`, one CorrectiveAction is created per finding, the audit's `severity_points` are recomputed, the audit moves `IN_PROGRESS → FINDINGS_ISSUED`, and the cycle moves `UNDER_AUDIT → CORRECTIVE_ACTION`.

Each corrective action opens in `OPEN` status against both its audit (`audit_id`) and the deficient attestation (`attestation_id`, a cross-aggregate reference), recording the `finding_severity` and the issuing auditor's `issued_by_user_id`. The server sets the deadline: a `MAJOR` finding is due 30 days after issuance, a `CRITICAL` finding 10 days, and a `MINOR` finding 60 days; this deadline is the action's `due_at`. The opening of a corrective action also moves the referenced attestation from `LAPSED` to `UNDER_CORRECTION`.

Remediation is a two-party loop by design. The `ShopManager` of the audited shop submits corrected `evidence_uri` against each `OPEN` action; submission is only legal at or before `due_at` (later attempts are rejected with `ERR_CORRECTIVE_OVERDUE`, HTTP 422), moves the action to `SUBMITTED`, and — when the last `OPEN` action of the audit is submitted so that every action is `SUBMITTED` or `VERIFIED` — moves the audit `FINDINGS_ISSUED → VERIFICATION`. A `NetworkAuditor` then verifies each submission with a `verdict`. The verifying auditor must be a different person than the issuer: a verifier whose `X-User-ID` equals the action's `issued_by_user_id` is rejected with `ERR_SELF_VERIFICATION`. A verdict of `VERIFIED` moves the action `SUBMITTED → VERIFIED`, returns the referenced attestation from `UNDER_CORRECTION` to `ACTIVE` as a compensation, and recomputes the shop's `live_compliance_score` so the score recovers toward its pre-lapse value; when that verification completes the last non-verified action of the audit, the audit moves `VERIFICATION → PASSED`, its `grade` is computed, and the cycle becomes eligible for `CLOSED_PASS`. A verdict of `REJECTED` moves the action `SUBMITTED → REJECTED`, spawns a brand-new corrective action in `OPEN` status with a freshly calculated `due_at` (the revision loop), bumps the audit's `round_number` by one, and returns the audit `VERIFICATION → FINDINGS_ISSUED`. The audit's `round_number` is 1 at creation and increments on every such rejection round.

Grading is points-based. The audit's `severity_points` are the sum over all of its corrective actions — `REJECTED` actions and their `OPEN` replacements each count once — of severity weights: 1 per `MINOR`, 5 per `MAJOR`, 25 per `CRITICAL`. On top of that sits an escalation penalty of 3 points per WarrantyClaim against the shop's repairs that is in `ESCALATED` status at the evaluation instant; the two together form the effective points. The grade boundaries are inclusive exactly as stated: 0 effective points is grade `A`; from 1 up to and including 5 is `B`; from 6 up to and including 24 is `C`; 25 or more is `F`. This is why a shop's escalated warranty claims matter beyond the claim itself — each open escalation worsens the next audit's grade.

Closing the cycle is the `NetworkAuditor`'s final act and is OCC-guarded by `expected_cycle_version` per §2.9; the request carries the `result` (PASS or FAIL). Closing with PASS from `CORRECTIVE_ACTION` requires every corrective action of the cycle's audit to be `VERIFIED`; it computes the audit's `grade`, freezes `audit_snapshot_score`, and applies the shop posture transition dictated by the grade (`CERTIFIED` for `A` or `B`, `PROBATION` for `C`, `SUSPENDED` for `F`) per §3.1. Closing with FAIL, or a clock sweep that finds any corrective action past `due_at` still `OPEN` or `SUBMITTED` while the audit is in `VERIFICATION`, moves the audit to `FAILED` and the cycle to `CLOSED_FAIL`, with the shop posture following the suspension rules of §3.1. Note the asymmetry: an audit that passed with zero findings closes its cycle immediately at finding-issuance time, whereas an audit that issued findings only closes its cycle when the auditor explicitly closes it after verification.

### 3.4. Technicians and Training Currency

A `ShopManager` hires a technician into their shop with a `full_name` and a `tech_role` of `STRUCTURAL`, `NON_STRUCTURAL`, `ESTIMATOR`, `REFINISH`, or `ADAS_SPECIALIST`. New technicians start `PROVISIONAL`. The technician's `curriculum_progress_pct` tracks what fraction of the required curriculum for their role is satisfied by non-expired completions.

The training catalogue is administered by a `NetworkAdmin`. Each course has a stable `course_code`, a `title`, a `required_for_roles` array naming the technician roles for which it is required, a `validity_months` (at least 1) for how long a completion stays current, `credit_hours` (zero or more), and an `active` flag (default true) controlling whether new completions may be recorded against it. A completion is recorded by a `ShopManager` or `NetworkAdmin` with the `course_id`, the `completed_at` timestamp, and a `proof_uri`; the server also records the `technician_id` implied by the path. A completion is born `CURRENT` and stays current until `completed_at` plus the course's `validity_months` calendar months; the clock sweep stamps it `EXPIRED` once that instant is past — `EXPIRED` is never set at creation.

Currency is computed per technician as follows. The required set is every `active` course whose `required_for_roles` contains the technician's `tech_role`. A required course is satisfied when the technician holds a completion of that course in `CURRENT` status. `curriculum_progress_pct` is 100.0 times the satisfied count divided by the required count, rounded to 2 decimal places round-half-up; a technician with an empty required set is defined at 100.0 by vacuous satisfaction. Status follows the percentage: a technician is `CURRENT` exactly when progress reaches 100.0 (and they are not `INACTIVE`); when a required completion flips to `EXPIRED` under the clock sweep and drops progress below 100.0, a previously `CURRENT` technician falls to `LAPSED`, the shop's `live_compliance_score` is recomputed with the training-category weight of §3.2, and any repair order in `ESTIMATE` that names this technician as lead can no longer be approved until reassigned — the lapse does not auto-void anything. Recording a new completion that restores progress to 100.0 flips the technician back from `LAPSED` (or `PROVISIONAL`) to `CURRENT` and recomputes the shop score as a compensation. A `PROVISIONAL` technician becomes `CURRENT` the first time progress reaches 100.0, whether via a completion create or a sweep recompute.

A `ShopManager` may deactivate a technician, moving them from `PROVISIONAL` or `CURRENT` to the terminal `INACTIVE`, only while no repair order references the technician with status `ESTIMATE`, `APPROVED`, `IN_REPAIR`, `QC`, `REWORK`, or `CALIBRATION`.

### 3.5. Repair Orders and Procedural Chronology

A repair order is the unit of certified work. A `ShopManager` creates one under their shop with the vehicle's `vin` (17 characters), `vehicle_model_year`, `estimate_total_cents` (zero or more), and an `assigned_technician_id` naming the lead technician; optional fields are `is_structural` (default false), `adas_equipped` (nullable — when omitted the server derives ADAS equipment from the model year, treating vehicles of model year 2018 or later as ADAS-equipped), `referral_id` (nullable for walk-ins), and `insurer_relation_id` (nullable) identifying the DRP relationship the repair is billed under. Creation is OCC-guarded by `expected_shop_version` per §2.9. Creating the order increments the shop's `lifetime_repair_count` — the counter grows at create time and is never touched again — and bumps the shop's `version`. The order begins in `ESTIMATE` with `rework_count` 0, both OE parts ratios at 0.0, and `completed_at` null.

Posture gates new work at two points. Creating a repair order, and later approving its estimate, both require the shop's `certification_status` to be `CERTIFIED` or `PROBATION`; a shop in `SUSPENDED`, `EXPIRED`, or `DECERTIFIED` may not start new repairs, and the attempt is rejected with `ERR_SHOP_NOT_CERTIFIED` (HTTP 422). Approval — moving the order `ESTIMATE → APPROVED` — carries three further preconditions, evaluated after the posture check. Structural work must be backed by capability: if `is_structural` is true, the shop's `structural_capability` must be true and the assigned technician must have `tech_role` `STRUCTURAL` in `CURRENT` status and belong to the same shop, else the approval (or the create of a structural order) is rejected with `ERR_STRUCTURAL_CAPABILITY` (HTTP 422). For non-structural orders the assigned technician must be `CURRENT` or, at the looser bar for non-structural work, `PROVISIONAL`, and must belong to the same shop. And the mandatory pre-repair scanning rule: at least one `PRE_SCAN` procedure step with a `result` other than `NOT_APPLICABLE` must already exist on the order, else approval is rejected with `ERR_PRE_SCAN_REQUIRED` (HTTP 422).

Physical work begins with `APPROVED → IN_REPAIR`, legal only once at least one part line in `ACTIVE` status exists on the order. When the shop believes the work is done, the order moves `IN_REPAIR → QC` by submitting to quality control. Quality control has two exits. Failing QC moves `QC → REWORK` and increments `rework_count` — but only while `rework_count` is below the maximum of 3 loops; failing beyond that is rejected with `ERR_MAX_REWORK` (HTTP 422). A reworked order returns `REWORK → QC` by submitting to QC again. Passing QC splits on the vehicle: on an ADAS-equipped vehicle the order moves `QC → CALIBRATION`, and on a non-ADAS vehicle it moves directly `QC → COMPLETE`.

Completion is chronology-gated, and the two paths differ. On the non-ADAS path, passing QC requires a `POST_SCAN` step with `result` `PASS` whose `performed_at` is strictly later than the `created_at` of every `ACTIVE` part line on the order — the scan-after-parts rule proving the final scan saw the finished car; failure is `ERR_POST_SCAN_REQUIRED` (HTTP 422). On the ADAS path, passing QC from `CALIBRATION` requires an `ADAS_CALIBRATION_STATIC` or `ADAS_CALIBRATION_DYNAMIC` step with `result` `PASS` whose `performed_at` is strictly later than every `POST_SCAN` step's `performed_at` — calibration-after-scan; failure is `ERR_CALIBRATION_SEQUENCE` (HTTP 422). Either completion stamps `completed_at` with the logical clock.

Procedure steps are the evidentiary record. A `ShopManager` records a step with a `step_type` of `PRE_SCAN`, `STRUCTURAL_MEASURE`, `WELD_BOND`, `POST_SCAN`, `ADAS_CALIBRATION_STATIC`, or `ADAS_CALIBRATION_DYNAMIC`; the `performed_by_technician_id`; the `performed_at` timestamp against which all chronology rules are evaluated; a `result` of `PASS`, `FAIL`, or `NOT_APPLICABLE`; and, when the step is a `PRE_SCAN` or `POST_SCAN` with a result other than `NOT_APPLICABLE`, a mandatory `scan_report_uri`. Steps may only be recorded while the order is in `IN_REPAIR`, `QC`, `REWORK`, or `CALIBRATION`. Each step receives a server-assigned `sequence_index`, its chronological position within the order, ordered by `performed_at` ascending with `created_at` ascending as the tie-break. Re-performing a step of the same type voids the prior record: the older step of that `step_type` moves from `RECORDED` to `VOIDED`, and the order's chronology validations are re-evaluated against the surviving records.

An order can be abandoned. From `ESTIMATE`, voiding is unconditional and moves the order to the terminal `VOIDED`, optionally carrying a `reason`. From `APPROVED`, voiding is legal only while no `WELD_BOND` step exists — structural work has not started — and likewise accepts a `reason`. Voiding an approved order does not revert a linked referral that was already `ACCEPTED`; the acceptance remains as historical record.

### 3.6. Parts Provenance and OE Usage

Every part consumed on a repair order is a line item recording the catalog `part_number`, a `part_class` of `OE`, `OE_SURPLUS`, `AFTERMARKET`, `RECYCLED`, or `REMANUFACTURED`, the `unit_cost_cents` (zero or more), the `quantity` (at least 1), an `is_safety_critical` flag (default false), and an `alternative_justification`. Two classification rules guard parts at entry. Safety-critical parts — airbags, seatbelts, structural components — may only be `OE` or `OE_SURPLUS`; a safety-critical line classified otherwise is rejected with `ERR_SAFETY_PART_CLASS` (HTTP 422). And every line whose class is `AFTERMARKET`, `RECYCLED`, or `REMANUFACTURED` must carry a non-empty `alternative_justification` documenting the reason and the consumer's consent reference; a missing justification is rejected with `ERR_ALT_PART_UNDOCUMENTED` (HTTP 422). A line is born `ACTIVE` in `line_status` and may be removed — moving to the terminal `REMOVED` — only while the order remains editable in `ESTIMATE`, `APPROVED`, or `IN_REPAIR`.

Two OE-usage ratios are recomputed on every line create and every removal, over the order's `ACTIVE` lines only, with `OE` and `OE_SURPLUS` counting as original equipment. The by-count ratio, `oe_parts_ratio_by_count`, is the number of active OE-class lines divided by the number of all active lines — each line weighs equally, so a cheap aftermarket clip drags the ratio exactly as much as an expensive aftermarket bumper; this is the variant the audit's OE-usage expectation check reads. The by-cost ratio, `oe_parts_ratio_by_cost`, divides the sum of `unit_cost_cents` times `quantity` over OE-class active lines by the same sum over all active lines — cost-weighted, so expensive OE parts can mask many cheap non-OE lines, and identical input data yields different ratios under the two variants; this is the variant used for insurer DRP reporting. Both ratios are rounded to 4 decimal places round-half-up, and both are defined as 1.0 when the order has no active lines at all — the empty set is vacuously compliant.

### 3.7. Warranty: Delivery Grace, Reserve Accrual, and Claims

Completion is not closure. Twenty-four hours after `completed_at`, if no warranty claim has been filed against the order, the clock sweep moves the order `COMPLETE → WARRANTY_ACTIVE`, and at that moment the shop's `warranty_reserve_cents` is increased by the order's reserve accrual. The accrual is computed from the transitioning order alone, in a pinned evaluation order. First, a marginal tiered rate is applied to the order's `estimate_total_cents`: 3.0% on the first 100,000 cents, 2.0% on the portion above 100,000 up to and including 500,000 cents, and 1.0% on the portion above 500,000 cents — each tier's rate applies only to the base falling within that tier's band. Second, the tiered amount is multiplied by 1.5 when the order is ADAS-equipped, or by 1.0 otherwise. Third, the result is rounded half-up to whole cents. Fourth and last, a flat penalty of 500 cents per rework loop (`rework_count`) is added. Rounding before adding the penalty is mandatory — evaluating in any other order produces different cents.

The warranty period runs 12 calendar months from `completed_at`. A claim may be filed by a `ShopManager` or `NetworkAdmin` — recording `claimant_contact`, a `defect_category` of `WORKMANSHIP`, `PART_DEFECT`, `CORROSION`, `PAINT_ADHESION`, or `CALIBRATION_DRIFT`, and an estimated remedy `claim_amount_cents` (zero or more) — only while the order is in `WARRANTY_ACTIVE` and the filing falls within that window; the server stamps `filed_at` and records `filed_by_role`, and a filing outside the window or against an order in any other status is rejected with `ERR_WARRANTY_EXPIRED` (HTTP 422). The claim is born `FILED`.

Claim handling belongs to the `NetworkAdmin` under segregation of duties. Review moves the claim `FILED → UNDER_REVIEW` and records the reviewing party in `reviewed_by_user_id`, which stays null until review; the claim's own `status` field tracks the `FILED`, `UNDER_REVIEW`, `ESCALATED`, `RESOLVED_ACCEPTED`, `RESOLVED_DENIED`, and `CLOSED` lifecycle. The reviewer may never be the filer, so a claim filed by a `ShopManager` may not be reviewed by that same user — a violation is `ERR_SELF_VERIFICATION` (HTTP 422), and the same rule guards resolution. From `UNDER_REVIEW`, escalation to the OEM is mandatory in form: a claim whose `defect_category` is `PART_DEFECT`, or whose `claim_amount_cents` exceeds 500,000 cents, must pass through `ESCALATED` before it can be resolved, and each claim sitting in `ESCALATED` adds its 3-point penalty to the next audit's grading per §3.3. Resolution with verdict `ACCEPTED` — from `UNDER_REVIEW` or, when escalation was required, from `ESCALATED` — moves the claim to `RESOLVED_ACCEPTED` and decrements the shop's `warranty_reserve_cents` by the claim amount, capped at the order's remaining accrual and never driving the shop reserve below zero; a resolution that would breach that floor is rejected with `ERR_RESERVE_FLOOR` (HTTP 422). Resolution with verdict `DENIED` moves the claim to `RESOLVED_DENIED` with no reserve effect. Thirty days after either resolution, the clock sweep closes the claim. Finally, when the sweep finds the logical clock past the end of the warranty window with no claim of the order in `FILED`, `UNDER_REVIEW`, or `ESCALATED`, the order moves `WARRANTY_ACTIVE → CLOSED` and the unreleased remainder of its accrual is subtracted back out of the shop's reserve — the compensating release that makes a claim-free repair net-zero on the ledger.

### 3.8. Referrals, the Locator, and Insurer Relations

Referrals enter the network from three origins, recorded as `source_type`: `DEALER`, `INSURER`, or `CONSUMER_DIRECT`. A `DealerRep`, `InsurerRep`, or `NetworkAdmin` creates a referral with the `consumer_zip` used for radius ranking, a `source_reference` (dealer code, insurer claim id, or marketing code), the vehicle's `vin`, and — required exactly when the source is an insurer — the `insurer_code`, which is otherwise null. The referral is born `UNROUTED` with `routed_shop_id` null and `routed_at` null.

Routing is a scored selector over an eligibility-filtered candidate pool. A shop is eligible when its `certification_status` is `CERTIFIED` or `PROBATION`, its `locator_hidden` is false, and its location is within 25 miles of the consumer ZIP centroid by haversine distance; when the referral's source is an insurer, an additional gate requires an `ACTIVE` insurer relation between the shop and the referral's `insurer_code` with `steering_enabled` true. Each candidate is scored as 0.6 times (1 minus the distance in miles divided by 25), plus 0.3 times (the shop's `live_compliance_score` divided by 100.0), plus 0.1 times (1 minus the capped load fraction, where the capped load fraction is the smaller of `pending_referral_count` and 20, divided by 20) — proximity dominates, then compliance, then load, with pending workload capped at 20 for the load term and intermediate scores carried to 6 decimal places round-half-up. Candidates sort by score descending; ties break first on `live_compliance_score` descending, then on `created_at` ascending so the earliest-onboarded shop wins — a shop's `id` never participates in ranking or tie-breaking. Routing happens automatically at creation when the pool is non-empty, or on demand for an `UNROUTED` referral at a `NetworkAdmin`'s request. A successful route moves the referral `UNROUTED → ROUTED`, stamps `routed_at` with the logical clock, records the winner as `routed_shop_id`, and increments that shop's `pending_referral_count`. An empty pool is not an error: the referral stays `UNROUTED` and is returned with `routed_shop_id` null.

The routed shop's manager answers within the TTL. Accepting requires the acting shop to be the referral's `routed_shop_id`, the logical clock to be earlier than `routed_at` plus 72 hours, and the shop's posture to still be `CERTIFIED` or `PROBATION`; acceptance moves the referral `ROUTED → ACCEPTED` and decrements the shop's `pending_referral_count`. A late or posture-ineligible acceptance is rejected with `ERR_REFERRAL_EXPIRED` (HTTP 422). Declining — again only by the routed shop — moves the referral to `DECLINED` and decrements the counter. If neither happens, the clock sweep expires the referral at 72 hours past `routed_at`, moving it `ROUTED → EXPIRED` and decrementing the counter as the exact compensation of the routing increment. Recall from §3.1 that a shop suspension cascade also force-declines every `ROUTED` referral pointing at the shop.

The consumer locator is the network's public face: an anonymous search by `zip_code`, with optional `radius_miles`, lists visible shops — those in `CERTIFIED` or `PROBATION` posture with `locator_hidden` false — within the radius, ranked by the same scoring formula above, with `limit` and `offset` paginating the result.

Insurer relations are the network's commercial plumbing. A `NetworkAdmin` establishes a DRP relationship between a shop and an insurer with the stable `insurer_code` — unique per shop-and-insurer pair — and a negotiated `discount_pct_bps` expressed in basis points from 0 to 2000. The relation is born `ACTIVE`, and its `steering_enabled` flag is initialized from the shop's posture at creation: steering is enabled only while the shop is `CERTIFIED` or `PROBATION`, and the flag is recomputed on every shop posture change per the cascades of §3.1. A `NetworkAdmin` may suspend an `ACTIVE` relation (steering off), reinstate a `SUSPENDED` relation — legal only while the shop's posture is `CERTIFIED` or `PROBATION`, recomputing steering from posture — or terminate a relation from `ACTIVE` or `SUSPENDED`, which moves it to the terminal `TERMINATED` status and leaves steering disabled. Decertification terminates every `ACTIVE` relation of the shop outright.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify or act upon an existing resource return `200 OK`. The table below is a navigational summary only — request payloads, response shapes, and side effects are specified in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/network/shops` | Register a new shop into the network as APPLICANT | NetworkAdmin |
| GET | `/network/shops` | List shops with filters and pagination | NetworkAdmin, NetworkAuditor, ShopManager, DealerRep, InsurerRep |
| GET | `/network/shops/{id}` | Fetch one shop incl. derived posture fields | NetworkAdmin, NetworkAuditor, ShopManager, DealerRep, InsurerRep |
| POST | `/network/shops/{id}/decertify` | Terminate a long-suspended shop from the network | NetworkAdmin |
| POST | `/network/shops/{id}/certification-cycles` | Open the next certification cycle; window must be exactly 365 days and zero-gap adjacent to the previous cycle | NetworkAdmin |
| GET | `/network/shops/{id}/certification-cycles` | List a shop's certification cycles | NetworkAdmin, NetworkAuditor, ShopManager |
| GET | `/network/certification-cycles/{id}` | Fetch one cycle | NetworkAdmin, NetworkAuditor, ShopManager |
| POST | `/network/certification-cycles/{id}/close` | Close a cycle with result PASS or FAIL; OCC-guarded; applies grade and shop posture transitions | NetworkAuditor |
| POST | `/network/requirements` | Create a requirement row in DRAFT | NetworkAdmin |
| GET | `/network/requirements` | List requirements with filters; `supersedes_requirement_id` finds revision children of a requirement row | NetworkAdmin, NetworkAuditor, ShopManager |
| GET | `/network/requirements/{id}` | Fetch one requirement row | NetworkAdmin, NetworkAuditor, ShopManager |
| POST | `/network/requirements/{id}/publish` | Publish a DRAFT requirement | NetworkAdmin |
| POST | `/network/requirements/{id}/publish-revision` | Publish a new revision of a PUBLISHED requirement, superseding the old row and lapsing pinned attestations | NetworkAdmin |
| POST | `/network/requirements/{id}/retire` | Retire a requirement; pinned attestations lapse | NetworkAdmin |
| POST | `/network/shops/{id}/attestations` | Attest satisfaction of a published requirement revision; OCC-guarded; supersedes the older ACTIVE attestation for the same requirement row | ShopManager |
| GET | `/network/shops/{id}/attestations` | List a shop's attestations | NetworkAdmin, NetworkAuditor, ShopManager |
| GET | `/network/attestations` | Filtered list of attestations across shops; `requirement_id` finds all attestations pinned to a requirement row | NetworkAdmin, NetworkAuditor |
| GET | `/network/attestations/{id}` | Fetch one attestation | NetworkAdmin, NetworkAuditor, ShopManager |
| POST | `/network/certification-cycles/{id}/audits` | Schedule an audit; half-open window overlap with the same shop's active audits is rejected | NetworkAuditor |
| GET | `/network/certification-cycles/{id}/audits` | List audits of a cycle | NetworkAdmin, NetworkAuditor, ShopManager |
| GET | `/network/audits/{id}` | Fetch one audit | NetworkAdmin, NetworkAuditor, ShopManager |
| POST | `/network/audits/{id}/begin` | Begin a scheduled audit within its window | NetworkAuditor |
| POST | `/network/audits/{id}/cancel` | Cancel a scheduled audit | NetworkAuditor |
| POST | `/network/audits/{id}/issue-findings` | Issue findings; each finding lapses the referenced attestation and opens a corrective action; zero findings passes the audit | NetworkAuditor |
| GET | `/network/audits/{id}/corrective-actions` | List corrective actions of an audit | NetworkAdmin, NetworkAuditor, ShopManager |
| GET | `/network/corrective-actions` | Filtered list of corrective actions; `attestation_id` finds actions against an attestation | NetworkAdmin, NetworkAuditor |
| GET | `/network/corrective-actions/{id}` | Fetch one corrective action | NetworkAdmin, NetworkAuditor, ShopManager |
| POST | `/network/corrective-actions/{id}/submit` | Shop submits corrected evidence before `due_at` | ShopManager |
| POST | `/network/corrective-actions/{id}/verify` | Auditor verifies or rejects submitted evidence; verifier must differ from issuer | NetworkAuditor |
| POST | `/network/shops/{id}/technicians` | Hire a technician into a shop | ShopManager |
| GET | `/network/shops/{id}/technicians` | List a shop's technicians | NetworkAdmin, NetworkAuditor, ShopManager |
| GET | `/network/technicians/{id}` | Fetch one technician | NetworkAdmin, NetworkAuditor, ShopManager |
| POST | `/network/technicians/{id}/deactivate` | Deactivate a technician with no open repair orders | ShopManager |
| POST | `/network/training-courses` | Create a training course | NetworkAdmin |
| GET | `/network/training-courses` | List training courses | NetworkAdmin, NetworkAuditor, ShopManager |
| GET | `/network/training-courses/{id}` | Fetch one course | NetworkAdmin, NetworkAuditor, ShopManager |
| POST | `/network/technicians/{id}/course-completions` | Record a course completion; recomputes curriculum and may flip technician status | ShopManager, NetworkAdmin |
| GET | `/network/technicians/{id}/course-completions` | List a technician's completions | NetworkAdmin, NetworkAuditor, ShopManager |
| GET | `/network/training-courses/{id}/completions` | List completions recorded against a course (reverse lookup) | NetworkAdmin, NetworkAuditor, ShopManager |
| GET | `/network/technicians/{id}/repair-orders` | List repair orders where this technician is the assigned lead (reverse lookup) | NetworkAdmin, NetworkAuditor, ShopManager |
| GET | `/network/technicians/{id}/procedure-steps` | List procedure steps performed by this technician (reverse lookup) | NetworkAdmin, NetworkAuditor, ShopManager |
| GET | `/network/referrals/{id}/repair-orders` | List repair orders created from this referral (reverse lookup) | NetworkAdmin, DealerRep, InsurerRep, ShopManager |
| GET | `/network/insurer-relations/{id}/repair-orders` | List repair orders billed under this insurer relation (reverse lookup) | NetworkAdmin, InsurerRep |
| POST | `/network/shops/{id}/repair-orders` | Create a repair order; OCC-guarded on shop version; requires shop CERTIFIED or PROBATION | ShopManager |
| GET | `/network/shops/{id}/repair-orders` | List a shop's repair orders | NetworkAdmin, NetworkAuditor, ShopManager, InsurerRep |
| GET | `/network/repair-orders/{id}` | Fetch one repair order | NetworkAdmin, NetworkAuditor, ShopManager, InsurerRep |
| POST | `/network/repair-orders/{id}/approve` | Approve an estimate; requires a completed PRE_SCAN step and role/capability checks | ShopManager |
| POST | `/network/repair-orders/{id}/start-repair` | Begin physical repair; requires at least one ACTIVE part line | ShopManager |
| POST | `/network/repair-orders/{id}/submit-qc` | Submit to QC from IN_REPAIR or REWORK | ShopManager |
| POST | `/network/repair-orders/{id}/fail-qc` | Fail QC into REWORK; bounded by the maximum of 3 rework loops | ShopManager |
| POST | `/network/repair-orders/{id}/pass-qc` | Pass QC; routes via CALIBRATION for ADAS vehicles; enforces scan/calibration chronology | ShopManager |
| POST | `/network/repair-orders/{id}/void` | Void an order in ESTIMATE or APPROVED (latter only before structural work starts) | ShopManager |
| POST | `/network/repair-orders/{id}/procedure-steps` | Record a procedure step; re-performing a step type voids the older RECORDED row of the same type | ShopManager |
| GET | `/network/repair-orders/{id}/procedure-steps` | List steps of a repair order | NetworkAdmin, NetworkAuditor, ShopManager, InsurerRep |
| POST | `/network/repair-orders/{id}/part-lines` | Add a part line; safety-critical and documentation rules enforced; ratios recomputed | ShopManager |
| GET | `/network/repair-orders/{id}/part-lines` | List part lines of a repair order | NetworkAdmin, NetworkAuditor, ShopManager, InsurerRep |
| DELETE | `/network/repair-orders/{id}/part-lines/{id}` | Remove a part line while the order is editable | ShopManager |
| POST | `/network/repair-orders/{id}/warranty-claims` | File a warranty claim against a completed certified repair within the warranty window | ShopManager, NetworkAdmin |
| GET | `/network/repair-orders/{id}/warranty-claims` | List claims of a repair order | NetworkAdmin, NetworkAuditor, ShopManager, InsurerRep |
| GET | `/network/warranty-claims/{id}` | Fetch one claim | NetworkAdmin, NetworkAuditor, ShopManager |
| POST | `/network/warranty-claims/{id}/review` | Move a claim to UNDER_REVIEW; reviewer must differ from filer | NetworkAdmin |
| POST | `/network/warranty-claims/{id}/escalate` | Escalate a defect to the OEM; required for PART_DEFECT or claims over the escalation threshold | NetworkAdmin |
| POST | `/network/warranty-claims/{id}/resolve` | Resolve a claim ACCEPTED or DENIED; ACCEPTED decrements the shop reserve (floor 0, capped at the order's remaining accrual) | NetworkAdmin |
| POST | `/network/shops/{id}/insurer-relations` | Establish a DRP relationship between a shop and an insurer | NetworkAdmin |
| GET | `/network/shops/{id}/insurer-relations` | List a shop's insurer relations | NetworkAdmin, NetworkAuditor, ShopManager, InsurerRep |
| GET | `/network/insurer-relations/{id}` | Fetch one insurer relation | NetworkAdmin, InsurerRep |
| POST | `/network/insurer-relations/{id}/suspend` | Suspend a relation; steering off | NetworkAdmin |
| POST | `/network/insurer-relations/{id}/reinstate` | Reinstate a suspended relation when the shop posture allows steering | NetworkAdmin |
| POST | `/network/insurer-relations/{id}/terminate` | Terminate a relation | NetworkAdmin |
| POST | `/network/referrals` | Create a referral; auto-routes via the ranking selector when the candidate pool is non-empty, else stays UNROUTED | DealerRep, InsurerRep, NetworkAdmin |
| GET | `/network/referrals/{id}` | Fetch one referral | NetworkAdmin, DealerRep, InsurerRep, ShopManager |
| GET | `/network/referrals` | Filtered list of referrals; `routed_shop_id` finds referrals pointing at a shop | NetworkAdmin, DealerRep, InsurerRep, ShopManager |
| POST | `/network/referrals/{id}/route` | Explicitly (re)run the routing selector for an UNROUTED referral | NetworkAdmin |
| POST | `/network/referrals/{id}/accept` | Routed shop accepts the referral within the TTL | ShopManager |
| POST | `/network/referrals/{id}/decline` | Routed shop declines the referral | ShopManager |
| POST | `/network/locator/search` | Consumer-facing locator: visible certified/probation shops within radius, ranked by the referral scoring formula; anonymous, no auth | Anonymous |
| POST | `/network/_clock/set_current_utc` | Set the logical clock (startup default 2026-09-01T00:00:00Z); advancing triggers all time-gated sweeps | NetworkAdmin |
| POST | `/network/_sweep/run` | Re-run all time-gated sweeps at the current logical clock without advancing it | NetworkAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in §2 and §3 where the guarded workflow is described.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_SAFETY_PART_CLASS` | 422 |
| `ERR_ALT_PART_UNDOCUMENTED` | 422 |
| `ERR_PRE_SCAN_REQUIRED` | 422 |
| `ERR_POST_SCAN_REQUIRED` | 422 |
| `ERR_CALIBRATION_SEQUENCE` | 422 |
| `ERR_STRUCTURAL_CAPABILITY` | 422 |
| `ERR_SHOP_NOT_CERTIFIED` | 422 |
| `ERR_SELF_VERIFICATION` | 422 |
| `ERR_CYCLE_WINDOW` | 422 |
| `ERR_AUDIT_OVERLAP` | 409 |
| `ERR_AUDIT_WINDOW_MISSED` | 422 |
| `ERR_WARRANTY_EXPIRED` | 422 |
| `ERR_REFERRAL_EXPIRED` | 422 |
| `ERR_CORRECTIVE_OVERDUE` | 422 |
| `ERR_DECERTIFY_BLOCKED` | 422 |
| `ERR_EFFECTIVE_IN_PAST` | 422 |
| `ERR_RESERVE_FLOOR` | 422 |
| `ERR_MAX_REWORK` | 422 |



