# Connected Vehicle Emergency Services API — Product Requirements Document

## 1. Introduction

This document specifies the product requirements for the Connected Vehicle Emergency Services API, a platform that combines automatic crash notification, emergency dispatch coordination, stolen-vehicle assistance, vehicle diagnostics, and subscription management into a single telematics offering. The service is sold to vehicle owners as a tiered subscription: at the low end a safety-only tier that entitles the vehicle to automatic crash notification and SOS dispatch, and at the high end a premium tier that adds remote lock/unlock/horn/locate commands, turn-by-turn navigation, and a monthly cellular data allowance. Every subscription begins as a time-boxed trial; the platform must handle trial conversion, billing retries, lapse, an emergency-only retention decision, reactivation, and final cancellation.

Two properties of the domain shape the system's design. First, all safety-relevant behavior is contingent on cellular coverage: a vehicle whose crash or command originates in a region without cellular service cannot be reached by the platform, and coverage takes precedence over every entitlement check. Second, certain interventions — most notably remote slowdown of a stolen vehicle — require segregation of duties between law enforcement (who reports and verifies a theft) and emergency operations (who arm and execute the slowdown), with strict hardware and coverage preconditions before the slowdown capability is unlocked. A logical clock governs all time-dependent behavior — trial expiry, billing retry windows, lapse and retention deadlines, remote-command expiry, and the trailing windows used in scoring — so the entire system can be driven deterministically in test.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules and contracts that apply to every endpoint.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two headers: `X-User-ID` identifying the acting principal and `X-User-Role` naming the operational capacity. A request missing either header, or carrying a role value the server does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The two endpoints exempt from this requirement are the logical-clock setter and the vehicle-ingestion endpoints (crash events, diagnostic reports, and remote-command outcome reports). The logical-clock setter performs no authentication or role check at all. The ingestion endpoints accept requests with no auth headers at all; when auth headers are supplied, the presented role must be `SystemIngestion` — a request carrying any other recognized role is rejected with `ERR_UNAUTHORIZED` (HTTP 403), and a request whose supplied role value is not recognized is rejected with `ERR_UNAUTHENTICATED` (HTTP 401).

The recognized roles, with exact spelling, are: `PlatformAdmin`, `Account`, `Advisor`, `PSAPOperator`, `LawEnforcement`, `EmergencyOperator`, `DealerService`, `BillingAdmin`, and `SystemIngestion`. Any attempt to invoke an operation outside the caller's role — or, for an entity-backed role, to act on a resource owned by another principal — is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

Identity semantics differ per role. When `X-User-Role` is `Account`, `X-User-ID` is the `id` of the acting `Account` resource; ownership checks on any resource that references an `Account` (vehicles, subscriptions, consents, appointments created by an account) compare the resource's foreign-key field to `X-User-ID`. Vehicle-descendant resources — crash events, remote commands, diagnostic reports, and service appointments — are scoped through their vehicle: a single-resource read by an `Account` caller whose vehicle belongs to a different account is rejected with `ERR_UNAUTHORIZED`, and flat list endpoints invoked by an `Account` caller silently restrict their result sets to resources attached to that account's own vehicles (or, for consents and subscriptions, to the account itself) rather than erroring. Stolen-vehicle case reads carry no `Account` ownership check. When `X-User-Role` is any of `PlatformAdmin`, `Advisor`, `PSAPOperator`, `LawEnforcement`, `EmergencyOperator`, `DealerService`, `BillingAdmin`, or `SystemIngestion`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `verified_by_user_id` on a `StolenVehicleCase` when a `LawEnforcement` officer verifies a report — but it does not compare it to any entity's `id` for authorization purposes.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, taken from the server's wall clock (not the logical clock). Requests to unrecognized paths, or recognized paths with an unsupported method, are answered with `ERR_NOT_FOUND` (HTTP 404) in the standard error envelope.
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

List endpoints accept two query parameters: `limit` and `offset`. The `limit` parameter specifies the maximum number of items to return; it defaults to 10, has a minimum of 1, and has a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0. Out-of-range values are clamped rather than rejected: a `limit` below 1 is treated as 1, a `limit` above 100 is treated as 100, a negative `offset` is treated as 0, and a non-integer `limit` or `offset` falls back to its default. All list endpoints return resources sorted by `created_at` in ascending order unless stated otherwise, with ties broken by `id` in ascending order. The `meta` object of every list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every primary resource in the system — `PlanTier`, `Account`, `Vehicle`, `Subscription`, `CoverageZone`, `CrashEvent`, `DispatchRequest`, `PSAP`, `StolenVehicleCase`, `RemoteCommand`, `DiagnosticReport`, `Dealer`, `ServiceAppointment`, and `DataConsent` — carries a standard set of system-managed fields:

- `id` (string): a unique, server-generated UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, stamped from the logical clock when the resource is first persisted.
- `updated_at` (string): an ISO 8601 UTC timestamp stamped from the logical clock on every mutation of the resource.
- `version` (integer): a system-managed integer that starts at 1 on creation and increments by exactly 1 on every mutation.

All entities in this domain carry the full common-field set; none is exempt. In addition, every lifecycle-bearing entity exposes a `status` field whose value is drawn from that entity's state machine (the exact enumeration values appear throughout §3 in UPPERCASE). List endpoints that support filtering accept `status` as a query parameter, matching against those exact strings.

### 2.5. Nested Resource Retrieval and Path Validation

The API exposes both nested paths (for example, a subscription addressed under its owning account) and flat, filterable list paths (for example, a cross-account subscription listing). For any endpoint whose path contains multiple resource identifiers, the server validates identifiers in a strict left-to-right order: each identifier must exist, and each child must belong to the parent declared to its left. The first identifier that fails existence or parentage produces an `ERR_NOT_FOUND` (HTTP 404) and the request stops there — later identifiers in the path are not consulted. This applies uniformly to reads, writes, and action endpoints.

### 2.6. The Logical Clock

All time-dependent behavior in the system — trial expiry, billing retry windows, retention deadlines, command expiry, trailing scoring windows — is driven by a single logical clock, never by wall-clock time. Before any clock-setting call has been made, the logical clock reads exactly `2026-09-01T00:00:00Z`. A `PlatformAdmin` may advance the logical clock by posting the target instant in a `to_iso8601` field; a missing or malformed `to_iso8601` is rejected with `ERR_INVALID_REQUEST`. The call returns the new value in a `current_utc` field. Advancing the clock fires every time-based transition that has become due: a `PAST_DUE` subscription whose retry window has closed lapses, a `LAPSED` subscription whose retention window has closed is cancelled, and any `RemoteCommand` whose `expires_at` has been reached flips to `EXPIRED`. The same time-based transitions are also re-evaluated lazily whenever a subscription endpoint or a remote-command endpoint is served, so their effects are observable on those resources even between clock-setting calls.

### 2.7. Optimistic Concurrency Control on Subscription Writes

Two subscription-mutating operations — converting a trial to paid, and reactivating an emergency-retained subscription — require the client to declare the subscription version it last observed. The request body for either operation must carry `expected_subscription_version`. If the supplied value does not equal the subscription's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412), and no state change occurs. This protects the client from acting on a subscription that has already been converted or reactivated by another writer: the prior write legitimately supersedes the stale writer's intent. Endpoints not named here do not take a version field; all other writes are single-writer sequential by role.

### 2.8. Validation Order

When multiple validation rules apply to a single request, the server evaluates them in a fixed priority order so that callers see a deterministic error rather than whichever rule happened to fire first. The order is: (1) authentication — auth headers present and the role recognized, else `ERR_UNAUTHENTICATED`; (2) authorization — role permitted for the operation and, for entity-backed roles, ownership verified, else `ERR_UNAUTHORIZED`; (3) path existence and parentage, validated left-to-right, else `ERR_NOT_FOUND`; (4) request-body well-formedness — required fields present, enum values valid, types correct — else `ERR_INVALID_REQUEST`; (5) optimistic concurrency — `expected_subscription_version` matches the current `version` where applicable, else `ERR_STALE_VERSION`; (6) state-machine legality — the target resource is in a valid from-state for the requested transition, else `ERR_INVALID_STATE`; (7) safety gates on stolen-vehicle slowdown — verification precedes arming, generation-5 hardware present, cellular coverage in the vehicle's region, and reporter distinct from verifier — else the matching safety error; (8) temporal gates — retention window, future-dated appointments, monotonic odometer, remote-command cap window — else the matching temporal error; (9) constraint gates — PSAP availability and region match, dealer capacity, consent dependencies, uniqueness — else the matching constraint error; (10) coverage and entitlement gates — cellular coverage dominates, emergency entitlement, tier capability flags, emergency-only command restriction — else the matching coverage/entitlement error; and finally (11) billing-transition legality, else `ERR_BILLING_TRANSITION_INVALID`. Later rules are consulted only after all earlier rules pass. Three refinements pin the order where the list above is ambiguous. For an identifier carried in the request body rather than the path (for example, the `vehicle_id` on subscription creation or the `psap_id` on dispatch creation), the referenced resource's existence is checked after body well-formedness, and any ownership check on it follows its existence check. For crash-event ingestion, the severity-threshold check is evaluated immediately after request-body well-formedness, before the coverage and entitlement gates. For remote-command creation, the evaluated order is coverage, then entitlement, then the periodic cap window.

### 2.9. Coverage Dominates Entitlement

Every telematics operation — crash-event ingestion, remote commands, navigation, and data connectivity — is gated first by the `CoverageZone` of the operating region and only then by the subscription's entitlements. If the `CoverageZone` row for the region has `has_cellular` set to false — or no `CoverageZone` row exists for the region at all — the operation is rejected with `ERR_NO_CELLULAR_COVERAGE` regardless of how generous the subscription's tier is. Only after coverage is established does the server consult the entitlement snapshot: tier capability flags for fully-paid statuses, the emergency-only bundle for `EMERGENCY_RETAINED` subscriptions, and nothing at all for `LAPSED`, `CANCELLED`, or missing subscriptions.

### 2.10. Precision and Rounding

Monetary amounts are always integers of cents. Computed severity values are carried to 1 decimal place with round-half-up. Insurance scores are carried to 2 decimal places with round-half-up. Health scores and command counts are integers; wherever the health-score formula divides, the division is integer division that truncates toward zero, and the truncation happens before the result is clamped. Threshold comparisons throughout the system are inclusive at the boundary unless explicitly stated otherwise.

## 3. Business Logic & Workflows

### 3.1. Platform Onboarding: Tiers, Coverage, Accounts, and Vehicles

Before any subscriber activity can occur, a `PlatformAdmin` seeds the platform's reference data. A `PlanTier` is defined by its `code` — one of `EMERGENCY_ONLY`, `SAFETY`, `SAFETY_REMOTE`, or `PREMIUM`, unique across tiers — together with its `monthly_fee_cents` (a non-negative integer of cents) and four entitlement flags: `allows_emergency` (entitles automatic crash notification and SOS dispatch), `allows_remote_commands` (entitles lock, unlock, horn-and-lights, and locate commands), `allows_navigation` (entitles turn-by-turn navigation), and `allows_data_gb` (a non-negative monthly data allowance in gigabytes, where 0 means the tier carries no data-connectivity entitlement). Newly created tiers arrive in `ACTIVE` status; a tier that is no longer offered transitions to `RETIRED`.

Coverage is defined per region through `CoverageZone` records. Each zone maps a two-letter `region_code` (unique across zones) to three booleans: `has_cellular` (whether cellular telematics service is available in the region at all), `supports_data` (whether data connectivity is offered there), and `supports_navigation` (whether navigation services are offered). A vehicle may only be registered into a region that has a `CoverageZone` row; a registration naming a region with no `CoverageZone` row is rejected with `ERR_INVALID_REQUEST`.

Account registration captures the account holder's `full_name`, a unique `email` (uniqueness enforced across accounts, with duplicates rejected as `ERR_DUPLICATE`), a contact `phone` in E.164 form, and a `home_region_code` used to seed coverage evaluation. Accounts are created in `ACTIVE` status; closure moves them to `CLOSED`.

A vehicle is registered by its owning account with a `vin` (exactly 17 characters, uppercase alphanumeric excluding the letters I, O, and Q; unique across the platform, with duplicates rejected as `ERR_DUPLICATE`), the `make` and `model` strings, a `model_year` of 2015 or later, the two-letter `region_code` of its primary operating region, and a `hardware_generation` of either 4 or 5 — only generation 5 supports remote slowdown. The owning account's identity is persisted on the vehicle as `account_id`, and the flat cross-account vehicle list accepts `account_id` and `status` as filter parameters. New vehicles arrive in `ACTIVE` status. From there the vehicle lifecycle admits four transitions: a verified stolen-vehicle report moves the vehicle from `ACTIVE` to `STOLEN_REPORTED`; closing the case as recovered moves it from `STOLEN_REPORTED` to `RECOVERED`; the account may then update the vehicle from `RECOVERED` back to `ACTIVE`; and the account may decommission an `ACTIVE` vehicle by updating its status to `DECOMMISSIONED` — but only when no subscription on that vehicle sits in `TRIAL`, `ACTIVE`, `PAST_DUE`, or `EMERGENCY_RETAINED`. Any other vehicle-state update is rejected with `ERR_INVALID_STATE`.

### 3.2. The Subscription Lifecycle: Trial, Billing, Lapse, and the Emergency-Retention Decision

A subscription is created by the account for a specific `vehicle_id` against a chosen `tier_code`. A `vehicle_id` that does not exist is rejected with `ERR_NOT_FOUND`, a vehicle owned by a different account is rejected with `ERR_UNAUTHORIZED`, and a `tier_code` naming no defined tier is rejected with `ERR_INVALID_REQUEST`; the tier's own status is not consulted, so a `RETIRED` tier remains subscribable. Only one non-terminal subscription may exist per vehicle. On creation the subscription enters `TRIAL` status, the server stamps `trial_start_date` from the logical clock, and `trial_end_date` is computed as exactly 30 days after the trial start. The `current_period_start` is set to the creation date, and `next_renewal_date` is computed as 30 days after `current_period_start` while the subscription is `ACTIVE` (and null in any other status, including `TRIAL`). Two further system-managed fields book-keep the lifecycle: `lapse_date`, which is set when the subscription enters `LAPSED` and remains null otherwise, and `conversion_fee_paid_cents`, which records the fee charged on trial conversion (0 when waived). The computed `emergency_only_flag` is true whenever the subscription's status is `EMERGENCY_RETAINED`, and also true when an `ACTIVE` subscription sits on a tier whose `allows_emergency` is true while every other entitlement flag is false; it is false in all other cases.

**Conversion.** Converting a trial to paid moves the subscription from `TRIAL` to `ACTIVE`. The request must carry `expected_subscription_version` matching the subscription's current `version`; a stale value is rejected with `ERR_STALE_VERSION` (HTTP 412). The conversion fee is evaluated in a pinned order: if the logical-clock date is strictly before `trial_end_date`, the fee is 0 regardless of tier price; otherwise the fee is the larger of zero and the tier's `monthly_fee_cents` multiplied by 0.20, with the product rounded half-up to the cent exactly once and no second rounding applied after the maximum is taken. The result is recorded as `conversion_fee_paid_cents`. A successful conversion also resets `current_period_start` to the logical-clock date, sets `next_renewal_date` to 30 days later, and increments the subscription's `version` by 1.

**Billing events.** A `BillingAdmin` records payment outcomes against an `ACTIVE` or `PAST_DUE` subscription via an `outcome` field. Three transitions exist. A `PAYMENT_FAILED` outcome against an `ACTIVE` subscription moves it to `PAST_DUE`; `next_renewal_date` is left unchanged and a 10-day retry window opens. A `PAYMENT_SUCCEEDED` outcome against a `PAST_DUE` subscription returns it to `ACTIVE`, resetting `current_period_start` to the logical-clock date, pushing `next_renewal_date` 30 days out, and zeroing `period_remote_commands_used`. A `PAYMENT_SUCCEEDED` outcome against an `ACTIVE` subscription is a renewal: it leaves the status at `ACTIVE` but performs the same period reset — `current_period_start` to the logical-clock date, `next_renewal_date` 30 days out, `period_remote_commands_used` zeroed. Any other combination of outcome and current status is rejected with `ERR_BILLING_TRANSITION_INVALID`.

**Lapse and the retention decision.** When the logical clock reaches 10 days after the date a `PAST_DUE` subscription entered that state without a successful payment, the subscription transitions automatically to `LAPSED`; `lapse_date` is stamped from the logical clock and `next_renewal_date` becomes null. The account then faces a 30-day retention window: the account may keep emergency-only functionality by exercising the retention decision while the logical-clock date is on or before `lapse_date` plus 30 days — reaching the boundary exactly still qualifies — provided the linked vehicle is still in `ACTIVE` status (a retention attempt whose vehicle is not `ACTIVE` is rejected with `ERR_INVALID_STATE`). A successful retention moves the subscription from `LAPSED` to `EMERGENCY_RETAINED` and sets `emergency_only_flag` to true; an attempt past the window is rejected with `ERR_RETENTION_WINDOW_EXPIRED`. If the retention window closes with no decision, the system transitions the subscription to `CANCELLED` and clears `emergency_only_flag` to false.

**Emergency-retained behavior.** While a subscription sits in `EMERGENCY_RETAINED`, its entitlements collapse to a fixed bundle: automatic crash notification remains, and the emergency `LOCATE` remote command remains, but every other entitlement is denied. The account may exit this state in two directions. Reactivation returns the subscription to `ACTIVE`: the request must carry `expected_subscription_version` matching the current `version` (mismatches are rejected with `ERR_STALE_VERSION`), and on success `current_period_start` is reset to the logical-clock date, `next_renewal_date` is pushed 30 days out, `period_remote_commands_used` is zeroed, `emergency_only_flag` is recomputed, and the subscription's `version` increments by 1. Cancellation from `EMERGENCY_RETAINED` moves the subscription to `CANCELLED` and clears `emergency_only_flag` to false.

**Cancellation.** Cancellation is permitted from `TRIAL`, from `ACTIVE`, and from `EMERGENCY_RETAINED`; every cancellation lands in the terminal `CANCELLED` state. Cancelling an `ACTIVE` subscription nulls `next_renewal_date`; cancelling an `EMERGENCY_RETAINED` subscription clears `emergency_only_flag`; cancelling a `TRIAL` subscription has no further side effects. Cancellation attempts from any other status are rejected with `ERR_INVALID_STATE`.

### 3.3. Automatic Crash Notification, Advisor Connection, and Dispatch

When a vehicle's sensors detect an impact, the `SystemIngestion` identity reports the event with `delta_v_kph` (a non-negative impact severity in kilometers per hour), a `rollover_detected` flag, an `airbag_deployed` flag (both flags default to false if not supplied), and the `location_region_code` where the crash occurred. Three gates apply at creation, in the order below.

First, severity is scored. The raw score is the sum of three contributions: 0.6 times the smaller of `delta_v_kph` and 80; 25 if `airbag_deployed` is true and 0 otherwise; and 20 if `rollover_detected` is true and 0 otherwise. The resulting `severity_score` is rounded half-up to 1 decimal place. A report whose `severity_score` comes out strictly below 35 is rejected with `ERR_CRASH_THRESHOLD_NOT_MET` and no `CrashEvent` row is persisted. Two sensor variants fall out of this formula: when both flags come from the raw payload the sensor-reported score can reach the `SEVERE` band without extreme delta-V; when both flags are false the score reduces to 0.6 times the capped delta-V alone, which for identical delta-V produces a score up to 45.0 points lower than the sensor-reported variant. Immediately after scoring, the score is banded: a `severity_score` of at least 60 bands as `SEVERE`, a score of at least 35 bands as `MODERATE`, and a score below 35 bands as `MINOR` (which can arise only from a manual replay, since events below 35 are rejected at creation).

Second, coverage is consulted. If the `CoverageZone` for `location_region_code` has `has_cellular` set to false or no such zone exists, the event is persisted directly into the terminal `REJECTED_NO_COVERAGE` status — coverage dominates and no entitlement check is reached, so the event's `subscription_id` is null even if the vehicle has a subscription.

Third, entitlement is resolved. The server resolves the vehicle's subscription — if any subscription exists for the vehicle, regardless of its status, and when several exist the most recently created one is resolved — and snapshots that subscription's `id` into the event's `subscription_id` (null only when the vehicle has no subscription at all). If the resolved subscription is in `TRIAL`, `ACTIVE`, `PAST_DUE`, or `EMERGENCY_RETAINED` and its entitlement bundle has `allows_emergency` true, the event is admitted in `RECEIVED` status. Otherwise — for `LAPSED`, `CANCELLED`, or missing subscriptions, or for any tier without emergency entitlement — the event is persisted directly into the terminal `REJECTED_NO_ENTITLEMENT` status; the `subscription_id` snapshot described above is still recorded on a `REJECTED_NO_ENTITLEMENT` event whenever a subscription exists.

Once `RECEIVED`, an `Advisor` connects to the event, moving it from `RECEIVED` to `ADVISOR_CONNECTED`; the severity data transmission — `severity_score`, `severity_band`, `airbag_deployed`, and `rollover_detected` — is logged at this point. From `ADVISOR_CONNECTED` the advisor has two exits. If the occupants confirm they are uninjured, the advisor closes the event, moving it to the terminal `CLOSED_NO_INJURY`. Otherwise the advisor coordinates dispatch by selecting a PSAP via a `psap_id`: a `psap_id` naming no registered PSAP is rejected with `ERR_NOT_FOUND`, and the chosen PSAP must be in `ACTIVE` status, must have `accepts_location_transfer` true, and must serve the same region as the event's `location_region_code` — failures of those three gates are rejected with `ERR_PSAP_UNAVAILABLE`. A successful dispatch creates a `DispatchRequest` in `PENDING` status, immediately transitions it to `LOCATION_SENT` with a `location_payload` snapshot frozen from the crash location and the `severity_band` — concretely, an object carrying `vehicle_id`, `region_code`, `severity_band`, `severity_score`, `airbag_deployed`, and `rollover_detected` from the crash event — and moves the parent `CrashEvent` from `ADVISOR_CONNECTED` to `DISPATCH_COORDINATED`. The `DispatchRequest` carries a `crash_event_id` linking it back to its origin, as well as `vehicle_id`, `psap_id`, and an `acknowledged_at` field that stays null until acknowledgement; the creation response already shows the dispatch in `LOCATION_SENT`.

The dispatch lifecycle has two terminal outcomes. A `PSAPOperator` acknowledges receipt, moving the dispatch from `LOCATION_SENT` to `ACKNOWLEDGED` and stamping `acknowledged_at` from the logical clock; the acknowledgement bubbles up to the parent `CrashEvent`, auto-transitioning it from `DISPATCH_COORDINATED` to the terminal `CLOSED_DISPATCHED`. Alternatively, an `Advisor` may cancel a dispatch that has not yet been acknowledged, moving it from `LOCATION_SENT` to `CANCELLED`. There is no optimistic concurrency control on the dispatch state machine — all writes are single-writer sequential by role.

PSAPs are registered by a `PlatformAdmin` with a `name`, a two-letter `region_code`, and an `accepts_location_transfer` flag that defaults to true when omitted. Newly registered PSAPs arrive in `ACTIVE` status.

### 3.4. Stolen Vehicle Assistance: Report, Verification, and Remote Slowdown

A stolen-vehicle workflow begins when a `LawEnforcement` officer reports the theft, supplying a `police_report_number` (unique across cases, with duplicates rejected as `ERR_DUPLICATE`) and the `reporting_agency`. The vehicle must be in `ACTIVE` status — a report against a vehicle in any other status is rejected with `ERR_INVALID_STATE` — and only one open case may exist per vehicle, where open means `REPORTED`, `VERIFIED`, `SLOWDOWN_ARMED`, or `SLOWDOWN_EXECUTED`; a report against a vehicle with an open case is rejected with `ERR_INVALID_STATE`. The new case enters `REPORTED` status.

Verification is a separate act by a `LawEnforcement` officer, and segregation of duties is enforced: the verifier's `X-User-ID` must differ from the reporter's recorded `X-User-ID`. A verification attempt where the two identifiers coincide is rejected with `ERR_SEGREGATION_OF_DUTIES`. Successful verification moves the case from `REPORTED` to `VERIFIED`, records the verifier's identity in `verified_by_user_id`, and cascades to the vehicle, moving it from `ACTIVE` to `STOLEN_REPORTED` — this cascade is what arms slowdown eligibility downstream.

Arming slowdown is performed by an `EmergencyOperator` — never by the verifying officer — and only after all of the following hold: the case is in `VERIFIED` (law-enforcement verification must precede any slowdown; an attempt against a case in any other status is rejected with `ERR_SLOWDOWN_NOT_VERIFIED`); the vehicle's `hardware_generation` is 5 (any other generation is rejected with `ERR_SLOWDOWN_UNSUPPORTED_HARDWARE`); and the `CoverageZone` for the vehicle's `region_code` has `has_cellular` true (a coverage failure is rejected with `ERR_NO_CELLULAR_COVERAGE`). A successful arm moves the case from `VERIFIED` to `SLOWDOWN_ARMED`.

Execution of the slowdown, also by an `EmergencyOperator`, requires the case to be in `SLOWDOWN_ARMED` and the vehicle to be in `STOLEN_REPORTED` — a failure of either precondition is rejected with `ERR_INVALID_STATE`; on success the case moves from `SLOWDOWN_ARMED` to `SLOWDOWN_EXECUTED` and `slowdown_executed_at` is stamped from the logical clock.

Closure has three forms, all performed by `LawEnforcement`. From `SLOWDOWN_EXECUTED`, closing as recovered moves the case to the terminal `CLOSED_RECOVERED` and cascades to the vehicle, restoring it from `STOLEN_REPORTED` to `RECOVERED`. From `VERIFIED`, closing as recovered — when the vehicle was located before any slowdown — also moves the case to `CLOSED_RECOVERED` and performs the same vehicle restoration cascade. From `REPORTED`, closing as unverified moves the case to the terminal `CLOSED_UNVERIFIED` with no vehicle cascade. Once the case is closed, the account may return the vehicle from `RECOVERED` to `ACTIVE` via a vehicle-status update.

### 3.5. Remote Commands and the Periodic Cap

An account issues a remote command to one of its vehicles by supplying a `command_type` — one of `LOCK`, `UNLOCK`, `HORN_LIGHTS`, or `LOCATE`. Acceptance is gated by three checks, evaluated in the order coverage, then entitlement, then the periodic cap. First, coverage: the `CoverageZone` for the vehicle's `region_code` must have `has_cellular` true, else the request is rejected with `ERR_NO_CELLULAR_COVERAGE`. Second, entitlement: the vehicle's subscription is snapshotted into the command's `subscription_id` (null when no subscription exists), and the resolved bundle must have `allows_remote_commands` true — unless the subscription is in `EMERGENCY_RETAINED`, in which case only `LOCATE` is permitted under the emergency-only path and any other command type is rejected with `ERR_EMERGENCY_ONLY_COMMAND`. A tier lacking remote-command entitlement is rejected with `ERR_TIER_CAPABILITY_MISSING`, and the same rejection applies when the vehicle's subscription is `LAPSED` or `CANCELLED` or the vehicle has no subscription at all. Third, the periodic cap, described below.

On acceptance the command enters `PENDING` status with `expires_at` computed as exactly 10 minutes after `created_at`. The system then attempts immediate delivery, moving the command from `PENDING` to `SENT`; the `PENDING` stage is transient within request handling, so the creation response already presents the command in `SENT` status. From `SENT`, the vehicle reports back through the ingestion identity: an acknowledgement moves the command to the terminal `ACKNOWLEDGED`, and a failure report moves it to the terminal `FAILED`; both outcomes consume the periodic cap. Independently, whenever the logical clock reaches a command's `expires_at`, the command flips from `PENDING` or `SENT` to the terminal `EXPIRED` — and an `EXPIRED` command never consumes the cap.

The cap accounting differs by subscription status. For subscriptions in `TRIAL`, `ACTIVE`, or `PAST_DUE`, `period_remote_commands_used` counts the subscription's `RemoteCommand` rows whose status is `ACKNOWLEDGED` or `FAILED` and whose `created_at` falls within the closed-open window from `current_period_start` up to but not including `current_period_start` plus 30 days. The per-tier cap is 0 for `EMERGENCY_ONLY`, 0 for `SAFETY`, 10 for `SAFETY_REMOTE`, and 50 for `PREMIUM`; a new command is accepted only when the count is strictly less than the cap, and a count equal to the cap is rejected with `ERR_REMOTE_COMMAND_CAP_REACHED`. For subscriptions in `EMERGENCY_RETAINED`, the accounting uses a different baseline: exactly 2 emergency `LOCATE` commands are permitted per 30-day window counted from `lapse_date` (not from `current_period_start`), and only rows whose `is_emergency_command` flag is true count against that fixed cap. The `is_emergency_command` flag is true exactly when the command was accepted under the emergency-only path of an `EMERGENCY_RETAINED` subscription; a `LOCATE` command issued under any other subscription status carries the flag false.

### 3.6. Vehicle Diagnostics and Dealer Service Scheduling

A vehicle's onboard systems upload diagnostic reports through the ingestion identity, supplying `odometer_km` (non-negative), `engine_hours` (non-negative), a list of `dtc_codes` (diagnostic trouble codes; an empty array means a clean report, and the default when omitted is the empty array), and `oil_life_pct` (an integer between 0 and 100 inclusive). The odometer is monotonically non-decreasing per vehicle: a report whose `odometer_km` is lower than the highest `odometer_km` among the vehicle's existing reports is rejected with `ERR_ODOMETER_REGRESSION`, while a value equal to that maximum is accepted.

On acceptance the server computes a `health_score` between 0 and 100. The score starts from a base of 100, subtracts 8 for each trouble code present in `dtc_codes`, and then subtracts 1 for every full 5 percent of oil wear — computed by integer-dividing the difference between 100 and `oil_life_pct` by 5, truncating toward zero before the clamp. The result is clamped to lie between 0 and 100 inclusive. Two variants fall out: a clean report — empty `dtc_codes` and `oil_life_pct` equal to 100 — always scores exactly 100 and is the only variant that can hit the ceiling; any report with a trouble code or oil life below 100 scores strictly below 100, and two reports with identical odometer can differ by up to the full 100 points. New reports arrive in `GENERATED` status.

A service appointment links a dealer, a vehicle, and a motivating diagnostic report. Either the account or a `DealerService` writer may request one, supplying `vehicle_id`, `diagnostic_report_id`, and a `scheduled_date`. The servicing dealer's identity is persisted on the appointment as `dealer_id`, and the flat cross-dealer appointment list accepts `dealer_id` along with `vehicle_id`, `diagnostic_report_id`, and `status` as filter parameters. The scheduled date must be supplied as an ISO calendar date in `YYYY-MM-DD` form — any other shape is rejected with `ERR_INVALID_REQUEST` — and must be strictly in the future relative to the logical clock; a past or same-day value is rejected with `ERR_APPOINTMENT_IN_PAST`. The referenced `vehicle_id` or `diagnostic_report_id` not naming an existing resource is rejected with `ERR_NOT_FOUND`; the report is not required to belong to the named vehicle. New appointments enter `REQUESTED` status.

Confirmation is the dealer's act and carries the capacity gate: the dealer must be in `ACTIVE` status (a confirm against a non-`ACTIVE` dealer is rejected with `ERR_INVALID_STATE`), and the count of the dealer's `CONFIRMED` appointments whose `scheduled_date` equals the candidate's `scheduled_date` must be strictly less than the dealer's `service_capacity_per_day` — so a dealer with capacity 1 and 1 confirmed appointment on that day rejects the next confirm with `ERR_DEALER_CAPACITY_REACHED`. On success the appointment moves from `REQUESTED` to `CONFIRMED` and the linked `DiagnosticReport` cascades from `GENERATED` to `SERVICE_SCHEDULED`. Completion moves a `CONFIRMED` appointment to the terminal `COMPLETED`.

Cancellation is permitted from either `REQUESTED` or `CONFIRMED` and lands in the terminal `CANCELLED`. Cancelling a `REQUESTED` appointment has no further effect. Cancelling a `CONFIRMED` appointment triggers a compensating cascade: the linked `DiagnosticReport` reverts from `SERVICE_SCHEDULED` back to `GENERATED`, but only if no other non-cancelled appointment still references the same report.

Dealers themselves are onboarded by the platform with a `name`, a two-letter `region_code`, and a `service_capacity_per_day` of at least 1. Dealers arrive in `ACTIVE` status and may be moved to `SUSPENDED`; a suspended dealer cannot confirm new appointments.

### 3.7. Data Consents and the Insurance Score

Each account manages its own data-sharing posture through `DataConsent` records, one per consent scope. The `consent_type` is either `DRIVING_DATA_COLLECTION` or `INSURANCE_PROGRAM_SHARING`. Creating a consent lands it in `GRANTED` status with `granted_at` stamped from the logical clock; if a non-superseded consent of the same `consent_type` already exists for the account — whether `GRANTED` or `REVOKED` — the prior row is automatically moved to `SUPERSEDED`, and if the superseded row is an insurance-sharing consent its `effective_score` is nulled. The driving-data dependency applies at creation as well: creating an `INSURANCE_PROGRAM_SHARING` consent while the account's `DRIVING_DATA_COLLECTION` consent is not currently `GRANTED` is rejected with `ERR_CONSENT_DEPENDENCY_MISSING`. At most one non-`SUPERSEDED` consent exists per account and consent type at any moment.

Revocation moves a `GRANTED` consent to `REVOKED`, stamping `revoked_at` from the logical clock; for an insurance-sharing consent, revocation also nulls `effective_score`, since the score is no longer shared. Re-granting moves a `REVOKED` consent back to `GRANTED` — the machine is cyclic between these two states — resetting `granted_at` to the logical clock and clearing `revoked_at` to null. Re-granting an insurance-sharing consent carries a cross-entity dependency: the account's `DRIVING_DATA_COLLECTION` consent must currently be `GRANTED`; otherwise the grant is rejected with `ERR_CONSENT_DEPENDENCY_MISSING`. On a successful re-grant of insurance sharing, the `effective_score` is recomputed.

The insurance score is maintained only while an `INSURANCE_PROGRAM_SHARING` consent is `GRANTED`; it is null at all other times. The score is computed at the moment the consent enters `GRANTED` — at creation and at each re-grant — and the computed value is then stored on the consent; later diagnostic reports do not change the stored `effective_score` until the next grant transition. The score aggregates the account's vehicles' `DiagnosticReport` rows created within the trailing 90 days of the logical clock — that is, reports whose creation instant falls between the logical clock minus 90 days and the logical clock, inclusive — restricted to reports in `GENERATED` or `SERVICE_SCHEDULED` status. The raw value is the sum of those reports' `health_score` values, and the count is the number of those reports. The `effective_score` is the raw sum divided by the count, rounded half-up to 2 decimal places; when no qualifying reports exist, the score is the baseline value 50.00. The evaluation order is pinned — reports are aggregated first, then the average is taken — which fully defines the value because nothing else in the system depends on `effective_score`.

## 4. Endpoint Definitions

Operations that create new resources return `201 Created`; operations that modify an existing resource return `200 OK`. The logical-clock setter returns `200 OK`. All other status codes are error codes as catalogued in §5.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the logical clock; fires time-based transitions | PlatformAdmin |
| POST | `/plan-tiers` | Define a subscription plan tier | PlatformAdmin |
| GET | `/plan-tiers` | List plan tiers | PlatformAdmin, Account, EmergencyOperator |
| GET | `/plan-tiers/{tierId}` | Get a plan tier | PlatformAdmin, Account, EmergencyOperator |
| POST | `/accounts` | Register an account | PlatformAdmin |
| GET | `/accounts/{accountId}` | Get an account | PlatformAdmin, Account, Advisor, EmergencyOperator |
| POST | `/coverage-zones` | Define a coverage zone for a region | PlatformAdmin |
| GET | `/coverage-zones` | List coverage zones | PlatformAdmin, Account, Advisor, EmergencyOperator |
| GET | `/coverage-zones/{zoneId}` | Get a coverage zone | PlatformAdmin, Account, Advisor, EmergencyOperator |
| POST | `/accounts/{accountId}/vehicles` | Register a vehicle on an account | Account |
| GET | `/accounts/{accountId}/vehicles` | List vehicles of an account | PlatformAdmin, Account, Advisor |
| GET | `/accounts/vehicles/{vehicleId}` | Get a vehicle (prefixed alias of the flat read) | PlatformAdmin, Account, Advisor, EmergencyOperator, LawEnforcement, DealerService |
| GET | `/accounts/vehicles` | List vehicles across accounts (flat, filterable) | PlatformAdmin, Account, Advisor, EmergencyOperator, LawEnforcement, DealerService |
| GET | `/vehicles/{vehicleId}` | Get a vehicle | PlatformAdmin, Account, Advisor, EmergencyOperator, LawEnforcement, DealerService |
| PATCH | `/vehicles/{vehicleId}` | Update vehicle status (RECOVERED to ACTIVE, ACTIVE to DECOMMISSIONED) | Account, PlatformAdmin |
| POST | `/accounts/{accountId}/subscriptions` | Start a trial subscription for a vehicle | Account |
| GET | `/accounts/{accountId}/subscriptions` | List subscriptions of an account | PlatformAdmin, Account, Advisor, EmergencyOperator |
| GET | `/accounts/subscriptions` | List subscriptions across accounts (flat, filterable) | PlatformAdmin, Account, Advisor, EmergencyOperator, BillingAdmin |
| GET | `/accounts/subscriptions/{subscriptionId}` | Get a subscription (prefixed alias of the flat read) | PlatformAdmin, Account, Advisor, EmergencyOperator, BillingAdmin |
| GET | `/accounts/{accountId}/subscriptions/{subscriptionId}` | Get a subscription | PlatformAdmin, Account, Advisor, EmergencyOperator |
| POST | `/accounts/{accountId}/subscriptions/{subscriptionId}/convert` | Convert TRIAL to ACTIVE (OCC on subscription version) | Account |
| POST | `/accounts/{accountId}/subscriptions/{subscriptionId}/billing-events` | Record a billing outcome (renewal success / payment failure / retry success) | BillingAdmin |
| POST | `/accounts/{accountId}/subscriptions/{subscriptionId}/retain-emergency` | Retention decision: keep emergency-only functionality after lapse | Account |
| POST | `/accounts/{accountId}/subscriptions/{subscriptionId}/reactivate` | Reactivate an EMERGENCY_RETAINED subscription to ACTIVE (OCC) | Account |
| POST | `/accounts/{accountId}/subscriptions/{subscriptionId}/cancel` | Cancel a TRIAL, ACTIVE, or EMERGENCY_RETAINED subscription | Account |
| POST | `/vehicles/{vehicleId}/crash-events` | Vehicle ingestion endpoint: automatic crash notification | SystemIngestion |
| GET | `/accounts/crash-events` | List crash events across vehicles (flat, filterable) | PlatformAdmin, Account, Advisor, EmergencyOperator |
| GET | `/vehicles/{vehicleId}/crash-events` | List crash events of a vehicle | PlatformAdmin, Account, Advisor, EmergencyOperator |
| GET | `/accounts/crash-events/{eventId}` | Get a crash event (prefixed alias of the flat read) | PlatformAdmin, Account, Advisor, EmergencyOperator |
| GET | `/vehicles/{vehicleId}/crash-events/{eventId}` | Get a crash event | PlatformAdmin, Account, Advisor, EmergencyOperator |
| POST | `/vehicles/{vehicleId}/crash-events/{eventId}/connect-advisor` | Advisor connects to the crash event; severity data transmitted | Advisor |
| POST | `/vehicles/{vehicleId}/crash-events/{eventId}/dispatch-requests` | Create a dispatch request to a PSAP with location transfer | Advisor |
| POST | `/vehicles/{vehicleId}/crash-events/{eventId}/close` | Close a crash event with no dispatch (occupants OK) | Advisor |
| GET | `/accounts/dispatch-requests` | List dispatch requests (flat, filterable) | PlatformAdmin, Advisor, PSAPOperator, EmergencyOperator |
| GET | `/accounts/dispatch-requests/{dispatchId}` | Get a dispatch request (prefixed alias of the flat read) | PlatformAdmin, Advisor, PSAPOperator, EmergencyOperator |
| GET | `/dispatch-requests/{dispatchId}` | Get a dispatch request | PlatformAdmin, Advisor, PSAPOperator, EmergencyOperator |
| GET | `/vehicles/{vehicleId}/dispatch-requests` | List dispatch requests for a vehicle | PlatformAdmin, Advisor, EmergencyOperator |
| POST | `/dispatch-requests/{dispatchId}/acknowledge` | PSAP acknowledges receipt of the dispatch | PSAPOperator |
| POST | `/dispatch-requests/{dispatchId}/cancel` | Advisor cancels a pending dispatch | Advisor |
| GET | `/accounts/psaps/{psapId}/dispatch-requests` | List dispatch requests routed to a PSAP | PlatformAdmin, PSAPOperator, Advisor |
| POST | `/psaps` | Register a public safety answering point | PlatformAdmin |
| GET | `/accounts/psaps/{psapId}` | Get a PSAP (prefixed alias of the flat read) | PlatformAdmin, Advisor, EmergencyOperator, PSAPOperator |
| GET | `/psaps` | List PSAPs | PlatformAdmin, Advisor, EmergencyOperator, PSAPOperator |
| GET | `/psaps/{psapId}` | Get a PSAP | PlatformAdmin, Advisor, EmergencyOperator, PSAPOperator |
| POST | `/vehicles/{vehicleId}/stolen-cases` | Report a vehicle stolen (opens a case) | LawEnforcement |
| GET | `/accounts/stolen-cases` | List stolen-vehicle cases (flat, filterable) | PlatformAdmin, LawEnforcement, EmergencyOperator, Account |
| GET | `/vehicles/{vehicleId}/stolen-cases` | List stolen-vehicle cases of a vehicle | PlatformAdmin, LawEnforcement, EmergencyOperator, Account |
| GET | `/accounts/stolen-cases/{caseId}` | Get a stolen-vehicle case (prefixed alias of the flat read) | PlatformAdmin, LawEnforcement, EmergencyOperator, Account |
| GET | `/vehicles/{vehicleId}/stolen-cases/{caseId}` | Get a stolen-vehicle case | PlatformAdmin, LawEnforcement, EmergencyOperator, Account |
| POST | `/vehicles/{vehicleId}/stolen-cases/{caseId}/verify` | Law enforcement verifies the report; arms vehicle tracking | LawEnforcement |
| POST | `/vehicles/{vehicleId}/stolen-cases/{caseId}/arm-slowdown` | Arm remote slowdown after verification (gen-5 hardware and cellular coverage required) | EmergencyOperator |
| POST | `/vehicles/{vehicleId}/stolen-cases/{caseId}/execute-slowdown` | Execute the armed remote slowdown | EmergencyOperator |
| POST | `/vehicles/{vehicleId}/stolen-cases/{caseId}/close-recovered` | Close the case as recovered; restores vehicle operability | LawEnforcement |
| POST | `/vehicles/{vehicleId}/stolen-cases/{caseId}/close-unverified` | Close an unverified report | LawEnforcement |
| POST | `/vehicles/{vehicleId}/remote-commands` | Issue a remote command (lock/unlock/horn/locate) | Account |
| GET | `/accounts/remote-commands` | List remote commands (flat, filterable) | PlatformAdmin, Account, EmergencyOperator, SystemIngestion |
| GET | `/vehicles/{vehicleId}/remote-commands` | List remote commands of a vehicle | PlatformAdmin, Account, EmergencyOperator |
| GET | `/accounts/remote-commands/{commandId}` | Get a remote command (prefixed alias of the flat read) | PlatformAdmin, Account, EmergencyOperator, SystemIngestion |
| GET | `/remote-commands/{commandId}` | Get a remote command | PlatformAdmin, Account, EmergencyOperator, SystemIngestion |
| POST | `/remote-commands/{commandId}/acknowledge` | Vehicle acknowledges command execution | SystemIngestion |
| POST | `/remote-commands/{commandId}/fail` | Vehicle reports command failure | SystemIngestion |
| POST | `/vehicles/{vehicleId}/diagnostic-reports` | Vehicle uploads a diagnostic report | SystemIngestion |
| GET | `/accounts/diagnostic-reports` | List diagnostic reports (flat, filterable) | PlatformAdmin, Account, DealerService |
| GET | `/vehicles/{vehicleId}/diagnostic-reports` | List diagnostic reports of a vehicle | PlatformAdmin, Account, DealerService |
| GET | `/accounts/diagnostic-reports/{reportId}` | Get a diagnostic report (prefixed alias of the flat read) | PlatformAdmin, Account, DealerService |
| GET | `/vehicles/{vehicleId}/diagnostic-reports/{reportId}` | Get a diagnostic report | PlatformAdmin, Account, DealerService |
| POST | `/dealers` | Register a dealer | PlatformAdmin |
| GET | `/accounts/dealers/{dealerId}` | Get a dealer (prefixed alias of the flat read) | PlatformAdmin, Account, DealerService |
| GET | `/dealers` | List dealers | PlatformAdmin, Account, DealerService |
| GET | `/dealers/{dealerId}` | Get a dealer | PlatformAdmin, Account, DealerService |
| POST | `/dealers/{dealerId}/appointments` | Schedule a service appointment from a diagnostic report | Account, DealerService |
| GET | `/accounts/service-appointments` | List service appointments (flat, filterable) | PlatformAdmin, Account, DealerService |
| GET | `/dealers/{dealerId}/appointments` | List appointments of a dealer | PlatformAdmin, Account, DealerService |
| POST | `/dealers/{dealerId}/appointments/{appointmentId}/confirm` | Dealer confirms an appointment (capacity gate) | DealerService |
| POST | `/dealers/{dealerId}/appointments/{appointmentId}/complete` | Mark an appointment completed | DealerService |
| POST | `/dealers/{dealerId}/appointments/{appointmentId}/cancel` | Cancel an appointment | Account, DealerService |
| GET | `/accounts/service-appointments/{appointmentId}` | Get a service appointment (prefixed alias of the flat read) | PlatformAdmin, Account, DealerService |
| GET | `/accounts/consents/{consentId}` | Get a consent record (prefixed alias) | PlatformAdmin, Account |
| POST | `/accounts/{accountId}/consents` | Create a consent record (supersedes any prior consent of the same type) | Account |
| GET | `/accounts/consents` | List consents (flat, filterable) | PlatformAdmin, Account |
| GET | `/accounts/{accountId}/consents` | List consents of an account | PlatformAdmin, Account |
| POST | `/accounts/{accountId}/consents/{consentId}/revoke` | Revoke a granted consent | Account |
| POST | `/accounts/{accountId}/consents/{consentId}/grant` | Re-grant a revoked consent (cyclic) | Account |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_SLOWDOWN_NOT_VERIFIED` | 409 |
| `ERR_SLOWDOWN_UNSUPPORTED_HARDWARE` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 409 |
| `ERR_RETENTION_WINDOW_EXPIRED` | 409 |
| `ERR_APPOINTMENT_IN_PAST` | 409 |
| `ERR_ODOMETER_REGRESSION` | 409 |
| `ERR_REMOTE_COMMAND_CAP_REACHED` | 409 |
| `ERR_PSAP_UNAVAILABLE` | 409 |
| `ERR_DEALER_CAPACITY_REACHED` | 409 |
| `ERR_CONSENT_DEPENDENCY_MISSING` | 409 |
| `ERR_DUPLICATE` | 409 |
| `ERR_NO_CELLULAR_COVERAGE` | 422 |
| `ERR_EMERGENCY_ENTITLEMENT_MISSING` | 422 |
| `ERR_TIER_CAPABILITY_MISSING` | 422 |
| `ERR_EMERGENCY_ONLY_COMMAND` | 422 |
| `ERR_CRASH_THRESHOLD_NOT_MET` | 422 |
| `ERR_BILLING_TRANSITION_INVALID` | 409 |
