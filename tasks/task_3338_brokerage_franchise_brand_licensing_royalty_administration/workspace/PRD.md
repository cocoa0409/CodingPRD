# Brokerage Franchise Brand Licensing & Royalty Administration API — Product Requirements Document

## 1. Introduction

A national real-estate franchisor grows by licensing its consumer brands to independent brokerages, market by market. Each license is a commercial contract: the franchisee earns the right to operate under the brand inside an exclusive territory for a fixed term, and in exchange owes the franchisor a royalty on gross commission income plus a contribution to the brand's national advertising fund. Around that contract sits a larger operating fabric — conversion plans that walk a newly signed brokerage through onboarding, monthly reporting of headcount and production that drives royalty assessment, brand-standards audits that can escalate into default cases, a governed advertising fund whose spending is ratified by franchisee advisory councils, and a tightly sequenced wind-down protocol that strips the brand identity from a terminated brokerage before the file can be closed.

This document specifies the REST API that administers that fabric. It is written for the engineers who will implement the service. The system is responsible for keeping eleven interacting resources consistent with one another across territory exclusivity, dual-variant royalty computation, council quorum arithmetic, optimistic concurrency on agreement mutation, and a forward-only logical clock that sweeps expired agreements. Where a rule sounds financial, treat it as exact integer arithmetic over cents; where a rule sounds procedural, treat it as a state machine whose transitions, preconditions, and cascades are binding. The API is mounted under `/franchise` and exposes forty-four endpoints across three operator roles.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the operational capacity in which they act. The system recognizes exactly three roles, spelled as follows: `FranchisorOps`, `FranchiseeAdmin`, and `BrandAuditor`. A request whose `X-User-Role` header is missing, or names anything other than these three roles, or — for entity-backed roles — lacks an `X-User-ID`, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is authenticated but is not listed among the authorized roles for the target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE`.

Role identity semantics differ per role and are binding for ownership checks:

- When `X-User-Role` is `FranchiseeAdmin`, `X-User-ID` is the `id` of the acting `Brokerage`; ownership checks on any resource that references a `Brokerage` compare the resource's foreign-key field to `X-User-ID`. A `FranchiseeAdmin` acting on an agent, an agent-count report, a GCI report, or a de-identification task outside their own brokerage's scope is rejected with `ERR_FORBIDDEN_OWNERSHIP`.
- When `X-User-Role` is `FranchisorOps`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server does not compare it to any entity's `id`.
- When `X-User-Role` is `BrandAuditor`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity and is never compared against an entity's `id`.

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

List endpoints accept two query parameters controlling pagination. The `limit` parameter specifies the maximum number of items to return; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. Unless otherwise specified, all list endpoints return resources sorted by `created_at` in ascending order. Paginated list responses include `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. Resource Identity, Timestamps, and Versioning

Most primary resources — `Brand`, `Market`, `Brokerage`, `FranchiseAgreement`, `ConversionPlan`, `Agent`, `RoyaltyPeriod`, `DefaultCase`, `AdvisoryCouncil`, `AdFundSpendProposal`, `ComplianceAudit`, and `DeidentificationTask` — carry a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` and `updated_at` fields are ISO 8601 UTC timestamps with three fractional digits; `updated_at` refreshes on every mutation. The `version` field is an integer that increments by exactly 1 on every mutation of the resource, including mutations caused by system-driven side effects such as cascades and clock sweeps.

Three resources are deliberately lighter. `AgentCountReport`, `GCIReport`, and `AdFundLedgerEntry` carry only `id` and `created_at`; both `updated_at` and `version` are absent on these entities, because they are append-only records that are never modified after creation.

### 2.5. Money, Rates, and Rounding Discipline

All monetary amounts in this system are integers denominated in cents — GCI, royalty dues, caps, thresholds, fund balances, and proposal amounts alike. All percentage rates are integers denominated in basis points, where 100 basis points equal one percent. Every rate-to-amount multiplication in the royalty and ad-fund pipelines is floored to whole cents, and the system pins a round-per-leg-then-sum discipline: each multiplication leg is floored independently before the legs are summed, never the reverse. For ad-fund accrual there is exactly one rounding event per period, taken at accrual time; downstream ledger balances sum already-floored integers and never round again. No fuzzy estimation is permitted anywhere in the financial pipeline — a reader reconstructing the arithmetic from this document must arrive at exactly the same integers the server produces.

### 2.6. Optimistic Concurrency on Agreement Mutation

Two write operations on a franchise agreement participate in optimistic concurrency control: activation of a `DRAFT` agreement, and amendment of a `DRAFT` agreement's commercial terms. Both requests must carry `expected_agreement_version`, a non-optional field holding the `version` of the `FranchiseAgreement` the client last observed. If the agreement's current `version` on the server does not match the supplied `expected_agreement_version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412) — the canonical case being a client that read the agreement at some version, another write having since advanced that version, and the client's request arriving with a stale expectation. Endpoints other than these two do not accept a version field.

### 2.7. The Logical Clock and the Expiry Sweep

The server maintains a logical clock used for all date-sensitive evaluation, including term expiry and deadline computation. At startup, before any explicit adjustment, the logical clock reads exactly `2026-09-01T00:00:00Z` and never silently falls back to wall-clock time. A `FranchisorOps` operator may advance the logical clock by supplying a `to_iso8601` instant; the clock moves forward only, and an attempt to set it backwards is rejected with `ERR_CLOCK_REGRESSION`. Advancing the clock triggers a sweep: every `FranchiseAgreement` in `ACTIVE` status whose `term_end` is earlier than the new logical date transitions to `EXPIRED` as a system side effect, with its `version` incremented. Natural expiry carries no de-identification obligations — the wind-down protocol described later applies only to termination for cause.

### 2.8. Nested Path Validation and Existence Ordering

When an endpoint path contains multiple resource identifiers, the system validates the existence of each identifier in strict left-to-right order as it appears in the URL. The request is rejected with `ERR_NOT_FOUND` at the first identifier that does not correspond to an existing resource, before any later identifier or any business rule is evaluated. The same existence discipline applies to identifiers carried in the request body: every referenced `id` — agreement, brand, market, brokerage, council, proposal, default case, audit, task, or royalty period — must resolve to an existing resource, or the request fails with `ERR_NOT_FOUND`.

### 2.9. Validation Ordering Across a Request

A single request can fail several rules at once, and the order in which checks run determines which error the caller sees. The system evaluates, in this fixed order: first authentication of the headers (`ERR_UNAUTHENTICATED`); then role authorization for the endpoint (`ERR_UNAUTHORIZED_ROLE`); then brokerage-ownership scope for `FranchiseeAdmin` callers (`ERR_FORBIDDEN_OWNERSHIP`); then existence of every referenced identifier (`ERR_NOT_FOUND`); then state-machine legality of the requested transition (`ERR_INVALID_STATE`); then the optimistic-concurrency version match on activation and amendment (`ERR_STALE_VERSION`); then payload shape, enum membership, and numeric ranges (`ERR_INVALID_REQUEST`); and only then the business rules — territory conflict, term sanity, council eligibility, report and period uniqueness, missing GCI reports, fund sufficiency, vote rules, zero-due waiver, escalated-default termination, open-default suspension, conversion readiness, milestone indexing, audit-state rules, clock regression, agreement-liveness for reporting, agent license uniqueness, brokerage liveness for agent creation, brand/brokerage liveness for agreement creation, renewal target validity, voter segregation, and de-identification completeness — each surfaced under its own error code as described in §3 and catalogued in §5.

## 3. Business Logic & Workflows

### 3.1. Brands, Markets, and the Brokerage Roster

The franchisor's portfolio begins with its brands. A `FranchisorOps` operator creates a `Brand` by supplying a `brand_code` — a stable uppercase code of between 2 and 16 uppercase letters or digits, unique across all brands — together with a human-readable `display_name`. A brand is born in `ACTIVE` status; it may later be `RETIRED`, after which it can no longer anchor new agreements, though existing agreements are unaffected. Brand listings support a `status` filter alongside the standard pagination parameters.

Markets carve the country into exclusive territories. Creating a `Market` requires a unique `market_code` (for example, a metro designator such as PHX-METRO) and a human-readable `name`. Brokerages are the independent companies that may become franchisees: registration captures the `legal_name`, the `home_market_id` of the market where the principal office sits, and the `principal_email` of the brokerage principal. A brokerage begins life as a `PROSPECT`, becomes `FRANCHISED` the moment its first franchise agreement activates, and ultimately reaches `TERMINATED` when its last live agreement closes out — transitions the system performs on its own, never at a client's direct request. Brokerage listings accept `status` and `home_market_id` filters.

### 3.2. Granting the License: Agreements, Commercial Terms, and Renewal

A franchise agreement is drafted by `FranchisorOps` against a specific brokerage, brand, and market, identified by `brokerage_id`, `brand_id`, and `market_id`. The commercial heart of the agreement is a set of five figures. The `base_royalty_rate_bps` is the royalty rate in basis points applied to gross commission income, and must be greater than zero and at most 10000. The `annual_royalty_cap_cents` is the ceiling on billed royalty within one agreement calendar year, and must be greater than zero. The `volume_incentive_threshold_cents` is the annual GCI level at which a volume-incentive rebate on marginal royalty becomes available, and must also be greater than zero. The `volume_incentive_rate_bps` is the reduced marginal rate applied above that threshold; it must be at least zero and strictly less than the base rate. Finally, the `ad_fund_rate_bps` is the national advertising fund contribution rate in basis points of GCI, bounded above zero and at most 1000.

The agreement's term is defined by `term_start` — the first, inclusive day of the license, an ISO 8601 date at 00:00:00Z — and `term_end`, the last, inclusive day. The term must be sane: `term_end` strictly after `term_start`, or the create is rejected with `ERR_INVALID_TERM`. Creation also requires the referenced brand to be `ACTIVE` and the brokerage to be `PROSPECT` or `FRANCHISED`; drafting against a `RETIRED` brand or a `TERMINATED` brokerage fails with `ERR_BRAND_OR_BROKERAGE_INACTIVE`. Territory rights occupy the half-open interval from `term_start` up to but not including the day after `term_end`, so an agreement whose `term_end` was yesterday imposes no territorial claim today.

A new agreement may optionally renew an old one through `renewed_from_id`. The renewal target must reference an agreement of the same brokerage and the same brand, and the target must exist; otherwise creation fails with `ERR_RENEWAL_TARGET_INVALID`. A renewal's `term_start` must additionally be on or after the renewed agreement's `term_end`, and violating that ordering also surfaces `ERR_INVALID_TERM`. Fresh grants carry no renewal link. Every new agreement is born in `DRAFT` status, with `activated_at` null, `cumulative_billed_royalty_cents` and `cumulative_gci_cents` at zero, and `open_cure_count` at zero. Agreement listings accept `brokerage_id`, `brand_id`, `market_id`, `status`, and `renewed_from_id` filters, and the roster of a single brokerage's agreements is also reachable through the brokerage itself.

While the agreement remains in `DRAFT`, `FranchisorOps` may amend its commercial terms — any subset of the five rates and caps plus the two term dates — through an amendment request that must also carry `expected_agreement_version` per §2.6. A stale version yields `ERR_STALE_VERSION`, and term changes remain subject to the same `ERR_INVALID_TERM` sanity rules as creation. Each successful amendment increments the agreement's `version` by 1.

### 3.3. Conversion Planning and Activation

Signing an independent brokerage is only half the battle; the brokerage must convert — rebrand its offices, migrate its technology, onboard its agents — before the license goes live. A `ConversionPlan` is created against a `DRAFT` agreement with a `milestones` array. Each milestone is an object carrying a `name`, a `target_date`, and a `sequence`; the sequence values across the array must form a 1-based contiguous permutation — every position from 1 up to the count of milestones present exactly once, with no gaps and no duplicates. The plan tracks `milestones_done`, the count of milestones whose `done` flag is true, and a derived `ready` flag: the plan is ready exactly when `milestones_done` equals the total number of milestones and the plan contains at least one milestone. An empty milestone array is therefore never ready, and the readiness comparison is equality — a plan with every milestone done is ready, no more and no less.

Either `FranchisorOps` or the owning `FranchiseeAdmin` may mark a milestone done by submitting its `sequence` index. The index must reference an existing milestone that is not already done; an out-of-range index or an already-completed milestone is rejected with `ERR_MILESTONE_INVALID`. Each completion recomputes `milestones_done` and `ready`.

Activation is the pivotal moment of the lifecycle, and it is guarded more heavily than any other transition. When `FranchisorOps` activates an agreement, the system checks, in order: the generic pipeline of §2.9; that the agreement is in `DRAFT` (otherwise `ERR_INVALID_STATE`); that `expected_agreement_version` matches the agreement's current `version` (otherwise `ERR_STALE_VERSION`); that the brand is still `ACTIVE`; that a `ConversionPlan` exists for this agreement with `ready` true (otherwise `ERR_CONVERSION_INCOMPLETE`); and the territory conflict rule — no other agreement sharing the same `brand_id` and `market_id` may currently stand in `ACTIVE`, `SUSPENDED`, or `DEIDENTIFYING` status. A conflicting live grant is rejected with `ERR_TERRITORY_CONFLICT`. Because a `TERMINATED` agreement hops into `DEIDENTIFYING` within the same request that terminates it, a terminated-but-not-yet-closed grant still blocks re-grant of its territory; only `DRAFT`, `EXPIRED`, and `CLOSED` agreements leave a market free. On success the agreement becomes `ACTIVE`, `activated_at` is stamped, and the agreement's `version` increments by 1. If this is the brokerage's first activation — the brokerage still a `PROSPECT` — the brokerage simultaneously becomes `FRANCHISED`, its own `version` incrementing as part of the same side-effect cascade.

### 3.4. Agents and Monthly Reporting

Agents affiliate with brokerages. Registering an agent captures the `full_name`, a state `license_no`, and the `affiliated_on` date; the license number must be unique within the owning brokerage, and a duplicate is rejected with `ERR_DUPLICATE_LICENSE`. Agent creation is open to `FranchisorOps` and to the owning `FranchiseeAdmin`, but only while the brokerage is `PROSPECT` or `FRANCHISED` — registering under a `TERMINATED` brokerage fails with `ERR_BROKERAGE_TERMINATED`. Agents are born `ACTIVE` and may be deactivated to `INACTIVE` by the owning `FranchiseeAdmin`; reactivation back to `ACTIVE` is likewise the owning admin's call, but only while the brokerage is `FRANCHISED` — reactivating under a `TERMINATED` brokerage fails with the same `ERR_BROKERAGE_TERMINATED`. When a brokerage itself reaches `TERMINATED`, every one of its `ACTIVE` agents flips to `INACTIVE` as a cascade, with no per-agent request required. Agent listings accept a `status` filter.

Two monthly reports feed the royalty machine, and both are keyed by `period_month`, a month key in `YYYY-MM` form. The `AgentCountReport` records `active_agent_count` — the number of agents in `ACTIVE` status at report time, zero or more — and stamps `reported_at` at submission. The `GCIReport` records `gci_cents`, the month's gross commission income in cents, also zero or more; it stamps `reported_at` and additionally records `reported_by_role`, the `X-User-Role` of the submitter — `FRANCHISEE_ADMIN` or `FRANCHISOR_OPS` — which drives variant selection in royalty assessment. Both reports may be filed by the owning `FranchiseeAdmin` or by `FranchisorOps`. Within one agreement, each `period_month` may be reported at most once per report type: a second `AgentCountReport` or `GCIReport` for the same agreement and month is rejected with `ERR_DUPLICATE_REPORT`. Reports of either kind, and royalty assessments as well, are only accepted while the agreement is `ACTIVE` or `SUSPENDED`; filing against an agreement in any other status fails with `ERR_AGREEMENT_NOT_LIVE`.

### 3.5. Royalty Assessment: Tiers, Cap, Rebate, and the Two Variants

Once a month's GCI has been reported, `FranchisorOps` assesses the month, producing a `RoyaltyPeriod` for that agreement and `period_month`. Assessment is impossible without the report — if no `GCIReport` exists for the requested month, the request fails with `ERR_GCI_REPORT_MISSING` — and a month may be assessed at most once per agreement, a second assessment being rejected with `ERR_DUPLICATE_PERIOD`. The new period snapshots `gci_cents` from the report and computes three money figures.

The final royalty, `royalty_due_cents`, runs a five-step pipeline over exact integer cents. Let the month's GCI be the report amount; let the agreement's `cumulative_gci_cents` before this month be the running year-to-date figure, and `cumulative_billed_royalty_cents` the running billed total. Step one splits the month's GCI at the volume threshold using annual cumulative figures: the portion below the threshold is the amount by which the smaller of the running total after this month and the threshold exceeds the smaller of the running total before this month and the threshold (floored at zero), and the remainder of the month lies above the threshold. Step two prices each leg separately — the below-threshold portion multiplied by `base_royalty_rate_bps` and divided by 10000, floored to whole cents; the above-threshold portion multiplied by `volume_incentive_rate_bps` and divided by 10000, floored to whole cents — and the raw royalty is the sum of the two floored legs. The round-per-leg-then-sum order of §2.5 is pinned here: flooring each leg before summing is required, and summing first and flooring once is forbidden. Step three applies the annual cap: the billed royalty is the smaller of the raw royalty and the remaining headroom under `annual_royalty_cap_cents` after `cumulative_billed_royalty_cents`, with the headroom floored at zero so a fully consumed cap yields zero billed royalty. Step four applies the volume-incentive rebate, and its position after the cap is pinned so the rebate never re-opens capped royalty: when the running GCI total after this month exceeds the threshold, the rebate is the above-threshold portion of this month's GCI multiplied by the difference between the base and volume rates, then by 50 percent, divided by 10000, floored to whole cents; otherwise the rebate is zero. The final `royalty_due_cents` is the billed royalty minus the rebate, floored at zero. Step five advances the running totals: `cumulative_billed_royalty_cents` grows by the billed royalty from step three, and `cumulative_gci_cents` becomes the running total after this month.

The period also carries `provisional_royalty_cents`, a second variant of the same month's royalty computed at the same assessment for reporting purposes. The provisional variant skips both the annual cap and the volume-incentive rebate — it is exactly the raw royalty from step two, evaluated on the same GCI input. Under the pinned constants it is therefore always at least `royalty_due_cents`, and it diverges from the final figure precisely when the cap or the rebate binds.

Both cumulative counters live on the agreement and reset on calendar-year boundaries. When a period is created whose `period_month` falls in a different calendar year than the agreement's most recent prior period — or, for the very first period, in a different calendar year than `term_start` — both counters reset to zero before the five-step pipeline runs.

The same assessment also accrues the national advertising fund contribution, `ad_fund_due_cents`: the month's GCI multiplied by `ad_fund_rate_bps` and divided by 10000, floored to whole cents, exactly one rounding event at accrual. When the computed contribution is greater than zero, the assessment appends a `COLLECT` entry to the brand's ad-fund ledger, recording the `brand_id` of the agreement's brand, the contributing `agreement_id`, and the new period's `period_id`, with `amount_cents` equal to the contribution. When the agreement is `SUSPENDED` at assessment time, the month's contribution is zero and no ledger entry is created at all — suspension pauses fund accrual without pausing royalty.

A period is born in `ASSESSED` status and ends in one of two terminal states. Settlement moves it `ASSESSED` → `SETTLED` and stamps `settled_at`. Waiver moves it `ASSESSED` → `WAIVED`, but only when `royalty_due_cents` is exactly zero; waiving a period with any positive due is rejected with `ERR_WAIVE_REQUIRES_ZERO_DUE`.

### 3.6. The National Advertising Fund: Ledger, Councils, and Governed Spending

Each brand's national advertising fund is an append-only ledger of `AdFundLedgerEntry` rows. An entry records the `brand_id`, an `entry_type` of either `COLLECT` or `SPEND`, and a positive `amount_cents`; `COLLECT` rows also carry the contributing `agreement_id` and `period_id`, while `SPEND` rows leave both null. The brand's fund balance is the sum of all `COLLECT` amounts minus the sum of all `SPEND` amounts across all periods with no time window, exposed as a computed read returning `balance_cents` and `brand_id`. Because entries are append-only and amounts are already floored at accrual, the balance itself never rounds. Ledger listings per brand accept `entry_type`, `agreement_id`, and `period_id` filters; an agreement-scoped ledger view accepts `entry_type`; and a period-scoped view returns the zero or one `COLLECT` rows tied to that period.

Spending from the fund is governed by a franchisee advisory council per brand. Seating a council requires the `brand_id`, a `seat_count`, and the `member_brokerage_ids` occupying those seats. The seat count must be at least 3 and odd, and the member list must contain exactly `seat_count` brokerages. Every seated brokerage must pass a two-part eligibility test: it must hold a franchise agreement in this brand that is currently `ACTIVE` or `SUSPENDED`, and it must not already sit on another council of the same brand. An ineligible nominee is rejected with `ERR_COUNCIL_INELIGIBLE_MEMBER`. The council's `quorum_votes` is derived as the floor of half the seat count plus one, recomputed whenever `seat_count` changes, and a seated member may later be replaced by supplying `outgoing_brokerage_id` and `incoming_brokerage_id` — the incoming brokerage must pass the same eligibility test at replacement time. Council listings accept a `brand_id` filter, and a brand's councils are also reachable through the brand itself.

A spend proposal is drafted with the `brand_id` of the fund it draws on, the `council_id` that must ratify it, a short `title`, and the requested `amount_cents`, which must be greater than zero. The proposal begins in `DRAFT` with `approvals` and `rejections` at zero and `approver_ids` and `rejecter_ids` empty. Submission moves it `DRAFT` → `SUBMITTED`, requiring the referenced council to exist.

Voting is the franchisee's voice: a seated council member, acting as a `FranchiseeAdmin`, casts a `vote` of either `APPROVE` or `REJECT` against a `SUBMITTED` proposal. Three safety rules guard the ballot box. The voter must be a seated member of the proposal's council — otherwise `ERR_NOT_COUNCIL_MEMBER`. The voter may vote only once per proposal; a second vote of either flavor is rejected with `ERR_DUPLICATE_VOTE`, enforced through the recorded `approver_ids` and `rejecter_ids`. And segregation of duties bars a voter who is in default to the very fund being spent: a brokerage with an `ESCALATED` default case on any agreement of the proposal's brand may not vote on that proposal, and the attempt is rejected with `ERR_VOTER_IN_DEFAULT`. Each accepted vote appends the voter's brokerage id to the matching id list and recomputes the counts. Resolution is automatic at quorum: the moment `approvals` reaches the council's `quorum_votes` the proposal transitions `SUBMITTED` → `APPROVED`, and the moment `rejections` reaches that same quorum it transitions `SUBMITTED` → `REJECTED`. The comparison is inclusive — a proposal resolves at exactly quorum, never only beyond it.

An `APPROVED` proposal is executed by `FranchisorOps`, which debits the fund: the system appends a `SPEND` ledger entry for the proposal's `amount_cents` with null `agreement_id` and `period_id`, and the proposal becomes `EXECUTED`. Execution requires the brand's fund balance at execute time to cover the full `amount_cents`; an overdraw attempt is rejected with `ERR_INSUFFICIENT_FUND_BALANCE`. Proposal listings accept `brand_id`, `council_id`, and `status` filters.

### 3.7. Brand-Standards Audits

Compliance is policed through audits. A `ComplianceAudit` is scheduled against an agreement by a `BrandAuditor` or by `FranchisorOps`, naming an `audit_type` of `SIGNAGE`, `MARKETING`, `TECH_ADOPTION`, or `AGENT_ONBOARDING`. The audit is born `SCHEDULED`; audit listings accept a `status` filter.

Starting an audit is the `BrandAuditor`'s exclusive act and requires two conditions: the audit must be `SCHEDULED`, and the parent agreement must be `ACTIVE` — an audit cannot be opened against a suspended, expired, or winding-down agreement. On start, the audit moves to `IN_PROGRESS` and stamps `started_at`. An audit that will not run may instead be cancelled, `SCHEDULED` → `CANCELLED`, again only by the `BrandAuditor` and only from `SCHEDULED`.

Completion is likewise the `BrandAuditor`'s act, allowed only from `IN_PROGRESS`, and requires a `finding` in the request body — `PASS` or `FAIL` — which is recorded on the audit as it becomes `COMPLETED`. A `PASS` closes the matter. A `FAIL` does not: the system opens a `DefaultCase` on the agreement with `reason_code` `BRAND_STANDARDS` in `OPEN` status, and the agreement's `open_cure_count` is recomputed to include it. Audit failure is therefore one of the two on-ramps into the default machinery.

### 3.8. Defaults, Suspension, and Termination for Cause

The other on-ramp is direct: `FranchisorOps` may open a `DefaultCase` on an agreement at any time, naming a `reason_code` of `PAYMENT`, `BRAND_STANDARDS`, `REPORTING`, or `TERRITORY`. The case is born `OPEN`, stamps `opened_at`, and computes its `cure_deadline` as exactly 30 days after `opened_at` — the hard deadline past which an escalated default may drive termination. Each creation, escalation, and resolution recomputes the agreement's `open_cure_count`, which counts only cases in `OPEN` or `CURING`; `ESCALATED` cases do not count toward it (they gate termination instead), and `RESOLVED` cases never count.

A default moves through a small lattice. Starting the cure moves it `OPEN` → `CURING`. Escalation moves it from either `OPEN` or `CURING` to `ESCALATED`, stamping `escalated_at`; because an escalated case no longer counts toward `open_cure_count`, escalation recomputes that counter as well. Resolution closes the case to `RESOLVED` from any of `OPEN`, `CURING`, or `ESCALATED`. Every resolution recomputes `open_cure_count`, and when the counter falls to zero while the agreement sits in `SUSPENDED`, the agreement resumes on its own — a system-driven `SUSPENDED` → `ACTIVE` hop that increments the agreement's `version`. Default-case listings accept a `status` filter.

Suspension is the franchisor's sanction short of termination: `FranchisorOps` moves an agreement `ACTIVE` → `SUSPENDED`, but only when at least one default case stands in `OPEN` or `CURING` — that is, when `open_cure_count` is at least 1. Suspending with no open default is rejected with `ERR_SUSPENSION_REQUIRES_OPEN_DEFAULT`. A suspended agreement keeps filing reports and being assessed, but as §3.5 describes, its ad-fund accrual pauses for the duration.

Termination for cause requires escalation to have failed: `FranchisorOps` may terminate an agreement in `ACTIVE` or `SUSPENDED` only when at least one of its default cases stands in `ESCALATED` — that is, the escalation has already occurred, with `escalated_at` no later than the present. Terminating without an escalated default is rejected with `ERR_TERMINATION_REQUIRES_ESCALATED_DEFAULT`. Termination is a compound event executed within a single request. The agreement first lands in `TERMINATED`; the system then creates five `DeidentificationTask` rows, one in `PENDING` status for each category, each with `due_at` set to the termination timestamp plus 60 days; and the agreement immediately hops `TERMINATED` → `DEIDENTIFYING` within the same request once the tasks exist, with the agreement's `version` incremented by 1. Natural expiry, by contrast, creates no tasks at all — an agreement that simply outlives its term goes straight to `EXPIRED` via the clock sweep of §2.7.

### 3.9. De-identification, Closure, and the Brokerage Wind-Down

Post-termination obligations strip the brand identity from the departing brokerage. Each task's `category` is one of the five de-identification categories — `SIGNAGE_REMOVAL`, `MARKETING_WITHDRAWAL`, `DATA_PURGE`, `DOMAIN_RELEASE`, and `DIRECTORY_REMOVAL` — and every terminated agreement spawns exactly one task per `category`. Task listings accept a `status` filter.

Each task walks a two-step verification. The owning `FranchiseeAdmin` — whose `X-User-ID` must equal the agreement's `brokerage_id` — marks a `PENDING` task done, moving it to `COMPLETED`. `FranchisorOps` then verifies a `COMPLETED` task, moving it to `VERIFIED`. Verification order matters: a task must be `COMPLETED` before it can be verified, and agreement closure requires all five categories present and verified; a verify call that would close the file without all five categories verified is rejected with `ERR_DEIDENTIFICATION_INCOMPLETE`.

The `due_at` of each task is advisory rather than a gate: the agreement cannot transition `DEIDENTIFYING` → `CLOSED` until every task is `VERIFIED`, regardless of whether the 60-day window has passed, and a late-but-verified task still closes the file. When the final task is verified and no default case of the agreement remains in `OPEN`, `CURING`, or `ESCALATED`, the agreement closes, `DEIDENTIFYING` → `CLOSED`, with its `version` incremented. Closure then propagates upward: if no agreement of the brokerage remains in any non-terminal state — nothing left in `DRAFT`, `ACTIVE`, `SUSPENDED`, `TERMINATED`, or `DEIDENTIFYING` — the brokerage itself transitions `FRANCHISED` → `TERMINATED`, its `version` increments, and every one of its agents still `ACTIVE` flips to `INACTIVE` as the final cascade of the lifecycle.

## 4. Endpoint Definitions

New resources are returned with HTTP 201 upon creation; modifications, state transitions, and computed reads return HTTP 200. All endpoints live under the `/franchise` mount. Request bodies, response shapes, and side effects are specified in §2 and §3; the table below is a navigational summary only.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /franchise/brands | Create a brand | FranchisorOps |
| GET | /franchise/brands | List brands with pagination | FranchisorOps, FranchiseeAdmin, BrandAuditor |
| GET | /franchise/brands/{id} | Get one brand | FranchisorOps, FranchiseeAdmin, BrandAuditor |
| GET | /franchise/brands/{id}/ad-fund-balance | Computed read of the brand's ad fund balance | FranchisorOps, FranchiseeAdmin |
| GET | /franchise/brands/{id}/ad-fund-ledger | List ad fund ledger entries for a brand | FranchisorOps, FranchiseeAdmin |
| POST | /franchise/markets | Create a market | FranchisorOps |
| GET | /franchise/markets | List markets | FranchisorOps, FranchiseeAdmin, BrandAuditor |
| POST | /franchise/brokerages | Register a prospective brokerage | FranchisorOps |
| GET | /franchise/brokerages | List brokerages | FranchisorOps, BrandAuditor |
| GET | /franchise/brokerages/{id} | Get one brokerage | FranchisorOps, FranchiseeAdmin, BrandAuditor |
| POST | /franchise/brokerages/{id}/agents | Register an agent under a brokerage | FranchisorOps, FranchiseeAdmin |
| GET | /franchise/brokerages/{id}/agents | List agents of a brokerage | FranchisorOps, FranchiseeAdmin, BrandAuditor |
| POST | /franchise/agents/{id}/deactivate | Deactivate an agent | FranchiseeAdmin |
| POST | /franchise/agents/{id}/reactivate | Reactivate an agent (requires brokerage FRANCHISED) | FranchiseeAdmin |
| POST | /franchise/agreements | Create a franchise agreement in DRAFT | FranchisorOps |
| GET | /franchise/agreements | List agreements with brokerage/brand/market/status filters | FranchisorOps, FranchiseeAdmin, BrandAuditor |
| GET | /franchise/agreements/{id} | Get one agreement | FranchisorOps, FranchiseeAdmin, BrandAuditor |
| GET | /franchise/brokerages/{id}/agreements | List agreements of a brokerage | FranchisorOps, FranchiseeAdmin, BrandAuditor |
| POST | /franchise/agreements/{id}/amend | Amend commercial terms of a DRAFT agreement (OCC) | FranchisorOps |
| POST | /franchise/agreements/{id}/activate | Activate a DRAFT agreement (OCC); requires a ready conversion plan and no territory conflict | FranchisorOps |
| POST | /franchise/agreements/{id}/suspend | Suspend an ACTIVE agreement (requires an open default) | FranchisorOps |
| POST | /franchise/agreements/{id}/terminate | Terminate an ACTIVE or SUSPENDED agreement (requires an escalated default); spawns five de-identification tasks and hops to DEIDENTIFYING | FranchisorOps |
| POST | /franchise/agreements/{id}/conversion-plans | Create the conversion plan for a DRAFT agreement | FranchisorOps |
| GET | /franchise/agreements/{id}/conversion-plans | List conversion plans of an agreement (0 or 1 element) | FranchisorOps, FranchiseeAdmin |
| POST | /franchise/conversion-plans/{id}/milestones/complete | Mark one milestone (by sequence index) done | FranchisorOps, FranchiseeAdmin |
| POST | /franchise/agreements/{id}/agent-count-reports | Submit a monthly agent count report | FranchiseeAdmin, FranchisorOps |
| GET | /franchise/agreements/{id}/agent-count-reports | List agent count reports of an agreement | FranchisorOps, FranchiseeAdmin |
| POST | /franchise/agreements/{id}/gci-reports | Submit a monthly GCI report | FranchiseeAdmin, FranchisorOps |
| GET | /franchise/agreements/{id}/gci-reports | List GCI reports of an agreement | FranchisorOps, FranchiseeAdmin |
| POST | /franchise/agreements/{id}/royalty-periods | Assess a month's royalty and ad fund for the agreement | FranchisorOps |
| GET | /franchise/agreements/{id}/royalty-periods | List royalty periods of an agreement | FranchisorOps, FranchiseeAdmin |
| GET | /franchise/agreements/{id}/ad-fund-ledger | List ad fund ledger entries whose agreement is this agreement | FranchisorOps, FranchiseeAdmin |
| POST | /franchise/royalty-periods/{id}/settle | Settle an assessed royalty period | FranchisorOps |
| GET | /franchise/royalty-periods/{id} | Get one royalty period | FranchisorOps, FranchiseeAdmin |
| GET | /franchise/royalty-periods/{id}/ad-fund-ledger | List ad fund ledger entries tied to this period (0 or 1 COLLECT rows) | FranchisorOps, FranchiseeAdmin |
| POST | /franchise/royalty-periods/{id}/waive | Waive an assessed royalty period whose royalty due is zero | FranchisorOps |
| POST | /franchise/agreements/{id}/default-cases | Open a default case on an agreement | FranchisorOps |
| GET | /franchise/agreements/{id}/default-cases | List default cases of an agreement | FranchisorOps, FranchiseeAdmin, BrandAuditor |
| POST | /franchise/default-cases/{id}/start-cure | Move a default OPEN to CURING | FranchisorOps |
| POST | /franchise/default-cases/{id}/escalate | Move a default OPEN or CURING to ESCALATED | FranchisorOps |
| POST | /franchise/default-cases/{id}/resolve | Resolve a default from OPEN, CURING, or ESCALATED | FranchisorOps |
| POST | /franchise/advisory-councils | Seat a franchisee advisory council for a brand | FranchisorOps |
| GET | /franchise/advisory-councils | List councils; brand filter supported | FranchisorOps, FranchiseeAdmin |
| GET | /franchise/brands/{id}/advisory-councils | List councils of a brand | FranchisorOps, FranchiseeAdmin |
| POST | /franchise/advisory-councils/{id}/replace-member | Replace a seated brokerage with another eligible brokerage | FranchisorOps |
| POST | /franchise/ad-fund-proposals | Create a spend proposal in DRAFT | FranchisorOps |
| GET | /franchise/ad-fund-proposals | List proposals with brand/council/status filters | FranchisorOps, FranchiseeAdmin |
| GET | /franchise/ad-fund-proposals/{id} | Get one proposal | FranchisorOps, FranchiseeAdmin |
| POST | /franchise/ad-fund-proposals/{id}/submit | Submit a DRAFT proposal to its council | FranchisorOps |
| POST | /franchise/ad-fund-proposals/{id}/votes | Cast an APPROVE or REJECT vote as a seated council member brokerage | FranchiseeAdmin |
| POST | /franchise/ad-fund-proposals/{id}/execute | Execute an APPROVED proposal; debits the brand ad fund | FranchisorOps |
| POST | /franchise/agreements/{id}/compliance-audits | Schedule a compliance audit on an agreement | BrandAuditor, FranchisorOps |
| GET | /franchise/agreements/{id}/compliance-audits | List audits of an agreement | FranchisorOps, FranchiseeAdmin, BrandAuditor |
| POST | /franchise/compliance-audits/{id}/start | Start a SCHEDULED audit | BrandAuditor |
| POST | /franchise/compliance-audits/{id}/complete | Complete an IN_PROGRESS audit with a finding | BrandAuditor |
| POST | /franchise/compliance-audits/{id}/cancel | Cancel a SCHEDULED audit | BrandAuditor |
| GET | /franchise/agreements/{id}/deidentification-tasks | List de-identification tasks of an agreement | FranchisorOps, FranchiseeAdmin |
| POST | /franchise/deidentification-tasks/{id}/complete | Franchisee marks a task complete (own brokerage only) | FranchiseeAdmin |
| POST | /franchise/deidentification-tasks/{id}/verify | Franchisor verifies a completed task; the last verify closes the agreement | FranchisorOps |
| POST | /franchise/_clock/set_current_utc | Set the logical clock (forward-only); sweeps expired ACTIVE agreements | FranchisorOps |

## 5. Error Code Catalogue

The trigger condition for each error is specified in the narrative of §2 and §3; this table is a reference index only.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED_ROLE | 403 |
| ERR_FORBIDDEN_OWNERSHIP | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_INVALID_REQUEST | 400 |
| ERR_TERRITORY_CONFLICT | 409 |
| ERR_INVALID_TERM | 422 |
| ERR_COUNCIL_INELIGIBLE_MEMBER | 422 |
| ERR_DUPLICATE_REPORT | 409 |
| ERR_DUPLICATE_PERIOD | 409 |
| ERR_GCI_REPORT_MISSING | 422 |
| ERR_INSUFFICIENT_FUND_BALANCE | 422 |
| ERR_DUPLICATE_VOTE | 409 |
| ERR_NOT_COUNCIL_MEMBER | 403 |
| ERR_WAIVE_REQUIRES_ZERO_DUE | 422 |
| ERR_TERMINATION_REQUIRES_ESCALATED_DEFAULT | 422 |
| ERR_SUSPENSION_REQUIRES_OPEN_DEFAULT | 422 |
| ERR_CONVERSION_INCOMPLETE | 422 |
| ERR_MILESTONE_INVALID | 422 |
| ERR_CLOCK_REGRESSION | 422 |
| ERR_AGREEMENT_NOT_LIVE | 409 |
| ERR_DUPLICATE_LICENSE | 409 |
| ERR_BROKERAGE_TERMINATED | 409 |
| ERR_BRAND_OR_BROKERAGE_INACTIVE | 409 |
| ERR_RENEWAL_TARGET_INVALID | 422 |
| ERR_VOTER_IN_DEFAULT | 403 |
| ERR_DEIDENTIFICATION_INCOMPLETE | 422 |
