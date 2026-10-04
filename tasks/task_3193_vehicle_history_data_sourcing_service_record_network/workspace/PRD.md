# Vehicle History Network API — Product Requirements Document

## 1. Introduction

This document specifies the product requirements for the Vehicle History Network API: a multi-party platform that aggregates vehicle history data from a federated network of reporting partners — motor vehicle agencies, insurers, auto auctions, service shops, and inspection stations — and turns it into consumer- and dealer-facing history report products, backed by a buyback guarantee program. The platform's core challenge is trust: records arrive from dozens of independent sources with varying reliability, jurisdictions use inconsistent terminology for the same title brand, and the same event may be reported by multiple parties with conflicting details. The system therefore treats every record as an attributable, auditable event, maintains a rolling reliability score for every feed partner, normalizes jurisdictional brand vocabulary into a canonical severity-ranked taxonomy, and attaches a confidence level to every accident report.

Beyond ingestion, the platform governs the full commercial lifecycle around the data: service shops earn reporting tools in exchange for contributed history, owners and shops can challenge erroneous records through a source-verified correction workflow, dealers sync inventory listings that may be enrolled in a buyback guarantee, and both consumers and dealers purchase point-in-time report snapshots under distinct pricing models. A logical clock and a feed-health monitoring epoch drive all time-dependent behavior — decay, suspension, correction expiry, subscription windows, and claim settlement — making the entire system deterministic and testable.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming their operational capacity. A request missing either header, or presenting a role the platform does not declare, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. A request whose role is valid but not permitted for the target endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE`.

The platform recognizes six roles, spelled exactly as follows: `NetworkAdmin`, `SourceOperator`, `ShopOperator`, `VehicleOwner`, `DealerAgent`, and `GuaranteeAdmin`.

Identity semantics differ per role. When `X-User-Role` is `SourceOperator`, `X-User-ID` is the `id` of the acting `DataSource`; ownership checks on any resource that references a `DataSource` compare the resource's foreign-key field to `X-User-ID` — most notably, correction verification requires the acting operator's id to equal the challenged record's `source_id`. When `X-User-Role` is `ShopOperator`, `X-User-ID` is the `id` of the acting `Shop`. When `X-User-Role` is `VehicleOwner`, `X-User-ID` is the `id` of the acting `ConsumerAccount`. When `X-User-Role` is `DealerAgent`, `X-User-ID` is the `id` of the acting `Dealer`; ownership checks on listings and dealer-scoped report purchases compare the resource's `dealer_id` to `X-User-ID`. When `X-User-Role` is `NetworkAdmin` or `GuaranteeAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it against any entity's `id`.

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

List endpoints accept two query parameters. `limit` caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` skips a number of items from the front of the result set and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. Common Resource Properties and Monetized Precision

Every primary resource in the platform — Network, DataSource, Shop, Vehicle, HistoryRecord, CorrectionRequest, ConsumerAccount, Dealer, InventoryListing, GuaranteeClaim, and ReportOrder — carries a standard set of system-managed fields:

- `id` (string): a server-minted unique identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on any mutation of the resource's properties.
- `version` (integer): a system-managed counter that increments by exactly one on every mutation, including mutations caused by recomputation of derived fields.

All monetary quantities throughout the platform — prices, balances, asking prices, payouts, and caps — are expressed as integer cents. Calculations that would otherwise produce fractional cents (such as percentage-of-price guarantee payouts) are rounded down to the nearest whole cent. Confidence scores, reliability scores, and severity values are integers as described in their respective rules.

Requests that are structurally malformed — a missing required field, an invalid enum value, a negative amount, or an otherwise unparsable body — are rejected with `ERR_INVALID_REQUEST` before any business validation runs.

### 2.5. The Logical Clock and the Feed-Health Epoch

Time inside the platform is governed by a logical clock, not the wall clock. At server startup the logical clock reads exactly `2026-09-01T00:00:00Z`, and it must never fall back to wall-clock time thereafter; an admin-only test-driving capability sets the logical clock to a supplied `to_iso8601` instant. Record `event_date` values are validated against this logical clock's current date.

Coarser-grained operational time is tracked per network as an integer `epoch_index`, starting at 0 when a network is created. A `NetworkAdmin` advances the epoch by one through a dedicated capability; the advance is the heartbeat that drives feed reliability decay and auto-suspension, accident-confidence recomputation and unreliable-record purges, correction-request expiry, guarantee-claim settlement and denial sweeps, and dealer auto-suspension for overdue invoices (see §3.2 and §3.7). Several timestamps across the data model — `submitted_epoch_index`, `suspended_epoch_index`, `opened_epoch_index`, `source_deadline_epoch`, `subscription_started_epoch`, `window_start_epoch`, `window_end_epoch`, and `payout_epoch_index` — are expressed in epoch units and are always compared against the network's current `epoch_index`.

### 2.6. Feed Reliability and Source Suspension

Every `DataSource` carries a `reliability_score` from 0 to 100, starting at 100, plus two streak counters: `consecutive_missed_epochs`, counting epochs in a row in which the source submitted zero records, and `record_rejection_streak`, counting consecutively rejected submissions. Reliability is deliberately asymmetric: an idle epoch costs a source 10 points of reliability, while an active epoch recovers only 2 points, clamped to the 0–100 range. A rejected submission increments `record_rejection_streak` by one; an accepted submission resets it to zero. When either streak reaches 3, the source is automatically suspended — a decision that carries heavy downstream consequences described in §3.2.

### 2.7. Brand Normalization and Severity Ranking

Title-brand vocabulary differs across jurisdictions; the platform normalizes it against a per-network `brand_lexicon`, fixed at network creation, that maps each jurisdiction's raw wording to one of six canonical brands: `NONE`, `CLEAN`, `LEMON`, `FLOOD`, `REBUILT`, and `SALVAGE`. Canonical brands carry a strict severity ranking: `NONE` is 0, `CLEAN` is 1, `LEMON` is 2, `FLOOD` is 3, `REBUILT` is 4, and `SALVAGE` is 5. A `raw_brand_text` value that has no entry in the submitting record's jurisdiction lexicon cannot be normalized and is rejected with `ERR_UNKNOWN_BRAND_TERM`. The default lexicon installed at network creation covers, for jurisdiction CA, the mappings "salvage certificate" to `SALVAGE`, "revived salvage" to `REBUILT`, "flood" to `FLOOD`, "lemon law buyback" to `LEMON`, and "clean" to `CLEAN`; and for jurisdiction TX, "salvage title" to `SALVAGE`, "rebuilt" to `REBUILT`, "water damage" to `FLOOD`, "manufacturer buyback" to `LEMON`, and "clear" to `CLEAN`.

### 2.8. Optimistic Concurrency Control

Three write operations are protected by optimistic concurrency control, because each mutates (or reads a snapshot of) a parent aggregate whose `version` advances independently:

- Submitting a history record against a vehicle requires the request to carry `expected_vehicle_version`, the client last-observed `version` of the target `Vehicle`. If the vehicle's current `version` differs — because rollup recomputation on any record ingest, withdrawal, or supersession bumps it — the submission is rejected with `ERR_STALE_VERSION` (HTTP 412), forcing the client to re-read before writing.
- Opening a correction request against a vehicle likewise requires `expected_vehicle_version`; a stale value is rejected with `ERR_STALE_VERSION` (HTTP 412), since the requester may be challenging a rollup that no longer exists.
- Enrolling a listing into the buyback guarantee requires `expected_listing_version` matching the `InventoryListing`'s current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), because enrollment snapshots listing state and vehicle brand, both of which may have moved since the client's last read.

Endpoints not listed above do not accept a version field, and no OCC check is performed for them.

### 2.9. Hierarchical Consistency and Nested Resource Retrieval

Resources form a strict hierarchy: a Network contains DataSources, Shops, Vehicles, ConsumerAccounts, Dealers, and ReportOrders; a Vehicle contains HistoryRecords and CorrectionRequests; a Dealer contains InventoryListings and GuaranteeClaims. Whenever a parent undergoes a state change that invalidates its children — most notably source suspension withdrawing every record the source contributed — the cascade executes immediately and recomputes every derived value that depended on the withdrawn children, and each recomputation mutates the owning entity's `updated_at` and increments its `version`.

For any endpoint whose path nests multiple resource identifiers, the platform validates path segments left to right: the network first, then each successive child, returning `ERR_NOT_FOUND` for the first segment that does not resolve within its parent's scope, before any business rule is evaluated. State-machine legality is checked after existence: an operation on an existing resource whose current state does not permit the requested transition — including any re-trigger against a terminal state — is rejected with `ERR_INVALID_STATE_TRANSITION`.

The path-parameter identifiers used across the API are `networkId`, `sourceId`, `recordId`, `vehicleId`, `shopId`, `correctionId`, `consumerId`, `dealerId`, `listingId`, `claimId`, and `reportId`; each names the `id` of the corresponding resource as it appears in the endpoint paths of §4.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Network and Its Feed Partners

A `NetworkAdmin` creates a network by supplying a display `name` and a `guarantee_payout_cap_cents`, the per-vehicle lifetime cap on buyback payouts. The new network starts at `epoch_index` 0 with the default `brand_lexicon` of §2.7 installed, and with `enrolled_listing_count` at 0 — a running count of listings currently enrolled in the guarantee program.

With a network in place, the administrator registers data-sharing agreements as `DataSource` records, each identified by a `source_type` — one of `MVA`, `INSURER`, `AUCTION`, `SERVICE_SHOP`, or `INSPECTION_STATION` — and a `jurisdiction` naming the reporting authority's state or region code. A freshly registered source sits in `PENDING` status with a `reliability_score` of 100. Activation by a `NetworkAdmin` moves the source from `PENDING` to `ACTIVE`, resetting `consecutive_missed_epochs` to 0 and affirming the initial reliability of 100. Only `ACTIVE` sources may submit records; a submission aimed at a source in any other status is rejected with `ERR_SOURCE_NOT_ACTIVE`.

Sources are listed with optional `network_id`, `status`, and `source_type` filters, and each source exposes the list of records it has submitted, filterable by `status`.

### 3.2. Epoch Advancement: Decay, Suspension, and the Purge Sweep

Advancing the epoch is the platform's batch reconciliation. When a `NetworkAdmin` advances the epoch, the network's `epoch_index` increments by one and the following steps execute. For every `ACTIVE` source, the platform counts the records that source submitted during the epoch just ended. If the count is zero, `consecutive_missed_epochs` increments by one and the source's `reliability_score` drops by 10, never falling below 0. If the count is at least one, `consecutive_missed_epochs` resets to 0 and the `reliability_score` rises by 2, never exceeding 100. A source whose `consecutive_missed_epochs` reaches 3, or whose `record_rejection_streak` has reached 3, is automatically moved from `ACTIVE` to `SUSPENDED`.

Suspension is deliberately severe. The source's `suspended_epoch_index` is stamped with the current `epoch_index`, and every `ACTIVE` history record attributed to that source cascades to `WITHDRAWN`. Each withdrawal decrements the owning vehicle's `active_record_count` by one and re-runs the vehicle's brand and accident rollups (§3.4). Rollup changes may invalidate `OPEN` guarantee-claim escalations; those claims are re-evaluated during the same epoch advance's claim sweep and are moved to `DENIED` if the escalation no longer holds.

Remediation follows suspension. A `NetworkAdmin` may reactivate a suspended source only after at least one full epoch has elapsed since suspension — that is, the current `epoch_index` minus `suspended_epoch_index` must be at least 1, otherwise the request fails with `ERR_REMEDIATION_TOO_EARLY`. If the suspension was rejection-driven, the administrator must first reset the streak through a dedicated streak-reset capability; attempting reactivation while `record_rejection_streak` is still at 3 or above fails with `ERR_STREAK_NOT_RESET`. Successful reactivation returns the source to `ACTIVE`, sets `reliability_score` to 50, and zeroes both `consecutive_missed_epochs` and `record_rejection_streak`. Records withdrawn by the suspension cascade are not restored; the source must resubmit them.

Termination is the irreversible end of an agreement. An `ACTIVE` source may be terminated by a `NetworkAdmin` only when it has no `ACTIVE` records remaining; otherwise the termination is refused with `ERR_SOURCE_HAS_ACTIVE_RECORDS`. A `SUSPENDED` source may be terminated only after at least two epochs have elapsed since its suspension — the current `epoch_index` minus `suspended_epoch_index` must be at least 2, otherwise `ERR_TERMINATION_TOO_EARLY` is returned. `TERMINATED` is terminal.

The same epoch advance also recomputes accident confidence for every `ACTIVE` accident record using the source's post-decay reliability (the recomputed variant of §3.5), purges stale unreliable records (§3.5), expires overdue correction verifications (§3.6), settles approved claims and sweeps unjustified ones (§3.7), and suspends dealers whose invoice balance has exceeded the threshold (§3.8).

### 3.3. Ingesting History Records: VIN Matching, Dedupe, and Idempotency

A `SourceOperator` submits a history record by providing the `vin` the record pertains to, the `source_id` of the submitting source (which must match the operator's own identity), the `record_type` — one of `TITLE_BRAND`, `ACCIDENT`, `SERVICE`, or `INSPECTION` — and an `event_date` in ISO `YYYY-MM-DD` form. Type-specific fields apply: `jurisdiction` and `raw_brand_text` for title-brand records, `damage_severity` on a 1–10 scale for accident records, `odometer_reading` for service and inspection records, and `reported_cost_cents` for accident and service records; fields not applicable to the record's type are null. Every submission also carries a source-side `payload_ref` and a client-supplied `idempotency_key`. Because ingest mutates the matched vehicle's rollups, the request may carry `expected_vehicle_version` under the OCC rule of §2.8; a stale value is rejected with `ERR_STALE_VERSION`. An `event_date` later than the logical clock's current date is rejected with `ERR_EVENT_IN_FUTURE`.

The VIN is the matching backbone. When a vehicle already exists in the network whose `vin` equals the submitted `vin` exactly, the record attaches to that vehicle with `match_method` `EXACT_VIN`. When no exact match exists but exactly one vehicle in the network has a `vin` of the same 17-character length differing from the submitted VIN in exactly one character position, the record attaches to that vehicle with `match_method` `FUZZY_VIN`. When more than one existing vehicle sits at that distance, the submission is rejected with `ERR_AMBIGUOUS_VIN_MATCH` rather than risk a misattribution. When no vehicle matches at all, a new `Vehicle` is created lazily with the submitted `vin`, and the record attaches to it as an `EXACT_VIN` match. All vehicles in the network participate in matching regardless of status.

Before any dedupe logic runs, idempotency is honored: if the same `idempotency_key` arrives with an identical payload, the original record is returned unchanged and no new record is created. If the same `idempotency_key` arrives with a different payload, the submission is rejected with `ERR_IDEMPOTENCY_CONFLICT`.

Dedupe then groups records by a computed `dedupe_group_key`. For a `TITLE_BRAND` record the key combines the `vin`, the literal `TITLE_BRAND` type, and the `jurisdiction`; for `ACCIDENT` and `INSPECTION` records the key combines the `vin`, the `record_type`, and the `event_date`; for `SERVICE` records the key is null, because multiple service visits in one day are legitimate and never dedupe. Within a group, a new submission from the same source that matches an existing `ACTIVE` record's group is resolved by content: if the content fields — `raw_brand_text`, `damage_severity`, `odometer_reading`, and `reported_cost_cents` — are all identical to the existing record but the `idempotency_key` differs, the new submission is rejected with `ERR_DUPLICATE_RECORD`; if any content field differs, the new record supersedes the old. A submission from a different source in the same group is accepted as corroboration, not a duplicate.

Supersession links the two records: the old record transitions from `ACTIVE` to `SUPERSEDED`, its `superseded_by_record_id` points at the new record, the vehicle's `superseded_record_count` increments by one, and `active_record_count` is unchanged because the swap is one-for-one. The vehicle's brand rollup re-runs immediately, and the vehicle's `version` increments — which is precisely what the OCC rule on record submission protects against.

### 3.4. Vehicle Rollups: The Canonical Picture of a Vehicle

A `Vehicle` is little more than a `vin` plus a set of continuously maintained derived fields. Its `canonical_brand` is the brand of highest severity among the vehicle's `ACTIVE` title-brand records — `NONE` when no such records exist, with `brand_severity` 0 — and ties are broken by earliest `event_date`, then by earliest record `created_at`. Its `brand_severity` mirrors the winning record's severity. Its `active_record_count` counts `ACTIVE` records of all types, and its `superseded_record_count` counts those that have been superseded. Its `max_confirmed_accident_severity` is the maximum `damage_severity` over `ACTIVE` accident records whose `confidence_score` is at least 70, or 0 when no such record exists.

These rollups re-run on any transition of any of the vehicle's records into or out of `ACTIVE` — ingest, same-source supersession, suspension-cascade withdrawal, correction-driven withdrawal or supersession, and the unreliable-record purge alike. Every rollup recomputation mutates the vehicle, refreshing `updated_at` and incrementing `version`. Vehicles can be listed with optional `network_id` and `canonical_brand` filters, and each vehicle exposes its records, filterable by `record_type` and `status`.

### 3.5. Accident Confidence: Provisional and Recomputed Variants

Every accident record carries a computed `confidence_score` from 0 to 100 and a derived `confidence_level`: `HIGH` when the score is at least 85, `MEDIUM` when at least 70, `LOW` when at least 40, and `UNRELIABLE` below 40. Non-accident records carry no confidence values.

The score blends corroboration with source trust. Consider the set of other `ACTIVE` accident records on the same vehicle whose `event_date` lies within 30 days of this record's `event_date` in either direction and which were submitted by a different source. Records in that agreeing set submitted by sources of the same `source_type` as this record's source contribute a same-type bonus of 10 points each, capped at two contributing records for a maximum of 20 points. Records in that set from sources of a different `source_type` contribute a cross-type bonus of 20 points each, likewise capped at two contributing records for a maximum of 40 points. The base of 40 plus both bonuses is then multiplied by the submitting source's `reliability_score` divided by 100 — the score clamped to the 0–100 range — and the result is rounded down to an integer.

Two variants of this calculation exist and produce different scores for identical record data when reliability has moved. The provisional variant runs at ingest and uses the source's reliability as of the submission epoch. The recomputed variant runs during each epoch advance and uses the source's post-decay reliability; a record whose recomputed score crosses below 40 becomes `UNRELIABLE`. The epoch advance then purges unreliable history: any `ACTIVE` accident record whose recomputed `confidence_score` is below 40 and whose `submitted_epoch_index` is at least 2 epochs behind the current `epoch_index` — that is, the submitted epoch is less than or equal to the current epoch minus 2 — transitions from `ACTIVE` to `VOIDED`, decrementing the vehicle's `active_record_count` by one and re-running the accident rollup.

### 3.6. Service Shops, Service Records, and Reporting-Tool Tiers

Shops join the network through an application: a `NetworkAdmin` registers a shop with its `legal_name`, and the shop begins in `APPLIED` status with `reporting_tool_tier` `NONE`. Approval moves the shop from `APPLIED` to `ACTIVE` and does two more things atomically: it auto-provisions a dedicated `DataSource` of `source_type` `SERVICE_SHOP` with `jurisdiction` "SHOP" in `ACTIVE` status, recorded as the shop's `data_source_id`, and it grants the shop the `BASIC` reporting-tool tier. A shop's service records are always attributed to this provisioned source, never to a source of the shop's choosing.

Once `ACTIVE`, a `ShopOperator` submits service records against its own shop, providing the `vin`, `event_date`, `odometer_reading`, an optional `reported_cost_cents`, plus `payload_ref` and `idempotency_key`; the request may carry `expected_vehicle_version` under the OCC rule of §2.8. The platform forces the record type to `SERVICE`, sets `source_id` to the shop's provisioned source, leaves `jurisdiction` null, and then runs the same ingest pipeline as external records: VIN matching, idempotency, dedupe, rollup recomputation, and a `version` increment on the vehicle. A shop that is not `ACTIVE` cannot submit; the attempt is rejected with `ERR_SHOP_NOT_ACTIVE`.

Service and inspection records — from shops and external sources alike — are subject to odometer monotonicity: the submitted `odometer_reading` must be at least the maximum odometer reading across the vehicle's `ACTIVE` service and inspection records with an earlier `event_date`. Readings on the same day may tie. A reading below that maximum is rejected with `ERR_ODOMETER_ROLLBACK`.

Shops earn better tooling by contributing. The shop's tier is recomputed whenever a service record attributed to its provisioned source becomes `ACTIVE`, and on reversal when such a record leaves `ACTIVE`. The rule is a simple threshold over the count of the shop's `ACTIVE` service records: at 50 or more the tier is `PRO`; below 50 it is `BASIC`. The boundary is inclusive — exactly 50 earns `PRO`, while 49 leaves the shop at `BASIC`. Upgrades respect shop status: crossing the threshold while the shop is `SUSPENDED` defers the promotion, applying it only upon reactivation. Downgrades do not wait: when a reversal drops the count below 50, the shop returns from `PRO` to `BASIC` immediately regardless of status. Note that reaching a count of exactly 10 confers nothing new — the shop already holds `BASIC` from approval.

A `NetworkAdmin` may suspend an `ACTIVE` shop, stamping `suspended_epoch_index` with the current epoch; suspension blocks new service-record submissions via `ERR_SHOP_NOT_ACTIVE` but deliberately leaves the provisioned `DataSource` `ACTIVE` and withdraws no history. Reactivation requires at least one full epoch to have elapsed since suspension (otherwise `ERR_REMEDIATION_TOO_EARLY`) and applies any deferred tier upgrade. Terminating an `ACTIVE` shop is refused with `ERR_SHOP_HAS_OPEN_CORRECTIONS` while any correction request naming the shop as requester remains `OPEN` or `AWAITING_SOURCE`; otherwise the shop becomes `TERMINATED`, and its provisioned source is terminated too — but only if that source has no `ACTIVE` records, in which case the source stays `ACTIVE` even though the shop termination still succeeds. Shops are listed with optional `network_id`, `data_source_id`, and `status` filters, and each shop exposes its submitted service records.

### 3.7. Corrections: Source-Verified Dispute Resolution

When a vehicle owner or a shop believes a record is wrong, they open a correction request against the record's vehicle, supplying the `target_record_id`, a free-text `reason`, an optional `corrected_record` replacement payload, and `expected_vehicle_version` for the OCC check of §2.8 — a mismatch is rejected with `ERR_STALE_VERSION`. The target record must belong to the path vehicle and still be `ACTIVE`; otherwise the request is rejected with `ERR_RECORD_NOT_ACTIVE`. The new request opens in `OPEN` status, stamped with `opened_epoch_index` equal to the current epoch. The platform derives `requester_role` from the acting role — `OWNER` for a `VehicleOwner`, `SHOP` for a `ShopOperator` — and records `requester_shop_id` when the requester is a shop, leaving it null otherwise.

A `NetworkAdmin` routes an `OPEN` request to the record's owning source for verification, moving it from `OPEN` to `AWAITING_SOURCE`. The target record must still be `ACTIVE` at routing time, otherwise `ERR_RECORD_NOT_ACTIVE`. Routing sets `source_deadline_epoch` to the current epoch plus 2 — the source has two epochs to respond.

The owning `SourceOperator` then either confirms or denies the correction. Both actions require the acting operator's identity to equal the target record's `source_id`; any other source attempting verification is rejected with `ERR_NOT_RECORD_SOURCE`. Confirmation moves the request from `AWAITING_SOURCE` to `VERIFIED`; denial moves it to `REJECTED`, a terminal state. If the source does not respond in time, the epoch advance expires the request: when the current `epoch_index` moves past `source_deadline_epoch`, an `AWAITING_SOURCE` request transitions to `EXPIRED`, also terminal.

A `VERIFIED` request is applied by a `NetworkAdmin`, who chooses a `resolution_action`. `WITHDRAW` is always permitted and moves the request to `APPLIED` while transitioning the target record from `ACTIVE` to `WITHDRAWN` — firing the withdrawal cascade: the vehicle's `active_record_count` decrements by one and both the brand and accident rollups re-run. `SUPERSEDE` requires the `corrected_record` payload; applying a supersede without it fails with `ERR_CORRECTION_PAYLOAD_REQUIRED`. A supersede creates a replacement history record attributed to the target's original `source_id` carrying the corrected fields, transitions the target from `ACTIVE` to `SUPERSEDED` with `superseded_by_record_id` pointing at the replacement, and fires the supersession cascade of §3.3, including the brand rollup re-run. Either way, rollup changes are observed by open guarantee claims at the next epoch advance's claim sweep.

Correction requests can be read individually — including through a vehicle-scoped alias — listed per vehicle with an optional `status` filter, listed per network, or listed globally with `network_id`, `vehicle_id`, `target_record_id`, `requester_shop_id`, and `status` filters.

### 3.8. Dealers, Subscriptions, and the Report Ledger

A `NetworkAdmin` registers a dealer with its `legal_name`; the dealer starts `ACTIVE` with `subscription_tier` `NONE`, `period_reports_used` at 0, and `invoice_balance_cents` at 0. A `DealerAgent` acting for the dealer starts or renews a subscription by choosing a `tier` of `STANDARD` or `PRO` (or downgrading to `NONE`); the change stamps `subscription_started_epoch` with the current epoch and resets `period_reports_used` to 0, opening a fresh 30-epoch window.

The subscription window is half-open: it covers epochs from `subscription_started_epoch` inclusive up to but not including `subscription_started_epoch` plus 30. The last valid epoch is therefore the start epoch plus 29; a dealer-scoped report purchase at the start epoch plus 30 or later is rejected with `ERR_SUBSCRIPTION_WINDOW_EXPIRED`, and the dealer must resubscribe to continue.

Dealers are fiscally accountable. Overage report charges and approved guarantee payouts accrue to `invoice_balance_cents`. During an epoch advance, any dealer whose `invoice_balance_cents` exceeds 1,000,000 cents — ten thousand dollars — is automatically moved from `ACTIVE` to `SUSPENDED`, and suspension blocks both listing publication and guarantee enrollment: attempts at either fail with `ERR_DEALER_SUSPENDED`. A `NetworkAdmin` reinstates a suspended dealer only once the balance is back within the threshold — `invoice_balance_cents` at or below 1,000,000 — otherwise the reinstatement fails with `ERR_DEALER_BALANCE_OUTSTANDING`.

### 3.9. Inventory Listings and the Buyback Guarantee

A `DealerAgent` creates an inventory listing under their dealer by naming the `vehicle_id` on offer and an `asking_price_cents`. The listing begins in `DRAFT` status with `guarantee_status` `UNENROLLED`. Publication requires the dealer to be `ACTIVE` (otherwise `ERR_DEALER_SUSPENDED`), the acting agent to own the listing's dealer (otherwise `ERR_NOT_LISTING_OWNER`), and the vehicle to exist (otherwise `ERR_NOT_FOUND`). Publishing moves the listing from `DRAFT` to `PUBLISHED`, stamps `window_start_epoch` with the current epoch, and accepts an optional `window_end_epoch` — an exclusive end to the publication window, which must be strictly greater than `window_start_epoch`; when omitted, the window is open-ended and `window_end_epoch` stays null.

Enrollment into the buyback guarantee is the pivotal commercial act. The agent enrolls a listing by presenting `expected_listing_version` under the OCC rule of §2.8. Enrollment requires the listing to be `PUBLISHED`, the dealer `ACTIVE`, and the vehicle's current `canonical_brand` severity to be at most 1 — that is, `NONE` or `CLEAN`; any other combination is rejected with `ERR_NOT_ENROLLABLE`. On success the listing's `guarantee_status` moves from `UNENROLLED` to `ENROLLED`, the vehicle's current `canonical_brand` is snapshotted into `enrolled_brand` as the baseline for future claims, the network's `enrolled_listing_count` increments by one, and the listing's `version` increments by one.

Delisting moves a listing from `PUBLISHED` to terminal `DELISTED`. An enrolled listing may not be delisted while a claim on it is `OPEN` or `APPROVED` — the attempt fails with `ERR_CLAIM_IN_FLIGHT`. Otherwise delisting an enrolled listing voids the guarantee: `guarantee_status` moves from `ENROLLED` to `VOIDED` and the network's `enrolled_listing_count` decrements by one. Unenrolled listings delist without further effect.

Listings are readable per dealer with an optional `status` filter, per network, or globally with `network_id`, `vehicle_id`, `dealer_id`, and `status` filters.

### 3.10. Guarantee Claims: Escalation, Payout, and the Claim Sweep

A buyback claim is filed against an enrolled listing by a `GuaranteeAdmin`, or by a `DealerAgent` acting for the dealer that owns the listing — an agent acting for any other dealer is rejected with `ERR_NOT_LISTING_OWNER`. The filing supplies the `listing_id`, the buyer's `claimant_name`, and a free-text `claim_reason`, and the claim opens in `OPEN` status with `payout_cents` at 0.

Filing enforces two guards, both carrying HTTP 409. First, closed claim occupancy: at most one claim per listing may occupy the non-terminal set of `OPEN` or `APPROVED` at any time, so a second claim while an earlier one is still `OPEN` or `APPROVED` is rejected with `ERR_CLAIM_OVERLAP`. Second, the half-open publication window must contain the filing epoch: when the listing's `window_end_epoch` is set and the current `epoch_index` has reached it, filing is rejected with `ERR_LISTING_WINDOW_CLOSED`. Filing exactly at `window_end_epoch` minus 1 remains valid; filing at `window_end_epoch` itself is not. A listing whose guarantee is not currently `ENROLLED` rejects the filing with `ERR_GUARANTEE_NOT_ENROLLED`.

Approval is where the program pays out. A `GuaranteeAdmin` approves an `OPEN` claim only when three conditions hold: the listing's `guarantee_status` is still `ENROLLED` (otherwise `ERR_GUARANTEE_NOT_ENROLLED`); the vehicle's current `canonical_brand` severity is strictly greater than the `enrolled_brand` snapshot's severity (otherwise `ERR_BRAND_NOT_ESCALATED`); and the current canonical brand is attributable to a record that was `ACTIVE` at the epoch the claim opened or later — the escalation must be post-enrollment. Approval computes the payout (below), stamps it into `payout_cents`, voids the listing's guarantee — `guarantee_status` moves from `ENROLLED` to `VOIDED` and the network's `enrolled_listing_count` decrements by one — and adds the payout amount to the owning dealer's `invoice_balance_cents`, clawing the program cost back to the dealer ledger.

The payout waterfall evaluates in a fixed order: eligibility first, then the base, then the brand percentage, then the provisional payout, then the lifetime-cap clamp. The base is the listing's `asking_price_cents`. The severity delta is the vehicle's current `brand_severity` minus the `enrolled_brand` snapshot's severity — note the current rollup, not any snapshot, drives this figure; the snapshot only establishes that an escalation exists. A delta of 3 or more prices the brand percentage at 100 percent; a delta of exactly 2 prices it at 75 percent; a delta of 1 prices it at 50 percent. The provisional payout is the base multiplied by that percentage, divided by 100, and rounded down to whole cents. The lifetime dimension then clamps: the platform sums `payout_cents` over all `PAID` claims whose listings refer to the same vehicle, subtracts that from the network's `guarantee_payout_cap_cents` (never below zero), and the final `payout_cents` is the smaller of the provisional payout and that remaining lifetime allowance. Two variants therefore exist for identical listing and vehicle data: uncapped, when the remaining allowance covers the provisional payout in full, and capped, when earlier paid claims have drained the lifetime cap and the payout is clamped to what remains.

Rejection by a `GuaranteeAdmin` moves an `OPEN` claim to terminal `REJECTED` with no side effects. The epoch advance runs the claim sweep: any `OPEN` claim whose escalation no longer holds — for example because the record that produced the escalation has since been withdrawn — is moved to terminal `DENIED`. And one epoch after approval, the advance moves an `APPROVED` claim to terminal `PAID`, stamping `payout_epoch_index` with the current epoch and drawing the payout against the per-vehicle lifetime cap. Claims are readable individually, per dealer with an optional `status` filter, per network, or globally with `network_id`, `listing_id`, `dealer_id`, and `status` filters.

### 3.11. Report Products: Consumer Per-Report and Dealer Subscription Pricing

Reports are the read product of the network. A `VehicleOwner` registers a consumer account with an `email` unique within the network; the account starts with `credit_balance_cents` at 0, and a `NetworkAdmin` tops it up by an `amount_cents` that is added to the balance. Consumers can be listed per network or globally with an optional `network_id` filter.

Purchasing a report creates a `ReportOrder` naming the `vehicle_id` and a `product` of either `CONSUMER_SINGLE` or `DEALER_SUBSCRIPTION`, with `buyer_consumer_id` or `buyer_dealer_id` identifying the buyer as appropriate. The purchase is atomic and the order's `status` is `CONFIRMED` from creation — a terminal state. At purchase time the platform computes a point-in-time `snapshot` of the vehicle — its `canonical_brand`, its active title, accident, service, and inspection records, and per-accident confidence — freezes it onto the order, and never mutates it afterwards; the `price_cents` charged is likewise fixed at purchase.

Pricing follows a pinned evaluation order: determine eligibility, then compute included-versus-overage position, then compute the tiered overage price, then apply the floor, then debit the ledger, and only then increment the usage counter — so the current order is always priced against the pre-increment counter.

For `CONSUMER_SINGLE`, a `VehicleOwner` pays from prepaid credit. The first purchase for a given vehicle costs 3,999 cents; a returning buyer who already holds a prior `CONFIRMED` order for the same vehicle pays the reduced rate of 1,900 cents. The account's `credit_balance_cents` must cover the price at purchase time, otherwise the purchase is rejected with `ERR_INSUFFICIENT_CREDIT`; on success the price is debited from the balance.

For `DEALER_SUBSCRIPTION`, a `DealerAgent` buys against the dealer's subscription. A dealer whose `subscription_tier` is `NONE` is rejected with `ERR_NO_SUBSCRIPTION`, and a purchase outside the current 30-epoch window is rejected with `ERR_SUBSCRIPTION_WINDOW_EXPIRED` (§3.8). Within a valid window, the first tranche of reports is included in the subscription — 25 reports for `STANDARD`, 200 for `PRO` — and costs 0 cents while `period_reports_used` is below the included count. Beyond the included count, each report is an overage unit priced on a declining tier: the first ten overage reports (overage units 1 through 10) cost 500 cents each, the next ten (units 11 through 20) cost 400 cents each, the tier stepping down by 100 cents for every further block of ten overage units, subject to a floor of 300 cents per report below which the price never falls. Formally, for the overage unit whose 1-based index is the pre-increment `period_reports_used` minus the included count plus one, the price is 500 minus 100 times the whole number of complete blocks of ten before that unit's index, floored at 300. Every overage charge accrues to the dealer's `invoice_balance_cents`, and `period_reports_used` increments by one with each dealer-subscription purchase — which is what the auto-suspension rule of §3.8 ultimately polices. The dealer's `period_overage_units` is the amount by which `period_reports_used` exceeds the included count, never below zero.

Report orders are readable individually (including the frozen snapshot), per vehicle, per consumer, per dealer, per network, or globally with `network_id`, `vehicle_id`, `buyer_consumer_id`, `buyer_dealer_id`, and `product` filters.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource return `200 OK`. Validation failures, state conflicts, fiscal rejections, and concurrency mismatches return the 4xx codes catalogued in §5.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock | NetworkAdmin |
| POST | `/networks` | Create a network with brand lexicon and guarantee cap | NetworkAdmin |
| GET | `/networks/{networkId}` | Get a network | Any |
| GET | `/networks/{networkId}/corrections` | List correction requests within a network | Any |
| GET | `/networks/{networkId}/consumers` | List consumer accounts within a network | Any |
| GET | `/networks/{networkId}/dealers` | List dealers within a network | Any |
| GET | `/networks/{networkId}/records` | List records within a network | Any |
| GET | `/networks/{networkId}/listings` | List listings within a network | Any |
| GET | `/networks/{networkId}/claims` | List claims within a network | Any |
| GET | `/networks/{networkId}/reports` | List report orders within a network | Any |
| POST | `/advance_epoch` | Advance the feed-health monitoring epoch by one | NetworkAdmin |
| POST | `/sources` | Register a data source agreement | NetworkAdmin |
| GET | `/sources/{sourceId}` | Get a data source | Any |
| GET | `/sources` | List data sources | Any |
| POST | `/sources/{sourceId}/activate` | Activate a PENDING source | NetworkAdmin |
| POST | `/sources/{sourceId}/reactivate` | Reactivate a SUSPENDED source after remediation | NetworkAdmin |
| POST | `/sources/{sourceId}/reset_streak` | Reset the record rejection streak to 0 | NetworkAdmin |
| POST | `/sources/{sourceId}/terminate` | Terminate a source agreement | NetworkAdmin |
| GET | `/sources/{sourceId}/records` | List records submitted by a source | Any |
| POST | `/records` | Submit a history record from an external data source | SourceOperator |
| GET | `/records` | List history records across the network | Any |
| GET | `/records/{recordId}` | Get a history record | Any |
| GET | `/vehicles/{vehicleId}/records` | List records for a vehicle | Any |
| GET | `/vehicles/{vehicleId}` | Get a vehicle (rollups included) | Any |
| GET | `/vehicles` | List vehicles | Any |
| POST | `/shops` | Apply for a service shop membership | NetworkAdmin |
| GET | `/shops/{shopId}` | Get a shop | Any |
| GET | `/shops` | List shops | Any |
| POST | `/shops/{shopId}/approve` | Approve a shop; provisions its SERVICE_SHOP data source | NetworkAdmin |
| POST | `/shops/{shopId}/suspend` | Suspend a shop | NetworkAdmin |
| POST | `/shops/{shopId}/reactivate` | Reactivate a suspended shop; applies deferred tier upgrades | NetworkAdmin |
| POST | `/shops/{shopId}/terminate` | Terminate a shop | NetworkAdmin |
| POST | `/shops/{shopId}/service-records` | Shop submits a service record via its provisioned source | ShopOperator |
| GET | `/shops/{shopId}/service-records` | List a shop's submitted service records | Any |
| POST | `/vehicles/{vehicleId}/corrections` | Open a data correction request against a record | VehicleOwner, ShopOperator |
| GET | `/corrections/{correctionId}` | Get a correction request | Any |
| GET | `/vehicles/{vehicleId}/corrections/{correctionId}` | Get a correction request (vehicle-scoped alias) | Any |
| GET | `/vehicles/{vehicleId}/corrections` | List corrections for a vehicle | Any |
| GET | `/corrections` | List correction requests (filtered) | Any |
| POST | `/corrections/{correctionId}/route_to_source` | Route correction to the owning source for verification | NetworkAdmin |
| POST | `/corrections/{correctionId}/source_confirm` | Owning source verifies the correction | SourceOperator |
| POST | `/corrections/{correctionId}/source_deny` | Owning source denies the correction | SourceOperator |
| POST | `/corrections/{correctionId}/apply` | Apply a verified correction (withdraw or supersede) | NetworkAdmin |
| POST | `/consumers` | Register a consumer account | VehicleOwner |
| GET | `/consumers/{consumerId}` | Get a consumer account | Any |
| GET | `/consumers` | List consumer accounts (filtered) | Any |
| POST | `/consumers/{consumerId}/credit` | Top up consumer prepaid credit | NetworkAdmin |
| POST | `/dealers` | Register a dealer | NetworkAdmin |
| GET | `/dealers/{dealerId}` | Get a dealer | Any |
| GET | `/dealers` | List dealers (filtered) | Any |
| POST | `/dealers/{dealerId}/subscribe` | Start or renew a subscription tier; resets the window and counter | DealerAgent |
| POST | `/dealers/{dealerId}/reinstate` | Reinstate a suspended dealer whose balance is within threshold | NetworkAdmin |
| POST | `/dealers/{dealerId}/listings` | Create an inventory listing (DRAFT) | DealerAgent |
| GET | `/dealers/{dealerId}/listings` | List a dealer's listings | Any |
| GET | `/listings/{listingId}` | Get a listing | Any |
| GET | `/listings` | List listings across the network (filtered) | Any |
| POST | `/dealers/{dealerId}/listings/{listingId}/publish` | Publish a listing; starts its publication window | DealerAgent |
| POST | `/dealers/{dealerId}/listings/{listingId}/delist` | Delist a listing; enrolled guarantees are voided unless a claim is in flight | DealerAgent |
| POST | `/dealers/{dealerId}/listings/{listingId}/enroll_guarantee` | Enroll a published listing in the buyback guarantee | DealerAgent |
| POST | `/claims` | File a buyback guarantee claim | GuaranteeAdmin, DealerAgent |
| GET | `/claims/{claimId}` | Get a claim | Any |
| GET | `/claims` | List claims across the network (filtered) | Any |
| GET | `/dealers/{dealerId}/claims` | List claims for a dealer | Any |
| POST | `/claims/{claimId}/approve` | Approve a claim; computes payout, voids guarantee, debits dealer ledger | GuaranteeAdmin |
| POST | `/claims/{claimId}/reject` | Reject a claim | GuaranteeAdmin |
| POST | `/reports` | Purchase a vehicle history report | VehicleOwner, DealerAgent |
| GET | `/reports/{reportId}` | Get a report order including its frozen snapshot | Any |
| GET | `/reports` | List report orders across the network (filtered) | Any |
| GET | `/vehicles/{vehicleId}/reports` | List report orders for a vehicle | Any |
| GET | `/consumers/{consumerId}/reports` | List report orders bought by a consumer | Any |
| GET | `/dealers/{dealerId}/reports` | List report orders bought by a dealer | Any |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE_TRANSITION` | 409 |
| `ERR_SOURCE_NOT_ACTIVE` | 409 |
| `ERR_SHOP_NOT_ACTIVE` | 409 |
| `ERR_AMBIGUOUS_VIN_MATCH` | 409 |
| `ERR_EVENT_IN_FUTURE` | 422 |
| `ERR_IDEMPOTENCY_CONFLICT` | 409 |
| `ERR_DUPLICATE_RECORD` | 409 |
| `ERR_UNKNOWN_BRAND_TERM` | 422 |
| `ERR_ODOMETER_ROLLBACK` | 422 |
| `ERR_RECORD_NOT_ACTIVE` | 409 |
| `ERR_NOT_RECORD_SOURCE` | 403 |
| `ERR_CORRECTION_PAYLOAD_REQUIRED` | 400 |
| `ERR_REMEDIATION_TOO_EARLY` | 409 |
| `ERR_TERMINATION_TOO_EARLY` | 409 |
| `ERR_STREAK_NOT_RESET` | 409 |
| `ERR_SOURCE_HAS_ACTIVE_RECORDS` | 409 |
| `ERR_SHOP_HAS_OPEN_CORRECTIONS` | 409 |
| `ERR_INSUFFICIENT_CREDIT` | 402 |
| `ERR_NO_SUBSCRIPTION` | 402 |
| `ERR_SUBSCRIPTION_WINDOW_EXPIRED` | 409 |
| `ERR_DEALER_SUSPENDED` | 409 |
| `ERR_DEALER_BALANCE_OUTSTANDING` | 409 |
| `ERR_NOT_LISTING_OWNER` | 403 |
| `ERR_NOT_ENROLLABLE` | 409 |
| `ERR_GUARANTEE_NOT_ENROLLED` | 409 |
| `ERR_BRAND_NOT_ESCALATED` | 409 |
| `ERR_CLAIM_IN_FLIGHT` | 409 |
| `ERR_CLAIM_OVERLAP` | 409 |
| `ERR_LISTING_WINDOW_CLOSED` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_REQUEST` | 400 |
