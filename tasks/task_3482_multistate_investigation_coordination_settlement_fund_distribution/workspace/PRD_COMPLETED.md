# Multistate Settlement Coordination API — Product Requirements Document

## 1. Introduction

When dozens of state attorneys general join forces against a national company, the coordination problem becomes as formidable as the underlying legal matter. Offices that answer to different governors, legislatures, and appropriations processes must form an executive committee, shield their shared work product behind common interest agreements, issue investigative demands under each state's own authority, negotiate a single settlement with national reach, divide the money fairly, pay identified consumers, and then police the defendant's conduct for years afterward. Each of those steps is a place where the effort can stall, leak, or be challenged — and each produces records that courts, auditors, and legislatures will later scrutinize.

This document specifies the Multistate Settlement Coordination API, the system of record for that entire lifecycle. The API tracks state attorney general offices and their legislative appropriation rules; investigations that advance through clearly separated phases; participations that record each office's invitation, common interest agreement execution, committee designation, and withdrawal; investigative demands and the defendant's negotiated consolidated responses to them; settlement term sheets whose negotiation cycles, sign-on campaigns, and executions are governed by explicit quorum and deadline rules; allocation lines that divide the executed fund among locked-in states; disbursements subject to per-state appropriation controls; consumer restitution claims with pro-rata payout administration; and multi-period compliance monitoring whose breach findings can freeze money mid-stream and whose clean completion closes the matter for good.

A deliberate segregation of duties runs through the design: no single role can propose terms, counter them, execute the settlement, certify a disbursement, and release the funds. Committee coordination, lead-state advocacy, defendant negotiation, fund administration, legislative certification, and compliance monitoring are separate operational capacities, and the API enforces that separation on every write.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. All resources are mounted under the `/multistate` path prefix, with exactly one exception: the logical-clock endpoint described in §2.4, which lives outside that prefix.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Every request must carry `X-User-Role`, naming one of the seven declared roles, and — whenever the named role is entity-backed — `X-User-ID`, identifying the specific acting entity. A request whose `X-User-Role` header is missing or names no declared role, or whose `X-User-ID` is missing or empty although the named role is entity-backed, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted on the target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

The seven roles, spelled exactly as the API recognizes them, are:

- `CommitteeChair` — the executive committee coordinator who runs office registration, committee formation, phase advancement, sign-on opening, settlement execution, and monitoring period scheduling. When `X-User-Role` is `CommitteeChair`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- `LeadStateAG` — a user of an attorney general office that holds a `LEAD`, `ACTIVE` participation in the relevant investigation. When `X-User-Role` is `LeadStateAG`, `X-User-ID` is the `id` of the acting `StateOffice`; ownership checks on any resource that references a `StateOffice` compare the resource's office foreign-key field to `X-User-ID`.
- `ParticipatingStateAG` — a user of a member (non-lead) participating state's attorney general office. When `X-User-Role` is `ParticipatingStateAG`, `X-User-ID` is likewise the `id` of the acting `StateOffice`, and ownership checks compare resource office fields to it.
- `DefendantCounsel` — outside counsel for the investigation target, who negotiates consolidated responses and settlement terms and funds the executed settlement. When `X-User-Role` is `DefendantCounsel`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- `FundAdministrator` — the settlement fund administrator, who registers and validates claimants, computes restitution, and releases certified disbursements. When `X-User-Role` is `FundAdministrator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- `StateLegislature` — the legislative appropriations authority of a state, which certifies disbursements for its own state only. When `X-User-Role` is `StateLegislature`, `X-User-ID` is the `id` of the certifying `StateOffice`, and ownership checks compare the target disbursement's office to it.
- `ComplianceMonitor` — the independent compliance monitor, who files per-term findings in monitoring periods. When `X-User-Role` is `ComplianceMonitor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.

Beyond role admission, entity-backed callers face an ownership check on office-scoped operations: executing a common interest agreement, withdrawing a participation, issuing a demand, recording a sign-on decision, requesting a disbursement, and certifying a disbursement each require `X-User-ID` to equal the `state_office_id` of the office that owns the target resource; lead-gated operations (proposing or revising a settlement, accepting a consolidated response) additionally require that the caller's office hold a `LEAD` and `ACTIVE` participation in the relevant investigation. A caller failing this check is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). The `CommitteeChair`, whose identity is opaque, may perform a withdrawal on any office's behalf and is exempt from office-ownership comparison. All read endpoints are shared: every one of the seven roles may call any GET endpoint.

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

Endpoints that return lists of resources are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10 when omitted, accepts a minimum of 1, and is capped at a maximum of 100. The `offset` parameter sets the number of items skipped before the page begins and defaults to 0. A non-integer `limit` or `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400); an integer `limit` outside the 1–100 range is clamped to the nearest bound rather than rejected, and a negative `offset` is likewise clamped to 0.

Unless otherwise specified, every list endpoint returns its resources sorted by `created_at` in ascending order — oldest first. Resources sharing a `created_at` — common, since the logical clock moves only when set — are ordered by creation sequence, never by resource `id`.

List responses carry four pagination fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`, where `total_count` reports the full size of the underlying collection and `has_more` indicates whether further items exist beyond the returned page.

### 2.4. Logical Time and the System Clock

Every deadline, window, and timestamp rule in this API reads a server-held **logical clock**, never the wall clock. Before any test-driving call, the logical clock's value is exactly `2026-09-01T00:00:00Z`. The sign-on deadline, the legislative certification window, the claim window, and every monitoring period window are all evaluated against this logical time, as are all recorded timestamps such as `invited_at`, `executed_at`, and `decided_at`.

An administrative, test-driving capability advances the clock: it is the one endpoint mounted outside the `/multistate` prefix, at `POST /_clock/set_current_utc`, and it is restricted to the `CommitteeChair` role. The request body carries a single field, `to_iso8601`, an ISO 8601 UTC timestamp to which the clock is set; a value carrying an explicit offset is normalized to UTC, a value carrying no offset is read as UTC, and an unparseable value is rejected with `ERR_INVALID_REQUEST` (HTTP 400). The endpoint responds with HTTP 200 and a body whose `data` is an object containing `current_utc`, a string echoing the clock's new value. No other endpoint reads or writes the clock, and no business operation ever consults wall-clock time.

### 2.5. Common Resource Properties and Optimistic Concurrency Control

Every resource in the API — state offices, investigations, participations, demands, consolidated responses, settlements, allocation lines, disbursements, claimants, and monitoring periods — shares four system-managed properties. The `id` is a server-minted UUID with no type prefix. The `created_at` and `updated_at` timestamps are ISO 8601 UTC strings rendered with three fractional digits; `created_at` is fixed at creation while `updated_at` is refreshed on every mutation. The `version` is an integer that starts at 1 on creation and increments by exactly 1 on every mutation of the resource, whether the mutation came from a client request or from an automatic server-side cascade.

Three write operations participate in optimistic concurrency control, and each names its own required version field. Countering a settlement and revising a settlement each require the request body to carry `expected_settlement_version`, holding the caller's last observed `version` of the target settlement; if the settlement's current `version` has advanced past that value — because a counter or revise has already landed since the caller last read it — the write is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the caller from overwriting negotiation state it has not observed. Updating a state office requires `expected_state_office_version` in the same fashion: a mismatch with the office's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412), since allocation-relevant fields such as `population` and `harm_measure_cents` may have changed underneath the caller. No endpoint other than these three accepts a version field.

### 2.6. Monetary Precision and Basis-Point Arithmetic

All money in the system is carried as integer cents; all allocation weights are carried as integer basis points, and the weights of the allocation lines belonging to one settlement always sum to exactly 10000 basis points. Two rounding disciplines appear, and each calculation states which one it uses. Where a rule calls for rounding half up — the lead-cost computation and the sign-on quorum ratio — a fractional result of one half or greater rounds up to the next integer, and anything smaller rounds down. Where a rule calls for a per-recipient floor — allocation line shares and claimant payouts — each recipient's amount is rounded down to a whole cent, and the leftover cents are then distributed one cent at a time in a pinned, deterministic order stated with the rule; ties are never broken by resource `id`. Wherever a rule's pinned tie-break timestamp is itself identical across recipients — common, since the logical clock moves only when set — the remaining order is the creation sequence of the underlying records. Integer counts (committee quorum, negotiation rounds, breach counts) use inclusive boundaries wherever a threshold is stated as "at least".

### 2.7. Provisional versus Final Computation Variants

Settlement economics are computed twice under the same formulas but with different inclusion sets and timing, and the PRD refers to these as the **provisional variant** and the **final variant** throughout. The provisional variant runs when a settlement is proposed, and again when a revise supplies a new total: it evaluates the lead-cost and distributable-pool formulas and the weight-normalization formula over the investigation's `ACTIVE` participations at proposal time, reading live state-office registry values, and stores its outputs on the settlement as `provisional_distributable_cents` and `provisional_weight_bps_by_state` (a map from state code to normalized basis points). When the provisional weight normalization deals out its remainder basis points among equal raw values, ties are broken by participation `invited_at` ascending — the earliest-invited office first — and never by id. The provisional variant creates no allocation lines and locks nothing. The final variant runs only at settlement execution: it evaluates the same formulas over the locked sign-on set alone — so states that declined or lapsed are excluded and their weight is redistributed among the locked states — using per-state basis values snapshotted at execution time into each line's `basis_value_snapshot`, and it persists `distributable_cents` and `lead_cost_cents` while creating one allocation line per locked state. Whenever the participant set or the registry values changed between proposal and execution, the two variants legitimately produce different per-state weights.

### 2.8. Validation Ordering and Nested Resource Resolution

Every request is evaluated against a fixed ladder of checks, and the first failure wins — no later check runs once an earlier one has rejected the request. The rungs, in order, are:

1. **Authentication** — the role header must name a declared role and the identity header must be present for entity-backed roles (`ERR_UNAUTHENTICATED`).
2. **Role authorization** — the caller's role must be permitted on the endpoint (`ERR_UNAUTHORIZED_ROLE`).
3. **Body schema** — required fields must be present, types must be valid, enum members must be among the declared values, and extraneous fields are ignored, whether they name ids or anything else (`ERR_INVALID_REQUEST`).
4. **Path existence** — path identifiers are resolved left to right along the URL hierarchy, and an unresolvable segment yields the not-found error of its own resource type: `ERR_STATE_OFFICE_NOT_FOUND` under a state-office path, `ERR_INVESTIGATION_NOT_FOUND` under an investigation path, `ERR_PARTICIPATION_NOT_FOUND` under a participation path, `ERR_RESPONSE_NOT_FOUND` under a consolidated-response path, `ERR_SETTLEMENT_NOT_FOUND` under a settlement path, `ERR_ALLOCATION_LINE_NOT_FOUND` under an allocation-line path, `ERR_DISBURSEMENT_NOT_FOUND` under a disbursement path, `ERR_CLAIMANT_NOT_FOUND` under a claimant path, and `ERR_MONITORING_PERIOD_NOT_FOUND` under a monitoring-period path (all HTTP 404). A missing parent is reported before any child segment is examined.
5. **Entity-backed ownership** — office-scoped and lead-gated writes compare `X-User-ID` to the owning office (`ERR_NOT_RESOURCE_OWNER`).
6. **State and phase gates** — the investigation's phase must admit the operation (`ERR_INVALID_PHASE`), and the target resource's own state machine must admit the trigger (`ERR_INVALID_STATE`, with the more specific `ERR_PARTICIPATION_INACTIVE`, `ERR_LINE_NOT_DISBURSABLE`, `ERR_SETTLEMENT_NOT_FUNDED`, `ERR_RESTITUTION_LOCKED`, and `ERR_SIGNED_STATE_CANNOT_WITHDRAW` where those named conditions apply).
7. **Optimistic concurrency** — a stale expected version is rejected (`ERR_STALE_VERSION`).
8. **Compliance hold** — an active hold blocks disbursement creation and release (`ERR_COMPLIANCE_HOLD_ACTIVE`).
9. **Referential integrity** — cross-resource payload references must resolve (`ERR_NOT_A_PARTICIPANT`, `ERR_RESPONSE_DEMANDS_INVALID`, `ERR_INVALID_TERM_INDEX`).
10. **Temporal windows** — deadlines and windows are enforced (`ERR_SIGN_ON_WINDOW_CLOSED`, `ERR_CERTIFICATION_WINDOW_CLOSED`, `ERR_CLAIM_WINDOW_CLOSED`, `ERR_LEAD_WINDOW_OVERLAP`, `ERR_PERIOD_NOT_CONTIGUOUS`, `ERR_PERIOD_NOT_STARTED`).
11. **Business constraints** — uniqueness, quorum, and cap rules (`ERR_DUPLICATE_PARTICIPATION`, `ERR_DUPLICATE_SIGN_ON`, `ERR_DUPLICATE_FINDING`, `ERR_NEGOTIATED_SHARES_INVALID`, `ERR_ACTIVATION_QUORUM_MISSING`, `ERR_NEGOTIATION_EXHAUSTED`, `ERR_QUORUM_NOT_MET`, `ERR_CIA_TIER_INSUFFICIENT`, `ERR_PERIOD_LIMIT_REACHED`, `ERR_NO_ACCEPTED_RESPONSE`, `ERR_NO_AGREED_SETTLEMENT`).
12. **Fiscal bounds** — money limits (`ERR_DEPOSIT_EXCEEDS_TOTAL`, `ERR_INSUFFICIENT_FUND_BALANCE`, `ERR_AMOUNT_EXCEEDS_REMAINING`, `ERR_VALIDATION_EXCEEDS_CLAIM`, `ERR_USE_CODE_NOT_PERMITTED`).

The practical consequence of the ordering is that, for example, a request with a well-formed body but a nonexistent parent id fails at rung 4 and never reaches the state checks; a stale-version rejection at rung 7 masks any temporal or fiscal problem the same request might also have had.

### 2.9. Hierarchical Cascades and Automatic Transitions

The server maintains consistency across the aggregate hierarchy without waiting for explicit client requests on the affected resources. When a single operation mutates more than one entity, every cascade is applied atomically as part of that operation, and every resource the cascade touches has its `updated_at` refreshed and its `version` incremented. The automatic transitions a client can observe are: accepting a consolidated response folds every demand it lists into the consolidated state; a defendant counter bounces the investigation's phase backward, and a lead-office revise returns it forward again; a successful settlement execution locks the signed sign-on entries, lapses the silent ones, and creates the allocation lines; a collapsed settlement returns the investigation to negotiation and clears the investigation's active-settlement pointer; the first disbursement release moves the settlement's fund into disbursing, and from there the moment every allocation line of a settlement reaches a terminal state the fund becomes fully disbursed (a fund that never entered `DISBURSING` does not jump straight to `DISBURSED` even if every line reverts); a breach-escalated monitoring close raises the settlement's compliance hold and freezes its certified disbursements, while a spotless close can cure the hold and unfreeze them; and the final monitoring period closing clean against a fully disbursed fund closes out the settlement and the investigation together. §3 describes each cascade beside the workflow that triggers it.

## 3. Business Logic & Workflows

This section walks the lifecycle of a multistate matter in the order an executive committee experiences it: forming the committee, running discovery, negotiating, collecting sign-ons, executing and funding, disbursing under appropriation rules, paying consumers, and monitoring compliance through closure.

### 3.1. Office Registry and Executive Committee Formation

Before any matter exists, the `CommitteeChair` registers each participating attorney general's office. Registration supplies a two-letter `state_code`, an integer `population`, an integer `harm_measure_cents` estimating in-state harm in cents, and an `appropriation_rule` of `PREAPPROPRIATED`, `CERTIFICATION_REQUIRED`, or `GENERAL_FUND_ONLY` describing how that state's legislature controls use of proceeds. The `state_code` is unique across all registered offices: a duplicate registration is rejected with `ERR_INVALID_REQUEST` (HTTP 400). The population and harm figures are not bookkeeping trivia — they are the raw inputs to two of the three allocation bases a settlement may later adopt — so the chair may correct them by updating the office, a write that carries `expected_state_office_version` and is rejected with `ERR_STALE_VERSION` when the office's `version` has advanced since the caller last read it. The updatable fields are `population`, `harm_measure_cents`, and `appropriation_rule`; `state_code` is immutable, and a `state_code` supplied in an update is ignored. An update that changes none of the three still increments `version` by 1 and refreshes `updated_at`. Updates increment the office's `version` by 1 and never retroactively alter allocation snapshots already captured at a settlement's execution.

A new investigation is born in `DRAFT` phase with a `title`, a `target_name` naming the investigated company, and a `summary` of the matter; its `phase` field moves through `DRAFT`, `OPEN`, `DISCOVERY`, `NEGOTIATION`, `SETTLEMENT_PENDING`, `SETTLED`, `MONITORING`, and `CLOSED` over its life. The chair builds the executive committee by inviting offices: each invitation names a `state_office_id` and creates a participation row in `INVITED` status with `invited_at` set to the current logical time, its `investigation_id` pointing at the matter, its `cia_status` at `NOT_EXECUTED`, its `cia_tier` null, and its `committee_role` at `MEMBER`. Invitations are accepted in any investigation phase, and an invitation naming an unregistered `state_office_id` is rejected with `ERR_STATE_OFFICE_NOT_FOUND` (HTTP 404). One office may hold only one non-`WITHDRAWN` participation per investigation; a second live invitation for the same office is rejected with `ERR_DUPLICATE_PARTICIPATION` (HTTP 409).

An invited office joins by executing the common interest agreement. The caller must be a `ParticipatingStateAG` or `LeadStateAG` whose `X-User-ID` equals the participation's `state_office_id`, the participation must still be `INVITED` (otherwise `ERR_INVALID_STATE`), and the request names a `confidentiality_tier` of `STANDARD`, `RESTRICTED`, or `LEAD_ONLY`. Execution flips two dimensions of the participation atomically: `status` moves `INVITED` → `ACTIVE` and `cia_status` becomes `EXECUTED`, while `cia_tier` records the chosen tier and `cia_executed_at` records the logical time.

The chair seats lead offices by designating a participation's `committee_role` from `MEMBER` to `LEAD`. Designation requires the participation to be `ACTIVE` (else `ERR_PARTICIPATION_INACTIVE`), its `cia_tier` to be `RESTRICTED` or `LEAD_ONLY` — a `STANDARD`-tier office cannot lead, and the attempt is rejected with `ERR_CIA_TIER_INSUFFICIENT` (HTTP 422) — and the investigation's phase to be `DRAFT` or `OPEN` (else `ERR_INVALID_PHASE`). Designating a participation that already holds `LEAD` is accepted and re-stamps its designation order, which §3.4 uses to place lead-bonus remainder cents.

Advancing the investigation from `DRAFT` to `OPEN` is the first gated phase transition. The chair requests the advance with `to_phase` set to `OPEN`, and the activation quorum is evaluated: the matter must field at least 2 `ACTIVE` participations whose `committee_role` is `LEAD`, and at least 3 `ACTIVE` participations in total, with withdrawn offices excluded from both counts; falling short on either leg is rejected with `ERR_ACTIVATION_QUORUM_MISSING` (HTTP 422). A second gate protects lead capacity: no office holding `LEAD` on this investigation may simultaneously hold `committee_role` `LEAD` on another investigation whose phase is `OPEN`, `DISCOVERY`, `NEGOTIATION`, or `SETTLEMENT_PENDING`. Equivalently, each lead office's lead-capacity window is the half-open interval from the investigation's `opened_at` (inclusive) to its `settled_at` (exclusive), and two such windows on different investigations may not overlap for the same office — adjacency, where one matter's `settled_at` equals the other's `opened_at`, is allowed. A conflict is rejected with `ERR_LEAD_WINDOW_OVERLAP` (HTTP 409). A successful activation stamps `opened_at` with the current logical time.

An office leaves a matter by withdrawing, moving its participation `ACTIVE` → `WITHDRAWN`; the office itself (either AG role, matched by `X-User-ID`) or the `CommitteeChair` may perform the withdrawal. A withdrawal attempted on a participation that is not `ACTIVE` — still `INVITED` or already `WITHDRAWN` — is rejected with `ERR_INVALID_STATE` (HTTP 409). Withdrawal is refused with `ERR_SIGNED_STATE_CANNOT_WITHDRAW` (HTTP 409) while the office holds a sign-on entry in `SIGNED` or `LOCKED` status on any settlement of this investigation whose `term_status` is neither `COLLAPSED` nor `CLOSED_OUT` — a state that has committed to a live settlement cannot simply walk away. A completed withdrawal resets `committee_role` to `MEMBER` and stamps `withdrawn_at`.

### 3.2. Investigative Demands and Consolidated Responses

Once the matter is open, each office investigates under its own state authority. An office whose participation is `ACTIVE` issues an investigative demand by supplying `scope_text`; the demand is created already in `ISSUED` status with `issued_at` set to the current logical time and its `participation_id` pointing back at the issuing office's participation. Issuance from a participation that is not `ACTIVE` — the common interest agreement must be executed first — is rejected with `ERR_PARTICIPATION_INACTIVE` (HTTP 409), and issuance is lawful only while the investigation is in `OPEN` or `DISCOVERY` phase; outside those phases the request fails with `ERR_INVALID_PHASE` (HTTP 409).

Rather than answering dozens of demands piecemeal, the `DefendantCounsel` negotiates a consolidated response covering a chosen set of them. Submission carries `demand_ids` — a non-empty array in which every id must resolve to a demand of this same investigation whose status is still `ISSUED`; an empty list, a demand from another investigation, or a demand already consolidated is rejected with `ERR_RESPONSE_DEMANDS_INVALID` (HTTP 422), while a repeated id is not rejected — each entry is validated on its own and a repeated demand is folded idempotently at acceptance — plus a `coverage_summary` describing the negotiated production. Submission is lawful only in `DISCOVERY` or `NEGOTIATION` phase (else `ERR_INVALID_PHASE`), and creates the response in `SUBMITTED` status with `submitted_at` recorded.

A lead office then reviews the production: acceptance by a `LeadStateAG` whose office holds a `LEAD`, `ACTIVE` participation in this investigation moves the response `SUBMITTED` → `ACCEPTED` (from any other status the attempt fails with `ERR_INVALID_STATE`), stamps `accepted_at`, and — as one atomic cascade — folds every listed demand from `ISSUED` to `CONSOLIDATED`, stamping each demand's `consolidated_at` and writing the accepted response's id into its `consolidated_response_id`. When the defendant has produced everything promised, the `DefendantCounsel` marks the response fulfilled, moving `ACCEPTED` → `FULFILLED` and stamping `fulfilled_at`.

Discovery gates negotiation. Advancing the investigation from `DISCOVERY` to `NEGOTIATION` requires that at least one consolidated response of the investigation have status `ACCEPTED` or `FULFILLED`; without one the advance is rejected with `ERR_NO_ACCEPTED_RESPONSE` (HTTP 422). Advancing from `OPEN` to `DISCOVERY` carries no preconditions. Every manual advance names its target in `to_phase` and moves exactly one step along the declared chain — `OPEN`, `DISCOVERY`, `NEGOTIATION`, `SETTLEMENT_PENDING`, `SETTLED`, `MONITORING` are the settable targets; `CLOSED` is reached only automatically — and an advance that skips steps, names an unreachable target, or is attempted from a phase the chain does not connect is rejected with `ERR_INVALID_PHASE`.

### 3.3. Settlement Negotiation and the Counter–Revise Cycle

With the matter in `NEGOTIATION`, a lead office proposes a term sheet. The proposal supplies `monetary_total_cents` (the total monetary settlement, in cents), `restitution_reserve_cents` (the cents carved out for consumer restitution, zero or greater), an `allocation_basis` of `POPULATION`, `HARM_MEASURE`, or `NEGOTIATED`, and `injunctive_terms`, an array of at least one nationally applicable injunctive term string. The total must strictly exceed the restitution reserve, and the terms array must be non-empty; violations are rejected with `ERR_INVALID_REQUEST`. When the basis is `NEGOTIATED`, the proposal must also carry `negotiated_shares`, a map from state code to basis points whose key set equals exactly the state codes of the investigation's `ACTIVE` participations and whose values sum to exactly 10000; a missing, mismatched, or mis-summed map is rejected with `ERR_NEGOTIATED_SHARES_INVALID` (HTTP 422). Individual share values are not sign-checked — only the key set and the 10000-sum are validated — and under a `POPULATION` or `HARM_MEASURE` basis a supplied `negotiated_shares` map is accepted and stored as-is, unvalidated. Only one live settlement may exist per investigation: proposing while any earlier settlement of the matter has a `term_status` other than `COLLAPSED` is rejected with `ERR_INVALID_STATE`, and proposing outside `NEGOTIATION` phase fails with `ERR_INVALID_PHASE`.

A created settlement starts in `PROPOSED` term status with `fund_status` `UNFUNDED`, `negotiation_round` 0, `deposited_cents` 0, `compliance_hold` false, `restitution_computed` false, `restitution_reserve_balance_cents` initialized to the proposed `restitution_reserve_cents`, and `counter_total_cents` null. The provisional allocation variant runs immediately (§2.7): its distributable-pool result is stored in `provisional_distributable_cents` and its per-state weights in `provisional_weight_bps_by_state`. The settlement becomes the investigation's active settlement, recorded in the investigation's `active_settlement_id`.

The distributable-pool formula has a pinned evaluation order because its terms look circular; they must never be solved jointly. First, the base is the `monetary_total_cents` minus the `restitution_reserve_cents`. Second, the lead-state cost pool is the smaller of 25000000 cents and the base multiplied by 500 basis points out of 10000, rounded half up to a whole cent — that is, the lead pool is 5 percent of the base, capped at $250,000. Third, the distributable pool is the base minus that lead cost pool. Both the provisional and final variants use exactly this order.

The defendant answers a proposal with a counter. Countering is lawful only from `PROPOSED` (else `ERR_INVALID_STATE`), must carry `expected_settlement_version` matching the settlement's current `version` (else `ERR_STALE_VERSION`, HTTP 412), and is bounded by the negotiation cap: the counter is rejected with `ERR_NEGOTIATION_EXHAUSTED` (HTTP 422) when applying it would push `negotiation_round` beyond 4 — rounds 1 through 4 are allowed, a fifth is not. A successful counter moves `PROPOSED` → `COUNTERED`, increments `negotiation_round` by 1, records the supplied `counter_total_cents` when one is provided — a counter omitting it leaves any previously recorded value unchanged — while the optional free-text `note` accompanies the request only and is never persisted on the settlement, increments the settlement's `version` by 1, and — because a counter reopens factual disputes — automatically bounces an investigation sitting in `NEGOTIATION` back to `DISCOVERY`.

The lead side answers a counter with a revise. Revising is lawful only from `COUNTERED` (else `ERR_INVALID_STATE`) and carries the same `expected_settlement_version` OCC guard with the same `ERR_STALE_VERSION` rejection. When the revise supplies `revised_total_cents`, the settlement's `monetary_total_cents` is updated and the provisional allocation variant is recomputed against the new total — the revised total is not re-validated against `restitution_reserve_cents` — and the optional `note` may accompany the revision either way, likewise never persisted. A successful revise moves `COUNTERED` → `PROPOSED`, increments `version` by 1, and automatically returns the investigation from `DISCOVERY` to `NEGOTIATION` — this automatic return deliberately skips the accepted-response gate, since the bounce originated from this settlement's own counter rather than from a loss of discovery coverage.

Alternatively, the defendant may simply accept the current proposal: agreement by the `DefendantCounsel` moves `PROPOSED` → `TERMS_AGREED` with no further preconditions. Once the active settlement's `term_status` is `TERMS_AGREED` (or later `SIGN_ON_OPEN`), the chair may advance the investigation `NEGOTIATION` → `SETTLEMENT_PENDING`; attempting that advance without such a settlement is rejected with `ERR_NO_AGREED_SETTLEMENT` (HTTP 422).

### 3.4. Sign-On Campaign and Execution

Terms agreed nationally must still be ratified state by state. The `CommitteeChair` opens the sign-on window on a settlement in `TERMS_AGREED` (from any other status the attempt fails with `ERR_INVALID_STATE`) while the investigation is in `SETTLEMENT_PENDING` (else `ERR_INVALID_PHASE`). Opening stamps `sign_on_opened_at` with the current logical time and fixes `sign_on_deadline` exactly 45 days later — offices have a 45-day window to decide — and moves the settlement `TERMS_AGREED` → `SIGN_ON_OPEN`.

Each office records its own sign-on decision with `decision` set to `SIGNED` or `DECLINED`, acting as a `ParticipatingStateAG` or `LeadStateAG` whose `X-User-ID` matches its office. Four gates guard the recording, in the ladder order of §2.8: the settlement must be in `SIGN_ON_OPEN` (else `ERR_INVALID_STATE`); the caller's office must hold an `ACTIVE` participation in the settlement's investigation (else `ERR_NOT_A_PARTICIPANT`, HTTP 422); the current logical time must be at or before `sign_on_deadline` (else `ERR_SIGN_ON_WINDOW_CLOSED`, HTTP 422); and the office must not already hold a sign-on entry on this settlement — one decision per office, with a second attempt rejected as `ERR_DUPLICATE_SIGN_ON` (HTTP 409). A recorded decision appends an embedded entry to the settlement's `sign_ons` array carrying the office's `state_office_id` and `state_code`, the `decision`, a `status` matching the decision (`SIGNED` or `DECLINED`), and `decided_at` stamped with the logical time. The request returns the updated settlement object.

Execution is the moment of truth, performed by the `CommitteeChair` on a settlement in `SIGN_ON_OPEN` while the investigation is in `SETTLEMENT_PENDING`. The sign-on quorum is evaluated over two sets: the **eligible** offices are the investigation's `ACTIVE` participations as of open-sign-on time, and the **signed** offices are the `sign_ons` entries whose status is `SIGNED` or `LOCKED` at execution. Using each office's raw basis value — its `population` under a `POPULATION` basis, its `harm_measure_cents` under `HARM_MEASURE`, or its `negotiated_shares` entry under `NEGOTIATED`, read from live registry values — the quorum ratio in basis points is 10000 multiplied by the sum of raw values over the signed offices, divided by the sum of raw values over the eligible offices, rounded half up. Quorum is met when that ratio is at least 8000 basis points — exactly 8000 passes — **and** at least 3 states have signed. If the current logical time is at or before the deadline and quorum is not met, execution is rejected with `ERR_QUORUM_NOT_MET` (HTTP 422) and nothing changes. If the deadline has passed and quorum remains unmet, the settlement collapses: `SIGN_ON_OPEN` → `COLLAPSED`, the investigation's phase automatically returns `SETTLEMENT_PENDING` → `NEGOTIATION`, and the investigation's `active_settlement_id` is cleared to null, freeing the committee to propose again.

A quorum-met execution moves the settlement `SIGN_ON_OPEN` → `EXECUTED` and stamps `executed_at`. Every `sign_ons` entry in `SIGNED` status becomes `LOCKED`, and every office holding an `ACTIVE` participation that never recorded a decision receives an embedded entry with status `LAPSED`, carrying `decision` null and `decided_at` null, appended in the creation order of the offices' participations — lapsed and declined offices take nothing. The final allocation variant then runs (§2.7). Weight normalization assigns each locked state a `weight_bps`: each locked state's raw basis value is divided by the sum of raw values over the locked set, scaled by 10000, and rounded down to a whole basis point; the shortfall between 10000 and the sum of the floored weights is then distributed one basis point at a time to the largest raw values, breaking ties by sign-on `decided_at` ascending — earlier deciders first — and never by id. Each state's `basis_value_snapshot` captures its raw basis value at execution time.

Allocation lines are then created, one per `LOCKED` state, in `decided_at` ascending order, each recording its `settlement_id`, the paid office's `state_office_id`, a denormalized `state_code`, the snapshot, and its computed `weight_bps`. Per-line shares follow a pinned rounding order: first each line's `share_cents` is the settlement's `distributable_cents` multiplied by the line's `weight_bps` out of 10000, rounded down to a whole cent; then the remainder — the distributable pool minus the sum of those floors — is dealt out one cent at a time in order of `weight_bps` descending, ties broken by `decided_at` ascending, never by id. The lead cost pool is split equally among locked lines whose offices hold `committee_role` `LEAD`, with any equal-split remainder cents going to the lead line whose participation was designated earliest; if no lead state signed at all, the entire lead cost pool is instead folded back into the distributable pool before shares are computed. Each line's `gross_share_cents` is its `share_cents` plus its `lead_bonus_cents`, and every line maintains the invariant that `disbursed_cents`, `reverted_cents`, and `remaining_cents` always sum to `gross_share_cents` — a fresh line starts with zero disbursed and reverted, so its `remaining_cents` equals its gross. Lines are born in `ELIGIBLE` status. With the settlement executed, the chair may advance the investigation `SETTLEMENT_PENDING` → `SETTLED` — the only manual step into `SETTLED`, gated on the active settlement being `EXECUTED` (else `ERR_INVALID_STATE`) — which stamps the investigation's `settled_at` and closes every lead office's capacity window for this matter.

### 3.5. Funding, Disbursement, and Legislative Appropriation

An executed settlement is a promise until the defendant funds it. The `DefendantCounsel` deposits money in any number of tranches, each carrying an `amount_cents`; no lower bound is pinned on `amount_cents` — the only fiscal guard is the cumulative cap below. Deposits are lawful only on a settlement whose `term_status` is `EXECUTED` (else `ERR_INVALID_STATE`), and no deposit may push the cumulative `deposited_cents` past the settlement's `monetary_total_cents` — an overshooting deposit is rejected with `ERR_DEPOSIT_EXCEEDS_TOTAL` (HTTP 422). Each accepted deposit is added to `deposited_cents` and drives the fund dimension: the first deposit that leaves the fund short of the total moves `UNFUNDED` → `PARTIALLY_FUNDED`, and the deposit that brings cumulative funding to exactly the total moves the fund to `FUNDED`. Once the fund has advanced to `DISBURSING` or `DISBURSED`, later deposits still raise `deposited_cents` up to the cap but never move `fund_status` backward. The fund dimension is parallel to term status: it evolves independently on deposit and release events, through `UNFUNDED`, `PARTIALLY_FUNDED`, `FUNDED`, `DISBURSING`, and terminally `DISBURSED`.

States draw on their allocation lines by requesting disbursements. The caller is the office itself — a `ParticipatingStateAG` or `LeadStateAG` whose `X-User-ID` equals the line's `state_office_id` — supplying `amount_cents` and a `use_code` of `PROGRAM`, `GENERAL_FUND`, or `RESTITUTION_ADMIN` declaring the permitted use of proceeds. The request is guarded in ladder order: the line must be `ELIGIBLE` or `DISBURSING` (else `ERR_LINE_NOT_DISBURSABLE`, HTTP 409); the settlement's fund must be at least partially funded — `PARTIALLY_FUNDED`, `FUNDED`, or `DISBURSING` — since partial funding permits release up to the available balance (else `ERR_SETTLEMENT_NOT_FUNDED`, HTTP 409); the settlement's `compliance_hold` must be false (else `ERR_COMPLIANCE_HOLD_ACTIVE`, HTTP 409); the `amount_cents` must be greater than zero and no more than the line's `remaining_cents` (else `ERR_AMOUNT_EXCEEDS_REMAINING`, HTTP 422); and an office whose `appropriation_rule` is `GENERAL_FUND_ONLY` may request only `use_code` `GENERAL_FUND` (else `ERR_USE_CODE_NOT_PERMITTED`, HTTP 422). Creation records the line's id in the disbursement's `allocation_line_id`, stamps `requested_at`, and flips the line `ELIGIBLE` → `DISBURSING` on its first activity.

What happens at creation depends on the state's appropriation rule. For a `PREAPPROPRIATED` office the disbursement is created already `CERTIFIED` — certification is automatic and `certified_at` is stamped with the same logical time as `requested_at`. For offices under `CERTIFICATION_REQUIRED` or `GENERAL_FUND_ONLY`, the disbursement is created in `REQUESTED` and must wait for the legislature: a `StateLegislature` caller whose `X-User-ID` equals the line's office certifies the request, lawful only from `REQUESTED` (else `ERR_INVALID_STATE`) and only at or before the certification deadline, which is the settlement's `executed_at` plus 180 days. Certification attempted after that window is rejected with `ERR_CERTIFICATION_WINDOW_CLOSED` (HTTP 422) and mutates nothing; a timely certification stamps `certified_at`.

Release is the fund administrator's exclusive act. A `FundAdministrator` releases a disbursement only from `CERTIFIED` (else `ERR_INVALID_STATE`), only while the settlement's `compliance_hold` is false (else `ERR_COMPLIANCE_HOLD_ACTIVE`), and only while the settlement's undisbursed balance covers it — `deposited_cents` minus `released_cents` must be at least the disbursement's amount, else `ERR_INSUFFICIENT_FUND_BALANCE` (HTTP 422). A release stamps `released_at` and cascades: the amount is added to the settlement's `released_cents`; the line's `disbursed_cents` grows by the amount and its `remaining_cents` is recomputed under the gross-share invariant; the line moves `DISBURSING` → `DISBURSED` the moment its cumulative `disbursed_cents` equals its `gross_share_cents` — and a line with no prior activity whose full gross share is covered by a single release moves directly `ELIGIBLE` → `DISBURSED`; the settlement's fund moves to `DISBURSING` on the first release (from either `FUNDED` or `PARTIALLY_FUNDED`), and on to `DISBURSED` the moment every allocation line of the settlement has reached a terminal status, `DISBURSED` or `REVERTED`.

Two after-market corrections keep the books honest, both described with the workflows that trigger them: a breach-escalated monitoring close moves a settlement's `CERTIFIED` disbursements to `HELD` (§3.7), and the restitution compute sweeps disbursements still stuck in `REQUESTED` past their certification deadline into `REVERTED`, returning their cents to the restitution reserve (§3.6).

### 3.6. Consumer Restitution Administration

The restitution reserve carved out of every settlement exists for identified individual consumers, administered by the `FundAdministrator`. Claimants may be registered only against an `EXECUTED` settlement (else `ERR_INVALID_STATE`) and only within the claim window: the current logical time must be at or before `executed_at` plus 90 days, after which registration is rejected with `ERR_CLAIM_WINDOW_CLOSED` (HTTP 422). Registration supplies the consumer's `state_code` — informational only, with no foreign-key linkage — an administrator-assigned `contact_ref`, and a `claimed_loss_cents` strictly greater than zero (else `ERR_INVALID_REQUEST`). New claimants enter in `REGISTERED` status.

The administrator then adjudicates each registered claim with a `decision`. A `DENIED` decision moves `REGISTERED` → `DENIED` outright, and a `validated_loss_cents` supplied alongside a `DENIED` decision is ignored. A `VALIDATED` decision carries `validated_loss_cents` — omitting it is rejected with `ERR_INVALID_REQUEST` (HTTP 400) — which must be greater than zero and no more than the claim's `claimed_loss_cents`; a value exceeding the claim, or one not greater than zero, is rejected with `ERR_VALIDATION_EXCEEDS_CLAIM` (HTTP 422) — and moves `REGISTERED` → `VALIDATED`, setting the claim's `estimated_payout_cents` equal to its `validated_loss_cents`. That estimate is the estimated payout variant: it assumes no proration, and it is knowingly optimistic whenever the reserve will prove oversubscribed. Either decision is lawful only from `REGISTERED` (else `ERR_INVALID_STATE`).

Once the claim window has closed, the administrator computes restitution for the settlement. The compute is lawful only strictly after the claim window — running it at or before `executed_at` plus 90 days is rejected with `ERR_CLAIM_WINDOW_CLOSED` — and only once: a settlement whose `restitution_computed` is already true rejects a second compute with `ERR_RESTITUTION_LOCKED` (HTTP 409). A settlement that was never executed has no claim window at all; a compute against one is rejected with `ERR_INVALID_STATE` (HTTP 409).

The compute runs two phases in a fixed order. The **appropriation reversion sweep** goes first: every disbursement on the settlement's lines still sitting in `REQUESTED` whose certification deadline — the settlement's `executed_at` plus 180 days — lies in the past at compute time is moved `REQUESTED` → `REVERTED`, processed in `requested_at` ascending chronological order, never by id. Each reversion adds the disbursement's amount to its line's `reverted_cents` and the settlement's `reverted_cents`, recomputes the line's `remaining_cents`, and adds the amount to `restitution_reserve_balance_cents`, so reverted cents enlarge the payout pool before proration. A line whose `remaining_cents` reaches zero through reversion while its `disbursed_cents` is still below its `gross_share_cents` moves `DISBURSING` → `REVERTED`; the sweep can likewise revert a never-disbursed `ELIGIBLE` line's full remaining balance straight to `REVERTED`. In both cases the reverted cents flow into the settlement's restitution reserve balance.

The **proration** phase then pays claimants. Every claimant still `REGISTERED` after the window is lapsed to `LAPSED`; `DENIED` claimants are excluded; only `VALIDATED` claimants share the pool, which is the settlement's `restitution_reserve_balance_cents` at compute time — the original reserve plus any swept reversions, minus nothing yet. If the sum of `validated_loss_cents` over those claimants does not exceed the pool, every validated claimant is paid its full validated loss and the remainder is the pool minus that sum. Otherwise each claimant's `payout_cents` is the pool multiplied by its `validated_loss_cents` and divided by the sum of validated losses, rounded down to a whole cent, and the leftover cents are distributed one at a time in order of `validated_loss_cents` descending, ties broken by `created_at` ascending, never by id. Every `VALIDATED` claimant transitions to `PAID` with its assigned `payout_cents` — strictly smaller than its earlier `estimated_payout_cents` whenever the pool was oversubscribed — and the reserve balance is decremented by each payout as it is assigned. When the dust settles, the remaining unclaimed balance is stored as the settlement's `restitution_remainder_cents`, the `restitution_reserve_balance_cents` equals that remainder, and `restitution_computed` is set true, locking the settlement against any recompute.

### 3.7. Compliance Monitoring and Case Closure

A settled matter enters long-horizon oversight once the defendant's money is committed. The chair may advance the investigation `SETTLED` → `MONITORING` only when the active settlement's `fund_status` is `FUNDED`, `DISBURSING`, or `DISBURSED` — an unfunded or merely partially funded settlement cannot enter monitoring, and the advance is rejected with `ERR_SETTLEMENT_NOT_FUNDED` (HTTP 409).

Monitoring proceeds in consecutive periods opened by the `CommitteeChair` against an `EXECUTED` settlement (else `ERR_INVALID_STATE`). Each period carries a 1-based `period_index` that may not exceed 6 — opening a seventh is rejected with `ERR_PERIOD_LIMIT_REACHED` (HTTP 422) — and a half-open window from `window_start` (inclusive) to `window_end` (exclusive), each exactly 180 days long: the first period's `window_start` is the settlement's `executed_at`, and each later period's `window_start` is exactly the previous period's `window_end`, so the windows tile the timeline with neither gap nor overlap. Opening the next period while its predecessor is still `OPEN`, or any arrangement that would gap or overlap the previous window, is rejected with `ERR_PERIOD_NOT_CONTIGUOUS` (HTTP 409), and opening a period before its `window_start` has been reached is rejected with `ERR_PERIOD_NOT_STARTED` (HTTP 422). A new period opens in `OPEN` status.

Within a period, the `ComplianceMonitor` files one finding per injunctive term. A filing names a `term_index` that must be a 0-based index into the settlement's `injunctive_terms` array — an out-of-range index is rejected with `ERR_INVALID_TERM_INDEX` (HTTP 422) — an `outcome` of `COMPLIANT` or `BREACH`, and an optional `note`; the filing's `filed_at` is stamped into the period's embedded `findings` array. At most one finding may exist per injunctive term per period: a second filing for the same `term_index` in the same period is rejected with `ERR_DUPLICATE_FINDING` (HTTP 409). The filing returns the period object.

A period closes itself the moment every injunctive term has a finding, stamping `closed_at` and counting its `breach_count` — the number of findings with `outcome` `BREACH`. Three outcomes follow the count. If `breach_count` is at least 2, the period closes `CLOSED_BREACH` and escalates: the settlement's `compliance_hold` is set true, and every `CERTIFIED` disbursement on the settlement's lines moves to `HELD`, freezing money in place until the defendant cures. If `breach_count` is exactly zero, the period closes `CLOSED_COMPLIANT`, and when the settlement's hold had been raised by an earlier breach, the close cures it: `compliance_hold` returns to false and every `HELD` disbursement returns to `CERTIFIED`. If `breach_count` is exactly 1 — below the escalation threshold of 2 but not clean — the period still closes `CLOSED_COMPLIANT`, but the hold is left untouched in either direction.

The endgame arrives with the final period. When the period whose `period_index` is 6 closes with `breach_count` zero while the settlement's `fund_status` is `DISBURSED`, the settlement's `term_status` moves `EXECUTED` → `CLOSED_OUT`, and that close-out cascades upward: the investigation's phase moves `MONITORING` → `CLOSED` automatically, ending the matter. `CLOSED_OUT` and `COLLAPSED` are the settlement's terminal term statuses, `DISBURSED` the terminal fund status, and `CLOSED` the investigation's terminal phase; no further transitions leave them.

## 4. Endpoint Definitions

Operations that create a new resource — registering an office, opening an investigation, inviting a participation, issuing a demand, submitting a response, proposing a settlement, recording a sign-on decision, requesting a disbursement, registering a claimant, opening a monitoring period, or filing a finding — return `201 Created`. Operations that modify an existing resource or drive a state transition — phase advances, CIA execution, lead designation, withdrawal, acceptance, fulfillment, counter, revise, agreement, sign-on opening, execution, deposit, certification, release, validation, restitution compute, office updates, and the clock set — return `200 OK`. One endpoint, the logical clock, is mounted outside the `/multistate` prefix; every other path below is under it. Request bodies and full response payloads for each operation are specified by the narratives of §2 and §3; the table is a routing and authorization summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST   | `/_clock/set_current_utc` | Set the logical clock (outside the `/multistate` prefix) | CommitteeChair |
| POST   | `/multistate/state-offices` | Register a state AG office | CommitteeChair |
| GET    | `/multistate/state-offices/{id}` | Read one office | All roles |
| PATCH  | `/multistate/state-offices/{id}` | Update allocation inputs / appropriation rule (OCC on office version) | CommitteeChair |
| POST   | `/multistate/investigations` | Create an investigation in DRAFT | CommitteeChair |
| GET    | `/multistate/investigations/{id}` | Read one investigation | All roles |
| POST   | `/multistate/investigations/{id}/advance` | Advance the phase one step forward | CommitteeChair |
| GET    | `/multistate/investigations/{id}/participations` | List participations of an investigation | All roles |
| GET    | `/multistate/investigations/{id}/responses` | List consolidated responses of an investigation | All roles |
| GET    | `/multistate/investigations/{id}/settlements` | List settlements of an investigation | All roles |
| POST   | `/multistate/investigations/{id}/participations` | Invite a state office (creates an INVITED participation) | CommitteeChair |
| GET    | `/multistate/participations/{id}` | Read one participation | All roles |
| GET    | `/multistate/state-offices/{id}/participations` | List participations of a state office across investigations | All roles |
| POST   | `/multistate/participations/{id}/execute-cia` | Execute the common interest agreement at a confidentiality tier | ParticipatingStateAG, LeadStateAG |
| POST   | `/multistate/participations/{id}/designate-lead` | Seat the office on the executive committee | CommitteeChair |
| POST   | `/multistate/participations/{id}/withdraw` | Withdraw an ACTIVE participation | ParticipatingStateAG, LeadStateAG, CommitteeChair |
| POST   | `/multistate/participations/{id}/demands` | Issue an investigative demand under the office's own authority | ParticipatingStateAG, LeadStateAG |
| GET    | `/multistate/participations/{id}/demands` | List demands issued by a participation | All roles |
| POST   | `/multistate/investigations/{id}/responses` | Submit a negotiated consolidated response covering demands | DefendantCounsel |
| POST   | `/multistate/responses/{id}/accept` | Accept a consolidated response; consolidates its demands | LeadStateAG |
| POST   | `/multistate/responses/{id}/fulfill` | Mark an accepted response fulfilled | DefendantCounsel |
| POST   | `/multistate/investigations/{id}/settlements` | Propose a settlement term sheet (provisional allocation computed) | LeadStateAG |
| GET    | `/multistate/settlements/{id}` | Read one settlement (includes embedded sign-ons and computed allocation fields) | All roles |
| POST   | `/multistate/settlements/{id}/counter` | Defendant counters the proposal (OCC on settlement version) | DefendantCounsel |
| POST   | `/multistate/settlements/{id}/revise` | Lead state revises after a counter (OCC on settlement version) | LeadStateAG |
| POST   | `/multistate/settlements/{id}/agree-terms` | Defendant accepts the current proposal | DefendantCounsel |
| POST   | `/multistate/settlements/{id}/open-sign-on` | Open the 45-day sign-on window | CommitteeChair |
| POST   | `/multistate/settlements/{id}/sign-ons` | Record the caller office's sign-on decision | ParticipatingStateAG, LeadStateAG |
| POST   | `/multistate/settlements/{id}/execute` | Evaluate the sign-on quorum; execute or collapse the settlement | CommitteeChair |
| POST   | `/multistate/settlements/{id}/deposit` | Deposit defendant funds into the settlement | DefendantCounsel |
| GET    | `/multistate/allocation-lines/{id}` | Read one allocation line | All roles |
| GET    | `/multistate/settlements/{id}/allocation-lines` | List allocation lines of a settlement | All roles |
| GET    | `/multistate/state-offices/{id}/allocation-lines` | List allocation lines of a state office | All roles |
| POST   | `/multistate/allocation-lines/{id}/disbursements` | Request a disbursement from a line (auto-certified for PREAPPROPRIATED offices) | ParticipatingStateAG, LeadStateAG |
| GET    | `/multistate/allocation-lines/{id}/disbursements` | List disbursements of a line | All roles |
| POST   | `/multistate/disbursements/{id}/certify` | Legislative certification of a requested disbursement (own state only) | StateLegislature |
| POST   | `/multistate/disbursements/{id}/release` | Release a certified disbursement | FundAdministrator |
| POST   | `/multistate/settlements/{id}/claimants` | Register an identified consumer claimant | FundAdministrator |
| GET    | `/multistate/settlements/{id}/claimants` | List claimants of a settlement | All roles |
| POST   | `/multistate/claimants/{id}/validate` | Validate or deny a registered claim | FundAdministrator |
| POST   | `/multistate/settlements/{id}/restitution-compute` | Lapse stale claims, sweep stale disbursements, pro-rate payouts | FundAdministrator |
| POST   | `/multistate/settlements/{id}/monitoring-periods` | Open the next monitoring period | CommitteeChair |
| GET    | `/multistate/settlements/{id}/monitoring-periods` | List monitoring periods of a settlement | All roles |
| POST   | `/multistate/monitoring-periods/{id}/findings` | File a compliance finding for one injunctive term | ComplianceMonitor |

## 5. Error Code Catalogue

The catalogue below enumerates every application-level error identifier the API can return and its HTTP status. The conditions that trigger each error are defined by the narratives of §2 and §3, alongside the workflows they guard. A failure outside the catalogue — an unhandled server error — is reported in the same envelope with error_id `ERR_INTERNAL` and HTTP status 500.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_STATE_OFFICE_NOT_FOUND` | 404 Not Found |
| `ERR_INVESTIGATION_NOT_FOUND` | 404 Not Found |
| `ERR_PARTICIPATION_NOT_FOUND` | 404 Not Found |
| `ERR_RESPONSE_NOT_FOUND` | 404 Not Found |
| `ERR_SETTLEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_ALLOCATION_LINE_NOT_FOUND` | 404 Not Found |
| `ERR_DISBURSEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_CLAIMANT_NOT_FOUND` | 404 Not Found |
| `ERR_MONITORING_PERIOD_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_PHASE` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_PARTICIPATION_INACTIVE` | 409 Conflict |
| `ERR_LINE_NOT_DISBURSABLE` | 409 Conflict |
| `ERR_SETTLEMENT_NOT_FUNDED` | 409 Conflict |
| `ERR_RESTITUTION_LOCKED` | 409 Conflict |
| `ERR_SIGNED_STATE_CANNOT_WITHDRAW` | 409 Conflict |
| `ERR_COMPLIANCE_HOLD_ACTIVE` | 409 Conflict |
| `ERR_DUPLICATE_PARTICIPATION` | 409 Conflict |
| `ERR_DUPLICATE_SIGN_ON` | 409 Conflict |
| `ERR_DUPLICATE_FINDING` | 409 Conflict |
| `ERR_PERIOD_NOT_CONTIGUOUS` | 409 Conflict |
| `ERR_LEAD_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_NOT_A_PARTICIPANT` | 422 Unprocessable Entity |
| `ERR_RESPONSE_DEMANDS_INVALID` | 422 Unprocessable Entity |
| `ERR_INVALID_TERM_INDEX` | 422 Unprocessable Entity |
| `ERR_SIGN_ON_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_CERTIFICATION_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_CLAIM_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_PERIOD_NOT_STARTED` | 422 Unprocessable Entity |
| `ERR_NEGOTIATED_SHARES_INVALID` | 422 Unprocessable Entity |
| `ERR_ACTIVATION_QUORUM_MISSING` | 422 Unprocessable Entity |
| `ERR_NEGOTIATION_EXHAUSTED` | 422 Unprocessable Entity |
| `ERR_QUORUM_NOT_MET` | 422 Unprocessable Entity |
| `ERR_CIA_TIER_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_PERIOD_LIMIT_REACHED` | 422 Unprocessable Entity |
| `ERR_NO_ACCEPTED_RESPONSE` | 422 Unprocessable Entity |
| `ERR_NO_AGREED_SETTLEMENT` | 422 Unprocessable Entity |
| `ERR_DEPOSIT_EXCEEDS_TOTAL` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_FUND_BALANCE` | 422 Unprocessable Entity |
| `ERR_AMOUNT_EXCEEDS_REMAINING` | 422 Unprocessable Entity |
| `ERR_VALIDATION_EXCEEDS_CLAIM` | 422 Unprocessable Entity |
| `ERR_USE_CODE_NOT_PERMITTED` | 422 Unprocessable Entity |
