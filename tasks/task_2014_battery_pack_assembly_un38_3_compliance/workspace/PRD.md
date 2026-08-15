# Battery Pack Assembly & UN38.3 Compliance API — Product Requirements Document

## 1. Introduction

A contract battery pack integrator operates at the intersection of manufacturing execution and dangerous-goods regulation. Cells arrive from vendors in lots whose declared state of charge must be independently verified; packs are welded together under tightly bounded thermal budgets; the battery management firmware flashed onto each pack must be reviewed, approved, and traceable; and no pack may leave the building until its UN38.3 safety dossier has been compiled, scored, and approved. On top of the assembly line sit warehouse fire-code segregation rules keyed to state of charge, carrier tendering with dangerous-goods surcharges, customer returns that require verified safe discharge, and recall campaigns that must trace affected packs by lot, bill of materials, or serial range.

This document specifies the API that backs those operations. It is written for the engineers who will implement the service: every workflow, state transition, calculation, and rejection rule described here is normative. All business resources are mounted under `/api`; a small administrative capability for driving the server's logical clock lives outside that prefix and is described in §2.13. Six operator roles share the system under strict segregation-of-duties rules, and every mutating workflow is gated on the owning program's posture, so that a suspended program freezes its assembly floor without erasing its audit trail.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two authentication headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, declaring the capacity in which they act. A request in which either header is missing or malformed is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. The system recognizes seven role designations: `AssemblyLead`, `QualityEngineer`, `SafetyOfficer`, `LogisticsCoordinator`, `CarrierAgent`, `CustomerService`, and `Any` (the shared read-only designation under which all authenticated roles may call read endpoints). An authenticated operator who attempts an operation reserved for a different role is rejected with `ERR_INSUFFICIENT_PERMISSIONS`.

For every role, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server never compares it against any resource's `id`. It is, however, recorded on the artifacts each role produces, and segregation-of-duties checks (§2.11) compare it against those recordings. Concretely: when `X-User-Role` is `AssemblyLead`, the identifier is recorded as `operator_id` on each `WeldingParameterRecord` and as `flashed_by_id` on each `BMSFlashRecord`, and the firmware submission act binds it as the submitter for later approval checks. When `X-User-Role` is `QualityEngineer`, it is recorded as `inspector_id` on each `CellInspectionRecord` and as `certified_by_id` on each certified `WeldingParameterRecord`. When `X-User-Role` is `SafetyOfficer`, it is recorded as `approver_id` on each `FirmwareApproval` and as `approved_by_id` on each approved `ReturnAuthorization`. When `X-User-Role` is `CustomerService`, it is recorded as `requested_by_id` on each `ReturnAuthorization`. When `X-User-Role` is `LogisticsCoordinator` or `CarrierAgent`, the identifier authorizes the operation but is not persisted onto any entity field. When `X-User-Role` is `Any`, the identifier simply authenticates a read.

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

List endpoints paginate through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, accepts a minimum of 1, and is capped at a maximum of 100. The `offset` parameter skips a number of items from the front of the result set and defaults to 0. Every list response is sorted by creation timestamp (`created_at`) in ascending order unless explicitly stated otherwise, and every list response carries `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties & Immutable Event Records

Every primary resource in the system carries a standard set of system-managed fields: `id`, a server-minted UUID with no type prefix; `created_at`, an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created; `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation; and `version`, an integer starting at 1 that increments by one on every mutation of that resource. Any mutation of a resource — including server-side updates to its computed fields — refreshes its `updated_at` and increments its `version`.

Five entity types are immutable event records and deliberately break this pattern: `CellInspectionRecord`, `WeldingParameterRecord`, `FirmwareApproval`, `BMSFlashRecord`, and `ShipmentPackLink`. Each of these carries only `id` and `created_at`; both `updated_at` and `version` are absent, because the record is never modified after it is persisted. Attempts to change history are expressed by recording new events (a re-inspection, a re-flash, a new dossier cycle), never by editing old ones.

### 2.5. Hierarchical Addressing, Cross-Program Integrity & Nested Retrieval

Every resource in the system ultimately belongs to an `IntegrationProgram`, and the URL hierarchy reflects that ownership. Nested endpoints are validated strictly left to right: the server resolves the program first, then the resource named at the next segment, and so on, rejecting immediately with the `404` error of the first path segment that does not resolve — `ERR_PROGRAM_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_BOM_NOT_FOUND`, `ERR_PACK_NOT_FOUND`, `ERR_WELD_RECORD_NOT_FOUND`, `ERR_FIRMWARE_NOT_FOUND`, `ERR_DOSSIER_NOT_FOUND`, `ERR_LOCATION_NOT_FOUND`, `ERR_PLACEMENT_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, `ERR_RMA_NOT_FOUND`, or `ERR_RECALL_NOT_FOUND` as appropriate. The path variables appearing across the API are `{programId}`, `{lotId}`, `{bomId}`, `{packId}`, `{recordId}`, `{fwId}`, `{dossierId}`, `{locationId}`, `{placementId}`, `{shipmentId}`, `{rmaId}`, and `{recallId}` on nested routes, plus `{recId}`, `{approvalId}`, and `{linkId}` on the flat retrieval routes described below.

Referential integrity is program-scoped. Whenever a child-creating call references another resource — a lot, a BOM, a firmware row, a storage location, a shipment — that referenced resource must belong to the same program as the path's `{programId}`; otherwise the call is rejected with `ERR_CROSS_PROGRAM_REFERENCE`. Each entity also stores its program lineage explicitly: child resources carry a denormalized `program_id`, so a `CellInspectionRecord`, `WeldingParameterRecord`, `FirmwareApproval`, `BMSFlashRecord`, `SafetyTestDossier`, `StoragePlacement`, or `ShipmentPackLink` always names the program it belongs to alongside its direct parent's foreign key.

In addition to the nested routes, every child entity is reachable through a flat single-get route and a flat filtered-list route, so that any foreign key declared on an entity can be traversed in reverse. The flat list routes accept the standard pagination parameters plus optional equality filters mirroring the entity's foreign keys: `program_id`, `cell_lot_id`, `bom_id`, `bms_firmware_id`, `dossier_id`, `storage_location_id`, `active_recall_id`, `approval_record_id`, `battery_pack_id`, `transport_shipment_id`, `scope_lot_id`, and `scope_bom_id` are each accepted where the underlying entity carries such a field.

### 2.6. Program Posture Gating

An `IntegrationProgram` moves through `OPEN`, `SUSPENDED`, and `CLOSED`, and its posture gates everything beneath it. Any call that creates or mutates a child resource under a program requires that program to be `OPEN`; when it is not, the call is rejected with `ERR_PROGRAM_NOT_OPEN`. Suspension is the stronger operational freeze: while a program is `SUSPENDED`, all non-terminal `CellLot` transitions, all non-terminal `BatteryPack` assembly-axis transitions, and the placement transition from `STAGED` to `STORED` are blocked, even where those transitions would otherwise be legal. `CLOSED` is terminal; nothing under a closed program may change.

### 2.7. Compliance Risk Index

Each program carries a `compliance_risk_index`, an aggregate posture score that starts at 100 when the program is created and only ever moves downward — a lower index signals a worse compliance position. Three events decrement it. A lot rejected by a hard-failed inspection reduces the index by 3, never driving it below a floor of 0. A dossier whose final score falls short of the passing threshold reduces the index by 5. And recall activation reduces the index by the campaign's severity weight multiplied by the number of packs captured, where the severity weights are 15 for `CLASS_I`, 8 for `CLASS_II`, and 3 for `CLASS_III` — equivalently, each captured pack's forced transition to `RECALLED` deducts the severity weight exactly once. The index is read-only and recomputed by the server as these events occur.

### 2.8. Watt-Hour Capacity & Fire-Zone Accounting

Two parallel ledgers track stored energy. At the program level, `storage_capacity_wh` declares the total watt-hours permitted across all of the program's storage slots, `wh_committed` reports the watt-hours currently committed by packs whose logistics status is `STAGED` or `STORED`, and `wh_available` is the difference between the two. At the slot level, each `StorageLocation` declares a `capacity_wh` it may hold, reports `wh_occupied` as the summed `pack_energy_wh` of packs currently staged or stored there, and derives `wh_headroom` as its capacity minus its occupancy. Staging a pack increases both `wh_occupied` on the slot and `wh_committed` on the program by the pack's energy; picking, releasing, or recall force-release decreases both by the same amount. These derived figures are read-only and move only as placement events occur.

### 2.9. Units, Precision & Rounding

Physical quantities obey fixed precision conventions so that clients and server never diverge on representation. State-of-charge percentages (`receiving_soc_percent`, `measured_soc_percent`, `soc_percent`, `target_soc_percent`, `actual_soc_after_discharge`) carry one decimal place. Voltages such as `measured_voltage_v` and the declared weight `declared_weight_kg` carry two decimal places. Computed energy and heat values — `nominal_energy_wh`, `pack_energy_wh`, `heat_dose_j`, `welding_heat_dose_j` — and the dossier scores `provisional_un_score` and `final_un_score` are rounded half-up to exactly two decimal places, with rounding applied as the final step of each calculation. The carrier charge `carrier_charge_cents` is a whole number of cents, rounded half-up from the computed dollar amount. Weld current `current_amps` and electrode force `electrode_force_n` are accepted at one decimal place, and `pulse_ms` is an integer count of milliseconds.

### 2.10. Optimistic Concurrency Control

Two write endpoints enforce optimistic concurrency control, and only those two carry a version field in their request body; no other endpoint accepts one.

Assembling a pack requires the request to carry `expected_bom_version`, the `version` of the `PackBOM` as the client last observed it. If the BOM's current `version` does not match — for example because another pack assembly has consumed the BOM in the meantime and advanced it — the creation is rejected with `ERR_STALE_VERSION` (HTTP 412). Recording the eight-field test matrix onto a safety dossier likewise requires `expected_pack_version`, the `version` of the parent `BatteryPack` as the client last observed it; a mismatch with the pack's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412), which prevents a client from persisting a test matrix against a pack state it has not observed — for instance after a safe-discharge event has moved the pack's state of charge.

### 2.11. Segregation of Duties

Three hand-offs in the system are forbidden to a single operator, each enforced as a `403` rejection. The `QualityEngineer` certifying a weld must not be the `AssemblyLead` who recorded it: if the certifier's `X-User-ID` equals the record's `operator_id`, certification is rejected with `ERR_SOD_WELD_CERTIFY`. The `SafetyOfficer` approving a firmware must not be the `AssemblyLead` who submitted it for review: a matching identifier is rejected with `ERR_SOD_FIRMWARE_APPROVE`. And the `SafetyOfficer` approving a return authorization must not be the `CustomerService` operator recorded as its `requested_by_id`: a match is rejected with `ERR_SOD_RMA_APPROVE`.

### 2.12. Validation Precedence

When several checks could reject the same request, the server evaluates them in a fixed global order so that the error a client receives is deterministic. Before business validation begins, malformed payloads, missing required fields, and type mismatches are rejected with `ERR_INVALID_REQUEST`, and an enum field carrying a value outside its declared set is rejected with `ERR_INVALID_ENUM`. The ordered cascade then runs as follows:

1. Header presence and well-formedness (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. Role permission for the attempted operation (`ERR_INSUFFICIENT_PERMISSIONS`).
3. Path-parameter existence, resolved left to right (the `404` family of §2.5).
4. Program posture — the program must be `OPEN` for any child-creating or child-mutating call (`ERR_PROGRAM_NOT_OPEN`).
5. Resource state preconditions for the attempted transition (the `ERR_{RESOURCE}_NOT_{EXPECTED_STATE}` family, e.g. `ERR_PACK_NOT_BUILT`, `ERR_DOSSIER_NOT_OPEN`, `ERR_SHIPMENT_NOT_DRAFT`).
6. Segregation of duties (`ERR_SOD_WELD_CERTIFY`, `ERR_SOD_FIRMWARE_APPROVE`, `ERR_SOD_RMA_APPROVE`).
7. Storage SOC-band acceptance (`ERR_SOC_BAND_NOT_ACCEPTED`).
8. Receiving-inspection SOC tolerance (`ERR_SOC_OUT_OF_TOLERANCE`).
9. Weld profile match and heat-dose ceiling (`ERR_WELD_PROFILE_MISMATCH`, `ERR_HEAT_DOSE_EXCEEDED`).
10. Dossier test-matrix completeness (`ERR_INCOMPLETE_TEST_MATRIX`).
11. Return target-SOC ceiling (`ERR_TARGET_SOC_TOO_HIGH`).
12. Cross-program referential integrity (`ERR_CROSS_PROGRAM_REFERENCE`).
13. Lot acceptance and lot capacity for a new BOM (`ERR_LOT_NOT_ACCEPTED`, `ERR_LOT_DEPLETED`).
14. Firmware approval state for flashing (`ERR_FIRMWARE_NOT_APPROVED`).
15. Pack not already attached to a non-terminal shipment (`ERR_PACK_ALREADY_ATTACHED`).
16. Storage-slot capacity (`ERR_LOCATION_CAPACITY_EXCEEDED`).
17. Program watt-hour capacity (`ERR_PROGRAM_CAPACITY_EXCEEDED`).
18. Shipment UN-class agreement (`ERR_UN_CLASS_MISMATCH`).
19. Lot retest bound (`ERR_RETEST_LIMIT_EXCEEDED`).
20. Recall capture blocks on pick and release (`ERR_PACK_UNDER_RECALL`).
21. Shipment non-emptiness at tender (`ERR_SHIPMENT_EMPTY`).
22. Optimistic-concurrency version match (`ERR_STALE_VERSION`).

### 2.13. Logical Clock for Test Driving

For deterministic testing of time-gated behavior, the server maintains a logical clock initialized at startup to 2026-08-01T00:00:00Z. A `SafetyOfficer`-only administrative capability sets the clock to a supplied instant: the request carries `to_iso8601`, and the response carries the resulting `current_utc`. This capability is mounted outside the `/api` business namespace and has no effect on business state beyond the timestamps the server subsequently mints.

## 3. Business Logic & Workflows

### 3.1. Program Setup & Lifecycle

Everything begins when a `SafetyOfficer` opens an integration program by supplying a unique `program_code` (for example, PRG-2014-A) and the program's `storage_capacity_wh`. A newly created program starts with `status` equal to `OPEN`, a `compliance_risk_index` of 100, `wh_committed` at 0, `recall_count` at 0, and `version` at 1.

Suspension is a deliberate freeze. A `SafetyOfficer` may suspend a program that is `OPEN` — attempting it in any other state is rejected with `ERR_PROGRAM_NOT_OPEN` — moving its `status` to `SUSPENDED` and engaging the gating described in §2.6: lot transitions, pack assembly transitions, and placement stores all halt while the freeze holds. Resuming requires the program to be `SUSPENDED` (otherwise `ERR_PROGRAM_NOT_SUSPENDED`) and returns `status` to `OPEN`; as part of resuming, the server re-evaluates every pack's `active_recall_id`, dropping links to recalls that are no longer `ACTIVE` so that stale capture markers never outlive the campaign that set them.

Closing a program is allowed only from `OPEN` and only when the program's book is clean. The close is rejected with `ERR_UNRESOLVED_PACKS_REMAIN` if any pack exists whose assembly axis has not reached `RECALLED` and whose logistics axis has not reached `DELIVERED` or `RETURNED` — in other words, every pack must either be recall-terminated or have completed its outbound journey. It is rejected with `ERR_OPEN_SHIPMENTS_REMAIN` if any shipment still sits in `TENDERED`, `CARRIER_ACCEPTED`, or `IN_TRANSIT`, and with `ERR_ACTIVE_RECALL_EXISTS` if any recall campaign remains `ACTIVE`. When all three guards pass, the program's `status` becomes `CLOSED`, which is terminal.

### 3.2. Cell Lot Receiving, Quarantine & Inspection

A `QualityEngineer` receives a cell lot into a program by declaring its `lot_code` (unique within the program), the `cell_count` of cells in the lot (which must be greater than zero), the per-cell `rated_capacity_mah`, and the `receiving_soc_percent` declared at the dock — a value between 0 and 100 inclusive, recorded to one decimal place. The lot is born in `RECEIVED` status with `quarantine_cycle_count` at 0 and `measured_soc_percent` still null, because no accepted measurement exists yet.

From `RECEIVED`, the lot is moved to `QUARANTINE` for inspection; the move requires the lot to be `RECEIVED` (otherwise `ERR_LOT_NOT_RECEIVED`) and the program to be `OPEN`. Quarantine is where the inspection loop runs. Each inspection records an immutable `CellInspectionRecord` carrying the inspector's `measured_soc_percent` (0 to 100, one decimal), `measured_voltage_v` (open-circuit voltage, two decimals), a `visual_defect_count` of zero or more, and an `outcome` of `PASS`, `FAIL_SOFT`, or `FAIL_HARD`; the server stamps the record with the recording engineer's identifier as `inspector_id` and denormalizes `cell_lot_id` and `program_id` onto it. Recording an inspection requires the lot to be in `QUARANTINE`, failing with `ERR_LOT_NOT_IN_QUARANTINE` otherwise.

The three outcomes diverge sharply. A `PASS` outcome accepts the lot — acceptance is only defined for a passing outcome, and a request that would accept on any other outcome is rejected with `ERR_INSPECTION_NOT_PASS` — but only when the measured state of charge corroborates the paperwork: `measured_soc_percent` must lie within 2.0 percentage points of the lot's declared `receiving_soc_percent` in either direction, or the acceptance is rejected with `ERR_SOC_OUT_OF_TOLERANCE`. On acceptance the lot's status becomes `ACCEPTED`, the measured value is persisted onto the lot as its `measured_soc_percent`, and the first acceptance leaves `quarantine_cycle_count` untouched. A `FAIL_HARD` outcome rejects the lot outright: its status becomes `REJECTED` and the program's `compliance_risk_index` drops by 3, floored at 0. A `FAIL_SOFT` outcome is inconclusive — the lot remains in `QUARANTINE` via a self-loop and its `quarantine_cycle_count` increments by 1.

Rejection is not quite the end. A `QualityEngineer` may send a `REJECTED` lot back into `QUARANTINE` for a retest, but only while `quarantine_cycle_count` remains below 2; the transition requires the lot to be `REJECTED` (otherwise `ERR_LOT_NOT_REJECTED`), is refused with `ERR_RETEST_LIMIT_EXCEEDED` once the lot has already cycled through quarantine twice, and increments `quarantine_cycle_count` by 1 as it fires.

Consumption is tracked automatically. When the summed `cells_required` across all locked BOMs drawing on a lot reaches the lot's `cell_count`, the lot transitions from `ACCEPTED` to `DEPLETED` on its own; thereafter, any attempt to define a new BOM against the lot is rejected with `ERR_LOT_DEPLETED`.

### 3.3. BOM Definition & Pack Assembly

An `AssemblyLead` defines a pack bill of materials inside a program by supplying a `bom_code` unique within the program, the `cell_lot_id` of the lot the BOM draws cells from, the `cells_required` consumed per pack, the `series_count` and `parallel_count` of the pack's cell topology (each at least 1), a `welding_profile` of `WELD_PROFILE_A`, `WELD_PROFILE_B`, or `WELD_PROFILE_C` selecting the base heat dose for welding, and an optional `version_note`. The referenced lot must belong to the same program (otherwise `ERR_CROSS_PROGRAM_REFERENCE`), must be `ACCEPTED` (otherwise `ERR_LOT_NOT_ACCEPTED`), and must still have cells to spare: the cells already committed by locked BOMs plus the new BOM's `cells_required` must not exceed the lot's `cell_count`, or the definition is refused with `ERR_LOT_DEPLETED`. The BOM's `nominal_energy_wh` is computed at creation as the `cells_required` multiplied by the lot's `rated_capacity_mah`, multiplied by the nominal 3.6 volts per cell, and divided by 1000, rounded half-up to two decimal places. A BOM is born with `is_locked` false; the moment a pack consumes it, `is_locked` becomes true and its `welding_profile` and `cells_required` are immutable from then on.

Assembling a pack is the act that joins the BOM to the line. The `AssemblyLead` posts a payload naming the `bom_id` and the concurrency guard `expected_bom_version` (§2.10), and the server mints the pack in a single transaction. The new pack receives a `serial_number` in the form SN- followed by the program's `program_code`, a dash, and a zero-padded six-digit counter; its `cell_lot_id` is copied from the BOM's lot at assembly time; its `pack_energy_wh` is frozen to the BOM's `nominal_energy_wh`; and its `soc_percent` is initialized from the lot's `measured_soc_percent`. From that initial charge the server derives the pack's `soc_band` under the plain threshold variant (§3.7). The pack starts with `assembly_status` of `BUILT`, `logistics_status` of `NOT_STORED`, and `disposition` of `IN_SERVICE`; its `bms_firmware_id`, `dossier_id`, `storage_location_id`, and `active_recall_id` are all null, `is_safe_discharged` is false, and `shipping_classification` is `NONE`. Consuming the BOM flips its `is_locked` to true and increments the BOM's `version` by 1 — which is precisely why a stale `expected_bom_version` must be refused.

The pack then advances along the assembly axis — `BUILT` → `WELD_RECORDED` → `WELD_CERTIFIED` → `BMS_FLASHED` → `TEST_QUEUED` → `CLASSIFIED` → `READY_TO_STORE` — with the welding, firmware, and dossier gates described in §3.4 through §3.6. In parallel and independently, the logistics axis runs `NOT_STORED` → `STAGED` → `STORED` → `PICKED` → `PACKED_FOR_SHIP` → `SHIPPED` → `DELIVERED` → `RETURNED`, governed by §3.7 through §3.9. The two axes meet at join points: a pack cannot be staged until its assembly axis reaches `READY_TO_STORE`, and a recall can cut across both axes at once. A pack whose assembly axis reaches `RECALLED` is finished on that axis regardless of where its logistics axis stands.

### 3.4. Welding Records & Weld Certification

Welding is the first assembly gate. An `AssemblyLead` records a weld on a pack that is still `BUILT` — any other assembly state is rejected with `ERR_PACK_NOT_BUILT` — under an `OPEN` program, supplying the `weld_count` performed (at least 1), the weld current `current_amps` at one decimal, the pulse duration `pulse_ms` in whole milliseconds (at least 1), the `electrode_force_n` applied at one decimal, and the `weld_profile_used`. The record is persisted immutably, stamped with the operator's identifier as `operator_id` and the pack's `battery_pack_id` and `program_id`, with `is_certified` initially false and `certified_by_id` null.

Recording a weld computes its `heat_dose_j`, the total thermal energy deposited, which is also propagated onto the pack as `welding_heat_dose_j` as the pack's assembly status moves `BUILT` → `WELD_RECORDED`. The dose depends non-linearly on all four inputs. Each welding profile carries a base dose — 12.0 joules for `WELD_PROFILE_A`, 18.0 for `WELD_PROFILE_B`, 25.0 for `WELD_PROFILE_C` — and a force factor modulates the physics: one plus the amount by which `electrode_force_n` deviates from the 30-newton nominal, divided by 100, clamped so the factor never falls below 0.7 nor rises above 1.4. The raw joules are the `weld_count` multiplied by the `current_amps`, multiplied by the pulse duration expressed in seconds (the `pulse_ms` divided by 1000), multiplied by the profile's base dose; the force factor is then applied to that product, and only at the end is the result rounded half-up to two decimal places. Each profile also carries a ceiling — 450.0 joules for `WELD_PROFILE_A`, 700.0 for `WELD_PROFILE_B`, 1050.0 for `WELD_PROFILE_C` — but the ceiling is enforced at certification, not at recording: an over-ceiling weld record still persists, and it is the certification step that refuses it.

Certification is the quality gate, performed by a `QualityEngineer` on a pack that is `WELD_RECORDED` (otherwise `ERR_PACK_NOT_WELD_RECORDED`). The record must not already be certified (`ERR_WELD_ALREADY_CERTIFIED`); segregation of duties forbids the certifier from being the operator who laid the weld (`ERR_SOD_WELD_CERTIFY`, §2.11); the recorded `weld_profile_used` must equal the BOM's `welding_profile` (`ERR_WELD_PROFILE_MISMATCH`); and the computed `heat_dose_j` must not exceed the ceiling of that profile (`ERR_HEAT_DOSE_EXCEEDED`). When all four guards pass, the record's `is_certified` flips to true, `certified_by_id` is stamped with the certifier's identifier, and the pack advances `WELD_RECORDED` → `WELD_CERTIFIED`.

### 3.5. BMS Firmware Governance & Flashing

Firmware follows its own governed lifecycle, cyclic by design. An `AssemblyLead` registers a firmware binary by supplying its `firmware_version` (a semantic version string such as 2.4.1), the `binary_sha256` of the image as 64 lowercase hexadecimal characters, and an optional `supports_soc_hysteresis` flag that defaults to false; the row is born in `DRAFT` with `approval_record_id` null. Submitting a `DRAFT` firmware for review moves it to `PENDING_REVIEW` — attempting the submission from any state other than `DRAFT` or `DEPRECATED` is rejected, with `ERR_FIRMWARE_NOT_DRAFT` guarding the former path and `ERR_FIRMWARE_NOT_DEPRECATED` the latter, since a deprecated firmware may re-enter review through the same act.

A `SafetyOfficer` then records an immutable decision with a `decision` of `APPROVE` or `REJECT` and a free-text `rationale` of at least 20 characters. Approval requires the firmware to be `PENDING_REVIEW` (`ERR_FIRMWARE_NOT_PENDING_REVIEW`) and, per segregation of duties, the approver must not be the `AssemblyLead` who submitted it (`ERR_SOD_FIRMWARE_APPROVE`); an approval persists the `FirmwareApproval` stamped with `approver_id`, moves the firmware to `APPROVED`, and points `approval_record_id` at that approval row. A rejection also persists the decision record but returns the firmware to `DRAFT`. The decision value `REVOKE` is never accepted on the decision endpoint itself; revocation rows are written exclusively through deprecation.

Deprecation is how an `APPROVED` firmware leaves service: a `SafetyOfficer` deprecates it, which requires the firmware to be `APPROVED` (`ERR_FIRMWARE_NOT_APPROVED`) and is refused with `ERR_FIRMWARE_IN_USE` whenever any pack that has not reached a terminal assembly state references the firmware and has progressed to `TEST_QUEUED` or beyond. Deprecation writes a `FirmwareApproval` whose `decision` is `REVOKE`, clears `approval_record_id` to null, and moves the firmware to `DEPRECATED` — from which the re-certification cycle can carry it back through `PENDING_REVIEW` to `APPROVED` again.

Flashing joins firmware to hardware. An `AssemblyLead` flashes a pack that is `WELD_CERTIFIED` (otherwise `ERR_PACK_NOT_WELD_CERTIFIED`) by naming the `bms_firmware_id`; the firmware must exist in the same program and be `APPROVED`, with any other state rejected as `ERR_FIRMWARE_NOT_APPROVED`, and the binary hash flashed must be the one covered by the firmware's active approval through its `approval_record_id` linkage. The flash persists an immutable `BMSFlashRecord` stamped with `flashed_by_id` and a `flash_cycle_index` that counts the pack's flash attempts from 1 upward; the pack's `bms_firmware_id` is set, and its assembly status advances `WELD_CERTIFIED` → `BMS_FLASHED`.

### 3.6. UN38.3 Safety Test Dossiers & Shipping Classification

The dossier is where a pack earns its right to ship. A `QualityEngineer` opens a `SafetyTestDossier` against a pack that is `BMS_FLASHED` (otherwise `ERR_PACK_NOT_BMS_FLASHED`), provided no other dossier for the same pack sits in a non-terminal state — `OPEN`, `TESTS_RECORDED`, or `SUBMITTED` — which would trigger `ERR_DOSSIER_ALREADY_OPEN`. The first dossier carries `dossier_cycle_index` 1; opening it sets the pack's `dossier_id` and advances the pack `BMS_FLASHED` → `TEST_QUEUED`, with the dossier itself born in `OPEN`, its eight test fields null, its `outcome` `PENDING`, and its `final_un_score` still null.

Recording the test matrix is the QualityEngineer's next act, and it is the second concurrency-guarded write in the system: the request carries `expected_pack_version` alongside the eight measurements (§2.10). The dossier must still be `OPEN` (`ERR_DOSSIER_NOT_OPEN`), and all eight fields must be non-null before the matrix is accepted — `altitude_sim_kpa` for the T1 altitude simulation, `thermal_cycles` for T2, `vibration_minutes` for T3, `shock_g_peak` for T4, and the boolean results `external_short_circuit_ok` (T5), `impact_crush_ok` (T6), `overcharge_ok` (T7), and `forced_discharge_ok` (T8); an incomplete matrix is rejected with `ERR_INCOMPLETE_TEST_MATRIX`. Acceptance computes the dossier's `provisional_un_score`, moves the dossier `OPEN` → `TESTS_RECORDED`, and increments the pack's `version` by 1.

The composite score weights the eight tests so their contributions sum to 100: T1 carries 10, T2 carries 15, T3 carries 12, T4 carries 13, T5 carries 15, T6 carries 15, T7 carries 10, and T8 carries 10. Each numeric test is normalized to a sub-score between 0 and 1 by dividing the recorded value by its reference and clamping the quotient to that range: `altitude_sim_kpa` against the 11.6 kPa reference, `thermal_cycles` against 10 cycles, `vibration_minutes` against 180 minutes, and `shock_g_peak` against 150 G — a value at or above its reference yields a full sub-score of 1. Each boolean test contributes 1 when true and 0 when false. The score is the sum of each weight multiplied by its sub-score, rounded half-up to two decimal places. The two scoring variants differ only in how a missing boolean is treated: the provisional variant, computed when the matrix is recorded, counts a null boolean as an optimistic 0.5 while a false boolean still counts 0; the final variant, computed at submission, counts a null boolean as 0 and applies a strict fail-fast — any false boolean forces the entire final score to 0.0.

Submission is a `SafetyOfficer` act on a dossier that is `TESTS_RECORDED` (`ERR_DOSSIER_NOT_TESTS_RECORDED`) whose pack is `TEST_QUEUED` (`ERR_PACK_NOT_TEST_QUEUED`). It computes the `final_un_score` under the final variant and assigns the `outcome`. A final score of at least 85.0 marks the dossier `PASS`: the dossier's status becomes `SUBMITTED`, the pack's `shipping_classification` is derived from the dossier outcome and the pack's chemistry flag into one of `UN3480`, `UN3481`, `UN3090`, or `UN3091` (it remains `NONE` until this point), and the pack's assembly status moves `TEST_QUEUED` → `CLASSIFIED`. A final score below 85.0 marks the dossier `FAIL`: instead of settling in `SUBMITTED` the dossier lands in `FAILED`, the program's `compliance_risk_index` drops by 5, and the pack stays in `TEST_QUEUED`. From there the retest cycle runs: a `QualityEngineer` opens a fresh dossier, permitted only while the pack remains `TEST_QUEUED` (`ERR_PACK_NOT_TEST_QUEUED`) and no other dossier for the pack sits in a non-terminal state (`ERR_DOSSIER_ALREADY_OPEN`); the new dossier carries an incremented `dossier_cycle_index`, the pack's `dossier_id` re-points to it, and the pack's assembly status stays `TEST_QUEUED` throughout.

Approval closes the loop: a `SafetyOfficer` approves a dossier that is `SUBMITTED` (`ERR_DOSSIER_NOT_SUBMITTED`) with `outcome` equal to `PASS` (`ERR_DOSSIER_NOT_PASS`) on a pack that is `CLASSIFIED` (`ERR_PACK_NOT_CLASSIFIED`), moving the dossier to `APPROVED` and the pack `CLASSIFIED` → `READY_TO_STORE`. Only then is the logistics axis allowed to engage.

### 3.7. Storage, SOC Bands & Fire-Code Segregation

Storage is governed by state of charge. A pack's `soc_band` derives from its `soc_percent`: strictly below 30.0 places it in `SOC_LOW`, at least 30.0 and at most 60.0 places it in `SOC_MID`, and above 60.0 places it in `SOC_HIGH`. The plain variant of this assignment applies at pack creation and whenever the pack's flashed firmware does not support hysteresis. The hysteresis variant applies only when the band is recomputed after a safe-discharge event (§3.9) and the pack's flashed firmware has `supports_soc_hysteresis` true: the band boundaries then widen by 2.0 percentage points against the direction of travel to stop oscillation, so a pack in `SOC_MID` moves down into `SOC_LOW` only when its charge falls strictly below 28.0, and up into `SOC_HIGH` only when its charge rises strictly above 62.0.

A `LogisticsCoordinator` provisions warehouse slots by declaring a `location_code`, a `fire_zone` of `ZONE_A`, `ZONE_B`, `ZONE_C`, or `ZONE_ISOLATION`, a `capacity_wh` greater than zero, and the `accepts_soc_band` list — the subset of the three SOC bands the slot is fire-rated to hold. Slots are born with `wh_occupied` at 0 and derive `wh_headroom` per §2.8.

Staging a pack places it at a slot, and the pack's `soc_band` is re-evaluated as part of the act. The `LogisticsCoordinator` supplies the `storage_location_id` and the `battery_pack_id`, and a battery of guards fires in the order of §2.12: the pack's assembly axis must be `READY_TO_STORE` (`ERR_PACK_NOT_READY_TO_STORE`), its logistics axis must still be `NOT_STORED` (`ERR_PACK_ALREADY_STORED`), the program must be `OPEN` (`ERR_PROGRAM_NOT_OPEN`), the slot must exist within the same program (`ERR_LOCATION_NOT_FOUND`, or `ERR_CROSS_PROGRAM_REFERENCE` for a foreign slot), the pack's `soc_band` must appear in the slot's `accepts_soc_band` (`ERR_SOC_BAND_NOT_ACCEPTED`), the slot's `wh_headroom` must be at least the pack's `pack_energy_wh` (`ERR_LOCATION_CAPACITY_EXCEEDED`), and the program's `wh_available` must likewise cover the pack (`ERR_PROGRAM_CAPACITY_EXCEEDED`). Staging persists a `StoragePlacement` in `STAGED` status with `staged_at_utc` set, adds the pack's energy to the slot's `wh_occupied` and the program's `wh_committed`, sets the pack's `storage_location_id`, and moves its logistics axis `NOT_STORED` → `STAGED`.

Marking the placement stored requires the placement to be `STAGED` (`ERR_PLACEMENT_NOT_STAGED`) under an `OPEN` program; it sets `stored_at_utc`, moves the placement `STAGED` → `STORED`, and moves the pack's logistics axis to `STORED`. Picking reverses the residency: a `LogisticsCoordinator` picks a pack whose logistics axis is `STORED` (`ERR_PACK_NOT_STORED`), provided no `ACTIVE` recall currently captures it (`ERR_PACK_UNDER_RECALL`); picking stamps `released_at_utc` and moves the placement to `RELEASED`, subtracts the pack's energy from `wh_occupied` and `wh_committed`, clears the pack's `storage_location_id` to null, and advances the pack `STORED` → `PICKED`. A placement can also be released manually without a pick — the same recall guard applies (`ERR_PACK_UNDER_RECALL`) — which releases the placement, decrements the same two watt-hour ledgers, clears `storage_location_id`, and returns the pack's logistics axis to `NOT_STORED`. The `STAGED` → `RELEASED` and `STORED` → `RELEASED` transitions additionally fire automatically when a recall force-releases the pack (§3.9), with the server itself as the actor.

### 3.8. Transport Shipments & Carrier Tendering

Outbound transport begins when a `LogisticsCoordinator` opens a shipment in `DRAFT` status with a `carrier_code` (such as DHL-DG or FEDEX-DG), a `un_class_code` of `UN3480`, `UN3481`, `UN3090`, or `UN3091`, and the `declared_weight_kg` at two decimals; `total_pack_count` and `total_wh` start at 0 and `carrier_charge_cents` is uncomputed until tender.

Packs are attached one at a time. Attaching requires the pack's logistics axis to be `PICKED` (`ERR_PACK_NOT_PICKED`), the shipment to be `DRAFT` (`ERR_SHIPMENT_NOT_DRAFT`), the pack's `shipping_classification` to equal the shipment's `un_class_code` (`ERR_UN_CLASS_MISMATCH`), and the pack to be free of any other non-terminal shipment (`ERR_PACK_ALREADY_ATTACHED`). A successful attach persists an immutable `ShipmentPackLink` stamped with `attached_at_utc` and its `transport_shipment_id`, `battery_pack_id`, and `program_id`, increments the shipment's `total_pack_count` by 1, adds the pack's `pack_energy_wh` to `total_wh`, and moves the pack `PICKED` → `PACKED_FOR_SHIP`.

Tendering offers the shipment to the carrier. The shipment must be `DRAFT` and must contain at least one pack — an empty tender is rejected with `ERR_SHIPMENT_EMPTY` — and the UN-class agreement of every attached pack is re-verified (`ERR_UN_CLASS_MISMATCH`). Tendering moves the shipment `DRAFT` → `TENDERED` and computes the provisional `carrier_charge_cents`. The charge is tiered on `total_wh`: the first 500 watt-hours price at $0.12 per watt-hour, the portion above 500 up to 2000 watt-hours at $0.09, the portion above 2000 up to 5000 watt-hours at $0.06, and any portion beyond 5000 watt-hours at $0.04. A weight surcharge of forty cents per kilogram of `declared_weight_kg` is added to the watt-hour component, and the combined dollar amount is then multiplied by the dangerous-goods multiplier of the shipment's `un_class_code` — 1.25 for `UN3480`, 1.15 for `UN3481`, 1.35 for `UN3090`, and 1.20 for `UN3091` — before being converted to cents and rounded half-up to a whole number of cents.

The carrier then decides. A `CarrierAgent` accepts a `TENDERED` shipment (any other state yields `ERR_SHIPMENT_NOT_TENDERED`), optionally supplying a corrected `declared_weight_kg` that overrides the tendered figure; acceptance recomputes the charge under its final variant — idempotent over the same stored fields, but reflecting any weight override — and moves the shipment `TENDERED` → `CARRIER_ACCEPTED`. Rejection, also by the `CarrierAgent` and also requiring `TENDERED`, moves the shipment to `CARRIER_REJECTED`, from which it automatically returns to `DRAFT` for a re-tender cycle while the attached packs remain `PACKED_FOR_SHIP`. Once accepted, the `CarrierAgent` marks the shipment in transit — requiring `CARRIER_ACCEPTED` (`ERR_SHIPMENT_NOT_CARRIER_ACCEPTED`) — moving it to `IN_TRANSIT` and cascading every attached pack from `PACKED_FOR_SHIP` to `SHIPPED`. Final delivery requires `IN_TRANSIT` (`ERR_SHIPMENT_NOT_IN_TRANSIT`), moves the shipment to its terminal `DELIVERED` state, cascades every attached pack from `SHIPPED` to `DELIVERED`, and sets each delivered pack's `disposition` to `IN_SERVICE`.

### 3.9. Returns, Safe Discharge & Recall Campaigns

A return starts at the customer's door. A `CustomerService` operator opens a `ReturnAuthorization` against a program by naming the `battery_pack_id` being returned, a `reason_code` of `DEFECT`, `WARRANTY`, `OVERSTOCK`, or `RECALL_RETURN`, and the `target_soc_percent` the pack must be discharged to; the RMA is born in `REQUESTED` with the opener stamped as `requested_by_id` and `approved_by_id` and `actual_soc_after_discharge` still null.

Approval belongs to the `SafetyOfficer` and is guarded four ways: the RMA must be `REQUESTED` (`ERR_RMA_NOT_REQUESTED`), the referenced pack's logistics axis must be `DELIVERED` (`ERR_PACK_NOT_DELIVERED`), segregation of duties forbids the approver from being the requester (`ERR_SOD_RMA_APPROVE`), and the `target_soc_percent` must not exceed the safe-discharge ceiling of 30.0 percent (`ERR_TARGET_SOC_TOO_HIGH`). Approval stamps `approved_by_id`, moves the RMA `REQUESTED` → `APPROVED`, and sets the pack's `disposition` to `RETURN_PENDING`. Denial, also by a `SafetyOfficer` and requiring only `REQUESTED`, moves the RMA to its terminal `DENIED` state.

Discharge is quality work. A `QualityEngineer` begins discharge on an `APPROVED` RMA (`ERR_RMA_NOT_APPROVED`) whose pack is not currently held under a recall (`ERR_PACK_UNDER_RECALL`), moving the RMA to `DISCHARGE_PENDING`. Completing the discharge requires `DISCHARGE_PENDING` (`ERR_RMA_NOT_DISCHARGE_PENDING`) and takes the measured `final_soc_percent`, which must be at or below the RMA's `target_soc_percent` — overshooting the target is rejected with `ERR_DISCHARGE_TARGET_NOT_MET`. Completion writes `actual_soc_after_discharge` from the measured value, drives the pack's `soc_percent` to the same figure, recomputes the pack's `soc_band` under the hysteresis variant when the flashed firmware supports it (§3.7), sets `is_safe_discharged` to true, moves the pack's `disposition` to `DISCHARGED`, and moves the RMA to `DISCHARGED`. The `CustomerService` operator then receives the physical pack: receiving requires the RMA to be `DISCHARGED` (`ERR_RMA_NOT_DISCHARGED`) and rejects with `ERR_RMA_PACK_MISMATCH` if the RMA's `battery_pack_id` names a different pack than the one being received; it moves the RMA to `RECEIVED`, cascades the pack's logistics axis `DELIVERED` → `RETURNED`, and sets the pack's `disposition` to `SCRAPPED`. Closing the RMA requires `RECEIVED` (`ERR_RMA_NOT_RECEIVED`) and moves it to terminal `CLOSED`.

Recalls cut across everything. A `SafetyOfficer` opens a `RecallCampaign` with a `recall_code` unique within the program, a `severity` of `CLASS_I`, `CLASS_II`, or `CLASS_III`, and any combination of the three scope selectors: `scope_lot_id` capturing every pack built from a lot, `scope_bom_id` capturing every pack built from a BOM, and `scope_serial_prefix` capturing every pack whose `serial_number` begins with the given prefix (for example, SN-PRG-2014-A-0001). The campaign is born in `DRAFT` with `packs_in_scope` and `packs_contained` at 0.

Activation is the cascade. The campaign must be `DRAFT` (`ERR_RECALL_NOT_DRAFT`) and at least one scope selector must be set (`ERR_RECALL_SCOPE_EMPTY`). The capture set is the union of the three selector matches, deduplicated by pack and excluding packs already in `RECALLED` assembly status; `packs_in_scope` becomes its size. Every captured pack has its `active_recall_id` set to the campaign and its `disposition` driven to `RECALLED_HOLD`; each captured pack currently at `READY_TO_STORE` fires its assembly transition to `RECALLED`, and `packs_contained` counts those whose assembly axis has reached `RECALLED`. Captured packs currently `STAGED` or `STORED` are force-released — their placement moves to `RELEASED` and the slot's `wh_occupied` and the program's `wh_committed` are decremented accordingly — so recalled inventory never sits in rated storage. The program's `recall_count` increments by 1, and its `compliance_risk_index` drops by the severity weight (15, 8, or 3 per §2.7) multiplied by the capture count. Once captured, a recall hold blocks picking and manual release (`ERR_PACK_UNDER_RECALL`) and blocks the start of discharge on any RMA for the pack.

Containment and closure wind the campaign down. Marking contained requires the campaign to be `ACTIVE` (`ERR_RECALL_NOT_ACTIVE`) and refuses with `ERR_RECALL_NOT_FULLY_CONTAINED` while `packs_contained` still trails `packs_in_scope`. Closing requires `CONTAINED` (`ERR_RECALL_NOT_CONTAINED`); it moves the campaign to terminal `CLOSED`, decrements the program's `recall_count` by 1, and clears `active_recall_id` on every linked pack — though those packs keep their `RECALLED_HOLD` disposition as permanent evidence. A pack whose assembly axis has reached `RECALLED` is terminal on that axis whether its logistics axis ends at `RETURNED`, `DELIVERED`, or `NOT_STORED`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource return `200 OK`. The table below is a routing summary only — request payloads, response bodies, and side effects are defined by the narratives of §2 and §3, and all nested paths validate left to right per §2.5.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/integration-programs` | Create a new IntegrationProgram | SafetyOfficer |
| GET | `/api/integration-programs` | List IntegrationPrograms | Any |
| GET | `/api/integration-programs/{programId}` | Get a specific IntegrationProgram | Any |
| POST | `/api/integration-programs/{programId}/suspend` | Suspend a program (gates child mutations) | SafetyOfficer |
| POST | `/api/integration-programs/{programId}/resume` | Resume a suspended program | SafetyOfficer |
| POST | `/api/integration-programs/{programId}/close` | Close a program | SafetyOfficer |
| POST | `/api/integration-programs/{programId}/cell-lots` | Receive a new CellLot | QualityEngineer |
| GET | `/api/integration-programs/{programId}/cell-lots` | List CellLots for a program | Any |
| GET | `/api/integration-programs/{programId}/cell-lots/{lotId}` | Get a specific CellLot | Any |
| POST | `/api/integration-programs/{programId}/cell-lots/{lotId}/quarantine` | Move lot to QUARANTINE for inspection | QualityEngineer |
| POST | `/api/integration-programs/{programId}/cell-lots/{lotId}/inspections` | Record an immutable CellInspectionRecord | QualityEngineer |
| GET | `/api/integration-programs/{programId}/cell-lots/{lotId}/inspections` | List inspection records for a lot | Any |
| POST | `/api/integration-programs/{programId}/cell-lots/{lotId}/retest` | Re-enter QUARANTINE from REJECTED | QualityEngineer |
| POST | `/api/integration-programs/{programId}/pack-boms` | Define a PackBOM drawing cells from a lot | AssemblyLead |
| GET | `/api/integration-programs/{programId}/pack-boms` | List PackBOMs | Any |
| GET | `/api/integration-programs/{programId}/pack-boms/{bomId}` | Get a specific PackBOM | Any |
| POST | `/api/integration-programs/{programId}/battery-packs` | Assemble a new BatteryPack from a BOM | AssemblyLead |
| GET | `/api/integration-programs/{programId}/battery-packs` | List BatteryPacks | Any |
| GET | `/api/integration-programs/{programId}/battery-packs/{packId}` | Get a specific BatteryPack | Any |
| POST | `/api/integration-programs/{programId}/battery-packs/{packId}/pick` | Pick a STORED pack (releases placement) | LogisticsCoordinator |
| POST | `/api/integration-programs/{programId}/battery-packs/{packId}/welding-records` | Record a weld (immutable) | AssemblyLead |
| GET | `/api/integration-programs/{programId}/battery-packs/{packId}/welding-records` | List weld records for a pack | Any |
| GET | `/api/integration-programs/{programId}/battery-packs/{packId}/welding-records/{recordId}` | Get a specific weld record | Any |
| POST | `/api/integration-programs/{programId}/battery-packs/{packId}/welding-records/{recordId}/certify` | Certify a weld (SoD: certifier differs from operator) | QualityEngineer |
| POST | `/api/integration-programs/{programId}/bms-firmwares` | Register a new BMS firmware binary | AssemblyLead |
| GET | `/api/integration-programs/{programId}/bms-firmwares` | List firmware rows | Any |
| GET | `/api/integration-programs/{programId}/bms-firmwares/{fwId}` | Get a specific firmware | Any |
| POST | `/api/integration-programs/{programId}/bms-firmwares/{fwId}/submit-review` | Move DRAFT or DEPRECATED firmware to PENDING_REVIEW | AssemblyLead |
| POST | `/api/integration-programs/{programId}/bms-firmwares/{fwId}/approvals` | Record a firmware approval decision (immutable) | SafetyOfficer |
| GET | `/api/integration-programs/{programId}/bms-firmwares/{fwId}/approvals` | List approval events for a firmware | Any |
| POST | `/api/integration-programs/{programId}/bms-firmwares/{fwId}/deprecate` | Deprecate an APPROVED firmware | SafetyOfficer |
| POST | `/api/integration-programs/{programId}/battery-packs/{packId}/bms-flash-records` | Flash firmware onto a pack | AssemblyLead |
| GET | `/api/integration-programs/{programId}/battery-packs/{packId}/bms-flash-records` | List flash records for a pack | Any |
| POST | `/api/integration-programs/{programId}/battery-packs/{packId}/safety-test-dossiers` | Open a new dossier for a pack (initial or retest) | QualityEngineer |
| GET | `/api/integration-programs/{programId}/battery-packs/{packId}/safety-test-dossiers` | List dossiers for a pack | Any |
| GET | `/api/integration-programs/{programId}/battery-packs/{packId}/safety-test-dossiers/{dossierId}` | Get a specific dossier | Any |
| PUT | `/api/integration-programs/{programId}/battery-packs/{packId}/safety-test-dossiers/{dossierId}` | Record the 8-field test matrix (OCC on pack version) | QualityEngineer |
| POST | `/api/integration-programs/{programId}/battery-packs/{packId}/safety-test-dossiers/{dossierId}/submit` | Submit dossier; compute final score and assign outcome | SafetyOfficer |
| POST | `/api/integration-programs/{programId}/battery-packs/{packId}/safety-test-dossiers/{dossierId}/approve` | Approve a SUBMITTED PASS dossier | SafetyOfficer |
| POST | `/api/integration-programs/{programId}/storage-locations` | Create a storage slot | LogisticsCoordinator |
| GET | `/api/integration-programs/{programId}/storage-locations` | List storage slots | Any |
| GET | `/api/integration-programs/{programId}/storage-locations/{locationId}` | Get a storage slot | Any |
| POST | `/api/integration-programs/{programId}/storage-placements` | Stage a pack at a slot | LogisticsCoordinator |
| GET | `/api/integration-programs/{programId}/storage-placements` | List placements | Any |
| GET | `/api/integration-programs/{programId}/storage-placements/{placementId}` | Get a specific placement | Any |
| POST | `/api/integration-programs/{programId}/storage-placements/{placementId}/store` | Mark a placement as STORED | LogisticsCoordinator |
| POST | `/api/integration-programs/{programId}/storage-placements/{placementId}/release` | Release a placement manually (blocked under recall) | LogisticsCoordinator |
| POST | `/api/integration-programs/{programId}/transport-shipments` | Create a DRAFT shipment | LogisticsCoordinator |
| GET | `/api/integration-programs/{programId}/transport-shipments` | List shipments | Any |
| GET | `/api/integration-programs/{programId}/transport-shipments/{shipmentId}` | Get a shipment | Any |
| POST | `/api/integration-programs/{programId}/transport-shipments/{shipmentId}/attach` | Attach a PICKED pack to a DRAFT shipment | LogisticsCoordinator |
| GET | `/api/integration-programs/{programId}/transport-shipments/{shipmentId}/packs` | List packs attached to a shipment | Any |
| POST | `/api/integration-programs/{programId}/transport-shipments/{shipmentId}/tender` | Tender a DRAFT shipment (provisional charge) | LogisticsCoordinator |
| POST | `/api/integration-programs/{programId}/transport-shipments/{shipmentId}/carrier-accept` | Carrier accepts a tendered shipment (final charge) | CarrierAgent |
| POST | `/api/integration-programs/{programId}/transport-shipments/{shipmentId}/carrier-reject` | Carrier rejects a tendered shipment | CarrierAgent |
| POST | `/api/integration-programs/{programId}/transport-shipments/{shipmentId}/mark-in-transit` | Mark shipment IN_TRANSIT; cascades packs to SHIPPED | CarrierAgent |
| POST | `/api/integration-programs/{programId}/transport-shipments/{shipmentId}/mark-delivered` | Mark shipment DELIVERED; cascades packs to DELIVERED | CarrierAgent |
| POST | `/api/integration-programs/{programId}/return-authorizations` | Open a return authorization | CustomerService |
| GET | `/api/integration-programs/{programId}/return-authorizations` | List RMAs | Any |
| GET | `/api/integration-programs/{programId}/return-authorizations/{rmaId}` | Get a specific RMA | Any |
| POST | `/api/integration-programs/{programId}/return-authorizations/{rmaId}/approve` | Approve an RMA (SoD vs requester) | SafetyOfficer |
| POST | `/api/integration-programs/{programId}/return-authorizations/{rmaId}/deny` | Deny an RMA | SafetyOfficer |
| POST | `/api/integration-programs/{programId}/return-authorizations/{rmaId}/begin-discharge` | Begin safe discharge | QualityEngineer |
| POST | `/api/integration-programs/{programId}/return-authorizations/{rmaId}/complete-discharge` | Record final SOC and complete discharge | QualityEngineer |
| POST | `/api/integration-programs/{programId}/return-authorizations/{rmaId}/receive` | Mark the returned pack received | CustomerService |
| POST | `/api/integration-programs/{programId}/return-authorizations/{rmaId}/close` | Close the RMA | CustomerService |
| POST | `/api/integration-programs/{programId}/recall-campaigns` | Open a recall campaign | SafetyOfficer |
| GET | `/api/integration-programs/{programId}/recall-campaigns` | List recall campaigns | Any |
| GET | `/api/integration-programs/{programId}/recall-campaigns/{recallId}` | Get a recall campaign | Any |
| POST | `/api/integration-programs/{programId}/recall-campaigns/{recallId}/activate` | Activate the recall — cascades to capture packs | SafetyOfficer |
| POST | `/api/integration-programs/{programId}/recall-campaigns/{recallId}/mark-contained` | Mark recall contained when all packs recovered | SafetyOfficer |
| POST | `/api/integration-programs/{programId}/recall-campaigns/{recallId}/close` | Close a contained recall | SafetyOfficer |
| POST | `/_clock/set_current_utc` | Set the server's logical clock (default at startup: 2026-08-01T00:00:00Z) | SafetyOfficer |
| GET | `/api/cell-lots/{lotId}` | Flat single-get for a CellLot by id | Any |
| GET | `/api/cell-lots` | Flat filtered list of CellLots | Any |
| GET | `/api/cell-inspection-records/{recId}` | Flat single-get for a CellInspectionRecord by id | Any |
| GET | `/api/cell-inspection-records` | Flat filtered list of CellInspectionRecords | Any |
| GET | `/api/pack-boms/{bomId}` | Flat single-get for a PackBOM by id | Any |
| GET | `/api/pack-boms` | Flat filtered list of PackBOMs | Any |
| GET | `/api/battery-packs/{packId}` | Flat single-get for a BatteryPack by id | Any |
| GET | `/api/battery-packs` | Flat filtered list of BatteryPacks | Any |
| GET | `/api/welding-parameter-records/{recId}` | Flat single-get for a WeldingParameterRecord by id | Any |
| GET | `/api/welding-parameter-records` | Flat filtered list of WeldingParameterRecords | Any |
| GET | `/api/bms-firmwares/{fwId}` | Flat single-get for a BMSFirmware by id | Any |
| GET | `/api/bms-firmwares` | Flat filtered list of BMSFirmwares | Any |
| GET | `/api/firmware-approvals/{approvalId}` | Flat single-get for a FirmwareApproval by id | Any |
| GET | `/api/firmware-approvals` | Flat filtered list of FirmwareApprovals | Any |
| GET | `/api/bms-flash-records/{recId}` | Flat single-get for a BMSFlashRecord by id | Any |
| GET | `/api/bms-flash-records` | Flat filtered list of BMSFlashRecords | Any |
| GET | `/api/safety-test-dossiers/{dossierId}` | Flat single-get for a SafetyTestDossier by id | Any |
| GET | `/api/safety-test-dossiers` | Flat filtered list of SafetyTestDossiers | Any |
| GET | `/api/storage-locations/{locationId}` | Flat single-get for a StorageLocation by id | Any |
| GET | `/api/storage-locations` | Flat filtered list of StorageLocations | Any |
| GET | `/api/storage-placements/{placementId}` | Flat single-get for a StoragePlacement by id | Any |
| GET | `/api/storage-placements` | Flat filtered list of StoragePlacements | Any |
| GET | `/api/transport-shipments/{shipmentId}` | Flat single-get for a TransportShipment by id | Any |
| GET | `/api/transport-shipments` | Flat filtered list of TransportShipments | Any |
| GET | `/api/shipment-pack-links/{linkId}` | Flat single-get for a ShipmentPackLink by id | Any |
| GET | `/api/shipment-pack-links` | Flat filtered list of ShipmentPackLinks | Any |
| GET | `/api/return-authorizations/{rmaId}` | Flat single-get for a ReturnAuthorization by id | Any |
| GET | `/api/return-authorizations` | Flat filtered list of ReturnAuthorizations | Any |
| GET | `/api/recall-campaigns/{recallId}` | Flat single-get for a RecallCampaign by id | Any |
| GET | `/api/recall-campaigns` | Flat filtered list of RecallCampaigns | Any |

## 5. Error Code Catalogue

The catalogue below assigns each error identifier its HTTP status code. Trigger conditions are specified in the narratives of §2 and §3 rather than repeated here.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_PROGRAM_NOT_FOUND` | 404 Not Found |
| `ERR_LOT_NOT_FOUND` | 404 Not Found |
| `ERR_BOM_NOT_FOUND` | 404 Not Found |
| `ERR_PACK_NOT_FOUND` | 404 Not Found |
| `ERR_WELD_RECORD_NOT_FOUND` | 404 Not Found |
| `ERR_FIRMWARE_NOT_FOUND` | 404 Not Found |
| `ERR_DOSSIER_NOT_FOUND` | 404 Not Found |
| `ERR_LOCATION_NOT_FOUND` | 404 Not Found |
| `ERR_PLACEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_SHIPMENT_NOT_FOUND` | 404 Not Found |
| `ERR_RMA_NOT_FOUND` | 404 Not Found |
| `ERR_RECALL_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_ENUM` | 400 Bad Request |
| `ERR_PROGRAM_NOT_OPEN` | 409 Conflict |
| `ERR_PROGRAM_NOT_SUSPENDED` | 409 Conflict |
| `ERR_UNRESOLVED_PACKS_REMAIN` | 409 Conflict |
| `ERR_OPEN_SHIPMENTS_REMAIN` | 409 Conflict |
| `ERR_ACTIVE_RECALL_EXISTS` | 409 Conflict |
| `ERR_LOT_NOT_RECEIVED` | 409 Conflict |
| `ERR_LOT_NOT_IN_QUARANTINE` | 409 Conflict |
| `ERR_LOT_NOT_REJECTED` | 409 Conflict |
| `ERR_LOT_NOT_ACCEPTED` | 409 Conflict |
| `ERR_LOT_DEPLETED` | 409 Conflict |
| `ERR_INSPECTION_NOT_PASS` | 409 Conflict |
| `ERR_SOC_OUT_OF_TOLERANCE` | 422 Unprocessable Entity |
| `ERR_RETEST_LIMIT_EXCEEDED` | 409 Conflict |
| `ERR_PACK_NOT_BUILT` | 409 Conflict |
| `ERR_PACK_NOT_WELD_RECORDED` | 409 Conflict |
| `ERR_PACK_NOT_WELD_CERTIFIED` | 409 Conflict |
| `ERR_PACK_NOT_BMS_FLASHED` | 409 Conflict |
| `ERR_PACK_NOT_TEST_QUEUED` | 409 Conflict |
| `ERR_PACK_NOT_CLASSIFIED` | 409 Conflict |
| `ERR_PACK_NOT_READY_TO_STORE` | 409 Conflict |
| `ERR_PACK_ALREADY_STORED` | 409 Conflict |
| `ERR_PACK_NOT_STORED` | 409 Conflict |
| `ERR_PACK_NOT_PICKED` | 409 Conflict |
| `ERR_PACK_ALREADY_ATTACHED` | 409 Conflict |
| `ERR_PACK_NOT_DELIVERED` | 409 Conflict |
| `ERR_PACK_UNDER_RECALL` | 409 Conflict |
| `ERR_WELD_ALREADY_CERTIFIED` | 409 Conflict |
| `ERR_WELD_PROFILE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_HEAT_DOSE_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_FIRMWARE_NOT_DRAFT` | 409 Conflict |
| `ERR_FIRMWARE_NOT_PENDING_REVIEW` | 409 Conflict |
| `ERR_FIRMWARE_NOT_APPROVED` | 409 Conflict |
| `ERR_FIRMWARE_NOT_DEPRECATED` | 409 Conflict |
| `ERR_FIRMWARE_IN_USE` | 409 Conflict |
| `ERR_DOSSIER_ALREADY_OPEN` | 409 Conflict |
| `ERR_DOSSIER_NOT_OPEN` | 409 Conflict |
| `ERR_DOSSIER_NOT_TESTS_RECORDED` | 409 Conflict |
| `ERR_DOSSIER_NOT_SUBMITTED` | 409 Conflict |
| `ERR_DOSSIER_NOT_PASS` | 409 Conflict |
| `ERR_INCOMPLETE_TEST_MATRIX` | 422 Unprocessable Entity |
| `ERR_PLACEMENT_NOT_STAGED` | 409 Conflict |
| `ERR_SOC_BAND_NOT_ACCEPTED` | 422 Unprocessable Entity |
| `ERR_LOCATION_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_PROGRAM_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_SHIPMENT_NOT_DRAFT` | 409 Conflict |
| `ERR_SHIPMENT_EMPTY` | 422 Unprocessable Entity |
| `ERR_SHIPMENT_NOT_TENDERED` | 409 Conflict |
| `ERR_SHIPMENT_NOT_CARRIER_ACCEPTED` | 409 Conflict |
| `ERR_SHIPMENT_NOT_IN_TRANSIT` | 409 Conflict |
| `ERR_UN_CLASS_MISMATCH` | 422 Unprocessable Entity |
| `ERR_RMA_NOT_REQUESTED` | 409 Conflict |
| `ERR_RMA_NOT_APPROVED` | 409 Conflict |
| `ERR_RMA_NOT_DISCHARGE_PENDING` | 409 Conflict |
| `ERR_RMA_NOT_DISCHARGED` | 409 Conflict |
| `ERR_RMA_NOT_RECEIVED` | 409 Conflict |
| `ERR_RMA_PACK_MISMATCH` | 409 Conflict |
| `ERR_TARGET_SOC_TOO_HIGH` | 422 Unprocessable Entity |
| `ERR_DISCHARGE_TARGET_NOT_MET` | 422 Unprocessable Entity |
| `ERR_RECALL_NOT_DRAFT` | 409 Conflict |
| `ERR_RECALL_NOT_ACTIVE` | 409 Conflict |
| `ERR_RECALL_NOT_CONTAINED` | 409 Conflict |
| `ERR_RECALL_SCOPE_EMPTY` | 422 Unprocessable Entity |
| `ERR_RECALL_NOT_FULLY_CONTAINED` | 409 Conflict |
| `ERR_SOD_WELD_CERTIFY` | 403 Forbidden |
| `ERR_SOD_FIRMWARE_APPROVE` | 403 Forbidden |
| `ERR_SOD_RMA_APPROVE` | 403 Forbidden |
| `ERR_CROSS_PROGRAM_REFERENCE` | 422 Unprocessable Entity |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
