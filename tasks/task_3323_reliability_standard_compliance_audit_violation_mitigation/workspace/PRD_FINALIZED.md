# Reliability Compliance Audit API — Product Requirements Document

## 1. Introduction

Bulk-power reliability in a large interconnection depends on a shared, enforceable set of reliability standards — and on a credible program for proving that every registered entity actually meets them, continuously, and not merely at the moment an auditor happens to look. This document specifies the Reliability Compliance Audit API, the system through which a regional reliability organization registers entities by function, schedules and executes compliance monitoring engagements (audits, spot checks, and self-certifications), collects and adjudicates evidence demonstrating continuous coverage of the monitored period, records and prices violations, manages mitigation plans and their milestones, runs a self-logging program for minimal-risk exceptions, controls access evidence for critical infrastructure protection (CIP) assets, and adjudicates appeals through regional and, where requested, federal review.

The business problem the system solves is threefold. First, applicability: an entity that registers as, say, a Generator Owner and a Transmission Operator is subject to a different set of standards than a pure Load-Serving Entity, and that applicable set must stay correct as registrations change, because every downstream workflow — engagements, evidence, violations, self-reports — is scoped by it. Second, evidence over time: compliance is demonstrated by coverage, so the system tracks for each in-scope standard the fraction of the monitored period that submitted and accepted evidence actually covers, with explicit handling of overlapping and adjacent coverage windows. Third, proportionality and process: a violation's penalty is priced from its risk factor and severity with discounts for self-identification, aggravation for engagements whose evidence coverage was gappy, and escalation for recidivism; mitigation, settlement, restriction of non-compliant entities, and two-level appeals are modeled as explicit, auditable state transitions rather than informal correspondence.

All endpoints are mounted under the `/compliance` prefix. Time in this system is governed by a server-maintained logical clock (not wall-clock time): the logical clock defaults to `2026-09-01T00:00:00Z` before any operator sets it, it can be set to a supplied instant, and it can be advanced forward, which is what drives scheduled sweeps such as milestone due-date expiry and restriction of entities with confirmed past-due penalties.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. A request missing either header, or carrying a malformed one, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is not authorized for the endpoint is rejected with `ERR_UNAUTHORIZED`. One scoping rule deserves emphasis because it cuts across the appeals workflow: `RegionalEntityReviewer` may grant or deny only appeals currently in `APPEAL_PENDING_REVIEW`, while `FederalReviewer` may grant or deny only appeals in `FEDERAL_REVIEW_REQUESTED`; the wrong level for the appeal's current status is an authorization failure, not merely an invalid state.

The system recognizes six roles, spelled exactly as follows: `RegistrationCoordinator`, `ComplianceAuditor`, `EntityComplianceOfficer`, `CIPAssetManager`, `RegionalEntityReviewer`, and `FederalReviewer`.

Identity semantics differ by role. When `X-User-Role` is `EntityComplianceOfficer`, `X-User-ID` is the `id` of the acting `RegisteredEntity`; ownership checks on any resource that references a `RegisteredEntity` compare the resource's foreign-key field (for example a self-report's `entity_id` or a violation's `entity_id`) to `X-User-ID`. The same rule applies when `X-User-Role` is `CIPAssetManager`: `X-User-ID` is the `id` of the acting `RegisteredEntity`, and ownership checks on CIP assets and their access grants compare the asset's `entity_id` to `X-User-ID`. When `X-User-Role` is `RegistrationCoordinator`, `ComplianceAuditor`, `RegionalEntityReviewer`, or `FederalReviewer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, to enforce segregation-of-duties rules about who submitted a mitigation plan or created a violation) but does not compare it to any entity's `id`.

Segregation of duties is enforced across workflow steps. The same `X-User-ID` that submitted a `MitigationPlan` may not later approve or verify that plan, and the same `X-User-ID` that created a `Violation` may not confirm its `Penalty`; violations of this rule are rejected with `ERR_SOD_CONFLICT`.

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

List endpoints accept two query parameters. `limit` caps the number of items returned; when omitted it defaults to 10, and accepted values range from a minimum of 1 to a maximum of 100. `offset` says how many items to skip and defaults to 0. Every list response returns resources sorted by `created_at` in ascending order, and the `meta` object of the envelope carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every resource in the system carries a standard set of system-managed fields. `id` is a server-minted UUID with no type prefix. `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits; `updated_at` refreshes on any mutation of the resource. `version` is an integer that increments by one on every mutation and underpins optimistic concurrency control where it applies (§2.7). All entities in this system — `RegisteredEntity`, `Engagement`, `EvidenceArtifact`, `SelfReport`, `Violation`, `MitigationPlan`, `Milestone`, `SelfLogEntry`, `ReviewPeriod`, `CIPAsset`, `AccessGrant`, `Penalty`, and `Appeal` — carry the full common set. Mutations driven by cascades (for example an entity's `compliance_status` flipping because a penalty became past due, or an engagement's `coverage_fraction` recomputing because evidence was accepted) count as mutations of the affected resource and therefore bump its `version` and refresh its `updated_at`.

### 2.5. Validation Order and Nested Resource Retrieval

Incoming requests pass through a fixed sequence of validation layers, and the order matters because it determines which error a multiply-defective request receives. Authentication comes first: missing or malformed `X-User-Role` or `X-User-ID` headers fail as `ERR_UNAUTHENTICATED`. Authorization comes second: a caller whose role is not permitted for the endpoint — including the appeal-level scoping described in §2.1 — fails as `ERR_UNAUTHORIZED`. Existence is checked third: every identifier referenced in the path or the body must resolve to an existing row, validated left-to-right along the path, so a request naming a nonexistent engagement under a nonexistent entity surfaces the failure at the first identifier that does not resolve, as `ERR_NOT_FOUND`. Fourth, the registered-entity posture gate runs: entity-initiated mutation endpoints — filing a self-report, submitting a mitigation plan, filing an appeal, logging a self-log entry, or creating an access grant — are rejected with `ERR_ENTITY_RESTRICTED` when the acting entity's `compliance_status` is `RESTRICTED`. Fifth, optimistic-concurrency checks run where an endpoint requires an expected version (§2.7), with a mismatch rejected as `ERR_STALE_VERSION`. Sixth, generic state preconditions are evaluated: the target resource must be in a state from which the requested transition is defined, or the request fails as `ERR_INVALID_STATE`.

Only after these six layers pass do the domain-specific business rules run, in the following relative order: self-logging enrollment and the CIP access-log evidence requirement first, then the temporal rules (engagement start timing, evidence submission timing, appeal windows, interval well-formedness), then referential ownership (an entity-scoped caller acting only on its own entity's resources, else `ERR_FORBIDDEN`), then standard applicability, then violation source integrity, then the various per-resource constraint checks, then segregation of duties, and finally the fiscal state rules for penalties. Generic malformed input — a missing required field, a wrong type, or an unrecognized enum value — is the final catch-all and is rejected as `ERR_INVALID_REQUEST`.

### 2.6. Precision, Rounding, and Money

All penalty arithmetic uses decimal arithmetic, never floating point. Compound adjustment factors are carried to exactly 4 decimal places using round-half-even. Final monetary amounts are rounded to exactly 2 decimal places using round-half-up. Coverage fractions are likewise expressed to 4 decimal places, rounded half-up. Durations of coverage are computed in integer seconds using exact datetime arithmetic. All monetary values in API responses are rendered as numbers with at most 2 decimal places.

### 2.7. Optimistic Concurrency Control

Two write endpoints require the caller to attest the version of the parent `Violation` they last observed, by including `expected_violation_version` as a non-optional field of the request body: submitting a mitigation plan for a violation, and filing an appeal against a violation. If the supplied value does not match the violation's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). This protects against acting on a stale view of the violation — for example, when another writer's action has already advanced the violation's version since the client last read it. No other endpoint takes an expected-version field.

### 2.8. Entity Posture: Restriction and Reinstatement

Each registered entity carries a derived `compliance_status` of `ACTIVE` or `RESTRICTED`. An entity becomes `RESTRICTED` when a confirmed penalty against it remains unsettled past its due date — that is, when the current logical clock has advanced beyond the penalty's `due_date` while the penalty is still in `CONFIRMED` status. The restriction is applied by the clock-advance sweep and is also checked inline whenever a penalty is confirmed, settled, or waived. The entity returns to `ACTIVE` only when no confirmed past-due penalty remains against it; both settlement and waiver can lift the restriction, and the sweep applies the same rule. While an entity is `RESTRICTED`, the entity-initiated mutations listed in §2.5 are blocked with `ERR_ENTITY_RESTRICTED`.

## 3. Business Logic & Workflows

### 3.1. Registration and the Applicable Standards Set

A `RegistrationCoordinator` onboards a bulk-power participant by creating a `RegisteredEntity` with its `legal_name` and a `registration_functions` list. The function list must be a non-empty subset of the recognized function codes — `GO`, `GOP`, `TO`, `TOP`, `TP`, `BA`, `RC`, `IA`, `PC`, `DP`, `LSE`, and `RP` — because the entire applicability model hangs off it. At creation, and again whenever a registration is updated, the server derives `applicable_standards`: the union, across every function code the entity registered under, of the standard library entries mapped to that code, each element carrying a `standard_id` and a human-readable `standard_code`. The derived `applicable_standard_count` always equals the number of elements in `applicable_standards`, and the same recomputation that rewrites the standard list also rewrites the count, keeping the two in lockstep. A registration update may change `registration_functions`, may flip `enrollment_self_logging` (which defaults to `false` when not supplied at creation), or both; any such update triggers the applicability recomputation even if only the enrollment flag changed in the payload.

Every registered entity also carries three derived posture fields that downstream workflows read constantly. `compliance_status` is `ACTIVE` or `RESTRICTED` per the restriction rule of §2.8. `open_violation_count` counts the entity's violations whose status is `OPEN`, `MITIGATION_SUBMITTED`, `MITIGATION_IN_PROGRESS`, or `APPEALED`, and is recomputed on every violation creation and status change. `unresolved_appeal_count` counts the entity's appeals sitting in `APPEAL_PENDING_REVIEW`. Listing registrations supports filters on `compliance_status` alongside the usual `limit` and `offset`, so reviewers can sweep for restricted entities directly.

### 3.2. Compliance Engagements and Evidence Coverage

A `ComplianceAuditor` schedules an `Engagement` against a registered entity, choosing an `engagement_type` of `AUDIT`, `SPOT_CHECK`, or `SELF_CERTIFICATION`, a non-empty `standard_ids` list naming the standards in scope, and a monitored window from `period_start` to `period_end`; the period end must be strictly after the period start, or the request fails as `ERR_INVALID_INTERVAL`. Every standard named in scope must belong to the target entity's `applicable_standards`; naming a standard the entity is not registered for is rejected with `ERR_STANDARD_NOT_APPLICABLE`, and this applicability check is evaluated again at engagement start time, not only at scheduling. An engagement begins life `SCHEDULED`.

Starting an engagement moves it from `SCHEDULED` to `IN_PROGRESS` and is permitted only once the logical clock has reached `period_start`; an early start attempt is rejected with `ERR_ENGAGEMENT_NOT_YET_OPEN`. Completing moves `IN_PROGRESS` to `COMPLETED` and triggers one final recomputation of the engagement's `coverage_fraction`. Cancellation is allowed from either `SCHEDULED` or `IN_PROGRESS` and lands the engagement in `CANCELLED`; cancelling cascades to the evidence already on file, moving every still-`SUBMITTED` artifact of that engagement to `REJECTED` and recomputing the coverage fraction accordingly. Each start, complete, or cancel is a mutation of the engagement and increments its `version`.

While an engagement is `IN_PROGRESS`, the monitored entity's `EntityComplianceOfficer` submits `EvidenceArtifact` rows into it. Submission to an engagement that is not `IN_PROGRESS` fails with `ERR_ENGAGEMENT_NOT_IN_PROGRESS`. Each artifact names its `engagement_id`, the `standard_id` it speaks for, an `artifact_kind` of `OPERATING_RECORD`, `ACCESS_LOG`, or `MAINTENANCE_RECORD`, and the attested coverage window from `coverage_start` to `coverage_end`, which must be a well-formed interval (end strictly after start, else `ERR_INVALID_INTERVAL`). The server stamps `submitted_at` from the logical clock, and the artifact enters `SUBMITTED`. When the artifact kind is `ACCESS_LOG`, a CIP requirement applies: the artifact must carry a non-null `cip_asset_id` referencing an asset that is currently `ACTIVE` and flagged as a BES cyber asset; an access-log artifact without such a reference is rejected with `ERR_CIP_EVIDENCE_REQUIRED`, and this check runs before the engagement-in-progress temporal check. For other artifact kinds, `cip_asset_id` stays null.

The auditor then adjudicates each artifact. Acceptance moves `SUBMITTED` to `ACCEPTED`; rejection moves it to `REJECTED`; either may record an optional `review_note` (which defaults to an empty string). Both decisions are permitted only while the parent engagement remains `IN_PROGRESS` — once the engagement is completed or cancelled, its evidence is frozen, and an accept or reject attempt is rejected with `ERR_EVIDENCE_NOT_REVIEWABLE`. Every accept or reject recomputes the engagement's `coverage_fraction`, as does the cancellation cascade above, and each decision bumps the artifact's `version`.

The coverage math is precise. For one standard within one engagement, the covered period is computed by collecting the coverage windows of that engagement's artifacts for that standard whose status is `SUBMITTED` or `ACCEPTED`, treating each window as a half-open interval that includes its start and excludes its end, merging overlapping windows into their union and merging adjacent windows whose gap is exactly zero, then intersecting each merged interval with the engagement's monitored period — clipping it at `period_start` and `period_end` — and summing the surviving lengths in integer seconds. The engagement's `coverage_fraction` is then the average across all in-scope standards of each standard's covered period divided by the full monitored period length, rounded half-up to 4 decimal places. Continuous compliance, in other words, means a coverage fraction of one: evidence must cover the whole period, not merely exist somewhere inside it.

Listing endpoints for engagements and evidence accept filters: engagements by `entity_id` and `status`, evidence by `engagement_id`, `cip_asset_id`, and `status`, in each case combined with `limit` and `offset`.

### 3.3. Self-Reports

An entity's `EntityComplianceOfficer` may self-report a potential noncompliance, supplying the `entity_id` of their own entity, the `standard_id` in question, a narrative `description`, and an `occurred_at` timestamp, which must not lie in the future of the logical clock. The caller must act on their own entity — the `entity_id` in the payload must equal the caller's `X-User-ID`, otherwise the request is rejected with `ERR_FORBIDDEN` — and the reported standard must belong to the entity's `applicable_standards`, otherwise `ERR_STANDARD_NOT_APPLICABLE`. A self-report enters `RECEIVED` and then moves, under a `ComplianceAuditor`, from `RECEIVED` to `TRIAGED`, and from there either to `CONFIRMED` or to `DISMISSED`. Confirmation is what makes the report actionable downstream: only a `CONFIRMED` self-report can serve as the source of a recorded violation. Self-reports can be listed filtered by `entity_id` and `status`.

### 3.4. Violations and Proposed Penalty Pricing

A `ComplianceAuditor` records a `Violation` with the violating `entity_id`, the `standard_id` violated (which must belong to that entity's applicable standards, else `ERR_STANDARD_NOT_APPLICABLE`), a `source_type` of `AUDIT`, `SPOT_CHECK`, `SELF_REPORT`, or `SELF_LOG`, a violation interval from `violation_start` to `violation_end` (end strictly after start, else `ERR_INVALID_INTERVAL`), an assessed `violation_risk_factor` of `MINIMAL`, `MODERATE`, or `SERIOUS`, and an assessed `severity_level` of `LOWER`, `MODERATE`, `HIGH`, or `SEVERE`. Source integrity is enforced. When the source type is `AUDIT` or `SPOT_CHECK`, a `source_engagement_id` must be supplied referencing an engagement of the matching type that has reached `COMPLETED`; when the source type is `SELF_REPORT`, a `source_self_report_id` must be supplied referencing a self-report in `CONFIRMED` status. Violations whose source references are missing, mismatched, or not in the required terminal state are rejected with `ERR_VIOLATION_SOURCE_INVALID`. A violation created with source type `SELF_LOG` arises only through the self-log review escalation path of §3.6, never through direct creation.

The moment a violation enters `OPEN`, the server computes its `proposed_penalty`, and creating the violation increments the owning entity's `open_violation_count` by one. The proposed penalty is built as a weighted score. The base amount is read from a fixed table keyed by risk factor: one thousand for `MINIMAL`, five thousand for `MODERATE`, and twenty-five thousand for `SERIOUS`. A compound adjustment factor then starts at one and is multiplied step by step: doubled when the severity is `SEVERE`, multiplied by one and a half when the severity is `HIGH`, multiplied by 0.6 when the violation came in through a self-report, multiplied by 0.4 when it came in through the self-logging program, and multiplied by 1.25 when the violation references a source engagement whose `coverage_fraction` is below 0.8 — an evidence-coverage gap aggravates the penalty because thin coverage undermines confidence in the monitored period. Finally, recidivism escalates: the server counts the entity's other violations that are `CLOSED` with a non-null `final_penalty`, caps that count at five, and multiplies the running factor by one plus one tenth times the capped count. The factor is then rounded half-even to 4 decimal places, and the amount is the base times the factor, rounded half-up to 2 decimal places.

A violation is priced as `proposed_penalty` while it sits in `OPEN` or `APPEALED`. The `final_penalty` stays null until the violation reaches `CLOSED`, at which point the same computation runs again with one difference: if the violation's `violation_end` lies more than 365 days before the closure time, the base amount is first discounted by ten percent — nine tenths of the tabulated base, rounded half-up to 2 decimal places — before the factor steps apply. Every other step is identical: the severity multipliers, the self-identification discounts, the coverage-gap aggravation for a source engagement whose `coverage_fraction` is below 0.8, and the recidivism escalation all apply again in the closure recomputation. Violations are listable filtered by `entity_id`, `status`, `source_engagement_id`, and `source_self_report_id`.

The violation lifecycle itself is the spine of the whole system; §3.5 through §3.8 walk its branches.

### 3.5. Mitigation Plans and Milestones

When a violation sits in `OPEN`, the entity's `EntityComplianceOfficer` submits a mitigation plan by providing a narrative `description` together with the required `expected_violation_version` carrying the violation `version` the client last observed — the OCC contract of §2.7, under which a stale view is rejected with `ERR_STALE_VERSION`. Two business preconditions guard this step, evaluated after the OCC check: the violation must actually be in `OPEN` (a plan submission against a violation in any other state fails as `ERR_VIOLATION_STATE`), and the violation must not already have a mitigation plan — the relationship is one-to-one, so a second plan for the same violation fails as `ERR_MITIGATION_PLAN_EXISTS`. A successful submission creates the `MitigationPlan`, stamps `submitted_at` from the logical clock, flips the plan from `DRAFT` to `SUBMITTED` immediately, and moves the violation from `OPEN` to `MITIGATION_SUBMITTED`, bumping the violation's `version`. The entity's `open_violation_count` does not change here: a violation in `MITIGATION_SUBMITTED` is still counted as open.

Under a `ComplianceAuditor`, a `SUBMITTED` plan can be approved or rejected. Approval moves the plan to `APPROVED` and, as a cascade, moves the violation from `MITIGATION_SUBMITTED` to `MITIGATION_IN_PROGRESS`. Rejection moves the plan to `REJECTED` and leaves the violation where it is. Rejection is also possible from `APPROVED` — a post-approval rejection keeps the violation in `MITIGATION_IN_PROGRESS` while the plan itself returns to `REJECTED`, from which the entity may resubmit it back to `SUBMITTED`, optionally revising the `description`; resubmission from any state other than `REJECTED` fails as `ERR_PLAN_STATE`. Recall from §2.1 that whoever submitted the plan may not be the one to approve or later verify it.

Milestones structure the plan's execution. The entity adds a `Milestone` to a plan by supplying a `title` and a `due_date` that must lie strictly in the future of the logical clock at creation, else `ERR_INVALID_INTERVAL`; the milestone's `plan_id` is assigned by the system to the plan named in the request. Milestones may be added only while the plan is `APPROVED` — adding to a plan in any other state fails as `ERR_PLAN_STATE` — and each new milestone starts `PENDING`. Marking a milestone complete, also gated on the plan being `APPROVED`, moves it from `PENDING` to `COMPLETED` and stamps `completed_at` from the logical clock. The clock-advance sweep plays the other side of this lifecycle: any milestone still `PENDING` whose `due_date` has fallen behind the logical clock is swept to `MISSED`. A missed milestone is not dead — marking it complete from `MISSED` still moves it to `COMPLETED` with `completed_at` stamped, and the late completion remains auditable through the milestone's `updated_at` and `version`.

Once every milestone of the plan stands in `COMPLETED` — none `PENDING`, none `MISSED` — the entity's officer marks the mitigation complete, moving the violation from `MITIGATION_IN_PROGRESS` to `MITIGATION_COMPLETE`. Attempting this with milestones outstanding is rejected with `ERR_MILESTONES_INCOMPLETE`, and attempting it from any other violation state fails as `ERR_VIOLATION_STATE`. The final step is verification: the auditor verifies an `APPROVED` plan — verification from any other plan state fails as `ERR_PLAN_STATE` — and only when the violation has reached `MITIGATION_COMPLETE`, else `ERR_VIOLATION_STATE`. Verification moves the plan to `VERIFIED` and cascades the violation from `MITIGATION_COMPLETE` to `CLOSED`, which recomputes the violation's `final_penalty` per §3.4, decrements the entity's `open_violation_count` by one, and upserts the violation's `Penalty` row so its `amount` equals the recomputed final penalty. Plans are listable filtered by `violation_id` and `status`, and a plan's milestones are listed under the plan itself.

### 3.6. The Self-Logging Program and Review Periods

Entities enrolled in the self-logging program — those whose `enrollment_self_logging` flag is true — may log minimal-risk exceptions directly instead of waiting for formal processing. The entity's officer registers a `SelfLogEntry` with their own `entity_id` (mismatch with `X-User-ID` is `ERR_FORBIDDEN`), a `standard_id` that must belong to the entity's applicable standards, and an `exception_note` describing the exception. An entity not enrolled is rejected with `ERR_SELF_LOG_NOT_ENROLLED`. The server stamps `logged_at` and attaches the entry to a review period: the caller may name an explicit `period_id`, or leave it null, in which case the system attaches the entry to the nearest unclosed period by that period's `open_at` time. Either way, the period's `entry_count` grows by one — `entry_count` is the running count of self-log entries attached to the period. The entry begins in `LOGGED`.

A `ComplianceAuditor` opens a new `ReviewPeriod` at any time; the server stamps `open_at`, `closed_at` starts null, and the period is `OPEN`. Moving the period from `OPEN` to `REVIEWING` requires that at least one entry has accumulated — starting review of an empty period is rejected with `ERR_EMPTY_REVIEW_PERIOD`. While the period is `REVIEWING`, the auditor reviews each `LOGGED` entry with an `outcome` of `REVIEWED_OK` or `ESCALATED`; reviewing an entry whose period is not in `REVIEWING` fails as `ERR_INVALID_STATE`. A `REVIEWED_OK` outcome moves the entry to `REVIEWED_OK` and adds one to the period's `reviewed_ok_count` — the period's count of entries that passed review. An `ESCALATED` outcome moves the entry to `ESCALATED`, adds one to the period's `escalated_count` — its count of escalated entries — and creates a `Violation` for the entry's entity and standard with source type `SELF_LOG`. For an escalation, the review call also carries a `violation_risk_factor` and a `severity_level` for the violation being created. Here the program's bargain shows: when the escalation's risk factor is `MINIMAL` and its severity is `LOWER`, the violation is created with `is_self_logging_qualified` set to true and moves atomically from `OPEN` to `DISMISSED` in the same act — it never enters `open_violation_count`, the net effect on the count being zero. Any other risk/severity combination creates the violation in `OPEN` and increments the entity's `open_violation_count` by one, which is how a self-log escalation becomes a formal case. The `is_self_logging_qualified` flag is set at creation and is true only for the minimal-risk, lowest-severity combination.

Closing a period moves it from `REVIEWING` to `CLOSED` and stamps `closed_at`, but only when every entry of the period has been adjudicated — any entry still `LOGGED` blocks closure with `ERR_ENTRIES_UNREVIEWED`. Entries of a period can be listed directly (with a `status` filter), self-log entries overall can be listed filtered by `entity_id`, `period_id`, and `status`, and review periods can be listed filtered by `status`.

### 3.7. CIP Assets and Access Control Evidence

Critical infrastructure protection has its own slice of the model, owned by the `CIPAssetManager` role acting for its entity. Registering a `CIPAsset` records the owning `entity_id`, an `asset_name`, and an `impact_rating` of `HIGH`, `MEDIUM`, or `LOW`. The server derives `is_bes_cyber_asset`: it is true exactly when the impact rating is `HIGH`, and false otherwise. This flag is what drives the access-log evidence obligation of §3.2 — access-log artifacts must point at an `ACTIVE` asset whose flag is true. An asset begins `ACTIVE` and can be decommissioned, moving it one-way to `DECOMMISSIONED`. Decommissioning is blocked while any access grant against the asset is still `ACTIVE`; the attempt is rejected with `ERR_ACTIVE_ACCESS_GRANTS`, so grants must be revoked first.

An `AccessGrant` records `asset_id`, the opaque `grantee_badge` of the person being granted access, and a `scope` of `PHYSICAL` or `ELECTRONIC`. The server stamps `granted_at`, leaves `revoked_at` null, and starts the grant `ACTIVE`. Granting access to an asset that is already `DECOMMISSIONED` fails with `ERR_ASSET_DECOMMISSIONED`. Revoking moves a grant one-way from `ACTIVE` to `REVOKED` and stamps `revoked_at`. Assets and grants are listable, filtered by `entity_id` and `status` for assets and by `asset_id` and `status` for grants.

### 3.8. Penalties, Settlement, and Entity Restriction

Issuing a penalty for a violation creates the `Penalty` row in `ASSESSED`, one per violation. The row snapshots the violation's pricing at issuance: `base_amount` and `adjustment_factor` come from the penalty computation, and `amount` is the snapshot of the violation's `proposed_penalty` — the base times the factor, rounded half-up to 2 decimal places as always. The server stamps `issued_at` and sets `due_date` exactly thirty days after issuance. A `ComplianceAuditor` confirms an `ASSESSED` penalty, moving it to `CONFIRMED` — confirming a penalty in any other state fails as `ERR_PENALTY_ALREADY_RESOLVED`, and recall from §2.1 that the auditor who created the violation may not be the one to confirm its penalty. Confirmation is also a restriction checkpoint: if the penalty is already past due at confirm time, the owning entity's `compliance_status` becomes `RESTRICTED` per §2.8.

A confirmed penalty resolves in one of two terminal ways. The entity's officer settles it, moving `CONFIRMED` to `SETTLED`; settlement is an entity-scoped action, so the caller's identity must match the entity that owns the violation, else `ERR_FORBIDDEN`. Alternatively, a `FederalReviewer` waives it, moving `CONFIRMED` to `WAIVED` — the federal override. Either action attempted on a penalty not in `CONFIRMED` fails as `ERR_PENALTY_NOT_CONFIRMED`. Both resolution paths re-run the restriction check for the owning entity: if the entity was `RESTRICTED` and no other confirmed past-due penalty remains against it, the entity returns to `ACTIVE`. When a violation reaches `CLOSED` through mitigation verification or a granted appeal, the penalty row for that violation is created or updated so that its `amount` equals the violation's recomputed `final_penalty` — the closing act re-prices the penalty to its final number. Penalties are listable filtered by `violation_id` and `status`.

### 3.9. Appeals and Two-Level Review

An entity that disputes a violation files an appeal, supplying `grounds` and the OCC field `expected_violation_version` per §2.7. Filing is permitted while the violation is `OPEN`, `MITIGATION_SUBMITTED`, or `MITIGATION_IN_PROGRESS` — from any other violation state the filing fails as `ERR_VIOLATION_STATE` — and only within the appeal window: the filing must reach the system no later than 30 days (the appeal-window length) measured from the moment the violation entered `OPEN`, and a filing after that window has closed is rejected with `ERR_APPEAL_WINDOW_EXPIRED`. Only one appeal may be live at a time: the appealable-state and appeal-window checks above run first, and only then, if the violation already has an appeal in `APPEAL_PENDING_REVIEW` or `FEDERAL_REVIEW_REQUESTED`, is a further filing rejected with `ERR_DUPLICATE_ACTIVE_APPEAL` — a second filing against a violation sitting in `APPEALED` therefore fails as `ERR_VIOLATION_STATE`, not as a duplicate. A successful filing creates the `Appeal` in `APPEAL_PENDING_REVIEW`, stamps `submitted_at`, moves the violation to `APPEALED`, bumps the violation's `version`, and adds one to the entity's `unresolved_appeal_count`.

At the regional level, a `RegionalEntityReviewer` grants or denies the pending appeal, moving it to `APPEAL_GRANTED` or `APPEAL_DENIED` respectively. A grant at either review level — regional or federal — closes the case: the violation moves from `APPEALED` to `CLOSED`, its `final_penalty` is recomputed per §3.4 (with the stale-violation discount applied when the violation ended more than 365 days before closure), the entity's `open_violation_count` drops by one, the entity's `unresolved_appeal_count` drops by one, and the violation's penalty row is created or updated with `amount` equal to the recomputed final penalty. A denial restores the violation to wherever its mitigation posture dictates: back to `OPEN` when no mitigation plan exists for the violation, back to `MITIGATION_SUBMITTED` when the plan is `SUBMITTED` or `REJECTED`, and back to `MITIGATION_IN_PROGRESS` when the plan is `APPROVED`; each denial path decrements the entity's `unresolved_appeal_count` by one — unless the denial is subsequently re-opened for federal review, in which case the federal-review request re-increments it, keeping the count aligned with appeals still alive.

A denied appeal is not necessarily final. Within the federal review window — the request must be filed no later than 30 days (the federal-review-window length) measured from the moment of denial, otherwise it is rejected with `ERR_APPEAL_WINDOW_EXPIRED` — the entity's officer requests federal review, moving the appeal from `APPEAL_DENIED` to `FEDERAL_REVIEW_REQUESTED` and adding one to `unresolved_appeal_count`; the request from any status other than `APPEAL_DENIED` fails as `ERR_INVALID_STATE`. At the federal level, a `FederalReviewer` grants or denies the appeal a second time, with the same consequences as the regional decision: a grant closes the violation, a denial restores its pre-appeal posture per the plan state, and in both cases the counter bookkeeping flows through the violation transition. The second grant or denial is final. Appeals are listable filtered by `violation_id` and `status`.

### 3.10. The Logical Clock and Scheduled Sweeps

Time itself is administered. A `RegionalEntityReviewer` sets the logical clock to a supplied `to_iso8601` instant, or advances it forward by a number of `seconds`; either operation returns the resulting `now`. Advancing the clock runs two sweeps in one motion. The milestone sweep moves every `PENDING` milestone whose `due_date` has fallen behind the new clock to `MISSED` (§3.5). The restriction sweep walks all penalties: every penalty in `CONFIRMED` whose `due_date` lies before the current clock forces its owning entity's `compliance_status` to `RESTRICTED`, and an entity returns to `ACTIVE` only when no confirmed past-due penalty remains (§2.8). Because the sweeps run on advance, tests and operators drive time-dependent behavior — restriction, missed milestones, appeal-window expiry — entirely through these clock operations rather than by waiting.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource return `200 OK`. The table below is a summary only — request payloads, preconditions, and side effects are specified by the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/compliance/_clock/set_current_utc` | Set the logical clock to a supplied instant | RegionalEntityReviewer |
| POST | `/compliance/_clock/advance` | Advance the logical clock; runs milestone and restriction sweeps | RegionalEntityReviewer |
| POST | `/compliance/registrations` | Register an entity by function set | RegistrationCoordinator |
| GET | `/compliance/registrations` | List registered entities | RegistrationCoordinator, ComplianceAuditor, RegionalEntityReviewer, FederalReviewer, EntityComplianceOfficer, CIPAssetManager |
| GET | `/compliance/registrations/{entityId}` | Get one registered entity | RegistrationCoordinator, ComplianceAuditor, RegionalEntityReviewer, FederalReviewer, EntityComplianceOfficer, CIPAssetManager |
| PATCH | `/compliance/registrations/{entityId}` | Update functions and/or self-logging enrollment; recompute applicability | RegistrationCoordinator |
| POST | `/compliance/engagements` | Schedule an audit, spot check, or self-certification | ComplianceAuditor |
| GET | `/compliance/engagements` | List engagements | ComplianceAuditor, RegionalEntityReviewer, FederalReviewer, EntityComplianceOfficer |
| GET | `/compliance/engagements/{engagementId}` | Get one engagement | ComplianceAuditor, RegionalEntityReviewer, FederalReviewer, EntityComplianceOfficer |
| POST | `/compliance/engagements/{engagementId}/start` | Transition SCHEDULED to IN_PROGRESS | ComplianceAuditor |
| POST | `/compliance/engagements/{engagementId}/complete` | Transition IN_PROGRESS to COMPLETED | ComplianceAuditor |
| POST | `/compliance/engagements/{engagementId}/cancel` | Cancel a non-terminal engagement; cascade-rejects submitted evidence | ComplianceAuditor |
| POST | `/compliance/evidence` | Submit an evidence artifact to an in-progress engagement | EntityComplianceOfficer |
| GET | `/compliance/evidence` | List evidence artifacts | ComplianceAuditor, RegionalEntityReviewer, FederalReviewer, EntityComplianceOfficer |
| GET | `/compliance/evidence/{evidenceId}` | Get one evidence artifact | ComplianceAuditor, RegionalEntityReviewer, FederalReviewer, EntityComplianceOfficer |
| POST | `/compliance/evidence/{evidenceId}/accept` | Accept submitted evidence | ComplianceAuditor |
| POST | `/compliance/evidence/{evidenceId}/reject` | Reject submitted evidence | ComplianceAuditor |
| POST | `/compliance/self-reports` | Entity self-reports a potential violation | EntityComplianceOfficer |
| GET | `/compliance/self-reports` | List self-reports | ComplianceAuditor, RegionalEntityReviewer, FederalReviewer, EntityComplianceOfficer |
| GET | `/compliance/self-reports/{selfReportId}` | Get one self-report | ComplianceAuditor, RegionalEntityReviewer, FederalReviewer, EntityComplianceOfficer |
| POST | `/compliance/self-reports/{selfReportId}/triage` | Transition RECEIVED to TRIAGED | ComplianceAuditor |
| POST | `/compliance/self-reports/{selfReportId}/confirm` | Transition TRIAGED to CONFIRMED | ComplianceAuditor |
| POST | `/compliance/self-reports/{selfReportId}/dismiss` | Transition TRIAGED to DISMISSED | ComplianceAuditor |
| POST | `/compliance/violations` | Record a violation; computes the proposed penalty | ComplianceAuditor |
| GET | `/compliance/violations` | List violations | ComplianceAuditor, RegionalEntityReviewer, FederalReviewer, EntityComplianceOfficer |
| GET | `/compliance/violations/{violationId}` | Get one violation | ComplianceAuditor, RegionalEntityReviewer, FederalReviewer, EntityComplianceOfficer |
| POST | `/compliance/violations/{violationId}/mitigation-plans` | Submit a mitigation plan for an open violation (OCC-guarded) | EntityComplianceOfficer |
| GET | `/compliance/mitigation-plans` | List mitigation plans | ComplianceAuditor, RegionalEntityReviewer, FederalReviewer, EntityComplianceOfficer |
| GET | `/compliance/mitigation-plans/{planId}` | Get one mitigation plan | ComplianceAuditor, RegionalEntityReviewer, FederalReviewer, EntityComplianceOfficer |
| POST | `/compliance/mitigation-plans/{planId}/approve` | Transition SUBMITTED to APPROVED; violation enters MITIGATION_IN_PROGRESS | ComplianceAuditor |
| POST | `/compliance/mitigation-plans/{planId}/reject` | Transition SUBMITTED or APPROVED to REJECTED | ComplianceAuditor |
| POST | `/compliance/mitigation-plans/{planId}/resubmit` | Transition REJECTED to SUBMITTED (revision loop) | EntityComplianceOfficer |
| POST | `/compliance/mitigation-plans/{planId}/verify` | Transition APPROVED to VERIFIED; closes the violation and finalizes the penalty | ComplianceAuditor |
| POST | `/compliance/mitigation-plans/{planId}/milestones` | Add a milestone to a plan | EntityComplianceOfficer |
| GET | `/compliance/mitigation-plans/{id}/milestones` | List milestones of a plan | ComplianceAuditor, RegionalEntityReviewer, FederalReviewer, EntityComplianceOfficer |
| GET | `/compliance/milestones/{milestoneId}` | Get one milestone | ComplianceAuditor, RegionalEntityReviewer, FederalReviewer, EntityComplianceOfficer |
| POST | `/compliance/milestones/{milestoneId}/complete` | Transition PENDING or MISSED to COMPLETED | EntityComplianceOfficer |
| POST | `/compliance/violations/{violationId}/complete-mitigation` | Transition MITIGATION_IN_PROGRESS to MITIGATION_COMPLETE; requires all milestones completed | EntityComplianceOfficer |
| POST | `/compliance/self-log-entries` | Log a minimal-risk exception under the self-logging program | EntityComplianceOfficer |
| GET | `/compliance/self-log-entries` | List self-log entries | ComplianceAuditor, RegionalEntityReviewer, FederalReviewer, EntityComplianceOfficer |
| GET | `/compliance/self-log-entries/{entryId}` | Get one self-log entry | ComplianceAuditor, RegionalEntityReviewer, FederalReviewer, EntityComplianceOfficer |
| GET | `/compliance/review-periods/{periodId}/entries` | List self-log entries attached to a review period | ComplianceAuditor, RegionalEntityReviewer, FederalReviewer, EntityComplianceOfficer |
| POST | `/compliance/self-log-entries/{entryId}/review` | Apply a review outcome to a logged entry whose period is reviewing | ComplianceAuditor |
| POST | `/compliance/review-periods` | Open a new self-log review period | ComplianceAuditor |
| GET | `/compliance/review-periods` | List review periods | ComplianceAuditor, RegionalEntityReviewer, FederalReviewer, EntityComplianceOfficer |
| GET | `/compliance/review-periods/{periodId}` | Get one review period | ComplianceAuditor, RegionalEntityReviewer, FederalReviewer, EntityComplianceOfficer |
| POST | `/compliance/review-periods/{periodId}/start-review` | Transition OPEN to REVIEWING | ComplianceAuditor |
| POST | `/compliance/review-periods/{periodId}/close` | Transition REVIEWING to CLOSED; requires every entry reviewed | ComplianceAuditor |
| POST | `/compliance/cip-assets` | Register a CIP asset with impact categorization | CIPAssetManager |
| GET | `/compliance/cip-assets` | List CIP assets | ComplianceAuditor, RegionalEntityReviewer, FederalReviewer, EntityComplianceOfficer, CIPAssetManager |
| GET | `/compliance/cip-assets/{assetId}` | Get one CIP asset | ComplianceAuditor, RegionalEntityReviewer, FederalReviewer, EntityComplianceOfficer, CIPAssetManager |
| POST | `/compliance/cip-assets/{assetId}/decommission` | Transition ACTIVE to DECOMMISSIONED; requires no active grants | CIPAssetManager |
| POST | `/compliance/access-grants` | Grant physical or electronic access to a CIP asset | CIPAssetManager |
| GET | `/compliance/access-grants` | List access grants | ComplianceAuditor, RegionalEntityReviewer, FederalReviewer, CIPAssetManager |
| GET | `/compliance/access-grants/{grantId}` | Get one access grant | ComplianceAuditor, RegionalEntityReviewer, FederalReviewer, CIPAssetManager |
| POST | `/compliance/access-grants/{grantId}/revoke` | Transition ACTIVE to REVOKED | CIPAssetManager |
| POST | `/compliance/penalties` | Issue the penalty for a violation (creates the row in ASSESSED) | ComplianceAuditor |
| GET | `/compliance/penalties` | List penalties | ComplianceAuditor, RegionalEntityReviewer, FederalReviewer, EntityComplianceOfficer |
| GET | `/compliance/penalties/{penaltyId}` | Get one penalty | ComplianceAuditor, RegionalEntityReviewer, FederalReviewer, EntityComplianceOfficer |
| POST | `/compliance/penalties/{penaltyId}/confirm` | Transition ASSESSED to CONFIRMED | ComplianceAuditor |
| POST | `/compliance/penalties/{penaltyId}/settle` | Transition CONFIRMED to SETTLED | EntityComplianceOfficer |
| POST | `/compliance/penalties/{penaltyId}/waive` | Transition CONFIRMED to WAIVED (federal override) | FederalReviewer |
| POST | `/compliance/violations/{violationId}/appeals` | File an appeal (OCC-guarded) | EntityComplianceOfficer |
| GET | `/compliance/appeals` | List appeals | ComplianceAuditor, RegionalEntityReviewer, FederalReviewer, EntityComplianceOfficer |
| GET | `/compliance/appeals/{appealId}` | Get one appeal | ComplianceAuditor, RegionalEntityReviewer, FederalReviewer, EntityComplianceOfficer |
| POST | `/compliance/appeals/{appealId}/grant` | Grant an appeal at the level matching its current status | RegionalEntityReviewer, FederalReviewer |
| POST | `/compliance/appeals/{appealId}/deny` | Deny an appeal at the level matching its current status | RegionalEntityReviewer, FederalReviewer |
| POST | `/compliance/appeals/{appealId}/request-federal-review` | Transition APPEAL_DENIED to FEDERAL_REVIEW_REQUESTED within the federal window | EntityComplianceOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_SOD_CONFLICT` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ENTITY_RESTRICTED` | 409 |
| `ERR_STANDARD_NOT_APPLICABLE` | 422 |
| `ERR_INVALID_INTERVAL` | 422 |
| `ERR_ENGAGEMENT_NOT_YET_OPEN` | 409 |
| `ERR_ENGAGEMENT_NOT_IN_PROGRESS` | 409 |
| `ERR_EVIDENCE_NOT_REVIEWABLE` | 409 |
| `ERR_CIP_EVIDENCE_REQUIRED` | 422 |
| `ERR_VIOLATION_SOURCE_INVALID` | 422 |
| `ERR_VIOLATION_STATE` | 409 |
| `ERR_MITIGATION_PLAN_EXISTS` | 409 |
| `ERR_PLAN_STATE` | 409 |
| `ERR_MILESTONES_INCOMPLETE` | 409 |
| `ERR_SELF_LOG_NOT_ENROLLED` | 422 |
| `ERR_EMPTY_REVIEW_PERIOD` | 422 |
| `ERR_ENTRIES_UNREVIEWED` | 409 |
| `ERR_ACTIVE_ACCESS_GRANTS` | 409 |
| `ERR_ASSET_DECOMMISSIONED` | 409 |
| `ERR_APPEAL_WINDOW_EXPIRED` | 422 |
| `ERR_DUPLICATE_ACTIVE_APPEAL` | 409 |
| `ERR_PENALTY_NOT_CONFIRMED` | 409 |
| `ERR_PENALTY_ALREADY_RESOLVED` | 409 |
| `ERR_STALE_VERSION` | 412 |
