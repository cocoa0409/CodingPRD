# Analyst Research Entitlements API — Product Requirements Document

## 1. Introduction

Research subscribers do not buy documents; they buy access to analysts. A client organization signs a term contract that pays for a fixed number of seats and a pool of inquiry units, and every seat it provisions carries a role-based entitlement to a defined set of research artefact classes. This document specifies the API that governs that commercial relationship end to end: contract and seat administration, the inquiry allowance ledger, analyst routing and scheduling, research authoring and publication, comparative vendor evaluation, vendor briefings, and the conference programming that sits at the boundary between research and sponsorship revenue.

The API must also protect something harder to price: research independence. An analyst may not brief, evaluate or fact-check a vendor that pays them; the sales organization may never move research status; a document's author may never serve as its own peer reviewer. Every commercial tie is therefore registered, screened and audited, and every placement decision is frozen at publication so that a later commercial entanglement cannot silently rewrite a published evaluation. The same discipline governs time itself: all deadlines, embargoes, renewal windows and capacity rules are evaluated against a single logical clock that the platform advances explicitly, never against wall-clock time, so that every time-dependent rule in this specification is deterministic and reproducible.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules that apply to every resource in the API. The API is mounted under the `/research` prefix; the only operation outside that prefix is the logical-clock control endpoint described in §2.4.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the capacity in which that user acts. The single exception is the logical-clock control operation described in §2.4, which is not authenticated. A request that omits either header is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose `X-User-Role` value is not listed among the roles authorized for the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403). The endpoint table in §4 is the authoritative statement of which roles may call which operation.

The platform recognizes nine roles, spelled exactly as follows: `PlatformAdmin`, `ClientAdmin`, `SeatHolder`, `Analyst`, `ResearchDirector`, `ComplianceOfficer`, `VendorRep`, `EventProgrammer` and `SalesRep`.

`PlatformAdmin` operates the research platform: it seeds reference data, drives the logical clock and performs recovery operations. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity and is never compared to any entity's `id`.

`ClientAdmin` administers a subscribing client account, managing its seats and cancelling inquiries on the account's behalf. When `X-User-Role` is `ClientAdmin`, `X-User-ID` is the `id` of the acting `ClientAccount`; ownership checks on any resource that references a `ClientAccount` compare the resource's foreign-key field to `X-User-ID`.

`SeatHolder` is the named user of a seat; it spends the account's inquiry allowance and reads research under the seat's entitlements. When `X-User-Role` is `SeatHolder`, `X-User-ID` is the `id` of the acting `Seat`; ownership checks on any resource that references a `Seat` compare the resource's foreign-key field to `X-User-ID`.

`Analyst` runs inquiries, authors documents, peer reviews and briefs vendors. When `X-User-Role` is `Analyst`, `X-User-ID` is the `id` of the acting `Analyst`; ownership checks on any resource that references an `Analyst` compare the resource's foreign-key field to `X-User-ID`.

`ResearchDirector` owns methodology governance: it approves publication, decides appeals and finalizes placements. When `X-User-Role` is `ResearchDirector`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity and is never compared to any entity's `id`.

`ComplianceOfficer` owns the sales/research separation register and audit reads. When `X-User-Role` is `ComplianceOfficer`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity and is never compared to any entity's `id`.

`VendorRep` represents a vendor: it responds to fact checks, appeals placements, buys reprints and requests briefings. When `X-User-Role` is `VendorRep`, `X-User-ID` is the `id` of the acting `Vendor`; ownership checks on any resource that references a `Vendor` compare the resource's foreign-key field to `X-User-ID`.

`EventProgrammer` owns conference programming: it builds the agenda and guards the sponsorship boundary. When `X-User-Role` is `EventProgrammer`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity and is never compared to any entity's `id`.

`SalesRep` is the commercial seller: it registers sponsorship and advisory ties but can never touch research status. When `X-User-Role` is `SalesRep`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity and is never compared to any entity's `id`.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits; it is the current reading of the logical clock of §2.4, never wall-clock time.
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

List endpoints are paginated with two query parameters. The `limit` parameter sets the maximum number of items returned in one page; it defaults to 10, must be at least 1, and must be at most 100. The `offset` parameter sets the number of items skipped before the first returned item and defaults to 0. A `limit` or `offset` outside its allowed range is clamped to the nearest bound rather than rejected, a value that is not a number falls back to that parameter's default, and the clamped values are the ones echoed in `meta`. Unless a list endpoint's description states otherwise, every list is ordered by `created_at` ascending.

Every list response carries four pagination fields inside the `meta` object of the response envelope: `limit`, `offset`, `total_count` and `has_more`. `total_count` is the number of resources matching the request's filters across all pages, and `has_more` is true when further items remain beyond the returned page. A list endpoint's filter query parameters are named after the resource fields they match — the field's own name for a scalar and `<entity>_id` for a foreign key — and a filter that is absent or empty is ignored.

### 2.4. The Logical Clock and Time-Driven Evaluation

Time in this system is a controlled input, not an ambient condition. The server maintains a logical clock whose startup default is exactly `2026-09-01T00:00:00Z`, and it never falls back to wall-clock time. Every deadline, embargo, renewal window, capacity day and late-response determination in this specification is evaluated against that logical clock.

The clock is advanced by an administrative capability exposed at the API root as `/_clock/set_current_utc` and, as an equivalent alias, under the research prefix as `/research/_clock/set_current_utc`. It accepts a single input, `current_utc`, which must parse as an ISO 8601 instant or the request is rejected with `ERR_INVALID_REQUEST` (HTTP 400), and is restricted to `PlatformAdmin`. This operation is the one request in the API that does not require the `X-User-ID` and `X-User-Role` headers: supplying neither is accepted, supplying only one of the two is rejected with `ERR_UNAUTHENTICATED` (HTTP 401), and supplying both applies the ordinary authorization rule, so a role other than `PlatformAdmin` is rejected with `ERR_UNAUTHORIZED` (HTTP 403). It returns HTTP 200. Advancing the clock does not itself rewrite resources; the time-derived conditions it affects are re-evaluated on the next read or write of the affected resource, and the server may then perform the resulting transitions without any explicit client request on that resource. A collection list read does not perform this re-evaluation and reports stored state; a single-resource read does, and it also re-evaluates the clock-driven conditions of the resources that hang off the one read — reading an account evaluates that account and its inquiries, and reading a document evaluates that document and its inclusions. The evaluations driven by the clock are: the release of a document embargo, the entry of an inquiry into `IN_PREP`, the entry of an account into `RENEWAL_REVIEW`, and the lapse of an open fact-check cycle.

Boundary semantics are pinned per rule and are not uniform, so each must be applied exactly as stated where it is defined:

- An account enters `RENEWAL_REVIEW` once the clock reading reaches `contract_end_utc` minus 90 days; the boundary is inclusive, so a clock reading of exactly that instant triggers the transition.
- An inquiry enters `IN_PREP` once the clock reading reaches its `scheduled_start_utc` minus 24 hours; this boundary is inclusive as well.
- An inquiry cancellation is free while the clock reading is at or before `scheduled_start_utc` minus 24 hours, and is late once the clock reading is strictly after that instant.
- An embargo releases once the clock reading reaches `embargo_until`; the boundary is inclusive.
- A fact-check cycle lapses once the clock reading is strictly after `fact_check_due_utc`; a vendor response landing exactly at `fact_check_due_utc` is on time.
- A conference event completes once the clock reading is strictly after its `end_utc`.
- An appeal may be filed while the clock reading is at or before `appeal_window_closes_at`.
- A requested inquiry start instant must not be strictly before the current clock reading.

### 2.5. Research Independence and the Separation Register

Research independence is enforced as a first-class system constraint rather than a policy statement. Two prohibitions are checked before any work product is created or adjudicated: the acting analyst must hold no `ACTIVE` `SalesRelationship` with the vendor in play, and a peer reviewer must differ from the document's lead analyst. On the two operations whose acting role is not an analyst — responding to a vendor fact check and finalizing a vendor inclusion — the first prohibition is read against the parent document's lead analyst, and the operation is refused while the inclusion's `lead_analyst_conflicted` flag is true. A violation of either prohibition is rejected with `ERR_SEPARATION_OF_DUTIES_VIOLATION` (HTTP 403). This check applies to exactly four operations: requesting a vendor briefing, responding to a vendor fact check, submitting a document for peer review, and finalizing a vendor inclusion.

The register of commercial ties is kept on each `Analyst` as `conflicted_vendor_ids`, the list of vendors with which the analyst holds an `ACTIVE` `SalesRelationship`, and is summarized by the analyst's `integrity_flag`. The flag is `CLEAR` while the analyst holds no active commercial tie. When one or two ties are recorded the flag becomes `CONFLICT_REVIEW`; once the analyst's conflicted vendor list holds three or more entries the flag becomes `CONFLICT_BLOCKED`. Terminating a tie removes that vendor from `conflicted_vendor_ids`; the flag falls back to `CONFLICT_REVIEW` while one or two ties remain and returns to `CLEAR` when none remain. An analyst whose flag is `CONFLICT_BLOCKED` is excluded from inquiry topic routing, and an analyst whose flag is not `CLEAR` is excluded from briefing routing. Compensating actions are not retroactive: a briefing that was already revoked by separation is never restored by terminating the relationship that caused the revocation.

### 2.6. The Inquiry Allowance Ledger

Every `ClientAccount` carries an inquiry allowance ledger, recomputed on every inquiry state change and on every read of the account. The ledger aggregates the account's inquiries into two quantities. A unit is settled, and counted as consumed, when the inquiry is `COMPLETED` or `NO_SHOW`, or when it is `CANCELLED` with `units_consumed` equal to 1 — that is, a late cancellation. A unit is reserved while the inquiry is `SCHEDULED` or `IN_PREP`. Inquiries that are `SUBMITTED` or `ROUTED`, and inquiries cancelled without charge, contribute to neither aggregate.

Two ledger remainders are exposed on the account, and neither is derived from the other. `remaining_consumed_units` equals `inquiry_allowance_total` minus the settled units; this is the CONSUMPTION variant, read by renewal-overage reporting and by the usage component of the research-utilization score. `remaining_reserved_units` equals `inquiry_allowance_total` minus the settled units minus the reserved units; this is the RESERVATION variant, and it is the figure that must be at least 1 before a new inquiry can be scheduled. Because the reservation variant debits both settled and reserved units while the consumption variant ignores reservations entirely, an account with open `SCHEDULED` inquiries reads a smaller `remaining_reserved_units` than `remaining_consumed_units`, and the scheduling gate blocks a new booking before the settled ledger would. The settled aggregate is exposed as `consumed_inquiry_units` and the reserved aggregate as `reserved_inquiry_units`. All ledger figures are integer unit counts and are never rounded. A late cancellation consumes exactly 1 unit; a free cancellation consumes exactly 0 units.

### 2.7. Research Utilization Scoring and Renewal Posture

Research utilization is measured as a weighted score between 0 and 100, computed from three components, each capped at its own weight. The activation component is 40 multiplied by the smaller of 1 and the ratio of `active_seat_count` to 80 percent of `seat_count_contracted`. The usage component is 35 multiplied by the smaller of 1 and the ratio of `consumed_inquiry_units` to 70 percent of a usage denominator. The retention component is 25 multiplied by the smaller of 1 and the ratio of one minus `revoked_seat_count` divided by `seat_count_contracted`, to 0.95. The weights are 40, 35 and 25, and the target rates are 0.80, 0.70 and 0.95 respectively. The score is the sum of the three components, rounded half up to 2 decimal places, applied once to the summed total.

Two variants of the score exist, differing only in the usage denominator. In the SEAT_WEIGHTED variant the usage denominator is `inquiry_allowance_total`; this variant is exposed as `utilization_score` and is what the account dashboard read returns, so an account that bought seats it never activated is penalised. In the ACTIVE_WEIGHTED variant the usage denominator is `inquiry_allowance_total` multiplied by `active_seat_count` and divided by `seat_count_contracted`, rounded half up to 2 decimal places; this variant is exposed as `utilization_score_active_weighted` and is the one the contract-renewal gate reads, so the same account scores higher once unused seats are excluded from the denominator.

Three guards apply. When `seat_count_contracted` is 0 the score is 0.00. When the usage denominator is 0 the usage component is 0, never an undefined value. When `active_seat_count` is 0 the ACTIVE_WEIGHTED variant returns 0.00 outright.

`renewal_posture` is derived from a score using two ceilings: the posture is `AT_RISK` when the score is below 40, `WATCH` when the score is at least 40 and below 70, and `HEALTHY` when the score is 70 or above. The score is recomputed on seat activation, on seat revocation, on inquiry settlement, and during contract renewal review.

### 2.8. Evaluation Scoring, Deadline and Share Arithmetic

A vendor's placement in a comparative document is driven by a weighted evaluation score assembled from the `dimension_scores` rows supplied when the inclusion is created. Each row carries a `dimension`, a `raw_score` on a scale from 0.00 to 5.00, and a `weight_pct` between 0 and 1 inclusive. The weights across the rows must sum to exactly 1.00; a set that does not is a malformed request and is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

The score is computed with a pinned rounding order: each dimension's points are `weight_pct` multiplied by `raw_score`, rounded half up to 2 decimal places; `weighted_total_score` is then the sum of those already-rounded per-dimension points, rounded half up to 2 decimal places. Rounding the unrounded products only once at the end is expressly rejected — it can produce a different cent for the same inputs (for example 3.85 where the pinned order yields 3.86) and must not be used. A placement may be finalized as an inclusion only when `inclusion_criteria_met_count` is at least 4 of the six published inclusion criteria and `weighted_total_score` is at least 2.50; otherwise the finalization is rejected with `ERR_INCLUSION_CRITERIA_NOT_MET` (HTTP 409). A late fact-check response would reduce the inclusion's `weighted_total_score` by 0.25, and the score never falls below 0.00; §3.5 refuses every response that lands after the deadline, so this reduction is never applied.

Fact-check deadlines are calendar-based, not business-day based. When a round is opened at an instant T, the raw deadline is T plus 14 calendar days. If that date falls on a Saturday the deadline rolls forward by 2 days; if it falls on a Sunday it rolls forward by 1 day; otherwise it stays. The deadline `fact_check_due_utc` is that date at 23:59:59Z. A response is late exactly when `fact_check_response_at` is strictly after `fact_check_due_utc`; a response at the deadline itself is on time.

Conference agendas are governed by the sponsor minute share. The total session minutes are the sum of `duration_minutes` across all agenda rows, and the sponsor minutes are the sum of `duration_minutes` across the rows whose `session_kind` is `SPONSOR_KEYNOTE`. When there are no agenda rows the share is 0; otherwise `sponsor_minute_share` is the sponsor minutes divided by the total minutes, rounded half up to 4 decimal places. A sponsor keynote row is accepted only when the share recomputed on the post-append state is at most 0.4000 — exactly 0.4000 is allowed and 0.4001 is rejected with `ERR_SPONSOR_SHARE_EXCEEDED` (HTTP 409).

Numeric precision is pinned per family: evaluation scores and utilization scores carry 2 decimal places rounded half up; the sponsor minute share carries 4 decimal places rounded half up; licence fees are whole cents rounded half up; ledger figures are integer unit counts; timestamps are rendered in UTC at second precision, dropping any fractional part, unless a field states otherwise. Only `created_at` and `updated_at` (§2.10) and `api_request_timestamp` (§2.2) state otherwise and carry three fractional digits; every other instant the API emits — lifecycle stamps such as `embargo_until`, `fact_check_requested_at`, `fact_check_due_utc` and `appeal_window_closes_at` included, and equally an instant supplied by the client and echoed back — is rendered without a fractional part, for example `2026-09-15T00:00:00Z`.

### 2.9. Reprint Licence Arithmetic

A vendor inclusion may carry a reprint licence whose fee is computed from the inclusion's `reprint_tier`, `permitted_marketing_use` and `reprint_copies_used`. The base fee is 0 cents for the `NONE` tier, 250,000 cents for `STANDARD`, and 600,000 cents for `PREMIUM`. The copies included in the base fee are 0 for `NONE`, 500 for `STANDARD`, and 2,000 for `PREMIUM`; each copy beyond that allowance costs 900 cents on `STANDARD` and 700 cents on `PREMIUM` (and 0 on `NONE`). The overage copy count is the larger of 0 and the used copies minus the tier's included copies, and the overage fee is the overage copy count multiplied by the tier's per-copy rate. The pre-discount total is the base fee plus the overage fee.

The volume discount is selected from that pre-discount total, which already contains the overage component: 15 percent when the pre-discount total is at least 1,000,000 cents, otherwise 10 percent when it is at least 500,000 cents, otherwise no discount. The fee `reprint_fee_cents` is the pre-discount total multiplied by one minus the discount percentage, multiplied by the use multiplier for `permitted_marketing_use` — 0.00 for `NO_USE`, 0.50 for `INTERNAL_ONLY`, 0.75 for `SOCIAL_SNIPPET`, and 1.00 for `FULL_REPRINT` — rounded half up to a whole number of cents. The fee is 0 whenever `reprint_tier` is `NONE`. Selecting the discount bracket after discounting instead of before is expressly rejected, because it can drop an order into a lower bracket; the bracket is always chosen from the pre-discount total.

Copy adjustments are made by supplying `delta_copies`, which is applied to `reprint_copies_used` and recomputes the fee; the optional `permitted_marketing_use` supplied with an adjustment replaces the current use and is reflected in the recomputation. An adjustment is refused with `ERR_REPRINT_COPIES_EXCEEDED` (HTTP 409) when it would drive `reprint_copies_used` below 0 or above `reprint_copies_authorized`.

### 2.10. Common Resource Properties

Every entity in this API — `ClientAccount`, `Seat`, `Analyst`, `InquiryRequest`, `ResearchDocument`, `Vendor`, `VendorInclusion`, `VendorBriefing`, `SalesRelationship`, `ConferenceEvent` and `Sponsorship` — carries the same four system-managed properties:

- `id`: a server-minted UUID that is unique across the system and carries no type prefix. Every resource is addressed by this value.
- `created_at`: the ISO 8601 UTC instant at which the resource was created, formatted with three fractional digits (for example `2025-05-24T10:30:00.123Z`).
- `updated_at`: the ISO 8601 UTC instant at which the resource was last modified, in the same three-fractional-digit format. Any change to any field of a resource — including a recomputation of a derived field — refreshes `updated_at`.
- `version`: an integer that starts at its initial value and increments by one on every modification of the resource. It is the value clients read to participate in the optimistic concurrency rules of §2.12. A resource created directly in a state that a rule describes as the result of a transition — an inquiry created `ROUTED`, a briefing created `SCHEDULED`, an inclusion created `UNDER_EVALUATION` — starts at version 1, because that transition is part of the create rather than a separate modification. A create that computes derived values differing from the placeholders the row is minted with — a `ClientAccount`'s seat counts, ledger remainders and utilization scores — is a modification, so a freshly created account is returned at version 2.

Fields that record a lifecycle instant are null until the event that stamps them occurs, and lifecycle booleans begin false; clients never supply these system-managed values. Free-text inputs that the specification describes as an accompanying reason, rationale or comment — `decline_reason`, `cancel_reason`, `termination_reason`, `revision_reason`, `rationale`, `comments` — and a fact-check response's `response_summary` and `correction_offered` are validated for presence and type but are not persisted on the resource and never appear in a response.

### 2.11. Nested Resource Retrieval and Validation Precedence

When a request targets a nested resource, the server validates the identifiers in the order they are declared, left to right, and rejects the request at the first failure. A path identifier that matches no resource of its kind produces that entity's own not-found error, and the request never proceeds to evaluate later identifiers or body rules. The not-found family is: `ERR_CLIENT_ACCOUNT_NOT_FOUND`, `ERR_SEAT_NOT_FOUND`, `ERR_ANALYST_NOT_FOUND`, `ERR_INQUIRY_NOT_FOUND`, `ERR_DOCUMENT_NOT_FOUND`, `ERR_VENDOR_NOT_FOUND`, `ERR_VENDOR_INCLUSION_NOT_FOUND`, `ERR_BRIEFING_NOT_FOUND`, `ERR_SALES_RELATIONSHIP_NOT_FOUND`, `ERR_CONFERENCE_EVENT_NOT_FOUND` and `ERR_SPONSORSHIP_NOT_FOUND`, all HTTP 404. A body foreign key that references a missing resource is reported the same way, using the error of the referenced entity.

Beyond existence, checks run in a fixed precedence. When more than one check would fail, the earliest one in this ordering determines the response, and later checks are not evaluated:

1. Authentication: both `X-User-ID` and `X-User-Role` are present, except on the clock operation. Failure is `ERR_UNAUTHENTICATED` (HTTP 401). This check applies to all requests except `/_clock/set_current_utc`.
2. Authorization: the supplied role is listed among the endpoint's authorized roles. Failure is `ERR_UNAUTHORIZED` (HTTP 403). This check applies to all endpoints.
3. Request shape: every required input field is present, enum members are in range, and integers satisfy their declared bounds — including the requirement that evaluation weights sum to exactly 1.00. Fields the endpoint does not declare are ignored. Failure is `ERR_INVALID_REQUEST` (HTTP 400). This check applies to all write endpoints.
4. Referential existence, left to right as described above. This check applies to every endpoint with a path identifier or a body foreign key.
5. Target state: the resource named by the request is in a state from which the requested transition exists, and a resource in a terminal state rejects every further transition. Failure is `ERR_INVALID_STATE` (HTTP 409). This check applies to all action endpoints.
6. Research independence, as defined in §2.5. Failure is `ERR_SEPARATION_OF_DUTIES_VIOLATION` (HTTP 403). This check applies to exactly four operations: requesting a vendor briefing, responding to a vendor fact check, submitting a document for peer review, and finalizing a vendor inclusion.
7. Time windows: a requested inquiry start instant must not be strictly before the clock (`ERR_INQUIRY_START_IN_PAST`, HTTP 400); an appeal must be filed on or before `appeal_window_closes_at` (`ERR_APPEAL_WINDOW_CLOSED`, HTTP 409); a fact-check response must land on or before `fact_check_due_utc` and is refused once the cycle has lapsed (`ERR_FACT_CHECK_RESPONSE_LATE`, HTTP 409); and a vendor read of an `EMBARGOED` document is refused (`ERR_EMBARGO_ACTIVE`, HTTP 403). This check applies to inquiry submission, inquiry scheduling, appeal filing, fact-check responses and document reads by a vendor.
8. Uniqueness, capacity and overlap: `seat_email` must be unique within its account (`ERR_DUPLICATE_SEAT_EMAIL`); an analyst's inquiry windows must not overlap (`ERR_INQUIRY_SLOT_OVERLAP`); an analyst may hold at most 3 inquiries starting on the same UTC calendar day (`ERR_ANALYST_DAILY_INQUIRY_CAP`); briefing slots must respect the 15-minute buffer (`ERR_BRIEFING_SLOT_CONFLICT`); `PLATINUM` sponsor exclusivity windows must not overlap (`ERR_SPONSOR_EXCLUSIVITY_OVERLAP`); the sponsor minute share must stay at or below 0.4000 (`ERR_SPONSOR_SHARE_EXCEEDED`); and an inclusion may be appealed at most twice (`ERR_APPEAL_LIMIT_REACHED`). All of these are HTTP 409. This check applies to seat creation, inquiry scheduling, briefing requests, sponsorship creation, agenda session appends and appeal filing.
9. Referenced entity state: the seat must be `ACTIVE` and its account `ACTIVE` before an inquiry may be submitted (`ERR_SEAT_NOT_ACTIVE`, HTTP 409), and the linked conference event must still be `DRAFT` or `PROGRAMMING` before a sponsorship may be activated (`ERR_EVENT_AGENDA_LOCKED`, HTTP 409).
10. Allowance: the account's reservation remainder must be at least 1 before an inquiry may be scheduled (`ERR_INQUIRY_ALLOWANCE_EXHAUSTED`, HTTP 409).
11. Optimistic concurrency, as defined in §2.12 (`ERR_STALE_VERSION`, HTTP 412).

### 2.12. Optimistic Concurrency Control and Cascading Side Effects

Three write operations require the client to present its last-observed version of a parent entity, and each is rejected when that version is stale. Creating a vendor inclusion on a document requires `expected_document_version`; if it does not equal the document's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). Creating a sales relationship requires `expected_analyst_version`; if it does not equal the analyst's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). Creating a sponsorship requires `expected_conference_event_version`; if it does not equal the event's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). These three fields are non-optional on their respective operations. No other endpoint accepts a version field: a create that is legitimate on product grounds is never blocked by a state precondition, and the stale-version check is what keeps each snapshot coherent.

Several operations mutate more than one entity, and every cascade is part of the contract rather than an implementation detail. Revoking a seat updates the seat's own status and timestamps, recomputes the owning account's active, provisioned and revoked seat counts, recomputes the account's `utilization_score` and `renewal_posture`, and can push the account's contract into `RENEWAL_REVIEW` when the active seat count falls below half of the contracted seats rounded up. Publishing a document freezes every inclusion on it and re-derives vendor eligibility in a three-step cascade. Creating a sales relationship propagates through briefings, inclusions and the vendor registry in a four-step cascade. Reopening a published document, upholding an appeal and resolving a fact-check dispute each re-open downstream rounds. Every step of every cascade mutates the affected resource in the ordinary way: the resource's `updated_at` is refreshed and its `version` is incremented, and the cascade continues from the mutated state.

## 3. Business Logic & Workflows

### 3.1. Onboarding a Client Account and Provisioning Seats

A `PlatformAdmin` opens a client relationship by creating a `ClientAccount` with its contract terms: the `legal_name` and `industry` of the subscribing enterprise, its contracting `region` (one of `NA`, `EMEA`, `APAC`), the `contract_start_utc` and `contract_end_utc` that bound the term, the `seat_count_contracted` the client has paid for (at least 1), the `inquiry_allowance_total` included in the term (at least 0), and the `reprint_tier` available to the account (one of `NONE`, `STANDARD`, `PREMIUM`). The new account starts in `contract_status` `ACTIVE`. Its `active_seat_count`, `provisioned_seat_count` and `revoked_seat_count` all start at 0, both ledger remainders start equal to `inquiry_allowance_total`, `utilization_score` and `utilization_score_active_weighted` are computed by the standard scoring rules, and `renewal_posture` is derived from the score. `renewal_decided_at` stays null until a renewal decision is recorded.

Seats are then provisioned onto the account by a `ClientAdmin` acting for that account. A `Seat` is created with its `client_account_id`, the named user's `seat_email` — which must be unique within the account, or the request is rejected with `ERR_DUPLICATE_SEAT_EMAIL` (HTTP 409) — and a `research_role` of `EXECUTIVE_VIEWER`, `PRACTITIONER`, `ARCHITECT` or `STRATEGIST`. The optional `seat_kind` distinguishes a `NAMED` seat from a `SHARED` pool seat and defaults to `NAMED`; the optional `entitlement_override_types` list grants extra document types on top of the role matrix and defaults to an empty list. A new seat begins in status `PROVISIONED`, with `activated_at` and `revoked_at` null and `last_inquiry_at` null; the owning account's `provisioned_seat_count` is incremented and its utilization score is recomputed.

Research entitlements are derived when a seat is activated. The `research_role` selects a base set of document types, and any `entitlement_override_types` are appended in the order supplied and de-duplicated into `entitlement_document_types`. An `EXECUTIVE_VIEWER` seat may open `MARKET_GUIDE` documents. A `PRACTITIONER` seat may open `MARKET_GUIDE`, `COMPARATIVE_MATRIX` and `HYPE_PROFILE` documents. An `ARCHITECT` seat may open `MARKET_GUIDE`, `COMPARATIVE_MATRIX`, `HYPE_PROFILE` and `CRITICAL_CAPABILITIES` documents. A `STRATEGIST` seat may open `MARKET_GUIDE`, `COMPARATIVE_MATRIX` and `CRITICAL_CAPABILITIES` documents. An override adds a type regardless of the role matrix, so an `EXECUTIVE_VIEWER` with `CRITICAL_CAPABILITIES` supplied as an override may open that type as well. An override member that is not one of the four document types is a malformed request (`ERR_INVALID_REQUEST`, HTTP 400). The derived list is reported on the seat; the API defines no entitlement-refusal error, so it does not gate any request.

Activation moves a seat from `PROVISIONED` to `ACTIVE` and is permitted only while the owning account's `contract_status` is `ACTIVE`. The activation stamps `activated_at` with the clock reading, increments the seat's `version`, derives `entitlement_document_types`, increments the account's `active_seat_count` while decrementing its `provisioned_seat_count`, and recomputes the account's utilization score and renewal posture. The seat's status is the gate for the account's inquiry capability: an inquiry may only be submitted from a seat that is `ACTIVE`, on an account whose contract is `ACTIVE`.

Revocation is available from either `PROVISIONED` or `ACTIVE` and ends the seat's life in the terminal `REVOKED` state, stamping `revoked_at` with the clock reading and incrementing the seat's `version`. An `ACTIVE` seat that is revoked also has its `entitlement_document_types` emptied, and the account's `active_seat_count` is decremented; a `PROVISIONED` seat that is revoked instead decrements the account's `provisioned_seat_count`. Both paths increment the account's `revoked_seat_count` and recompute the account's `utilization_score` with the SEAT_WEIGHTED variant and its `renewal_posture`. Two consequences are worth calling out because they couple seat administration to the contract. First, if the recomputed utilization score falls below 40, the account's posture becomes `AT_RISK`. Second, if the account's `active_seat_count` falls below half of `seat_count_contracted` rounded up to the next whole number, the account's `contract_status` moves from `ACTIVE` to `RENEWAL_REVIEW` and its `updated_at` is refreshed.

An account reaches `RENEWAL_REVIEW` automatically as its term approaches its end. Once the logical clock reaches `contract_end_utc` minus 90 days — the boundary is inclusive — the transition is evaluated on every write that touches the account and on every read of the account, and an account whose `contract_status` is `ACTIVE` moves to `RENEWAL_REVIEW` with its `updated_at` refreshed, its `version` incremented, and its `renewal_posture` recomputed from the current utilization score.

### 3.2. Inquiry Routing, Scheduling and Preparation

The analyst roster that routing draws on is seeded by a `PlatformAdmin`, who registers each analyst with a `full_name`, a `practice_area` (one of `CIO_TECH`, `DATA_ANALYTICS`, `SECURITY`, `ERP_FINANCE`), the `topic_routes` the analyst accepts for inquiry routing, and a `seniority` band (one of `ASSOCIATE`, `SENIOR`, `VP`, `DISTINGUISHED`). An optional `status` defaults to `ACTIVE` and may also be `ON_LEAVE` or `EMERITUS`. A newly registered analyst starts with `integrity_flag` `CLEAR`, an empty `conflicted_vendor_ids` list, `open_inquiry_count` 0 and `inquiries_completed_total` 0.

A `SeatHolder` submits an inquiry by supplying the `seat_id` that will spend the allowance unit, the `topic_route` the question belongs to, a `question_summary`, the `requested_start_utc`, and a `duration_minutes` of 30, 45 or 60 minutes. An optional `preparation_notes` string may accompany the request and defaults to an empty string. Two gates apply before the inquiry exists: the requested start instant must not be strictly before the current clock reading, or the request is rejected with `ERR_INQUIRY_START_IN_PAST` (HTTP 400); and the owning seat must be `ACTIVE` on an account whose contract is `ACTIVE`, or the request is rejected with `ERR_SEAT_NOT_ACTIVE` (HTTP 409). The new inquiry begins in `SUBMITTED`, with `analyst_id` unset, `scheduled_start_utc` null, `settled_at` null, `units_consumed` 0, `note_delivered` false, `note_reference` an empty string, `declined_analyst_ids` empty, and `routing_attempt_count` 0.

Topic routing then runs as part of the submission and assigns the analyst. A candidate is eligible when the analyst's own status is `ACTIVE`, the inquiry's `topic_route` is present in the analyst's `topic_routes`, the analyst's `id` is not already in the inquiry's `declined_analyst_ids`, and the analyst's `integrity_flag` is not `CONFLICT_BLOCKED`. Eligible analysts are ranked by seniority — `DISTINGUISHED` outranks `VP`, which outranks `SENIOR`, which outranks `ASSOCIATE` — and ties are broken first by the analyst's `open_inquiry_count` — the number of inquiries assigned to that analyst that are in `ROUTED`, `SCHEDULED` or `IN_PREP` — ascending, and then by the analyst's `created_at` ascending. The final tie-break is always `created_at`, never the analyst identifier. Because the logical clock does not advance on writes, analysts registered at the same clock reading share an identical `created_at`; when candidates remain tied after every rule above, the one registered earliest is chosen. If the eligible pool is empty, the submission is rejected with `ERR_ANALYST_NOT_ELIGIBLE` (HTTP 409) and no inquiry row is created. Otherwise the winner's `id` becomes the inquiry's `analyst_id`, `routing_attempt_count` is set to 1, the inquiry moves to `ROUTED` with its `version` incremented, the winner's `open_inquiry_count` is incremented, and the seat's `last_inquiry_at` is stamped with the clock reading.

Scheduling is the assigned analyst's act, and it confirms the slot with a `scheduled_start_utc`. Six conditions must hold. The acting analyst must be the inquiry's `analyst_id`; the inquiry must be in `ROUTED`; the supplied start must not be strictly before the clock reading, or the request fails with `ERR_INQUIRY_START_IN_PAST` (HTTP 400); the half-open window from the supplied start for the inquiry's `duration_minutes` must not overlap any other inquiry of the same analyst that is `SCHEDULED` or `IN_PREP`, or the request fails with `ERR_INQUIRY_SLOT_OVERLAP` (HTTP 409); the analyst must hold fewer than 3 inquiries whose `scheduled_start_utc` falls on the same UTC calendar day as the requested slot, or the request fails with `ERR_ANALYST_DAILY_INQUIRY_CAP` (HTTP 409); and the account's `remaining_reserved_units` must be at least 1, or the request fails with `ERR_INQUIRY_ALLOWANCE_EXHAUSTED` (HTTP 409). On success the inquiry moves to `SCHEDULED`, `scheduled_start_utc` records the confirmed instant, the `version` is incremented, the account's `reserved_inquiry_units` is incremented and its `remaining_reserved_units` recomputed. The account's `remaining_consumed_units` does not move at scheduling time: the CONSUMPTION ledger only changes when an inquiry settles.

An analyst who cannot take a scheduled inquiry declines it, optionally supplying a `decline_reason`. A decline is available only while the inquiry is `SCHEDULED` and only to the assigned analyst. The declining analyst is appended to `declined_analyst_ids` and thereby removed from eligibility for the rest of this inquiry's life; topic routing runs again over the remaining eligible analysts, and the winner becomes the new `analyst_id` while `routing_attempt_count` is incremented. If no eligible analyst remains, the decline is refused with `ERR_ANALYST_NOT_ELIGIBLE` (HTTP 409) and nothing is mutated: the declining analyst is not recorded in `declined_analyst_ids`, the inquiry stays `SCHEDULED` with its current `analyst_id`, and no ledger figure moves. The inquiry returns to `ROUTED`, `scheduled_start_utc` is cleared, the `version` is incremented, the account's `reserved_inquiry_units` is decremented and its `remaining_reserved_units` recomputed, and the load counters move: the previous analyst's `open_inquiry_count` is decremented and the new analyst's is incremented.

Preparation is automatic and clock-driven. Once the logical clock reaches the inquiry's `scheduled_start_utc` minus 24 hours — the boundary is inclusive — the inquiry moves from `SCHEDULED` to `IN_PREP` on the next read or write, and its `version` is incremented. From that point `preparation_notes` is mandatory for a successful completion: an inquiry whose `preparation_notes` is empty cannot be closed out as completed and the attempt is rejected with `ERR_PREPARATION_NOTES_REQUIRED` (HTTP 409).

### 3.3. Inquiry Settlement, Cancellation and the Allowance Ledger

Closing out an inquiry is the assigned analyst's act, performed once the inquiry is in `IN_PREP` and the clock has reached the scheduled start. A completion attempted while the inquiry is not `IN_PREP`, or while the clock is still strictly before `scheduled_start_utc`, is refused with `ERR_INVALID_STATE` (HTTP 409). The completion request carries an `outcome` of either `COMPLETED` or `NO_SHOW`, a `note_delivered` boolean, and an optional `note_reference` pointing at the delivered note artefact.

A completion with outcome `COMPLETED` additionally requires that `note_delivered` is true and that `preparation_notes` is non-empty; an empty preparation note is refused with `ERR_PREPARATION_NOTES_REQUIRED` (HTTP 409). On success the inquiry reaches the terminal `COMPLETED` state with `units_consumed` set to 1, `settled_at` stamped with the clock reading, and its `version` incremented. The account's `reserved_inquiry_units` is decremented and its `consumed_inquiry_units` incremented, and both ledger remainders are recomputed; the account's utilization score and renewal posture are recomputed. The analyst's `open_inquiry_count` is decremented and their lifetime `inquiries_completed_total` is incremented.

A completion with outcome `NO_SHOW` requires only that the inquiry is `IN_PREP` and the clock has reached the scheduled start. It reaches the terminal `NO_SHOW` state with `units_consumed` set to 1, `note_delivered` forced to false, `settled_at` stamped with the clock reading, and its `version` incremented. The ledger moves exactly as in the completed case — the reservation is released and the unit is consumed — and the account's utilization score and renewal posture are recomputed, but the analyst's `inquiries_completed_total` is not incremented; only `open_inquiry_count` is decremented.

Cancellation belongs to the seat that owns the inquiry, and it may be exercised while the inquiry is `ROUTED`, `SCHEDULED` or `IN_PREP`; an optional `cancel_reason` may accompany it. Every cancellation ends in the terminal `CANCELLED` state with `settled_at` stamped and the `version` incremented, and every cancellation decrements the routed analyst's `open_inquiry_count`. The charge depends on how far the inquiry had progressed. Cancelling a `ROUTED` inquiry that was never scheduled consumes nothing: `units_consumed` is 0 and no ledger account moves, because no unit had been reserved. Cancelling a scheduled or in-preparation inquiry is free while the clock reading is at or before `scheduled_start_utc` minus 24 hours — `units_consumed` is 0 and only the reservation is released, decrementing `reserved_inquiry_units` — and is late once the clock reading is strictly after that instant, in which case `units_consumed` is 1 and the account's `reserved_inquiry_units` is decremented while its `consumed_inquiry_units` is incremented. The charge follows the clock reading against that boundary, not the status the evaluation produced: an inquiry that has just entered `IN_PREP` because the clock reading has reached `scheduled_start_utc` minus 24 hours — but has not passed it — is still cancelled free of charge, and only a clock reading strictly after the boundary makes the cancellation late. The account's utilization score is recomputed in both the free and the late branch, and the renewal posture follows it. `COMPLETED`, `NO_SHOW` and `CANCELLED` are terminal: any further transition attempted on such an inquiry is rejected with `ERR_INVALID_STATE` (HTTP 409).

The allowance ledger that these settlements feed is described in §2.6. In short, settled inquiries — `COMPLETED`, `NO_SHOW`, and late-cancelled ones — reduce `remaining_consumed_units`, while open `SCHEDULED` and `IN_PREP` inquiries additionally reduce `remaining_reserved_units`, which is the figure the scheduling gate reads.

### 3.4. Contract Renewal and Measured Utilization

Renewal is a governance decision recorded by a `ResearchDirector` while the account sits in `RENEWAL_REVIEW`. The decision request carries a `decision` whose value is `RENEW` or `CHURN`. An account that is not in `RENEWAL_REVIEW` rejects the decision with `ERR_INVALID_STATE` (HTTP 409), and the two terminal outcomes of this lifecycle, `RENEWED` and `CHURNED`, accept no further decision at all.

A `RENEW` decision is gated on measured research utilization. The gate reads the ACTIVE_WEIGHTED variant of the score — `utilization_score_active_weighted` — not the dashboard variant, and requires it to be at least 40; a score of exactly 40 passes. The decision also requires that no seat on the account is still in `PROVISIONED` status, meaning every contracted seat has been either activated or revoked. A `RENEW` that fails either condition is rejected with `ERR_RENEWAL_UTILIZATION_TOO_LOW` (HTTP 409). On success the account's `contract_status` becomes `RENEWED`, `renewal_decided_at` is stamped with the clock reading, the `version` is incremented, and the utilization score is recomputed one final time and frozen into `renewal_posture`.

A `CHURN` decision requires only that the account is in `RENEWAL_REVIEW`. It sets `contract_status` to `CHURNED`, stamps `renewal_decided_at` with the clock reading, and increments the `version`. It also cascades to the account's people: every `ACTIVE` seat on the account is revoked in the ordinary way and `active_seat_count` is recomputed. The cascade stops at seats. Commercial relationships are deliberately untouched — the analysts who hold ties connected to this account are not affected by the churn — so the separation register survives the loss of the client.

An account's utilization is also the subject of the renewal-overage report, which reads `remaining_consumed_units` — the CONSUMPTION variant of the allowance ledger — rather than the reservation remainder, so that overage reporting reflects settled usage rather than units merely held by open bookings.

### 3.5. Authoring Research: Peer Review and Fact-Check Cycles

A research document is opened by an `Analyst` or a `ResearchDirector` with a `title`, a `doc_type` (one of `MARKET_GUIDE`, `COMPARATIVE_MATRIX`, `HYPE_PROFILE`, `CRITICAL_CAPABILITIES`), the `practice_area` that owns it (one of `CIO_TECH`, `DATA_ANALYTICS`, `SECURITY`, `ERP_FINANCE`), and the `lead_analyst_id` who authors it. An optional `embargo_days` sets the embargo length in days and must be at least 0; when it is omitted the length defaults by document type to 30 days for a `MARKET_GUIDE`, 45 days for a `COMPARATIVE_MATRIX`, 14 days for a `HYPE_PROFILE`, and 21 days for a `CRITICAL_CAPABILITIES`. An optional `peer_reviewer_analyst_id` may be named up front and defaults to an empty string. The document is created in `editorial_status` `DRAFT` and `embargo_status` `EMBARGOED`, with `peer_verdict` `NOT_ASSIGNED`, `peer_review_round` 0, `fact_check_open_count` 0, `included_vendor_count` 0, `placement_locked` false, `revision_count` 0, and `published_at` and `embargo_until` null.

Submitting for review supplies the `peer_reviewer_analyst_id` and is available while the document's `editorial_status` is `DRAFT` or `REVISED`. The named reviewer must be set and must differ from `lead_analyst_id`; a submission that names the author as reviewer is rejected with `ERR_SEPARATION_OF_DUTIES_VIOLATION` (HTTP 403). On success the document enters `PEER_REVIEW`, `peer_verdict` becomes `PENDING`, `peer_review_round` is incremented, and the `version` is incremented.

The reviewer — and only the reviewer — returns a `verdict` of `APPROVE` or `REVISE`, optionally with `comments`. An `APPROVE` records `peer_verdict` `APPROVE` and advances the document to `FACT_CHECK`, and it opens a fact-check round for every inclusion on the document whose `inclusion_status` is `INCLUDED`: each such inclusion's `fact_check_status` becomes `REQUESTED`, `fact_check_requested_at` is stamped with the clock reading, `fact_check_round` is incremented, and `fact_check_due_utc` is computed by the deadline rule of §2.8. The document's `fact_check_open_count` is then recomputed. A `REVISE` records `peer_verdict` `REVISE` and returns the document to `DRAFT`; the author reworks it and may submit it for review again.

Vendors answer their fact-check requests. A response is made by the vendor that owns the inclusion — the acting vendor's identifier must equal the inclusion's `vendor_id` — and carries a `response_summary` and a `correction_offered` value. It is available only while the inclusion's `fact_check_status` is `REQUESTED`, and it is refused with `ERR_SEPARATION_OF_DUTIES_VIOLATION` (HTTP 403) while the inclusion's `lead_analyst_conflicted` is true. A response that arrives after the deadline is refused with `ERR_FACT_CHECK_RESPONSE_LATE` (HTTP 409) — whether the inclusion has already been marked `LAPSED` or the clock has merely passed `fact_check_due_utc` — and this refusal takes precedence over the target-state check; when the inclusion was still `REQUESTED`, the refusal first lapses it (`fact_check_status` `LAPSED`, `fact_check_late` true) and recomputes the parent document's `fact_check_open_count`. Because a response after the deadline is always refused, no accepted response is ever late: `fact_check_late` is false on every `VENDOR_RESPONDED` row, and the 0.25 penalty and the exclusion that two consecutive late rounds would trigger are never applied. A successful response moves `fact_check_status` to `VENDOR_RESPONDED` and stamps `fact_check_response_at` with the clock reading.

An unanswered round lapses on its own. Once the logical clock is strictly after `fact_check_due_utc`, an inclusion still in `REQUESTED` moves to `LAPSED` with `fact_check_late` set to true and its `version` incremented, and the parent document's `fact_check_open_count` is recomputed. A response landing exactly at `fact_check_due_utc` is on time; one second later the cycle has lapsed.

Research governance adjudicates each response. An `ACCEPT` outcome moves `fact_check_status` from `VENDOR_RESPONDED` to `ADJUDICATED`, recomputes the document's `fact_check_open_count`, and, when that count reaches 0 while the document is in `FACT_CHECK`, moves the document to `CLEARED` with the count set to 0. A `DISPUTE` outcome is available only while `fact_check_round` is below 3; it moves `fact_check_status` to `DISPUTED`, and the next round opens immediately: `fact_check_status` returns to `REQUESTED` with `fact_check_round` incremented, `fact_check_requested_at` stamped with the clock reading, and a fresh `fact_check_due_utc`. The loop `REQUESTED` → `VENDOR_RESPONDED` → `DISPUTED` → `REQUESTED` is capped at a `fact_check_round` of 3.

The document's `fact_check_open_count` counts the inclusions on it whose `fact_check_status` is `REQUESTED`, `VENDOR_RESPONDED` or `DISPUTED`; it is recomputed whenever a round is opened, lapses, or is adjudicated.

A document is cleared only when it is in `FACT_CHECK`, at least one inclusion on it has `inclusion_status` `INCLUDED`, and every inclusion whose `inclusion_status` is `INCLUDED` has reached `fact_check_status` `ADJUDICATED`.

### 3.6. Publication, Embargo and the Frozen Placement Snapshot

Publication is a `ResearchDirector` decision available once a document is `CLEARED`. It sets `editorial_status` to `PUBLISHED` and `published_at` to the clock reading, sets `embargo_status` to `EMBARGOED`, and computes `embargo_until` as `published_at` plus `embargo_days`, rolled forward to the following Monday at 00:00:00Z when that landing date falls on a Saturday or a Sunday. The document's `revision_count` is left unchanged by publication, and the `version` is incremented.

Publication freezes the document's evaluation snapshot in a three-step cascade. First, every inclusion on the document receives `placement_locked` true, and its `weighted_total_score` is frozen at its current value; the document's own `placement_locked` flag is set true as well and stays true for as long as the document is `PUBLISHED`. Second, for each inclusion whose `inclusion_status` is `INCLUDED`, the linked `Vendor`'s `briefing_eligible` is recomputed by the rule stated at the end of this paragraph — it becomes true for a vendor that holds no active sales tie; for each inclusion whose `inclusion_status` is `EXCLUDED`, that inclusion's `appeal_window_closes_at` is set to `published_at` plus 30 days. Third, the document's `included_vendor_count` is recomputed from the frozen snapshot, counting inclusions whose `inclusion_status` is `INCLUDED` or `APPEAL_UPHELD`. A vendor is briefing-eligible when it holds at least one placement whose `inclusion_status` is exactly `INCLUDED` on a `PUBLISHED` document — an `APPEAL_UPHELD` placement does not by itself confer eligibility — and it carries no `ACTIVE` `SalesRelationship` at all (`active_sales_relationship_count` is 0). The flag is recomputed from that rule at each point that can move it, rather than merely set.

The embargo is a second, independent axis of the document's state. `embargo_status` begins at `EMBARGOED` and moves to the terminal `RELEASED` once the logical clock reaches `embargo_until` — the boundary is inclusive — with the transition evaluated on every read or write of the document and the document's `version` incremented. A vendor read of a document whose `embargo_status` is `EMBARGOED` is refused with `ERR_EMBARGO_ACTIVE` (HTTP 403); other roles read the document normally. A document that has never been published keeps `embargo_status` `EMBARGOED` with `embargo_until` null, and the release rule applies only once `published_at` is set.

Reopening a published document is the revision path, available to an `Analyst` or `ResearchDirector` and requiring a `revision_reason`. It moves `editorial_status` from `PUBLISHED` to `REVISED` and increments both `revision_count` and the document's `version`. Every inclusion on the document whose `inclusion_status` is `INCLUDED` or `APPEAL_UPHELD` is unlocked and re-checked: `placement_locked` becomes false (as does the document's own flag), `fact_check_status` becomes `REQUESTED`, `fact_check_round` is incremented, `fact_check_requested_at` is stamped with the clock reading, and `fact_check_due_utc` is recomputed. The document's `fact_check_open_count` is recomputed, and, because a revision has opened at least one round, the document then moves immediately from `REVISED` to `FACT_CHECK` with its `version` incremented.

### 3.7. Vendor Placement: Evaluation, Appeals and Reprint Licensing

A vendor enters the research universe through registration with a `vendor_name`, an `hq_region` (one of `NA`, `EMEA`, `APAC`) and an `employee_count_band` (one of `SMB`, `MIDMARKET`, `ENTERPRISE`). Every registered vendor is `ACTIVE`; the `status` value is system-initialized at creation and is never client-supplied. A new vendor starts with `briefing_eligible` false, `active_sales_relationship_count` 0 and `last_briefing_at` null.

An `Analyst` or `ResearchDirector` proposes a vendor for a comparative document by creating a `VendorInclusion` that names the `vendor_id` and carries the evaluation evidence: `dimension_scores` rows, each with a `dimension`, a `raw_score` and a `weight_pct`; an `inclusion_criteria_met_count` between 0 and 6; and the `expected_document_version` the client last observed for the parent document. The proposal may also pre-set the licensing terms — `reprint_tier` (default `NONE`), `permitted_marketing_use` (default `NO_USE`) and `reprint_copies_authorized` (default 0, at least 0). Because the document's version must match the supplied `expected_document_version`, a proposal built against a stale view of the document is rejected with `ERR_STALE_VERSION` (HTTP 412) before any snapshot is written; this is the serialization point that keeps the evaluation snapshot coherent with the document version the client last observed.

A created inclusion begins in `PROPOSED`, and it advances immediately to `UNDER_EVALUATION` when its weights sum to exactly 1.00. At that point `weighted_total_score` is computed by the pinned per-dimension rounding rule of §2.8, `criteria_evaluated_at` is stamped with the clock reading, `fact_check_status` remains `NOT_STARTED`, `appeal_count` starts at 0, `fact_check_round` starts at 0, `placement_locked` starts false, `appeal_filed_at` is null and `appeal_grounds` is an empty string until an appeal is filed, and `reprint_fee_cents` is computed from the licensing terms. The inclusion also records `lead_analyst_conflicted`, which is true when the parent document's `lead_analyst_id` holds an `ACTIVE` `SalesRelationship` with this vendor. Creating a newer inclusion for the same `document_id` and `vendor_id` pair supersedes the older row: the older inclusion moves from `INCLUDED` to `SUPERSEDED`, its `placement_locked` becomes false, and the parent document's `included_vendor_count` is recomputed. The parent document's `version` is incremented by the create itself.

Placement is finalized by a `ResearchDirector` with an `outcome` of `INCLUDE` or `EXCLUDE`. An `INCLUDE` requires the inclusion to be `UNDER_EVALUATION`, `inclusion_criteria_met_count` to be at least 4 of the six published criteria, and `weighted_total_score` to be at least 2.50; a finalization that misses either threshold is rejected with `ERR_INCLUSION_CRITERIA_NOT_MET` (HTTP 409). A successful inclusion sets `inclusion_status` to `INCLUDED` and recomputes the parent document's `included_vendor_count`. An `EXCLUDE` requires only that the inclusion is `UNDER_EVALUATION`; it sets `inclusion_status` to `EXCLUDED`, and, when the parent document is already `PUBLISHED`, it also sets the inclusion's `appeal_window_closes_at` to `published_at` plus 30 days.

Exclusion is appealable by the vendor, through its `VendorRep`, and the appeal carries the vendor's `appeal_grounds`. An appeal may be filed from `EXCLUDED` or from `APPEAL_DENIED`, by the vendor that owns the inclusion, while `appeal_count` is below 2 and while the parent document is `PUBLISHED` and the clock reading is at or before `appeal_window_closes_at`. An appeal whose parent document is not `PUBLISHED` is refused with `ERR_INVALID_STATE` (HTTP 409), not with an appeal-window error. An appeal filed after the window closes is rejected with `ERR_APPEAL_WINDOW_CLOSED` (HTTP 409), and an appeal attempted once `appeal_count` is already 2 is rejected with `ERR_APPEAL_LIMIT_REACHED` (HTTP 409). A successful appeal moves the inclusion to `UNDER_APPEAL`, stamps `appeal_filed_at` with the clock reading, stores the `appeal_grounds` (replacing any earlier grounds when the appeal follows a denial), increments `appeal_count`, and increments the inclusion's `version`. The appeal loop runs `EXCLUDED` → `UNDER_APPEAL` → `APPEAL_DENIED` → `UNDER_APPEAL` and is capped at an `appeal_count` of 2.

Research governance decides the appeal with an `outcome` of `UPHOLD` or `DENY`, optionally accompanied by a `rationale`. An `UPHOLD` moves the inclusion to `APPEAL_UPHELD`, recomputes the parent document's `included_vendor_count`, and — when the parent document's `editorial_status` is `PUBLISHED` — reopens the document: it moves `PUBLISHED` → `REVISED` with `revision_count` incremented, and every inclusion on it whose `inclusion_status` is `INCLUDED` or `APPEAL_UPHELD` has its `fact_check_status` set to `REQUESTED`. The document is left at `REVISED`: unlike the revision path of §3.6, this re-opening does not advance it to `FACT_CHECK`. The document's own `placement_locked` flag is cleared, each re-opened inclusion receives a fresh `fact_check_round`, `fact_check_requested_at` and `fact_check_due_utc`, and the document's `fact_check_open_count` is recomputed. A `DENY` moves the inclusion to `APPEAL_DENIED` and leaves the placement snapshot unchanged; `appeal_count` keeps its current value, so a second appeal remains possible while the window is open. Both outcomes increment the inclusion's `version`.

Licensing is administered on the placement itself. The `reprint_tier` purchased for the placement, the `permitted_marketing_use` it allows, the `reprint_copies_authorized` the licence grants, and the `reprint_copies_used` consumed against it together drive `reprint_fee_cents` by the arithmetic of §2.9; the fee is recomputed on every copy adjustment and when the placement is finalized. A `VendorRep` or `PlatformAdmin` adjusts consumption by supplying `delta_copies`, optionally replacing `permitted_marketing_use` in the same request; the fee is recomputed and an adjustment that would drive `reprint_copies_used` below 0 or above `reprint_copies_authorized` is refused with `ERR_REPRINT_COPIES_EXCEEDED` (HTTP 409).

Two state axes live on the same inclusion row and evolve independently: `inclusion_status` governs placement, and `fact_check_status` governs the verification cycle. A fact-check round never changes `inclusion_status`, and an appeal never changes `fact_check_status` — except through the explicit reopening cascade that an upheld appeal triggers on the parent document.

### 3.8. Vendor Briefings and the Separation Register

A vendor, through its `VendorRep`, requests a briefing by supplying its `vendor_id`, the `briefing_topic` it wants to present, a `requested_start_utc` and a `duration_minutes` of 30, 45 or 60. Separation screening runs inside the creation, before any analyst is assigned, and its result is recorded in `separation_check_result` — `PASS` when an analyst is found, and `FAIL_SALES_RELATIONSHIP` when the briefing is later revoked by the separation cascade; because screening completes inside the create, `PENDING` is never observable on a persisted row. A briefing that passes screening and whose slot is free is created directly in `SCHEDULED` with `separation_check_result` `PASS` and an `analyst_id` assigned by briefing routing, so the intermediate `SCREENED` state is likewise never observable.

Briefing routing mirrors inquiry routing but with a stricter independence bar. A candidate must have analyst status `ACTIVE`, must list the `briefing_topic` in their `topic_routes`, and must have `integrity_flag` `CLEAR` — an analyst holding any active commercial tie is ineligible regardless of topic. Candidates are ranked by the number of open briefings already assigned to them, ascending, with ties broken by the analyst's `created_at` ascending; when candidates remain tied on `created_at` as well — analysts registered at the same clock reading share an identical value — the one registered earliest is chosen. When the eligible pool is empty — every topic-eligible analyst is conflicted — the request is refused with `ERR_BRIEFING_SEPARATION_FAILED` (HTTP 403) and no briefing row is created.

The slot is confirmed at creation when the requested window, expanded by a 15-minute buffer on both sides, does not overlap any other briefing of the assigned analyst that is `SCHEDULED` or `HELD`; when that buffer check fails the request is rejected with `ERR_BRIEFING_SLOT_CONFLICT` (HTTP 409). A confirmed briefing is created in `SCHEDULED` at version 1; the confirmation is part of the create, not a separate modification.

The assigned analyst records the outcome. The request is read as a decline exactly when it carries a `decline_reason` and no `held_at`, and as a held recording otherwise; a `held_at` value supplied by the client is ignored, and the clock reading is what gets stamped. Recording a held briefing is available while the briefing is `SCHEDULED`, requires that the clock has reached the briefing's `requested_start_utc` (a recording attempted before that instant is refused with `ERR_INVALID_STATE`, HTTP 409), requires the caller to be the assigned analyst unless it is a `ResearchDirector`, and moves the briefing to the terminal `HELD` state with `held_at` stamped with the clock reading and the `version` incremented; the linked vendor's `last_briefing_at` is stamped with the same instant and its `briefing_eligible` is recomputed. Recording a decline supplies a `decline_reason` and omits the held instant; it is available while the briefing is `SCREENED` or `SCHEDULED` (in practice always `SCHEDULED`, since a briefing is created already confirmed), may be recorded by any `Analyst` or `ResearchDirector` rather than only the assigned analyst, moves the briefing to the terminal `DECLINED` state, increments the `version`, and leaves the vendor's `last_briefing_at` unchanged. The terminal states `HELD`, `DECLINED` and `REVOKED_BY_SEPARATION` accept no further transitions.

Commercial ties are registered separately, by a `SalesRep` or `ComplianceOfficer`, as a `SalesRelationship` naming the `analyst_id`, the `vendor_id`, a `relationship_type` of `SPONSORSHIP`, `PAID_ADVISORY` or `SPEAKING_FEE`, an `annual_value_cents` of at least 0, and the `expected_analyst_version` the client last observed for the analyst. A registration built against a stale analyst version is rejected with `ERR_STALE_VERSION` (HTTP 412). The relationship is created in `ACTIVE` with `started_at` stamped, the analyst's `version` incremented, and a four-step cascade propagated immediately.

The cascade is the heart of the separation regime. First, the vendor is added to the analyst's `conflicted_vendor_ids`, and the analyst's `integrity_flag` becomes `CONFLICT_BLOCKED` once that list holds three or more entries, or `CONFLICT_REVIEW` otherwise. Second, every briefing for this analyst and vendor pair whose status is `REQUESTED`, `SCREENED` or `SCHEDULED` moves to `REVOKED_BY_SEPARATION` with `separation_check_result` `FAIL_SALES_RELATIONSHIP` and its `version` incremented. Third, every inclusion whose parent document's `lead_analyst_id` is this analyst, whose `vendor_id` is this vendor, and whose `inclusion_status` is `PROPOSED` or `UNDER_EVALUATION` is marked `lead_analyst_conflicted` true and reverted to `PROPOSED`. Fourth, the linked vendor's `active_sales_relationship_count` is incremented and its `briefing_eligible` recomputed.

A tie is ended by a `ComplianceOfficer` or `SalesRep` supplying an optional `termination_reason`. Termination requires the relationship to be `ACTIVE`; it moves the relationship to the terminal `TERMINATED` state, stamps `terminated_at` with the clock reading, and increments the `version`. The compensating side effects unwind the register but not history: the vendor is removed from `conflicted_vendor_ids`, the analyst's `integrity_flag` drops to `CONFLICT_REVIEW` while one or two ties remain and to `CLEAR` when none remain, the vendor's `active_sales_relationship_count` is decremented, and the vendor's `briefing_eligible` is recomputed. A briefing that was already revoked by separation is never restored.

### 3.9. Conference Programming and the Sponsorship Boundary

An `EventProgrammer` opens a `ConferenceEvent` with an `event_name`, a `venue_region` (one of `NA`, `EMEA`, `APAC`), and its `start_utc` and `end_utc` bounds. The event is created in `DRAFT` with an empty `sessions` list, `research_session_minutes`, `sponsor_session_minutes` and `sponsorship_revenue_cents` at 0, `sponsor_minute_share` at 0, and `agenda_locked_at` null.

The agenda is built by appending session rows, each carrying a `session_title`, a `session_kind` of `RESEARCH_SESSION` or `SPONSOR_KEYNOTE`, a `duration_minutes` that is an integer of at least 15, and, for a sponsored row, a `sponsor_vendor_id`. Appending the first row to a `DRAFT` event opens programming and moves it to `PROGRAMMING`. While the event is `DRAFT`, `PROGRAMMING` or `AGENDA_LOCKED` (for the reopening `RESEARCH_SESSION` row), a row is accepted only when the share recomputed on the post-append state stays at or below 0.4000 — a row that would push `sponsor_minute_share` above that ceiling is rejected with `ERR_SPONSOR_SHARE_EXCEEDED` (HTTP 409) — and a `SPONSOR_KEYNOTE` row naming a `sponsor_vendor_id` is refused with `ERR_SPONSOR_EXCLUSIVITY_OVERLAP` (HTTP 409) when that same vendor holds an `ACTIVE` `PLATINUM` sponsorship on this event whose exclusivity window overlaps the event window — the check reads only the row's own vendor, so a `PLATINUM` window held by a different vendor does not block the row, and the vendor's own sponsorship is not exempt; both windows are compared half-open. A row that names no `sponsor_vendor_id` skips the check and carries a null `sponsor_vendor_id`. Each accepted row is appended, `research_session_minutes`, `sponsor_session_minutes` and `sponsor_minute_share` are recomputed, and the event's `version` is incremented.

Locking the agenda is available to an `EventProgrammer` or `ResearchDirector` while the event is `PROGRAMMING` and the agenda contains at least one `RESEARCH_SESSION`. It moves the event to `AGENDA_LOCKED` and stamps `agenda_locked_at` with the clock reading. After a lock, the only way to add an agenda row is to reopen programming with a `RESEARCH_SESSION` row, which reverts the event to `PROGRAMMING`, appends the row and recomputes the share; a `SPONSOR_KEYNOTE` row appended to a locked agenda is refused with `ERR_AGENDA_LOCKED` (HTTP 409), because sponsor rows alone never reopen an agenda. An `AGENDA_LOCKED` event completes automatically once the logical clock is strictly after its `end_utc`; the next read moves it to the terminal `COMPLETED` state with its `version` incremented.

Sponsorship packages are sold against an event by a `SalesRep` or `EventProgrammer`. A `Sponsorship` names the `conference_event_id`, the `vendor_id`, a `tier` of `PLATINUM`, `GOLD` or `SILVER`, an `amount_cents` of at least 0, an `exclusivity_start_utc` and an `exclusivity_end_utc`, and the `expected_conference_event_version` the client last observed for the event. A sale built against a stale event version is rejected with `ERR_STALE_VERSION` (HTTP 412). The exclusivity window is half-open: its start instant is included and its end instant is excluded. `PLATINUM` windows are exclusive, and a new `PLATINUM` sponsorship whose window overlaps another `ACTIVE` `PLATINUM` window on the same event is rejected with `ERR_SPONSOR_EXCLUSIVITY_OVERLAP` (HTTP 409). A successful sale is created in `PENDING` with `sponsor_slot_counted` false, and the event's `version` is incremented.

Activation is available to an `EventProgrammer` or `SalesRep` while the sponsorship is `PENDING` and the linked event is still `DRAFT` or `PROGRAMMING`; once the agenda is locked the event can no longer accept an activation, and the attempt is rejected with `ERR_EVENT_AGENDA_LOCKED` (HTTP 409). Activation sets the sponsorship to `ACTIVE`, stamps `activated_at` with the clock reading, sets `sponsor_slot_counted` true, increments the sponsorship's `version`, and books the revenue: the event's `sponsorship_revenue_cents` is incremented by the sponsorship's `amount_cents` and the event's `version` is incremented. Cancellation is available to an `EventProgrammer` or `ComplianceOfficer` while the sponsorship is `ACTIVE` and the linked event is still `DRAFT` or `PROGRAMMING` — a locked agenda can no longer be un-sold, and the attempt is refused with `ERR_EVENT_AGENDA_LOCKED` (HTTP 409). Cancellation accepts an optional `cancel_reason`, moves the sponsorship to the terminal `CANCELLED` state, stamps `cancelled_at` with the clock reading, sets `sponsor_slot_counted` false, increments the sponsorship's `version`, and reverses the revenue by decrementing the event's `sponsorship_revenue_cents` by the sponsorship's `amount_cents` while incrementing the event's `version`.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource, or add a new distinct resource to a collection, return HTTP 201 Created. Operations that modify an existing resource, including those that add a row to a resource's internal collection, return HTTP 200 OK, and the modified or created resource is returned in the response envelope's `data` field. The logical-clock operation also returns HTTP 200. Every request carries the `X-User-ID` and `X-User-Role` headers described in §2.1 except the clock operation.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the logical clock to the supplied instant | PlatformAdmin |
| POST | `/research/clients` | Create a client account with its contract terms | PlatformAdmin |
| GET | `/research/clients/{id}` | Read an account with its utilization, ledger remainders and renewal posture | PlatformAdmin, ClientAdmin, ResearchDirector, ComplianceOfficer |
| POST | `/research/clients/{id}/renewal-decisions` | Record the renewal decision (RENEW or CHURN) | ResearchDirector, PlatformAdmin |
| POST | `/research/seats` | Provision a seat on an account | ClientAdmin, PlatformAdmin |
| GET | `/research/seats/{id}` | Read a seat with its derived entitlement document types | ClientAdmin, PlatformAdmin, SeatHolder, ResearchDirector, ComplianceOfficer |
| GET | `/research/seats` | List seats filtered by account, status or research role | ClientAdmin, PlatformAdmin, ResearchDirector, ComplianceOfficer |
| POST | `/research/seats/{id}/activate` | Activate a provisioned seat and derive its research entitlements | ClientAdmin, PlatformAdmin |
| POST | `/research/seats/{id}/revoke` | Revoke a seat and re-derive account utilization | ClientAdmin, PlatformAdmin |
| POST | `/research/analysts` | Register an analyst with topic routes | PlatformAdmin |
| GET | `/research/analysts/{id}` | Read an analyst with integrity flag and load counters | PlatformAdmin, ResearchDirector, ComplianceOfficer, Analyst, SeatHolder |
| GET | `/research/analysts` | List analysts filtered by practice area, topic route or status | PlatformAdmin, ResearchDirector, ComplianceOfficer, SeatHolder, Analyst |
| POST | `/research/inquiry-requests` | Submit an inquiry; topic routing assigns the analyst | SeatHolder |
| GET | `/research/inquiry-requests/{id}` | Read an inquiry | SeatHolder, Analyst, PlatformAdmin, ResearchDirector, ClientAdmin |
| GET | `/research/inquiry-requests` | List inquiries filtered by seat, analyst or status | SeatHolder, Analyst, PlatformAdmin, ResearchDirector, ClientAdmin |
| POST | `/research/inquiry-requests/{id}/schedule` | Confirm the slot and reserve one allowance unit | Analyst |
| POST | `/research/inquiry-requests/{id}/decline` | Decline the inquiry and re-route it | Analyst |
| POST | `/research/inquiry-requests/{id}/complete` | Close out a prepared inquiry as COMPLETED or NO_SHOW | Analyst |
| POST | `/research/inquiry-requests/{id}/cancel` | Cancel the inquiry; free before the 24-hour boundary, unit-consuming after | SeatHolder, ClientAdmin |
| POST | `/research/documents` | Open a research document in DRAFT | Analyst, ResearchDirector |
| GET | `/research/documents/{id}` | Read a document; vendor reads are refused while the embargo is active | Analyst, ResearchDirector, ClientAdmin, SeatHolder, VendorRep, ComplianceOfficer, PlatformAdmin |
| GET | `/research/documents` | List documents filtered by lead analyst, editorial status or type | Analyst, ResearchDirector, PlatformAdmin, ComplianceOfficer |
| POST | `/research/documents/{id}/submit-for-review` | Assign peer review; the reviewer must differ from the lead analyst | Analyst, ResearchDirector |
| POST | `/research/documents/{id}/peer-verdicts` | Return the reviewer verdict APPROVE or REVISE | Analyst |
| POST | `/research/documents/{id}/publish` | Publish a cleared document and freeze the placement snapshot | ResearchDirector |
| POST | `/research/documents/{id}/revise` | Reopen a published document and re-open its fact-check rounds | Analyst, ResearchDirector |
| POST | `/research/vendors` | Register a vendor in the research universe | PlatformAdmin, VendorRep |
| GET | `/research/vendors/{id}` | Read a vendor with its separation exposure and briefing eligibility | PlatformAdmin, ResearchDirector, ComplianceOfficer, VendorRep, Analyst |
| POST | `/research/documents/{id}/vendor-inclusions` | Propose a vendor for a comparative document with its dimension scores | Analyst, ResearchDirector |
| GET | `/research/vendor-inclusions/{id}` | Read an inclusion with its score, fact-check and licence state | Analyst, ResearchDirector, VendorRep, ComplianceOfficer, PlatformAdmin |
| GET | `/research/vendor-inclusions` | List inclusions filtered by document, vendor or placement status | Analyst, ResearchDirector, VendorRep, ComplianceOfficer, PlatformAdmin |
| POST | `/research/vendor-inclusions/{id}/finalize` | Set the placement to INCLUDE or EXCLUDE | ResearchDirector |
| POST | `/research/vendor-inclusions/{id}/appeals` | File an appeal against an exclusion | VendorRep |
| POST | `/research/vendor-inclusions/{id}/appeal-decisions` | Decide the appeal as UPHOLD or DENY | ResearchDirector |
| POST | `/research/vendor-inclusions/{id}/fact-check-responses` | Vendor answers a fact-check request | VendorRep |
| POST | `/research/vendor-inclusions/{id}/fact-check-decisions` | Accept or dispute the fact-check response | ResearchDirector |
| POST | `/research/vendor-inclusions/{id}/reprint-copy-adjustments` | Adjust licensed reprint copies and recompute the licence fee | VendorRep, PlatformAdmin |
| POST | `/research/vendor-briefings` | Request a briefing; separation screening runs at creation | VendorRep |
| GET | `/research/vendor-briefings/{id}` | Read a briefing | VendorRep, Analyst, ResearchDirector, ComplianceOfficer, PlatformAdmin |
| GET | `/research/vendor-briefings` | List briefings filtered by vendor, analyst or status | VendorRep, Analyst, ResearchDirector, ComplianceOfficer, PlatformAdmin |
| POST | `/research/vendor-briefings/{id}/record-briefing` | Record the briefing as held or declined | Analyst, ResearchDirector |
| POST | `/research/sales-relationships` | Register a commercial tie and trigger the separation cascade | SalesRep, ComplianceOfficer |
| GET | `/research/sales-relationships/{id}` | Read a commercial tie | ComplianceOfficer, ResearchDirector, PlatformAdmin, SalesRep |
| GET | `/research/sales-relationships` | List commercial ties filtered by analyst, vendor or status | ComplianceOfficer, ResearchDirector, PlatformAdmin, SalesRep |
| POST | `/research/sales-relationships/{id}/terminate` | Terminate a commercial tie and unwind the register | ComplianceOfficer, SalesRep |
| POST | `/research/conference-events` | Create a conference event in DRAFT | EventProgrammer, PlatformAdmin |
| GET | `/research/conference-events/{id}` | Read an event with its agenda mix and sponsorship revenue | EventProgrammer, PlatformAdmin, ResearchDirector, ComplianceOfficer |
| POST | `/research/conference-events/{id}/sessions` | Append an agenda session row | EventProgrammer |
| POST | `/research/conference-events/{id}/lock-agenda` | Lock the agenda for delivery | EventProgrammer, ResearchDirector |
| POST | `/research/sponsorships` | Sell a sponsorship package against an event | SalesRep, EventProgrammer |
| GET | `/research/sponsorships/{id}` | Read a sponsorship package | SalesRep, EventProgrammer, ComplianceOfficer, PlatformAdmin |
| GET | `/research/sponsorships` | List sponsorships filtered by event, vendor or status | SalesRep, EventProgrammer, ComplianceOfficer, PlatformAdmin |
| POST | `/research/sponsorships/{id}/activate` | Activate a pending package and book its revenue | EventProgrammer, SalesRep |
| POST | `/research/sponsorships/{id}/cancel` | Cancel an active package and reverse its revenue | EventProgrammer, ComplianceOfficer |

## 5. Error Code Catalogue

The table below lists every error identifier this API can return together with its HTTP status code. The conditions that trigger each error are stated in §2 and §3 next to the rule they guard.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_CLIENT_ACCOUNT_NOT_FOUND` | 404 Not Found |
| `ERR_SEAT_NOT_FOUND` | 404 Not Found |
| `ERR_ANALYST_NOT_FOUND` | 404 Not Found |
| `ERR_INQUIRY_NOT_FOUND` | 404 Not Found |
| `ERR_DOCUMENT_NOT_FOUND` | 404 Not Found |
| `ERR_VENDOR_NOT_FOUND` | 404 Not Found |
| `ERR_VENDOR_INCLUSION_NOT_FOUND` | 404 Not Found |
| `ERR_BRIEFING_NOT_FOUND` | 404 Not Found |
| `ERR_SALES_RELATIONSHIP_NOT_FOUND` | 404 Not Found |
| `ERR_CONFERENCE_EVENT_NOT_FOUND` | 404 Not Found |
| `ERR_SPONSORSHIP_NOT_FOUND` | 404 Not Found |
| `ERR_ANALYST_NOT_ELIGIBLE` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_SEPARATION_OF_DUTIES_VIOLATION` | 403 Forbidden |
| `ERR_INQUIRY_START_IN_PAST` | 400 Bad Request |
| `ERR_INQUIRY_ALLOWANCE_EXHAUSTED` | 409 Conflict |
| `ERR_INQUIRY_SLOT_OVERLAP` | 409 Conflict |
| `ERR_ANALYST_DAILY_INQUIRY_CAP` | 409 Conflict |
| `ERR_BRIEFING_SLOT_CONFLICT` | 409 Conflict |
| `ERR_BRIEFING_SEPARATION_FAILED` | 403 Forbidden |
| `ERR_DUPLICATE_SEAT_EMAIL` | 409 Conflict |
| `ERR_APPEAL_WINDOW_CLOSED` | 409 Conflict |
| `ERR_APPEAL_LIMIT_REACHED` | 409 Conflict |
| `ERR_EMBARGO_ACTIVE` | 403 Forbidden |
| `ERR_FACT_CHECK_RESPONSE_LATE` | 409 Conflict |
| `ERR_INCLUSION_CRITERIA_NOT_MET` | 409 Conflict |
| `ERR_SEAT_NOT_ACTIVE` | 409 Conflict |
| `ERR_SPONSOR_EXCLUSIVITY_OVERLAP` | 409 Conflict |
| `ERR_SPONSOR_SHARE_EXCEEDED` | 409 Conflict |
| `ERR_AGENDA_LOCKED` | 409 Conflict |
| `ERR_EVENT_AGENDA_LOCKED` | 409 Conflict |
| `ERR_REPRINT_COPIES_EXCEEDED` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_RENEWAL_UTILIZATION_TOO_LOW` | 409 Conflict |
| `ERR_PREPARATION_NOTES_REQUIRED` | 409 Conflict |

Requests that do not match a declared operation are answered outside this catalogue: an undeclared path returns `ERR_NOT_FOUND` (HTTP 404), an unsupported method on a declared path returns `ERR_METHOD_NOT_ALLOWED` (HTTP 405), and an unexpected server-side failure returns `ERR_INTERNAL` (HTTP 500).

