# Home Battery Storage API — Product Requirements Document

## 1. Introduction

Residential battery storage has become the most paperwork-dense product a certified installation company sells. A single Powerwall-class project has to survive a load calculation that an electrical authority will second-guess, a building permit that can be sent back for corrections three times, a utility interconnection application that decides how many kilowatts the house is allowed to push back onto the grid, two or three stacked incentive programs whose funding pools are finite and whose caps interact, four commissioning tests that must all pass before anybody is allowed to energize anything, a manufacturer warranty that lapses if nobody registers it within a month, and — for households that opt in — a seasonal bring-your-own-device program that pays for measured performance during utility dispatch events. Today that sequence lives in spreadsheets, installer inboxes and utility portals that do not talk to each other, and the failure modes are expensive: a bank commissioned against an expired permit, a rebate paid on a nameplate figure that the capacity discharge test never confirmed, an incentive stack that quietly exceeded the tightest program's percent-of-cost ceiling.

This document specifies the backend API that replaces that patchwork. The service is the system of record for installer certification, premises, sizing, equipment design, permits, interconnection, incentives, commissioning, warranty, and BYOD dispatch settlement. Its defining characteristic is that a battery system's progress is **two independent stories told about the same row**: the physical build (design, lock, install, commission) and the utility relationship (application, approval to install, permission to operate). Neither story implies the other, and the points where they must interlock — you may not mark a bank installed before the utility says approved-to-install, and the utility may not grant permission to operate before the bank is commissioned and its permit inspection has passed — are stated explicitly rather than left to convention.

The second defining characteristic is money and capacity that must not drift. Incentive funds move through a three-bucket ledger on each program, dispatch capacity moves through a per-event committed-capacity ledger, and every compensating action in the system — voiding a reservation, denying a claim, clawing back a payment, withdrawing from BYOD, an inspection that flips from passed back to failed — must return exactly what it took, to the cent and to the kilowatt. Readers should treat the arithmetic in §2 and §3 as normative to the last decimal place: the benchmark for a correct implementation is not "approximately the right award" but the same integer number of cents.

## 2. Global Specifications & System-Wide Principles

### 2.1. Actors, Identity Headers and Role-Based Access Control

Every request to every endpoint must carry two headers: `X-User-ID`, identifying the caller, and `X-User-Role`, naming the caller's role. If either header is absent, or if `X-User-Role` is not one of the six role names declared below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If both headers are well formed but the named role is not among the roles authorized for the target endpoint (see the authorization column of §4), the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403).

The six roles are `CertifiedInstaller`, `Homeowner`, `AuthorityHavingJurisdiction`, `UtilityInterconnectionReviewer`, `RebateAdministrator`, and `ManufacturerWarrantyAgent`.

- A `CertifiedInstaller` is the manufacturer-certified installation company. It designs and builds systems, drives permitting and interconnection paperwork, schedules and records commissioning tests, registers warranties, reserves incentives, files warranty claims and enrolls households in the dispatch program.
- A `Homeowner` owns the premises. The homeowner consents to utility dispatch of their battery and may withdraw that consent; otherwise the role is read-only.
- An `AuthorityHavingJurisdiction` is the building and electrical authority: it reviews load calculations, issues permits and records field-inspection outcomes.
- A `UtilityInterconnectionReviewer` is utility distributed-energy staff: it reviews interconnection applications, grants permission to operate, schedules and settles dispatch events, and reports metered delivery.
- A `RebateAdministrator` administers incentive programs: creating funded programs, adjudicating, paying and clawing back rebate claims.
- A `ManufacturerWarrantyAgent` staffs the manufacturer's certification and warranty desk: certifying installer companies, amending or suspending certifications, raising fleet-monitoring alerts and adjudicating warranty claims.

Two of the six roles are backed by persisted entities, and for those two `X-User-ID` is not an arbitrary token. When `X-User-Role` is `CertifiedInstaller`, `X-User-ID` is the `id` of the acting `InstallerAccount`; ownership checks on any resource that references an `InstallerAccount` compare the resource's foreign-key field to `X-User-ID`. When `X-User-Role` is `Homeowner`, `X-User-ID` is the `id` of the acting `Site`; ownership checks on any resource that references a `Site` compare the resource's foreign-key field to `X-User-ID`.

The remaining four roles are opaque operator identities. When `X-User-Role` is `AuthorityHavingJurisdiction`, `UtilityInterconnectionReviewer`, `RebateAdministrator` or `ManufacturerWarrantyAgent`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example as `reviewed_by_user_id` or `pto_granted_by_user_id` on an `InterconnectionApplication`, or as `approved_by_user_id` or `paid_by_user_id` on a `RebateClaim`, where a transition writes it — but it never compares such a value to any entity's `id`.

**Ownership enforcement.** For requests that name an existing resource in the path, an entity-backed role must own the resource it is acting on. A `CertifiedInstaller`'s `X-User-ID` must equal the `installer_id` of the battery system in question, or the `installer_id` of the system reachable from the target load calculation, permit, interconnection application, rebate claim, commissioning test, monitoring alert or BYOD enrollment. A `Homeowner`'s `X-User-ID` must equal the target `Site`'s own `id`, or the `site_id` of the system reachable from the target resource. Violations are rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). Opaque roles are exempt from this check, and the check does not apply to the logical-clock endpoint, which any of the six roles may call.

**Segregation of duties.** Two decisions in this system may not be made twice by the same person. The operator who grants permission to operate must not be the operator whose `X-User-ID` was recorded as the application's `reviewed_by_user_id`, and the operator who releases payment on a rebate claim must not be the operator whose `X-User-ID` was recorded as the claim's `approved_by_user_id`. Either violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

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

Every list endpoint accepts two pagination query parameters. `limit` bounds the number of records returned; it defaults to 10 when omitted, may not be smaller than 1, and may not be larger than 100. `offset` is the number of records to skip before the first returned record and defaults to 0.

Unless a specific endpoint says otherwise, list results are ordered by `created_at` ascending.

List responses report their paging position in the envelope's `meta` object, which carries `limit`, `offset`, `total_count` and `has_more` alongside the two request-identification fields.

### 2.4. Flat Collections, Path Identifiers and Reverse Discovery

There are no nested ownership URLs in this API. Every resource collection is mounted at the root of the service, and a child resource points at its parent through a foreign-key field in its own body rather than through its position in a URL. A permit references the bank it covers, a rebate claim references both the bank and the funding program, a dispatch performance references both the event and the enrollment — but each of them is addressed at its own top-level collection.

Because relationships are not visible in the URL structure, every foreign key has a corresponding filtered-list read. Load calculations may be filtered by `site_id` and by `status`; battery systems by `site_id`, `installer_id`, `load_calculation_id`, the self-referential `expands_system_id`, `build_status` and `grid_status`; permits by `battery_system_id`, `jurisdiction_code` and `status`; interconnection applications by `battery_system_id`, `status` and `export_mode`; incentive programs by `program_type`; rebate claims by `battery_system_id`, `program_id` and `status`; commissioning tests by `battery_system_id`, `test_type`, `status` and `result`; monitoring alerts by `battery_system_id`, `alert_code`, `severity` and `status`; BYOD enrollments by `battery_system_id`, `season` and `status`; dispatch events by `territory_code`, `status` and `event_type`; and dispatch performances by `dispatch_event_id`, `byod_enrollment_id` and `status`. Filters combine conjunctively, and any filter may be omitted.

When a request names one or more identifiers, resolution is strictly left to right: path parameters first, in the order they appear in the path, then foreign keys carried in the request body, in the order the endpoint declares them. The first identifier that resolves to nothing decides the response, and each entity type raises its own 404: `ERR_INSTALLER_NOT_FOUND`, `ERR_SITE_NOT_FOUND`, `ERR_LOAD_CALCULATION_NOT_FOUND`, `ERR_BATTERY_SYSTEM_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, `ERR_PROGRAM_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_TEST_NOT_FOUND`, `ERR_ALERT_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`, `ERR_EVENT_NOT_FOUND` and `ERR_PERFORMANCE_NOT_FOUND`. The same 404 codes cover the "derived" lookups an operation performs on the caller's behalf: when a rule needs the permit of a system that has no permit at all, the objection is `ERR_PERMIT_NOT_FOUND`, and when a rule needs the interconnection application of a system that has none, it is `ERR_APPLICATION_NOT_FOUND`. The identifiers themselves appear in paths as `{installerId}`, `{siteId}`, `{loadCalculationId}`, `{batterySystemId}`, `{permitId}`, `{applicationId}`, `{programId}`, `{claimId}`, `{testId}`, `{alertId}`, `{enrollmentId}`, `{eventId}` and `{performanceId}`.

Malformed payloads are a separate concern from missing resources. A request that omits a required field, sends null where a value is required, supplies a value outside a declared enumeration, sends a negative quantity where only non-negative values are meaningful, supplies a window whose `window_end` is not strictly after its `window_start`, sends an empty essential-circuit list under essential-loads scoping, registers a serial-number list whose length differs from the bank's `unit_count`, or supplies a firmware string that is not three dot-separated integers, is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

### 2.5. Common Resource Properties and the Logical Clock

Every resource in this system — installer accounts, sites, load calculations, battery systems, permits, interconnection applications, incentive programs, rebate claims, commissioning tests, monitoring alerts, BYOD enrollments, dispatch events and dispatch performances — carries the same four system-managed properties.

- `id` (string): a server-minted UUID. It carries no type prefix and no embedded meaning.
- `created_at` (string): the ISO 8601 UTC instant at which the resource was created, with three fractional-second digits, for example `2026-08-01T00:00:00.000Z`.
- `updated_at` (string): the ISO 8601 UTC instant of the most recent mutation, in the same format. It is refreshed on every mutation, including mutations the server performs on its own initiative as part of a cascade.
- `version` (integer): a counter that increases by exactly one on every mutation of that resource. It is the currency of the optimistic-concurrency checks described in §2.6.

The critical consequence of the third and fourth bullets is that *server-initiated* writes count. When a claim clawback increments an installer's `clawback_count`, when commissioning rewrites a claim's `final_amount_cents`, when a cascade suspends an enrollment or cancels a pending performance, or when a ledger bucket on a program moves, the touched resource's `updated_at` is refreshed and its `version` advances just as if a client had written it directly.

All datetime values the server emits are ISO 8601 UTC with three fractional digits. A datetime supplied by a caller must be a complete ISO 8601 instant — a calendar date together with a time of day given to the second, optionally carrying fractional seconds and optionally carrying a trailing `Z` or a numeric UTC offset — and it is normalized to that same three-fractional-digit UTC form before it is stored, compared or echoed back; a value that carries only a calendar date, or that is otherwise not a parseable instant, is a malformed request under §2.4 and is rejected with `ERR_INVALID_REQUEST`. All time-sensitive rules in this domain (certification expiry, permit validity, warranty deadlines, test windows, dispatch windows, settlement eligibility) read a **logical clock** rather than wall-clock time. Before any client sets it, the logical clock reads exactly `2026-08-01T00:00:00Z`, and it never falls back to real time. An administrative capability lets any of the six roles move that clock to a supplied `to_iso8601` instant; every deadline, expiry and window comparison in the system reads the clock's current value at the moment the request is processed. Timestamps the server stamps onto resources — `issued_at`, `commissioned_at`, `warranty_registered_at`, `pto_granted_at`, `paid_at`, `consented_at`, `recorded_at` and `settled_at` — are all taken from the logical clock.

### 2.6. Optimistic Concurrency on Aggregate Parents

Two write operations in this API aggregate onto a parent whose current shape the client must have observed before writing, and each is guarded by an explicit version check. In both cases the version field is a **required, non-optional** input; a request that omits it is a malformed request under §2.4.

Reserving a rebate claim requires `expected_battery_system_version`, carrying the client's last observed `version` of the target `BatterySystem`. If that value does not equal the system's current `version`, the reservation is rejected with `ERR_STALE_SYSTEM_VERSION` (HTTP 412). This guard cannot be replaced by a state precondition, because reserving a second claim against the same bank is legitimate product behaviour — incentives stack across programs — so the system's state alone never reveals that the client is working from an outdated view. Any prior write to the bank invalidates that view, including a sibling claim reservation, since reserving a claim itself advances the bank's `version`.

Creating an expansion of a commissioned bank likewise requires `expected_battery_system_version` matching the base system's current `version`, and a mismatch is rejected with `ERR_STALE_SYSTEM_VERSION` (HTTP 412).

Calling an enrolled battery into a dispatch event requires `expected_dispatch_event_version`, carrying the client's last observed `version` of the target `DispatchEvent`. A mismatch with the event's current `version` is rejected with `ERR_STALE_EVENT_VERSION` (HTTP 412). Again a state precondition would not do: adding another participation is normal, since an event aggregates many enrollments, so nothing in the event's status tells the server that the caller's view of committed capacity is out of date. The version check is what makes the aggregate capacity decision safe.

No other endpoint accepts a version field, and no other endpoint performs a version check.

### 2.7. Units, Precision and Rounding Discipline

Power and energy figures (kilowatts and kilowatt-hours) are stored and returned with exactly 2 decimal places, rounded half up. Ratios — the performance and season-compliance figures of the dispatch program — are stored and returned with exactly 4 decimal places, rounded half up. Money is always an integer number of cents; there are no fractional cents anywhere in the system, and no monetary value is ever expressed as a string.

Two rules about *where* rounding happens are normative, because getting them wrong produces answers that differ by a cent or a hundredth of a kilowatt:

- **Compute on exact decimal arithmetic, and round only where this document says to round.** Intermediate volt-ampere subtotals, tier subtotals and per-kilowatt products are carried unrounded; binary floating-point intermediate rounding is not an acceptable substitute.
- **One rounding step per figure.** Where a formula multiplies an unrounded subtotal by a basis-point multiplier, the multiplication happens first and only the product is rounded. Rounding the subtotal before applying the multiplier, or rounding each tier separately and then summing, is wrong.

Basis points appear throughout the incentive and dispatch arithmetic; a basis-point figure is always divided by 10000 to obtain the multiplier it denotes, so 7500 basis points means three quarters and 12500 basis points means one and one quarter. Where a figure is described as floored, the fractional part is discarded toward zero; where it is described as rounded, half-up rounding applies. Ledger transfers between buckets are exact integer moves and involve no rounding at all.

### 2.8. The Two-Dimension System Status Model

A `BatterySystem` row carries two status fields that evolve independently. `build_status` is the physical build dimension and takes one of `DESIGN_DRAFT`, `DESIGN_LOCKED`, `INSTALLED`, `COMMISSIONED`, `SUPERSEDED` or `DESIGN_HOLD`; it begins at `DESIGN_DRAFT`, and `SUPERSEDED` and `DESIGN_HOLD` are terminal. `grid_status` is the utility interconnection dimension and takes one of `NOT_APPLIED`, `APPLICATION_SUBMITTED`, `APPROVED_TO_INSTALL`, `PTO_GRANTED` or `DENIED`; it begins at `NOT_APPLIED`, and `DENIED` is terminal.

Neither dimension implies anything about the other. A bank may legitimately sit at `DESIGN_LOCKED` with `PTO_GRANTED`, or at `COMMISSIONED` with `APPLICATION_SUBMITTED`; advancing one dimension never advances the other by itself. Where the two must interlock, the coupling is written as an explicit precondition on the specific transition (see §3.2, §3.4 and §3.5), and the two dimensions raise different objections: an operation blocked by the build dimension is rejected with `ERR_SYSTEM_BUILD_STATE_INVALID`, while an operation blocked by the grid dimension is rejected with `ERR_SYSTEM_GRID_STATE_INVALID`. Both carry HTTP 409.

### 2.9. Cascade Discipline

Four multi-hop cascades exist in this domain, and each is triggered by exactly one operator decision. Each hop is *caused* by the hop before it, so a hop whose precondition does not hold simply does not fire, and the hops after it do not fire either.

- **Cascade A** begins when a field inspection flips a permit from `INSPECTION_PASSED` to `INSPECTION_FAILED`. It withdraws the utility's blessing: the interconnection application returns to `SUPPLEMENTAL_REVIEW`, the bank's `grid_status` returns to `APPLICATION_SUBMITTED`, and — only when the bank was actually at `PTO_GRANTED` — the household's BYOD enrollment is suspended and its pending dispatch participations are cancelled with their capacity returned.
- **Cascade B** begins when an installer commissions a bank. It fixes the verified capacity, re-prices every open rebate claim on that bank under the final award variant, and returns the freed portion of each reservation to its program pool.
- **Cascade C** begins when an installer creates an expansion of a commissioned bank. It supersedes the base bank, suspends that bank's enrollment and cancels the enrollment's pending participations with their capacity returned.
- **Cascade D** begins when an administrator claws back a paid claim. It restores the program pool, counts the clawback against the installer, suspends that installer's certification once the count reaches the suspension threshold, and puts every one of that installer's not-yet-installed designs on hold.

Where a cascade touches many rows, the processing order is pinned and is stated with the cascade in §3. Ordering matters because the intermediate values a later row reads may have been changed by an earlier row.

### 2.10. Ledger Invariants: Incentive Money and Dispatch Capacity

Each `IncentiveProgram` holds a three-bucket ledger in integer cents: `total_budget_cents` is the immutable size of the pool, `remaining_budget_cents` is the unencumbered balance, `reserved_budget_cents` is the sum held for claims that are still in flight, and `paid_budget_cents` is the sum actually disbursed. After every single claim transition the following must hold exactly: `total_budget_cents` equals `remaining_budget_cents` plus `reserved_budget_cents` plus `paid_budget_cents`. At program creation `remaining_budget_cents` equals `total_budget_cents` and the other two buckets are zero.

Every ledger move in the claim lifecycle is expressed in terms of the claim's **effective hold**, which is its `final_amount_cents` when that field has been written and its `reserved_amount_cents` while it has not. Using the effective hold is what makes the compensating actions exact: a claim that was re-priced downward at commissioning releases only what is still held, never the original reservation.

The dispatch program keeps a structurally similar ledger in kilowatts. Each `DispatchEvent` maintains `enrolled_pledged_kw`, the sum of `pledged_kw_snapshot` over its participations that are in `PENDING`, `REPORTED` or `SETTLED`. Whenever a participation is cancelled — by a homeowner withdrawing, or by cascade A or cascade C — that participation's `pledged_kw_snapshot` is subtracted from its event's `enrolled_pledged_kw`, restoring the ledger to exactly its pre-participation value. Each event also accumulates `total_net_payment_cents` across its settled participations.

### 2.11. The Model Catalog and Firmware Comparison

Battery hardware is described by a fixed manufacturer catalog keyed by `model_code`. Model `PWX_A` provides 13.5 usable kWh and 5.0 kW of continuous power per unit, permits at most 10 units in one bank, and requires firmware `24.4.0` or newer. Model `PWX_B` provides 13.5 usable kWh and 11.5 kW per unit, permits at most 4 units, and requires firmware `25.2.0` or newer. Model `PWX_C` provides 11.9 usable kWh and 4.6 kW per unit, permits at most 12 units, and requires firmware `24.4.0` or newer. A bank's `usable_kwh` is its `unit_count` multiplied by the per-unit usable energy of its model, and its `continuous_kw` is its `unit_count` multiplied by the per-unit continuous power of its model, each rounded half up to two decimals. Neither figure is ever accepted from a caller.

Gateways come in two families. The `GW2_HOME` inverter belongs to gateway family GW2 and the `GW3_HOME` inverter belongs to gateway family GW3. As a catalog fact, `PWX_A` and `PWX_C` are natively GW2-family models and `PWX_B` is a GW3-family model.

Firmware versions are strings of dot-separated integers such as `24.8.1`. Two firmware strings are compared component by component from left to right as integers, with missing components treated as zero — so `25.2` is not older than `25.2.0`, and `24.10.0` is newer than `24.9.9`. A firmware string that is not of the form integer-dot-integer-dot-integer is a malformed request.

### 2.12. Rejection Precedence

When more than one objection applies to a single request, exactly one is reported, and the choice is not arbitrary. The server evaluates objections in the following fixed order and returns the first that fires. The intent is that structural problems are reported before business problems, and that a budget objection — the least informative of all — is reported only when nothing else is wrong.

1. **Authentication.** Both identity headers present and `X-User-Role` one of the six declared roles, else `ERR_UNAUTHENTICATED`.
2. **Role authorization.** The authenticated role is listed for the target endpoint, else `ERR_ROLE_NOT_PERMITTED`.
3. **Ownership.** Entity-backed roles own the addressed resource, else `ERR_NOT_RESOURCE_OWNER`.
4. **Existence.** Every referenced resource resolves, path parameters left to right and then body foreign keys in declaration order, each miss raising that entity's own 404.
5. **Request shape.** Required fields present and non-null, enumerations respected, quantities non-negative, windows strictly ordered, and the other shape rules of §2.4, else `ERR_INVALID_REQUEST`.
6. **State.** The target resource is in a state from which the requested transition is declared, else the state error of the entity concerned — `ERR_LOAD_CALC_STATE_INVALID`, `ERR_SYSTEM_BUILD_STATE_INVALID`, `ERR_SYSTEM_GRID_STATE_INVALID`, `ERR_PERMIT_STATE_INVALID`, `ERR_APPLICATION_STATE_INVALID`, `ERR_CLAIM_STATE_INVALID`, `ERR_ALERT_STATE_INVALID`, `ERR_ENROLLMENT_STATE_INVALID`, `ERR_EVENT_STATE_INVALID` or `ERR_PERFORMANCE_STATE_INVALID`.
7. **Optimistic concurrency.** The supplied expected parent version matches, else `ERR_STALE_SYSTEM_VERSION` or `ERR_STALE_EVENT_VERSION`. This applies to claim reservation, bank expansion and event participation.
8. **Segregation of duties.** The acting operator is not the one whose decision is being countersigned, else `ERR_SEGREGATION_OF_DUTIES`. This applies to the permission-to-operate grant and to claim payment.
9. **Commissioning safety.** The four-test completeness and pass rules of §3.5, raising `ERR_COMMISSIONING_TESTS_INCOMPLETE`, `ERR_BACKUP_TRANSITION_NOT_VERIFIED` or `ERR_COMMISSIONING_TEST_FAILED`. This applies to commissioning a bank.
10. **Certification and coverage.** In this internal order: installer certification (`ERR_INSTALLER_NOT_CERTIFIED`), then load-calculation approval (`ERR_LOAD_CALC_NOT_APPROVED`), then capacity sufficiency (`ERR_CAPACITY_BELOW_REQUIRED`), then warranty standing for claim filing (`ERR_WARRANTY_NOT_ACTIVE`). These guard four operations: creating a battery system, locking a design, creating an expansion, and filing a warranty claim against an alert.
11. **Cross-entity workflow gating.** The permission-to-operate grant requires a passed permit inspection (`ERR_PERMIT_NOT_PASSED`); BYOD enrollment requires a commissioned, permission-granted bank (`ERR_ENROLLMENT_REQUIRES_PTO`); claim reservation requires the bank's grid dimension to have reached approval (`ERR_SYSTEM_GRID_STATE_INVALID`).
12. **Temporal and overlap.** In this internal order: permit validity at commissioning (`ERR_PERMIT_EXPIRED`), then commissioning-window conflict (`ERR_TEST_WINDOW_CONFLICT`), then territory dispatch capacity (`ERR_TERRITORY_CAPACITY_EXCEEDED`). These guard commissioning a bank, scheduling a commissioning test, and scheduling a dispatch event respectively.
13. **Uniqueness and cardinality.** `ERR_DUPLICATE_PERMIT`, `ERR_DUPLICATE_APPLICATION`, `ERR_DUPLICATE_PROGRAM_CLAIM`, `ERR_DUPLICATE_TEST`, `ERR_DUPLICATE_ENROLLMENT`, `ERR_PARTICIPATION_DUPLICATE` and `ERR_PERMIT_CORRECTION_LIMIT`, guarding permit creation, permit review, application creation, claim reservation, test scheduling, enrollment creation and event participation.
14. **Incentive and program commitments.** In this internal order: export commitment (`ERR_EXPORT_COMMITMENT_REQUIRED`), then capacity commitment bounds (`ERR_CAPACITY_COMMITMENT_INVALID`), then stacking headroom (`ERR_STACK_CAP_EXCEEDED`), then expansion compatibility in the order inverter family (`ERR_INVERTER_INCOMPATIBLE`), firmware (`ERR_FIRMWARE_TOO_OLD`), unit ceiling (`ERR_UNIT_LIMIT_EXCEEDED`), then the enrollment pledge bounds (`ERR_PLEDGE_EXCEEDS_CAPACITY`). These guard claim reservation, bank expansion and enrollment creation.
15. **Fiscal capacity.** Evaluated last, so that every state, referential, temporal and constraint objection is reported in preference to a budget objection: the program's `remaining_budget_cents` must cover the reservation, else `ERR_PROGRAM_BUDGET_EXHAUSTED`. This guards claim reservation.

## 3. Business Logic & Workflows

### 3.1. Certifying an Installer and Recording the Premises

Nothing in this system happens without a certified installation company, and the manufacturer's warranty desk is the only party that can create one. A `ManufacturerWarrantyAgent` registers a company by supplying its `company_name` — a non-empty string of at most 120 characters — together with the `certification_level` it has been granted, the list of `certified_model_codes` its technicians are qualified to install, and the `certification_expires_on` instant at which the certification lapses. The level is one of `NONE`, `CERTIFIED` or `ADVANCED`, and defaults to `CERTIFIED` when the caller does not state it. The model list contains values drawn from `PWX_A`, `PWX_B` and `PWX_C`; it may be empty only for a company whose level is `NONE`. Expiry is an **exclusive** upper bound: the certification is usable while the logical clock reads strictly earlier than `certification_expires_on`, and is unusable from that instant onward.

A new account opens with `certification_status` of `ACTIVE` and with all three of its compliance counters at zero: `clawback_count`, `late_warranty_registration_count` and `commissioned_system_count`. The status field takes one of `ACTIVE` or `SUSPENDED`, and the transition to `SUSPENDED` is never a client decision — it is written only by the clawback cascade of §3.6. The counters are equally out of the client's hands. `clawback_count` records how many rebate claims on this installer's banks reached `CLAWED_BACK`; `late_warranty_registration_count` records how many banks had their warranty registered after the registration deadline had passed; `commissioned_system_count` records how many banks this installer drove to `COMMISSIONED`.

The warranty desk may amend a certification later — to renew the expiry, promote or demote the `certification_level`, widen or narrow the `certified_model_codes`, or restore `certification_status` to `ACTIVE` after a suspension. Only the fields present in the amendment are replaced; anything omitted keeps its stored value, and the amendment advances the installer account's `version` by one. Restoring `ACTIVE` this way is the only route back from suspension, and it does not by itself release any design that the suspension put on hold.

**Premises.** A `CertifiedInstaller` opens a project by recording the premise. The site is described by the `homeowner_name` of record (a non-empty string), the `utility_territory_code` the premise sits in (`TER_WEST`, `TER_EAST` or `TER_NORTH`, which is what later scopes dispatch-event capacity), the `service_panel_amps` main-panel rating (one of 100, 125, 200 or 400), the conditioned `floor_area_sqft` (which must be greater than zero), the five-digit `postal_code`, and `existing_pv_kw_dc`, the nameplate DC rating of solar already on the roof, which must not be negative and defaults to 0 when there is none. The site's `id` doubles as the `X-User-ID` of the `Homeowner` who lives there, which is how a homeowner's later consent is authenticated.

### 3.2. Sizing the Backup: The Load Calculation

Before any hardware is chosen, the installer records a **load calculation** for the premise. The payload names the `site_id` it sizes for, the `method` to be used, the `backup_scope` decision, and the electrical inputs `lighting_area_sqft`, `appliance_load_va`, `heating_va` and `cooling_va`. Note that the calculation restates its own lighting area rather than reading `floor_area_sqft` from the site: no field of the `Site` participates in the arithmetic, so editing a premise record can never silently re-size a calculation an authority has already approved.

The `method` is either `NEC_220_82_STANDARD` or `NEC_220_87_MEASURED`, and it selects between two genuinely different ways of arriving at the same figure. Under the measured method the installer must supply `measured_peak_kw`, the fifteen-minute measured peak demand, which must be greater than zero; under the standard method that field must be omitted entirely. The `backup_scope` is either `WHOLE_HOME` or `ESSENTIAL_LOADS`. Under essential-loads scoping the installer must enumerate `essential_circuits`, an ordered list of objects each carrying a `label`, a `load_kw` figure and a `has_motor` flag; under whole-home scoping that list must be empty. The order in which circuits are listed is not decoration — it is the pinned tie-break for circuits of equal `load_kw`.

A calculation is created in `DRAFT` with `revision_round_count` at zero and `reviewer_notes` unset, and the sizing arithmetic runs immediately, so the computed `connected_load_kw`, `required_continuous_kw` and `required_surge_kw` are already populated in the creation response.

**Step one: the connected load.** The general lighting term is the `lighting_area_sqft` figure multiplied by 3 volt-amperes per square foot. That lighting term plus `appliance_load_va` gives an "other load" subtotal, to which the demand split is applied: the first 3000 volt-amperes of that subtotal count at full value, and every volt-ampere of the subtotal beyond 3000 counts at 40 percent. Separately, the HVAC term is the larger of `heating_va` and `cooling_va` — the smaller of the two is discarded, not added. Under the standard method, `connected_load_kw` is the sum of the demand-split general term and the HVAC term, divided by 1000 to convert volt-amperes to kilowatts, rounded half up to two decimals. Under the measured method, `connected_load_kw` is instead `measured_peak_kw` multiplied by 1.25 — a 25 percent headroom allowance — rounded half up to two decimals, and every one of the nameplate volt-ampere inputs is ignored. The same premise therefore yields a different `connected_load_kw` under the two methods, and under whole-home scoping a different `required_continuous_kw` and `required_surge_kw` as well.

**Step two, whole-home branch.** When the scope is `WHOLE_HOME`, `required_continuous_kw` is exactly `connected_load_kw`, and `required_surge_kw` is `connected_load_kw` multiplied by 1.75, rounded half up to two decimals.

**Step two, essential-loads branch.** When the scope is `ESSENTIAL_LOADS`, the circuits are first ranked by `load_kw` in descending order, and where two circuits carry the same `load_kw` the one that appeared earlier in the submitted `essential_circuits` array ranks first. The `load_kw` figures of the top 2 ranked circuits are summed to give a top-circuit total; the `load_kw` figures of all remaining circuits are summed to give a remainder total. The continuous requirement is the top-circuit total plus half of the remainder total, but never more than `connected_load_kw` — the smaller of those two quantities is taken — rounded half up to two decimals. The surge requirement starts from motor inrush: for every circuit whose `has_motor` is true, its `load_kw` multiplied by 3.0 is a candidate, and the largest candidate is the motor surge figure; when no circuit has a motor the motor surge figure is 0. `required_surge_kw` is then that motor surge figure plus 25 percent of the already-computed `required_continuous_kw`, rounded half up to two decimals.

**Review cycle.** A calculation moves `DRAFT → SUBMITTED` when the installer submits it, and the submission is also the installer's chance to correct the inputs: any of `method`, `backup_scope`, `lighting_area_sqft`, `appliance_load_va`, `heating_va`, `cooling_va`, `measured_peak_kw` or `essential_circuits` supplied on the submission replaces the stored value first, and the sizing arithmetic then re-runs against the post-override values. Supplying none of them resubmits the calculation unchanged. The two input-consistency rules are checked against those post-override values: the measured method requires `measured_peak_kw` to be present, essential-loads scoping requires a non-empty `essential_circuits`, and whole-home scoping requires an empty one.

An `AuthorityHavingJurisdiction` then reviews a `SUBMITTED` calculation with a `decision` of either `APPROVE` or `REQUEST_REVISION`, optionally attaching `reviewer_notes`; when the notes are omitted the field is set to null. `APPROVE` moves the calculation `SUBMITTED → APPROVED`, which is terminal — an approved calculation can neither be resubmitted nor reviewed again. `REQUEST_REVISION` moves it `SUBMITTED → REVISION_REQUIRED` and increments `revision_round_count` by one; the counter records how many times the authority sent the work back, so it advances on the review decision and not on the installer's resubmission. From `REVISION_REQUIRED` the installer submits again, returning the calculation to `SUBMITTED`, and this `REVISION_REQUIRED → SUBMITTED → REVISION_REQUIRED` loop may repeat without limit. Submitting a calculation that is not in `DRAFT` or `REVISION_REQUIRED`, or reviewing one that is not `SUBMITTED`, is rejected with `ERR_LOAD_CALC_STATE_INVALID`.

### 3.3. Designing, Locking and Building the Bank

With an approved calculation in hand, the installer designs the bank. The design payload names the `site_id` of the premise, the `installer_id` of the accountable company, the `load_calculation_id` that is the sizing basis, the `model_code` of the battery, the `unit_count` (at least one), the `inverter_model` paired with the bank (`GW2_HOME` or `GW3_HOME`), the `firmware_version` shipped on the gateway, and the `installed_cost_cents` total, which must be greater than zero and which later serves as the denominator of the incentive stacking ceiling. The bank's `usable_kwh` and `continuous_kw` are derived from the catalog of §2.11 and the unit count; a caller cannot set them. A new bank opens at `build_status` of `DESIGN_DRAFT` and `grid_status` of `NOT_APPLIED`, with `warranty_status` of `UNREGISTERED`, `verified_capacity_kwh` unset, and `expands_system_id` null because it is an original build rather than an expansion.

Three prerequisites are checked at design time, in this order. First, the acting installer must be in good standing: `certification_status` of `ACTIVE`, a `certification_expires_on` that the logical clock has not yet reached, and a `certified_model_codes` list that contains the requested `model_code`; any of the three failing raises `ERR_INSTALLER_NOT_CERTIFIED`. Second, the referenced load calculation must be `APPROVED` and must belong to the same site as the bank, else `ERR_LOAD_CALC_NOT_APPROVED`. Third, the bank's derived `continuous_kw` must be at least the calculation's `required_continuous_kw`, else `ERR_CAPACITY_BELOW_REQUIRED`. A bank whose continuous power exactly equals the requirement is acceptable.

**Locking the design.** Freezing the design advances the bank `DESIGN_DRAFT → DESIGN_LOCKED`, and it re-checks the same three prerequisites in the same order — the approved-calculation check, the capacity-sufficiency check, and the installer's certification standing, including that the certification has not expired since the design was drawn and that the model is still covered. Locking is what makes permitting and interconnection possible; both of those workflows refuse to accept a bank whose design is still a draft. Locking performs no cross-entity write: it advances the bank's own `version` by one and refreshes its `updated_at`.

**Marking the bank installed.** Physical completion advances the bank `DESIGN_LOCKED → INSTALLED`, and it is the first place where the two status dimensions interlock. Three conditions apply. The bank's permit must exist and must be in `ISSUED`, `INSPECTION_FAILED` or `INSPECTION_PASSED` — a permit still in `DRAFT`, `SUBMITTED` or `CORRECTIONS_REQUIRED` is not enough, and a bank with no permit at all raises `ERR_PERMIT_NOT_FOUND`. That permit must still be inside its validity window, meaning the logical clock reads strictly earlier than its `expires_on`; a request made at or after that instant is rejected with `ERR_PERMIT_EXPIRED`. And the bank's `grid_status` must have reached `APPROVED_TO_INSTALL` — no more and no less — so an installer who has not yet obtained the utility's approval, or whose approval was withdrawn back to `APPLICATION_SUBMITTED`, is rejected with `ERR_SYSTEM_GRID_STATE_INVALID`. Like locking, marking installed writes nothing outside the bank row.

**Designs put on hold.** Two build states are terminal. `SUPERSEDED` is reached when an expansion replaces the bank (§3.9). `DESIGN_HOLD` is reached only through the clawback cascade of §3.6: when an installer's certification is suspended, every one of that installer's banks sitting at `DESIGN_DRAFT` or `DESIGN_LOCKED` moves to `DESIGN_HOLD`, each such move advancing that bank's `version` and refreshing its `updated_at`. Banks already at `INSTALLED` or `COMMISSIONED` are left alone. A bank in `DESIGN_HOLD` or `SUPERSEDED` accepts no further build-lifecycle operation; attempts are rejected with `ERR_SYSTEM_BUILD_STATE_INVALID`, as is any build operation requested from a build state that does not declare it — commissioning a merely design-locked bank, for instance, or expanding one that is not yet commissioned.

### 3.4. Permitting and Field Inspection

Permitting runs in parallel with everything else. The installer opens a permit against a design-locked bank by naming the `battery_system_id` it covers, the `jurisdiction_code` that will review and inspect it (`AHJ_CITY` or `AHJ_COUNTY`), and the `plan_set_ref` reference of the submitted plan-set revision. The permit opens in `DRAFT` with `correction_round_count` at zero and with `issued_at`, `expires_on` and `inspection_findings` all unset. No permit status is terminal, so a bank may carry at most one permit ever: a second attempt is rejected with `ERR_DUPLICATE_PERMIT`.

Submitting the permit moves it `DRAFT → SUBMITTED`, and requires the referenced bank to be at `DESIGN_LOCKED` or `INSTALLED`. A `plan_set_ref` supplied on the submission replaces the stored reference; omitting it leaves the stored reference alone. The same submission action serves the correction loop, moving a permit `CORRECTIONS_REQUIRED → SUBMITTED` with the same optional plan-set replacement.

An `AuthorityHavingJurisdiction` reviews a `SUBMITTED` permit with a `decision` of `ISSUE` or `REQUEST_CORRECTIONS`, and may attach an `inspection_findings` note to the decision. `ISSUE` requires the authority to supply `expires_on`, and that instant must be strictly after the current logical clock reading — an already-lapsed validity window may not be stamped onto a permit. On issuance the permit moves `SUBMITTED → ISSUED`, `issued_at` is stamped from the logical clock and `expires_on` takes the supplied value. `REQUEST_CORRECTIONS` moves the permit `SUBMITTED → CORRECTIONS_REQUIRED` and increments `correction_round_count` by one; the counter advances on the review decision, not on the installer's resubmission. Corrections are bounded: an authority may only request further corrections while `correction_round_count` is still below 3, so the fourth request is rejected with `ERR_PERMIT_CORRECTION_LIMIT`. Reviewing a permit that is not `SUBMITTED`, or submitting one that is neither `DRAFT` nor `CORRECTIONS_REQUIRED`, is rejected with `ERR_PERMIT_STATE_INVALID`.

**Field inspections.** The authority records an inspection outcome with a `result` of `PASS` or `FAIL`, optionally attaching `inspection_findings`, which replaces the stored findings and is set to null when omitted. Every inspection outcome requires the permit to still be inside its validity window — the logical clock strictly earlier than `expires_on`. A `PASS` may be recorded from `ISSUED` or from `INSPECTION_FAILED`, in both cases landing on `INSPECTION_PASSED`; recording a pass from `INSPECTION_FAILED` is the re-inspection path. A `FAIL` may be recorded from `ISSUED`, landing on `INSPECTION_FAILED`, and this simply means the first inspection did not pass. Recording a `FAIL` from `INSPECTION_PASSED` is a different and much heavier event: a post-energization re-inspection that revokes a bank the utility has already blessed. This `INSPECTION_PASSED → INSPECTION_FAILED` edge is the head of **cascade A**, and it fires in four coupled hops.

The first hop sets the permit to `INSPECTION_FAILED` and records the supplied `inspection_findings`. Caused by that — because the passed inspection the utility relied on has been withdrawn — the second hop finds the interconnection application of the same bank whose `status` is either `APPROVED_TO_INSTALL` or `PTO_GRANTED` and returns it to `SUPPLEMENTAL_REVIEW`, incrementing its `supplemental_round_count` by one and clearing `approved_export_kw` back to null; when the application had reached `PTO_GRANTED`, both `pto_granted_by_user_id` and `pto_granted_at` are cleared to null as well, because permission to operate no longer exists. Caused by the second hop, the third hop sets the bank's `grid_status` to `APPLICATION_SUBMITTED`, whichever of `APPROVED_TO_INSTALL` or `PTO_GRANTED` it held before.

The fourth and fifth hops fire only when the third hop moved the bank *out of* `PTO_GRANTED` — that is, only when the household actually had permission to operate. In that case every BYOD enrollment of that bank whose `status` is `ENROLLED` becomes `SUSPENDED`, and for each such enrollment every dispatch participation still in `PENDING` whose event is still `SCHEDULED` becomes `CANCELLED`, with that event's `enrolled_pledged_kw` reduced by the cancelled participation's `pledged_kw_snapshot`. A bank that was only at `APPROVED_TO_INSTALL` has no enrollment to suspend — enrollment requires permission to operate in the first place — so those two hops have nothing to do.

### 3.5. Interconnection: From Application to Permission to Operate

The utility relationship starts with an interconnection application. The installer files it against a bank by naming the `battery_system_id`, the `export_mode` posture being requested — `NON_EXPORT`, `LIMITED_EXPORT` or `FULL_EXPORT` — and the `requested_export_kw` limit, which must not be negative and which must be exactly 0 when the requested mode is `NON_EXPORT`. The application opens in `DRAFT` with `supplemental_round_count` at zero and with `approved_export_kw`, `reviewed_by_user_id`, `pto_granted_by_user_id` and `pto_granted_at` all unset. A bank may carry only one live application: if it already has one whose `status` is anything other than `DENIED`, a second filing is rejected with `ERR_DUPLICATE_APPLICATION`.

Submitting the application moves it `DRAFT → SUBMITTED` and requires the bank to be at `DESIGN_LOCKED`, `INSTALLED` or `COMMISSIONED` — a bank still in `DESIGN_DRAFT` has nothing stable to review — and requires that the bank's `grid_status` is not already `DENIED`, since a utility denial is final for that bank. The submission may revise the request in flight: a `requested_export_kw` or `export_mode` supplied on the submission replaces the stored value. Submission also advances the bank's grid dimension to `APPLICATION_SUBMITTED`, whether the bank was previously at `NOT_APPLIED` or already at `APPLICATION_SUBMITTED`. The same submission action answers a supplemental-review request, moving the application `SUPPLEMENTAL_REVIEW → SUBMITTED` and again setting the bank's `grid_status` to `APPLICATION_SUBMITTED`; that loop may repeat without limit.

A `UtilityInterconnectionReviewer` adjudicates a `SUBMITTED` application with a `decision` of `APPROVE_TO_INSTALL`, `REQUEST_SUPPLEMENTAL` or `DENY`. All three require the application to be in `SUBMITTED`; anything else is rejected with `ERR_APPLICATION_STATE_INVALID`.

- `APPROVE_TO_INSTALL` moves the application `SUBMITTED → APPROVED_TO_INSTALL` and the bank `APPLICATION_SUBMITTED → APPROVED_TO_INSTALL`. The reviewer may derate the allowance by supplying `approved_export_kw`; when that field is omitted, the approved limit defaults to the `requested_export_kw` on the application. The approval is checked for internal consistency first: an application whose `export_mode` is `NON_EXPORT` must carry a `requested_export_kw` of 0. The reviewer's `X-User-ID` is recorded as `reviewed_by_user_id`, and that record is the whole basis of the segregation-of-duties rule described below.
- `REQUEST_SUPPLEMENTAL` moves the application `SUBMITTED → SUPPLEMENTAL_REVIEW` and increments `supplemental_round_count` by one. Like the other round counters in this system, it advances when the application *enters* the sent-back state, whether the reviewer put it there or cascade A did, and not when the installer answers.
- `DENY` moves the application `SUBMITTED → DENIED` and sets the bank's `grid_status` to `DENIED`. Both are terminal: no further interconnection application may be created for that bank, and no further decision may be taken on the denied one.

**Permission to operate.** The final utility step is the permission-to-operate grant, which moves the application `APPROVED_TO_INSTALL → PTO_GRANTED` and the bank's `grid_status` likewise from `APPROVED_TO_INSTALL` to `PTO_GRANTED`. It is the second interlock between the two dimensions and it carries three preconditions beyond the application's own state. The bank's `build_status` must be `COMMISSIONED` — the utility does not energize a bank whose commissioning tests have not been signed off — else `ERR_SYSTEM_BUILD_STATE_INVALID`. The bank's permit must be in `INSPECTION_PASSED`, else `ERR_PERMIT_NOT_PASSED`. And the granting operator's `X-User-ID` must differ from the `reviewed_by_user_id` recorded at the approval, else `ERR_SEGREGATION_OF_DUTIES`. On success the grant records `pto_granted_by_user_id` from the caller's `X-User-ID` and stamps `pto_granted_at` from the logical clock.

### 3.6. Commissioning: Tests, Verdicts and the Commissioning Cascade

A bank is commissioned only after four distinct verifications have been booked, performed and recorded. The installer schedules each one by naming the `battery_system_id` under test, the `test_type`, and a half-open window given by an inclusive `window_start` and an exclusive `window_end` that must be strictly later than the start. The four types are `BACKUP_TRANSITION`, `CAPACITY_DISCHARGE`, `ANTI_ISLANDING` and `FIRMWARE_BASELINE`, and a bank may hold at most one test of each type — a second booking of the same type for the same bank is rejected with `ERR_DUPLICATE_TEST`. A test is created with `status` of `SCHEDULED`, `result` of `PENDING`, and `recorded_at` unset.

Because a technician cannot be in two places at once, a new window is checked against every other non-cancelled commissioning window belonging to the same installer, across all of that installer's banks. Both sides of every window are padded by 30 minutes of travel buffer before the comparison, and windows are treated as half-open intervals that include their start and exclude their end. Two windows that abut exactly, or that are separated by at least the buffer, are therefore fine; anything closer is rejected with `ERR_TEST_WINDOW_CONFLICT`.

**Recording a verdict.** When the test has been performed, the installer records the measured figure. Which figure matters depends on the type: `transition_ms` is the measured grid-to-backup transition time and belongs only to a `BACKUP_TRANSITION` test; `delivered_kwh` is the energy delivered and belongs only to a `CAPACITY_DISCHARGE` test; `anti_islanding_trip_ms` is the measured trip time and belongs only to an `ANTI_ISLANDING` test; `reported_firmware_version` is the firmware read off the gateway and belongs only to a `FIRMWARE_BASELINE` test. The verdict is never supplied by the caller — it is computed, and a caller-supplied verdict would be ignored, so none is accepted. Recording sets `status` to `RECORDED` and stamps `recorded_at` from the logical clock.

The verdict rules are these. A `BACKUP_TRANSITION` test passes when its `transition_ms` is at most 200 milliseconds and fails otherwise. An `ANTI_ISLANDING` test passes when its `anti_islanding_trip_ms` is at most 2000 milliseconds and fails otherwise. A `CAPACITY_DISCHARGE` test passes when its `delivered_kwh` is at least 90 percent of the bank's design `usable_kwh`, the boundary being inclusive, and fails otherwise. A `FIRMWARE_BASELINE` test passes when its `reported_firmware_version` is not older than the catalog minimum firmware for the bank's `model_code`, compared component-wise as described in §2.11, and fails otherwise. In every case `result` becomes `PASS` or `FAIL`.

**Commissioning the bank.** Commissioning advances the bank `INSTALLED → COMMISSIONED`. Its safety gate is evaluated before any of its temporal gates: for each of the four test types there must be exactly one test of that type on the bank whose `status` is `RECORDED`, and every one of the four must have a `result` of `PASS`. A missing type, or a type still sitting at `SCHEDULED`, is rejected with `ERR_COMMISSIONING_TESTS_INCOMPLETE`. If all four have been recorded but the `BACKUP_TRANSITION` one failed, the rejection is the specific `ERR_BACKUP_TRANSITION_NOT_VERIFIED` — the backup transition is the safety-critical verification and is named in preference to the generic objection. If all four have been recorded and some test other than `BACKUP_TRANSITION` failed, the rejection is `ERR_COMMISSIONING_TEST_FAILED`. Only after the test gate is satisfied does the permit gate apply: the bank's permit must not have reached its `expires_on`, else `ERR_PERMIT_EXPIRED`.

Commissioning is the head of **cascade B**, three hops deep. The first hop sets `build_status` to `COMMISSIONED`, stamps `commissioned_at` from the logical clock, derives `warranty_deadline_at` as `commissioned_at` plus 30 days, copies the `delivered_kwh` of the recorded `CAPACITY_DISCHARGE` test into the bank's `verified_capacity_kwh`, and increments the accountable installer's `commissioned_system_count` by one.

The second hop is caused by the first hop writing `verified_capacity_kwh`: with a measured capacity now on record, every rebate claim on this bank whose `status` is `RESERVED` or `SUBMITTED` is re-priced under the final award variant of §3.7, writing its `basis_kwh_final` and setting its `final_amount_cents` to the smaller of the freshly computed award and the `reserved_amount_cents` already held. Claims are processed in a pinned order: ascending `stack_priority` of their program first, and among claims of equal priority, ascending `created_at` of the claim. The order matters because each claim's stacking headroom is computed against the effective holds of its siblings as they stand when its turn comes.

The third hop is caused by the second hop lowering each claim's effective hold. For every claim the second hop touched, the difference between its `reserved_amount_cents` and its new `final_amount_cents` is computed, that difference is subtracted from its program's `reserved_budget_cents` and added back to that program's `remaining_budget_cents`. When the final award equals the reservation the difference is zero and the buckets do not move; the three-bucket invariant of §2.10 holds either way.

**Warranty registration.** Once a bank is commissioned, the installer registers the manufacturer warranty by supplying the `coverage_years` term and the `serial_numbers` of the individual units, whose count must equal the bank's `unit_count`. Registration stamps `warranty_registered_at` from the logical clock, stores the supplied term in `warranty_coverage_years` and the supplied serials in `serial_numbers`, and then decides coverage against the deadline. The deadline is `commissioned_at` plus 30 days and the boundary is **inclusive**: a registration landing exactly on `warranty_deadline_at` is on time and sets `warranty_status` to `ACTIVE`. A registration landing after that instant sets `warranty_status` to `VOID` and increments the installer's `late_warranty_registration_count` by one. The comparison is made at millisecond resolution against the logical clock. Coverage matters downstream in two places: a rebate claim cannot be submitted for a bank whose warranty is not `ACTIVE`, and a warranty claim cannot be filed against an alert on such a bank.

### 3.7. Incentives: Programs, the Stacking Waterfall and Claim Adjudication

A `RebateAdministrator` stands up a funded program by supplying its `name`, its `program_type` — `STATE_CAPACITY`, `UTILITY_UPFRONT` or `FEDERAL_ADDER` — and its `total_budget_cents`, which must be greater than zero and which is immutable thereafter. The program's price schedule has two energy tiers: `tier1_limit_kwh` is the inclusive upper bound of the first tier in kilowatt-hours and must be greater than zero, `tier1_rate_cents_per_kwh` is the cents per kilowatt-hour paid inside that tier, and `tier2_rate_cents_per_kwh` is the rate paid on basis above the tier-one limit; both rates must be non-negative. `per_project_cap_cents` is the most the program will pay for one bank and must be greater than zero. `stack_priority` is the program's place in the stacking waterfall and must be at least 1, with lower values consuming stacking headroom first. `max_stack_pct_of_cost_bp` is the program's own view of how much of a project's installed cost all incentives together may cover, expressed in basis points between 1 and 10000. `requires_export_commitment` is a boolean that defaults to false, and `min_capacity_commitment_kw` is the least dispatchable capacity a claim must commit and must be non-negative. A new program opens with `remaining_budget_cents` equal to `total_budget_cents`, and with `reserved_budget_cents` and `paid_budget_cents` both at zero.

**Reserving a claim.** The installer reserves an incentive by naming the `battery_system_id`, the `program_id` of the pool being drawn on, the `capacity_commitment_kw` the household commits to make available, the `export_commitment` posture accepted for the incentive term (`NON_EXPORT`, `LIMITED_EXPORT` or `FULL_EXPORT`), and the `expected_battery_system_version` required by §2.6. Reservation is only meaningful in a specific window of the bank's life: the bank's `build_status` must be `DESIGN_LOCKED` or `INSTALLED` and its `grid_status` must be `APPROVED_TO_INSTALL` or `PTO_GRANTED`, else `ERR_SYSTEM_GRID_STATE_INVALID`. A bank may hold only one live claim per program: if it already has a claim on the same program whose `status` is not `VOID`, `DENIED` or `CLAWED_BACK`, the reservation is rejected with `ERR_DUPLICATE_PROGRAM_CLAIM`.

Three commitment checks then run in order. When the program's `requires_export_commitment` is true, the claim's `export_commitment` must not be `NON_EXPORT` and the bank's interconnection `export_mode` must not be `NON_EXPORT` either, else `ERR_EXPORT_COMMITMENT_REQUIRED`. The `capacity_commitment_kw` must be at least the program's `min_capacity_commitment_kw` and at most the bank's `continuous_kw` — a household cannot promise more power than its bank can produce — else `ERR_CAPACITY_COMMITMENT_INVALID`. And the stacking headroom described below must be strictly positive, else `ERR_STACK_CAP_EXCEEDED`.

**The award arithmetic.** The award is computed twice over a claim's life, from the same six-step recipe, differing only in the energy basis it starts from. At reservation the basis is the bank's design `usable_kwh`. At commissioning the basis is the smaller of the bank's design `usable_kwh` and its measured `verified_capacity_kwh`.

1. The first-tier energy is the basis or `tier1_limit_kwh`, whichever is smaller. The second-tier energy is the amount by which the basis exceeds `tier1_limit_kwh`, or zero when the basis does not exceed it.
2. The raw award is the first-tier energy multiplied by `tier1_rate_cents_per_kwh` plus the second-tier energy multiplied by `tier2_rate_cents_per_kwh`. This subtotal is **not** rounded.
3. The export multiplier is read from the claim's `export_commitment`: 7500 basis points for `NON_EXPORT`, 9000 basis points for `LIMITED_EXPORT`, and 10000 basis points for `FULL_EXPORT`. The raw award is multiplied by that basis-point figure and divided by 10000, and only that product is rounded half up to a whole number of cents. This is the single rounding step of the whole computation; rounding either tier subtotal on its own, or rounding before applying the multiplier, produces a figure that can differ by a cent and is wrong.
4. The result is then capped at the program's `per_project_cap_cents`, taking the smaller of the two.
5. The stacking ceiling is computed next. The set of involved programs is the program of every claim on this same bank whose `status` is not `VOID`, `DENIED` or `CLAWED_BACK`, together with this claim's own program. The tightest `max_stack_pct_of_cost_bp` among those programs is taken, multiplied by the bank's `installed_cost_cents`, divided by 10000, and floored to a whole number of cents; that figure is the claim's `stack_ceiling_cents`. The amount already committed by siblings is the sum, over every other claim on the same bank whose `status` is not `VOID`, `DENIED` or `CLAWED_BACK`, of that sibling's effective hold — its `final_amount_cents` when written, otherwise its `reserved_amount_cents` — accumulated in ascending program `stack_priority` and then ascending claim `created_at`. Headroom is the ceiling less that committed sum, floored at zero. Headroom of exactly zero is the `ERR_STACK_CAP_EXCEEDED` case.
6. Finally the award is reduced to the headroom if the headroom is smaller. This waterfall truncation is not an error — a program late in the priority order simply receives less than its own schedule would have paid.

At reservation the results are written as `basis_kwh_reserved`, `stack_ceiling_cents` and `reserved_amount_cents`, and the program pool is then encumbered: if the program's `remaining_budget_cents` is at least the reserved amount — exact equality succeeds — that amount moves out of `remaining_budget_cents` and into `reserved_budget_cents`. If it is strictly less, the whole reservation is rejected with `ERR_PROGRAM_BUDGET_EXHAUSTED`, and no bucket moves. Only the single program named by `program_id` participates; no other program's balances are read or written. A successful reservation also advances the bank's own `version` by one, which is why a client that reserved one claim must re-read the bank before reserving another.

At commissioning the results are written as `basis_kwh_final` and `final_amount_cents`, and the final figure is clamped to the `reserved_amount_cents` already held, because the reservation is a ceiling and never a floor. A bank that under-delivers on its capacity discharge test therefore earns strictly less than it reserved and hands the difference back to the pool. The final variant re-reads the sibling set at commissioning time, so a claim voided between reservation and commissioning frees headroom for the survivors.

**Adjudication.** A reserved claim is submitted for adjudication once the project is genuinely finished: the bank must be `COMMISSIONED`, its `grid_status` must be `PTO_GRANTED`, and its `warranty_status` must be `ACTIVE`. Submission moves the claim `RESERVED → SUBMITTED` and moves no money, because the hold already sits in `reserved_budget_cents`.

The administrator then decides a `SUBMITTED` claim with a `decision` of `APPROVE` or `DENY`. `APPROVE` moves the claim `SUBMITTED → APPROVED` and records the deciding operator's `X-User-ID` as `approved_by_user_id`; it requires `final_amount_cents` to have been written already, which is the commissioning cascade's job, so a claim on a bank that was somehow never commissioned cannot be approved. `DENY` moves the claim `SUBMITTED → DENIED` and releases the claim's effective hold: that amount leaves `reserved_budget_cents` and returns to `remaining_budget_cents`.

Payment moves an approved claim `APPROVED → PAID`. It must be performed by an operator whose `X-User-ID` differs from `approved_by_user_id`, records `paid_by_user_id` and stamps `paid_at` from the logical clock, and moves exactly `final_amount_cents` out of `reserved_budget_cents` and into `paid_budget_cents`.

**Voiding.** Before submission, the installer may withdraw a reservation. Voiding moves the claim `RESERVED → VOID`, takes a `reason` string which is stored in `clawback_reason` as the release audit note, and releases the claim's effective hold from `reserved_budget_cents` back to `remaining_budget_cents`. A voided claim also stops counting toward its siblings' stacking headroom, since `VOID` is one of the statuses excluded from the prior-committed set.

**Clawback.** A paid claim may be reversed, and this is the head of **cascade D**, four hops deep. The first hop moves the claim `PAID → CLAWED_BACK`, records the supplied `clawback_reason`, and moves exactly `final_amount_cents` out of `paid_budget_cents` and back into `remaining_budget_cents`. Caused by that, the second hop increments the `clawback_count` of the installer accountable for the bank the claim was filed against. Caused by the count reaching the threshold, the third hop fires when that installer's `clawback_count` is 2 or more, setting its `certification_status` to `SUSPENDED`. Caused by the suspension, the fourth hop walks every bank belonging to that installer whose `build_status` is `DESIGN_DRAFT` or `DESIGN_LOCKED`, in ascending `created_at`, and moves each to `DESIGN_HOLD`. A first clawback therefore has hops one and two only; the second clawback against the same installer trips the suspension and the design hold. Every transition of a claim from a state that does not declare it — submitting an approved claim, paying an unapproved one, clawing back one that was never paid — is rejected with `ERR_CLAIM_STATE_INVALID`.

### 3.8. Living With the System: Alerts, Warranty Claims and Expansions

Once a bank is in service the manufacturer's cloud watches it. Either the warranty desk or the accountable installer may raise a **monitoring alert** against a bank by naming the `battery_system_id`, the `alert_code` observed — `FIRMWARE_UPDATE_FAILED`, `CELL_IMBALANCE`, `GATEWAY_OFFLINE` or `THERMAL_DERATE` — the `severity` of the condition (`INFO`, `WARNING` or `CRITICAL`, the last reserved for conditions that put the bank's dispatch participation in question), and optionally the `reported_firmware_version` that was running when the alert fired. An alert opens in `OPEN` with `claim_round_count` at zero and with `acknowledged_by_user_id`, `claimed_component` and `resolution_notes` all unset.

Triage begins with acknowledgement, which moves the alert `OPEN → ACKNOWLEDGED` and records the acting caller's `X-User-ID` in `acknowledged_by_user_id`. Acknowledgement is the accountable installer's job, so the caller's `X-User-ID` must match the `installer_id` of the bank the alert was raised against.

An acknowledged alert can become a warranty claim. Filing moves the alert `ACKNOWLEDGED → UNDER_REVIEW`, requires the bank's `warranty_status` to be `ACTIVE` — a bank whose warranty is `UNREGISTERED` or `VOID` is rejected with `ERR_WARRANTY_NOT_ACTIVE` — records the `claimed_component` named on the filing, may carry `resolution_notes` giving the reviewer context, and increments `claim_round_count` by one. That counter tracks how many times the alert has entered `UNDER_REVIEW`, so it advances on the initial filing and again on every re-filing.

A `ManufacturerWarrantyAgent` adjudicates an alert in `UNDER_REVIEW` with a `decision` of `APPROVE`, `DENY` or `REQUEST_INFO`, optionally attaching `resolution_notes` which replace the stored note and are set to null when omitted. `APPROVE` moves the alert `UNDER_REVIEW → CLAIM_APPROVED` and `DENY` moves it `UNDER_REVIEW → CLAIM_DENIED`; both are terminal. `REQUEST_INFO` moves it `UNDER_REVIEW → INFO_REQUESTED`, from which the installer files again — supplying the requested information, again subject to the bank's warranty being `ACTIVE`, again recording `claimed_component` and again incrementing `claim_round_count` — returning the alert to `UNDER_REVIEW`. That review loop may repeat without limit. Acknowledging, filing or adjudicating from a status that does not declare the transition is rejected with `ERR_ALERT_STATE_INVALID`.

**Expanding a bank.** Households outgrow their first bank, and the system models an expansion as a *new* bank row that supersedes the old one rather than as an edit. Expansion is available only for a bank whose `build_status` is `COMMISSIONED` and whose `grid_status` is `PTO_GRANTED`. The request supplies `additional_unit_count`, the `inverter_model` and `firmware_version` of the expanded configuration, the incremental `installed_cost_cents` of the added units — the additional cost, not the new total — and the `expected_battery_system_version` of the base bank required by §2.6. The certification prerequisites of §3.3 apply here too, in the same order, so a suspended or lapsed installer cannot expand a bank.

Four compatibility rules are then evaluated in order against the base bank and the catalog of §2.11. First, the supplied `inverter_model` must belong to the same gateway family as the base bank's `inverter_model`; mixing a GW2-family gateway with a GW3-family one is rejected with `ERR_INVERTER_INCOMPATIBLE`. Second, the supplied `firmware_version` must be no older than the base bank's `firmware_version` and no older than the catalog minimum firmware for the base bank's `model_code`; either shortfall is rejected with `ERR_FIRMWARE_TOO_OLD`. Third, the base bank's `unit_count` plus `additional_unit_count` must not exceed the catalog's maximum unit count for that model, else `ERR_UNIT_LIMIT_EXCEEDED`. Fourth, the expanded bank inherits the original sizing obligation: its unit count is the base count plus the additional count, its energy is that unit count multiplied by the model's per-unit usable kWh and its power is that unit count multiplied by the model's per-unit continuous kW, each rounded half up to two decimals, and that new continuous power must be at least the `required_continuous_kw` of the load calculation the base bank was built against, else `ERR_CAPACITY_BELOW_REQUIRED`.

On success a new bank row is created. Its `expands_system_id` points at the base bank's `id`, its `unit_count` is the base count plus `additional_unit_count`, its `installed_cost_cents` is the base bank's installed cost plus the supplied additional cost, and its `site_id`, `installer_id`, `load_calculation_id` and `model_code` are copied from the base bank while its `inverter_model` and `firmware_version` come from the request. The new row starts fresh: `build_status` of `DESIGN_DRAFT`, `grid_status` of `NOT_APPLIED`, `warranty_status` of `UNREGISTERED`, and no `verified_capacity_kwh`, `commissioned_at`, `warranty_deadline_at`, `warranty_registered_at`, `warranty_coverage_years` or `serial_numbers` — the expanded bank must be permitted, approved, installed, commissioned and registered on its own account.

The base bank meanwhile enters **cascade C**. Its first hop sets the base bank's `build_status` to `SUPERSEDED`. Caused by that, the second hop moves every BYOD enrollment of the base bank whose `status` is `ENROLLED` to `SUSPENDED` — a superseded bank cannot answer a dispatch call. Caused by the second hop, the third hop cancels, for each such enrollment, every dispatch participation still in `PENDING` whose event is still `SCHEDULED`, subtracting each cancelled participation's `pledged_kw_snapshot` from its event's `enrolled_pledged_kw` so the event's committed-capacity ledger returns to exactly its pre-participation value.

### 3.9. Bring Your Own Device: Enrollment, Dispatch and Settlement

The utility's bring-your-own-device program pays households for capacity they actually deliver during dispatch events. The installer enrolls a bank by naming the `battery_system_id`, the `pledged_kw` the household offers per event, the `reserve_soc_pct` state-of-charge floor the household keeps back for its own backup, and the `season` the enrollment belongs to (`SUMMER_2026` or `WINTER_2026`). Enrollment presupposes a fully energized bank: the bank must be both `COMMISSIONED` on the build dimension and `PTO_GRANTED` on the grid dimension, else `ERR_ENROLLMENT_REQUIRES_PTO`. A bank may hold only one live enrollment per season — an existing enrollment for the same `season` whose `status` is not `WITHDRAWN` causes `ERR_DUPLICATE_ENROLLMENT`. The pledge itself is bounded: `pledged_kw` must be greater than zero and must not exceed the bank's `continuous_kw`, and `reserve_soc_pct` must lie between 0 and 50 inclusive; either violation is rejected with `ERR_PLEDGE_EXCEEDS_CAPACITY`. A new enrollment opens in `PENDING_CONSENT` with `cumulative_credited_kw`, `cumulative_pledged_kw`, `season_compliance_ratio`, `settled_event_count` and `performance_payment_cents_total` all at zero and with `consented_by_user_id` and `consented_at` unset.

Only the household can activate its own enrollment. Consent moves the enrollment `PENDING_CONSENT → ENROLLED`, requires the caller's `X-User-ID` to equal the `site_id` of the bank being enrolled, requires the bank's `grid_status` to still be `PTO_GRANTED`, and records `consented_by_user_id` from the caller's `X-User-ID` together with `consented_at` from the logical clock.

Either the household or its installer may withdraw, optionally supplying a `reason`. Withdrawing from `PENDING_CONSENT` moves the enrollment straight to `WITHDRAWN` and moves no capacity, because an unconsented enrollment can hold no participations. Withdrawing from `ENROLLED` moves it to `WITHDRAWN` and runs the capacity compensation: every participation of this enrollment still in `PENDING` whose event is still `SCHEDULED` becomes `CANCELLED`, processed in ascending participation `created_at`, and for each one the event's `enrolled_pledged_kw` is reduced by that participation's `pledged_kw_snapshot`, restoring the ledger to its pre-participation value. `WITHDRAWN` is terminal. An enrollment that a cascade has moved to `SUSPENDED` accepts neither consent nor withdrawal; those and any other undeclared transition are rejected with `ERR_ENROLLMENT_STATE_INVALID`.

**Calling an event.** A `UtilityInterconnectionReviewer` schedules a dispatch event by naming the `territory_code` it is called in, the half-open window bounded by an inclusive `window_start` and an exclusive `window_end` that must be strictly later, the `event_type` (`ECONOMIC` or `EMERGENCY`), the `target_kw` the utility is calling for (greater than zero), and the `payment_rate_cents_per_kw` it will pay per credited kilowatt (also greater than zero). Territory capacity is finite: the aggregate `target_kw` of time-overlapping events in the same `territory_code` may not exceed 1500 kW at any instant. The comparison uses half-open intervals with no buffer at all, so an event beginning at exactly the instant another ends never conflicts; a genuine overlap that would push the territory total above the cap is rejected with `ERR_TERRITORY_CAPACITY_EXCEEDED`. A new event opens in `SCHEDULED` with `enrolled_pledged_kw` and `total_net_payment_cents` at zero and `settled_at` unset.

The reviewer calls individual batteries into the event by naming the `byod_enrollment_id` and the `expected_dispatch_event_version`. Doing so creates a participation in `PENDING`, copies the enrollment's current `pledged_kw` into the participation's immutable `pledged_kw_snapshot`, adds that snapshot to the event's `enrolled_pledged_kw`, and advances the event's `version` by one — which is precisely why the next caller must re-read the event. The event must still be `SCHEDULED`, else `ERR_EVENT_STATE_INVALID`; the enrollment must be `ENROLLED`, else `ERR_ENROLLMENT_STATE_INVALID`; and an enrollment may appear in a given event only once, so a repeat is rejected with `ERR_PARTICIPATION_DUPLICATE`.

**Reporting delivery.** After the window has closed the reviewer reports metered `delivered_kwh` for a participation, which moves it `PENDING → REPORTED`. The event must still be `SCHEDULED` and the logical clock must have reached or passed the event's `window_end`; reporting for a participation that is not `PENDING` is rejected with `ERR_PERFORMANCE_STATE_INVALID`. Three figures are computed at this point and no money is. The event's window length in hours is computed exactly. `avg_delivered_kw` is `delivered_kwh` divided by that window length in hours, rounded half up to two decimals. `credited_kw` is the smaller of `avg_delivered_kw` and `pledged_kw_snapshot`, so over-delivery is never paid for. `performance_ratio` is `avg_delivered_kw` divided by `pledged_kw_snapshot`, rounded half up to four decimals.

**Settling the event.** Settlement moves the event `SCHEDULED → SETTLED` and requires that the logical clock has reached or passed `window_end` and that every participation of the event which is not `CANCELLED` has already reached `REPORTED`; a still-`PENDING` participation blocks settlement and is reported as `ERR_PERFORMANCE_STATE_INVALID`. Cancelled participations are skipped entirely — they contribute nothing to any accumulator and nothing to the event total. The remaining participations are settled one at a time in ascending participation `created_at`, each moving `REPORTED → SETTLED`, and the order is normative because each participation's bonus tier depends on accumulators the earlier ones have already advanced.

For each participation the settlement runs six steps.

1. **Gross payment.** The event multiplier is 12500 basis points when the event's `event_type` is `EMERGENCY` and 10000 basis points otherwise. The gross payment is `credited_kw` multiplied by the event's `payment_rate_cents_per_kw`, multiplied by that basis-point figure, divided by 10000, and rounded half up to a whole number of cents — one rounding step, after the multiplier. The result is stored as `gross_payment_cents`.
2. **Shortfall penalty.** When the participation's `performance_ratio` is strictly below 0.80, a penalty applies: take `pledged_kw_snapshot` multiplied by 0.80, subtract `avg_delivered_kw` from it, multiply the difference by the event's `payment_rate_cents_per_kw`, multiply by 0.50, and round half up to a whole number of cents. When the ratio is 0.80 or above, `shortfall_penalty_cents` is 0 — the boundary at exactly 0.80 is not a shortfall.
3. **Advance the enrollment's season accumulators.** The participation's `credited_kw` is added to the enrollment's `cumulative_credited_kw` and its `pledged_kw_snapshot` is added to the enrollment's `cumulative_pledged_kw`. The enrollment's `season_compliance_ratio` is then recomputed as `cumulative_credited_kw` divided by `cumulative_pledged_kw`, rounded half up to four decimals.
4. **Choose the bonus tier from the updated ratio.** This ordering is normative and non-negotiable: the tier is read from the `season_compliance_ratio` that already includes the participation being settled, never from the pre-event ratio. When that ratio is 0.95 or above the bonus is 1000 basis points; otherwise, when it is 0.85 or above the bonus is 500 basis points; otherwise there is no bonus. `bonus_cents` is `gross_payment_cents` multiplied by the chosen basis-point figure, divided by 10000, rounded half up to a whole number of cents.
5. **Net payment.** `net_payment_cents` is `gross_payment_cents` minus `shortfall_penalty_cents` plus `bonus_cents`, floored at zero — a participation never owes the utility money.
6. **Roll up.** The enrollment's `settled_event_count` is increased by one and its `performance_payment_cents_total` is increased by `net_payment_cents`; the event's `total_net_payment_cents` is increased by the same amount.

When every participation has been settled the event's `settled_at` is stamped from the logical clock and its `total_net_payment_cents` holds the sum of the settled net payments; an event with no non-cancelled participations settles with a total of zero. A settled event is terminal: neither a further participation nor a second settlement is possible, and both are rejected with `ERR_EVENT_STATE_INVALID`. The enrollment accumulators span every settled participation of that enrollment across all events of the season, in settlement order.

## 4. Endpoint Definitions

Every collection in this API is mounted at the root. An operation that brings a new resource into existence answers with HTTP 201 and the created resource in `data`; that includes the expansion endpoint, which creates a new battery system, and the participation endpoint, which creates a new dispatch performance. Every other successful operation — reads, state transitions, decisions, ledger movements, and the logical-clock capability — answers with HTTP 200, returning the affected resource in `data`, or an empty object where there is no resource to return. The table below gives only the HTTP contract and the authorized roles; the request payloads, the computed response fields and the side effects of each operation are specified in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/installers` | Register a manufacturer-certified installation company with its certification level, covered model codes and expiry. | ManufacturerWarrantyAgent |
| GET | `/installers/{installerId}` | Read one installer account, including its certification standing and compliance counters. | ManufacturerWarrantyAgent, CertifiedInstaller, RebateAdministrator, UtilityInterconnectionReviewer, AuthorityHavingJurisdiction |
| POST | `/installers/{installerId}/certification` | Amend an installer's certification — renew the expiry, change the level or covered models, or restore an account to active standing. | ManufacturerWarrantyAgent |
| POST | `/sites` | Create the premises record for a prospective installation; the site id doubles as the Homeowner's user id. | CertifiedInstaller |
| GET | `/sites/{siteId}` | Read one site. | CertifiedInstaller, Homeowner, AuthorityHavingJurisdiction, UtilityInterconnectionReviewer, RebateAdministrator |
| POST | `/load-calculations` | Create a load calculation and backup-scope design for a site; the sizing figures are computed immediately. | CertifiedInstaller |
| GET | `/load-calculations/{loadCalculationId}` | Read one load calculation with its computed sizing figures. | CertifiedInstaller, Homeowner, AuthorityHavingJurisdiction, UtilityInterconnectionReviewer |
| GET | `/load-calculations` | List load calculations, optionally filtered by site or status. | CertifiedInstaller, Homeowner, AuthorityHavingJurisdiction, UtilityInterconnectionReviewer |
| POST | `/load-calculations/{loadCalculationId}/submit` | Submit a draft calculation or resubmit one that was sent back, optionally overriding inputs before the sizing re-runs. | CertifiedInstaller |
| POST | `/load-calculations/{loadCalculationId}/review` | Authority decision on a submitted calculation: approve it or send it back for revision. | AuthorityHavingJurisdiction |
| POST | `/battery-systems` | Create a battery bank design against an approved load calculation. | CertifiedInstaller |
| GET | `/battery-systems/{batterySystemId}` | Read one battery system, including both status dimensions and the version used by the concurrency-guarded writes. | CertifiedInstaller, Homeowner, AuthorityHavingJurisdiction, UtilityInterconnectionReviewer, RebateAdministrator, ManufacturerWarrantyAgent |
| GET | `/battery-systems` | List battery systems, optionally filtered by site, installer, load calculation, superseded base system, or either status dimension. | CertifiedInstaller, Homeowner, AuthorityHavingJurisdiction, UtilityInterconnectionReviewer, RebateAdministrator, ManufacturerWarrantyAgent |
| POST | `/battery-systems/{batterySystemId}/lock-design` | Freeze the design so permitting and interconnection can proceed. | CertifiedInstaller |
| POST | `/battery-systems/{batterySystemId}/mark-installed` | Record physical installation completion. | CertifiedInstaller |
| POST | `/battery-systems/{batterySystemId}/commission` | Commission the bank; head of the commissioning cascade over rebate claims and program ledgers. | CertifiedInstaller |
| POST | `/battery-systems/{batterySystemId}/register-warranty` | Register the manufacturer warranty for a commissioned bank against its registration deadline. | CertifiedInstaller |
| POST | `/battery-systems/{batterySystemId}/expansions` | Add units to a commissioned bank, creating a new system that supersedes the base; concurrency-guarded on the base system's version. | CertifiedInstaller |
| POST | `/permits` | Open a building and electrical permit application for a design-locked system. | CertifiedInstaller |
| GET | `/permits/{permitId}` | Read one permit, including its correction round count and inspection findings. | CertifiedInstaller, Homeowner, AuthorityHavingJurisdiction, UtilityInterconnectionReviewer |
| GET | `/permits` | List permits, optionally filtered by system, jurisdiction or status. | CertifiedInstaller, Homeowner, AuthorityHavingJurisdiction, UtilityInterconnectionReviewer |
| POST | `/permits/{permitId}/submit` | Submit a draft permit, or resubmit one in corrections with an updated plan set. | CertifiedInstaller |
| POST | `/permits/{permitId}/review` | Jurisdiction decision on a submitted permit: issue it with a validity window, or request corrections. | AuthorityHavingJurisdiction |
| POST | `/permits/{permitId}/inspection-result` | Record a field-inspection outcome; a failure recorded against a previously passed inspection heads the interconnection-revocation cascade. | AuthorityHavingJurisdiction |
| POST | `/interconnection-applications` | File the utility interconnection application for a system, declaring the requested export posture and limit. | CertifiedInstaller |
| GET | `/interconnection-applications/{applicationId}` | Read one interconnection application, including the two operator identities the segregation-of-duties rule compares. | CertifiedInstaller, Homeowner, UtilityInterconnectionReviewer, AuthorityHavingJurisdiction, RebateAdministrator |
| GET | `/interconnection-applications` | List interconnection applications, optionally filtered by system, status or export mode. | CertifiedInstaller, Homeowner, UtilityInterconnectionReviewer, AuthorityHavingJurisdiction, RebateAdministrator |
| POST | `/interconnection-applications/{applicationId}/submit` | Submit a draft application or answer a supplemental-review request; also advances the system's grid dimension. | CertifiedInstaller |
| POST | `/interconnection-applications/{applicationId}/review` | Utility decision: approve to install (optionally derating the export limit), request supplemental review, or deny. | UtilityInterconnectionReviewer |
| POST | `/interconnection-applications/{applicationId}/grant-pto` | Grant permission to operate, by an operator other than the approving reviewer. | UtilityInterconnectionReviewer |
| POST | `/incentive-programs` | Create a funded incentive program with its two-tier rates, per-project cap, stacking priority and stacking ceiling. | RebateAdministrator |
| GET | `/incentive-programs/{programId}` | Read one incentive program with its three-bucket cents ledger. | RebateAdministrator, CertifiedInstaller, Homeowner, UtilityInterconnectionReviewer |
| GET | `/incentive-programs` | List incentive programs, optionally filtered by program type. | RebateAdministrator, CertifiedInstaller, Homeowner, UtilityInterconnectionReviewer |
| POST | `/rebate-claims` | Reserve an incentive for a system under one program, applying the stacking waterfall and encumbering the pool; concurrency-guarded on the system's version. | CertifiedInstaller |
| GET | `/rebate-claims/{claimId}` | Read one rebate claim, including both award variants and the approver and payer identities. | RebateAdministrator, CertifiedInstaller, Homeowner |
| GET | `/rebate-claims` | List rebate claims, optionally filtered by system, program or status. | RebateAdministrator, CertifiedInstaller, Homeowner |
| POST | `/rebate-claims/{claimId}/submit` | Submit a reserved claim for administrator adjudication. | CertifiedInstaller |
| POST | `/rebate-claims/{claimId}/decision` | Administrator approves or denies a submitted claim; denial releases the encumbrance. | RebateAdministrator |
| POST | `/rebate-claims/{claimId}/pay` | Disburse an approved claim, by an operator other than the approver. | RebateAdministrator |
| POST | `/rebate-claims/{claimId}/clawback` | Reverse a paid claim; head of the installer-suspension cascade. | RebateAdministrator |
| POST | `/rebate-claims/{claimId}/void` | Withdraw a reservation before submission, releasing the exact amount held and freeing stacking headroom. | CertifiedInstaller |
| POST | `/commissioning-tests` | Schedule one of the four required commissioning tests in a half-open window, subject to the installer's travel buffer. | CertifiedInstaller |
| GET | `/commissioning-tests/{testId}` | Read one commissioning test with its measured figures and verdict. | CertifiedInstaller, Homeowner, AuthorityHavingJurisdiction, UtilityInterconnectionReviewer, ManufacturerWarrantyAgent |
| GET | `/commissioning-tests` | List commissioning tests, optionally filtered by system, type, status or result. | CertifiedInstaller, Homeowner, AuthorityHavingJurisdiction, UtilityInterconnectionReviewer, ManufacturerWarrantyAgent |
| POST | `/commissioning-tests/{testId}/record-result` | Record the measured figures for a scheduled test; the verdict is computed, never supplied. | CertifiedInstaller |
| POST | `/monitoring-alerts` | Raise a fleet-monitoring alert against a battery system. | ManufacturerWarrantyAgent, CertifiedInstaller |
| GET | `/monitoring-alerts/{alertId}` | Read one monitoring alert and its warranty-claim lifecycle state. | ManufacturerWarrantyAgent, CertifiedInstaller, Homeowner |
| GET | `/monitoring-alerts` | List monitoring alerts, optionally filtered by system, code, severity or status. | ManufacturerWarrantyAgent, CertifiedInstaller, Homeowner |
| POST | `/monitoring-alerts/{alertId}/acknowledge` | Acknowledge an open alert and take ownership of triage. | CertifiedInstaller |
| POST | `/monitoring-alerts/{alertId}/file-claim` | File, or re-file after an information request, a warranty claim for the acknowledged alert. | CertifiedInstaller |
| POST | `/monitoring-alerts/{alertId}/review-claim` | Manufacturer adjudicates the warranty claim: approve, deny, or request further information. | ManufacturerWarrantyAgent |
| POST | `/byod-enrollments` | Enroll a commissioned, permission-granted system in a seasonal dispatch program with a pledged capacity and reserve floor. | CertifiedInstaller |
| GET | `/byod-enrollments/{enrollmentId}` | Read one enrollment with its season-to-date compliance accumulators. | CertifiedInstaller, Homeowner, UtilityInterconnectionReviewer |
| GET | `/byod-enrollments` | List enrollments, optionally filtered by system, season or status. | CertifiedInstaller, Homeowner, UtilityInterconnectionReviewer |
| POST | `/byod-enrollments/{enrollmentId}/consent` | Homeowner consents to utility dispatch of their battery, activating the enrollment. | Homeowner |
| POST | `/byod-enrollments/{enrollmentId}/withdraw` | Withdraw from the program, cancelling pending participations and returning their pledged capacity. | Homeowner, CertifiedInstaller |
| POST | `/dispatch-events` | Schedule a utility dispatch event in a territory over a half-open window, subject to the territory capacity cap. | UtilityInterconnectionReviewer |
| GET | `/dispatch-events/{eventId}` | Read one dispatch event, including its committed capacity and the version used by the concurrency-guarded write. | UtilityInterconnectionReviewer, CertifiedInstaller, Homeowner |
| GET | `/dispatch-events` | List dispatch events, optionally filtered by territory, status or event type. | UtilityInterconnectionReviewer, CertifiedInstaller, Homeowner |
| POST | `/dispatch-events/{eventId}/participations` | Call an enrolled battery into a scheduled event, snapshotting its pledged capacity; concurrency-guarded on the event's version. | UtilityInterconnectionReviewer |
| GET | `/dispatch-performances/{performanceId}` | Read one dispatch performance with its delivery figures and settlement amounts. | UtilityInterconnectionReviewer, CertifiedInstaller, Homeowner |
| GET | `/dispatch-performances` | List dispatch performances, optionally filtered by event, enrollment or status. | UtilityInterconnectionReviewer, CertifiedInstaller, Homeowner |
| POST | `/dispatch-performances/{performanceId}/report-delivery` | Report metered energy delivered during the event window and compute the delivery figures. | UtilityInterconnectionReviewer |
| POST | `/dispatch-events/{eventId}/settle` | Settle the event, pricing every reported participation in creation order and rolling up the totals. | UtilityInterconnectionReviewer |
| POST | `/_clock/set_current_utc` | Set the server's logical current UTC instant, which every deadline, expiry and window rule reads. | ManufacturerWarrantyAgent, CertifiedInstaller, Homeowner, AuthorityHavingJurisdiction, UtilityInterconnectionReviewer, RebateAdministrator |

## 5. Error Code Catalogue

Every error response carries its `error_id` in the envelope's `data` object as described in §2.2. The conditions that raise each code are specified in §2 and §3, and the order in which competing conditions are reported is fixed by §2.12.

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_ROLE_NOT_PERMITTED` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INSTALLER_NOT_FOUND` | 404 |
| `ERR_SITE_NOT_FOUND` | 404 |
| `ERR_LOAD_CALCULATION_NOT_FOUND` | 404 |
| `ERR_BATTERY_SYSTEM_NOT_FOUND` | 404 |
| `ERR_PERMIT_NOT_FOUND` | 404 |
| `ERR_APPLICATION_NOT_FOUND` | 404 |
| `ERR_PROGRAM_NOT_FOUND` | 404 |
| `ERR_CLAIM_NOT_FOUND` | 404 |
| `ERR_TEST_NOT_FOUND` | 404 |
| `ERR_ALERT_NOT_FOUND` | 404 |
| `ERR_ENROLLMENT_NOT_FOUND` | 404 |
| `ERR_EVENT_NOT_FOUND` | 404 |
| `ERR_PERFORMANCE_NOT_FOUND` | 404 |
| `ERR_LOAD_CALC_STATE_INVALID` | 409 |
| `ERR_SYSTEM_BUILD_STATE_INVALID` | 409 |
| `ERR_SYSTEM_GRID_STATE_INVALID` | 409 |
| `ERR_PERMIT_STATE_INVALID` | 409 |
| `ERR_APPLICATION_STATE_INVALID` | 409 |
| `ERR_CLAIM_STATE_INVALID` | 409 |
| `ERR_ALERT_STATE_INVALID` | 409 |
| `ERR_ENROLLMENT_STATE_INVALID` | 409 |
| `ERR_EVENT_STATE_INVALID` | 409 |
| `ERR_PERFORMANCE_STATE_INVALID` | 409 |
| `ERR_STALE_SYSTEM_VERSION` | 412 |
| `ERR_STALE_EVENT_VERSION` | 412 |
| `ERR_COMMISSIONING_TESTS_INCOMPLETE` | 422 |
| `ERR_BACKUP_TRANSITION_NOT_VERIFIED` | 422 |
| `ERR_COMMISSIONING_TEST_FAILED` | 422 |
| `ERR_INSTALLER_NOT_CERTIFIED` | 422 |
| `ERR_LOAD_CALC_NOT_APPROVED` | 422 |
| `ERR_CAPACITY_BELOW_REQUIRED` | 422 |
| `ERR_WARRANTY_NOT_ACTIVE` | 422 |
| `ERR_PERMIT_NOT_PASSED` | 422 |
| `ERR_ENROLLMENT_REQUIRES_PTO` | 422 |
| `ERR_PERMIT_EXPIRED` | 422 |
| `ERR_TEST_WINDOW_CONFLICT` | 409 |
| `ERR_TERRITORY_CAPACITY_EXCEEDED` | 409 |
| `ERR_DUPLICATE_PERMIT` | 409 |
| `ERR_DUPLICATE_APPLICATION` | 409 |
| `ERR_DUPLICATE_PROGRAM_CLAIM` | 409 |
| `ERR_DUPLICATE_TEST` | 409 |
| `ERR_DUPLICATE_ENROLLMENT` | 409 |
| `ERR_PARTICIPATION_DUPLICATE` | 409 |
| `ERR_PERMIT_CORRECTION_LIMIT` | 409 |
| `ERR_EXPORT_COMMITMENT_REQUIRED` | 422 |
| `ERR_CAPACITY_COMMITMENT_INVALID` | 422 |
| `ERR_STACK_CAP_EXCEEDED` | 422 |
| `ERR_INVERTER_INCOMPATIBLE` | 422 |
| `ERR_FIRMWARE_TOO_OLD` | 422 |
| `ERR_UNIT_LIMIT_EXCEEDED` | 422 |
| `ERR_PLEDGE_EXCEEDS_CAPACITY` | 422 |
| `ERR_PROGRAM_BUDGET_EXHAUSTED` | 422 |
