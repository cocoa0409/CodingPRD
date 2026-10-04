# Independent Practice Affiliation API — Product Requirements Document

## 1. Introduction

Independent physician practices increasingly face an economic choice: sell assets to a consolidator and lose autonomy, or affiliate with a single medical group that lets them keep ownership of their practice while gaining access to centralized payer contracting, technology, and revenue-cycle operations. This document describes the API for the affiliation platform that supports the second model — practice affiliation without asset acquisition, in the style of physician-enablement groups that unify independent practices under one legal medical group entity and one federal tax identification number.

Under this model, every affiliated practice bills under the group's single TIN and benefits from centrally negotiated payer contracts and fee-schedule improvements. Practice-level economics are preserved through a distribution model that returns each practice's collections net of the group's shared-services fee, with a hold-and-carry-forward threshold that smooths small payouts across periods. Technology and revenue-cycle standardization is phased in through market-scoped implementation waves with explicit cutover windows; a practice's affiliation becomes effective only when its assigned wave completes. Provider credentialing and payer enrollment run under the group with pinned lag-day rules, governance runs through physician-led market committees that ratify payer contracts, and departure terms — including notice periods, early-exit penalties, and a non-compete — are computed and settled when a practice leaves. Value-based incentive pools distribute shared-savings dollars across affiliated practices on a weighted, quality-gated basis.

The API is role-partitioned across nine operator roles and enforces segregation of duties between those who post revenue, those who finalize distributions, those who open governance motions, and those who vote on them. A server-side logical clock governs all date-dependent behavior so that cutover windows, credentialing lags, departure notice periods, and contract effective dates are deterministic and testable.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two authentication headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the operational capacity in which that user acts. A request missing either header, or presenting a malformed value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). Beyond authentication, each endpoint restricts the set of roles permitted to invoke it; a caller whose `X-User-Role` is not in the permitted set for that endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

The system recognizes exactly nine roles, with these exact spellings: `GroupAdministrator`, `PayerContractingOfficer`, `CredentialingCoordinator`, `PracticeExecutive`, `DistributionAccountant`, `GroupFinancialController`, `MarketCommitteeChair`, `PhysicianBoardMember`, and `ComplianceOfficer`.

Identity binding differs by role. When `X-User-Role` is `PracticeExecutive`, `X-User-ID` is the `id` of the acting `Practice`; ownership checks on any resource that references a `Practice` compare the resource's foreign-key field (for example `practice_id` on an affiliation agreement, departure case, or incentive allocation) to `X-User-ID`, and a mismatch is rejected with `ERR_PRACTICE_OWNERSHIP_MISMATCH` (HTTP 403). When `X-User-Role` is `MarketCommitteeChair` or `PhysicianBoardMember`, `X-User-ID` is the `id` of the acting `Provider`; for a ballot cast by a `PhysicianBoardMember`, the server compares `X-User-ID` against the provider population snapshotted as eligible for the vote, and a non-eligible caster is rejected with `ERR_INSUFFICIENT_PERMISSIONS`. For all remaining roles — `GroupAdministrator`, `PayerContractingOfficer`, `CredentialingCoordinator`, `DistributionAccountant`, `GroupFinancialController`, and `ComplianceOfficer` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `settled_by_user_id` on a `CollectionBatch` or `finalized_by_user_id` on a `DistributionStatement`) but does not compare it to any entity's `id`.

Segregation of duties is structural, not advisory. A `DistributionAccountant` posts, settles, and adjusts collection batches and drafts distribution statements but may never finalize a statement; a `GroupFinancialController` finalizes, amends, and reissues statements and runs incentive allocation and payment but may never post or settle a batch. Statement finalization additionally requires that the finalizer's `X-User-ID` differ from the `settled_by_user_id` of every batch covered by the statement, and a violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). A `MarketCommitteeChair` opens governance motions but never votes; a `PhysicianBoardMember` votes but never opens motions. Contract termination and departure review/settlement belong to the `ComplianceOfficer`, who shares the enrollment-termination capability with the `CredentialingCoordinator`.

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

List endpoints accept two query parameters. The `limit` parameter sets the maximum number of items returned: it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items skipped and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by their `created_at` timestamp in ascending order. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. Common Resource Properties

Every primary resource in the system — `MedicalGroup`, `Market`, `Practice`, `Provider`, `AffiliationAgreement`, `ImplementationWave`, `PayerContract`, `FeeScheduleRate`, `CredentialingEnrollment`, `CollectionBatch`, `DistributionStatement`, `ValueBasedIncentivePool`, `IncentiveAllocation`, `DepartureCase`, and `CommitteeVote` — carries a standard set of system-managed fields:

- `id` (string): a unique, server-generated identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp updated on every mutation of the resource.
- `version` (integer): a system-managed integer that increments by one on every mutation; it anchors optimistic concurrency control.

Any mutation of an entity — including mutations driven by cascades from another entity's state transition, such as a practice flipping to `AFFILIATED` when its wave completes — updates that entity's `updated_at` and increments its `version`.

State-bearing entities additionally expose a `status` field carrying the entity's current state as one of the exact UPPERCASE enumeration strings used throughout §3 (for example `FORMING`, `PROSPECT`, `DRAFT`, `PLANNED`, `NEGOTIATION`, `PROPOSED`, `SUBMITTED`, `POSTED`, `PROVISIONAL_ISSUED`, `OPEN`, `ENTERED`, `UNDER_REVIEW`, `ROSTERED`).

### 2.5. The Logical Clock

The server maintains a logical clock that governs every date-dependent rule in the system: credentialing lag windows, wave cutover windows, contract effective dates, departure notice periods, and the application date stamped onto new enrollments and departure cases. Before any call to set it, the logical clock reads exactly `2026-09-01T00:00:00Z`; it never falls back to wall-clock time. Dates consumed by date-granularity rules are the UTC calendar date of the logical clock. A `GroupAdministrator` may advance or set the logical clock through an admin-only test-driving capability that accepts a `to_iso8601` instant and applies it with no entity mutation.

### 2.6. Monetary Values, Rates, and Precision

All monetary amounts in the system are carried as integer cents; there are no fractional-cent values anywhere in the API. Where a calculation produces a fractional cent — the per-batch shared-services fee is the principal example — the value is rounded half-up to a whole cent at the pinned step of the algorithm before any summation. Rates such as `shared_services_tier1_rate`, `shared_services_tier2_rate`, and `shared_services_rate_override` are decimal multipliers applied to cent amounts. The fee-schedule uplift percentage `uplift_pct` and the activation-gate average are expressed to exactly 4 decimal places, rounded half-up. Incentive allocation `weight` values are expressed to exactly 6 decimal places, rounded half-up, while `share_cents` values are integer cents produced by a floor followed by a one-cent-at-a-time remainder waterfall. Tenure for departure purposes is measured in whole calendar months.

### 2.7. Optimistic Concurrency Control

Three write endpoints require the caller to present the version it last observed on a parent entity, and reject the write when the parent's version has since advanced. Endpoints not listed here take no version field.

- Drafting an affiliation agreement requires the request to carry `expected_practice_version` matching the target practice's current `version`. A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). This captures the case where another writer has just executed an agreement for the practice — legitimately moving it to `ONBOARDING` and superseding the prior agreement — and the current writer's view of the practice is stale.
- Locking an implementation wave requires `expected_wave_version` matching the wave's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), because the client's picture of the cutover window is stale. A successful lock itself increments the wave's `version` by one.
- Amending a distribution statement requires `expected_statement_version` matching the statement's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), because the client would otherwise be amending figures computed from a superseded batch state. Each successful amendment increments the statement's `version` by one.

### 2.8. Hierarchical Consistency and Cascades

The system maintains strict integrity across entity boundaries. When a parent entity undergoes a state transition that resolves or invalidates dependent work, the server cascades the transition to dependent entities automatically, without requiring an explicit client request on each one. The principal cascades are: wave completion flipping the wave's `ONBOARDING` practices to `AFFILIATED`, which in turn flips those practices' `APPROVED` credentialing enrollments to `EFFECTIVE`, which in turn flips each newly effective provider from `ROSTERED` to `ACTIVE` and recomputes the practice's `active_provider_count`; practice departure settlement flipping the practice to `DEPARTED`, deactivating its providers, terminating its open enrollments, terminating its executed agreement, and zeroing its `active_provider_count`; and payer-contract termination cascading termination onto every non-terminal enrollment written against that contract. Each entity mutated by a cascade updates its own `updated_at` and increments its own `version`.

### 2.9. Validation Order and Nested Retrieval

Validation on any request proceeds in a fixed priority order. First, the authentication headers are checked (§2.1). Second, the caller's role is checked against the endpoint's permitted set. Third, identity binding is enforced — practice ownership for `PracticeExecutive` calls and segregation of duties on statement finalization. Fourth, request shape: every required input field must be present, types must match, enum values must lie in their declared sets, amounts must be positive where required, periods must match the `YYYY-MM` format, and dates must match ISO `YYYY-MM-DD`; violations are rejected with `ERR_INVALID_REQUEST` (HTTP 400). Fifth, existence: identifiers in the URL path are resolved left to right, and then foreign keys in the request body in the order they are declared for that endpoint, each failure producing the resource-specific not-found error: `ERR_MEDICAL_GROUP_NOT_FOUND` for a medical group, `ERR_MARKET_NOT_FOUND` for a market, `ERR_PRACTICE_NOT_FOUND` for a practice, `ERR_PROVIDER_NOT_FOUND` for a provider, `ERR_AGREEMENT_NOT_FOUND` for an affiliation agreement, `ERR_WAVE_NOT_FOUND` for an implementation wave, `ERR_PAYER_CONTRACT_NOT_FOUND` for a payer contract, `ERR_RATE_NOT_FOUND` for a fee schedule rate, `ERR_ENROLLMENT_NOT_FOUND` for a credentialing enrollment, `ERR_BATCH_NOT_FOUND` for a collection batch, `ERR_STATEMENT_NOT_FOUND` for a distribution statement, `ERR_POOL_NOT_FOUND` for an incentive pool, `ERR_ALLOCATION_NOT_FOUND` for an incentive allocation, `ERR_DEPARTURE_CASE_NOT_FOUND` for a departure case, and `ERR_VOTE_NOT_FOUND` for a committee vote. Sixth, optimistic concurrency (§2.7). Seventh, state-machine preconditions and cross-entity state gates. Eighth, compliance acknowledgements. Ninth, temporal and interval sanity. Tenth, uniqueness, capacity, and window-overlap constraints. Eleventh, cross-linkage requirements such as effective-enrollment prerequisites. Twelfth, fiscal gates such as the settled-batch requirement on statement finalization. Because this order is fixed, an earlier failure always masks a later one — for example, a missing header surfaces as `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` even when the request would also have failed a state check.

### 2.10. Periods, Windows, and Intervals

Statement and pool periods use the `YYYY-MM` format. Wave cutover windows are half-open intervals: the start date is inclusive and the end date is exclusive, so one wave's `cutover_end_date` may coincide with another wave's `cutover_start_date` in the same market without overlap. Credentialing enrollment windows, by contrast, are closed intervals over `[effective_date, termination_date]`: the termination day itself is occupied, and the next day is free.

## 3. Business Logic & Workflows

### 3.1. Forming the Group and Its Markets

A `GroupAdministrator` begins by creating the `MedicalGroup`, supplying its `tin` — the single federal tax identification number under which every affiliated practice will bill, unique across groups — and a `display_name`. At creation the group also accepts its economic and departure-terms parameters, each with a default: `shared_services_tier1_rate` (default 0.07), `shared_services_tier1_cap_cents` (default 50000000), `shared_services_tier2_rate` (default 0.05), `distribution_hold_threshold_cents` (default 5000), `departure_notice_days` (default 180), `non_compete_term_months` (default 24), `early_exit_base_penalty_cents` (default 2500000), `early_exit_per_month_cents` (default 250000), and `insufficient_notice_penalty_cents` (default 500000). A new group starts in `FORMING` status. Activation moves the group from `FORMING` to `OPERATING`; attempting it on a group in any other state is rejected with `ERR_INVALID_TRANSITION`. Payer-contract negotiation requires an `OPERATING` group — opening a contract while the group is still `FORMING` is rejected with `ERR_GROUP_NOT_OPERATING`.

Within a group, the `GroupAdministrator` carves out markets. A `Market` is created with its `medical_group_id`, a `name`, a two-letter `state_code`, a `max_practices` capacity cap, and an optional `market_weight` (default 1.0) that later feeds incentive-allocation scoring. Market capacity is enforced at practice-creation time: the count of the market's practices whose status is `ONBOARDING`, `AFFILIATED`, `SUSPENDED`, or `DEPARTING` must stay at or below `max_practices`, so creation is rejected with `ERR_MARKET_AT_CAPACITY` exactly when the occupied count already equals `max_practices`. A practice in `PROSPECT` or `DEPARTED` status does not consume capacity.

### 3.2. Recruiting a Practice: Agreement, Wave, and Affiliation

A prospective practice enters the system when a `GroupAdministrator` creates a `Practice` with its `medical_group_id`, `market_id`, `legal_name`, the practice's pre-affiliation `legacy_tin` (retained for records only, since billing moves to the group TIN), and its organizational `org_npi`, which must be unique. The practice is born in `PROSPECT` status. Its `wave_id` starts null and is never client-supplied, and its `affiliation_effective_date`, `departure_effective_date`, and computed `active_provider_count` are system-managed.

Affiliation is contractual. A `PracticeExecutive` — whose `X-User-ID` must equal the practice's `id`, else `ERR_PRACTICE_OWNERSHIP_MISMATCH` — drafts an `AffiliationAgreement` for their own practice, supplying `practice_id`, the `distribution_model` (only `NET_OF_SHARED_SERVICES` is supported), and a `non_compete_accepted` acknowledgement that must be true: the group's non-compete and departure terms are a condition of affiliation, and a draft submitted without the acknowledgement is rejected with `ERR_NON_COMPETE_ACK_REQUIRED`. An optional `shared_services_rate_override` may replace the group's tiered fee schedule with one flat rate for this practice; when absent it is null. Because drafting mutates the practice — each new draft increments the practice's `version` by one — the draft request must carry `expected_practice_version` per §2.7. A new agreement starts in `DRAFT` and receives a per-practice monotonically increasing `agreement_seq` beginning at 1.

Execution is the pivotal act. Executing a `DRAFT` agreement requires the practice to be in `PROSPECT` or `AFFILIATED` status; otherwise the call fails with `ERR_INVALID_TRANSITION`. Two side effects follow. First, any other `EXECUTED` agreement of the same practice moves to `SUPERSEDED` — supersession is the CREATE-with-supersede pattern that lets a practice re-paper its terms while already affiliated. Second, when the practice is `PROSPECT`, execution moves it to `ONBOARDING` and assigns its `wave_id` via a selector: among implementation waves whose market matches the practice's market and whose status is `IN_CUTOVER`, the server picks the one with the lowest `cutover_start_date`, breaking ties by earliest `created_at`. If no wave in the practice's market is currently `IN_CUTOVER`, the execution fails with `ERR_NO_WAVE_IN_CUTOVER` and the practice remains `PROSPECT`. When the practice is already `AFFILIATED` (a re-papering), no wave assignment occurs and the practice simply stays `AFFILIATED` with the new agreement in force.

### 3.3. Implementation Waves and the Affiliation Cascade

Technology and revenue-cycle standardization roll out in waves. A `GroupAdministrator` plans an `ImplementationWave` for a market by supplying `market_id`, a human `wave_code` unique within the market, and the half-open cutover window bounded by `cutover_start_date` (inclusive) and `cutover_end_date` (exclusive). The end date must be strictly after the start date, or creation fails with `ERR_INVALID_CUTOVER_WINDOW`. Within one market, cutover windows of waves not yet `COMPLETE` must not overlap under half-open semantics — a shared boundary instant is permitted — and an overlapping plan is rejected with `ERR_WAVE_WINDOW_OVERLAP`. A new wave starts `PLANNED`.

The wave lifecycle is a small cycle. Locking moves a `PLANNED` wave to `LOCKED` and requires `expected_wave_version` per §2.7; locking a wave in any other state is `ERR_INVALID_TRANSITION`. Starting cutover moves a `LOCKED` wave to `IN_CUTOVER` and requires the logical clock date to be at least `cutover_start_date`; an early start is rejected with `ERR_INVALID_CUTOVER_WINDOW`. Completing the wave moves it from `IN_CUTOVER` to the terminal `COMPLETE` state and requires the logical clock date to be strictly before `cutover_end_date`, again failing with `ERR_INVALID_CUTOVER_WINDOW` when the window has closed. A wave in `IN_CUTOVER` may instead be rolled back to `LOCKED`; practices already assigned to the wave keep their `wave_id` and remain `ONBOARDING`.

Completion fires the affiliation cascade. Every practice whose `wave_id` equals the completing wave and whose status is `ONBOARDING` moves to `AFFILIATED`, with `affiliation_effective_date` stamped as the logical clock date. Each such practice then cascades hop two: every `CredentialingEnrollment` of the practice's providers that sits in `APPROVED` flips to `EFFECTIVE`. Each enrollment flipped to `EFFECTIVE` cascades hop three: its provider flips from `ROSTERED` to `ACTIVE`, and the practice's `active_provider_count` — the count of the practice's providers in `ACTIVE` status — is recomputed.

### 3.4. Rostering Providers and Credentialing Them Under the Group TIN

A `GroupAdministrator` rosters a `Provider` into a practice with `practice_id`, an individual `npi` (unique), `full_name`, free-text `specialty`, a `provider_role` of `PHYSICIAN` or `APP`, and an `employment_start_date` that later feeds credentialing effective-date sequencing. The host practice must be `PROSPECT`, `ONBOARDING`, or `AFFILIATED`; rostering into a practice in any other state is `ERR_INVALID_TRANSITION`. A new provider starts `ROSTERED`. A provider becomes `ACTIVE` the moment the first of its credentialing enrollments reaches `EFFECTIVE`, and becomes `DEACTIVATED` only through the departure cascade; both transitions recompute the practice's `active_provider_count`.

Enrollment under the group's contracts is the credentialing team's daily work. A `CredentialingCoordinator` submits a `CredentialingEnrollment` with `provider_id`, `payer_contract_id`, a `channel` of `STANDARD` or `EXPEDITED`, and a `requested_effective_date`. The contract must be `ACTIVE` (else `ERR_CONTRACT_NOT_ACTIVE`) and the provider's practice must be `ONBOARDING` or `AFFILIATED` (else `ERR_INVALID_TRANSITION`). At submission the server stamps `application_date` from the logical clock date, and the enrollment enters `SUBMITTED`. The requested effective date must be on or after the `application_date`, and for the `EXPEDITED` channel it must additionally fall within 45 days of the `application_date` — a longer span is rejected with `ERR_EXPEDITED_WINDOW_EXCEEDED`, while other shape violations are `ERR_INVALID_REQUEST`.

Approval computes the enrollment's `effective_date` with a pinned evaluation order: first the channel lag — 90 days for `STANDARD`, 30 days for `EXPEDITED` — is added to the `application_date` to produce a lag date; then the effective date is the later of that lag date and the provider's `employment_start_date`. The result is always on or after the `application_date` by construction. The landing state of an approval depends on where the provider's practice stands: while the practice is `ONBOARDING`, approval moves the enrollment from `SUBMITTED` to `APPROVED` (a staging state awaiting affiliation); while the practice is `AFFILIATED`, approval moves it directly from `SUBMITTED` to `EFFECTIVE`, flipping the provider `ROSTERED` to `ACTIVE` and recomputing `active_provider_count`. Approving an enrollment in any other starting state is `ERR_INVALID_TRANSITION`. Approval also enforces window exclusivity: the closed interval from the new enrollment's `effective_date` through its `termination_date` must not overlap any other non-`TERMINATED` enrollment for the same provider and contract — under closed-interval semantics the termination day itself is occupied and the next day is free — and an overlap is rejected with `ERR_ENROLLMENT_WINDOW_OVERLAP`.

Termination closes an enrollment from any non-terminal state (`SUBMITTED`, `APPROVED`, or `EFFECTIVE`). A manual termination by a `CredentialingCoordinator` or `ComplianceOfficer` accepts an explicit `termination_date` in the request. Cascade-driven terminations stamp `termination_date` from the logical clock date instead. Note that when an `EFFECTIVE` enrollment terminates, any provider deactivation that should follow — because the provider has no remaining `EFFECTIVE` enrollment anywhere and the practice is `DEPARTING` or `DEPARTED` — is handled by the departure cascade, not by the enrollment termination itself.

### 3.5. Payer Contracting and Physician Governance

A `PayerContractingOfficer` opens a `PayerContract` under the group's single TIN with `medical_group_id`, `payer_name`, a `contract_type` of `FEE_FOR_SERVICE`, `VALUE_BASED`, or `HYBRID`, and an `effective_date`. The contract starts in `NEGOTIATION`, and its `ratifying_vote_id` stays null until activation. The contract's `value_based_pool_eligible` flag is computed: true exactly when `contract_type` is `VALUE_BASED` or `HYBRID`.

Fee schedules are negotiated code by code. For a contract still in `NEGOTIATION`, the officer proposes a `FeeScheduleRate` with `payer_contract_id`, `cpt_code`, the practices' pre-affiliation benchmark `legacy_rate_cents`, and the negotiated `group_rate_cents`. The server computes `uplift_pct` as the difference between `group_rate_cents` and `legacy_rate_cents`, divided by `legacy_rate_cents`, expressed to 4 decimal places with round-half-up. A new rate starts `PROPOSED`, and proposing a rate for a contract-and-code pair that already has a `PROPOSED` rate supersedes the older one to `SUPERSEDED`.

Physician governance ratifies contracts. A `MarketCommitteeChair` opens a `CommitteeVote` in a market with `market_id`, a `motion_type` of `PAYER_CONTRACT_RATIFICATION` or `FEE_SCHEDULE_ADOPTION`, and the `subject_contract_id` the motion concerns. At creation the server snapshots `eligible_voter_count`: the count of providers with `provider_role` `PHYSICIAN` whose status is anything other than `DEACTIVATED` and whose practice sits in this market with status `ONBOARDING` or `AFFILIATED`. A vote that would snapshot zero eligible voters is rejected with `ERR_NO_ELIGIBLE_VOTERS`. A new vote is `OPEN` with `votes_for` and `votes_against` at zero and an empty `voted_provider_ids` roster.

A `PhysicianBoardMember` casts a ballot by submitting a `ballot` value of `FOR` or `AGAINST` (any other value is `ERR_INVALID_REQUEST`). The caller must be an eligible voter of the vote's market per the snapshot definition — their `X-User-ID` is their provider `id` — and an ineligible caster is rejected with `ERR_INSUFFICIENT_PERMISSIONS`. Each provider casts at most one ballot per vote; a second attempt is `ERR_DUPLICATE_VOTE`. Each cast updates `votes_for` or `votes_against` and records the caller's provider id in `voted_provider_ids`. The vote auto-closes on majority rules: a ballot that pushes `votes_for` strictly above half of `eligible_voter_count` — that is, above the floor of `eligible_voter_count` divided by two — closes the vote `PASSED`; a ballot that pushes `votes_against` above that same floor closes it `REJECTED`, as does the exhaustion of all eligible voters without `votes_for` ever exceeding half.

Contract activation is the payoff. Activating a contract moves it from `NEGOTIATION` to `ACTIVE` and is gated, in evaluation order, by four conditions: the contract must be in `NEGOTIATION` (else `ERR_INVALID_TRANSITION`); a `PASSED` `CommitteeVote` with `motion_type` `PAYER_CONTRACT_RATIFICATION` on this contract must exist (else `ERR_NO_PASSED_RATIFICATION_VOTE`); the logical clock date must be at least the contract's `effective_date` (else `ERR_INVALID_CUTOVER_WINDOW`); and, when `contract_type` is `FEE_FOR_SERVICE` or `HYBRID`, at least one `PROPOSED` fee-schedule rate must exist and the average uplift across those rates — each rate's `uplift_pct` summed and divided by the count of `PROPOSED` rates, to 4 decimal places round-half-up — must be at least 0.08 inclusive (else `ERR_FEE_SCHEDULE_UPLIFT_INSUFFICIENT`; zero `PROPOSED` rates fails the same gate). On activation the server records the passing vote's id in `ratifying_vote_id` and flips every `PROPOSED` rate of the contract to `ACTIVE`. Termination by a `ComplianceOfficer` moves an `ACTIVE` contract to `TERMINATED` and cascades: every enrollment written against the contract in `SUBMITTED`, `APPROVED`, or `EFFECTIVE` status moves to `TERMINATED` with `termination_date` stamped from the logical clock date. Providers already `ACTIVE` stay `ACTIVE` through this cascade.

### 3.6. Collections, Batches, and the Monthly Distribution

Revenue cycle starts with batches. A `DistributionAccountant` posts a `CollectionBatch` with `practice_id`, `payer_contract_id`, a `period` in `YYYY-MM` format, and a strictly positive `posted_amount_cents`. The practice must be `AFFILIATED` or `DEPARTING` (else `ERR_PRACTICE_NOT_AFFILIATED`), and at least one `EFFECTIVE` enrollment must link the practice — via any of its providers — to the referenced contract (else `ERR_NO_EFFECTIVE_ENROLLMENT`). Only one batch may exist per practice, contract, and period combination; a duplicate is rejected with `ERR_DUPLICATE_BATCH`. A new batch is `POSTED`, with `denial_amount_cents` at zero, `adjustment_total_cents` at zero, and `settled_by_user_id` null.

Settlement records denials: the accountant settles a `POSTED` batch by supplying `denial_amount_cents`, which must be at least zero and at most `posted_amount_cents` (else `ERR_INVALID_REQUEST`). The batch moves to `SETTLED`, its `settled_amount_cents` is fixed as `posted_amount_cents` minus `denial_amount_cents`, and `settled_by_user_id` records the settling accountant's `X-User-ID` for segregation of duties. Post-settlement recoupments and retro adjustments keep flowing: adjusting a `SETTLED` or `ADJUSTED` batch with a non-zero `adjustment_cents` (a zero adjustment is `ERR_INVALID_REQUEST`) adds the delta — positive or negative — into `adjustment_total_cents`, moves (or keeps) the batch in `ADJUSTED`, and recomputes `net_settled_cents` as `settled_amount_cents` plus `adjustment_total_cents`.

The monthly statement is where the practice sees its money. The accountant creates a `DistributionStatement` for a practice and period — at most one statement per practice and period, else `ERR_DUPLICATE_STATEMENT` — with the practice again required to be `AFFILIATED` or `DEPARTING`. At creation the statement enters `PROVISIONAL_ISSUED` and the provisional variant is computed immediately: `provisional_gross_cents` sums the period's batches, counting `SETTLED` and `ADJUSTED` batches at their `net_settled_cents` and `POSTED` batches at their full `posted_amount_cents`; `provisional_fee_cents` applies the shared-services fee schedule to that provisional gross; and `provisional_net_cents` is the provisional gross minus the provisional fee. The final-variant fields — `gross_collections_cents`, `shared_services_fee_cents`, `net_distribution_cents`, `carried_forward_in_cents`, `payable_total_cents`, `payout_cents`, `carried_forward_out_cents` — remain null until finalization, and `finalized_by_user_id` stays null as well.

The shared-services fee itself works in two modes. If the practice's `EXECUTED` agreement carries a non-null `shared_services_rate_override`, the fee is simply the gross basis multiplied by the override rate, rounded half-up to whole cents. Otherwise the group's tiered schedule applies, and the tier accounting is pinned: the period's batches are processed in chronological order by `created_at` ascending (which is a total order here since period and batch timestamps are identical only in tie cases that `created_at` resolves); a running tier-1 remainder starts at the group's `shared_services_tier1_cap_cents`; for each batch, the portion of its amount up to the remaining tier-1 room is charged at `shared_services_tier1_rate`, any excess at `shared_services_tier2_rate`, and that batch's fee is rounded half-up to whole cents before the tier-1 remainder is drawn down by the tier-1 portion consumed. The total fee is the sum of the per-batch rounded fees — rounding per batch first, then summing, never the reverse.

Finalization is a different hand. A `GroupFinancialController` finalizes a `PROVISIONAL_ISSUED` statement, and the checks run in a fixed order: the statement must be `PROVISIONAL_ISSUED` (else `ERR_INVALID_TRANSITION`); the practice must be `AFFILIATED` or `DEPARTING` (else `ERR_PRACTICE_NOT_AFFILIATED`); every batch of the practice for the period must be `SETTLED` or `ADJUSTED` — a lingering `POSTED` batch fails with `ERR_UNSETTLED_BATCHES_EXIST`; and segregation of duties requires the finalizer's `X-User-ID` to differ from the `settled_by_user_id` of every covered batch, else `ERR_SEGREGATION_OF_DUTIES`. The final variant then computes `gross_collections_cents` as the sum of `net_settled_cents` over `SETTLED` and `ADJUSTED` batches only — `POSTED` batches never enter the final basis — `shared_services_fee_cents` by the same two-mode fee schedule over that final gross, and `net_distribution_cents` as the final gross minus the final fee. For identical batch data the provisional and final variants disagree whenever any batch is still `POSTED` or carries denials or adjustments.

Hold and carry-forward then decide what actually pays out, in pinned order. First `carried_forward_in_cents` is read from the same practice's statement for the immediately preceding calendar month: it equals that statement's `carried_forward_out_cents`, but only when that statement exists and is `FINAL_ISSUED` or `REISSUED`; otherwise it is zero. Second, `payable_total_cents` is the sum of `net_distribution_cents` and `carried_forward_in_cents`. Third, the group's `distribution_hold_threshold_cents` decides: a payable total at or above the threshold pays out in full — `payout_cents` equals the payable total and `carried_forward_out_cents` is zero — while a payable total strictly below the threshold pays nothing this month and carries the entire payable total forward into `carried_forward_out_cents`. The boundary is inclusive on the paying side: exactly the threshold pays out. Finalization stamps `finalized_by_user_id` with the controller's `X-User-ID`.

Amendment keeps finalized numbers honest. Amending a `FINAL_ISSUED` or `REISSUED` statement moves it to `AMENDED` and recomputes every final-variant field from the batches' current `net_settled_cents` values; the request must carry `expected_statement_version` per §2.7, and each successful amendment increments the statement's `version`. Repeated amendment directly from `AMENDED` to `AMENDED` is permitted without an intervening reissue, still under the same OCC rule. Reissue moves an `AMENDED` statement to `REISSUED`, making the corrected figures the ones downstream carry-forward reads.

### 3.7. Value-Based Incentive Pools

Shared savings flow through pools. A `PayerContractingOfficer` opens a `ValueBasedIncentivePool` on a contract by supplying `payer_contract_id`, a `period`, a strictly positive `pool_amount_cents`, and an optional `quality_threshold` (default 60). The contract must be `ACTIVE` (else `ERR_CONTRACT_NOT_ACTIVE`) and value-eligible — `value_based_pool_eligible` must be true, else `ERR_INVALID_REQUEST`. The pool starts `OPEN` with `allocated_total_cents` at zero.

Practices attest their own performance. A `PracticeExecutive` enters an `IncentiveAllocation` into an `OPEN` pool with `pool_id`, their own `practice_id` (ownership-bound per §2.1), a `quality_score` between 0 and 100, and a strictly positive `attributed_lives` count of patients attributed under the pool's contract. The practice must be `AFFILIATED` (else `ERR_PRACTICE_NOT_AFFILIATED`) and an `EFFECTIVE` enrollment must link the practice to the pool's contract (else `ERR_NO_EFFECTIVE_ENROLLMENT`). A new allocation is `ENTERED`; its `weight` and `share_cents` stay null until allocation.

The controller then runs the pool through its pipeline. Closing entries moves an `OPEN` pool to `SCORING`. Allocation moves a `SCORING` pool to `ALLOCATED` — a pool in any other state fails with `ERR_POOL_NOT_SCORING` — and requires at least one `ENTERED` allocation whose `quality_score` is at least the pool's `quality_threshold`, else `ERR_NO_ELIGIBLE_ALLOCATIONS`. Allocation evaluates every `ENTERED` allocation: those at or above the threshold become `SCORED`; those strictly below become `INELIGIBLE` with `share_cents` zero and `weight` null. For each scored allocation the `weight` is its `quality_score` multiplied by its `attributed_lives` multiplied by the `market_weight` of the practice's market, rounded half-up to 6 decimal places. Shares follow a floor-then-waterfall pattern with pinned order: each scored allocation's raw share is the pool's `pool_amount_cents` multiplied by its `weight` and divided by the total weight across all scored allocations; `share_cents` begins at the floor of that raw share; the remainder — the pool amount minus the sum of floors — is then distributed one cent at a time to allocations ordered by fractional part of the raw share descending, then `quality_score` descending, then `created_at` ascending, each allocation receiving at most one cent per pass and passes repeating until the remainder is exhausted. The invariant is exact: `allocated_total_cents`, the sum of `share_cents` over `SCORED` (and later `PAYABLE`, `PAID`, `VOIDED`) allocations, equals `pool_amount_cents` exactly after allocation.

Distribution moves an `ALLOCATED` pool to `DISTRIBUTED` and flips each `SCORED` allocation to `PAYABLE`. Payment is per-allocation: the controller pays a `PAYABLE` allocation, moving it to `PAID` — paying in any other state fails with `ERR_ALLOCATION_NOT_PAYABLE`. Voiding unwinds a `DISTRIBUTED` pool to `VOIDED`: each `PAYABLE` allocation becomes `VOIDED`, while allocations already `PAID` stay `PAID`, and the conservation invariant holds — the sum of `PAID` shares plus the sum of `VOIDED` shares equals `pool_amount_cents`.

### 3.8. Departure: Notice, Dispute, and Settlement

Departure begins when a `PracticeExecutive` gives notice by creating a `DepartureCase` for their own practice with `practice_id` and a `requested_exit_date`. The practice must be `AFFILIATED`; otherwise creation fails with `ERR_INVALID_TRANSITION`. At most one non-terminal case may exist per practice. At creation the server stamps `notice_date` from the logical clock date, computes `earliest_exit_date` as `notice_date` plus the group's `departure_notice_days`, derives `notice_sufficient` as true exactly when `requested_exit_date` is on or after `earliest_exit_date`, and sets `assumed_exit_date` to the later of `requested_exit_date` and `earliest_exit_date`. The estimated penalty is evaluated against the assumed exit date (below). The case starts `UNDER_REVIEW`, and the practice immediately moves from `AFFILIATED` to `DEPARTING`.

The penalty math has two variants sharing one core. Tenure in whole calendar months is measured from the practice's `affiliation_effective_date` to the variant's exit date: twelve times the year difference, plus the month difference, minus one when the exit day-of-month is earlier than the affiliation day-of-month. `non_compete_applies` is true exactly when that tenure is strictly below the group's `non_compete_term_months`. When the non-compete applies, the penalty starts at the group's `early_exit_base_penalty_cents` and adds `early_exit_per_month_cents` for each whole month of tenure shortfall below `non_compete_term_months`. Independently, when `requested_exit_date` precedes `earliest_exit_date`, the flat `insufficient_notice_penalty_cents` is added. The estimated variant — computed at case creation and stored in `estimated_penalty_cents` — uses `assumed_exit_date` as its basis; the final variant — computed at settle and stored in `final_penalty_cents` — uses `actual_exit_date`, and the two diverge whenever the clock has moved past the assumed exit date by settle time.

Review and dispute form a loop. A `ComplianceOfficer` completes review, moving an `UNDER_REVIEW` case to `SETTLEMENT_PENDING`. The practice may dispute — a `PracticeExecutive` owning the practice moves a `SETTLEMENT_PENDING` case to `DISPUTED` (a caller who does not own the practice is rejected with `ERR_PRACTICE_OWNERSHIP_MISMATCH`) — and the `ComplianceOfficer` may resettle, moving a `DISPUTED` case back to `SETTLEMENT_PENDING`. Either side may walk away before settlement: rescission by the owning `PracticeExecutive` moves a case in `UNDER_REVIEW`, `SETTLEMENT_PENDING`, or `DISPUTED` to `RESCINDED` and returns the practice from `DEPARTING` to `AFFILIATED`.

Settlement is final. A `ComplianceOfficer` settles a `SETTLEMENT_PENDING` case, but only once the logical clock date has reached `earliest_exit_date`; an early settle is rejected with `ERR_EXIT_DATE_NOT_REACHED`. At settle, `actual_exit_date` is set to the latest of `requested_exit_date`, `earliest_exit_date`, and the logical clock date, and `final_penalty_cents` and `non_compete_applies` are recomputed on that basis. The case becomes `SETTLED`, and the practice moves from `DEPARTING` to `DEPARTED` with the full departure cascade: `departure_effective_date` is stamped from the case's `actual_exit_date`; every provider of the practice moves to `DEACTIVATED`; every enrollment of the practice's providers in `SUBMITTED`, `APPROVED`, or `EFFECTIVE` status moves to `TERMINATED` with `termination_date` set to `actual_exit_date`; the practice's `EXECUTED` agreement moves to `TERMINATED`; and `active_provider_count` is recomputed to zero.

### 3.9. Suspension and Reinstatement

Between affiliation and departure sits a reversible hold. A `GroupAdministrator` may suspend an `AFFILIATED` practice, moving it to `SUSPENDED`, and later reinstate a `SUSPENDED` practice back to `AFFILIATED`. Attempting either transition from any other state is rejected with `ERR_INVALID_TRANSITION`. Suspension carries no cascade: providers, enrollments, batches, and statements are untouched, and a `SUSPENDED` practice continues to occupy market capacity per §3.1.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — including all state transitions — return `200 OK`. The clock-setting capability returns `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | GroupAdministrator |
| POST | `/api/medical-groups` | Create the medical group | GroupAdministrator |
| GET | `/api/medical-groups` | List medical groups | Any |
| GET | `/api/medical-groups/{id}` | Get one medical group | Any |
| POST | `/api/medical-groups/{id}/activate` | FORMING → OPERATING | GroupAdministrator |
| POST | `/api/markets` | Create a market | GroupAdministrator |
| GET | `/api/markets` | List markets | Any |
| GET | `/api/markets/{id}` | Get one market | Any |
| POST | `/api/practices` | Create a prospect practice | GroupAdministrator |
| GET | `/api/practices` | List practices | Any |
| GET | `/api/practices/{id}` | Get one practice | Any |
| POST | `/api/practices/{id}/suspend` | AFFILIATED → SUSPENDED | GroupAdministrator |
| POST | `/api/practices/{id}/reinstate` | SUSPENDED → AFFILIATED | GroupAdministrator |
| POST | `/api/providers` | Roster a provider into a practice | GroupAdministrator |
| GET | `/api/providers` | List providers | Any |
| GET | `/api/providers/{id}` | Get one provider | Any |
| POST | `/api/affiliation-agreements` | Draft an affiliation agreement (OCC on practice version) | PracticeExecutive |
| GET | `/api/affiliation-agreements` | List agreements | Any |
| GET | `/api/affiliation-agreements/{id}` | Get one agreement | Any |
| POST | `/api/affiliation-agreements/{id}/execute` | DRAFT → EXECUTED; supersedes prior EXECUTED; onboards PROSPECT practice | PracticeExecutive |
| POST | `/api/implementation-waves` | Plan an implementation wave for a market | GroupAdministrator |
| GET | `/api/implementation-waves` | List waves | Any |
| GET | `/api/implementation-waves/{id}` | Get one wave | Any |
| POST | `/api/implementation-waves/{id}/lock` | PLANNED → LOCKED (OCC on wave version) | GroupAdministrator |
| POST | `/api/implementation-waves/{id}/start-cutover` | LOCKED → IN_CUTOVER; clock ≥ cutover_start_date | GroupAdministrator |
| POST | `/api/implementation-waves/{id}/complete` | IN_CUTOVER → COMPLETE; fires the affiliation cascade | GroupAdministrator |
| POST | `/api/implementation-waves/{id}/rollback` | IN_CUTOVER → LOCKED; assigned practices stay ONBOARDING | GroupAdministrator |
| POST | `/api/payer-contracts` | Open negotiation on a payer contract under the group TIN | PayerContractingOfficer |
| GET | `/api/payer-contracts` | List payer contracts | Any |
| GET | `/api/payer-contracts/{id}` | Get one payer contract | Any |
| POST | `/api/payer-contracts/{id}/activate` | NEGOTIATION → ACTIVE; ratification vote, effective date, uplift gate | PayerContractingOfficer |
| POST | `/api/payer-contracts/{id}/terminate` | ACTIVE → TERMINATED; cascades enrollment terminations | ComplianceOfficer |
| POST | `/api/fee-schedule-rates` | Propose a rate; supersedes prior PROPOSED rate for contract+code | PayerContractingOfficer |
| GET | `/api/fee-schedule-rates` | List fee schedule rates | Any |
| GET | `/api/fee-schedule-rates/{id}` | Get one rate | Any |
| POST | `/api/credentialing-enrollments` | Submit a provider enrollment under the group TIN | CredentialingCoordinator |
| GET | `/api/credentialing-enrollments` | List enrollments | Any |
| GET | `/api/credentialing-enrollments/{id}` | Get one enrollment | Any |
| POST | `/api/credentialing-enrollments/{id}/approve` | SUBMITTED → APPROVED or → EFFECTIVE per practice state | CredentialingCoordinator |
| POST | `/api/credentialing-enrollments/{id}/terminate` | Any non-terminal state → TERMINATED | CredentialingCoordinator, ComplianceOfficer |
| POST | `/api/collection-batches` | Post a practice's collections for a contract+period | DistributionAccountant |
| GET | `/api/collection-batches` | List collection batches | Any |
| GET | `/api/collection-batches/{id}` | Get one batch | Any |
| POST | `/api/collection-batches/{id}/settle` | POSTED → SETTLED with denials recorded | DistributionAccountant |
| POST | `/api/collection-batches/{id}/adjust` | SETTLED/ADJUSTED → ADJUSTED; applies a recoupment delta | DistributionAccountant |
| POST | `/api/distribution-statements` | Create the period statement; computes the provisional variant | DistributionAccountant |
| GET | `/api/distribution-statements` | List statements | Any |
| GET | `/api/distribution-statements/{id}` | Get one statement | Any |
| POST | `/api/distribution-statements/{id}/finalize` | PROVISIONAL_ISSUED → FINAL_ISSUED; final variant incl. hold/carry | GroupFinancialController |
| POST | `/api/distribution-statements/{id}/amend` | FINAL_ISSUED/REISSUED/AMENDED → AMENDED with recompute (OCC) | GroupFinancialController |
| POST | `/api/distribution-statements/{id}/reissue` | AMENDED → REISSUED | GroupFinancialController |
| POST | `/api/incentive-pools` | Open a value-based incentive pool on an eligible ACTIVE contract | PayerContractingOfficer |
| GET | `/api/incentive-pools` | List pools | Any |
| GET | `/api/incentive-pools/{id}` | Get one pool | Any |
| POST | `/api/incentive-pools/{id}/close-entries` | OPEN → SCORING | GroupFinancialController |
| POST | `/api/incentive-pools/{id}/allocate` | SCORING → ALLOCATED; computes weights and shares | GroupFinancialController |
| POST | `/api/incentive-pools/{id}/distribute` | ALLOCATED → DISTRIBUTED; SCORED → PAYABLE | GroupFinancialController |
| POST | `/api/incentive-pools/{id}/void` | DISTRIBUTED → VOIDED; PAYABLE → VOIDED | GroupFinancialController |
| POST | `/api/incentive-allocations` | Practice self-attests quality score and attributed lives | PracticeExecutive |
| GET | `/api/incentive-allocations` | List allocations | Any |
| GET | `/api/incentive-allocations/{id}` | Get one allocation | Any |
| POST | `/api/incentive-allocations/{id}/pay` | PAYABLE → PAID | GroupFinancialController |
| POST | `/api/departure-cases` | Practice gives departure notice; computes penalty estimate | PracticeExecutive |
| GET | `/api/departure-cases` | List departure cases | Any |
| GET | `/api/departure-cases/{id}` | Get one departure case | Any |
| POST | `/api/departure-cases/{id}/complete-review` | UNDER_REVIEW → SETTLEMENT_PENDING | ComplianceOfficer |
| POST | `/api/departure-cases/{id}/dispute` | SETTLEMENT_PENDING → DISPUTED | PracticeExecutive |
| POST | `/api/departure-cases/{id}/resettle` | DISPUTED → SETTLEMENT_PENDING | ComplianceOfficer |
| POST | `/api/departure-cases/{id}/settle` | SETTLEMENT_PENDING → SETTLED; practice → DEPARTED with cascade | ComplianceOfficer |
| POST | `/api/departure-cases/{id}/rescind` | UNDER_REVIEW/SETTLEMENT_PENDING/DISPUTED → RESCINDED | PracticeExecutive |
| POST | `/api/committee-votes` | Open a physician-governance motion; snapshots eligible voters | MarketCommitteeChair |
| GET | `/api/committee-votes` | List committee votes | Any |
| GET | `/api/committee-votes/{id}` | Get one vote | Any |
| POST | `/api/committee-votes/{id}/cast` | Cast a ballot; auto-closes per majority rules | PhysicianBoardMember |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_PRACTICE_OWNERSHIP_MISMATCH` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_MEDICAL_GROUP_NOT_FOUND` | 404 Not Found |
| `ERR_MARKET_NOT_FOUND` | 404 Not Found |
| `ERR_PRACTICE_NOT_FOUND` | 404 Not Found |
| `ERR_PROVIDER_NOT_FOUND` | 404 Not Found |
| `ERR_AGREEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_WAVE_NOT_FOUND` | 404 Not Found |
| `ERR_PAYER_CONTRACT_NOT_FOUND` | 404 Not Found |
| `ERR_RATE_NOT_FOUND` | 404 Not Found |
| `ERR_ENROLLMENT_NOT_FOUND` | 404 Not Found |
| `ERR_BATCH_NOT_FOUND` | 404 Not Found |
| `ERR_STATEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_POOL_NOT_FOUND` | 404 Not Found |
| `ERR_ALLOCATION_NOT_FOUND` | 404 Not Found |
| `ERR_DEPARTURE_CASE_NOT_FOUND` | 404 Not Found |
| `ERR_VOTE_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_TRANSITION` | 409 Conflict |
| `ERR_GROUP_NOT_OPERATING` | 409 Conflict |
| `ERR_PRACTICE_NOT_AFFILIATED` | 409 Conflict |
| `ERR_CONTRACT_NOT_ACTIVE` | 409 Conflict |
| `ERR_POOL_NOT_SCORING` | 409 Conflict |
| `ERR_ALLOCATION_NOT_PAYABLE` | 409 Conflict |
| `ERR_NO_WAVE_IN_CUTOVER` | 409 Conflict |
| `ERR_NO_PASSED_RATIFICATION_VOTE` | 422 Unprocessable Entity |
| `ERR_NO_ELIGIBLE_VOTERS` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_VOTE` | 409 Conflict |
| `ERR_INVALID_CUTOVER_WINDOW` | 422 Unprocessable Entity |
| `ERR_EXPEDITED_WINDOW_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_WAVE_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_ENROLLMENT_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_MARKET_AT_CAPACITY` | 409 Conflict |
| `ERR_DUPLICATE_BATCH` | 409 Conflict |
| `ERR_DUPLICATE_STATEMENT` | 409 Conflict |
| `ERR_NO_EFFECTIVE_ENROLLMENT` | 422 Unprocessable Entity |
| `ERR_UNSETTLED_BATCHES_EXIST` | 422 Unprocessable Entity |
| `ERR_FEE_SCHEDULE_UPLIFT_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_NON_COMPETE_ACK_REQUIRED` | 422 Unprocessable Entity |
| `ERR_EXIT_DATE_NOT_REACHED` | 422 Unprocessable Entity |
| `ERR_NO_ELIGIBLE_ALLOCATIONS` | 422 Unprocessable Entity |
