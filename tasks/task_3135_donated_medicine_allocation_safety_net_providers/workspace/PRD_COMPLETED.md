# Donated Medicine Allocation API — Product Requirements Document

## 1. Introduction

Safety-net health programs depend on a steady pipeline of donated pharmaceuticals: manufacturers and wholesalers surplus usable product, and free clinics, federally qualified health centers, rural health centers, hospital charity pharmacies, and disaster-response organizations depend on that supply to serve patients who otherwise could not afford treatment. Getting this right is not merely a logistics problem. Every donated unit carries expiration dating, cold-chain storage bands, restricted-use conditions, and — in the case of controlled substances — regulatory registration obligations on both the donating and receiving side. Mistakes cost patient safety, donor goodwill, and charitable-tax deductibility.

This document specifies the Donated Medicine Allocation API, mounted under `/medicine-relief`. The system manages the full lifecycle of donated product: intake of manufacturer lots into quarantine, quality-assurance release and recall, qualification of recipient sites against verified licensure, need-scored allocation decisions that commit lot quantities against a request, temperature-controlled and customs-cleared shipment, emergency-event surge handling with pre-positioned relief modules, donor-facing valuation reporting, and recipient-side distribution reporting on units dispensed and patients reached.

The architecture is deliberately audit-friendly. Allocation authority, logistics authority, compliance authority, quality-assurance authority, and recipient-side operational authority are held by segregated roles, and several state transitions (notably decision finalization and site suspension) are guarded by optimistic concurrency checks so that one officer can never act on a stale view of a record another officer has already advanced.

## 2. Global Specifications & System-Wide Principles

This section defines the contract-level rules every endpoint obeys. Business-specific workflow rules live in §3; §4 enumerates the HTTP surface; §5 catalogues the error identifiers.

### 2.1. User and Role-Based Access Control

Every request to the API must present two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, identifying the role under which the user is acting. A request missing either header, or presenting an empty or blank value, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). Once authenticated, the server consults the role matrix; if the named role is not permitted to invoke the targeted endpoint, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403) — a syntactically non-empty role string that is not one of the eight recognized roles is treated as an unauthorized role and likewise draws `ERR_FORBIDDEN_ROLE`, not `ERR_UNAUTHENTICATED`. Authentication precedes authorization in evaluation order.

The system recognizes eight roles, spelled exactly as follows: `PlatformAdmin`, `QAPharmacist`, `ComplianceOfficer`, `AllocationOfficer`, `LogisticsCoordinator`, `SiteCoordinator`, `EmergencyManager`, and `DonorReportingOfficer`.

Identity semantics differ across roles. For `SiteCoordinator`, `X-User-ID` is the `id` of the acting `RecipientSite`-affiliated user; ownership checks on resources that reference a site (shipment delivery confirmation, distribution-report creation and submission, allocation-request cancellation) compare the resource's site foreign key — or, for allocation requests, the `requested_by_user_id` recorded at submission — to `X-User-ID`. For the remaining seven roles (`PlatformAdmin`, `QAPharmacist`, `ComplianceOfficer`, `AllocationOfficer`, `LogisticsCoordinator`, `EmergencyManager`, `DonorReportingOfficer`), `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it on entities where a transition writes it (for example, `reviewer_user_id` on an `AllocationDecision`, `reviewed_by_user_id` on a `DistributionReport`, `submitted_by_user_id` on a `DistributionReport`, or `requested_by_user_id` on an `AllocationRequest`) but does not compare it to any entity's `id`.

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

List endpoints accept two query parameters. The `limit` parameter sets the page size: it defaults to 10, with a minimum of 1 and a maximum of 100; values outside that range are clamped to the nearest bound rather than rejected. The `offset` parameter sets how many records to skip and defaults to 0; a negative offset is clamped to 0. A `limit` or `offset` value that is not parseable as an integer is rejected with `ERR_INVALID_REQUEST` (HTTP 400). The `meta` object of a paginated list response carries `limit`, `offset`, `total_count`, and `has_more`, where `has_more` is true exactly when `offset + limit` is less than `total_count`. Unless otherwise specified, list endpoints return resources sorted by `created_at` in ascending order (equivalently, in insertion order).

List endpoints are filterable by exact-match query parameters on the resource's own fields; a filter parameter that is absent does not constrain the result. The supported filters are: donors — `status`, `country_code`; lots — `donor_id`, `lot_posture`, `product_class`, `ndc_code`; sites — `qualification_status`, `country_code`, `site_type`; licenses — `site_id`, `verification_status`, `license_type`; allocation requests — `site_id`, `status`, `ndc_code`, `emergency_event_id`; allocation decisions — `request_id`, `status`; allocation lines — `decision_id`, `lot_id`, `status`; shipments — `site_id`, `status`, `allocation_decision_id`, `customs_declaration_id`; customs declarations — `shipment_id`, `status`, `import_license_id`; emergency events — `status`, `severity`; prepositioned modules — `status`, `intended_use`, `holding_country_code`, `reserved_for_event_id`; valuation snapshots — `donor_id`, `snapshot_period`, `method`; distribution reports — `site_id`, `shipment_id`, `status`, `reporting_period`.

### 2.4. The Logical Clock

The server maintains a logical clock, not wall-clock time. Before any operator action, the logical clock reads exactly `2026-09-01T00:00:00Z`. A `PlatformAdmin` may set it to an arbitrary ISO 8601 UTC instant — ahead of or behind the current reading — by supplying a `current_utc` value; the clock never falls back to wall-clock time afterwards. The clock-set endpoint returns `200 OK` with a `data` object of the form `{"current_utc": "<the new reading, ISO 8601 UTC>"}`. All expiration dating, license expiry, reservation TTLs, surge windows, and reporting-period logic read from this clock. Advancing the clock triggers a sweep that expires overdue lots, expires overdue licenses, forfeits overdue allocation-line reservations, and stands down emergency events whose surge windows have closed. Each of these cascades is described in §3. Timestamps taken from the logical clock (`intake_recorded_at`, `qualified_at`, `decided_at`, `reservation_expires_at`, `dispatched_at`, `delivered_at`, `declared_at`, `surge_window_ends_at`, `generated_at`) are rendered in ISO 8601 UTC, omitting fractional seconds when the fraction is zero.

### 2.5. Common Resource Properties

Every top-level resource in this system (`ManufacturerDonor`, `ProductLot`, `RecipientSite`, `License`, `AllocationRequest`, `AllocationDecision`, `AllocationLine`, `Shipment`, `CustomsDeclaration`, `EmergencyEvent`, `PrepositionedModule`, `ValuationSnapshot`, `DistributionReport`) carries a standard envelope of system-managed fields:

- `id` — a server-minted UUID with no type prefix, rendered in the standard canonical form of five hyphen-separated hexadecimal groups (8-4-4-4-12, e.g. `3f6b2a1e-1234-4cde-9ab0-0123456789ab`).
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, set at creation and never modified.
- `updated_at` — an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` — an integer starting at 1 that increments by 1 on every mutation. This is the field consulted by the optimistic concurrency checks described in §2.6.

### 2.6. Optimistic Concurrency Control

Two write endpoints carry an optimistic-concurrency input field; no other endpoint takes a version field.

Finalizing an allocation decision requires the request body to include `expected_request_version`, carrying the client's last-observed `version` of the target `AllocationRequest`. If the field is absent, or the request's current `version` no longer matches — because another writer has advanced the request since the client last read it — the finalize is rejected with `ERR_STALE_VERSION` (HTTP 412). Suspension of a recipient site accepts an optional `expected_site_version`, carrying the client's last-observed `version` of the target `RecipientSite`; when the field is supplied and does not match, the suspension is rejected with `ERR_STALE_VERSION` (HTTP 412), and when it is omitted the suspension proceeds without a version check. The stale-version check is framed purely as a consistency guard against acting on an outdated snapshot: the error surfaces whenever the named parent entity's `version` has moved on from what the caller saw.

### 2.7. Validation Ordering

Every endpoint applies its guards in a fixed priority order, so that earlier failures mask later ones. Request-payload parsing comes first, ahead of the numbered sequence: missing or ill-typed body fields, enum violations, unparsable date or datetime strings, and out-of-range scalar inputs (such as `severity` outside 1–5 or `underserved_index` outside 0.0–1.0) are rejected with `ERR_INVALID_REQUEST` (HTTP 400) as the body is read, and the positive-integer guards on `quantity_received` and `quantity_requested` are rejected with `ERR_QUANTITY_INVALID` (HTTP 422) at the same stage. The order of the remaining guards is: (1) authentication of the `X-User-ID` / `X-User-Role` headers, rejected with `ERR_UNAUTHENTICATED`; (2) role authorization, rejected with `ERR_FORBIDDEN_ROLE`; (3) existence of every resource id referenced in path or body, rejected with `ERR_NOT_FOUND`; (4) ownership on the ownership-guarded endpoints, rejected with `ERR_FORBIDDEN_OWNERSHIP`; (5) state-machine permissibility, rejected with `ERR_INVALID_STATE`; (6) the OCC check on decision finalization, rejected with `ERR_STALE_VERSION`; (7) the OCC check on site suspension, also rejected with `ERR_STALE_VERSION`. Business-safety checks follow: (8) controlled-product authorization, (9) cold-chain capability, (10) lot releasability, (11) import-license presence, (12) verified-license presence at site qualification or reinstatement, (13) license expiry at verification, (14) decision quantity bounds, (15) site qualification, (16) donor active status, (17) module regional eligibility, (18) segregation of duties on distribution-report review, (19) lot availability sufficiency, (20) distribution-report overreporting, (21) customs declared-value positivity. Finally come referential checks: (22) malformed-request rejection with `ERR_INVALID_REQUEST`, (23) emergency-event reference validity with `ERR_EMERGENCY_NOT_ACTIVE`, (24) temperature-band compatibility with `ERR_INCOMPATIBLE_TEMPERATURE_BANDS`, (25) cold-chain packing with `ERR_COLD_CHAIN_PACK_REQUIRED`, and (26) customs clearance at dispatch with `ERR_CUSTOMS_NOT_CLEARED`. Where an endpoint narrative in §3 enumerates its own explicit check sequence (as §3.5 does for finalization), that endpoint-specific sequence is authoritative for that endpoint.

### 2.8. Quantity Ledger Invariants

Every `ProductLot` maintains five quantity counters: `quantity_received` (fixed at intake), `quantity_quarantined`, `quantity_committed`, `quantity_shipped`, and `quantity_expired`. The system derives `quantity_available` as the received count minus the quarantined, committed, shipped, and expired counts. This derived value must never go negative; any mutation that would drive it below zero is rejected with `ERR_INSUFFICIENT_AVAILABLE` (HTTP 409). The counters move together — when units leave one bucket they enter another, so the available figure always reconciles. Integer units are used throughout with no rounding.

### 2.9. Cold-Chain and Controlled-Product Protocols

Two safety regimes cut across intake, allocation, and shipment. **Controlled products** (a `ProductLot` whose `product_class` is `CONTROLLED`) may be accepted only from a `ManufacturerDonor` whose `dea_registration_no` is non-empty, and may be allocated only to a `RecipientSite` whose `has_dea_registration` is true; violations surface as `ERR_CONTROLLED_DONOR_UNREGISTERED` (at intake or release) or `ERR_CONTROLLED_SITE_NOT_AUTHORIZED` (at decision finalization), both HTTP 422. **Cold-chain products** (a lot whose `product_class` is `COLD_CHAIN`, surfaced as the derived boolean `requires_cold_chain`) may be allocated only to a site whose `cold_storage_capacity_l` is greater than zero — otherwise `ERR_COLD_CHAIN_INADEQUATE` (HTTP 422) — and any shipment containing such a lot must be packed with a validated cold shipper, with `packed_with_cold_shipper` set to true; otherwise `ERR_COLD_CHAIN_PACK_REQUIRED` (HTTP 422) at pack completion.

### 2.10. Nested Resource Retrieval and Hierarchy Validation

Where an operation references multiple resources — for example, a shipment scoped to a decision scoped to a request scoped to a site — the server validates identifiers in left-to-right order, returning `ERR_NOT_FOUND` (HTTP 404) for the first id that does not resolve. A reference to a resource under a non-existent parent therefore fails on the parent before any child check is attempted. Path variables across the API follow the resource naming convention: `{donor_id}` for donors, `{lot_id}` for lots, `{site_id}` for sites, `{license_id}` for licenses, `{request_id}` for allocation requests, `{decision_id}` for allocation decisions, `{line_id}` for allocation lines, `{shipment_id}` for shipments, `{declaration_id}` for customs declarations, `{event_id}` for emergency events, `{module_id}` for pre-positioned modules, `{snapshot_id}` for valuation snapshots, and `{report_id}` for distribution reports.

### 2.11. Precision and Rounding

Monetary values are computed in decimal arithmetic and rounded half-up to two decimal places wherever the system stores or returns a dollar figure (`unit_acquisition_value_usd`, `unit_wholesale_value_usd`, `declared_value_usd`, `total_value_usd`). Both aggregation calculations that sum per-unit values — the donor valuation snapshot and the customs declared value — round each line's contribution to two decimal places *before* summing; summing raw products and rounding once at the end produces different cents, and this specification pins the per-line-then-sum order. The need score is likewise rounded half-up to two decimal places. Temperature bands are stored to a single decimal place of Celsius.

## 3. Business Logic & Workflows

### 3.1. Donor Onboarding and Lot Intake

A `PlatformAdmin` registers a `ManufacturerDonor` by supplying the organization's `legal_name`, the two-letter ISO `country_code` of the donating entity, a `tax_id` used on valuation and donation reports, and — when the donor intends to contribute controlled substances — a `dea_registration_no` (optional at registration). New donors enter with `status` set to `ACTIVE` and `version` at 1. A donor may later be moved to `SUSPENDED` — permitted only from `ACTIVE` — which blocks new lot intake and quarantined-lot release with `ERR_DONOR_NOT_ACTIVE` (HTTP 409), or permanently to `DEACTIVATED`, permitted from either `ACTIVE` or `SUSPENDED`; attempting either transition from an ineligible status (including deactivating an already `DEACTIVATED` donor) is rejected with `ERR_INVALID_STATE` (HTTP 409).

Lot intake is performed by a `PlatformAdmin` or `QAPharmacist` via a payload naming the `donor_id`, the product's `ndc_code` and `product_name`, its `product_class` (one of `STANDARD`, `COLD_CHAIN`, `CONTROLLED`, `RESTRICTED_USE`), its `dosage_form` (one of `TABLET`, `CAPSULE`, `VIAL`, `AMPOULE`, `SYRUP`, `CREAM`, `DEVICE`), the `unit_of_measure` (`UNIT`, `VIAL`, `PACK`, or `BOX`), the `quantity_received` (a positive integer — zero or negative values are rejected with `ERR_QUANTITY_INVALID`, HTTP 422), the manufacturer-stamped `expiration_date`, the storage band `storage_temp_min_c` and `storage_temp_max_c` in Celsius, any `restricted_use_conditions` as a free-form list (for example hospital-only or not-for-retail; the field is optional and defaults to an empty list), and the two per-unit valuation references `unit_acquisition_value_usd` and `unit_wholesale_value_usd`. Every lot enters in `QUARANTINED` posture: `quantity_quarantined` is initialized to `quantity_received`, `quantity_committed`, `quantity_shipped`, and `quantity_expired` are initialized to zero, `quantity_available` remains zero, and `intake_recorded_at` is stamped from the logical clock. If the donor is not `ACTIVE`, intake is rejected with `ERR_DONOR_NOT_ACTIVE`. If the lot's class is `CONTROLLED` and the donor's `dea_registration_no` is empty, intake is rejected with `ERR_CONTROLLED_DONOR_UNREGISTERED`. The booleans `requires_cold_chain` and `is_controlled` are derived from `product_class` — the former true exactly when the class is `COLD_CHAIN`, the latter true exactly when the class is `CONTROLLED`.

### 3.2. Quality Release, Recall, and Expiry of Lots

A `QAPharmacist` releases a `QUARANTINED` lot, advancing `lot_posture` to `RELEASABLE`. Release requires the lot to currently be `QUARANTINED` (otherwise `ERR_INVALID_STATE`), the donor to be `ACTIVE` (otherwise `ERR_DONOR_NOT_ACTIVE`), and — for controlled lots — the donor's `dea_registration_no` to be non-empty (otherwise `ERR_CONTROLLED_DONOR_UNREGISTERED`). On release, the full `quantity_received` is subtracted from `quantity_quarantined` and added to `quantity_available`, and the lot's `version` increments by 1.

A recall, also executed by a `QAPharmacist`, moves a lot from either `QUARANTINED` or `RELEASABLE` into the terminal `RECALLED` posture; a lot in any other posture (`RECALLED` or `EXPIRED`) cannot be recalled and is rejected with `ERR_INVALID_STATE`. Recall has cascading consequences: every `AllocationLine` against this lot that is still in `RESERVED` status transitions to `RELEASED` (with each lot's `quantity_committed` decremented accordingly and the released units returning to `quantity_available`), and every `Shipment` in `PACKING` or `READY_TO_DISPATCH` containing lines against this lot transitions to `CANCELLED` (its `PICKED` lines against the recalled lot move to `RELEASED` rather than back to `RESERVED`). To keep the five-bucket ledger reconciled (§2.8: when units leave one bucket they enter another), the recall folds the lot's remaining non-shipped units into `quantity_expired`: for a lot recalled from `QUARANTINED`, the full `quantity_quarantined` balance moves into `quantity_expired`; for a lot recalled from `RELEASABLE`, whatever `quantity_available` remains after the line releases moves into `quantity_expired`. Units already in `quantity_shipped` stay in that bucket. The lot's derived `quantity_available` therefore falls to zero, and the lot's `version` increments by 1.

Expiry is automatic. When the logical clock reaches a lot's `expiration_date`, a lot in `RELEASABLE` with unshipped units transitions to the terminal `EXPIRED` posture: the remaining `quantity_available` is moved into `quantity_expired`, `quantity_available` becomes zero, and every `RESERVED` allocation line against the lot transitions to `FORFEITED`. A lot still in `QUARANTINED` at its expiration date also transitions to `EXPIRED`, with `quantity_quarantined` folded into `quantity_expired`. A `RELEASABLE` lot whose units are all already shipped or expired at its expiration date is left untouched by the sweep.

### 3.3. Recipient-Site Qualification and Licensing

A `PlatformAdmin` or `ComplianceOfficer` registers a `RecipientSite` with the `organization_name`, a `site_type` drawn from `FREE_CLINIC`, `FQHC`, `RURAL_HEALTH_CENTER`, `DISASTER_RESPONDER`, or `HOSPITAL_CHARITY`, the operating `country_code`, the verified refrigerated volume `cold_storage_capacity_l` in liters, the `has_dea_registration` flag, the self-reported `monthly_patient_volume`, and the `underserved_index` (a measure of community medical underservice between 0.0 and 1.0, where 1.0 is most underserved; values outside that range are rejected with `ERR_INVALID_REQUEST`, HTTP 400). New sites enter with `qualification_status` set to `PENDING_REVIEW`. The boolean `is_international` is derived: it is true exactly when `country_code` is not `US`.

A site cannot be qualified on intent alone — it must hold licensure. A `SiteCoordinator` or `ComplianceOfficer` registers a `License` against the site by supplying the `site_id`, the `license_type` (one of `PHARMACY`, `MEDICAL_DIRECTOR`, `DEA`, `WHOLESALER`, `IMPORT`), the `issuing_authority`, the `license_number`, and the `expires_on` date. Licenses enter with `verification_status` set to `PENDING`. A `ComplianceOfficer` then either verifies the license — possible only while it is `PENDING` and its `expires_on` is strictly after the current logical clock, otherwise `ERR_LICENSE_EXPIRED` (HTTP 422) — or rejects it. Verification moves the license to `VERIFIED`; rejection moves it to the terminal `REJECTED`. When the logical clock reaches a `VERIFIED` license's `expires_on`, the license automatically transitions to the terminal `EXPIRED` status. Each of these transitions recomputes the site's `active_license_count` — the count of the site's licenses in `VERIFIED` status whose `expires_on` is after the current logical clock.

Qualification itself is performed by a `ComplianceOfficer`, and only from `PENDING_REVIEW` (a site in any other status is rejected with `ERR_INVALID_STATE`). Moving a `PENDING_REVIEW` site to `QUALIFIED` requires at least one active license (otherwise `ERR_NO_VERIFIED_LICENSE`, HTTP 422) and, for sites whose `country_code` is not `US`, additionally requires that the site hold a `VERIFIED` `IMPORT` license whose expiry is strictly after the current logical clock (otherwise `ERR_IMPORT_LICENSE_MISSING`, HTTP 422; the import-license check is evaluated before the active-license-count check). On qualification, `qualified_at` is stamped from the logical clock and the site's `version` increments. A `QUALIFIED` site may be suspended by a `ComplianceOfficer`, moving it to `SUSPENDED`; if the request body carries `expected_site_version` it must match the site's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412) as described in §2.6, while an omitted field skips the version check. Suspension cascades: every `AllocationRequest` for the site in `SUBMITTED` or `UNDER_REVIEW` transitions to `CANCELLED`, and every `AllocationLine` in `RESERVED` for the site transitions to `RELEASED` with the corresponding lots' `quantity_committed` decreased and `quantity_available` increased. A `SUSPENDED` site may be reinstated to `QUALIFIED` by a `ComplianceOfficer`, again requiring `active_license_count` of at least one (otherwise `ERR_NO_VERIFIED_LICENSE`). Either a `QUALIFIED` or a `SUSPENDED` site may be permanently moved to the terminal `REVOKED` status (a site in any other status is rejected with `ERR_INVALID_STATE`); revocation carries the same cascade as suspension and additionally cancels every `Shipment` to the site that is still in `PACKING`, `AWAITING_CUSTOMS_DOCS`, or `READY_TO_DISPATCH`. There is no path out of `REVOKED`.

A subtle auto-cascade ties licensing back to qualification: if a license expiry causes a `QUALIFIED` site's `active_license_count` to drop to zero, the site automatically transitions to `SUSPENDED`, carrying the standard suspension cascade with it.

### 3.4. The Allocation Request Lifecycle

A `SiteCoordinator` submits an `AllocationRequest` naming the requesting `site_id`, the desired product's `ndc_code`, the `quantity_requested` (a positive integer — zero or negative values are rejected with `ERR_QUANTITY_INVALID`, HTTP 422), a free-text `justification_text`, and — when the request responds to a declared emergency — an `emergency_event_id`. The `requested_by_user_id` is captured from `X-User-ID`. If an `emergency_event_id` is supplied, the referenced `EmergencyEvent` must exist (otherwise `ERR_NOT_FOUND`) and must be in `ACTIVE` status for the request to confer emergency weighting; otherwise the submission is rejected with `ERR_EMERGENCY_NOT_ACTIVE` (HTTP 409). New requests enter in `SUBMITTED` status, with `need_score` null and `quantity_approved` zero.

An `AllocationOfficer` takes a `SUBMITTED` request into `UNDER_REVIEW`. Beginning review requires the site's `qualification_status` to be `QUALIFIED` (otherwise `ERR_SITE_NOT_QUALIFIED`, HTTP 409), and bumps the request's `version`. Two cyclic-revision paths also lead back into `UNDER_REVIEW`: a request already in `APPROVED` or `PARTIALLY_APPROVED` may be re-opened for review, but only while the site's qualification remains `QUALIFIED` and every line of the existing `FINALIZED` decision is still in `RESERVED` status — no line may have progressed to `PICKED`, `SHIPPED`, or `DELIVERED` (a violation is rejected with `ERR_INVALID_STATE`). This loop is what makes superseding decisions possible.

From `UNDER_REVIEW`, the officer may reject the request outright — moving it to the terminal `REJECTED` status, optionally recording a `rationale` — provided no `FINALIZED` decision exists for it (otherwise `ERR_INVALID_STATE`). The requesting `SiteCoordinator` may cancel their own request from either `SUBMITTED` or `UNDER_REVIEW`, again only while no `FINALIZED` decision exists; the server compares the request's `requested_by_user_id` to `X-User-ID` and rejects a mismatch with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403). Both `REJECTED` and `CANCELLED` are terminal.

The remaining transitions out of `UNDER_REVIEW` — to `APPROVED` or to `PARTIALLY_APPROVED` — are not performed directly by any user. They are derived consequences of decision finalization, described next.

### 3.5. Allocation Decisions and Quantity Commitment

An `AllocationOfficer` drafts an `AllocationDecision` against a request by naming the `request_id`, recording a free-text `rationale` (a required, non-empty string), and supplying a `lines` array, each line naming a `lot_id` and a `quantity`. The `reviewer_user_id` is captured from `X-User-ID`, and the decision enters in `DRAFT` status; its lines likewise enter in `DRAFT` status. A draft's lines carry no reservation yet — quantities are not committed against any lot until finalization. Draft creation does not require the request to be in any particular status. At draft creation the enforced guards are: the referenced request's site must be `QUALIFIED` (otherwise `ERR_SITE_NOT_QUALIFIED`); every referenced lot must exist and be in `RELEASABLE` posture (`QUARANTINED`, `RECALLED`, or `EXPIRED` lots cause rejection with `ERR_LOT_NOT_RELEASABLE`, HTTP 409); every line's `quantity` must be a positive integer; and the sum of line quantities must be strictly greater than zero and must not exceed the request's `quantity_requested` (violations surface as `ERR_QUANTITY_INVALID`, HTTP 422). The cold-chain capability, controlled-site authorization, and lot-availability checks are *not* applied at draft creation: cold-chain and controlled-site authorization are finalization-only guards (§2.9, "at decision finalization"), and because drafts carry no reservation the lot-availability invariant is a commit-time check applied only at finalization, where the quantity committed against each lot must leave that lot's `quantity_available` non-negative after the commit, otherwise `ERR_INSUFFICIENT_AVAILABLE`. The site-qualification and lot-releasability guards are re-checked at finalization as part of the ordered sequence below. A decision's serialized representation (both single-fetch and list) embeds its `lines` array.

Finalization is the pivotal transition, and it is guarded more heavily than any other operation in the system. The checks, in order: the decision must be in `DRAFT` (else `ERR_INVALID_STATE`); the caller must be the same officer who drafted it — `reviewer_user_id` must equal `X-User-ID`, enforcing segregation of duties so a different officer may not finalize another's draft (a mismatch is rejected with `ERR_FORBIDDEN_OWNERSHIP`, HTTP 403); the request's site must still be `QUALIFIED` (else `ERR_SITE_NOT_QUALIFIED`); the decision must carry at least one line (an empty decision is rejected with `ERR_QUANTITY_INVALID`, HTTP 422); every line's lot must be `RELEASABLE` (else `ERR_LOT_NOT_RELEASABLE`); for every line whose lot requires cold chain, the site's cold-storage capability must suffice (else `ERR_COLD_CHAIN_INADEQUATE`); for every line whose lot is controlled, the site's `has_dea_registration` must be true (else `ERR_CONTROLLED_SITE_NOT_AUTHORIZED`); the sum of line quantities must not exceed `quantity_requested` (else `ERR_QUANTITY_INVALID`); the lot-availability invariant must hold (else `ERR_INSUFFICIENT_AVAILABLE`); and the request body must carry `expected_request_version` matching the request's current `version` — a missing field is treated as a mismatch (else `ERR_STALE_VERSION`). Finalization itself does not require the request to be in `UNDER_REVIEW` or any other particular status.

On successful finalization, several things happen atomically. The decision moves to `FINALIZED` and `decided_at` is stamped from the logical clock. Every line moves to `RESERVED`, its quantity is added to its lot's `quantity_committed`, and each line's `reservation_expires_at` is set from `decided_at` plus a TTL: seventy-two hours for ordinary requests, shortened to twenty-four hours when the request's `emergency_event_id` references an `EmergencyEvent` in `ACTIVE` status. The request's `need_score` is computed and persisted (see §3.6). The request then transitions to `APPROVED` when the finalized lines exactly cover `quantity_requested`, or to `PARTIALLY_APPROVED` when they cover a positive quantity less than `quantity_requested`; `quantity_approved` is set to the covered amount, and the request's `version` increments. A draft may alternatively be voided by an `AllocationOfficer`, moving it to the terminal `VOID` status with no quantity impact — the lines were never reserved.

When a request in `APPROVED` or `PARTIALLY_APPROVED` is taken back into `UNDER_REVIEW` and a new draft is finalized, the previously `FINALIZED` decision transitions to the terminal `SUPERSEDED` status — permitted only while all of that decision's lines remain `RESERVED` (otherwise `ERR_INVALID_STATE`). Supersession releases the old decision's lines (each to `RELEASED`, with lot `quantity_committed` decreased and `quantity_available` increased), and the request's `quantity_approved` is recomputed from the superseding decision.

### 3.6. Need Scoring

The `need_score` is a weighted sum computed exactly once, at the moment a decision is finalized, and persisted on the `AllocationRequest`. Later changes to the site or the emergency event do not retroactively recompute it.

The score combines four components. The base score is the site's `underserved_index` multiplied by 100. The volume component takes the site's `monthly_patient_volume`, divides it by 1000, caps the result at 2.0, and multiplies the capped figure by 25 — so a site reporting 1000 patients per month earns 25 volume points and any site at or above 2000 patients per month earns the maximum 50. The emergency component contributes ten points per unit of the referenced event's `severity`, but only when the request references an `EmergencyEvent` whose status is `ACTIVE` at finalize time; otherwise it contributes zero. The storage adjustment subtracts a flat 50 points when any lot on the decision's lines requires cold chain and the site's `cold_storage_capacity_l` is exactly zero. The four components are summed and the total is rounded half-up to two decimal places.

### 3.7. Shipment Packing, Customs, and Delivery

Once a decision is `FINALIZED`, a `LogisticsCoordinator` creates a `Shipment` covering that decision's lines, naming the `allocation_decision_id`, the `carrier_name`, and whether the consignment is `packed_with_cold_shipper`. Creation requires the target site to be `QUALIFIED` (else `ERR_SITE_NOT_QUALIFIED`). The shipment's `site_id` is taken from the decision's request, and `is_international` mirrors the site's own flag. Every referenced line must be `RESERVED` and the decision `FINALIZED` (otherwise `ERR_INVALID_STATE`); on creation each line advances from `RESERVED` to `PICKED` and its quantity moves out of the lot's `quantity_committed` (the units are now in-flight rather than reserved). The shipment enters in `PACKING` status, with `requires_cold_chain`, `temperature_band_min_c`, `temperature_band_max_c`, and `customs_declaration_id` all null until the corresponding later steps populate them.

Marking packing complete is the point at which the temperature band is computed. Over the distinct lots referenced by the shipment's `PICKED` lines, `temperature_band_min_c` is the largest of the lots' `storage_temp_min_c` values and `temperature_band_max_c` is the smallest of the lots' `storage_temp_max_c` values — the tightest band that satisfies every lot. A shipment with no `PICKED` lines is rejected with `ERR_INVALID_STATE` (HTTP 409). If the resulting minimum exceeds the maximum, the lots cannot travel together and pack completion is rejected with `ERR_INCOMPATIBLE_TEMPERATURE_BANDS` (HTTP 422). The shipment's `requires_cold_chain` is true when any included lot requires cold chain; in that case `packed_with_cold_shipper` must be true, otherwise `ERR_COLD_CHAIN_PACK_REQUIRED`. From `PACKING`, an international shipment advances to `AWAITING_CUSTOMS_DOCS`; a domestic one advances directly to `READY_TO_DISPATCH`.

For international consignments, the `LogisticsCoordinator` creates a `CustomsDeclaration` naming the `shipment_id`, the Harmonized System `hs_code`, and the recipient's `import_license_id` — which must reference one of the destination site's licenses in `VERIFIED` status with `expires_on` after the current logical clock, otherwise `ERR_IMPORT_LICENSE_MISSING`. Declaration creation requires the shipment to be international (a declaration against a domestic shipment is rejected with `ERR_INVALID_STATE`) but imposes no requirement on the shipment's current status. The declaration enters in `DRAFT` status, the shipment's `customs_declaration_id` is populated (a later declaration for the same shipment replaces the link), and `destination_country_code` is copied from the site's `country_code`. Submitting the declaration — possible only from `DRAFT` — re-validates the import license (still `VERIFIED` and unexpired, otherwise `ERR_IMPORT_LICENSE_MISSING`) and computes `declared_value_usd`: for every `PICKED` line on the shipment's decision, the line's `quantity` is multiplied by the referenced lot's `unit_acquisition_value_usd`, each product is rounded half-up to two decimal places, and the rounded per-line amounts are summed. A declaration whose computed value is zero is rejected with `ERR_CUSTOMS_VALUE_INVALID` (HTTP 422). A `ComplianceOfficer` then clears the declaration — moving it from `SUBMITTED` to the terminal `CLEARED` status, which advances the shipment from `AWAITING_CUSTOMS_DOCS` to `READY_TO_DISPATCH` — or rejects it, moving it to the terminal `REJECTED` status and leaving the shipment in `AWAITING_CUSTOMS_DOCS`, whereupon the `LogisticsCoordinator` may prepare a fresh declaration. Both `clear` and `reject` accept an optional `reason` on rejection.

Dispatch moves a `READY_TO_DISPATCH` shipment to `DISPATCHED`. For international shipments the linked declaration must already be `CLEARED`, otherwise `ERR_CUSTOMS_NOT_CLEARED` (HTTP 409); and the destination site must still be `QUALIFIED`, otherwise `ERR_SITE_NOT_QUALIFIED`. On dispatch, `dispatched_at` is stamped and every `PICKED` line advances to `SHIPPED`, with each line's quantity added to its lot's `quantity_shipped`.

Delivery confirmation belongs to the destination site: a `SiteCoordinator` whose site matches the shipment's `site_id` confirms delivery, otherwise `ERR_FORBIDDEN_OWNERSHIP`. The shipment must be `DISPATCHED` (otherwise `ERR_INVALID_STATE`); it then moves to the terminal `DELIVERED` status, `delivered_at` is stamped, and every `SHIPPED` line advances to the terminal `DELIVERED` status. Alternatively, a `LogisticsCoordinator` may mark a `DISPATCHED` shipment as `DELIVERY_FAILED` with an optional `reason`; every `SHIPPED` line then transitions to the terminal `FORFEITED` status, and each line's quantity is removed from its lot's `quantity_shipped` and added to `quantity_expired` — the product is considered spoiled in transit.

A shipment may be cancelled by a `LogisticsCoordinator` while it is in `PACKING`, `AWAITING_CUSTOMS_DOCS`, or `READY_TO_DISPATCH`. Cancellation moves it to the terminal `CANCELLED` status and returns every `PICKED` line to `RESERVED`, with each line's quantity added back to its lot's `quantity_committed`.

### 3.8. Reservation Forfeiture

Reservation is time-boxed. When the logical clock passes a `RESERVED` line's `reservation_expires_at`, the line automatically transitions to the terminal `FORFEITED` status: the quantity is removed from the lot's `quantity_committed` and returned to `quantity_available`, and the parent request's `quantity_approved` is recomputed as the sum of quantities over the `FINALIZED` decision's lines in `RESERVED`, `PICKED`, `SHIPPED`, or `DELIVERED` status. If forfeiture leaves the request with zero approved units, the request itself transitions to the terminal `REJECTED` status.

### 3.9. Emergency Events and Pre-Positioned Modules

An `EmergencyManager` declares an `EmergencyEvent` with an `event_name`, a `severity` on the 1–5 scale (5 being catastrophic; values outside the range are rejected with `ERR_INVALID_REQUEST`), the list of `affected_country_codes` (an array of strings), and the `surge_window_ends_at` timestamp bounding the priority window. The event enters in `DECLARED` status with `declared_at` stamped from the logical clock. Activation by an `EmergencyManager` — permitted only from `DECLARED`, otherwise `ERR_INVALID_STATE` — moves the event to `ACTIVE`; from that moment, allocation requests referencing the event receive the emergency weighting described in §3.6 and the shortened reservation TTL described in §3.5. When the logical clock reaches `surge_window_ends_at`, the event automatically transitions to `STAND_DOWN`, and every `PrepositionedModule` currently `RESERVED` for the event returns to `AVAILABLE` with its `reserved_for_event_id` cleared. An `EmergencyManager` closes a `STAND_DOWN` event — moving it to the terminal `CLOSED` status — only once every `AllocationRequest` referencing the event has reached a terminal status (that is, `REJECTED` or `CANCELLED`), otherwise `ERR_INVALID_STATE`.

Pre-positioned modules are registered by an `EmergencyManager` or `PlatformAdmin` with a unique `module_code`, an `intended_use` drawn from `PRIMARY_CARE`, `TRAUMA`, `CHOLERA`, `MATERNAL`, or `COLD_CHAIN_VACCINE` (any other value is rejected with `ERR_INVALID_REQUEST`), and a `holding_country_code`. A module enters in `AVAILABLE` status with `quantity_on_hand` initialized to zero. Reserving a module for an event requires the module to be `AVAILABLE`, the target event to be `ACTIVE` (otherwise `ERR_EMERGENCY_NOT_ACTIVE`), and either the module's `holding_country_code` to appear in the event's `affected_country_codes` or the event's `severity` to be at least 4 — otherwise `ERR_MODULE_OUT_OF_REGION` (HTTP 422). Reservation moves the module to `RESERVED` and sets `reserved_for_event_id`. Deployment requires the module to be `RESERVED` and the event to remain `ACTIVE` (otherwise `ERR_EMERGENCY_NOT_ACTIVE`); the module moves to `DEPLOYED` with `quantity_on_hand` unchanged, since the goods are still in transit. Consumption requires the module to be `DEPLOYED` and the event to be in either `ACTIVE` or `STAND_DOWN` (otherwise `ERR_INVALID_STATE`); the module moves to the terminal `CONSUMED` status and `quantity_on_hand` falls to zero. A module whose event stands down while it is still `RESERVED` returns to `AVAILABLE` automatically, as described above. `DECOMMISSIONED` is the other terminal status for a module.

### 3.10. Donor Valuation Reporting

A `DonorReportingOfficer`, `ComplianceOfficer`, or `PlatformAdmin` generates a `ValuationSnapshot` for a donor by naming the `donor_id`, the `snapshot_period` as a year-month key, and the `method` — either `ACQUISITION_COST` or `WHOLESALE_REFERENCE` (any other value is rejected with `ERR_INVALID_REQUEST`). The snapshot aggregates the donor's lots whose `intake_recorded_at` falls in the named period, excluding any lot in `RECALLED` posture. Each included lot contributes its `quantity_received` multiplied by the per-unit value for the chosen method — `unit_acquisition_value_usd` under `ACQUISITION_COST` (the basis required for donor tax reporting) or `unit_wholesale_value_usd` under `WHOLESALE_REFERENCE` (the basis used for GAAP inventory disclosure). Each lot's contribution is rounded half-up to two decimal places *before* the rounded contributions are summed into `total_value_usd`; `lot_count` records how many lots were included, and `generated_at` is stamped from the logical clock.

### 3.11. Distribution Reporting by Recipient Sites

After a shipment reaches `DELIVERED`, the receiving `SiteCoordinator` files a `DistributionReport` naming the `site_id`, the `shipment_id`, the `reporting_period` as a year-month key, the `units_distributed` during the period, the `patients_reached`, and any `wastage_units` lost to expiry or damage. The `submitted_by_user_id` is captured from `X-User-ID`, which must equal the report's `site_id` (otherwise `ERR_FORBIDDEN_OWNERSHIP`), and the referenced shipment must be `DELIVERED` (otherwise `ERR_INVALID_STATE`); the report enters in `DRAFT` status. Submission by the same site coordinator — the server checks that `X-User-ID` belongs to the site on the report, otherwise `ERR_FORBIDDEN_OWNERSHIP` — moves the report to `SUBMITTED`. At submission, an overreport guard fires: the new report's `units_distributed` plus `wastage_units`, added to the same two figures summed over every prior report for the shipment in `SUBMITTED` or `ACCEPTED` status, must not exceed the total delivered quantity (the sum of quantities on the shipment decision's lines in `DELIVERED` status). A breach is rejected with `ERR_OVERREPORTED` (HTTP 422); exact equality with the delivered quantity is allowed.

Review of a `SUBMITTED` report belongs to a `ComplianceOfficer`, and segregation of duties is enforced strictly: the reviewing officer's user id must differ from the report's `submitted_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES` (HTTP 403) on either accept or reject. Acceptance moves the report to the terminal `ACCEPTED` status and records `reviewed_by_user_id`. Rejection — which accepts an optional `reason` — moves the report to the terminal `REJECTED` status and likewise records `reviewed_by_user_id`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify or transition an existing resource return `200 OK`. The table below is a routing summary only — request payloads, response shapes, side effects, and guard conditions are defined by the narratives in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/medicine-relief/_clock/set_current_utc` | Advance the server's logical clock | PlatformAdmin |
| POST | `/medicine-relief/donors` | Register a new manufacturer donor | PlatformAdmin |
| GET | `/medicine-relief/donors/{donor_id}` | Get a donor | PlatformAdmin, ComplianceOfficer, AllocationOfficer, DonorReportingOfficer |
| GET | `/medicine-relief/donors` | List donors (paginated) | PlatformAdmin, ComplianceOfficer, AllocationOfficer, DonorReportingOfficer |
| POST | `/medicine-relief/donors/{donor_id}/suspend` | Suspend a donor (blocks new intake) | PlatformAdmin |
| POST | `/medicine-relief/donors/{donor_id}/deactivate` | Deactivate a donor permanently | PlatformAdmin |
| POST | `/medicine-relief/lots` | Intake a new product lot (enters QUARANTINED) | PlatformAdmin, QAPharmacist |
| GET | `/medicine-relief/lots/{lot_id}` | Get a lot | PlatformAdmin, QAPharmacist, AllocationOfficer, LogisticsCoordinator, ComplianceOfficer, DonorReportingOfficer |
| GET | `/medicine-relief/lots` | List lots (paginated, filterable) | PlatformAdmin, QAPharmacist, AllocationOfficer, LogisticsCoordinator, ComplianceOfficer, DonorReportingOfficer |
| POST | `/medicine-relief/lots/{lot_id}/release` | QA-release a QUARANTINED lot | QAPharmacist |
| POST | `/medicine-relief/lots/{lot_id}/recall` | Recall a lot | QAPharmacist |
| POST | `/medicine-relief/sites` | Register a recipient site | PlatformAdmin, ComplianceOfficer |
| GET | `/medicine-relief/sites/{site_id}` | Get a site | PlatformAdmin, ComplianceOfficer, AllocationOfficer, LogisticsCoordinator, SiteCoordinator, EmergencyManager |
| GET | `/medicine-relief/sites` | List sites (paginated, filterable) | PlatformAdmin, ComplianceOfficer, AllocationOfficer, LogisticsCoordinator, EmergencyManager |
| POST | `/medicine-relief/sites/{site_id}/qualify` | Qualify a PENDING_REVIEW site | ComplianceOfficer |
| POST | `/medicine-relief/sites/{site_id}/suspend` | Suspend a QUALIFIED site (OCC) | ComplianceOfficer |
| POST | `/medicine-relief/sites/{site_id}/reinstate` | Reinstate a SUSPENDED site | ComplianceOfficer |
| POST | `/medicine-relief/sites/{site_id}/revoke` | Permanently revoke a site | ComplianceOfficer |
| POST | `/medicine-relief/licenses` | Register a license for a site | SiteCoordinator, ComplianceOfficer |
| GET | `/medicine-relief/licenses/{license_id}` | Get a license | ComplianceOfficer, SiteCoordinator, PlatformAdmin |
| GET | `/medicine-relief/licenses` | List licenses (paginated, filterable) | ComplianceOfficer, SiteCoordinator, PlatformAdmin |
| POST | `/medicine-relief/licenses/{license_id}/verify` | Verify a PENDING license | ComplianceOfficer |
| POST | `/medicine-relief/licenses/{license_id}/reject` | Reject a PENDING license | ComplianceOfficer |
| POST | `/medicine-relief/allocation-requests` | Submit an allocation request | SiteCoordinator |
| GET | `/medicine-relief/allocation-requests/{request_id}` | Get an allocation request | SiteCoordinator, AllocationOfficer, ComplianceOfficer, PlatformAdmin |
| GET | `/medicine-relief/allocation-requests` | List allocation requests (paginated, filterable) | SiteCoordinator, AllocationOfficer, ComplianceOfficer, PlatformAdmin |
| POST | `/medicine-relief/allocation-requests/{request_id}/begin-review` | Move a request to UNDER_REVIEW | AllocationOfficer |
| POST | `/medicine-relief/allocation-requests/{request_id}/reject` | Reject an UNDER_REVIEW request | AllocationOfficer |
| POST | `/medicine-relief/allocation-requests/{request_id}/cancel` | Site coordinator cancels own request | SiteCoordinator |
| POST | `/medicine-relief/allocation-decisions` | Create a DRAFT decision with lot lines | AllocationOfficer |
| GET | `/medicine-relief/allocation-decisions/{decision_id}` | Get a decision (includes lines) | AllocationOfficer, ComplianceOfficer, PlatformAdmin, SiteCoordinator |
| GET | `/medicine-relief/allocation-decisions` | List decisions (paginated, filterable) | AllocationOfficer, ComplianceOfficer, PlatformAdmin |
| POST | `/medicine-relief/allocation-decisions/{decision_id}/finalize` | Finalize a DRAFT decision (OCC) | AllocationOfficer |
| POST | `/medicine-relief/allocation-decisions/{decision_id}/void` | Void a DRAFT decision | AllocationOfficer |
| GET | `/medicine-relief/allocation-lines` | List allocation lines (paginated, filterable) | AllocationOfficer, ComplianceOfficer, LogisticsCoordinator, PlatformAdmin, SiteCoordinator |
| GET | `/medicine-relief/allocation-lines/{line_id}` | Get a single allocation line | AllocationOfficer, ComplianceOfficer, LogisticsCoordinator, PlatformAdmin |
| POST | `/medicine-relief/shipments` | Create a PACKING shipment for a FINALIZED decision | LogisticsCoordinator |
| GET | `/medicine-relief/shipments/{shipment_id}` | Get a shipment | LogisticsCoordinator, ComplianceOfficer, PlatformAdmin, SiteCoordinator |
| GET | `/medicine-relief/shipments` | List shipments (paginated, filterable) | LogisticsCoordinator, ComplianceOfficer, PlatformAdmin, SiteCoordinator |
| POST | `/medicine-relief/shipments/{shipment_id}/pack-complete` | Mark packing complete; compute temperature band | LogisticsCoordinator |
| POST | `/medicine-relief/shipments/{shipment_id}/dispatch` | Dispatch a READY_TO_DISPATCH shipment | LogisticsCoordinator |
| POST | `/medicine-relief/shipments/{shipment_id}/confirm-delivery` | Site coordinator confirms delivery | SiteCoordinator |
| POST | `/medicine-relief/shipments/{shipment_id}/mark-delivery-failed` | Mark a DISPATCHED shipment as failed | LogisticsCoordinator |
| POST | `/medicine-relief/shipments/{shipment_id}/cancel` | Cancel a pre-dispatch shipment | LogisticsCoordinator |
| POST | `/medicine-relief/customs-declarations` | Create a DRAFT customs declaration | LogisticsCoordinator |
| GET | `/medicine-relief/customs-declarations/{declaration_id}` | Get a customs declaration | LogisticsCoordinator, ComplianceOfficer, PlatformAdmin |
| GET | `/medicine-relief/customs-declarations` | List customs declarations (paginated, filterable) | LogisticsCoordinator, ComplianceOfficer, PlatformAdmin |
| POST | `/medicine-relief/customs-declarations/{declaration_id}/submit` | Submit a DRAFT declaration | LogisticsCoordinator |
| POST | `/medicine-relief/customs-declarations/{declaration_id}/clear` | Compliance clears a SUBMITTED declaration | ComplianceOfficer |
| POST | `/medicine-relief/customs-declarations/{declaration_id}/reject` | Compliance rejects a SUBMITTED declaration | ComplianceOfficer |
| POST | `/medicine-relief/emergency-events` | Declare an emergency event | EmergencyManager |
| GET | `/medicine-relief/emergency-events/{event_id}` | Get an emergency event | EmergencyManager, AllocationOfficer, ComplianceOfficer, PlatformAdmin, SiteCoordinator |
| GET | `/medicine-relief/emergency-events` | List emergency events (paginated, filterable) | EmergencyManager, AllocationOfficer, ComplianceOfficer, PlatformAdmin |
| POST | `/medicine-relief/emergency-events/{event_id}/activate` | Activate a DECLARED event | EmergencyManager |
| POST | `/medicine-relief/emergency-events/{event_id}/close` | Close a STAND_DOWN event | EmergencyManager |
| POST | `/medicine-relief/prepositioned-modules` | Register a pre-positioned module | EmergencyManager, PlatformAdmin |
| GET | `/medicine-relief/prepositioned-modules/{module_id}` | Get a module | EmergencyManager, PlatformAdmin, ComplianceOfficer |
| GET | `/medicine-relief/prepositioned-modules` | List modules (paginated, filterable) | EmergencyManager, PlatformAdmin, ComplianceOfficer |
| POST | `/medicine-relief/prepositioned-modules/{module_id}/reserve` | Reserve a module for an ACTIVE event | EmergencyManager |
| POST | `/medicine-relief/prepositioned-modules/{module_id}/deploy` | Deploy a RESERVED module | EmergencyManager |
| POST | `/medicine-relief/prepositioned-modules/{module_id}/consume` | Mark a DEPLOYED module consumed | EmergencyManager |
| POST | `/medicine-relief/valuation-snapshots` | Generate a valuation snapshot | DonorReportingOfficer, ComplianceOfficer, PlatformAdmin |
| GET | `/medicine-relief/valuation-snapshots/{snapshot_id}` | Get a snapshot | DonorReportingOfficer, ComplianceOfficer, PlatformAdmin |
| GET | `/medicine-relief/valuation-snapshots` | List snapshots (paginated, filterable) | DonorReportingOfficer, ComplianceOfficer, PlatformAdmin |
| POST | `/medicine-relief/distribution-reports` | File a DRAFT distribution report | SiteCoordinator |
| GET | `/medicine-relief/distribution-reports/{report_id}` | Get a distribution report | SiteCoordinator, ComplianceOfficer, DonorReportingOfficer, PlatformAdmin |
| GET | `/medicine-relief/distribution-reports` | List distribution reports (paginated, filterable) | SiteCoordinator, ComplianceOfficer, DonorReportingOfficer, PlatformAdmin |
| POST | `/medicine-relief/distribution-reports/{report_id}/submit` | Submit a DRAFT report | SiteCoordinator |
| POST | `/medicine-relief/distribution-reports/{report_id}/accept` | Compliance accepts a SUBMITTED report | ComplianceOfficer |
| POST | `/medicine-relief/distribution-reports/{report_id}/reject` | Compliance rejects a SUBMITTED report | ComplianceOfficer |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of §2 and §3; this table is a routing summary only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_FORBIDDEN_OWNERSHIP` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_DONOR_NOT_ACTIVE` | 409 |
| `ERR_CONTROLLED_DONOR_UNREGISTERED` | 422 |
| `ERR_CONTROLLED_SITE_NOT_AUTHORIZED` | 422 |
| `ERR_COLD_CHAIN_INADEQUATE` | 422 |
| `ERR_COLD_CHAIN_PACK_REQUIRED` | 422 |
| `ERR_LOT_NOT_RELEASABLE` | 409 |
| `ERR_IMPORT_LICENSE_MISSING` | 422 |
| `ERR_NO_VERIFIED_LICENSE` | 422 |
| `ERR_LICENSE_EXPIRED` | 422 |
| `ERR_SITE_NOT_QUALIFIED` | 409 |
| `ERR_QUANTITY_INVALID` | 422 |
| `ERR_INSUFFICIENT_AVAILABLE` | 409 |
| `ERR_OVERREPORTED` | 422 |
| `ERR_CUSTOMS_NOT_CLEARED` | 409 |
| `ERR_CUSTOMS_VALUE_INVALID` | 422 |
| `ERR_INCOMPATIBLE_TEMPERATURE_BANDS` | 422 |
| `ERR_MODULE_OUT_OF_REGION` | 422 |
| `ERR_EMERGENCY_NOT_ACTIVE` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
