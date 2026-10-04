# FMC Detention & Demurrage Complaint Adjudication API — Product Requirements Document

## 1. Introduction

Ocean carriers and marine terminal operators recover the cost of idle containers and congested terminals through detention and demurrage charges, and the Federal Maritime Commission polices how those charges are published, billed, disputed, and — when billing practices break down — punished. This document specifies the Commission's oversight API: a single platform on which regulated organizations file tariffs and service contracts, issue detention and demurrage invoices against them, and answer billing disputes; on which shippers escalate grievances from an informal ombuds process to formal adjudication backed by reparations authority; and on which the Commission itself reviews carrier agreements for competitive effects, licenses freight intermediaries against surety bonds, brings enforcement proceedings, and collects weekly port performance data.

Two commitments shape every workflow that follows. Billing must be checkable: each invoice carries the data elements a billed party needs to verify the charge, each charge derives deterministically from a published tariff or an effective service contract, and each dispute runs against a fixed response clock. Enforcement must be consequential: violation determinations and late dispute responses feed a per-carrier compliance score that, once it deteriorates past a fixed threshold, automatically suspends the carrier and cascades through its published tariffs, outstanding invoices, and pending disputes. A server-side logical clock governs every filing window, notice period, and deadline, so that statutory timing is evaluated deterministically rather than against wall-clock time.

## 2. Global Specifications & System-Wide Principles

This section fixes the platform-wide contracts — authentication, response envelopes, pagination, timekeeping, resource identity, money, validation ordering, concurrency control, and the automatic enforcement cascades — that every endpoint in §4 obeys.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. The platform recognizes exactly eight roles: `CommissionAdmin`, `CommissionDocket`, `ComplianceReviewer`, `OmbudsOfficer`, `AdministrativeLawJudge`, `EnforcementCounsel`, `CarrierRep`, and `ShipperRep`. A request missing either header, or whose `X-User-Role` names no declared role, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is not authorized for the target endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

The eight roles divide into two identity families. `CarrierRep` and `ShipperRep` are entity-backed: when `X-User-Role` is `CarrierRep`, `X-User-ID` is the `id` of the acting `CarrierOrganization`, and ownership checks on any resource that references a carrier compare the resource's carrier foreign-key field to `X-User-ID`; when `X-User-Role` is `ShipperRep`, `X-User-ID` is the `id` of the acting `ShipperAccount`, and ownership checks on any resource that references a shipper compare the resource's shipper foreign-key field to `X-User-ID`. The remaining six roles — `CommissionAdmin`, `CommissionDocket`, `ComplianceReviewer`, `OmbudsOfficer`, `AdministrativeLawJudge`, and `EnforcementCounsel` — carry opaque identities: `X-User-ID` is an operator identifier not tied to any persisted entity. The server may record it (for example, as `ombuds_officer_id` on a complaint, as `presiding_judge_id`, or as `opened_by_counsel_id` where a workflow assigns responsibility) but never compares it to any entity's `id`.

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

List endpoints paginate through two query parameters. `limit` caps the number of items returned: it defaults to 10 when omitted, accepts a minimum of 1, and accepts a maximum of 100. `offset` skips a number of items before the page begins and defaults to 0. Unless otherwise specified, every list endpoint returns its resources sorted by `created_at` in ascending order. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. The Logical Clock

Every timestamp the business rules consult — filing instants, issuance instants, decision instants, deadlines — is read from a server-side logical clock, never from wall-clock time. Before any operator intervention the clock reads `2026-09-01T00:00:00Z`, and the server must not fall back to wall-clock time under any circumstance. A `CommissionAdmin` alone may move time through a platform-level test-driving capability whose request carries a `to_iso8601` instant and whose response reports the resulting `current_utc`; that capability is mounted outside the `/fmc` business surface and is the only way the logical clock advances.

### 2.5. Common Resource Properties

Every primary resource carries a standard set of system-managed fields:

- `id` (string): a server-minted unique identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp rendered with three fractional digits, fixed at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp rendered with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): starts at creation and increments by one on every mutation, including mutations driven by the automatic cascades of §2.10.

One resource family is exempt: the weekly port congestion report is an append-only data-collection record and carries only `id` and `created_at` — both `updated_at` and `version` are absent from it.

### 2.6. Monetary Values, Integer Cents, and Rounding Discipline

All money on the platform moves in integer cents. Fields whose names end in `_cents` — rates, charges, settlements, awards, penalties, bond coverages — are whole numbers of cents with no fractional part, and every monetary calculation is exact integer arithmetic. Where a calculation requires rounding, the method is always round half up, and each calculation pins both the precision and the order in which rounded values combine: market-share percentages are rounded to four decimal places before being squared, squared contributions are rounded to two decimal places before being summed, and the summed concentration index is rounded to two decimal places; per-invoice reparation components are rounded to whole cents before being summed into an award. Occupancy ratios used in congestion scoring are compared as exact rational values against their decimal thresholds, without any rounding of the ratio itself.

### 2.7. Validation Discipline: Ordering and First Failure Wins

Every request walks an ordered ladder of checks, and evaluation stops at the first failure: the response carries that failure's error identifier and no later check is consulted. The ladder runs in this order:

1. Header presence and role validity (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. Role authorization for the endpoint (`ERR_INSUFFICIENT_PERMISSIONS`).
3. Ownership and identity — entity-backed callers acting only on their own organization or account, and assigned-officer checks where a workflow names a responsible individual; failures carry `ERR_FORBIDDEN_RESOURCE_ACCESS`. Ownership is a property of an existing resource, so a path identifier that does not resolve produces the not-found failure of rung 4 before any ownership comparison is made.
4. Path identifier existence, validated left to right (the per-family 404 errors of §2.8).
5. Existence of entities referenced in the request body (the same per-family 404 errors).
6. Request shape and scalar sanity — required fields present, enumerations valid, dates coherent, numerics in range (`ERR_INVALID_REQUEST`, `ERR_INVOICE_MISSING_REQUIRED_ELEMENT`, `ERR_INVALID_INVOICE_DATES`).
7. The carrier's operational standing for operational filings (`ERR_CARRIER_NOT_ACTIVE`).
8. From-state preconditions of the target resource; within this rung the checks run in a fixed order — tariff state first, then contract state, then license state, then the invoice, dispute, complaint, agreement, and proceeding from-state checks.
9. Temporal windows — notice periods, filing deadlines, response windows, waiting periods (the HTTP 422 window errors).
10. Cross-reference consistency between the request and existing resources (the HTTP 422 consistency errors).
11. Uniqueness and overlap constraints (the HTTP 409 constraint errors).
12. The complaint subject-set non-emptiness rule (`ERR_EMPTY_SUBJECT_SET`).
13. Bond ledger sufficiency for draws and reversals (the HTTP 402 errors).
14. Segregation of duties between ombuds service and adjudication (`ERR_ADJUDICATOR_CONFLICT`).
15. The competitive-concern gate on agreements going effective (`ERR_COMPETITIVE_CONCERN_UNRESOLVED`).
16. The optimistic-concurrency version assertion (`ERR_STALE_VERSION`), which is deliberately last: the version encodes the caller's view after all other input was assembled.

### 2.8. Nested Resource Retrieval

Several creation and listing endpoints nest a child collection beneath a parent path, and transitions act on resources identified by path segments. The server validates path identifiers strictly left to right — the carrier first, then the tariff, license, invoice, dispute, complaint, proceeding, or agreement beneath it — and rejects the request with the not-found error for the first identifier that fails to resolve, without consulting later segments. Each resource family has its own not-found identifier, all HTTP 404: `ERR_CARRIER_NOT_FOUND`, `ERR_SHIPPER_NOT_FOUND`, `ERR_TARIFF_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_LICENSE_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`, and `ERR_PROCEEDING_NOT_FOUND`. The same per-family errors report body references that fail to resolve — a `shipper_id`, a `tariff_id`, a `service_contract_id`, a `billed_party_shipper_id`, a `respondent_carrier_id`, an element of `subject_invoice_ids`, or an element of `member_carrier_ids` that names nothing. In URL templates the path variables are spelled `carrierId`, `shipperId`, `tariffId`, `contractId`, `agreementId`, `licenseId`, `invoiceId`, `disputeId`, `complaintId`, and `proceedingId`; a few nested collection routes abbreviate the parent segment to `id`, always referring to the parent resource named by that segment of the route.

### 2.9. Optimistic Concurrency Control

Two write operations guard against stale reads with an explicit version assertion, and no other endpoint accepts a version field. Filing a tariff publication against a carrier requires the request to carry `expected_carrier_version`, the caller's last observed `version` of that carrier; when another write — a sibling filing, or an enforcement-driven suspension — has advanced the carrier's version since the caller last read it, the filing is rejected with `ERR_STALE_VERSION` (HTTP 412), and the filer must re-observe the carrier before filing. Posting a draw or reversal against an OTI license requires `expected_license_version`, the caller's last observed `version` of that license; a prior draw, reversal, or bond append legitimately advances the license's version and changes remaining coverage, so a stale assertion is likewise rejected with `ERR_STALE_VERSION` (HTTP 412), and the caller must re-observe the ledger before posting. Both guarded writes increment the parent resource's `version` by one on success, and on both the version assertion is evaluated after every other request check has passed.

### 2.10. Compliance Standing and Automatic Enforcement Cascades

Every carrier organization carries a `compliance_score` that starts at 1000, is lowered by violation determinations and by late dispute responses, and never falls below zero. The score is the carrier's regulatory standing: the moment a deduction leaves it below 600, the carrier's `status` becomes `SUSPENDED` automatically — no operator action is required — and suspension is a terminal condition within the platform. A suspended carrier is barred from the operational filings: it cannot issue invoices, file service contracts, or publish tariffs.

Suspension triggers a cascade that settles the carrier's book of business in one deterministic chain. The violation determination adds its penalty into the carrier's `cumulative_civil_penalties_cents` and applies its `score_delta` to the `compliance_score`; the carrier then transitions from `ACTIVE` to `SUSPENDED`; every tariff publication of that carrier standing in `PUBLISHED` moves to `SUSPENDED`; every invoice of that carrier in `ISSUED` or `DISPUTED` status whose `charge_basis` is `TARIFF` and whose governing tariff has just been suspended moves to `VOIDED`; and every dispute still `PENDING` on a just-voided invoice is resolved as `UPHELD_WAIVED` with `resolved_amount_cents` set to zero and its `response_was_late` flag left untouched.

A second cascade runs through the bonding chain. When a draw leaves a license's total available coverage below its requirement, the license moves from `ACTIVE` to `SUSPENDED`, and every `EFFECTIVE` service contract of the carrier moves to `SUSPENDED` with it; when a reversal or a newly appended bond restores coverage up to the requirement, the license returns to `ACTIVE` and the suspended contracts return to `EFFECTIVE`. Each mutation in either cascade refreshes `updated_at` and increments `version` on the resource it touches.

## 3. Business Logic & Workflows

This section walks the platform's business processes from registration through enforcement. Structural details of every endpoint — methods, paths, and authorized roles — are collected in §4; the narratives below are the source of truth for what each operation does, what it requires, and what it changes.

### 3.1. Registering Regulated Organizations and Shipper Accounts

A `CommissionAdmin` onboards the regulated community. Registering an organization requires an `org_name` and an `org_type` — one of `VOCC` (vessel-operating common carrier), `MTO` (marine terminal operator), `NVOCC` (non-vessel-operating common carrier), or `OFF` (ocean freight forwarder) — and the `org_type` is immutable once the organization exists. A new organization begins in `ACTIVE` status with a `compliance_score` of 1000 and `cumulative_civil_penalties_cents` of zero; the penalties figure is a running total, summing `penalty_cents` across every enforcement proceeding against the carrier that has reached a `DETERMINED` outcome.

Registering a shipper requires a `company_name` and a `contact_email`. The account's `total_recovery_cents` ledger starts at zero and accumulates what the shipper actually recovers through the platform: informal ombuds settlements add to it, reparation awards add to it, and an appeal reversal claws an award back out of it. Both registration operations return the created resource, and reading either resource back is open to every role.

### 3.2. Tariff Filings: Notice Periods and Publication

A `CarrierRep` files a tariff publication against its own organization — the filing records the carrier named in the creation path as the tariff's `carrier_id` — supplying a filer-assigned `tariff_code`, a `charge_scope` of `DETENTION`, `DEMURRAGE`, or `GENERAL`, the `free_time_days` a billed party enjoys before per-diem accrual starts (zero or more), the `per_diem_rate_cents` charged per day after free time (a positive figure), an `accrual_method` of `CALENDAR` or `WORKING_DAY` that selects the invoice charge variant of §3.5, a `change_type` of `NEW`, `INCREASE`, or `DECREASE`, and a requested `effective_date`. The filing is stamped `filed_at` from the logical clock and begins life with `publication_status` in `DRAFT`.

Statutory notice scales with the direction of the change. An `INCREASE` requires thirty days of notice; a `NEW` or `DECREASE` filing requires one day. The server derives `notice_period_days` from the `change_type` accordingly and rejects a filing whose `effective_date` falls earlier than `filed_at` plus the applicable notice period with `ERR_EFFECTIVE_DATE_NOTICE_SHORT` (HTTP 422).

Filing is an optimistic-concurrency write on the carrier: the request must carry `expected_carrier_version` per §2.9, and a successful filing advances the carrier's `version` by one.

A draft becomes operative only through publication, performed by a `CarrierRep` of the owning carrier. Publication requires three conditions, evaluated in the ladder order of §2.7 — carrier standing before tariff state before the temporal window: the carrier must be `ACTIVE`, otherwise `ERR_CARRIER_NOT_ACTIVE` (HTTP 409); the tariff must stand in `DRAFT`, otherwise `ERR_TARIFF_NOT_IN_DRAFT` (HTTP 409); and the logical clock must have reached the tariff's `effective_date`, otherwise `ERR_PUBLISH_WINDOW_NOT_REACHED` (HTTP 422). A successful publication moves `publication_status` to `PUBLISHED`, where the tariff remains unless the enforcement cascade of §2.10 suspends it. A carrier's catalogue of tariff publications is listable by every role.

### 3.3. Service Contracts: Essential Terms and Timely Filing

Where a tariff is a public instrument, a service contract is a negotiated one between one carrier and one shipper. A `CarrierRep` files one against its own organization, supplying a `contract_reference`, the contracting shipper's `shipper_id`, the `agreed_at` instant at which the parties executed the contract, and the essential terms: `duration_months` (at least one), `minimum_quantity_commitment` in TEU (at least one), `negotiated_free_time_days` (zero or more), `negotiated_per_diem_rate_cents` (positive), and a `negotiated_accrual_method` of `CALENDAR` or `WORKING_DAY`. The filing carrier must be `ACTIVE`, and a carrier of type `NVOCC` or `OFF` must additionally hold an `ACTIVE` OTI license — a filing without one is rejected with `ERR_LICENSE_NOT_ACTIVE` (HTTP 409).

Filing is timely only within thirty days of execution: a filing whose `filed_at` falls later than thirty days after `agreed_at` is rejected with `ERR_LATE_SERVICE_CONTRACT_FILING` (HTTP 422). A contract accepted for filing has its `contract_status` born `EFFECTIVE`; it leaves that status only through the bonding cascade of §2.10, which suspends it while the carrier's license is under-covered and restores it when coverage returns. Contracts are listable by every role, and the listing accepts `carrier_id` and `shipper_id` filters.

### 3.4. OTI Licensing and the Surety Bond Ledger

Non-vessel-operating common carriers and ocean freight forwarders must be licensed before they may bill under contracts or issue invoices. A `CarrierRep` applies for a license under its own organization — recorded on the license as `organization_id` — by naming a `license_type` of `NVOCC` or `OFF`; the type must equal the organization's `org_type`, and a mismatch — or an application from an organization whose type is not licensable at all — is rejected with `ERR_LICENSE_TYPE_MISMATCH` (HTTP 422). The license's `required_bond_cents` is fixed by type: 7,500,000 cents for an `NVOCC`, 5,000,000 cents for an `OFF`. A new license begins with `license_status` in `PENDING_BOND`, an empty `surety_bonds` ledger, and `total_available_coverage_cents` of zero.

Coverage is built bond by bond. A `CarrierRep` appends a surety bond by supplying a filer-chosen `bond_ref`, a `surety_name`, and a `coverage_cents` figure; the reference must be unique within the license, and a duplicate is rejected with `ERR_DUPLICATE_BOND_REF` (HTTP 409). Each embedded bond also carries three computed figures: `drawn_cents`, starting at zero; `available_cents`, always equal to `coverage_cents` minus `drawn_cents`; and `bond_status`, which reads `EXHAUSTED` exactly when the bond is fully drawn and `ACTIVE` otherwise. The license's `total_available_coverage_cents` is the sum of availability across all of its bonds, and the per-bond invariant that `available_cents` plus `drawn_cents` equals `coverage_cents` holds after every draw and every reversal.

An `EnforcementCounsel` posts ledger movements against a bond: the request names the `bond_ref`, a signed `amount_cents`, and a free-text `reason`. A positive amount draws down coverage and may not exceed the bond's `available_cents`; a larger draw is rejected with `ERR_BOND_COVERAGE_EXCEEDED` (HTTP 402). A negative amount reverses a prior draw, and its magnitude may not exceed the bond's `drawn_cents`; a larger reversal is rejected with `ERR_BOND_REVERSAL_EXCEEDED` (HTTP 402). Posting is an optimistic-concurrency write on the license per §2.9 and must carry `expected_license_version`; every successful bond append, draw, or reversal advances the license's `version` by one.

After every mutation of the ledger the license re-evaluates coverage sufficiency in a fixed order: if total available coverage has reached `required_bond_cents` and the license is not `ACTIVE`, it becomes `ACTIVE`; otherwise, if total available coverage has fallen below `required_bond_cents` while the license is `ACTIVE`, it becomes `SUSPENDED`. The transitions carry the contract cascade of §2.10 with them. A license that leaves `ACTIVE` suspends the carrier's `EFFECTIVE` service contracts. A license that reaches `ACTIVE` for the first time restores those of the carrier's suspended contracts that were suspended by this license's own coverage loss. A license that returns to `ACTIVE` from `SUSPENDED` restores the carrier's suspended contracts to `EFFECTIVE`. A carrier's licenses, with their embedded bonds and coverage totals, are listable by every role.

### 3.5. Issuing Detention and Demurrage Invoices

A `CarrierRep` issues an invoice against its own organization — the carrier named in the creation path is recorded as the invoice's `carrier_id` — and the invoice must carry every data element a billed party needs to verify the charge: an `invoice_number`; a `charge_basis` declaring whether a public `TARIFF` or a negotiated `SERVICE_CONTRACT` governs; the `billed_party_shipper_id` of the party being billed; the `container_number`; the `port_code` of discharge or loading; and three dates — `availability_date`, when the container became available, `return_date`, when it was returned or picked up, and `last_accrual_date`, the last day on which charges accrued. An invoice missing any required element — including the basis-conditional reference, `tariff_id` when the basis is `TARIFF` or `service_contract_id` when it is `SERVICE_CONTRACT` — is rejected with `ERR_INVOICE_MISSING_REQUIRED_ELEMENT` (HTTP 400). The three dates must be coherent — availability no later than return, return no later than the last accrual date, and the last accrual date no later than the issuance instant — or the invoice is rejected with `ERR_INVALID_INVOICE_DATES` (HTTP 400). Two optional incentive-principle factors, `government_hold_days` and `appointment_unavailable_days`, count days of the accrual window lost to government holds and to unavailable gate appointments; each defaults to zero and may not be negative.

The governing document polices the issuance. Under a `TARIFF` basis the named tariff must stand in `PUBLISHED` — otherwise `ERR_TARIFF_NOT_PUBLISHED` (HTTP 409) — and must belong to the invoicing carrier, otherwise `ERR_TARIFF_CARRIER_MISMATCH` (HTTP 422). Under a `SERVICE_CONTRACT` basis the named contract must stand in `EFFECTIVE` — otherwise `ERR_CONTRACT_NOT_EFFECTIVE` (HTTP 409) — and must belong to the invoicing carrier with the billed party as its contracting shipper; a contract owned by another carrier, or one whose `shipper_id` differs from the `billed_party_shipper_id`, is rejected with `ERR_BILLED_PARTY_NOT_CONTRACT_PARTY` (HTTP 422). The invoicing carrier itself must be `ACTIVE` (otherwise `ERR_CARRIER_NOT_ACTIVE`), and an `NVOCC` or `OFF` carrier must hold an `ACTIVE` OTI license (otherwise `ERR_LICENSE_NOT_ACTIVE`). Timing is policed as well: an invoice may issue no later than thirty days after its `last_accrual_date`, and a later issuance is rejected with `ERR_LATE_INVOICE_ISSUANCE` (HTTP 422).

The charge itself is computed at issuance and is never client-supplied. The server copies `free_time_days`, `per_diem_rate_cents`, and `accrual_method` from the governing document onto the invoice — the tariff's values under a `TARIFF` basis, the contract's negotiated values under a `SERVICE_CONTRACT` basis — and ignores any values the client sent for these three fields. The free-time end is the instant exactly `free_time_days` days after `availability_date`. When `return_date` falls at or before the free-time end, `billable_days` is zero and the charge is zero. Otherwise the accrual window runs from the free-time end, exclusive, through `return_date`, inclusive, and the copied `accrual_method` selects the day count. Under `CALENDAR`, every started day bills: the elapsed seconds from the free-time end to `return_date` are divided by 86,400 — the number of seconds in a day — and the result is rounded up to a whole day, so any partial day bills as a full day while an exact whole-day span bills exactly. Under `WORKING_DAY`, the server enumerates the calendar dates strictly after the calendar date of the free-time end up to and including the calendar date of `return_date` and counts only those falling on a Monday, Tuesday, Wednesday, Thursday, or Friday; the time of day of `return_date` never adds a day, and identical inputs yield a count no larger than the calendar variant's. The invoice's `amount_cents` is then `billable_days` multiplied by `per_diem_rate_cents`, an exact integer-cent figure. The invoice is stamped `issued_at` from the logical clock and its `invoice_status` enters `ISSUED`.

Invoices are listable by every role; the listing accepts `carrier_id`, `billed_party_shipper_id`, `tariff_id`, and `service_contract_id` filters, which may be combined to narrow the result set.

### 3.6. Billing Disputes and the Thirty-Day Response Window

The billed party may contest an invoice while it stands in `ISSUED` status. A `ShipperRep` whose account is the invoice's billed party opens a billing dispute naming a `dispute_reason` — one of `LATE_ISSUANCE`, `INCORRECT_PARTY`, `MISSING_ELEMENTS`, `CHARGE_EXCEEDS_PUBLISHED`, or `OTHER` — and the invoice must stand in `ISSUED`, otherwise the filing is rejected with `ERR_INVOICE_NOT_DISPUTABLE` (HTTP 409). The dispute's `invoice_id` binds it to the invoice named in the creation path. Opening the dispute moves the invoice from `ISSUED` to `DISPUTED`, stamps the dispute's `filed_at` from the logical clock, and sets `response_due_at` thirty days after filing; the dispute begins with `resolution` in `PENDING`, no `responded_at`, no `requested_resolution`, `response_was_late` false, and `resolved_amount_cents` unset.

The carrier's answer is due on or before `response_due_at`. A `CarrierRep` of the invoicing carrier responds to a `PENDING` dispute — a response to an already-resolved dispute is rejected with `ERR_DISPUTE_NOT_PENDING` (HTTP 409) — by naming a `resolution` of `WAIVE`, `REDUCE`, or `DENY`. Every response records `responded_at` from the logical clock and stores the requested outcome in `requested_resolution`. Timeliness is judged at the response instant: a response recorded on or before the deadline is timely; a response recorded at any instant after it is late.

A timely `WAIVE` resolves the dispute as `UPHELD_WAIVED`: `resolved_amount_cents` becomes zero and the invoice is `VOIDED`. A timely `REDUCE` must carry a `reduced_amount_cents` that is present and strictly lower than the invoice's current `amount_cents` — an absent or insufficiently low figure is rejected with `ERR_REDUCED_AMOUNT_NOT_LOWER` (HTTP 400), while a negative figure fails the scalar-sanity rung of §2.7 as `ERR_INVALID_REQUEST` — and resolves the dispute as `UPHELD_REDUCED`: the reduced figure becomes both the dispute's `resolved_amount_cents` and the invoice's new `amount_cents`, replacing the charge outright without recomputing the day count, and the invoice returns to `ISSUED`. A timely `DENY` must carry a `denial_justification` — without one the response is rejected with `ERR_JUSTIFICATION_REQUIRED` (HTTP 400) — and resolves the dispute as `DENIED`: `resolved_amount_cents` takes the invoice's full `amount_cents` and the invoice returns to `ISSUED`.

A late response loses the right to choose. Regardless of the requested resolution, a response recorded after `response_due_at` forces the dispute to `UPHELD_WAIVED`: `response_was_late` is set true, `resolved_amount_cents` becomes zero, the invoice is `VOIDED`, and the carrier's `compliance_score` drops by 25 points for the late response. The forced waiver is also how the enforcement cascade of §2.10 resolves disputes whose invoices are voided out from under them — with the difference that the cascade leaves `response_was_late` untouched, since no response ever occurred.

Separately, the billed party may simply pay: a `ShipperRep` whose account is the billed party marks an `ISSUED` invoice paid, moving it to the terminal `PAID` status; an invoice in any other state is rejected with `ERR_INVOICE_NOT_PAYABLE` (HTTP 409). A paid invoice can no longer be disputed, and a disputed invoice can no longer be paid until its dispute resolves. The disputes on an invoice are listable by every role.

### 3.7. Shipper Complaints: Intake, Ombuds, Adjudication, and Appeal

When dispute-level remedies fall short, a `ShipperRep` escalates to a formal complaint against a carrier. The filing names the `respondent_carrier_id`, a non-empty `subject_invoice_ids` array — an empty set is rejected with `ERR_EMPTY_SUBJECT_SET` (HTTP 422) — and the `reparations_claimed_cents` sought, a positive figure that caps any eventual award. The complaining shipper's identity comes from the caller and is recorded as the complaint's `shipper_id`. Every subject invoice must exist, must bill the complaining shipper — otherwise `ERR_NOT_INVOICE_PARTY` (HTTP 422) — must have been issued by the respondent carrier — otherwise `ERR_RESPONDENT_NOT_INVOICE_CARRIER` (HTTP 422) — and must stand in `ISSUED`, `DISPUTED`, or `PAID` status; a `VOIDED` invoice leaves nothing to adjudicate and is rejected with `ERR_INVOICE_NOT_ACTIONABLE` (HTTP 409). The complaint itself must be filed no later than 180 days after the most recently issued of its subject invoices; a later filing is rejected with `ERR_COMPLAINT_FILING_WINDOW_EXPIRED` (HTTP 422). A docketed complaint begins with `complaint_status` in `DOCKETED` and `ombuds_rounds` at zero. Until the lifecycle reaches them, `ombuds_officer_id`, `informal_settlement_cents`, `presiding_judge_id`, `reparation_method`, `decided_at`, and `appeal_deadline` are unset, and `reparations_awarded_cents` stands at zero.

At intake the server computes the complaint's `incentive_principle_score`, an integer between 0 and 100 that is frozen for the life of the complaint and never recomputed. The score starts at 100, and each subject invoice, taken in the order listed in `subject_invoice_ids`, erodes it. Days the container spent under government hold cost 15 points per day, counted up to a maximum of three days per invoice — a `government_hold_days` figure beyond the third does not erode the score further. Days on which no gate appointment was available cost 10 points per day, again capped at three days per invoice through `appointment_unavailable_days`. Port congestion then applies once per invoice: the server gathers every weekly port congestion report whose `port_code` equals the invoice's `port_code` and whose reported week intersects the invoice's accrual footprint — concretely, reports whose `week_start` falls on or before the invoice's `last_accrual_date` while the seven-day week beginning at `week_start` extends past the invoice's `availability_date`. For each distinct `week_start` among the matched reports, the port's occupancy ratio for that week is the sum of `berth_occupancy_hours` across all matched reports sharing that week start, divided by 672 — the port-wide weekly berth-hour capacity. The largest such ratio, or zero when no report matches, decides the congestion deduction: a ratio reaching or exceeding 0.85 costs 25 points; otherwise a ratio reaching or exceeding 0.70 costs 10 points; below that, nothing. The score never falls below zero.

Complaints are listable by every role; the listing accepts `shipper_id` and `respondent_carrier_id` filters, and its `subject_invoice_ids` parameter carries a single invoice identifier and matches the complaints whose subject array contains it.

Informal resolution comes first. A `CommissionDocket` clerk refers a `DOCKETED` complaint to the ombuds process by naming an `ombuds_officer_id`; referral from any other status is rejected with `ERR_COMPLAINT_NOT_DOCKETED` (HTTP 409), and referral is permitted only while `ombuds_rounds` stands below two — a referral after two completed failed rounds is rejected with `ERR_OMBUDS_ROUND_LIMIT_EXCEEDED` (HTTP 409). Referral moves the complaint to `OMBUDS` and records the assigned officer on the complaint.

Only the assigned officer may close the round: the caller's `X-User-ID` must equal the complaint's current `ombuds_officer_id`, otherwise the request is rejected with `ERR_FORBIDDEN_RESOURCE_ACCESS` (HTTP 403). Closing with `outcome` `SETTLED` requires a `settlement_amount_cents` figure — absent, the request fails with `ERR_INVALID_REQUEST` (HTTP 400) — and resolves the complaint as `RESOLVED_INFORMAL`: the figure is recorded as `informal_settlement_cents` and added to the shipper's `total_recovery_cents`. Closing with `outcome` `FAILED` returns the complaint to `DOCKETED` and increments `ombuds_rounds` by one, consuming one of the two rounds the process allows.

Formal adjudication is opened by an `AdministrativeLawJudge` on a `DOCKETED` complaint — any other status again yields `ERR_COMPLAINT_NOT_DOCKETED` — subject to one segregation-of-duties bar: the judge who opens adjudication must not be the officer who ran the complaint's most recent ombuds round, and a conflicting caller is rejected with `ERR_ADJUDICATOR_CONFLICT` (HTTP 403). Opening records the caller as `presiding_judge_id` and moves the complaint to `ADJUDICATION_OPEN`.

The decision belongs to the presiding judge alone — a different caller is rejected with `ERR_FORBIDDEN_RESOURCE_ACCESS` — and only while the complaint stands in `ADJUDICATION_OPEN`, otherwise `ERR_COMPLAINT_NOT_ADJUDICATING` (HTTP 409). The decision carries no request payload: the frozen `incentive_principle_score` selects the reparation method first, before any amount is computed, and the method then computes the award from the subject invoices as they stand at decision time. A score below 50 selects `FLUIDITY_WEIGHTED` — the charges presumptively failed to promote freight fluidity — while a score of 50 or higher selects `OUT_OF_POCKET`. Under `OUT_OF_POCKET`, only subject invoices currently in `PAID` status contribute: each paid invoice contributes its current `amount_cents` plus interest of five percent of that amount, the interest rounded half up to a whole cent, while an invoice in any other status contributes nothing. Under `FLUIDITY_WEIGHTED`, every subject invoice contributes whether paid or not, each at 125 percent of its current `amount_cents`, the contribution rounded half up to a whole cent; identical invoice data therefore yields a different award than the out-of-pocket variant. The per-invoice components — each already rounded — are summed, and the award is the lesser of that sum and the complaint's `reparations_claimed_cents`. The chosen method is recorded as `reparation_method`, the award as `reparations_awarded_cents`; `decided_at` is stamped from the logical clock, the `appeal_deadline` falls thirty days after the decision, and the shipper's `total_recovery_cents` grows by the award. The complaint moves to `ADJUDICATION_DECIDED`.

Either party may appeal — the complainant shipper or the respondent carrier, and anyone else is rejected with `ERR_FORBIDDEN_RESOURCE_ACCESS` — while the complaint stands in `ADJUDICATION_DECIDED`, otherwise `ERR_APPEAL_NOT_ALLOWED` (HTTP 409), and while the logical clock remains on or before the `appeal_deadline`, otherwise `ERR_APPEAL_WINDOW_EXPIRED` (HTTP 422). A timely appeal moves the complaint to `APPEALED`. A `CommissionAdmin` then resolves the appeal with a `decision` of `AFFIRM` or `REVERSE` — a complaint not standing in `APPEALED` is rejected with `ERR_APPEAL_NOT_ALLOWED`. Affirmation lands the complaint in its terminal `FINAL` status with the award intact. Reversal lands it in `REVERSED`: the awarded amount is subtracted back out of the shipper's `total_recovery_cents`, and `reparations_awarded_cents` is reset to zero.

### 3.8. Carrier Agreements and Competitive Monitoring

Cooperative agreements among vessel-operating carriers are filed for competitive review before they may operate. A `CarrierRep` files an agreement with an `agreement_number`, an `agreement_type` of `VESSEL_SHARING`, `RATE_DISCUSSION`, `EQUIPMENT_POOLING`, or `SPACE_CHARTER`, and the `member_carrier_ids` of the parties. Membership is policed at filing: there must be at least two distinct members, every member must be a vessel-operating common carrier in `ACTIVE` standing, and the filing carrier's own organization must appear among the members — a failing membership is rejected with `ERR_INVALID_AGREEMENT_MEMBERSHIP` (HTTP 422). The filing records `filed_by_carrier_id` from the caller's identity and stamps `filed_at` from the logical clock; the `waiting_period_ends_at` is set forty-five days after filing; and the agreement's `review_status` enters `AWAITING_REVIEW` with an empty `monitoring_reports` array, a null `market_concentration_hhi`, and `competitive_concern_flag` false.

While an agreement awaits review, and after it goes effective, the members file competitive monitoring reports against it. Each report supplies a `reporting_period_start`, a `reporting_period_end`, a `total_market_teus` figure for the whole market, and `member_volumes` — one entry per member carrying that member's `carrier_id` and `carried_teus`. Reporting periods are half-open: a period includes its start and excludes its end, a new period must not overlap any existing report's period on the same agreement — though touching boundaries, where one period's end equals another's start, are allowed — and an intersecting submission is rejected with `ERR_MONITORING_PERIOD_OVERLAP` (HTTP 409). The `member_volumes` must cover exactly the member set: every entry's `carrier_id` must be a member of the agreement, and every member must be covered — a mismatch is rejected with `ERR_MEMBER_SET_MISMATCH` (HTTP 422).

Each accepted report carries a computed concentration index, its `hhi`. For each member entry, the member's market-share percentage is computed as `carried_teus` divided by `total_market_teus`, multiplied by 100, and rounded half up to four decimal places; each share is then squared and the square rounded half up to two decimal places to form that member's contribution; the report's `hhi` is the sum of the member contributions, itself rounded half up to two decimal places. This nested rounding order — share to four decimals, square to two, sum, then a final two-decimal rounding — is pinned: summing unrounded squares yields a different figure and is non-conformant. The agreement's `market_concentration_hhi` tracks the `hhi` of the report with the latest `reporting_period_end` among all reports on the agreement — not necessarily the most recently appended one — and stays null until the first report arrives. The `competitive_concern_flag` is true exactly when that concentration figure reaches or exceeds 2500.

An agreement goes effective only by a `ComplianceReviewer`'s declaration, and three conditions gate it: the agreement's `review_status` must stand in `AWAITING_REVIEW`, otherwise `ERR_AGREEMENT_NOT_AWAITING_REVIEW` (HTTP 409); the logical clock must have reached `waiting_period_ends_at`, otherwise `ERR_WAITING_PERIOD_NOT_ELAPSED` (HTTP 422); and the `competitive_concern_flag` must be false — a latest-report concentration at or above the 2500 threshold blocks effectiveness with `ERR_COMPETITIVE_CONCERN_UNRESOLVED` (HTTP 409). A successful declaration moves the agreement to `EFFECTIVE`. Agreements are listable by every role; the listing accepts a `member_carrier_ids` parameter carrying a single carrier identifier that matches agreements whose member array contains it, and a `filed_by_carrier_id` parameter that filters by the filing carrier.

### 3.9. Enforcement Proceedings, Civil Penalties, and Port Performance Data

An `EnforcementCounsel` opens a proceeding against a carrier by naming the `target_carrier_id` and a `basis` of `UNREASONABLE_PRACTICE`, `TARIFF_VIOLATION`, `UNLICENSED_ACTIVITY`, or `AGREEMENT_VIOLATION`. The proceeding's `proceeding_status` is born `NOTICE_ISSUED`, with the caller recorded as `opened_by_counsel_id`. Until a determination is made, `determination`, `repeat_offender`, `penalty_cents`, `score_delta`, and `determined_at` are unset, and `violation_count` and `willful` carry no value either.

Determination belongs to an `AdministrativeLawJudge` and only while the proceeding stands in `NOTICE_ISSUED` — otherwise `ERR_PROCEEDING_NOT_NOTICE_ISSUED` (HTTP 409). The request carries a `determination` of `VIOLATION_FOUND` or `NO_VIOLATION`. A no-violation determination moves the proceeding to `DISMISSED` with no penalty and no score consequence; `penalty_cents` and `score_delta` remain unset. A violation determination requires a `violation_count` of at least one — absent, the request fails with `ERR_INVALID_REQUEST` (HTTP 400) — and accepts an optional `willful` flag defaulting to false. At the determination instant the server fixes `repeat_offender`: it is true exactly when another proceeding against the same carrier already stands in `DETERMINED` with a violation found, and it is the order in which determinations are made — not any wall-clock ordering of the underlying conduct — that decides.

The civil penalty then assembles in a pinned evaluation order. The base is `violation_count` times 1,000,000 cents per violation; a willful violation doubles the base; a repeat offender multiplies the running figure by three-halves in exact integer arithmetic — multiply by three, then divide by two; and the result is capped at 100,000,000 cents per proceeding. The compliance-score deduction depends on the basis: an `UNREASONABLE_PRACTICE` finding costs 100 points per violation, capped at 500 points for the proceeding; any other basis costs 50 points per violation, capped at 250 points; the deduction is recorded as a negative `score_delta`. The proceeding records `penalty_cents`, `score_delta`, and a `determined_at` stamp, and moves to `DETERMINED`. On the carrier, `cumulative_civil_penalties_cents` grows by the penalty and `compliance_score` absorbs the `score_delta` without ever falling below zero; if the deduction leaves the score below 600, the full suspension cascade of §2.10 fires. The proceedings against a carrier are listable by every role.

Separate from adjudication, the Commission collects weekly performance data. A `CommissionDocket` clerk ingests one report per terminal per week: a `port_code`, a `terminal_code`, a `week_start` that must be the Monday of the reported week at midnight UTC — anything else fails with `ERR_INVALID_REQUEST` — `berth_occupancy_hours` and `gate_closures_hours`, each between zero and 168 inclusive (the hours in a week), and a non-negative `vessel_dwell_hours_avg`. The triple of port, terminal, and week is unique — a resubmission is rejected with `ERR_DUPLICATE_CONGESTION_REPORT` (HTTP 409) — and a port's weekly berth capacity is bounded across terminals: the sum of `berth_occupancy_hours` over all reports sharing a `port_code` and `week_start` may not exceed 672 hours, or the submission is rejected with `ERR_PORT_CAPACITY_EXCEEDED` (HTTP 409). These reports are append-only; per §2.5 they carry no `updated_at` and no `version`. The same data feeds the incentive-principle scoring of §3.7, which reads berth occupancy back out of it.

## 4. Endpoint Definitions

Operations that create a new resource — registering an organization or shipper, filing a tariff, contract, agreement, license, invoice, dispute, complaint, proceeding, monitoring report, bond, or congestion report — return `201 Created`. Operations that modify an existing resource in place — publish, respond, mark-paid, the ombuds and adjudication transitions, go-effective, draws, determine, and the clock — return `200 OK`, as do all reads. The complete request and response shape of every operation is defined by the narratives of §2 and §3; this table is a locator, not a schema.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/fmc/carriers` | Register a regulated organization (carrier, MTO, NVOCC, or OFF) | CommissionAdmin |
| GET | `/fmc/carriers/{carrierId}` | Get a carrier organization | All roles |
| POST | `/fmc/shippers` | Register a shipper account | CommissionAdmin |
| GET | `/fmc/shippers/{shipperId}` | Get a shipper account | All roles |
| POST | `/fmc/carriers/{carrierId}/tariff-publications` | File a tariff publication (created DRAFT); OCC-guarded on the carrier's version | CarrierRep |
| GET | `/fmc/carriers/{id}/tariff-publications` | List a carrier's tariff publications | All roles |
| POST | `/fmc/tariff-publications/{tariffId}/publish` | Publish a DRAFT tariff once its effective date is reached | CarrierRep |
| POST | `/fmc/carriers/{carrierId}/service-contracts` | File a service contract (timely within 30 days of execution; created EFFECTIVE) | CarrierRep |
| GET | `/fmc/service-contracts` | List service contracts, filterable | All roles |
| GET | `/fmc/service-contracts/{contractId}` | Get a service contract | All roles |
| POST | `/fmc/carrier-agreements` | File a carrier agreement for competitive review (45-day waiting period) | CarrierRep |
| GET | `/fmc/carrier-agreements` | List carrier agreements, filterable | All roles |
| GET | `/fmc/carrier-agreements/{agreementId}` | Get a carrier agreement including monitoring reports and HHI | All roles |
| POST | `/fmc/carrier-agreements/{agreementId}/go-effective` | Declare an agreement effective after the waiting period and competitive clearance | ComplianceReviewer |
| POST | `/fmc/carrier-agreements/{agreementId}/monitoring-reports` | Append a competitive monitoring report | CarrierRep |
| POST | `/fmc/carriers/{carrierId}/oti-licenses` | Apply for an OTI license (created PENDING_BOND) | CarrierRep |
| GET | `/fmc/carriers/{id}/oti-licenses` | List a carrier's OTI licenses with embedded bonds | All roles |
| POST | `/fmc/oti-licenses/{licenseId}/surety-bonds` | Append a surety bond to a license | CarrierRep |
| POST | `/fmc/oti-licenses/{licenseId}/draws` | Post a signed draw or reversal against a bond; OCC-guarded on the license's version | EnforcementCounsel |
| POST | `/fmc/carriers/{carrierId}/invoices` | Issue a detention/demurrage invoice with all required billing elements | CarrierRep |
| GET | `/fmc/invoices` | List invoices, filterable | All roles |
| GET | `/fmc/invoices/{invoiceId}` | Get an invoice | All roles |
| POST | `/fmc/invoices/{invoiceId}/mark-paid` | The billed party marks an ISSUED invoice paid | ShipperRep |
| POST | `/fmc/invoices/{invoiceId}/disputes` | The billed party opens a billing dispute on an ISSUED invoice | ShipperRep |
| GET | `/fmc/invoices/{id}/disputes` | List the disputes on an invoice | All roles |
| POST | `/fmc/invoice-disputes/{disputeId}/respond` | The carrier responds to a dispute within the response window | CarrierRep |
| POST | `/fmc/complaints` | File a detention/demurrage complaint; computes and freezes the incentive-principle score | ShipperRep |
| GET | `/fmc/complaints` | List complaints, filterable | All roles |
| GET | `/fmc/complaints/{complaintId}` | Get a complaint | All roles |
| POST | `/fmc/complaints/{complaintId}/refer-ombuds` | Refer a DOCKETED complaint to the ombuds process | CommissionDocket |
| POST | `/fmc/complaints/{complaintId}/close-ombuds` | The assigned officer closes the ombuds round (SETTLED or FAILED) | OmbudsOfficer |
| POST | `/fmc/complaints/{complaintId}/open-adjudication` | Open formal adjudication (segregation of duties applies) | AdministrativeLawJudge |
| POST | `/fmc/complaints/{complaintId}/decide` | The presiding judge issues the decision with reparations | AdministrativeLawJudge |
| POST | `/fmc/complaints/{complaintId}/appeal` | Complainant or respondent appeals within the appeal window | ShipperRep, CarrierRep |
| POST | `/fmc/complaints/{complaintId}/resolve-appeal` | Resolve an appeal at Commission level (AFFIRM or REVERSE) | CommissionAdmin |
| POST | `/fmc/enforcement-proceedings` | Open an enforcement proceeding against a carrier | EnforcementCounsel |
| GET | `/fmc/carriers/{id}/enforcement-proceedings` | List enforcement proceedings against a carrier | All roles |
| GET | `/fmc/enforcement-proceedings/{proceedingId}` | Get an enforcement proceeding | All roles |
| POST | `/fmc/enforcement-proceedings/{proceedingId}/determine` | Determine a proceeding; a violation computes penalty and score effects | AdministrativeLawJudge |
| POST | `/fmc/port-congestion-reports` | Ingest a weekly per-terminal port congestion report | CommissionDocket |
| POST | `/_clock/set_current_utc` | Set the server's logical clock (platform-level, outside the business surface) | CommissionAdmin |

## 5. Error Code Catalogue

The catalogue below enumerates every error identifier the API can return and its HTTP status code. The conditions that trigger each error are defined by the narratives of §2 and §3, not by this table.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_FORBIDDEN_RESOURCE_ACCESS` | 403 Forbidden |
| `ERR_CARRIER_NOT_FOUND` | 404 Not Found |
| `ERR_SHIPPER_NOT_FOUND` | 404 Not Found |
| `ERR_TARIFF_NOT_FOUND` | 404 Not Found |
| `ERR_CONTRACT_NOT_FOUND` | 404 Not Found |
| `ERR_AGREEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_LICENSE_NOT_FOUND` | 404 Not Found |
| `ERR_INVOICE_NOT_FOUND` | 404 Not Found |
| `ERR_DISPUTE_NOT_FOUND` | 404 Not Found |
| `ERR_COMPLAINT_NOT_FOUND` | 404 Not Found |
| `ERR_PROCEEDING_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVOICE_MISSING_REQUIRED_ELEMENT` | 400 Bad Request |
| `ERR_INVALID_INVOICE_DATES` | 400 Bad Request |
| `ERR_REDUCED_AMOUNT_NOT_LOWER` | 400 Bad Request |
| `ERR_JUSTIFICATION_REQUIRED` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_CARRIER_NOT_ACTIVE` | 409 Conflict |
| `ERR_TARIFF_NOT_IN_DRAFT` | 409 Conflict |
| `ERR_TARIFF_NOT_PUBLISHED` | 409 Conflict |
| `ERR_CONTRACT_NOT_EFFECTIVE` | 409 Conflict |
| `ERR_LICENSE_NOT_ACTIVE` | 409 Conflict |
| `ERR_INVOICE_NOT_DISPUTABLE` | 409 Conflict |
| `ERR_INVOICE_NOT_PAYABLE` | 409 Conflict |
| `ERR_DISPUTE_NOT_PENDING` | 409 Conflict |
| `ERR_COMPLAINT_NOT_DOCKETED` | 409 Conflict |
| `ERR_COMPLAINT_NOT_ADJUDICATING` | 409 Conflict |
| `ERR_APPEAL_NOT_ALLOWED` | 409 Conflict |
| `ERR_PROCEEDING_NOT_NOTICE_ISSUED` | 409 Conflict |
| `ERR_AGREEMENT_NOT_AWAITING_REVIEW` | 409 Conflict |
| `ERR_INVOICE_NOT_ACTIONABLE` | 409 Conflict |
| `ERR_EFFECTIVE_DATE_NOTICE_SHORT` | 422 Unprocessable Entity |
| `ERR_PUBLISH_WINDOW_NOT_REACHED` | 422 Unprocessable Entity |
| `ERR_LATE_SERVICE_CONTRACT_FILING` | 422 Unprocessable Entity |
| `ERR_LATE_INVOICE_ISSUANCE` | 422 Unprocessable Entity |
| `ERR_COMPLAINT_FILING_WINDOW_EXPIRED` | 422 Unprocessable Entity |
| `ERR_APPEAL_WINDOW_EXPIRED` | 422 Unprocessable Entity |
| `ERR_WAITING_PERIOD_NOT_ELAPSED` | 422 Unprocessable Entity |
| `ERR_TARIFF_CARRIER_MISMATCH` | 422 Unprocessable Entity |
| `ERR_BILLED_PARTY_NOT_CONTRACT_PARTY` | 422 Unprocessable Entity |
| `ERR_NOT_INVOICE_PARTY` | 422 Unprocessable Entity |
| `ERR_RESPONDENT_NOT_INVOICE_CARRIER` | 422 Unprocessable Entity |
| `ERR_LICENSE_TYPE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_INVALID_AGREEMENT_MEMBERSHIP` | 422 Unprocessable Entity |
| `ERR_MEMBER_SET_MISMATCH` | 422 Unprocessable Entity |
| `ERR_EMPTY_SUBJECT_SET` | 422 Unprocessable Entity |
| `ERR_OMBUDS_ROUND_LIMIT_EXCEEDED` | 409 Conflict |
| `ERR_MONITORING_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_DUPLICATE_CONGESTION_REPORT` | 409 Conflict |
| `ERR_DUPLICATE_BOND_REF` | 409 Conflict |
| `ERR_PORT_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_BOND_COVERAGE_EXCEEDED` | 402 Payment Required |
| `ERR_BOND_REVERSAL_EXCEEDED` | 402 Payment Required |
| `ERR_ADJUDICATOR_CONFLICT` | 403 Forbidden |
| `ERR_COMPETITIVE_CONCERN_UNRESOLVED` | 409 Conflict |
