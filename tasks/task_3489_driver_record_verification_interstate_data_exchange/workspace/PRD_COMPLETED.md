# Driver Record Exchange API — Product Requirements Document

## 1. Introduction

State driver licensing authorities do not operate in isolation. When a driver relocates across a state line, when a court conviction is handed down against a license held elsewhere, or when a branded vehicle title is presented for re-titling in a new jurisdiction, the integrity of every member's records depends on a shared fabric of interstate data exchange. This document specifies the Driver Record Exchange API, the association-operated platform through which state jurisdictions participate in interstate pointer, commercial driver, and title networks under common message standards, a common testing and certification discipline, and common governance.

The platform enforces the one-driver-one-record principle through a pointer system: exactly one jurisdiction holds the master record for any driver at any moment, and every other jurisdiction locates that record through the network rather than maintaining a shadow copy. It governs the full membership lifecycle of jurisdictions — application, activation, suspension, withdrawal — together with the connection testing and certification that a jurisdiction's systems must pass before traffic flows. On top of that substrate sit the operational workflows registrars run every day: claiming and transferring driver records, posting convictions against commercial posting deadlines, disqualifying drivers, issuing licenses against federal verification services, re-titling vehicles without washing brands, and settling the annual dues that fund the association. An independent audit function, deliberately segregated from both operations and administration, closes the loop on judicial disqualifications and fiscal assessments.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, protocols, and invariants that apply to every endpoint of the API.

### 2.1. User and Role-Based Access Control

Every request is authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying a malformed value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. Once the headers are accepted, the declared role is checked against the endpoint's authorized role set; a role outside that set is rejected with `ERR_INSUFFICIENT_PERMISSIONS`. A header value is malformed only when it is missing, empty, or blank; a well-formed but unrecognized role string — one outside the five roles — is still an accepted header and then fails role authorization on every endpoint, including reads, with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

The platform recognizes five roles. `AssociationAdmin` is association staff, responsible for the membership lifecycle, certification grants, fee issuance, and stewardship of the logical clock. `JurisdictionRegistrar` is a member jurisdiction's DMV operator, performing that jurisdiction's day-to-day record, licensing, titling, and fee work. `CertificationEngineer` runs the connection test suites used during onboarding and, by segregation of duties, may never grant certification — the grant belongs exclusively to an `AssociationAdmin`. `FederalVerifier` operates the social-security-number and lawful-status verification services consulted at license issuance. `AuditAuthority` is an independent auditor who records judicial disqualifications and performs dues audits and, by segregation of duties, may never issue invoices. Read endpoints are open to all five roles.

The identity carried in `X-User-ID` is interpreted per role. When `X-User-Role` is `JurisdictionRegistrar`, `X-User-ID` is the `id` of the acting `Jurisdiction`; ownership checks on any resource that references a `Jurisdiction` compare the resource's jurisdiction foreign key to `X-User-ID`, and a mismatch is rejected with `ERR_JURISDICTION_OWNERSHIP_MISMATCH`. When `X-User-Role` is `AssociationAdmin`, `CertificationEngineer`, `FederalVerifier`, or `AuditAuthority`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items from the front of the result set and defaults to 0. A `limit` or `offset` that is not an integer, a `limit` below 1 or above 100, or a negative `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Unless otherwise specified, every list endpoint returns its resources ordered by `created_at` ascending — a stable, deterministic order; resources created at the same logical instant share a `created_at`, and such ties are broken by insertion order.

The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and Derived State

The platform runs on a logical clock, not wall-clock time. At startup, before any explicit adjustment, the clock reads exactly `2026-09-01T00:00:00Z`, and it must never silently fall back to the host's wall clock. Every deadline, window, and time-derived status in the system — the commercial conviction posting deadline, certification test windows, the points windows, the disqualification lifecycle — reads this clock. An `AssociationAdmin` steers it through an admin-only capability that sets the current instant to a supplied `to_iso8601` value.

The clock's most visible consumer is the disqualification: a disqualification's `status` is not stored but derived at read time — `OVERTURNED` when its `overturned_at` is set, otherwise `COMPLETED` when the current date is strictly after its `end_date`, otherwise `ACTIVE`. Advancing the clock therefore re-evaluates derived statuses lazily on the next read, with no background job mutating records.

### 2.5. Common Resource Properties

Every primary resource carries a standard set of system-managed fields:

- `id` — a server-minted UUID, with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, recording when the resource was created.
- `updated_at` — an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` — a system-managed integer that starts at 1 at creation and increments with every mutation of the resource.

The `Conviction` is the deliberate exception. Convictions are immutable once posted — never edited, never removed — so a conviction carries only `id` and `created_at`; both `updated_at` and `version` are absent from it.

Mutations performed by the server itself count the same as client-driven ones. When a membership transition is applied to a jurisdiction, the jurisdiction's `version` increments by one and its `updated_at` refreshes; when a record claim or a transfer initiation succeeds, the driver identity's `version` increments by one — the very mechanism the staleness checks of §2.7 rely upon.

### 2.6. The Validation Ladder

Every mutating request passes through the same ordered gauntlet of checks, and the order is part of the contract: when several checks could reject the same request, the first failing rung on this ladder determines which error surfaces. The rungs, in order, are:

1. **Header presence.** `X-User-ID` and `X-User-Role` must be present and well-formed, else `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400).
2. **Role authorization.** The declared role must be among the endpoint's authorized roles, else `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).
3. **Registrar ownership.** When a `JurisdictionRegistrar` acts on a jurisdiction-scoped resource, `X-User-ID` must equal the `id` of the jurisdiction that owns — or will own — the resource: the record-holding jurisdiction for conviction posting; the issuing jurisdiction for license reinstatement; the invoiced jurisdiction for invoice dispute and settlement; the `from_jurisdiction_id` for recording a surrender; the `to_jurisdiction_id` for initiating, contesting, or completing a license transfer or completing a title transfer; and the registrar's own jurisdiction for enrolling in a system, claiming a record, issuing a license, titling a vehicle, or requesting a re-titling. A mismatch is `ERR_JURISDICTION_OWNERSHIP_MISMATCH` (HTTP 403). Where the comparison needs no stored resource — a body-carried jurisdiction id, as at enrollment — it is evaluated before existence; where ownership must be read off a stored resource, that resource's existence is established first, and a missing resource surfaces its not-found error even when the caller would also fail ownership.
4. **Existence.** Path identifiers and body foreign keys must reference existing resources, validated left to right; the first missing reference yields the corresponding not-found error — `ERR_JURISDICTION_NOT_FOUND`, `ERR_PARTICIPATION_NOT_FOUND`, `ERR_CERTIFICATION_NOT_FOUND`, `ERR_DRIVER_NOT_FOUND`, `ERR_RECORD_NOT_FOUND`, `ERR_LICENSE_NOT_FOUND`, `ERR_TRANSFER_NOT_FOUND`, `ERR_DISQUALIFICATION_NOT_FOUND`, `ERR_TITLE_NOT_FOUND`, `ERR_TITLE_TRANSFER_NOT_FOUND`, or `ERR_INVOICE_NOT_FOUND` (each HTTP 404).
5. **Staleness.** Where an endpoint requires `expected_driver_version` (see §2.7), the value must equal the driver identity's current `version`, else `ERR_STALE_VERSION` (HTTP 412).
6. **State-machine arcs.** The target resource must be in a state from which the requested transition is declared. This rung carries a pinned sub-order: a jurisdiction-activity failure surfaces first as `ERR_JURISDICTION_NOT_ACTIVE`, then a participation-certification failure as `ERR_PARTICIPATION_NOT_CERTIFIED`, and only then the resource-level arc failures — `ERR_INVALID_STATE`, `ERR_RECORD_NOT_ACTIVE`, `ERR_LICENSE_NOT_ACTIVE`, and `ERR_GRANT_REQUIRES_PASSED_CERTIFICATION` (all HTTP 409).
7. **Credentialing and brand safety.** Commercial credentialing and brand-washing gates: `ERR_ACTIVE_DISQUALIFICATION` and `ERR_BRAND_DISCLOSURE_MISMATCH` (HTTP 409).
8. **Uniqueness and exclusivity.** One-driver-one-record, record location, one in-flight transfer per driver, one `ACTIVE` title per VIN, unique participation pairs, unique jurisdiction codes: `ERR_RECORD_ALREADY_HELD`, `ERR_RECORD_HELD_BY_OTHER_JURISDICTION`, `ERR_TRANSFER_ALREADY_IN_FLIGHT`, `ERR_VIN_ALREADY_TITLED`, `ERR_PARTICIPATION_ALREADY_EXISTS`, and `ERR_JURISDICTION_CODE_TAKEN` (HTTP 409).
9. **Temporal windows.** Certification window shape (`ERR_INVALID_WINDOW`, HTTP 400), certification window overlap (`ERR_CERT_WINDOW_OVERLAP`, HTTP 409), completion inside the window (`ERR_OUTSIDE_TEST_WINDOW`, HTTP 422), and disqualification interval overlap (`ERR_DISQUALIFICATION_OVERLAP`, HTTP 409).
10. **Cross-aggregate referential integrity.** `ERR_SAME_JURISDICTION_TRANSFER` (HTTP 422) and, at license issuance when the driver has no `ACTIVE` record held by the caller's jurisdiction, `ERR_RECORD_NOT_FOUND` (HTTP 404).
11. **Fiscal integrity.** Settlement amounts must match the assessed amount to the cent, else `ERR_FEE_AMOUNT_MISMATCH` (HTTP 402).

Independent of the ladder, field-shape failures — a missing required field, an unknown enum member, a malformed date or datetime, or a value outside its declared shape such as demerit `points` beyond the one-to-six range or a quarterly volume array of the wrong length — are rejected with `ERR_INVALID_REQUEST` (HTTP 400) wherever they occur.

### 2.7. Optimistic Concurrency Control on the Driver Identity

Two write operations guard against acting on a stale view of a driver, and both key on the `DriverIdentity` version. A `POST /driver-exchange/driver-records` request must carry `expected_driver_version` equal to the driver identity's current `version`, and a `POST /driver-exchange/license-transfers` request must carry the same field under the same rule. If the driver identity's version has advanced since the client last read it — because another jurisdiction's record claim, or an earlier transfer initiation, legitimately became the driver's latest state — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from building on a driver state it has not observed. Clients obtain the current version from the driver retrieval endpoint before attempting either write.

On success, each of these two operations increments the driver identity's `version` by exactly one, so every claim and every transfer initiation invalidates previously observed versions. The `expected_driver_version` field is non-optional on these two endpoints and appears on no others; requests to any other endpoint carry no version field at all.

### 2.8. Cascades and Interstate Consistency

Suspending a jurisdiction is never a local edit. When an `AssociationAdmin` moves a jurisdiction from `ACTIVE` to `SUSPENDED`, two cascade links fire in sequence. Link one: every system participation of that jurisdiction currently `CERTIFIED` transitions to `SUSPENDED`, its `suspended_at` timestamp is set, and the jurisdiction's `certified_systems_count` is recomputed. Link two, caused by link one: every license transfer whose `to_jurisdiction_id` is the suspended jurisdiction and whose status is `INITIATED` or `CONTESTED` transitions to `CANCELLED`, because the `POINTER_NETWORK` participation those transfers relied upon is no longer certified. Re-activation runs the recovery in reverse: when the jurisdiction returns from `SUSPENDED` to `ACTIVE`, every participation of that jurisdiction sitting in `SUSPENDED` that has at least one `PASSED` connection certification transitions back to `CERTIFIED`, its `granted_at` refreshed and the certified count recomputed once more.

A second, independent cascade hangs off conviction posting. Posting a conviction recomputes the record's point totals; the disqualification evaluation may then create or extend a disqualification; and a created disqualification — automatic or judicial alike — suspends every `ACTIVE` license of class `COMMERCIAL` riding on that record, while `STANDARD` licenses are untouched. In all of these cascades the server performs the transitions itself, with no client request against the participation, transfer, or license, and each mutated resource's `updated_at` and `version` follow the common rules of §2.5.

### 2.9. Dates, Windows, and Interval Semantics

Two interval disciplines coexist in the platform, and confusing them is an interoperability bug. Certification test windows are half-open: the lower bound `window_start` is inclusive, the upper bound `window_end` is exclusive, so a completion attempted at exactly `window_start` is inside the window while one attempted at exactly `window_end` is outside it. Two scheduled windows of the same participation may touch — a new window starting exactly where an existing one ends is legal adjacency — but any positive intersection is rejected. Disqualification intervals, by contrast, are closed: both `start_date` and `end_date` are inclusive days, so two intervals that share even a single boundary day collide.

Calendar fields are ISO 8601 dates in `YYYY-MM-DD` form — `date_of_birth`, `offense_date`, `conviction_date`, `start_date`, `end_date` — while instants such as `window_start`, `granted_at`, and `posted_at` are full ISO 8601 UTC timestamps. Malformed values are rejected as `ERR_INVALID_REQUEST`. Durations surface as day counts: the points window spans 1,095 days — three years — and the commercial conviction posting deadline is 30 days, inclusive.

### 2.10. Cents, Basis Points, and Rounding

All money in the platform is integer cents; no fractional cent is ever stored. Where a charge is computed from rates that can land on a fraction of a cent, the result is rounded half up to whole cents — and the rounding point differs deliberately between the two dues calculations of §3.8: the provisional assessment rounds exactly once, after the annual cap is applied, while the audited settlement rounds each quarter's charge before summing the four quarters. Timeliness is integer-graded as well: `timeliness_score_bp` is a basis-point value between 0 and 10,000, rounded half up, where 10,000 represents a perfectly timely jurisdiction.

## 3. Business Logic & Workflows

### 3.1. Joining the Association: Membership from Application to Withdrawal

A jurisdiction enters the exchange when an `AssociationAdmin` registers it with a two-letter `code`, an official `name`, and the association-assigned dues weighting tier `fee_tier` — one of `TIER_1`, `TIER_2`, or `TIER_3`. The code must be unique across all jurisdictions; a collision is rejected with `ERR_JURISDICTION_CODE_TAKEN`. A freshly registered jurisdiction starts with `membership_status` `APPLIED`, a `certified_systems_count` of zero, and a `timeliness_score_bp` of 10,000 — the empty-set value for a member with no commercial convictions yet.

Activation is earned, not declared. An administrator moves a jurisdiction from `APPLIED` to `ACTIVE` by patching its `status`, and the transition is gated: at least one of the jurisdiction's system participations must already hold `CERTIFIED` status in the `POINTER_NETWORK`, otherwise the attempt fails with `ERR_PARTICIPATION_NOT_CERTIFIED`. From `ACTIVE`, two roads lead out. Suspension moves the jurisdiction to `SUSPENDED` and fires the two-link cascade described in §2.8 — certified participations drop, and in-flight incoming transfers cancel. Withdrawal, reachable from either `ACTIVE` or `SUSPENDED`, moves the jurisdiction to the terminal `WITHDRAWN`; a withdrawn jurisdiction's resources remain readable for the historical record. Re-activation from `SUSPENDED` back to `ACTIVE` restores suspended participations per the same cascade section. Every membership transition applied through this patching operation increments the jurisdiction's `version` by one.

### 3.2. Enrolling in a Network: Testing and Certification of Connections

A `JurisdictionRegistrar` enrolls its own jurisdiction in an interstate system by supplying `jurisdiction_id` and `system`, where the system is one of `POINTER_NETWORK`, `COMMERCIAL_DRIVER_NETWORK`, or `TITLE_NETWORK`. The `jurisdiction_id` must be the registrar's own jurisdiction — a mismatch is `ERR_JURISDICTION_OWNERSHIP_MISMATCH` — and the jurisdiction must be `APPLIED` or `ACTIVE`; enrollment attempted while `SUSPENDED` or `WITHDRAWN` is rejected with `ERR_INVALID_STATE`. One jurisdiction holds at most one participation per system: a duplicate pairing is rejected with `ERR_PARTICIPATION_ALREADY_EXISTS`. A new participation starts in `ENROLLING`.

Certification is a test-window discipline run by a `CertificationEngineer`. Scheduling a certification takes a `participation_id`, a `window_start`, and a `window_end`; the window end must lie strictly after the window start, else `ERR_INVALID_WINDOW`. Among a participation's `SCHEDULED` certifications, the half-open windows of §2.9 must not intersect — adjacency is allowed, and any positive overlap is rejected with `ERR_CERT_WINDOW_OVERLAP`. The certification is created `SCHEDULED`, and the very first scheduling against a participation moves that participation from `ENROLLING` to `TESTING`. While a certification remains `SCHEDULED`, its `score` and `completed_at` stay null.

Completing a certification is only valid while the logical clock sits inside the window; an attempt outside it — before `window_start`, or at or after `window_end` — is rejected with `ERR_OUTSIDE_TEST_WINDOW`. The engineer supplies a `result` of `PASSED` or `FAILED` and may include a conformance `score` between 0 and 100; the server records the outcome, the score, and the `completed_at` timestamp, and the certification reaches its terminal state, `SCHEDULED` → `PASSED` or `SCHEDULED` → `FAILED` as reported.

Granting certification is deliberately separated from running the test: the engineer who ran the suite cannot grant, and only an `AssociationAdmin` grants. The grant succeeds only when the participation's most recent completed certification — the one with the maximum `window_start` among those `PASSED` or `FAILED`, ties broken by latest `created_at` (and any remaining tie, at an identical `created_at`, broken in favor of the certification scheduled last) — is a `PASSED` one, else `ERR_GRANT_REQUIRES_PASSED_CERTIFICATION`; and the parent jurisdiction must not be `WITHDRAWN`, else `ERR_JURISDICTION_NOT_ACTIVE`. A successful grant moves the participation `TESTING` → `CERTIFIED`, stamps `granted_at` (which remains null until this first grant, just as `suspended_at` remains null until a first suspension), and recomputes the jurisdiction's `certified_systems_count`. Thereafter the participation's fate tracks its parent's: suspension of the jurisdiction drops it `CERTIFIED` → `SUSPENDED`, and re-activation restores it `SUSPENDED` → `CERTIFIED` provided at least one `PASSED` certification exists, the certified count recomputed at each swing. The full set of certifications is listable, optionally filtered by `participation_id`.

### 3.3. The Driver Identity and the One-Driver-One-Record Pointer

Driver identities are shared across the whole exchange. A `JurisdictionRegistrar` registers one with a `full_name`, a `date_of_birth`, an `ssn_last4_hash` — the salted hash of the social security number's last four digits against which the verification services later match — and a `lawful_status_basis` of `US_CITIZEN`, `PERMANENT_RESIDENT`, or `TEMPORARY_STATUS`. Registration presumes the registrar's own jurisdiction already exists on the platform; otherwise the call fails with `ERR_JURISDICTION_NOT_FOUND`.

The pointer discipline begins with the record claim. A registrar claims the master driver record for a driver into its own jurisdiction by supplying the `driver_id` together with `expected_driver_version` — the optimistic-concurrency guard of §2.7, rejected with `ERR_STALE_VERSION` when the driver's version has moved on since the client's read. The claiming jurisdiction must be `ACTIVE` and hold a `CERTIFIED` `POINTER_NETWORK` participation, failures surfacing per the ladder's pinned sub-order as `ERR_JURISDICTION_NOT_ACTIVE` or `ERR_PARTICIPATION_NOT_CERTIFIED`. And the one-driver-one-record invariant is absolute: if the driver already has an `ACTIVE` record in any jurisdiction, the claim is rejected with `ERR_RECORD_ALREADY_HELD`. A successful claim creates the record `ACTIVE`, binds `holding_jurisdiction_id` to the caller's jurisdiction, zeroes both `points_total` and `abstract_points_total`, and advances the driver identity's `version`.

Records are inspectable singly or as lists filtered by `driver_id`, by `holding_jurisdiction_id`, or by both, and each record exposes its conviction history and its disqualification history as nested listings. Because clients need the current version before either guarded write, the driver retrieval endpoint is the canonical place to read the driver identity's `version`. A record's own lifecycle has exactly one arc: when an interstate transfer completes, the master record moves — the old record goes `ACTIVE` → `TRANSFERRED_OUT` and a replacement record springs up in the receiving jurisdiction, `ACTIVE` with both point totals at zero, so the count of `ACTIVE` records for the driver remains exactly one. A `TRANSFERRED_OUT` record is a read-only artifact of history.

### 3.4. Posting Convictions: Points, Timeliness, and Disqualification

Convictions flow into the record held by the posting jurisdiction. A registrar posts one by supplying the `record_id`, the `offense_date`, the `conviction_date`, a `severity` of `NON_CMV`, `CMV_SERIOUS`, or `CMV_MAJOR`, and demerit `points` as an integer from 1 to 6 — a value outside that range is `ERR_INVALID_REQUEST`. The target record must be `ACTIVE`: a posting aimed at a `TRANSFERRED_OUT` record is rejected with `ERR_RECORD_NOT_ACTIVE`, because retired records are immutable. The caller must be a registrar of the record's holding jurisdiction, and that jurisdiction must be `ACTIVE` with a `CERTIFIED` `COMMERCIAL_DRIVER_NETWORK` participation.

The server stamps `posted_at` from the logical clock and computes `is_late`: a conviction is late when the number of days from its `conviction_date` to the posted date exceeds 30, and the deadline is inclusive — exactly 30 days is timely, while 31 days is late. Late postings are accepted, not rejected; the tardiness is flagged on the conviction and priced into the posting jurisdiction's timeliness score, which is recomputed at every posting. The eligible set for that score is the convictions on records the jurisdiction holds whose `severity` is `CMV_SERIOUS` or `CMV_MAJOR` — a record counts as held by its `holding_jurisdiction_id` whatever the record's own status, so the conviction history of a record that later transferred out continues to count toward that jurisdiction's score; `timeliness_score_bp` is ten thousand times the timely share of that set, rounded half up to an integer, and a full 10,000 while the set is empty.

Every posting also recomputes the record's two point totals, stored on the record at posting time. The operational total `points_total` sums the `points` of every conviction on the record whose `offense_date` falls within the trailing 1,095-day window — three years — ending on the logical clock's current date, both boundary days included, so a conviction exactly 1,095 days old still counts. The abstract total `abstract_points_total` is the identical sum keyed on `conviction_date` instead of `offense_date`; the two diverge whenever a conviction's offense and conviction dates straddle the window boundary differently. Because convictions are immutable and never removed, both sums always run over the record's full history, and both totals are plain integers with no rounding.

Then the disqualification evaluation fires, in a pinned order. First, the new point total is taken — the offense-window figure already including the just-posted conviction, because the points determine the tier and the new conviction is itself part of the points. Second, the trigger test: a just-posted conviction whose `severity` is `CMV_MAJOR` warrants a disqualification with a base duration of 365 days and `basis` `AUTO_MAJOR`; failing that, a new point total of at least 12 warrants one with a base of 90 days and `basis` `AUTO_POINTS`; otherwise nothing is created. Third, the priors are counted — the existing disqualifications on the record whose derived status is `ACTIVE` or `COMPLETED`, with overturned ones excluded from the count. Fourth, the duration is the base multiplied by one plus the prior count, the multiplier capped at three: a first disqualification runs the base duration, a second runs double, and a third or later runs triple, never more. Fifth, the window is set — `start_date` is the logical clock's current date, and `end_date` is the start date plus the duration in days, a closed interval in the sense of §2.9. Sixth, the overlap policy: if any existing derived-`ACTIVE` disqualification on the record has a closed interval intersecting the new one, no new entity is created; instead exactly one merge target — the intersecting disqualification with the earliest `start_date`, ties broken by earliest `created_at` — has its `end_date` extended to the later of its current end date and the newly computed end date. The extension is a single step with no iteration; the merge target's `basis` and `start_date` are unchanged, and every other derived-active disqualification is left untouched.

A created disqualification fires cascade link three: every `ACTIVE` license of `license_class` `COMMERCIAL` riding on the record is suspended, while `STANDARD` licenses are not. Courts also act directly: an `AuditAuthority` records a judicial disqualification by supplying the `record_id`, an explicit `start_date`, and an explicit `end_date`, giving it `basis` `MANUAL_JUDICIAL`, and the same commercial-license suspension cascade follows. Manual intervals must not overlap an existing derived-`ACTIVE` disqualification on the same record — under closed-interval semantics even a shared boundary day collides, and the attempt is rejected with `ERR_DISQUALIFICATION_OVERLAP`. An automatic disqualification, by contrast, always resolves through the merge path above rather than ever being rejected for overlap.

A disqualification's `status`, per §2.4, is derived at read time: `OVERTURNED` once overturned, else `COMPLETED` once the current date has passed its `end_date`, else `ACTIVE`. The only direct mutation is the overturn, performed by an `AuditAuthority` and valid only while the derived status is `ACTIVE` — overturning anything else is `ERR_INVALID_STATE` — which stamps `overturned_at` and flips the derived reading to `OVERTURNED`.

### 3.5. Issuing a License: Verification and Reinstatement

License issuance starts from the pointer. A registrar issues a license by supplying a `driver_id` and a `license_class` of `STANDARD` or `COMMERCIAL`. The driver must have an `ACTIVE` record held by the caller's own jurisdiction: when no such record exists the request fails with `ERR_RECORD_NOT_FOUND`, and when the driver's `ACTIVE` record is held by a different jurisdiction the request fails with `ERR_RECORD_HELD_BY_OTHER_JURISDICTION` — the remedy is the transfer protocol of §3.6, not a second issuance. The issuing jurisdiction must be `ACTIVE` with a `CERTIFIED` `POINTER_NETWORK` participation, and for the `COMMERCIAL` class a further safety gate applies: no disqualification on the backing record may have derived status `ACTIVE`, else `ERR_ACTIVE_DISQUALIFICATION`.

A new license is created in `PENDING_VERIFICATION` with its `record_id` bound to that backing record, its `issuing_jurisdiction_id` set to the caller's jurisdiction, and both verification dimensions — `ssn_check_status` and `lawful_status_check_status` — reading `PENDING`. The two dimensions resolve in parallel through the federal verification services: a `FederalVerifier` posts outcomes with a `check_type` selecting the `SSN` or `LAWFUL_STATUS` dimension and a `result` carrying the outcome, setting that dimension to `VERIFIED` or `FAILED`. When the second of the two dimensions lands `VERIFIED` — both now verified — the system moves the license `PENDING_VERIFICATION` → `ACTIVE`; the moment any dimension lands `FAILED`, the license goes `PENDING_VERIFICATION` → `DENIED`, a terminal state. Posting against a license that has left `PENDING_VERIFICATION`, or re-posting a dimension already decided, is rejected with `ERR_INVALID_STATE`.

Suspension arrives from the conviction side via cascade link three — a created disqualification drops an `ACTIVE` commercial license to `SUSPENDED`. Reinstatement is the registrar's lever back: a registrar of the license's `issuing_jurisdiction_id` reinstates a `SUSPENDED` license to `ACTIVE`, but only once no disqualification on the backing record has derived status `ACTIVE`; a live disqualification blocks the reinstatement with `ERR_ACTIVE_DISQUALIFICATION`, and a registrar of any other jurisdiction is turned away with `ERR_JURISDICTION_OWNERSHIP_MISMATCH`. Licenses are listable filtered by `driver_id`, by `issuing_jurisdiction_id`, or by `record_id`.

### 3.6. Moving Across State Lines: The License Transfer Protocol

When a driver relocates, the receiving jurisdiction initiates a license transfer by supplying the `driver_id`, the `prior_license_id` of the license to be surrendered, and `expected_driver_version` — the second guarded write of §2.7, rejected with `ERR_STALE_VERSION` when the client's view of the driver is stale. The prior license must be `ACTIVE` — a non-active one yields `ERR_LICENSE_NOT_ACTIVE` — and must belong to the driver's `ACTIVE` record chain; a prior license whose `driver_id` differs from the request's `driver_id` is rejected with `ERR_INVALID_REQUEST` (HTTP 400). The transfer's `from_jurisdiction_id` is derived from the prior license's issuing jurisdiction, and its `to_jurisdiction_id` is the initiating registrar's own jurisdiction, which must be `ACTIVE` with a `CERTIFIED` `POINTER_NETWORK` participation. One transfer per driver may be in flight at a time: if the driver already has a transfer in `INITIATED`, `SURRENDER_RECORDED`, or `CONTESTED`, initiation is rejected with `ERR_TRANSFER_ALREADY_IN_FLIGHT`. A fresh transfer starts `INITIATED` with `new_license_id` still null, and a successful initiation advances the driver identity's `version` by one.

Surrender is recorded by the sending side. A registrar of the `from_jurisdiction_id` records surrender of the prior license, moving the transfer `INITIATED` → `SURRENDER_RECORDED`; the prior license itself goes `ACTIVE` → `SURRENDERED`, and any `contest_reason` is cleared to null. The same action also closes a contest loop: from `CONTESTED`, a re-surrender returns the transfer to `SURRENDER_RECORDED` with identical effects.

Contest is the receiving side's objection. A registrar of the `to_jurisdiction_id` contests a recorded surrender with a `reason`, moving the transfer `SURRENDER_RECORDED` → `CONTESTED`; the reason is recorded as `contest_reason`, and — as compensation while the dispute runs — the prior license walks back `SURRENDERED` → `ACTIVE`.

Completion finalizes the move, again by a registrar of the `to_jurisdiction_id`. Three preconditions guard it: the prior license must be `SURRENDERED`, else `ERR_INVALID_STATE`; no disqualification on the driver's `ACTIVE` record may have derived status `ACTIVE`, else `ERR_ACTIVE_DISQUALIFICATION`; and the receiving jurisdiction must be `ACTIVE` with a `CERTIFIED` `POINTER_NETWORK` participation, else `ERR_PARTICIPATION_NOT_CERTIFIED`. The completion cascade then fires in full: the prior driver record goes `ACTIVE` → `TRANSFERRED_OUT`; a new driver record is created for the same driver with `holding_jurisdiction_id` set to the receiving jurisdiction, status `ACTIVE`, and both `points_total` and `abstract_points_total` at zero; a new license is created in `PENDING_VERIFICATION` with `issuing_jurisdiction_id` set to the receiving jurisdiction, its `record_id` pointing at the new record, its `license_class` copied from the prior license, and both check statuses `PENDING`; and the transfer's `new_license_id` is set to the new license as the transfer reaches its terminal `COMPLETED` state. The one-driver-one-record invariant holds across the move — exactly one `ACTIVE` record per driver before, during, and after.

Two further arcs end a transfer without completion. While the transfer is `INITIATED` or `CONTESTED`, suspension of the receiving jurisdiction — cascade link two of §2.8 — moves it to `CANCELLED`; on the `CONTESTED` path the prior license remains `ACTIVE`, because the contest compensation already restored it. Transfers are listable filtered by any of `driver_id`, `from_jurisdiction_id`, `to_jurisdiction_id`, `prior_license_id`, or `new_license_id`.

### 3.7. Titling Vehicles and Defeating Brand Washing

A registrar titles a vehicle in its own jurisdiction by supplying a seventeen-character `vin` and, optionally, a `brands` set drawn from `SALVAGE`, `FLOOD`, `REBUILT`, and `JUNK`, defaulting to empty when omitted. The titling jurisdiction must be `ACTIVE` with a `CERTIFIED` `TITLE_NETWORK` participation. At most one `ACTIVE` title exists per VIN across the exchange: a duplicate is rejected with `ERR_VIN_ALREADY_TITLED`. The title is created `ACTIVE` with `holding_jurisdiction_id` set to the caller's jurisdiction and `washing_alert` false.

Re-titling across state lines runs through a title transfer. A registrar of the receiving jurisdiction requests one with the source `vehicle_title_id` and the applicant's `disclosed_brands`. The receiving jurisdiction must differ from the source title's holding jurisdiction — a same-jurisdiction request is `ERR_SAME_JURISDICTION_TRANSFER` — and the brand-washing check runs synchronously at request time. If the disclosed set is not a superset of the source title's brands — that is, any brand on the source title is missing from the disclosure — the request is rejected with `ERR_BRAND_DISCLOSURE_MISMATCH`, the source title's `washing_alert` is set to true as a permanent marker (once set, it is never cleared), and no transfer is persisted. Otherwise the `carried_brands` are computed as the union of the source brands and the disclosed brands, sorted alphabetically for determinism, and the transfer is created in `VERIFIED` status. The empty boundary passes cleanly: when the source brands and the disclosure are both empty, verification succeeds and the carried set is empty.

Completion is performed by a registrar of the transfer's `to_jurisdiction_id` and requires the source title still `ACTIVE`, else `ERR_INVALID_STATE`. On completion the source title goes `ACTIVE` → `EXPORTED`; a new title springs up in the receiving jurisdiction carrying the same VIN, `brands` equal to the `carried_brands`, status `ACTIVE`, and a fresh `washing_alert` of false; and the transfer's `new_title_id` — null until now — is set as the transfer moves `VERIFIED` → `COMPLETED`, its terminal state. Title transfers are listable filtered by `vehicle_title_id` or by `to_jurisdiction_id`, and a jurisdiction's held titles are listable as a nested collection.

### 3.8. Association Dues: Assessment, Dispute, Settlement, and Audit

Each fiscal year the association assesses dues on its members. An `AssociationAdmin` issues an invoice with the `jurisdiction_id`, the `fiscal_year` (an integer), and the declared `projected_volume` — the jurisdiction's projected annual interchange transaction volume, a non-negative integer; anything else is `ERR_INVALID_REQUEST`. The invoiced jurisdiction must be `ACTIVE`, else `ERR_JURISDICTION_NOT_ACTIVE`. At issuance the server pins `certified_count_at_issue` to the jurisdiction's current `certified_systems_count` and computes the `provisional_amount_cents`; the invoice is created `ISSUED`, with `dispute_reason`, `settled_amount_cents`, `actual_volume_quarters`, and the final audit figures all still null.

The provisional assessment follows a pinned order, and the base fee is never multiplied — the volume discount applies to the transaction fee only. The certified count `n` is the pinned snapshot. The multiplier starts at one and drops by five hundredths for each certified system beyond the first — one certified system multiplies by exactly 1, two by 0.95, three by 0.90 — but never falls below the floor of 0.85, which binds from four systems onward; at zero certified systems — reachable only at audit time, when the jurisdiction may have been suspended since settlement — no discount applies and the multiplier is 1.05. The marginal transaction fee prices the declared volume in three brackets: the first ten thousand transactions at 12.5 cents each, the next forty thousand — from the ten-thousand-and-first through the fifty-thousandth — at 10.5 cents each, and every transaction beyond the fifty-thousandth at 8.5 cents each, with any bracket the volume does not reach contributing nothing. The provisional amount is then the 2,500,000-cent base fee plus the transaction fee scaled by the multiplier, capped at 20,000,000 cents, and rounded half up to whole cents exactly once, after the cap.

A registrar of the invoiced jurisdiction may dispute an `ISSUED` invoice with a `reason`; the invoice moves `ISSUED` → `DISPUTED` and the reason is recorded as `dispute_reason`. The association's answer is a reissue: an administrator supplies a corrected `projected_volume`, the provisional amount is recomputed — still with the multiplier built from the original pinned `certified_count_at_issue`, even if the live certified count has moved since first issuance — the `dispute_reason` is cleared to null, and the invoice returns `DISPUTED` → `ISSUED`. This dispute loop may repeat.

Settlement is exact-change only. A registrar of the invoiced jurisdiction settles with an `amount_cents` that must equal the `provisional_amount_cents` to the cent; any other figure is rejected with `ERR_FEE_AMOUNT_MISMATCH`. A successful settlement records the `settled_amount_cents` and moves the invoice `ISSUED` → `SETTLED`.

The audit closes the books. An `AuditAuthority` finalizes a `SETTLED` invoice by supplying `actual_volume_quarters` — exactly four non-negative integer volumes in quarter order, first quarter through fourth, anything else rejected as `ERR_INVALID_REQUEST` — moving the invoice `SETTLED` → `AUDITED`, its terminal state. The final assessment changes shape deliberately: for each quarter in turn, the charge is one quarter of the 2,500,000-cent base fee plus the same three-bracket marginal fee priced on that quarter's volume and scaled by the multiplier — but with `n` taken as the jurisdiction's current `certified_systems_count` at audit time rather than the pinned snapshot — and each quarter's charge is rounded half up to whole cents before the four rounded quarters are summed into `final_amount_cents`. Summing first and rounding once would be a different, incorrect result whenever a quarter's raw charge lands on a fractional cent, and because the multiplier uses the live count rather than the pinned one, identical annual totals can settle to a different amount than the provisional figure. The `adjustment_amount_cents` is the final amount minus the settled amount: positive means an underpayment still due from the jurisdiction, negative means a credit owed back to it. A jurisdiction's invoices are listable as a nested collection.

## 4. Endpoint Definitions

All endpoints are mounted under the `/driver-exchange` prefix. Operations that create a new resource return `201 Created`; operations that modify an existing resource or drive a state transition return `200 OK`, as do all reads. The table below summarizes the HTTP contract only — request payloads, response shapes, preconditions, and side effects are defined by the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/driver-exchange/_clock/set_current_utc` | Set the logical clock | AssociationAdmin |
| POST | `/driver-exchange/jurisdictions` | Register a member jurisdiction | AssociationAdmin |
| GET | `/driver-exchange/jurisdictions/{id}` | Get a jurisdiction | Any authenticated role |
| PATCH | `/driver-exchange/jurisdictions/{id}` | Transition membership status | AssociationAdmin |
| GET | `/driver-exchange/jurisdictions/{id}/system-participations` | List a jurisdiction's system participations | Any authenticated role |
| GET | `/driver-exchange/jurisdictions/{id}/fee-invoices` | List a jurisdiction's fee invoices | Any authenticated role |
| GET | `/driver-exchange/jurisdictions/{id}/vehicle-titles` | List titles held by a jurisdiction | Any authenticated role |
| POST | `/driver-exchange/system-participations` | Enroll the caller's jurisdiction in a system | JurisdictionRegistrar |
| POST | `/driver-exchange/system-participations/{id}/grant-certification` | Grant CERTIFIED status to a participation | AssociationAdmin |
| POST | `/driver-exchange/connection-certifications` | Schedule a certification test window | CertificationEngineer |
| GET | `/driver-exchange/connection-certifications/{id}` | Get a certification | Any authenticated role |
| GET | `/driver-exchange/connection-certifications` | List certifications, optionally by participation | Any authenticated role |
| POST | `/driver-exchange/connection-certifications/{id}/complete` | Record a certification result | CertificationEngineer |
| POST | `/driver-exchange/drivers` | Register a driver identity | JurisdictionRegistrar |
| GET | `/driver-exchange/drivers/{id}` | Get a driver (read its version before guarded writes) | Any authenticated role |
| POST | `/driver-exchange/driver-records` | Claim the master driver record into the caller's jurisdiction | JurisdictionRegistrar |
| GET | `/driver-exchange/driver-records/{id}` | Get a driver record | Any authenticated role |
| GET | `/driver-exchange/driver-records` | List driver records, filterable by driver or holding jurisdiction | Any authenticated role |
| GET | `/driver-exchange/driver-records/{id}/convictions` | List a record's convictions | Any authenticated role |
| GET | `/driver-exchange/driver-records/{id}/disqualifications` | List a record's disqualifications | Any authenticated role |
| POST | `/driver-exchange/convictions` | Post a conviction to a held record | JurisdictionRegistrar |
| POST | `/driver-exchange/disqualifications` | Record a judicial disqualification | AuditAuthority |
| POST | `/driver-exchange/disqualifications/{id}/overturn` | Overturn a disqualification | AuditAuthority |
| POST | `/driver-exchange/licenses` | Issue a license | JurisdictionRegistrar |
| GET | `/driver-exchange/licenses/{id}` | Get a license | Any authenticated role |
| GET | `/driver-exchange/licenses` | List licenses, filterable by driver, issuer, or record | Any authenticated role |
| POST | `/driver-exchange/licenses/{id}/verification-results` | Post an SSN or lawful-status verification outcome | FederalVerifier |
| POST | `/driver-exchange/licenses/{id}/reinstate` | Reinstate a suspended license | JurisdictionRegistrar |
| POST | `/driver-exchange/license-transfers` | Initiate a license transfer into the caller's jurisdiction | JurisdictionRegistrar |
| GET | `/driver-exchange/license-transfers/{id}` | Get a license transfer | Any authenticated role |
| GET | `/driver-exchange/license-transfers` | List license transfers, filterable by any transfer foreign key | Any authenticated role |
| POST | `/driver-exchange/license-transfers/{id}/record-surrender` | Record surrender of the prior license | JurisdictionRegistrar |
| POST | `/driver-exchange/license-transfers/{id}/contest` | Contest a recorded surrender | JurisdictionRegistrar |
| POST | `/driver-exchange/license-transfers/{id}/complete` | Complete the transfer | JurisdictionRegistrar |
| POST | `/driver-exchange/vehicle-titles` | Title a vehicle in the caller's jurisdiction | JurisdictionRegistrar |
| POST | `/driver-exchange/title-transfers` | Request an interstate re-titling | JurisdictionRegistrar |
| GET | `/driver-exchange/title-transfers/{id}` | Get a title transfer | Any authenticated role |
| GET | `/driver-exchange/title-transfers` | List title transfers, filterable by source title or receiving jurisdiction | Any authenticated role |
| POST | `/driver-exchange/title-transfers/{id}/complete` | Complete the re-titling | JurisdictionRegistrar |
| POST | `/driver-exchange/fee-invoices` | Issue an annual dues invoice | AssociationAdmin |
| POST | `/driver-exchange/fee-invoices/{id}/dispute` | Dispute an invoice | JurisdictionRegistrar |
| POST | `/driver-exchange/fee-invoices/{id}/reissue` | Reissue a disputed invoice with corrected volume | AssociationAdmin |
| POST | `/driver-exchange/fee-invoices/{id}/settle` | Settle an invoice | JurisdictionRegistrar |
| POST | `/driver-exchange/fee-invoices/{id}/finalize-audit` | Finalize the dues audit | AuditAuthority |

## 5. Error Code Catalogue

The table below enumerates every error identifier and its HTTP status code. The conditions that trigger each error are defined in the narratives of §2 and §3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_JURISDICTION_OWNERSHIP_MISMATCH` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_JURISDICTION_NOT_FOUND` | 404 Not Found |
| `ERR_PARTICIPATION_NOT_FOUND` | 404 Not Found |
| `ERR_CERTIFICATION_NOT_FOUND` | 404 Not Found |
| `ERR_DRIVER_NOT_FOUND` | 404 Not Found |
| `ERR_RECORD_NOT_FOUND` | 404 Not Found |
| `ERR_LICENSE_NOT_FOUND` | 404 Not Found |
| `ERR_TRANSFER_NOT_FOUND` | 404 Not Found |
| `ERR_DISQUALIFICATION_NOT_FOUND` | 404 Not Found |
| `ERR_TITLE_NOT_FOUND` | 404 Not Found |
| `ERR_TITLE_TRANSFER_NOT_FOUND` | 404 Not Found |
| `ERR_INVOICE_NOT_FOUND` | 404 Not Found |
| `ERR_JURISDICTION_NOT_ACTIVE` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_PARTICIPATION_NOT_CERTIFIED` | 409 Conflict |
| `ERR_RECORD_NOT_ACTIVE` | 409 Conflict |
| `ERR_LICENSE_NOT_ACTIVE` | 409 Conflict |
| `ERR_GRANT_REQUIRES_PASSED_CERTIFICATION` | 409 Conflict |
| `ERR_ACTIVE_DISQUALIFICATION` | 409 Conflict |
| `ERR_BRAND_DISCLOSURE_MISMATCH` | 409 Conflict |
| `ERR_RECORD_ALREADY_HELD` | 409 Conflict |
| `ERR_RECORD_HELD_BY_OTHER_JURISDICTION` | 409 Conflict |
| `ERR_TRANSFER_ALREADY_IN_FLIGHT` | 409 Conflict |
| `ERR_VIN_ALREADY_TITLED` | 409 Conflict |
| `ERR_PARTICIPATION_ALREADY_EXISTS` | 409 Conflict |
| `ERR_JURISDICTION_CODE_TAKEN` | 409 Conflict |
| `ERR_INVALID_WINDOW` | 400 Bad Request |
| `ERR_CERT_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_OUTSIDE_TEST_WINDOW` | 422 Unprocessable Entity |
| `ERR_DISQUALIFICATION_OVERLAP` | 409 Conflict |
| `ERR_SAME_JURISDICTION_TRANSFER` | 422 Unprocessable Entity |
| `ERR_FEE_AMOUNT_MISMATCH` | 402 Payment Required |
