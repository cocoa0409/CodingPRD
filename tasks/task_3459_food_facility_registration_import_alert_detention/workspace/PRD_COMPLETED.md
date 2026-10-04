# Food Facility Import Detention API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Food Facility Registration & Import Alert Detention API, a regulatory operations system in the style of the FDA human foods program. The platform governs the registration of domestic and foreign food facilities — including biennial renewal and the assignment of a unique facility identifier — and follows imported food shipments from the mandatory prior notice filed before arrival, through entry review screening against risk factors, firm history, and product codes, to examination, sampling, and final disposition. Facilities or country–product combinations that present a recurring risk may be placed on an import alert, subjecting their shipments to detention without physical examination, and may petition for removal by demonstrating a run of consecutive compliant shipments supported by corrective evidence.

Because the system is a compliance record as much as a workflow engine, several cross-cutting concerns shape every workflow. Detained shipments must be resolved — released, reconditioned, exported, or refused — within strict time limits, and every unit declared on an entry must be accounted for at all times. Foreign facility inspections can be scheduled, completed, or refused, with refusal to permit inspection carrying severe cascading consequences for the facility's registrations, notices, and open entries. Products already in commerce are handled through classified recalls whose effectiveness must be verified before termination. All regulatory timing is evaluated against a controllable logical clock so that expiry, deadline, and lead-time behavior is deterministic and auditable. Duties are deliberately segregated across seven roles so that, for example, the officer who places an import alert can never be the one who adjudicates a petition against it.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which that principal acts. The system recognizes exactly seven roles: `PlatformAdmin`, `FacilityOwner`, `Importer`, `EntryReviewer`, `ComplianceOfficer`, `FieldInspector`, and `RecallCoordinator`. A request missing either header, presenting a blank or whitespace-only `X-User-ID`, or presenting a role other than these seven, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A well-formed caller whose role is not among an operation's authorized roles is rejected with `ERR_FORBIDDEN` (HTTP 403); this also covers an `EntryReviewer` attempting to release an entry that is under detention.

Two roles are entity-backed. When `X-User-Role` is `FacilityOwner`, `X-User-ID` is the `id` of the acting Facility; ownership checks on any resource that references a Facility compare the resource's facility reference to `X-User-ID`. When `X-User-Role` is `Importer`, `X-User-ID` is the `id` of the acting ImporterFirm; ownership checks on a prior notice or an import entry compare its `importer_id` to `X-User-ID`. The remaining five roles — `PlatformAdmin`, `EntryReviewer`, `ComplianceOfficer`, `FieldInspector`, and `RecallCoordinator` — are opaque: for each of them, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record such identifiers (for example, as `inspector_user_id` on an Inspection or as `created_by_user_id` on an ImportAlert) but does not compare them to any entity's `id`. A failed entity-backed ownership comparison is rejected with `ERR_OWNERSHIP_VIOLATION` (HTTP 403).

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
- Requests that match no defined route are rejected in this same envelope with `error_id` `ERR_INVALID_REQUEST` at the routing layer's own status: 404 for an unknown path, 405 for an unsupported method, and 500 for an unexpected server failure. These framework-level rejections are the only use of an error identifier at a status other than the one §5 assigns it.

---

### 2.3. Pagination

Endpoints that return lists of resources are paginated through query parameters. The `limit` parameter sets the maximum number of items returned: it defaults to 10 when omitted, accepts a minimum of 1, and is capped at a maximum of 100 — a `limit` above 100 is clamped to 100, while a non-integer `limit` or one below 1 is rejected with `ERR_INVALID_REQUEST`. The `offset` parameter sets the number of items skipped and defaults to 0; a non-integer or negative `offset` is rejected with `ERR_INVALID_REQUEST`. An empty-string `limit` or `offset` is treated as omitted.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order; resources created at the same logical instant are ordered by the server's creation sequence (the order in which the server accepted them), never by `id`.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`; `has_more` is true exactly when `offset` plus the number of items actually returned is less than `total_count`.

The list endpoints accept exact-match query filters, combined conjunctively when several are supplied: prior notices filter by `facility_id`, `importer_id`, `status`, and `parent_pn_id`; entries by `facility_id`, `importer_id`, `prior_notice_id`, `detained_under_alert_id`, `disposition_status`, and `review_status`; import alerts by `facility_id`, `status`, and `scope_type`; recalls by `facility_id`, `classification`, `status`, and `product_code`.

### 2.4. The Logical Clock and the Ops Checkpoint

All regulatory timing in the system — registration expiry, detention deadlines, prior-notice lead windows, sample scheduling dates — is evaluated against a server-side **logical clock**, never against the wall clock. Before any operator intervention, the logical clock starts at exactly `2026-09-01T00:00:00Z`. Every business timestamp the server records (such as `registered_at`, `detained_at`, `disposition_completed_at`, or `lifted_at`) is taken from this logical clock.

A `PlatformAdmin`-only capability advances the logical clock by supplying a target `current_utc` instant; all registry resources are mounted under the `/registry` prefix, while this clock control is part of the platform surface outside that prefix. The clock moves forward only: a supplied instant that is not later than the current logical time is rejected with `ERR_INVALID_REQUEST`, as is a `current_utc` value that parses to no valid instant. The response echoes the new `current_utc` together with `expired_facility_ids` and `auto_refused_entry_ids`, the two lists produced by the checkpoint below, each listed in resource creation order.

Advancing the clock atomically runs the **ops checkpoint**, in this order:

1. **Facility expiry sweep.** Every facility still in `REGISTERED` status whose `expires_at` is strictly before the new logical time flips to `EXPIRED`, incrementing its `version` by 1. The comparison is strictly-less-than: a facility whose `expires_at` is exactly equal to the new time remains `REGISTERED`.
2. **Detention deadline sweep.** Every import entry still in `DETAINED` disposition whose `response_deadline_at` plus 24 hours is strictly before the new logical time is auto-refused: its held units move into the refused bucket, its facility's `open_detention_count` decreases by 1 and `violation_count` increases by 1, and the importing firm's standing is recomputed as for any refusal. This comparison is also strict: a detention whose deadline-plus-24-hour grace instant is exactly equal to the new time is not auto-refused. The 24-hour grace exists so that the deadline-passed rejection remains reachable on entries that are still detained between their response deadline and the sweep.

### 2.5. Common Resource Properties

All ten resources in this system — Facility, ImporterFirm, Laboratory, PriorNotice, ImportEntry, SampleAnalysis, ImportAlert, AlertPetition, Inspection, and Recall — carry a standard set of system-managed fields:

- **`id` (string):** a unique, server-generated identifier formatted as a UUID, with no type prefix.
- **`created_at` (string):** an ISO 8601 UTC timestamp recording when the resource was created, rendered as `YYYY-MM-DDTHH:MM:SS` followed by `Z`; an instant with sub-second precision appends a fractional part — three digits when the instant is aligned to whole milliseconds, six digits otherwise — while a whole-second instant (such as the clock's starting instant in §2.4) carries no fractional part.
- **`updated_at` (string):** an ISO 8601 UTC timestamp refreshed on every modification of the resource, rendered in the same format as `created_at`.
- **`version` (integer):** a system-managed integer that starts at 1 when the resource is created, increments with every modification of the resource, and anchors optimistic concurrency control where that mechanism applies.

In addition, each Facility carries a server-minted `registration_number` in the format `FFR-NNNNNN` — a zero-padded, monotonically increasing sequence whose first issued value is `FFR-000001`. Certain transitions called out in §3 increment `version` explicitly (for example, renewal, expiry, and suspension on a Facility; lifting on an ImportAlert; filing a petition, which increments the *alert's* version by 1; submitting evidence on a petition; and recording an effectiveness round on a Recall).

### 2.6. Validation Precedence: Which Failure Is Reported First

A single request can violate several rules at once. When that happens, the failure reported is the one whose category sits earliest in the following fixed order — the system does not collect errors, it reports the first failing category only:

1. **Authentication** — headers present and role recognized (`ERR_UNAUTHENTICATED`, 401).
2. **Role authorization** — caller's role is listed for the operation (`ERR_FORBIDDEN`, 403).
3. **Entity-backed ownership** — the caller is the owner the operation targets (`ERR_OWNERSHIP_VIOLATION`, 403). Where the ownership comparison is evaluable from the request alone — the path identifier itself on facility renewal, or the body-carried `importer_id` on prior-notice filing — it is evaluated here, before existence. Where the comparison must be read from the persisted target (a notice's or entry's `importer_id`, a petition's `filed_by_facility_id`, an inspection's `inspector_user_id` or `facility_id`), the target necessarily resolves first: its 404 precedes the ownership failure.
4. **Existence** — every identifier in the path resolves to an existing resource, as do the body-referenced identifiers the §3 narratives call out: the laboratory code on a sample order, the `facility_id` and `importer_id` on a prior-notice filing, and the `prior_notice_id` on entry creation (the `ERR_*_NOT_FOUND` family, 404; see §2.9). Other body-carried references — the `facility_id` of an import alert or of a recall — are not existence-checked.
5. **State guards** — the target resource is in a state that permits the operation (`ERR_FACILITY_NOT_RENEWABLE`, `ERR_PN_NOT_CONFIRMED`, `ERR_IMPORTER_REVOKED`, `ERR_ENTRY_INVALID_STATE`, `ERR_IMPORT_ALERT_NOT_ACTIVE`, `ERR_PETITION_NOT_REVIEWABLE`, `ERR_INSPECTION_NOT_OPEN`, `ERR_RECALL_INVALID_STATE`; all 409).
6. **Registration and recall safety gates** — facility registration active, no blocking `CLASS_I` recall (`ERR_REGISTRATION_NOT_ACTIVE`, `ERR_ACTIVE_RECALL_BLOCKS_ENTRY`; both 422).
7. **Timing windows** — lead-time, renewal-window, detention-deadline, and sample-date checks (`ERR_NOTICE_TOO_LATE`, `ERR_NOTICE_TOO_EARLY`, `ERR_RENEWAL_WINDOW_CLOSED`, `ERR_DETENTION_RESPONSE_DEADLINE_PASSED`, `ERR_SAMPLE_DATE_PAST`; all 422).
8. **Cross-reference coherence** — petition filer inside the alert scope, inspection targets a foreign facility (`ERR_ALERT_SCOPE_MISMATCH`, `ERR_INSPECTION_REQUIRES_FOREIGN_FACILITY`; both 422).
9. **Uniqueness, capacity, and accounting constraints** — duplicate identifiers, schedule overlap, laboratory capacity, segregation of duties, unit accounting, effectiveness thresholds (`ERR_DUPLICATE_UFI`, `ERR_DUPLICATE_ACCOUNT_CODE`, `ERR_DUPLICATE_LAB_CODE`, `ERR_INSPECTION_SCHEDULE_OVERLAP`, `ERR_LAB_CAPACITY_EXCEEDED` at 409; `ERR_SEGREGATION_OF_DUTIES` at 403; `ERR_UNITS_ACCOUNTING_MISMATCH`, `ERR_EFFECTIVENESS_THRESHOLD_NOT_MET` at 422).
10. **Optimistic concurrency** — a stale expected version (`ERR_STALE_VERSION`, 412).
11. **Petition approval sufficiency** — compliance streak and evidence (`ERR_INSUFFICIENT_COMPLIANT_SHIPMENTS`, 422).
12. **Request shape** — missing required fields, invalid enum values, range violations, inconsistent alert scope fields (`ERR_INVALID_REQUEST`, 400).

Because request-shape checking sits at the bottom of this order, a request that is malformed *and* violates a higher-ranked rule is reported under the higher-ranked rule. Three consequences of this ordering deserve emphasis, and the workflows in §3 rely on them: a renewal attempted on a `SUSPENDED` facility reports the state failure `ERR_FACILITY_NOT_RENEWABLE` even if the renewal window is also closed; the active-recall safety gate on entry creation is evaluated once the referenced prior notice has resolved — its inputs are the notice's `facility_id` and `product_code` — and, within tier 6, after the registration gate, so it outranks request-shape failures (entry creation admits no timing failures); and a sample analysis dated in the past reports `ERR_SAMPLE_DATE_PAST` even when the laboratory's day capacity is also exhausted.

### 2.7. Optimistic Concurrency Control

Exactly two operations are guarded by optimistic concurrency control, each on a named parent resource:

- **Renewing a facility** requires the request to carry `expected_facility_version`, holding the facility `version` the client last observed. If it does not match the facility's current `version` — because another writer's renewal or a cascade-driven mutation advanced it since — the renewal is rejected with `ERR_STALE_VERSION` (HTTP 412). A renewal computed from a stale view of `expires_at` must never silently extend registration twice on the same baseline.
- **Filing a petition against an import alert** requires `expected_import_alert_version`, holding the alert `version` the petitioner last observed. A mismatch with the alert's current `version` is likewise rejected with `ERR_STALE_VERSION` (HTTP 412), because petition evidence is assembled against a specific revision of the alert's content.

No other endpoint takes a version field; for every other operation the server applies no OCC check.

### 2.8. Units, Currency, and Rounding Discipline

Money is handled exclusively as integer cents: declared values arrive as `unit_value_cents` (zero or greater), and the reconditioning bond is stored as `bond_amount_cents`. Where a monetary computation involves a fractional rate, the result is rounded **half up** to whole cents at the step the workflow specifies — and, for the bond, that rounding happens per lot *before* any summation (see §3.6). Article quantities are integer units: `declared_units` is always greater than zero, and every resolution action moves units between buckets without ever creating or destroying the total.

Two conservation invariants hold at all times and may be asserted on any read:

- For every import entry, `units_held` + `units_released` + `units_refused` + `units_exported` + `units_destroyed` always equals the entry's `declared_units`.
- For every recall, `quantity_recovered` + `quantity_corrected` + `quantity_destroyed` + `quantity_outstanding` always equals the recall's `quantity_distributed`.

Percentage fields (`effectiveness_pct`, `consignee_contact_pct`) are reported with exactly 1 decimal place, rounded half up. Screening scores are pure integer arithmetic with no rounding. Importer-standing ratios are compared as exact rational quantities — never as rounded floats — as detailed in §3.2. Prior-notice lead times are computed to whole minutes and compared at minute granularity.

### 2.9. Nested Resource Retrieval and Existence Checking

For any request that addresses resources by identifier, the system validates identifiers in a strict left-to-right order as they appear in the path, and rejects the request with the `404` error corresponding to the *first* identifier that does not resolve: `ERR_FACILITY_NOT_FOUND` for a Facility, `ERR_IMPORTER_NOT_FOUND` for an ImporterFirm, `ERR_PRIOR_NOTICE_NOT_FOUND` for a PriorNotice, `ERR_ENTRY_NOT_FOUND` for an ImportEntry, `ERR_SAMPLE_NOT_FOUND` for a SampleAnalysis, `ERR_IMPORT_ALERT_NOT_FOUND` for an ImportAlert, `ERR_ALERT_PETITION_NOT_FOUND` for an AlertPetition, `ERR_INSPECTION_NOT_FOUND` for an Inspection, and `ERR_RECALL_NOT_FOUND` for a Recall. A request to list the petitions or inspections of a facility that does not exist therefore fails with `ERR_FACILITY_NOT_FOUND` before any petition or inspection lookup is attempted. Separately, when a request body references a laboratory by its business code, that `lab_code` must name an existing Laboratory, or the request fails with `ERR_LAB_NOT_FOUND`. Prior-notice filing likewise validates its body-carried `facility_id` and `importer_id` (in that order), and entry creation validates its body-carried `prior_notice_id`. Body-carried references the narratives do not call out are not resolved: placing an import alert and initiating a recall accept a `facility_id` that names no existing facility, and an inspection scheduled against an unresolvable `facility_id` fails the foreign-facility check with `ERR_INSPECTION_REQUIRES_FOREIGN_FACILITY` rather than a 404.

## 3. Business Logic & Workflows

### 3.1. Facility Registration, Biennial Renewal, and Suspension

A food facility enters the system when a `FacilityOwner` principal registers it with its `legal_name`, its `facility_kind` — exactly one of `DOMESTIC` or `FOREIGN` — its `country_code` as an ISO 3166-1 alpha-2 code, and a `ufi`, the Unique Facility Identifier supplied by the registrant. The `ufi` must be unique across all registered facilities; a duplicate is rejected with `ERR_DUPLICATE_UFI` (HTTP 409). Registration itself carries no ownership check, because the facility's identity does not exist yet: the server mints both the facility `id` and its `registration_number`, and the registering principal thereafter authenticates as `FacilityOwner` with `X-User-ID` equal to that facility `id`. A new facility is created with `registration_status` set to `REGISTERED`, with `registered_at` set to the current logical-clock instant, and with `expires_at` computed as `registered_at` plus 730 days. Two computed counters track the facility's compliance posture from that moment: `violation_count`, starting at 0, and `open_detention_count`, also starting at 0.

Registration is biennial and renewal is windowed. Renewal belongs to the facility itself: the caller's `X-User-ID` must equal the target facility's `id`, or the request fails with `ERR_OWNERSHIP_VIOLATION`. A renewal request is evaluated only for a facility in `REGISTERED` or `EXPIRED` status; a `SUSPENDED` facility is not renewable, and the attempt fails with `ERR_FACILITY_NOT_RENEWABLE` (HTTP 409) — a state failure that is reported even when the timing window happens to be closed as well. Provided the state permits it, the renewal window runs from 90 days before `expires_at` through 30 days after `expires_at`, both bounds inclusive; a request outside that window fails with `ERR_RENEWAL_WINDOW_CLOSED` (HTTP 422). The request must also carry `expected_facility_version` per §2.7. When the facility is still `REGISTERED` at renewal time (the current instant is before `expires_at`), the new `expires_at` extends the old one by a further 730 days. When the facility has already lapsed to `EXPIRED` (the current instant is at or after `expires_at`), the new `expires_at` is instead set to the current logical instant plus 730 days and the facility returns to `REGISTERED`. Either way the facility's `version` increments by 1. All of these comparisons are whole-second timestamp comparisons against the logical clock, and the expiry sweep itself is strictly-less-than as described in §2.4 — at the exact instant of `expires_at`, the facility is still registered.

Suspension is not a self-service transition. A facility moves from `REGISTERED` to `SUSPENDED` only as a cascade of an inspection refusal (see §3.8), incrementing `version` by 1. `SUSPENDED` is absorbing in this revision of the system: no reinstatement path exists, and every subsequent renewal attempt fails with `ERR_FACILITY_NOT_RENEWABLE`.

Registration posture gates downstream commerce. Filing a prior notice and creating an import entry both require the manufacturing facility to be `REGISTERED`; an `EXPIRED` or `SUSPENDED` facility causes the filing to fail with `ERR_REGISTRATION_NOT_ACTIVE` (HTTP 422).

### 3.2. Importer Standing and Laboratory Capacity

Importer firms are onboarded by a `PlatformAdmin`, who supplies the firm's `firm_name` and an `account_code` that must be unique across importers (duplicates are rejected with `ERR_DUPLICATE_ACCOUNT_CODE`, HTTP 409). A new importer begins in `GOOD_STANDING` with `refusal_count` 0 and `terminal_entry_count` 0, and thereafter authenticates with `X-User-ID` equal to its importer `id`. The `standing` field takes one of three values — `GOOD_STANDING`, `PROBATION`, or `REVOKED` — and is never set directly; it is recomputed.

Whenever one of the importer's entries reaches any terminal disposition — `RELEASED`, `REFUSED`, `EXPORTED`, or `RECONDITIONED` — including terminal states reached through cascades and through the deadline sweep, the importer's standing is recomputed in a pinned evaluation order. First, the triggering entry's outcome is applied to the counters: a refusal increments `refusal_count`, and every terminal outcome increments `terminal_entry_count`. Second, the refusal ratio is formed as `refusal_count` divided by the larger of 1 and `terminal_entry_count`. Third, the new standing is assigned: `REVOKED` when `refusal_count` has reached 4 or the ratio is at least one-half; otherwise `PROBATION` when `refusal_count` has reached 2 or the ratio is at least one-fifth; otherwise `GOOD_STANDING`. Ratio comparisons are exact rational comparisons with no floating-point rounding — the one-fifth test is whether `refusal_count` multiplied by 5 is at least `terminal_entry_count`, and the one-half test is whether `refusal_count` multiplied by 2 is at least `terminal_entry_count`. Fourth and finally, the new standing applies only to *future* prior-notice filings and entry creations; the entry whose outcome triggered the recompute is never retroactively affected by the standing it produced.

Standing has teeth in two places. A `REVOKED` importer can no longer file prior notices or create entries — both attempts fail with `ERR_IMPORTER_REVOKED` (HTTP 409). A `PROBATION` importer is not blocked, but every screening score computed for its entries carries a 15-point uplift (see §3.4).

Laboratories are simpler. A `PlatformAdmin` registers each laboratory with a `lab_code` — unique across laboratories, with duplicates rejected as `ERR_DUPLICATE_LAB_CODE` (HTTP 409) — and a `daily_sample_capacity`, an integer greater than 0 expressing the maximum total `sample_units` schedulable for that laboratory per UTC calendar day. The capacity is enforced where samples are ordered, in §3.5.

### 3.3. Prior Notice: Filing and Amendment

Before an imported food shipment arrives, its `Importer` files a prior notice carrying the full data set: the `importer_id` of the filing firm — which must equal the caller's `X-User-ID`, or the filing fails with `ERR_OWNERSHIP_VIOLATION` — the `facility_id` of the foreign manufacturing facility, the article's `product_code`, its `product_risk_class` (one of `LOW`, `STANDARD`, or `HIGH`), the `transport_mode` (`VESSEL`, `AIR`, `RAIL`, or `ROAD`), the expected `arrival_eta`, the `declared_units` (greater than 0), the `unit_value_cents` (zero or greater), and the `port_code` of the port of entry. Both referenced principals must exist: an unknown facility fails with `ERR_FACILITY_NOT_FOUND` and an unknown importer with `ERR_IMPORTER_NOT_FOUND`. The facility must be `REGISTERED` (§3.1's gate) and the importer must not be `REVOKED` (§3.2's gate). No facility-kind restriction applies at filing: a notice may name a `DOMESTIC` facility, in which case only the registration gate applies. A compliant filing is created `CONFIRMED`, with `is_amendment` false and `parent_pn_id` null.

Timing is validated against the logical clock at filing. The **lead time** is the interval from the current logical instant to `arrival_eta`, computed exactly to the minute. An initial filing must observe a minimum lead that depends on the transport mode: 8 hours for `VESSEL`, 4 hours for `AIR`, 4 hours for `RAIL`, and 2 hours for `ROAD`. A lead shorter than the applicable minimum is rejected with `ERR_NOTICE_TOO_LATE` (HTTP 422). The lead may not exceed 720 hours either; a farther-out arrival is rejected with `ERR_NOTICE_TOO_EARLY` (HTTP 422). Both boundaries are inclusive: a lead exactly equal to the mode minimum passes, and a lead of exactly 720.0 hours passes.

Plans change, and a notice still in `CONFIRMED` may be amended by its owning importer (again `X-User-ID` must equal the notice's `importer_id`; a notice in any other status fails with `ERR_PN_NOT_CONFIRMED`, HTTP 409). Amending supersedes: the original notice flips to `SUPERSEDED`, and a brand-new notice is created `CONFIRMED` with `is_amendment` set to true and `parent_pn_id` set to the superseded notice's `id`. The amendment payload always carries a fresh `arrival_eta` and may optionally replace `declared_units`, `unit_value_cents`, or `port_code`; every field not supplied is inherited from the superseded notice. Amendments are judged under a relaxed timing variant: the minimum lead is half the transport mode's minimum, rounded up to a whole hour — 4 hours for `VESSEL`, 2 for `AIR`, 2 for `RAIL`, and 1 for `ROAD` — while the 720-hour maximum is unchanged. Consider a vessel shipment whose ETA is 6 hours out: an initial filing would be rejected as too late, but the same lead is acceptable on an amendment. All three checks — too-late, too-early, ownership — apply to the amendment exactly as to an initial filing; the registration and importer-standing gates of the initial filing are not re-evaluated on an amendment.

Two further fates can befall a notice. Creating an import entry consumes it (§3.4), flipping it to `CONSUMED` — and exactly one entry may ever consume a notice, so a second attempt fails with `ERR_PN_NOT_CONFIRMED`. And if its facility is suspended through an inspection refusal, every one of the facility's still-`CONFIRMED` notices is compromised to `COMPROMISED` (§3.8). `SUPERSEDED`, `COMPROMISED`, and `CONSUMED` are all terminal; any operation that requires a `CONFIRMED` notice rejects the others with `ERR_PN_NOT_CONFIRMED`.

### 3.4. Entry Creation and Screening Review

An import entry is filed by an `Importer` against a `CONFIRMED` prior notice it owns, with `prior_notice_id` as the payload's key reference. The entry copies its `importer_id`, `facility_id`, `product_code`, `product_risk_class`, `declared_units`, and `unit_value_cents` from the notice, and its `is_amendment_pn` flag mirrors the notice's `is_amendment`; the `declared_units` total is immutable for the life of the entry and anchors the conservation invariant of §2.8. Filing flips the notice to `CONSUMED`. Beyond the notice-state and ownership checks, creation is gated on the facility being `REGISTERED` (`ERR_REGISTRATION_NOT_ACTIVE`), the importer not being `REVOKED` (`ERR_IMPORTER_REVOKED`), and the recall safety gate: when a recall exists in `CLASSIFIED` status with classification `CLASS_I` for the same `facility_id` and `product_code` as the new entry, creation is rejected with `ERR_ACTIVE_RECALL_BLOCKS_ENTRY` (HTTP 422). Recalls still `INITIATED` or already `TERMINATED` do not block, and the safety gate outranks referential and temporal failures under §2.6's order.

A new entry begins with `review_status` set to `PENDING_SCREENING` and `disposition_status` set to `PENDING` — two independent dimensions that evolve in parallel. Its `screening_decision` starts as `NONE`, `screening_score` is null until screening runs, `scoring_variant_applied` is null likewise, and `probation_adjustment_applied` starts at 0; all five unit buckets (`units_held`, `units_released`, `units_refused`, `units_exported`, `units_destroyed`) start at 0, `bond_amount_cents` is null, and `detained_at`, `response_deadline_at`, `detained_under_alert_id`, and `disposition_completed_at` are all null.

Screening is performed by an `EntryReviewer` and is allowed only while `review_status` is `PENDING_SCREENING`; a second screening attempt fails with `ERR_ENTRY_INVALID_STATE` (HTTP 409). Screening computes a score from the entry, its facility, and its importer:

- **Base points** come from `product_risk_class`: 10 for `LOW`, 30 for `STANDARD`, 60 for `HIGH`.
- **History terms** add the facility's `violation_count` capped at 5, multiplied by a violation weight, plus the importer's `refusal_count` capped at 3, multiplied by a refusal weight. The weights depend on which variant applies. When the facility's `violation_count` is 0 *and* the importer's `refusal_count` is 0 at screening time, the `BASE` variant applies with weights 8 and 12. Otherwise — any violation history or any prior refusal — the `HISTORY_WEIGHTED` variant applies with weights 16 and 24, so identical entry data scores strictly higher once a compliance history exists.
- **Circumstance terms** add 35 when an `ACTIVE` import alert matches the entry's scope, 10 when `is_amendment_pn` is true, and 15 when the importer's `standing` is `PROBATION`.

The score is the sum of these terms, capped at 100, computed with integer arithmetic. Screening records `screening_score`, the `scoring_variant_applied` (`BASE` or `HISTORY_WEIGHTED`), and `probation_adjustment_applied` (0 or 15, exactly the probation uplift included in the score) on the entry. The decision then follows: whenever an `ACTIVE` alert matches the entry's scope, the decision is `DETAIN` regardless of the numeric score — detention without physical examination — and the score is still computed and stored even though it cannot change the outcome. With no alert match, a score of 40 or more yields `SAMPLE`; anything below 40 yields `RELEASE`. For a worked contrast, take a `STANDARD` article whose facility has `violation_count` 1 with a clean importer and no alert: the `BASE` arithmetic would total 38 and release, but the history means the `HISTORY_WEIGHTED` variant actually applies, totalling 46 and routing the entry to sampling.

A `RELEASE` decision at screening is self-executing: the entry's `review_status` becomes `SCREENED`, its `disposition_status` becomes `RELEASED`, `units_released` is set to the full `declared_units`, `disposition_completed_at` is set to the current logical instant, and the importer's standing is recomputed. Because such an entry is already terminal, a later explicit release call on it is rejected with `ERR_ENTRY_INVALID_STATE`. A `SAMPLE` decision leaves the disposition `PENDING` awaiting laboratory work (§3.5). A `DETAIN` decision opens a detention as described in §3.6. In every case the entry leaves screening with `review_status` `SCREENED`.

### 3.5. Laboratory Sampling and Results

An entry that screened to `SAMPLE` cannot be released on the reviewer's judgment alone; it needs laboratory evidence. An `EntryReviewer` orders an analysis by supplying the `lab_code` of an existing laboratory, the `sample_units` to draw (greater than 0), and the `analysis_date` — a UTC calendar date in `YYYY-MM-DD` form on which the analysis is scheduled. Three guards apply, in §2.6's order: the `lab_code` must name an existing Laboratory, or the order fails with `ERR_LAB_NOT_FOUND`; the entry must currently be `SCREENED` with `screening_decision` `SAMPLE` and disposition still `PENDING`, or the order fails with `ERR_ENTRY_INVALID_STATE`; and the `analysis_date` must not fall before the current logical date, or the order fails with `ERR_SAMPLE_DATE_PAST` (HTTP 422) — a temporal failure that is reported even when capacity is also exhausted. Capacity is the aggregate kind: the sum of `sample_units` already scheduled for that laboratory on that UTC date, plus the new order's `sample_units`, must not exceed the laboratory's `daily_sample_capacity`, or the order fails with `ERR_LAB_CAPACITY_EXCEEDED` (HTTP 409). An analysis whose result has already been recorded still occupies its day's capacity — recording a result does not free the laboratory's capacity for that date. A successful order creates a SampleAnalysis in `SCHEDULED` status with `result` `PENDING`, linked back to the entry through its `entry_id`; the analyses linked to an entry can be listed in reverse through the entry's sample collection.

Results are recorded by an `EntryReviewer` against a scheduled sample. The sample must still be `SCHEDULED` — recording twice is rejected with `ERR_ENTRY_INVALID_STATE` — and the supplied `result` must be exactly `COMPLIANT` or `VIOLATIVE`, anything else failing with `ERR_INVALID_REQUEST`. Recording flips the sample to `RESULT_RECORDED` with the supplied result. A `COMPLIANT` result leaves the entry's disposition `PENDING`, ready for release. A `VIOLATIVE` result detains the owning entry for cause, provided it is still in `PENDING` disposition: the disposition becomes `DETAINED`, `detained_at` is set to the current logical instant, `response_deadline_at` opens a fresh 240-hour window, `units_held` is set to the full `declared_units`, `detained_under_alert_id` is left null (no alert is involved), and the facility's `open_detention_count` increases by 1.

Release of a sample-routed entry — available to both `EntryReviewer` and `ComplianceOfficer` — requires the disposition still `PENDING`, the `SAMPLE` decision, at least one linked analysis recorded `COMPLIANT`, and no linked analysis left unreconciled in a pending or `VIOLATIVE` state; otherwise the release fails with `ERR_ENTRY_INVALID_STATE`. On release the disposition becomes `RELEASED`, `units_released` is brought up to the full `declared_units`, `disposition_completed_at` is set, and the importer's standing is recomputed.

### 3.6. Detention and Its Resolution Paths

However it arises — a `DETAIN` decision at screening, the placement of a matching import alert (§3.7), an inspection-refusal cascade (§3.8), or a `VIOLATIVE` sample (§3.5) — a detention always opens the same way. The entry's `disposition_status` becomes `DETAINED` while `review_status` is left untouched, the parallel dimensions evolving independently. `detained_at` records the logical instant detention began, and `response_deadline_at` is computed as `detained_at` plus 240 hours — ten 24-hour days. `units_held` is set to the full `declared_units`, and the facility's `open_detention_count` increases by 1. For detentions under an import alert, `detained_under_alert_id` records the alert; for for-cause detentions it stays null. When several `ACTIVE` alerts match the same entry's scope, the entry is detained exactly once, under whichever matching alert was created first (ties are broken by creation order, which the server records and which is total), and an entry already `DETAINED` is never re-detained by a second matching alert.

While detained, the importing firm has two self-service exits, each requiring the caller's `X-User-ID` to equal the entry's `importer_id` (otherwise `ERR_OWNERSHIP_VIOLATION`) and each closing at the response deadline — once the logical time passes `response_deadline_at`, both fail with `ERR_DETENTION_RESPONSE_DEADLINE_PASSED` (HTTP 422):

- **Requesting reconditioning** asks to bring the article into compliance under bond. The request carries a `lots` array that must be non-empty, with every lot's `quantity` greater than 0 and every lot's `unit_value_cents` zero or greater, failing which the request is rejected with `ERR_INVALID_REQUEST`. The bond is computed and stored on the entry as `bond_amount_cents`, and the disposition remains `DETAINED`. A repeated reconditioning request on a still-detained entry is permitted and recomputes and overwrites `bond_amount_cents`. The bond's evaluation order is pinned, because rounding order changes the result: for each lot, the lot's value is its `quantity` multiplied by its `unit_value_cents`, an exact integer; each lot's bond share is that value multiplied by one-tenth (0.10), rounded half up to whole cents *per lot, before any summation*; the lot shares are then summed. Separately, the days detained are the whole 24-hour days elapsed since `detained_at` (any partial day discarded, never negative), and storage is those days multiplied by 1500 cents. The bond is the summed lot shares plus the storage charge. For example, three lots each of `quantity` 1 and `unit_value_cents` 105 yield a per-lot bond of 11 cents (10.5 rounded half up), hence 33 cents in total — summing first and rounding once would wrongly produce 32.
- **Exporting** the entry moves all held units out: `units_exported` increases by `units_held`, `units_held` returns to 0, the facility's `open_detention_count` decreases by 1, the disposition becomes `EXPORTED`, `disposition_completed_at` is set, and the importer's standing is recomputed — noting that `EXPORTED` is terminal but is *not* a refusal and does not increment `refusal_count`.

The compliance branch holds the other resolutions. Recording a **reconditioning outcome** is a `ComplianceOfficer` action valid only while the entry is `DETAINED` with a non-null `bond_amount_cents` (otherwise `ERR_ENTRY_INVALID_STATE`); the reported `units_passed` and `units_failed` must each be zero or greater and must sum exactly to `units_held`, or the report fails with `ERR_UNITS_ACCOUNTING_MISMATCH` (HTTP 422). Passed units move into `units_released`, failed units into `units_destroyed`, `units_held` returns to 0, and `open_detention_count` decreases by 1. When `units_failed` is 0 the entry reaches `RECONDITIONED`: `disposition_completed_at` is set and standing is recomputed, with no refusal recorded. When any unit failed, the *entire entry* counts as a refusal for compliance purposes even though the destroyed units sit in the destroyed bucket: the disposition becomes `REFUSED`, the facility's `violation_count` increases by 1, `disposition_completed_at` is set, and standing is recomputed as a refusal.

**Refusing admission** — a `ComplianceOfficer` action, also reachable from the deadline sweep of §2.4 — moves all held units into `units_refused`, zeroes `units_held`, decrements `open_detention_count`, increments the facility's `violation_count` by 1, sets the disposition `REFUSED` with `disposition_completed_at`, and recomputes the importer's standing as a refusal. The only precondition is that the entry is still `DETAINED`; otherwise the refusal fails with `ERR_ENTRY_INVALID_STATE`.

Finally, a detained entry can be **released** when detention-without-physical-examination evidence is accepted. Releasing from `DETAINED` is reserved to a `ComplianceOfficer`: an `EntryReviewer` attempting it is rejected with `ERR_FORBIDDEN` (HTTP 403), per §2.1. Release moves all held units into `units_released`, zeroes `units_held`, decrements `open_detention_count`, sets `disposition_completed_at` if it was not already set, marks the disposition `RELEASED`, and recomputes the importer's standing. The same release also arrives as a cascade when a petition against the holding alert is approved (§3.7). Every one of these resolutions preserves the conservation invariant of §2.8: units move between buckets, never into or out of existence.

### 3.7. Import Alerts and Petitions for Removal

A `ComplianceOfficer` places an import alert with a `scope_type` of exactly `FIRM` or `COUNTRY_PRODUCT`, plus an optional free-text `reason` (empty by default). The scope fields must be consistent with the scope type: a `FIRM` alert requires `facility_id` and forbids `country_code` and `product_code`; a `COUNTRY_PRODUCT` alert requires `country_code` and `product_code` and forbids `facility_id`. Inconsistent scope fields are rejected with `ERR_INVALID_REQUEST` (HTTP 400). An alert is created `ACTIVE`, records its creator's `X-User-ID` in `created_by_user_id` — the segregation-of-duties key used at adjudication — and has `lifted_at` null while active.

Placement has immediate teeth. Every import entry matching the alert's scope whose disposition is still `PENDING` — whatever its `review_status` — is detained without physical examination: for a `FIRM` alert, entries whose `facility_id` equals the alert's `facility_id`; for a `COUNTRY_PRODUCT` alert, entries whose facility's `country_code` equals the alert's `country_code` and whose own `product_code` equals the alert's `product_code`. Each affected entry opens a detention exactly as in §3.6, with `detained_under_alert_id` set to the new alert. Entries already terminal or already detained are untouched.

Removal runs through petitions. A `FacilityOwner` files a petition against an alert that is still `ACTIVE` (filing against a `LIFTED` alert fails with `ERR_IMPORT_ALERT_NOT_ACTIVE`, HTTP 409), carrying `expected_import_alert_version` per §2.7 and an initial `evidence_links` list, which may be empty at filing and extended later. The filer must lie inside the alert's scope: for a `FIRM` alert, the caller's `X-User-ID` must equal the alert's `facility_id`; for a `COUNTRY_PRODUCT` alert, the filing facility's `country_code` must equal the alert's `country_code` *and* the filer must have at least one prior notice or import entry bearing the alert's `product_code`. A filer outside the scope is rejected with `ERR_ALERT_SCOPE_MISMATCH` (HTTP 422). The petition is created in `EVIDENCE_REVIEW` status, with `alert_id` taken from the alert being petitioned and `filed_by_facility_id` set to the caller's facility `id`; `consecutive_compliant_count` stays null until adjudication. Filing a petition increments the *alert's* `version` by 1 — which is precisely the mutation the OCC field protects petitioners against missing. Petitions are reachable in both directions: listed per alert, and listed per filing facility.

While the petition remains `EVIDENCE_REVIEW`, the filing facility may submit additional evidence — again with `X-User-ID` equal to `filed_by_facility_id`, else `ERR_OWNERSHIP_VIOLATION` — which extends `evidence_links` and increments the petition's `version` by 1. Once the petition leaves `EVIDENCE_REVIEW`, both evidence submission and adjudication fail with `ERR_PETITION_NOT_REVIEWABLE` (HTTP 409).

Adjudication is a `ComplianceOfficer` decision, supplied as `decision`, of `APPROVE` or `DENY`, with one structural safeguard: the adjudicator's `X-User-ID` must differ from the alert's `created_by_user_id`, or the adjudication fails with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403) — the officer who placed the alert may never judge the petition against it. An `APPROVE` decision carries two further sufficiency requirements, evaluated only for approvals: the alert scope must show a **consecutive compliant streak** of at least 3, and `evidence_links` must be non-empty; either shortfall rejects the approval with `ERR_INSUFFICIENT_COMPLIANT_SHIPMENTS` (HTTP 422).

The streak is computed at adjudication time over the alert's scope. The candidate set is every import entry in scope — `facility_id` equal to the alert's `facility_id` for a `FIRM` alert; facility `country_code` equal to the alert's `country_code` and entry `product_code` equal to the alert's `product_code` for a `COUNTRY_PRODUCT` alert — restricted to entries whose `disposition_completed_at` is set and falls at or after the alert's `created_at`. Candidates are ordered by `disposition_completed_at` ascending, with ties broken by `created_at` ascending and any remaining ties (resources created at the same logical instant) broken by the server's creation sequence — never by `id`. The streak is the length of the *trailing* run of entries whose terminal disposition is `RELEASED` or `RECONDITIONED`; any `REFUSED` or `EXPORTED` entry breaks the run. Whatever the outcome, the computed count is stored on the petition as `consecutive_compliant_count`.

On approval, the petition becomes `APPROVED` and the alert is lifted: the alert's `status` becomes `LIFTED`, `lifted_at` records the logical instant, and the alert's `version` increments by 1. Lifting cascades: every import entry still `DETAINED` under this alert (`detained_under_alert_id` equal to it) is released exactly as in §3.6's compliance release — held units move to `units_released`, `open_detention_count` decrements, `disposition_completed_at` is set — with the importer's standing recomputed per released entry. On denial, the petition becomes `DENIED` with its streak stored, and the alert remains `ACTIVE`. `APPROVED` and `DENIED` are both terminal for the petition.

### 3.8. Foreign Facility Inspections

Foreign facilities are subject to inspection scheduling by a `FieldInspector`. Scheduling supplies the target `facility_id` — which must belong to a `FOREIGN` facility, a `DOMESTIC` target failing with `ERR_INSPECTION_REQUIRES_FOREIGN_FACILITY` (HTTP 422) — and a half-open interval from `scheduled_start_at` to `scheduled_end_at`, where the end must be strictly after the start (otherwise `ERR_INVALID_REQUEST`). One inspector may not hold two overlapping engagements: if the new interval intersects another `SCHEDULED` inspection of the same inspector — intervals being half-open, so a new start exactly equal to an existing end is adjacency and is allowed — scheduling fails with `ERR_INSPECTION_SCHEDULE_OVERLAP` (HTTP 409). The inspection is created `SCHEDULED`, and the scheduling inspector's `X-User-ID` is recorded as `inspector_user_id`; `findings_violation_count` is null until the inspection is completed. A facility's inspections can be listed in reverse through the facility's inspection collection.

Completion belongs to the scheduling inspector alone: the caller's `X-User-ID` must equal the inspection's `inspector_user_id`, else `ERR_OWNERSHIP_VIOLATION`, and the inspection must still be `SCHEDULED`, else `ERR_INSPECTION_NOT_OPEN` (HTTP 409). Completion records the `findings_violation_count` (zero or greater) supplied in the report, adds it to the facility's `violation_count`, increments the facility's `version`, and moves the inspection to `COMPLETED`.

The facility, for its part, may refuse to permit the inspection: a `FacilityOwner` whose `X-User-ID` equals the inspection's `facility_id` (else `ERR_OWNERSHIP_VIOLATION`) records the refusal while the inspection is `SCHEDULED` (else `ERR_INSPECTION_NOT_OPEN`). Refusal moves the inspection to `REFUSED_BY_FACILITY` and fires a three-link cascade. **Link 1:** the facility itself — if currently `REGISTERED` — is suspended to `SUSPENDED` with `version` incremented (an already-`EXPIRED` facility stays `EXPIRED`, and the remaining links still fire). **Link 2:** every import entry of that facility whose disposition is `PENDING`, whatever its `review_status`, is detained for cause exactly as in §3.6 — `detained_at` set, a fresh 240-hour `response_deadline_at`, `units_held` set to `declared_units`, `detained_under_alert_id` null, and `open_detention_count` incremented per entry. **Link 3:** every prior notice of the facility still in `CONFIRMED` is flipped to `COMPROMISED`, rendering it unusable for entry creation. The suspension is permanent: per §3.1, `SUSPENDED` is absorbing and renewal is impossible.

### 3.9. Recalls: Classification, Effectiveness Verification, and Termination

When violative product has already been distributed, a `RecallCoordinator` initiates a recall for the responsible `facility_id` and `product_code`, declaring the `quantity_distributed` (greater than 0). The recall is created `INITIATED` with `classification` `NONE`; its accounting starts clean with `quantity_recovered`, `quantity_corrected`, and `quantity_destroyed` all 0, `quantity_outstanding` equal to the full `quantity_distributed`, and `consignees_contacted` and `consignees_total` both 0.

Classification is a distinct act: while the recall is `INITIATED` (otherwise `ERR_RECALL_INVALID_STATE`, HTTP 409), the coordinator assigns a `classification` of `CLASS_I`, `CLASS_II`, or `CLASS_III` — any other value fails with `ERR_INVALID_REQUEST` — moving the recall to `CLASSIFIED`. Classification has an immediate external effect: from that moment, a `CLASS_I` recall in `CLASSIFIED` status activates the safety gate of §3.4, blocking creation of any new entry for the same facility and product code with `ERR_ACTIVE_RECALL_BLOCKS_ENTRY`. Recalls still `INITIATED` and recalls already `TERMINATED` never block.

While `CLASSIFIED`, the coordinator records effectiveness verification rounds. Each round reports three quantity deltas — `delta_recovered`, `delta_corrected`, and `delta_destroyed` — each of which must be zero or greater, with their sum not exceeding the recall's current `quantity_outstanding`; an over-report fails with `ERR_UNITS_ACCOUNTING_MISMATCH` (HTTP 422). The round also reports consignee contact figures: `consignees_contacted` is a non-negative *delta* added onto the cumulative contacted count, while `consignees_total` *replaces* the reported total consignee count and must be at least the new cumulative contacted figure, failing which the round is rejected with `ERR_INVALID_REQUEST`. A recorded round accumulates the three quantity buckets, recomputes the derived fields, and increments the recall's `version` by 1.

The derived fields are computed as follows. `quantity_outstanding` is `quantity_distributed` minus the three accounted buckets. `effectiveness_pct` is the accounted share — recovered plus corrected plus destroyed — expressed as a percentage of `quantity_distributed`, rounded half up to 1 decimal place. `consignee_contact_pct` is `consignees_contacted` as a percentage of `consignees_total`, likewise rounded half up to 1 decimal place, and is 0.0 whenever `consignees_total` is 0. The conservation invariant of §2.8 holds throughout: the three accounted buckets plus `quantity_outstanding` always equal `quantity_distributed`.

Termination releases the market from the recall. A recall may be terminated only from `CLASSIFIED` (otherwise `ERR_RECALL_INVALID_STATE`) and only once its classification's threshold is met: a `CLASS_I` recall requires `effectiveness_pct` of exactly 100.0 *and* `consignee_contact_pct` of exactly 100.0; a `CLASS_II` recall requires `effectiveness_pct` of at least 95.0; a `CLASS_III` recall requires `effectiveness_pct` of at least 90.0. Terminating early fails with `ERR_EFFECTIVENESS_THRESHOLD_NOT_MET` (HTTP 422). A successful termination moves the recall to `TERMINATED`, and from that instant its safety gate ceases to block new entries.

## 4. Endpoint Definitions

Operations that create a new resource — registering a facility, onboarding an importer or laboratory, filing a prior notice, amending one (which creates the superseding notice), creating an entry, ordering a sample analysis, placing an import alert, filing a petition, scheduling an inspection, or initiating a recall — return `201 Created`. Operations that act on an existing resource without creating a new one, and all reads, return `200 OK`. Request payloads, response payloads, and side effects for each operation are specified in the narratives of §2 and §3; the table below is a routing and authorization summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock and atomically run the ops checkpoint (facility expiry sweep, detention deadline sweep) | PlatformAdmin |
| POST | `/registry/facilities` | Register a food facility | FacilityOwner |
| GET | `/registry/facilities/{id}` | Read one facility, including computed `expires_at`, `violation_count`, `open_detention_count` | Any authenticated role |
| POST | `/registry/facilities/{id}/renew` | Renew a facility registration (OCC-guarded) | FacilityOwner |
| POST | `/registry/importers` | Onboard an importer firm | PlatformAdmin |
| POST | `/registry/laboratories` | Register a laboratory with its daily sample capacity | PlatformAdmin |
| POST | `/registry/prior-notices` | File a prior notice for an imported shipment | Importer |
| GET | `/registry/prior-notices/{id}` | Read one prior notice | Any authenticated role |
| GET | `/registry/prior-notices` | List prior notices with filters and pagination | Any authenticated role |
| POST | `/registry/prior-notices/{id}/amend` | Amend a CONFIRMED notice, superseding it with a new one | Importer |
| POST | `/registry/entries` | File an import entry against a CONFIRMED prior notice | Importer |
| GET | `/registry/entries/{id}` | Read one entry, including screening and disposition buckets | Any authenticated role |
| GET | `/registry/entries` | List entries with filters and pagination | Any authenticated role |
| POST | `/registry/entries/{id}/screen` | Run entry review screening and apply the computed decision | EntryReviewer |
| POST | `/registry/entries/{id}/record-sample` | Order a laboratory sample analysis for a SAMPLE-decision entry | EntryReviewer |
| POST | `/registry/entries/{id}/release` | Release an entry (a detained entry may be released only by a ComplianceOfficer) | EntryReviewer, ComplianceOfficer |
| POST | `/registry/entries/{id}/request-reconditioning` | Request reconditioning of a detained entry and compute the bond | Importer |
| POST | `/registry/entries/{id}/record-reconditioning-outcome` | Record the reconditioning result for a detained entry | ComplianceOfficer |
| POST | `/registry/entries/{id}/export` | Export a detained entry before the response deadline | Importer |
| POST | `/registry/entries/{id}/refuse` | Refuse admission of a detained entry | ComplianceOfficer |
| GET | `/registry/entries/{id}/samples` | List sample analyses linked to an entry | Any authenticated role |
| POST | `/registry/samples/{id}/record-result` | Record the laboratory result for a scheduled sample | EntryReviewer |
| POST | `/registry/import-alerts` | Place an import alert, auto-detaining matching open entries | ComplianceOfficer |
| GET | `/registry/import-alerts/{id}` | Read one import alert | Any authenticated role |
| GET | `/registry/import-alerts` | List import alerts with filters and pagination | Any authenticated role |
| POST | `/registry/import-alerts/{id}/petitions` | File a petition for removal from an ACTIVE alert (OCC-guarded) | FacilityOwner |
| GET | `/registry/import-alerts/{id}/petitions` | List petitions filed against an alert | Any authenticated role |
| GET | `/registry/facilities/{id}/petitions` | List petitions filed by a facility | Any authenticated role |
| POST | `/registry/alert-petitions/{id}/submit-evidence` | Extend a petition's corrective-evidence list | FacilityOwner |
| POST | `/registry/alert-petitions/{id}/adjudicate` | Adjudicate a petition (approve lifts the alert; deny leaves it active) | ComplianceOfficer |
| POST | `/registry/inspections` | Schedule a foreign-facility inspection | FieldInspector |
| GET | `/registry/facilities/{id}/inspections` | List inspections of a facility | Any authenticated role |
| POST | `/registry/inspections/{id}/complete` | Complete a scheduled inspection and record findings | FieldInspector |
| POST | `/registry/inspections/{id}/refuse-entry` | Record a facility's refusal to permit inspection (fires the three-link cascade) | FacilityOwner |
| POST | `/registry/recalls` | Initiate a recall for a firm's distributed product | RecallCoordinator |
| GET | `/registry/recalls/{id}` | Read one recall, including derived quantities and percentages | Any authenticated role |
| GET | `/registry/recalls` | List recalls with filters and pagination | Any authenticated role |
| POST | `/registry/recalls/{id}/classify` | Assign the recall classification (activates the CLASS_I safety gate) | RecallCoordinator |
| POST | `/registry/recalls/{id}/record-effectiveness` | Record an effectiveness verification round | RecallCoordinator |
| POST | `/registry/recalls/{id}/terminate` | Terminate a classified recall once its threshold is met | RecallCoordinator |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3; this catalogue is an identifier-to-status reference only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_OWNERSHIP_VIOLATION` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_FACILITY_NOT_FOUND` | 404 Not Found |
| `ERR_IMPORTER_NOT_FOUND` | 404 Not Found |
| `ERR_PRIOR_NOTICE_NOT_FOUND` | 404 Not Found |
| `ERR_ENTRY_NOT_FOUND` | 404 Not Found |
| `ERR_SAMPLE_NOT_FOUND` | 404 Not Found |
| `ERR_IMPORT_ALERT_NOT_FOUND` | 404 Not Found |
| `ERR_ALERT_PETITION_NOT_FOUND` | 404 Not Found |
| `ERR_INSPECTION_NOT_FOUND` | 404 Not Found |
| `ERR_RECALL_NOT_FOUND` | 404 Not Found |
| `ERR_LAB_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_DUPLICATE_UFI` | 409 Conflict |
| `ERR_DUPLICATE_ACCOUNT_CODE` | 409 Conflict |
| `ERR_DUPLICATE_LAB_CODE` | 409 Conflict |
| `ERR_FACILITY_NOT_RENEWABLE` | 409 Conflict |
| `ERR_PN_NOT_CONFIRMED` | 409 Conflict |
| `ERR_IMPORTER_REVOKED` | 409 Conflict |
| `ERR_ENTRY_INVALID_STATE` | 409 Conflict |
| `ERR_IMPORT_ALERT_NOT_ACTIVE` | 409 Conflict |
| `ERR_PETITION_NOT_REVIEWABLE` | 409 Conflict |
| `ERR_INSPECTION_NOT_OPEN` | 409 Conflict |
| `ERR_RECALL_INVALID_STATE` | 409 Conflict |
| `ERR_LAB_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_INSPECTION_SCHEDULE_OVERLAP` | 409 Conflict |
| `ERR_REGISTRATION_NOT_ACTIVE` | 422 Unprocessable Entity |
| `ERR_ACTIVE_RECALL_BLOCKS_ENTRY` | 422 Unprocessable Entity |
| `ERR_NOTICE_TOO_LATE` | 422 Unprocessable Entity |
| `ERR_NOTICE_TOO_EARLY` | 422 Unprocessable Entity |
| `ERR_RENEWAL_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_DETENTION_RESPONSE_DEADLINE_PASSED` | 422 Unprocessable Entity |
| `ERR_SAMPLE_DATE_PAST` | 422 Unprocessable Entity |
| `ERR_INSPECTION_REQUIRES_FOREIGN_FACILITY` | 422 Unprocessable Entity |
| `ERR_ALERT_SCOPE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_COMPLIANT_SHIPMENTS` | 422 Unprocessable Entity |
| `ERR_UNITS_ACCOUNTING_MISMATCH` | 422 Unprocessable Entity |
| `ERR_EFFECTIVENESS_THRESHOLD_NOT_MET` | 422 Unprocessable Entity |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
