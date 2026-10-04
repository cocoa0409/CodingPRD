# Smart Apartment Access Hardware API — Product Requirements Document

## 1. Introduction

Modern multifamily communities are, in practice, small distributed computing
environments. A single property can carry thousands of battery-powered locks,
thermostats, leak sensors and community-door controllers, all of them reachable
only over whatever wireless mesh the building happens to support. This document
specifies the API that SmartRent exposes to the operators who design that
network, install the hardware into it, and then keep it alive: hardware
deployment across smart locks, thermostats, leak sensors and community access
points; installation scheduling inside occupied units; hub connectivity and
network design in buildings with poor wireless coverage; resident onboarding
with app credentials; guest access and move-out credential revocation;
self-guided tour access for prospects with identity verification and
time-bounded entry codes; vacant-unit automation that sets temperature setpoints
and detects unauthorized entry; maintenance access workflows with statutory
notice requirements and audit trails; hardware failure and battery replacement
programs; and property-management integration for resident status changes.

Two pressures shape almost every rule that follows. The first is that access is a
safety property, not a convenience: an entry code that outlives the tenancy, or a
lock that opens on an empty unit, is a physical security incident, so credential
lifecycles are conservative and every credential that could open a door is
enumerated. The second is that these buildings are frequently hostile to radio.
Where coverage is marginal, an install that "succeeds" against a link that the
hub cannot actually hold is worse than no install at all, so the platform treats
wireless viability as a gate on both provisioning and resident onboarding rather
than as a diagnostic.

The result is a workflow-orchestration surface with an audit spine. Decisions are
made by a small set of peer roles — `PlatformAdmin`, `PropertyManager`,
`HardwareTechnician`, `MaintenanceTechnician`, `LeasingAgent` and `Resident` —
and each decision leaves a durable trace: status events for residents, alerts
for hardware, accruals for money spent on empty units, and state transitions on
every entity that can hold a door open. All endpoints are mounted under the
`/smart-rent` prefix.

## 2. Global Specifications & System-Wide Principles

This section states the cross-cutting rules that hold for every operation in the
API: who may call it, what a response looks like, how lists are paged, how
identity and money are represented, and in what order the platform evaluates the
checks that guard a request.

### 2.1. User and Role-Based Access Control

Every request must carry two headers. `X-User-ID` identifies the acting
operator and `X-User-Role` declares their capacity. A request that omits either
header, or that presents a `X-User-Role` value the platform does not recognize,
is refused with `ERR_UNAUTHENTICATED` and an HTTP status of 401. A request whose
role is recognized but is not permitted to perform the operation it targets is
refused with `ERR_FORBIDDEN` and an HTTP status of 403. Authorization is
per-operation, and the authoritative mapping of operation to permitted role is
the "Authorized Role(s)" column of the endpoint table in §4.

The platform recognizes exactly six roles, spelled as follows: `PlatformAdmin`,
`PropertyManager`, `HardwareTechnician`, `MaintenanceTechnician`,
`LeasingAgent`, and `Resident`.

`PlatformAdmin` is the SmartRent platform operator who provisions properties,
buildings and devices across all tenants. `PlatformAdmin` holds exclusive
authority over property creation and building creation, and shares the
remaining provisioning and read capabilities listed in §4.

`PropertyManager` is on-site property staff. The operations reserved to
`PropertyManager` alone are resident onboarding, resident deactivation, the
certification of legal notice on a maintenance visit, the cancellation of a
certified maintenance visit, and the vacant-unit automation run. `PropertyManager` additionally shares guest-pass issuance,
maintenance-visit requests and completion, installation-job creation, and the
matching read operations.

`HardwareTechnician` is the field technician who installs devices, replaces
batteries and closes work orders. Exclusive to `HardwareTechnician` are battery
replacement, starting an installation job, completing an installation job, and
progressing a work order through assignment. `HardwareTechnician` shares device
provisioning, building reachability scans, installation-job creation, and the
matching read operations.

`MaintenanceTechnician` is the in-house technician who performs unit visits. It
holds no exclusive operation; it shares maintenance-visit requests,
maintenance-visit completion, and maintenance-visit listing.

`LeasingAgent` is leasing staff. Verifying a prospect's identity on a tour
session is exclusive to `LeasingAgent`, which also shares tour-session requests
and tour-session listing.

`Resident` is a unit resident who manages guest passes on their own unit. It
holds no exclusive operation; it shares guest-pass issuance, guest-pass
extension, and guest-pass listing.

Identity is resolved differently for the resident role than for the five
operator roles. When `X-User-Role` is `Resident`, `X-User-ID` is the `id` of the
acting `Resident`; ownership checks on any resource that references a `Resident`
compare the resource's foreign-key field to `X-User-ID`. In particular, a
guest pass may only be issued or extended by a `Resident` whose own `id` equals
the pass's `host_resident_id`. When `X-User-Role` is `PlatformAdmin`,
`PropertyManager`, `HardwareTechnician`, `MaintenanceTechnician`, or
`LeasingAgent`, `X-User-ID` is an opaque operator identifier that is not tied to
any persisted entity. The platform records it where the workflow calls for an
operator reference — for example as the `assigned_technician_id` on a
`WorkOrder` or the `technician_id` on a `MaintenanceVisit` — but never compares
it to any entity's `id` and never uses it for ownership scoping.

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

List responses are paged through query parameters. `limit` sets the maximum number
of items returned; when it is omitted it defaults to 10, and the accepted range
is a minimum of 1 and a maximum of 100. A `limit` outside that range is clamped
into it rather than refused, and a negative `offset` is clamped to 0. `offset`
sets how many items are skipped
and defaults to 0. Every list endpoint returns its resources sorted by creation
timestamp in ascending order — that is, oldest `created_at` first. Paged and
unpaged list responses alike carry `limit`, `offset`, `total_count`, and
`has_more` in the `meta` object of the response envelope.

Several list endpoints accept optional narrowing filters. The available filter
parameters across the API are `property_id`, `building_id`, `unit_id`,
`occupancy_status`, `resident_id`, `subject_resident_id`, `host_resident_id`,
`technician_id`, `device_id`, and `alert_id`; each is used only by the
endpoints named in §4, and each is optional. When a filter is omitted, the
endpoint returns the unfiltered collection.

### 2.4. Hardware Identity and Common Resource Properties

Nearly every resource in this API is addressable and auditable. The following
long-lived resources all carry the standard system-managed fields: `Property`,
`Building`, `Unit`, `Device`, `DeviceAlert`, `WorkOrder`, `Resident`,
`AccessCredential`, `GuestPass`, `TourSession`, `MaintenanceVisit`, and
`InstallationJob`.

- `id` — a unique, server-minted identifier rendered as a UUID. It carries no
  type prefix and no readable component; two resources of different types may
  never be distinguished by inspecting an `id` string.
- `created_at` — an ISO 8601 timestamp in UTC with exactly three fractional
  digits (for example `2025-05-24T10:30:00.123Z`) recording when the resource
  was first created.
- `updated_at` — an ISO 8601 UTC timestamp with three fractional digits
  recording when the resource was last modified. Any change to any property of
  the resource refreshes it, including changes the server makes on its own
  behalf.
- `version` — an integer, starting at its initial value and incremented by
  exactly one on every modification of the resource. `version` is what clients
  echo back for optimistic concurrency control (§2.9), so a mutation that
  changes nothing observable still counts as a modification if it writes.

One resource is deliberately leaner. `ResidentStatusEvent` is an append-only
audit record and carries only `id` and `created_at`; both `updated_at` and
`version` are absent from its representation, and it is never modified after
creation.

Several attributes that the server derives rather than accepts are nevertheless
part of the resource's representation and are returned to clients. A client
reading a resource sees the computed `connectivity_ok` on a building, the
`budget_committed_cents` on a property, the `occupancy_status`, `target_setpoint_c`,
`hvac_mode` and `unauthorized_entry_detected` on a unit, the `battery_pct`,
`status`, `lock_state`, `battery_replacements` and `battery_health_score` on a
device, the `severity` and
`status` of an alert, the `battery_replaced` flag on a work order, the
`planned_hours`, `actual_hours`, `accrued_cost_cents` and `status` of a
maintenance visit, the `labor_hours` and `status` of an installation job, and the
`portal_credential_status` and `status` of a resident. The battery health score
is null on a device until a scan of its building first computes it. Refreshing
either of the two purely derived verdicts — a building's `connectivity_ok` and a
device's `battery_health_score` — is not a modification of the resource: it
neither refreshes `updated_at` nor increments `version`. Every other computed
attribute is written as part of a modification that does. Computed
attributes are never accepted as input, and supplying one is an unknown-field
rejection under §2.12.

### 2.5. Wireless Coverage and Building Connectivity

Every building in the portfolio declares a `network_design`, one of
`POINT_TO_POINT`, `FIELD_MESH`, or `HUB_RELAY`, and reports the measured hub
signal strength as `wifi_rssi_dbm` — a negative integer, so a value closer to
zero is a stronger link. The `connectivity_ok` attribute on a building is the
platform's verdict on whether that link is good enough to carry door traffic.

The verdict is a threshold comparison, and the threshold depends on the design.
A `POINT_TO_POINT` building must reach at least -67 dBm. A `FIELD_MESH` building
must reach at least -75 dBm. A `HUB_RELAY` building must reach at least -80 dBm.
The comparison is inclusive on the strong side: a building measuring exactly its
design threshold counts as connected.

Before the comparison, the raw reading is aged. If `last_hub_service_at` is
null — the hub has never been serviced — no age penalty applies and the raw
`wifi_rssi_dbm` is compared directly. If `last_hub_service_at` is set, the
platform subtracts an age penalty equal to 0.1 dB per whole day elapsed between
`last_hub_service_at` and the current logical clock, where the elapsed day count
is rounded down to a whole number before multiplication. Because the penalty is
subtracted from an already-negative number, an unserviced hub degrades the
effective link over time and can flip a building from connected to disconnected
even though its raw reading has not changed. The comparison uses exact dBm
values and involves no rounding of the reading itself.

`connectivity_ok` is computed when a building is created, and it is recomputed
whenever an operation that depends on it is evaluated — creating an installation
job refreshes it from the building's current `wifi_rssi_dbm` and
`last_hub_service_at`, and installation-job completion and resident onboarding
both consult it live rather than caching a stale verdict. Because the age penalty
depends on the logical clock (§3.10), the same building can read as connected at
one moment and disconnected at a later one without any of its stored attributes
having changed.

### 2.6. Access Windows, Legal Notice and Schedule Exclusivity

Two resource types occupy a unit's calendar: `MaintenanceVisit` and
`TourSession`. Occupations of the same unit may not overlap. Any request that
would create or start an occupation whose interval intersects an existing one on
the same unit is refused with `ERR_UNIT_SCHEDULE_CONFLICT` and an HTTP status of
409. The rule is checked when a maintenance visit is requested, when a
guest pass is issued against a unit, and when a scheduled installation job is
started. A maintenance visit holds its span only while it is `REQUESTED` or
`NOTICE_CERTIFIED`, so a `CANCELLED` or `COMPLETED` visit holds nothing; a tour
session holds its span only while it is `REQUESTED`, `VERIFIED` or `ACTIVE`, so a
`DENIED` or `COMPLETED` session holds nothing.

Maintenance entry into an occupied unit is additionally gated by statutory
notice. A visit is created in the `REQUESTED` state and cannot be certified
until the platform is satisfied that the tenant was given enough warning. The
required lead time is 48 hours for an ordinary visit and 24 hours for an
emergency visit — a visit is flagged as an emergency by its `is_emergency`
boolean, which defaults to false. The lead time is measured between the instant
notice was served, carried on the visit as `notice_mailed_at`, and the visit's
planned `start_at`. If notice was served later than the required lead time
allows, certification is refused with `ERR_NOTICE_REQUIREMENT_UNMET` and an HTTP
status of 409.

Entry is also confined to business hours. The visit's `start_at`, taken in its
local hour, must fall inside the half-open legal window that opens at 08:00 and
closes at 20:00 — that is, an hour of 08 through 19 is acceptable and an hour of
20 or later is not. A visit whose start falls outside that window is refused
with `ERR_OUTSIDE_NOTICE_WINDOW` and an HTTP status of 422.

### 2.7. Credential Conservation and the Move-Out Cascade

Access credentials are the platform's most sensitive rows, and they obey a
conservation invariant. Every `AccessCredential` belongs to exactly one unit,
and its lifecycle is a closed set: it is created in `ISSUED`, becomes `ACTIVE`
when its validity window opens, and ends as either `EXPIRED` (its window
elapsed) or `REVOKED` (it was withdrawn). The four live states partition the
population, so counting every credential a resident has ever held gives the same
number whether the count is taken as the sum of the `ISSUED`, `ACTIVE`, `EXPIRED`
and `REVOKED` groups or as the size of the full set. The count is an exact integer
and is never taken over a filtered time window.

The invariant has two scopes, and they differ. Scoped to a resident — that is,
restricted to rows whose `subject_resident_id` equals the resident's `id` — the
count covers only that resident's own credentials and excludes guest and tour
credentials. Scoped to a unit — restricted to rows whose `unit_id` equals the
unit's `id` — the count covers every credential on the unit, including those of
type `GUEST` and `TOUR`.

Move-out is the cascade that makes the invariant operationally meaningful. When
a resident is deactivated, every credential in the resident's scope that is
still `ISSUED` or `ACTIVE` is moved to `REVOKED` in the same operation, the
resident's `portal_credential_status` is recomputed, and the resident's unit is
pulled out of occupancy. The deactivation response reports the resident in
`DEACTIVATING`, not `REVOKED`: it first passes through `DEACTIVATING`, and only
becomes `REVOKED` once no credential in its scope remains in `ISSUED` or
`ACTIVE`. That condition is a matter of credential liveness alone — no clock
reading is consulted — and the cascade revokes the live credentials in the same
operation, so it is satisfied there and the terminal hop lands in storage as the
deactivation completes: a subsequent read observes `REVOKED`. This ordering is
deliberate — it guarantees that a resident is never marked as fully moved out
while a credential that could open their door is still live.

### 2.8. The Vacant-Unit Energy Budget

Empty units still cost money. Every property carries two budget attributes: a
`temp_budget_cents_per_day` allowance, which defaults to 500 cents and is
interpreted over a planning horizon of one day, and a
`budget_committed_cents` accumulator, which starts at 0.

`budget_committed_cents` is the sum of `accrued_cost_cents` across the property's
`MaintenanceVisit` rows whose status is `NOTICE_CERTIFIED` or `COMPLETED`. Rows
that are `CANCELLED` contribute nothing, and cancelling a visit resets that
visit's own `accrued_cost_cents` to 0 rather than leaving a stale accrual behind.
In addition, each installation job placed against a building of the property
holds a reservation of 2000 cents, and that reservation is carried inside
`budget_committed_cents`; a job that reaches `ABORTED` releases its reservation,
so only jobs still `SCHEDULED` or `IN_PROGRESS`, or `COMPLETED`, are counted.

The platform refuses any operation that would push `budget_committed_cents`
above `temp_budget_cents_per_day`. The check applies when a maintenance visit is
certified, when an installation job is completed, and when an installation job
is created, and the refusal carries `ERR_BUDGET_EXCEEDED` with an HTTP status of
409. Note that the check is on the committed total, not on the individual
operation's cost: an operation that is cheap in isolation is still refused if
the property's running total is already at or over its allowance.

### 2.9. Optimistic Concurrency Control

Two write operations in this API are guarded against stale client views, and
exactly two. Clients of these operations must supply the version they last
observed for the parent resource they are writing against; the field is
mandatory, not optional, and a request that omits it is incomplete.

The first guard applies when a work order is opened against a device alert. That
request must carry `expected_device_alert_version`, the client's last observed
`version` of the target `DeviceAlert`. If the alert's current `version` differs
from the supplied value — because another writer has since resolved, acknowledged
or otherwise mutated the alert — the operation is rejected with `ERR_STALE_VERSION`
and an HTTP status of 412. The client is thereby prevented from attaching work to
an alert state it has not observed.

The second guard applies when an installation job is created against a building.
That request must carry `expected_building_version`, the client's last observed
`version` of the target `Building`. If the building's current `version` differs
from the supplied value — because another writer has changed the building's
connectivity or placed its own job — the operation is rejected with
`ERR_STALE_VERSION` and an HTTP status of 412.

These two endpoints, and no others, take a version field. Every other write in
the API is unversioned: endpoints that are not named above neither accept nor
require an `expected_..._version` input. Both stale-version rejections are
evaluated as the last check in the platform's validation ordering (§2.12), so a
request that is both stale and otherwise invalid surfaces the earlier, more
specific error.

### 2.10. Device Telemetry and Battery Health

Devices report reachability rather than uptime, and the platform converts those
reports into two derived quantities: a per-device battery draw and a per-device
health score.

Battery draw is a function of failed contact. Every reachability scan in which a
device is absent costs the device one percentage point of `battery_pct`, and the
draw is floored so the value never becomes negative. A device that is present in
the scan loses nothing. Devices powered from mains — hubs — are pinned at 100
percent and never draw down. A scan in which a device is reachable and its
`battery_pct` is strictly below 20 percent raises a low-battery alert on that
device, with severity `MEDIUM`.

The battery health score is a weighted composite of three signals, and the order
in which its terms are rounded is pinned. The battery term is the device's
`battery_pct` multiplied by 0.5 and rounded half-up to one decimal place. The
firmware term is a firmware score multiplied by 0.3 and rounded half-up to one
decimal place, where the firmware score is 100 for `LATEST`, 40 for `OLD`, and 0
for `CRITICAL`. The alert term is an alert score multiplied by 0.2 and rounded
half-up to one decimal place, where the alert score is 100 less 25 for each
`OPEN` alert on the device, and never below 0. Each term is rounded first; the
three rounded terms are then summed and the sum is rounded half-up to one
decimal place. The score is computed for every device in the building, including
one that has been `DECOMMISSIONED`.

### 2.11. Numeric Precision and Rounding

Different quantities in this API carry different precision, and each is stated
here once so that no endpoint has to restate it.

Monetary amounts — `accrued_cost_cents`, `budget_committed_cents`,
`temp_budget_cents_per_day`, and the reserved installation amount — are whole
integer cents and are never rounded; the accrual arithmetic that produces them
is exact. Temperature setpoints are expressed in Celsius to one decimal place,
rounded half-up. Installation labor hours are expressed to two decimal places,
rounded half-up. Battery health scores are expressed to one decimal place,
rounded half-up, with the per-term rounding order described in §2.10. Signal
strength comparisons involve no rounding at all — the dBm values are compared
exactly as measured and as penalised.

### 2.12. Validation Order and Nested Resource Resolution

Multiple checks can apply to a single request, and a request can fail more than
one of them. To make the outcome deterministic, the platform evaluates its
checks in a fixed order and returns the first failure; a later check never masks
an earlier one.

The order is as follows. First, authentication: the two identity headers must be
present, and the role must be recognized — otherwise `ERR_UNAUTHENTICATED`
(401). Second, authorization: the calling role must be permitted for the
operation — otherwise `ERR_FORBIDDEN` (403). Third, request well-formedness: the
body must carry every required field, must carry no unknown field, and must not
attempt to supply a computed attribute — otherwise `ERR_INVALID_REQUEST` (400).
Fourth, existence, resolved left to right down the path (see below). Fifth, the
target resource must be in a state from which the requested transition is
declared — otherwise `ERR_INVALID_STATE` (409); this check guards tour
verification, work-order assignment, installation-job start, maintenance
certification, maintenance completion, guest-pass extension, and resident
onboarding. Sixth, the target resource must not already be in a terminal state —
otherwise `ERR_ALREADY_TERMINAL` (409); this guards work-order assignment once
the order is `CLOSED`, tour verification once the session is `COMPLETED`,
maintenance completion once the visit is `CANCELLED` or `COMPLETED`, and
guest-pass extension once the pass is `REVOKED`. Seventh, an operation that acts on a resident's unit
requires that resident not to be `REVOKED` — otherwise `ERR_RESIDENT_NOT_ACTIVE`
(409); this guards guest-pass issuance and guest-pass extension. Eighth, a tour
verification requires the session to be in a non-terminal state on which
verification is declared, namely `REQUESTED`, `DENIED` or `VERIFIED` — otherwise
`ERR_INVALID_STATE` (409). Ninth, the tour session's verification window must not
have elapsed — otherwise `ERR_IDENTITY_VERIFICATION_EXPIRED` (409). Tenth, legal
notice must have been served at the required lead time — otherwise
`ERR_NOTICE_REQUIREMENT_UNMET` (409). Eleventh, the visit start must fall inside
the legal notice window — otherwise `ERR_OUTSIDE_NOTICE_WINDOW` (422). Twelfth,
the requested window must not overlap an existing occupation of the same unit —
otherwise `ERR_UNIT_SCHEDULE_CONFLICT` (409). Thirteenth, the unit's building
must pass connectivity and at least one smart lock on the unit must be online —
otherwise `ERR_INSUFFICIENT_CONNECTIVITY` (409); this guards resident onboarding
and installation-job completion. Fourteenth, a hub installation requires the
target building already to pass connectivity — otherwise
`ERR_NO_HUB_CONNECTIVITY` (409). Fifteenth, the device whose battery is being
replaced must be reachable — otherwise `ERR_DEVICE_UNREACHABLE` (409).
Sixteenth, the credential's subject and validity window must be consistent with
the unit's occupancy, the resident's state and the credential's status —
otherwise `ERR_CREDENTIAL_OUT_OF_SCOPE` (409). Seventeenth, the supplied
identity document is compared against the tour session's prospect document; a
mismatch is not an error but a denial, recorded by moving the session to
`DENIED` and incrementing `verify_attempts` (§3.6). Eighteenth, a supplied setpoint
override must lie within the permitted setpoint range — otherwise
`ERR_SETPOINT_OUT_OF_RANGE` (422). Nineteenth, a unit's `unit_number` must be
unique within its property — otherwise `ERR_DUPLICATE_UNIT_NUMBER` (409).
Twentieth, the operation must not push the property's committed budget over its
allowance — otherwise `ERR_BUDGET_EXCEEDED` (409). Twenty-first and last, a
supplied `expected_..._version` must equal the parent's current `version` —
otherwise `ERR_STALE_VERSION` (412).

Because the budget check precedes the stale-version check, a request that is both
over budget and stale is refused for the budget. Because the existence check
precedes every state and business check, a request naming a resource that does
not exist is refused for that reason before any state, safety or financial rule
is consulted.

For paths that carry more than one resource identifier, existence is resolved in
strict left-to-right order, and the request is refused at the first identifier
that does not resolve. The identifier set is `propertyId`, `buildingId`,
`unitId`, `deviceId`, `residentId`, `guestPassId`, `tourSessionId`,
`maintenanceVisitId`, `installationJobId`, `deviceAlertId` and `workOrderId`.
The refusal status is 404, and the error identifier names the resource class that
failed: `ERR_PROPERTY_NOT_FOUND`, `ERR_BUILDING_NOT_FOUND`, `ERR_UNIT_NOT_FOUND`,
`ERR_DEVICE_NOT_FOUND`, `ERR_RESIDENT_NOT_FOUND`, `ERR_GUEST_PASS_NOT_FOUND`,
`ERR_TOUR_SESSION_NOT_FOUND`, `ERR_MAINTENANCE_VISIT_NOT_FOUND`,
`ERR_INSTALLATION_JOB_NOT_FOUND`, `ERR_DEVICE_ALERT_NOT_FOUND`, or
`ERR_WORK_ORDER_NOT_FOUND`. The rule reaches every endpoint whose error catalogue
entry names that class, and a request for a child under a missing parent always
reports the parent's identifier first.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Property: Portfolio, Buildings and Units

A `PlatformAdmin` opens the portfolio by registering a `Property`, supplying its
`name` and `address_line` and optionally a planned `unit_capacity` — which
defaults to 0 — together with a `temp_budget_cents_per_day` allowance, which
defaults to 500. The property is created with `budget_committed_cents` at 0 and
will accrue from there.

Buildings are added beneath an existing property. A `PlatformAdmin` supplies the
building's `name`, its `network_design` — one of `POINT_TO_POINT`, `FIELD_MESH`
or `HUB_RELAY` — a `wifi_rssi_dbm` reading, and optionally the instant the hub
was `last_hub_service_at`. On creation the platform immediately derives
`connectivity_ok` from the reading, the design threshold and the service age, by
the rules in §2.5. A building whose link does not clear its threshold is not
refused at creation; it is simply recorded as not connected, and that verdict
will later block the operations that depend on it.

Units are the third level. A `PropertyManager` or `PlatformAdmin` creates a unit
under a property with a `unit_number`, which must be unique inside that property,
and optionally the `building_id` of the building it sits in and the bookable
window bounds `pod_entry_window_start` and `pod_entry_window_end` that the
platform uses as the earliest and latest instant a tour or maintenance visit may
be booked against the unit. Supplying a `unit_number` that is already in use
within the property is refused with `ERR_DUPLICATE_UNIT_NUMBER` (409).

A newly created unit is born vacant. The server sets `occupancy_status` to
`VACANT`, `hvac_mode` to `VACANT_AUTO`, and `target_setpoint_c` to 26.0 — the
default vacant setpoint — and `unauthorized_entry_detected` to false. From that
point the unit's occupancy travels a one-way cycle with a cancellable tail:
`VACANT` becomes `OCCUPIED` when a resident moves in; `OCCUPIED` becomes
`NOTICE` when that resident gives notice; `NOTICE` becomes `NOTICE_ENDED` when
the logical clock reaches the declared notice end; and `NOTICE_ENDED` becomes
`VACANT` again once the unit is returned to the vacant program. Units may be
read individually or listed, and a list may be narrowed by property, by
building, or by occupancy state.

### 3.2. Radio Before Racks: Devices, Hubs and Reachability Scans

A `Device` is provisioned before it is installed. `PlatformAdmin` or
`HardwareTechnician` supplies the `device_type` — one of `SMART_LOCK`,
`THERMOSTAT`, `LEAK_SENSOR`, `COMMUNITY_ACCESS` or `HUB` — the `building_id` it
is installed in, an optional `unit_id` when the device serves a specific unit
(community devices and hubs leave it null), a `firmware_version` of `LATEST`,
`OLD` or `CRITICAL`, and an optional `battery_pct`. The platform initializes the
device to `status` `PROVISIONED`, `lock_state` `LOCKED`, `battery_replacements`
0, and `battery_pct` at the supplied value or 100 when none is supplied. A hub
is mains-powered: its `battery_pct` is pinned at 100 regardless of what is
supplied, and it never draws down.

Reachability is established by scanning. A scan of a building reports the set of
device identifiers that answered, in `reachable_device_ids`, and an optional
`window_forecast_c` and `relative_humidity_pct` that describe conditions at the
building at scan time; the platform returns the alerts the scan touched, with a
`200 OK` status rather than `201 Created` even though the scan may raise fresh
alerts. The
scan drives the device status dimension. A device in `PROVISIONED` that answers
becomes `ONLINE`. A device in `ONLINE` that does not answer becomes
`UNREACHABLE`, draws one percentage point of battery, and raises an `OFFLINE`
alert against it — this alert is `OPEN` from birth and carries severity `HIGH`.
A device in `UNREACHABLE` that answers again returns to `ONLINE`, and any `OPEN`
`OFFLINE` alert on it is resolved. The scan additionally recomputes the battery
health score of every device in the building — a `DECOMMISSIONED` device
included — by the weighted formula of §2.10, and it raises a `LOW_BATTERY` alert of severity `MEDIUM` on any
reachable device whose `battery_pct` has fallen strictly below 20 percent.

Device state is a parallel dimension, not a single ladder. A device's `status`
and its `lock_state` evolve independently: `lock_state` is meaningful only for
`SMART_LOCK` devices and begins `LOCKED`. Recording a lock event against a smart
lock that is currently `ONLINE` moves `lock_state` to `UNLOCKED` when the event
type is an unlock and back to `LOCKED` on a close; the event type arrives as
`event_type` — `UNLOCK` or `UNLOCKED` in either all-upper or all-lower case is an
unlock, and `CLOSE`, `CLOSED`, `LOCK` or `LOCKED` in either case is a close,
while any other value is refused with `ERR_INVALID_REQUEST` (400) — and an unlock
may carry an optional `credential_code`. Recording a lock event does not move the
device's `status`, which stays `ONLINE`. A lock event recorded against a device
that is not a `SMART_LOCK`, or that is not `ONLINE`, is refused with
`ERR_INVALID_STATE` (409).

The vacant-unit intrusion rule lives on that same action and is stated in full
in §3.3, because it is a property of the unit rather than of the device.

### 3.3. Vacant Units, Setpoints and Unauthorized Entry

A vacant unit is not an unmanaged unit. A `PropertyManager` runs the vacant
automation against a unit by supplying the building's `window_forecast_c` and
`relative_humidity_pct`, and optionally a `setpoint_override_c`. The setpoint the
platform writes to `target_setpoint_c` is derived, and the derivation has two
explicit shapes.

Ordinarily the base setpoint is 26.0 Celsius. If the window forecast reaches or
exceeds 30 Celsius, the base rises to 27.0 Celsius. The base is then clamped into
the permitted setpoint range, which runs from a minimum of 15 to a maximum of 27,
and written to one decimal place with half-up rounding; the default base
therefore survives unchanged, and the hot-weather base is clamped down to 27 if
it would exceed the ceiling. This is the base shape, and it is what applies
whenever the humidity is below the stress threshold of 60 percent, or the
forecast is below 27 Celsius, or both.

The humidity shape overrides it. When the relative humidity is at or above 60
percent and the window forecast is at or above 27 Celsius, the unit is
dehumidified rather than merely cooled: the platform ignores the base and the hot
clamp entirely and sets the setpoint to 24.0 Celsius, clamped to the same
permitted range. Humidity alone does not trigger this — a humid but mild window
takes the base shape — and a hot but dry window takes the base shape as well.

If the caller supplies a `setpoint_override_c`, it is validated against the
permitted range before use: a value below 15 or above 27 is refused with
`ERR_SETPOINT_OUT_OF_RANGE` (422). Note that only the override can violate the
range, because the computed value is already clamped. The automation always
leaves the unit in `hvac_mode` `VACANT_AUTO`.

The same automation completes the last hop of the occupancy cycle. When it is
run against a unit in `NOTICE_ENDED` and no resident whose status is `ACTIVE`
still references the unit, the unit moves to `VACANT` and its
`budget_committed_cents` roll-up on the owning property is refreshed.

The second responsibility of a vacant unit is intrusion detection, and it is
evaluated on smart-lock events. When a `HardwareTechnician` or `PropertyManager`
records an unlock event against a smart lock on a unit whose `occupancy_status`
is `VACANT`, the platform asks whether the unit has a reason for the door to be
open: an `ACTIVE` guest or tour credential whose window covers the current
logical clock, or a `NOTICE_CERTIFIED` maintenance visit whose window covers the
current logical clock. Absent both, the unlock has no authorization behind it.
The platform then sets the unit's `unauthorized_entry_detected` to true and
raises a `DeviceAlert` of type `UNAUTHORIZED_ENTRY`, severity `HIGH`, in `OPEN`
status. An authorized unlock on the same vacant unit turns the lock without
raising anything.

Occupancy itself is set by the resident side of the system, not by the device
side: creating the first resident against a vacant unit moves that unit to
`OCCUPIED` — see §3.4.

### 3.4. Resident Onboarding and the Credential Window

A `Resident` record is created by a `PlatformManager`-class operator — a
`PropertyManager` or `PlatformAdmin` — against a property and a unit, carrying
the resident's `full_name` and `email`. The record is born in
`PENDING_CREDENTIAL` with `portal_credential_status` `NOT_ISSUED`, and the
resident's presence is what marks the unit as lived in: creating the first
resident against a unit whose `occupancy_status` is `VACANT` and which has no
other non-`REVOKED` resident moves that unit to `OCCUPIED`, recomputes its
`hvac_mode` to `OCCUPIED` and its `target_setpoint_c` to 22.0 Celsius — the
occupied setpoint — and clears `unauthorized_entry_detected` to false.

A resident becomes an active tenant through onboarding by a `PropertyManager`.
A resident whose status is neither `PENDING_CREDENTIAL` nor `DEACTIVATING` is
refused with `ERR_INVALID_STATE` (409). Onboarding a `PENDING_CREDENTIAL`
resident additionally requires three things: the resident's unit is in
`OCCUPIED` or `NOTICE`; at least one `SMART_LOCK` device assigned to that unit is
`ONLINE`; and the unit's building passes connectivity. When any of those fails,
the request is refused with `ERR_INSUFFICIENT_CONNECTIVITY` (409). On success the platform
issues a resident credential — an `AccessCredential` whose `credential_type` is
`RESIDENT`, carrying `subject_resident_id` equal to the resident's `id`, created
directly in `ACTIVE` status — and recomputes `portal_credential_status` to
`ACTIVE`.

Every change of a resident's status leaves an audit record. A
`ResidentStatusEvent` is appended carrying the `resident_id` it describes, the
`from_status` it left and the `to_status` it entered, and the instant it happened
as `recorded_at`. Onboarding appends a `PENDING_CREDENTIAL` to `ACTIVE` event.

The same onboarding action also declares a move-out-cancellation branch for a
resident who is `DEACTIVATING` while their unit is in `NOTICE`: when reached, the
platform re-issues a resident credential and appends a `DEACTIVATING` to
`ACTIVE` event. That branch is not reachable in practice: deactivation bubbles
the resident from `DEACTIVATING` to `REVOKED` in the same operation, consulting
credential liveness alone (§3.5), so a stored resident is never observed in
`DEACTIVATING` and the status gate of the preceding paragraph refuses the
request. The cycle `ACTIVE` to `DEACTIVATING` and back to `ACTIVE` is declared
but cannot occur. Re-issuing while the resident is `DEACTIVATING` also
revives a previously `REVOKED` resident credential: a credential of type
`RESIDENT` whose parent resident is `DEACTIVATING` and whose `valid_until` is
still in the future returns to `ACTIVE` rather than being duplicated; when no
previously `REVOKED` resident credential satisfies that condition, the platform
mints a new resident credential instead. If the resident is also being onboarded
from `DEACTIVATING`, the platform supersedes any
still-`ACTIVE` resident credential by moving it to `REVOKED` and recomputing
`portal_credential_status`.

### 3.5. Move-Out: Notice, Revocation and the Termination of a Tenancy

Move-out begins when a `PropertyManager` deactivates a resident who is currently
`ACTIVE`. The request carries `notice_end_at`, the instant the tenancy is
declared to end. Deactivation is a single operation with a wide blast radius, and
every part of it happens together.

The resident moves from `ACTIVE` to `DEACTIVATING`, and a `ResidentStatusEvent`
records the hop. The resident's unit leaves occupancy, moving from `OCCUPIED` to
`NOTICE`. Every credential belonging to the resident that is still live — that
is, every `AccessCredential` in the resident's scope whose status is `ISSUED` or
`ACTIVE` — is moved to `REVOKED`, and the resident's
`portal_credential_status` is recomputed. Because the host no longer holds the
unit, the move-out also sweeps the door open for visitors: every `GuestPass`
whose `host_resident_id` equals the departing resident's `id` and whose status is
still `ACTIVE` is moved to `REVOKED`, and the `GUEST` credential that pass
created is withdrawn with it, so no live guest credential outlives its pass.

The resident does not reach its terminal state in the deactivation response: it
first passes through `DEACTIVATING`, and the response reports it there. The
bubble-up is a consequence of the cascade, not a separate operation, and it
consults no clock reading: while any credential in the resident's scope remains
in `ISSUED` or `ACTIVE` the resident stays `DEACTIVATING`, and once none does it
moves to `REVOKED` — its only terminal state — and appends a `DEACTIVATING` to
`REVOKED` event, and `portal_credential_status` settles at `REVOKED`. Because
deactivation revokes the live credentials in the same operation, the condition
is generally satisfied in the same breath, so the terminal hop lands in storage
as the deactivation completes — a subsequent read observes `REVOKED` — while
the response reports the resident as it stood before that hop, in
`DEACTIVATING`. Any credential that is somehow still live holds the resident in
`DEACTIVATING`.

The unit's own occupancy reaches its end by time rather than by request. When the
logical clock reaches the unit's declared notice end, a unit in `NOTICE` moves to
`NOTICE_ENDED`, the platform moves `hvac_mode` to `VACANT_AUTO`, and the resident
attached to the unit is bubbled to `REVOKED` once its credential scope holds
nothing live. The final hop back to `VACANT` is taken by the vacant automation of
§3.3.

### 3.6. Guest Passes, Tours and the Boundaries of a Credential

A guest pass is a bounded permission for someone other than the resident to
enter a unit. A `PropertyManager` or a `Resident` issues one against a unit by
supplying the `host_resident_id`, a free-text `guest_label`, and the entry window
as `start_at` and `end_at`. The pass is born `ACTIVE`, and issuing it also
creates a `GUEST`-type `AccessCredential` for the unit. The host must not be a
`REVOKED` resident — a request acting on a unit on behalf of a revoked resident
is refused with `ERR_RESIDENT_NOT_ACTIVE` (409) — and the requested window must
not collide with an existing occupation of the unit, which is refused with
`ERR_UNIT_SCHEDULE_CONFLICT` (409). The host must also be attached to the unit
the pass is issued against, must be `ACTIVE` or `DEACTIVATING` rather than
`PENDING_CREDENTIAL`, and the window must end after it starts; a request that
fails any of those is refused with `ERR_CREDENTIAL_OUT_OF_SCOPE` (409).

A pass ends in one of two ways. It expires on its own when the logical clock
reaches its `end_at`, moving from `ACTIVE` to `EXPIRED`; or it is revoked when
its host moves out, in which case a pass in `ACTIVE` whose `host_resident_id`
matches the departing resident is moved to `REVOKED`, as described in §3.5.
Revocation is terminal — a `REVOKED` pass cannot be extended, and an attempt
surfaces `ERR_ALREADY_TERMINAL` (409).

An expired pass can be revived. A `PropertyManager` or the resident host extends
a pass by supplying `new_end_at`, and the platform requires three things: the
pass is `EXPIRED`, the new end is later than the current logical clock, and the
hosting resident's status is `ACTIVE` or `DEACTIVATING`. A pass whose host is
revoked, or whose new window does not extend past the present, is refused with
`ERR_CREDENTIAL_OUT_OF_SCOPE` (409). On success the pass returns to `ACTIVE` and
its `end_at` becomes the supplied value.

Self-guided tours are the other bounded-permission pathway and they are stricter,
because the visitor is a stranger. A `PropertyManager` or `LeasingAgent` requests
a tour against a vacant unit by supplying a `prospect_name`, a
`prospect_id_document`, a `requested_start_at`, and optionally the
`duration_minutes`, which defaults to 60. The session is born `REQUESTED` with
`verify_attempts` at 0. The request is not gated on the unit's occupancy and is
not checked against the unit's existing occupations — a session may be requested
against an occupied unit or across an existing visit. The vacancy requirement is
enforced instead when the session is verified: a verification whose unit is not
`VACANT` is refused with `ERR_INVALID_STATE` (409). A `LeasingAgent` then verifies the prospect's identity by
supplying `identity_document_number`, and the verification window is short: it
stays open for 60 minutes measured from `requested_start_at`, and a verification
attempted after that window has elapsed is refused with
`ERR_IDENTITY_VERIFICATION_EXPIRED` (409). Verification is also confined to a
non-terminal session — the acceptable states are `REQUESTED`, `DENIED` and
`VERIFIED`; a session that is already `COMPLETED` is refused with
`ERR_ALREADY_TERMINAL` (409), and any other state is refused with
`ERR_INVALID_STATE` (409).

When the supplied document matches the session's `prospect_id_document`, the
session moves to `VERIFIED`. The platform then mints a `TOUR`-type
`AccessCredential` for the unit, `ACTIVE` on issue, valid from `requested_start_at`
until `requested_start_at` plus the session's `duration_minutes`; it stamps
`identity_verified_at` with the current logical clock; and it counts the attempt
by incrementing `verify_attempts`. The session reaches `ACTIVE` itself when the
logical clock arrives at the credential's start, and completes when the clock
reaches the credential's end with the tour concluded — at which point the session
moves to `COMPLETED`, its terminal state, and the tour credential moves to
`EXPIRED`.

When the document does not match, the session is denied rather than refused with
a business error: it moves to `DENIED` and `verify_attempts` is incremented. A
denied session can be retried by verifying it again, and that is the non-linear
shape in this state machine: a retry that matches moves the session straight from
`DENIED` to `VERIFIED`, and one that does not match leaves it `DENIED` with the
attempt counted — a denied session is never returned to `REQUESTED`. A retry is
permitted only while the session has made fewer than 3 attempts and the
verification window has not elapsed; each attempt increments the counter, so a
session that exhausts its attempts can no longer be retried. There is also a late-failure
branch: a session that has already been verified can be re-verified, and if the
document supplied on that re-verification does not match, the session falls back
from `VERIFIED` to `DENIED`, the tour credential is revoked, and `verify_attempts`
is incremented. A re-verification that matches changes nothing: the session stays
`VERIFIED`, no second tour credential is minted, and `verify_attempts` is not
incremented.

### 3.7. Maintenance Access, Notice and the Property Budget

Maintenance visits are how the platform admits an outsider to an occupied unit,
and the rules around them are the strictest in the API. A `PropertyManager` or
`MaintenanceTechnician` requests a visit against a unit by supplying the
`technician_id` who will attend, the planned `start_at` and `end_at`, and
optionally the `is_emergency` flag, which defaults to false. The visit is born
`REQUESTED`, its `planned_hours` is derived from the span between `start_at` and
`end_at`, and its `accrued_cost_cents` starts at 0. The requested window must not
overlap an existing occupation of the same unit.

Certification is the `PropertyManager`'s alone, and it is where the statutory
gates are applied. The operator supplies `notice_mailed_at`, the instant notice
was served, and the platform checks it against the visit's `start_at` under the
lead times of §2.6 — 48 hours for an ordinary visit, 24 hours for an emergency.
It also checks the start hour against the 08:00-to-20:00 half-open window. A
visit that fails the lead-time test is refused with
`ERR_NOTICE_REQUIREMENT_UNMET` (409) and one that fails the window test with
`ERR_OUTSIDE_NOTICE_WINDOW` (422); the lead-time test is evaluated first, so a
visit that is both late and outside hours reports the notice failure. On success
the visit moves to `NOTICE_CERTIFIED` and the platform records a provisional
accrual for it.

The accrual is where the property's energy budget is spent. A visit's
`accrued_cost_cents` is computed from a base of 2000 cents, plus an emergency
surcharge of 1500 cents when the visit is an emergency, plus 700 cents for each
hour of work where the hours are the visit's `planned_hours` rounded up to a
whole number. On certification the provisional figure uses the planned hours; on
completion the figure is replaced by one that uses the hours actually spent, so
the provisional number is superseded rather than added to. The property's
`budget_committed_cents` — the sum of `accrued_cost_cents` across visits in
`NOTICE_CERTIFIED` or `COMPLETED` plus the reservations held by installation jobs
— is recomputed after certification, after completion, and after cancellation,
and each of those steps can be refused with `ERR_BUDGET_EXCEEDED` (409) if the
total would breach the property's daily allowance. Cancelling a visit does not
merely drop out of the sum: the visit's own `accrued_cost_cents` is reset to 0,
so a cancelled visit contributes nothing and leaves no residual accrual behind.

A certified visit ends in one of two ways, both reached from `NOTICE_CERTIFIED`.
A `PropertyManager` or `MaintenanceTechnician` completes it by supplying
`actual_hours`, and completion requires that the actual hours be greater than
zero; the visit moves to `COMPLETED`, its accrual is restated with the actual
hours, and the property budget is recomputed one final time. Cancellation is
reserved to the `PropertyManager`: once a visit is `NOTICE_CERTIFIED`, a
cancellation request from any other role is refused with `ERR_FORBIDDEN` (403).
A `PropertyManager`
may instead cancel the visit before any work happens by supplying the cancellation
flag as `cancelled`; the visit moves to `CANCELLED` — a terminal state — and its
accrual resets to 0. Completion or cancellation of a visit that is not in
`NOTICE_CERTIFIED` is refused with `ERR_INVALID_STATE` (409); an attempt to act
on a visit that is already terminal — `CANCELLED` or `COMPLETED` — surfaces
`ERR_ALREADY_TERMINAL` (409); and a completion whose `actual_hours` is missing or
not greater than zero is refused with `ERR_INVALID_REQUEST` (400).

### 3.8. Installations, Hub Placement and Labor Accounting

An installation job is the last workflow, and it sits at the intersection of the
radio rules and the money rules. A `PropertyManager` or `HardwareTechnician`
creates one against a building by supplying the `device_type` to install, an
optional `unit_id` when the install targets a specific unit, the
`access_window_start` and `access_window_end` that the technician may work
within, an optional `requires_resident_coordination` flag defaulting to false,
and a mandatory `expected_building_version`. The job is born `SCHEDULED`, and
creating it holds a reservation of 2000 cents against the owning property's
`budget_committed_cents`. Creation also advances the building: the building's
`version` is incremented by exactly one, which is precisely the mutation that any
other client's later job creation will be measured against under §2.9. A request
whose `expected_building_version` no longer matches the building's current
`version` is refused with `ERR_STALE_VERSION` (412), and a request whose
reservation would breach the property's allowance is refused with
`ERR_BUDGET_EXCEEDED` (409); the budget check is evaluated first.

Starting a job accepts an optional `scheduled_start_at` — the instant the install
is planned to begin — which defaults to the job's `access_window_start`.

The install may not assume the tenant is out. When
`requires_resident_coordination` is true, starting the job requires the target
unit to be `OCCUPIED` and requires a `MaintenanceVisit` on that unit in
`NOTICE_CERTIFIED` status whose window covers the job's `scheduled_start_at` —
in other words, the resident has been given notice and the visit that carries
that notice is the visit the technician is arriving under. A hub installation
carries an additional precondition of its own, evaluated when the job is created
rather than when it is started: creating a `HUB` job requires the target building
to already pass its connectivity check, and a building that does not is refused
with `ERR_NO_HUB_CONNECTIVITY` (409). Finally, starting a job
requires that no maintenance visit and no tour session on that unit overlaps the
install interval — the interval beginning at `scheduled_start_at` and running for
120 minutes, the estimated install duration — and that a 30-minute buffer around
that span also be clear. Any collision is refused with
`ERR_UNIT_SCHEDULE_CONFLICT` (409).

Starting a job moves it to `IN_PROGRESS` and provisions hardware: the platform
creates a `Device` of the job's `device_type` for the target unit or building,
in `PROVISIONED` status, and the property's budget is recomputed. The
synthesized device carries `firmware_version` `LATEST`, `battery_pct` 100 and
`lock_state` `LOCKED`, and it starts with no battery replacements. Completion is
where the radio verdict finally decides the outcome, and it has two branches with
very different consequences. If the building passes connectivity, the job moves
to `COMPLETED`, the synthesized device is brought `ONLINE`, the job's
`labor_hours` is computed, and the property budget is recomputed. If the building
fails the connectivity check, the job moves to `ABORTED` — also a terminal state
— the synthesized device is moved to `DECOMMISSIONED`, the property budget is
recomputed, and no device is added to the unit's live set. The abort exists
because a device installed against a link the hub cannot hold is worse than an
uninstalled device, and the record must say the install was attempted and
rejected. A completion attempted against a job that is not `IN_PROGRESS` is
refused with `ERR_INVALID_STATE` (409).

Labor is priced by device class with a rework surcharge, and the evaluation order
is pinned. The base hours depend on the device: 0.5 for a `SMART_LOCK`, 0.4 for a
`THERMOSTAT`, 0.25 for a `LEAK_SENSOR`, 0.75 for `COMMUNITY_ACCESS`, and 1.0 for
a `HUB`. A base below 1.0 puts the job in the simple tier; a base at or above
1.0 puts it in the standard tier. A simple-tier job carries no rework surcharge;
a standard-tier job carries a rework surcharge of one quarter of the base. The
job's `labor_hours` is the base plus the rework, rounded half-up to two decimal
places.

### 3.9. Alerts, Work Orders and the Repair Loop

Hardware failures surface as `DeviceAlert` rows, and each alert is typed and
graded. The `alert_type` is `OFFLINE`, `LOW_BATTERY` or `UNAUTHORIZED_ENTRY`,
and the `severity` follows from the type rather than being chosen: `OFFLINE` and
`UNAUTHORIZED_ENTRY` alerts are `HIGH`, and `LOW_BATTERY` alerts are `MEDIUM`.
Alerts are born `OPEN`, and they carry both the `building_id` they were raised in
and the `device_id` they concern.

Repair is tracked by a `WorkOrder`, which is opened against an alert. A
`PropertyManager` or `HardwareTechnician` opens one by supplying the
`assigned_technician_id` of the technician taking the job — optional at creation
— and the mandatory `expected_device_alert_version`. An alert whose `version` has
advanced since the client last observed it is protected under §2.9: the request
is refused with `ERR_STALE_VERSION` (412), which prevents a work order from being
attached to an alert whose state the client has not seen. The work order is born
`OPEN` and its `battery_replaced` flag is false; opening it also advances the
alert's `version` by one.

A `HardwareTechnician` then progresses the order through assignment, supplying a
`technician_id`, an optional `replaced_battery` flag, and an optional
`confirm_repair` flag. The order is a three-step ladder: `OPEN` becomes
`ASSIGNED`, and `ASSIGNED` becomes `CLOSED`, which is terminal. Assignment of an
order that is already `CLOSED` is refused with `ERR_ALREADY_TERMINAL` (409), and
an order in any other state is refused with `ERR_INVALID_STATE` (409). Moving an
order from `OPEN` to `ASSIGNED` requires a non-null technician and, in the same
transaction, acknowledges the parent alert — the alert moves from `OPEN` to
`ACKNOWLEDGED`. The second hop is confirmed rather than automatic: a call
against an `ASSIGNED` order records the supplied `technician_id` and
`replaced_battery` flag but leaves the order in `ASSIGNED` unless the caller
also sets `confirm_repair` to true. When `confirm_repair` is true, moving an
order from `ASSIGNED` to `CLOSED` requires either that the target device is
`ONLINE` or that the battery was replaced — otherwise the request is refused
with `ERR_INVALID_STATE` (409) — and it resolves the parent alert, moving it
from `ACKNOWLEDGED` to `RESOLVED`; when the order records a battery replacement,
the target device's `battery_replacements` count is incremented by one.

Battery replacement also has a standalone pathway for `HardwareTechnician`, used
when a device is reachable but its battery is failing. The replacement requires
the device to be `ONLINE` — a device that is `UNREACHABLE` cannot be serviced and
the attempt is refused with `ERR_DEVICE_UNREACHABLE` (409). A successful
replacement restores `battery_pct` to 100, increments `battery_replacements` by
one, and resolves any `OPEN` `LOW_BATTERY` alert on the device. One special case
rides on this pathway: replacing the battery of a device whose
`firmware_version` is `CRITICAL` does not return the device to service. A device
whose firmware is `CRITICAL` moves from `ONLINE` to `DECOMMISSIONED`, which is
terminal — the platform refuses to keep fielding hardware that is known to be
running unsupported firmware.

Alerts are not one-way. A resolved alert can recur: when a device that was
reachable becomes absent from a scan again — or, more precisely, when an alert in
`RESOLVED` has its `device_id` absent from a scan's reachable set — the alert
returns to `OPEN`. And an alert of type `OFFLINE` or `LOW_BATTERY` whose device
answers a scan is resolved automatically by the scan itself, without any work
order being involved, and a `RESOLVED` alert on a device that has been
`DECOMMISSIONED` is not returned to `OPEN` by a later scan. `UNAUTHORIZED_ENTRY` alerts are never resolved by a scan;
they are the record of an intrusion event and are only closed through the work
order pathway.

### 3.10. The Logical Clock

Time in this API is logical, not physical, and it is authoritative for every
deadline, expiry and window in the document. A `PlatformAdmin` drives it with an
administrative capability that sets the clock to a supplied `current_utc`
instant. The clock is pinned at startup to `2026-09-01T00:00:00Z`, and before any
call it reads exactly that instant — it never falls back to wall-clock time, and
no deadline in this document may be evaluated against host time.

Advancing the clock is not a passive bookkeeping step; it is what propels several
time-driven transitions. When the clock moves, credentials whose `valid_until`
has arrived are expired, guest passes whose `end_at` has arrived are expired, and
units in `NOTICE` whose declared notice end has been reached advance to
`NOTICE_ENDED`. Tour sessions follow their issued credential: a `VERIFIED`
session becomes `ACTIVE` when the clock reaches the credential's `valid_from`,
and an `ACTIVE` session becomes `COMPLETED` when the clock reaches the
credential's `valid_until`. Installation jobs are swept as well: a job still in
`SCHEDULED` whose creation instant is at least 24 hours in the past is moved to
`ABORTED`, which releases the reservation it held against the property budget.
Because the clock is supplyable, every one of these
outcomes is deterministic rather than dependent on how long a test takes to run.

## 4. Endpoint Definitions

Operations that create a new, standalone resource, or that add a distinct
resource to a collection, return `201 Created`. Operations that modify an
existing resource return `200 OK`. The table below lists each operation with the
roles permitted to call it; it deliberately omits request bodies, response bodies
and side effects, which are specified in §2 and §3. Roles are to be read as the
exact strings defined in §2.1.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/properties` | Create a property | `PlatformAdmin` |
| GET | `/properties/{propertyId}` | Get a property | `PlatformAdmin`, `PropertyManager` |
| POST | `/properties/{propertyId}/buildings` | Create a building within a property | `PlatformAdmin` |
| GET | `/buildings` | List buildings, optionally filtered by property | `PlatformAdmin`, `PropertyManager`, `HardwareTechnician` |
| POST | `/properties/{propertyId}/units` | Create a unit within a property | `PlatformAdmin`, `PropertyManager` |
| GET | `/units` | List units, optionally filtered | `PlatformAdmin`, `PropertyManager`, `HardwareTechnician`, `LeasingAgent` |
| GET | `/units/{unitId}` | Get a unit | `PlatformAdmin`, `PropertyManager`, `HardwareTechnician`, `LeasingAgent` |
| POST | `/devices` | Provision a device | `PlatformAdmin`, `HardwareTechnician` |
| GET | `/devices` | List devices, optionally filtered | `PlatformAdmin`, `PropertyManager`, `HardwareTechnician` |
| POST | `/devices/{deviceId}/replace_battery` | Replace a device battery | `HardwareTechnician` |
| POST | `/devices/{deviceId}/lock-events` | Record a lock open/close event | `HardwareTechnician`, `PropertyManager` |
| POST | `/buildings/{buildingId}/device-scans` | Run a reachability scan over a building's devices | `PlatformAdmin`, `HardwareTechnician` |
| POST | `/residents` | Create a resident | `PlatformAdmin`, `PropertyManager` |
| GET | `/residents` | List residents, optionally filtered | `PlatformAdmin`, `PropertyManager` |
| POST | `/residents/{residentId}/onboard` | Onboard a resident and issue app credentials | `PropertyManager` |
| POST | `/residents/{residentId}/deactivate` | Deactivate a resident and revoke credentials | `PropertyManager` |
| GET | `/resident-status-events` | List resident status events, optionally filtered | `PlatformAdmin`, `PropertyManager` |
| GET | `/access-credentials` | List access credentials, optionally filtered | `PlatformAdmin`, `PropertyManager` |
| POST | `/units/{unitId}/guest-passes` | Issue a guest pass for a unit | `PropertyManager`, `Resident` |
| POST | `/guest-passes/{guestPassId}/extend` | Extend an expired guest pass | `PropertyManager`, `Resident` |
| GET | `/guest-passes` | List guest passes, optionally filtered | `PlatformAdmin`, `PropertyManager`, `Resident` |
| POST | `/units/{unitId}/tour-sessions` | Request a self-guided tour of a vacant unit | `PropertyManager`, `LeasingAgent` |
| POST | `/tour-sessions/{tourSessionId}/verify` | Verify prospect identity and issue a tour credential | `LeasingAgent` |
| GET | `/tour-sessions` | List tour sessions, optionally filtered | `PropertyManager`, `LeasingAgent` |
| POST | `/units/{unitId}/maintenance-visits` | Request a maintenance visit | `PropertyManager`, `MaintenanceTechnician` |
| POST | `/maintenance-visits/{maintenanceVisitId}/certify_notice` | Certify that legal notice was served | `PropertyManager` |
| POST | `/maintenance-visits/{maintenanceVisitId}/complete` | Complete or cancel a certified maintenance visit | `PropertyManager`, `MaintenanceTechnician` |
| GET | `/maintenance-visits` | List maintenance visits, optionally filtered | `PropertyManager`, `MaintenanceTechnician` |
| POST | `/buildings/{buildingId}/installation-jobs` | Create an installation job for a device | `PropertyManager`, `HardwareTechnician` |
| POST | `/installation-jobs/{installationJobId}/schedule` | Start a scheduled installation job | `HardwareTechnician` |
| POST | `/installation-jobs/{installationJobId}/complete` | Complete an in-progress installation job | `HardwareTechnician` |
| GET | `/installation-jobs` | List installation jobs, optionally filtered | `PropertyManager`, `HardwareTechnician` |
| GET | `/device-alerts` | List device alerts, optionally filtered | `PlatformAdmin`, `PropertyManager`, `HardwareTechnician` |
| POST | `/device-alerts/{deviceAlertId}/work-orders` | Open a work order against an alert | `PropertyManager`, `HardwareTechnician` |
| POST | `/work-orders/{workOrderId}/assign` | Assign a technician and progress the work order | `HardwareTechnician` |
| GET | `/work-orders` | List work orders, optionally filtered | `PropertyManager`, `HardwareTechnician` |
| POST | `/units/{unitId}/vacant-automation` | Run vacant-unit automation for a unit | `PropertyManager` |
| POST | `/_clock/set_current_utc` | Set the logical clock | `PlatformAdmin` |

## 5. Error Code Catalogue

The table below lists every error identifier this API can return and the HTTP
status that accompanies it. The conditions that trigger each error are specified
in §2 and §3, next to the rule that guards the operation.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_PROPERTY_NOT_FOUND` | 404 |
| `ERR_BUILDING_NOT_FOUND` | 404 |
| `ERR_UNIT_NOT_FOUND` | 404 |
| `ERR_DEVICE_NOT_FOUND` | 404 |
| `ERR_RESIDENT_NOT_FOUND` | 404 |
| `ERR_GUEST_PASS_NOT_FOUND` | 404 |
| `ERR_TOUR_SESSION_NOT_FOUND` | 404 |
| `ERR_MAINTENANCE_VISIT_NOT_FOUND` | 404 |
| `ERR_INSTALLATION_JOB_NOT_FOUND` | 404 |
| `ERR_DEVICE_ALERT_NOT_FOUND` | 404 |
| `ERR_WORK_ORDER_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ALREADY_TERMINAL` | 409 |
| `ERR_DEVICE_UNREACHABLE` | 409 |
| `ERR_INSUFFICIENT_CONNECTIVITY` | 409 |
| `ERR_NO_HUB_CONNECTIVITY` | 409 |
| `ERR_UNIT_SCHEDULE_CONFLICT` | 409 |
| `ERR_NOTICE_REQUIREMENT_UNMET` | 409 |
| `ERR_OUTSIDE_NOTICE_WINDOW` | 422 |
| `ERR_IDENTITY_VERIFICATION_EXPIRED` | 409 |
| `ERR_SETPOINT_OUT_OF_RANGE` | 422 |
| `ERR_CREDENTIAL_OUT_OF_SCOPE` | 409 |
| `ERR_RESIDENT_NOT_ACTIVE` | 409 |
| `ERR_BUDGET_EXCEEDED` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_DUPLICATE_UNIT_NUMBER` | 409 |