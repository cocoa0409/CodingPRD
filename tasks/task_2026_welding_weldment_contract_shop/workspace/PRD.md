# Welding & Weldment Contract Shop API — Product Requirements Document

## 1. Introduction

A contract welding shop bidding structural work under AWS D1.1 lives and dies by its paper trail: every weld on every joint must trace back to an approved procedure, a currently qualified welder, and a controlled consumable lot, and any gap in that chain is an audit finding waiting to happen. This document specifies the API for the 2026 Welding & Weldment Contract Shop, a system that runs the full compliance loop for a structural-steel job shop — governing welding procedure specifications (WPS) and their supporting procedure qualification records (PQR), enforcing the six-month welder continuity clock, controlling low-hydrogen consumable exposure between oven and joint, scheduling hold-point inspections across in-house visual examination and third-party NDT capacity, and deriving each weldment's shipping posture from the state of its joints, its repair rate, and its distortion history.

Rather than trusting operators to remember code requirements, the system embeds AWS D1.1 discipline directly into state transitions: document approvals carry segregation-of-duties checks, welder qualifications lapse automatically as the shop's logical clock advances, repair cycles are hard-capped, and a weldment cannot ship until every joint is welded out, every required NDT method has passed, and the traveler is fully signed. All work is scoped to a tenant `Shop`, every mutating workflow is traceable through versioned resources, and all system timestamps are taken from a deterministic, shop-level logical clock. The API is mounted under `/weld-shop`.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity in which they act. A request missing either header, or carrying a malformed value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is not authorized for the target operation is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

The system recognizes ten roles: `ShopAdmin`, `QCManager`, `WeldLead`, `Welder`, `CWI`, `MaterialController`, `ProductionPlanner`, `QualityInspector`, `ShippingClerk`, and `Any`. `Any` is the read-only umbrella: any authenticated role may perform GET reads. The named roles divide the write surface along a strict segregation-of-duties model — the people who weld are not the people who inspect, and the person who reviews a procedure qualification is not the person who approves the procedure built on it.

Role capabilities, in brief:

- `ShopAdmin` is the shop administrator. It alone creates the shop record, advances the logical clock, enrolls welders, and registers NDT vendors.
- `QCManager` is the quality-control manager. It alone creates and dispositions PQRs and WPS revisions (approve and reject), manages welder qualifications (create, requalify, revoke), declares joint repairs, rebinds held joints to a new WPS, clears repair-review posture, unfreezes weldments, and dispositions distortion reports.
- `WeldLead` runs the fabrication floor at the joint level: it creates joints, starts fabrication, and marks joints welded out.
- `Welder` records weld passes, and does so under its own identity (see the identity rule below).
- `CWI` is the Certified Welding Inspector: it schedules and records inspections and releases hold points.
- `MaterialController` owns ovens, consumable lots, and consumable issues — including returns, rebakes, and taking ovens offline or bringing them online.
- `ProductionPlanner` owns fixtures (create, reserve, release, send for repair), shop orders, weldment creation, and weldment cancellation.
- `QualityInspector` files distortion reports.
- `ShippingClerk` ships weldments.

Traveler sign-offs are shared across three roles with per-step restrictions detailed in §3.8: `WeldLead` signs the `FIT_UP` and `WELD_OUT` steps, `QualityInspector` signs the `VT` and `NDT` steps, and `CWI` signs the `VT`, `NDT`, and `FINAL` steps.

Identity semantics differ across roles, and are normative:

- When `X-User-Role` is `Welder`, `X-User-ID` is the `id` of the acting `Welder` entity; ownership checks on any resource that references a `Welder` compare the resource's foreign-key field to `X-User-ID`. A weld pass recorded under this role attributes the pass to that welder.
- When `X-User-Role` is `QCManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it — as `reviewed_by_user_id` on a PQR approval and as `approved_by_user_id` on a WPS approval — and the segregation-of-duties rule compares those two recorded identifiers against each other, but the identifier is never compared to any entity's `id`.
- When `X-User-Role` is `CWI`, `X-User-ID` is likewise opaque. The server records it as `inspector_user_id` on each inspection it performs and as `signed_by_user_id` on sign-offs, and the visual-inspection segregation rule compares it against the welder identifiers recorded on the joint's weld passes — again without treating it as any entity's `id`.
- When `X-User-Role` is `QualityInspector`, `X-User-ID` is opaque; the server records it as `reported_by_user_id` on distortion reports and as `signed_by_user_id` on sign-offs.
- When `X-User-Role` is `ShopAdmin`, `WeldLead`, `MaterialController`, `ProductionPlanner`, `ShippingClerk`, or `Any`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `signed_by_user_id` on a traveler sign-off) but does not compare it to any entity's `id`.

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

List endpoints paginate through two query parameters. The `limit` parameter sets the maximum number of items returned: it defaults to 10 when omitted, accepts a minimum of 1, and is capped at a maximum of 100. The `offset` parameter sets how many items to skip and defaults to 0.

Unless otherwise specified, every list endpoint returns its resources sorted by `created_at` in ascending order.

The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Primary resources — the `Shop` and its welders, NDT vendors, ovens, PQRs, WPS revisions, welder qualifications, consumable lots, fixtures, shop orders, weldments, and joints — share a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a bare UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording the last modification; every mutation refreshes it.
- `version` (integer): a system-managed integer that increments by one on every mutation of the resource, including mutations caused by cascades and derived-field recomputation; it is the basis for optimistic concurrency control.

Five ledger-style records are deliberately lighter: `ConsumableIssue`, `WeldPass`, `DistortionReport`, `Inspection`, and `TravelerSignOff` carry only `id` and `created_at`. Both `updated_at` and `version` are absent from these five; they are append-only evidence records and are never the target of an optimistic-concurrency check.

### 2.5. The Shop Logical Clock

Each `Shop` carries a logical clock in its `current_utc` field. The clock is initialized to `2026-08-01T00:00:00Z` when the shop is created and never advances on its own — time moves only when a `ShopAdmin` sets the clock, supplying the target instant as `to_iso8601`. Setting the clock writes `current_utc` to the supplied instant and triggers two recomputation sweeps: a welder-continuity sweep that re-evaluates every `QUALIFIED` qualification for lapse, and a joint/weldment posture recomputation across the shop.

Every system-side timestamp in the domain reads this logical clock rather than wall time: `welded_at_utc` on a weld pass, `issued_at_utc` and `returned_at_utc` on a consumable issue, `reported_at_utc` on a distortion report, `resulted_at_utc` on an inspection, `signed_at_utc` on a traveler sign-off, and `signed_off_at_utc` on a shipped weldment are all stamped from the shop's `current_utc` at the moment of the operation. Datetime comparisons throughout this document are made at second granularity.

### 2.6. Optimistic Concurrency Control

Three write operations are protected by optimistic concurrency control, each keyed to the `version` of the parent entity it mutates:

- Shipping a weldment requires the request to carry `expected_weldment_version`, holding the weldment `version` the client last observed. If the weldment's current `version` has advanced past the supplied value — for example because a joint result or a distortion disposition cascaded into the weldment — the ship request is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Starting fabrication on a joint requires `expected_joint_version`, holding the joint `version` the client last observed. A WPS-supersession cascade that flipped the joint to `ON_HOLD` advances the joint's `version`; a start-fabrication request still carrying the pre-cascade version is rejected with `ERR_STALE_VERSION` (HTTP 412) so the client re-reads and discovers the hold.
- Approving a WPS revision requires `expected_wps_version`, holding the WPS `version` the client last observed. If the WPS's current `version` has advanced, the approval is rejected with `ERR_STALE_VERSION` (HTTP 412).

On all three operations the version field is non-optional, and the comparison is against the parent entity's current stored `version` at the moment the write is evaluated. No other endpoint accepts a version field; requests to any other operation must not supply one.

### 2.7. Derived Posture and Cascade Consistency

A weldment's `posture` is never assigned directly by a client. It is a derived attribute that the server recomputes from the weldment's children and counters: joints placed `ON_HOLD` or still carrying a `PENDING` distortion report restrict the weldment, a repair rate that reaches the shop's contractual limit moves it into review, and a failed NDT result combined with repeated distortion freezes it. The same derivation philosophy runs the other way — when the underlying conditions clear (reports dispositioned, holds rebound, reviews cleared by a `QCManager`), the posture is recomputed back. Posture changes are themselves mutations: each recomputation that alters a weldment refreshes its `updated_at` and increments its `version`.

Cascades propagate state across the hierarchy so that no record is left inconsistent with its container. Approving a new WPS revision supersedes the prior approved revision and places still-`PENDING` joints that reference it `ON_HOLD`. Taking an oven offline quarantines its issued lots and voids their open issues. Shipping or cancelling the last active weldment on a fixture returns the fixture to service; shipping the last weldment on an order completes the order. Cancelling a weldment cancels its non-terminal joints and voids its in-flight inspections. Each of these secondary mutations independently refreshes the affected resource's `updated_at` and increments its `version`.

### 2.8. Validation Precedence

When several validations could reject the same request, the server applies them in a fixed precedence so the surfaced error is deterministic. First come the transport-level checks: header presence and well-formedness (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`), then role authorization (`ERR_INSUFFICIENT_PERMISSIONS`). Next, the server resolves every identifier in the path left to right, rejecting with `ERR_NOT_FOUND` at the first identifier that does not resolve. Next comes optimistic concurrency: a stale `expected_weldment_version`, `expected_joint_version`, or `expected_wps_version` is rejected (`ERR_STALE_VERSION`) before any lifecycle evaluation. Lifecycle state is evaluated next — the resource must be in the correct state for the requested transition, surfacing either the transition-specific state error or the generic `ERR_INVALID_STATE` (HTTP 409).

Only after state checks pass do business rules run, in this order: segregation-of-duties and welding-code safety checks (WPS/PQR process and material agreement, the thickness envelope, welder continuity, consumable-lot usability); then business constraints (weldment posture gates, oven capacity, the repair-cycle and rebake caps); then temporal rules (vendor slot conflicts, inspection timing); then fiscal quantity checks (issued mass against remaining mass); and finally referential completeness (traveler steps before shipment). A request whose body is malformed or missing a required field is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Wherever a single operation enforces several of these rules, the per-operation narratives in §3 state their evaluation order explicitly.

### 2.9. Measurement Precision and Rounding

All percentages in the system — above all the weldment `repair_rate_pct` — are stored at exactly two decimal places, rounded half-up. Mass quantities (`received_kg`, `remaining_kg`, `issued_kg`, `consumable_used_kg`, oven load) are carried in kilograms at two decimal places. Atmospheric exposure is tracked in whole minutes only: any partial minute is discarded, and the cumulative `exposed_minutes_total` on a lot is an integer minute count. Thickness values (`thickness_range_min_mm`, `thickness_range_max_mm`, `thickness_min_mm`, `thickness_max_mm`, `base_metal_thickness_mm`) are floating-point millimetres, and every thickness comparison in this document is inclusive of its boundary — a value sitting exactly on an envelope edge passes. Datetime arithmetic is performed at second granularity, and the welder-continuity boundary is inclusive of the expiry instant: a qualification is lapsed when the shop clock reaches or passes its expiry, and is still valid strictly before it.

### 2.10. Nested Retrieval, Flat Collections, and Addressing

Requests that target nested resources are validated strictly left to right along the path. A request addressed at a joint beneath a weldment beneath a shop — for example one carrying `{id}`, `{weldmentId}`, and `{jointId}` — first resolves the shop, then the weldment within it, then the joint; the request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first identifier in the chain that does not resolve, and deeper identifiers are never consulted. Path variables used across the API are `{id}`, `{welderId}`, `{vendorId}`, `{ovenId}`, `{pqrId}`, `{wpsId}`, `{qualId}`, `{lotId}`, `{issueId}`, `{fixtureId}`, `{orderId}`, `{weldmentId}`, `{jointId}`, `{passId}`, `{reportId}`, `{inspectionId}`, and `{signoffId}`.

In addition to the nested paths, every child entity is reachable through a flat, shop-agnostic two-segment path — a single-resource GET and a filtered list GET — so that audit tooling can address records directly by their own identifier. List endpoints accept optional equality filters drawn from the entity's foreign keys and lifecycle fields: welders, NDT vendors, ovens, PQRs, fixtures, and shop orders filter by `shop_id`; WPS revisions filter by `shop_id`, `pqr_id`, or `superseded_by_id`; welder qualifications filter by `shop_id`, `welder_id`, or `wps_id`; consumable lots filter by `shop_id`, `oven_id`, or `status`; consumable issues filter by `shop_id`, `lot_id`, `oven_id`, or `issued_to_welder_id`; weldments filter by `shop_id`, `shop_order_id`, or `fixture_id`; joints filter by `shop_id`, `weldment_id`, or `wps_id`; weld passes filter by `shop_id`, `joint_id`, `welder_id`, `qualification_id`, or `consumable_lot_id`; distortion reports filter by `shop_id`, `weldment_id`, or `joint_id`; inspections filter by `shop_id`, `joint_id`, or `vendor_id`; and traveler sign-offs filter by `shop_id` or `weldment_id`. The nested list endpoints under a shop accept the same non-shop filters (for example, a shop-scoped qualification list narrows by `welder_id` or `wps_id`, and a shop-scoped lot list by `oven_id` or `status`).

## 3. Business Logic & Workflows

### 3.1. Shop Onboarding and Procedure Qualification

A `ShopAdmin` onboards a new contract shop by supplying its legal `shop_name`, the `aws_d1_1_revision` the shop is contractually bound to (for example, `D1.1:2025`), and optionally a `repair_rate_limit_pct` — the shop-wide contractual ceiling on repair work, expressed as a whole percent and defaulting to 5 when omitted. Creation of the shop also seeds its logical clock, so the shop begins life with `current_utc` set to `2026-08-01T00:00:00Z`. The shop record anchors everything else: welders, vendors, ovens, documents, orders, and lots all carry a `shop_id` back to it.

Before any arc is struck, the shop must qualify its welding procedures. The foundation document is the **PQR** — a procedure qualification record evidencing that a process produced sound test welds. A `QCManager` drafts a PQR with its `pqr_number` (unique within the shop), its `process` (one of `SMAW`, `GMAW`, `FCAW`, `GTAW`, or `SAW`), the `base_metal_spec` it was qualified on (for example ASTM A36 or A572 Gr50), the qualified thickness window `thickness_range_min_mm` through `thickness_range_max_mm`, and the external `test_report_id` referencing the mechanical test report. A PQR is born `DRAFT`. Approving it — again a `QCManager` action — requires that it still be `DRAFT` (otherwise `ERR_PQR_NOT_DRAFT`) and that its thickness window be well formed, meaning the maximum is strictly greater than the minimum (otherwise `ERR_INVALID_THICKNESS_RANGE`). Approval stamps the PQR with the approver's identity in `reviewed_by_user_id` and increments its `version`; an `APPROVED` PQR is immutable from that moment on. A `QCManager` may instead reject a `DRAFT` PQR, moving it to `REJECTED` and incrementing its `version`. Both `APPROVED` and `REJECTED` are terminal for the PQR.

The **WPS** is the working document derived from a PQR, and it carries a revision cycle. Creating a WPS revision takes a `wps_number`, an integer `revision` counter within that number, the supporting `pqr_id`, the `process`, the `base_metal_spec`, and the qualified thickness window `thickness_min_mm` through `thickness_max_mm` that this document will cover. The combination of shop, `wps_number`, and `revision` is unique, so a shop evolves a procedure by drafting revision N+1 while revision N is in force. A new revision is born `DRAFT`.

Approving a WPS revision is the most heavily gated write in the system, and its checks are evaluated in a fixed order. First the optimistic-concurrency gate: the request must carry `expected_wps_version` matching the revision's current `version`, else it is rejected with `ERR_STALE_VERSION` as described in §2.6. Then the lifecycle gates: the revision itself must be `DRAFT` (`ERR_WPS_NOT_DRAFT`), and the referenced PQR must be `APPROVED` at that moment (`ERR_PQR_NOT_APPROVED`). Then segregation of duties: the approving `X-User-ID` must differ from the `reviewed_by_user_id` recorded on the supporting PQR — the same person may not review a qualification record and approve the procedure built on it (`ERR_SEGREGATION_OF_DUTIES`, HTTP 403). Then welding-code agreement: the WPS `process` must equal the PQR `process` (`ERR_WPS_PQR_PROCESS_MISMATCH`) and the WPS `base_metal_spec` must equal the PQR `base_metal_spec` (`ERR_WPS_PQR_MATERIAL_MISMATCH`). Then the thickness envelope, evaluated with inclusive boundaries: the WPS `thickness_min_mm` must be at least the PQR `thickness_range_min_mm`, and the WPS `thickness_max_mm` must be at most the PQR `thickness_range_max_mm` — a WPS envelope that exactly matches the PQR envelope passes, and any protrusion is rejected with `ERR_WPS_THICKNESS_OUTSIDE_PQR`. Finally, revision uniqueness: no other WPS in the same shop with the same `wps_number` and `revision` may already be `APPROVED` (`ERR_WPS_REVISION_CONFLICT`).

Approval leaves a long shadow of side effects. The revision pins its supporting evidence: `pinned_pqr_version` captures the PQR's `version` at approval time, so any later re-approval must re-pin against the PQR's then-current version. The approver's identity is recorded in `approved_by_user_id`, and the revision's `version` increments. Any prior WPS revision in the same shop carrying the same `wps_number` at a lower `revision` that is still `APPROVED` is cascaded to `SUPERSEDED`, with its `superseded_by_id` pointed at the newly approved revision and its own `version` incremented. Supersession ripples outward: every joint still `PENDING` in fabrication that references a superseded WPS is flipped to `ON_HOLD` until a `QCManager` rebinds it, and every welder qualification tied to a superseded WPS that is still `QUALIFIED` is re-evaluated for continuity lapse as of the shop's current clock (see §3.2). Rejecting a `DRAFT` revision moves it to `REJECTED` and increments its `version`. `REJECTED` and `SUPERSEDED` are terminal; `APPROVED` is not, because a newer revision can supersede it — the cycle runs `DRAFT` to `APPROVED` to `SUPERSEDED`, with a fresh `DRAFT` created for the next revision.

### 3.2. Welder Roster, Qualification, and the Continuity Clock

The `ShopAdmin` maintains the welder roster. Each welder is enrolled with a `stencil` — the badge or stencil ID stamped into the work, unique within the shop — and a `full_name`. A welder's `status` begins at `ACTIVE`; the full vocabulary is `ACTIVE`, `SUSPENDED`, and `TERMINATED`.

A welder may only weld under a procedure they are qualified for. A `QCManager` creates a **WelderQualification** by naming the `welder_id`, the `wps_id` of the specific WPS revision the welder tested against, the qualified `process` (which must match the WPS's `process`), and `qualified_at_utc`, the date the welder passed the performance test. The qualification is born `QUALIFIED`; its `last_weld_at_utc` is initialized to `qualified_at_utc`, and its `continuity_expires_at_utc` is computed as the later of `qualified_at_utc` and `last_weld_at_utc` plus 183 days — the AWS D1.1 six-month continuity window. Thereafter, every weld pass the welder records under that qualification refreshes `last_weld_at_utc` to the shop clock at pass time, which recomputes the expiry from that new baseline.

Continuity lapse is evaluated at second granularity with an inclusive boundary: a qualification is lapsed when the shop's `current_utc` reaches or passes its `continuity_expires_at_utc` — it is lapsed *at* the expiry instant, not after it. The same formula is evaluated on two triggers. Prospectively, each weld pass checks the qualification at the moment of the pass. Retrospectively, two sweeps re-evaluate every `QUALIFIED` row against the clock without any new weld activity: advancing the shop clock runs the continuity sweep, and the WPS-supersession cascade of §3.1 re-evaluates all `QUALIFIED` qualifications tied to a superseded WPS, flipping to `LAPSED` those whose welder's `last_weld_at_utc` lies more than 183 days in the past relative to `current_utc`. A lapse increments the qualification's `version` and forces a recomputation of the welder's `status`: a welder left with no `QUALIFIED` qualification at all becomes `SUSPENDED`.

A `LAPSED` qualification can be brought back. Requalification by a `QCManager` requires that the qualification currently be `LAPSED` (otherwise `ERR_QUAL_NOT_LAPSED`), that the welder not be `TERMINATED` (otherwise `ERR_WELDER_TERMINATED`), and that the WPS the qualification references still be `APPROVED` rather than `SUPERSEDED` (otherwise `ERR_WPS_NOT_APPROVED`). Requalification sets `qualified_at_utc` and `last_weld_at_utc` to the shop's current clock, extends `continuity_expires_at_utc` to 183 days past that instant, returns the qualification to `QUALIFIED`, and recomputes the welder's `status` under the same rule in reverse — with a `QUALIFIED` qualification present again, the welder leaves `SUSPENDED` and returns to `ACTIVE`. A `QCManager` may also revoke a qualification outright; revocation is permitted from either `QUALIFIED` or `LAPSED` with no further preconditions, moves the qualification to the terminal `REVOKED` state, and recomputes the welder's `status`.

### 3.3. Consumable Lots, Ovens, and Exposure Control

Low-hydrogen electrode discipline is enforced through ovens and lot accounting. A `MaterialController` registers each oven with its physical `oven_code`, a `holding_temp_c` that must be at least 120 and at most 300 degrees Celsius, and a `capacity_electrodes_kg` giving the maximum electrode mass the oven can hold. An oven is born `ONLINE`; its status vocabulary is `ONLINE`, `OFFLINE`, and `QUARANTINED`.

Receiving a consumable lot places it directly into an oven. The `MaterialController` supplies the manufacturer `lot_number`, the `filler_spec` (for example E7018 or ER70S-6), the `process` the filler supports (again one of `SMAW`, `GMAW`, `FCAW`, `GTAW`, `SAW`), the `received_kg` mass, and the `oven_id` of the receiving oven. Before the lot is accepted, the oven's projected load is checked: the load is the sum of `remaining_kg` across all lots currently in that oven whose status is `IN_OVEN` or `QUARANTINED` (lots that are `EXHAUSTED` or `CONSUMED` no longer count against it), and the existing load plus the new lot must be at most the oven's `capacity_electrodes_kg` — the comparison is inclusive, so a projected load exactly equal to capacity is accepted, and anything beyond it is rejected with `ERR_OVEN_CAPACITY_EXCEEDED`. A received lot is born `IN_OVEN` with `remaining_kg` equal to `received_kg`, `exposed_minutes_total` at 0, and `rebake_count` at 0. Its status vocabulary comprises `IN_OVEN`, `ISSUED`, `EXPOSED`, `QUARANTINED`, `EXHAUSTED`, and `CONSUMED`; the terminal states are `QUARANTINED`, `EXHAUSTED`, and `CONSUMED`. The `remaining_kg` on a lot is never set directly: it is derived as the received mass minus everything consumed by weld passes and everything currently issued and not yet returned.

Issuing electrodes moves material from oven to welder. The `MaterialController` creates a **ConsumableIssue** naming the `lot_id`, the `oven_id`, the `issued_to_welder_id`, and the `issued_kg` quantity. The issue is permitted only when the oven is `ONLINE` (otherwise `ERR_OVEN_NOT_ONLINE`), the lot is sitting `IN_OVEN` (otherwise `ERR_LOT_NOT_IN_OVEN`), and the lot's `remaining_kg` is at least the `issued_kg` requested (otherwise `ERR_INSUFFICIENT_LOT_QUANTITY`). The issue is born `OPEN` with `issued_at_utc` stamped from the shop clock; the lot's `remaining_kg` is drawn down by the issued mass and the lot moves to `ISSUED`. The lot's `process` must support the process of the WPS governing whatever joint the material is burned on — that compatibility is verified at the first weld pass rather than at issue time.

Returning an issue closes the exposure loop. The issue must still be `OPEN`; the return stamps `returned_at_utc` from the shop clock, moves the issue to `RETURNED`, and computes its `exposure_minutes` as the whole minutes elapsed between `issued_at_utc` and the return, discarding any partial minute. (While an issue is still open, its exposure is reckoned against the shop's current clock instead; either way the figure is integer minutes.) The returned issue's exposure is added to the lot's cumulative `exposed_minutes_total`, and the lot is then re-evaluated: if the lot is an `SMAW` low-hydrogen lot whose cumulative exposure has reached or exceeded 240 minutes — four hours of total atmospheric exposure — it is quarantined; otherwise it returns to `IN_OVEN` while any `remaining_kg` is left, or becomes `EXHAUSTED` once nothing remains. Exposure quarantine applies to `SMAW` lots only; other processes accumulate exposure without triggering it. Returns, like issues, require the oven to be `ONLINE` (`ERR_OVEN_NOT_ONLINE`).

A quarantined lot gets exactly one second chance. Rebaking — a `MaterialController` action — requires that the lot be `QUARANTINED` (otherwise `ERR_LOT_NOT_QUARANTINED`), that its `rebake_count` still be below 1, since AWS D1.1 permits at most one rebake (otherwise `ERR_LOT_REBAKE_LIMIT`), and that the oven referenced for the rebake be `ONLINE`. Rebaking increments `rebake_count`, resets `exposed_minutes_total` to 0, and returns the lot to `IN_OVEN`; because the lot is already inside the oven, no capacity check is performed. A lot that is quarantined while its `rebake_count` is already 1 has exhausted its rebake and remains `QUARANTINED` permanently.

Ovens themselves are toggled by the `MaterialController`. Taking an oven offline cascades through its contents: every lot in that oven whose status is `ISSUED` with an issue still `OPEN` is cascaded to `QUARANTINED`, and those open issues are voided to `VOID`. Lots sitting `IN_OVEN` remain `IN_OVEN`, but nothing may be issued from the oven until it is back online. Bringing the oven back online reverses the oven state with no further effects. Independently, whenever a lot's `remaining_kg` reaches zero — whether drawn down by an issue or consumed pass by pass — the system moves the lot to `EXHAUSTED`.

At weld-pass time the lot must be usable: a lot in `ISSUED` status may be consumed, while a lot that is `QUARANTINED`, `EXHAUSTED`, `CONSUMED`, or otherwise in the wrong state for the action is rejected with `ERR_LOT_NOT_USABLE`.

### 3.4. Fixtures, Shop Orders, and Weldments

Workholding is tracked as first-class tooling. A `ProductionPlanner` registers each fixture with a `fixture_code`, a `capacity_weldments` of at least 1 (the number of weldments the fixture can hold simultaneously), and an `owner_party` of `SHOP` or `CUSTOMER`, which determines disposition rights when the weldment closes out. A fixture is born `AVAILABLE`; its vocabulary is `AVAILABLE`, `RESERVED`, `IN_USE`, and `UNDER_REPAIR`. Reserving a fixture moves it from `AVAILABLE` to `RESERVED`. A reserved fixture may be released back to `AVAILABLE`, but only while no weldment in a non-terminal posture still references it. Once fabrication begins, the system itself moves the fixture from `RESERVED` to `IN_USE` the moment the first joint on a referencing weldment leaves `PENDING` for `IN_PROGRESS`; symmetrically, when the last non-terminal weldment on the fixture reaches `SHIPPED` or `CANCELLED`, the fixture returns from `IN_USE` to `AVAILABLE`. An `IN_USE` fixture may be sent for repair, moving it to `UNDER_REPAIR`, only once every weldment referencing it is in `SHIPPED` or `CANCELLED` posture.

Customer work enters as a **ShopOrder**, created by a `ProductionPlanner` with the customer's `po_number` (unique within the shop), the `customer_name`, and the contractual `promised_ship_date_utc`. An order is born `OPEN`; its status vocabulary is `OPEN`, `IN_PROGRESS`, `COMPLETE`, and `CANCELLED`.

Each physical assembly on the order is a **Weldment**, created under its order with a `weldment_serial` unique within that order, the `fixture_id` of the fixture that will hold it (required before any fabrication can start), and the `drawing_revision` it is built to. A weldment is born with `posture` `OPEN`; its posture vocabulary is `OPEN`, `RESTRICTED`, `FROZEN`, `REPAIR_REVIEW`, `SHIPPED`, and `CANCELLED`, and the terminal postures are `SHIPPED` and `CANCELLED`. Its audit counters all begin at zero — `repair_pass_count`, `total_pass_count`, `repair_rate_pct`, and `distortion_count` — and `signed_off_at_utc` stays null until the traveler is completed at shipment. Creating a weldment also advances its parent order from `OPEN` to `IN_PROGRESS` when the order was still `OPEN`. The weldment carries both `shop_id` and `shop_order_id` for direct addressability, and its `version` is the optimistic-concurrency anchor for weldment-level mutations.

### 3.5. Joint Fabrication and Weld-Pass Recording

A weldment is mapped into weldable **Joints** by the `WeldLead`, who creates each joint under its weldment with a `joint_number` matching the drawing, the `wps_id` of the governing WPS revision, the actual `base_metal_thickness_mm` at the joint, and the `required_ndt_methods` — a subset of `VT`, `UT`, and `RT`, with `VT` always implicitly required whether listed or not. A joint carries two parallel status dimensions from birth: `fabrication_status` begins at `PENDING` (vocabulary `PENDING`, `IN_PROGRESS`, `WELDED_OUT`, `ON_HOLD`, `CANCELLED`) while `inspection_status` begins at `NOT_READY` (vocabulary `NOT_READY`, `READY_FOR_VT`, `VT_PASSED`, `NDT_IN_PROGRESS`, `NDT_PASSED`, `NDT_FAILED`, `REPAIR_REQUIRED`, `REPAIR_WELDED_OUT`). The joint's `repair_cycle_count` starts at 0, and its `version` anchors optimistic concurrency for joint-level writes.

Starting fabrication is a `WeldLead` action guarded on five fronts, and the request must carry `expected_joint_version` matching the joint's current `version` — a stale version means the client has not observed the joint's true state (for example an `ON_HOLD` cascade) and is rejected with `ERR_STALE_VERSION` as described in §2.6. The joint must be `PENDING` in fabrication. Its parent weldment's `posture` must be `OPEN`: a weldment in `RESTRICTED`, `REPAIR_REVIEW`, or `FROZEN` posture blocks the start with `ERR_WELDMENT_NOT_OPEN`. The referenced WPS must be `APPROVED` at that moment — a superseded or still-draft document is rejected with `ERR_WPS_NOT_APPROVED`. The joint's `base_metal_thickness_mm` must lie within the WPS thickness envelope, meaning at least the WPS `thickness_min_mm` and at most its `thickness_max_mm`, boundaries inclusive (`ERR_JOINT_THICKNESS_OUTSIDE_WPS`). And the fixture referenced by the parent weldment must be `RESERVED` or `IN_USE`. A successful start moves `fabrication_status` to `IN_PROGRESS`, increments the joint's `version`, and — when this is the first fabrication activity on a weldment referencing the fixture — cascades the fixture from `RESERVED` to `IN_USE`.

With fabrication underway, welders record their work pass by pass. Recording a weld pass is the `Welder` role's exclusive write, performed under the welder's own entity identity per §2.1. The payload names the `welder_id`, the `qualification_id` of the qualification being exercised, the `consumable_lot_id` being burned, the `consumable_used_kg` consumed on the pass, and an `is_repair` flag marking whether the pass repairs a previously rejected region. Three gates guard the write. The qualification must be `QUALIFIED` with its `continuity_expires_at_utc` still in the future at the pass: a pass attempted at or after the expiry instant is rejected with `ERR_WELDER_CONTINUITY_LAPSED`. The lot must be usable — `ISSUED` and process-compatible with the joint's governing WPS — otherwise `ERR_LOT_NOT_USABLE`. And the parent weldment's `posture` must be `OPEN`, otherwise `ERR_WELDMENT_NOT_OPEN`. A recorded pass is stamped with `welded_at_utc` from the shop clock and fans out: the qualification's `last_weld_at_utc` advances to the clock and its continuity expiry is recomputed; the lot's `remaining_kg` is drawn down by `consumable_used_kg`; the weldment's `total_pass_count` increments by one, and its `repair_pass_count` increments by one when `is_repair` is true; the weldment's `repair_rate_pct` is recomputed (see §3.7) and the repair-review gate evaluated; and the first pass recorded on a joint moves that joint's `inspection_status` from `NOT_READY` to `READY_FOR_VT`. Each weld pass carries `shop_id` and `joint_id` for addressing.

When a joint's welding is complete, the `WeldLead` marks it welded out. The joint must be `IN_PROGRESS` in fabrication and must have at least one recorded weld pass (`ERR_NO_WELD_PASSES`); the parent weldment must again be `OPEN` (`ERR_WELDMENT_NOT_OPEN`). Welding out moves `fabrication_status` to `WELDED_OUT` and sets `inspection_status` to `READY_FOR_VT` when it is not already further along. The same action serves the repair loop with a tighter gate: for a joint in `REPAIR_REQUIRED`, welding out requires at least one weld pass with `is_repair` true recorded after the joint's most recent `NDT_FAILED` transition; the joint passes through the `REPAIR_WELDED_OUT` designation that marks a completed repair weld-out, and its `inspection_status` returns to `READY_FOR_VT` so the visual-then-NDT inspection loop repeats.

### 3.6. Inspection Hold Points and NDT Vendor Scheduling

Third-party examination capacity is modelled explicitly. The `ShopAdmin` registers each **NDT vendor** with a `vendor_name`, the `supported_methods` it can perform (a subset of `VT`, `UT`, and `RT`), and an `hourly_capacity` giving the number of concurrent inspection slots it can run per hour. A vendor is born `ACTIVE`; its status vocabulary is `ACTIVE` and `SUSPENDED`, and only an `ACTIVE` vendor may be scheduled.

Inspections are scheduled and recorded by the `CWI` role against a joint, supplying the `method` (`VT`, `UT`, or `RT`), the `scheduled_start_utc` and `scheduled_end_utc` of the slot (the end must be strictly after the start), and, depending on method, a `vendor_id`; a VT inspection may carry its `result` and `result_code` (an indication code such as `POROSITY`, `SLAG`, or `CRACK`) in the same call. Method discipline is strict — the method must be one of the three, a `VT` inspection is performed in-house so its `vendor_id` must be null, and a `UT` or `RT` inspection must name a vendor — with violations rejected as `ERR_INVALID_NDT_METHOD`. Each inspection records the performing inspector's identity as `inspector_user_id`, and each carries a `hold_point_released` flag, initially false, which is set true when the hold point is released and gates downstream fabrication on the joint.

Visual testing is the first hold point. Recording a VT inspection with a `PASS` result requires the joint's `inspection_status` to be `READY_FOR_VT`, and enforces segregation of duties: the inspector's `X-User-ID` must not equal any welder who recorded a pass on that joint (`ERR_SEGREGATION_OF_DUTIES`, HTTP 403). A passed VT either completes the joint's inspection obligations or opens the next one: when the joint's `required_ndt_methods` call for nothing beyond `VT`, the joint moves straight to `NDT_PASSED`; otherwise it moves to `VT_PASSED` and awaits its `UT` or `RT` examination.

Scheduling a `UT` or `RT` inspection requires the joint to be `VT_PASSED`, and books vendor capacity. The named vendor must be `ACTIVE` and must list the requested method among its `supported_methods`, otherwise `ERR_NDT_VENDOR_INVALID`. Capacity is enforced on overlapping bookings: the system counts the vendor's scheduled-but-not-yet-resulted inspections whose time windows overlap the new one — an existing booking overlaps when it starts before the new booking ends and ends after the new booking starts, on half-open intervals, so a booking that ends exactly when the new one begins does not conflict — and the new booking is accepted only while that overlap count is below the vendor's `hourly_capacity`, otherwise `ERR_NDT_VENDOR_SLOT_CONFLICT` (HTTP 409). A successfully scheduled `UT` or `RT` moves the joint's `inspection_status` to `NDT_IN_PROGRESS`. VT bookings, being in-house, perform no capacity check at all.

Results for `UT` and `RT` are recorded against the scheduled inspection once its slot has elapsed: the inspection's `result` must still be unset, and the shop clock must have reached the booking's `scheduled_end_utc` — recording earlier is rejected with `ERR_INSPECTION_TOO_EARLY`. Recording stamps `resulted_at_utc` from the clock and stores the `result` (`PASS` or `FAIL`) with its `result_code`. A `PASS` completes the method: once every method in the joint's `required_ndt_methods` has a passing inspection row, the joint's `inspection_status` becomes `NDT_PASSED`, and the passing inspection's `hold_point_released` is set true, releasing the hold point that gates downstream fabrication on the joint. A `FAIL` moves the joint to `NDT_FAILED`, increments the joint's `repair_cycle_count` by one, and triggers two further evaluations: if the count has exceeded the AWS D1.1 hard cap of two repair cycles, the joint is cancelled outright; and the parent weldment's freeze criteria are recomputed as described in §3.7.

### 3.7. Distortion, Repair Cycles, and Weldment Posture

Distortion is reported against a specific joint by a `QualityInspector`, who supplies the `joint_id`, the `measured_deviation_mm` observed, and the drawing's `tolerance_mm`. The report records the reporter's identity as `reported_by_user_id` and stamps `reported_at_utc` from the shop clock; its `disposition` begins at `PENDING`, with vocabulary `PENDING`, `REWORK`, `USE_AS_IS`, and `SCRAP`. Every report increments the parent weldment's `distortion_count` by one, and each report in turn feeds the weldment's derived posture.

The weldment's `posture` integrates four signals. While `OPEN`, the presence of at least one joint `ON_HOLD`, or of any distortion report still `PENDING`, derives `RESTRICTED`. Independently, the repair-rate gate watches `repair_rate_pct` — computed as one hundred times the weldment's `repair_pass_count` divided by its `total_pass_count`, rounded half-up to two decimal places, and defined as 0 when no passes exist. The rate is recomputed on every weld-pass insert or removal, and the gate's boundary is inclusive: the moment the weldment-scoped `repair_rate_pct` reaches or exceeds the shop's `repair_rate_limit_pct`, an `OPEN` weldment moves to `REPAIR_REVIEW`. (The same formula is also computed scoped to a single joint's passes for joint-level display and audit reporting; only the weldment-scoped aggregate drives the contractual gate.) While a weldment sits in `REPAIR_REVIEW`, no joint may newly enter `IN_PROGRESS` fabrication — start-fabrication, weld-pass recording, and weld-out are all rejected with `ERR_WELDMENT_NOT_OPEN`. A `QCManager` clears the review once the weldment is in `REPAIR_REVIEW` posture and every distortion report on it has a `disposition` other than `PENDING`; clearing increments the weldment's `version` and returns it to `OPEN`. A `RESTRICTED` weldment returns to `OPEN` on its own once the last `PENDING` distortion report has been dispositioned and no joint remains `ON_HOLD`.

The most severe posture is `FROZEN`, derived when two conditions coincide on an `OPEN` weldment: at least one joint carries `inspection_status` `NDT_FAILED`, and the weldment's `distortion_count` has reached at least 2 (the boundary is inclusive). Freezing voids every in-flight inspection booking against the weldment's joints — scheduled inspections that have not yet been resulted are discarded and their vendor slots released. A `QCManager` unfreezes the weldment once it is `FROZEN` and every `NDT_FAILED` joint has been moved on to `REPAIR_REQUIRED` or `REPAIR_WELDED_OUT`; unfreezing increments the weldment's `version` and returns it to `OPEN`.

Repair work re-enters the loop through the `QCManager`, who declares a repair on a joint whose `inspection_status` is `NDT_FAILED`. The declaration moves the joint to `REPAIR_REQUIRED` and re-opens its `fabrication_status` to `IN_PROGRESS` so repair passes can be welded. The AWS D1.1 repair-cycle hard cap applies here directly: declaring a repair that would push the joint beyond its two-cycle budget is rejected with `ERR_REPAIR_CYCLE_LIMIT` — and, per §3.6, a failure recorded while the count already stands at two cancels the joint outright. Joints placed `ON_HOLD` by the WPS-supersession cascade of §3.1 are recovered by the `QCManager` through rebinding: the joint must currently be `ON_HOLD` in fabrication, the supplied `new_wps_id` must reference an `APPROVED` WPS in the same shop (otherwise `ERR_WPS_NOT_APPROVED`), and the joint's `base_metal_thickness_mm` must fall within the new document's thickness envelope, boundaries inclusive (otherwise `ERR_JOINT_THICKNESS_OUTSIDE_WPS`). Rebinding rewrites the joint's `wps_id`, returns `fabrication_status` to `PENDING`, and recomputes the parent weldment's posture — a `RESTRICTED` weldment returns to `OPEN` when no other holds or pending reports remain.

Dispositioning resolves a distortion report. A `QCManager` supplies the `disposition`, which must be one of `REWORK`, `USE_AS_IS`, or `SCRAP` — anything else is rejected with `ERR_INVALID_DISPOSITION`. Scrapping the distorted work cascades the parent weldment to `CANCELLED`. When the last `PENDING` report on a weldment is dispositioned and no joint remains `ON_HOLD`, the weldment's posture recomputes from `RESTRICTED` back to `OPEN`.

### 3.8. Traveler Sign-Off, Shipment, and Order Completion

The traveler is the weldment's paper of record. Sign-offs are recorded per step, with `step_code` drawn from `FIT_UP`, `WELD_OUT`, `VT`, `NDT`, and `FINAL`. The signatory's identity is stamped as `signed_by_user_id`, `signed_at_utc` is taken from the shop clock, and free-form `notes` may accompany the entry. Signing authority is split per §2.1: the `WeldLead` signs `FIT_UP` and `WELD_OUT`, the `QualityInspector` signs `VT` and `NDT`, and the `CWI` signs `VT`, `NDT`, and `FINAL`. Signing the `FINAL` step verifies that all prior steps already exist on the weldment's traveler.

Shipment closes the weldment. Shipping is the `ShippingClerk`'s exclusive write and carries the optimistic-concurrency field `expected_weldment_version` per §2.6 — a weldment whose `version` has advanced since the clerk last read it (a late inspection result or disposition is enough) rejects the ship with `ERR_STALE_VERSION`. The weldment's `posture` must be `OPEN` (otherwise `ERR_WELDMENT_NOT_OPEN`); every joint on it must be `WELDED_OUT` in fabrication (otherwise `ERR_JOINTS_NOT_WELDED_OUT`); every joint must be `NDT_PASSED` in inspection (otherwise `ERR_JOINTS_NOT_NDT_PASSED`); and all five traveler steps — `FIT_UP`, `WELD_OUT`, `VT`, `NDT`, and `FINAL` — must be present (otherwise `ERR_TRAVELER_INCOMPLETE`). Finally the fixture must be dispositioned for close-out: when the referenced fixture's `owner_party` is `CUSTOMER`, a release-to-customer record must exist for it, and when `SHOP`, the fixture must be standing `AVAILABLE` or `IN_USE` — otherwise `ERR_FIXTURE_NOT_DISPOSITIONED`. A successful ship moves the posture to `SHIPPED`, stamps `signed_off_at_utc` from the shop clock, increments the weldment's `version`, and cascades in both directions: if this was the last non-terminal weldment on its fixture, the fixture returns from `IN_USE` to `AVAILABLE`; and when every weldment on the parent order is `SHIPPED`, the order moves from `IN_PROGRESS` to `COMPLETE`.

A weldment may instead be cancelled by a `ProductionPlanner`, but only while no weld passes exist against any of its joints — a weldment with recorded passes is rejected with `ERR_WELDMENT_HAS_PASSES`. Cancellation moves the posture from `OPEN` to `CANCELLED`, cancels every non-terminal joint on the weldment, voids its in-flight inspections, and runs the same fixture cascade as a shipment.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — including state-transition actions such as approvals, shipment, returns, and clock advancement — return `200 OK`. All reads return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/weld-shop/_clock/set_current_utc` | Set the shop logical clock (startup default 2026-08-01T00:00:00Z) | ShopAdmin |
| POST | `/weld-shop/shops` | Create a shop | ShopAdmin |
| GET | `/weld-shop/shops/{id}` | Get a shop | Any |
| POST | `/weld-shop/shops/{id}/welders` | Create a welder | ShopAdmin |
| GET | `/weld-shop/shops/{id}/welders` | List welders | Any |
| GET | `/weld-shop/shops/{id}/welders/{welderId}` | Get a welder | Any |
| POST | `/weld-shop/shops/{id}/ndt-vendors` | Create an NDT vendor | ShopAdmin |
| GET | `/weld-shop/shops/{id}/ndt-vendors` | List NDT vendors | Any |
| POST | `/weld-shop/shops/{id}/ovens` | Create an oven | MaterialController |
| GET | `/weld-shop/shops/{id}/ovens` | List ovens | Any |
| POST | `/weld-shop/shops/{id}/ovens/{ovenId}/take-offline` | Take an oven offline; cascades lot quarantine and voids open issues | MaterialController |
| POST | `/weld-shop/shops/{id}/ovens/{ovenId}/bring-online` | Bring an oven online | MaterialController |
| POST | `/weld-shop/shops/{id}/pqrs` | Create a PQR | QCManager |
| GET | `/weld-shop/shops/{id}/pqrs` | List PQRs | Any |
| GET | `/weld-shop/shops/{id}/pqrs/{pqrId}` | Get a PQR | Any |
| POST | `/weld-shop/shops/{id}/pqrs/{pqrId}/approve` | Approve a PQR | QCManager |
| POST | `/weld-shop/shops/{id}/pqrs/{pqrId}/reject` | Reject a PQR | QCManager |
| POST | `/weld-shop/shops/{id}/wps` | Create a WPS revision | QCManager |
| GET | `/weld-shop/shops/{id}/wps` | List WPS revisions | Any |
| GET | `/weld-shop/shops/{id}/wps/{wpsId}` | Get a WPS revision | Any |
| POST | `/weld-shop/shops/{id}/wps/{wpsId}/approve` | Approve a WPS revision (OCC-gated; triggers the supersession cascade) | QCManager |
| POST | `/weld-shop/shops/{id}/wps/{wpsId}/reject` | Reject a WPS revision | QCManager |
| POST | `/weld-shop/shops/{id}/welder-qualifications` | Create a welder qualification | QCManager |
| GET | `/weld-shop/shops/{id}/welder-qualifications` | List welder qualifications (filter by `welder_id` or `wps_id`) | Any |
| GET | `/weld-shop/shops/{id}/welder-qualifications/{qualId}` | Get a welder qualification | Any |
| POST | `/weld-shop/shops/{id}/welder-qualifications/{qualId}/requalify` | Requalify a `LAPSED` qualification | QCManager |
| POST | `/weld-shop/shops/{id}/welder-qualifications/{qualId}/revoke` | Revoke a qualification | QCManager |
| POST | `/weld-shop/shops/{id}/consumable-lots` | Receive a consumable lot into an oven | MaterialController |
| GET | `/weld-shop/shops/{id}/consumable-lots` | List consumable lots (filter by `oven_id` or `status`) | Any |
| GET | `/weld-shop/shops/{id}/consumable-lots/{lotId}` | Get a consumable lot | Any |
| POST | `/weld-shop/shops/{id}/consumable-lots/{lotId}/rebake` | Rebake a quarantined lot (at most once) | MaterialController |
| POST | `/weld-shop/shops/{id}/consumable-issues` | Issue consumables from an oven to a welder | MaterialController |
| GET | `/weld-shop/shops/{id}/consumable-issues` | List consumable issues (filter by `lot_id` or `issued_to_welder_id`) | Any |
| POST | `/weld-shop/shops/{id}/consumable-issues/{issueId}/return` | Return unused consumables; accumulates exposure | MaterialController |
| POST | `/weld-shop/shops/{id}/fixtures` | Create a fixture | ProductionPlanner |
| GET | `/weld-shop/shops/{id}/fixtures` | List fixtures | Any |
| POST | `/weld-shop/shops/{id}/fixtures/{fixtureId}/reserve` | Reserve a fixture | ProductionPlanner |
| POST | `/weld-shop/shops/{id}/fixtures/{fixtureId}/release` | Release a reserved fixture | ProductionPlanner |
| POST | `/weld-shop/shops/{id}/fixtures/{fixtureId}/send-for-repair` | Send an `IN_USE` fixture for repair | ProductionPlanner |
| POST | `/weld-shop/shops/{id}/shop-orders` | Create a shop order | ProductionPlanner |
| GET | `/weld-shop/shops/{id}/shop-orders` | List shop orders | Any |
| GET | `/weld-shop/shops/{id}/shop-orders/{orderId}` | Get a shop order | Any |
| POST | `/weld-shop/shops/{id}/shop-orders/{orderId}/weldments` | Create a weldment under an order | ProductionPlanner |
| GET | `/weld-shop/shops/{id}/shop-orders/{orderId}/weldments` | List weldments under an order | Any |
| GET | `/weld-shop/shops/{id}/weldments/{weldmentId}` | Get a weldment | Any |
| POST | `/weld-shop/shops/{id}/weldments/{weldmentId}/ship` | Ship a weldment (OCC-gated) | ShippingClerk |
| POST | `/weld-shop/shops/{id}/weldments/{weldmentId}/cancel` | Cancel a weldment | ProductionPlanner |
| POST | `/weld-shop/shops/{id}/weldments/{weldmentId}/clear-repair-review` | Clear the `REPAIR_REVIEW` posture | QCManager |
| POST | `/weld-shop/shops/{id}/weldments/{weldmentId}/unfreeze` | Unfreeze a `FROZEN` weldment | QCManager |
| POST | `/weld-shop/shops/{id}/weldments/{weldmentId}/joints` | Create a joint | WeldLead |
| GET | `/weld-shop/shops/{id}/weldments/{weldmentId}/joints` | List joints under a weldment | Any |
| GET | `/weld-shop/shops/{id}/joints/{jointId}` | Get a joint | Any |
| POST | `/weld-shop/shops/{id}/joints/{jointId}/start-fabrication` | Start fabrication on a joint (OCC-gated) | WeldLead |
| POST | `/weld-shop/shops/{id}/joints/{jointId}/weld-out` | Mark a joint welded out | WeldLead |
| POST | `/weld-shop/shops/{id}/joints/{jointId}/declare-repair` | Declare a repair after an NDT failure | QCManager |
| POST | `/weld-shop/shops/{id}/joints/{jointId}/rebind-wps` | Rebind an `ON_HOLD` joint to a new approved WPS | QCManager |
| POST | `/weld-shop/shops/{id}/joints/{jointId}/weld-passes` | Record a weld pass | Welder |
| GET | `/weld-shop/shops/{id}/joints/{jointId}/weld-passes` | List weld passes for a joint | Any |
| POST | `/weld-shop/shops/{id}/weldments/{weldmentId}/distortion-reports` | Report distortion against a joint | QualityInspector |
| GET | `/weld-shop/shops/{id}/weldments/{weldmentId}/distortion-reports` | List distortion reports for a weldment | Any |
| POST | `/weld-shop/shops/{id}/distortion-reports/{reportId}/disposition` | Disposition a distortion report (`REWORK` / `USE_AS_IS` / `SCRAP`) | QCManager |
| POST | `/weld-shop/shops/{id}/joints/{jointId}/inspections` | Schedule or record an inspection (VT in-house; UT/RT via vendor) | CWI |
| GET | `/weld-shop/shops/{id}/joints/{jointId}/inspections` | List inspections for a joint | Any |
| GET | `/weld-shop/shops/{id}/inspections/{inspectionId}` | Get an inspection | Any |
| POST | `/weld-shop/shops/{id}/inspections/{inspectionId}/record-result` | Record a UT/RT result | CWI |
| POST | `/weld-shop/shops/{id}/weldments/{weldmentId}/traveler-sign-offs` | Record a traveler sign-off step | CWI, WeldLead, QualityInspector |
| GET | `/weld-shop/shops/{id}/weldments/{weldmentId}/traveler-sign-offs` | List traveler sign-offs for a weldment | Any |
| GET | `/weld-shop/welders/{welderId}` | Get a welder by id (flat) | Any |
| GET | `/weld-shop/welders` | List welders filtered by `shop_id` | Any |
| GET | `/weld-shop/ndt-vendors/{vendorId}` | Get an NDT vendor by id (flat) | Any |
| GET | `/weld-shop/ndt-vendors` | List NDT vendors filtered by `shop_id` | Any |
| GET | `/weld-shop/ovens/{ovenId}` | Get an oven by id (flat) | Any |
| GET | `/weld-shop/ovens` | List ovens filtered by `shop_id` | Any |
| GET | `/weld-shop/pqrs/{pqrId}` | Get a PQR by id (flat) | Any |
| GET | `/weld-shop/pqrs` | List PQRs filtered by `shop_id` | Any |
| GET | `/weld-shop/wps/{wpsId}` | Get a WPS revision by id (flat) | Any |
| GET | `/weld-shop/wps` | List WPS revisions filtered by `shop_id`, `pqr_id`, or `superseded_by_id` | Any |
| GET | `/weld-shop/welder-qualifications/{qualId}` | Get a qualification by id (flat) | Any |
| GET | `/weld-shop/welder-qualifications` | List qualifications filtered by `shop_id`, `welder_id`, or `wps_id` | Any |
| GET | `/weld-shop/consumable-lots/{lotId}` | Get a lot by id (flat) | Any |
| GET | `/weld-shop/consumable-lots` | List lots filtered by `shop_id`, `oven_id`, or `status` | Any |
| GET | `/weld-shop/consumable-issues/{issueId}` | Get an issue by id (flat) | Any |
| GET | `/weld-shop/consumable-issues` | List issues filtered by `shop_id`, `lot_id`, `oven_id`, or `issued_to_welder_id` | Any |
| GET | `/weld-shop/fixtures/{fixtureId}` | Get a fixture by id (flat) | Any |
| GET | `/weld-shop/fixtures` | List fixtures filtered by `shop_id` | Any |
| GET | `/weld-shop/shop-orders/{orderId}` | Get a shop order by id (flat) | Any |
| GET | `/weld-shop/shop-orders` | List shop orders filtered by `shop_id` | Any |
| GET | `/weld-shop/weldments/{weldmentId}` | Get a weldment by id (flat) | Any |
| GET | `/weld-shop/weldments` | List weldments filtered by `shop_id`, `shop_order_id`, or `fixture_id` | Any |
| GET | `/weld-shop/joints/{jointId}` | Get a joint by id (flat) | Any |
| GET | `/weld-shop/joints` | List joints filtered by `shop_id`, `weldment_id`, or `wps_id` | Any |
| GET | `/weld-shop/weld-passes/{passId}` | Get a weld pass by id (flat) | Any |
| GET | `/weld-shop/weld-passes` | List weld passes filtered by `shop_id`, `joint_id`, `welder_id`, `qualification_id`, or `consumable_lot_id` | Any |
| GET | `/weld-shop/distortion-reports/{reportId}` | Get a distortion report by id (flat) | Any |
| GET | `/weld-shop/distortion-reports` | List distortion reports filtered by `shop_id`, `weldment_id`, or `joint_id` | Any |
| GET | `/weld-shop/inspections/{inspectionId}` | Get an inspection by id (flat) | Any |
| GET | `/weld-shop/inspections` | List inspections filtered by `shop_id`, `joint_id`, or `vendor_id` | Any |
| GET | `/weld-shop/traveler-sign-offs/{signoffId}` | Get a traveler sign-off by id (flat) | Any |
| GET | `/weld-shop/traveler-sign-offs` | List traveler sign-offs filtered by `shop_id` or `weldment_id` | Any |

## 5. Error Code Catalogue

Trigger conditions for each error are described in the narratives of §2 and §3; this catalogue is the canonical identifier-to-status mapping.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_PQR_NOT_DRAFT` | 409 Conflict |
| `ERR_INVALID_THICKNESS_RANGE` | 422 Unprocessable Entity |
| `ERR_WPS_NOT_DRAFT` | 409 Conflict |
| `ERR_PQR_NOT_APPROVED` | 422 Unprocessable Entity |
| `ERR_WPS_PQR_PROCESS_MISMATCH` | 422 Unprocessable Entity |
| `ERR_WPS_PQR_MATERIAL_MISMATCH` | 422 Unprocessable Entity |
| `ERR_WPS_THICKNESS_OUTSIDE_PQR` | 422 Unprocessable Entity |
| `ERR_WPS_REVISION_CONFLICT` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_WPS_NOT_APPROVED` | 422 Unprocessable Entity |
| `ERR_JOINT_THICKNESS_OUTSIDE_WPS` | 422 Unprocessable Entity |
| `ERR_QUAL_NOT_LAPSED` | 409 Conflict |
| `ERR_WELDER_TERMINATED` | 422 Unprocessable Entity |
| `ERR_WELDER_CONTINUITY_LAPSED` | 422 Unprocessable Entity |
| `ERR_OVEN_NOT_ONLINE` | 409 Conflict |
| `ERR_OVEN_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_LOT_NOT_IN_OVEN` | 409 Conflict |
| `ERR_LOT_NOT_USABLE` | 422 Unprocessable Entity |
| `ERR_LOT_NOT_QUARANTINED` | 409 Conflict |
| `ERR_LOT_REBAKE_LIMIT` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_LOT_QUANTITY` | 422 Unprocessable Entity |
| `ERR_NDT_VENDOR_INVALID` | 422 Unprocessable Entity |
| `ERR_NDT_VENDOR_SLOT_CONFLICT` | 409 Conflict |
| `ERR_INSPECTION_TOO_EARLY` | 422 Unprocessable Entity |
| `ERR_REPAIR_CYCLE_LIMIT` | 422 Unprocessable Entity |
| `ERR_WELDMENT_NOT_OPEN` | 409 Conflict |
| `ERR_WELDMENT_HAS_PASSES` | 409 Conflict |
| `ERR_JOINTS_NOT_WELDED_OUT` | 409 Conflict |
| `ERR_JOINTS_NOT_NDT_PASSED` | 409 Conflict |
| `ERR_TRAVELER_INCOMPLETE` | 409 Conflict |
| `ERR_FIXTURE_NOT_DISPOSITIONED` | 409 Conflict |
| `ERR_NO_WELD_PASSES` | 409 Conflict |
| `ERR_INVALID_DISPOSITION` | 422 Unprocessable Entity |
| `ERR_INVALID_NDT_METHOD` | 422 Unprocessable Entity |
