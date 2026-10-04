# Agent Profit Share API — Product Requirements Document

## 1. Introduction

A real-estate brokerage organized around market centers shares office profit with the agents who build the office. Each agent closes transactions, pays a split of gross commission to the market center as "company dollar" until an annual cap is reached, and then keeps everything above the cap for the remainder of their cap year. Each month, a portion of the market center's profit flows back to agents through a profit-share pool, allocated not by personal production but by sponsorship: an agent earns on the production of every agent they recruited, and on the production of everyone those recruits recruited, across up to seven downline levels.

This document specifies the API that operates that model. It covers market-center and agent administration, document-gated agent onboarding with sponsor attestation, sponsor-attribution disputes adjudicated by regional leadership, commission posting with a provisional cap split and a final chronological replay, monthly profit-share periods closed in two stages (a forward-looking preliminary close and a governance-ratified final close), ledger entries for expenses and adjustments, vesting of profit-share rights at departure, and agent transfers between market centers that preserve both cap-year state and the downline sponsorship graph.

Two design pressures shape the specification. First, every financial figure exists in two variants — a provisional, forward-looking number computed at posting or preliminary close, and a final number produced only when governance ratifies the period — and the two are expected to diverge whenever events fail to settle. Second, the sponsorship graph is materialized as a closure of up to seven levels per child agent, and disputes can re-point a subtree after projections already exist, forcing clawbacks and regeneration. Readers should keep both pressures in mind throughout; the scattering of rules across §3 reflects where they bite in the business process rather than where they sit in a schema.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID` identifying the caller and `X-User-Role` identifying the caller's role. A request missing either header, or carrying a role the system does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403). Authorization is evaluated after authentication and before any resource-existence or business validation.

Five roles exist, spelled exactly as follows: `PlatformAdmin`, `MarketCenterAdmin`, `RegionalDirector`, `ALCChair`, and `Agent`.

Identity binding differs by role. When `X-User-Role` is `MarketCenterAdmin`, `ALCChair`, or `Agent`, `X-User-ID` is the `id` of the acting `Agent` entity; ownership checks on any resource that references an `Agent` compare the resource's foreign-key field (for example, a transfer request's `agent_id` or a dispute's `filer_agent_id`) to `X-User-ID`. A `MarketCenterAdmin` is an active agent of the center operating its books, and an `ALCChair` is an agent of the center who ratifies or rejects final closes — both act through their own agent identity. When `X-User-Role` is `PlatformAdmin` or `RegionalDirector`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.

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

List endpoints accept `limit` and `offset` query parameters. `limit` defaults to 10, with a minimum of 1 and a maximum of 100. `offset` defaults to 0. Results are sorted by `created_at` ascending. The `meta` block of list responses carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every persisted resource carries an `id` that is a server-minted UUID with no type prefix. All entities except `ProfitShareLedgerEntry` additionally carry `created_at` (ISO 8601 UTC timestamp with three fractional digits, set at creation), `updated_at` (refreshed on every mutation), and `version` (an integer incremented on every mutation of the row, starting at 1 when the resource is created). `ProfitShareLedgerEntry` carries only `id` and `created_at`; it has neither `updated_at` nor `version`, because ledger entries are append-only. The `api_request_timestamp` in the envelope meta is a wall-clock timestamp; only the business-rule timestamps named in §2.8 come from the logical clock.

Several agent-facing workflows increment the acting agent's `version` as a side effect — onboarding activation, departure, commission posting, voiding, transfer completion, and distribution transitions that recompute agent totals. Clients must treat `version` as an opaque counter and rely on `GET /agents/{id}` to observe the current value before any version-guarded write.

### 2.5. Validation Order and Rejection Semantics

When a request violates multiple rules, exactly one error is returned, chosen by the following global priority order. Authentication comes first (missing or unrecognized headers, `ERR_UNAUTHENTICATED`), then role authorization (`ERR_FORBIDDEN`), then path-parameter existence checks evaluated left-to-right along the URL hierarchy (each with its resource-specific not-found error), then existence of body-referenced identifiers, then field well-formedness (`ERR_VALIDATION`), then state eligibility for the requested transition (`ERR_INVALID_STATE`), then the business rules in their documented order: temporal windows, referential constraints, business constraints, fiscal positivity, segregation of duties, and finally the optimistic-concurrency stale-version check (`ERR_STALE_AGENT_VERSION`), which is evaluated last.

Left-to-right path validation means that on a nested path such as a market center's agent collection, the market center's existence is confirmed (else `ERR_MARKET_CENTER_NOT_FOUND`) before any agent id on the path is resolved (else `ERR_AGENT_NOT_FOUND`). Each resource class has its own not-found error identifier — `ERR_MARKET_CENTER_NOT_FOUND`, `ERR_AGENT_NOT_FOUND`, `ERR_PERIOD_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`, `ERR_DOCUMENT_NOT_FOUND`, `ERR_COMMISSION_EVENT_NOT_FOUND`, `ERR_TRANSFER_NOT_FOUND`, `ERR_RESOLUTION_NOT_FOUND`, and `ERR_DISTRIBUTION_NOT_FOUND` — all carrying HTTP 404, and the same per-resource identifiers apply when a body field references a nonexistent resource.

### 2.6. Monetary Precision and the Two-Variant Profit Model

All monetary figures are carried at two decimal places, rounded half-up. Vesting ratios are carried at four decimal places, rounded half-up. The distribution scale factor (pool divided by gross entitlement total) is carried at full precision until each scaled line is individually rounded; no intermediate rounding of the factor is permitted.

Profit exists in two variants and the distinction is load-bearing everywhere it appears. The provisional variant counts company dollar from every commission event of the month whose status is `POSTED` or `SETTLED`; the final variant counts only `SETTLED` events, valued by a chronological replay of the agent's entire cap year rather than by the provisional splits recorded at posting. An event that never settles inflates the provisional figure relative to the final one, and an agent whose cap boundary falls mid-month can see a different split under replay than under posting-time accrual. Any field whose name begins with `provisional_` is forward-looking; any figure named `final_` exists only after governance ratification and is `null` until then — the one exception is a commission event's own `final_company_dollar`, which the replay writes onto every event of a replayed agent once a period of that agent's center ratifies: `SETTLED` events receive their replayed values, and non-`SETTLED` events are written as 0.00.

### 2.7. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency on the agent row: posting a commission event and creating a transfer request for an agent. Both require a non-optional request field `expected_agent_version` carrying the `version` the client last observed on that `Agent`. If the agent's current `version` differs from the supplied value — because any other write has advanced it since the client's last read — the request is rejected with `ERR_STALE_AGENT_VERSION` (HTTP 412), preventing the client from writing against state it has not observed. No other endpoint takes a version field.

### 2.8. The Logical Clock

The server keeps a logical clock used for all time-gated business rules: dispute filing deadlines, transfer effectiveness, receipt timestamps, and vesting windows. At startup the clock reads 2026-09-01T00:00:00Z, and the server must never fall back to wall-clock time. A `PlatformAdmin` advances the clock through a dedicated test-driving capability that accepts a `to_iso8601` timestamp and returns the new `current_utc`; time-gated rules are re-evaluated lazily on the next read or write rather than by an eager sweep.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Market Center

A `PlatformAdmin` creates a market center by supplying a `name` and a `region_code`; the center starts in status `ACTIVE` and can later be moved to `SUSPENDED` and back to `ACTIVE` by the same role. Suspension is a gate, not a teardown: while a center is `SUSPENDED`, new agent enrollment into that center, creation of new profit-share periods for it, and approval or completion of transfers involving it are all blocked with `ERR_CENTER_NOT_ACTIVE` (HTTP 422). Existing records remain readable and already-running workflows otherwise continue.

Agents come to life inside a center. Enrollment requires `full_name`, `email` (unique across the entire system; a duplicate is rejected with `ERR_VALIDATION`), and `join_date`, and may optionally name a `sponsor_agent_id`. A center's very first agent has no sponsor; every later enrollee may name one, subject to the sponsorship rules of §3.3. Enrollment is permitted to `MarketCenterAdmin` and also to `PlatformAdmin`, so that a brand-new center can bootstrap its first agent before any administrator identity exists for it. The sponsor must be an `ACTIVE` agent — with one deliberate bootstrap exception: a `PlatformAdmin` enrollment may name a sponsor who is not yet `ACTIVE`, while a `MarketCenterAdmin` enrollment may not (the same `ERR_SPONSOR_CROSS_CENTER` rejection applies). Suspension of the center, closure-graph construction, and cap-year initialization aside, enrollment also initializes `pending_payable_profit_share` and `lifetime_profit_share` at 0.00. A newly enrolled agent's version is 1, so the automatic activation of §3.2 moves it to 2.

### 3.2. Enrollment, Onboarding Documents, and Activation

A newly enrolled agent begins with `membership_status` `ENROLLED_PENDING_DOCS` and `cap_status` `UNCAPPED` — two independent state dimensions that evolve on the same row and never imply one another. The agent's cap year is initialized as the interval starting at `join_date` (inclusive, recorded in `cap_year_start`) and ending one year later (exclusive, recorded in `cap_year_end`), with `accrued_company_dollar` at 0.00. A `VestingSchedule` is created one-to-one with the agent in status `ACCRUING`, its `vesting_start_date` equal to the agent's `join_date`. `departure_date` is `null` for any agent who has not departed, and the computed flag `vested` mirrors whether the linked vesting schedule has reached `VESTED`.

Onboarding documents arrive one at a time. Each document carries a `document_type` drawn from `SPONSOR_ATTESTATION`, `ICA_SIGNED`, and `W9`; an opaque `document_ref` storage key; and a server-stamped `received_at` from the logical clock. A `SPONSOR_ATTESTATION` document additionally requires `attested_sponsor_agent_id` naming the agent the paperwork claims as sponsor — which may legitimately differ from the `sponsor_agent_id` recorded on the agent, and that mismatch is exactly what a sponsorship dispute later litigates. For any other document type, `attested_sponsor_agent_id` is `null`.

Activation is automatic. The moment the agent's document set contains both `ICA_SIGNED` and `W9` — plus a `SPONSOR_ATTESTATION` when the agent has a non-null `sponsor_agent_id` — `membership_status` moves from `ENROLLED_PENDING_DOCS` to `ACTIVE` and the agent's `version` is incremented. Only `ACTIVE` agents may have commissions posted against them; posting against an agent in any other membership state fails with `ERR_INVALID_STATE` (HTTP 409).

### 3.3. The Sponsorship Graph and Its Closure

Sponsorship is a self-referential chain: each agent's `sponsor_agent_id` points at another agent. The system materializes that chain as a closure of `SponsorshipEdge` rows. Each edge names a `parent_agent_id` (the upline, sponsor side), a `child_agent_id` (the downline, sponsored side), and a `depth_level` giving the tree distance from parent to child. When an agent enrolls with a sponsor, the system walks the sponsor chain upward from the new sponsor — depth 1 is the direct sponsor, depth 2 the sponsor's sponsor, and so on — creating one edge per ancestor reached, stopping at depth 7 or at an ancestor whose own `sponsor_agent_id` is null. Depths beyond seven earn nothing and produce no edge.

Two referential constraints guard enrollment, checked in this relative order under §2.5 (referential constraints follow field well-formedness but precede business constraints such as the suspension gate): the sponsor must be an `ACTIVE` agent enrolled in the same market center as the enrollee (else `ERR_SPONSOR_CROSS_CENTER`, HTTP 422), and the new sponsor chain must neither be the enrollee themself nor loop back through the enrollee (else `ERR_SPONSOR_CYCLE`, HTTP 422) — the cycle check itself is enforced while the closure is built along the chain. Edges carry a `status` of `ACTIVE` or `SUPERSEDED`; an edge becomes `SUPERSEDED` only when a dispute overturn re-points a subtree, as described in §3.4.

Anyone may inspect the graph: an agent's downline is the set of edges where the agent is the parent, their upline the edges where they are the child, and a global edge listing accepts filters on `parent_agent_id`, `child_agent_id`, `status`, and `depth_level` alongside the standard pagination parameters.

### 3.4. Sponsorship Disputes: Filing, Adjudication, and Overturn Cascades

An agent who believes another agent's sponsorship was recorded incorrectly files a dispute naming the `sponsored_agent_id`, an `evidence_document_id`, and a free-text `reason`. The filer is taken from `X-User-ID` and recorded as `filer_agent_id`; the sponsor of record at filing time is snapshotted into `current_sponsor_agent_id`; `filed_at` is stamped from the logical clock. The dispute is accepted only within a window: `window_deadline` is computed as the sponsored agent's `join_date` plus ninety days, and filing is accepted when `filed_at` falls on or before that deadline — the boundary is inclusive. A filing after the deadline is rejected with `ERR_DISPUTE_WINDOW_EXPIRED` (HTTP 422).

Three additional filing-time checks apply, evaluated after the window check: the evidence document must be a `SPONSOR_ATTESTATION` belonging to the sponsored agent whose `attested_sponsor_agent_id` equals the filer (else `ERR_EVIDENCE_INVALID`); the filer and the sponsored agent must be enrolled in the same market center (else `ERR_SPONSOR_CROSS_CENTER`); and the filer must be neither the sponsored agent themself nor the current sponsor of record (else `ERR_DISPUTE_NOT_ACTIONABLE`, HTTP 422). A dispute starts in status `FILED`.

Adjudication belongs to the `RegionalDirector`. Opening review moves a dispute from `FILED` to `UNDER_REVIEW`. Resolution takes an `outcome` of `UPHELD`, `OVERTURNED`, or `DISMISSED`, recorded in the dispute's `resolution` field, and moves the dispute to `RESOLVED_UPHELD`, `RESOLVED_OVERTURNED`, or `DISMISSED` respectively. `RESOLVED_UPHELD` and `DISMISSED` are terminal: the recorded sponsor stands and no tree mutation occurs. `RESOLVED_OVERTURNED` is not terminal — see the appeal path below — but it fires a large cascade immediately: first a cycle guard walks the filer's sponsor chain and refuses the overturn with `ERR_SPONSOR_CYCLE` (HTTP 422, the dispute remaining `UNDER_REVIEW`) if the new chain would loop back through the sponsored agent; then the sponsored agent's `sponsor_agent_id` is re-pointed to the filer and that agent's `version` incremented; every `ACTIVE` edge whose child is the sponsored agent or any descendant of it via active edges becomes `SUPERSEDED`; and a fresh closure (depths one through seven) is rebuilt along the new sponsor chain, with descendants' edges whose paths crossed the re-pointed root re-derived. Any `ProfitShareDistribution` with `basis` `PROVISIONAL` still in status `PROJECTION` whose `level_breakdown` references a superseded edge moves to `CLAWED_BACK`; the owning period's full `PROVISIONAL` `PROJECTION` distribution set is then discarded and regenerated from the new closure against the existing `provisional_pool` (clawed-back rows remain in `CLAWED_BACK`), and the period's `distributed_total` and `center_retained_amount` are recomputed.

Appeal is the filer's single second chance, and it is available from either resolved outcome. The appellant must be the original filer — `X-User-ID` compared to `filer_agent_id`, else `ERR_FORBIDDEN` — and `appeal_count` must still be zero, else `ERR_APPEAL_EXHAUSTED` (HTTP 422), since at most one appeal is permitted. A successful appeal moves the dispute from `RESOLVED_UPHELD` or `RESOLVED_OVERTURNED` to `REOPENED` and increments `appeal_count` by one; opening review then moves `REOPENED` back to `UNDER_REVIEW` for a fresh adjudication. Dispute listings support filtering by `filer_agent_id`, `sponsored_agent_id`, `evidence_document_id`, and `status`.

### 3.5. Commission Posting, the Cap Split, and the Cap Year

A `MarketCenterAdmin` posts a commission event by supplying the producing `agent_id`, a `gross_commission` in dollars, the business date `occurred_on`, an `external_ref` ledger reference carried verbatim on the event (uniqueness is not enforced by the server), and the OCC guard `expected_agent_version`. The event's `market_center_id` is snapshotted from the agent's home center at posting. Posting is guarded by the stale-version rule of §2.7 and by two business checks: `gross_commission` must be greater than zero (else `ERR_NONPOSITIVE_AMOUNT`, HTTP 422), and `occurred_on` must not precede the agent's current `cap_year_start` — backdated postings into a closed cap year are rejected with `ERR_BACKDATED_COMMISSION` (HTTP 422). A posting whose `occurred_on` falls at or beyond `cap_year_end` is not rejected; it triggers cap-year rollover instead, as described below.

The provisional split runs at posting. The company-dollar rate is thirty percent of gross, rounded half-up to two decimals. The annual cap is 20,000.00 dollars of accrued company dollar per cap year. The split proceeds as follows: compute the raw company dollar as gross commission times the rate, rounded; compute the remaining headroom as the cap minus the agent's current `accrued_company_dollar` (floored at zero); the event's `company_dollar` is the smaller of the raw figure and the headroom; `agent_retained` is the gross minus that company dollar, rounded to two decimals. `cap_applied` is true exactly when the cap bound — not the rate — determined the company dollar, which is to say when the raw figure exceeded the remaining headroom. The agent's `accrued_company_dollar` advances by the event's company dollar, and when the resulting accrual reaches at least 20,000.00 — the boundary is inclusive — `cap_status` flips from `UNCAPPED` to `CAPPED`. While `CAPPED`, subsequent splits yield a `company_dollar` of 0.00 and full retention by the agent until rollover. Each posting increments the agent's `version` by one.

Cap-year rollover fires automatically inside a posting whose `occurred_on` reaches or passes `cap_year_end`: `cap_year_start` and `cap_year_end` advance by whole years until `occurred_on` falls strictly inside the new interval, `accrued_company_dollar` resets to 0.00, and `cap_status` returns to `UNCAPPED` — all before the new event's split is applied against the fresh accrual.

Voiding is the cap's release valve. A `MarketCenterAdmin` may settle a `POSTED` event (moving it to `SETTLED`, which makes it eligible for the final replay; settling touches only the event itself — the agent's accrual and version are unchanged) or void it (moving it to `VOID`) — both terminal. Voiding is refused with `ERR_INVALID_STATE` if any profit-share period covering the event's month for the event's market center has already reached `FINAL_CLOSED`. A void subtracts the event's `company_dollar` from the agent's `accrued_company_dollar`; if the result falls strictly below 20,000.00 while the agent is `CAPPED`, `cap_status` reverts to `UNCAPPED`. Open or preliminarily-closed periods for that month recompute their `provisional_profit`, and the agent's `version` increments.

### 3.6. Monthly Periods, Ledger Entries, and Preliminary Close

Each market center keeps one profit-share period per calendar month, identified by `period_month` in `YYYY-MM` format and unique per center — a duplicate is rejected with `ERR_PERIOD_MONTH_CONFLICT` (HTTP 409). A period opens in status `OPEN`.

While `OPEN`, the period accepts ledger entries recording the center's costs and corrections — entries are rejected with `ERR_INVALID_STATE` once the period leaves `OPEN`. Each entry carries an `entry_type` of `EXPENSE` or `ADJUSTMENT`, an `amount`, and an optional `memo`. An `EXPENSE` amount must be greater than zero (else `ERR_NONPOSITIVE_AMOUNT`) and debits profit; an `ADJUSTMENT` is signed and may be negative. Ledger entries are append-only and carry no version. Every entry creation recomputes the period's `provisional_profit`.

Preliminary close is the first of two closing stages and belongs to the `MarketCenterAdmin` — with a twist: the acting `X-User-ID` must be an `Agent` with `membership_status` `ACTIVE` enrolled in this period's market center, else the close is rejected with `ERR_MCA_NOT_CENTER_AGENT` (HTTP 422). Two further guards apply: the period must be `OPEN`, and the computed `provisional_profit` must be greater than zero, else `ERR_PROFIT_NOT_POSITIVE` (HTTP 422); per §2.5 the state guard fires before the actor-identity guard.

The provisional profit computation is forward-looking: total company dollar from the center's commission events whose `occurred_on` falls in the period month with status `POSTED` or `SETTLED`, minus the sum of `EXPENSE` entries, plus the signed sum of `ADJUSTMENT` entries, rounded half-up to two decimals. The `provisional_pool` is then fifty-two percent of that profit, likewise rounded. The close records the acting user in `preliminary_closed_by` — a value that later drives segregation of duties — moves the period to `PRELIMINARY_CLOSED`, and mints `PROJECTION` distributions with `basis` `PROVISIONAL` per the allocation waterfall of §3.8, scaled and remainder-adjusted against the `provisional_pool`.

### 3.7. Governance: Draft, Proposal, Ratification, Rejection, and Amend

Final close is not an administrative act; it is a governance act. For a `PRELIMINARY_CLOSED` period, a `MarketCenterAdmin` drafts a `GovernanceResolution` of `resolution_type` `FINAL_CLOSE_RATIFICATION`, starting in status `DRAFT`. Proposing the resolution — permitted only while the owning period is `PRELIMINARY_CLOSED`, else `ERR_INVALID_STATE` — moves the resolution from `DRAFT` to `PROPOSED`, stamps `proposed_by` with the acting user, and moves the period to `FINAL_CLOSE_PENDING`.

The `ALCChair` then decides. Ratification requires the resolution to be `PROPOSED` and enforces segregation of duties: the ratifying `X-User-ID` — the chair's own agent id — must differ from the period's `preliminary_closed_by`, else `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). The ratifier is recorded in `ratified_by`. Rejection, also from `PROPOSED`, moves the resolution to `REJECTED` and returns the period from `FINAL_CLOSE_PENDING` to `PRELIMINARY_CLOSED`, reopening it for a fresh proposal; a rejected resolution can be amended — optionally carrying new `notes` — back to `DRAFT` by a `MarketCenterAdmin`, ready to be proposed again. Ratification is the terminal state of the resolution and triggers the full final-close cascade of §3.9.

### 3.8. The Distribution Waterfall

Profit share rewards sponsorship, not production. For each potential recipient agent — `ACTIVE` agents in any case, plus `DEPARTED` agents whose vesting schedule is `VESTED` under the `FINAL` basis — the system considers the recipient's `ACTIVE` downline edges and builds one entitlement line per edge: the level rate for the edge's `depth_level` multiplied by the child agent's attributable company dollar for the period. Attributable company dollar is the provisional `company_dollar` sum when the basis is `PROVISIONAL`, and the replayed `final_company_dollar` sum when the basis is `FINAL`. Children whose vesting schedule is `FORFEITED` are excluded from entitlement sets entirely — their edges remain for historical attribution but generate no lines. The level rates by depth are: fifty percent at level 1, ten percent at level 2, five percent at level 3, five percent at level 4, seven and a half percent at level 5, ten percent at level 6, and twelve and a half percent at level 7.

Rounding order is pinned and not negotiable: each entitlement line is rounded to two decimals half-up first, and only then summed. Summing first and rounding once is prohibited — it produces different cents. If the gross total of all lines across all recipients exceeds the pool, every line is scaled by the ratio of pool to gross total (the factor carried at full precision), each scaled line is rounded two decimals half-up, and the residual delta — pool minus the sum of scaled lines, rounded — is applied to the single line with the largest pre-rounding fractional part; ties break to the lower `depth_level` first, then the recipient agent's earlier `created_at`, then the source child agent's earlier `created_at`. If the gross total fits within the pool, no scaling occurs and the unallocated remainder stays with the center.

Lines with zero entitlement are omitted, and a recipient with no positive lines receives no distribution row at all; if no entitlement line survives at all, no distributions are created and the entire pool stays with the center. Each surviving recipient gets one distribution whose `amount` is the sum of their scaled lines and whose `level_breakdown` array records every contributing line with its `source_agent_id`, `depth_level`, `entitlement`, and `scaled_amount`. Conservation holds at all times: the sum of distribution amounts plus `center_retained_amount` equals the current pool, where `distributed_total` sums the period's distributions in status `PROJECTION` or `PAYABLE` and is recomputed on every distribution creation or transition. Before final close the current pool is `provisional_pool`; after, it is `profit_share_pool`.

### 3.9. Final Close: The Chronological Replay and the Ratification Cascade

Ratification computes `final_profit` by replaying each affected agent's entire cap year over `SETTLED` events only. The evaluation order is pinned: events are sorted by `occurred_on` ascending, ties broken by the event's `created_at` ascending — never by id, never by gross size, which is what decides which of two same-day events absorbs the last capped dollar. A replay accrual starts at 0.00 and resets to 0.00 at each cap-year anniversary crossed during replay. Each event's `final_company_dollar` is the smaller of its raw thirty-percent split (rounded) and the remaining cap headroom at that point in the replay, and the accrual advances by that amount event by event. The period's `final_profit` is the sum of those replayed values over the month's settled events, minus expenses, plus adjustments, rounded. If `final_profit` is not greater than zero, ratification is refused with `ERR_PROFIT_NOT_POSITIVE`. The `profit_share_pool` is fifty-two percent of `final_profit`, rounded.

The cascade then fans out. Every `PROJECTION` distribution of the period is retired and replaced by a fresh `FINAL`-basis distribution minted directly in status `PAYABLE`, its `amount` computed under the `FINAL` basis against the `profit_share_pool` and its `level_breakdown` populated accordingly; each recipient agent's `pending_payable_profit_share` — the sum of that agent's `PAYABLE` distribution amounts — is recomputed and each touched agent's `version` incremented (touched meaning any agent who held a retired `PROJECTION` row or receives a new `PAYABLE` row); and the vesting schedules of `DEPARTED` recipients are re-evaluated for continuation eligibility. `distributed_total` and `center_retained_amount` are recomputed against `profit_share_pool`, preserving the invariant that their sum equals the pool. The period lands in `FINAL_CLOSED`, terminal. For the final basis, the recipient set additionally includes `DEPARTED` agents whose vesting schedule is `VESTED` — a vested leaver keeps earning.

Payment is a separate, deliberate act: a `MarketCenterAdmin` marks a `PAYABLE` distribution paid, moving it to `PAID`, adding the `amount` to the recipient's `lifetime_profit_share` (the sum of that agent's `PAID` distributions), subtracting it from `pending_payable_profit_share`, and incrementing the agent's `version`. Distribution listings filter by `agent_id`, `period_id`, `status`, and — on the period-scoped listing — `basis`.

### 3.10. Departure, Vesting, and Forfeiture

A `MarketCenterAdmin` records an agent's departure by supplying a `departure_date`. Departure is blocked while any transfer request for the agent sits in `REQUESTED` or `APPROVED` (else `ERR_TRANSFER_IN_PROGRESS`, HTTP 409). On departure, `membership_status` moves from `ACTIVE` to `DEPARTED` — terminal — and the vesting schedule is evaluated in two variants. The provisional variant counts whole calendar months between `join_date` and `departure_date` as `service_months_provisional` — computed from the year-month difference, reduced by one when the departure day-of-month precedes the join day-of-month — and `vested_ratio_provisional` is that count divided by thirty-six, capped at one, four decimals half-up; an agent departing the day before their join-day anniversary in month thirty-six scores thirty-five thirty-sixths, 0.9722. The final variant counts exact days as `service_days_final`, with `vested_ratio_final` that count divided by 1095, capped at one, four decimals half-up.

Adjudication uses the final variant only: the schedule moves from `ACCRUING` to `VESTED` when `service_days_final` reaches at least 1095 days — the boundary is inclusive, so exactly 1095 days vests in full — and to `FORFEITED` otherwise. Both ratios floor at zero: a negative month count or a `departure_date` before `join_date` yields 0.0000, with `service_days_final` floored at 0. A vested agent's `vested` flag becomes true and they remain eligible for profit share on periods closing after departure. A forfeited agent's `vested` becomes false, and every outstanding distribution of theirs in status `PROJECTION` or `PAYABLE` moves to `FORFEITED`, each transition recomputing the owning period's `distributed_total` (and, for a forfeited `PAYABLE`, the agent's `pending_payable_profit_share`); the agent is excluded from all future entitlement sets. The departing agent's `version` increments.

### 3.11. Transfers Between Market Centers

An agent initiates a transfer by naming a `to_market_center_id` and an `effective_date`, guarded by `expected_agent_version` per §2.7; the request's `agent_id` is the caller and `from_market_center_id` is snapshotted from the agent's current center. Creation increments the agent's `version` by one. Three constraints guard the request, in the temporal-before-constraint ordering of §2.5: the `effective_date` must not fall inside any source-center period whose month contains it and whose status is `PRELIMINARY_CLOSED`, `FINAL_CLOSE_PENDING`, or `FINAL_CLOSED` (else `ERR_TRANSFER_WINDOW_CONFLICT`, HTTP 422); the destination must differ from the current center (else `ERR_TRANSFER_SELF_CENTER`, HTTP 422) and must exist and be `ACTIVE` (a suspended destination yields `ERR_CENTER_NOT_ACTIVE`); and no other transfer request for the same agent may be `REQUESTED` or `APPROVED` (else `ERR_TRANSFER_IN_PROGRESS`). The request starts in status `REQUESTED`.

A `MarketCenterAdmin` approves or rejects a `REQUESTED` transfer; approval additionally requires the destination center to be `ACTIVE`, else `ERR_CENTER_NOT_ACTIVE`. The requesting agent may cancel their own request from `REQUESTED` or `APPROVED` — `X-User-ID` must equal the request's `agent_id`, else `ERR_FORBIDDEN`. Completion, by a `MarketCenterAdmin`, requires both centers `ACTIVE` (else `ERR_CENTER_NOT_ACTIVE`) and the logical clock to have reached the `effective_date` (else `ERR_TRANSFER_NOT_EFFECTIVE`, HTTP 422). Completion rewrites the agent's `market_center_id` to the destination while leaving `membership_status` untouched, and — the defining property of the design — preserves everything else: `downline_preserved` is always true, the sponsorship closure follows the transferring agent verbatim with no edge rewritten, and the cap year (`cap_year_start`, `cap_year_end`, `accrued_company_dollar`, and `cap_status`) carries over unchanged with no reset. The agent's `version` increments. Transfer listings filter by `agent_id`, `from_market_center_id`, `to_market_center_id`, and `status`.

## 4. Endpoint Definitions

All endpoints require the `X-User-ID` and `X-User-Role` headers. Creating a new resource returns HTTP 201; modifications, actions, and reads return HTTP 200. Errors carry the envelope of §2.2 with the error identifiers of §5. On `POST /governance-resolutions/{id}/amend` the resolution-existence check (`ERR_RESOLUTION_NOT_FOUND`) precedes role authorization, mirroring the path-existence rule of §2.5. No distribution row is mutated in place across bases: the §3.4 regeneration replaces the period's `PROJECTION` set with fresh rows, and the §3.9 cascade retires `PROJECTION` rows and mints new `PAYABLE` rows under the `FINAL` basis, so a period can hold distributions of both bases (which is why the period-scoped listing filters on `basis`).

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /_clock/set_current_utc | Advance the server's logical clock | PlatformAdmin |
| POST | /market-centers | Create a market center | PlatformAdmin |
| GET | /market-centers/{id} | Get one market center | PlatformAdmin, MarketCenterAdmin, RegionalDirector, ALCChair, Agent |
| POST | /market-centers/{id}/suspend | Suspend a market center | PlatformAdmin |
| POST | /market-centers/{id}/reactivate | Reactivate a market center | PlatformAdmin |
| GET | /market-centers/{id}/agents | List agents of a market center | PlatformAdmin, MarketCenterAdmin, RegionalDirector, ALCChair, Agent |
| POST | /market-centers/{id}/agents | Enroll an agent into a market center | PlatformAdmin, MarketCenterAdmin |
| GET | /agents | List agents with filters | PlatformAdmin, MarketCenterAdmin, RegionalDirector, ALCChair, Agent |
| GET | /agents/{id} | Get one agent (includes `version` for OCC) | PlatformAdmin, MarketCenterAdmin, RegionalDirector, ALCChair, Agent |
| POST | /agents/{id}/onboarding-documents | Attach an onboarding document | PlatformAdmin, MarketCenterAdmin |
| GET | /agents/{id}/onboarding-documents | List an agent's onboarding documents | PlatformAdmin, MarketCenterAdmin, RegionalDirector, ALCChair, Agent |
| GET | /agents/{id}/downline | Edges where this agent is the upline | PlatformAdmin, MarketCenterAdmin, RegionalDirector, ALCChair, Agent |
| GET | /agents/{id}/upline | Edges where this agent is the downline | PlatformAdmin, MarketCenterAdmin, RegionalDirector, ALCChair, Agent |
| GET | /agents/{id}/vesting-schedule | The agent's vesting schedule (array of length 0 or 1) | PlatformAdmin, MarketCenterAdmin, RegionalDirector, ALCChair, Agent |
| POST | /agents/{id}/depart | Record an agent's departure; evaluates vesting | MarketCenterAdmin |
| POST | /agents/{id}/transfer-requests | Request a transfer (OCC on agent version) | Agent |
| GET | /sponsorship-edges | List sponsorship closure edges with filters | PlatformAdmin, MarketCenterAdmin, RegionalDirector, ALCChair, Agent |
| POST | /sponsorship-disputes | File a sponsor-attribution dispute | Agent |
| GET | /sponsorship-disputes | List disputes with filters | PlatformAdmin, MarketCenterAdmin, RegionalDirector, ALCChair, Agent |
| GET | /sponsorship-disputes/{id} | Get one dispute | PlatformAdmin, MarketCenterAdmin, RegionalDirector, ALCChair, Agent |
| POST | /sponsorship-disputes/{id}/open-review | Move a FILED or REOPENED dispute to UNDER_REVIEW | RegionalDirector |
| POST | /sponsorship-disputes/{id}/resolve | Resolve an UNDER_REVIEW dispute | RegionalDirector |
| POST | /sponsorship-disputes/{id}/appeal | Appeal a resolved dispute (filer only, at most once) | Agent |
| POST | /commission-events | Post a commission event (OCC on agent version) | MarketCenterAdmin |
| GET | /commission-events | List commission events with filters | PlatformAdmin, MarketCenterAdmin, RegionalDirector, ALCChair, Agent |
| GET | /commission-events/{id} | Get one commission event | PlatformAdmin, MarketCenterAdmin, RegionalDirector, ALCChair, Agent |
| POST | /commission-events/{id}/settle | Settle a POSTED event | MarketCenterAdmin |
| POST | /commission-events/{id}/void | Void a POSTED event | MarketCenterAdmin |
| POST | /market-centers/{id}/profit-share-periods | Open a monthly profit-share period | MarketCenterAdmin |
| GET | /profit-share-periods | List periods with filters | PlatformAdmin, MarketCenterAdmin, RegionalDirector, ALCChair, Agent |
| GET | /profit-share-periods/{id} | Get one period | PlatformAdmin, MarketCenterAdmin, RegionalDirector, ALCChair, Agent |
| POST | /profit-share-periods/{id}/ledger-entries | Append an expense or adjustment entry | MarketCenterAdmin |
| GET | /profit-share-periods/{id}/ledger-entries | List ledger entries of a period | PlatformAdmin, MarketCenterAdmin, RegionalDirector, ALCChair, Agent |
| POST | /profit-share-periods/{id}/preliminary-close | Preliminary close: provisional profit, pool, PROJECTION distributions | MarketCenterAdmin |
| GET | /profit-share-periods/{id}/distributions | List distributions of a period | PlatformAdmin, MarketCenterAdmin, RegionalDirector, ALCChair, Agent |
| POST | /profit-share-periods/{id}/governance-resolutions | Draft a FINAL_CLOSE_RATIFICATION resolution | MarketCenterAdmin |
| GET | /profit-share-periods/{id}/governance-resolutions | List resolutions of a period | PlatformAdmin, MarketCenterAdmin, RegionalDirector, ALCChair, Agent |
| POST | /governance-resolutions/{id}/propose | Propose a DRAFT resolution; period moves to FINAL_CLOSE_PENDING | MarketCenterAdmin |
| POST | /governance-resolutions/{id}/amend | Amend a REJECTED resolution back to DRAFT | MarketCenterAdmin |
| POST | /governance-resolutions/{id}/ratify | ALC chair ratifies: final close and full cascade | ALCChair |
| POST | /governance-resolutions/{id}/reject | ALC chair rejects: period returns to PRELIMINARY_CLOSED | ALCChair |
| GET | /governance-resolutions/{id} | Get one governance resolution | PlatformAdmin, MarketCenterAdmin, RegionalDirector, ALCChair, Agent |
| GET | /profit-share-distributions | List distributions with filters | PlatformAdmin, MarketCenterAdmin, RegionalDirector, ALCChair, Agent |
| GET | /profit-share-distributions/{id} | Get one distribution | PlatformAdmin, MarketCenterAdmin, RegionalDirector, ALCChair, Agent |
| POST | /profit-share-distributions/{id}/mark-paid | Mark a PAYABLE distribution paid | MarketCenterAdmin |
| GET | /transfer-requests | List transfer requests with filters | PlatformAdmin, MarketCenterAdmin, RegionalDirector, ALCChair, Agent |
| GET | /transfer-requests/{id} | Get one transfer request | PlatformAdmin, MarketCenterAdmin, RegionalDirector, ALCChair, Agent |
| POST | /transfer-requests/{id}/approve | Approve a REQUESTED transfer | MarketCenterAdmin |
| POST | /transfer-requests/{id}/reject | Reject a REQUESTED transfer | MarketCenterAdmin |
| POST | /transfer-requests/{id}/cancel | Cancel a REQUESTED or APPROVED transfer (requesting agent only) | Agent |
| POST | /transfer-requests/{id}/complete | Complete an APPROVED transfer at/after its effective date | MarketCenterAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_VALIDATION | 400 |
| ERR_MARKET_CENTER_NOT_FOUND | 404 |
| ERR_AGENT_NOT_FOUND | 404 |
| ERR_PERIOD_NOT_FOUND | 404 |
| ERR_DISPUTE_NOT_FOUND | 404 |
| ERR_DOCUMENT_NOT_FOUND | 404 |
| ERR_COMMISSION_EVENT_NOT_FOUND | 404 |
| ERR_TRANSFER_NOT_FOUND | 404 |
| ERR_RESOLUTION_NOT_FOUND | 404 |
| ERR_DISTRIBUTION_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_AGENT_VERSION | 412 |
| ERR_DISPUTE_WINDOW_EXPIRED | 422 |
| ERR_TRANSFER_WINDOW_CONFLICT | 422 |
| ERR_BACKDATED_COMMISSION | 422 |
| ERR_TRANSFER_NOT_EFFECTIVE | 422 |
| ERR_SPONSOR_CROSS_CENTER | 422 |
| ERR_SPONSOR_CYCLE | 422 |
| ERR_EVIDENCE_INVALID | 422 |
| ERR_DISPUTE_NOT_ACTIONABLE | 422 |
| ERR_APPEAL_EXHAUSTED | 422 |
| ERR_PERIOD_MONTH_CONFLICT | 409 |
| ERR_TRANSFER_SELF_CENTER | 422 |
| ERR_TRANSFER_IN_PROGRESS | 409 |
| ERR_CENTER_NOT_ACTIVE | 422 |
| ERR_NONPOSITIVE_AMOUNT | 422 |
| ERR_PROFIT_NOT_POSITIVE | 422 |
| ERR_MCA_NOT_CENTER_AGENT | 422 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
