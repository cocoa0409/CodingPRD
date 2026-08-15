# Utility Rate Case API — Product Requirements Document

## 1. Introduction

This document specifies a state public utility commission's rate case and cost-of-service filing system. A rate case is the formal regulatory proceeding through which an investor-owned utility seeks commission approval to change the rates it charges customers. The proceeding is adversarial and documentary: the utility files testimony, accounting schedules, and rate-design proposals; commission staff audit the filing; intervenor parties (industrial customer groups, consumer advocates, environmental organizations) issue discovery, dispute adjustments, and negotiate settlements; and an administrative law judge manages the procedural calendar, rules on discovery objections, and ultimately issues a final order.

The system under specification manages the entire lifecycle of one such docket, from the utility's initial test-year data assembly through the commission's compliance-monitoring true-up after new rates take effect. It covers test-year booked amounts and known-and-measurable adjustments, rate-base computation and audit, customer-class cost allocation under two alternative demand-allocation methods, multi-party discovery with deadlines and ALJ rulings, settlement circulation with unanimous-consent signature mechanics, issuance of a final order that simultaneously adopts a settlement, approves tariff schedules, and approves regulatory-asset amortization, post-order rate implementation, monthly amortization posting with strict ordering and LIFO reversal, and annual compliance filings with de-minimis true-up reconciliation. Because the same docket record is concurrently touched by the utility, commission staff, intervenor representatives, and the ALJ, the system enforces strict role scoping, segregation of duties on adjustment verification, and optimistic concurrency on the small set of write endpoints whose legitimate semantics include superseding a prior round.

The audience is the engineering team implementing this API. Every rule stated here is contractual; where a numeric threshold, rounding rule, evaluation order, or cascade is given, it is a requirement, not an illustration.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` and `X-User-Role`. Either header missing or empty is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). Once headers are present, the role named in `X-User-Role` is checked against the endpoint's authorized role list; a caller whose role is not listed is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

Four roles exist, spelled exactly:

- `UtilityFiler` — utility regulatory staff: assembles test-year data, proposes adjustments and rate design, responds to discovery, circulates settlements, implements rates, files compliance.
- `CommissionStaff` — public utility commission staff: deficiency review, rate-base audit, opens discovery, staff data requests, compliance review, clock control for the procedural calendar.
- `IntervenorRep` — registered intervenor party representative; `X-User-ID` equals the Intervenor `id` of the party they represent.
- `ALJ` — administrative law judge: procedural schedule control, objection rulings, settlement recommendation/remand, final order, docket closure.

**Identity semantics.** When `X-User-Role` is `IntervenorRep`, `X-User-ID` is the `id` of the acting Intervenor; ownership checks on any resource that references an Intervenor compare the resource's foreign-key field (for example, a SettlementSignatory's `intervenor_id` or a DataRequest's `issuing_intervenor_id`) to `X-User-ID`. When `X-User-Role` is `UtilityFiler`, `CommissionStaff`, or `ALJ`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it where a transition writes it (for example, as `proposed_by_user_id` or `verified_by_user_id` on an Adjustment) but does not compare it to any entity's `id`.

**Ownership scope.** `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403) rejects ownership violations on the ownership-scoped endpoints: an IntervenorRep withdrawing a data request must be the request's `issuing_intervenor_id`; signing, declining, or rescinding a SettlementSignatory requires `X-User-ID` equal to the signatory's `intervenor_id`; an IntervenorRep withdrawing a party must equal that party's `id`; and withdrawing an Adjustment requires `X-User-ID` equal to the adjustment's `proposed_by_user_id`. Segregation of duties applies to Adjustment verify: the verifier's `X-User-ID` must differ from the adjustment's `proposed_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits. It is generated from wall-clock time and is independent of the §2.6 logical clock, which timestamps only persisted entity fields and deadline computations.
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

All list endpoints accept `limit` and `offset` query parameters. `limit` defaults to 10, has a minimum of 1, and a maximum of 100. `offset` defaults to 0, with a minimum of 0. A non-integer or out-of-range `limit` or `offset` is `ERR_INVALID_REQUEST` (HTTP 400); on list endpoints, header presence and role authorization are enforced before `limit`/`offset` validation. Unrecognized query parameters are ignored. The `meta` block of every list response carries `limit`, `offset`, `total_count`, and `has_more`, where `has_more` is true exactly when `offset` plus the number of rows returned is less than `total_count`. Every list endpoint returns rows ordered by `created_at` ascending. Rows minted in a single cascade share one `created_at` timestamp; their relative order is the cascade's generation order, pinned per collection: for AmortizationEntry the order is `period_index` ascending, and for SettlementSignatory the generation loop iterates the case's Intervenors by `created_at` ascending, breaking ties by `party_name` ascending. Any rows sharing one `created_at` — cascade-minted or not — are ordered by creation (insertion) sequence, which is also the residual tie-break after the pinned cascade orders. The random UUID `id` field is never used as a sort key or tie-break anywhere.

### 2.4. Common Resource Properties

Every persisted resource carries an `id` field, which is a server-minted UUID with no type prefix. Resources with the standard field set additionally carry `created_at` and `updated_at`, both ISO 8601 UTC timestamps at whole-second precision (`YYYY-MM-DDTHH:MM:SSZ`) stamped from the §2.6 logical clock, and an integer `version` that starts at 1 at creation and increments on mutation. Date-time inputs are accepted in any ISO 8601 form and are stored normalized to UTC at whole-second precision (fractional seconds truncated, offsets converted). All resources named in this specification — RateCase, Intervenor, TestYearEntry, Adjustment, RateBaseItem, CustomerClass, DataRequest, SettlementProposal, SettlementSignatory, RegulatoryAsset, AmortizationEntry, TariffRate, ComplianceFiling — carry the standard field set. Each of these resources also carries a `status` field whose value is one of the entity-specific UPPERCASE state strings enumerated in §3.

### 2.5. Monetary Precision and Rounding

All monetary values are integer cents. No monetary field is a float, and no monetary computation produces a fractional cent. Where a calculation produces an intermediate non-integer, the rounding rule is stated alongside the formula in §3; the two rounding modes used in this specification are **round half up** (used for the rate-of-return component, the three class cost-allocation components, per-tier energy charges, the gradualism system-average and cap, and the true-up threshold) and **round half away from zero** (used for per-class true-up line allocation). The amortization schedule uses **floor** for base installments and pushes the rounding remainder into the final installment. The two named rounding modes are realized by a single symmetric primitive: for a negative quotient, ties resolve away from zero (the two modes coincide for non-negative quotients, which are the common case). Integer-cent addition and subtraction are otherwise exact.

### 2.6. The Procedural Clock

The server maintains a logical clock used to timestamp every time-derived field and to drive two system sweeps. At startup, before any call, the clock reads exactly `2026-08-01T00:00:00Z`; it never falls back to wall-clock time. An administrative test-driving capability (restricted to `CommissionStaff`) sets the logical clock to a supplied `to_iso8601` instant and returns the new `current_utc`. Only strictly forward moves are accepted: an attempt to set the clock to an instant at or before the current logical clock is rejected with `ERR_CLOCK_REGRESSION` (HTTP 409). After each successful advance, the server runs the discovery-overdue sweep and the tariff-supersede sweep described in §3.4 and §3.7.

### 2.7. Nested Resource Retrieval

Endpoints whose paths carry multiple resource identifiers validate path identifiers left-to-right. Each identifier must reference an existing resource, otherwise the request is rejected with the resource-type-specific not-found error listed in §5 (for example, an unknown case id on any `/api/v1/rate-cases/{caseId}/...` path is `ERR_RATE_CASE_NOT_FOUND`).

### 2.8. Optimistic Concurrency Control

Two create-with-supersede endpoints take a non-optional `expected_rate_case_version` input field that carries the client's last observed `version` of the parent RateCase: settlement-round creation and compliance-filing creation. If `expected_rate_case_version` does not equal the case's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from composing a round (or a filing) that would supersede state it has not observed. Endpoints not listed here do not take a version field.

### 2.9. Request Validation Order

On any request, validations are applied in a fixed priority order so that a request failing several checks surfaces the same error on every implementation. First, request-shape checks (required fields present, no unknown fields, enum members valid, integer ranges respected, tier arrays well-formed) — failures are `ERR_INVALID_REQUEST` (HTTP 400). Date-range internal consistency is checked at the same priority — `ERR_INVALID_DATE_RANGE` (HTTP 400) — as are the two notes-required rules, `ERR_DEFICIENCY_NOTES_REQUIRED` and `ERR_REMAND_NOTES_REQUIRED`. After shape and date checks come authentication header presence, then role authorization. Ownership scope and segregation of duties follow role authorization, but their position relative to existence checks depends on whether the rule needs the stored record: the two ownership rules that compare `X-User-ID` directly against a request field or the path identifier itself — data-request issuance by an `IntervenorRep` (`issuing_intervenor_id` must equal `X-User-ID`) and party withdrawal by an `IntervenorRep` (`X-User-ID` must equal the path's intervenor id) — run immediately after role authorization, before existence checks; every other ownership or segregation-of-duties rule (adjustment withdrawal and verification, data-request withdrawal, signatory sign, decline, and rescind) runs immediately after the target resource's existence check, because the stored record must be read first. Existence checks (each `ERR_*_NOT_FOUND`) resolve the parent case reference first, then remaining body-supplied references in the order their fields are listed in §3. After existence come state-machine guards (the per-entity `ERR_INVALID_*_STATE` family and the case-phase guards `ERR_ENTRIES_NOT_LOCKED`, `ERR_UNRESOLVED_ADJUSTMENTS`, `ERR_NO_TEST_YEAR_ENTRIES`, `ERR_NO_RATE_BASE_ITEMS`, `ERR_OVERDUE_DATA_REQUESTS_EXIST`, `ERR_NO_RECOMMENDED_SETTLEMENT`, `ERR_CLASS_TARIFF_MISSING`, `ERR_NO_ACCEPTED_FILING`, `ERR_PROPOSAL_NOT_SUPERSEDABLE`, `ERR_FILING_NOT_SUPERSEDABLE`), then business-safety (`ERR_BELOW_CUSTOMER_COST_FLOOR`), then temporal-window rules (`ERR_DISCOVERY_WINDOW_CLOSED`, `ERR_TARIFF_WINDOW_OVERLAP`, `ERR_DEFERRAL_OVERLAPS_TEST_YEAR`, `ERR_CLOCK_REGRESSION`), then cross-case referential rules (`ERR_ADJUSTMENT_NOT_IN_CASE`, `ERR_CLASS_NOT_IN_CASE`, `ERR_PARTY_NOT_IN_CASE`, `ERR_INCOMPLETE_CLASS_REVENUE`), then structural uniqueness and ordering (`ERR_CASE_NUMBER_NOT_UNIQUE`, `ERR_CLASS_CODE_NOT_UNIQUE`, `ERR_AMORTIZATION_OUT_OF_ORDER`, `ERR_REVERSAL_NOT_LATEST`, `ERR_GRADUALISM_CAP_EXCEEDED`), then fiscal integrity (`ERR_RR_MISMATCH`, `ERR_NONPOSITIVE_REVENUE_REQUIREMENT`, `ERR_SETTLEMENT_ABOVE_FILED`), and finally OCC (`ERR_STALE_VERSION`).

### 2.10. Aggregate Counters on the Case

Two counters live on the RateCase and are maintained incrementally by the operations described in §3 — they are not recomputed from scratch on read. `overdue_data_request_count` counts this case's DataRequests currently in `OVERDUE`; it is incremented by the discovery-overdue sweep each time a request flips to `OVERDUE`, and decremented whenever a request leaves `OVERDUE` (by response, withdrawal, or party-withdrawal cascade). `assented_proposal_count` counts this case's SettlementProposals currently in `ASSENTED`, `RECOMMENDED`, `ADOPTED`, or `REMANDED` that reached `ASSENTED` via full signature; it is incremented on the bubble-up to `ASSENTED` and decremented on a rescind that drops an `ASSENTED` proposal back to `UNDER_NEGOTIATION` — a remand does not decrement it, so a remanded proposal remains counted. Both counters start at 0 when the case is created.

## 3. Business Logic & Workflows

### 3.1. Docket Opening and Test-Year Assembly

A `UtilityFiler` opens a new rate case docket by supplying `case_number` (the unique docket number, for example `UR-2026-104`, unique across all cases — a duplicate is `ERR_CASE_NUMBER_NOT_UNIQUE`), `utility_name`, `test_year_start`, `test_year_end`, `return_on_rate_base_bp` (the authorized return on rate base in basis points, so `750` means 7.50%, accepted in the range 1 through 3000 inclusive), `proposed_revenue_requirement_cents` (the utility's as-filed revenue requirement claim, validated at submit-filing), and `allocation_method` (either `COINCIDENT_PEAK` or `ENERGY_AVERAGE`, selecting how demand costs are allocated across customer classes). The test-year window is a closed interval: `test_year_end` must be strictly after `test_year_start`, otherwise `ERR_INVALID_DATE_RANGE`. A new case enters `DRAFT`, and the two aggregate counters `overdue_data_request_count` and `assented_proposal_count` initialize to zero.

While the case is in `DRAFT` or `DEFICIENT`, the utility assembles the test-year record. Each booked line is a TestYearEntry created with `rate_case_id`, `account_code` (a FERC-style account code), `category` (one of `O_AND_M`, `DEPRECIATION`, or `TAXES`), and `booked_amount_cents` (the per-books test-year amount, which must be greater than or equal to zero). On creation, `adjusted_amount_cents` equals `booked_amount_cents` and the entry's status is `DRAFT`.

Test-year entries carry their own small state machine. The utility submits a `DRAFT` entry (moving it to `SUBMITTED`), may reopen a `SUBMITTED` entry back to `DRAFT` while the case remains editable, and locks a `SUBMITTED` entry to `LOCKED`. All three transitions require the owning case in `DRAFT` or `DEFICIENT`; the wrong entry state yields `ERR_INVALID_ENTRY_STATE`, the wrong case state yields `ERR_INVALID_CASE_STATE`, and the entry-state guard is evaluated before the case-state guard. Locking is blocked by any `DISPUTED` adjustment targeting the entry — `ERR_UNRESOLVED_ENTRY_ADJUSTMENTS`, checked after the entry-state and case-state guards — but `PROPOSED` adjustments do not block entry lock (they block the case-level filing instead). `LOCKED` is terminal for an entry.

### 3.2. Known-and-Measurable Adjustments and Segregation of Duties

Against a test-year entry in `DRAFT` or `SUBMITTED`, a `UtilityFiler` may propose a known-and-measurable adjustment by supplying `rate_case_id`, `test_year_entry_id` (which must reference an entry of the same case — a cross-case reference is `ERR_ADJUSTMENT_NOT_IN_CASE`), a signed `amount_cents` (which must not equal zero — a zero amount is `ERR_INVALID_REQUEST`), and a `reason` text. The server records the caller's `X-User-ID` into `proposed_by_user_id`, sets the status to `PROPOSED`, and recomputes the entry's `adjusted_amount_cents`.

The entry's adjusted amount is the booked amount plus the sum of `amount_cents` over all adjustments of that entry whose status is `PROPOSED`, `VERIFIED`, `DISPUTED`, or `ACCEPTED`; `WITHDRAWN` and `REJECTED` adjustments are excluded. This recomputation is triggered by adjustment creation, verification, rejection, and withdrawal, and by the submit-filing acceptance cascade described in §3.3.

Verification enforces segregation of duties. A `UtilityFiler` verifies a `PROPOSED` or `DISPUTED` adjustment; the verifier's `X-User-ID` must differ from `proposed_by_user_id` (otherwise `ERR_SEGREGATION_OF_DUTIES`), the adjustment must be in `PROPOSED` or `DISPUTED` (otherwise `ERR_INVALID_ADJUSTMENT_STATE`), and the owning entry must not be `LOCKED` (otherwise `ERR_INVALID_ENTRY_STATE`) — the three checks run in that order: segregation of duties, then adjustment state, then entry lock. On success the server sets `verified_by_user_id` to the caller, moves the adjustment to `VERIFIED`, and recomputes the entry's `adjusted_amount_cents` — a `VERIFIED` adjustment counts toward the entry total. Dispute is the inverse voice: `CommissionStaff` or any `IntervenorRep` may dispute a `VERIFIED` adjustment, moving it to `DISPUTED`. Rejection is a staff-only action: a `CommissionStaff` operator rejects a `VERIFIED` or `DISPUTED` adjustment, moving it to `REJECTED` and triggering a recompute that excludes the rejected amount. Withdrawal is restricted to the proposer: a `UtilityFiler` withdraws a `PROPOSED` or `DISPUTED` adjustment, requiring `X-User-ID` equal to `proposed_by_user_id` (otherwise `ERR_FORBIDDEN_OWNERSHIP`); the adjustment moves to `WITHDRAWN` and is excluded from the entry total. `ACCEPTED`, `REJECTED`, and `WITHDRAWN` are terminal states.

### 3.3. Rate Base and the Submit-Filing Gate

In parallel with test-year entries, the utility assembles the rate base. Each RateBaseItem is created while the case is in `DRAFT` or `DEFICIENT` with `rate_case_id`, `label`, and four monetary inputs — `plant_in_service_cents` (gross plant in service), `accumulated_depreciation_cents` (the depreciation reserve), `working_capital_cents` (the cash working capital allowance), and `accumulated_deferred_taxes_cents` (accumulated deferred income taxes, treated as a deduction). All four amounts must be greater than or equal to zero. The item's net rate base is computed as `plant_in_service_cents` minus `accumulated_depreciation_cents` plus `working_capital_cents` minus `accumulated_deferred_taxes_cents`; this `net_rate_base_cents` is stored on the item. A new item enters `DRAFT`.

RateBaseItem follows a submit–audit–revise cycle. The utility submits a `DRAFT` item (moving to `SUBMITTED`) while the case is in `DRAFT` or `DEFICIENT`. Staff audit is then available while the case is in `FILED`, `ACCEPTED`, `DISCOVERY`, `HEARING`, or `SETTLEMENT`: a `CommissionStaff` audit with `outcome` equal to `AUDIT_PASS` moves the item to `AUDITED`; an audit with `outcome` equal to `AUDIT_EXCEPTION` moves it to `EXCEPTION` (an optional `exception_notes` text is accepted with either outcome; it is not persisted on the item). An `EXCEPTION` item may be revised by the utility: the four amount fields are replaced with the request values, `net_rate_base_cents` is recomputed, and the item returns to `SUBMITTED`. Revision is permitted while the case is in `FILED`, `ACCEPTED`, `DISCOVERY`, `HEARING`, `SETTLEMENT`, or `DEFICIENT`. Wrong item state is `ERR_INVALID_ITEM_STATE`; wrong case state is `ERR_INVALID_CASE_STATE`; on submit, audit, and revise the item-state guard is evaluated before the case-state guard. `AUDITED` is terminal.

The filing gate is the submit-filing transition, available to `UtilityFiler` while the case is in `DRAFT` or `DEFICIENT` (any other case state is `ERR_INVALID_CASE_STATE`, checked before the enumerated guards). Its guards are evaluated in a pinned order. Case-level guards come first, in this order: (1) at least one TestYearEntry exists for the case — otherwise `ERR_NO_TEST_YEAR_ENTRIES`; (2) every TestYearEntry of the case is `LOCKED` — otherwise `ERR_ENTRIES_NOT_LOCKED`; (3) zero adjustments of the case are in `PROPOSED` or `DISPUTED` — otherwise `ERR_UNRESOLVED_ADJUSTMENTS`; (4) at least one RateBaseItem of the case is in `SUBMITTED` or `AUDITED` — otherwise `ERR_NO_RATE_BASE_ITEMS`. Fiscal guards follow, also in pinned order: (1) the computed as-filed revenue requirement must be strictly greater than zero — otherwise `ERR_NONPOSITIVE_REVENUE_REQUIREMENT`; (2) the absolute difference between the case's `proposed_revenue_requirement_cents` and the computed as-filed revenue requirement must be at most 100 cents — otherwise `ERR_RR_MISMATCH`. On success, every `VERIFIED` adjustment of the case moves to `ACCEPTED` (the acceptance cascade), and the case moves to `FILED`.

### 3.4. Sufficiency Review, Discovery, and the Data-Request Lifecycle

After filing, `CommissionStaff` performs a sufficiency review via the deficiency-review action, supplying an `outcome`. With `outcome` equal to `ACCEPTED` the case moves from `FILED` to `ACCEPTED`. With `outcome` equal to `DEFICIENT` the case moves back to `DEFICIENT`, and a non-empty `deficiency_notes` must be supplied — otherwise `ERR_DEFICIENCY_NOTES_REQUIRED`. A `deficiency_notes` supplied on the `ACCEPTED` branch is accepted and ignored; the notes are not persisted on the case in either branch. Either branch requires the case in `FILED` (`ERR_INVALID_CASE_STATE`).

Once `ACCEPTED`, staff opens discovery. This stamps `discovery_close_at` to the current logical clock plus 120 days and moves the case to `DISCOVERY`. Data requests may not be issued after `discovery_close_at`: an issue request whose clock time is later than `discovery_close_at` is rejected with `ERR_DISCOVERY_WINDOW_CLOSED`.

A data request is created by an `IntervenorRep` or by `CommissionStaff`. The payload carries `rate_case_id`, `subject`, `body`, an optional `issuing_intervenor_id`, and an optional `referenced_adjustment_id` for targeted discovery. `issuer_kind` is derived from the caller's role: `INTERVENOR` for an `IntervenorRep` caller, `STAFF` for a `CommissionStaff` caller. An `IntervenorRep` caller must pass `issuing_intervenor_id` equal to their `X-User-ID` (a mismatch is `ERR_FORBIDDEN_OWNERSHIP`; omitting it is `ERR_INVALID_REQUEST`); a `CommissionStaff` caller must omit `issuing_intervenor_id` (supplying it is `ERR_INVALID_REQUEST`). A JSON null is treated as omitted. If `referenced_adjustment_id` is present it must reference an adjustment of the same case — otherwise `ERR_ADJUSTMENT_NOT_IN_CASE`; if `issuing_intervenor_id` is present it must reference an intervenor of the same case — otherwise `ERR_PARTY_NOT_IN_CASE`. A referenced id that resolves to nothing at all draws the resource-type-specific not-found error (`ERR_ADJUSTMENT_NOT_FOUND` or `ERR_INTERVENOR_NOT_FOUND`) from the existence tier, which precedes the same-case checks. The server stamps `issued_at` with the current clock, sets `response_due_at` to `issued_at` plus 10 days, and the request enters `ISSUED`. `response_text`, `objection_reason`, `ruling`, and `extended_due_at` are null at issue.

The utility answers a request in `ISSUED`, `OVERDUE`, or `RESPOND_REQUIRED` by responding with a `response_text`; the request moves to `RESPONDED`. Responding to a request that is currently `OVERDUE` also decrements the case's `overdue_data_request_count`. As an alternative available only from `ISSUED`, the utility may object, supplying an `objection_reason`; the request moves to `OBJECTED`. The ALJ then rules on the objection with a `ruling`: `SUSTAINED` moves the request to `CLOSED` and records the ruling; `OVERRULED` moves it to `RESPOND_REQUIRED`, records the ruling, and sets `extended_due_at` to the ruling clock time plus 5 days. Any wrong-state invocation is `ERR_INVALID_REQUEST_STATE`.

Withdrawal of a data request is available from `ISSUED`, `OBJECTED`, `OVERDUE`, or `RESPOND_REQUIRED` to the issuing party: if `issuer_kind` is `INTERVENOR`, the caller must be an `IntervenorRep` whose `X-User-ID` equals `issuing_intervenor_id` (otherwise `ERR_FORBIDDEN_OWNERSHIP`); if `issuer_kind` is `STAFF`, the caller must be `CommissionStaff`. Withdrawing a request that is currently `OVERDUE` decrements the case's `overdue_data_request_count`.

The discovery-overdue sweep runs each time the logical clock advances. Every DataRequest in `ISSUED` whose `response_due_at` is strictly before the new clock flips to `OVERDUE`, and every DataRequest in `RESPOND_REQUIRED` whose `extended_due_at` is strictly before the new clock flips to `OVERDUE`; each flip increments the owning case's `overdue_data_request_count` by one. A request whose due instant is exactly equal to the new clock is not overdue — the comparison is strictly-before. The sweep processes candidates in `created_at` ascending order; the count is order-independent because each flip contributes exactly one.

### 3.5. Hearing, Settlement Circulation, and Unanimous Consent

The ALJ advances the case from `DISCOVERY` to `HEARING` once discovery is clean: the case must be in `DISCOVERY` (otherwise `ERR_INVALID_CASE_STATE`, checked first) and `overdue_data_request_count` must equal zero (otherwise `ERR_OVERDUE_DATA_REQUESTS_EXIST`). From `HEARING`, the ALJ opens the settlement window, moving the case to `SETTLEMENT`.

While the case is in `SETTLEMENT`, a `UtilityFiler` may open a new settlement round by creating a SettlementProposal with `rate_case_id`, `proposed_revenue_requirement_cents`, `terms`, and the OCC field `expected_rate_case_version`. The settlement's revenue requirement must not exceed the case's `proposed_revenue_requirement_cents` — a settlement above the filed claim is `ERR_SETTLEMENT_ABOVE_FILED`. Because creating a new round legitimately supersedes the case's prior round, the supersede rules apply: if the case has an existing proposal in `DRAFT` or `UNDER_NEGOTIATION`, that proposal moves to `SUPERSEDED` and each of its signatories in `PENDING` or `SIGNED` moves to `VOID` (affected proposals then recompute their signature counts, with `VOID` rows excluded from both `signature_count` and `required_signature_count`); if the case has an existing proposal in `ASSENTED`, `RECOMMENDED`, or `ADOPTED`, the new round is rejected with `ERR_PROPOSAL_NOT_SUPERSEDABLE`. The new proposal's `round_number` is one for the case's first proposal, otherwise one more than the maximum existing `round_number`; it enters `DRAFT` with `signature_count` and `required_signature_count` both zero; and the create increments the case's `version`.

Circulation moves a `DRAFT` proposal to `UNDER_NEGOTIATION` (requiring the owning case in `SETTLEMENT`, otherwise `ERR_INVALID_CASE_STATE`; a proposal not in `DRAFT` is `ERR_INVALID_PROPOSAL_STATE`, and the proposal-state guard is evaluated before the case-state guard). At circulation the server generates one SettlementSignatory in `PENDING` for each Intervenor of the case currently in `PARTY` status, iterating parties by `created_at` ascending (tie-break `party_name` ascending) for deterministic list order. `required_signature_count` is set to the number of signatories generated. Each signatory row carries `settlement_proposal_id` and `intervenor_id`; `signed_at` is null until signed.

Signing is an `IntervenorRep` action on the rep's own row: the signatory must be in `PENDING` (otherwise `ERR_INVALID_SIGNATORY_STATE`), the caller's `X-User-ID` must equal the row's `intervenor_id` (otherwise `ERR_FORBIDDEN_OWNERSHIP`), and the owning proposal must be in `UNDER_NEGOTIATION` (otherwise `ERR_INVALID_PROPOSAL_STATE`). On signing, the row moves to `SIGNED`, `signed_at` is stamped with the current clock, and the proposal's `signature_count` (the count of its signatories in `SIGNED`) is recomputed. If after a sign the proposal's `signature_count` equals its `required_signature_count` and `required_signature_count` is greater than zero, the proposal bubbles up to `ASSENTED` and the case's `assented_proposal_count` is incremented by one.

Decline is the terminal negative voice: an `IntervenorRep` declines their own `PENDING` row, moving it to `DECLINED` — decline consults only the row's state; the owning proposal's state is not checked. The proposal can no longer reach `ASSENTED`, and the remedy is a superseding round. Rescind is available on a `SIGNED` row while the owning proposal is in `UNDER_NEGOTIATION` or `ASSENTED`: the row moves to `RESCINDED`, the proposal's `signature_count` is recomputed, and if the proposal was `ASSENTED` it drops back to `UNDER_NEGOTIATION` and the case's `assented_proposal_count` is decremented by one. A signatory in `PENDING` also moves to `VOID` when its owning proposal is superseded or when its party withdraws; a signatory in `SIGNED` moves to `VOID` only when its owning proposal is superseded. In both `VOID` cascades the affected proposal recomputes its signature counts with `VOID` rows excluded — `required_signature_count` excluded in the party-withdrawal and supersede cases, and `signature_count` excluded in the supersede case.

Once a proposal is `ASSENTED`, the ALJ either recommends it (moving it to `RECOMMENDED`) or remands it with a `remand_reason` (moving it to `REMANDED`, which is terminal; a new round is the remedy, since only `DRAFT` or `UNDER_NEGOTIATION` proposals are superseded by a new round). Recommend and remand check only the proposal's state — there is no case-phase guard — and a missing or blank `remand_reason` is `ERR_INVALID_REQUEST`; the reason is not persisted on the proposal. With at least one `RECOMMENDED` proposal on the case, the ALJ certifies the record by advancing the case to `ORDER_PENDING`; if no proposal is `RECOMMENDED`, the advance is rejected with `ERR_NO_RECOMMENDED_SETTLEMENT` — the case-state guard (case must be in `SETTLEMENT`, otherwise `ERR_INVALID_CASE_STATE`) runs first.

### 3.6. Final Order, Tariff Approval, and Regulatory-Asset Amortization

The issue-order action is the proceeding's denouement, available to the ALJ while the case is in `ORDER_PENDING`. The request carries `approved_tariff_ids` and `approved_asset_ids`, both required arrays of strings, either of which may be empty. Ids are validated in a pinned order: tariff ids before asset ids. Every listed id must resolve — an unknown tariff id is `ERR_TARIFF_NOT_FOUND`, an unknown asset id is `ERR_ASSET_NOT_FOUND` — with the existence of all tariff ids checked first, then all asset ids, before any state check. Every id in `approved_tariff_ids` must reference a TariffRate of this case in `PROPOSED` — otherwise `ERR_INVALID_TARIFF_STATE`. Every id in `approved_asset_ids` must reference a RegulatoryAsset of this case in `DEFERRED` — otherwise `ERR_INVALID_ASSET_STATE`.

The side effects cascade in hops. First, the case's `authorized_revenue_requirement_cents` is set from the `RECOMMENDED` proposal's `proposed_revenue_requirement_cents` (if several proposals are `RECOMMENDED`, the one with the largest `round_number`; a tie is impossible), and that proposal moves from `RECOMMENDED` to `ADOPTED`. Second, each listed tariff moves from `PROPOSED` to `APPROVED`, and each unlisted `PROPOSED` tariff moves to `REJECTED`. Third, each tariff approval recomputes its class's `approved_revenue_cents` from the approved tariff's `proposed_revenue_cents`; approvals are applied in tariff creation order, so when several approved tariffs share one class the latest-created approved tariff's `proposed_revenue_cents` prevails. Fourth, each class recompute refreshes the case's `revenue_at_approved_rates_cents` as the sum of `approved_revenue_cents` over all classes. Fifth, each listed asset moves from `DEFERRED` to `APPROVED_FOR_AMORTIZATION` and its AmortizationEntry rows are generated — one row per period, `period_index` running from 1 through `amortization_months` ascending, each row in `PENDING`, amounts per the amortization schedule below — while each unlisted `DEFERRED` asset moves to `DISALLOWED`. Finally the case moves to `DECIDED`.

The amortization schedule of a RegulatoryAsset is pinned. The asset is created (while the case is in `DRAFT` or `DEFICIENT`) with `rate_case_id`, `asset_name`, `principal_cents` (strictly greater than zero), `incurrence_start`, `incurrence_end` (a closed window: `incurrence_end` must be greater than or equal to `incurrence_start`, otherwise `ERR_INVALID_DATE_RANGE`; and the window must not intersect the case's test year — a single shared day counts as intersection, otherwise `ERR_DEFERRAL_OVERLAPS_TEST_YEAR`), and `amortization_months` (strictly greater than zero). At creation the server computes `monthly_base_cents` as the floor of `principal_cents` divided by `amortization_months`, and `final_month_cents` as `principal_cents` minus `monthly_base_cents` multiplied by one less than `amortization_months`; `amortized_to_date_cents` initializes to zero and the asset enters `DEFERRED`. The rounding remainder is absorbed entirely by the last installment — the schedule floors each base installment and pushes the remainder to the tail, rather than rounding each installment independently. The invariant is that the sum of all generated `amount_cents` equals `principal_cents` exactly. Each generated entry has `amount_cents` equal to `monthly_base_cents` for every `period_index` less than `amortization_months`, and equal to `final_month_cents` for the final `period_index`; the entry's `regulatory_asset_id` references the owning asset and `rate_case_id` is denormalized onto each entry from that asset for filtering, and `posted_at` is null until posted.

Rate implementation, performed by the utility while the case is `DECIDED` (the case-phase guard, `ERR_INVALID_CASE_STATE`, runs first), requires every CustomerClass of the case to have at least one tariff in `APPROVED` — otherwise `ERR_CLASS_TARIFF_MISSING`. On success every `APPROVED` tariff moves to `EFFECTIVE`, every `APPROVED_FOR_AMORTIZATION` asset moves to `AMORTIZING`, and the case moves to `RATES_IMPLEMENTED`.

Posting and reversal of amortization installments are utility actions with strict ordering. Posting requires the entry in `PENDING` (`ERR_INVALID_AMORT_ENTRY_STATE`), the owning asset in `AMORTIZING` (`ERR_INVALID_ASSET_STATE`), and the entry's `period_index` equal to the minimum `period_index` among the asset's `PENDING` entries — posting out of order is `ERR_AMORTIZATION_OUT_OF_ORDER`. A successful post stamps `posted_at`, moves the entry to `POSTED`, adds the entry's `amount_cents` to the asset's `amortized_to_date_cents`, and if no `PENDING` entries remain the asset bubbles up to `FULLY_AMORTIZED`. Reversal is LIFO: the entry must be in `POSTED`, the asset in `AMORTIZING` or `FULLY_AMORTIZED`, and the entry's `period_index` equal to the maximum `period_index` among the asset's `POSTED` entries — otherwise `ERR_REVERSAL_NOT_LATEST`. A successful reversal moves the entry to `REVERSED`, subtracts its `amount_cents` from `amortized_to_date_cents`, and if the asset was `FULLY_AMORTIZED` returns it to `AMORTIZING`.

### 3.7. Customer Classes, Cost Allocation, and Tariff Rate Design

The utility defines each CustomerClass while the case is in `DRAFT` or `DEFICIENT` with `rate_case_id`, `class_code` (unique within the case — a duplicate is `ERR_CLASS_CODE_NOT_UNIQUE`), and the billing determinants: `customer_count` (average customers in the test year, strictly greater than zero), `monthly_kwh_per_customer` (strictly greater than zero), `annual_kwh` (the class's annual energy, strictly greater than zero, an informational consistency anchor), `coincident_peak_kw` (class contribution to system coincident peak, strictly greater than zero), `average_demand_kw` (strictly greater than zero), `present_customer_charge_cents` (the present monthly customer charge per customer, greater than or equal to zero), and `present_tiers` (the present marginal energy tiers as an ascending array of objects each with `up_to_kwh` and `rate_mills`, where exactly one terminal tier has `up_to_kwh` null and `rate_mills` is thousandths of a dollar per kWh). Tier arrays — here and on TariffRate — are validated strictly as request shape: the array is non-empty; each tier object carries exactly the keys `up_to_kwh` and `rate_mills`; every non-terminal `up_to_kwh` is a positive integer and the caps are strictly ascending; `rate_mills` is a non-negative integer; and the null-`up_to_kwh` tier must be the last element — any violation is `ERR_INVALID_REQUEST`. On creation the server computes `present_revenue_cents` and `allocated_cost_cents`, and refreshes the case's `present_revenue_total_cents` as the sum of `present_revenue_cents` over all classes of the case. Creating a class also recomputes and persists `allocated_cost_cents` for every class of the case (the new class included) under the case's `allocation_method`; the stored values are not revisited on later entry, adjustment, or item mutations. `approved_revenue_cents` is null until the issue-order cascade sets it.

Tiered marginal energy pricing is the shared primitive behind both present and proposed revenue. Given a monthly usage in kWh and an ascending tier array, walk the tiers in ascending `up_to_kwh` order with the null-`up_to_kwh` terminal tier last and of infinite width, maintaining a running floor starting at zero. Each tier's width is: for the terminal null tier, the usage minus the floor; for any other tier, the larger of zero and the smaller of the usage and that tier's `up_to_kwh`, minus the floor. Each tier contributes its width multiplied by its `rate_mills`, divided by 100 (converting mills to cents per kWh); the per-tier product is rounded half up to integer cents before summation across tiers, and the outer expression is then exact integer arithmetic. After each non-terminal tier, the floor advances to that tier's `up_to_kwh`, and the walk stops once the floor reaches the usage.

A class's `present_revenue_cents` is twelve times `customer_count`, multiplied by the sum of `present_customer_charge_cents` and the tiered-marginal energy charge for `monthly_kwh_per_customer` under `present_tiers`.

Class cost allocation splits the case's cost of service across classes. The cost-of-service total is the sum of `adjusted_amount_cents` over the case's TestYearEntries in `LOCKED` status across the `O_AND_M`, `DEPRECIATION`, and `TAXES` categories — `DRAFT` and `SUBMITTED` entries are excluded. Each class's allocated cost is the sum of three components, each rounded half up to integer cents before summation: a demand component equal to the cost-of-service total times 60% times the class's demand share, an energy component equal to the cost-of-service total times 25% times the class's energy share, and a customer component equal to the cost-of-service total times 15% times the class's customer share. The demand share depends on the case's `allocation_method`: under `COINCIDENT_PEAK` the share is the class's `coincident_peak_kw` over the sum of `coincident_peak_kw` across all classes; under `ENERGY_AVERAGE` the share is the class's `annual_kwh` over the sum of `annual_kwh` across all classes. The energy share is always `annual_kwh` over the all-class sum, and the customer share is `customer_count` over the all-class sum. After per-class pre-residual allocations are computed, a residual equal to the cost-of-service total minus the sum of pre-residual allocations is assigned in full (whether positive or negative) to the class with the largest pre-residual allocation; ties break by larger `customer_count`, then by earlier `created_at`. The chosen class's `allocated_cost_cents` absorbs the residual; every other class's `allocated_cost_cents` equals its pre-residual sum.

A TariffRate is the utility's proposed rate design for one class, creatable while the case is in `DISCOVERY`, `HEARING`, or `SETTLEMENT` (`ERR_INVALID_CASE_STATE` otherwise). The payload carries `rate_case_id`, `customer_class_id` (which must reference a class of the same case — otherwise `ERR_CLASS_NOT_IN_CASE`), `label`, `proposed_customer_charge_cents` (greater than or equal to zero), `proposed_tiers` (the same ascending shape as `present_tiers`, exactly one terminal null `up_to_kwh`), `effective_start`, and an optional `effective_end`. The effective window is half-open — `effective_start` inclusive, `effective_end` exclusive — with a null `effective_end` meaning open-ended; when present, `effective_end` must be strictly after `effective_start` (`ERR_INVALID_DATE_RANGE`). The window must not overlap another non-`REJECTED` tariff of the same class under half-open semantics — adjacency is allowed and a null end is infinity; an overlap is `ERR_TARIFF_WINDOW_OVERLAP`. On creation the server computes `proposed_revenue_cents` as twelve times the class's `customer_count`, multiplied by the sum of `proposed_customer_charge_cents` and the tiered-marginal charge for `monthly_kwh_per_customer` under `proposed_tiers`; the tariff enters `PROPOSED`.

Two price-integrity guards run at tariff creation, in the validation order fixed by §2.9. The anti-subsidy floor requires the tariff's `proposed_revenue_cents` to be at least the class's customer-cost component — that is, the cost-of-service total times 15% times the class's customer share, rounded half up — computed at tariff-create time; a tariff below the floor is `ERR_BELOW_CUSTOMER_COST_FLOOR`. The gradualism cap constrains per-class rate shock: first compute `present_total` as the sum of `present_revenue_cents` over all classes of the case, then the system-average increase in basis points as the round-half-up of ten thousand times the case's `proposed_revenue_requirement_cents` minus `present_total`, divided by `present_total`. If the system-average increase is less than or equal to zero — a revenue-decreasing case — the cap check is skipped entirely. The check is likewise skipped when `present_total` is zero (the system average cannot be computed) and, for the class at hand, when the class's `present_revenue_cents` is zero (the class increase cannot be computed). Otherwise the cap in basis points is the round-half-up of one and a half times the system-average increase, and the class increase in basis points is the round-half-up of ten thousand times the tariff's `proposed_revenue_cents` minus the class's `present_revenue_cents`, divided by the class's `present_revenue_cents`. The tariff is rejected with `ERR_GRADUALISM_CAP_EXCEEDED` only when the class increase is strictly greater than the cap; an increase exactly equal to the cap passes. The two rounding steps are pinned in order: system average first, then the cap.

The tariff-supersede sweep runs each time the logical clock advances. For each CustomerClass, consider its tariffs in `EFFECTIVE`: the current tariff is the one with the latest `effective_start` that is less than or equal to the new clock (a tie is impossible, because overlapping windows for the same class are rejected at create). Every other `EFFECTIVE` tariff of the class whose `effective_start` is strictly before that latest `effective_start` moves to `SUPERSEDED`. A tariff whose window has simply ended — `effective_end` at or before the new clock — with no later-starting `EFFECTIVE` successor stays `EFFECTIVE`; supersession is driven only by a later-starting successor, never by window expiry.

### 3.8. Revenue-Requirement Reporting, Bill Impact, and True-Up Compliance

The revenue requirement is reported under two variants that differ only in their rate-base input set. The as-filed variant — the filing-time view used by submit-filing validation — includes RateBaseItems in `SUBMITTED` or `AUDITED`. The as-audited variant — the post-audit view used at order drafting — includes RateBaseItems in `AUDITED` only, excluding `SUBMITTED` and `EXCEPTION` items. In both variants the evaluation order is pinned, breaking the apparent circularity that the return component is a percentage of a base that audit status changes: first compute the cost of service (over `LOCKED` entries, as in §3.7); second compute the rate-base total as the sum of `net_rate_base_cents` over the variant's input set; third compute the return component as the rate-base total multiplied by `return_on_rate_base_bp` and divided by ten thousand, rounded half up to integer cents — the return is rounded before addition; fourth, the revenue requirement is the cost of service plus the rounded return. The first two steps are both evaluated before the third; no term feeds back. The computed read for revenue requirement accepts an optional `variant` parameter (default `as_filed`; an unrecognized value is `ERR_INVALID_REQUEST`, checked before authorization) and returns `variant`, `rate_base_cents`, `cost_of_service_cents`, `return_cents`, and `revenue_requirement_cents`. The case mirrors the two computed figures as `revenue_requirement_as_filed_cents` and `revenue_requirement_as_audited_cents`.

The computed read for cost allocation accepts an optional `method` parameter (defaulting to the case's `allocation_method`, so an `ENERGY_AVERAGE` override may be requested on a `COINCIDENT_PEAK` case and vice versa; an unrecognized value is `ERR_INVALID_REQUEST`, checked after authorization and case loading) and returns the `method`, the `cost_of_service_cents` total, the `residual_cents`, and per-class `lines`, each carrying `class_id`, `class_code`, `demand_component_cents`, `energy_component_cents`, `customer_component_cents`, and the final `allocated_cost_cents` after residual assignment. When the case has no classes, `lines` is empty and `residual_cents` (equal to the cost-of-service total) is reported but assigned to no class.

The bill-impact read prices one month's bill for a class under present rates versus a selected tariff. Required inputs are `customer_class_id` (which must reference a class of the addressed case — otherwise `ERR_CLASS_NOT_IN_CASE`) and `monthly_kwh`, which must be a non-negative integer (otherwise `ERR_INVALID_REQUEST`); an optional `tariff_id` selects the proposed leg explicitly. An unknown `customer_class_id` is `ERR_CLASS_NOT_FOUND`, checked before any tariff lookup; an explicit `tariff_id` is used as-is — no class or case membership check is applied to it — but an unknown one is `ERR_TARIFF_NOT_FOUND`, checked after class existence and before the class-in-case check. When `tariff_id` is omitted, the selection rule picks the class's tariff in `EFFECTIVE`; if several, the one with the latest `effective_start`; if none, the most recently created `PROPOSED` tariff of the class by `created_at` descending; if none, the read is rejected with `ERR_TARIFF_NOT_FOUND`. The present bill is the class's `present_customer_charge_cents` plus the tiered-marginal charge for `monthly_kwh` under `present_tiers`. The proposed bill is the selected tariff's `proposed_customer_charge_cents` plus the tiered-marginal charge for `monthly_kwh` under `proposed_tiers`. The impact in basis points is the round-half-up of ten thousand times the difference of proposed minus present bill, divided by the present bill; a present bill of zero is `ERR_INVALID_REQUEST`. The response carries `present_bill_cents`, `proposed_bill_cents`, and `impact_pct_bp`.

Once rates are implemented, staff begins compliance monitoring, moving the case from `RATES_IMPLEMENTED` to `COMPLIANCE_MONITORING`. In that phase the utility opens a ComplianceFiling with `rate_case_id`, `period_label` (for example `RATE_YEAR_1`), `actual_revenue_by_class` (an array of per-class actuals, each with `class_code` and `actual_revenue_cents` — the latter may be any integer — covering every CustomerClass of the case exactly once — otherwise `ERR_INCOMPLETE_CLASS_REVENUE`), and the OCC field `expected_rate_case_version`. The new filing supersedes the case's existing filing in `DRAFT` or `REMANDED` (the superseded filing moves to `SUPERSEDED` and the new filing's `supersedes_filing_id` is set to the superseded filing's `id`; null for the case's first filing); an existing filing in `SUBMITTED` or `ACCEPTED` blocks the new filing with `ERR_FILING_NOT_SUPERSEDABLE`. At creation the server computes `actual_total_revenue_cents` as the sum of `actual_revenue_cents` over the per-class lines, the filing enters `DRAFT` with `true_up_delta_cents`, `true_up_action`, and `class_true_up_lines` null until submission, and the create increments the case's `version`.

Submitting a `DRAFT` filing (filing not in `DRAFT` is `ERR_INVALID_FILING_STATE`, checked first; the case must then be in `COMPLIANCE_MONITORING`, otherwise `ERR_INVALID_CASE_STATE`) freezes the true-up computation. The evaluation order is pinned so that prior-period rider effects never feed the current delta: the delta is computed from raw actuals only. First, `actual_total` is the sum of `actual_revenue_cents` across `actual_revenue_by_class`. Second, `true_up_delta_cents` is `actual_total` minus the case's `authorized_revenue_requirement_cents`; a positive delta is over-collection (a refund owed to customers), a negative delta is under-collection (a surcharge owed to the utility). Third, the de-minimis threshold is the larger of 100000 cents and the round-half-up of the authorized revenue requirement times 0.005. Fourth, `true_up_action` is `NONE` when the absolute value of the delta is less than or equal to the threshold — a delta exactly equal to the threshold is `NONE`, since the trigger is strictly-greater — otherwise `REFUND` when the delta is positive and `SURCHARGE` when it is negative. Fifth, per-class true-up lines are computed even when the action is `NONE`, for transparency: each line is the round-half-away-from-zero of the delta times that class's `actual_revenue_cents` divided by `actual_total` (when `actual_total` is zero every line is zero), and the residual — the delta minus the sum of lines — is assigned to the class with the largest `actual_revenue_cents`, ties broken by `class_code` ascending. These lines are stored as `class_true_up_lines`, an array of objects each with `class_code` and `line_cents`, emitted in the order of `actual_revenue_by_class`.

Staff review of a `SUBMITTED` filing takes an `outcome`: `ACCEPT` moves it to `ACCEPTED`; `REMAND` moves it to `REMANDED` and requires a non-empty `remand_notes` — otherwise `ERR_REMAND_NOTES_REQUIRED`. A `remand_notes` supplied with `ACCEPT` is accepted and ignored; the notes are not persisted on the filing in either branch. A `DRAFT` or `REMANDED` filing is superseded by a newly created filing as described above; `ACCEPTED` and `SUPERSEDED` are terminal. The ALJ closes the docket from `COMPLIANCE_MONITORING` (the case-phase guard, `ERR_INVALID_CASE_STATE`, runs first) once at least one ComplianceFiling of the case is `ACCEPTED` — otherwise `ERR_NO_ACCEPTED_FILING` — moving the case to `CLOSED`, its terminal state.

### 3.9. Party Registration and Withdrawal Cascade

An `IntervenorRep` self-registers a party on a case by creating an Intervenor with `rate_case_id`, `party_name`, `representative_name`, and `contact_email` (the service-list email); registration is accepted in any case phase — there is no case-state guard. The response `id` is the party's identity — the value the representative will present as `X-User-ID` on subsequent calls. A new party enters `PARTY`.

Withdrawal is available to the party's own representative (whose `X-User-ID` must equal the Intervenor `id`, otherwise `ERR_FORBIDDEN_OWNERSHIP`) or to `CommissionStaff`, and requires the party in `PARTY` (otherwise `ERR_INVALID_INTERVENOR_STATE`). The cascade runs in hops: first the party moves to `WITHDRAWN`; second, every DataRequest whose `issuing_intervenor_id` is this party and whose status is `ISSUED`, `OBJECTED`, `RESPOND_REQUIRED`, or `OVERDUE` moves to `WITHDRAWN`; third, each hop-2 withdrawal out of `OVERDUE` decrements the owning case's `overdue_data_request_count`; and fourth, every SettlementSignatory whose `intervenor_id` is this party and whose status is `PENDING` moves to `VOID`, with each affected proposal recomputing `signature_count` and `required_signature_count` with `VOID` rows excluded from both. `WITHDRAWN` is terminal for a party.

## 4. Endpoint Definitions

All endpoints return the standard envelope of §2.2. New resources are returned with HTTP 201; state transitions and modifications of existing resources return HTTP 200. Unless §3 describes a payload for the endpoint, action and transition endpoints take no request fields — any supplied field is `ERR_INVALID_REQUEST`. Every request body must be a JSON object: a missing body is treated as an empty object, and a non-object body is `ERR_INVALID_REQUEST`. The table below is a summary only — request payloads, response fields, and cascades are specified by the narratives in §3.

| Method | Path | Description | Authorized Role(s) |
|--------|------|-------------|--------------------|
| POST | /api/v1/rate-cases | Open a new rate case docket (status DRAFT) | UtilityFiler |
| GET | /api/v1/rate-cases | List rate cases, paginated | UtilityFiler, CommissionStaff, IntervenorRep, ALJ |
| GET | /api/v1/rate-cases/{caseId} | Read one rate case | UtilityFiler, CommissionStaff, IntervenorRep, ALJ |
| POST | /api/v1/rate-cases/{caseId}/submit-filing | Submit the filing (DRAFT or DEFICIENT -> FILED); cascades VERIFIED adjustments to ACCEPTED | UtilityFiler |
| POST | /api/v1/rate-cases/{caseId}/deficiency-review | Commission staff sufficiency review: outcome ACCEPTED -> ACCEPTED, DEFICIENT -> DEFICIENT (notes required) | CommissionStaff |
| POST | /api/v1/rate-cases/{caseId}/open-discovery | Open the discovery window; sets discovery_close_at = clock + 120 days | CommissionStaff |
| POST | /api/v1/rate-cases/{caseId}/advance-to-hearing | Close discovery and move to hearing; requires zero OVERDUE data requests | ALJ |
| POST | /api/v1/rate-cases/{caseId}/open-settlement-window | Open the settlement negotiation window | ALJ |
| POST | /api/v1/rate-cases/{caseId}/advance-to-order-pending | Certify the record; requires at least one RECOMMENDED settlement proposal | ALJ |
| POST | /api/v1/rate-cases/{caseId}/issue-order | Issue the final order: adopts the RECOMMENDED proposal, approves/rejects tariffs, approves/disallows regulatory assets and generates amortization schedules | ALJ |
| POST | /api/v1/rate-cases/{caseId}/implement-rates | Put approved rates into effect and start amortization | UtilityFiler |
| POST | /api/v1/rate-cases/{caseId}/begin-compliance-monitoring | Enter compliance monitoring phase | CommissionStaff |
| POST | /api/v1/rate-cases/{caseId}/close | Close the docket; requires at least one ACCEPTED compliance filing | ALJ |
| GET | /api/v1/rate-cases/{caseId}/revenue-requirement | Computed read: revenue requirement breakdown under the requested variant (default as_filed) | UtilityFiler, CommissionStaff, IntervenorRep, ALJ |
| GET | /api/v1/rate-cases/{caseId}/cost-allocation | Computed read: class cost-of-service allocation under the requested method (default case.allocation_method) | UtilityFiler, CommissionStaff, IntervenorRep, ALJ |
| GET | /api/v1/rate-cases/{caseId}/bill-impact | Computed read: monthly bill for a class under present rates vs a selected tariff | UtilityFiler, CommissionStaff, IntervenorRep, ALJ |
| POST | /api/v1/intervenors | Register an intervenor party on a case; the response id is the party's IntervenorRep identity | IntervenorRep |
| GET | /api/v1/intervenors | List intervenors; filterable by rate_case_id and status | UtilityFiler, CommissionStaff, IntervenorRep, ALJ |
| GET | /api/v1/intervenors/{intervenorId} | Read one intervenor | UtilityFiler, CommissionStaff, IntervenorRep, ALJ |
| POST | /api/v1/intervenors/{intervenorId}/withdraw | Withdraw a party; cascades its open data requests to WITHDRAWN and its PENDING signatories to VOID | IntervenorRep, CommissionStaff |
| POST | /api/v1/test-year-entries | Add a booked test-year line (case must be DRAFT or DEFICIENT) | UtilityFiler |
| GET | /api/v1/test-year-entries | List test-year entries; filterable by rate_case_id and status | UtilityFiler, CommissionStaff, IntervenorRep, ALJ |
| GET | /api/v1/test-year-entries/{entryId} | Read one test-year entry | UtilityFiler, CommissionStaff, IntervenorRep, ALJ |
| POST | /api/v1/test-year-entries/{entryId}/submit | Submit an entry for review (DRAFT -> SUBMITTED) | UtilityFiler |
| POST | /api/v1/test-year-entries/{entryId}/reopen | Reopen a submitted entry (SUBMITTED -> DRAFT) while the case is editable | UtilityFiler |
| POST | /api/v1/test-year-entries/{entryId}/lock | Lock an entry (SUBMITTED -> LOCKED); requires no DISPUTED adjustments on the entry | UtilityFiler |
| POST | /api/v1/adjustments | Propose a known-and-measurable adjustment against an entry in DRAFT or SUBMITTED | UtilityFiler |
| GET | /api/v1/adjustments | List adjustments; filterable by rate_case_id, test_year_entry_id, status | UtilityFiler, CommissionStaff, IntervenorRep, ALJ |
| GET | /api/v1/adjustments/{adjustmentId} | Read one adjustment | UtilityFiler, CommissionStaff, IntervenorRep, ALJ |
| POST | /api/v1/adjustments/{adjustmentId}/verify | Verify a PROPOSED or DISPUTED adjustment; verifier must differ from proposer | UtilityFiler |
| POST | /api/v1/adjustments/{adjustmentId}/withdraw | Withdraw a PROPOSED or DISPUTED adjustment (proposer only) | UtilityFiler |
| POST | /api/v1/adjustments/{adjustmentId}/dispute | Dispute a VERIFIED adjustment (staff or any intervenor party) | CommissionStaff, IntervenorRep |
| POST | /api/v1/adjustments/{adjustmentId}/reject | Reject a VERIFIED or DISPUTED adjustment | CommissionStaff |
| POST | /api/v1/rate-base-items | Add a rate-base item (case DRAFT or DEFICIENT) | UtilityFiler |
| GET | /api/v1/rate-base-items | List rate-base items; filterable by rate_case_id and status | UtilityFiler, CommissionStaff, IntervenorRep, ALJ |
| GET | /api/v1/rate-base-items/{itemId} | Read one rate-base item | UtilityFiler, CommissionStaff, IntervenorRep, ALJ |
| POST | /api/v1/rate-base-items/{itemId}/submit | Submit a DRAFT item for audit | UtilityFiler |
| POST | /api/v1/rate-base-items/{itemId}/audit | Staff audit: outcome AUDIT_PASS -> AUDITED, AUDIT_EXCEPTION -> EXCEPTION | CommissionStaff |
| POST | /api/v1/rate-base-items/{itemId}/revise | Revise an EXCEPTION item's amounts (EXCEPTION -> SUBMITTED) | UtilityFiler |
| POST | /api/v1/customer-classes | Define a customer class with billing determinants and present rate structure (case DRAFT or DEFICIENT) | UtilityFiler |
| GET | /api/v1/customer-classes | List customer classes; filterable by rate_case_id | UtilityFiler, CommissionStaff, IntervenorRep, ALJ |
| GET | /api/v1/customer-classes/{classId} | Read one customer class | UtilityFiler, CommissionStaff, IntervenorRep, ALJ |
| POST | /api/v1/data-requests | Issue a data request (case in DISCOVERY, within the discovery window); IntervenorRep callers must pass issuing_intervenor_id equal to their X-User-ID; CommissionStaff callers must omit it | IntervenorRep, CommissionStaff |
| GET | /api/v1/data-requests | List data requests; filterable by rate_case_id, issuing_intervenor_id, referenced_adjustment_id, status | UtilityFiler, CommissionStaff, IntervenorRep, ALJ |
| GET | /api/v1/data-requests/{requestId} | Read one data request | UtilityFiler, CommissionStaff, IntervenorRep, ALJ |
| POST | /api/v1/data-requests/{requestId}/respond | Utility responds (from ISSUED, OVERDUE, or RESPOND_REQUIRED) | UtilityFiler |
| POST | /api/v1/data-requests/{requestId}/object | Utility objects instead of responding (from ISSUED only) | UtilityFiler |
| POST | /api/v1/data-requests/{requestId}/rule | ALJ rules on an objection: SUSTAINED -> CLOSED; OVERRULED -> RESPOND_REQUIRED with extended_due_at = clock + 5 days | ALJ |
| POST | /api/v1/data-requests/{requestId}/withdraw | Issuing party withdraws an open request | IntervenorRep, CommissionStaff |
| POST | /api/v1/settlement-proposals | Open a new settlement round (case must be in SETTLEMENT); supersedes the case's existing DRAFT or UNDER_NEGOTIATION proposal; OCC-guarded on the case version | UtilityFiler |
| GET | /api/v1/settlement-proposals | List settlement proposals; filterable by rate_case_id and status | UtilityFiler, CommissionStaff, IntervenorRep, ALJ |
| GET | /api/v1/settlement-proposals/{proposalId} | Read one settlement proposal | UtilityFiler, CommissionStaff, IntervenorRep, ALJ |
| POST | /api/v1/settlement-proposals/{proposalId}/circulate | Circulate a DRAFT proposal to all PARTY intervenors; generates PENDING signatory rows | UtilityFiler |
| POST | /api/v1/settlement-proposals/{proposalId}/recommend | ALJ recommends an ASSENTED proposal to the commission | ALJ |
| POST | /api/v1/settlement-proposals/{proposalId}/remand | ALJ remands an ASSENTED proposal (terminal; remedy is a new round) | ALJ |
| GET | /api/v1/settlement-signatories | List signatory rows; filterable by settlement_proposal_id, intervenor_id, status | UtilityFiler, CommissionStaff, IntervenorRep, ALJ |
| GET | /api/v1/settlement-signatories/{signatoryId} | Read one signatory row | UtilityFiler, CommissionStaff, IntervenorRep, ALJ |
| POST | /api/v1/settlement-signatories/{signatoryId}/sign | Sign a PENDING signatory row (owning intervenor's rep only); bubbles the proposal to ASSENTED on unanimity | IntervenorRep |
| POST | /api/v1/settlement-signatories/{signatoryId}/decline | Decline a PENDING signatory row (owning intervenor's rep only); terminal | IntervenorRep |
| POST | /api/v1/settlement-signatories/{signatoryId}/rescind | Rescind a SIGNED row while the proposal is UNDER_NEGOTIATION or ASSENTED; drops an ASSENTED proposal back to UNDER_NEGOTIATION | IntervenorRep |
| POST | /api/v1/regulatory-assets | Register a deferred regulatory asset (case DRAFT or DEFICIENT); closed incurrence window must not intersect the test year | UtilityFiler |
| GET | /api/v1/regulatory-assets | List regulatory assets; filterable by rate_case_id and status | UtilityFiler, CommissionStaff, IntervenorRep, ALJ |
| GET | /api/v1/regulatory-assets/{assetId} | Read one regulatory asset | UtilityFiler, CommissionStaff, IntervenorRep, ALJ |
| GET | /api/v1/amortization-entries | List amortization entries; filterable by regulatory_asset_id, rate_case_id, status | UtilityFiler, CommissionStaff, IntervenorRep, ALJ |
| GET | /api/v1/amortization-entries/{entryId} | Read one amortization entry | UtilityFiler, CommissionStaff, IntervenorRep, ALJ |
| POST | /api/v1/amortization-entries/{entryId}/post | Post the earliest PENDING installment of an AMORTIZING asset | UtilityFiler |
| POST | /api/v1/amortization-entries/{entryId}/reverse | Reverse the latest POSTED installment (LIFO) of an AMORTIZING or FULLY_AMORTIZED asset | UtilityFiler |
| POST | /api/v1/tariff-rates | Propose a tariff schedule for a class (case in DISCOVERY, HEARING, or SETTLEMENT); half-open effective window must not overlap a same-class non-REJECTED tariff; anti-subsidy floor and gradualism cap enforced | UtilityFiler |
| GET | /api/v1/tariff-rates | List tariff rates; filterable by rate_case_id, customer_class_id, status | UtilityFiler, CommissionStaff, IntervenorRep, ALJ |
| GET | /api/v1/tariff-rates/{tariffId} | Read one tariff rate | UtilityFiler, CommissionStaff, IntervenorRep, ALJ |
| POST | /api/v1/compliance-filings | Open a compliance filing (case in COMPLIANCE_MONITORING); supersedes the case's existing DRAFT or REMANDED filing; OCC-guarded on the case version | UtilityFiler |
| GET | /api/v1/compliance-filings | List compliance filings; filterable by rate_case_id, status, and supersedes_filing_id | UtilityFiler, CommissionStaff, IntervenorRep, ALJ |
| GET | /api/v1/compliance-filings/{filingId} | Read one compliance filing | UtilityFiler, CommissionStaff, IntervenorRep, ALJ |
| POST | /api/v1/compliance-filings/{filingId}/submit | Submit a DRAFT filing; freezes the true-up computation | UtilityFiler |
| POST | /api/v1/compliance-filings/{filingId}/review | Staff review: outcome ACCEPT -> ACCEPTED, REMAND -> REMANDED (notes required) | CommissionStaff |
| POST | /_clock/set_current_utc | Test-driving endpoint: set the server's logical clock (ISO8601 UTC); forward-only; runs the discovery-overdue and tariff-supersede sweeps | CommissionStaff |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the §2 and §3 narratives; this table enumerates only the identifier-to-status mapping. A request matching no defined route — or an undefined method on a defined route — is rejected with `ERR_NOT_FOUND` (HTTP 404).

| Error ID | HTTP Status Code |
|----------|------------------|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_DATE_RANGE | 400 |
| ERR_DEFICIENCY_NOTES_REQUIRED | 400 |
| ERR_REMAND_NOTES_REQUIRED | 400 |
| ERR_INSUFFICIENT_PERMISSIONS | 403 |
| ERR_FORBIDDEN_OWNERSHIP | 403 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_STALE_VERSION | 412 |
| ERR_RATE_CASE_NOT_FOUND | 404 |
| ERR_INTERVENOR_NOT_FOUND | 404 |
| ERR_ENTRY_NOT_FOUND | 404 |
| ERR_ADJUSTMENT_NOT_FOUND | 404 |
| ERR_ITEM_NOT_FOUND | 404 |
| ERR_CLASS_NOT_FOUND | 404 |
| ERR_DATA_REQUEST_NOT_FOUND | 404 |
| ERR_PROPOSAL_NOT_FOUND | 404 |
| ERR_SIGNATORY_NOT_FOUND | 404 |
| ERR_ASSET_NOT_FOUND | 404 |
| ERR_AMORT_ENTRY_NOT_FOUND | 404 |
| ERR_TARIFF_NOT_FOUND | 404 |
| ERR_FILING_NOT_FOUND | 404 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_CASE_STATE | 409 |
| ERR_INVALID_ENTRY_STATE | 409 |
| ERR_INVALID_ADJUSTMENT_STATE | 409 |
| ERR_INVALID_ITEM_STATE | 409 |
| ERR_INVALID_REQUEST_STATE | 409 |
| ERR_INVALID_PROPOSAL_STATE | 409 |
| ERR_INVALID_SIGNATORY_STATE | 409 |
| ERR_INVALID_ASSET_STATE | 409 |
| ERR_INVALID_AMORT_ENTRY_STATE | 409 |
| ERR_INVALID_TARIFF_STATE | 409 |
| ERR_INVALID_FILING_STATE | 409 |
| ERR_INVALID_INTERVENOR_STATE | 409 |
| ERR_NO_TEST_YEAR_ENTRIES | 409 |
| ERR_ENTRIES_NOT_LOCKED | 409 |
| ERR_UNRESOLVED_ENTRY_ADJUSTMENTS | 409 |
| ERR_UNRESOLVED_ADJUSTMENTS | 409 |
| ERR_NO_RATE_BASE_ITEMS | 409 |
| ERR_OVERDUE_DATA_REQUESTS_EXIST | 409 |
| ERR_NO_RECOMMENDED_SETTLEMENT | 409 |
| ERR_CLASS_TARIFF_MISSING | 409 |
| ERR_NO_ACCEPTED_FILING | 409 |
| ERR_PROPOSAL_NOT_SUPERSEDABLE | 409 |
| ERR_FILING_NOT_SUPERSEDABLE | 409 |
| ERR_BELOW_CUSTOMER_COST_FLOOR | 422 |
| ERR_DISCOVERY_WINDOW_CLOSED | 409 |
| ERR_TARIFF_WINDOW_OVERLAP | 409 |
| ERR_DEFERRAL_OVERLAPS_TEST_YEAR | 409 |
| ERR_CLOCK_REGRESSION | 409 |
| ERR_ADJUSTMENT_NOT_IN_CASE | 422 |
| ERR_CLASS_NOT_IN_CASE | 422 |
| ERR_PARTY_NOT_IN_CASE | 422 |
| ERR_INCOMPLETE_CLASS_REVENUE | 422 |
| ERR_CASE_NUMBER_NOT_UNIQUE | 422 |
| ERR_CLASS_CODE_NOT_UNIQUE | 422 |
| ERR_AMORTIZATION_OUT_OF_ORDER | 422 |
| ERR_REVERSAL_NOT_LATEST | 422 |
| ERR_GRADUALISM_CAP_EXCEEDED | 422 |
| ERR_RR_MISMATCH | 422 |
| ERR_NONPOSITIVE_REVENUE_REQUIREMENT | 422 |
| ERR_SETTLEMENT_ABOVE_FILED | 422 |
