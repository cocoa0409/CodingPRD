# Observability Billing API — Product Requirements Document

## 1. Introduction

Modern observability platforms do not sell seats; they sell meters. A single customer account can simultaneously consume infrastructure host hours, custom metric cardinality, log ingestion bandwidth, log indexing capacity, traces, and synthetic test runs — each with its own unit, its own rate, and its own commitment contract. When container and serverless fleets fluctuate by the minute, the simple question "how many hosts did the customer run this month?" has at least two defensible answers, and the choice between them is worth real money. This document specifies the Usage-Based Observability Billing API: the system of record that turns raw telemetry samples into defensible invoices.

The platform serves several audiences at once. Billing operators open and close monthly billing periods, negotiate commitment contracts, and steer cardinality incidents to resolution. Ingestion pipelines stream host-hour samples, log events, rollup snapshots, and usage attribution records into open periods around the clock. Finance auditors need a read-only window into every period, invoice, and per-team chargeback rollup. Team leads own their team's chargeback bucket and can formally dispute attribution they believe is wrong. Throughout, the system must reconcile two competing forces: customers want the cheaper of the plausible billing algorithms, and the business wants log ingestion charged on every byte that arrives while indexing is charged only on the events the customer chose to keep.

A deliberate design stance runs through the specification: money is always integer cents, rounding is always round-half-up, and invoice totals are rounded per line and then summed — never summed and then rounded. State transitions are explicit, optimistic concurrency protects the two account-level write operations where interleaved writers could silently corrupt commercial terms, and a logical clock — never the wall clock — decides when a period may close.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. All resources are mounted under the `/api` URL prefix; the test-driving clock endpoint is the sole exception and lives outside it.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a set of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes five distinct roles: `PlatformAdmin`, `BillingAdmin`, `IngestionAgent`, `TeamLead`, and `FinanceReader`. A request missing either header, or carrying a role value outside this enumeration, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is authenticated but not permitted to invoke the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

Role identity semantics differ by role, and are normative:

- When `X-User-Role` is `PlatformAdmin`, `BillingAdmin`, `IngestionAgent`, or `FinanceReader`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it for audit purposes but does not compare it to any entity's `id`.
- When `X-User-Role` is `TeamLead`, `X-User-ID` is the `id` of the acting `Team`; ownership checks on any resource that references a `Team` compare the resource's foreign-key field to `X-User-ID`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every primary resource in the system carries a standard set of system-managed fields:

- **`id` (string):** A unique, server-minted identifier for the resource, formatted as a UUID with no type prefix.
- **`created_at` (string):** An ISO 8601 timestamp in UTC with three fractional digits (e.g., `2026-09-01T00:00:00.000Z`) indicating when the resource was first created.
- **`updated_at` (string):** An ISO 8601 UTC timestamp, in the same format, indicating when the resource was last modified. Any change to the resource's properties refreshes it.
- **`version` (integer):** A system-managed integer starting at 1 that increments with every modification to the resource. It backs the optimistic concurrency control rules described in §2.8.

One deliberate exception exists: an `InvoiceLine` is immutable once written. It carries only `id` and `created_at`; both `updated_at` and `version` are absent from it.

Every mutation to a resource — including system-driven mutations such as a rollup snapshot recomputing a `cardinality_estimate`, a top-up increasing a `committed_quantity`, or a dispute acceptance reassigning a `team_id` — refreshes the mutated resource's `updated_at` and increments its `version` (except on `InvoiceLine`, which never mutates).

### 2.5. Validation Ordering and Nested Resource Retrieval

Every request passes through a fixed, priority-ordered validation pipeline. The order is normative; when several checks would fail, the one with the highest priority surfaces:

1. **Authentication.** The headers of §2.1 are present and the role is one of the declared role names — otherwise `ERR_UNAUTHENTICATED`.
2. **Authorization.** The role is permitted to invoke the endpoint — otherwise `ERR_FORBIDDEN`.
3. **Path existence.** When an endpoint path contains multiple resource identifiers (e.g., an account id followed by a period id followed by an event id), the system validates each identifier in strict left-to-right order and rejects with `ERR_NOT_FOUND` at the first identifier that does not resolve.
4. **Body foreign-key existence.** Identifiers supplied in the request body that reference other records (such as a commitment id, a retention tier id, or a team id) must resolve to live records — otherwise `ERR_NOT_FOUND`.
5. **Period openness.** Any mutation that writes meter, host-hour, or log data requires the parent billing period to be `OPEN`; against a `CLOSED` or `SETTLED` period the request is rejected with `ERR_PERIOD_CLOSED`.
6. **Entity state preconditions.** The action-specific state machine precondition must hold (for example, commitment activation requires the commitment to be `DRAFT`; dispute acceptance requires the dispute to be `OPEN`; incident transitions follow their declared cycle) — otherwise `ERR_INVALID_STATE`.
7. **Retention tier window integrity.** A new or updated retention tier must not collide with a sibling tier's effective window — otherwise `ERR_TIER_WINDOW_OVERLAP` (see §2.9).
8. **Commitment window integrity.** A new commitment, or a top-up, must not create an overlapping window for the same account and meter — otherwise `ERR_COMMITMENT_WINDOW_OVERLAP` (see §2.9).
9. **Plan tier monitor cap.** Creating a monitor that would exceed the plan's active-monitor cap is rejected with `ERR_PLAN_LIMIT` (see §3.8).
10. **Fiscal standing.** Commitment creation and activation require the account's `standing` to be `GOOD` — otherwise `ERR_ACCOUNT_DELINQUENT`.
11. **Tag policy enforcement.** A `BLOCK`-mode tag policy rejects a non-compliant usage record with `ERR_TAG_POLICY_VIOLATION` (see §3.6).
12. **Optimistic concurrency.** Endpoints covered by §2.8 reject a stale `expected_billing_account_version` with `ERR_STALE_VERSION`.
13. **Payload schema.** Required fields present, types correct, enum values valid — otherwise `ERR_INVALID_REQUEST`.

Because schema validation runs last, a request that is simultaneously malformed and unauthorized surfaces `ERR_FORBIDDEN`, not `ERR_INVALID_REQUEST`.

### 2.6. The Logical Clock

The system does not consult wall-clock time for any business decision. Instead it maintains a logical clock whose value at server startup is `2026-09-01T00:00:00Z`. The clock must never fall back to wall-clock time during the server's lifetime. A `PlatformAdmin` may advance the logical clock through an admin-only test-driving capability that sets the current instant to a supplied `current_utc` value. Two business rules read the clock: a billing period may only be closed once the logical clock has reached or passed the period's `period_end_utc`, and a commitment top-up is only admissible while the logical clock has not passed the commitment's `window_end_utc`.

### 2.7. Money, Precision, and Rounding

All monetary amounts in the system are integer cents. Rates are stored as integer cents per unit (per host, per gigabyte, per million events, per cardinality unit) and amounts are computed as integer cents. Wherever a multiplication can produce a fractional cent, the result is rounded **half-up** to the nearest integer cent. Two rounding disciplines are pinned and must not be interchanged:

- **Per-line rounding, then sum.** When an invoice is issued, each line's amount is fully computed and rounded first; the invoice's `total_amount_cents` is the plain sum of the already-rounded line amounts. Summing unrounded line values and rounding once at the end is explicitly forbidden — the two orders can differ by cents, and the pinned order is per-line-then-sum.
- **Charge split before rate.** When a meter's quantity is priced against a commitment, the quantity is first split into a committed portion and an overage portion, and each portion is priced at its own rate.

Basis-point multipliers use a base of ten thousand: a multiplier value of 10000 means exactly 1.0 times the underlying rate.

### 2.8. Optimistic Concurrency Control

Two account-level creation endpoints are protected by optimistic concurrency control, and only these two:

- Creating a `Commitment` requires the request to carry `expected_billing_account_version`, the `version` of the parent `BillingAccount` the client last observed. If the account's current `version` no longer matches — because another writer advanced it since the read — the create is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Creating a `RetentionTier` likewise requires `expected_billing_account_version` matching the parent account's current `version`, with the same `ERR_STALE_VERSION` (HTTP 412) rejection on mismatch.

Both creations, on success, increment the parent `BillingAccount`'s `version` by 1. No other endpoint takes a version field; endpoints not listed here are processed without an OCC check.

### 2.9. Window Arithmetic: Half-Open vs. Closed Intervals

Two different overlap disciplines coexist, and each is pinned to its resource:

- A `RetentionTier`'s effective window is **half-open**: it covers instants from `effective_from_utc` (inclusive) up to but not including `effective_to_utc`. Two tiers on the same account whose half-open windows intersect are rejected with `ERR_TIER_WINDOW_OVERLAP`. Adjacent windows — one ending exactly where the next begins — do not overlap. The same check also rejects configurations that would leave a gap when the previous tier carries an explicit `effective_to_utc`.
- A `Commitment`'s window is **closed on both ends**: it covers instants from `window_start_utc` through `window_end_utc` inclusive. Two commitments for the same account and the same meter whose closed intervals share any instant — including touching at a single endpoint — are rejected with `ERR_COMMITMENT_WINDOW_OVERLAP`.

This asymmetry is intentional: retention pricing may tile seamlessly, while pre-purchased commitments for the same meter must never double-cover even a single instant.

### 2.10. Hierarchical Consistency and Cascades

State changes propagate. Closing a billing period settles every elapsed commitment under it and drafts the invoice. Remediating a cardinality incident quarantines the parent metric series; verifying and later closing it returns the series to service. Accepting an attribution dispute reassigns the underlying usage record and triggers a chargeback rollup recompute. Whenever such a cascade mutates a resource, that resource's `updated_at` refreshes and its `version` increments. The server performs these cascading mutations automatically when criteria are met — no separate client call on the affected resource is required.

## 3. Business Logic & Workflows

### 3.1. Accounts, Plan Tiers, and Billing Periods

A `PlatformAdmin` onboards a customer by creating a **BillingAccount**, supplying a display `name`, a `plan_tier` of `FREE`, `PRO`, or `ENTERPRISE`, and a `billing_cycle_anchor_day` — a day-of-month between 1 and 28 at which each billing period opens. A new account carries `standing` set to `GOOD`. An invoice that stays unpaid past its grace window drags the account's `standing` to `DELINQUENT` (§2.5 names the error this surfaces as), and delinquency blocks all new commitment creation and activation until resolved (§3.4).

Commercial terms for each tier live in a **PlanTierConfig**, created by a `PlatformAdmin` with the tier's `plan_tier` (unique across configs), its hard monitor cap `max_monitors` (5 for `FREE`, 50 for `PRO`, 500 for `ENTERPRISE`), the bundled cardinality quota `included_custom_metrics`, and the four rate fields: `host_overage_rate_cents`, `log_ingest_rate_cents_per_gb`, `log_index_rate_cents_per_million`, and `custom_metric_rate_cents_per_unit`. These rates are the fallback on-demand prices used whenever no active commitment covers a meter. `PlanTierConfig` carries no rate fields for `TRACE` or `SYNTHETIC`; when no active commitment covers one of those meters, its fallback on-demand rate is zero cents per unit, so both invoice lines and the chargeback rollup rate uncommitted `TRACE` and `SYNTHETIC` quantity at zero.

Within an account, a `BillingAdmin` opens a **BillingPeriod** by supplying `period_start_utc` (inclusive) and `period_end_utc` (exclusive). The period begins in `OPEN` status and is the container for all metered activity: host-hour samples, log events, meter accumulators, and usage records all carry the period's id as their parent reference. Every mutation that writes usage into a period — recording a host-hour sample, ingesting a log event, posting a usage record, reindexing an excluded event — requires the period to still be `OPEN`; against a `CLOSED` or `SETTLED` period the write is rejected with `ERR_PERIOD_CLOSED`.

### 3.2. Host Attribution and the Two Billable Counts

An `IngestionAgent` samples the fleet once per hour, recording a **HostHourRecord** with the `hour_bucket_utc` (an hour-grain timestamp aligned to the top of the hour), the `infra_host_count` of distinct infrastructure hosts observed that hour, the `container_host_count` of attributed container-host equivalents (which fluctuates minute-by-minute in reality but is rolled up to the hour here), and the `serverless_invocation_count` for that hour. Serverless invocations are priced separately from hosts and never enter the host billable computation. At most one record may exist per period per hour bucket; a duplicate submission for an already-recorded `hour_bucket_utc` within the same period is rejected with `ERR_DUPLICATE_HOST_HOUR`.

When the period closes, the system computes the month's billable host count twice, by two different algorithms, over exactly the same input set — the host-hour records whose `hour_bucket_utc` falls within the period's half-open window from `period_start_utc` up to but not including `period_end_utc`. Both variants treat a record's combined host footprint as the sum of its `infra_host_count` and `container_host_count`, and both return 0 when no records exist:

- **High-water mark.** The billable count is the single largest combined host footprint observed across all hour buckets in the period.
- **Ninety-ninth percentile.** The combined footprints are sorted in ascending order; with `n` records, the rank index is the number of records multiplied by 0.99 and rounded up to a whole number (a 1-based index); the billable count is the value at that rank. Equivalently, this is the smallest value such that at least 99 percent of hours are at or below it.

The **charged host count** actually billed for the period is the *smaller* of the two results — deliberately cheaper for the customer, and documented as the billing rule. Both algorithms also have a provisional form used for draft invoice display and preview dashboards during an `OPEN` period: the high-water-mark provisional simply computes over the hours observed so far (ignoring the empty tail of the month), and the percentile provisional applies the identical rank-index computation to the partial hour set. At close, the final variants lock over the full hour set.

### 3.3. Log Ingestion, Exclusion Filters, and Reindexing

Logs are billed on two separate legs, and the separation is the core cost-control story. **Ingestion is charged on every byte that arrives**, regardless of what happens to the event afterward; **indexing is charged only on events that are actually kept queryable**.

An `IngestionAgent` ingests a **LogEvent** by supplying the `size_bytes` of the raw event, a `service_tag` used both by exclusion filters and by chargeback attribution, an informational `ingested_at_utc` timestamp (ordering of events otherwise uses `created_at`), and optionally a `retention_tier_id` naming the retention tier the event should be indexed under. At ingest the event's `exclusion_state` starts as `PENDING` and is resolved synchronously, before the ingest call returns, by evaluating the account's exclusion filters.

Filter selection proceeds as follows. The candidate set is every **ExclusionFilter** on the account that is currently `enabled` and whose `service_tag_pattern` — a glob — matches the event's `service_tag`. Filters with `enabled` set to false never match. If no candidate matches, no filter applies and the event becomes `INDEXED`. If candidates exist, the winner is the candidate with the lowest `priority` value; ties are broken by earlier `created_at`, and the record's `id` must never be used as a tie-breaker. When the winning filter's `sample_rate_pct` is 0, the event becomes `EXCLUDED`. Otherwise the filter admits a deterministic sample: the event is admitted to `INDEXED` when the hash of its `service_tag`, taken modulo 100, is strictly less than the winner's `sample_rate_pct`; otherwise it is `EXCLUDED`. A `sample_rate_pct` of 100 therefore admits every matched event, and values are confined to the inclusive range 0 through 100.

Whichever way the decision lands, the ingest leg is charged: the `LOG_INGEST` meter accumulator's `quantity` increases by the event's `size_bytes`. Only when the event lands in `INDEXED` does the `LOG_INDEX` accumulator's `quantity` increase by 1. The `LOG_INDEX` leg is created lazily: an ingest that lands `EXCLUDED` does not create the period's `LOG_INDEX` accumulator at all — the first `LOG_INDEX` unit in a period, whether from an event landing `INDEXED` at ingest or from a successful reindex, is what creates it.

The two legs are priced differently. The ingest charge converts bytes to gigabytes using one billion bytes per gigabyte, multiplies by the plan's `log_ingest_rate_cents_per_gb`, and rounds half-up to integer cents. The index charge applies only while the event's `exclusion_state` is `INDEXED`: the plan's `log_index_rate_cents_per_million` is divided by one million to obtain a per-event rate, that rate is multiplied by the event's retention tier multiplier — the tier's `index_rate_multiplier_bp` divided by the ten-thousand basis-point base, so 10000 means exactly the plan rate — and the result is rounded half-up to integer cents. An excluded event therefore costs its ingest bytes and nothing more.

Exclusion is reversible while the books are open. A `BillingAdmin` may reindex an `EXCLUDED` event, moving its `exclusion_state` to `INDEXED`. Reindexing is refused with `ERR_PERIOD_CLOSED` once the parent period is past `OPEN`; it is also refused when an enabled exclusion filter currently matches the event with a `sample_rate_pct` of 0 — such an event is under a hard exclusion and may not be revived. A successful reindex increments the `LOG_INDEX` accumulator's `quantity` by 1 and debits the account's active `LOG_INDEX` commitment by 1; when no such active commitment exists, the reindex is rejected with `ERR_NO_ACTIVE_COMMITMENT`. The index leg is charged at reindex time; the ingest leg is never re-charged.

A `BillingAdmin` manages the filter set directly: filters are created with their `service_tag_pattern`, `sample_rate_pct`, `priority`, and optional `enabled` flag (defaulting to true), and an existing filter can be disabled, flipping `enabled` to false so it no longer matches anything.

### 3.4. Commitments and Overage Pricing

A **Commitment** is a pre-purchased block of quantity on one meter. A `BillingAdmin` creates one against an account by naming the `meter` — one of `INFRA_HOST`, `CUSTOM_METRIC`, `LOG_INGEST`, `LOG_INDEX`, `TRACE`, or `SYNTHETIC` — the `committed_quantity` for the window, the inclusive `window_start_utc` and `window_end_utc` bounding the window, the negotiated `committed_unit_rate_cents`, and the `overage_unit_rate_cents` that applies once the block is consumed. Because creation is OCC-protected (§2.8), the request must also carry `expected_billing_account_version`; a stale value is rejected with `ERR_STALE_VERSION`, and a successful create bumps the account's `version`.

Creation additionally enforces two guards, in pipeline order (§2.5): the account's `standing` must be `GOOD` (otherwise `ERR_ACCOUNT_DELINQUENT`), and the closed window from `window_start_utc` through `window_end_utc` must not share any instant with another commitment on the same account and meter (otherwise `ERR_COMMITMENT_WINDOW_OVERLAP`).

A new commitment starts in `DRAFT` and bills nothing until a `BillingAdmin` activates it. Activation repeats the two guards — the account must still be in `GOOD` standing, and the no-overlap rule is re-evaluated against the commitment's closed window — and moves the commitment to `ACTIVE`.

While `ACTIVE`, each unit of metered usage first draws down the commitment. The commitment's `consumed_quantity` tracks the drawdown, starting at 0. Every meter accumulator in the period carries three reconciling quantities: the cumulative `quantity` metered, the `committed_consumed_quantity` debited against an active commitment, and the `on_demand_quantity`, which is always the `quantity` minus the `committed_consumed_quantity`. When a meter's quantity updates, the charge for the new quantity is split before rating: the committed portion is the smaller of the new quantity and the commitment's remaining headroom (its `committed_quantity` minus its `consumed_quantity`, floored at zero), the overage portion is whatever of the new quantity exceeds the committed portion (floored at zero), and the charge is the committed portion priced at `committed_unit_rate_cents` plus the overage portion priced at `overage_unit_rate_cents`, rounded half-up to integer cents. With no active commitment on the meter, the committed portion is zero and the entire quantity bills at the overage rate, which falls back to the plan's on-demand rate from its `PlanTierConfig`.

When `consumed_quantity` reaches `committed_quantity`, the commitment transitions automatically from `ACTIVE` to `EXHAUSTED`, and subsequent usage on the meter routes entirely to on-demand pricing. Exhaustion is not final: while the logical clock has not yet passed the `window_end_utc`, a `BillingAdmin` may top the commitment up, supplying a `top_up_quantity` that is added to `committed_quantity` and returning the commitment to `ACTIVE` so consumption resumes against it. A top-up is still subject to the window-overlap guard of §2.9.

Commitments settle with the books. When the parent billing period closes and the commitment's window has elapsed, an `ACTIVE` commitment moves to `SETTLED` and its `expired_quantity` is set to the unused remainder — its `committed_quantity` minus its `consumed_quantity`. An `EXHAUSTED` commitment settling at period close records an `expired_quantity` of 0. `SETTLED` is terminal.

### 3.5. Retention Tiers

A **RetentionTier** prices indexed log retention. A `BillingAdmin` creates one with a `name`, the `retention_days` an indexed event remains queryable, and an effective window bounded by `effective_from_utc` (inclusive) and `effective_to_utc` (exclusive) — the half-open discipline of §2.9. The tier's commercial lever is `index_rate_multiplier_bp`, a basis-point multiplier applied to the plan's per-event index rate (§3.3): 10000 bills exactly the plan rate, higher values bill a premium for longer retention. Creation is OCC-protected exactly like commitment creation — the request carries `expected_billing_account_version`, stale values draw `ERR_STALE_VERSION`, and a successful create increments the account's `version` — and it must not overlap a sibling tier's half-open window, nor leave a gap behind a predecessor that declared an explicit end, on pain of `ERR_TIER_WINDOW_OVERLAP`. An event ingested with a `retention_tier_id` pointing at a tier carries that tier's multiplier; the field stays null while the event is excluded.

### 3.6. Teams, Usage Attribution, Tag Governance, and Disputes

Chargeback starts with the **Team**: a `BillingAdmin` registers each internal team with a `name` and a finance `cost_center` code. Teams are the buckets usage rolls up into.

Usage is attributed by posting a **UsageRecord** against an open period, naming the `meter`, the `quantity` attributed, and optionally the `team_id` of the owning team. Both `IngestionAgent` pipelines and `BillingAdmin` operators may post usage records. Each accepted record also bumps the matching meter accumulator for the period.

Whether a record is trustworthy for chargeback is governed by the account's **TagPolicy** rules. A tag policy names a `required_tag_key` that must be present on every usage record, a whitelist `allowed_values` of acceptable values for that tag, and an `enforcement` mode of `WARN` or `BLOCK`. When a usage record arrives whose team attribution is missing or whose tag value falls outside the whitelist:

- Under `WARN`, the record is accepted but its computed `tag_compliant` flag is set to false, keeping it out of any team's rollup (§3.9).
- Under `BLOCK`, the record is rejected outright with `ERR_TAG_POLICY_VIOLATION` (HTTP 422).

A record that satisfies the policy carries `tag_compliant` true. A record whose `team_id` is null — accepted only because no `BLOCK` policy forbade it — is inherently non-compliant for rollup purposes.

A `TeamLead` who believes a usage record has been attributed to the wrong team opens an **AttributionDispute** on it, supplying the `raised_by_team_id` of the disputing team and a free-text `reason`. Opening the dispute sets the usage record's `disputed` flag to true, and a disputed record is held out of chargeback rollups while the dispute is `OPEN`. A `BillingAdmin` then resolves it in one of two directions. Rejecting the dispute moves it to `REJECTED` and simply clears the `disputed` flag, restoring the original attribution. Accepting the dispute — permitted only while the usage record's billing period is still `OPEN` — moves the dispute to `ACCEPTED`, clears the `disputed` flag, reassigns the record's `team_id` to the `raised_by_team_id`, and recomputes the chargeback rollup. Both resolutions are terminal; the dispute never reopens.

### 3.7. Custom Metrics and Cardinality Incidents

A `BillingAdmin` or `TeamLead` registers a **CustomMetricSeries** with a `metric_name` and the owning `team_id` used for chargeback. The series starts `ACTIVE` with a `cardinality_estimate` of 0. An `IngestionAgent` periodically posts a rollup snapshot carrying a fresh `cardinality_estimate`, and each snapshot recomputes the series' estimate and drives the incident machinery below.

Custom metric billing is quota-then-rate: the plan's `included_custom_metrics` cardinality units are bundled at no charge, and units beyond the quota bill at the plan's `custom_metric_rate_cents_per_unit`. Abuse detection runs on a soft cap of ten thousand units above the bundled quota. At each rollup snapshot, if the series' recomputed `cardinality_estimate` is **strictly greater** than the plan's `included_custom_metrics` plus the ten-thousand soft cap — equality does not trigger — and the series has no `OPEN` incident, the system opens a **CardinalityIncident**, recording the `opened_at_cardinality` and the `threshold_used` that fired.

The incident lifecycle is a cycle with one loop back. A `BillingAdmin` first triages an `OPEN` incident, moving it to `TRIAGED`. Remediation then requires a non-empty `remediation_note` describing the fix; on remediation the incident becomes `REMEDIATED` and two cascades fire: the parent series' `status` flips to `QUARANTINED`, and a quarantined series stops contributing to the account's billable custom-metric cardinality — the `CUSTOM_METRIC` meter accumulator no longer counts it. Thereafter the lifecycle is driven by the rollup snapshots themselves. When the series' `cardinality_estimate` has stayed below the threshold for two consecutive snapshots, a `REMEDIATED` incident advances automatically to `VERIFIED`. If instead the estimate crosses the threshold again while the incident is `VERIFIED`, the incident loops back to `OPEN` on recurrence and the parent series is quarantined again. A `BillingAdmin` closes a `VERIFIED` incident, moving it to the terminal `CLOSED` state and restoring the parent series to `ACTIVE` so it resumes contributing to billable cardinality.

Open incidents block the books: a billing period cannot be closed while any incident under the account is still `OPEN`, unless each such incident is explicitly waived; the attempt is rejected with `ERR_OPEN_INCIDENTS_BLOCK_CLOSE`.

### 3.8. Monitors and Plan Limits

A **Monitor** is an alerting rule created by a `BillingAdmin` or `TeamLead` with a `name` and a `monitor_kind` of `METRIC`, `LOG`, `APM`, or `SYNTHETIC`. New monitors start `ACTIVE`. The plan's hard cap counts only `ACTIVE` monitors: creating a monitor is rejected with `ERR_PLAN_LIMIT` when the account's count of `ACTIVE` monitors has already reached the plan's `max_monitors` — the cap is reached exactly when the active count equals the cap, so the create that would push it over fails. Muting a monitor moves it from `ACTIVE` to `MUTED` and releases its slot against the cap; deletion — a `BillingAdmin`-only operation available from any status — moves it to `DELETED`, which likewise does not count.

### 3.9. Period Close, Invoicing, Settlement, and Chargeback

When the logical clock has reached or passed a period's `period_end_utc`, a `BillingAdmin` may close it, moving the period from `OPEN` to `CLOSED`. Close is a compound transaction with four effects. First, the host billable counts are computed and locked by the two algorithms of §3.2 — the high-water mark and the ninety-ninth percentile — and the charged host count is fixed as the smaller of the two. Second, a draft **Invoice** is created in `DRAFT` status with one **InvoiceLine** per meter whose period quantity is non-zero; each line records its `meter` and the `rated_quantity` actually charged for that meter (the committed portion plus the overage portion), while the line's `amount_cents` is computed at issue time. Third, every commitment under the account whose window has elapsed settles per §3.4, converting unconsumed quantity into `expired_quantity`. Fourth — as a precondition rather than an effect — close is refused with `ERR_OPEN_INCIDENTS_BLOCK_CLOSE` while any cardinality incident under the account remains `OPEN` and unwaived, and refused outright while the logical clock still sits before `period_end_utc`.

A `BillingAdmin` issues a draft invoice, moving it from `DRAFT` to `ISSUED`. Issue is the moment money is computed: for each line, the committed portion's amount is the line's committed quantity times the commitment's `committed_unit_rate_cents`, rounded half-up to integer cents; the overage portion's amount is the overage quantity times the `overage_unit_rate_cents`, rounded half-up to integer cents; and the line's `amount_cents` is the sum of those two already-rounded amounts. The invoice's `total_amount_cents` is then the plain sum of the per-line amounts — per-line rounding first, sum second, in that pinned order (§2.7). From `ISSUED`, the invoice reaches a terminal state in one of two ways: payment moves it to `PAID` (and keeps the account's `standing` at `GOOD`), or voiding moves it to `VOID`.

With the invoice terminal, a `BillingAdmin` settles the period, moving it from `CLOSED` to the terminal `SETTLED` state; settlement requires the period's invoice to be `PAID` or `VOID`. Settling locks all usage records and meter accumulators under the period against further mutation.

Chargeback is computed on demand, never stored. When a `FinanceReader` or `BillingAdmin` requests the chargeback rollup for a period, the system rates each usage record in the period and sums per team — including only records whose `tag_compliant` flag is true and whose `disputed` flag is false. Records that fail tag compliance, or that carry no `team_id` at all, are excluded from every team's bucket and aggregated instead into a special `UNATTRIBUTED` bucket reported alongside the per-team figures; the response carries a `by_team` array and the `unattributed_cents` total. Disputed records sit out of the rollup entirely until their dispute resolves (§3.6).

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code. Operations that modify an existing resource — including all state-transition actions — return a `200 OK`. Readers must consult §2 and §3 for each endpoint's request fields, preconditions, and side effects; the table below is a navigation index, not a request/response specification.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/billing-accounts` | Create a BillingAccount | PlatformAdmin |
| GET | `/api/billing-accounts` | List BillingAccounts | PlatformAdmin, FinanceReader |
| GET | `/api/billing-accounts/{id}` | Get a BillingAccount | PlatformAdmin, BillingAdmin, FinanceReader, TeamLead |
| POST | `/api/plan-tier-configs` | Create a PlanTierConfig | PlatformAdmin |
| GET | `/api/plan-tier-configs/{id}` | Get a PlanTierConfig | PlatformAdmin, BillingAdmin, FinanceReader |
| POST | `/api/billing-accounts/{id}/billing-periods` | Open a new BillingPeriod | BillingAdmin |
| GET | `/api/billing-accounts/{id}/billing-periods` | List periods for the account | BillingAdmin, FinanceReader |
| GET | `/api/billing-accounts/{id}/billing-periods/{id}` | Get a BillingPeriod | BillingAdmin, FinanceReader, TeamLead |
| POST | `/api/billing-accounts/{id}/billing-periods/{id}/close` | Close the period and compute final billables + draft invoice | BillingAdmin |
| POST | `/api/billing-accounts/{id}/billing-periods/{id}/settle` | Settle a closed period | BillingAdmin |
| POST | `/api/billing-accounts/{id}/billing-periods/{id}/host-hour-records` | Record an hour's host attribution sample | IngestionAgent |
| GET | `/api/billing-accounts/{id}/billing-periods/{id}/host-hour-records` | List host hour records in a period | BillingAdmin, FinanceReader |
| GET | `/api/billing-accounts/{id}/billing-periods/{id}/meter-accumulators` | List meters for the period | BillingAdmin, FinanceReader, TeamLead |
| POST | `/api/billing-accounts/{id}/billing-periods/{id}/log-events` | Ingest a LogEvent | IngestionAgent |
| GET | `/api/billing-accounts/{id}/billing-periods/{id}/log-events` | List log events | BillingAdmin, FinanceReader |
| POST | `/api/billing-accounts/{id}/log-events/{id}/reindex` | Move an EXCLUDED event to INDEXED | BillingAdmin |
| POST | `/api/billing-accounts/{id}/retention-tiers` | Create a RetentionTier | BillingAdmin |
| GET | `/api/billing-accounts/{id}/retention-tiers` | List retention tiers | BillingAdmin, FinanceReader |
| POST | `/api/billing-accounts/{id}/exclusion-filters` | Create an exclusion filter | BillingAdmin |
| GET | `/api/billing-accounts/{id}/exclusion-filters` | List exclusion filters | BillingAdmin, FinanceReader |
| POST | `/api/billing-accounts/{id}/exclusion-filters/{id}/disable` | Disable an exclusion filter | BillingAdmin |
| POST | `/api/billing-accounts/{id}/custom-metric-series` | Register a custom metric series | BillingAdmin, TeamLead |
| GET | `/api/billing-accounts/{id}/custom-metric-series` | List custom metric series | BillingAdmin, FinanceReader, TeamLead |
| POST | `/api/billing-accounts/{id}/custom-metric-series/{id}/rollup` | Post a rollup snapshot | IngestionAgent |
| GET | `/api/billing-accounts/{id}/cardinality-incidents` | List cardinality incidents | BillingAdmin, FinanceReader |
| POST | `/api/billing-accounts/{id}/cardinality-incidents/{id}/triage` | Move an incident OPEN to TRIAGED | BillingAdmin |
| POST | `/api/billing-accounts/{id}/cardinality-incidents/{id}/remediate` | Move an incident TRIAGED to REMEDIATED | BillingAdmin |
| POST | `/api/billing-accounts/{id}/cardinality-incidents/{id}/close` | Move an incident VERIFIED to CLOSED | BillingAdmin |
| POST | `/api/billing-accounts/{id}/commitments` | Create a Commitment | BillingAdmin |
| GET | `/api/billing-accounts/{id}/commitments` | List commitments | BillingAdmin, FinanceReader |
| POST | `/api/billing-accounts/{id}/commitments/{id}/activate` | Activate a DRAFT commitment | BillingAdmin |
| POST | `/api/billing-accounts/{id}/commitments/{id}/top-up` | Top up an EXHAUSTED commitment | BillingAdmin |
| POST | `/api/billing-accounts/{id}/teams` | Create a Team | BillingAdmin |
| GET | `/api/billing-accounts/{id}/teams` | List teams | BillingAdmin, FinanceReader, TeamLead |
| POST | `/api/billing-accounts/{id}/billing-periods/{id}/usage-records` | Attribute usage to a team for chargeback | IngestionAgent, BillingAdmin |
| GET | `/api/billing-accounts/{id}/billing-periods/{id}/usage-records` | List usage records | BillingAdmin, FinanceReader, TeamLead |
| POST | `/api/billing-accounts/{id}/usage-records/{id}/disputes` | Open an attribution dispute | TeamLead |
| POST | `/api/billing-accounts/{id}/attribution-disputes/{id}/accept` | Accept a dispute and reassign attribution | BillingAdmin |
| POST | `/api/billing-accounts/{id}/attribution-disputes/{id}/reject` | Reject a dispute | BillingAdmin |
| POST | `/api/billing-accounts/{id}/tag-policies` | Create a TagPolicy | BillingAdmin |
| GET | `/api/billing-accounts/{id}/tag-policies` | List tag policies | BillingAdmin, FinanceReader |
| POST | `/api/billing-accounts/{id}/monitors` | Create a Monitor | BillingAdmin, TeamLead |
| GET | `/api/billing-accounts/{id}/monitors` | List monitors | BillingAdmin, FinanceReader, TeamLead |
| POST | `/api/billing-accounts/{id}/monitors/{id}/mute` | Mute an ACTIVE monitor | BillingAdmin, TeamLead |
| POST | `/api/billing-accounts/{id}/monitors/{id}/delete` | Delete a monitor | BillingAdmin |
| GET | `/api/billing-accounts/{id}/invoices/{id}` | Get an invoice | BillingAdmin, FinanceReader |
| GET | `/api/billing-accounts/{id}/invoices/{id}/lines` | List lines for an invoice | BillingAdmin, FinanceReader |
| POST | `/api/billing-accounts/{id}/invoices/{id}/issue` | Issue a DRAFT invoice | BillingAdmin |
| POST | `/api/billing-accounts/{id}/invoices/{id}/pay` | Mark an ISSUED invoice PAID | BillingAdmin |
| POST | `/api/billing-accounts/{id}/invoices/{id}/void` | Void an ISSUED invoice | BillingAdmin |
| GET | `/api/billing-accounts/{id}/billing-periods/{id}/chargeback` | Computed rollup per team plus UNATTRIBUTED bucket | FinanceReader, BillingAdmin |
| GET | `/api/billing-periods/{id}` | Fetch a BillingPeriod by id | BillingAdmin, FinanceReader, TeamLead |
| GET | `/api/billing-periods` | Filtered list of BillingPeriods | BillingAdmin, FinanceReader |
| GET | `/api/host-hour-records/{id}` | Fetch a HostHourRecord by id | BillingAdmin, FinanceReader |
| GET | `/api/host-hour-records` | Filtered list of HostHourRecords | BillingAdmin, FinanceReader |
| GET | `/api/meter-accumulators/{id}` | Fetch a MeterAccumulator by id | BillingAdmin, FinanceReader, TeamLead |
| GET | `/api/meter-accumulators` | Filtered list of MeterAccumulators | BillingAdmin, FinanceReader, TeamLead |
| GET | `/api/log-events/{id}` | Fetch a LogEvent by id | BillingAdmin, FinanceReader |
| GET | `/api/log-events` | Filtered list of LogEvents | BillingAdmin, FinanceReader |
| GET | `/api/retention-tiers/{id}` | Fetch a RetentionTier by id | BillingAdmin, FinanceReader |
| GET | `/api/retention-tiers` | Filtered list of RetentionTiers | BillingAdmin, FinanceReader |
| GET | `/api/exclusion-filters/{id}` | Fetch an ExclusionFilter by id | BillingAdmin, FinanceReader |
| GET | `/api/exclusion-filters` | Filtered list of ExclusionFilters | BillingAdmin, FinanceReader |
| GET | `/api/custom-metric-series/{id}` | Fetch a CustomMetricSeries by id | BillingAdmin, FinanceReader, TeamLead |
| GET | `/api/custom-metric-series` | Filtered list of CustomMetricSeries | BillingAdmin, FinanceReader, TeamLead |
| GET | `/api/cardinality-incidents/{id}` | Fetch a CardinalityIncident by id | BillingAdmin, FinanceReader |
| GET | `/api/cardinality-incidents` | Filtered list of CardinalityIncidents | BillingAdmin, FinanceReader |
| GET | `/api/commitments/{id}` | Fetch a Commitment by id | BillingAdmin, FinanceReader |
| GET | `/api/commitments` | Filtered list of Commitments | BillingAdmin, FinanceReader |
| GET | `/api/teams/{id}` | Fetch a Team by id | BillingAdmin, FinanceReader, TeamLead |
| GET | `/api/teams` | Filtered list of Teams | BillingAdmin, FinanceReader, TeamLead |
| GET | `/api/usage-records/{id}` | Fetch a UsageRecord by id | BillingAdmin, FinanceReader, TeamLead |
| GET | `/api/usage-records` | Filtered list of UsageRecords | BillingAdmin, FinanceReader, TeamLead |
| GET | `/api/attribution-disputes/{id}` | Fetch an AttributionDispute by id | BillingAdmin, FinanceReader, TeamLead |
| GET | `/api/attribution-disputes` | Filtered list of AttributionDisputes | BillingAdmin, FinanceReader, TeamLead |
| GET | `/api/tag-policies/{id}` | Fetch a TagPolicy by id | BillingAdmin, FinanceReader |
| GET | `/api/tag-policies` | Filtered list of TagPolicies | BillingAdmin, FinanceReader |
| GET | `/api/monitors/{id}` | Fetch a Monitor by id | BillingAdmin, FinanceReader, TeamLead |
| GET | `/api/monitors` | Filtered list of Monitors | BillingAdmin, FinanceReader, TeamLead |
| GET | `/api/invoices/{id}` | Fetch an Invoice by id | BillingAdmin, FinanceReader |
| GET | `/api/invoices` | Filtered list of Invoices | BillingAdmin, FinanceReader |
| GET | `/api/invoice-lines/{id}` | Fetch an InvoiceLine by id | BillingAdmin, FinanceReader |
| GET | `/api/invoice-lines` | Filtered list of InvoiceLines | BillingAdmin, FinanceReader |
| POST | `/_clock/set_current_utc` | Set the logical clock | PlatformAdmin |

List endpoints accept the standard `limit` and `offset` pagination parameters of §2.3 plus the resource-specific filters described in §3 (for example, listing billing periods accepts `status`; listing log events accepts `exclusion_state` and `service_tag`; the flat filtered lists accept the foreign-key filter named by the resource, such as `billing_account_id`, `billing_period_id`, `invoice_id`, `usage_record_id`, `raised_by_team_id`, `custom_metric_series_id`, or `team_id`, alongside attribute filters such as `plan_tier`, `standing`, `meter`, `enabled`, `monitor_kind`, `tag_compliant`, and `retention_tier_id`).

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narrative of §2 and §3; this table is the index of identifiers to HTTP status codes.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_PERIOD_CLOSED` | 409 |
| `ERR_ACCOUNT_DELINQUENT` | 409 |
| `ERR_COMMITMENT_WINDOW_OVERLAP` | 409 |
| `ERR_TIER_WINDOW_OVERLAP` | 409 |
| `ERR_PLAN_LIMIT` | 409 |
| `ERR_DUPLICATE_HOST_HOUR` | 409 |
| `ERR_NO_ACTIVE_COMMITMENT` | 409 |
| `ERR_OPEN_INCIDENTS_BLOCK_CLOSE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_TAG_POLICY_VIOLATION` | 422 |
