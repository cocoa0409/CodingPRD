# Rideshare Manifest Ops API — Product Requirements Document

## 1. Introduction

Rideshare launch economics are won or lost on the manifest. A single vehicle carries dozens of small payloads for many customers at once, and every kilogram and cubic meter must be reconciled against hard capacity limits while orbit targets, dispenser interfaces, regulatory licenses, and shared range availability constrain one another. When a mission slips, the consequences fan outward: range slots must be released, contracts rebooked onto later flights, and customers made whole. This document specifies the Rideshare Manifest Ops API, the system of record for assembling a rideshare manifest, scheduling it against a launch range, and carrying it through liftoff, deployment sequencing, and post-launch anomaly resolution.

The API serves eight operational roles spanning the launch provider, its payload customers, the range authority, and the licensing regulator. It governs customer contracting with launch-date windows, tiered per-kilogram pricing, and rebooking rights; payload integration with dispenser-port assignment, mechanical and electrical interface verification, and independent safety review; scored license applications for both launch authorization and payload operators; range scheduling with turnaround buffers, weather holds, and collision-avoidance windows; and the cascading effects of delays and scrubs on customer schedules. Every temporal rule in the system reads a single logical clock rather than the wall clock, so all window arithmetic is deterministic and reproducible.

All business resources are mounted under the `/rideshare` prefix; the platform's logical clock is driven through `/_clock/set_current_utc`.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, structural contracts, and cross-cutting principles that apply to every endpoint of the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. A request in which either header is missing, empty, or whitespace-only is rejected with `ERR_MISSING_OR_INVALID_CONTEXT_HEADER` (HTTP 400). The system recognizes exactly eight roles: `PlatformAdmin`, `MissionOps`, `ContractManager`, `Customer`, `IntegrationEngineer`, `SafetyOfficer`, `RangeOfficer`, and `Regulator`. Each endpoint authorizes a fixed subset of these roles, and a caller whose role is not in the endpoint's list is rejected with `ERR_FORBIDDEN` (HTTP 403).

Identity binding differs by role. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a `Customer` — a contract's `customer_id`, a license's `customer_id` — compare the resource's foreign-key field to `X-User-ID`. For the seven operator-side roles — `PlatformAdmin`, `MissionOps`, `ContractManager`, `IntegrationEngineer`, `SafetyOfficer`, `RangeOfficer`, and `Regulator` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it, and it does so as `created_by_user_id` on interface verifications and safety reviews, but it never compares it to any entity's `id`.

Customer scoping is enforced as invisibility, not as a permission error. A `Customer`-role caller may touch only contracts, licenses, payloads, and delay events belonging to the customer whose `id` equals `X-User-ID`; attempts to reach another customer's resource surface as `ERR_CONTRACT_NOT_FOUND` (HTTP 404), indistinguishable from a nonexistent resource. List endpoints visible to the `Customer` role auto-filter to the caller's own `customer_id`.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, read from the logical clock of §2.4 rather than any wall clock.
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
- Requests that match no route are rejected with `ERR_NOT_FOUND` (HTTP 404), and requests using a method the matched path does not support with `ERR_METHOD_NOT_ALLOWED` (HTTP 405); both use this same error envelope.

---

### 2.3. Pagination

For endpoints that return lists of resources, pagination is controlled by the `limit` and `offset` query parameters. When omitted, `limit` defaults to 10, with a minimum of 1 and a maximum of 100, and `offset` defaults to 0. Out-of-range values are clamped, not rejected: a `limit` below 1 or above 100 is pulled to the nearer bound and a negative `offset` is raised to 0, while a non-integer `limit` or `offset` is rejected with `ERR_INVALID_REQUEST` (400). Likewise, a query-string filter that names an enum domain — `status`, `kind`, `check_type`, `outcome`, `decision` — rejects a value outside that domain with `ERR_INVALID_REQUEST` (400). Unless an endpoint states otherwise, list endpoints return resources sorted by `created_at` in ascending order, with ties on `created_at` broken by creation order (the sequence in which the resources were persisted); the dispenser-port listing, the contract-payload listing, and the separation-event listing each declare their own ordering where they are described in §3. Paginated list responses include the fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. Logical Time and the Mission Clock

The system never reads the wall clock. Every time-dependent rule — window containment, weather and collision-avoidance membership, license validity, rebooking day counts, expiry — evaluates against a single logical clock. At server startup the logical clock reads exactly `2026-09-01T00:00:00Z`. A `PlatformAdmin` moves it by calling `/_clock/set_current_utc` with a `current_utc` instant; any parseable ISO 8601 instant is accepted — the clock may be moved backward as freely as forward, with no monotonicity guard — and the response body echoes the accepted `current_utc` verbatim, exactly as submitted, rather than in the canonical rendering of §2.5. Every move of the clock synchronously runs the time-driven expiry sweep described in §3.9 before the response is returned, so expirations are visible immediately after the clock changes.

### 2.5. Common Resource Properties and Version Semantics

All primary resources share a standard set of system-managed fields:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): an optimistic-concurrency counter.

Timestamps supplied by callers — the window bounds on missions, contracts, and range slots, exclusion-window `start_utc` and `end_utc`, license `valid_until`, and the window bounds recorded on delay events — are parsed as ISO 8601 instants — an instant submitted without a UTC offset is interpreted as UTC — and stored as instants; wherever they appear in a resource representation they are rendered in the same canonical form as `created_at`: an ISO 8601 UTC timestamp with exactly three fractional digits (a submitted `2026-10-05T12:00:00Z` reads back as `2026-10-05T12:00:00.000Z`).

An entity's `version` starts at 1 when the entity is created and increments by exactly 1 only where a state-machine transition or an endpoint's documented side effects say so. Pure derived-field recomputation — for example `committed_mass_kg`, `committed_volume_m3`, or `firm_mass_kg` being refreshed after an assignment confirm — updates `updated_at` without any `version` bump. Creating child rows, such as dispenser ports on a mission or verifications and safety reviews on an assignment, never increments the parent's `version`.

Append-only records — `InterfaceVerification`, `SafetyReview`, `ExclusionWindow`, and `DelayEvent` — carry only `id` and `created_at`; both `updated_at` and `version` are absent from these entities.

### 2.6. Validation Order: The Request Pipeline

Every request passes through the same validation pipeline, and the stages run in a fixed order: a failure at an earlier stage masks every later check, so the response always carries the first applicable rejection. The stages are:

1. **Context headers.** `X-User-ID` and `X-User-Role` must be present and non-empty, else `ERR_MISSING_OR_INVALID_CONTEXT_HEADER` (400).
2. **Role authorization.** The role must appear in the endpoint's authorized list, else `ERR_FORBIDDEN` (403).
3. **Customer scoping.** A `Customer`-role caller reaching for another customer's contract, license, payload, or delay event receives `ERR_CONTRACT_NOT_FOUND` (404).
4. **Request shape.** An empty request body is treated as an empty object (required-field checks then apply), while a malformed or non-object JSON body is rejected outright; fields an endpoint does not declare are ignored. All required fields must be present; enum values must lie in their declared domains; numeric domains are enforced (masses and volumes strictly greater than zero, license scores integers from 0 to 100 inclusive); every window's open must be strictly before its close; `WEATHER` windows must be range-scoped and `COLA` windows orbit-scoped; and license filings must pair `MISSION` subjects with `LAUNCH_AUTHORIZATION` and `CUSTOMER` subjects with `PAYLOAD_OPERATOR`, with the matching foreign key present. Violations surface as `ERR_INVALID_REQUEST` (400).
5. **Resource existence.** Referenced resources must exist, validated left-to-right along the URL path and then across body fields in their declared input order, surfacing the appropriate one of `ERR_CUSTOMER_NOT_FOUND`, `ERR_MISSION_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_PAYLOAD_NOT_FOUND`, `ERR_DISPENSER_PORT_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_RANGE_SLOT_NOT_FOUND`, `ERR_LICENSE_NOT_FOUND`, `ERR_SEPARATION_EVENT_NOT_FOUND`, or `ERR_ANOMALY_NOT_FOUND` (all 404).
6. **Optimistic concurrency.** The guarded writes of §2.8 compare the client-supplied expected version against the parent entity's current `version`, surfacing `ERR_STALE_MISSION_VERSION` or `ERR_STALE_CONTRACT_VERSION` (412).
7. **Lifecycle state.** The target resources must stand in a from-state of the requested transition, surfacing `ERR_INVALID_STATE`, `ERR_CONTRACT_NOT_SIGNED`, `ERR_MANIFEST_LOCKED`, `ERR_PAYLOAD_ALREADY_MANIFESTED`, `ERR_REBOOKING_NOT_ELIGIBLE`, `ERR_VERIFICATION_INCOMPLETE`, `ERR_SAFETY_REVIEW_REQUIRED`, or `ERR_ANOMALIES_UNRESOLVED` (all 409).
8. **Regulatory and safety gates.** License-held checks, grant thresholds, segregation of duties, collision-avoidance, and weather, surfacing `ERR_LICENSE_NOT_GRANTED`, `ERR_LICENSE_SCORE_TOO_LOW`, `ERR_COLA_CONFLICT`, or `ERR_WEATHER_HOLD` (all 422), and `ERR_SOD_VIOLATION` (403).
9. **Window arithmetic.** Contract, slot, mission, and delay window comparisons, surfacing `ERR_WINDOW_INCOMPATIBLE`, `ERR_LAUNCH_WINDOW_VIOLATION`, or `ERR_DELAY_REGRESSION` (all 422).
10. **Compatibility and uniqueness.** Orbit, interface, port-occupancy, mission-pinning, and port-label checks, surfacing `ERR_ORBIT_MISMATCH`, `ERR_INTERFACE_INCOMPATIBLE`, `ERR_MISSION_MISMATCH`, or `ERR_DUPLICATE_PORT_CODE` (all 422), and `ERR_PORT_OCCUPIED` (409).
11. **Capacity.** Mission mass and volume ceilings and per-port mass limits, surfacing `ERR_MASS_CAPACITY_EXCEEDED` or `ERR_VOLUME_CAPACITY_EXCEEDED` (both 422).

Because the order is fixed, a caller can never observe, for instance, a capacity failure on an assignment whose mission is not even accepting manifests: the state rejection arrives first.

### 2.7. Nested Resource Retrieval

Requests that address nested resources are validated left-to-right. When a path contains several identifiers — a mission and one of its dispenser ports, an assignment and one of its verifications — the system confirms each identifier in path order and rejects immediately with the 404 corresponding to the first identifier that does not resolve: a request naming a nonexistent mission fails with `ERR_MISSION_NOT_FOUND` before the system even examines later identifiers. Existence checks then continue across request-body references in their declared input order. This ordering applies uniformly to reads, creations, transitions, and removals.

### 2.8. Optimistic Concurrency Control

Exactly two write operations carry an optimistic-concurrency guard, each keyed to its parent entity's `version`.

Creating a manifest assignment requires the non-optional field `expected_mission_version`, carrying the client's last observed `version` of the target mission. If the mission's version has advanced since that observation — because another assignment was created or removed, the manifest was locked, or a delay landed — the create is rejected with `ERR_STALE_MISSION_VERSION` (HTTP 412), protecting the client from acting on a stale view of manifest capacity.

Rebooking a contract requires the non-optional field `expected_contract_version`, carrying the client's last observed `version` of the contract. A mismatch with the contract's current `version` is rejected with `ERR_STALE_CONTRACT_VERSION` (HTTP 412), protecting the client's view of `rebookings_remaining` and accumulated fees.

Endpoints not named here do not accept a version field.

### 2.9. Manifest Capacity Accounting

Every mission carries three derived commitment fields that together describe how full the vehicle is. `committed_mass_kg` and `committed_volume_m3` implement the TOTAL variant of manifest commitment: they sum the `mass_kg` and `volume_m3` of payloads whose assignments to the mission stand in `PROVISIONAL`, `CONFIRMED`, or `INTEGRATED`. `firm_mass_kg` implements the FIRM variant: the same mass sum restricted to assignments in `CONFIRMED` or `INTEGRATED`, excluding provisional reservations. For a mission holding 100 kg of confirmed assignments and 50 kg of provisional ones, the committed mass reads 150 kg while the firm mass reads 100 kg.

These fields are recomputed immediately, within the same request, whenever the manifest changes: assignment creation, assignment confirmation (which moves mass from the provisional-only bucket into the firm set), manual or cascaded removal, manifest lock, and scrub. Recomputation is a derived-field refresh: it updates the mission's `updated_at` but, per §2.5, never increments the mission's `version` on its own. Capacity gating at assignment-creation time evaluates the TOTAL variant, while lock-readiness reporting leans on the FIRM variant.

### 2.10. Monetary Precision and the Integration Fee Ledger

All monetary values are integer cents, and masses may themselves be fractional kilograms. Wherever a calculation produces a fractional cent, the system rounds half up to a whole cent. Two summation orders coexist on purpose, and they are not interchangeable. Each assignment's `integration_fee_cents` is rounded to a whole cent at the moment the assignment is created, per line. When the manifest is locked, the mission's `integration_revenue_cents` is stored as the sum of those already-rounded per-line fees — round per line, then sum — while `revenue_estimate_cents` is stored as the sum of the unrounded per-line terms, rounded half up once at the end — sum, then round. The two totals legitimately differ by a few cents: two CUBESAT lines of 1.001 kg each store 19,220 cents of integration revenue against an estimate of 19,219 cents. Both figures are stored on the mission at lock time and remain available on reads thereafter.

### 2.11. Segregation of Duties in Safety Sign-Off

Safety approval is deliberately separated from integration work. The engineer who records an interface verification is identified by `created_by_user_id`, captured from the `X-User-ID` header. A `SafetyOfficer` recording a safety review must not be the same individual as any engineer who recorded a `PASSED` verification on the same assignment: if the reviewer's `X-User-ID` equals the `created_by_user_id` of any `PASSED` interface verification on that assignment, the review is rejected with `ERR_SOD_VIOLATION` (HTTP 403).

## 3. Business Logic & Workflows

### 3.1. Provisioning the Manifest: Customers, Missions, and Dispenser Rings

Before any contract exists, a `PlatformAdmin` registers each customer organization with its legal `org_name` and primary `contact_email`. An optional `default_rebookings` count seeds the number of free rebooking rights each new contract of this customer receives; when omitted, it defaults to 1.

A `MissionOps` operator then creates rideshare missions. Each mission takes a `mission_name` (for example, Transporter-19), a `target_orbit` of `SSO`, `LEO`, or `GTO`, and a launch window: `window_open_utc` as the earliest permitted launch instant and `window_close_utc` as the latest, both closed bounds, with the close strictly after the open. Capacity is declared as `mass_capacity_kg` and `volume_capacity_m3`, each strictly greater than zero. A new mission opens in `MANIFEST_OPEN` status with `committed_mass_kg`, `committed_volume_m3`, `firm_mass_kg`, `integration_revenue_cents`, and `revenue_estimate_cents` all at zero. From there the mission walks a cyclic state machine: `MANIFEST_OPEN` to `MANIFEST_LOCKED` at manifest lock, onward to `RANGE_SCHEDULED` when a range slot is confirmed, to `LAUNCHED` at liftoff, and finally to `COMPLETED` once deployment finishes; a delay can drop it from `RANGE_SCHEDULED` back to `MANIFEST_LOCKED`, and either `MANIFEST_LOCKED` or `RANGE_SCHEDULED` can be scrubbed into the terminal `SCRUBBED` state.

The **dispenser ring** is configured per mission. A `MissionOps` operator adds ports one at a time, each with a `port_code` label, an integer `stack_position` (a higher position deploys earlier), a strictly positive `max_mass_kg`, and a non-empty `supported_interface_classes` array drawn from `RING_15`, `RING_24`, and `CUBESAT`. Both `port_code` and `stack_position` must be unique within the mission; reusing either is rejected with `ERR_DUPLICATE_PORT_CODE` (HTTP 422). Each port records its owning mission in `mission_id`, taken from the path it was created under. Listing a mission's ports returns them ordered by `stack_position` descending — deployment order, tip of the stack first. Adding a port is child-row creation and never bumps the mission's `version`.

### 3.2. Contracting and the Price Quote

A `ContractManager` drafts launch contracts on behalf of customers. Creation takes the contracting `customer_id` (an unknown customer is rejected with `ERR_CUSTOMER_NOT_FOUND`), a `pricing_mode` of `MARGINAL` or `FLAT`, and the contract's own launch-date window — `window_open_utc` and `window_close_utc`, closed bounds with the close strictly after the open — plus a `payloads` array describing every payload the contract covers. Each array entry supplies a `payload_name`, a strictly positive `mass_kg` and `volume_m3`, an `interface_class` of `RING_15`, `RING_24`, or `CUBESAT`, and a `required_orbit` of `SSO`, `LEO`, or `GTO`. The array may be empty, in which case the contract is created covering no payloads. The create is atomic across the array: if any single payload entry is invalid, the whole contract is rejected with `ERR_INVALID_REQUEST` and nothing is persisted. On success, each entry becomes a payload in `REGISTERED` status, stamped with its owning contract's `contract_id`.

Two optional fields shape the contract's future. `target_mission_id` pins the contract to a preferred mission: once set, assignments for this contract's payloads must target exactly that mission, a constraint enforced later as `ERR_MISSION_MISMATCH`. `rebookings_remaining` sets the free rebooking count; omitting it, or supplying the sentinel value of -1, inherits the customer’s `default_rebookings`; any other supplied integer is stored as given — there is no non-negativity constraint, and a stored negative simply never opens the free-rebooking door of §3.7. A fresh contract stands in `DRAFT` with `quoted_price_cents` and `total_rebooking_fees_cents` at zero and `rebook_eligible` false.

Signing belongs to the customer alone. The caller must present `X-User-Role` of `Customer` with `X-User-ID` equal to the contract's `customer_id`; any other caller receives `ERR_CONTRACT_NOT_FOUND` (HTTP 404), as if the contract did not exist. Signing computes and stores `quoted_price_cents` over the contract's payloads and moves the contract from `DRAFT` to `SIGNED`, incrementing its `version`. The quote is immutable thereafter — rebooking retargets a contract but never re-quotes it.

The quote aggregates the `mass_kg` of all of the contract's payloads, regardless of their status, and then prices by mode. Under `MARGINAL`, the aggregate mass waterfalls across three tiers: the first 50 kilograms bill at 600,000 cents per kilogram; the next 150 kilograms — aggregate mass above 50 kilograms, up to a cumulative ceiling of 200 kilograms — bill at 500,000 cents per kilogram; and any mass beyond 200 kilograms bills at 425,000 cents per kilogram. Each tier line is rounded half up to a whole cent before the three lines are summed. Under `FLAT`, the entire aggregate bills at the single rate of the highest tier reached: 600,000 cents per kilogram when the aggregate is at most 50 kilograms, 500,000 cents per kilogram when it is above 50 and at most 200 kilograms, and 425,000 cents per kilogram when it exceeds 200 kilograms, with the single multiplication rounded half up to a whole cent once. The tier boundaries belong to the lower tier in both modes: an aggregate of exactly 50 kilograms bills entirely within the first tier, and an aggregate of exactly 200 kilograms bills across the first two tiers with zero mass in the third.

Contracts can be listed with optional `customer_id`, `target_mission_id`, and `status` filters, ordered by `created_at` ascending; a `Customer`-role caller sees only its own. A contract's payloads are listed in exactly the order they were declared in the creation `payloads` array, with an optional `status` filter. From `SIGNED`, a contract automatically advances to `MANIFESTED` the moment the first live assignment is created for one of its payloads (§3.3), and it falls back from `MANIFESTED` to `SIGNED` whenever its last live assignment leaves the manifest through any removal path — manual removal, the delay cascade, a license revocation cascade, or a scrub.

### 3.3. Manifesting Payloads: Assignment, Verification, and Safety Approval

Manifesting a payload reserves capacity on a mission's dispenser ring. A `MissionOps` operator creates an assignment by naming the `mission_id`, the `payload_id`, the `dispenser_port_id` of a port on that mission's ring, and the optimistic-concurrency guard `expected_mission_version` (§2.8). The request then walks the validation pipeline of §2.6: existence failures surface as `ERR_MISSION_NOT_FOUND`, `ERR_PAYLOAD_NOT_FOUND`, or `ERR_DISPENSER_PORT_NOT_FOUND` — the last also covering a `dispenser_port_id` that names a port on a different mission's ring, which is indistinguishable from a nonexistent port; a mission version mismatch surfaces as `ERR_STALE_MISSION_VERSION`. Lifecycle gates follow. The mission must still be `MANIFEST_OPEN`, else `ERR_MANIFEST_LOCKED` (HTTP 409); the payload must be `REGISTERED`, else `ERR_PAYLOAD_ALREADY_MANIFESTED` (409); and the payload's contract must stand in `SIGNED` or `MANIFESTED`, else `ERR_CONTRACT_NOT_SIGNED` (409).

Temporal and compatibility checks come after the state gates. The contract's launch-date window must cover the mission's window — the contract's `window_open_utc` on or before the mission's `window_open_utc`, and the contract's `window_close_utc` on or after the mission's `window_close_utc` — else `ERR_WINDOW_INCOMPATIBLE` (HTTP 422). The payload's `required_orbit` must equal the mission's `target_orbit`, else `ERR_ORBIT_MISMATCH`. The payload's `interface_class` must appear in the port's `supported_interface_classes`, else `ERR_INTERFACE_INCOMPATIBLE`. The port must carry no other live assignment — one whose status is not `REMOVED` — else `ERR_PORT_OCCUPIED` (HTTP 409). And if the contract's `target_mission_id` is set, it must equal the assignment's mission, else `ERR_MISSION_MISMATCH`.

Capacity is judged last, on the TOTAL commitment variant of §2.9, with equality permitted. If adding the payload would push the mission's `committed_mass_kg` strictly above `mass_capacity_kg`, the create is rejected with `ERR_MASS_CAPACITY_EXCEEDED`; only after mass passes does the system check volume, rejecting with `ERR_VOLUME_CAPACITY_EXCEEDED` when `committed_volume_m3` would exceed `volume_capacity_m3`. Only after both mission-level checks pass is the per-port limit judged: the payload's `mass_kg` must not exceed the port's `max_mass_kg` — a payload exactly at the port's limit is allowed — or the create fails with `ERR_MASS_CAPACITY_EXCEEDED`.

A successful create lands the assignment in `PROVISIONAL` and triggers a chain of effects. The per-line integration fee is computed and stored as `integration_fee_cents`: the payload's `mass_kg` multiplied by 12,000 cents per kilogram, multiplied by the interface factor of its `interface_class` — 1.0 for `RING_15`, 1.25 for `RING_24`, and 0.8 for `CUBESAT` — then rounded half up to a whole cent. The payload advances from `REGISTERED` to `MANIFESTED`, incrementing its `version`. If this is the contract's first live assignment, the contract advances from `SIGNED` to `MANIFESTED`, incrementing its `version`. The mission's commitment fields are recomputed, and the mission's `version` increments by 1.

With the assignment in place, integration work begins. An `IntegrationEngineer` records interface verifications — immutable rows carrying the `assignment_id` from the path, a `check_type` of `MECHANICAL` or `ELECTRICAL`, an `outcome` of `PASSED` or `FAILED`, and optional free-text `notes`. Each verification stores the recording engineer's `X-User-ID` as `created_by_user_id`. Verifications are never updated; they may be recorded on an assignment in any status, and the latest record per `check_type` is the one that governs confirmation, ties on `created_at` breaking in favor of the record persisted later. A `SafetyOfficer` independently records safety reviews on the assignment — the `assignment_id` again taken from the path — with a `decision` of `APPROVE` or `REJECT` and an optional `rationale`, likewise immutable and stamped with `created_by_user_id`, and subject to the segregation-of-duties rule of §2.11. Safety reviews may likewise be recorded on an assignment in any status, and the latest safety review by `created_at` governs the assignment, with the same later-persistence tie-break. Verification listings filter by `check_type` and `outcome`; review listings filter by `decision`.

Confirmation is the point of commitment. A `MissionOps` operator confirms a `PROVISIONAL` assignment, and the gates fire in pipeline order: the assignment must be `PROVISIONAL` (else `ERR_INVALID_STATE`); the latest `MECHANICAL` verification must be `PASSED` and the latest `ELECTRICAL` verification must be `PASSED`, else `ERR_VERIFICATION_INCOMPLETE` (HTTP 409); the latest safety review must be an `APPROVE`, else `ERR_SAFETY_REVIEW_REQUIRED` (409); and the payload's customer must hold a `GRANTED` license of kind `PAYLOAD_OPERATOR`, else `ERR_LICENSE_NOT_GRANTED` (422). Confirmation increments the assignment's `version` and moves the mass it represents into the mission's firm accounting (§2.9).

Removal unwinds the commitment. A `MissionOps` operator may remove an assignment — optionally supplying a `reason_code`, which is validated as a string but not persisted on the assignment — only while it is `PROVISIONAL` or `CONFIRMED`; any other state is rejected with `ERR_INVALID_STATE`, though the cascade paths of §3.4 and §3.7 may also remove `INTEGRATED` assignments. Removal releases capacity: the mission's commitment fields are recomputed, the payload returns from `MANIFESTED` to `REGISTERED` with a version increment, and — when the removed assignment was the contract's last live one — the contract falls back from `MANIFESTED` to `SIGNED` with its own increment. The assignment's `version` and the mission's `version` each increment by 1. Assignments are listed with optional `mission_id`, `payload_id`, `dispenser_port_id`, and `status` filters, ordered by `created_at` ascending.

### 3.4. Regulatory Licensing: Filing, Grant, and Revocation

Two kinds of license keep the manifest legal. A launch authorization covers a mission: it is filed by `MissionOps` with `subject_type` `MISSION`, `kind` `LAUNCH_AUTHORIZATION`, and the subject `mission_id`. A payload-operator license covers a customer: it is filed by the `Customer` itself with `subject_type` `CUSTOMER`, `kind` `PAYLOAD_OPERATOR`, and the subject `customer_id` — and the filer's `X-User-ID` must equal that `customer_id`, else the filing is rejected with `ERR_FORBIDDEN` (HTTP 403). Symmetrically, a filing naming `subject_type` `MISSION` from any role other than `MissionOps` is rejected with `ERR_FORBIDDEN` (HTTP 403). Incoherent pairings — a `MISSION` subject with `PAYLOAD_OPERATOR` kind, a `CUSTOMER` subject with `LAUNCH_AUTHORIZATION` kind, or a filing missing the foreign key its `subject_type` requires — fail request-shape validation with `ERR_INVALID_REQUEST`.

Every filing carries three quality scores — `debris_score` for the orbital-debris mitigation plan, `spectrum_score` for spectrum coordination, and `operator_history_score` for operator track record, each an integer from 0 to 100 inclusive — plus a `valid_until` validity bound that must lie strictly in the future at filing time — a `valid_until` at or before the current logical time fails request-shape validation with `ERR_INVALID_REQUEST` (400). Within this endpoint the subject/kind coherence and `valid_until` checks run before the role binding just described, which in turn runs before the existence check on the referenced subject. The system immediately computes `composite_score` as one-half of `debris_score` plus three-tenths of `spectrum_score` plus one-fifth of `operator_history_score`, rounded half up to a whole integer, and the application enters `SUBMITTED`.

A `Regulator` decides each application by naming a `to_state`; the only accepted values are `GRANTED`, `DENIED`, and `REVOKED`, any other value failing request-shape validation with `ERR_INVALID_REQUEST` (400). Granting requires a `composite_score` of at least 70: a score of exactly 70 grants, while 69 or below is rejected with `ERR_LICENSE_SCORE_TOO_LOW` (HTTP 422). Denial from `SUBMITTED` is unconditional. Each of these transitions increments the license's `version`.

Revocation is the heavy hammer, and only one revocation cascades. When a `Regulator` moves a `GRANTED` license to `REVOKED`, a license covering a `CUSTOMER` subject of kind `PAYLOAD_OPERATOR` takes the manifest down with it: every live assignment — status `PROVISIONAL`, `CONFIRMED`, or `INTEGRATED` — of any payload belonging to that customer's contracts, on any mission in `MANIFEST_OPEN`, `MANIFEST_LOCKED`, or `RANGE_SCHEDULED`, is moved to `REMOVED`, each removal running the full release and bubble-up side effects of §3.3. A launch-authorization revocation changes the license's state and nothing else. Either way, the license's `version` increments by 1. Expiry is gentler still: a `GRANTED` license whose `valid_until` falls behind the logical clock moves to `EXPIRED` in the sweep of §3.9 with no assignment cascade at all — the deliberate contrast with revocation. `DENIED`, `REVOKED`, and `EXPIRED` are terminal.

Licenses are listed with optional `mission_id`, `customer_id`, `kind`, and `status` filters, ordered by `created_at` ascending; a `Customer`-role caller sees only its own filings.

### 3.5. Range Scheduling and Exclusion Windows

Launch ranges are shared infrastructure, and the `RangeOfficer` speaks for the range. A slot request names the `mission_id`, a `range_code` of `CCAFS` or `VAFB`, and a window — `window_open_utc` and `window_close_utc`, closed bounds with the close strictly after the open — and lands in `REQUESTED`. A mission's slots are listed with an optional `status` filter.

**Exclusion windows** close parts of the calendar. A `RangeOfficer` publishes each one with a `scope_type` of `RANGE` or `ORBIT`, a `scope_value` naming the range code (`CCAFS` or `VAFB`) or the orbit (`SSO`, `LEO`, or `GTO`) it applies to, and a `kind`: `WEATHER` windows must be range-scoped and `COLA` (collision-avoidance) windows must be orbit-scoped, a mismatched pairing — or a `scope_value` outside the domain its `scope_type` implies — being rejected with `ERR_INVALID_REQUEST`. Every exclusion window is the half-open interval from `start_utc` (inclusive) to `end_utc` (exclusive), with `end_utc` strictly after `start_utc`: an instant exactly at `start_utc` falls inside the window, while an instant exactly at `end_utc` is already clear of it. Exclusion windows are append-only records carrying only `id` and `created_at`.

Reservation enforces spacing between operators. Reserving a `REQUESTED` slot moves it to `RESERVED` only if it clears the turnaround buffer against every other slot on the same `range_code` that stands in `RESERVED` or `CONFIRMED`: on at least one side, a clear gap of 45 minutes or more must separate the two windows — either the new window's `window_close_utc` plus 45 minutes falls on or before the existing window's `window_open_utc`, or the existing window's `window_close_utc` plus 45 minutes falls on or before the new window's `window_open_utc`. A gap of exactly 45 minutes passes; anything shorter is a conflict, rejected with `ERR_RANGE_WINDOW_CONFLICT` (HTTP 422). Slots in `REQUESTED`, `RELEASED`, or `CONSUMED` never participate in the conflict check. Reservation increments the slot's `version`.

Confirmation is where the range, the regulator, and the manifest meet. Confirming a `RESERVED` slot runs its gates in pipeline order. The mission must stand in `MANIFEST_LOCKED`, else `ERR_INVALID_STATE` (HTTP 409). The mission must hold a `GRANTED` license of kind `LAUNCH_AUTHORIZATION` whose `valid_until` is on or after the slot's `window_close_utc`, else `ERR_LICENSE_NOT_GRANTED` (HTTP 422). No `COLA` exclusion window scoped to the mission's `target_orbit` may intersect the slot window under half-open semantics — intersection meaning the slot's `window_open_utc` is strictly before the exclusion window's `end_utc` and the exclusion window's `start_utc` is strictly before the slot's `window_close_utc`; windows that merely touch, the slot closing exactly as the exclusion opens or opening exactly as the exclusion closes, do not conflict — else `ERR_COLA_CONFLICT` (422). And the slot window must contain the mission window: the slot's `window_open_utc` on or before the mission's `window_open_utc`, and the slot's `window_close_utc` on or after the mission's `window_close_utc`, else `ERR_WINDOW_INCOMPATIBLE` (422). On success the slot becomes `CONFIRMED` with a version increment, and the mission automatically advances from `MANIFEST_LOCKED` to `RANGE_SCHEDULED`, incrementing the mission's `version` as well.

### 3.6. Manifest Lock, Launch, and Deployment Sequencing

Locking the manifest freezes the vehicle's load. A `MissionOps` operator locks a mission standing in `MANIFEST_OPEN`, but only when the manifest is fully adjudicated: at least one assignment on the mission must be `CONFIRMED`, and every assignment on the mission must stand in `CONFIRMED` or `REMOVED` — a lingering `PROVISIONAL` blocks the lock — with violations rejected as `ERR_INVALID_STATE` (HTTP 409). The lock flips every `CONFIRMED` assignment to `INTEGRATED`, incrementing each assignment's `version`, and stores both revenue figures of §2.10 on the mission: `integration_revenue_cents` as the sum of the already-rounded per-line `integration_fee_cents` values across the assignments that reach `INTEGRATED` in this lock, and `revenue_estimate_cents` as the round-half-up of the sum of the unrounded per-line terms. The mission's `version` increments by 1.

Launch is a single operator action gated by the sky and the calendar. A `MissionOps` operator launches a mission standing in `RANGE_SCHEDULED`; the launch instant is the current logical time — call it t. The gates run in pipeline order. State comes first: a mission not in `RANGE_SCHEDULED` is rejected with `ERR_INVALID_STATE`. Safety comes next: any `WEATHER` exclusion window scoped to the confirmed slot's `range_code` whose `start_utc` is at or before t and whose `end_utc` is strictly after t holds the launch with `ERR_WEATHER_HOLD` (HTTP 422) — remembering that an instant exactly at a weather window's `end_utc` is clear. Temporal containment comes last: t must fall within the mission's window on closed bounds and within the confirmed slot's window on closed bounds, either failure producing `ERR_LAUNCH_WINDOW_VIOLATION` (422).

A successful launch consumes the slot and choreographs deployment. The mission's `CONFIRMED` slot moves to `CONSUMED`, a cascade transition that refreshes the slot's `updated_at` but carries no `version` increment. The system then creates one **separation event** per assignment that is `INTEGRATED` at launch, in deployment order: assignments are ordered by their dispenser port's `stack_position` descending — the tip of the stack deploys first — with ties broken by the assignment's `created_at` in ascending order; identifiers are never used for ordering. The first event in this order is commanded at an `offset_seconds` of zero, and each subsequent event's `offset_seconds` equals the previous event's offset plus a base gap of 30 seconds, plus an additional 15 seconds whenever two consecutive payloads share the same `interface_class`. Each event records its zero-based `sequence_index` in this order along with the `mission_id` and `assignment_id` it belongs to, and starts in `PLANNED`. Separation-event status transitions never increment the event's `version`; they refresh `updated_at` only. The mission advances to `LAUNCHED` with a version increment.

Separation outcomes arrive from the mission console. A `MissionOps` operator reports each event's `outcome` as `EXECUTED` or `ANOMALOUS`. Reporting `EXECUTED` against a `PLANNED` event cascades upward: the event's assignment moves from `INTEGRATED` to `DEPLOYED` and its payload from `MANIFESTED` to `DEPLOYED`, each incrementing its `version`; and the bubble-up continues — if every payload of the assignment's contract is now `DEPLOYED`, the contract moves from `MANIFESTED` to `FULFILLED` with a version increment, and if every separation event of the mission has reached `EXECUTED`, the mission moves from `LAUNCHED` to `COMPLETED`, again with a version increment. Reporting `ANOMALOUS` requires `anomaly_category` (`SEPARATION` or `PAYLOAD_TELEMETRY`) and `anomaly_severity` (`LOW`, `MEDIUM`, or `HIGH`); if either is missing, the report is rejected with `ERR_INVALID_REQUEST`. An anomalous report creates an anomaly record in `OPEN` status, its `mission_id` copied from the separation event and its `category` and `severity` taken from the report. An event in `ANOMALOUS` may later be reported `EXECUTED`, but only once every anomaly of the mission stands in `RESOLVED`, else the report is rejected with `ERR_ANOMALIES_UNRESOLVED` (HTTP 409); a successful late execution then runs the same deployment and bubble-up effects as a clean one. Reporting `EXECUTED` on an already-`EXECUTED` event, or reporting `ANOMALOUS` on an event no longer in `PLANNED`, is rejected with `ERR_INVALID_STATE` (HTTP 409). Separation events are listed ordered by `sequence_index` ascending, with optional `mission_id`, `assignment_id`, and `status` filters.

### 3.7. Delay, Scrub, and Rebooking Rights

Delays are a fact of the launch business, and the API prices their fallout. A `MissionOps` operator delays a mission by supplying `new_window_open_utc`, `new_window_close_utc`, and a free-text `reason_code`. The mission must not stand in a terminal state: delaying a `COMPLETED` or `SCRUBBED` mission is rejected with `ERR_INVALID_STATE` (HTTP 409). The new open must be strictly after the mission's current `window_open_utc` — a sideways or backward move is rejected with `ERR_DELAY_REGRESSION` (HTTP 422) — and the new close must be strictly after the new open. The delay records a `DelayEvent`, which is why the operation returns 201: the record captures the mission's `mission_id`, the `previous_window_open_utc` and `previous_window_close_utc`, the new bounds, the `reason_code`, and two system-computed fields, `slot_released` and `assignments_removed_count`; like all event records it carries only `id` and `created_at`. A mission's delay history is listed for `MissionOps`, `ContractManager`, and the affected `Customer` — a `Customer` counting as affected when one of its contracts, in any status, has `target_mission_id` naming this mission or holds, or ever held, an assignment on it in any assignment status; any other `Customer`-role caller receives `ERR_CONTRACT_NOT_FOUND` (HTTP 404), as if the resource did not exist.

The delay cascade runs immediately. The mission's window is replaced by the new bounds, incrementing the mission's `version` by 1. If the mission stood in `RANGE_SCHEDULED`, the containment test decides the slot's fate: when the `CONFIRMED` slot no longer contains the new window — containment requiring the slot's `window_open_utc` on or before the new open and the slot's `window_close_utc` on or after the new close — the slot is released to `RELEASED` (a cascade transition carrying no `version` increment), `slot_released` is recorded true, and the mission drops back from `RANGE_SCHEDULED` to `MANIFEST_LOCKED`, that automatic hop incrementing the mission's `version` again. A slot that still contains the new window is never released by a delay, and in that case the mission stays `RANGE_SCHEDULED`.

Impacted contracts are then swept in the order the contracts were created, `created_at` ascending. The sweep visits every contract whose `target_mission_id` names this mission or that holds a live assignment on it; a contract whose `window_close_utc` falls before the new mission `window_close_utc` is impacted. For each impacted contract, every live assignment of its payloads on this mission moves to `REMOVED` — each removal running the full release cascade of §3.3 — and every impacted contract — whatever its status, and whether or not it held assignments on this mission — has `rebook_eligible` set true, a flag change that refreshes `updated_at` without any `version` increment; a contract standing in `MANIFESTED` whose last live assignment has left additionally falls back to `SIGNED` per §3.3, with its own `version` increment. Contracts whose window still covers the new mission window are untouched. `assignments_removed_count` records how many assignments the cascade removed, and the mission's commitment fields are recomputed once the sweep completes.

Scrubbing is the terminal version of the same logic. A `MissionOps` operator scrubs a mission standing in `MANIFEST_LOCKED` or `RANGE_SCHEDULED`, supplying a `reason_code`; the mission moves to `SCRUBBED` with a version increment. Every assignment in `PROVISIONAL`, `CONFIRMED`, or `INTEGRATED` moves to `REMOVED`; each payload returns to `REGISTERED`; and each contract left with no remaining live assignments while standing in `MANIFESTED` returns to `SIGNED` with `rebook_eligible` set true. From `RANGE_SCHEDULED`, every slot of the mission standing in `RESERVED` or `CONFIRMED` is released to `RELEASED`, again with no `version` increment. The mission's commitment fields are recomputed — all zero once the sweep completes.

Rebooking is how stripped or patient customers move to a later flight. The owning `Customer`, or a `ContractManager` acting on its behalf, rebooks a contract by naming `to_mission_id` and the optimistic-concurrency guard `expected_contract_version` (§2.8); a stale version is rejected with `ERR_STALE_CONTRACT_VERSION` (HTTP 412). The contract must stand in `SIGNED` and the target mission must be `MANIFEST_OPEN`, else `ERR_REBOOKING_NOT_ELIGIBLE` (HTTP 409); and the contract's window must cover the target mission's window — the same closed-bound coverage as §3.3 — else `ERR_WINDOW_INCOMPATIBLE` (422). The fee depends on which of three doors stands open, checked in this order. If `rebook_eligible` is true, the rebooking is free: no fee is charged, `rebookings_remaining` is left unchanged, and the flag is cleared to false. Otherwise, if `rebookings_remaining` is greater than zero, the rebooking consumes one right: no fee is charged and `rebookings_remaining` decreases by 1. Otherwise the fee is a bracketed percentage of `quoted_price_cents`, rounded half up to a whole cent: 10 percent when the target mission's `window_open_utc` is at least 61 days away, 25 percent when it is between 31 and 60 days away inclusive, and 50 percent when it is 30 days away or fewer — the day count being the whole-day floor of the gap between the current logical time and the target mission's `window_open_utc`, measured in 86,400-second days. Whatever the fee, it accumulates into `total_rebooking_fees_cents`, `target_mission_id` is set to `to_mission_id`, and the contract's `version` increments by 1. The stored `quoted_price_cents` never changes.

### 3.8. Anomaly Investigation and Mission Completion

Anomalies raised at deployment time (§3.6) live their own lifecycle, driven by `MissionOps` or `SafetyOfficer` naming a `to_state`; the accepted values are exactly `UNDER_INVESTIGATION`, `ESCALATED`, and `RESOLVED`, any other value failing request-shape validation with `ERR_INVALID_REQUEST` (400). An anomaly opens in `OPEN`, moves to `UNDER_INVESTIGATION`, may be promoted to `ESCALATED`, and may drop back from `ESCALATED` to `UNDER_INVESTIGATION` as the picture clarifies. Resolution is possible from either `UNDER_INVESTIGATION` or `ESCALATED` into `RESOLVED`, and it is not complete without a disposition: the transition requires a `disposition` of `NOMINAL` or `LOSS` — a missing or out-of-domain value is rejected with `ERR_INVALID_REQUEST` — and records any supplied `resolution_notes`; `disposition` and `resolution_notes` supplied on transitions to other states are ignored and never stored. Every transition increments the anomaly's `version`. A mission's anomalies are listed for `MissionOps` and `SafetyOfficer` with an optional `status` filter.

Completion is entirely automatic. As each separation event reports `EXECUTED`, the system re-examines the fleet: when every separation event of a mission has reached `EXECUTED`, the mission moves from `LAUNCHED` to `COMPLETED`, incrementing its `version`. `COMPLETED` and `SCRUBBED` are the mission's terminal states. For contracts, `FULFILLED` and `EXPIRED` are terminal; for payloads, `DEPLOYED` is terminal; for assignments, `DEPLOYED` and `REMOVED` close the lifecycle; for slots, `CONSUMED` and `RELEASED` are terminal.

### 3.9. Time-Driven Expiry

Every move of the logical clock (§2.4) runs the expiry sweep synchronously, before the clock response returns, and the sweep examines two populations. Each contract still in `SIGNED` whose `window_close_utc` lies before the current logical time moves to `EXPIRED`, with `rebook_eligible` cleared to false and its `version` incremented. Each license still in `GRANTED` whose `valid_until` lies before the current logical time moves to `EXPIRED` with its `version` incremented and — in deliberate contrast to revocation — no assignment cascade. Contracts in `DRAFT`, `MANIFESTED`, or `FULFILLED` are never swept, and neither are licenses in `SUBMITTED`, `DENIED`, or `REVOKED`.

## 4. Endpoint Definitions

Operations that create a new resource — registering a customer, creating a mission, adding a dispenser port, drafting a contract, manifesting an assignment, recording a verification or a safety review, filing a license, requesting a range slot, publishing an exclusion window, and recording a delay (which persists a new `DelayEvent`) — return `201 Created`. Operations that modify an existing resource, including every state transition and the clock move, return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock and run the expiry sweep | PlatformAdmin |
| POST | `/rideshare/customers` | Register a customer organization | PlatformAdmin |
| POST | `/rideshare/missions` | Create a rideshare mission | MissionOps |
| GET | `/rideshare/missions/{id}` | Read a mission including computed commitment and revenue fields | MissionOps, RangeOfficer, IntegrationEngineer, SafetyOfficer, ContractManager, Regulator, PlatformAdmin, Customer |
| POST | `/rideshare/missions/{id}/lock-manifest` | Lock the manifest and store both integration revenue totals | MissionOps |
| POST | `/rideshare/missions/{id}/launch` | Launch the mission and create separation events | MissionOps |
| POST | `/rideshare/missions/{id}/scrub` | Scrub the mission, releasing slots and stripping the manifest | MissionOps |
| POST | `/rideshare/missions/{id}/delay` | Move the mission window later and run the delay cascade | MissionOps |
| POST | `/rideshare/missions/{id}/dispenser-ports` | Add a dispenser port to a mission | MissionOps |
| GET | `/rideshare/missions/{id}/dispenser-ports` | List a mission's dispenser ports | MissionOps, IntegrationEngineer |
| GET | `/rideshare/missions/{id}/range-slots` | List a mission's range slots | MissionOps, RangeOfficer |
| GET | `/rideshare/missions/{id}/delay-events` | List a mission's delay events | MissionOps, ContractManager, Customer |
| GET | `/rideshare/missions/{id}/anomalies` | List a mission's anomaly reports | MissionOps, SafetyOfficer |
| POST | `/rideshare/contracts` | Create a contract atomically with its payloads | ContractManager |
| GET | `/rideshare/contracts` | List contracts | ContractManager, Customer, MissionOps |
| GET | `/rideshare/contracts/{id}` | Read a contract | ContractManager, Customer, MissionOps |
| POST | `/rideshare/contracts/{id}/sign` | Sign a contract and store its price quote | Customer |
| POST | `/rideshare/contracts/{id}/rebook` | Retarget a signed contract to a later mission | Customer, ContractManager |
| GET | `/rideshare/contracts/{id}/payloads` | List a contract's payloads in declaration order | ContractManager, Customer, MissionOps, IntegrationEngineer |
| POST | `/rideshare/assignments` | Manifest a payload onto a mission port | MissionOps |
| GET | `/rideshare/assignments` | List manifest assignments | MissionOps, IntegrationEngineer, SafetyOfficer |
| GET | `/rideshare/assignments/{id}` | Read a manifest assignment | MissionOps, IntegrationEngineer, SafetyOfficer |
| POST | `/rideshare/assignments/{id}/confirm` | Confirm a provisional assignment | MissionOps |
| POST | `/rideshare/assignments/{id}/remove` | Remove an assignment from the manifest | MissionOps |
| POST | `/rideshare/assignments/{id}/verifications` | Record an interface verification | IntegrationEngineer |
| GET | `/rideshare/assignments/{id}/verifications` | List an assignment's interface verifications | IntegrationEngineer, SafetyOfficer, MissionOps |
| POST | `/rideshare/assignments/{id}/safety-reviews` | Record a safety review decision | SafetyOfficer |
| GET | `/rideshare/assignments/{id}/safety-reviews` | List an assignment's safety reviews | SafetyOfficer, MissionOps |
| POST | `/rideshare/licenses` | File a license application | MissionOps, Customer |
| GET | `/rideshare/licenses` | List license applications | Regulator, MissionOps, Customer |
| GET | `/rideshare/licenses/{id}` | Read a license | Regulator, MissionOps, Customer |
| POST | `/rideshare/licenses/{id}/transition` | Grant, deny, or revoke a license | Regulator |
| POST | `/rideshare/range-slots` | Request range time for a mission | RangeOfficer |
| POST | `/rideshare/range-slots/{id}/reserve` | Reserve a requested range slot | RangeOfficer |
| POST | `/rideshare/range-slots/{id}/confirm` | Confirm a reserved range slot | RangeOfficer |
| POST | `/rideshare/exclusion-windows` | Publish a weather or COLA exclusion window | RangeOfficer |
| GET | `/rideshare/separation-events` | List separation events | MissionOps, IntegrationEngineer, SafetyOfficer |
| GET | `/rideshare/separation-events/{id}` | Read a separation event | MissionOps, IntegrationEngineer, SafetyOfficer |
| POST | `/rideshare/separation-events/{id}/report-outcome` | Report a separation outcome | MissionOps |
| POST | `/rideshare/anomalies/{id}/transition` | Transition an anomaly report | MissionOps, SafetyOfficer |

## 5. Error Code Catalogue

Trigger conditions for each error live in §2 and §3 alongside the workflows they guard.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_SOD_VIOLATION` | 403 Forbidden |
| `ERR_CUSTOMER_NOT_FOUND` | 404 Not Found |
| `ERR_MISSION_NOT_FOUND` | 404 Not Found |
| `ERR_CONTRACT_NOT_FOUND` | 404 Not Found |
| `ERR_PAYLOAD_NOT_FOUND` | 404 Not Found |
| `ERR_DISPENSER_PORT_NOT_FOUND` | 404 Not Found |
| `ERR_ASSIGNMENT_NOT_FOUND` | 404 Not Found |
| `ERR_RANGE_SLOT_NOT_FOUND` | 404 Not Found |
| `ERR_LICENSE_NOT_FOUND` | 404 Not Found |
| `ERR_SEPARATION_EVENT_NOT_FOUND` | 404 Not Found |
| `ERR_ANOMALY_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_CONTRACT_NOT_SIGNED` | 409 Conflict |
| `ERR_MANIFEST_LOCKED` | 409 Conflict |
| `ERR_PAYLOAD_ALREADY_MANIFESTED` | 409 Conflict |
| `ERR_VERIFICATION_INCOMPLETE` | 409 Conflict |
| `ERR_SAFETY_REVIEW_REQUIRED` | 409 Conflict |
| `ERR_ANOMALIES_UNRESOLVED` | 409 Conflict |
| `ERR_PORT_OCCUPIED` | 409 Conflict |
| `ERR_REBOOKING_NOT_ELIGIBLE` | 409 Conflict |
| `ERR_STALE_MISSION_VERSION` | 412 Precondition Failed |
| `ERR_STALE_CONTRACT_VERSION` | 412 Precondition Failed |
| `ERR_LICENSE_NOT_GRANTED` | 422 Unprocessable Entity |
| `ERR_LICENSE_SCORE_TOO_LOW` | 422 Unprocessable Entity |
| `ERR_COLA_CONFLICT` | 422 Unprocessable Entity |
| `ERR_WEATHER_HOLD` | 422 Unprocessable Entity |
| `ERR_LAUNCH_WINDOW_VIOLATION` | 422 Unprocessable Entity |
| `ERR_WINDOW_INCOMPATIBLE` | 422 Unprocessable Entity |
| `ERR_ORBIT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_INTERFACE_INCOMPATIBLE` | 422 Unprocessable Entity |
| `ERR_MISSION_MISMATCH` | 422 Unprocessable Entity |
| `ERR_MASS_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_VOLUME_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_RANGE_WINDOW_CONFLICT` | 422 Unprocessable Entity |
| `ERR_DELAY_REGRESSION` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_PORT_CODE` | 422 Unprocessable Entity |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_METHOD_NOT_ALLOWED` | 405 Method Not Allowed |
