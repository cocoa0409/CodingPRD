# Program Evaluation Federal Reporting API — Product Requirements Document

## 1. Introduction

Federal agencies that fund social programs must demonstrate, with credible evidence, whether those programs work. This document specifies the Program Evaluation Federal Reporting API: the system of record an independent evaluation firm uses to run a federally commissioned study from contract award through public dissemination. The API covers the award of an evaluation contract carrying research questions, design constraints, and required reporting deliverables; the selection of a randomized or quasi-experimental design backed by a formal power analysis and a site-recruitment feasibility projection; site and participant recruitment under informed consent; institutional review board approval with strict burden minimization; data collection across surveys, administrative records, and site visits with linkage and privacy protections; preregistration of the analysis plan to foreclose selective reporting; peer-reviewed findings reporting to the agency under comment, revision, and publication timelines; preparation of restricted-use data files for outside researchers under disclosure-risk review; and dissemination and technical assistance to program operators.

Two commitments shape every rule that follows. The first is research integrity: primary outcomes are frozen at preregistration, treatment allocation is deterministic and reproducible, report deadlines are enforced against a server-maintained logical clock, and segregation of duties prevents any operator from reviewing their own work. The second is human-subjects protection: no data collection may occur outside an active IRB approval window, per-participant burden is capped, unresolved records of withdrawn participants are quarantined, and a restricted-use file is released only after surviving a quantitative disclosure-risk gate. Wherever money, time, or privacy is at stake, the API favors an explicit, auditable transition over an implicit one.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. All resources are mounted under the `/evaluation` URL prefix; the single exception is the platform-level logical-clock capability described in §2.4.

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which names their operational capacity. The system recognizes nine roles: `AgencyOfficer`, `PrincipalInvestigator`, `StudyDirector`, `DataManager`, `IRBReviewer`, `PeerReviewer`, `Participant`, `ExternalResearcher`, and `PlatformAdmin`. A request missing either header, or carrying an `X-User-Role` value that is not one of these nine declared role names, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). Once a request is authenticated, each operation is restricted to the roles named for it in §4; an authenticated caller attempting an operation outside their role is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

Role identity works in two distinct ways. When `X-User-Role` is `Participant`, `X-User-ID` is the `id` of the acting `Participant` record; ownership checks on any resource that references a `Participant` compare the resource's foreign-key field to `X-User-ID`. A caller in the `Participant` role may therefore consent only on their own record, withdraw only their own record, and read only their own detail view — any attempt to act on a participant whose `id` differs from `X-User-ID` is rejected with `ERR_UNAUTHORIZED_ROLE`. When `X-User-Role` is any of `AgencyOfficer`, `PrincipalInvestigator`, `StudyDirector`, `DataManager`, `IRBReviewer`, `PeerReviewer`, `ExternalResearcher`, or `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — as `submitted_by_id` and `decided_by_id` on an IRB protocol, as `submitted_by_id` and `reviewed_by_id` on a findings report, or as `prepared_by_id` on a restricted-use file — but it never compares such an `X-User-ID` to any entity's `id`.

Three segregation-of-duties pairings follow from this identity model, and each is enforced where the corresponding workflow is described in §3: an `IRBReviewer` may not decide a protocol that the same `X-User-ID` submitted; a `PeerReviewer` may not review a findings report that the same `X-User-ID` submitted; and the `AgencyOfficer` deciding a disclosure review may not be the operator whose `X-User-ID` prepared the file. Each violation is rejected with `ERR_SEGREGATION_OF_DUTIES`. Separately, the `ExternalResearcher` role has read-only access to exactly one collection — a study's restricted-use files — and sees only released files there, as detailed in §3.9. The `PlatformAdmin` role exists solely to operate the logical clock of §2.4 and performs no business operations.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and Temporal Semantics

Every temporal rule in this API — approval windows, collection windows, review deadlines — is evaluated against a server-maintained logical clock, never against wall-clock time. Before any operator intervention the logical clock reads exactly `2026-09-01T00:00:00Z`, the `CLOCK_DEFAULT_UTC` constant, and it never falls back to wall-clock time on its own. It advances only when explicitly set: a benchmark operator in the `PlatformAdmin` role sets the clock through `POST /_clock/set_current_utc`, an endpoint mounted deliberately at the server root outside the `/evaluation` prefix, supplying `to_iso8601` as an ISO 8601 UTC timestamp; a successful call returns the new `current_utc` with HTTP 200. Setting the clock is also the trigger on which IRB expiry is evaluated: any protocol whose approval window has ended at the new logical time expires immediately, firing the suspension cascade described in §3.3.

Two boundary conventions apply uniformly. First, every validity window in the system — an IRB approval window delimited by `approval_start` and `approval_end`, a data-collection window delimited by `open_at` and `close_at` — is half-open: it includes its start instant and excludes its end instant. An IRB protocol is therefore already expired at exactly its `approval_end`, and a wave may be opened at exactly its `open_at` but not at exactly its `close_at`. Second, action deadlines are inclusive: an action due at a computed timestamp remains allowed at exactly that timestamp and fails one second later. Deadline arithmetic uses whole days at second precision, as detailed in §3.7 and §3.8.

### 2.5. Common Resource Properties

Every resource in this API — contract, study, design plan, IRB protocol, site, participant, data collection wave, response record, analysis plan, findings report, restricted-use file, and dissemination activity — carries a standard set of system-managed fields:

- `id` (string): a unique, server-generated identifier for the resource, formatted as a UUID with no type prefix.
- `created_at` (string): an ISO 8601 timestamp in UTC with three fractional digits (for example, `2026-09-01T00:00:00.000Z`) recording when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp, in the same format, recording the most recent modification of the resource.
- `version` (integer): a system-managed integer that increments by one on every mutation of the resource, whether the mutation came from a client request or from an automatic system transition.

Any change to a resource — a state transition, a recomputed counter, a cascade-applied quarantine, an extended approval window — refreshes `updated_at` and increments `version` on that resource. Because no resource type in this API is exempt, clients can rely on these four fields being present in every object returned in `data`.

### 2.6. Hierarchical Integrity, Cascades, and Quarantine

The resource hierarchy is a tree with one cross-branch link. An `EvaluationContract` owns one or more `Study` resources (referenced by the study's `contract_id`). A `Study` in turn owns design plans, IRB protocols, sites, data collection waves, analysis plans, findings reports, restricted-use files, and dissemination activities, each carrying the owning `study_id`. A `Site` owns its participants via their `site_id`, and a `DataCollectionWave` owns its response records via their `wave_id`. The single cross-branch reference is that each `ResponseRecord` also points at a `Participant` through `participant_id`, linking the collection branch back to the recruitment branch.

Hierarchical consistency is maintained by cascade. When a parent resource reaches a state that invalidates its descendants — a contract terminated, a site withdrawn, an IRB protocol expired — the server automatically transitions every affected descendant in the same request, without requiring a separate client call on each one. Conversely, child events can advance a parent: a study's `status` moves forward on its own when a design plan locks, a first wave opens, a last wave closes, a first report is drafted, a first report is published, or dissemination completes. Each cascade-applied transition is a full mutation of the affected resource, refreshing its `updated_at` and incrementing its `version`.

Quarantine is the system's mechanism for isolating data whose integrity context has collapsed. A response record in `QUARANTINED` status is terminal, is excluded from the participant's billed-burden total, and is counted on the study's `quarantined_record_count`; nothing restores a quarantined record, even when the condition that caused the quarantine is later remedied. The full set of quarantine triggers is enumerated in §3.5 and §3.6.

### 2.7. Nested Resource Retrieval

The API enforces a strict, hierarchical validation protocol for all requests that target nested resources. When an endpoint path contains multiple resource identifiers (for example, a study nested under a contract, or a wave nested under a study), the system validates the existence of each identifier in sequential, left-to-right order, and a nested resource must actually belong to its path parent. The request is rejected immediately with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not exist or does not belong to the enclosing parent; the system does not proceed to evaluate later identifiers or any business rule once an earlier path segment has failed.

### 2.8. Request Validation Order

Every mutating request passes through a fixed pipeline of validation stages, and the pipeline is ordered: the first failing stage determines the error returned, so a caller can never observe a later-stage error while an earlier-stage failure is present. The stages, in order, are:

1. **User context.** `X-User-ID` and `X-User-Role` must be present and the role must be a declared role name (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`, HTTP 400).
2. **Authorization.** The role must be in the endpoint's role list; additionally, for the entity-backed `Participant` role acting on a participant resource, `X-User-ID` must equal that participant's `id` (`ERR_UNAUTHORIZED_ROLE`, HTTP 403).
3. **Path existence.** Path identifiers must exist and nest correctly, validated left to right (`ERR_NOT_FOUND`, HTTP 404).
4. **Request-body schema.** Required fields must be present, undeclared fields are rejected, types must be valid, enum values must be in range, and a window end must be after its start where applicable (`ERR_INVALID_REQUEST`, HTTP 400).
5. **Optimistic concurrency.** Where §2.9 applies, the supplied `expected_study_version` must match the study's current `version` (`ERR_STALE_VERSION`, HTTP 412).
6. **State validity.** The target entity must be in a valid from-state for the requested transition, and each child-creating operation must find its parent in a state that accepts children — a contract must be `ACTIVE`, a study must be in the stage appropriate to the child type and never `TERMINATED` or `COMPLETED`, a site must be `RECRUITED` or `ACTIVE` to accept participants, and a wave must be `OPEN` to accept records. The state-stage errors are `ERR_CONTRACT_NOT_ACTIVE`, `ERR_STUDY_INVALID_STATE`, `ERR_DESIGN_PLAN_INVALID_STATE`, `ERR_IRB_INVALID_STATE`, `ERR_SITE_INVALID_STATE`, `ERR_PARTICIPANT_INVALID_STATE`, `ERR_WAVE_INVALID_STATE`, `ERR_ANALYSIS_PLAN_INVALID_STATE`, `ERR_REPORT_INVALID_STATE`, `ERR_RUF_INVALID_STATE`, `ERR_DISSEMINATION_INVALID_STATE`, and `ERR_WAVE_NOT_OPEN` (each HTTP 409).
7. **Human-subjects compliance.** The compliance stage enforces IRB coverage (`ERR_NO_APPROVED_IRB`, `ERR_IRB_EXPIRED`), consent-form version currency (`ERR_CONSENT_VERSION_STALE`), the per-participant burden cap (`ERR_BURDEN_CAP_EXCEEDED`), preregistration timing (`ERR_PREREGISTRATION_TOO_LATE`), the freeze on primary outcomes (`ERR_PRIMARY_OUTCOME_FROZEN`), segregation of duties (`ERR_SEGREGATION_OF_DUTIES`), and the disclosure-risk release gate (`ERR_DISCLOSURE_RISK_TOO_HIGH`).
8. **Windows and deadlines.** Temporal rules follow: wave opening inside its declared window (`ERR_WAVE_WINDOW_NOT_STARTED`), site-visit spacing (`ERR_VISIT_WINDOW_CONFLICT`), non-overlapping IRB approval windows (`ERR_IRB_WINDOW_OVERLAP`), and the revision and publication deadlines (`ERR_REVISION_DEADLINE_MISSED`, `ERR_PUBLICATION_DEADLINE_MISSED`).
9. **Capacity, coverage, and gates.** The penultimate stage enforces site capacity (`ERR_SITE_CAPACITY_EXCEEDED`), design feasibility (`ERR_INSUFFICIENT_POWER`), primary-outcome coverage (`ERR_UNREPORTED_PRIMARY_OUTCOME`), participant eligibility for data collection (`ERR_PARTICIPANT_NOT_CONSENTED`), the published-report prerequisite (`ERR_NO_PUBLISHED_REPORT`), and the all-studies-completed closeout gate (`ERR_STUDIES_NOT_COMPLETED`).
10. **Fiscal sufficiency.** Last, the payment milestone on a publication must fit within the contract's remaining funds (`ERR_INSUFFICIENT_CONTRACT_FUNDS`, HTTP 402).

### 2.9. Optimistic Concurrency Control

Exactly one operation in this API carries an optimistic-concurrency guard: creating a design plan for a study. Because that creation supersedes the study's current `DRAFT` or `RETURNED_FOR_REVISION` plan and advances the study's `version`, the create request must carry `expected_study_version` holding the `version` of the study as the client last observed it; the field is non-optional on that operation. If the supplied value no longer matches the study's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412), which signals that another design-plan write has legitimately superseded the prior plan since the client last read the study. No other endpoint takes a version field: a client that supplies one anywhere else has supplied an undeclared field, and all other mutations proceed without a concurrency token.

### 2.10. Numeric Precision and Rounding

Distinct quantities in this domain carry distinct, deliberately chosen precision rules, and each calculation in §3 states which rule it uses:

- **Money** is exact integer arithmetic in cents. `award_amount_cents`, `disbursed_cents`, `forfeited_cents`, `remaining_cents`, and `payment_milestone_cents` are integers; no rounding ever applies, and the ledger invariant of §3.1 holds to the cent.
- **Sample sizes** round up: required per-arm enrollment is always rounded up to the next whole participant, and the total requirement is exactly twice the per-arm figure.
- **Recruitment yields** round down: each pipeline site's contribution is rounded down to a whole participant before any summing.
- **Burden minutes** round half up per record: each response record's billed minutes are individually rounded half up to a whole minute, and participant totals are exact integer sums of those per-record values. The rounding order — round each record first, then sum — is pinned; summing raw products and rounding once at the end is explicitly rejected.
- **Disclosure-risk scores** are computed to 4 decimal places with round-half-up rounding.

All numeric values are represented in API responses as standard JSON numbers, not strings.

## 3. Business Logic & Workflows

### 3.1. Contract Award and the Funds Ledger

Work begins when an `AgencyOfficer` awards an **EvaluationContract**, supplying an `agency_code` identifying the funding agency, a `title`, the total `award_amount_cents` as an integer number of cents that must be greater than zero, and optionally a `deliverable_report_count` naming how many `FINAL` reports the agency requires — the count defaults to 1 and must be at least 1. A new contract starts `ACTIVE` with `disbursed_cents` and `forfeited_cents` both zero and `remaining_cents` equal to the full award.

The contract's three ledger fields form a single invariant that holds at every observable instant: the disbursed amount plus the forfeited amount plus the remaining amount always equals the award amount. Funds leave `remaining_cents` in exactly two ways. Publication of a findings report disburses that report's payment milestone, as described in §3.8. Termination or closeout of the contract forfeits whatever remains undisbursed: in both cases `forfeited_cents` is set to the then-current `remaining_cents` and `remaining_cents` becomes zero, so the invariant is preserved.

Termination is the nuclear option. An `AgencyOfficer` terminates an `ACTIVE` contract — any other contract state is rejected with `ERR_CONTRACT_NOT_ACTIVE` — supplying a `reason` that is recorded in the contract's `terminated_reason` field (which stays null on an unterminated contract). Termination cascades through the entire hierarchy of §2.6 in the same request: every non-terminal study of the contract moves to `TERMINATED`; within each such study, every non-terminal site moves to `WITHDRAWN`; every non-terminal participant of those sites moves to `WITHDRAWN` with `withdrawal_reason` set to `CONTRACT_TERMINATED`; every `RECEIVED` or `VALIDATED` response record of a withdrawn participant moves to `QUARANTINED`; every `PLANNED`, `OPEN`, or `SUSPENDED` wave moves to `CANCELLED`; every `DRAFT`, `SUBMITTED`, `PEER_REVIEWED`, or `REVISION` findings report moves to `CANCELLED`; and every `PLANNED` dissemination activity moves to `CANCELLED`.

Closeout is the orderly exit. An `AgencyOfficer` closes out a contract only while it is `ACTIVE` (otherwise `ERR_CONTRACT_NOT_ACTIVE`) and only when every study of the contract has reached `COMPLETED`; if any study is short of `COMPLETED`, the closeout is rejected with `ERR_STUDIES_NOT_COMPLETED`. A successful closeout moves the contract to `CLOSED` and forfeits the undisbursed remainder exactly as termination does. `CLOSED` and `TERMINATED` are both terminal for a contract. While a contract lives, its `ACTIVE` status is also the gate for creating studies beneath it: attempting to create a study under a contract that is not `ACTIVE` fails with `ERR_CONTRACT_NOT_ACTIVE`.

### 3.2. Study Setup and Design Planning

A `PrincipalInvestigator` creates a **Study** under an `ACTIVE` contract, supplying a `title` and the `research_question` text. The study is born in `DESIGN` status with `committed_projected_n`, `pipeline_projected_n`, `enrolled_total`, and `quarantined_record_count` all zero and `sample_adequacy` set to `UNASSESSED`. From there the study advances on its own through the stages `DESIGN` → `RECRUITMENT` → `DATA_COLLECTION` → `ANALYSIS` → `REPORTING` → `DISSEMINATION` → `COMPLETED` as the milestones described in §3.4 through §3.8 are reached; no client ever sets a study's stage directly. `TERMINATED` is reachable from any non-terminal stage, but only through the contract-termination cascade of §3.1.

The first artifact a study needs is a **DesignPlan**. A `PrincipalInvestigator` drafts one while the study is in `DESIGN` or `RECRUITMENT` — at any later stage the creation is rejected with `ERR_STUDY_INVALID_STATE` — supplying the `design_type` (one of `RCT`, `QED_MATCHING`, `QED_RDD`, or `QED_DID`; any of the three `QED_*` values selects the quasi-experimental variant), the minimum detectable effect `mde` (a standardized effect that must be greater than zero), the average `cluster_size` (participants per cluster, at least 1), the intra-cluster correlation `icc` (between 0 and 1 inclusive), and the assumed `attrition_rate` (at least 0 and strictly less than 1). Two informational fields, `alpha` (default 0.05) and `power_target` (default 0.8), may be supplied for documentation, but the computation below always uses the pinned critical values regardless of what they say. The allocation ratio is expressed as `randomization_ratio_num` treatment slots out of `randomization_ratio_den` total slots per allocation cycle — the numerator defaults to 1 and must be at least 1 and strictly less than the denominator, which defaults to 2 and must be at least 2. Malformed combinations of any of these inputs are rejected with `ERR_INVALID_REQUEST`.

Creating a design plan is the one OCC-guarded write in the system: the request must carry `expected_study_version` equal to the study's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412) per §2.9. A successful creation starts the plan in `DRAFT` with `revision_number` 1 — unless it supersedes an existing plan, in which case the new plan's `revision_number` is the superseded plan's value plus one. Creation automatically supersedes the study's current plan when that plan sits in `DRAFT` or `RETURNED_FOR_REVISION`: the older plan moves to `SUPERSEDED`, a terminal state, and is never again the study's current plan. The creation also increments the study's `version` by one and triggers the feasibility recomputation of §3.4.

The required sample size is stamped onto the plan at creation and is never recomputed afterward — a later revise only reopens the plan for submission and never re-derives its numbers. The computation proceeds in fixed steps. First, the design effect is one plus the product of the intra-cluster correlation and one less than the average cluster size. Second, the raw per-arm requirement is twice the square of the sum of the two pinned critical values — the two-sided significance critical value `Z_ALPHA_CRIT` of 1.96 and the power critical value `Z_POWER_CRIT` of 0.84 — multiplied by the design effect and divided by the square of the minimum detectable effect. Third, for an `RCT` design the per-arm sample size `n_per_arm` is the raw requirement divided by one minus the attrition rate, rounded up to the next whole participant; for any quasi-experimental variant the raw requirement is first multiplied by the variance inflation factor `QED_VARIANCE_INFLATION` of 1.44 (the square of 1.2) before the same attrition division and upward rounding, so identical inputs always demand a larger per-arm sample under a quasi-experimental design. Finally, `required_total_n` is exactly twice `n_per_arm`. For illustration, with `mde` 0.5, `cluster_size` 10, `icc` 0.05, and `attrition_rate` 0.15, the design effect is 1.45 and the raw requirement is 90.944; an `RCT` plan then requires 107 per arm for a `required_total_n` of 214, while a quasi-experimental plan requires 155 per arm for a total of 310.

Submission is the feasibility gate. A `PrincipalInvestigator` submits a plan only from `DRAFT` — submission from any other state is rejected with `ERR_DESIGN_PLAN_INVALID_STATE` — and only when the study's `pipeline_projected_n` (the optimistic recruitment projection of §3.4) is at least the plan's `required_total_n`; a shortfall is rejected with `ERR_INSUFFICIENT_POWER` (HTTP 422). A successful submission moves the plan to `SUBMITTED`.

The agency then decides. An `AgencyOfficer` records a `decision` on a `SUBMITTED` plan — from any other state the attempt is rejected with `ERR_DESIGN_PLAN_INVALID_STATE`. A `decision` of `APPROVED` moves the plan to `AGENCY_APPROVED`, and if at that moment at least one site of the study is already `RECRUITED` or `ACTIVE`, the plan continues immediately, within the same request, to `LOCKED` — and the study, if still in `DESIGN`, advances to `RECRUITMENT` in the same breath. A `decision` of `RETURNED` instead moves the plan to `RETURNED_FOR_REVISION`, from which a `PrincipalInvestigator` reopens it as `DRAFT` by revising; revising increments `revision_number` by one, keeps every design parameter unchanged, and is itself allowed only from `RETURNED_FOR_REVISION` (otherwise `ERR_DESIGN_PLAN_INVALID_STATE`). Independently of the decision path, a plan in `AGENCY_APPROVED` locks automatically the moment the study's first site reaches `RECRUITED` or `ACTIVE` — §3.4 describes how signing a site MOU triggers this — and locking is what advances a `DESIGN` study into `RECRUITMENT`. `LOCKED` is terminal: a locked plan can no longer be revised, resubmitted, or superseded, and several downstream operations require it.

### 3.3. The IRB Protocol and Human-Subjects Compliance

No human-subjects activity — site activation, wave opening, participant consent — may proceed without a currently approved **IRBProtocol**, and the protocol's lifecycle is deliberately cyclical. A `PrincipalInvestigator` drafts a protocol for a study with a `title` and an `estimated_burden_minutes` estimate of the per-participant burden, which must be at least 0 and at most the system-wide burden ceiling `MAX_TOTAL_BURDEN_MINUTES` of 480 minutes; an estimate outside that range is rejected with `ERR_INVALID_REQUEST`. The protocol starts in `DRAFT` with `consent_form_version` 1.

A `PrincipalInvestigator` submits the protocol to the IRB from `DRAFT`, from `MODIFICATIONS_REQUIRED`, or from `EXPIRED` — resubmission after required modifications and re-submission after expiry both follow the same path — and submission from any other state is rejected with `ERR_IRB_INVALID_STATE`. Each submission records the caller's `X-User-ID` in `submitted_by_id` and moves the protocol to `SUBMITTED`.

An `IRBReviewer` then records a `decision`. The reviewer must not be the operator who submitted the protocol: if the deciding `X-User-ID` equals the recorded `submitted_by_id`, the decision is rejected with `ERR_SEGREGATION_OF_DUTIES`. A `decision` of `MODIFICATIONS_REQUIRED` moves the protocol back for rework with no further bookkeeping beyond recording `decided_by_id`. A `decision` of `APPROVED` pins the approval window: the payload must carry `approval_start` and `approval_end`, the end must be after the start, and the window's length must not exceed `IRB_MAX_APPROVAL_DAYS` of 365 days — violations of any of these are rejected with `ERR_INVALID_REQUEST`. The half-open window from `approval_start` (inclusive) to `approval_end` (exclusive) must also not overlap the approval window of any other `APPROVED` protocol of the same study; two windows that merely touch, one's start equalling the other's end, do not count as overlapping. An overlap is rejected with `ERR_IRB_WINDOW_OVERLAP`. On approval the deciding reviewer's `X-User-ID` is stored in `decided_by_id`, and if the protocol's history within this submission cycle passed through `MODIFICATIONS_REQUIRED` at least once, `consent_form_version` increments by one — this is how participants are forced to re-consent against revised consent language, per §3.5.

An approved protocol can be extended without a full resubmission. Continuing review by an `IRBReviewer` on an `APPROVED` protocol — any other state is rejected with `ERR_IRB_INVALID_STATE` — accepts a `new_approval_end` and sets `approval_end` to it, incrementing the protocol's `version`. The extension may only lengthen, never shorten: `new_approval_end` must be strictly later than the current `approval_end` and no later than 365 days after the protocol's original `approval_start`, measured from that original start rather than from any previously extended end; anything else is rejected with `ERR_INVALID_REQUEST`. Continuing review is a self-loop — the protocol stays `APPROVED` throughout.

Expiry is automatic and unforgiving. When the logical clock of §2.4 reaches or passes an `APPROVED` protocol's `approval_end` — at exactly `approval_end` the protocol is already expired, because the window is half-open — the protocol moves to `EXPIRED` and the cascade fires in the same instant: every `OPEN` wave of the study moves to `SUSPENDED`, and every `RECEIVED` or `VALIDATED` response record of each newly suspended wave moves to `QUARANTINED`, with the study's `quarantined_record_count` recomputed to include them. An `EXPIRED` protocol is not terminal — it can be resubmitted as described above — but until a protocol of the study is approved again, every IRB-gated operation fails. That gate has two distinct failure textures used consistently in §3.4, §3.5, and §3.6: if no protocol of the study has ever reached `APPROVED`, the rejection is `ERR_NO_APPROVED_IRB`; if approved protocols exist but every approval window has passed, the rejection is `ERR_IRB_EXPIRED`.

### 3.4. Site Recruitment and Feasibility Projections

Sites are the recruitment engine, and a `StudyDirector` manages their pipeline. Adding a **Site** to a study requires the study to be in `DESIGN` or `RECRUITMENT` — any other stage is rejected with `ERR_STUDY_INVALID_STATE` — and takes a `name` and a `max_participants` capacity of at least 1. A new site starts `PROSPECTED`.

Outreach advances or ends the pursuit. Recording an outreach `outcome` on a `PROSPECTED` site — from any other state the call is rejected with `ERR_SITE_INVALID_STATE` — moves it to `CONTACTED` when the `outcome` is `CONTACTED`, or to the terminal `DECLINED` when the `outcome` is `DECLINED`. Signing the memorandum of understanding moves a `CONTACTED` site to `RECRUITED`; signing requires the study to still be in `DESIGN` or `RECRUITMENT` (otherwise `ERR_STUDY_INVALID_STATE`) and carries an important side effect: if the study's current design plan — the latest-created plan not in `SUPERSEDED` — is sitting in `AGENCY_APPROVED`, the plan locks immediately to `LOCKED`, and the study, if still in `DESIGN`, advances to `RECRUITMENT`. Activation then moves a `RECRUITED` site to `ACTIVE`, but only behind two gates: the study must hold an `APPROVED` IRB protocol whose window covers the current logical time (`ERR_NO_APPROVED_IRB` when none is approved, `ERR_IRB_EXPIRED` when every approved window has passed), and the study's current design plan must be `LOCKED` (otherwise `ERR_DESIGN_PLAN_INVALID_STATE`). Only an `ACTIVE` site can consent participants.

Withdrawal unwinds a site. A `StudyDirector` may withdraw a site from `RECRUITED` or `ACTIVE` — from any other state the rejection is `ERR_SITE_INVALID_STATE` — optionally recording a `reason`. Withdrawal cascades: every non-terminal participant of the site moves to `WITHDRAWN` with `withdrawal_reason` `SITE_WITHDRAWN`, each such participant withdrawal quarantines that participant's `RECEIVED` or `VALIDATED` records and, when the participant had consented, decrements the site's `enrolled_count`, exactly as §3.5 specifies for participant withdrawal. The study's `committed_projected_n`, `pipeline_projected_n`, `enrolled_total`, and `sample_adequacy` are then recomputed — and because a withdrawn site contributes nothing, adequacy can flip from `ADEQUATE` back to `UNDERPOWERED`. The remaining site state, `COMPLETED`, is reached only through the study-completion cascade of §3.8, which moves every `ACTIVE` site to `COMPLETED`.

Two projection counters on the study quantify recruitment feasibility, and they are recomputed on every site creation, outreach, MOU signing, activation, and withdrawal, as well as on every design-plan creation. `committed_projected_n` counts only secured capacity: the sum of `max_participants` over the study's `RECRUITED` and `ACTIVE` sites. `pipeline_projected_n` adds expected yield from the pipeline: for each `CONTACTED` site, the site's `max_participants` multiplied by the yield credit `YIELD_CONTACTED` of 0.35 and rounded down to a whole participant, plus for each `PROSPECTED` site the same product with the yield credit `YIELD_PROSPECTED` of 0.10, again rounded down per site before summing. Sites in `DECLINED`, `WITHDRAWN`, or `COMPLETED` contribute zero to both variants. For illustration, a study with one `RECRUITED` site of capacity 60 and two `CONTACTED` sites of capacity 300 each reports a committed projection of 60 and a pipeline projection of 270 — 60 plus 105 plus 105. The study's `sample_adequacy` derives from these figures: it is `UNASSESSED` while the study has no non-superseded design plan, `ADEQUATE` once the pipeline projection is at least the current plan's `required_total_n`, and `UNDERPOWERED` when it falls short. This adequacy signal is informational everywhere except at design-plan submission, where §3.2's gate enforces it.

### 3.5. Participant Consent, Randomization, and Withdrawal

A `StudyDirector` identifies a prospective **Participant** at a site by supplying a site-local `external_ref` reference code — deliberately not a government identifier. Identification requires the site to be `RECRUITED` or `ACTIVE`; at any other site state the creation is rejected with `ERR_SITE_INVALID_STATE`. The participant starts `IDENTIFIED`, with `consent_form_version` and `consented_at` both null and `burden_total_minutes` at 0. Staff roles can list participants with optional `site_id` and `status` filters; a caller in the `Participant` role can read only their own record, as §2.1 establishes.

Consent is self-service. The participant themselves — `X-User-Role` `Participant` with `X-User-ID` equal to the participant's `id`, otherwise `ERR_UNAUTHORIZED_ROLE` — consents by supplying the `consent_form_version` they are signing. The gate chain runs: the participant must be `IDENTIFIED` (otherwise `ERR_PARTICIPANT_INVALID_STATE`); the site must be `ACTIVE` (otherwise `ERR_SITE_INVALID_STATE`); the study must hold an `APPROVED` IRB protocol whose window covers the current logical time (`ERR_NO_APPROVED_IRB` if none has ever been approved, `ERR_IRB_EXPIRED` if every approved window has passed); the supplied `consent_form_version` must equal that currently approved protocol's `consent_form_version` — a participant handed last cycle's form is rejected with `ERR_CONSENT_VERSION_STALE`; and the site's `enrolled_count` must be below its `max_participants`, with a consent arriving when the site is exactly at capacity rejected with `ERR_SITE_CAPACITY_EXCEEDED`. A successful consent moves the participant to `CONSENTED`, records the signed `consent_form_version` and the logical-clock time in `consented_at`, increments the site's `enrolled_count` by one, and recomputes the study's `enrolled_total`.

Randomization is deterministic and reproducible by construction. A `PrincipalInvestigator` randomizes a participant who is `CONSENTED` — any other status is rejected with `ERR_PARTICIPANT_INVALID_STATE`, and the catalogue additionally associates `ERR_PARTICIPANT_NOT_CONSENTED` with this consent requirement on the randomization path — under a study whose current design plan is `LOCKED` (otherwise `ERR_DESIGN_PLAN_INVALID_STATE`). The allocation rule uses the site's own `randomized_count` of randomizations performed so far: compute the remainder of that count divided by the locked plan's `randomization_ratio_den`; when the remainder is strictly less than `randomization_ratio_num` the participant enters `RANDOMIZED_TREATMENT`, and otherwise `RANDOMIZED_CONTROL`. The site's `randomized_count` then increments by one. Under the default 1-of-2 ratio, allocations at a site alternate deterministically — treatment, control, treatment, control — beginning with treatment.

Withdrawal is always available pre-completion and takes three origins. A participant withdraws themselves (the `Participant` role, `X-User-ID` equal to the participant's `id`, otherwise `ERR_UNAUTHORIZED_ROLE`), or a `StudyDirector` withdraws them; an optional `reason` may accompany the request. Withdrawal is permitted from `IDENTIFIED`, `CONSENTED`, `RANDOMIZED_TREATMENT`, or `RANDOMIZED_CONTROL` — any other status is rejected with `ERR_PARTICIPANT_INVALID_STATE` — and arrives at `WITHDRAWN` with `withdrawal_reason` recording the origin: `PARTICIPANT_INITIATED` when the participant or a study director initiated it directly, `SITE_WITHDRAWN` when it arrived through the site-withdrawal cascade, or `CONTRACT_TERMINATED` through contract termination. Leaving a consented-or-randomized status decrements the site's `enrolled_count` by one and recomputes the study's `enrolled_total`; leaving `IDENTIFIED` touches neither, since an identified-only participant was never counted. In all cases, every `RECEIVED` or `VALIDATED` response record of the participant moves to `QUARANTINED` and the study's `quarantined_record_count` is recomputed. Participants in `CONSENTED` or either randomized status instead reach `COMPLETED` through the site-completion cascade of §3.8; `COMPLETED` and `WITHDRAWN` are the terminal participant states.

The enrollment counters obey a strict reconciliation invariant: at every observable instant, the sum of `enrolled_count` over a study's sites equals the study's `enrolled_total`, and both equal a direct recount of the participants in the three counted statuses — `CONSENTED`, `RANDOMIZED_TREATMENT`, and `RANDOMIZED_CONTROL`. The consent (+1) and withdrawal (−1) side effects exist precisely to keep this compensating pair in balance.

### 3.6. Data Collection Waves and Response Records

A `DataManager` plans a **DataCollectionWave** for a study in `RECRUITMENT` or `DATA_COLLECTION` — at any other study stage the creation is rejected with `ERR_STUDY_INVALID_STATE`. The wave carries a `wave_type` of `SURVEY`, `ADMIN_RECORDS`, or `SITE_VISIT`; an inclusive window start `open_at`; and an exclusive window end `close_at` that must be later than `open_at` (a malformed window is rejected with `ERR_INVALID_REQUEST`). A `SITE_VISIT` wave must name its host through `site_id`, while `site_id` is forbidden — present only as null — on the other two wave types; violating either rule is rejected with `ERR_INVALID_REQUEST`. Site visits additionally observe a spacing rule: at the same site, a new `SITE_VISIT` window must neither overlap nor sit closer than `SITE_VISIT_MIN_GAP_DAYS` of 7 days to the window of any other non-`CANCELLED` `SITE_VISIT` wave of that site — a gap of exactly 7 days passes, anything tighter or overlapping is rejected with `ERR_VISIT_WINDOW_CONFLICT`. A new wave starts `PLANNED`. Beyond the per-study listing, a cross-study wave listing exists for operations staff, filterable by `site_id` (a reverse lookup of every wave touching a site), `study_id`, `wave_type`, and `status`.

Opening a wave is the moment collection becomes legal. A `DataManager` opens a wave from `PLANNED` or `SUSPENDED` — from any other state the rejection is `ERR_WAVE_INVALID_STATE` — and only while the current logical time lies within the wave's window: at exactly `open_at` opening is allowed, at exactly `close_at` it is not, and any attempt outside the window is rejected with `ERR_WAVE_WINDOW_NOT_STARTED`. Opening also requires live IRB coverage per §3.3 (`ERR_NO_APPROVED_IRB`, `ERR_IRB_EXPIRED`). The first wave of a study to reach `OPEN` advances the study from `RECRUITMENT` to `DATA_COLLECTION`. When a `SUSPENDED` wave is reopened after re-approval, its records that the expiry cascade quarantined remain `QUARANTINED` — there is no auto-restore, by the quarantine principle of §2.6.

While a wave is `OPEN`, a `DataManager` adds a **ResponseRecord** to it — any other wave state is rejected with `ERR_WAVE_NOT_OPEN` — supplying the responding `participant_id`, the raw `instrument_minutes` (at least 1), and an opaque `payload_ref` pointing at the collected instrument payload. The participant must be in `CONSENTED`, `RANDOMIZED_TREATMENT`, or `RANDOMIZED_CONTROL` and therefore not `WITHDRAWN`; an ineligible participant is rejected with `ERR_PARTICIPANT_NOT_CONSENTED`. Each record's billed burden is computed individually: `billed_minutes` is the record's `instrument_minutes` multiplied by the mode factor of the owning wave's `wave_type` — `MODE_FACTOR_SURVEY` of 1.0 for `SURVEY`, `MODE_FACTOR_SITE_VISIT` of 1.25 for `SITE_VISIT`, and `MODE_FACTOR_ADMIN_RECORDS` of 0.5 for `ADMIN_RECORDS` — rounded half up to a whole minute. A participant's `burden_total_minutes` is then the exact integer sum of `billed_minutes` over that participant's records in `RECEIVED`, `VALIDATED`, or `LINKED` status; `QUARANTINED` records are excluded. The rounding order is pinned — each record is rounded first, then the integers are summed — and the alternative of summing raw products and rounding once is explicitly rejected. For illustration, two `SITE_VISIT` records of 45 minutes and one `SURVEY` record of 45 minutes bill as 56 plus 56 plus 45, totalling 157; the rejected sum-first order would produce 158. A record whose billed minutes would push the participant's total above the burden ceiling `MAX_TOTAL_BURDEN_MINUTES` of 480 is rejected with `ERR_BURDEN_CAP_EXCEEDED` (HTTP 422); a total landing at exactly 480 is allowed. A created record starts `RECEIVED`, with `linkage_key` still null.

Closing and linking finish a wave. Closing — by a `DataManager`, only from `OPEN` (otherwise `ERR_WAVE_INVALID_STATE`) — moves the wave to `CLOSED` and moves every `RECEIVED` record of the wave to `VALIDATED`. When a wave closes and no other wave of the study remains in `PLANNED`, `OPEN`, or `SUSPENDED` — every other wave having reached `CLOSED`, `LINKED`, or `CANCELLED` — a study still in `DATA_COLLECTION` advances to `ANALYSIS`. Linking — again a `DataManager` action, only from `CLOSED` (otherwise `ERR_WAVE_INVALID_STATE`) — requires that no record of the wave remain in `RECEIVED` (an unresolved record blocks the link with `ERR_RECORDS_UNRESOLVED`) and moves the wave to `LINKED`, at which point every `VALIDATED` record moves to `LINKED` and receives its pseudonymous `linkage_key`; pseudonymization happens at linkage and not before. `LINKED` and `CANCELLED` are the terminal wave states, with `CANCELLED` reachable from `PLANNED`, `OPEN`, or `SUSPENDED` only through the contract-termination cascade. A record's own lifecycle mirrors its wave: `RECEIVED` → `VALIDATED` on wave close, `VALIDATED` → `LINKED` on wave link, and `RECEIVED` or `VALIDATED` → `QUARANTINED` on participant withdrawal or IRB expiry; `LINKED` and `QUARANTINED` are terminal for a record.

### 3.7. Analysis Preregistration and Findings Reports

Before any data is unblinded, the evaluation commits to its analysis. A `PrincipalInvestigator` drafts an **AnalysisPlan** — permitted while the study is anywhere from `DESIGN` through `ANALYSIS`, and rejected at later stages with `ERR_STUDY_INVALID_STATE` — supplying the `primary_outcomes` array of prespecified primary outcome codes and optionally a `secondary_outcomes` array. The plan starts `DRAFT` with `amendment_count` 0 and `registered_at` null.

Preregistration is the point of no return. Registering requires the plan to be `DRAFT` (otherwise `ERR_ANALYSIS_PLAN_INVALID_STATE`), requires the study's current design plan to be `LOCKED` (otherwise `ERR_DESIGN_PLAN_INVALID_STATE`), and — critically — requires that no wave of the study has yet reached `CLOSED` or `LINKED`: preregistration must precede unblinded data, and a late attempt is rejected with `ERR_PREREGISTRATION_TOO_LATE`. Registration moves the plan to `PREREGISTERED`, stamps `registered_at` with the current logical time, and freezes `primary_outcomes`: the set of primary outcomes at registration is version-pinned and can never change afterward. Amendments are still possible for secondary analyses: a `PrincipalInvestigator` amends a `PREREGISTERED` plan — from `DRAFT` the call is rejected with `ERR_ANALYSIS_PLAN_INVALID_STATE` — replacing `secondary_outcomes` wholesale and incrementing `amendment_count` by one, but any payload containing a `primary_outcomes` key is rejected outright with `ERR_PRIMARY_OUTCOME_FROZEN`. Amendment is a self-loop: the plan never leaves `PREREGISTERED`.

Findings reports carry results back to the agency. A `PrincipalInvestigator` drafts a **FindingsReport** while the study is in `ANALYSIS`, `REPORTING`, or `DISSEMINATION` — other stages are rejected with `ERR_STUDY_INVALID_STATE` — supplying a `title`, a `report_type` of `INTERIM` or `FINAL`, the `addressed_primary_outcomes` this report speaks to, and a `payment_milestone_cents` of at least 0 that the contract will disburse on publication. The very first report created under an `ANALYSIS` study advances the study to `REPORTING`. A new report starts `DRAFT` with `revision_count` 0 and `submitted_at`, `accepted_at`, `reviewed_by_id`, `revision_due`, and `publication_due` all null.

Submission puts a report on the clock. A `PrincipalInvestigator` submits from `DRAFT` or resubmits from `REVISION` — any other state is rejected with `ERR_REPORT_INVALID_STATE`. Two integrity gates apply at every submission: the study must hold a `PREREGISTERED` analysis plan (otherwise `ERR_ANALYSIS_PLAN_NOT_REGISTERED`), and the report's `addressed_primary_outcomes` must include every code in that plan's frozen `primary_outcomes` — a report that silently drops a preregistered primary outcome is rejected with `ERR_UNREPORTED_PRIMARY_OUTCOME` (HTTP 422). A resubmission from `REVISION` carries one more gate: the current logical time must be at or before `revision_due`, with submission at exactly the deadline allowed and one second past it rejected with `ERR_REVISION_DEADLINE_MISSED` (HTTP 422). Submission stamps `submitted_at` with the current logical time, records the caller in `submitted_by_id`, and sets `peer_review_due` to `submitted_at` plus `PEER_REVIEW_DAYS` of 45 days — an informational due date that no transition enforces; on a resubmission these fields are recomputed and `revision_due` is cleared.

Peer review then runs under segregation of duties. A `PeerReviewer` reviews a `SUBMITTED` report — any other state is rejected with `ERR_REPORT_INVALID_STATE` — optionally attaching `reviewer_notes`, and the reviewer's `X-User-ID` must differ from the recorded `submitted_by_id`; a self-review is rejected with `ERR_SEGREGATION_OF_DUTIES`. The review records `reviewed_by_id` and moves the report to `PEER_REVIEWED`. The agency then deliberates — conventionally within its informational comment window of `AGENCY_COMMENT_DAYS` of 30 days after peer review, though no transition is gated on it — and an `AgencyOfficer` records a `decision` on the `PEER_REVIEWED` report (other states: `ERR_REPORT_INVALID_STATE`). A `decision` of `ACCEPTED` stamps `accepted_at` and sets `publication_due` to `accepted_at` plus `PUBLICATION_DAYS` of 90 days. A `decision` of `REVISION_REQUIRED` moves the report to `REVISION`, increments `revision_count` by one, and sets `revision_due` to the decision time plus `REVISION_DAYS` of 60 days, starting the revision loop that ends in a resubmission as described above.

### 3.8. Publication, Payment, and Dissemination

Publication is where money moves. An `AgencyOfficer` publishes an `ACCEPTED` report — any other state is rejected with `ERR_REPORT_INVALID_STATE` — subject to two gates evaluated in pipeline order. The deadline gate requires the current logical time to be at or before `publication_due`, with publication at exactly the deadline allowed and anything later rejected with `ERR_PUBLICATION_DEADLINE_MISSED` (HTTP 422). The fiscal gate requires the report's `payment_milestone_cents` to fit within the owning contract's current `remaining_cents`; an overdraw is rejected with `ERR_INSUFFICIENT_CONTRACT_FUNDS` (HTTP 402). On publication the contract's `disbursed_cents` increases by the milestone amount, `remaining_cents` is recomputed under the §3.1 invariant, and the report reaches the terminal `PUBLISHED` state. The first report of a study to reach `PUBLISHED` advances the study from `REPORTING` to `DISSEMINATION`.

With published findings in hand, the evaluation turns to practice. A `PrincipalInvestigator` plans a **DisseminationActivity** — permitted only once the study has at least one `PUBLISHED` report, otherwise `ERR_NO_PUBLISHED_REPORT` — supplying an `activity_type` of `WEBINAR`, `TA_SESSION`, or `BRIEF`, a `title`, a `scheduled_at` logical time, and an `operator_count` of program operators served, which must be at least 1. The activity starts `PLANNED`. Completing it — a `PrincipalInvestigator` action valid only from `PLANNED`, otherwise `ERR_DISSEMINATION_INVALID_STATE` — moves it to `COMPLETED`. Activities in `PLANNED` are also swept to `CANCELLED` by contract termination.

Study completion closes the loop. A study in `DISSEMINATION` moves to `COMPLETED` automatically the moment both of its exit conditions hold: the count of its `PUBLISHED` reports with `report_type` `FINAL` has reached the contract's `deliverable_report_count`, and at least one of its dissemination activities has reached `COMPLETED`. Completing the study cascades downward: every `ACTIVE` site of the study moves to `COMPLETED`, and every participant of those sites still in `CONSENTED` or a randomized status moves to `COMPLETED`. Once every study of a contract is `COMPLETED`, the contract itself becomes eligible for the closeout of §3.1.

### 3.9. Restricted-Use Files and Disclosure Review

Outside researchers get access through **RestrictedUseFile** resources, prepared under quantitative privacy control. A `DataManager` prepares a file for a study — permitted only once the study has at least one `PUBLISHED` report, otherwise `ERR_NO_PUBLISHED_REPORT` — supplying a `title`, a non-empty `cell_counts` array of anonymized cell sizes (each an integer of at least 1), and a parallel `sensitivity_weights` array giving each cell's sensitivity weight as a number greater than 0 and at most 1; the two arrays must have the same length, and schema violations are rejected with `ERR_INVALID_REQUEST`. The preparer's `X-User-ID` is recorded in `prepared_by_id`, and the file starts `DRAFT` with `suppressed_cell_count`, `max_risk`, and `mean_risk` not yet computed.

Submitting the file for review runs the disclosure computation. A `DataManager` submits from `DRAFT` or from `RISK_REJECTED` — any other state is rejected with `ERR_RUF_INVALID_STATE` — moving the file to `DISCLOSURE_REVIEW` and computing the three privacy measures in a pinned evaluation order. First, suppression: every cell whose count is below the k-anonymity floor `K_ANONYMITY_MIN` of 5 is suppressed, and `suppressed_cell_count` records how many cells fell. Second, all denominators are taken over the surviving cells only — suppressed cells never enter any sum. Third, each surviving cell's risk is its `sensitivity_weights` entry divided by its `cell_counts` entry, and `max_risk` is the largest such per-cell risk. Fourth, `mean_risk` is the sum of the surviving cells' sensitivity weights divided by the sum of the surviving cells' counts — a weight-weighted average that is strictly smaller than `max_risk` whenever the surviving cells' risks differ. Both risk scores are expressed to 4 decimal places with round-half-up rounding, and if no cells survive suppression, both fall back to 1.0. For illustration, with `cell_counts` of 5, 4, 12, and 30 against weights of 1.0, 1.0, 0.5, and 0.5, the cell of count 4 is suppressed; the survivors' worst cell yields a `max_risk` of 0.20 — exactly at the release gate, so it passes — while `mean_risk` computes to 0.0426.

The release decision belongs to the agency, under segregation of duties. An `AgencyOfficer` records a `decision` on a file in `DISCLOSURE_REVIEW` — any other state is rejected with `ERR_RUF_INVALID_STATE` — and the decider's `X-User-ID` must differ from `prepared_by_id`, else `ERR_SEGREGATION_OF_DUTIES`. A `decision` of `APPROVE` releases the file only through the risk gate: `max_risk` must be at most `MAX_DISCLOSURE_RISK` of 0.20, with a value of exactly 0.20 passing and anything above rejected with `ERR_DISCLOSURE_RISK_TOO_HIGH` (HTTP 422); a passing approval moves the file to the terminal `RELEASED` state. A `decision` of `REJECT` moves the file to `RISK_REJECTED`, from which the `DataManager` may revise the cell structure and submit it for review again. Visibility follows release: staff roles list all of a study's restricted-use files, while an `ExternalResearcher` listing the same collection sees only `RELEASED` files.

## 4. Endpoint Definitions

Operations that create a new resource — awarding a contract, adding a study, plan, protocol, site, participant, wave, record, analysis plan, report, restricted-use file, or dissemination activity — return `201 Created` with the new resource in `data`. Operations that transition or otherwise modify an existing resource, and all reads, return `200 OK`. The table below is a summary only: request payloads, response shapes, and side effects are specified by the workflow narratives of §3 and the principles of §2, not by this table.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/evaluation/contracts` | Award a new evaluation contract (starts `ACTIVE`) | AgencyOfficer |
| GET | `/evaluation/contracts/{contractId}` | Get one contract | AgencyOfficer, PrincipalInvestigator, StudyDirector, DataManager, IRBReviewer, PeerReviewer |
| POST | `/evaluation/contracts/{contractId}/terminate` | Terminate a contract; cascades through studies, sites, participants, waves, reports, activities | AgencyOfficer |
| POST | `/evaluation/contracts/{contractId}/closeout` | Close a contract once every study is `COMPLETED` | AgencyOfficer |
| POST | `/evaluation/contracts/{id}/studies` | Create a study under a contract (starts `DESIGN`) | PrincipalInvestigator |
| GET | `/evaluation/contracts/{id}/studies` | List studies of a contract | AgencyOfficer, PrincipalInvestigator, StudyDirector, DataManager, IRBReviewer, PeerReviewer |
| GET | `/evaluation/studies/{studyId}` | Get one study (projections, adequacy, counters) | AgencyOfficer, PrincipalInvestigator, StudyDirector, DataManager, IRBReviewer, PeerReviewer |
| POST | `/evaluation/studies/{id}/design-plans` | Create a design plan revision (OCC-guarded; supersedes the current `DRAFT` or `RETURNED_FOR_REVISION` plan) | PrincipalInvestigator |
| GET | `/evaluation/studies/{id}/design-plans` | List design plans of a study | AgencyOfficer, PrincipalInvestigator, StudyDirector, DataManager, IRBReviewer, PeerReviewer |
| POST | `/evaluation/design-plans/{planId}/submit` | Submit a `DRAFT` plan to the agency (feasibility gate) | PrincipalInvestigator |
| POST | `/evaluation/design-plans/{planId}/agency-decision` | Agency approves or returns a submitted plan | AgencyOfficer |
| POST | `/evaluation/design-plans/{planId}/revise` | Reopen a `RETURNED_FOR_REVISION` plan as `DRAFT` | PrincipalInvestigator |
| POST | `/evaluation/studies/{id}/irb-protocols` | Create an IRB protocol draft | PrincipalInvestigator |
| GET | `/evaluation/studies/{id}/irb-protocols` | List IRB protocols of a study | AgencyOfficer, PrincipalInvestigator, StudyDirector, DataManager, IRBReviewer, PeerReviewer |
| POST | `/evaluation/irb-protocols/{irbId}/submit` | Submit (or resubmit) a protocol to the IRB | PrincipalInvestigator |
| POST | `/evaluation/irb-protocols/{irbId}/decision` | IRB decision; approval pins the half-open approval window | IRBReviewer |
| POST | `/evaluation/irb-protocols/{irbId}/continuing-review` | Extend the `approval_end` of an `APPROVED` protocol | IRBReviewer |
| POST | `/evaluation/studies/{id}/sites` | Add a recruitment site (starts `PROSPECTED`) | StudyDirector |
| GET | `/evaluation/studies/{id}/sites` | List sites of a study | AgencyOfficer, PrincipalInvestigator, StudyDirector, DataManager, IRBReviewer, PeerReviewer |
| POST | `/evaluation/sites/{siteId}/outreach` | Record an outreach outcome (`CONTACTED` advances, `DECLINED` terminates) | StudyDirector |
| POST | `/evaluation/sites/{siteId}/sign-mou` | Sign the site MOU; may lock the approved design plan | StudyDirector |
| POST | `/evaluation/sites/{siteId}/activate` | Activate a recruited site (requires unexpired IRB approval and a `LOCKED` plan) | StudyDirector |
| POST | `/evaluation/sites/{siteId}/withdraw` | Withdraw a site; cascades to participants and their records | StudyDirector |
| POST | `/evaluation/sites/{siteId}/participants` | Identify a prospective participant at a site (starts `IDENTIFIED`) | StudyDirector |
| GET | `/evaluation/participants` | List participants, optionally filtered by `site_id` and `status` | AgencyOfficer, PrincipalInvestigator, StudyDirector, DataManager, IRBReviewer, PeerReviewer |
| GET | `/evaluation/participants/{participantId}` | Get one participant; the `Participant` role reads only its own record | AgencyOfficer, PrincipalInvestigator, StudyDirector, DataManager, IRBReviewer, PeerReviewer, Participant |
| POST | `/evaluation/participants/{participantId}/consent` | Participant self-consents against the current approved consent form version | Participant |
| POST | `/evaluation/participants/{participantId}/randomize` | Deterministic arm allocation by per-site counter and the locked plan's ratio | PrincipalInvestigator |
| POST | `/evaluation/participants/{participantId}/withdraw` | Withdraw a participant; quarantines their unresolved records | Participant, StudyDirector |
| POST | `/evaluation/studies/{id}/waves` | Plan a data collection wave; site visits carry `site_id` and obey the spacing rule | DataManager |
| GET | `/evaluation/studies/{id}/waves` | List waves of a study | AgencyOfficer, PrincipalInvestigator, StudyDirector, DataManager, IRBReviewer, PeerReviewer |
| GET | `/evaluation/waves` | List waves across studies, filterable by `site_id`, `study_id`, `wave_type`, `status` | AgencyOfficer, PrincipalInvestigator, StudyDirector, DataManager, IRBReviewer, PeerReviewer |
| GET | `/evaluation/waves/{waveId}` | Get one wave | AgencyOfficer, PrincipalInvestigator, StudyDirector, DataManager, IRBReviewer, PeerReviewer |
| POST | `/evaluation/waves/{waveId}/open` | Open a planned or suspended wave inside its window (requires unexpired IRB approval) | DataManager |
| POST | `/evaluation/waves/{waveId}/close` | Close an open wave; validates its received records | DataManager |
| POST | `/evaluation/waves/{waveId}/link` | Link a closed wave; assigns pseudonymous linkage keys | DataManager |
| POST | `/evaluation/waves/{id}/records` | Add a collected record to an `OPEN` wave (burden-cap checked) | DataManager |
| GET | `/evaluation/waves/{id}/records` | List records of a wave | AgencyOfficer, PrincipalInvestigator, StudyDirector, DataManager, IRBReviewer, PeerReviewer |
| GET | `/evaluation/participants/{id}/records` | List records of a participant | AgencyOfficer, PrincipalInvestigator, StudyDirector, DataManager, IRBReviewer, PeerReviewer |
| POST | `/evaluation/studies/{id}/analysis-plans` | Draft an analysis plan with prespecified outcomes | PrincipalInvestigator |
| GET | `/evaluation/studies/{id}/analysis-plans` | List analysis plans of a study | AgencyOfficer, PrincipalInvestigator, StudyDirector, DataManager, IRBReviewer, PeerReviewer |
| POST | `/evaluation/analysis-plans/{planId}/register` | Preregister the plan; freezes primary outcomes | PrincipalInvestigator |
| POST | `/evaluation/analysis-plans/{planId}/amend` | Amend secondary outcomes post-registration | PrincipalInvestigator |
| POST | `/evaluation/studies/{id}/reports` | Draft a findings report (first creation advances the study) | PrincipalInvestigator |
| GET | `/evaluation/studies/{id}/reports` | List reports of a study | AgencyOfficer, PrincipalInvestigator, StudyDirector, DataManager, IRBReviewer, PeerReviewer |
| POST | `/evaluation/reports/{reportId}/submit` | Submit (or resubmit after revision) a report to the agency | PrincipalInvestigator |
| POST | `/evaluation/reports/{reportId}/review` | Peer review a submitted report (reviewer must not be the submitter) | PeerReviewer |
| POST | `/evaluation/reports/{reportId}/agency-decision` | Agency accepts the report or returns it for revision | AgencyOfficer |
| POST | `/evaluation/reports/{reportId}/publish` | Publish an accepted report within its deadline; disburses the milestone | AgencyOfficer |
| POST | `/evaluation/studies/{id}/restricted-use-files` | Prepare a restricted-use data file (requires a `PUBLISHED` report) | DataManager |
| GET | `/evaluation/studies/{id}/restricted-use-files` | List a study's restricted-use files (`ExternalResearcher` sees `RELEASED` only) | AgencyOfficer, PrincipalInvestigator, StudyDirector, DataManager, IRBReviewer, PeerReviewer, ExternalResearcher |
| POST | `/evaluation/restricted-use-files/{fileId}/submit-review` | Submit a file for disclosure-risk review (computes suppression and risk) | DataManager |
| POST | `/evaluation/restricted-use-files/{fileId}/review-decision` | Agency disclosure decision (decider must not be the preparer) | AgencyOfficer |
| POST | `/evaluation/studies/{id}/dissemination-activities` | Plan a dissemination or technical-assistance activity (requires a `PUBLISHED` report) | PrincipalInvestigator |
| GET | `/evaluation/studies/{id}/dissemination-activities` | List dissemination activities of a study | AgencyOfficer, PrincipalInvestigator, StudyDirector, DataManager, IRBReviewer, PeerReviewer |
| POST | `/evaluation/dissemination-activities/{activityId}/complete` | Mark an activity completed; may complete the study | PrincipalInvestigator |
| POST | `/_clock/set_current_utc` | Set the server logical clock (platform-level; outside the `/evaluation` prefix); evaluates IRB expiry | PlatformAdmin |

## 5. Error Code Catalogue

The table below enumerates every error identifier the API can return and its HTTP status. The conditions that trigger each error are specified in the narratives of §2 and §3, not here.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_CONTRACT_NOT_ACTIVE` | 409 Conflict |
| `ERR_STUDY_INVALID_STATE` | 409 Conflict |
| `ERR_DESIGN_PLAN_INVALID_STATE` | 409 Conflict |
| `ERR_IRB_INVALID_STATE` | 409 Conflict |
| `ERR_SITE_INVALID_STATE` | 409 Conflict |
| `ERR_PARTICIPANT_INVALID_STATE` | 409 Conflict |
| `ERR_WAVE_INVALID_STATE` | 409 Conflict |
| `ERR_ANALYSIS_PLAN_INVALID_STATE` | 409 Conflict |
| `ERR_REPORT_INVALID_STATE` | 409 Conflict |
| `ERR_RUF_INVALID_STATE` | 409 Conflict |
| `ERR_DISSEMINATION_INVALID_STATE` | 409 Conflict |
| `ERR_INSUFFICIENT_POWER` | 422 Unprocessable Entity |
| `ERR_NO_APPROVED_IRB` | 409 Conflict |
| `ERR_IRB_EXPIRED` | 409 Conflict |
| `ERR_IRB_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_CONSENT_VERSION_STALE` | 409 Conflict |
| `ERR_SITE_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_BURDEN_CAP_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_VISIT_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_PREREGISTRATION_TOO_LATE` | 409 Conflict |
| `ERR_PRIMARY_OUTCOME_FROZEN` | 409 Conflict |
| `ERR_UNREPORTED_PRIMARY_OUTCOME` | 422 Unprocessable Entity |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_REVISION_DEADLINE_MISSED` | 422 Unprocessable Entity |
| `ERR_PUBLICATION_DEADLINE_MISSED` | 422 Unprocessable Entity |
| `ERR_DISCLOSURE_RISK_TOO_HIGH` | 422 Unprocessable Entity |
| `ERR_NO_PUBLISHED_REPORT` | 409 Conflict |
| `ERR_STUDIES_NOT_COMPLETED` | 409 Conflict |
| `ERR_PARTICIPANT_NOT_CONSENTED` | 409 Conflict |
| `ERR_WAVE_NOT_OPEN` | 409 Conflict |
| `ERR_RECORDS_UNRESOLVED` | 409 Conflict |
| `ERR_WAVE_WINDOW_NOT_STARTED` | 409 Conflict |
| `ERR_ANALYSIS_PLAN_NOT_REGISTERED` | 409 Conflict |
| `ERR_INSUFFICIENT_CONTRACT_FUNDS` | 402 Payment Required |
