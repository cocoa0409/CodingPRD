# Exclusive Agency Appointment API — Product Requirements Document

## 1. Introduction

An exclusive agency is the smallest unit of distribution the company owns outright. When a territory is opened, a candidate is recruited, vetted, licensed, and bound by an exclusive agent agreement; everything the agent subsequently writes belongs to the company's book, not to the agent. The Exclusive Agency Appointment API is the system of record for that entire arc — the market-need analysis that justifies opening a territory, the candidate assessment that decides whether to proceed, the appointment and licensing steps that bring an agent into force, the agreement that fixes commission rates across product lines, the marketing spend that supports the office, the team members appointed beneath the agent, and finally the cessation and book-transfer machinery that returns a departing agent's policies to the network.

The operational pain this API addresses is that agency management today is stitched together from spreadsheets, licensing portals, and claims extracts that never reconcile. Book counts, exposure, trailing commission, loss ratio, and valuation are all derived quantities — each one computed from policies, agreements, staff, and claims that change independently — and every organisation that manages them by hand eventually disagrees with itself about what a book is worth. The API therefore treats derived figures as *recomputed* rather than *accumulated*, and pins every rate, cap, threshold, and rounding rule so that two readers of the same book arrive at the same cents.

The service is a REST API mounted under the top-level path `/agency-network`. It exposes the agency roll, the agent roster, policies and their claims, agreements, team staffing, marketing campaigns, license records, and book transfers, together with a periodic operations sweep and a logical clock that make time-dependent term rolls and licensing windows fully deterministic for testing.

## 2. Global Specifications & System-Wide Principles

The rules in this section hold for every endpoint in the API. They cover authentication and role identity, the shape of every response, pagination, record identity, the recomputation model that keeps derived book figures honest, how nested identifiers are resolved, monetary precision, the commission-split ledger invariants, optimistic concurrency, licensing and capacity gates, deterministic time, and the order in which validation failures are reported.

### 2.1. User and Role-Based Access Control

Every request must carry two headers. `X-User-Role` names the acting role and `X-User-ID` identifies the acting party. Either header missing or empty is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). An authenticated request whose role is not permitted for the requested operation — per the role matrix below and the authorized-role column of §4 — is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

Seven roles exist, spelled exactly as follows: `PlatformAdmin`, `AppointingExecutive`, `FieldManager`, `AgencyPrincipal`, `ClaimsAdjuster`, `RegulatoryBoard`, and `StaffMember`.

Identity semantics differ by role. When `X-User-Role` is `PlatformAdmin`, `AppointingExecutive`, `FieldManager`, `ClaimsAdjuster`, or `RegulatoryBoard`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it where a workflow names the acting party, but it is never compared to any entity's `id`. When `X-User-Role` is `AgencyPrincipal`, `X-User-ID` is the `id` of the acting `Agency`; ownership checks on any agency-scoped resource compare that resource's agency foreign key to `X-User-ID`. When `X-User-Role` is `StaffMember`, `X-User-ID` is the `id` of the acting `StaffMember` record, and that role is read-only — it may read its sponsoring agreement and its own staff record and nothing more.

`PlatformAdmin` is the operational administrator: it runs the periodic ops sweep, seeds raw records, controls the logical clock, and reads staff and license records. `AppointingExecutive` approves and rejects appointment applications and governs the agency roll, activating and terminating agencies. `FieldManager` is the field recruiter: it submits and scores applications, mints agents, reads licenses, transitions books, writes agreements, creates policies, and drives policy reassignment. `AgencyPrincipal` owns the agency office and manages its marketing campaigns, team staffing, policy cancellations, and cessation requests. `ClaimsAdjuster` files, settles, resolves, and denies claims. `RegulatoryBoard` posts and reads state license records.

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

List endpoints accept a `limit` query parameter giving the maximum number of records to return; when omitted it defaults to 10, and it is constrained to a minimum of 1 and a maximum of 100. A second query parameter, `offset`, gives the number of records to skip and defaults to 0. Values outside these bounds are rejected rather than clamped.

Unless a more specific ordering is stated, list results are ordered by the resource's creation timestamp in ascending order. Paginated and unpaginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

Most list endpoints also accept optional filter query parameters named after the field being filtered. In practice the filterable identifiers across the API are `status`, `region_code`, `agency_id`, `state_code`, `agent_id`, `book_transfer_id`, `holder_agent_id`, `owner_agency_id`, `from_agency_id`, `to_agency_id`, `successor_agent_id`, `sponsoring_agreement_id`, and `policy_id`; §4 records which collections support which of them.

### 2.4. Resource Identity and Common Record Properties

Every top-level record — `Agency`, `Agent`, `Policy`, `Agreement`, `StaffMember`, `MarketingCampaign`, `Claim`, `BookTransfer`, and `AppointmentApplication` — carries the same four system-managed properties.

- `id` is a server-minted unique identifier formatted as a UUID string with no type prefix and no embedded entity name.
- `created_at` is an ISO 8601 timestamp in UTC with three fractional digits (for example `2025-05-24T10:30:00.123Z`) recording when the record was first created. It is never modified.
- `updated_at` is an ISO 8601 UTC timestamp with three fractional digits recording the last mutation to the record, including mutations to derived fields.
- `version` is a system-managed integer that starts at 1 and increments by one on every modification to the record. It is the anchor for optimistic concurrency control described in §2.9.

The one exception is `LicenseRecord`, which is immutable after posting. A license record carries only `id` and `created_at`; it has neither `updated_at` nor `version`, and no request may supply or expect them.

Any mutation of a derived property — recomputing an agency's exposure, re-deriving a policy's paid claims, refreshing a book transfer's retention — is a mutation of the owning record and therefore advances that record's `updated_at` and increments its `version`. A recompute that a change makes necessary advances the version of every record it rewrites; only a pure read — the performance snapshot, a book-transfer read, and the ops sweep's transaction reads — is catalogue-and-response only, minting no new `version`.

### 2.5. Book Custody, Derived Bookkeeping and Anniversary Terms

The company, not the agent, owns the book. This is why every book-level figure on an `Agency` is derived rather than entered: `book_open_count` counts the agency's policies that are still `OPEN`; `exposure_inforce_cents` sums `annual_premium_cents` across those same open policies; `agency_level_units` counts the agency's `Agreement` records that are in state `ACTIVE`; `annualized_commission_cents` is the commission the agency has earned in its current twelve-month anniversary term; and `allowance_carryover_cents` is rebuilt alongside the marketing allowance ledger; the routine also rebuilds `growth_new_pct`, `performance_status`, `agency_valuation_cents`, `agency_paid_claims_cents`, and `staffing_reimbursement_cents`, and refreshes the marketing pool, its spend and carryover, the three agreement commission lines, and the agreement-level staffing reimbursement out of the same pass. A single reconciliation routine, `recompute_agency`, rebuilds *all* of these from their current children after any write to the agency's policies, agreements, or staff. The rebuild is from source, not incremental: an implementation that adds and subtracts deltas will drift away from the truth after claims are compensated or policies are cancelled.

Reconciliation cascades outward from the entity that changed. Settling a claim is the deepest example: the owning `Policy`'s `paid_claims_cents` is rebuilt from its claims, the agency's `agency_paid_claims_cents` is rebuilt from its policies, `loss_ratio` is rebuilt from paid claims and open exposure, and finally `performance_status` is re-evaluated. A claim that has not yet been compensated contributes nothing to the paid total, so the agency's gross paid claims are always the sum of the compensated `policy_paid_cents` across its claims. Cancelling a policy rebuilds the agency's `book_open_count` and `exposure_inforce_cents`. Terminating a staff member rebuilds `agency_level_units` and then `staffing_reimbursement_cents`. Each hop independently advances the affected record's `updated_at` and increments its `version`.

Term boundaries are explicit. `term_start_date` marks the beginning of the current twelve-month anniversary term; it is set when an agency activates and reset at each ops-run rollover. `ops_run_index` is a monotonic counter that starts at 0 and increments by exactly one per ops run, so the number of sweeps an agency has seen is always observable.

### 2.6. Nested Resource Resolution and Left-to-Right Existence Ordering

Several paths name more than one record — an agency and a campaign, an agent and one of its policies, and so on. When a path carries multiple identifiers, the server resolves them strictly left to right and stops at the first identifier that matches nothing. The canonical ordering across the resource hierarchy is agency, then agent, then agreement, then policy, then claim.

The failure code names the *first* unresolved step, not the last: an unresolvable agency identifier produces `ERR_AGENCY_NOT_FOUND`, an unresolvable agent identifier produces `ERR_AGENT_NOT_FOUND`, an unresolvable agreement identifier produces `ERR_AGREEMENT_NOT_FOUND`, an unresolvable policy identifier produces `ERR_POLICY_NOT_FOUND`, and an unresolvable claim identifier produces `ERR_CLAIM_NOT_FOUND`. All five carry HTTP 404. Consequently a request that names both a non-existent agency and a non-existent campaign under it fails on the agency, and the campaign is never examined.

### 2.7. Monetary Precision and the Allowance Ledger

All monetary amounts in this API are integer cent values exposed as numbers. Derived monetary figures are computed with decimal arithmetic and stored rounded to exactly two decimal places using the round-half-up method — a value whose third decimal is exactly five is rounded away from zero. Rate and ratio fields supplied by the client, such as the per-line rates inside a commission schedule, are preserved at the precision they were supplied with and are not re-quantised.

Two derived figures deviate from the "two decimals" habit in their *type* but not their arithmetic: `appointment_priority` and `loss_ratio` outputs described in §3 are rounded half up at the stated precision, while `appointment_priority` is exposed as a whole integer.

The marketing allowance ledger is the one place where precision and capping interact. The agency's exposure forms a base: the open exposure multiplied by the rate 0.04, rounded half up, capped at 250,000.00 cents. `marketing_allowance_pool_cents` is then that base plus `allowance_carryover_cents`, capped at 400,000.00 cents. `allowance_carryover_cents` is defined as the pool minus `marketing_allowance_spent_cents`, which is itself the sum of `marketing_allowance_cents` over every campaign that has reached `PARTICIPATED` for that agency. The carryover therefore leads the ledger: it is derived from the pool, never added to it as an afterthought. Worked through: an agency with three million cents of open exposure and a prior carryover of 25,000.00 cents reaches a pool of 145,000.00 cents, whereas an implementation that ignores the prior carryover reaches only 120,000.00 cents. The prior carryover is not free-floating state: it is the term-opening allowance balance, a figure the agency opened its current term with. Within a term it changes only at a term rollover, where the term's unused carryover becomes the next term's opening balance; ordinary spend advances `marketing_allowance_spent_cents` and reduces the carryover without feeding back into the pool, so a draw already spent is never absorbed by the pool a second time.

### 2.8. Commission Split Invariants and Chargeback Ledgers

House and sub-producer compensation is governed by a pinned split, not by a negotiated ratio. The split base for an agreement is fixed at 120,000.00 cents. The house half is half of that base, rounded half up. The amount released to a sub-producer is twenty percent of the house half, rounded half up. The house remainder is the house half minus the released amount, rounded half up. The invariant that must hold after any release or chargeback is that the released amount plus the house remainder equals the house half exactly — 12,000.00 plus 48,000.00 equals 60,000.00 in the pinned case. Changing the split base changes both halves but never breaks the invariant.

The released portion is tracked on each policy as `sub_producer_released_commission_cents` — the agency's house half already released to a sub-producer, standing at twenty percent of that half until altered. Resolving a settled claim posts a resolution chargeback against this ledger: the chargeback equals the claim's `policy_paid_cents`, and the ledger becomes the greater of (its previous value minus the chargeback) and zero. The ledger is never permitted to fall below zero, and a partial recovery reduces it by less than the full paid amount.

### 2.9. Optimistic Concurrency Control on Agency and Agent Writes

Writers that mutate a book are expected to have read the book first. Agency-scoped writes that alter the allowance ledger or the agency roll carry `expected_agency_version`, the client's last observed `version` of the target `Agency`. Agent-scoped writes that alter an agent's contractual position carry `expected_agent_version`, the client's last observed `version` of the target `Agent`. When the supplied value does not match the parent record's current `version`, the write is refused with `ERR_STALE_VERSION` (HTTP 412) and no state is changed. This is a pure version check: it does not depend on requests overlapping.

Two writes are explicitly governed by this rule. Campaign participation requires `expected_agency_version`, because a prior participation on the same agency advances the allowance pool the client last observed; a sequential re-send carrying the older version observes the advanced agency `version` and is refused. Agreement transcription requires `expected_agent_version`, so that transcribing into force against an agent whose `version` has advanced since the client last read it is refused under the same semantics.

The same rejection applies to any other write that carries one of these version fields — agency activation carries `expected_agency_version`, and the new-agent book transition carries `expected_agent_version` — so a mismatch there is likewise `ERR_STALE_VERSION` (HTTP 412). Writes that carry neither field perform no version check.

### 2.10. Licensing Currency, Staffing Capacity and Territorial Fit

An agent's `license_status` is one of `NOT_LICENSED`, `LICENSED`, or `EXPIRED`. The value is not chosen by the client: it is set by reading the state board's license record, and a license whose `license_expiry_date` has fallen earlier than the current logical time is `EXPIRED` no matter what it previously read. Every duty that depends on an appointment or on a book transition requires `license_status` to be `LICENSED`; when it is not, the duty is refused with `ERR_LICENSED_REQUIRED` (HTTP 400). This governs agent minting, book transition, cessation, agreement transcription, and team-member appointment alike.

Two capacity gates bound the roll. An agency may carry at most eleven agency-level units before it can absorb another agent; a transition or a team-member appointment targeting an agency already at twelve units is refused with `ERR_AGENCY_STAFFING_CAP` (HTTP 409). Team allocation itself is bounded per member: `allocation_units` must be between 1 and 20 inclusive, with ten units representing one full-time equivalent.

A territorial gate protects the field organisation. A territory classified as a support subtype whose `market_need_score` is at most 40 cannot fit a new appointment, and the assessment that finds this is refused with `ERR_MARKET_NEED_EXISTS` (HTTP 409).

Booked windows are exclusive per owner. A campaign's `start_date`–`end_date` window and a team member's `assignment_start_date`–`assignment_end_date` window are closed intervals, and each must not collide with a sibling window over the same owner. A collision is refused with `ERR_INTERVAL_OVERLAP` (HTTP 409).

### 2.11. The Logical Clock and Deterministic Term Rolls

Time in this API is server-controlled, never wall-clock. On startup the logical clock reads `2026-09-01T00:00:00Z` and the server must not fall back to real wall-clock time before the first clock call. The clock is moved by an administrative capability that accepts a `to_iso8601` instant; issuing it re-evaluates license expiry and any retention or deadline windows that depend on the current instant. Only the clock's instant matters, and any parseable ISO 8601 form is accepted: with or without a trailing `Z`, and an input carrying no offset is read as UTC. A date supplied without a time of day lands at midnight of that day. Every timestamp the server mints — `created_at`, `updated_at`, `appointment_date`, `term_start_date`, `license_verified_at`, `termination_initiated_at` — is read from this logical clock.

Because time is frozen until it is explicitly advanced, term rolls are reproducible: the anniversary term boundary is driven by `term_start_date`, the ops sweep advances `ops_run_index` by one and resets `annualized_commission_cents` to zero at a rollover, and license expiry is decided by comparing `license_expiry_date` against the current logical instant rather than against any external source.

### 2.12. Validation Precedence and Failure Ordering

When a request violates more than one rule, the reported failure is decided by a fixed precedence, evaluated from the lowest number upward. Textual order of the checks in this document does not express precedence, so it is stated here.

Authentication and role checks come first: missing or empty credentials surface as `ERR_UNAUTHENTICATED` (401) before anything else, and a role that is not permitted surfaces as `ERR_UNAUTHORIZED` (403) before any business rule is examined. Existence checks follow, left to right as described in §2.6, and produce the 404 family. State checks come next: a resource not in the state the transition requires yields `ERR_INVALID_STATE` (409), and any attempt to leave a terminal state yields `ERR_ALREADY_TERMINAL` (409). Business-safety gates come after state: licensing (`ERR_LICENSED_REQUIRED`, 400) and the requirement that a sponsoring agreement's owner agent be in a live state (`ERR_SPONSOR_AGREEMENT_NOT_ACTIVE`, 409). Business-constraint checks follow: territorial fit (`ERR_MARKET_NEED_EXISTS`, 409), the staffing cap (`ERR_AGENCY_STAFFING_CAP`, 409), and product-line schedule coverage (`ERR_SCHEDULE_MISSING`, 400). Temporal overlap (`ERR_INTERVAL_OVERLAP`, 409) comes next, then the fiscal gates — `ERR_ALLOWANCE_INSUFFICIENT` (400) and a stale version (`ERR_STALE_VERSION`, 412, which is evaluated before any fiscal computation is attempted). The referential tail is checked last: outstanding held policies (`ERR_HOLDING_POLICIES_REMAIN`, 409), a missing successor (`ERR_NO_SUCCESSOR_AGENT`, 409), and duplicate policy or agency codes (`ERR_DUPLICATE_POLICY`, 409).

## 3. Business Logic & Workflows

### 3.1. Territory Assessment and the Appointment Application Pipeline

A `FieldManager` opens the pipeline by submitting an appointment application for a state, supplying `state_code`, `market_need_score`, `candidate_assessment_score`, `market_odds_score`, and `creation_channel`. The record lands in `SUBMITTED`. `creation_channel` is either `DIGITAL` or `FIELD`, is fixed at creation, and is immutable thereafter. Submission itself applies no territorial fit test; the only territorial refusal in the pipeline is the support-subtype check at assessment time described below.

Scoring is a `FieldManager` action that moves an application from `SUBMITTED` to `SCORED`. The scoring inputs are the three scores supplied at submission; the assessment may also be given a territory subtype on the submission, and re-assessment re-derives the values from those inputs. It recomputes three derived values. A second assessment of an application that is already `SCORED` is accepted and stays `SCORED`; re-assessment is idempotent on the derived values. Assessment of an application in any other state is refused with `ERR_INVALID_STATE` (HTTP 409).

`appointment_priority` is a weighted score: four tenths of `market_odds_score`, plus three tenths of `candidate_assessment_score`, plus three tenths of `market_need_score`, with the weights summing to exactly one. The weighted sum is rounded half up to the nearest whole integer and exposed as an integer between 0 and 100. When two applications produce the same priority, the tie is broken deterministically by `created_at`. An implementation that divides first and rounds last can land differently on exact halves; the pinned behaviour closes the calculation at whole points on the final sum.

`required_action` is decided by an ordered chain of four outcomes, evaluated top to bottom with the first match winning. If `market_odds_score` is below 40, or `candidate_assessment_score` is below 40, the action is `REJECT`. Otherwise, if both scores are strictly greater than 70, the action is `PROCEED`. Otherwise, if either score lies between 60 and 70 inclusive, the action is `MARKET_ANALYSIS_REQUIRED`. In every remaining case the action is `REJECT`. Note the asymmetry the boundaries create: the high band is open, so a score of exactly 70 is not sufficient for `PROCEED` and falls into the middle band, whereas the middle band is closed at both ends.

`application_value_tier` is granted at a single boundary: an `appointment_priority` of at least 80 makes the application `PREMIUM`; anything lower makes it `STANDARD`. A priority of exactly 80 is `PREMIUM`.

One territorial rule can stop an application at assessment time. An application whose `market_need_score` is at most 40 for a territory of the support subtype does not fit that territory, and the assessment is refused with `ERR_MARKET_NEED_EXISTS` (HTTP 409). The subtype is the application's own declared `territory_subtype`, fixed at submission and read case-insensitively; an application declaring no subtype is not of the support subtype, so the gate never fires for it.

Closure of an application belongs to an `AppointingExecutive`. Approval moves a `SCORED` application to `APPROVED` and is permitted only when `required_action` is `PROCEED`; an approval attempted while the action reads anything else is refused with `ERR_INVALID_STATE` (HTTP 409), as is approval of an application that is not `SCORED`. Rejection moves a `SCORED` application to `REJECTED` and records the optional `closure_note` supplied with the request. Both `REJECTED` and `CONSUMED` are terminal, so any later attempt to move an application out of either state is refused with `ERR_ALREADY_TERMINAL` (HTTP 409). Applications are listed and read by `FieldManager` and `AppointingExecutive`, with filtering available on `status` and on the appointed `agent_id`.

### 3.2. Minting, Licensing and the New-Agent Transition onto a Book

Appointment converts a decision into a person. An agent record's lifecycle begins in `CANDIDATE`, the un-minted state it holds before any application has produced it. A `FieldManager` appoints from an `APPROVED` application, which consumes the application — moving it to `CONSUMED` — and mints a new `Agent` in state `APPOINTED`, which is the `CANDIDATE` to `APPOINTED` transition. The new agent carries `full_name`, `state_code`, and `market_need_score` from the application, starts with `is_new_agent` true, and is stamped with `appointment_date` when the agreement later transcribes. The application carries the candidate's name — supplied as `full_name` or under the `applicant_name` alias — and the mint copies whichever was supplied, leaving the agent's name null when neither was. Its `license_status` begins as `NOT_LICENSED`, and its `agency_id` stays unset until a book transition binds it. The minted agent's `id` is written back onto the application as `agent_id`.

Licensing is read, not asserted. Reading an agent's license calls the state board and upserts a `LicenseRecord` capturing `full_name`, `state_code`, `product_lines`, and `license_expiry_date`; it then sets the agent's `license_status` to `LICENSED`, refreshes `license_expiry_date` on the agent, and stamps `license_verified_at` on the agent's agreement with the current logical time. Until that first read, the agreement's `license_verified_at` is null. A license whose `license_expiry_date` has fallen earlier than the current logical instant is `EXPIRED`, and every appointment or book-transition duty is then refused with `ERR_LICENSED_REQUIRED` (HTTP 400).

Moving a new agent onto an agency's book is the `APPOINTED` to `TRANSITIONING` step, and it is gated four ways. The agent must still be `is_new_agent` true. The agent's `license_status` must be `LICENSED`, read against the state `LicenseRecord`. The target agency must be `ACTIVE`. And the target agency's `agency_level_units` must be below twelve; an agency already at twelve is refused with `ERR_AGENCY_STAFFING_CAP` (HTTP 409). On success the agent's `agency_id` is bound to the target agency and the agency's `agency_level_units` is recomputed. The request must carry `expected_agent_version`; a stale value is refused with `ERR_STALE_VERSION` (HTTP 412) before any of the above is evaluated as a success.

Two supporting facts complete the picture. The periodic ops sweep sets an agent's `state_market_need_acknowledged` flag to true whenever the agent's agency reports a `market_need_score` below 40, marking that the low-need condition has been acknowledged. And an administrative seeding capability can mint a raw agent record directly from `full_name`, `state_code`, `license_status`, `is_new_agent`, and `status`, optionally setting `market_need_score` and `license_expiry_date`, bypassing the application pipeline for configuration and test purposes only.

### 3.3. Drafting and Transcribing the Agent Agreement: Commission Schedules

An agreement is the contract that makes an agent productive. A `FieldManager` drafts one against an `agent_id` and an `agency_id`, choosing an `agreement_type` of either `EXCLUSIVE_AGENT` or `TEAM_MEMBER`, and supplying the `commission_schedule`. Drafting moves the agreement from `DRAFT` to `UNDER_REVIEW`. The schedule is the client's number, never the server's: it is an input object giving a new-business rate and a renewal rate for each product line, for example a `{new, renewal}` pair for `AUTO`, for `HOME`, and for `LIFE`. The server never computes or infers these rates.

A schedule must cover all three product lines. If the supplied schedule is missing a `{new, renewal}` pair for `AUTO`, `HOME`, or `LIFE`, both drafting and transcription are refused with `ERR_SCHEDULE_MISSING` (HTTP 400).

Transcription brings the agreement into force, moving it from `UNDER_REVIEW` to `ACTIVE`. It requires the acting agent's `license_status` to be `LICENSED`, the owner agent to be in `TRANSITIONING`, and — for this path — the agreement type to be `EXCLUSIVE_AGENT`. The request carries `expected_agent_version`, and a mismatch with the agent's current `version` is refused with `ERR_STALE_VERSION` (HTTP 412). Transcription stamps `license_verified_at` with the current logical time, sets `appointment_date` on the agent, moves the agent from `TRANSITIONING` to `ACTIVE`, and triggers a cascade of recomputations: the agency's `book_open_count`, `exposure_inforce_cents`, and `annualized_commission_cents`; the agent's `is_new_agent`; and the three commission lines below. The three lines are computed from the agency's book under that agreement's schedule and are written onto each of the agency's agreements, and `annualized_commission_cents` is set to the direct-additions line plus the renewal line.

`direct_additions_commission_cents` aggregates new business. Taking every policy of the agency whose `is_new_business` is true and whose `status` is `OPEN`, ordered by `first_written_at` ascending with `policy_number` ascending breaking any tie, each policy's line commission is its `annual_premium_cents` multiplied by that policy's product-line new-business rate from the agreement's `commission_schedule`, quantised to the cent with round-half-up (a half-cent line rounds away from zero). Each line is rounded *before* summing, and the total is the sum of those rounded lines. Rounding the aggregate once at the end is not equivalent and can drift by a cent whenever a rate is fractional.

`renewal_commission_cents` is the same aggregation over the complementary set: policies of the agency whose `is_new_business` is false and whose `status` is `OPEN`, in the same chronological order with the same tie-break, each line being `annual_premium_cents` multiplied by that product line's *renewal* rate, rounded half up per policy and then summed. A renewal line never uses the new-business rate, and a single blended rate applied across both business types is not equivalent whenever renewal and new rates differ for any line.

`direct_additions_revenue_cents` mirrors the direct-additions commission line: it is the sum, over the agency's new-business `OPEN` policies, of `annual_premium_cents` multiplied by that line's new-business rate, each rounded half up. Renewal business contributes nothing to this figure, and including renewals inflates it.

Finally, `is_new_agent` is a derived recency flag rather than a stored intent: an agent is a new agent for the first 24 months counted from `appointment_date`, and the flag is recomputed whenever the agent changes.

### 3.4. Marketing Allowance and Lead-Program Participation

Each agency funds its own field marketing from a company allowance. An `AgencyPrincipal` creates a campaign by supplying `campaign_type` — one of `LEAD_PROGRAM`, `BRAND`, or `COMMUNITY` — a `marketing_allowance_cents` draw that must be zero or greater, an optimistic `expected_leads` projection, and the `start_date` and `end_date` of the campaign window. The campaign is created in `PLANNED`. Its `participation_posture` is derived from the parent agency's `status` and is one of `OPEN`, `RESTRICTED`, or `FROZEN`; it gates every write to the campaign, and only an `OPEN` posture permits a campaign to be edited, participated, or cancelled. A campaign window that collides with a sibling campaign window over the same agency is refused with `ERR_INTERVAL_OVERLAP` (HTTP 409).

Editing is available while the campaign is still `PLANNED` and the parent agency is `APPROVED` or `ACTIVE`, and only under an `OPEN` posture. The editable fields are `marketing_allowance_cents` and `expected_leads`, both updated in place without leaving `PLANNED`. Cancelling likewise applies to a `PLANNED` campaign and moves it to `CANCELLED`, which is terminal, and debits no allowance: cancelling a planned campaign costs the agency nothing.

Participation is the point at which money actually moves. Moving a campaign from `PLANNED` to `PARTICIPATED` requires an `OPEN` posture and requires that the agency's remaining allowance — its `marketing_allowance_pool_cents` minus its `marketing_allowance_spent_cents` — be at least the campaign's `marketing_allowance_cents`. A draw the pool cannot absorb is refused with `ERR_ALLOWANCE_INSUFFICIENT` (HTTP 400). On success the campaign moves to `PARTICIPATED`, the agency's `marketing_allowance_spent_cents` grows by this campaign's draw, `allowance_carryover_cents` is recomputed, and the agency's `version` advances by one. Each of the agency's agreements carries the recomputed pool, spend and carryover alongside it.

Because participation mutates the agency's pool, it must carry `expected_agency_version`. A request whose version is stale relative to the agency's current `version` is refused with `ERR_STALE_VERSION` (HTTP 412) and the campaign is left untouched.

### 3.5. Team Staffing and Sub-Producer Appointments

An agency's office is staffed by team members appointed beneath a sponsoring agent. An `AgencyPrincipal` nominates a member by supplying `full_name`, `role_title`, `allocation_units`, and the `sponsoring_agreement_id` of the agreement that sponsors the appointment, together with an optional `assignment_start_date` and `assignment_end_date` describing the booked window. The nomination lands in `PENDING`, and `allocated_agent_id` is provisionally set to the sponsor agreement's agent. `allocation_units` must be between 1 and 20 inclusive, where ten units represent one full-time equivalent; a count outside that range, or one not supplied at all, is refused with `ERR_INVALID_ALLOCATION_UNITS` (HTTP 400) before the sponsor and window gates are examined. A booked window that collides with a sibling member's window over the same sponsored agent — closed intervals that overlap, including windows that merely touch at an endpoint — is refused with `ERR_INTERVAL_OVERLAP` (HTTP 409), and this applies at nomination as well as at appointment. A member already `TERMINATED` is disregarded when a new booked window is tested for collision.

The sponsor gate applies to both nomination and appointment. The sponsoring agreement's owner agent must be in a live state — `ACTIVE` or `TRANSITIONING`. A nomination or appointment whose sponsor is not live is refused with `ERR_SPONSOR_AGREEMENT_NOT_ACTIVE` (HTTP 409).

Appointment moves the member from `PENDING` to `ACTIVE` and is permitted only when three conditions hold together: the sponsoring agreement is `ACTIVE`, the sponsoring agreement's owner agent is `ACTIVE`, and the member's `allocated_agent_id` resolves to an agent whose `license_status` is `LICENSED`. A member allocated under a non-licensed agent is refused with `ERR_LICENSED_REQUIRED` (HTTP 400). The member's own state is examined first: appointing a member that is already `TERMINATED` is refused with `ERR_ALREADY_TERMINAL` (409), and appointing a member that is in any other non-`PENDING` state is refused with `ERR_INVALID_STATE` (409); the sponsor and licensing gates are evaluated only for a member still in `PENDING`. At the moment of appointment, `allocated_agent_id` is written with the agent that was allocated, fixing the attribution; the practising agency is read off the member's own `agency_id`. The same agency staffing cap that bounds agent transitions bounds team appointment: an agency already at twelve `agency_level_units` is refused with `ERR_AGENCY_STAFFING_CAP` (HTTP 409). Appointing also recomputes `staffing_reimbursement_cents`.

`staffing_reimbursement_cents` reimburses the agency for its active team, at one cent per allocation unit and capped at 500.00 cents. Formally, take every `StaffMember` under the agency whose `status` is `ACTIVE`, multiply each one's `allocation_units` by 1.00 cent, round each product half up, sum the results, and then cap the *total* at 500.00 cents — the cap is applied once to the sum, not per member. The figure is carried on the owning `Agency` and mirrored onto each of that agency's agreements, so it may be read off either the agency or an agreement under it. Because the reimbursement is driven by headcount state, it is recomputed whenever a staff member activates or terminates.

Termination of a team member is not driven by a principal's request but by the agency's own status changes. When an agency agreement expires or the agency itself terminates, its `ACTIVE` staff members become `TERMINATED`. That termination then feeds a two-hop cascade: first `agency_level_units` is recomputed from the agency's remaining `ACTIVE` agreements, and then `staffing_reimbursement_cents` is recomputed from the agency's current `ACTIVE` team.

A `StaffMember` role exists in the API for read access only. A member identified by `X-User-ID` may read its own staff record and its sponsoring agreement, and nothing else.

### 3.6. Performance Measurement: Growth, Loss Ratio and Agency Valuation

An agency's health is measured on three axes — growth, loss experience, and value — and all three are derived, never entered. An `AppointingExecutive`, `FieldManager`, or `AgencyPrincipal` can read the agency's performance snapshot, which exposes `book_open_count`, `exposure_inforce_cents`, `agency_paid_claims_cents`, `loss_ratio`, `growth_new_pct`, `performance_status`, and `agency_valuation_cents`.

Claims experience accumulates from the bottom up. Each `Policy` carries `paid_claims_cents`, the sum of `policy_paid_cents` across the claims linked to it. Each `Agency` carries `agency_paid_claims_cents`, the sum of `policy_paid_cents` across every claim on any policy whose `owner_agency_id` is that agency, subject to a total cap of 10,000,000.00 cents. The pinned reading is the gross-paid one: the full paid amount counts against the agency, and recoveries are not netted back even after a claim is resolved.

`loss_ratio` expresses those paid claims against the agency's premium base. It is `agency_paid_claims_cents` divided by the agency's open exposure multiplied by the base rate 0.12, all multiplied by 100, and rounded half up. The ratio is considered flagged when it is strictly greater than 70. The pinned basis is paid claims: counting open reserves instead of paid amounts diverges the moment a claim is denied, because a denied claim contributes nothing to the paid total.

`growth_new_pct` compares the agency's current trailing commission against the base it started the term with. It is the agency's `annualized_commission_cents` minus the term's `rolling_base_cents`, divided by that base, multiplied by 100, and rounded half up. The `rolling_base_cents` is the sum of the agency's established book commission over the prior twelve months, snapshotted at `term_start_date`. An agency that has entered no base — a fresh term, or an agency never activated — carries a base of zero, and a zero base yields a `growth_new_pct` of zero rather than a division by zero.

`performance_status` is then assigned by a strictly ordered chain of three outcomes, evaluated top to bottom with the first match winning. If the agency's `loss_ratio` is greater than 70, the status is `AT_RISK`. Otherwise, if `growth_new_pct` is below zero, the status is `BEHIND`. Otherwise the status is `ON_TRACK`. The order matters and is not negotiable: an agency with a loss ratio of 80 and a growth of minus 75 percent is `AT_RISK` and never `BEHIND`, and an implementation that evaluates growth first would mislabel it.

`agency_valuation_cents` prices the book at replacement. It is the maximum of (1,000,000.00 cents plus `annualized_commission_cents` multiplied by 1.5, minus `agency_paid_claims_cents`) and a floor of 2,000,000.00 cents — the floor governs whenever the formula implies less. When the agency's loss ratio exceeds 70 the multiple collapses to 1.0 instead of 1.5, and the floor still governs.

### 3.7. Cessation, Book Transfer and Policy Reassignment

Cessation begins when an `AgencyPrincipal` posts a cessation for an agent, recording the agent's `last_day_iso8601`. The agent must be `ACTIVE`; anything else is refused with `ERR_INVALID_STATE` (HTTP 409). Cessation is itself a licensing-gated duty, so a non-licensed agent is refused with `ERR_LICENSED_REQUIRED` (HTTP 400). On success the agent moves to `PENDING_TERMINATION`, `termination_initiated_at` is stamped on the agreement, the agreement moves to `SUSPENDED`, the book is reclaimed, active agreements are expired, and `termination_value_cents` is recomputed.

Two figures are computed at cessation. `cessation_bonus_cents` rewards tenure: when the agreement is younger than twelve months at the current logical instant the bonus is zero regardless of staffing; otherwise it is ten cents multiplied by the count of `StaffMember` records under the agent's agency whose `status` is `ACTIVE` at that moment, rounded half up — with five active staff that is 50.00 cents. Note that a license that has lapsed to `EXPIRED` forces this bonus to zero on the next cessation.

`contract_value_cents` is the contract value of the book on termination, and it is never negative. It is the greater of zero and the sum of (the agency's `annualized_commission_cents` multiplied by 1.5, rounded half up), plus `cessation_bonus_cents`, minus the agency's `agency_paid_claims_cents`. The multiple is measured against the book's seasoning, with age counted from `appointment_date` to the current logical instant: a book younger than five years uses a 2.0 multiple on the trailing-twelve-month base, because an unseasoned book has not yet matured. The 1.5 multiple belongs to a book seasoned at least five years, a position this API's enforced recency makes unobservable — an agent's new-agent status is already retired past 24 months — so in practice the contract value is always priced at the 2.0 multiple. The floor of zero is applied last, after the bonus is added and the claims are subtracted.

Reassignment is the network's answer to a vacancy. The `PENDING_TERMINATION` to `TRANSITIONING` step is not requested by a person — the periodic ops sweep performs it once at least one candidate agency exists in the agent's own region with `status` `ACTIVE` and `agency_level_units` below twelve. That step recomputes the successor selection and the retention check. Finalization also performs the same promotion itself when the agent is still `PENDING_TERMINATION` and the promotion condition holds, so a reassignment reaches its declared end state even before the next sweep.

Successor selection is scoped to the region and ranked by weight. Its candidate set is every `Agent` whose `status` is `ACTIVE`, whose agency has a `region_code` equal to the ceasing agency's `region_code`, and whose `id` is not the ceasing agent's. If that set is empty the selection raises `ERR_NO_SUCCESSOR_AGENT` (HTTP 409). Candidates are ranked by `agency_level_units` descending, with `created_at` ascending breaking ties; the first candidate wins. `id` is never a tie-break input. The pin matters: an agent already carrying the ceasing book is excluded when a same-region agency agent exists.

Policies move one at a time and then in bulk. Reassigning a single policy supplies a `successor_agent_id`; the policy must currently be held by the ceasing agent and be `OPEN`, and it stays `OPEN` while its `holder_agent_id` moves to the successor and its `owner_agency_id` moves to the successor's agency. The policy's `first_written_at` is preserved unchanged, because the original chronological tie-break key must survive a transfer.

The finalization step converts policy-level reassignment into a completed transition. Every policy still held by the departing agent that is `OPEN` becomes `TRANSFERRED`; the agent's other policies are left as they are. Finalization also re-runs the successor selection, so a finalization for which the same-region `ACTIVE` candidate set is empty is refused with `ERR_NO_SUCCESSOR_AGENT` (HTTP 409). Finalization requires that the departing agent hold no remaining `OPEN` policies: if it does, the request is refused with `ERR_HOLDING_POLICIES_REMAIN` (HTTP 409). Once the last open policy has moved, the agent moves from `TRANSITIONING` to `TERMINATED`, which is terminal. A request made from any other agent state is refused with `ERR_INVALID_STATE` (HTTP 409) or, from a terminal state, with `ERR_ALREADY_TERMINAL` (HTTP 409).

The book transfer record captures the economics of the move. It is posted with `agent_id`, `from_agency_id`, and `to_agency_id`, begins in `PENDING`, and is maintained through `SETTLED` and, on reversal, `REVERSED`. Its `successor_agent_id` is filled by the successor selection above and stays null while the transfer is pending unless the posting request itself named a successor, in which case that successor is recorded at posting and stands. An explicit posting attaches the agent's current policies to the transfer as its transferred book. Three computed counts describe the outcome: `transferred_policy_count` counts the policies this transfer reassigned, `retained_policy_count` counts those still `OPEN` and held by the successor, and `retention_pct` is the retained count divided by the transferred count, multiplied by 100, rounded half up. `retention_met` is true when `retention_pct` is at least 85 — forty-four of fifty retained is 88.00 percent and meets the target. Retention is measured by successor holding, not by agency holding: counting any `OPEN` policy sitting at the agency can inflate the figure once the agent has left.

`settlement_payable_cents` is what the transferring agency receives. The transferred base is the sum over the transferred policies of each policy's `annual_premium_cents` multiplied by 0.10; the transfer commission is that base multiplied by 0.10; and the settlement payable is the transfer commission multiplied by 0.90, rounded half up. When the prior agent terminated for cause — a condition pinned on the transfer record itself at posting — the early-write rule bites: for any policy written less than 24 months before the current logical instant, the transfer commission is *not* payable at all, so that policy contributes nothing to the base used for settlement.

### 3.8. Policy Book Maintenance and Claims Compensation

Policies are the atoms of the book. A `FieldManager` creates one by supplying `policy_number`, `product_line`, `annual_premium_cents`, `is_new_business`, `holder_agent_id`, and `owner_agency_id`. The named owner agency and holder agent are resolved before any other check, left to right: an unknown agency yields `ERR_AGENCY_NOT_FOUND` (404) and an unknown holder agent yields `ERR_AGENT_NOT_FOUND` (404). `product_line` is `AUTO`, `HOME`, or `LIFE`; `is_new_business` is true for first-year business and false for renewal. A policy's `status` is one of `OPEN`, `LAPSED`, `CANCELLED`, or `TRANSFERRED`: a newly created policy starts `OPEN`, `LAPSED` marks a policy whose premium lapsed without a cancellation, and `CANCELLED` and `TRANSFERRED` are the terminal outcomes described below. `policy_number` must be unique across all policies, and a duplicate is refused with `ERR_DUPLICATE_POLICY` (HTTP 409) — the same code covers a duplicate `agency_code` at agency creation. Creating or cancelling a policy recomputes the owning agency's `book_open_count` and `exposure_inforce_cents`.

Cancellation is an `AgencyPrincipal` action that moves an `OPEN` policy to `CANCELLED`. `CANCELLED` and `TRANSFERRED` are both terminal for a policy, so any transition out of either is refused with `ERR_ALREADY_TERMINAL` (HTTP 409), and a transition attempted from a state the move does not accept is refused with `ERR_INVALID_STATE` (HTTP 409).

A `ClaimsAdjuster` files a claim against a policy by supplying `policy_id` and `claim_amount_cents`, the gross reserve. The claim opens in `OPEN` with `policy_paid_cents` as yet unset, and every claim is filed `OPEN` regardless of its policy's state or a prior claim on the same policy. Three actions resolve it.

Settling moves the claim from `OPEN` to `PAID` and sets `policy_paid_cents` to the lesser of the reserve `claim_amount_cents` and eighty percent of the policy's `annual_premium_cents`, rounded half up to the cent — the paid amount can therefore differ from the reserve because of the deductible structure. Settlement then runs the deepest cascade in the system: the owning policy's `paid_claims_cents` is rebuilt from its claims, the agency's `agency_paid_claims_cents` is rebuilt from its policies, the agency's `loss_ratio` is rebuilt from paid claims and open exposure, and the agency's `performance_status` is re-evaluated.

Denying moves the claim from `OPEN` to `DENIED` and sets `policy_paid_cents` to zero, then re-evaluates the same chain — loss ratio, then termination value, then agency valuation. Denial is terminal, so a denied claim can be neither settled nor resolved.

Resolving moves a `PAID` claim back to `OPEN` and posts a resolution chargeback. The chargeback equals the claim's `policy_paid_cents`; the policy's `sub_producer_released_commission_cents` ledger is reduced by that amount, floored at zero. The cascade then recomputes the agency's loss ratio, then the agreement's `termination_value_cents`, then the agency's valuation.

The periodic ops sweep provides a fourth path: it shelf-reopens a `PAID` claim whose policy has been restored, returning it to `OPEN` and setting `policy_paid_cents` to zero, and recomputing the agency's loss ratio and expiration posture. The sweep is deliberately narrow: a `PAID` claim whose policy was never restored — including one whose policy has simply stayed `OPEN` — is left untouched by the sweep, so an ordinary sweep never zeroes an already-settled claim. A claim whose policy is no longer `OPEN` is likewise left alone.

### 3.9. Agency Activation, Termination and the Periodic Ops Sweep

An agency begins life as a territory decision. An `AppointingExecutive` creates it with a unique `agency_code`, a display `name`, the `region_code` that will later drive successor ranking, and a `market_need_score` between 0 and 100. Each of those four fields is a required part of the create input, and a create that omits any of them is refused rather than stored. It starts in `APPROVED`, and `recompute_agency` runs against it immediately.

Activation moves an `APPROVED` agency to `ACTIVE`. It stamps `term_start_date` with the current logical instant and resets `ops_run_index` to zero, beginning the first twelve-month anniversary term. The request carries `expected_agency_version`, and a stale value is refused with `ERR_STALE_VERSION` (HTTP 412).

Termination moves an `ACTIVE` agency to `TERMINATED`, which is terminal. It is permitted only once every agent contracted to the agency has a `status` of `PENDING_TERMINATION` or `TERMINATED`; an agency still carrying a live agent is refused with `ERR_INVALID_STATE` (HTTP 409). Termination cascades in two directions: every `StaffMember` under the agency becomes `TERMINATED`, which in turn recomputes the agency's `agency_level_units` and then its `staffing_reimbursement_cents`; and every `MarketingCampaign` under the agency becomes `CANCELLED`.

The periodic ops sweep is the agency roll's heartbeat, run by a `PlatformAdmin` or an `AppointingExecutive`. A sweep is accepted only for an agency that is `ACTIVE`: a request against a terminal agency is refused with `ERR_ALREADY_TERMINAL` (409), and one against an agency that is not yet `ACTIVE` (for example `APPROVED`) is refused with `ERR_INVALID_STATE` (409). Each run increments `ops_run_index` by one, so the counter always records how many sweeps the agency has seen. A run rolls the anniversary term when the term boundary is reached, resetting `annualized_commission_cents` to zero at the rollover so the new term starts from a clean trailing figure; the term's unused allowance carryover becomes the following term's opening balance, and `rolling_base_cents` resets to zero alongside the trailing commission. A run expires active agreements whose sponsors can no longer support them, and it sweeps license expiries: when an agent's `license_status` is anything other than `LICENSED`, the sponsoring agreement suspends, the agent moves to `PENDING_TERMINATION`, and the agency's `ACTIVE` staff members become `TERMINATED`. A run shelf-reopens settled claims as described in §3.8, and it recomputes `performance_status` and `agency_valuation_cents` for every `ACTIVE` agency. It also sets `state_market_need_acknowledged` on agents whose agency `market_need_score` is below 40.

Two administrative capabilities round out the lifecycle. The logical clock is set through a `PlatformAdmin` capability that accepts a `to_iso8601` instant; advancing the clock re-evaluates license expiry and any retention or deadline windows; it also refreshes each agent's recency flag, re-derives every book transfer's retention and settlement against the new instant, and cuts a termination value on each agreement. It is the only thing that makes time move: on startup the clock reads `2026-09-01T00:00:00Z` and the server must not fall back to real wall-clock time before the first call. Separately, a `PlatformAdmin` test-driving capability posts a trailing-twelve-month commission settlement into an agency's anniversary term by accepting an `annualized_commission_cents` value, setting that figure on the agency directly and recomputing its valuation — this lets the trailing-commission inputs be established without a full year of policy activity. A diagnostic envelope-echo capability and the raw-agent seeding capability described in §3.2 exist alongside it for scaffolding and testing only. A `RegulatoryBoard` posts a state license record — carrying `agent_id`, `full_name`, `state_code`, `product_lines`, and `license_expiry_date` — which upserts the agent's license record; a suspension posted this way surfaces on the sponsoring agreement's next ops sweep as a suspended agency agreement.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource, or add a distinct new resource to a collection, return `201 Created`. Operations that modify an existing resource return `200 OK`; the one exception in this API is the cancellation of a planned marketing campaign, which returns `204 No Content`. The table below lists the HTTP contract only — request bodies, response shapes, side effects, and the validation rules that guard each operation are specified in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/agency-network/_clock/set_current_utc` | Advance the logical clock to a supplied instant | PlatformAdmin |
| POST | `/agency-network/_inject/agent` | Seed a raw agent record for configuration and testing | PlatformAdmin |
| GET | `/agency-network/_envelopes/echo` | Diagnostic echo of the response envelope | PlatformAdmin |
| POST | `/agency-network/agencies` | Create an agency in APPROVED status | AppointingExecutive |
| GET | `/agency-network/agencies` | List agencies | AppointingExecutive, FieldManager, AgencyPrincipal |
| GET | `/agency-network/agencies/{id}` | Read one agency | AppointingExecutive, FieldManager, AgencyPrincipal |
| POST | `/agency-network/agencies/{id}/activate` | Activate an approved agency | AppointingExecutive |
| POST | `/agency-network/agencies/{id}/terminate` | Terminate an agency once all its agents have ceased | AppointingExecutive |
| POST | `/agency-network/agencies/{id}/run_ops` | Run the periodic agency operations sweep | PlatformAdmin, AppointingExecutive |
| GET | `/agency-network/agencies/{id}/performance` | Read the agency performance snapshot | AppointingExecutive, FieldManager, AgencyPrincipal |
| POST | `/agency-network/agencies/{id}/marketing-campaigns` | Create a marketing campaign under the agency | AgencyPrincipal |
| GET | `/agency-network/agencies/{id}/marketing-campaigns` | List the agency's marketing campaigns | AgencyPrincipal, FieldManager, AppointingExecutive |
| GET | `/agency-network/agencies/{id}/marketing-campaigns/{cid}` | Read one campaign | AgencyPrincipal, FieldManager, AppointingExecutive |
| PUT | `/agency-network/agencies/{id}/marketing-campaigns/{cid}` | Update an editable campaign | AgencyPrincipal |
| POST | `/agency-network/agencies/{id}/marketing-campaigns/{cid}/participate` | Participate a campaign, drawing down the allowance pool | AgencyPrincipal |
| DELETE | `/agency-network/agencies/{id}/marketing-campaigns/{cid}` | Cancel a planned campaign | AgencyPrincipal |
| POST | `/agency-network/appointment-applications` | Submit an appointment application | FieldManager |
| GET | `/agency-network/appointment-applications` | List appointment applications | FieldManager, AppointingExecutive |
| GET | `/agency-network/appointment-applications/{id}` | Read one application | FieldManager, AppointingExecutive |
| POST | `/agency-network/appointment-applications/{id}/assess` | Score an application and derive its priority, action and tier | FieldManager |
| POST | `/agency-network/appointment-applications/{id}/approve` | Approve a scored application | AppointingExecutive |
| POST | `/agency-network/appointment-applications/{id}/reject` | Reject a scored application | AppointingExecutive |
| POST | `/agency-network/appointment-applications/{id}/appoint` | Mint the agent from an approved application | FieldManager |
| GET | `/agency-network/agents` | List agents | FieldManager, AppointingExecutive, AgencyPrincipal |
| GET | `/agency-network/agents/{id}` | Read one agent | FieldManager, AppointingExecutive, AgencyPrincipal |
| POST | `/agency-network/agents/{id}/read-license` | Read the agent's license from the state board | FieldManager, PlatformAdmin |
| POST | `/agency-network/agents/{id}/transition-book` | Transition a new agent onto an agency's book | FieldManager |
| POST | `/agency-network/agents/{id}/cessation` | Post the cessation of an active agent | AgencyPrincipal |
| POST | `/agency-network/agents/{id}/policies/{pid}/cessation` | Reassign one policy of a ceasing agent | FieldManager |
| POST | `/agency-network/agents/{id}/complete-reassignment` | Finalize reassignment once the agent holds no open policies | FieldManager |
| GET | `/agency-network/agents/{id}/staff` | List the team members allocated to an agent | AppointingExecutive, FieldManager, AgencyPrincipal |
| POST | `/agency-network/agents/{id}/book-transfer` | Post a book transfer for a transitioning agent | AgencyPrincipal, FieldManager |
| GET | `/agency-network/agents/{id}/book-transfers` | List the book transfers attached to an agent | AgencyPrincipal, FieldManager, PlatformAdmin |
| POST | `/agency-network/agreements` | Draft an agreement for an agent | FieldManager |
| GET | `/agency-network/agreements` | List agreements | FieldManager, AppointingExecutive, AgencyPrincipal |
| GET | `/agency-network/agreements/{id}` | Read one agreement | FieldManager, AppointingExecutive, AgencyPrincipal, StaffMember |
| POST | `/agency-network/agreements/{id}/transcribe` | Transcribe an agreement into force | FieldManager |
| POST | `/agency-network/staff` | Nominate a team member under a sponsoring agreement | AgencyPrincipal |
| GET | `/agency-network/staff` | List team members | AgencyPrincipal, FieldManager, PlatformAdmin |
| GET | `/agency-network/staff/{id}` | Read one team member | AgencyPrincipal, FieldManager, PlatformAdmin |
| POST | `/agency-network/staff/{id}/appoint` | Appoint a nominated team member | AgencyPrincipal |
| POST | `/agency-network/policies` | Create a policy on an agent's book | FieldManager |
| GET | `/agency-network/policies` | List policies | FieldManager, AgencyPrincipal, ClaimsAdjuster |
| GET | `/agency-network/policies/{id}` | Read one policy | FieldManager, AgencyPrincipal, ClaimsAdjuster |
| POST | `/agency-network/policies/{id}/cancel` | Cancel an open policy | AgencyPrincipal |
| POST | `/agency-network/claims` | File a claim against a policy | ClaimsAdjuster |
| GET | `/agency-network/claims` | List claims | ClaimsAdjuster, AgencyPrincipal |
| GET | `/agency-network/claims/{id}` | Read one claim | ClaimsAdjuster, AgencyPrincipal |
| POST | `/agency-network/claims/{id}/settle` | Settle an open claim | ClaimsAdjuster |
| POST | `/agency-network/claims/{id}/resolve` | Re-open a paid claim and post a resolution chargeback | ClaimsAdjuster |
| POST | `/agency-network/claims/{id}/deny` | Deny an open claim | ClaimsAdjuster |
| POST | `/agency-network/license-records` | Post a state-board license record | RegulatoryBoard |
| GET | `/agency-network/license-records` | List license records | RegulatoryBoard, PlatformAdmin |
| GET | `/agency-network/agencies/{id}/policies` | List the policies booked under an agency | AppointingExecutive, FieldManager, AgencyPrincipal, ClaimsAdjuster |
| GET | `/agency-network/agencies/{id}/agents` | List the agents contracted to an agency | AppointingExecutive, FieldManager, AgencyPrincipal |
| GET | `/agency-network/book-transfers` | List book transfers | AppointingExecutive, FieldManager, AgencyPrincipal, PlatformAdmin |
| GET | `/agency-network/book-transfers/{id}` | Read one book transfer | AppointingExecutive, FieldManager, AgencyPrincipal, PlatformAdmin |
| POST | `/agency-network/agencies/{id}/book-settlement` | Post a trailing-twelve-month commission settlement into the agency's term | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_AGENCY_NOT_FOUND` | 404 Not Found |
| `ERR_AGENT_NOT_FOUND` | 404 Not Found |
| `ERR_AGREEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_POLICY_NOT_FOUND` | 404 Not Found |
| `ERR_CLAIM_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ALREADY_TERMINAL` | 409 Conflict |
| `ERR_LICENSED_REQUIRED` | 400 Bad Request |
| `ERR_SPONSOR_AGREEMENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_MARKET_NEED_EXISTS` | 409 Conflict |
| `ERR_AGENCY_STAFFING_CAP` | 409 Conflict |
| `ERR_SCHEDULE_MISSING` | 400 Bad Request |
| `ERR_INTERVAL_OVERLAP` | 409 Conflict |
| `ERR_ALLOWANCE_INSUFFICIENT` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_HOLDING_POLICIES_REMAIN` | 409 Conflict |
| `ERR_NO_SUCCESSOR_AGENT` | 409 Conflict |
| `ERR_DUPLICATE_POLICY` | 409 Conflict |
| `ERR_INVALID_TERRITORY` | 400 Bad Request |